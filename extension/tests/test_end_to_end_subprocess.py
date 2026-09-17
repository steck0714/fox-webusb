# -*- coding: utf-8 -*-
"""
test_end_to_end_subprocess.py
==============================
`python -m fox_webusb_host` を実際に別プロセスとして起動し、Firefoxの
ネイティブメッセージングと全く同じワイヤ形式(4バイト長 + JSON、応答は
base64チャンク分割)でやり取りする統合テスト。unittestの単体テスト
(test_bridge.py等)がbridge.pyのロジックを直接検証するのに対し、これは
「実プロセス境界を挟んでも本当に動くか」を検証する——protocol.pyの
フレーミング実装ミスや、__main__.pyのスレッド配線ミスは単体テストでは
見えないことがあるため。

実機のUSBデバイスは無い環境で実行される前提なので、ここで検証できるのは
「起動する」「診断用メソッドが正しく往復する」「未知メソッド/信頼チェックが
正しく機能する」等、ハードウェア非依存の範囲に限る。
"""
import base64
import json
import os
import struct
import subprocess
import sys
import time


NATIVE_HOST_DIR = os.path.join(os.path.dirname(__file__), "..", "native-host")


def _send(proc, obj):
    encoded = json.dumps(obj).encode("utf-8")
    proc.stdin.write(struct.pack("@I", len(encoded)))
    proc.stdin.write(encoded)
    proc.stdin.flush()


def _read_one_logical_message(proc, timeout=10):
    """チャンク分割されたレスポンスを1つ、完全に読んで結合する。"""
    deadline = time.time() + timeout
    parts = []
    total = None
    while True:
        if time.time() > deadline:
            raise TimeoutError("timed out waiting for a response from the native host")
        raw_len = proc.stdout.read(4)
        if len(raw_len) < 4:
            raise EOFError("native host closed stdout unexpectedly")
        (length,) = struct.unpack("@I", raw_len)
        raw = proc.stdout.read(length)
        chunk = json.loads(raw.decode("utf-8"))
        if chunk["seq"] == 0:
            parts = []
            total = chunk["total"]
        parts.append(chunk["part"])
        if len(parts) == total:
            b64 = "".join(parts)
            return json.loads(base64.b64decode(b64).decode("utf-8"))


def test_native_host_subprocess_responds_to_diagnostics():
    proc = subprocess.Popen(
        [sys.executable, "-m", "fox_webusb_host"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=NATIVE_HOST_DIR,
    )
    try:
        _send(proc, {"id": "1", "method": "diagnostics", "origin": None, "trusted": True, "params": {}})
        response = _read_one_logical_message(proc)
        assert response["id"] == "1"
        assert response["type"] == "response"
        assert response["success"] is True
        assert "deviceCount" in response
        assert "rustAccel" in response
        print("test_native_host_subprocess_responds_to_diagnostics: OK")
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)


def test_native_host_subprocess_rejects_untrusted_trusted_only_call():
    proc = subprocess.Popen(
        [sys.executable, "-m", "fox_webusb_host"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=NATIVE_HOST_DIR,
    )
    try:
        _send(proc, {"id": "1", "method": "listGrantedOrigins", "origin": None, "trusted": False, "params": {}})
        response = _read_one_logical_message(proc)
        assert response["success"] is False
        assert response["error"].startswith("SecurityError")
        print("test_native_host_subprocess_rejects_untrusted_trusted_only_call: OK")
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)


def test_native_host_subprocess_reports_unknown_method():
    proc = subprocess.Popen(
        [sys.executable, "-m", "fox_webusb_host"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=NATIVE_HOST_DIR,
    )
    try:
        _send(proc, {"id": "42", "method": "thisMethodDoesNotExist", "origin": "https://example.com", "trusted": False, "params": {}})
        response = _read_one_logical_message(proc)
        assert response["id"] == "42"
        assert response["success"] is False
        assert response["error"].startswith("NotFoundError")
        print("test_native_host_subprocess_reports_unknown_method: OK")
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)


def test_native_host_subprocess_handles_many_concurrent_requests():
    """スレッドプールで複数リクエストを並行処理できること、かつ全てに
    正しくレスポンスが返ることを、実プロセス越しに確認する。"""
    proc = subprocess.Popen(
        [sys.executable, "-m", "fox_webusb_host"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=NATIVE_HOST_DIR,
    )
    try:
        n = 20
        for i in range(n):
            _send(proc, {"id": str(i), "method": "diagnostics", "origin": None, "trusted": True, "params": {}})
        seen_ids = set()
        for _ in range(n):
            response = _read_one_logical_message(proc)
            seen_ids.add(response["id"])
        assert seen_ids == {str(i) for i in range(n)}
        print("test_native_host_subprocess_handles_many_concurrent_requests: OK")
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)


def test_native_host_exits_cleanly_when_stdin_closes():
    proc = subprocess.Popen(
        [sys.executable, "-m", "fox_webusb_host"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=NATIVE_HOST_DIR,
    )
    proc.stdin.close()
    exit_code = proc.wait(timeout=5)
    assert exit_code == 0
    print("test_native_host_exits_cleanly_when_stdin_closes: OK")
