# -*- coding: utf-8 -*-
"""
bridge.py
=========
移植元 pyside6-webusb (v0.0.4b0) の WebUSBBridge (QObject + @Slot群) を、
Firefoxのネイティブメッセージングホストという別のプロセスモデルへ移植したもの。

このファイルが「ロジックとして」原作と違う点は、根本的には次の1点に集約される:
    原作は「1個の WebUSBBridge インスタンス = 1個の QWebEnginePage(=1タブ)」
    という前提の上に立っていたが、fox-webusb のネイティブホストは
    「1プロセス = ブラウザ全体(全タブ・全オリジン)」というモデルで動く。
これに伴って生じた設計変更は以下のとおり(詳細はREADME/CHANGELOG参照):

1. **オリジンの出自**: 原作は FrameOriginTracker が
   QWebEnginePage.navigationRequested を監視して発行した「フレームトークン」
   をJSから受け取り、それをオリジン文字列へ解決していた(JS自身に
   「私のオリジンはこれです」と自己申告させると偽装され得るため)。
   fox-webusbでは、拡張機能のbackground.jsが
   `browser.runtime.onMessage`のsender.url(ブラウザ自身が、実際にメッセージを
   送ってきたフレームについて教えてくれる、ページ側JSからは偽装不可能な値)
   からオリジンを求め、このbridgeの各メソッドへ直接「呼び出し元のorigin」
   として渡す。フレームトークンや `_frame_tracker` は存在しない
   (`dispatch()`のorigin引数を参照)。

2. **設定の永続化**: QSettingsではなく `settings_store.SettingsStore`
   (JSONファイル1個)。ロジック(許可オリジン単位/既知デバイス単位で
   何を憶えるか)は同じ。

3. **チューザーダイアログ**: PySide6のQDialogではなくTkinter
   (`chooser_dialog.py`)。呼び出しは `self._chooser_fn(devices, origin,
   refresh_callback)` という関数呼び出しとして注入されるので、bridge.py
   自体はGUIツールキットに一切依存しない(テスト時は簡単にモックできる)。

4. **並行性モデルとreentrancy対策**: 原作はQtのメインスレッド1本の上で
   `@Slot`が同期的に実行され、`QCoreApplication.processEvents()`だけが
   「別の呼び出しが割り込む」唯一の経路だった(v0.0.4b0で追加された
   `_busy_handles`は、まさにこの一点だけを塞ぐピンポイントな対策)。
   fox-webusbのネイティブホストは複数リクエストを本物のスレッドプールで
   並行処理するため、任意の2つの呼び出しが同じhandleに対して *いつでも*
   競合しうる。そこで `_busy_handles`(bool集合)を、あらゆるhandle操作
   メソッドに適用される汎用的な**ハンドル単位のロック**(`_handle_guard`)
   へ一般化した。これは原作より広い範囲を保護しており、原作がv0.0.4bの
   CHANGELOGで「スコープ外」と明記していた`closeDevice`の穴も自然に塞がれる
   (closeDeviceも同じ`_handle_guard`を通るため)。
   なお、v0.0.4b0がQt UIフリーズ対策として導入した「256KiB単位への
   bulk転送チャンク分割 + processEvents()」は、**意図的に移植していない**:
   その対策が守ろうとしていたのはQtのメインスレッド(=アプリ全体のUI)
   であり、fox-webusbにはそれに相当する共有UIスレッドが存在しない
   (チューザーダイアログは専用のGUIスレッドで独立に動く)。さらに、
   ctypesベースのpyusbバックエンドはブロッキングI/O呼び出し中にGILを
   解放するため、1回の大きなpyusb呼び出し中でも他のワーカースレッドは
   普通に進行できる。したがって単一の大きな`dev.read()`/`dev.write()`
   呼び出しをそのまま使っても、libusb自身が単一呼び出し内で
   「要求量に達する」か「short packetを受信する」かの早い方で完了させる
   という仕様どおりの意味論はそのまま保たれる(この点はチャンク分割
   ループで人為的に再現する必要のあるものではない)。

5. **isochronous転送**: 原作の低レベル実装の詳細(どのバックエンドAPIを
   直接叩いていたか)はこの移植では確認できなかったため、
   `dev.read()`/`dev.write()`をisochronousエンドポイントに対して直接
   呼び出すベストエフォート実装で代替した。原作自身がREADME/CHANGELOGで
   「実機で未検証」と明記している機能であり、この移植でもその位置づけは
   変えていない——pyusb/libusbバックエンドがisochronousをサポートしない
   環境では、クラッシュではなく分かりやすいエラーを返す。

6. **Rustアクセラレーション**: `native/fox_webusb_accel/`
   (旧`pyside6_webusb_accel`)は元々Qtに一切依存しない「バイト列→バイト列」の
   処理層だったため、パッケージ名の変更以外は無改造でそのまま使える。
   importに失敗した場合の標準ライブラリbase64へのフォールバックも同じ。
"""
import contextlib
import functools
import threading

import usb.core
import usb.util as usb_util

try:
    import fox_webusb_accel as _rust_accel
    HAVE_RUST_ACCEL = True
except ImportError:
    _rust_accel = None
    HAVE_RUST_ACCEL = False

import base64


def _b64encode(data) -> str:
    if HAVE_RUST_ACCEL:
        return _rust_accel.encode_base64(bytes(data))
    return base64.b64encode(bytes(data)).decode("ascii")


def _b64decode(s: str) -> bytes:
    if HAVE_RUST_ACCEL:
        return bytes(_rust_accel.decode_base64(s))
    return base64.b64decode(s)


from .errors import (
    security_error,
    invalid_state_error,
    not_found_error,
    invalid_access_error,
    index_size_error,
)
from .hardening import (
    is_protected_interface_class,
    protected_class_name,
    is_blocklisted_device,
    device_is_fully_blocked,
    build_device_descriptor,
    interface_class_for,
    UsbHotplugWatcher,
    is_valid_usb_device_filter,
    device_matches_any_usb_filter,
    is_stall_error,
    is_babble_error,
    safe_error_str,
    CONTROL_TRANSFER_MAX_LENGTH,
    BULK_TRANSFER_MAX_LENGTH,
    ISOCHRONOUS_TRANSFER_MAX_TOTAL_LENGTH,
    scaled_transfer_timeout_ms,
)
from .settings_store import SettingsStore

# 標準的なUSB control transferのbmRequestTypeビットレイアウト(USB 2.0仕様
# 9.3節)。requestType(standard/class/vendor)とrecipient(device/interface/
# endpoint/other)をpage_polyfill.js側で1バイトに合成してから渡してもらう
# (direction bitは方向が自明なcontrolTransferIn/Outどちらを呼んだかで
# Python側が強制的に上書きするので、JS側が誤った方向ビットを送ってきても
# 影響しない)。
_RECIPIENT_MASK = 0x1F
_TYPE_MASK = 0x60
_TYPE_STANDARD, _TYPE_CLASS, _TYPE_VENDOR = 0x00, 0x20, 0x40
_RECIPIENT_DEVICE, _RECIPIENT_INTERFACE, _RECIPIENT_ENDPOINT = 0x00, 0x01, 0x02


class _HandleBusyError(Exception):
    """あるhandle(またはチューザーダイアログ用の予約キー)に対する操作が
    既に別のスレッドで進行中の場合に、_handle_guard()が送出する内部例外。
    ユーザー向けのInvalidStateErrorへは_guarded()デコレータが変換する。"""


def _guarded(handle_param="handle"):
    """paramsからhandle_paramを取り出し、_handle_guard()で保護しながら
    メソッド本体を呼ぶデコレータ。原作の「@Slotの中身を丸ごとtry/exceptし、
    何が起きても安全な文字列に変換して返す」という設計哲学はそのまま
    踏襲しつつ、ハンドル単位の排他制御を追加している(このファイルの
    冒頭docstring 4節を参照)。"""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(self, origin, params):
            handle_id = params.get(handle_param)
            try:
                with self._handle_guard(handle_id):
                    return fn(self, origin, params)
            except _HandleBusyError:
                return self._busy_error(handle_id)
            except Exception as e:  # 🛡️ pyusb/libusb由来の未知の例外を含め、何が起きても安全な文字列に変換する
                return {"success": False, "error": safe_error_str(e)}
        return wrapper
    return decorator


class WebUsbNativeBridge:
    """fox-webusbネイティブホストの中核。__main__.py のワーカースレッドから
    dispatch() 経由で呼ばれる。GUI(チューザー)やイベント配送(ホットプラグ)は
    コンストラクタで注入されたコールバックを介して行い、このクラス自体は
    Tkinterにもネイティブメッセージングの通信方式にも依存しない
    (=pytestで素朴にインスタンス化して直接メソッドを呼ぶだけでテストできる、
    原作と同じ設計方針)。"""

    def __init__(self, settings_store=None, chooser_fn=None, event_sink=None, usb_finder=None):
        self._settings = settings_store or SettingsStore()
        # chooser_fn(devices: list[dict], origin: str, refresh_callback: Callable[[], list[dict]]) -> dict|None
        self._chooser_fn = chooser_fn
        # event_sink(event: dict) -> None  (connect/disconnectイベントの配送先。__main__.pyが差し込む)
        self._event_sink = event_sink
        # usb_finder() -> Iterable[usb.core.Device]  (テスト時にフェイクデバイス一覧を注入するため。既定はusb.core.find)
        self._usb_finder = usb_finder or (lambda: usb.core.find(find_all=True))

        self._open_devices = {}   # handle_id(int) -> {"device", "origin", "vendor_id", "product_id", "configuration_selected", "claimed_interfaces", "active_alternates"}
        self._next_handle = 1
        self._next_handle_lock = threading.Lock()

        self._handle_locks = {}          # handle_id または "__chooser__" -> threading.Lock()
        self._handle_locks_guard = threading.Lock()

        self._hotplug = UsbHotplugWatcher(self._current_device_pairs)
        # 🆕 fox-webusb固有の配慮: UsbHotplugWatcherは_known=set()から始まる
        # ため、素朴に使うと最初のpoll()で「既に挿さっていたデバイス」まで
        # 丸ごと『新規接続』として報告してしまう。原作(1ページ=1インスタンス)
        # ではページ読み込みのたびに多少これが起きても実害は小さかったが、
        # fox-webusbのホストはブラウザ全体で1つの常駐プロセスなので、
        # 起動直後に「既存デバイスぶんの偽のconnectイベント」が全許可オリジンへ
        # 一斉配信されるのは避けたい。ここで一度だけ静かにpoll()して基準を
        # 作っておくことで、実際にイベントを配送し始めるのは本物の抜き差しが
        # 起きてからになる。
        #
        # 🛡️ v0.0.0a0: pyusb(libusb1バックエンド)の実際の初期化タイミングは
        # 「最初にusb.core.find()系の関数が呼ばれた瞬間」であることが多い。
        # このプロセスは複数スレッド(ワーカースレッドプール・ホットプラグ
        # 監視スレッド・GUIスレッドの中のダイアログ更新タイマー)から
        # それぞれ独立に列挙を呼びうるため、"初回初期化"が複数スレッドから
        # 完全に同時に起きるレース条件を構造的に排除しておく
        # (libusb自体はスレッドセーフを謳っているが、その保証の外側にある
        # Python/ctypesレベルのバックエンド探索・DLL読み込み処理[特にWindows]
        # まで完全にスレッドセーフだと過信しない、という保守的な判断)。
        # 列挙はどのみち高頻度な操作ではない(ホットプラグ監視は1.5秒間隔、
        # チューザーの自動更新も1.5秒間隔)ため、直列化のコストは無視できる。
        self._enumeration_lock = threading.Lock()
        self._hotplug.poll()

    # ============================================================
    # dispatch: __main__.py のワーカースレッドから呼ばれる唯一の入口
    # ============================================================
    def dispatch(self, method, origin, trusted, params):
        """method名を実際のメソッドへ振り分ける。ページ向けメソッド
        (PAGE_METHODS)はorigin必須、信頼済み専用メソッド(TRUSTED_METHODS)は
        trusted=Trueでなければ拒否する——ただし実際にどちらに属するかの
        「最終判断」は拡張機能側(background.js)のisTrustedSender()が
        既に行っており、ここでのtrustedチェックは多層防御の2枚目に過ぎない
        (background.jsを迂回して直接このプロセスに話しかけられるのは
        Firefox自身のネイティブメッセージング経路だけなので、通常は
        ここに到達する前に弾かれているはずである)。"""
        fn = self._DISPATCH_TABLE.get(method)
        if fn is None:
            return {"success": False, "error": not_found_error(f"unknown method: {method}")}
        is_trusted_only = method in self._TRUSTED_ONLY_METHODS
        if is_trusted_only and not trusted:
            return {"success": False, "error": security_error("this method is only available to the extension's own pages")}
        try:
            if is_trusted_only:
                return fn(self, params)
            return fn(self, origin, params)
        except Exception as e:
            return {"success": False, "error": safe_error_str(e)}

    # ============================================================
    # ハンドル単位の排他制御
    # ============================================================
    def _lock_for_handle(self, handle_id):
        with self._handle_locks_guard:
            lock = self._handle_locks.get(handle_id)
            if lock is None:
                lock = threading.Lock()
                self._handle_locks[handle_id] = lock
            return lock

    @contextlib.contextmanager
    def _handle_guard(self, handle_id):
        lock = self._lock_for_handle(handle_id)
        if not lock.acquire(blocking=False):
            raise _HandleBusyError(handle_id)
        try:
            yield
        finally:
            lock.release()

    def _busy_error(self, handle_id):
        return {"success": False, "error": invalid_state_error(
            f"handle {handle_id} is currently busy with another operation"
        )}

    def _forget_handle_lock(self, handle_id):
        with self._handle_locks_guard:
            self._handle_locks.pop(handle_id, None)

    # ============================================================
    # デバイス列挙・物理デバイス解決
    # ============================================================
    def _current_device_pairs(self):
        try:
            with self._enumeration_lock:
                return {(d.idVendor, d.idProduct) for d in self._usb_finder()}
        except Exception:
            return set()

    def _find_physical_device(self, vendor_id, product_id):
        """指定vendorId/productIdの、現在接続中の実機を1台返す(見つからなければ
        None)。同一VID/PIDの機器が複数挿さっている場合は先頭の1台を返す
        ——シリアル番号まで見た厳密な一意特定はしない、この実装の既知の
        単純化(README参照)。"""
        try:
            with self._enumeration_lock:
                for dev in self._usb_finder():
                    if dev.idVendor == vendor_id and dev.idProduct == product_id:
                        return dev
        except Exception:
            pass
        return None

    def _find_claimed_endpoint(self, dev, info, endpoint_number, direction):
        """endpoint_number(1-15)・direction("in"/"out")が、現在claimされて
        いるいずれかのインターフェースの、現在アクティブなalternate setting
        に実在するエンドポイントかどうかを、実際のディスクリプタに基づいて
        独立に検証する(JS側の状態管理は一切信用しない。防御的多層化)。
        見つかればpyusbのEndpointオブジェクトを、無ければNoneを返す。"""
        try:
            cfg = dev.get_active_configuration()
        except Exception:
            return None
        address = (endpoint_number or 0) | (0x80 if direction == "in" else 0x00)
        for interface_number in info["claimed_interfaces"]:
            alternate_setting = info["active_alternates"].get(interface_number, 0)
            try:
                intf = usb_util.find_descriptor(
                    cfg, bInterfaceNumber=interface_number, bAlternateSetting=alternate_setting,
                )
            except Exception:
                intf = None
            if intf is None:
                continue
            try:
                for ep in intf:
                    if ep.bEndpointAddress == address:
                        return ep
            except Exception:
                continue
        return None

    def _get_open_device_and_info(self, handle_id, origin):
        """handle_idがこのoriginによって開かれたものであることを確認した上で
        (device, info)を返す。別オリジンのhandleは『存在しない』ものとして
        扱う(=NotFoundErrorで、SecurityErrorではない。存在の有無自体を
        オリジン間で漏らさないため——原作の_get_open_deviceと同じ方針)。"""
        info = self._open_devices.get(handle_id)
        if info is None or info["origin"] != origin:
            return None, None
        return info["device"], info

    def _validate_transfer_length(self, length, max_length):
        try:
            length = int(length)
        except (TypeError, ValueError):
            return {"success": False, "error": index_size_error("length must be a number")}
        if length < 0:
            return {"success": False, "error": index_size_error("length must not be negative")}
        if length > max_length:
            return {"success": False, "error": index_size_error(
                f"length exceeds the maximum of {max_length} bytes this implementation allows per call"
            )}
        return None

    def _validate_packet_lengths(self, packet_lengths, max_total):
        if not isinstance(packet_lengths, list) or not packet_lengths:
            return None, {"success": False, "error": index_size_error("packetLengths must be a non-empty array")}
        try:
            lengths = [int(x) for x in packet_lengths]
        except (TypeError, ValueError):
            return None, {"success": False, "error": index_size_error("packetLengths must contain numbers")}
        if any(length < 0 for length in lengths):
            return None, {"success": False, "error": index_size_error("packetLengths must not be negative")}
        total = sum(lengths)
        if total > max_total:
            return None, {"success": False, "error": index_size_error(
                f"total packetLengths ({total}) exceeds the maximum of {max_total} bytes this implementation allows per call"
            )}
        # 🛡️ この実装固有の制約(仕様上の要求ではない): isochronous転送は
        # 低レベルバックエンドの制約により、1回の呼び出し内では全パケットが
        # 同一サイズであることを要求する。
        if len(set(lengths)) > 1:
            return None, {"success": False, "error": invalid_access_error(
                "this implementation requires all packetLengths in a single isochronous call to be equal"
            )}
        return lengths, None

    def _control_transfer_validation_error(self, dev, info, request_type_byte, request, index):
        recipient = request_type_byte & _RECIPIENT_MASK
        req_type = request_type_byte & _TYPE_MASK

        if recipient == _RECIPIENT_INTERFACE:
            interface_number = (index or 0) & 0xFF  # 仕様: recipient=interfaceの場合、wIndex下位バイトがインターフェース番号
            if interface_number not in info["claimed_interfaces"]:
                return {"success": False, "error": invalid_state_error(
                    f"interface {interface_number} must be claimed before sending a control transfer to it"
                )}
            iface_class = interface_class_for(dev, interface_number)
            if req_type == _TYPE_CLASS and iface_class is not None and is_protected_interface_class(iface_class):
                return {"success": False, "error": security_error(
                    f"class-specific control requests to protected interface class "
                    f"{protected_class_name(iface_class)} (0x{iface_class:02x}) are not allowed"
                )}
        elif recipient == _RECIPIENT_ENDPOINT:
            endpoint_address = (index or 0) & 0xFF
            endpoint_number = endpoint_address & 0x0F
            direction = "in" if (endpoint_address & 0x80) else "out"
            if self._find_claimed_endpoint(dev, info, endpoint_number, direction) is None:
                return {"success": False, "error": invalid_state_error(
                    "control transfer targets an endpoint that is not part of a currently claimed interface"
                )}

        if req_type == _TYPE_STANDARD:
            # 🛡️ このAPI自身が状態管理している操作(configuration切り替え・
            # alternate setting切り替え)を、生のcontrol transferで裏から
            # 行われるとPython側の状態(claimed_interfaces等)と実機がずれる。
            if recipient == _RECIPIENT_DEVICE and request in (0x05, 0x09):  # SET_ADDRESS, SET_CONFIGURATION
                return {"success": False, "error": security_error(
                    "this standard request must go through the dedicated method "
                    "(e.g. selectConfiguration()) instead of a raw control transfer"
                )}
            if recipient == _RECIPIENT_INTERFACE and request == 0x0B:  # SET_INTERFACE
                return {"success": False, "error": security_error(
                    "SET_INTERFACE must go through selectAlternateInterface() instead of a raw control transfer"
                )}

        if is_blocklisted_device(getattr(dev, "idVendor", None), getattr(dev, "idProduct", None)):
            return {"success": False, "error": security_error("this device is on the security blocklist")}
        return None

    # ============================================================
    # ページ向けメソッド (WebUSB仕様の navigator.usb / USBDevice に対応)
    # ============================================================

    def list_devices(self, origin, params):
        try:
            grants = self._settings.load_granted_origins().get(origin, [])
            granted_pairs = {(g["vendorId"], g["productId"]) for g in grants}
            result = []
            with self._enumeration_lock:
                found = list(self._usb_finder())
            for dev in found:
                pair = (dev.idVendor, dev.idProduct)
                if pair in granted_pairs and not device_is_fully_blocked(dev):
                    result.append(build_device_descriptor(dev, usb_util, include_configurations=True))
            return {"devices": result}
        except Exception as e:
            return {"devices": [], "error": safe_error_str(e)}

    def request_device_chooser(self, origin, params):
        filters = params.get("filters") or []
        exclusion_filters = params.get("exclusionFilters") or []
        try:
            with self._handle_guard("__chooser__"):
                return self._request_device_chooser_impl(origin, filters, exclusion_filters)
        except _HandleBusyError:
            return {"success": False, "error": invalid_state_error("a device chooser is already open")}

    def _request_device_chooser_impl(self, origin, filters, exclusion_filters):
        for f in filters:
            if not is_valid_usb_device_filter(f):
                return {"success": False, "error": security_error("invalid device filter")}
        for f in exclusion_filters:
            if not is_valid_usb_device_filter(f):
                return {"success": False, "error": security_error("invalid exclusion filter")}

        def candidates():
            try:
                with self._enumeration_lock:
                    devices = list(self._usb_finder())
            except Exception:
                devices = []
            included = [d for d in devices if device_matches_any_usb_filter(d, usb_util, filters)]
            if exclusion_filters:
                included = [d for d in included if not device_matches_any_usb_filter(d, usb_util, exclusion_filters)]
            return [d for d in included if not device_is_fully_blocked(d)]

        def descriptors_for_refresh():
            known = {(d["vendorId"], d["productId"]): d for d in self._settings.load_known_devices()}
            result = []
            for dev in candidates():
                desc = build_device_descriptor(dev, usb_util, include_configurations=False)
                k = (desc["vendorId"], desc["productId"])
                if k in known:
                    desc["connectCount"] = known[k].get("connectCount")
                result.append(desc)
            result.sort(key=lambda d: -(d.get("connectCount") or 0))
            return result

        if self._chooser_fn is None:
            return {"success": False, "error": not_found_error("no device chooser UI is available in this environment")}

        initial = descriptors_for_refresh()
        selected = self._chooser_fn(initial, origin, descriptors_for_refresh)
        if selected is None:
            return {"success": False, "error": not_found_error("the user did not select a device")}

        dev = self._find_physical_device(selected.get("vendorId"), selected.get("productId"))
        if dev is None:
            return {"success": False, "error": not_found_error("the selected device is no longer connected")}

        self._settings.grant(origin, selected["vendorId"], selected["productId"])
        self._settings.record_device_usage(
            selected["vendorId"], selected["productId"],
            selected.get("productName"), selected.get("manufacturerName"),
        )
        rich = build_device_descriptor(dev, usb_util, include_configurations=True)
        return {"success": True, "device": rich}

    def open_device(self, origin, params):
        vendor_id = params.get("vendorId")
        product_id = params.get("productId")
        try:
            if not self._settings.is_granted(origin, vendor_id, product_id):
                return {"success": False, "error": security_error("this origin has not been granted access to this device")}
            dev = self._find_physical_device(vendor_id, product_id)
            if dev is None:
                return {"success": False, "error": not_found_error("device is not currently connected")}
            if device_is_fully_blocked(dev):
                return {"success": False, "error": security_error("this device is on the security blocklist")}
            with self._next_handle_lock:
                handle_id = self._next_handle
                self._next_handle += 1
            self._open_devices[handle_id] = {
                "device": dev, "origin": origin,
                "vendor_id": vendor_id, "product_id": product_id,
                "configuration_selected": False,
                "claimed_interfaces": set(),
                "active_alternates": {},
            }
            return {"success": True, "handle": handle_id}
        except Exception as e:
            return {"success": False, "error": safe_error_str(e)}

    @_guarded()
    def close_device(self, origin, params):
        handle_id = params.get("handle")
        dev, info = self._get_open_device_and_info(handle_id, origin)
        if dev is not None:
            for interface_number in list(info["claimed_interfaces"]):
                try:
                    usb_util.release_interface(dev, interface_number)
                except Exception:
                    pass
            try:
                usb_util.dispose_resources(dev)
            except Exception:
                pass
            self._open_devices.pop(handle_id, None)
        self._forget_handle_lock(handle_id)
        return {"success": True}

    @_guarded()
    def claim_interface(self, origin, params):
        handle_id = params.get("handle")
        interface_number = params.get("interfaceNumber")
        dev, info = self._get_open_device_and_info(handle_id, origin)
        if dev is None:
            return {"success": False, "error": not_found_error(f"no open device for handle {handle_id}")}
        if not info["configuration_selected"]:
            return {"success": False, "error": invalid_state_error(
                "no configuration has been selected; call selectConfiguration() first"
            )}
        if interface_number in info["claimed_interfaces"]:
            return {"success": True}  # 仕様: 既にclaim済みのインターフェースへの再claimは単純成功
        iface_class = interface_class_for(dev, interface_number)
        if iface_class is None:
            return {"success": False, "error": not_found_error(
                f"interface {interface_number} was not found on the active configuration"
            )}
        if is_protected_interface_class(iface_class):
            return {"success": False, "error": security_error(
                f"interface class {protected_class_name(iface_class)} (0x{iface_class:02x}) is protected and cannot be claimed"
            )}
        if device_is_fully_blocked(dev):
            return {"success": False, "error": security_error("this device is on the security blocklist")}
        try:
            usb_util.claim_interface(dev, interface_number)
            dev.set_interface_altsetting(interface=interface_number, alternate_setting=0)
        except Exception as e:
            return {"success": False, "error": safe_error_str(e)}
        info["claimed_interfaces"].add(interface_number)
        info["active_alternates"][interface_number] = 0
        return {"success": True}

    @_guarded()
    def release_interface(self, origin, params):
        handle_id = params.get("handle")
        interface_number = params.get("interfaceNumber")
        dev, info = self._get_open_device_and_info(handle_id, origin)
        if dev is None:
            return {"success": False, "error": not_found_error(f"no open device for handle {handle_id}")}
        if interface_number not in info["claimed_interfaces"]:
            return {"success": False, "error": invalid_state_error(f"interface {interface_number} is not currently claimed")}
        try:
            usb_util.release_interface(dev, interface_number)
        except Exception as e:
            return {"success": False, "error": safe_error_str(e)}
        info["claimed_interfaces"].discard(interface_number)
        info["active_alternates"].pop(interface_number, None)
        return {"success": True}

    @_guarded()
    def select_configuration(self, origin, params):
        handle_id = params.get("handle")
        configuration_value = params.get("configurationValue")
        dev, info = self._get_open_device_and_info(handle_id, origin)
        if dev is None:
            return {"success": False, "error": not_found_error(f"no open device for handle {handle_id}")}
        # 仕様: configuration切り替えは、既存のインターフェースclaimを全て
        # 暗黙的に解放する(configurationが変わればインターフェース番号の
        # 意味そのものが変わりうるため)。
        for interface_number in list(info["claimed_interfaces"]):
            try:
                usb_util.release_interface(dev, interface_number)
            except Exception:
                pass
        info["claimed_interfaces"].clear()
        info["active_alternates"].clear()
        try:
            dev.set_configuration(configuration_value)
        except Exception as e:
            return {"success": False, "error": safe_error_str(e)}
        info["configuration_selected"] = True
        return {"success": True}

    @_guarded()
    def select_alternate_interface(self, origin, params):
        handle_id = params.get("handle")
        interface_number = params.get("interfaceNumber")
        alternate_setting = params.get("alternateSetting")
        dev, info = self._get_open_device_and_info(handle_id, origin)
        if dev is None:
            return {"success": False, "error": not_found_error(f"no open device for handle {handle_id}")}
        if interface_number not in info["claimed_interfaces"]:
            return {"success": False, "error": invalid_state_error(
                f"interface {interface_number} must be claimed before selecting an alternate setting"
            )}
        try:
            dev.set_interface_altsetting(interface=interface_number, alternate_setting=alternate_setting)
        except Exception as e:
            return {"success": False, "error": safe_error_str(e)}
        info["active_alternates"][interface_number] = alternate_setting
        return {"success": True}

    @_guarded()
    def reset_device(self, origin, params):
        handle_id = params.get("handle")
        dev, info = self._get_open_device_and_info(handle_id, origin)
        if dev is None:
            return {"success": False, "error": not_found_error(f"no open device for handle {handle_id}")}
        try:
            dev.reset()
        except Exception as e:
            return {"success": False, "error": safe_error_str(e)}
        info["claimed_interfaces"].clear()
        info["active_alternates"].clear()
        info["configuration_selected"] = False
        return {"success": True}

    @_guarded()
    def clear_halt(self, origin, params):
        handle_id = params.get("handle")
        direction = params.get("direction")
        endpoint_number = params.get("endpointNumber")
        dev, info = self._get_open_device_and_info(handle_id, origin)
        if dev is None:
            return {"success": False, "error": not_found_error(f"no open device for handle {handle_id}")}
        if not (1 <= (endpoint_number or 0) <= 15):
            return {"success": False, "error": index_size_error("endpointNumber must be between 1 and 15")}
        ep = self._find_claimed_endpoint(dev, info, endpoint_number, direction)
        if ep is None:
            return {"success": False, "error": not_found_error("endpoint is not part of a currently claimed interface")}
        try:
            dev.clear_halt(ep.bEndpointAddress)
        except Exception as e:
            return {"success": False, "error": safe_error_str(e)}
        return {"success": True}

    @_guarded()
    def bulk_transfer_in(self, origin, params):
        handle_id = params.get("handle")
        endpoint = params.get("endpoint")
        length = params.get("length")
        dev, info = self._get_open_device_and_info(handle_id, origin)
        if dev is None:
            return {"success": False, "error": not_found_error(f"no open device for handle {handle_id}")}
        length_error = self._validate_transfer_length(length, BULK_TRANSFER_MAX_LENGTH)
        if length_error is not None:
            return length_error
        if not (1 <= (endpoint or 0) <= 15):
            return {"success": False, "error": index_size_error("endpoint must be between 1 and 15")}
        if self._find_claimed_endpoint(dev, info, endpoint, "in") is None:
            return {"success": False, "error": not_found_error("endpoint is not part of a currently claimed interface")}
        endpoint_address = endpoint | 0x80
        try:
            data = bytes(dev.read(endpoint_address, length, timeout=scaled_transfer_timeout_ms(length)))
        except Exception as e:
            # 🛡️ 実仕様: STALL/babbleはPromiseのreject対象ではなく、
            #    status:'stall'/'babble'を伴う"成功"resolveとして返す。
            if is_stall_error(e):
                return {"success": True, "status": "stall", "data": ""}
            if is_babble_error(e):
                return {"success": True, "status": "babble", "data": ""}
            raise
        return {"success": True, "status": "ok", "data": _b64encode(data)}

    @_guarded()
    def bulk_transfer_out(self, origin, params):
        handle_id = params.get("handle")
        endpoint = params.get("endpoint")
        dev, info = self._get_open_device_and_info(handle_id, origin)
        if dev is None:
            return {"success": False, "error": not_found_error(f"no open device for handle {handle_id}")}
        if not (1 <= (endpoint or 0) <= 15):
            return {"success": False, "error": index_size_error("endpoint must be between 1 and 15")}
        if self._find_claimed_endpoint(dev, info, endpoint, "out") is None:
            return {"success": False, "error": not_found_error("endpoint is not part of a currently claimed interface")}
        try:
            data = _b64decode(params.get("data", ""))
        except Exception:
            return {"success": False, "error": index_size_error("data is not valid base64")}
        length_error = self._validate_transfer_length(len(data), BULK_TRANSFER_MAX_LENGTH)
        if length_error is not None:
            return length_error
        try:
            written = dev.write(endpoint, data, timeout=scaled_transfer_timeout_ms(len(data)))
        except Exception as e:
            if is_stall_error(e):
                return {"success": True, "status": "stall", "bytesWritten": 0}
            raise
        return {"success": True, "status": "ok", "bytesWritten": written}

    @_guarded()
    def control_transfer_in(self, origin, params):
        handle_id = params.get("handle")
        request_type = (params.get("requestType", 0) & 0x7F) | 0x80
        request = params.get("request")
        value = params.get("value")
        index = params.get("index")
        length = params.get("length")
        dev, info = self._get_open_device_and_info(handle_id, origin)
        if dev is None:
            return {"success": False, "error": not_found_error(f"no open device for handle {handle_id}")}
        length_error = self._validate_transfer_length(length, CONTROL_TRANSFER_MAX_LENGTH)
        if length_error is not None:
            return length_error
        validation_error = self._control_transfer_validation_error(dev, info, request_type, request, index)
        if validation_error is not None:
            return validation_error
        try:
            data = dev.ctrl_transfer(request_type, request, value, index, length,
                                      timeout=scaled_transfer_timeout_ms(length))
        except Exception as e:
            if is_stall_error(e):
                return {"success": True, "status": "stall", "data": ""}
            if is_babble_error(e):
                return {"success": True, "status": "babble", "data": ""}
            raise
        return {"success": True, "status": "ok", "data": _b64encode(bytes(data))}

    @_guarded()
    def control_transfer_out(self, origin, params):
        handle_id = params.get("handle")
        request_type = params.get("requestType", 0) & 0x7F
        request = params.get("request")
        value = params.get("value")
        index = params.get("index")
        dev, info = self._get_open_device_and_info(handle_id, origin)
        if dev is None:
            return {"success": False, "error": not_found_error(f"no open device for handle {handle_id}")}
        validation_error = self._control_transfer_validation_error(dev, info, request_type, request, index)
        if validation_error is not None:
            return validation_error
        try:
            data = _b64decode(params.get("data", ""))
        except Exception:
            return {"success": False, "error": index_size_error("data is not valid base64")}
        length_error = self._validate_transfer_length(len(data), CONTROL_TRANSFER_MAX_LENGTH)
        if length_error is not None:
            return length_error
        try:
            written = dev.ctrl_transfer(request_type, request, value, index, data,
                                         timeout=scaled_transfer_timeout_ms(len(data)))
        except Exception as e:
            if is_stall_error(e):
                return {"success": True, "status": "stall", "bytesWritten": 0}
            raise
        return {"success": True, "status": "ok", "bytesWritten": written}

    @_guarded()
    def isochronous_transfer_in(self, origin, params):
        handle_id = params.get("handle")
        endpoint = params.get("endpoint")
        dev, info = self._get_open_device_and_info(handle_id, origin)
        if dev is None:
            return {"success": False, "error": not_found_error(f"no open device for handle {handle_id}")}
        packet_lengths, err = self._validate_packet_lengths(params.get("packetLengths"), ISOCHRONOUS_TRANSFER_MAX_TOTAL_LENGTH)
        if err is not None:
            return err
        if not (1 <= (endpoint or 0) <= 15):
            return {"success": False, "error": index_size_error("endpoint must be between 1 and 15")}
        ep = self._find_claimed_endpoint(dev, info, endpoint, "in")
        if ep is None:
            return {"success": False, "error": not_found_error("endpoint is not part of a currently claimed interface")}
        if usb_util.endpoint_type(ep.bmAttributes) != usb_util.ENDPOINT_TYPE_ISO:
            return {"success": False, "error": invalid_access_error("endpoint is not an isochronous endpoint")}

        total_length = sum(packet_lengths)
        endpoint_address = endpoint | 0x80
        try:
            received = bytes(dev.read(endpoint_address, total_length, timeout=scaled_transfer_timeout_ms(total_length)))
        except NotImplementedError:
            # 🧪 ベストエフォート実装(README/CHANGELOG参照): pyusb/libusb
            # バックエンドがisochronousをサポートしない環境向けの、
            # クラッシュしない明示的なエラー。
            return {"success": False, "error": invalid_access_error(
                "isochronous transfers are not supported by the USB backend available on this system"
            )}
        except Exception as e:
            if not is_babble_error(e):
                raise
            received = b""

        packets = []
        offset = 0
        for packet_length in packet_lengths:
            chunk = received[offset:offset + packet_length]
            offset += packet_length
            packets.append({"status": "ok", "data": _b64encode(chunk)})
        return {"success": True, "packets": packets}

    @_guarded()
    def isochronous_transfer_out(self, origin, params):
        handle_id = params.get("handle")
        endpoint = params.get("endpoint")
        dev, info = self._get_open_device_and_info(handle_id, origin)
        if dev is None:
            return {"success": False, "error": not_found_error(f"no open device for handle {handle_id}")}
        packet_lengths, err = self._validate_packet_lengths(params.get("packetLengths"), ISOCHRONOUS_TRANSFER_MAX_TOTAL_LENGTH)
        if err is not None:
            return err
        if not (1 <= (endpoint or 0) <= 15):
            return {"success": False, "error": index_size_error("endpoint must be between 1 and 15")}
        ep = self._find_claimed_endpoint(dev, info, endpoint, "out")
        if ep is None:
            return {"success": False, "error": not_found_error("endpoint is not part of a currently claimed interface")}
        if usb_util.endpoint_type(ep.bmAttributes) != usb_util.ENDPOINT_TYPE_ISO:
            return {"success": False, "error": invalid_access_error("endpoint is not an isochronous endpoint")}
        try:
            data = _b64decode(params.get("data", ""))
        except Exception:
            return {"success": False, "error": index_size_error("data is not valid base64")}
        if len(data) != sum(packet_lengths):
            return {"success": False, "error": index_size_error("data length does not match the sum of packetLengths")}
        try:
            dev.write(endpoint, data, timeout=scaled_transfer_timeout_ms(len(data)))
        except NotImplementedError:
            return {"success": False, "error": invalid_access_error(
                "isochronous transfers are not supported by the USB backend available on this system"
            )}
        return {"success": True, "packets": [{"status": "ok", "bytesWritten": pl} for pl in packet_lengths]}

    def forget_granted_device(self, origin, params):
        self._settings.revoke(origin, params.get("vendorId"), params.get("productId"))
        # 仕様: forget()は既に開いているハンドルには影響しない(進行中のセッションは
        # 維持されるが、以後のgetDevices()/requestDevice()には出てこなくなる)。
        return {"success": True}

    # ============================================================
    # 信頼済み専用メソッド (拡張機能のオプションページからのみ到達可能。
    # background.js の isTrustedSender() が sender.url を検証して初めて
    # ここまで届く——ページ埋め込みのJSからは到達できない)
    # ============================================================

    def list_known_devices(self, params):
        return {"devices": self._settings.load_known_devices()}

    def forget_known_device(self, params):
        vendor_id, product_id = params.get("vendorId"), params.get("productId")
        remaining = [
            d for d in self._settings.load_known_devices()
            if not (d.get("vendorId") == vendor_id and d.get("productId") == product_id)
        ]
        self._settings.save_known_devices(remaining)
        return {"success": True}

    def forget_all_known_devices(self, params):
        self._settings.save_known_devices([])
        return {"success": True}

    def list_granted_origins(self, params):
        return {"origins": self._settings.load_granted_origins()}

    def revoke_origin_grant(self, params):
        ok = self._settings.revoke(params.get("origin"), params.get("vendorId"), params.get("productId"))
        return {"success": ok}

    def revoke_all_for_origin(self, params):
        ok = self._settings.revoke_all_for_origin(params.get("origin"))
        return {"success": ok}

    def diagnostics(self, params):
        try:
            with self._enumeration_lock:
                count = len(list(self._usb_finder()))
            return {"success": True, "deviceCount": count, "rustAccel": HAVE_RUST_ACCEL}
        except Exception as e:
            return {"success": False, "error": safe_error_str(e)}

    def origin_closed(self, params):
        """background.jsからの通知: このoriginを表示していたタブ/フレームが
        もう1つも残っていない。開いていたハンドルを解放する(原作の
        _on_page_navigatedの一般化——単位が『1ページのナビゲーション』から
        『あるoriginを表示するタブが0個になったこと』に変わっている)。
        転送処理などで現在busyなハンドルは無理に横取りせず、次の機会に
        委ねる(_HandleBusyErrorを握りつぶすだけで、エラー扱いにはしない)。"""
        origin = params.get("origin")
        if not origin:
            return {"success": True}
        for handle_id, info in list(self._open_devices.items()):
            if info["origin"] != origin:
                continue
            try:
                with self._handle_guard(handle_id):
                    dev = info["device"]
                    for interface_number in list(info["claimed_interfaces"]):
                        try:
                            usb_util.release_interface(dev, interface_number)
                        except Exception:
                            pass
                    try:
                        usb_util.dispose_resources(dev)
                    except Exception:
                        pass
                    self._open_devices.pop(handle_id, None)
            except _HandleBusyError:
                continue
        return {"success": True}

    # ============================================================
    # ホットプラグ監視(__main__.pyの常駐スレッドが呼ぶ)
    # ============================================================
    def poll_hotplug_events(self):
        connected, disconnected = self._hotplug.poll()
        if self._event_sink is None:
            return
        for vendor_id, product_id in connected:
            origins = self._settings.origins_granted_for_device(vendor_id, product_id)
            if not origins:
                continue
            dev = self._find_physical_device(vendor_id, product_id)
            device_desc = (
                build_device_descriptor(dev, usb_util, include_configurations=True)
                if dev is not None else {"vendorId": vendor_id, "productId": product_id}
            )
            self._event_sink({"type": "event", "event": "connect", "origins": origins, "device": device_desc})
        for vendor_id, product_id in disconnected:
            origins = self._settings.origins_granted_for_device(vendor_id, product_id)
            if not origins:
                continue
            self._event_sink({
                "type": "event", "event": "disconnect", "origins": origins,
                "device": {"vendorId": vendor_id, "productId": product_id},
            })

    _TRUSTED_ONLY_METHODS = frozenset([
        "listKnownDevices", "forgetKnownDevice", "forgetAllKnownDevices",
        "listGrantedOrigins", "revokeOriginGrant", "revokeAllForOrigin",
        "diagnostics", "originClosed",
    ])

    _DISPATCH_TABLE = {
        "listDevices": list_devices,
        "requestDeviceChooser": request_device_chooser,
        "openDevice": open_device,
        "closeDevice": close_device,
        "claimInterface": claim_interface,
        "releaseInterface": release_interface,
        "selectConfiguration": select_configuration,
        "selectAlternateInterface": select_alternate_interface,
        "resetDevice": reset_device,
        "clearHalt": clear_halt,
        "bulkTransferIn": bulk_transfer_in,
        "bulkTransferOut": bulk_transfer_out,
        "controlTransferIn": control_transfer_in,
        "controlTransferOut": control_transfer_out,
        "isochronousTransferIn": isochronous_transfer_in,
        "isochronousTransferOut": isochronous_transfer_out,
        "forgetGrantedDevice": forget_granted_device,
        "listKnownDevices": list_known_devices,
        "forgetKnownDevice": forget_known_device,
        "forgetAllKnownDevices": forget_all_known_devices,
        "listGrantedOrigins": list_granted_origins,
        "revokeOriginGrant": revoke_origin_grant,
        "revokeAllForOrigin": revoke_all_for_origin,
        "diagnostics": diagnostics,
        "originClosed": origin_closed,
    }
