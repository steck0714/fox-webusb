# -*- coding: utf-8 -*-
"""
fox-webusb ネイティブメッセージングホスト。

移植元 pyside6-webusb (v0.0.4b0) の「PySide6/QtWebEngineアプリにnavigator.usb
ポリフィルを注入するQtブリッジ」を、「Firefox拡張機能から起動される、
ブラウザ本体とは独立したネイティブメッセージングホスト」として書き直したもの。
詳しい設計についてはリポジトリ直下のREADME.md、および bridge.py 冒頭の
docstringを参照。

コードネーム: fox-webusb
バージョン: 0.0.0.2 (v0.0.0a1に残っていたFirefoxアドオンlinter
[web-ext lint/AMOのvalidator]の警告[VERSION_FORMAT_DEPRECATED: Manifest
V3以降で使えなくなる英字入りバージョン文字列]を解消するための修正リリース。
機能面はv0.0.0a1から変更なし([0.0.0.1]でinnerHTMLへの動的な値の代入等は
既に解消済みだったため、残っていたのはバージョン文字列のみ)。バージョン
文字列自体から英字を排除する必要があったため、"a1"のような接尾辞ではなく
4つ目の数字セグメントで表現している。Firefoxのバージョン比較規則
[未指定の末尾セグメントは0として扱われる]上、0.0.0.2は0.0.0.1より新しく
0.0.1より古い、というv0.0.0a1と同じ「0.0.0の直後・0.0.1の手前」という
位置づけを保っている。詳細はCHANGELOG.md [0.0.0.2] を参照)
"""

__version__ = "0.0.0.2"
__codename__ = "fox-webusb"
