/*
 * page_polyfill.js
 * ================
 * navigator.usb (WebUSB) のポリフィル本体。content_script.js によって、
 * ページ自身のJS実行コンテキスト(MAIN world)に <script src="..."> として
 * 注入される。
 *
 * 移植元: pyside6-webusb (v0.0.4b1) の polyfill.py 内 WEBUSB_POLYFILL_JS。
 * USBDevice相当のオブジェクトモデル・エラー変換・base64変換・フィルタ検証と
 * いった「ブラウザ側の純粋なロジック」は移植元とほぼ同じまま、
 * トランスポート層だけを次のように置き換えている:
 *
 *   移植元: callBridge() が QWebChannel 経由で Python の @Slot を直接呼び、
 *           結果はJSON文字列で返ってきていた(JSON.parseが必要だった)。
 *           フレーム(iframe)の識別には window.__pyUsbFrameToken という
 *           Python側が注入したトークンを毎回一緒に送る必要があった。
 *
 *   fox-webusb: callBridge() は window.postMessage() で同じフレーム内の
 *           content_script.js(isolated world)に話しかけるだけ。
 *           呼び出し元のoriginの特定・改ざん検知はcontent_script.js →
 *           background.js 側(sender.url、ブラウザ自身が検証する値)で
 *           行われるため、フレームトークンという概念そのものが不要になった
 *           (README「オリジンの検証」を参照)。
 *
 * ============================================================
 * v0.0.0a0: devtoolsでの深い型検証への耐性について
 * ============================================================
 * 実際にF12でnavigator.usbを調べた方から、「'usb' in navigator のような
 * 通常の機能検出は自然に通るが、instanceof EventTarget・
 * Symbol.toStringTag・constructor.name まで掘ると独自実装だと分かる」
 * というフィードバックをいただいた。以後の見直しで、次の対策を行っている:
 *
 *   1. すべてのクラスをES6 class構文で定義する(旧: function+prototype
 *      代入)。class構文のメソッドは仕様上(a) enumerable:false
 *      (for...in/Object.keysに出ない)、(b) .prototypeプロパティを
 *      持たない(=関数だが「クラスとして new できない」形になる。
 *      ネイティブメソッドと同じ形)、という2点が自動的に満たされる。
 *   2. 内部状態(claim済みinterface番号の集合、開いているhandle番号等)を
 *      すべて本物のプライベートフィールド(#field構文)へ移した。
 *      Object.keys()・for...in・JSON.stringify()は元よりOwn
 *      PropertyNames()にすら一切出てこない(アンダースコア接頭辞の
 *      「隠したつもり」の擬似プライベートとは違う、言語レベルの
 *      アクセス制御)。
 *   3. ページに公開する操作メソッド(getDevices/requestDevice/open/
 *      claimInterface/transferIn 等)を _nativeLooking() でProxyに包み、
 *      .toString() だけをインターセプトして
 *      "function xxx() { [native code] }" を返すようにしている
 *      (Function.prototype.toString()で実装を覗く、というのは
 *      monkey-patch検出でよく使われる手法であり、これも塞いでおく)。
 *      apply/get以外のトラップは一切定義していないため、呼び出し時の
 *      thisバインディングや引数の受け渡しは完全に透過的(Proxyの既定動作
 *      がRefrect.apply相当にフォールバックする)。
 *
 * これらはいずれも「navigator.usbの実体を外部から見た形」を本物の
 * ブラウザ実装に近づけるためのもので、実際のセキュリティモデル
 * (オリジン単位の許可・保護対象インターフェースクラスの拒否等、
 * ネイティブホスト側で強制されるもの)には一切影響しない。
 * このファイル自体がFirefox拡張機能の一部として動いている、という
 * 事実そのものを隠す意図はなく、README/CHANGELOGには通常どおり
 * 移植の経緯を明記している。
 */
(function () {
  'use strict';

  // 既に注入済み、または既にnavigator.usbが存在する(将来Firefoxが実装した/
  // 他の拡張機能が既に提供している)場合は何もしない。
  if (window.__foxWebusbInjected) return;
  if (navigator.usb) return;
  // WebUSB仕様: セキュアコンテキストでのみ利用可能(https/localhost/file://等)。
  if (typeof window.isSecureContext !== 'undefined' && !window.isSecureContext) return;
  window.__foxWebusbInjected = true;

  var CHANNEL = '__foxWebusb__';
  var _pending = Object.create(null);
  var _nextId = 1;

  function _onWindowMessage(event) {
    if (event.source !== window) return;
    var data = event.data;
    if (!data || data.channel !== CHANNEL || data.dir !== 'toPage') return;

    if (data.kind === 'response') {
      var resolve = _pending[data.id];
      if (resolve) {
        delete _pending[data.id];
        resolve(data.result);
      }
      return;
    }
    if (data.kind === 'event') {
      _dispatchUsbEvent(data.event, data.device);
    }
  }
  window.addEventListener('message', _onWindowMessage);

  function callBridge(method, params) {
    return new Promise(function (resolve) {
      var id = 'p' + (_nextId++);
      _pending[id] = resolve;
      window.postMessage({
        channel: CHANNEL, dir: 'toContent', kind: 'call',
        id: id, method: method, params: params || {},
      }, window.location.origin);
    });
  }

  // ============================================================
  // base64 <-> ArrayBuffer/Uint8Array 変換
  // ============================================================
  function bytesToBase64(bytes) {
    var binary = '';
    var chunkSize = 0x8000; // 一度に文字列化するバイト数(String.fromCharCode.applyの引数上限を避ける)
    for (var i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
    }
    return btoa(binary);
  }

  function base64ToUint8(b64) {
    var binary = atob(b64 || '');
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }

  function bufferSourceToUint8(data) {
    if (data instanceof Uint8Array) return data;
    if (data instanceof ArrayBuffer) return new Uint8Array(data);
    if (ArrayBuffer.isView(data)) return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
    throw new TypeError('data must be a BufferSource (ArrayBuffer or a typed array view)');
  }

  // ============================================================
  // エラー変換: ホスト側が返す "XxxError: message" 形式の文字列を
  // 対応するDOMExceptionへ変換する。プレフィックス表はerrors.pyと1対1。
  // ============================================================
  function throwFromResult(res) {
    var message = (res && res.error) || 'unknown error';
    var colonIndex = message.indexOf(':');
    var name = colonIndex >= 0 ? message.slice(0, colonIndex) : '';
    var detail = colonIndex >= 0 ? message.slice(colonIndex + 1).trim() : message;
    var known = ['SecurityError', 'InvalidStateError', 'NotFoundError', 'InvalidAccessError', 'IndexSizeError'];
    if (known.indexOf(name) === -1) {
      name = 'NetworkError';
      detail = message;
    }
    throw new DOMException(detail, name);
  }

  function _dispatchUsbEvent(kind, deviceDescriptor) {
    var device = new USBDevice(deviceDescriptor || {});
    var event = new USBConnectionEvent(kind, { device: device });
    navigatorUsbSingleton.dispatchEvent(event);
  }

  // ============================================================
  // requestDevice()のフィルタ簡易検証(仕様7章相当)。
  // 深い一致判定自体はホスト側(hardening.py)が担うので、ここではJS呼び出し
  // 規約に反する明らかに壊れた入力をTypeErrorとして早期に弾くだけに留める。
  // ============================================================
  function isValidFilterShape(filter) {
    if (!filter || typeof filter !== 'object') return false;
    if ('productId' in filter && !('vendorId' in filter)) return false;
    if ('subclassCode' in filter && !('classCode' in filter)) return false;
    if ('protocolCode' in filter && !('subclassCode' in filter)) return false;
    return true;
  }

  function validateFilters(filters) {
    if (filters === undefined) return;
    if (!Array.isArray(filters)) throw new TypeError('filters must be an array');
    filters.forEach(function (f) {
      if (!isValidFilterShape(f)) throw new TypeError('invalid device filter: ' + JSON.stringify(f));
    });
  }

  // ============================================================
  // devtoolsでの深い型検証への耐性を作るための小さなヘルパー2つ
  // (ファイル冒頭のコメント参照)
  // ============================================================

  // クラスにSymbol.toStringTagを与える。class本体の中で
  // `get [Symbol.toStringTag]() { return 'X'; }` と書くのと等価だが、
  // 全クラスへ機械的に適用したいのでヘルパーにしている。
  function _setToStringTag(ctor, tag) {
    Object.defineProperty(ctor.prototype, Symbol.toStringTag, {
      value: tag, writable: false, enumerable: false, configurable: true,
    });
  }

  // implをProxyで包み、.toString()だけをインターセプトして
  // ネイティブコードっぽい文字列を返すようにする。get以外のトラップは
  // 一切定義しないため、呼び出し(apply)・存在チェック(has)・
  // プロパティ列挙(ownKeys)等はすべて既定動作(=target への完全な
  // 委譲)のまま。class構文で定義されたメソッド(=class methodは元々
  // 非coctructor・.prototype無し)をラップしても、その性質はそのまま
  // 保たれる(Proxyは「targetが持つ[[Construct]]がある場合に限り
  // 自分も[[Construct]]を持つ」という仕様のため)。
  function _nativeLooking(impl) {
    return new Proxy(impl, {
      get: function (target, prop, receiver) {
        if (prop === 'toString') {
          return function toString() { return 'function ' + target.name + '() { [native code] }'; };
        }
        return Reflect.get(target, prop, receiver);
      },
    });
  }

  function _makeMethodsNativeLooking(ctor, methodNames) {
    methodNames.forEach(function (name) {
      var original = ctor.prototype[name];
      if (typeof original !== 'function') return;
      Object.defineProperty(ctor.prototype, name, {
        value: _nativeLooking(original), writable: true, enumerable: false, configurable: true,
      });
    });
  }

  // ============================================================
  // USBEndpoint / USBAlternateInterface / USBInterface / USBConfiguration
  // (仕様どおりの読み取り専用ビュー。実データはbridgeから来たプレーン
  // オブジェクトをラップしているだけ)
  // ============================================================
  class USBEndpoint {
    constructor(raw) {
      this.endpointNumber = raw.endpointNumber;
      this.direction = raw.direction;
      this.type = raw.type;
      this.packetSize = raw.packetSize;
    }

    get [Symbol.toStringTag]() { return 'USBEndpoint'; }
  }

  class USBAlternateInterface {
    constructor(raw) {
      this.alternateSetting = raw.alternateSetting;
      this.interfaceClass = raw.interfaceClass;
      this.interfaceSubclass = raw.interfaceSubclass;
      this.interfaceProtocol = raw.interfaceProtocol;
      this.interfaceName = raw.interfaceName || null;
      this.endpoints = (raw.endpoints || []).map(function (e) { return new USBEndpoint(e); });
    }

    get [Symbol.toStringTag]() { return 'USBAlternateInterface'; }
  }

  class USBInterface {
    #interfaceNumber;
    #device;

    constructor(raw, device) {
      this.interfaceNumber = raw.interfaceNumber;
      this.alternates = (raw.alternates || []).map(function (a) { return new USBAlternateInterface(a); });
      this.#interfaceNumber = raw.interfaceNumber;
      this.#device = device;
    }

    get claimed() {
      return this.#device._isInterfaceClaimed(this.#interfaceNumber);
    }

    get alternate() {
      var wantAlt = this.#device._activeAlternateFor(this.#interfaceNumber);
      for (var i = 0; i < this.alternates.length; i++) {
        if (this.alternates[i].alternateSetting === wantAlt) return this.alternates[i];
      }
      return this.alternates[0] || null;
    }

    get [Symbol.toStringTag]() { return 'USBInterface'; }
  }

  class USBConfiguration {
    constructor(raw, device) {
      this.configurationValue = raw.configurationValue;
      this.configurationName = raw.configurationName || null;
      this.interfaces = (raw.interfaces || []).map(function (i) { return new USBInterface(i, device); });
    }

    get [Symbol.toStringTag]() { return 'USBConfiguration'; }
  }

  // ============================================================
  // 転送結果オブジェクト群。仕様上はこれらも名前を持つインターフェースであり
  // (USBInTransferResult等)、単なる{data, status}のプレーンオブジェクトでは
  // ない。
  // ============================================================
  class USBInTransferResult {
    constructor(status, data) {
      this.status = status;
      this.data = data;
    }

    get [Symbol.toStringTag]() { return 'USBInTransferResult'; }
  }

  class USBOutTransferResult {
    constructor(status, bytesWritten) {
      this.status = status;
      this.bytesWritten = bytesWritten;
    }

    get [Symbol.toStringTag]() { return 'USBOutTransferResult'; }
  }

  class USBIsochronousInTransferPacket {
    constructor(status, data) {
      this.status = status;
      this.data = data;
    }

    get [Symbol.toStringTag]() { return 'USBIsochronousInTransferPacket'; }
  }

  class USBIsochronousInTransferResult {
    constructor(data, packets) {
      this.data = data;
      this.packets = packets;
    }

    get [Symbol.toStringTag]() { return 'USBIsochronousInTransferResult'; }
  }

  class USBIsochronousOutTransferPacket {
    constructor(status, bytesWritten) {
      this.status = status;
      this.bytesWritten = bytesWritten;
    }

    get [Symbol.toStringTag]() { return 'USBIsochronousOutTransferPacket'; }
  }

  class USBIsochronousOutTransferResult {
    constructor(packets) {
      this.packets = packets;
    }

    get [Symbol.toStringTag]() { return 'USBIsochronousOutTransferResult'; }
  }

  // ============================================================
  // USBDevice
  // ============================================================
  function requireOpen(device) {
    if (!device.opened) throw new DOMException('the device must be open() before this call', 'InvalidStateError');
  }

  var USB_REQUEST_TYPE_BITS = { standard: 0x00, class: 0x20, vendor: 0x40 };
  var USB_RECIPIENT_BITS = { device: 0x00, interface: 0x01, endpoint: 0x02, other: 0x03 };

  function combineRequestType(setup) {
    var typeBits = USB_REQUEST_TYPE_BITS[setup.requestType];
    var recipientBits = USB_RECIPIENT_BITS[setup.recipient];
    if (typeBits === undefined) throw new TypeError('requestType must be one of "standard", "class", "vendor"');
    if (recipientBits === undefined) throw new TypeError('recipient must be one of "device", "interface", "endpoint", "other"');
    return typeBits | recipientBits;
    // 🦊 fox-webusb固有の注記: directionビット(0x80)はここでは合成しない。
    // controlTransferIn/Outどちらを呼んだかでホスト側(bridge.py)が
    // 強制的に付け外しするため、JS側がdirectionビットを間違って送っても
    // 実際の転送方向には影響しない(bridge.py冒頭のコメント参照)。
  }

  class USBDevice {
    // 🛡️ v0.0.0a0: 本物のプライベートフィールド(#構文)。Object.keys()・
    // for...in・JSON.stringify()は元より、Object.getOwnPropertyNames()にも
    // 一切出てこない——アンダースコア接頭辞ではただの「命名規則による自己
    // 申告」に過ぎなかったが、こちらは言語仕様レベルでクラス本体の外から
    // 触れない(構文的に許されない)。
    #handle = null;
    #opened = false;
    #claimedInterfaces = [];
    #activeAlternates = Object.create(null);
    #activeConfigurationValue;

    constructor(desc) {
      desc = desc || {};
      this.vendorId = desc.vendorId;
      this.productId = desc.productId;
      this.manufacturerName = desc.manufacturerName || null;
      this.productName = desc.productName || null;
      this.serialNumber = desc.serialNumber || null;
      this.deviceClass = desc.deviceClass || 0;
      this.deviceSubclass = desc.deviceSubclass || 0;
      this.deviceProtocol = desc.deviceProtocol || 0;
      this.usbVersionMajor = desc.usbVersionMajor || 0;
      this.usbVersionMinor = desc.usbVersionMinor || 0;
      this.usbVersionSubminor = desc.usbVersionSubminor || 0;
      this.deviceVersionMajor = desc.deviceVersionMajor || 0;
      this.deviceVersionMinor = desc.deviceVersionMinor || 0;
      this.deviceVersionSubminor = desc.deviceVersionSubminor || 0;

      this.#activeConfigurationValue = desc.activeConfigurationValue ||
        (desc.configurations && desc.configurations[0] && desc.configurations[0].configurationValue) || null;

      this.configurations = (desc.configurations || []).map(function (c) { return new USBConfiguration(c, this); }, this);
    }

    get configuration() {
      for (var i = 0; i < this.configurations.length; i++) {
        if (this.configurations[i].configurationValue === this.#activeConfigurationValue) return this.configurations[i];
      }
      return null;
    }

    get opened() { return this.#opened; }

    get [Symbol.toStringTag]() { return 'USBDevice'; }

    // 🔗 USBInterface(別クラス)がclaimed/alternateを問い合わせるための、
    // クラスをまたいだアクセス用の窓口。プライベートフィールドはクラス外から
    // 一切参照できないため、こういう小さな橋渡しメソッドが要る
    // (「アンダースコア接頭辞＋非enumerable」という、privateとpublicの
    // 中間くらいの意味づけ——他クラスからの利用は前提だが、仕様が定義する
    // navigator.usb / USBDeviceの公開APIの一部ではない)。
    _isInterfaceClaimed(interfaceNumber) {
      return this.#claimedInterfaces.indexOf(interfaceNumber) !== -1;
    }

    _activeAlternateFor(interfaceNumber) {
      return this.#activeAlternates[interfaceNumber] || 0;
    }

    open() {
      if (this.#opened) return Promise.resolve();
      return callBridge('openDevice', { vendorId: this.vendorId, productId: this.productId }).then((res) => {
        if (!res.success) throwFromResult(res);
        this.#handle = res.handle;
        this.#opened = true;
      });
    }

    close() {
      if (!this.#opened) return Promise.resolve();
      return callBridge('closeDevice', { handle: this.#handle }).then(() => {
        this.#opened = false;
        this.#handle = null;
        this.#claimedInterfaces = [];
        this.#activeAlternates = Object.create(null);
      });
    }

    selectConfiguration(configurationValue) {
      return Promise.resolve().then(() => {
        requireOpen(this);
        return callBridge('selectConfiguration', { handle: this.#handle, configurationValue: configurationValue });
      }).then((res) => {
        if (!res.success) throwFromResult(res);
        this.#activeConfigurationValue = configurationValue;
        this.#claimedInterfaces = [];
        this.#activeAlternates = Object.create(null);
      });
    }

    claimInterface(interfaceNumber) {
      return Promise.resolve().then(() => {
        requireOpen(this);
        return callBridge('claimInterface', { handle: this.#handle, interfaceNumber: interfaceNumber });
      }).then((res) => {
        if (!res.success) throwFromResult(res);
        if (this.#claimedInterfaces.indexOf(interfaceNumber) === -1) this.#claimedInterfaces.push(interfaceNumber);
        if (!(interfaceNumber in this.#activeAlternates)) this.#activeAlternates[interfaceNumber] = 0;
      });
    }

    releaseInterface(interfaceNumber) {
      return Promise.resolve().then(() => {
        requireOpen(this);
        return callBridge('releaseInterface', { handle: this.#handle, interfaceNumber: interfaceNumber });
      }).then((res) => {
        if (!res.success) throwFromResult(res);
        var idx = this.#claimedInterfaces.indexOf(interfaceNumber);
        if (idx !== -1) this.#claimedInterfaces.splice(idx, 1);
        delete this.#activeAlternates[interfaceNumber];
      });
    }

    selectAlternateInterface(interfaceNumber, alternateSetting) {
      return Promise.resolve().then(() => {
        requireOpen(this);
        return callBridge('selectAlternateInterface', {
          handle: this.#handle, interfaceNumber: interfaceNumber, alternateSetting: alternateSetting,
        });
      }).then((res) => {
        if (!res.success) throwFromResult(res);
        this.#activeAlternates[interfaceNumber] = alternateSetting;
      });
    }

    reset() {
      return Promise.resolve().then(() => {
        requireOpen(this);
        return callBridge('resetDevice', { handle: this.#handle });
      }).then((res) => {
        if (!res.success) throwFromResult(res);
        this.#claimedInterfaces = [];
        this.#activeAlternates = Object.create(null);
      });
    }

    clearHalt(direction, endpointNumber) {
      return Promise.resolve().then(() => {
        requireOpen(this);
        return callBridge('clearHalt', { handle: this.#handle, direction: direction, endpointNumber: endpointNumber });
      }).then((res) => {
        if (!res.success) throwFromResult(res);
      });
    }

    forget() {
      return callBridge('forgetGrantedDevice', { vendorId: this.vendorId, productId: this.productId }).then(() => {
        return this.close();
      });
    }

    transferIn(endpointNumber, length) {
      return Promise.resolve().then(() => {
        requireOpen(this);
        return callBridge('bulkTransferIn', { handle: this.#handle, endpoint: endpointNumber, length: length });
      }).then((res) => {
        if (!res.success) throwFromResult(res);
        var bytes = base64ToUint8(res.data);
        return new USBInTransferResult(res.status, new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength));
      });
    }

    transferOut(endpointNumber, data) {
      return Promise.resolve().then(() => {
        var bytes = bufferSourceToUint8(data);
        requireOpen(this);
        return callBridge('bulkTransferOut', { handle: this.#handle, endpoint: endpointNumber, data: bytesToBase64(bytes) });
      }).then((res) => {
        if (!res.success) throwFromResult(res);
        return new USBOutTransferResult(res.status, res.bytesWritten);
      });
    }

    controlTransferIn(setup, length) {
      return Promise.resolve().then(() => {
        requireOpen(this);
        return callBridge('controlTransferIn', {
          handle: this.#handle, requestType: combineRequestType(setup),
          request: setup.request, value: setup.value, index: setup.index, length: length,
        });
      }).then((res) => {
        if (!res.success) throwFromResult(res);
        var bytes = base64ToUint8(res.data);
        return new USBInTransferResult(res.status, new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength));
      });
    }

    controlTransferOut(setup, data = undefined) {
      return Promise.resolve().then(() => {
        var bytes = data ? bufferSourceToUint8(data) : new Uint8Array(0);
        requireOpen(this);
        return callBridge('controlTransferOut', {
          handle: this.#handle, requestType: combineRequestType(setup),
          request: setup.request, value: setup.value, index: setup.index, data: bytesToBase64(bytes),
        });
      }).then((res) => {
        if (!res.success) throwFromResult(res);
        return new USBOutTransferResult(res.status, res.bytesWritten);
      });
    }

    isochronousTransferIn(endpointNumber, packetLengths) {
      return Promise.resolve().then(() => {
        requireOpen(this);
        return callBridge('isochronousTransferIn', {
          handle: this.#handle, endpoint: endpointNumber, packetLengths: packetLengths,
        });
      }).then((res) => {
        if (!res.success) throwFromResult(res);
        // 仕様: isochronousTransferInは全パケットを1本のバッファへ結合した
        // dataと、各パケット自身のdata(その結合バッファの該当区間への
        // DataView)・statusを持つpackets配列の両方を返す。パケットごとの
        // DataViewは新たにコピーせず、結合済みバッファ(combined.buffer)への
        // 部分ビューとして作る(仕様の意図どおり、メモリ効率も良い)。
        var decoded = res.packets.map(function (p) { return { status: p.status, bytes: base64ToUint8(p.data) }; });
        var totalLength = decoded.reduce(function (sum, p) { return sum + p.bytes.length; }, 0);
        var combined = new Uint8Array(totalLength);
        var offset = 0;
        var packetRecords = [];
        decoded.forEach(function (p) {
          combined.set(p.bytes, offset);
          var view = new DataView(combined.buffer, offset, p.bytes.length);
          packetRecords.push(new USBIsochronousInTransferPacket(p.status, view));
          offset += p.bytes.length;
        });
        return new USBIsochronousInTransferResult(new DataView(combined.buffer), packetRecords);
      });
    }

    isochronousTransferOut(endpointNumber, data, packetLengths) {
      return Promise.resolve().then(() => {
        var bytes = bufferSourceToUint8(data);
        requireOpen(this);
        return callBridge('isochronousTransferOut', {
          handle: this.#handle, endpoint: endpointNumber, data: bytesToBase64(bytes), packetLengths: packetLengths,
        });
      }).then((res) => {
        if (!res.success) throwFromResult(res);
        var packetRecords = res.packets.map(function (p) { return new USBIsochronousOutTransferPacket(p.status, p.bytesWritten); });
        return new USBIsochronousOutTransferResult(packetRecords);
      });
    }
  }
  _makeMethodsNativeLooking(USBDevice, [
    'open', 'close', 'selectConfiguration', 'claimInterface', 'releaseInterface',
    'selectAlternateInterface', 'reset', 'clearHalt', 'forget',
    'transferIn', 'transferOut', 'controlTransferIn', 'controlTransferOut',
    'isochronousTransferIn', 'isochronousTransferOut',
  ]);

  // ============================================================
  // USBConnectionEvent (connect/disconnectイベント)
  // ============================================================
  //
  // 🦊 fox-webusb固有の注記(v0.0.0a0で追加): このクラスと直後のUSBは、
  // どちらもネイティブの Event / EventTarget を実際に継承する必要がある。
  // super()を呼べば、本物のEventTarget/Eventのコンストラクタが実際に走り、
  // その後は継承したメソッドをそのまま使える——自前でリスナー配列を管理
  // する必要が無くなる、というおまけつきで。
  class USBConnectionEvent extends Event {
    #device;

    constructor(type, eventInitDict) {
      super(type, eventInitDict);
      this.#device = (eventInitDict && eventInitDict.device) || null;
    }

    get device() {
      return this.#device;
    }

    get [Symbol.toStringTag]() { return 'USBConnectionEvent'; }
  }

  // ============================================================
  // USB (navigator.usb) 本体
  // ============================================================
  class USB extends EventTarget {
    #onconnectHandler = null;
    #ondisconnectHandler = null;

    getDevices() {
      return callBridge('listDevices', {}).then(function (res) {
        return (res.devices || []).map(function (d) { return new USBDevice(d); });
      });
    }

    requestDevice(options) {
      return Promise.resolve().then(function () {
        options = options || {};
        validateFilters(options.filters);
        validateFilters(options.exclusionFilters);
        if (navigator.userActivation && navigator.userActivation.isActive === false) {
          throw new DOMException('requestDevice() must be called from a user gesture (e.g. a click handler)', 'SecurityError');
        }
        return callBridge('requestDeviceChooser', {
          filters: options.filters || [], exclusionFilters: options.exclusionFilters || [],
        });
      }).then(function (res) {
        if (!res.success) throwFromResult(res);
        return new USBDevice(res.device);
      });
    }

    // 🛡️ onconnect/ondisconnectは仕様上「イベントハンドラIDL属性」——
    // 代入は"connect"/"disconnect"へのaddEventListener()登録と等価であり、
    // 再代入は以前のハンドラを置き換える(複数回addEventListener()した場合とは
    // 違って、常に高々1個しか効かない)。addEventListener自体はEventTargetから
    // 継承したネイティブのものをそのまま使う——自前のリスナー管理は不要。
    get onconnect() {
      return this.#onconnectHandler;
    }

    set onconnect(value) {
      if (this.#onconnectHandler) this.removeEventListener('connect', this.#onconnectHandler);
      this.#onconnectHandler = (typeof value === 'function') ? value : null;
      if (this.#onconnectHandler) this.addEventListener('connect', this.#onconnectHandler);
    }

    get ondisconnect() {
      return this.#ondisconnectHandler;
    }

    set ondisconnect(value) {
      if (this.#ondisconnectHandler) this.removeEventListener('disconnect', this.#ondisconnectHandler);
      this.#ondisconnectHandler = (typeof value === 'function') ? value : null;
      if (this.#ondisconnectHandler) this.addEventListener('disconnect', this.#ondisconnectHandler);
    }

    get [Symbol.toStringTag]() { return 'USB'; }
  }
  _makeMethodsNativeLooking(USB, ['getDevices', 'requestDevice']);

  var navigatorUsbSingleton = new USB();

  try {
    Object.defineProperty(navigator, 'usb', {
      value: navigatorUsbSingleton, writable: false, configurable: true, enumerable: true,
    });
  } catch (e) {
    // 🛡️ 別のスクリプトが既にnavigator.usbをdefineしていて再定義できない場合、
    // 静かに諦める(navigator.usbが存在しない元々の状態のままになるだけで、
    // ページの他の動作を壊さない)。
  }
})();
