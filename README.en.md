# fox-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **Experimental (v0.0.0)**: The core implementation connecting down to actual USB communication is complete. However, this is an initial pre-release and has **not yet been verified with physical USB devices**. Use with caution.

## About

`fox-webusb` is an experimental Firefox-oriented implementation of [Mock-webusb](https://github.com/steck0714/Mock-webusb), created to provide a WebUSB-compatible API in environments where native WebUSB may not be available.

Unlike purely visual or superficial polyfills, `fox-webusb` is designed to handle the pipeline down to actual underlying USB communication.

The project uses a Firefox WebExtension and Native Messaging to connect the JavaScript API to a native USB backend.

```text
Web Page
    │
    │ navigator.usb
    ▼
Firefox Extension
    │
    │ Native Messaging
    ▼
Native Host
    │
    │ PyUSB / libusb
    ▼
USB Device
```

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

> The example above demonstrates the JavaScript API surface. Native host setup and Firefox extension installation are required for actual USB communication.

## API

`fox-webusb` provides a WebUSB-compatible API surface centered around `navigator.usb`.

The implementation includes WebUSB-style objects such as:

```text
navigator.usb
USB
USBDevice
USBConfiguration
USBInterface
USBAlternateInterface
USBEndpoint
USBConnectionEvent
USBInTransferResult
USBOutTransferResult
USBIsochronousInTransferResult
USBIsochronousOutTransferResult
USBIsochronousInTransferPacket
```

The implementation aims to reproduce the observable behavior and structure of the WebUSB API where practical.

It is **not** a copy of Chromium's internal WebUSB implementation.

## Architecture

```text
┌──────────────────────────┐
│        Web Page          │
│                          │
│      navigator.usb       │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│   Firefox WebExtension   │
│                          │
│  Page Polyfill           │
│  Content Script          │
│  Background Script       │
└────────────┬─────────────┘
             │
             │ Native Messaging
             ▼
┌──────────────────────────┐
│      Native Host         │
│                          │
│  Python / Protocol       │
│  USB Bridge              │
│  Security Checks         │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│      PyUSB / libusb      │
└────────────┬─────────────┘
             │
             ▼
        USB Device
```

## Native Messaging

`fox-webusb` uses Firefox Native Messaging to communicate between the extension and the native USB backend.

```text
Firefox Extension
        │
        │ Native Messaging
        ▼
   Native Host
        │
        ▼
   USB Backend
```

The native host is responsible for operations that cannot be performed directly from ordinary WebExtension JavaScript.

On Windows, standard input/output streams are explicitly configured for binary mode to avoid problems caused by text-mode stream processing.

Incoming native messages are also subject to size limits and protocol validation.

## USB Communication

The project is designed to reach the underlying USB communication layer rather than only returning simulated device objects.

The backend can handle operations including:

- USB device enumeration
- Device opening and closing
- Configuration handling
- Interface handling
- Control transfers
- Bulk transfers
- Interrupt transfers
- Isochronous transfers

Some transfer behavior depends on the capabilities and semantics of the underlying PyUSB/libusb backend.

In particular, isochronous transfer behavior may not be identical to a native browser WebUSB implementation.

## Security

Because `fox-webusb` can reach native USB functionality, security restrictions are part of the implementation.

The project includes checks and restrictions around areas such as:

- Secure contexts
- User activation
- Origin handling
- Trusted extension-side operations
- Protected USB interface classes
- Security-sensitive USB devices
- Native Messaging input validation

The extension does not treat arbitrary USB access as unrestricted.

Security behavior may change as the project continues to be tested and developed.

## Current Status & Roadmap

- [x] Create repository
- [x] Technical research & design
- [x] Implement initial mock logic
- [x] Minimal working demo
- [x] Firefox extension implementation
- [x] Native Messaging integration
- [x] Python USB backend
- [x] Core pipeline reaching actual USB communication
- [x] API-shape improvements
- [x] Automated tests
- [ ] Physical device verification & hardware testing 🧪
- [ ] Broader hardware compatibility testing
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

Although the projects share implementation history, `fox-webusb` has its own Firefox-oriented architecture and runtime environment.

## Difference from Chromium WebUSB

`fox-webusb` should not be considered a Chromium WebUSB implementation.

The architecture is different:

```text
Chromium WebUSB

Web Page
    │
    ▼
Chromium WebUSB
    │
    ▼
Browser USB Backend
    │
    ▼
USB Device
```

```text
fox-webusb

Web Page
    │
    ▼
Firefox WebExtension
    │
    ▼
Native Messaging
    │
    ▼
Python / PyUSB / libusb
    │
    ▼
USB Device
```

The goal is to provide a compatible WebUSB API surface in Firefox-oriented environments, not to reproduce Chromium's internal implementation.

## Difference from pyside6-webusb

`fox-webusb` shares implementation history and concepts with `pyside6-webusb`, but it is not simply a direct copy.

The runtime environment is different:

```text
pyside6-webusb
    │
    ▼
PySide6 / Qt
    │
    ▼
Python USB Backend
    │
    ▼
USB Device
```

```text
fox-webusb
    │
    ▼
Firefox WebExtension
    │
    ▼
Native Messaging
    │
    ▼
Python USB Backend
    │
    ▼
USB Device
```

The Firefox implementation therefore requires additional components for browser-extension communication and native-host integration.

## Testing

The project includes automated tests for multiple parts of the implementation.

```text
Python Tests
    │
    ├── Protocol
    ├── Bridge
    ├── Security
    └── USB-related logic

Node.js Tests
    │
    └── WebUSB API behavior

Rust Tests
    │
    └── Native acceleration components
```

Automated tests do not replace physical USB device testing.

Compatibility with real USB hardware remains an ongoing area of verification.

## Important Notice

This project is experimental software.

Some code may have been generated or assisted by AI. The implementation may therefore contain bugs or limitations and may not work correctly in every environment.

Physical USB device testing has not yet been completed.

Hardware compatibility, browser behavior, and edge cases may differ from native WebUSB implementations.

Use this project for experimentation and development with appropriate caution.

## Credits & License

Derived from [steck0714/Mock-webusb](https://github.com/steck0714/Mock-webusb).

Licensed under the MIT License.
