# -*- coding: utf-8 -*-
"""
settings_store.py
==================
移植元 (pyside6-webusb) は許可情報の永続化に Qt の QSettings を使っていた
(ホストアプリの QMainWindow が `.settings` 属性を持っていればそれを、無ければ
QSettings(organization, application) にフォールバックする設計)。fox-webusb の
ネイティブホストは Qt に一切依存しないプロセスなので、同じ役割を果たす
「OS標準の設定ディレクトリに置く1個のJSONファイル」に置き換えたのがこのモジュール。

保存内容は移植元と同じ2つ:
  - granted_origins: {origin: [{"vendorId":.., "productId":.., "grantedAt":..}, ...]}
    (requestDevice()でユーザーが明示的に許可したデバイス。オリジン単位)
  - known_devices: [{"vendorId":.., "productId":.., "productName":.., "manufacturerName":..,
                      "firstSeen":.., "lastConnected":.., "connectCount":.., "priority":..}, ...]
    (チューザーダイアログの並べ替えに使う接続履歴。オリジンとは無関係のホスト全体で1つ)

設計判断:
  - 1個のJSONファイルにまとめる(QSettingsのキーごとの粒度は踏襲しない)。
    このプロセスは1ユーザー・1ホストインスタンスが前提であり、複数キーに分ける
    実益がない。
  - 書き込みは「一時ファイルに書いてから os.replace()」で原子的に行う。複数の
    スレッド(ワーカースレッド・ホットプラグ監視スレッド・チューザーダイアログを
    操作するGUIスレッド)から同時に触られる可能性があるため、プロセス内では
    threading.RLock で直列化し、プロセス外(同じユーザーで複数のFirefoxプロファイル
    が同時にこのホストを起動する等)に対しては os.replace() のOSレベルの原子性で
    「読み込み時に壊れた/中途半端なJSONを掴む」ことだけは避ける
    (最後に書き込んだプロセスが勝つ、という単純な楽観的並行性。移植元のQSettingsも
    同程度の保証しかしていない)。
"""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path


def default_settings_path() -> Path:
    """OS ごとの慣習に沿った設定ファイルの既定パスを返す。
    Windows: %APPDATA%\\fox-webusb\\settings.json
    macOS:   ~/Library/Application Support/fox-webusb/settings.json
    Linux他: $XDG_CONFIG_HOME/fox-webusb/settings.json (既定 ~/.config/fox-webusb/settings.json)
    """
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
        return root / "fox-webusb" / "settings.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "fox-webusb" / "settings.json"
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "fox-webusb" / "settings.json"


class SettingsStore:
    """許可済みオリジン(granted_origins)と既知デバイス履歴(known_devices)を
    1個のJSONファイルへ永続化するストア。bridge.py から呼ばれる。"""

    def __init__(self, path=None):
        self._path = Path(path) if path is not None else default_settings_path()
        self._lock = threading.RLock()
        self._data = {"granted_origins": {}, "known_devices": []}
        self._load()

    # ---- 内部: 読み書き ----

    def _load(self):
        with self._lock:
            try:
                raw = self._path.read_text(encoding="utf-8")
                data = json.loads(raw)
                if isinstance(data, dict):
                    self._data = {
                        "granted_origins": data.get("granted_origins") if isinstance(data.get("granted_origins"), dict) else {},
                        "known_devices": data.get("known_devices") if isinstance(data.get("known_devices"), list) else [],
                    }
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"[fox-webusb-host] settings_store: 読み込みに失敗、既定値で継続します: {e}", file=sys.stderr)

    def _save(self):
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp_name = tempfile.mkstemp(
                    prefix=".settings-", suffix=".json.tmp", dir=str(self._path.parent)
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(self._data, f, ensure_ascii=False, indent=2)
                    os.replace(tmp_name, self._path)
                except Exception:
                    try:
                        os.unlink(tmp_name)
                    except OSError:
                        pass
                    raise
            except Exception as e:
                print(f"[fox-webusb-host] settings_store: 保存に失敗しました: {e}", file=sys.stderr)

    # ---- granted_origins ----

    def load_granted_origins(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._data["granted_origins"]))  # deep copy

    def save_granted_origins(self, data: dict):
        with self._lock:
            self._data["granted_origins"] = data
            self._save()

    def is_granted(self, origin, vendor_id, product_id) -> bool:
        if not origin:
            return False
        grants = self.load_granted_origins().get(origin, [])
        return any(g.get("vendorId") == vendor_id and g.get("productId") == product_id for g in grants)

    def grant(self, origin, vendor_id, product_id):
        if not origin:
            return
        with self._lock:
            data = self._data["granted_origins"]
            grants = data.setdefault(origin, [])
            if not any(g.get("vendorId") == vendor_id and g.get("productId") == product_id for g in grants):
                import time
                grants.append({"vendorId": vendor_id, "productId": product_id, "grantedAt": time.time()})
                self._save()

    def revoke(self, origin, vendor_id, product_id) -> bool:
        with self._lock:
            data = self._data["granted_origins"]
            grants = data.get(origin, [])
            new_grants = [g for g in grants if not (g.get("vendorId") == vendor_id and g.get("productId") == product_id)]
            if len(new_grants) != len(grants):
                data[origin] = new_grants
                self._save()
                return True
            return False

    def revoke_all_for_origin(self, origin) -> bool:
        with self._lock:
            data = self._data["granted_origins"]
            if origin in data:
                del data[origin]
                self._save()
                return True
            return False

    def origins_granted_for_device(self, vendor_id, product_id) -> list:
        """このvendorId/productIdの組を許可しているオリジンの一覧を返す
        (ホットプラグ通知のファンアウト先を決めるための逆引き。移植元は
        1ページ=1ブリッジだったため『現在のページのオリジン』1つだけを見れば
        済んだが、fox-webusbのホストはブラウザ全体で1つなので、通知すべき
        全オリジンをここで洗い出す必要がある)。"""
        with self._lock:
            result = []
            for origin, grants in self._data["granted_origins"].items():
                if any(g.get("vendorId") == vendor_id and g.get("productId") == product_id for g in grants):
                    result.append(origin)
            return result

    # ---- known_devices ----

    def load_known_devices(self) -> list:
        with self._lock:
            return json.loads(json.dumps(self._data["known_devices"]))  # deep copy

    def save_known_devices(self, devices_list: list):
        with self._lock:
            self._data["known_devices"] = devices_list
            self._save()

    def record_device_usage(self, vendor_id, product_id, product_name, manufacturer_name):
        """接続したデバイスを既知一覧に記録し、最終接続時刻・接続回数を更新する
        (チューザーダイアログの並べ替えに使用)。"""
        import time
        with self._lock:
            devices = self._data["known_devices"]
            now = time.time()
            found = False
            for d in devices:
                if d.get("vendorId") == vendor_id and d.get("productId") == product_id:
                    d["lastConnected"] = now
                    d["connectCount"] = d.get("connectCount", 0) + 1
                    if product_name:
                        d["productName"] = product_name
                    if manufacturer_name:
                        d["manufacturerName"] = manufacturer_name
                    found = True
                    break
            if not found:
                devices.append({
                    "vendorId": vendor_id, "productId": product_id,
                    "productName": product_name, "manufacturerName": manufacturer_name,
                    "firstSeen": now, "lastConnected": now, "connectCount": 1,
                    "priority": len(devices),
                })
            self._save()
