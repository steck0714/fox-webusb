# -*- coding: utf-8 -*-
"""test_errors.py: errors.pyはfox-webusbへの移植でも一切変更していない
(Qt非依存の純粋ロジックだったため)ので、検証内容も移植元と同じ。"""
from fox_webusb_host.errors import (
    security_error, invalid_state_error, not_found_error,
    invalid_access_error, index_size_error,
)
# safe_error_str は制御文字の除去・長さ上限といった「例外文字列の無害化」を
# 担うため、DOMException接頭辞のビルダー集であるerrors.pyではなく
# hardening.pyに置いている(このファイルのテストはtest_hardening.py側)。


def test_each_builder_uses_the_correct_prefix():
    assert security_error("x").startswith("SecurityError:")
    assert invalid_state_error("x").startswith("InvalidStateError:")
    assert not_found_error("x").startswith("NotFoundError:")
    assert invalid_access_error("x").startswith("InvalidAccessError:")
    assert index_size_error("x").startswith("IndexSizeError:")
    print("test_each_builder_uses_the_correct_prefix: OK")


def test_message_is_preserved_after_the_prefix():
    assert security_error("nope") == "SecurityError: nope"
    print("test_message_is_preserved_after_the_prefix: OK")



