# fox-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

> ⚠️ **Experimental Alpha — v0.0.0a**
>
> `fox-webusb` is an experimental, unofficial WebUSB-compatible implementation for Firefox-oriented environments.
>
> It connects a WebUSB-style JavaScript API pipeline to a native USB backend. The project is still in an early alpha stage, and hardware compatibility is being actively verified.

## About

`fox-webusb` is an experimental Firefox-oriented implementation derived from ideas and implementation history associated with Mock-webusb.

The goal is to provide a WebUSB-compatible API surface in environments where Firefox does not provide a native `navigator.usb` implementation.

This project does not attempt to reproduce Chromium's internal WebUSB implementation. Instead, it builds an alternative architecture around Firefox WebExtensions and Native Messaging.

```text
Web Page
    │
    │ navigator.usb
    ▼
Firefox WebExtension
    │
    │ Native Messaging
    ▼
Native Host
    │
    │ Python USB Backend
    ▼
PyUSB / libusb
    │
    ▼
USB Device
```

The project goes beyond a visual API polyfill and aims to connect WebUSB-style JavaScript operations to an underlying USB communication backend.

## Why fox-webusb?

Firefox does not provide a native `navigator.usb` implementation.

`fox-webusb` explores whether a WebUSB-compatible API can be provided through:

- Firefox WebExtensions
- page-side JavaScript injection
- content-script messaging
- background-script coordination
- Firefox Native Messaging
- a native USB backend

This makes `fox-webusb` both a WebUSB compatibility project and an architectural experiment.

# Architecture

```text
┌──────────────────────────────┐
│          Web Page            │
│                              │
│       navigator.usb          │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│      Firefox WebExtension    │
│                              │
│  • Page Polyfill             │
│  • Content Script            │
│  • Background Script         │
│  • Extension UI              │
└──────────────┬───────────────┘
               │
               │ Native Messaging
               ▼
┌──────────────────────────────┐
│         Native Host          │
│                              │
│  • Protocol                  │
│  • USB Bridge                │
│  • Permission Handling       │
│  • Security Checks           │
│  • Device Chooser            │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│       PyUSB / libusb         │
└──────────────┬───────────────┘
               │
               ▼
          USB Device
```

Unlike a browser-native implementation, multiple components cooperate to expose the API. The web page itself does not communicate directly with the USB backend.

# API

`fox-webusb` exposes a WebUSB-compatible API centered around:

```javascript
navigator.usb
```

The implementation uses WebUSB-style objects such as:

```text
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

The goal is to reproduce the observable API shape and behavior of WebUSB where practical.

Example:

```javascript
if (!navigator.usb) {
    throw new Error("fox-webusb is not initialized");
}

const devices = await navigator.usb.getDevices();

console.log("Authorized USB devices:", devices);
```

Device selection follows a familiar WebUSB-style flow:

```javascript
const device = await navigator.usb.requestDevice({
    filters: [
        { vendorId: 0x1234 }
    ]
});

console.log(device);
```

Actual device availability depends on the extension, native host, operating system, USB permissions, and backend support.

# USB Communication

The native backend is designed to support operations including:

- USB device enumeration
- opening and closing devices
- configuration selection
- interface claiming and release
- alternate interface selection
- control transfers
- bulk transfers
- interrupt transfers
- isochronous transfers where available
- endpoint halt handling
- device reset operations

Some behavior depends on the capabilities and semantics of the underlying PyUSB/libusb environment. Compatibility should therefore not yet be considered identical to browser-native WebUSB.

# Native Messaging

Firefox WebExtensions cannot directly perform arbitrary native USB operations.

`fox-webusb` therefore uses Firefox Native Messaging:

```text
Web Page
    │
    ▼
Page Polyfill
    │
    ▼
Content Script
    │
    ▼
Background Script
    │
    ▼
Native Messaging
    │
    ▼
fox-webusb Native Host
    │
    ▼
USB Backend
```

The native host forms the boundary between the browser environment and the USB backend. The communication layer handles protocol validation and message-size constraints.

# Security Model

Because `fox-webusb` can reach native USB functionality, unrestricted device access is not the design goal.

The project includes restrictions and validation around:

- origin handling
- user activation
- device permission management
- authorized-device tracking
- protected USB interface classes
- security-sensitive devices
- control-transfer validation
- Native Messaging protocol validation
- trusted extension-side communication

The design aims to prevent arbitrary web pages from treating the native USB backend as unrestricted system access.

# Origin Handling

A browser API must preserve the relationship between a device request and the site that made it.

`fox-webusb` therefore uses the Firefox extension environment to derive and manage request origins. It does not simply trust arbitrary origin strings supplied by page JavaScript.

Browser-side information and extension-side request handling are used to associate requests with the relevant page and frame.

# Device Permissions

The project follows a permission-oriented model.

A site should not automatically receive unrestricted access to every USB device visible to the operating system.

Conceptually:

```text
Web Page
    │
    │ requestDevice()
    ▼
Device Selection
    │
    ▼
Permission / Grant
    │
    ▼
Authorized Device
    │
    ▼
getDevices()
```

`getDevices()` is intended to work with devices that have already been authorized instead of exposing the complete system USB device list directly to arbitrary pages.

# Hotplug Events

The implementation includes infrastructure for monitoring USB connection-state changes.

Conceptually:

```text
USB Device
    │
    │ connect / disconnect
    ▼
Native Host
    │
    ▼
Background Script
    │
    ▼
Registered Frames
    │
    ▼
navigator.usb
```

The extension architecture can coordinate relevant events across registered tabs and frames.

# Native Acceleration

The repository also contains an optional native acceleration component for operations such as:

- Base64 encoding and decoding
- binary protocol helpers
- packet packing and unpacking
- validation helpers
- checksum-related operations

The acceleration layer is intended to remain optional.

# TypeScript Definitions

`fox-webusb` includes TypeScript definitions describing the exposed WebUSB-style API.

This allows projects to reference objects such as:

```typescript
USBDevice
USBConfiguration
USBInterface
USBEndpoint
```

without treating the API purely as untyped injected JavaScript.

# Testing

The project contains tests for multiple implementation layers:

```text
Python Tests
    ├── USB Bridge
    ├── Security / Hardening
    ├── Permission Logic
    ├── Settings Store
    ├── Native Messaging Protocol
    └── End-to-End Native Host Tests

JavaScript Tests
    └── Page Polyfill API Behavior

TypeScript Tests
    └── API Type Definitions

Rust Tests
    └── Optional Native Acceleration
```

Automated tests are important, but they do not replace testing with real USB hardware.

Physical-device testing is still necessary for operating-system behavior, driver interaction, libusb compatibility, device-specific transfer behavior, timing, permission edge cases, and browser/Native Messaging integration.

# Current Status

## Implemented

- [x] Firefox-oriented architecture
- [x] Firefox WebExtension
- [x] page-side `navigator.usb` polyfill
- [x] content-script communication
- [x] background-script coordination
- [x] Firefox Native Messaging integration
- [x] native Python host
- [x] PyUSB/libusb backend integration
- [x] WebUSB-style object model
- [x] device permission management
- [x] origin-aware request handling
- [x] USB transfer handling
- [x] security restrictions and validation
- [x] hotplug monitoring infrastructure
- [x] automated Python tests
- [x] JavaScript API tests
- [x] TypeScript definitions
- [x] optional native acceleration

## Still Experimental

- [ ] broad physical USB device verification
- [ ] wider operating-system compatibility testing
- [ ] device-specific compatibility testing
- [ ] long-term API stabilization
- [ ] compatibility testing with real WebUSB applications

# Relationship with Mock-webusb

`fox-webusb` shares implementation history and ideas with Mock-webusb but is developed as a separate project with a different browser architecture.

The Firefox environment requires a different transport and integration model:

```text
Firefox WebExtension
        │
        ▼
Native Messaging
        │
        ▼
Native USB Backend
```

It should therefore not be considered merely a renamed copy of another WebUSB implementation.

# Difference from Chromium WebUSB

Chromium WebUSB conceptually operates as part of the browser's native implementation:

```text
Web Page
    │
    ▼
Browser WebUSB Implementation
    │
    ▼
Browser USB Backend
    │
    ▼
USB Device
```

`fox-webusb` instead uses:

```text
Web Page
    │
    ▼
Firefox WebExtension
    │
    ▼
Native Messaging
    │
    ▼
Native Host
    │
    ▼
PyUSB / libusb
    │
    ▼
USB Device
```

The goal is API compatibility where practical, not reproduction of Chromium's internal WebUSB implementation.

# Known Limitations

`fox-webusb` is experimental software.

Important limitations include:

- real-hardware compatibility is still being expanded
- behavior can depend on the operating system and USB drivers
- PyUSB/libusb behavior can differ from browser-native WebUSB
- isochronous transfers may have backend-specific limitations
- Native Messaging introduces transport constraints
- browser, extension, and native-host setup are all required
- API compatibility does not guarantee compatibility with every existing WebUSB application

# Important Notice

> ⚠️ `fox-webusb` is experimental alpha software.

The project may contain AI-generated or AI-assisted code.

As a result, there may be bugs, incomplete behavior, compatibility differences, undiscovered security issues, and hardware-specific limitations.

Do not assume that experimental API compatibility is equivalent to production-ready browser-native WebUSB support.

Use appropriate caution when testing with physical hardware.

# Credits

`fox-webusb` is based on implementation history and ideas associated with Mock-webusb.

# License

MIT License.
