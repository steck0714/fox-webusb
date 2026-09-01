# fox-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **Experimental (v0.0.0)**: The core implementation connecting down to actual USB communication is complete. However, this is an initial pre-release and has **not yet been verified with physical USB devices**. Use with caution.

## About

`fox-webusb` is an experimental Firefox-oriented implementation of [Mock-webusb](https://github.com/steck0714/Mock-webusb), created to provide a WebUSB-compatible API in environments where native WebUSB may not be available.

Unlike purely visual or superficial polyfills, `fox-webusb` is designed to handle the pipeline down to actual underlying USB communication.

## Quick Start (v0.0.0)

Once the `fox-webusb` polyfill is loaded, it provides the standard `navigator.usb` interface:

```html
<script src="https://jsdelivr.net"></script>

<script>
(async () => {
  if (!navigator.usb) {
    throw new Error("fox-webusb is not initialized");
  }

  console.log("fox-webusb:", navigator.usb);

  const devices = await navigator.usb.getDevices();
  console.log("USB devices:", devices);
})();
</script>
```

## Current Status & Roadmap

- [x] Create repository
- [x] Technical research & design
- [x] Implement initial mock logic
- [x] Minimal working demo
- [x] Core pipeline reaching actual USB communication
- [ ] Physical device verification & hardware testing 🧪
- [ ] API stabilization

## Relationship with Mock-webusb

```text
Mock-APIs
    │
    └── Mock-webusb
          │
          └── fox-webusb
```

`fox-webusb` is an implementation derived from the Mock-webusb project and is developed as a separate project for Firefox-oriented environments.

## ⚠️ Important Notice

This project is experimental software.

Some code may have been generated or assisted by AI. The implementation may therefore contain bugs or limitations and may not work correctly in every environment.

Physical USB device testing has not yet been completed.

## Credits & License

Derived from [steck0714/Mock-webusb](https://github.com/steck0714/Mock-webusb).

Licensed under the MIT License.