/*
 * test_page_polyfill.js
 * ======================
 * page_polyfill.js を実際のFirefox無しにNodeで動かして検証する。
 * window.postMessage()をイベントループ的にエミュレートし、その中で
 * 'toContent'方向のメッセージを見つけたら、テストごとに用意した
 * フェイクのcontent_script/background/ネイティブホストの振る舞い
 * (mockDispatch)へ回して結果を'toPage'として投げ返す——これにより、
 * 実際のpage_polyfill.jsのコード(callBridge、OpenWebUSBDevice、
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
    btoa: global.btoa, atob: global.atob,
    Uint8Array, Int8Array, DataView, ArrayBuffer, TextEncoder, TextDecoder,
    Promise, Object, Array, JSON, Math, Error, TypeError, RangeError, String, Number, Boolean,
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
    const { navigator } = makeSandbox(() => ({ devices: [SIMPLE_DEVICE] }));
    const [device] = await navigator.usb.getDevices();
    device._opened = true; // requireOpen()を通すためのテスト用の直接操作
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
    assert.strictEqual(result.packets[0].length, 4);
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
})();
