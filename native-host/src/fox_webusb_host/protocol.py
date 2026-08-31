# -*- coding: utf-8 -*-
"""
protocol.py
===========
Firefoxのネイティブメッセージングの生ワイヤ形式(stdin/stdoutを使い、各メッセージの
前に4バイトのネイティブバイトオーダー長を置く)の読み書きと、その上に乗せる
「チャンク分割」レイヤーを提供する。

なぜチャンク分割が要るか:
  MDN (developer.mozilla.org/.../Native_messaging, 2026年8月時点で確認) は
  「ホスト→拡張機能方向の1メッセージの最大サイズは1MB」「拡張機能→ホスト方向は
  最大4GB」と明記している。移植元(pyside6-webusb)の bulkTransferIn は最大64MiB
  (BULK_TRANSFER_MAX_LENGTH, hardening.py)まで許可しており、base64化すると
  約85MBになりうる — これはホスト→拡張機能方向で送るとFirefox側の1MB上限に
  抵触する(実際に "Native application tried to send a message of N bytes,
  which exceeds the limit of 1048576 bytes" というエラーになる。Mozilla Discourse
  等で複数件報告例あり)。

  対策として、ホスト→拡張機能方向のメッセージだけ、次の2段構えのエンベロープで
  送る:
    1. 送りたい論理メッセージ(dict)を1回 json.dumps() してUTF-8バイト列にする。
    2. それを base64 化する(base64は必ずASCII、つまり文字数=バイト数になるため、
       「マルチバイト文字の境界を跨いで安全に分割できるか」を気にせず単純な
       文字数スライスでチャンクに切れる。多バイト文字を含みうるのは製品名等の
       USB文字列記述子由来のフィールドだが、base64化した時点で全て安全なASCIIに
       正規化されるので、分割位置に関する特別な配慮が一切不要になる)。
    3. 700,000文字ずつ(Firefoxの1MB上限に対して十分な余裕を持たせた値)に
       分割し、{"seq":i, "total":N, "part": <断片>} という形の"小さい"
       ネイティブメッセージを複数回、stdout の書き込みロックを保持したまま
       (=他のスレッドの送信と絶対に混ざらない状態で)連続して送る。
    4. 拡張機能側(background.js)は同じロジックで断片を連結し、base64を
       デコードしてから元のJSON文字列を復元する。

  拡張機能→ホスト方向(4GB上限)はこの分割が要らないほど余裕があるため、
  browser.runtime.Port.postMessage() がFirefox本体側で組み立てる生のワイヤ
  形式をそのまま1メッセージとして読むだけでよい(read_message()参照)。
"""
import base64
import json
import struct
import sys
import threading

# ホスト→拡張機能方向、1チャンクあたりの文字数(base64後、つまりバイト数と等しい)。
# Firefoxの1,048,576バイト上限に対して十分な余白を持たせてある
# (エンベロープ自体のJSON構造化文字が数十バイト乗るだけなので、700,000は
# 安全側にかなり余裕を持たせた値)。
CHUNK_SIZE = 700_000

_stdout_lock = threading.Lock()


def read_message():
    """拡張機能(browser.runtime.Port経由)から届いた1メッセージを読み、
    dictとして返す。ストリームが閉じられた(=拡張機能が切断した)場合はNoneを返す。"""
    raw_length = _read_exact(sys.stdin.buffer, 4)
    if raw_length is None:
        return None
    (message_length,) = struct.unpack("@I", raw_length)
    if message_length == 0:
        return {}
    raw_message = _read_exact(sys.stdin.buffer, message_length)
    if raw_message is None:
        return None
    return json.loads(raw_message.decode("utf-8"))


def _read_exact(stream, n):
    """ちょうどnバイト読むまでブロックする。EOFに達したらNoneを返す。
    io.BufferedReader.read(n) は「nバイト読めるまで、あるいはEOFまで内部で
    繰り返し読む」ことがPythonのドキュメントで保証されているため、本来は
    1回の呼び出しで十分だが、念のため明示的なループにしておく
    (MDNのサンプルコードもsys.stdin.buffer.read(messageLength)を1回呼ぶだけの
    形になっており、それに準拠しつつ多重防御している)。"""
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _write_raw(obj):
    encoded = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("@I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def send_message(obj):
    """objを拡張機能へ送る。上記docstring記載のとおり、base64化した上で
    CHUNK_SIZEごとに分割した{"seq","total","part"}エンベロープを複数回
    送ることで、Firefoxのホスト→拡張機能1MB上限を透過的に回避する。

    stdoutの書き込みは全体をロックで囲み、複数スレッド(ワーカースレッドの
    レスポンス送信・ホットプラグ監視スレッドのイベント送信)が同時に
    send_message()を呼んでも、1つの論理メッセージのチャンク列が別の
    呼び出しのチャンクと混ざらないことを保証する。"""
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")
    total = max(1, (len(b64) + CHUNK_SIZE - 1) // CHUNK_SIZE)
    with _stdout_lock:
        for seq in range(total):
            part = b64[seq * CHUNK_SIZE:(seq + 1) * CHUNK_SIZE]
            _write_raw({"seq": seq, "total": total, "part": part})
