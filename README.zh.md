# fox-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **实验版本 (v0.0.0)**：连接到实际 USB 通信的核心实现已经完成。

但是，这是初始预发布版本，**目前尚未使用实体 USB 设备进行验证**。请谨慎使用。

## 关于

`fox-webusb` 是基于 [Mock-webusb](https://github.com/steck0714/Mock-webusb) 开发的 Firefox 面向实验性 WebUSB 兼容实现。

其目标是在无法使用原生 WebUSB 的环境中提供兼容 WebUSB 的 API。

与仅提供表面 API 的简单 Polyfill 不同，`fox-webusb` 的设计目标是处理一直到实际底层 USB 通信的完整流程。

## Quick Start (v0.0.0)

加载 `fox-webusb` Polyfill 后，它会提供标准的 `navigator.usb` 接口：

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

## 当前状态与路线图

- [x] 创建仓库
- [x] 技术研究与设计
- [x] 实现初始 Mock 逻辑
- [x] 最小可运行演示
- [x] 完成连接到实际 USB 通信的核心流程
- [ ] 实体 USB 设备验证与硬件测试 🧪
- [ ] API 稳定化

## 与 Mock-webusb 的关系

```text
Mock-APIs
    │
    └── Mock-webusb
          │
          └── fox-webusb
```

`fox-webusb` 基于 Mock-webusb 开发，并作为面向 Firefox 环境的独立项目进行开发。

## ⚠️ 注意事项

本项目属于实验性软件。

项目中可能包含由 AI 生成或在 AI 协助下生成的代码。因此，其中可能存在错误或限制，也无法保证在所有环境下正常运行。

目前尚未完成实体 USB 设备测试。

## Credits & License

本项目基于 [steck0714/Mock-webusb](https://github.com/steck0714/Mock-webusb) 开发。

采用 MIT License。