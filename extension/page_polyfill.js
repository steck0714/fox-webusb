/*
 * page_polyfill.js
 * ================
 * navigator.usb (WebUSB) のポリフィル本体。content_script.js によって、
 * ページ自身のJS実行コンテキスト(MAIN world)に <script src="..."> として
 * 注入される。
 *
 * 移植元: pyside6-webusb (v0.0.4b0) の polyfill.py 内 WEBUSB_POLYFILL_JS。
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
 *           (README「オリジンの検証」を参照)。callBridge()の戻り値は
 *           postMessageで渡された時点で既に構造化されたオブジェクトなので、
 *           JSON.parseは不要。
 *
 * このファイル自体はどのフレームでも同じ内容が注入される
 * (content_script.jsがall_frames:trueで動くため)。
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
  var _listeners = { connect: [], disconnect: [] };

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
    var list = _listeners[kind];
    if (!list || !list.length) return;
    var device = new OpenWebUSBDevice(deviceDescriptor || {});
    var evt = { type: kind, device: device };
    for (var i = 0; i < list.length; i++) {
      try {
        list[i].call(navigatorUsbSingleton, evt);
      } catch (e) {
        // 1つのリスナーの例外で他のリスナー呼び出しを止めない(通常のDOMイベント配送と同じ振る舞い)
        setTimeout(function () { throw e; });
      }
    }
    if (typeof navigatorUsbSingleton['on' + kind] === 'function') {
      try { navigatorUsbSingleton['on' + kind].call(navigatorUsbSingleton, evt); } catch (e) { setTimeout(function () { throw e; }); }
    }
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

  // ============================================================
  // インターフェース/エンドポイントのディスクリプタ木を、
  // claim状態・alternate選択状態と突き合わせて解釈するヘルパー群
  // ============================================================
  function deriveInterfaceState(device, interfaceNumber) {
    var iface = null;
    for (var i = 0; i < device.configurations.length; i++) {
      var cfg = device.configurations[i];
      if (cfg.configurationValue !== device._activeConfigurationValue) continue;
      for (var j = 0; j < cfg.interfaces.length; j++) {
        if (cfg.interfaces[j].interfaceNumber === interfaceNumber) { iface = cfg.interfaces[j]; break; }
      }
    }
    return iface;
  }

  function _findClaimedEndpoint(device, endpointNumber, direction) {
    var claimedAlt = device._claimedAlternates[String(endpointNumber) + ':' + direction];
    for (var i = 0; i < device.configurations.length; i++) {
      var cfg = device.configurations[i];
      if (cfg.configurationValue !== device._activeConfigurationValue) continue;
      for (var j = 0; j < cfg.interfaces.length; j++) {
        var interfaceNumber = cfg.interfaces[j].interfaceNumber;
        if (device._claimedInterfaces.indexOf(interfaceNumber) === -1) continue;
        var altSetting = device._activeAlternates[interfaceNumber] || 0;
        var alternates = cfg.interfaces[j].alternates;
        for (var k = 0; k < alternates.length; k++) {
          if (alternates[k].alternateSetting !== altSetting) continue;
          var endpoints = alternates[k].endpoints;
          for (var m = 0; m < endpoints.length; m++) {
            if (endpoints[m].endpointNumber === endpointNumber && endpoints[m].direction === direction) {
              return endpoints[m];
            }
          }
        }
      }
    }
    void claimedAlt;
    return null;
  }

  // ============================================================
  // USBConfiguration / USBInterface / USBAlternateInterface / USBEndpoint
  // (仕様どおりの読み取り専用ビュー。実データはbridgeから来たプレーン
  // オブジェクトをラップしているだけ)
  // ============================================================
  function USBEndpoint(raw) {
    this.endpointNumber = raw.endpointNumber;
    this.direction = raw.direction;
    this.type = raw.type;
    this.packetSize = raw.packetSize;
  }

  function USBAlternateInterface(raw) {
    this.alternateSetting = raw.alternateSetting;
    this.interfaceClass = raw.interfaceClass;
    this.interfaceSubclass = raw.interfaceSubclass;
    this.interfaceProtocol = raw.interfaceProtocol;
    this.interfaceName = raw.interfaceName || null;
    this.endpoints = (raw.endpoints || []).map(function (e) { return new USBEndpoint(e); });
  }

  function USBInterfaceView(raw, device) {
    var self = this;
    this.interfaceNumber = raw.interfaceNumber;
    this.alternates = (raw.alternates || []).map(function (a) { return new USBAlternateInterface(a); });
    Object.defineProperty(this, 'claimed', {
      get: function () { return device._claimedInterfaces.indexOf(self.interfaceNumber) !== -1; },
    });
    Object.defineProperty(this, 'alternate', {
      get: function () {
        var wantAlt = device._activeAlternates[self.interfaceNumber] || 0;
        for (var i = 0; i < self.alternates.length; i++) {
          if (self.alternates[i].alternateSetting === wantAlt) return self.alternates[i];
        }
        return self.alternates[0] || null;
      },
    });
  }

  function USBConfigurationView(raw, device) {
    this.configurationValue = raw.configurationValue;
    this.configurationName = raw.configurationName || null;
    this.interfaces = (raw.interfaces || []).map(function (i) { return new USBInterfaceView(i, device); });
  }

  // ============================================================
  // USBDevice
  // ============================================================
  function OpenWebUSBDevice(desc) {
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

    this._activeConfigurationValue = desc.activeConfigurationValue || (desc.configurations && desc.configurations[0] && desc.configurations[0].configurationValue) || null;
    this._claimedInterfaces = [];
    this._activeAlternates = {};
    this._claimedAlternates = {};
    this._handle = null;
    this._opened = false;

    var self = this;
    this.configurations = (desc.configurations || []).map(function (c) { return new USBConfigurationView(c, self); });
    Object.defineProperty(this, 'configuration', {
      get: function () {
        for (var i = 0; i < self.configurations.length; i++) {
          if (self.configurations[i].configurationValue === self._activeConfigurationValue) return self.configurations[i];
        }
        return null;
      },
    });
    Object.defineProperty(this, 'opened', { get: function () { return self._opened; } });
  }

  OpenWebUSBDevice.prototype.open = function () {
    var self = this;
    if (this._opened) return Promise.resolve();
    return callBridge('openDevice', { vendorId: this.vendorId, productId: this.productId }).then(function (res) {
      if (!res.success) throwFromResult(res);
      self._handle = res.handle;
      self._opened = true;
    });
  };

  OpenWebUSBDevice.prototype.close = function () {
    var self = this;
    if (!this._opened) return Promise.resolve();
    return callBridge('closeDevice', { handle: this._handle }).then(function () {
      self._opened = false;
      self._handle = null;
      self._claimedInterfaces = [];
      self._activeAlternates = {};
    });
  };

  function requireOpen(device) {
    if (!device._opened) throw new DOMException('the device must be open() before this call', 'InvalidStateError');
  }

  // 🛡️ 重要: WebUSB(に限らずPromiseを返すWeb API全般)の規約では、引数検証や
  // 前提状態チェックの失敗も含めて「常にPromiseのrejectとして」報告する
  // ——同期的にthrowしてはいけない。呼び出し側が
  // `promise.catch(...)` や `await` の中の `try/catch` だけを書けば、
  // エラーの原因(引数不正か、状態不正か、実際の転送失敗か)によらず
  // 一様に処理できることを保証するため。以下の各メソッドが
  // `Promise.resolve().then(function () { ...検証... })` から書き始めて
  // いるのはこのためで、`.then()`コールバック内で投げた例外は自動的に
  // その戻り値Promiseのrejectionに変換される(Promise仕様どおりの挙動)。

  OpenWebUSBDevice.prototype.selectConfiguration = function (configurationValue) {
    var self = this;
    return Promise.resolve().then(function () {
      requireOpen(self);
      return callBridge('selectConfiguration', { handle: self._handle, configurationValue: configurationValue });
    }).then(function (res) {
      if (!res.success) throwFromResult(res);
      self._activeConfigurationValue = configurationValue;
      self._claimedInterfaces = [];
      self._activeAlternates = {};
    });
  };

  OpenWebUSBDevice.prototype.claimInterface = function (interfaceNumber) {
    var self = this;
    return Promise.resolve().then(function () {
      requireOpen(self);
      return callBridge('claimInterface', { handle: self._handle, interfaceNumber: interfaceNumber });
    }).then(function (res) {
      if (!res.success) throwFromResult(res);
      if (self._claimedInterfaces.indexOf(interfaceNumber) === -1) self._claimedInterfaces.push(interfaceNumber);
      if (!(interfaceNumber in self._activeAlternates)) self._activeAlternates[interfaceNumber] = 0;
    });
  };

  OpenWebUSBDevice.prototype.releaseInterface = function (interfaceNumber) {
    var self = this;
    return Promise.resolve().then(function () {
      requireOpen(self);
      return callBridge('releaseInterface', { handle: self._handle, interfaceNumber: interfaceNumber });
    }).then(function (res) {
      if (!res.success) throwFromResult(res);
      var idx = self._claimedInterfaces.indexOf(interfaceNumber);
      if (idx !== -1) self._claimedInterfaces.splice(idx, 1);
      delete self._activeAlternates[interfaceNumber];
    });
  };

  OpenWebUSBDevice.prototype.selectAlternateInterface = function (interfaceNumber, alternateSetting) {
    var self = this;
    return Promise.resolve().then(function () {
      requireOpen(self);
      return callBridge('selectAlternateInterface', {
        handle: self._handle, interfaceNumber: interfaceNumber, alternateSetting: alternateSetting,
      });
    }).then(function (res) {
      if (!res.success) throwFromResult(res);
      self._activeAlternates[interfaceNumber] = alternateSetting;
    });
  };

  OpenWebUSBDevice.prototype.reset = function () {
    var self = this;
    return Promise.resolve().then(function () {
      requireOpen(self);
      return callBridge('resetDevice', { handle: self._handle });
    }).then(function (res) {
      if (!res.success) throwFromResult(res);
      self._claimedInterfaces = [];
      self._activeAlternates = {};
    });
  };

  OpenWebUSBDevice.prototype.clearHalt = function (direction, endpointNumber) {
    var self = this;
    return Promise.resolve().then(function () {
      requireOpen(self);
      return callBridge('clearHalt', { handle: self._handle, direction: direction, endpointNumber: endpointNumber });
    }).then(function (res) {
      if (!res.success) throwFromResult(res);
    });
  };

  OpenWebUSBDevice.prototype.forget = function () {
    var self = this;
    return callBridge('forgetGrantedDevice', { vendorId: this.vendorId, productId: this.productId }).then(function () {
      return self.close();
    });
  };

  OpenWebUSBDevice.prototype.transferIn = function (endpointNumber, length) {
    var self = this;
    return Promise.resolve().then(function () {
      requireOpen(self);
      return callBridge('bulkTransferIn', { handle: self._handle, endpoint: endpointNumber, length: length });
    }).then(function (res) {
      if (!res.success) throwFromResult(res);
      var bytes = base64ToUint8(res.data);
      return { data: new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), status: res.status };
    });
  };

  OpenWebUSBDevice.prototype.transferOut = function (endpointNumber, data) {
    var self = this;
    return Promise.resolve().then(function () {
      var bytes = bufferSourceToUint8(data);
      requireOpen(self);
      return callBridge('bulkTransferOut', { handle: self._handle, endpoint: endpointNumber, data: bytesToBase64(bytes) });
    }).then(function (res) {
      if (!res.success) throwFromResult(res);
      return { bytesWritten: res.bytesWritten, status: res.status };
    });
  };

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

  OpenWebUSBDevice.prototype.controlTransferIn = function (setup, length) {
    var self = this;
    return Promise.resolve().then(function () {
      requireOpen(self);
      return callBridge('controlTransferIn', {
        handle: self._handle, requestType: combineRequestType(setup),
        request: setup.request, value: setup.value, index: setup.index, length: length,
      });
    }).then(function (res) {
      if (!res.success) throwFromResult(res);
      var bytes = base64ToUint8(res.data);
      return { data: new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), status: res.status };
    });
  };

  OpenWebUSBDevice.prototype.controlTransferOut = function (setup, data) {
    var self = this;
    return Promise.resolve().then(function () {
      var bytes = data ? bufferSourceToUint8(data) : new Uint8Array(0);
      requireOpen(self);
      return callBridge('controlTransferOut', {
        handle: self._handle, requestType: combineRequestType(setup),
        request: setup.request, value: setup.value, index: setup.index, data: bytesToBase64(bytes),
      });
    }).then(function (res) {
      if (!res.success) throwFromResult(res);
      return { bytesWritten: res.bytesWritten, status: res.status };
    });
  };

  OpenWebUSBDevice.prototype.isochronousTransferIn = function (endpointNumber, packetLengths) {
    var self = this;
    return Promise.resolve().then(function () {
      requireOpen(self);
      return callBridge('isochronousTransferIn', {
        handle: self._handle, endpoint: endpointNumber, packetLengths: packetLengths,
      });
    }).then(function (res) {
      if (!res.success) throwFromResult(res);
      var packets = res.packets.map(function (p) {
        var bytes = base64ToUint8(p.data);
        return { data: new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), status: p.status };
      });
      // 仕様: isochronousTransferInは全パケットを1本のバッファへ結合したdataと、
      // 各パケットの{length, status}を持つpackets配列の両方を返す。
      var totalLength = packets.reduce(function (sum, p) { return sum + p.data.byteLength; }, 0);
      var combined = new Uint8Array(totalLength);
      var offset = 0;
      var packetRecords = [];
      packets.forEach(function (p) {
        combined.set(new Uint8Array(p.data.buffer, p.data.byteOffset, p.data.byteLength), offset);
        packetRecords.push({ length: p.data.byteLength, status: p.status });
        offset += p.data.byteLength;
      });
      return { data: new DataView(combined.buffer), packets: packetRecords };
    });
  };

  OpenWebUSBDevice.prototype.isochronousTransferOut = function (endpointNumber, data, packetLengths) {
    var self = this;
    return Promise.resolve().then(function () {
      var bytes = bufferSourceToUint8(data);
      requireOpen(self);
      return callBridge('isochronousTransferOut', {
        handle: self._handle, endpoint: endpointNumber, data: bytesToBase64(bytes), packetLengths: packetLengths,
      });
    }).then(function (res) {
      if (!res.success) throwFromResult(res);
      var packetRecords = res.packets.map(function (p) { return { bytesWritten: p.bytesWritten, status: p.status }; });
      return { packets: packetRecords };
    });
  };

  void deriveInterfaceState;
  void _findClaimedEndpoint;

  // ============================================================
  // USB (navigator.usb) シングルトン
  // ============================================================
  function validateFilters(filters) {
    if (filters === undefined) return;
    if (!Array.isArray(filters)) throw new TypeError('filters must be an array');
    filters.forEach(function (f) {
      if (!isValidFilterShape(f)) throw new TypeError('invalid device filter: ' + JSON.stringify(f));
    });
  }

  function USBSingleton() {}
  USBSingleton.prototype.getDevices = function () {
    return callBridge('listDevices', {}).then(function (res) {
      return (res.devices || []).map(function (d) { return new OpenWebUSBDevice(d); });
    });
  };

  USBSingleton.prototype.requestDevice = function (options) {
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
      return new OpenWebUSBDevice(res.device);
    });
  };

  USBSingleton.prototype.addEventListener = function (type, listener) {
    if (!_listeners[type]) return;
    if (_listeners[type].indexOf(listener) === -1) _listeners[type].push(listener);
  };
  USBSingleton.prototype.removeEventListener = function (type, listener) {
    if (!_listeners[type]) return;
    var idx = _listeners[type].indexOf(listener);
    if (idx !== -1) _listeners[type].splice(idx, 1);
  };

  var navigatorUsbSingleton = new USBSingleton();
  navigatorUsbSingleton.onconnect = null;
  navigatorUsbSingleton.ondisconnect = null;

  try {
    Object.defineProperty(navigator, 'usb', {
      value: navigatorUsbSingleton, writable: false, configurable: false, enumerable: true,
    });
  } catch (e) {
    // 🛡️ 別のスクリプトが既にnavigator.usbをdefineしていて再定義できない場合、
    // 静かに諦める(navigator.usbが存在しない元々の状態のままになるだけで、
    // ページの他の動作を壊さない)。
  }
})();
