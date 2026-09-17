// Type definitions for `window.__foxWebUSB` -- the fox-webusb-specific
// debug helper AND (under `.extensions`) the stable, mock-webusb-family-only
// capability surface that a site's own code may feature-detect and use.
//
// 🛡️ Deliberately kept in a separate file from webusb-polyfill.d.ts: that
// file describes the shared, spec-shaped `navigator.usb` surface that is
// byte-for-byte identical across pyside6-webusb/tauri-webusb/fox-webusb (see
// its header comment). `window.__foxWebUSB` is NOT part of that shared
// surface -- `window.__pysideWebUSB` (pyside6-webusb) currently exposes only
// `listGrantedDevices`/`bridgeInfo`/`explainTransferLimits`, without the
// `extensions.attestation` capability documented here, which is fox-webusb's
// own addition as of v0.0.0a1. Consult each project's own README before
// assuming feature parity.
//
// None of this exists on real Chrome's `navigator.usb`. Always feature-detect
// (`typeof window.__foxWebUSB !== 'undefined'`) before relying on it -- code
// written against these types will simply not run under real Chrome, or
// under an origin that Permissions Policy has denied the `usb` feature to
// (see README.md, "アーキテクチャ" / "二重サーフェス").

interface FoxWebUsbTransferLimits {
  readonly bulkTransferMaxLength: number;
  readonly controlTransferMaxLength: number;
}

interface FoxWebUsbBridgeInfo {
  readonly available: true;
  readonly bridgeVersion: string;
  readonly rustAccelerated: boolean;
  readonly transferLimits: FoxWebUsbTransferLimits;
}

interface FoxWebUsbGrantedDeviceRow {
  readonly vendorId: string; // e.g. "0x2341" -- pre-formatted for console.table(), not a parseable number
  readonly productId: string;
  readonly productName: string | null;
  readonly manufacturerName: string | null;
  readonly serialNumber: string | null;
  readonly opened: boolean;
}

/**
 * Local attestation (Ed25519, RFC 8032). An origin-scoped, TOFU-style
 * capability that lets a site prove "this response came from the same local
 * bridge instance as before" -- something real Chrome's WebUSB has no
 * equivalent for. See `native-host/src/fox_webusb_host/attestation.py`
 * (fox-webusb) for the full design rationale and its stated limits.
 *
 * The key pair is derived independently per calling origin: two different
 * origins calling `getPublicKey()` will always see two different, otherwise
 * unlinkable keys. Do not build a cross-origin identity scheme on top of
 * this -- that would defeat the point of the per-origin isolation.
 */
interface FoxWebUsbAttestation {
  /** Resolves true if the optional `cryptography` dependency is installed on the native host and this feature is actually usable; false (never rejects) otherwise. */
  isSupported(): Promise<boolean>;
  /** The calling origin's Ed25519 public key (32 raw bytes), generating one on first call. Safe to persist and share -- it is, by definition, public. */
  getPublicKey(): Promise<Uint8Array>;
  /**
   * Signs `challenge` with the calling origin's private key and returns the
   * 64-byte Ed25519 signature. Pass a fresh, unpredictable nonce you
   * generated yourself (e.g. via `crypto.getRandomValues`) -- reusing a
   * fixed challenge defeats the point of a challenge-response scheme.
   * Rejects with a real `TypeError` if `challenge` is larger than the host's
   * configured limit (4096 bytes as of v0.0.0a1).
   */
  sign(challenge: BufferSource): Promise<Uint8Array>;
}

interface FoxWebUsbExtensions {
  readonly attestation: FoxWebUsbAttestation;
}

interface FoxWebUsbDebugHelper {
  /** Fetches `navigator.usb.getDevices()` for the calling origin and additionally pretty-prints it via `console.table()`. Discloses nothing `getDevices()` itself didn't already. */
  listGrantedDevices(): Promise<FoxWebUsbGrantedDeviceRow[]>;
  /** Version/capability info for the bridge currently backing this page's `navigator.usb`. The "F12 version check" helper -- open DevTools and call `__foxWebUSB.bridgeInfo()`. */
  bridgeInfo(): Promise<FoxWebUsbBridgeInfo>;
  /** Logs and returns the current transfer-size policy. */
  explainTransferLimits(): Promise<FoxWebUsbTransferLimits>;
  /** Stable, mock-webusb-family-only capabilities a site's own code (not just DevTools) may build against. Always feature-detect before use. */
  readonly extensions: FoxWebUsbExtensions;
}

interface Window {
  __foxWebUSB?: FoxWebUsbDebugHelper;
}
