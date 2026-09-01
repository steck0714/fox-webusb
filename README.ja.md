# fox-webusb

🇯🇵 [日本語](README.ja.md) | 🇺🇸 [English](README.en.md) | 🇨🇳 [简体中文](README.zh.md)

⚠️ **実験版 (v0.0.0)**: 実際のUSB通信まで接続するコア実装が完成しています。

ただし、初期プレリリース版であり、**実機のUSBデバイスではまだ検証されていません**。使用する際は注意してください。

## 概要

`fox-webusb` は、[Mock-webusb](https://github.com/steck0714/Mock-webusb) をベースにした、Firefox向けの実験的なWebUSB互換実装です。

ネイティブWebUSBが利用できない環境でもWebUSB互換APIを提供することを目的としています。

単純に見た目だけのAPIを提供するポリフィルではなく、実際のUSB通信まで到達するパイプラインを扱えるよう設計されています。

## Quick Start (v0.0.0)

`fox-webusb` のポリフィルを読み込むと、標準的な `navigator.usb` インターフェースを提供します。

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

## 現在の状態とロードマップ

- [x] リポジトリ作成
- [x] 技術調査・設計
- [x] 初期モックロジックの実装
- [x] 最小動作デモ
- [x] 実際のUSB通信まで到達するコアパイプライン
- [ ] 実機USBデバイスでの検証・ハードウェアテスト 🧪
- [ ] APIの安定化

## Mock-webusbとの関係

```text
Mock-APIs
    │
    └── Mock-webusb
          │
          └── fox-webusb
```

`fox-webusb` はMock-webusbから派生した実装であり、Firefox向けの環境を対象とした独立プロジェクトとして開発されています。

## ⚠️ 注意事項

本プロジェクトは実験的なソフトウェアです。

AIによって生成されたコード、またはAIの支援を受けたコードが含まれる場合があります。そのため、バグや制限が存在する可能性があり、すべての環境で正常に動作することを保証するものではありません。

現時点では実機USBデバイスによる検証は完了していません。

## Credits & License

[steck0714/Mock-webusb](https://github.com/steck0714/Mock-webusb) をベースに開発されています。

MIT Licenseの下で公開されています。