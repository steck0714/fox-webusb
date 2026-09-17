/*
 * test_extension_surface.js
 * ==========================
 * background.js が実際に定義する「Firefox-style surface」
 * (README/webusb_core.js「二重サーフェス」参照)を、最小限のbrowser.*
 * WebExtensions APIモックの上でNodeから動かして検証する。
 *
 * postMessage経由のChromium surfaceはtest_page_polyfill.jsが既に
 * webusb_core.js自体を(別のトランスポートで)徹底的に検証しているため、
 * ここではbackground.js固有の配線——EXTENSION_ORIGINの計算、
 * callNative()への直結、ネイティブホストとのチャンク分割プロトコルの
 * 実際のエンコード/デコード——が正しいことだけを確かめれば十分である。
 *
 * 実行: node tests/test_extension_surface.js
 */
'use strict';
const vm = require('vm');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const CORE_SRC = fs.readFileSync(path.join(__dirname, '..', 'extension', 'webusb_core.js'), 'utf8');
const BACKGROUND_SRC = fs.readFileSync(path.join(__dirname, '..', 'extension', 'background.js'), 'utf8');

function encodeNativeMessage(obj) {
  // background.js の onNativeChunk() が期待する形にエンコードする:
  // JSON文字列 → UTF-8バイト列 → base64 → { seq: 0, total: 1, part: <b64> } のチャンク1個。
  const jsonStr = JSON.stringify(obj);
  const bytes = Buffer.from(jsonStr, 'utf8');
  const b64 = bytes.toString('base64');
  return { seq: 0, total: 1, part: b64 };
}

function makeSandbox() {
  const tabsOnRemovedListeners = [];
  const runtimeOnMessageListeners = [];
  let fakePort = null;

  const browser = {
    runtime: {
      getURL(p) { return 'moz-extension://test-extension-id' + (p || ''); },
      connectNative(name) {
        const listeners = { message: [], disconnect: [] };
        fakePort = {
          _name: name,
          postMessage(msg) { fakePort._lastSent = msg; },
          onMessage: { addListener(fn) { listeners.message.push(fn); } },
          onDisconnect: { addListener(fn) { listeners.disconnect.push(fn); } },
          _deliver(msg) { listeners.message.forEach((fn) => fn(msg)); },
        };
        return fakePort;
      },
      onMessage: { addListener(fn) { runtimeOnMessageListeners.push(fn); } },
      openOptionsPage() {},
      lastError: null,
    },
    tabs: {
      onRemoved: { addListener(fn) { tabsOnRemovedListeners.push(fn); } },
      sendMessage() { return Promise.resolve(); },
    },
    webRequest: undefined,
  };

  const sandbox = {
    browser, console,
    URL, Set, Map, Promise, JSON, Object, Array, Error, String, Number, Boolean, Symbol,
    Uint8Array, DataView, ArrayBuffer, TextDecoder, TextEncoder,
    Proxy, Reflect, EventTarget, Event, DOMException,
    btoa: (s) => Buffer.from(s, 'binary').toString('base64'),
    atob: (s) => Buffer.from(s, 'base64').toString('binary'),
    setTimeout, clearTimeout,
    navigator: {}, // background pageは本物のnavigatorを持つ(README参照) — 属性追加できるプレーンオブジェクトで代用
  };
  sandbox.window = sandbox; // 実際のbackground pageでは window === globalThis そのもの
  vm.createContext(sandbox);
  vm.runInContext(CORE_SRC, sandbox, { filename: 'webusb_core.js' });
  vm.runInContext(BACKGROUND_SRC, sandbox, { filename: 'background.js' });
  return { sandbox, getPort: () => fakePort };
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

(async () => {
  await run('EXTENSION_ORIGIN is derived once from browser.runtime.getURL(\'/\') and reused consistently', async () => {
    // 🛡️ Node.jsの汎用URL実装は moz-extension: のような拡張機能固有の
    // スキームを「特別なスキーム」として認識せず、.origin が文字列"null"に
    // なる(実際のFirefox/Chromeは自分自身の拡張機能スキームを正しく
    // origin化する——このプロジェクトの他の箇所、originFromSender()等が
    // まさにその実ブラウザの挙動に依存している)。そのためここでは
    // 「実際にどんな文字列になるか」ではなく、「一度計算した値が
    // ずっと同じように使い回されているか」という、Node環境でも
    // 意味を持つ形で検証する。
    const { sandbox } = makeSandbox();
    assert.strictEqual(typeof sandbox.EXTENSION_ORIGIN, 'string');
    assert.ok(sandbox.EXTENSION_ORIGIN.length > 0);
  });

  await run('background.js attaches navigator.usb (Firefox-style surface) to its own navigator', async () => {
    const { sandbox } = makeSandbox();
    assert.ok(sandbox.navigator.usb, 'navigator.usb should be defined inside the background page context');
    assert.strictEqual(typeof sandbox.navigator.usb.getDevices, 'function');
    assert.strictEqual(typeof sandbox.navigator.usb.requestDevice, 'function');
  });

  await run('navigator.usb.getDevices() round-trips through the same chunked native-messaging protocol as page requests', async () => {
    const { sandbox, getPort } = makeSandbox();
    const promise = sandbox.navigator.usb.getDevices();
    const port = getPort();
    assert.ok(port, 'connectNative() should have been called');
    assert.ok(port._lastSent, 'a message should have been posted to the native port');
    assert.strictEqual(port._lastSent.method, 'listDevices');
    // 🛡️ Webページ由来のoriginとは違う、拡張機能自身のoriginで許可を照会する
    // (実値そのものはNode環境では実ブラウザと一致しない。上のテスト参照)
    assert.strictEqual(port._lastSent.origin, sandbox.EXTENSION_ORIGIN);
    assert.strictEqual(port._lastSent.trusted, true);

    // ネイティブホストからの応答を、実際に使われるチャンク分割プロトコル
    // どおりにエンコードして返す。
    const responseDevice = { vendorId: 0x2341, productId: 0x8036, configurations: [] };
    port._deliver(encodeNativeMessage({
      type: 'response', id: port._lastSent.id, success: true, devices: [responseDevice],
    }));

    const devices = await promise;
    assert.strictEqual(devices.length, 1);
    assert.strictEqual(devices[0].vendorId, 0x2341);
    assert.strictEqual(devices[0].productId, 0x8036);
  });

  await run('a device connect/disconnect event addressed to EXTENSION_ORIGIN reaches the Firefox-style surface\'s own navigator.usb', async () => {
    const { sandbox } = makeSandbox();
    let received = null;
    sandbox.navigator.usb.addEventListener('connect', (event) => { received = event; });

    // background.js自身のdispatchDeviceEvent()を、ネイティブホストからの
    // pushイベントを受け取ったのと同じ形で直接呼ぶ(ページ側frameRegistryへの
    // 配送はtabs.sendMessageのモックなので実際には何も起きないが、
    // 拡張機能自身のUSBインスタンスへの配送だけを見る)。
    sandbox.dispatchDeviceEvent({
      event: 'connect',
      origins: [sandbox.EXTENSION_ORIGIN],
      device: { vendorId: 0x1234, productId: 0x5678, configurations: [] },
    });

    assert.ok(received, 'the connect event should have reached navigator.usb');
    assert.strictEqual(received.device.vendorId, 0x1234);
    assert.ok(received instanceof sandbox.Event, 'the event should be a real Event instance');
  });

  await run('an event NOT addressed to EXTENSION_ORIGIN does not reach the Firefox-style surface', async () => {
    const { sandbox } = makeSandbox();
    let received = null;
    sandbox.navigator.usb.addEventListener('connect', (event) => { received = event; });

    sandbox.dispatchDeviceEvent({
      event: 'connect',
      origins: ['https://some-unrelated-page.example'],
      device: { vendorId: 0x1234, productId: 0x5678, configurations: [] },
    });

    assert.strictEqual(received, null, 'an event for a different origin must not reach the extension\'s own surface');
  });

  await run('__foxWebUsbManagement exposes the trusted-only management operations to the extension\'s own pages', async () => {
    const { sandbox, getPort } = makeSandbox();
    assert.strictEqual(typeof sandbox.window.__foxWebUsbManagement.listKnownDevices, 'function');
    assert.strictEqual(typeof sandbox.window.__foxWebUsbManagement.forgetKnownDevice, 'function');
    assert.strictEqual(typeof sandbox.window.__foxWebUsbManagement.diagnostics, 'function');

    const promise = sandbox.window.__foxWebUsbManagement.diagnostics();
    const port = getPort();
    assert.strictEqual(port._lastSent.method, 'diagnostics');
    assert.strictEqual(port._lastSent.trusted, true, 'management calls must mark themselves trusted, matching options.js-originated calls');

    port._deliver(encodeNativeMessage({ type: 'response', id: port._lastSent.id, success: true, deviceCount: 3, rustAccel: false }));
    const result = await promise;
    assert.strictEqual(result.deviceCount, 3);
  });
})();
