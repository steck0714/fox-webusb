# fox-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

> ⚠️ **实验性 Alpha 版本 — v0.0.0a**
>
> `fox-webusb` 是一个面向 Firefox 环境的非官方、实验性 WebUSB 兼容实现。
>
> 项目将 WebUSB 风格的 JavaScript API 与原生 USB 后端连接起来。目前仍处于早期 Alpha 阶段，实体 USB 设备兼容性正在持续验证。

## 关于

`fox-webusb` 是一个面向 Firefox 环境的实验性 WebUSB 兼容实现，其部分设计思路和实现历史与 Mock-webusb 有关。

项目的目标是在 Firefox 没有原生 `navigator.usb` 实现的环境中，提供接近 WebUSB 的 API。

本项目并不尝试复制 Chromium 内部的 WebUSB 实现，而是采用基于 Firefox WebExtension 和 Native Messaging 的独立架构。

```text
Web 页面
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
USB 设备
```

项目的目标不仅是提供表面上的 API Polyfill，还包括将 WebUSB 风格的 JavaScript 操作连接到底层 USB 通信后端。

## 为什么需要 fox-webusb？

Firefox 没有原生的 `navigator.usb` 实现。

`fox-webusb` 尝试通过组合以下组件提供 WebUSB 兼容 API：

- Firefox WebExtension
- 页面侧 JavaScript 注入
- Content Script 通信
- Background Script 协调
- Firefox Native Messaging
- 原生 USB 后端

因此，`fox-webusb` 既是 WebUSB 兼容项目，也是关于如何在 Firefox 环境中构建 WebUSB 风格 API 的架构实验。

# 架构

```text
┌──────────────────────────────┐
│           Web 页面           │
│                              │
│       navigator.usb          │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│    Firefox WebExtension      │
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
          USB 设备
```

与浏览器原生 WebUSB 不同，`fox-webusb` 需要多个组件协同工作。Web 页面本身不会直接与 USB 后端通信。

# API

`fox-webusb` 围绕以下 API 提供 WebUSB 兼容接口：

```javascript
navigator.usb
```

实现中包含类似 WebUSB 的对象：

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

项目的目标是在实际可行的范围内重现 WebUSB API 的可观察结构和行为。

示例：

```javascript
if (!navigator.usb) {
    throw new Error("fox-webusb is not initialized");
}

const devices = await navigator.usb.getDevices();

console.log("Authorized USB devices:", devices);
```

设备选择采用接近 WebUSB 的流程：

```javascript
const device = await navigator.usb.requestDevice({
    filters: [
        { vendorId: 0x1234 }
    ]
});

console.log(device);
```

实际可用设备取决于 Extension、Native Host、操作系统、USB 权限、驱动程序和底层后端支持情况。

# USB 通信

原生后端旨在支持以下操作：

- USB 设备枚举
- 打开和关闭设备
- Configuration 选择
- Interface 的 Claim 和 Release
- Alternate Interface 选择
- Control Transfer
- Bulk Transfer
- Interrupt Transfer
- 支持环境中的 Isochronous Transfer
- Endpoint Halt 处理
- Device Reset

部分行为取决于底层 PyUSB/libusb 的能力和语义。因此，目前不应认为它与浏览器原生 WebUSB 具有完全相同的兼容性。

# Native Messaging

Firefox WebExtension 无法仅通过普通 JavaScript 直接执行任意原生 USB 操作。

因此，`fox-webusb` 使用 Firefox Native Messaging：

```text
Web 页面
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

Native Host 是浏览器环境和 USB 后端之间的边界。通信层负责处理协议验证和消息大小限制。

# 安全模型

由于 `fox-webusb` 可以访问原生 USB 功能，因此其设计目标不是提供无限制的设备访问。

项目针对以下领域提供限制和验证：

- Origin 处理
- User Activation
- 设备权限管理
- 已授权设备管理
- 受保护的 USB Interface Class
- 安全敏感设备
- Control Transfer 验证
- Native Messaging 协议验证
- 受信任的 Extension 端通信

设计目标是避免任意 Web 页面将 Native Host 当作无限制的系统 USB API。

# Origin 处理

浏览器 API 需要保持设备请求与发起请求的网站之间的关联。

因此，`fox-webusb` 使用 Firefox Extension 环境来获取和管理请求来源。页面 JavaScript 提供的任意 Origin 字符串不会被无条件直接信任。

项目利用浏览器侧信息和 Extension 侧请求处理，将请求与相应的页面和 Frame 关联起来。

# 设备权限

项目采用面向权限的设备访问模型。

目标并不是让网站自动获得操作系统中所有 USB 设备的无限制访问权限。

概念流程如下：

```text
Web 页面
    │
    │ requestDevice()
    ▼
设备选择
    │
    ▼
权限授予
    │
    ▼
已授权设备
    │
    ▼
getDevices()
```

`getDevices()` 的目标是处理已经授权的设备，而不是直接向任意 Web 页面公开完整的系统 USB 设备列表。

# Hotplug 事件

实现中还包含用于监控 USB 设备连接状态变化的基础设施。

概念上：

```text
USB 设备
    │
    │ connect / disconnect
    ▼
Native Host
    │
    ▼
Background Script
    │
    ▼
已注册 Frame
    │
    ▼
navigator.usb
```

Extension 架构可以协调并向已注册的 Tab 和 Frame 分发相关事件。

# Native Acceleration

仓库还包含一个可选的原生加速层，可用于：

- Base64 编码和解码
- 二进制协议辅助处理
- 数据包 Pack / Unpack
- Validation Helper
- Checksum 相关处理

该加速层被设计为可选组件。

# TypeScript 定义

`fox-webusb` 包含用于描述公开 WebUSB 风格 API 的 TypeScript 定义。

例如可以引用：

```typescript
USBDevice
USBConfiguration
USBInterface
USBEndpoint
```

因此，API 不必仅作为没有类型信息的注入 JavaScript 来使用。

# 测试

项目包含针对多个实现层的测试：

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

自动化测试非常重要，但不能替代实体 USB 硬件测试。

操作系统行为、USB 驱动程序、libusb 兼容性、设备特定 Transfer 行为、时序、权限边界情况，以及 Firefox 与 Native Messaging 的集成仍需要通过实际硬件进行验证。

# 当前状态

## 已实现

- [x] 面向 Firefox 的架构
- [x] Firefox WebExtension
- [x] 页面侧 `navigator.usb` Polyfill
- [x] Content Script 通信
- [x] Background Script 协调
- [x] Firefox Native Messaging 集成
- [x] Python Native Host
- [x] PyUSB/libusb 后端集成
- [x] WebUSB 风格对象模型
- [x] 设备权限管理
- [x] Origin 感知的请求处理
- [x] USB Transfer 处理
- [x] 安全限制与验证
- [x] Hotplug 监控基础设施
- [x] Python 自动化测试
- [x] JavaScript API 测试
- [x] TypeScript 定义
- [x] 可选 Native Acceleration

## 仍处于实验阶段

- [ ] 更广泛的实体 USB 设备验证
- [ ] 更广泛的操作系统兼容性测试
- [ ] 设备特定兼容性测试
- [ ] 长期 API 稳定化
- [ ] 与真实 WebUSB 应用的兼容性验证

# 与 Mock-webusb 的关系

`fox-webusb` 与 Mock-webusb 共享部分实现历史和设计思路，但它是采用不同浏览器架构的独立项目。

Firefox 环境中的通信路径和集成方式不同：

```text
Firefox WebExtension
        │
        ▼
Native Messaging
        │
        ▼
Native USB Backend
```

因此，它不应被视为只是简单改名后的另一份 WebUSB 实现。

# 与 Chromium WebUSB 的区别

Chromium 的 WebUSB 在概念上属于浏览器内部的原生实现：

```text
Web 页面
    │
    ▼
Browser WebUSB Implementation
    │
    ▼
Browser USB Backend
    │
    ▼
USB 设备
```

而 `fox-webusb` 使用：

```text
Web 页面
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
USB 设备
```

这样的外部组件架构。

目标是在实际可行的范围内提供 API 兼容性，而不是复制 Chromium 内部的 WebUSB 实现。

# 已知限制

`fox-webusb` 是实验性软件。

主要限制包括：

- 实体硬件兼容性仍在持续验证
- 行为可能因操作系统和 USB 驱动不同而变化
- PyUSB/libusb 的行为可能与浏览器原生 WebUSB 不同
- Isochronous Transfer 可能存在后端特定限制
- Native Messaging 存在通信层面的限制
- 使用时需要完成 Browser、Extension 和 Native Host 的配置
- API 形状兼容并不保证所有现有 WebUSB 应用都能够正常工作

# ⚠️ 重要提示

> ⚠️ `fox-webusb` 是 Experimental Alpha Software。

项目中可能包含由 AI 生成或在 AI 协助下生成的代码。

因此可能存在 Bug、未完成行为、兼容性差异、尚未发现的安全问题以及设备特定限制。

实验性的 API 兼容性并不意味着已经达到生产环境级别的浏览器原生 WebUSB 质量。

使用实体硬件进行测试时，请保持适当谨慎。

# Credits

`fox-webusb` 基于与 Mock-webusb 相关的实现历史和设计思路。

# License

MIT License.
