# -*- coding: utf-8 -*-
"""
i18n.py
========
chooser_dialog.py(Tkinter、ネイティブホスト側のGUI)向けの、ごく簡易な
翻訳テーブル。

なぜこれが必要か: 拡張機能側(popup/options)は標準のWebExtensions i18n API
(`browser.i18n`、`_locales/*/messages.json`)を使えるが、ネイティブホストは
Firefox本体から独立した別プロセスのPythonプログラムであり、`browser.i18n`
相当の仕組みを持たない。チューザーダイアログの表示言語をFirefox本体のUI言語に
合わせるため、`browser.i18n.getUILanguage()`の結果をbridge.pyの
request_device_chooser()経由でここまで渡してもらい(あくまで表示上の好みで
あって、認可判定には一切使わない——bridge.pyのdocstring参照)、対応する
翻訳を返す。

対応言語は `_locales/` (拡張機能側)と同じ ja / en / zh_CN の3つ。それ以外の
localeを渡された場合、またはlocaleが渡されなかった場合は既定で英語
(chooser_dialog.py の元々の言語)にフォールバックする。

キー自体が見つからない場合は、キー文字列そのものをそのまま返す
(「翻訳が抜けている」ことが分かるようにするため。KeyErrorで落とすよりは
ユーザーに見える形で不完全さを示す方が安全側だという判断)。
"""

_MESSAGES = {
    "en": {
        "chooserTitle": "Connect a USB device",
        "unknownOrigin": "(unknown origin)",
        "trustReminder": "wants to connect to a USB device. Only choose a device you "
                          "recognize and trust — the site will be able to send and "
                          "receive raw data with it.",
        "columnDevice": "Device",
        "columnDetails": "Details",
        "noSelection": "No device selected yet.",
        "connectButton": "Connect",
        "cancelButton": "Cancel",
        "unknownDevice": "Unknown device ({vid_pid})",
        "connectedOnceBefore": "connected before",
        "connectedNTimesBefore": "connected {count}x before",
    },
    "ja": {
        "chooserTitle": "USBデバイスへの接続",
        "unknownOrigin": "(不明なオリジン)",
        "trustReminder": "USBデバイスへの接続を求めています。信頼できると分かって"
                          "いるデバイスだけを選んでください——選択すると、そのサイトは"
                          "このデバイスと生のデータを送受信できるようになります。",
        "columnDevice": "デバイス",
        "columnDetails": "詳細",
        "noSelection": "まだデバイスが選択されていません。",
        "connectButton": "接続",
        "cancelButton": "キャンセル",
        "unknownDevice": "不明なデバイス ({vid_pid})",
        "connectedOnceBefore": "接続履歴あり",
        "connectedNTimesBefore": "{count}回接続履歴あり",
    },
    "zh_CN": {
        "chooserTitle": "连接 USB 设备",
        "unknownOrigin": "(未知来源)",
        "trustReminder": "请求连接一个 USB 设备。请仅选择您认识且信任的设备——"
                          "选择后,该网站将能够与此设备收发原始数据。",
        "columnDevice": "设备",
        "columnDetails": "详情",
        "noSelection": "尚未选择设备。",
        "connectButton": "连接",
        "cancelButton": "取消",
        "unknownDevice": "未知设备 ({vid_pid})",
        "connectedOnceBefore": "之前连接过",
        "connectedNTimesBefore": "之前连接过 {count} 次",
    },
}

_DEFAULT_LOCALE = "en"


def _resolve_locale(locale):
    """'ja', 'ja-JP', 'zh-CN', 'zh_CN' 等、Firefoxが渡してくる可能性のある
    表記のゆれを吸収して、_MESSAGESのキーに正規化する。一致するものが
    無ければ既定言語にフォールバックする。"""
    if not locale:
        return _DEFAULT_LOCALE
    normalized = locale.replace("-", "_")
    if normalized in _MESSAGES:
        return normalized
    # "zh_CN_x" のような細かいバリアント違いや "ja_JP" のような地域付き表記は、
    # 言語部分(最初のセグメント)だけで再度マッチを試みる。
    primary = normalized.split("_")[0]
    for candidate in _MESSAGES:
        if candidate == primary or candidate.split("_")[0] == primary:
            return candidate
    return _DEFAULT_LOCALE


def translate(locale, key, **kwargs):
    """localeに対応するメッセージを返す(無ければ既定言語、それでも無ければ
    キー自身)。kwargsは{name}形式のプレースホルダに .format() で埋め込む。"""
    resolved = _resolve_locale(locale)
    table = _MESSAGES.get(resolved, _MESSAGES[_DEFAULT_LOCALE])
    template = table.get(key) or _MESSAGES[_DEFAULT_LOCALE].get(key) or key
    try:
        return template.format(**kwargs) if kwargs else template
    except (KeyError, IndexError):
        return template
