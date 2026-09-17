# -*- coding: utf-8 -*-
"""
fox-webusb ネイティブメッセージングホスト。

移植元 pyside6-webusb (v0.0.4b0) の「PySide6/QtWebEngineアプリにnavigator.usb
ポリフィルを注入するQtブリッジ」を、「Firefox拡張機能から起動される、
ブラウザ本体とは独立したネイティブメッセージングホスト」として書き直したもの。
詳しい設計についてはリポジトリ直下のREADME.md、および bridge.py 冒頭の
docstringを参照。

コードネーム: fox-webusb
バージョン: 0.0.0a1 (v0.0.0a0に対する大規模な機能追加・セキュリティ強化
リリース。独立したセキュリティ監査[pyside6-webusb側]で見つかった問題の
移植修正、二重サーフェスアーキテクチャ[webusb_core.js]、現行WebUSB仕様との
突き合わせ[USBConnectionEvent/Permissions Policy]、ローカルアテステーション
[Ed25519]、独自コマンド、F12デバッグヘルパー、UIのja/en/zh_CN多言語対応
[チューザーダイアログ含む]等。詳細はCHANGELOG.md [0.0.0a1] を参照)
"""

__version__ = "0.0.0a1"
__codename__ = "fox-webusb"
