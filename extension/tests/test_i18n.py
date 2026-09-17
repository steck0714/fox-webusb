# -*- coding: utf-8 -*-
"""i18n.py (chooser_dialog.py向け簡易翻訳テーブル) のテスト。"""
from fox_webusb_host.i18n import translate


def test_translate_returns_correct_language_for_each_supported_locale():
    assert translate("en", "connectButton") == "Connect"
    assert translate("ja", "connectButton") == "接続"
    assert translate("zh_CN", "connectButton") == "连接"
    print("test_translate_returns_correct_language_for_each_supported_locale: OK")


def test_translate_falls_back_to_english_for_unrecognized_locale():
    assert translate("fr", "connectButton") == "Connect"
    assert translate("xx-YY", "connectButton") == "Connect"
    print("test_translate_falls_back_to_english_for_unrecognized_locale: OK")


def test_translate_falls_back_to_english_when_locale_is_none():
    assert translate(None, "connectButton") == "Connect"
    print("test_translate_falls_back_to_english_when_locale_is_none: OK")


def test_translate_normalizes_hyphenated_and_regioned_locale_codes():
    # ブラウザ側は "zh-CN" (ハイフン)で渡してくる可能性がある一方、
    # このテーブル自体は "zh_CN" (アンダースコア)で保持している。
    assert translate("zh-CN", "cancelButton") == translate("zh_CN", "cancelButton")
    # 地域サブタグ付きの日本語("ja-JP"、通常は起こらないがフォーマットとしてはあり得る)
    assert translate("ja-JP", "cancelButton") == translate("ja", "cancelButton")
    print("test_translate_normalizes_hyphenated_and_regioned_locale_codes: OK")


def test_translate_substitutes_placeholders():
    assert "{" not in translate("en", "unknownDevice", vid_pid="1234:abcd")
    assert "1234:abcd" in translate("en", "unknownDevice", vid_pid="1234:abcd")
    assert "3" in translate("ja", "connectedNTimesBefore", count=3)
    print("test_translate_substitutes_placeholders: OK")


def test_translate_returns_the_key_itself_for_an_unknown_key_rather_than_raising():
    # KeyErrorで落とすより、ユーザーから見て「翻訳が抜けている」ことが分かる形
    # (キー文字列そのもの)を返す方が安全側、というi18n.py自身の設計方針。
    result = translate("en", "thisKeyDoesNotExist")
    assert result == "thisKeyDoesNotExist"
    print("test_translate_returns_the_key_itself_for_an_unknown_key_rather_than_raising: OK")


def test_all_three_locales_define_the_exact_same_set_of_keys():
    # 🛡️ 1つの言語にだけキーを足し忘れる、というありがちなi18nの劣化を防ぐ
    # 回帰テスト。_MESSAGESの内部辞書に直接アクセスして検証する。
    from fox_webusb_host import i18n
    key_sets = {locale: set(table.keys()) for locale, table in i18n._MESSAGES.items()}
    reference = key_sets["en"]
    for locale, keys in key_sets.items():
        assert keys == reference, f"{locale} のキー集合がenと一致しない: 差分={keys.symmetric_difference(reference)}"
    print("test_all_three_locales_define_the_exact_same_set_of_keys: OK")
