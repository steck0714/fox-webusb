# fox-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

> ⚠️ **Experimental Alpha — v0.0.0a**
>
> `fox-webusb` is an experimental, unofficial WebUSB-compatible implementation for Firefox-oriented environments.
>
> The project is capable of connecting the JavaScript API pipeline to a native USB backend. However, it remains an early alpha project and hardware compatibility is still being verified.

## About

`fox-webusb` is an experimental Firefox-oriented implementation derived from the ideas and implementation history of [Mock-webusb](https://github.com/steck0714/Mock-webusb).

The goal is to provide a WebUSB-compatible API surface in environments where Firefox does not provide a native `navigator.usb` implementation.

This project is not intended to reproduce Chromium's internal WebUSB implementation.

Instead, it builds an alternative architecture around Firefox WebExtensions and Native Messaging:

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

The project is designed to go beyond a purely visual API polyfill and connect WebUSB-style JavaScript operations to an underlying USB communication backend.

## Why fox-webusb?

Firefox does not provide a native `navigator.usb` implementation.

`fox-webusb` explores whether a WebUSB-compatible API can instead be provided through the combination of:

- Firefox WebExtensions
- Page-side JavaScript injection
- Content-script messaging
- Background-script coordination
- Firefox Native Messaging
- A native USB backend

This makes `fox-webusb` an architectural experiment as much as a WebUSB compatibility project.

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

Unlike a browser-native implementation, multiple components cooperate to expose the API.

The page itself does not communicate directly with the USB backend.

# API

`fox-webusb` exposes a WebUSB-compatible API centered around:

```javascript
navigator.usb
```

The implementation includes WebUSB-style objects such as:

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

The project aims to reproduce the observable API shape and behavior of WebUSB where practical.

Example:

```javascript
if (!navigator.usb) {
    throw new Error("fox-webusb is not initialized");
}

const devices = await navigator.usb.getDevices();

console.log("Authorized USB devices:", devices);
```

For device selection, applications use the familiar WebUSB-style flow:

```javascript
const device = await navigator.usb.requestDevice({
    filters: [
        {
            vendorId: 0x1234
        }
    ]
});

console.log(device);
```

Actual device availability depends on the extension, native host, operating system, USB permissions, and backend support.

# USB Communication

The native backend is designed to support operations including:

- USB device enumeration
- Device opening
- Device closing
- Configuration selection
- Interface claiming
- Interface release
- Alternate interface selection
- Control transfers
- Bulk transfers
- Interrupt transfers
- Isochronous transfer support where available
- Endpoint halt handling
- Device reset operations

The exact behavior of some operations depends on the capabilities and semantics of the underlying PyUSB/libusb environment.

Therefore, compatibility should not yet be considered identical to a browser-native WebUSB implementation.

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

The native host acts as the boundary between the browser environment and the USB backend.

The implementation includes protocol validation and message-size handling for communication between the extension and the native process.

Large payload handling may use encoded and chunked transport formats depending on the operation.

# Security Model

Because `fox-webusb` can reach native USB functionality, unrestricted device access is not the design goal.

The project includes restrictions and validation around areas such as:

- Origin handling
- User activation
- Device permission management
- Authorized-device tracking
- Protected USB interface classes
- Security-sensitive devices
- Control-transfer validation
- Native Messaging protocol validation
- Trusted extension-side communication

The implementation is intended to prevent arbitrary web pages from treating the native USB backend as unrestricted system access.

Security behavior may continue to evolve as the project is tested.

# Origin Handling

One of the important differences between a browser API and a simple JavaScript polyfill is that device access must remain associated with the requesting site.

`fox-webusb` therefore uses the Firefox extension environment to derive and manage request origins.

The architecture does not simply trust arbitrary origin strings supplied by page JavaScript.

Browser-side information and extension-side request handling are used to associate requests with the relevant page and frame.

This is important because the native host itself does not have direct access to the browser's full page security context.

# Device Permissions

The project follows a permission-oriented model.

A site should not automatically receive unrestricted access to every USB device visible to the operating system.

The intended flow is conceptually:

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

`getDevices()` is intended to operate on devices that have already been authorized rather than exposing the complete system USB device list directly to arbitrary pages.

# Hotplug Events

The implementation also includes infrastructure for USB connection monitoring.

When device connection state changes, the project can distribute WebUSB-style events through the extension architecture.

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

Because the architecture is browser-wide rather than tied to a single embedded browser page, the extension can coordinate events across multiple registered tabs and frames where appropriate.

# Native Acceleration

The repository also contains an optional native acceleration component.

The acceleration layer is intended for operations such as:

- Base64 encoding and decoding
- Binary protocol helpers
- Packet packing
- Packet unpacking
- Validation helpers
- Checksum-related operations

The project can retain a non-accelerated implementation path where the optional native component is unavailable.

# TypeScript Definitions

`fox-webusb` includes TypeScript definitions describing the exposed WebUSB-style API.

The definitions are intended to allow projects to reference objects such as:

```typescript
USBDevice
USBConfiguration
USBInterface
USBEndpoint
```

without treating the API purely as untyped injected JavaScript.

# Testing

The project contains tests for multiple layers of the implementation.

```text
Python Tests
    │
    ├── USB Bridge
    ├── Security / Hardening
    ├── Permission Logic
    ├── Settings Store
    ├── Native Messaging Protocol
    └── End-to-End Native Host Tests

JavaScript Tests
    │
    └── Page Polyfill API Behavior

TypeScript Tests
    │
    └── API Type Definitions

Rust Tests
    │
    └── Optional Native Acceleration
```

Automated tests are important for validating API behavior and internal architecture.

However:

> Automated tests do not replace testing with real USB hardware.

Physical-device testing remains necessary for validating operating-system behavior, driver interaction, libusb compatibility, device-specific transfer behavior, permission edge cases, real hardware timing, and browser/Native Messaging integration.

# Current Status

## Implemented

- [x] Firefox-oriented architecture
- [x] Firefox WebExtension
- [x] Page-side `navigator.usb` polyfill
- [x] Content-script communication
- [x] Background-script coordination
- [x] Firefox Native Messaging integration
- [x] Native Python host
- [x] PyUSB/libusb backend integration
- [x] WebUSB-style object model
- [x] Device permission management
- [x] Origin-aware request handling
- [x] USB transfer handling
- [x] Security restrictions and validation
- [x] Hotplug monitoring infrastructure
- [x] Automated Python tests
- [x] JavaScript API tests
- [x] TypeScript definitions
- [x] Optional native acceleration

## Still Experimental

- [ ] Broad physical USB device verification
- [ ] Wider operating-system compatibility testing
- [ ] Device-specific compatibility testing
- [ ] Long-term API stabilization
- [ ] Compatibility testing with real WebUSB applications

# Relationship with Mock-webusb

```text
Mock-APIs
    │
    └── Mock-webusb
          │
          └── fox-webusb
```

`fox-webusb` shares implementation history and ideas with Mock-webusb but is developed as a separate project with a different browser architecture.

The Firefox environment requires a different transport and integration model.

Instead of communicating through an embedded browser bridge, `fox-webusb` uses:

```text
Firefox WebExtension
        │
        ▼
Native Messaging
        │
        ▼
Native USB Backend
```

This means the project should not be considered merely a renamed copy of another WebUSB implementation.

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

`fox-webusb` instead uses an external architecture:

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

The goal is API compatibility where practical.

The goal is **not** to reproduce Chromium's internal WebUSB implementation.

# Known Limitations

`fox-webusb` is experimental software.

Important limitations include:

- Real hardware compatibility is still being expanded.
- Behavior can depend on the operating system and USB drivers.
- PyUSB/libusb behavior may differ from browser-native WebUSB behavior.
- Isochronous transfers may have backend-specific limitations.
- Native Messaging introduces transport constraints that do not exist in a native browser implementation.
- Browser, extension, and native-host setup are all required.
- API compatibility does not guarantee compatibility with every existing WebUSB application.

# Important Notice

> ⚠️ `fox-webusb` is experimental alpha software.

Some code in this project may have been generated or assisted by AI.

As a result, the project may contain bugs, incomplete behavior, compatibility differences, security issues that have not yet been discovered, and hardware-specific limitations.

Do not assume that experimental API compatibility is equivalent to production-ready browser-native WebUSB support.

Use appropriate caution when testing with physical hardware.

# Credits

`fox-webusb` is based on implementation history and ideas originating from:

- [steck0714/Mock-webusb](https://github.com/steck0714/Mock-webusb)

# License

MIT License.
