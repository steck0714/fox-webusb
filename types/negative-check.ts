// negative-check.ts
// ==================
// sample-usage.ts が「正しい使い方が通ること」を確認するのに対し、こちらは
// 「間違った使い方がちゃんと型エラーになること」を確認する。各行の
// `// @ts-expect-error` は「次の行は型エラーになるはずだ」という表明で、
// もし実際にはエラーにならなかった場合はts-expect-error自身がエラーに
// なる(=このファイルは「意図したエラーが本当に起きているか」ごと
// tscでチェックできる)。`npx tsc --noEmit --strict negative-check.ts`
// がエラー無く通ることを確認している。

/// <reference path="./webusb-polyfill.d.ts" />

async function negativeChecks(): Promise<void> {
  // requestDevice()はfiltersを含むオブジェクトを要求する(素の配列や省略は不可)
  // @ts-expect-error
  await navigator.usb.requestDevice();
  // @ts-expect-error
  await navigator.usb.requestDevice([{ vendorId: 1 }]);

  const device = await navigator.usb.requestDevice({ filters: [{}] });

  // vendorId/productIdはnumber。文字列は不可。
  // @ts-expect-error
  await navigator.usb.requestDevice({ filters: [{ vendorId: '0x2341' }] });

  // claimInterface()はnumberを要求する(文字列不可)
  // @ts-expect-error
  await device.claimInterface('0');

  // transferOut()の第2引数はBufferSource(ArrayBuffer/TypedArray)。素の配列は不可。
  // @ts-expect-error
  await device.transferOut(1, [1, 2, 3, 4]);

  // controlTransferIn()のrequestTypeは規定の4値のみ。任意の文字列は不可。
  // @ts-expect-error
  await device.controlTransferIn({ requestType: 'weird', recipient: 'device', request: 0, value: 0, index: 0 }, 8);

  // recipientも同様に規定の4値のみ。
  // @ts-expect-error
  await device.controlTransferIn({ requestType: 'standard', recipient: 'nope', request: 0, value: 0, index: 0 }, 8);

  // clearHalt()のdirectionは'in'|'out'のみ。
  // @ts-expect-error
  await device.clearHalt('sideways', 1);

  // 読み取り専用プロパティへの代入は不可。
  // @ts-expect-error
  device.vendorId = 0x9999;
  // @ts-expect-error
  device.opened = true;

  // addEventListener()の第1引数は'connect'|'disconnect'(その他の任意文字列は
  // 汎用オーバーロード側に落ちてEventListenerOrEventListenerObjectを要求するため、
  // 第2引数にUSBConnectionEvent固有のdeviceプロパティを期待する関数は渡せない)。
  // @ts-expect-error
  navigator.usb.addEventListener('connect', (event: { device: { vendorId: string } }) => { void event; });

  // isochronousTransferIn()のpacketLengthsはnumber[]。文字列配列は不可。
  // @ts-expect-error
  await device.isochronousTransferIn(1, ['8', '8']);
}

void negativeChecks;
