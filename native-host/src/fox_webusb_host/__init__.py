# -*- coding: utf-8 -*-
"""
fox-webusb ネイティブメッセージングホスト。

移植元 pyside6-webusb (v0.0.4b0) の「PySide6/QtWebEngineアプリにnavigator.usb
ポリフィルを注入するQtブリッジ」を、「Firefox拡張機能から起動される、
ブラウザ本体とは独立したネイティブメッセージングホスト」として書き直したもの。
詳しい設計についてはリポジトリ直下のREADME.md、および bridge.py 冒頭の
docstringを参照。

コードネーム: fox-webusb
バージョン: 0.0.0.3 (GitHubタグ表記: v0.0.0a2+。fox-webusbがFirefoxアドオン
として正式に許諾されたことを受けての、pip installまわりの安定化・機能追加
リリース。0.0.0.1/0.0.0.2はコンプライアンスのみの無挙動修正だったため
v0.0.0a1のまま扱われたが、本リリースは新しい振る舞い(環境診断ツール
fox-webusb-host-doctor の追加、install.pyのpip install連携の見直し)を
追加するため、姉妹プロジェクトpyside6-webusbの0.0.5a0エントリと同じ理由
[「単なるパッチではなく振る舞いを追加するのでアルファ番号を進める」]で
GitHubタグ側のアルファ番号を a1 → a2 へ進めている。manifest.jsonのバージョン
文字列自体は0.0.0.1/0.0.0.2と同じ理由(Firefoxの仕様上、英字を含められない)
により、GitHubタグとは独立に、単純な4番目のセグメントの継続として
0.0.0.3としている——0.0.0.2は0.0.0.1より新しく0.0.1より古い、という
位置づけを保ったまま。詳細はCHANGELOG.md [0.0.0.3] を参照)
"""

__version__ = "0.0.0.3"
__codename__ = "fox-webusb"
