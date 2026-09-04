/*
 * test_page_polyfill.js
 * ======================
 * page_polyfill.js を実際のFirefox無しにNodeで動かして検証する。
 * window.postMessage()をイベントループ的にエミュレートし、その中で
 * 'toContent'方向のメッセージを見つけたら、テストごとに用意した
 * フェイクのcontent_script/background/ネイティブホストの振る舞い
 * (mockDispatch)へ回して結果を'toPage'として投げ返す——これにより、
 * 実際のpage_polyfill.jsのコード(callBridge、USBDevice、
 * throwFromResult、base64変換等)を一切書き換えずに丸ごと検証できる。
 *
 * 移植元(pyside6-webusb)のtests/test_polyfill.jsが、QWebChannelの
 * トランスポートをモックして同じ発想でテストしていたのと同じ設計方針を、
 * fox-webusbのトランスポート(postMessage)に合わせて書き直したもの。
 *
 * 実行: node tests/test_page_polyfill.js
 */
'use strict';
const vm = require('vm');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const POLYFILL_SRC = fs.readFileSync(
  path.join(__dirname, '..', 'extension', 'page_polyfill.js'), 'utf8',
);

function makeSandbox(mockDispatch, opts) {
  opts = opts || {};
  const listeners = [];
  const window = {
    location: { origin: opts.origin || 'https://example.com' },
    isSecureContext: opts.isSecureContext !== undefined ? opts.isSecureContext : true,
    addEventListener(type, fn) { if (type === 'message') listeners.push(fn); },
    removeEventListener(type, fn) {
      const i = listeners.indexOf(fn);
      if (i !== -1) listeners.splice(i, 1);
    },
    postMessage(data) {
      setTimeout(() => {
        const event = { source: window, origin: window.location.origin, data };
        listeners.slice().forEach((fn) => fn(event));
      }, 0);
    },
  };

  // フェイクのcontent_script.js: page_polyfill.jsからの'toContent'呼び出しを
  // mockDispatch(method, params)へ回し、戻り値(または戻り値を返すPromise)を
  // 'toPage'レスポンスとして投げ返す。
  window.addEventListener('message', (event) => {
    const data = event.data;
    if (!data || data.channel !== '__foxWebusb__' || data.dir !== 'toContent' || data.kind !== 'call') return;
    Promise.resolve().then(() => mockDispatch(data.method, data.params)).then((result) => {
      window.postMessage({ channel: '__foxWebusb__', dir: 'toPage', kind: 'response', id: data.id, result: result });
    });
  });

  const navigator = {
    usb: opts.preExistingUsb, // 通常はundefined
    userActivation: opts.userActivation !== undefined ? opts.userActivation : { isActive: true },
  };

  const sandbox = {
    window, navigator, document: { location: window.location },
    DOMException: global.DOMException,
    EventTarget: global.EventTarget, Event: global.Event,
    btoa: global.btoa, atob: global.atob,
    Uint8Array, Int8Array, DataView, ArrayBuffer, TextEncoder, TextDecoder,
    Promise, Object, Array, JSON, Math, Error, TypeError, RangeError, String, Number, Boolean, Symbol,
    setTimeout, clearTimeout, console,
  };
  vm.createContext(sandbox);
  vm.runInContext(POLYFILL_SRC, sandbox, { filename: 'page_polyfill.js' });
  return sandbox;
}

function pushEvent(sandbox, eventName, device) {
  sandbox.window.postMessage({ channel: '__foxWebusb__', dir: 'toPage', kind: 'event', event: eventName, device: device });
}

async function run(name, fn) {
  try {
    await fn();
    console.log(`${name}: OK`);
  } catch (e) {
    console.error(`${name}: FAIL`);
    console.error(e && e.stack ? e.stack : e);
    process.exitCode = 1;
  }
}

const SIMPLE_DEVICE = {
  vendorId: 0x1111, productId: 0x2222, productName: 'Test Device', manufacturerName: 'Acme',
  activeConfigurationValue: 1,
  configurations: [{
    configurationValue: 1, configurationName: 'Default',
    interfaces: [{
      interfaceNumber: 0,
      alternates: [{
        alternateSetting: 0, interfaceClass: 0xff, interfaceSubclass: 0, interfaceProtocol: 0,
        endpoints: [
          { endpointNumber: 1, direction: 'in', type: 'bulk', packetSize: 64 },
          { endpointNumber: 2, direction: 'out', type: 'bulk', packetSize: 64 },
        ],
      }],
    }],
  }],
};

(async () => {
  await run('navigator.usb is defined after injection', async () => {
    const { navigator } = makeSandbox(() => ({}));
    assert.ok(navigator.usb, 'navigator.usb should be defined');
    assert.strictEqual(typeof navigator.usb.getDevices, 'function');
    assert.strictEqual(typeof navigator.usb.requestDevice, 'function');
  });

  await run('does not override an existing navigator.usb', async () => {
    const marker = { alreadyThere: true };
    const { navigator } = makeSandbox(() => ({}), { preExistingUsb: marker });
    assert.strictEqual(navigator.usb, marker);
  });

  await run('does nothing outside a secure context', async () => {
    const { navigator } = makeSandbox(() => ({}), { isSecureContext: false });
    assert.strictEqual(navigator.usb, undefined);
  });

  await run('getDevices() resolves with USBDevice-like wrappers', async () => {
    const { navigator } = makeSandbox((method) => {
      assert.strictEqual(method, 'listDevices');
      return { devices: [SIMPLE_DEVICE] };
    });
    const devices = await navigator.usb.getDevices();
    assert.strictEqual(devices.length, 1);
    assert.strictEqual(devices[0].vendorId, 0x1111);
    assert.strictEqual(devices[0].productName, 'Test Device');
    assert.strictEqual(devices[0].configurations.length, 1);
    assert.strictEqual(devices[0].configurations[0].interfaces[0].interfaceNumber, 0);
    assert.strictEqual(devices[0].opened, false);
  });

  await run('requestDevice() rejects with NotFoundError when cancelled', async () => {
    const { navigator } = makeSandbox((method) => {
      assert.strictEqual(method, 'requestDeviceChooser');
      return { success: false, error: 'NotFoundError: the user did not select a device' };
    });
    await assert.rejects(
      () => navigator.usb.requestDevice({ filters: [{ vendorId: 0x1111 }] }),
      (err) => err instanceof global.DOMException && err.name === 'NotFoundError',
    );
  });

  await run('requestDevice() requires an array for filters (TypeError)', async () => {
    const { navigator } = makeSandbox(() => ({ success: true, device: SIMPLE_DEVICE }));
    await assert.rejects(
      () => navigator.usb.requestDevice({ filters: 'not-an-array' }),
      (err) => err instanceof global.TypeError,
    );
  });

  await run('requestDevice() rejects invalid filter shapes before calling the bridge', async () => {
    let bridgeCalled = false;
    const { navigator } = makeSandbox(() => { bridgeCalled = true; return { success: true, device: SIMPLE_DEVICE }; });
    await assert.rejects(
      () => navigator.usb.requestDevice({ filters: [{ productId: 1 }] }), // vendorId無し
      (err) => err instanceof global.TypeError,
    );
    assert.strictEqual(bridgeCalled, false, 'the bridge should not be called for a structurally invalid filter');
  });

  await run('requestDevice() requires user activation', async () => {
    const { navigator } = makeSandbox(() => ({ success: true, device: SIMPLE_DEVICE }), {
      userActivation: { isActive: false },
    });
    await assert.rejects(
      () => navigator.usb.requestDevice({ filters: [{}] }),
      (err) => err instanceof global.DOMException && err.name === 'SecurityError',
    );
  });

  await run('open()/close() round trip and track the opened flag', async () => {
    let handleCounter = 0;
    const { navigator } = makeSandbox((method, params) => {
      if (method === 'listDevices') return { devices: [SIMPLE_DEVICE] };
      if (method === 'openDevice') return { success: true, handle: ++handleCounter };
      if (method === 'closeDevice') { assert.strictEqual(params.handle, handleCounter); return { success: true }; }
      throw new Error('unexpected method ' + method);
    });
    const [device] = await navigator.usb.getDevices();
    assert.strictEqual(device.opened, false);
    await device.open();
    assert.strictEqual(device.opened, true);
    await device.close();
    assert.strictEqual(device.opened, false);
  });

  await run('claimInterface()/releaseInterface() require the device to be open', async () => {
    const { navigator } = makeSandbox(() => ({ devices: [SIMPLE_DEVICE] }));
    const [device] = await navigator.usb.getDevices();
    await assert.rejects(
      () => device.claimInterface(0),
      (err) => err instanceof global.DOMException && err.name === 'InvalidStateError',
    );
  });

  await run('transferIn() base64-decodes data and preserves status', async () => {
    const payload = Buffer.from('hello fox-webusb', 'utf8');
    const { navigator } = makeSandbox((method, params) => {
      if (method === 'listDevices') return { devices: [SIMPLE_DEVICE] };
      if (method === 'openDevice') return { success: true, handle: 1 };
      if (method === 'bulkTransferIn') {
        assert.strictEqual(params.endpoint, 1);
        assert.strictEqual(params.length, 64);
        return { success: true, status: 'ok', data: payload.toString('base64') };
      }
      throw new Error('unexpected method ' + method);
    });
    const [device] = await navigator.usb.getDevices();
    await device.open();
    const result = await device.transferIn(1, 64);
    assert.strictEqual(result.status, 'ok');
    const received = Buffer.from(result.data.buffer, result.data.byteOffset, result.data.byteLength);
    assert.strictEqual(received.toString('utf8'), 'hello fox-webusb');
  });

  await run('transferOut() base64-encodes the payload it sends', async () => {
    let capturedB64 = null;
    const { navigator } = makeSandbox((method, params) => {
      if (method === 'listDevices') return { devices: [SIMPLE_DEVICE] };
      if (method === 'openDevice') return { success: true, handle: 1 };
      if (method === 'bulkTransferOut') { capturedB64 = params.data; return { success: true, status: 'ok', bytesWritten: 5 }; }
      throw new Error('unexpected method ' + method);
    });
    const [device] = await navigator.usb.getDevices();
    await device.open();
    const data = new Uint8Array([1, 2, 3, 4, 5]);
    const result = await device.transferOut(2, data);
    assert.strictEqual(result.bytesWritten, 5);
    assert.strictEqual(Buffer.from(capturedB64, 'base64').equals(Buffer.from(data)), true);
  });

  await run('a large (500KB) transferOut/transferIn round trip stays byte-identical', async () => {
    const size = 500000;
    const original = new Uint8Array(size);
    for (let i = 0; i < size; i++) original[i] = i % 256;
    let stored = null;
    const { navigator } = makeSandbox((method, params) => {
      if (method === 'listDevices') return { devices: [SIMPLE_DEVICE] };
      if (method === 'openDevice') return { success: true, handle: 1 };
      if (method === 'bulkTransferOut') { stored = params.data; return { success: true, status: 'ok', bytesWritten: size }; }
      if (method === 'bulkTransferIn') return { success: true, status: 'ok', data: stored };
      throw new Error('unexpected method ' + method);
    });
    const [device] = await navigator.usb.getDevices();
    await device.open();
    await device.transferOut(2, original);
    const result = await device.transferIn(1, size);
    const received = new Uint8Array(result.data.buffer, result.data.byteOffset, result.data.byteLength);
    assert.strictEqual(received.length, size);
    for (let i = 0; i < size; i++) {
      if (received[i] !== original[i]) throw new Error(`byte mismatch at offset ${i}`);
    }
  });

  await run('controlTransferIn() combines requestType/recipient into one byte, without the direction bit', async () => {
    const { navigator } = makeSandbox((method, params) => {
      if (method === 'listDevices') return { devices: [SIMPLE_DEVICE] };
      if (method === 'openDevice') return { success: true, handle: 1 };
      if (method === 'controlTransferIn') {
        // vendor(0x40) | interface(0x01) = 0x41 で、directionビット(0x80)は
        // JS側で立てない設計(bridge.py側が呼び出しメソッドに応じて強制する)。
        assert.strictEqual(params.requestType, 0x41);
        return { success: true, status: 'ok', data: Buffer.from([9, 9]).toString('base64') };
      }
      throw new Error('unexpected method ' + method);
    });
    const [device] = await navigator.usb.getDevices();
    await device.open();
    const result = await device.controlTransferIn({ requestType: 'vendor', recipient: 'interface', request: 1, value: 0, index: 0 }, 2);
    assert.strictEqual(result.status, 'ok');
  });

  await run('combineRequestType rejects unknown requestType/recipient strings', async () => {
    const { navigator } = makeSandbox((method) => {
      if (method === 'listDevices') return { devices: [SIMPLE_DEVICE] };
      if (method === 'openDevice') return { success: true, handle: 1 };
      throw new Error('unexpected method ' + method);
    });
    const [device] = await navigator.usb.getDevices();
    await device.open();
    // 🆕 v0.0.0a0: #openedは本物のプライベートフィールドになったため、
    // 以前のようにdevice._opened = trueで外から偽装することはできない
    // (実際にopen()を通す必要がある——これ自体がカプセル化が効いている
    // ことの確認でもある)。
    await assert.rejects(
      () => device.controlTransferIn({ requestType: 'nonsense', recipient: 'device', request: 1, value: 0, index: 0 }, 1),
      (err) => err instanceof global.TypeError,
    );
  });

  await run('isochronousTransferIn() combines all packets into one DataView plus a packets array', async () => {
    const { navigator } = makeSandbox((method, params) => {
      if (method === 'listDevices') return { devices: [SIMPLE_DEVICE] };
      if (method === 'openDevice') return { success: true, handle: 1 };
      if (method === 'isochronousTransferIn') {
        assert.deepStrictEqual(params.packetLengths, [4, 4]);
        return {
          success: true,
          packets: [
            { status: 'ok', data: Buffer.from('AAAA').toString('base64') },
            { status: 'ok', data: Buffer.from('BBBB').toString('base64') },
          ],
        };
      }
      throw new Error('unexpected method ' + method);
    });
    const [device] = await navigator.usb.getDevices();
    await device.open();
    const result = await device.isochronousTransferIn(1, [4, 4]);
    assert.strictEqual(result.packets.length, 2);
    assert.strictEqual(result.packets[0].data.byteLength, 4);
    assert.strictEqual(Buffer.from(result.packets[0].data.buffer, result.packets[0].data.byteOffset, 4).toString('utf8'), 'AAAA');
    assert.strictEqual(Buffer.from(result.packets[1].data.buffer, result.packets[1].data.byteOffset, 4).toString('utf8'), 'BBBB');
    const combined = Buffer.from(result.data.buffer);
    assert.strictEqual(combined.toString('utf8'), 'AAAABBBB');
  });

  await run('an error response is thrown as the matching DOMException', async () => {
    const { navigator } = makeSandbox((method) => {
      if (method === 'listDevices') return { devices: [SIMPLE_DEVICE] };
      if (method === 'openDevice') return { success: false, error: 'SecurityError: this origin has not been granted access to this device' };
      throw new Error('unexpected method ' + method);
    });
    const [device] = await navigator.usb.getDevices();
    await assert.rejects(
      () => device.open(),
      (err) => err instanceof global.DOMException && err.name === 'SecurityError' &&
        /not been granted access/.test(err.message),
    );
  });

  await run('an unrecognized error prefix is surfaced as NetworkError rather than silently dropped', async () => {
    const { navigator } = makeSandbox((method) => {
      if (method === 'listDevices') return { devices: [SIMPLE_DEVICE] };
      if (method === 'openDevice') return { success: false, error: 'libusb: some low-level failure' };
      throw new Error('unexpected method ' + method);
    });
    const [device] = await navigator.usb.getDevices();
    await assert.rejects(
      () => device.open(),
      (err) => err instanceof global.DOMException && err.name === 'NetworkError',
    );
  });

  await run("'connect' events reach a registered listener as a USBConnectionEvent-like object", async () => {
    const sandbox = makeSandbox(() => ({}));
    const { navigator, window } = sandbox;
    let receivedDevice = null;
    navigator.usb.addEventListener('connect', (evt) => { receivedDevice = evt.device; });
    pushEvent(sandbox, 'connect', SIMPLE_DEVICE);
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.ok(receivedDevice);
    assert.strictEqual(receivedDevice.vendorId, 0x1111);
    void window;
  });

  await run("removeEventListener() actually stops further delivery", async () => {
    const sandbox = makeSandbox(() => ({}));
    const { navigator } = sandbox;
    let callCount = 0;
    const handler = () => { callCount++; };
    navigator.usb.addEventListener('disconnect', handler);
    pushEvent(sandbox, 'disconnect', SIMPLE_DEVICE);
    await new Promise((resolve) => setTimeout(resolve, 10));
    navigator.usb.removeEventListener('disconnect', handler);
    pushEvent(sandbox, 'disconnect', SIMPLE_DEVICE);
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.strictEqual(callCount, 1);
  });

  await run('forget() revokes the grant and then closes the device', async () => {
    const calls = [];
    const { navigator } = makeSandbox((method, params) => {
      calls.push(method);
      if (method === 'listDevices') return { devices: [SIMPLE_DEVICE] };
      if (method === 'openDevice') return { success: true, handle: 7 };
      if (method === 'forgetGrantedDevice') return { success: true };
      if (method === 'closeDevice') { assert.strictEqual(params.handle, 7); return { success: true }; }
      throw new Error('unexpected method ' + method);
    });
    const [device] = await navigator.usb.getDevices();
    await device.open();
    await device.forget();
    assert.deepStrictEqual(calls, ['listDevices', 'openDevice', 'forgetGrantedDevice', 'closeDevice']);
    assert.strictEqual(device.opened, false);
  });

  // ============================================================
  // 🆕 v0.0.0a0: 深い型検証への耐性(devtoolsで prototype/toStringTag を
  // 掘られても、本物のブラウザ実装と見分けがつきにくいことの検証)。
  // 実際にF12でnavigator.usbを調べた方からのフィードバックがきっかけ。
  // ============================================================

  await run('navigator.usb is a real EventTarget (instanceof, prototype chain)', async () => {
    const { navigator, EventTarget } = makeSandbox(() => ({}));
    assert.strictEqual(navigator.usb instanceof EventTarget, true);
    const proto = Object.getPrototypeOf(Object.getPrototypeOf(navigator.usb));
    assert.strictEqual(proto, EventTarget.prototype);
  });

  await run('navigator.usb identifies as "USB" under deep introspection', async () => {
    const { navigator } = makeSandbox(() => ({}));
    assert.strictEqual(navigator.usb.constructor.name, 'USB');
    assert.strictEqual(navigator.usb[Symbol.toStringTag], 'USB');
    assert.strictEqual(Object.prototype.toString.call(navigator.usb), '[object USB]');
  });

  await run('navigator.usb inherits the real addEventListener/removeEventListener (not a hand-rolled override)', async () => {
    const { navigator, EventTarget } = makeSandbox(() => ({}));
    assert.strictEqual(navigator.usb.addEventListener, EventTarget.prototype.addEventListener);
    assert.strictEqual(navigator.usb.removeEventListener, EventTarget.prototype.removeEventListener);
    assert.strictEqual(typeof navigator.usb.dispatchEvent, 'function');
  });

  await run('a USBDevice instance identifies as "USBDevice" under deep introspection', async () => {
    const { navigator } = makeSandbox(() => ({ devices: [SIMPLE_DEVICE] }));
    const [device] = await navigator.usb.getDevices();
    assert.strictEqual(device.constructor.name, 'USBDevice');
    assert.strictEqual(device[Symbol.toStringTag], 'USBDevice');
    assert.strictEqual(Object.prototype.toString.call(device), '[object USBDevice]');
  });

  await run('nested USBConfiguration/USBInterface/USBEndpoint identify correctly under deep introspection', async () => {
    const { navigator } = makeSandbox(() => ({ devices: [SIMPLE_DEVICE] }));
    const [device] = await navigator.usb.getDevices();
    const cfg = device.configurations[0];
    const iface = cfg.interfaces[0];
    const alt = iface.alternates[0];
    const ep = alt.endpoints[0];
    assert.strictEqual(Object.prototype.toString.call(cfg), '[object USBConfiguration]');
    assert.strictEqual(Object.prototype.toString.call(iface), '[object USBInterface]');
    assert.strictEqual(Object.prototype.toString.call(alt), '[object USBAlternateInterface]');
    assert.strictEqual(Object.prototype.toString.call(ep), '[object USBEndpoint]');
  });

  await run('dispatched connect/disconnect events are real USBConnectionEvent (extends Event) instances', async () => {
    const sandbox = makeSandbox(() => ({}));
    const { navigator, Event } = sandbox;
    let received = null;
    navigator.usb.addEventListener('connect', (evt) => { received = evt; });
    pushEvent(sandbox, 'connect', SIMPLE_DEVICE);
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.ok(received);
    assert.strictEqual(received instanceof Event, true);
    assert.strictEqual(received.type, 'connect');
    assert.strictEqual(Object.prototype.toString.call(received), '[object USBConnectionEvent]');
    assert.strictEqual(received.device.vendorId, 0x1111);
  });

  await run('onconnect/ondisconnect behave as single-slot IDL event handler attributes', async () => {
    const sandbox = makeSandbox(() => ({}));
    const { navigator } = sandbox;
    let firstCalls = 0;
    let secondCalls = 0;
    navigator.usb.onconnect = () => { firstCalls++; };
    assert.strictEqual(typeof navigator.usb.onconnect, 'function');
    // 再代入すると、以前のハンドラは自動的に外れる(2つとも同時には効かない)。
    navigator.usb.onconnect = () => { secondCalls++; };
    pushEvent(sandbox, 'connect', SIMPLE_DEVICE);
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.strictEqual(firstCalls, 0);
    assert.strictEqual(secondCalls, 1);
    // nullを代入すれば解除できる。
    navigator.usb.ondisconnect = null;
    assert.strictEqual(navigator.usb.ondisconnect, null);
  });

  await run('onconnect handler and an addEventListener()-registered listener both fire', async () => {
    const sandbox = makeSandbox(() => ({}));
    const { navigator } = sandbox;
    const order = [];
    navigator.usb.addEventListener('connect', () => order.push('listener'));
    navigator.usb.onconnect = () => order.push('onconnect');
    pushEvent(sandbox, 'connect', SIMPLE_DEVICE);
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.strictEqual(order.length, 2);
    assert.ok(order.includes('listener'));
    assert.ok(order.includes('onconnect'));
  });

  await run('USBInTransferResult/USBOutTransferResult identify correctly under deep introspection', async () => {
    const { navigator } = makeSandbox((method) => {
      if (method === 'listDevices') return { devices: [SIMPLE_DEVICE] };
      if (method === 'openDevice') return { success: true, handle: 1 };
      if (method === 'bulkTransferIn') return { success: true, status: 'ok', data: Buffer.from('hi').toString('base64') };
      if (method === 'bulkTransferOut') return { success: true, status: 'ok', bytesWritten: 2 };
      throw new Error('unexpected method ' + method);
    });
    const [device] = await navigator.usb.getDevices();
    await device.open();
    const inResult = await device.transferIn(1, 8);
    const outResult = await device.transferOut(2, new Uint8Array([1, 2]));
    assert.strictEqual(Object.prototype.toString.call(inResult), '[object USBInTransferResult]');
    assert.strictEqual(Object.prototype.toString.call(outResult), '[object USBOutTransferResult]');
  });

  // ============================================================
  // 🆕 v0.0.0a0 (続き): 「chrome webusbでnavigator.usbの有無を調べる際に
  // 考えられるチェック」への追加対策。private fieldsによる内部状態の
  // 完全な不可視化、.prototypeの不在(class構文のメソッドは非コンストラクタ
  // 関数になるため)、Function.prototype.toString()の偽装を検証する。
  // ============================================================

  await run('no internal state leaks via Object.keys()/getOwnPropertyNames() on navigator.usb', async () => {
    const { navigator } = makeSandbox(() => ({}));
    assert.deepStrictEqual(Object.keys(navigator.usb), []);
    // getOwnPropertyNames()はenumerable:falseなものも拾うので、より厳しい確認になる。
    // #フィールドは真のプライベートなので、これにも一切出てこないはず。
    const ownNames = Object.getOwnPropertyNames(navigator.usb);
    assert.ok(!ownNames.some((n) => n.includes('onconnect') || n.includes('ondisconnect') || n.startsWith('#')));
  });

  await run('no internal state leaks via Object.keys()/getOwnPropertyNames() on a USBDevice instance', async () => {
    const { navigator } = makeSandbox(() => ({ devices: [SIMPLE_DEVICE] }));
    const [device] = await navigator.usb.getDevices();
    const keys = Object.keys(device).sort();
    // 仕様どおりの読み取り専用属性だけが出るべきで、handle/opened/
    // claimedInterfaces等の内部実装詳細は一切出てはいけない。
    const expected = [
      'configurations', 'deviceClass', 'deviceProtocol', 'deviceSubclass',
      'deviceVersionMajor', 'deviceVersionMinor', 'deviceVersionSubminor',
      'manufacturerName', 'productId', 'productName', 'serialNumber',
      'usbVersionMajor', 'usbVersionMinor', 'usbVersionSubminor', 'vendorId',
    ].sort();
    assert.deepStrictEqual(keys, expected);
    const ownNames = Object.getOwnPropertyNames(device);
    assert.ok(!ownNames.some((n) => n.includes('handle') || n.includes('claimed') || n.includes('Alternate') || n.startsWith('#')));
  });

  await run('exposed methods have no .prototype property (matching native, non-constructible operations)', async () => {
    const { navigator } = makeSandbox(() => ({ devices: [SIMPLE_DEVICE] }));
    assert.strictEqual(navigator.usb.getDevices.prototype, undefined);
    assert.strictEqual(navigator.usb.requestDevice.prototype, undefined);
    const [device] = await navigator.usb.getDevices();
    assert.strictEqual(device.open.prototype, undefined);
    assert.strictEqual(device.transferIn.prototype, undefined);
  });

  await run('exposed methods are not constructible (new x() throws, matching native operations)', async () => {
    const { navigator } = makeSandbox(() => ({}));
    assert.throws(() => new navigator.usb.getDevices(), TypeError);
    assert.throws(() => new navigator.usb.requestDevice(), TypeError);
  });

  await run('Function.prototype.toString() on exposed methods reports as native code', async () => {
    const { navigator } = makeSandbox(() => ({ devices: [SIMPLE_DEVICE] }));
    assert.strictEqual(navigator.usb.getDevices.toString(), 'function getDevices() { [native code] }');
    assert.strictEqual(navigator.usb.requestDevice.toString(), 'function requestDevice() { [native code] }');
    assert.strictEqual(String(navigator.usb.getDevices), 'function getDevices() { [native code] }');
    const [device] = await navigator.usb.getDevices();
    assert.strictEqual(device.open.toString(), 'function open() { [native code] }');
    assert.strictEqual(device.transferIn.toString(), 'function transferIn() { [native code] }');
    // addEventListener/removeEventListenerには一切手を加えておらず、EventTarget.prototype
    // から継承したものをそのまま使っている(前の "inherits the real ..." テストで確認済み)。
    // そのためこれらの.toString()結果は実ブラウザのEventTarget実装がそのまま出るだけで、
    // fox-webusb側のコードには依存しない——Node自身のEventTargetは(実ブラウザと違い)
    // 純粋なJS実装なので、ここでは意図的に検証対象から外している。
  });

  await run('toString-spoofing proxy is fully transparent to normal calls (this-binding, args, return value)', async () => {
    const captured = [];
    const { navigator } = makeSandbox((method, params) => {
      captured.push([method, params]);
      if (method === 'listDevices') return { devices: [SIMPLE_DEVICE] };
      if (method === 'openDevice') return { success: true, handle: 42 };
      throw new Error('unexpected method ' + method);
    });
    const [device] = await navigator.usb.getDevices();
    // メソッドを変数へ取り出してから呼んでも(=thisを明示的に渡しても)正しく動くこと
    const openFn = device.open;
    await openFn.call(device);
    assert.strictEqual(device.opened, true);
  });

  await run('method arity (.length) matches the WebIDL operation signature', async () => {
    const { navigator } = makeSandbox(() => ({ devices: [SIMPLE_DEVICE] }));
    assert.strictEqual(navigator.usb.getDevices.length, 0);
    assert.strictEqual(navigator.usb.requestDevice.length, 1);
  });


})();
