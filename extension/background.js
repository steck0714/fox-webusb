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
  // 🛡️/🦊 v0.0.0a1: 拡張機能自身(Firefox-style surface、下記参照)が
  // このデバイスへの許可を持っている場合は、そちらのUSBインスタンスにも
  // 同じconnect/disconnectを配送する——ページ向け(frameRegistry)と拡張機能
  // 自身向け(extensionSurface)は別々のUSBインスタンスなので、片方に届いても
  // もう片方には自動的に届かない。
  if (origins.has(EXTENSION_ORIGIN) && extensionSurface) {
    extensionSurface.core.dispatchConnectionEvent(msg.event, msg.device);
  }
}

function callNative(method, origin, params, trusted, hasGesture, locale) {
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
      nativePort.postMessage({
        id: id, method: method, origin: origin, trusted: !!trusted, hasGesture: !!hasGesture,
        locale: locale || null, params: params || {},
      });
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
  'isAvailable', 'getAttestationPublicKey', 'signAttestationChallenge',
  'listDevices', 'requestDeviceChooser', 'openDevice', 'closeDevice',
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
      // 🛡️ v0.0.0a1: message.hasGesture は content_script.js が isolated world
      // 側で独立に計算したものであり(このスクリプト自身のドキュメントに
      // 張ったcapturing listenerが観測した、本物のevent.isTrusted===trueの
      // 操作のみに基づく)、message.params(ページが自由に詰め込める側)から
      // ではなくmessage自身のトップレベルフィールドから読む。ページ側JSが
      // 直接postMessageを偽造してcontent_script.jsをすり抜けようとしても、
      // ここで信用するのはcontent_script.js自身が計算した値だけになる。
      return callNative(method, callerOrigin, message.params, trusted, !!message.hasGesture, message.locale).catch(function (e) {
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

// ============================================================
// 🦊 Firefox-style surface (v0.0.0a1)
// ============================================================
// README「二重サーフェス」参照。content_script.js/postMessageの中継を一切
// 経由せず、この拡張機能自身の特権的なページ(background page自身、および
// getBackgroundPage()経由のpopup.js)がWebUSB機能を直接使うための窓口。
//
// 🛡️ ここを通る呼び出しにgesture_token的な検証を課していない理由:
// requestDeviceChooserのgesture検証(has_gesture、content_script.js参照)は
// 「content_script.jsが待ち受けるpostMessageの形さえ真似すれば、任意の
// Webページがpage_polyfill.jsのユーザー操作チェックを一度も通さずに
// ホストへ到達できてしまう」という、Webページという第三者由来の脅威を
// 防ぐためのものだった。この経路はそもそもWebコンテンツから到達不可能
// (呼び出せるのはこの拡張機能自身のJSだけ——別のJS実行コンテキストから
// 直接関数を呼ぶ手段はWebページには無い)なので、同じ脅威モデルが
// 適用されない。実際の「本物のクリックか」の検証は、popup.js側で
// requestDevice()を呼ぶ箇所自身が担う(実際のイベントハンドラの中で
// 呼ぶ、という通常のコーディング規約の話であり、悪意ある第三者からの
// 防御ではなく単なる誤用防止)。
var EXTENSION_ORIGIN = new URL(browser.runtime.getURL('/')).origin;

function _extensionSurfaceCallBridge(method, params) {
  // requestDeviceChooser向けのhasGesture=trueは上記のとおり、Webページ
  // からの偽造脅威が構造的に存在しないために付与している(常時true)。
  // 他のメソッドにとってこの引数は無視されるだけなので無害。
  return callNative(method, EXTENSION_ORIGIN, params, true, true).then(function (result) {
    return result;
  }, function (e) {
    return { success: false, error: 'NetworkError: ' + (e && e.message ? e.message : String(e)) };
  });
}

var extensionSurface = null;
try {
  if (typeof FoxWebusbCore !== 'undefined') {
    var extensionCore = FoxWebusbCore.create(_extensionSurfaceCallBridge, { requestDeviceNeedsGesture: false });
    extensionSurface = { core: extensionCore };
    // background page自身も(隠れているとはいえ)実際のHTML文書なので、
    // navigator が本物として存在する。ここへ取り付けておけば、
    // getBackgroundPage() 越しに popup.js からも
    // `bg.navigator.usb` としてそのまま参照できる。
    if (typeof navigator !== 'undefined') {
      try {
        Object.defineProperty(navigator, 'usb', {
          value: extensionCore.usb, writable: false, configurable: false, enumerable: true,
        });
      } catch (e) { /* 既に何か定義済みなら諦める(background page内で他に定義する理由は通常無いはずだが念のため) */ }
    }
  }
} catch (e) {
  console.error('[fox-webusb] Firefox-style surfaceの初期化に失敗しました:', e);
}

// ============================================================
// 🦊 独自コマンド拡張: window.__foxWebUsbManagement (v0.0.0a1)
// ============================================================
// WebUSB仕様には存在しない、この実装固有の管理系操作
// (listKnownDevices等、TRUSTED_ONLY_METHODS参照)を、拡張機能自身の
// 特権的なページ(options.js/popup.js)から人間工学的に呼べるようにする。
// 🛡️ 互換性について: navigator.usb自体の形状・挙動には一切手を加えない
// ——これはnavigator.usbとは別の、background page自身のグローバルスコープに
// 生える、完全に独立した名前空間である。既存のoptions.js/popup.jsが
// browser.runtime.sendMessage()を手組みする代わりに
// `browser.runtime.getBackgroundPage().then(bg => bg.__foxWebUsbManagement.X())`
// と書けるようにするための、単なる薄い糖衣構文。実際の認可判定
// (trusted=trueの検証)は従来どおりネイティブホスト側のdispatch()が行う
// ——ここはあくまで「呼び方」を整理するだけで、新しい権限を何も追加しない。
window.__foxWebUsbManagement = {
  listKnownDevices: function () { return callNative('listKnownDevices', null, {}, true); },
  forgetKnownDevice: function (vendorId, productId) {
    return callNative('forgetKnownDevice', null, { vendorId: vendorId, productId: productId }, true);
  },
  forgetAllKnownDevices: function () { return callNative('forgetAllKnownDevices', null, {}, true); },
  listGrantedOrigins: function () { return callNative('listGrantedOrigins', null, {}, true); },
  revokeOriginGrant: function (origin, vendorId, productId) {
    return callNative('revokeOriginGrant', null, { origin: origin, vendorId: vendorId, productId: productId }, true);
  },
  revokeAllForOrigin: function (origin) { return callNative('revokeAllForOrigin', null, { origin: origin }, true); },
  diagnostics: function () { return callNative('diagnostics', null, {}, true); },
};
