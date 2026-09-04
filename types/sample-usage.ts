// sample-usage.ts
// ================
// webusb-polyfill.d.ts が実際のアプリコードから使い物になる形をしているかを
// 型チェックだけで確認するための例。`npx tsc --noEmit --strict sample-usage.ts`
// がエラー無く通ることを CI/手元検証で確認している(tests/README.md参照)。
// このファイル自体は実行されない(型チェック専用)。

/// <reference path="./webusb-polyfill.d.ts" />

async function connectAndBlink(): Promise<void> {
  if (!navigator.usb) {
    throw new Error('navigator.usb is not available in this browser');
  }

  const device = await navigator.usb.requestDevice({
    filters: [{ vendorId: 0x2341 }], // Arduino
  });

  console.log(device.productName, device.manufacturerName, device.serialNumber);

  await device.open();
  if (device.configuration === null) {
    await device.selectConfiguration(device.configurations[0].configurationValue);
  }
  await device.claimInterface(0);

  for (const iface of device.configuration!.interfaces) {
    for (const ep of iface.alternate.endpoints) {
      console.log(`endpoint ${ep.endpointNumber} ${ep.direction} ${ep.type} (${ep.packetSize} bytes)`);
    }
  }

  const outResult = await device.transferOut(1, new Uint8Array([0x01, 0x00]));
  console.log('wrote', outResult.bytesWritten, 'bytes, status', outResult.status);

  const inResult = await device.transferIn(1, 64);
  const bytes = new Uint8Array(inResult.data.buffer, inResult.data.byteOffset, inResult.data.byteLength);
  console.log('read', bytes.length, 'bytes, status', inResult.status);

  const status = await device.controlTransferIn(
    { requestType: 'standard', recipient: 'device', request: 0x00, value: 0, index: 0 },
    2,
  );
  void status;

  const isoResult = await device.isochronousTransferIn(1, [8, 8, 8]);
  for (const packet of isoResult.packets) {
    console.log(packet.data.byteLength, packet.status);
  }

  await device.reset();
  await device.releaseInterface(0);
  await device.close();
}

function watchForHotplug(): void {
  const onConnect = (event: USBConnectionEvent) => {
    console.log('connected:', event.device.productName);
  };
  const onDisconnect = (event: USBConnectionEvent) => {
    console.log('disconnected:', event.device.productName);
  };
  navigator.usb.addEventListener('connect', onConnect);
  navigator.usb.addEventListener('disconnect', onDisconnect);
  // 型どおりに後始末もできることの確認
  navigator.usb.removeEventListener('connect', onConnect);
  navigator.usb.removeEventListener('disconnect', onDisconnect);
}

async function forgetADevice(): Promise<void> {
  const [device] = await navigator.usb.getDevices();
  if (device) await device.forget();
}

async function clearAStall(): Promise<void> {
  const [device] = await navigator.usb.getDevices();
  await device.open();
  await device.clearHalt('in', 1);
  await device.close();
}

void connectAndBlink;
void watchForHotplug;
void forgetADevice;
void clearAStall;
