/*
 * webusb_core.js
 * ==============
 * navigator.usb(WebUSB)のオブジェクトモデル・エラー変換・base64変換・
 * フィルタ検証といった「トランスポートに依存しないロジック」を、
 * どこから使われるかから切り離して一箇所にまとめたもの。
 *
 * ============================================================
 * v0.0.0a1: 「二重サーフェス」アーキテクチャ
 * ============================================================
 *
 *   USB backend (pyusb/libusb, ネイティブホストプロセス)
 *        │
 *        ▼
 *   USB compatibility core (bridge.py / hardening.py — 保護対象クラス・
 *        ブロックリスト・オリジン単位の許可・フィルタ照合等、実際の
 *        WebUSBセキュリティモデルそのもの。唯一の実装がここにしかない)
 *        │
 *        ├─────────────────────┬─────────────────────────┐
 *        ▼                     ▼
 *   Chromium surface       Firefox-style surface
 *   (page_polyfill.js)     (background.js / popup.js)
 *
 * 「Chromium surface」は、content_script.jsが任意のWebページのMAIN world
 * へ注入する page_polyfill.js が実装する、window.postMessage()越しの
 * navigator.usb ——実際のChromeが持つ navigator.usb と見分けが付かない
 * ことを目指した、ページ向けの顔。
 *
 * 「Firefox-style surface」は、拡張機能自身の特権的なページ
 * (background.js・popup.js)が、postMessage/content_scriptの中継を一切
 * 経由せず、ネイティブホストへの唯一の窓口であるbackground.js自身の
 * dispatch関数を直接呼び出して使う、拡張機能内部向けの顔。これは
 * WICGの実際の提案(webusb "extension-service-worker-explainer"、
 * および実際にChrome 118以降で拡張機能のservice workerに
 * navigator.usbを公開しているChrome拡張機能向けWebUSBの仕様どおりの
 * 方向性)と同じ発想を、Manifest V2の永続的background pageという
 * fox-webusb自身のアーキテクチャに合わせて実装したもの。
 *
 * 🛡️ 「Firefox風」なのはあくまで配線(トランスポート)の話であって、
 * ここで定義するクラス自体・振る舞い(メソッド名・引数・戻り値・
 * エラー名・イベントの形)はWebUSB仕様そのままである。この
 * webusb_core.js自体は両サーフェスから共有される単一の実装なので、
 * 「Chromium面とFirefox面で挙動が違う」という食い違いはそもそも
 * 構造的に起こり得ない——差があるとすれば、それは意図してトランスポート
 * (=呼び出し元のコンテキストが拡張機能自身かどうか)に応じて変える
 * べき部分(後述のrequestDevice()のユーザー操作要件等)だけである。
 *
 * このファイル自体は「USB compatibility core」そのものではなく(実体は
 * ネイティブホスト側のbridge.py/hardening.pyにある)、あくまで両サーフェス
 * が同じ形でそのcoreを叩けるようにする、JS側の薄い共通層である。
 *
 * ============================================================
 * 使い方
 * ============================================================
 *   var core = FoxWebusbCore.create(callBridge, { requestDeviceNeedsGesture: true });
 *   // callBridge(method: string, params: object) => Promise<object>
 *   //   (戻り値は常に生のオブジェクト。JSON文字列ではない——呼び出し元が
 *   //   どう文字列化/デコードするかはトランスポートの側の関心事)
 *   navigator.usb = core.usb; // または好きな名前で公開する
 *   core.dispatchConnectionEvent('connect', deviceDescriptor); // push通知を受けたら呼ぶ
 */
(function (root) {
  'use strict';

  function createFoxWebusbCore(callBridge, options) {
    options = options || {};
    // 🛡️ requestDevice()のnavigator.userActivationチェックは、呼び出し元の
    // 実行コンテキストが「本物のページ(ユーザーが実際にクリックし得る)」か
    // 「常駐backgroundページ(通常は絶対にユーザー操作を受け取らない)」かで
    // 意味が変わる。Chromium surface(page_polyfill.js)・popup.js向けの
    // Firefox-style surfaceでは既定でtrue(仕様どおり検証する)。
    // background.js自身の内部利用のように、そもそもrequestDevice()を
    // このコンテキストから呼ぶ設計になっていない場合はfalseを渡せる
    // (それでもホスト側のhas_gesture検証自体は別途必ず行われる——
    // これはあくまでJS側の早期TypeError/SecurityErrorの話)。
    var requestDeviceNeedsGesture = options.requestDeviceNeedsGesture !== false;

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
    // 対応する例外へ変換する。プレフィックス表はerrors.pyと1対1。
    // 🛡️ 'TypeError'だけは他と扱いが違う: 実仕様がDOMExceptionではなく
    // 組み込みのTypeErrorを要求する箇所(filters構造検証等)に対応するため。
    // ============================================================
    function throwFromResult(res) {
      var message = (res && res.error) || 'unknown error';
      var colonIndex = message.indexOf(':');
      var name = colonIndex >= 0 ? message.slice(0, colonIndex) : '';
      var detail = colonIndex >= 0 ? message.slice(colonIndex + 1).trim() : message;
      if (name === 'TypeError') throw new TypeError(detail);
      var known = ['SecurityError', 'InvalidStateError', 'NotFoundError', 'InvalidAccessError', 'IndexSizeError'];
      if (known.indexOf(name) === -1) {
        name = 'NetworkError';
        detail = message;
      }
      throw new DOMException(detail, name);
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
    // ============================================================
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
    // 転送結果オブジェクト群
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
    }

    class USBDevice {
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
    // 🛡️ v0.0.0a1: WICG仕様の現行版(2026年9月時点、wicg.github.io/webusb
    // index.bsを実際に確認)どおりのIDL形状にした:
    //   dictionary USBConnectionEventInit : EventInit { required USBDevice device; };
    //   interface USBConnectionEvent : Event { [SameObject] readonly attribute USBDevice device; };
    // 「requiredなdevice」を仕様どおり強制する(以前はeventInitDict.device
    // が無くても#device=nullで黙って構築できてしまっていた——仕様が
    // 求める"device must always be present"という保証と食い違っていた)。
    class USBConnectionEvent extends Event {
      #device;

      constructor(type, eventInitDict) {
        super(type, eventInitDict);
        if (!eventInitDict || !eventInitDict.device) {
          throw new TypeError("Failed to construct 'USBConnectionEvent': "
            + "required member device is undefined.");
        }
        this.#device = eventInitDict.device;
      }

      get device() {
        return this.#device;
      }

      get [Symbol.toStringTag]() { return 'USBConnectionEvent'; }
    }

    // ============================================================
    // USB (navigator.usb 本体)
    // ============================================================
    class USB extends EventTarget {
      #onconnectHandler = null;
      #ondisconnectHandler = null;

      getDevices() {
        return callBridge('listDevices', {}).then(function (res) {
          return (res.devices || []).map(function (d) { return new USBDevice(d); });
        });
      }

      requestDevice(reqOptions) {
        return Promise.resolve().then(function () {
          reqOptions = reqOptions || {};
          validateFilters(reqOptions.filters);
          validateFilters(reqOptions.exclusionFilters);
          if (requestDeviceNeedsGesture &&
              typeof navigator !== 'undefined' && navigator.userActivation &&
              navigator.userActivation.isActive === false) {
            throw new DOMException('requestDevice() must be called from a user gesture (e.g. a click handler)', 'SecurityError');
          }
          return callBridge('requestDeviceChooser', {
            filters: reqOptions.filters || [], exclusionFilters: reqOptions.exclusionFilters || [],
          });
        }).then(function (res) {
          if (!res.success) throwFromResult(res);
          return new USBDevice(res.device);
        });
      }

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

    var usbInstance = new USB();

    function dispatchConnectionEvent(kind, deviceDescriptor) {
      var device = new USBDevice(deviceDescriptor || {});
      var event = new USBConnectionEvent(kind, { device: device });
      usbInstance.dispatchEvent(event);
    }

    return {
      usb: usbInstance,
      USBDevice: USBDevice,
      USBConnectionEvent: USBConnectionEvent,
      dispatchConnectionEvent: dispatchConnectionEvent,
      throwFromResult: throwFromResult,
      validateFilters: validateFilters,
      // 🦊 独自拡張(実Chromeのnavigator.usbには相当機能が無い): このブリッジ
      // 自体の状態(バージョン・Rustアクセラレーションが実際に効いているか・
      // 転送サイズの上限)。意図的にnavigator.usb/USBクラス自体には一切乗せて
      // いない——乗せてしまうとObject.getOwnPropertyNames()等での深層検査で
      // 「実Chromeには無い独自メソッド」として露見し、既存のdevtools耐性
      // (test_page_polyfill.js「no internal state leaks」「exposed methods
      // have no .prototype」等)が意味を成さなくなる。__foxWebUSB(F12
      // デバッグヘルパー、page_polyfill.js参照)からだけ使う、独立した関数。
      isAvailable: function () { return callBridge('isAvailable', {}); },

      // 🦊 独自拡張(実Chromeのnavigator.usbには存在しない): ローカル
      // アテステーション。オリジンごとのEd25519鍵ペアを使い、サイトが
      // 「このレスポンスが本当に前回と同じローカルブリッジから来たものか」を
      // 検証できるようにする(TOFU方式——先にgetPublicKey()の結果を保存して
      // おき、以降sign()の結果をその公開鍵で検証する)。詳細は
      // native-host/src/fox_webusb_host/attestation.py のモジュール
      // docstring参照。使っているのは確立されたEd25519署名方式そのもので、
      // 独自の暗号アルゴリズムではない。
      attestation: {
        isSupported: function () {
          return callBridge('isAvailable', {}).then(function () { return true; }).catch(function () { return false; });
        },
        getPublicKey: function () {
          return callBridge('getAttestationPublicKey', {}).then(function (res) {
            if (!res.success) throwFromResult(res);
            return base64ToUint8(res.publicKey);
          });
        },
        sign: function (challengeBytes) {
          var challenge = bufferSourceToUint8(challengeBytes);
          return callBridge('signAttestationChallenge', { challenge: bytesToBase64(challenge) }).then(function (res) {
            if (!res.success) throwFromResult(res);
            return base64ToUint8(res.signature);
          });
        },
      },
    };
  }

  var FoxWebusbCore = { create: createFoxWebusbCore };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = FoxWebusbCore; // Node(テストランナー)向け
  } else if (typeof window !== 'undefined') {
    window.FoxWebusbCore = FoxWebusbCore; // ページ/拡張機能ページのグローバルスコープ向け(通常経路)
  } else {
    root.FoxWebusbCore = FoxWebusbCore; // 保険(windowが無いがCommonJSでもない実行環境向け)
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
