/*
 * background.js
 * =============
 * fox-webusb拡張機能のバックグラウンドページ(persistent: true — ネイティブ
 * メッセージングの接続とホットプラグイベントの配送を継続して行う必要が
 * あるため、非persistentなイベントページではなく持続的に常駐させている。
 * README「なぜManifest V2/persistent backgroundか」参照)。
 *
 * 責務:
 *   1. ネイティブメッセージングホスト(fox-webusbのPythonプロセス)との
 *      接続維持・チャンク分割されたレスポンスの再構成。
 *   2. content_script.js からの呼び出し(__foxWebusbCall)を受け取り、
 *      sender.url から検証済みのoriginを求めた上でホストへ転送する。
 *      ページ側JSは自分のoriginを一切自己申告しない/できない
 *      ——background.jsがsender.urlという、ブラウザ自身が埋めるフィールド
 *      からoriginを引く。これが移植元のFrameOriginTracker相当の役割を
 *      果たしている(仕組みは全く違うが、狙いは同じ: 「ページ自身の
     *      申告を信用しない」)。
 *   3. どのタブ/フレームが今どのoriginを表示しているかの登録簿を持ち、
 *      ホストから届いたconnect/disconnectイベントを該当オリジンの
 *      全フレームへ配送する。
 *   4. 拡張機能自身のページ(オプションページ)からの「信頼済み専用」
 *      呼び出しを区別する(isTrustedSender)。
 */

var NATIVE_HOST_NAME = 'org.fox_webusb.host';

var nativePort = null;
var nativeAvailable = false;
var lastNativeError = null;

// requestId(このスクリプトが発番する文字列) -> {resolve, reject}
var pendingRequests = new Map();
var nextRequestId = 1;

// "tabId:frameId" -> {origin, tabId, frameId}
var frameRegistry = new Map();

// ネイティブホストからのチャンク分割メッセージの再構成バッファ
var _chunkParts = [];
var _chunkExpectedTotal = null;

function connectNative() {
  try {
    nativePort = browser.runtime.connectNative(NATIVE_HOST_NAME);
  } catch (e) {
    nativeAvailable = false;
    lastNativeError = String(e && e.message ? e.message : e);
    return;
  }
  nativeAvailable = true;
  lastNativeError = null;
  nativePort.onMessage.addListener(onNativeChunk);
  nativePort.onDisconnect.addListener(function () {
    nativeAvailable = false;
    lastNativeError = (browser.runtime.lastError && browser.runtime.lastError.message) || 'disconnected';
    nativePort = null;
    pendingRequests.forEach(function (pending) {
      pending.reject(new Error('fox-webusb native host disconnected: ' + lastNativeError));
    });
    pendingRequests.clear();
  });
}
connectNative();

function onNativeChunk(chunk) {
  if (!chunk || typeof chunk.seq !== 'number') return;
  if (chunk.seq === 0) {
    _chunkParts = [];
    _chunkExpectedTotal = chunk.total;
  }
  _chunkParts.push(chunk.part);
  if (_chunkParts.length < (_chunkExpectedTotal || 1)) return;

  var b64 = _chunkParts.join('');
  _chunkParts = [];
  var msg;
  try {
    var binary = atob(b64);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    var jsonStr = new TextDecoder('utf-8').decode(bytes);
    msg = JSON.parse(jsonStr);
  } catch (e) {
    console.error('fox-webusb: failed to decode a message from the native host', e);
    return;
  }
  handleNativeMessage(msg);
}

function handleNativeMessage(msg) {
  if (msg.type === 'response' && msg.id != null) {
    var pending = pendingRequests.get(msg.id);
    if (pending) {
      pendingRequests.delete(msg.id);
      pending.resolve(msg);
    }
    return;
  }
  if (msg.type === 'event') {
    dispatchDeviceEvent(msg);
  }
}

function dispatchDeviceEvent(msg) {
  var origins = new Set(msg.origins || []);
  if (!origins.size) return;
  frameRegistry.forEach(function (info) {
    if (!origins.has(info.origin)) return;
    browser.tabs.sendMessage(info.tabId, { __foxWebusbPush: true, event: msg.event, device: msg.device }, { frameId: info.frameId })
      .catch(function () { /* フレームが既に無くなっている等。次の登録更新やtabs.onRemovedで自然に片付く */ });
  });
}

function callNative(method, origin, params, trusted) {
  return new Promise(function (resolve, reject) {
    if (!nativeAvailable) connectNative();
    if (!nativeAvailable) {
      reject(new Error(
        'fox-webusb native host is not reachable' + (lastNativeError ? ' (' + lastNativeError + ')' : '') +
        '. Is it installed? See the extension options page for setup instructions.',
      ));
      return;
    }
    var id = String(nextRequestId++);
    pendingRequests.set(id, { resolve: resolve, reject: reject });
    try {
      nativePort.postMessage({ id: id, method: method, origin: origin, trusted: !!trusted, params: params || {} });
    } catch (e) {
      pendingRequests.delete(id);
      reject(e);
    }
  });
}

function isTrustedSender(sender) {
  return !!(sender && sender.url && sender.url.indexOf(browser.runtime.getURL('/')) === 0);
}

function originFromSender(sender) {
  try { return new URL(sender.url).origin; } catch (e) { return null; }
}

var PAGE_METHODS = new Set([
  'isAvailable', 'listDevices', 'requestDeviceChooser', 'openDevice', 'closeDevice',
  'claimInterface', 'releaseInterface', 'selectConfiguration', 'selectAlternateInterface',
  'resetDevice', 'clearHalt', 'bulkTransferIn', 'bulkTransferOut', 'controlTransferIn',
  'controlTransferOut', 'isochronousTransferIn', 'isochronousTransferOut', 'forgetGrantedDevice',
]);
var TRUSTED_ONLY_METHODS = new Set([
  'listKnownDevices', 'forgetKnownDevice', 'forgetAllKnownDevices',
  'listGrantedOrigins', 'revokeOriginGrant', 'revokeAllForOrigin', 'diagnostics',
]);

browser.runtime.onMessage.addListener(function (message, sender) {
  if (!message) return;

  if (message.__foxWebusbRegister) {
    if (sender.tab) {
      var origin = originFromSender(sender);
      frameRegistry.set(sender.tab.id + ':' + sender.frameId, { origin: origin, tabId: sender.tab.id, frameId: sender.frameId });
    }
    return Promise.resolve({ ok: true });
  }

  if (message.__foxWebusbUnregister) {
    if (sender.tab) frameRegistry.delete(sender.tab.id + ':' + sender.frameId);
    return Promise.resolve({ ok: true });
  }

  if (message.__foxWebusbCall) {
    var method = message.method;
    var trusted = isTrustedSender(sender);

    if (method === 'getStatus') {
      return Promise.resolve({ nativeAvailable: nativeAvailable, lastNativeError: lastNativeError });
    }
    if (PAGE_METHODS.has(method)) {
      var callerOrigin = originFromSender(sender);
      if (!callerOrigin) return Promise.resolve({ success: false, error: 'SecurityError: could not determine the calling origin' });
      return callNative(method, callerOrigin, message.params, trusted).catch(function (e) {
        return { success: false, error: 'NetworkError: ' + (e && e.message ? e.message : String(e)) };
      });
    }
    if (TRUSTED_ONLY_METHODS.has(method)) {
      if (!trusted) return Promise.resolve({ success: false, error: "SecurityError: this method is only available to the extension's own pages" });
      return callNative(method, null, message.params, true).catch(function (e) {
        return { success: false, error: 'NetworkError: ' + (e && e.message ? e.message : String(e)) };
      });
    }
    return Promise.resolve({ success: false, error: 'NotFoundError: unknown method: ' + method });
  }
});

browser.tabs.onRemoved.addListener(function (tabId) {
  var removedOrigins = [];
  frameRegistry.forEach(function (info, key) {
    if (info.tabId === tabId) {
      removedOrigins.push(info.origin);
      frameRegistry.delete(key);
    }
  });
  reapClosedOrigins(removedOrigins);
});

function reapClosedOrigins(candidateOrigins) {
  // candidateOrigins のうち、他のどのタブ/フレームにももう表示されていない
  // ものだけをホストへ「originClosed」として通知する(README「originClosed」
  // ・bridge.pyのorigin_closed()参照——開きっぱなしのハンドルを解放する
  // ハウスキーピング。応答は特に待たない)。
  if (!candidateOrigins.length || !nativeAvailable) return;
  var stillOpen = new Set();
  frameRegistry.forEach(function (info) { stillOpen.add(info.origin); });
  var uniqueCandidates = new Set(candidateOrigins);
  uniqueCandidates.forEach(function (origin) {
    if (origin && !stillOpen.has(origin)) {
      callNative('originClosed', null, { origin: origin }, true).catch(function () {});
    }
  });
}
