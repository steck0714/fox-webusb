// fox-webusb-extensions-sample-usage.ts
// =======================================
// fox-webusb-extensions.d.ts が実際のアプリコードから使い物になる形をして
// いるかを型チェックだけで確認するための例。`npx tsc --noEmit --strict
// fox-webusb-extensions.d.ts fox-webusb-extensions-sample-usage.ts` が
// エラー無く通ることをCI/手元検証で確認している(README.md参照)。
// このファイル自体は実行されない(型チェック専用)。

/// <reference path="./fox-webusb-extensions.d.ts" />

async function checkBridgeVersion(): Promise<void> {
  // 実Chrome上ではwindow.__foxWebUSB自体が存在しないため、常に機能検出
  // してから使う。
  if (!window.__foxWebUSB) {
    console.log('not running under fox-webusb (or a sibling mock-webusb implementation)');
    return;
  }

  const info = await window.__foxWebUSB.bridgeInfo();
  console.log(`fox-webusb ${info.bridgeVersion}, rustAccelerated=${info.rustAccelerated}`);
  console.log(`bulk limit: ${info.transferLimits.bulkTransferMaxLength} bytes`);

  const rows = await window.__foxWebUSB.listGrantedDevices();
  for (const row of rows) {
    console.log(row.vendorId, row.productId, row.productName, row.opened);
  }
}

// TOFU (trust-on-first-use) local attestation flow: enroll a public key on
// first visit, then verify a fresh challenge signature on later visits.
async function enrollAttestationKey(): Promise<Uint8Array | null> {
  const attestation = window.__foxWebUSB?.extensions.attestation;
  if (!attestation || !(await attestation.isSupported())) return null;
  return attestation.getPublicKey();
}

async function proveSameBridgeInstance(storedPublicKey: Uint8Array): Promise<boolean> {
  const attestation = window.__foxWebUSB?.extensions.attestation;
  if (!attestation) return false;

  const challenge = crypto.getRandomValues(new Uint8Array(32));
  const signature = await attestation.sign(challenge);

  // Verification itself happens wherever you like -- a server, or here via
  // Web Crypto's Ed25519 support -- this file only checks that the .d.ts
  // shapes are usable, not that verification succeeds.
  // (`.slice()` normalizes to a plain ArrayBuffer-backed view -- newer
  // TypeScript DOM lib versions distinguish `Uint8Array<ArrayBufferLike>`
  // from `BufferSource`'s more specific `ArrayBufferView<ArrayBuffer>`,
  // which is unrelated to this project's own types.)
  const key = await crypto.subtle.importKey('raw', storedPublicKey.slice(), { name: 'Ed25519' }, false, ['verify']);
  return crypto.subtle.verify('Ed25519', key, signature.slice(), challenge.slice());
}

void checkBridgeVersion();
void enrollAttestationKey();
void proveSameBridgeInstance(new Uint8Array(32));
