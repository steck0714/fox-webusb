# -*- coding: utf-8 -*-
"""
__main__.py
===========
fox-webusb ネイティブメッセージングホストのエントリーポイント。
`python3 -m fox_webusb_host` として起動される想定(ネイティブメッセージングの
マニフェストのpathは、これを起動する小さなランチャースクリプトを指す。
native-manifest/README参照)。

スレッド構成(このファイル冒頭で一望できるようにまとめておく。詳しい設計判断の
理由は bridge.py 冒頭のdocstring、および chooser_dialog.py のdocstringを参照):

  - メインスレッド: stdinからFirefoxのメッセージを読み続けるだけの単純な
    ループ(protocol.read_message()はブロッキング)。読めたメッセージは
    即座にワーカースレッドプールへ投げ、次のメッセージを読みに戻る。
    これにより「次のメッセージを読む」動作が、あるリクエストの処理時間に
    引きずられて遅延することはない。

  - ワーカースレッドプール(既定4スレッド、WORKER_THREADSで調整可): 実際に
    bridge.dispatch()を呼び、pyusbとやり取りする。プールにしている理由は、
    遅い/応答しないデバイス相手の1回の呼び出しが、他の無関係な呼び出し
    (別デバイスへの操作や、診断目的のisAvailable的な軽い問い合わせ)まで
    巻き込んで待たせないようにするため。同一handleへの同時アクセスは
    bridge.py側の_handle_guard()が直列化するので、ここでの並行実行によって
    pyusb呼び出しが競合することはない。

  - ホットプラグ監視スレッド(1本、デーモン): 1.5秒おきに
    bridge.poll_hotplug_events()を呼ぶだけの単純なループ。

  - GUIスレッド(1本、Tkinterが使える場合のみ起動): チューザーダイアログの
    表示だけを担当する。Tkinterはウィジェットを作ったスレッドからしか
    安全に操作できないため専用スレッドに隔離し、他のスレッドとは
    queue.Queue + concurrent.futures.Future でやり取りする。Tkinter自体が
    使えない環境(python3-tkが入っていない等)では、requestDevice()は
    "no device chooser UI is available" という分かりやすいエラーで失敗する
    ——プロセスがクラッシュしたり、他の機能まで巻き込んで止まったりはしない。
"""
import concurrent.futures
import queue
import sys
import threading
import time
import traceback

from . import protocol
from .bridge import HAVE_RUST_ACCEL, WebUsbNativeBridge
from .settings_store import SettingsStore

WORKER_THREADS = 4
HOTPLUG_POLL_INTERVAL_SECONDS = 1.5
GUI_DIALOG_POLL_MS = 50
GUI_READY_TIMEOUT_SECONDS = 10


def _log(*args):
    print("[fox-webusb-host]", *args, file=sys.stderr, flush=True)


class _ChooserGui:
    """チューザーダイアログ専用の常駐GUIスレッドをラップするクラス。
    Tkinterが利用できない環境でも例外を投げずに動作し続け、その場合は
    self.chooser_fn が None になる(bridge.pyはchooser_fn=Noneを正しく
    扱い、requestDevice()呼び出しに分かりやすいエラーを返す)。"""

    def __init__(self):
        self._ready = threading.Event()
        self._queue = queue.Queue()
        self._available = True
        thread = threading.Thread(target=self._run, name="fox-webusb-gui", daemon=True)
        thread.start()
        self._ready.wait(timeout=GUI_READY_TIMEOUT_SECONDS)

    def _run(self):
        try:
            import tkinter as tk
        except Exception as e:
            _log("Tkinter is not available; the device chooser dialog will be disabled:", e)
            self._available = False
            self._ready.set()
            return

        from .chooser_dialog import show_chooser

        try:
            root = tk.Tk()
            root.withdraw()
        except Exception as e:
            # 🛡️ ディスプレイが無い(例: SSH越しのヘッドレス環境)等でTkが
            # 初期化自体に失敗するケース。プロセス全体を巻き込まず、
            # チューザー機能だけを静かに無効化する。
            _log("Tkinter could not be initialized (no display?); the device chooser dialog will be disabled:", e)
            self._available = False
            self._ready.set()
            return

        def poll():
            try:
                while True:
                    devices, origin, refresh_callback, future = self._queue.get_nowait()
                    try:
                        selected = show_chooser(root, devices, origin, refresh_callback)
                        if not future.cancelled():
                            future.set_result(selected)
                    except Exception as e:
                        if not future.cancelled():
                            future.set_exception(e)
            except queue.Empty:
                pass
            root.after(GUI_DIALOG_POLL_MS, poll)

        root.after(GUI_DIALOG_POLL_MS, poll)
        self._ready.set()
        root.mainloop()

    def choose(self, devices, origin, refresh_callback):
        future = concurrent.futures.Future()
        self._queue.put((devices, origin, refresh_callback, future))
        return future.result()

    @property
    def chooser_fn(self):
        return self.choose if self._available else None


def main():
    settings = SettingsStore()
    gui = _ChooserGui()

    bridge = WebUsbNativeBridge(
        settings_store=settings,
        chooser_fn=gui.chooser_fn,
        event_sink=protocol.send_message,
    )

    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=WORKER_THREADS, thread_name_prefix="fox-webusb-worker",
    )

    def handle_request(msg):
        request_id = msg.get("id")
        method = msg.get("method")
        origin = msg.get("origin")
        trusted = bool(msg.get("trusted"))
        params = msg.get("params") or {}
        try:
            result = bridge.dispatch(method, origin, trusted, params)
        except Exception as e:  # 🛡️ dispatch()自体は内部で既に広くtry/exceptしているが、最後の砦としてもう一段
            _log(f"unhandled exception while dispatching {method!r}:", e)
            _log(traceback.format_exc())
            result = {"success": False, "error": f"InvalidStateError: internal error: {e}"}
        if request_id is not None:
            try:
                protocol.send_message({"id": request_id, "type": "response", **result})
            except Exception as e:
                _log("failed to send response:", e)

    def hotplug_loop():
        while True:
            time.sleep(HOTPLUG_POLL_INTERVAL_SECONDS)
            try:
                bridge.poll_hotplug_events()
            except Exception as e:
                _log("hotplug poll error:", e)

    threading.Thread(target=hotplug_loop, name="fox-webusb-hotplug", daemon=True).start()

    _log(f"started. rust acceleration: {'available' if HAVE_RUST_ACCEL else 'not built, falling back to pure Python'}."
         f" device chooser: {'available' if gui.chooser_fn else 'DISABLED (tkinter unavailable)'}."
         f" settings file: {settings._path}")

    try:
        while True:
            try:
                msg = protocol.read_message()
            except Exception as e:
                _log("fatal error reading from stdin, exiting:", e)
                break
            if msg is None:
                _log("stdin closed (extension disconnected); exiting")
                break
            if not isinstance(msg, dict):
                continue
            executor.submit(handle_request, msg)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _log("fatal startup error:")
        _log(traceback.format_exc())
        sys.exit(1)
