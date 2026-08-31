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
