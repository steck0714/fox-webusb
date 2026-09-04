# -*- coding: utf-8 -*-
"""
fox-webusb ネイティブメッセージングホスト。

移植元 pyside6-webusb (v0.0.4b0) の「PySide6/QtWebEngineアプリにnavigator.usb
ポリフィルを注入するQtブリッジ」を、「Firefox拡張機能から起動される、
ブラウザ本体とは独立したネイティブメッセージングホスト」として書き直したもの。
詳しい設計についてはリポジトリ直下のREADME.md、および bridge.py 冒頭の
docstringを参照。

コードネーム: fox-webusb
バージョン: 0.0.0a0 (v0.0.0を実機環境[Windows + LibreWolf]で検証した結果
[checklog.md]に基づく修正リリース。移植元のバージョン番号[0.0.4b0/b1]とは
独立に0.0.0系列で数えている——アーキテクチャが別物になったため、移植元の
バージョン系列を引き継ぐより、新しいコードベースとして0.0.0から始めるのが
誠実だと判断した。詳細はCHANGELOG.md [0.0.0a0] を参照)
"""

__version__ = "0.0.0a0"
__codename__ = "fox-webusb"
