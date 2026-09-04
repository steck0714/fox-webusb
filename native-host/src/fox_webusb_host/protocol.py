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

なぜ ensure_binary_stdio() が要るか(v0.0.0a0で追加。実機報告に基づく修正):
  実際にWindows上のLibreWolf(Firefox系ブラウザ)でこのホストを動かした
  検証(checklog.md)で、requestDevice()呼び出しの最中にネイティブホストが
  切断される不具合が報告された。原因はこのモジュール固有の実装ミスで、
  Windows特有の「標準入出力の既定モード」に起因するフレーミング破損だった
  と判断している。詳細は ensure_binary_stdio() のdocstringを参照。
  __main__.py の main() は、標準入出力へ1バイトも触れる前に必ずこの関数を
  呼ぶ(呼び忘れるとWindows上で本モジュールが正しく動作しない)。
"""
import base64
import json
import os
import struct
import sys
import threading

# ホスト→拡張機能方向、1チャンクあたりの文字数(base64後、つまりバイト数と等しい)。
# Firefoxの1,048,576バイト上限に対して十分な余白を持たせてある
# (エンベロープ自体のJSON構造化文字が数十バイト乗るだけなので、700,000は
# 安全側にかなり余裕を持たせた値)。
CHUNK_SIZE = 700_000

# 🛡️ v0.0.0a0: 拡張機能→ホスト方向で受け取る1メッセージの長さプレフィックスに
# 対する上限。これを超える値が来たら「本物の巨大なリクエスト」ではなく
# 「フレーミングが壊れている(下記ensure_binary_stdio()参照)」と判断し、
# 実際に読もうとする前に早期にエラーとして扱う。
#
# 実測に基づく根拠: このプロジェクトが単一メッセージとして受け取りうる
# 最大の正当なペイロードは、bulkTransferOut/controlTransferOutの
# BULK_TRANSFER_MAX_LENGTH=64MiB相当のUSBデータをbase64化したもの
# (約85.4MiB)+ JSON構造のオーバーヘッド。これに十分な余裕を持たせて
# 128MiBを上限とする。実機環境からの report (checklog.md,
# LibreWolf/Windows) で "cannot read more than 33554432 bytes" という
# フレーミング破損由来とみられるエラーが観測されたため追加した安全網であり、
# 根本原因そのものはensure_binary_stdio()側で別途対処する。
MAX_INCOMING_MESSAGE_BYTES = 128 * 1024 * 1024

_stdout_lock = threading.Lock()
_binary_stdio_ensured = False


def ensure_binary_stdio():
    """Windows特有の落とし穴への対処: Windows上のPythonでは、stdin/stdoutの
    ファイルディスクリプタは(Pythonのio層が`.buffer`経由でバイト列を渡して
    くれるにもかかわらず)既定でMS-DOS由来の「テキストモード」のまま残っている
    ことがある。これはPythonのio.TextIOWrapperが行う改行変換
    (`sys.stdin`自体の話。`.buffer`にアクセスすればこの層は素通りできる)とは
    別の、Windows Cランタイム(msvcrt)がファイルディスクリプタ番号そのものに
    対して保持している、もう1段階下のモードフラグである。
    このモードが「テキスト」のままだと、`.buffer`経由で読み書きしていても
    なお:
      - 0x0D 0x0A (CRLF) の並びが 0x0A 1バイトへ黙って書き換えられる
      - 読み取り中に 0x1A (Ctrl-Z, 伝統的なMS-DOSのEOFマーカー) に出会うと、
        実際にはまだデータが続いていてもそこでストリーム終端とみなされる
    という、このプロジェクトが使う「4バイト長プレフィックス + 生バイト列」
    という形式のプロトコルにとって致命的な破損が起こりうる。長さプレフィックス
    のたった1バイトがこれに該当するだけで、以降のフレーミングが丸ごと
    ずれてしまう(実機での報告 checklog.md 参照: 小さいメッセージ
    [getDevices()等]はたまたま巻き込まれず動いたが、あるメッセージ長で
    運悪く踏んでしまうと、以降の読み取りが全て壊れた長さ値を掴む形で
    破綻する、という形で観測結果と整合する)。

    対処は、標準ライブラリの`msvcrt.setmode()`でこのCランタイムレベルの
    フラグを明示的に`O_BINARY`へ切り替えるだけでよい
    (Chromeの公式ネイティブメッセージングサンプル
    [GoogleChrome/chrome-extensions-samples] や、長年のPython on Windowsの
    定石として広く知られる対処そのもの)。標準入出力を1バイトも読み書きする
    前に、プロセス起動直後に1度だけ呼ぶ必要がある。Windows以外では何もしない
    (安全に繰り返し呼んでもよい、冪等な操作)。"""
    global _binary_stdio_ensured
    if _binary_stdio_ensured:
        return
    if sys.platform == "win32":
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    _binary_stdio_ensured = True


def read_message():
    """拡張機能(browser.runtime.Port経由)から届いた1メッセージを読み、
    dictとして返す。ストリームが閉じられた(=拡張機能が切断した)場合はNoneを返す。"""
    raw_length = _read_exact(sys.stdin.buffer, 4)
    if raw_length is None:
        return None
    (message_length,) = struct.unpack("@I", raw_length)
    if message_length == 0:
        return {}
    if message_length > MAX_INCOMING_MESSAGE_BYTES:
        # 🛡️ 実際に読もうとする前に諦める。フレーミングが壊れている
        # (ensure_binary_stdio()参照)場合、この値は事実上ランダムな
        # 4バイトなので、際限なく大きい・読み進めても絶対に終わらない
        # 値になりうる。ここで早期に、分かりやすい例外として失敗させる。
        raise ValueError(
            f"refusing to read a {message_length}-byte message "
            f"(exceeds MAX_INCOMING_MESSAGE_BYTES={MAX_INCOMING_MESSAGE_BYTES}); "
            f"the native-messaging stream is likely corrupted or desynchronized"
        )
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
