# fox-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

> ⚠️ **Experimental Alpha — v0.0.0a**
>
> `fox-webusb` は、Firefox系環境でWebUSB互換APIを提供することを目的とした、非公式かつ実験的な実装です。
>
> WebUSB風のJavaScript APIからネイティブUSBバックエンドまで接続する構成を実装しています。現在はまだ初期Alpha段階であり、実機USBデバイスとの互換性を継続して検証しています。

## 概要

`fox-webusb` は、Mock-webusbに関連する実装履歴やアイデアをもとにした、Firefox向けの実験的なWebUSB互換実装です。

Firefoxにネイティブの `navigator.usb` 実装が存在しない環境で、WebUSBに近いAPIを提供することを目的としています。

本プロジェクトはChromium内部のWebUSB実装を再現するものではありません。代わりに、Firefox WebExtensionとNative Messagingを組み合わせた独自のアーキテクチャを採用しています。

```text
Webページ
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
USBデバイス
```

単に `navigator.usb` の見た目だけを再現するポリフィルではなく、WebUSB風のJavaScript操作を実際のUSB通信バックエンドまで接続することを目標にしています。

## なぜ fox-webusb なのか？

Firefoxにはネイティブの `navigator.usb` 実装がありません。

`fox-webusb` は、以下を組み合わせることでWebUSB互換APIを提供できるかを実験しています。

- Firefox WebExtension
- ページ側JavaScriptの注入
- Content Scriptによる通信
- Background Scriptによる調整
- Firefox Native Messaging
- ネイティブUSBバックエンド

そのため `fox-webusb` は、WebUSB互換プロジェクトであると同時に、Firefox上でWebUSB風APIを構築するためのアーキテクチャ実験でもあります。

# アーキテクチャ

```text
┌──────────────────────────────┐
│          Webページ           │
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
          USBデバイス
```

ブラウザにネイティブ実装されたWebUSBとは異なり、複数のコンポーネントが協力してAPIを提供します。Webページ自体がUSBバックエンドへ直接通信するわけではありません。

# API

`fox-webusb` は、次のAPIを中心としたWebUSB互換インターフェースを提供します。

```javascript
navigator.usb
```

実装では、以下のようなWebUSBスタイルのオブジェクトを扱います。

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

可能な範囲でWebUSB APIの外部から観測できる形状や挙動を再現することを目標としています。

例:

```javascript
if (!navigator.usb) {
    throw new Error("fox-webusb is not initialized");
}

const devices = await navigator.usb.getDevices();

console.log("Authorized USB devices:", devices);
```

デバイス選択も、WebUSBに近い形式で行います。

```javascript
const device = await navigator.usb.requestDevice({
    filters: [
        { vendorId: 0x1234 }
    ]
});

console.log(device);
```

実際に利用できるデバイスは、Extension、Native Host、OS、USB権限、ドライバ、バックエンドの対応状況などに依存します。

# USB通信

ネイティブバックエンドでは、主に以下の操作を扱うことを目標としています。

- USBデバイスの列挙
- デバイスのオープンとクローズ
- Configurationの選択
- InterfaceのClaimとRelease
- Alternate Interfaceの選択
- Control Transfer
- Bulk Transfer
- Interrupt Transfer
- 対応環境でのIsochronous Transfer
- Endpoint Haltの処理
- Device Reset

一部の挙動は、PyUSB/libusbバックエンドの機能や仕様に依存します。そのため、現時点ではブラウザネイティブのWebUSBと完全に同一の互換性を保証するものではありません。

# Native Messaging

Firefox WebExtensionは、通常のJavaScriptだけで任意のネイティブUSB操作を直接実行することはできません。

そのため `fox-webusb` ではFirefox Native Messagingを利用します。

```text
Webページ
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

Native Hostは、ブラウザ環境とUSBバックエンドの境界となります。通信レイヤーでは、プロトコル検証やメッセージサイズの制約を扱います。

# セキュリティモデル

`fox-webusb` はネイティブUSB機能まで到達できるため、無制限なデバイスアクセスを目的としていません。

実装では、次のような領域に対する制限や検証を行います。

- Originの処理
- User Activation
- デバイス権限管理
- 許可済みデバイスの管理
- 保護対象USB Interface Class
- セキュリティ上注意が必要なデバイス
- Control Transferの検証
- Native Messagingプロトコルの検証
- 信頼されたExtension側通信

任意のWebページがNative Hostを無制限のシステムUSB APIとして扱えないようにすることを意図しています。

# Origin処理

ブラウザAPIでは、デバイス要求と、その要求を行ったサイトとの関係を保持する必要があります。

`fox-webusb` では、Firefox Extension環境を利用してリクエスト元のOriginを取得・管理します。ページ側JavaScriptが任意に指定したOrigin文字列を、そのまま無条件で信用する設計ではありません。

ブラウザ側で取得できる情報とExtension側のリクエスト処理を利用し、リクエストを対応するページやFrameと関連付けます。

# デバイス権限

本プロジェクトは、権限を意識したデバイスアクセスモデルを採用しています。

WebサイトがOS上で認識されているすべてのUSBデバイスへ自動的に無制限アクセスできるようにすることが目的ではありません。

概念的な流れは次のとおりです。

```text
Webページ
    │
    │ requestDevice()
    ▼
デバイス選択
    │
    ▼
権限の許可
    │
    ▼
許可済みデバイス
    │
    ▼
getDevices()
```

`getDevices()` は、任意のWebページへシステム上のUSBデバイス一覧を直接公開するのではなく、すでに許可されたデバイスを扱うことを想定しています。

# Hotplugイベント

USBデバイスの接続状態変化を監視するための基盤も含まれています。

概念的には次のような経路です。

```text
USBデバイス
    │
    │ connect / disconnect
    ▼
Native Host
    │
    ▼
Background Script
    │
    ▼
登録済みFrame
    │
    ▼
navigator.usb
```

Extensionアーキテクチャを利用して、登録されたTabやFrameに対して関連するイベントを調整・配信できます。

# Native Acceleration

リポジトリには、オプションのネイティブアクセラレーション層も含まれています。

対象には、次のような処理があります。

- Base64エンコードとデコード
- バイナリプロトコル処理
- パケットのPack / Unpack
- Validation Helper
- Checksum関連処理

アクセラレーション層は必須依存ではなく、オプションとして利用することを想定しています。

# TypeScript定義

`fox-webusb` には、公開するWebUSBスタイルAPIを記述するTypeScript定義が含まれています。

例えば、以下のようなオブジェクトを型情報付きで参照できます。

```typescript
USBDevice
USBConfiguration
USBInterface
USBEndpoint
```

これにより、APIを単なる型なしの注入JavaScriptとして扱う必要がありません。

# テスト

プロジェクトには、複数の実装レイヤーに対するテストが含まれています。

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

自動テストは重要ですが、実機USBデバイスでの検証を置き換えるものではありません。

OSごとの挙動、USBドライバ、libusb互換性、デバイス固有のTransfer挙動、タイミング、権限処理の境界ケース、FirefoxとNative Messagingの統合などは、実機による確認が必要です。

# 現在の状態

## 実装済み

- [x] Firefox向けアーキテクチャ
- [x] Firefox WebExtension
- [x] ページ側 `navigator.usb` ポリフィル
- [x] Content Script通信
- [x] Background Scriptによる調整
- [x] Firefox Native Messaging統合
- [x] Python Native Host
- [x] PyUSB/libusbバックエンド統合
- [x] WebUSBスタイルのオブジェクトモデル
- [x] デバイス権限管理
- [x] Originを考慮したリクエスト処理
- [x] USB Transfer処理
- [x] セキュリティ制限と検証
- [x] Hotplug監視基盤
- [x] Python自動テスト
- [x] JavaScript APIテスト
- [x] TypeScript定義
- [x] オプションのNative Acceleration

## まだ実験段階

- [ ] 幅広い実機USBデバイスでの検証
- [ ] より広いOS互換性テスト
- [ ] デバイス固有の互換性テスト
- [ ] 長期的なAPI安定化
- [ ] 実際のWebUSBアプリケーションとの互換性検証

# Mock-webusbとの関係

`fox-webusb` はMock-webusbと実装履歴やアイデアを共有していますが、異なるブラウザアーキテクチャを採用する独立したプロジェクトです。

Firefox環境では、通信経路と統合方法が異なります。

```text
Firefox WebExtension
        │
        ▼
Native Messaging
        │
        ▼
Native USB Backend
```

そのため、単に別のWebUSB実装を改名しただけのものではありません。

# Chromium WebUSBとの違い

ChromiumのWebUSBは、概念的にはブラウザ内部のネイティブ実装として動作します。

```text
Webページ
    │
    ▼
Browser WebUSB Implementation
    │
    ▼
Browser USB Backend
    │
    ▼
USBデバイス
```

一方、`fox-webusb` は次のような構成です。

```text
Webページ
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
USBデバイス
```

目標は可能な範囲でのAPI互換性であり、Chromium内部のWebUSB実装そのものを再現することではありません。

# 既知の制限

`fox-webusb` は実験的なソフトウェアです。

主な制限には次のようなものがあります。

- 実機ハードウェアとの互換性は継続して検証中
- OSやUSBドライバによって挙動が異なる可能性
- PyUSB/libusbの挙動がブラウザネイティブWebUSBと異なる可能性
- Isochronous Transferにはバックエンド固有の制限がある可能性
- Native Messaging固有の通信制約
- Browser、Extension、Native Hostのセットアップが必要
- API形状が互換でも、すべての既存WebUSBアプリケーションの動作を保証するものではない

# ⚠️ 注意事項

> ⚠️ `fox-webusb` はExperimental Alpha Softwareです。

本プロジェクトには、AIによって生成されたコード、またはAIの支援を受けたコードが含まれる場合があります。

そのため、バグ、未完成の挙動、互換性の違い、未発見のセキュリティ上の問題、デバイス固有の制限などが存在する可能性があります。

実験的なAPI互換性が、そのまま本番環境向けのブラウザネイティブWebUSB品質を意味するものではありません。

実機ハードウェアを使用する際は、十分注意してテストしてください。

# Credits

`fox-webusb` は、Mock-webusbに関連する実装履歴やアイデアをもとにしています。

# License

MIT License.
