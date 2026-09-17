// fox-webusb-extensions-negative-check.ts
// =========================================
// fox-webusb-extensions-sample-usage.ts が「正しい使い方が通ること」を
// 確認するのに対し、こちらは「間違った使い方がちゃんと型エラーになること」
// を確認する。README.md参照。

/// <reference path="./fox-webusb-extensions.d.ts" />

async function foxWebUsbExtensionsNegativeChecks(): Promise<void> {
  if (!window.__foxWebUSB) return;
  const { attestation } = window.__foxWebUSB.extensions;

  // sign()はBufferSource(ArrayBuffer/TypedArray)を要求する。文字列は不可
  // (「challengeは自分でランダム生成したバイト列を渡す」設計であり、
  // 文字列を暗黙にUTF-8エンコードする、といった魔法は無い)。
  // @ts-expect-error
  await attestation.sign('not a byte array');

  // @ts-expect-error
  await attestation.sign(123);

  // getPublicKey()は引数を取らない。
  // @ts-expect-error
  await attestation.getPublicKey('unexpected argument');

  // bridgeInfo()の戻り値は読み取り専用(readonly)。書き換え不可。
  const info = await window.__foxWebUSB.bridgeInfo();
  // @ts-expect-error
  info.bridgeVersion = '9.9.9';
  // @ts-expect-error
  info.transferLimits.bulkTransferMaxLength = 0;

  // extensions自体もreadonly(差し替え不可)。
  // @ts-expect-error
  window.__foxWebUSB.extensions = { attestation: attestation };
}

void foxWebUsbExtensionsNegativeChecks();
