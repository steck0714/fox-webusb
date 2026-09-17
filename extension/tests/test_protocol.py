# -*- coding: utf-8 -*-
"""test_protocol.py: ネイティブメッセージングの生ワイヤ形式(4バイト長 + JSON)の
読み書きと、Firefoxのホスト→拡張機能1MB上限を回避するためのチャンク分割
エンベロープを検証する。sys.stdin.buffer/sys.stdout.bufferをBytesIOへ
差し替えることで、実際のパイプ無しにワイヤフォーマットを直接検証できる。"""
import base64
import io
import json
import struct

import fox_webusb_host.protocol as protocol


class _FakeStdin:
    def __init__(self, data: bytes):
        self.buffer = io.BytesIO(data)


class _FakeStdout:
    """sys.stdoutを丸ごと差し替えるので、protocol.py が使う.bufferだけでなく、
    テスト自身の print(...) が使うテキストの write()/flush() も生えていないと
    print() 自体がAttributeErrorで落ちてしまう(pytestは実stdoutをキャプチャする
    ラッパーに差し替えるが、ここでさらにこちらのフェイクへ上書きしているため)。"""

    def __init__(self):
        self.buffer = io.BytesIO()

    def write(self, _s):
        pass

    def flush(self):
        pass


def _encode_frames(messages):
    """テスト用: read_message()に読ませる生バイト列を組み立てる。"""
    out = b""
    for msg in messages:
        encoded = json.dumps(msg).encode("utf-8")
        out += struct.pack("@I", len(encoded)) + encoded
    return out


def test_read_message_parses_one_frame(monkeypatch):
    monkeypatch.setattr(protocol.sys, "stdin", _FakeStdin(_encode_frames([{"hello": "world"}])))
    msg = protocol.read_message()
    assert msg == {"hello": "world"}
    print("test_read_message_parses_one_frame: OK")


def test_read_message_returns_none_at_eof(monkeypatch):
    monkeypatch.setattr(protocol.sys, "stdin", _FakeStdin(b""))
    assert protocol.read_message() is None
    print("test_read_message_returns_none_at_eof: OK")


def test_read_message_handles_multiple_frames_in_sequence(monkeypatch):
    monkeypatch.setattr(protocol.sys, "stdin", _FakeStdin(_encode_frames([{"a": 1}, {"b": 2}])))
    assert protocol.read_message() == {"a": 1}
    assert protocol.read_message() == {"b": 2}
    assert protocol.read_message() is None
    print("test_read_message_handles_multiple_frames_in_sequence: OK")


def _decode_all_frames(raw: bytes):
    frames = []
    offset = 0
    while offset < len(raw):
        (length,) = struct.unpack_from("@I", raw, offset)
        offset += 4
        frames.append(json.loads(raw[offset:offset + length]))
        offset += length
    return frames


def _reassemble(frames):
    frames_sorted = sorted(frames, key=lambda f: f["seq"])
    b64 = "".join(f["part"] for f in frames_sorted)
    raw = base64.b64decode(b64)
    return json.loads(raw.decode("utf-8"))


def test_send_message_small_payload_is_a_single_chunk(monkeypatch):
    fake_out = _FakeStdout()
    monkeypatch.setattr(protocol.sys, "stdout", fake_out)
    protocol.send_message({"hello": "world"})
    frames = _decode_all_frames(fake_out.buffer.getvalue())
    assert len(frames) == 1
    assert frames[0]["seq"] == 0 and frames[0]["total"] == 1
    assert _reassemble(frames) == {"hello": "world"}
    print("test_send_message_small_payload_is_a_single_chunk: OK")


def test_send_message_large_payload_is_split_into_multiple_chunks(monkeypatch):
    fake_out = _FakeStdout()
    monkeypatch.setattr(protocol.sys, "stdout", fake_out)
    # base64後に CHUNK_SIZE(700,000文字) を確実に超えるサイズにする
    big_data = "A" * 2_000_000
    protocol.send_message({"data": big_data})
    frames = _decode_all_frames(fake_out.buffer.getvalue())
    assert len(frames) > 1
    assert all(f["total"] == len(frames) for f in frames)
    assert [f["seq"] for f in frames] == list(range(len(frames)))
    # 個々のフレームがFirefoxの1MB上限を大きく下回っていること
    for f in frames:
        assert len(json.dumps(f).encode("utf-8")) < 1_000_000
    reassembled = _reassemble(frames)
    assert reassembled["data"] == big_data
    print("test_send_message_large_payload_is_split_into_multiple_chunks: OK")


def test_send_message_round_trips_non_ascii_strings(monkeypatch):
    """USB文字列記述子由来の日本語プロダクト名等が壊れずに往復することを確認する
    (base64でラップしてから分割するため、マルチバイト文字の境界を跨ぐ分割でも
    安全であることが肝)。"""
    fake_out = _FakeStdout()
    monkeypatch.setattr(protocol.sys, "stdout", fake_out)
    payload = {"productName": "日本語のプロダクト名 🦊", "manufacturerName": "テスト製造者"}
    protocol.send_message(payload)
    frames = _decode_all_frames(fake_out.buffer.getvalue())
    assert _reassemble(frames) == payload
    print("test_send_message_round_trips_non_ascii_strings: OK")


def test_chunk_boundary_can_fall_inside_a_multibyte_character(monkeypatch):
    """CHUNK_SIZEを一時的に小さくして、意図的にマルチバイト文字の途中で
    チャンク境界を跨がせても壊れないことを確認する。"""
    monkeypatch.setattr(protocol, "CHUNK_SIZE", 5)
    fake_out = _FakeStdout()
    monkeypatch.setattr(protocol.sys, "stdout", fake_out)
    payload = {"text": "日本語テスト文字列アイウエオ"}
    protocol.send_message(payload)
    frames = _decode_all_frames(fake_out.buffer.getvalue())
    assert len(frames) > 1
    assert _reassemble(frames) == payload
    print("test_chunk_boundary_can_fall_inside_a_multibyte_character: OK")


def test_send_message_is_thread_safe_and_does_not_interleave(monkeypatch):
    import threading

    fake_out = _FakeStdout()
    monkeypatch.setattr(protocol.sys, "stdout", fake_out)
    monkeypatch.setattr(protocol, "CHUNK_SIZE", 20)  # 小さくして各メッセージが複数チャンクに割れるようにする

    def send(tag):
        protocol.send_message({"tag": tag, "data": tag * 200})

    threads = [threading.Thread(target=send, args=(f"T{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    frames = _decode_all_frames(fake_out.buffer.getvalue())
    # 各メッセージのチャンク列が連続しており、他のメッセージのチャンクと
    # 混ざっていないことを確認する: seq==0から始まるグループごとに区切って
    # 再構成し、8個とも正しくJSONへ戻ることを検証する。
    groups = []
    current = []
    for f in frames:
        if f["seq"] == 0 and current:
            groups.append(current)
            current = []
        current.append(f)
    if current:
        groups.append(current)
    assert len(groups) == 8
    tags_seen = set()
    for group in groups:
        obj = _reassemble(group)
        assert obj["data"] == obj["tag"] * 200
        tags_seen.add(obj["tag"])
    assert tags_seen == {f"T{i}" for i in range(8)}
    print("test_send_message_is_thread_safe_and_does_not_interleave: OK")


def test_ensure_binary_stdio_is_idempotent_and_safe_on_non_windows(monkeypatch):
    """🆕 v0.0.0a0 (checklog.md, Windows/LibreWolfでの実機報告に基づく修正):
    ensure_binary_stdio()は複数回呼んでも安全(2回目以降は何もしない)で、
    Windows以外のプラットフォームでは無条件に無害(msvcrtの呼び出し自体を
    一切試みない)ことを確認する。実際のmsvcrt.setmode()呼び出しそのものの
    検証はWindows実機でしかできないため、ここでは「呼び出し回数・分岐」の
    ロジックだけを検証する。"""
    monkeypatch.setattr(protocol, "_binary_stdio_ensured", False)
    monkeypatch.setattr(protocol.sys, "platform", "linux")
    protocol.ensure_binary_stdio()
    assert protocol._binary_stdio_ensured is True
    protocol.ensure_binary_stdio()  # 2回目もエラーにならないこと
    print("test_ensure_binary_stdio_is_idempotent_and_safe_on_non_windows: OK")


def test_ensure_binary_stdio_calls_msvcrt_setmode_on_windows(monkeypatch):
    """🆕 v0.0.0a0: win32と判定された場合に、実際にmsvcrt.setmode()が
    stdin/stdout双方のファイル記述子に対してO_BINARYで呼ばれることを確認する。
    実機のWindowsが無い環境でも、msvcrtモジュール自体をフェイクに差し替える
    ことでロジックを検証できる(msvcrtはWindows専用の標準ライブラリモジュール
    であり、Linux上のPythonには存在しないため、sys.modulesへ直接フェイクを
    登録する)。"""
    monkeypatch.setattr(protocol, "_binary_stdio_ensured", False)
    monkeypatch.setattr(protocol.sys, "platform", "win32")
    # os.O_BINARY はWindows専用の定数で、Linux上のPythonには存在しない。
    # ここでは「win32だと判定された場合の分岐ロジック」だけを検証したいので、
    # 実際の値(Windows上では0x8000)を模した値を一時的に生やしておく。
    monkeypatch.setattr(protocol.os, "O_BINARY", 0x8000, raising=False)

    calls = []

    class _FakeMsvcrt:
        @staticmethod
        def setmode(fd, mode):
            calls.append((fd, mode))

    import sys as _sys
    monkeypatch.setitem(_sys.modules, "msvcrt", _FakeMsvcrt())

    class _FakeStreamWithFileno:
        def fileno(self):
            return 0

        def write(self, _s):
            pass

        def flush(self):
            pass

    monkeypatch.setattr(protocol.sys, "stdin", _FakeStreamWithFileno())
    monkeypatch.setattr(protocol.sys, "stdout", _FakeStreamWithFileno())

    protocol.ensure_binary_stdio()
    assert len(calls) == 2
    assert all(mode == protocol.os.O_BINARY for _fd, mode in calls)
    print("test_ensure_binary_stdio_calls_msvcrt_setmode_on_windows: OK")


def test_read_message_rejects_absurdly_large_length_prefix(monkeypatch):
    """🆕 v0.0.0a0 (checklog.md, "cannot read more than 33554432 bytes" 相当の
    症状に対する安全網): 壊れた/デシンクしたストリームは長さプレフィックスが
    事実上ランダムな値になりうる。実際に読もうとして延々ブロックしたり、
    巨大なメモリ確保を試みたりする前に、早期に分かりやすいValueErrorとして
    失敗することを確認する。"""
    huge_length = protocol.MAX_INCOMING_MESSAGE_BYTES + 1
    raw = struct.pack("@I", huge_length)
    monkeypatch.setattr(protocol.sys, "stdin", _FakeStdin(raw))
    try:
        protocol.read_message()
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "refusing to read" in str(e)
    print("test_read_message_rejects_absurdly_large_length_prefix: OK")


def test_read_message_accepts_normal_sized_message_under_the_cap(monkeypatch):
    """上限より十分小さい正当なメッセージは引き続き問題なく読めることの
    回帰確認(上限チェックが正当なメッセージまで巻き込んで拒否しないこと)。"""
    payload = {"hello": "world"}
    encoded = json.dumps(payload).encode("utf-8")
    raw = struct.pack("@I", len(encoded)) + encoded
    monkeypatch.setattr(protocol.sys, "stdin", _FakeStdin(raw))
    assert protocol.read_message() == payload
    print("test_read_message_accepts_normal_sized_message_under_the_cap: OK")
