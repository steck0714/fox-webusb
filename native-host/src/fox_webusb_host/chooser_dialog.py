# -*- coding: utf-8 -*-
"""
chooser_dialog.py
==================
移植元 (pyside6-webusb) の chooser_dialog.py は PySide6 の QDialog で、
「今どのオリジンが要求しているか」「信頼できる注記」「ライブ更新される候補一覧」
「未選択ではConnectを押せない」という原則をそのまま踏襲しつつ、GUIツールキットを
Tkinter(標準ライブラリ、追加インストール不要)に置き換えたのがこのモジュール。

なぜTkinterか:
  移植元はもともとQtWebEngineへnavigator.usbを注入するためにPySide6に依存して
  いたので、チューザーもPySide6で書くのが自然だった。fox-webusbのネイティブ
  ホストはブラウザ本体(Firefox)から独立したただのPythonプロセスであり、
  QtWebEngineに相当するものは存在しない——チューザーダイアログを出すためだけに
  PySide6/Qtという重い依存関係を持ち込む理由がなくなったため、標準ライブラリ
  だけで完結するTkinterに切り替えた(README「なぜTkinterか」参照)。

スレッドモデル上の注意(__main__.py側の設計と対になっている):
  Tkinterはウィジェットを作ったスレッド以外から触ってはいけない、という制約が
  ある。fox-webusbのネイティブホストは複数リクエストを並行処理するスレッド
  プールを持つため、「チューザーを出す必要が生じたワーカースレッド」と
  「実際にTkinterのイベントループを回しているGUIスレッド」は別スレッドになる。
  このモジュール自体はどのスレッドで動くかを一切気にしない、素朴な
  「(root, devices, origin, refresh_callback) を渡されたらモーダルダイアログを
  1個作り、選ばれたデバイス(またはNone)を返す」という関数として実装し、
  スレッドをまたいだ受け渡し(queue.Queue + concurrent.futures.Future)は
  __main__.py 側の責務とする。
"""
import tkinter as tk
from tkinter import ttk


def _device_label(device: dict) -> tuple:
    """(1行目=太字で見せたい主表示, 2行目=補足)のペアを返す。
    移植元の _DeviceRowWidget が「製品名(無ければVID:PID)」+
    「メーカー名 vendorId:productId [既知デバイスなら再接続回数]」という
    2行表示だったのを、Treeviewの2カラム(name, detail)へ落とし込む。"""
    product_name = device.get("productName") or None
    vendor_id = device.get("vendorId", 0)
    product_id = device.get("productId", 0)
    manufacturer = device.get("manufacturerName") or ""
    vid_pid = f"{vendor_id:04x}:{product_id:04x}"

    primary = product_name if product_name else f"Unknown device ({vid_pid})"
    detail_parts = []
    if manufacturer:
        detail_parts.append(manufacturer)
    detail_parts.append(vid_pid)
    connect_count = device.get("connectCount")
    if connect_count:
        detail_parts.append(f"connected {connect_count}x before" if connect_count > 1 else "connected before")
    return primary, "  ·  ".join(detail_parts)


def _device_identity(device: dict):
    """再描画をまたいで「同じ物理デバイス」を追跡するための識別子。
    シリアル番号があればそれを優先し(同一VID/PIDの機器を複数挿している場合でも
    区別できる)、無ければ (vendorId, productId) にフォールバックする
    (移植元と同じ優先順位)。"""
    serial = device.get("serialNumber")
    if serial:
        return ("serial", serial)
    return ("vidpid", device.get("vendorId"), device.get("productId"))


class ChooserDialog(tk.Toplevel):
    """origin からの requestDevice() 呼び出しに応じて出す、ネイティブのモーダル
    デバイス選択ダイアログ。呼び出し側(__main__.pyのGUIスレッド)は:

        dlg = ChooserDialog(root, devices, origin, refresh_callback)
        root.wait_window(dlg)
        result = dlg.selected_device  # dict または None(キャンセル)

    という手順で使うことを想定している(Tkinterのモーダルダイアログの定石)。
    """

    REFRESH_INTERVAL_MS = 1500

    def __init__(self, parent, devices, origin, refresh_callback):
        super().__init__(parent)
        self.title("Connect a USB device")
        self.selected_device = None
        self._refresh_callback = refresh_callback
        self._devices = list(devices)
        self._closed = False

        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer, text=origin or "(unknown origin)",
            font=("TkDefaultFont", 11, "bold"), wraplength=440,
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text="wants to connect to a USB device. Only choose a device you recognize "
                 "and trust — the site will be able to send and receive raw data with it.",
            wraplength=440, foreground="#555555",
        ).pack(anchor="w", pady=(2, 12))

        columns = ("name", "detail")
        self._tree = ttk.Treeview(
            outer, columns=columns, show="tree headings", height=8, selectmode="browse",
        )
        self._tree.heading("#0", text="")
        self._tree.column("#0", width=0, stretch=False)
        self._tree.heading("name", text="Device")
        self._tree.column("name", width=220, anchor="w")
        self._tree.heading("detail", text="Details")
        self._tree.column("detail", width=260, anchor="w")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_selection_changed)
        self._tree.bind("<Double-Button-1>", self._on_double_click)

        button_row = ttk.Frame(outer)
        button_row.pack(fill="x", pady=(12, 0))
        ttk.Label(button_row, text="No device selected yet.", foreground="#777777").pack(side="left")
        self._connect_btn = ttk.Button(button_row, text="Connect", command=self._on_connect, state="disabled")
        self._connect_btn.pack(side="right")
        ttk.Button(button_row, text="Cancel", command=self._on_cancel).pack(side="right", padx=(0, 8))

        self._populate(self._devices, preserve_selection=False)

        self.update_idletasks()
        self.grab_set()
        self.focus_set()
        self.after(self.REFRESH_INTERVAL_MS, self._poll_refresh)

    # ---- 一覧の描画 ----

    def _populate(self, devices, preserve_selection=True):
        previous_identity = None
        if preserve_selection:
            sel = self._tree.selection()
            if sel:
                idx = int(sel[0])
                if 0 <= idx < len(self._devices):
                    previous_identity = _device_identity(self._devices[idx])

        self._tree.delete(*self._tree.get_children())
        self._devices = list(devices)
        restore_iid = None
        for i, device in enumerate(self._devices):
            primary, detail = _device_label(device)
            iid = str(i)
            self._tree.insert("", "end", iid=iid, values=(primary, detail))
            if previous_identity is not None and _device_identity(device) == previous_identity:
                restore_iid = iid

        if restore_iid is not None:
            self._tree.selection_set(restore_iid)
        else:
            # 🛡️ 移植元と同じ方針: 一覧が更新されても自動的に何かを選択状態には
            # しない(=ユーザーが明示的にクリックするまでConnectは押せないまま)。
            self._connect_btn.configure(state="disabled")

    def _poll_refresh(self):
        if self._closed:
            return
        try:
            fresh_devices = self._refresh_callback()
        except Exception:
            fresh_devices = self._devices
        self._populate(fresh_devices, preserve_selection=True)
        self.after(self.REFRESH_INTERVAL_MS, self._poll_refresh)

    # ---- イベントハンドラ ----

    def _on_selection_changed(self, _event=None):
        has_selection = bool(self._tree.selection())
        self._connect_btn.configure(state=("normal" if has_selection else "disabled"))

    def _on_double_click(self, _event=None):
        if self._tree.selection():
            self._on_connect()

    def _on_connect(self):
        sel = self._tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self._devices):
            self.selected_device = self._devices[idx]
        self._closed = True
        self.grab_release()
        self.destroy()

    def _on_cancel(self):
        self.selected_device = None
        self._closed = True
        self.grab_release()
        self.destroy()


def show_chooser(root, devices, origin, refresh_callback):
    """root(Tkスレッド上で作られた常駐ルート)の子としてChooserDialogを1個表示し、
    閉じるまでブロックしてから選択結果(dictまたはNone)を返す。この関数自体は
    必ずTkinterのメインスレッド(rootを作ったスレッド)から呼び出すこと——
    __main__.py 側は、この関数呼び出し自体をGUIスレッドのイベントループ上で
    実行されるコールバックの中からのみ行う。"""
    dlg = ChooserDialog(root, devices, origin, refresh_callback)
    root.wait_window(dlg)
    return dlg.selected_device
