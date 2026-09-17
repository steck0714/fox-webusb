# -*- coding: utf-8 -*-
"""test_settings_store.py: SettingsStore(QSettingsの代替となるJSONファイル
ストア)の読み書き・原子性・オリジン単位/デバイス単位それぞれの操作を検証する。"""
import json

from fox_webusb_host.settings_store import SettingsStore


def test_grant_and_is_granted_round_trip(tmp_path):
    store = SettingsStore(path=tmp_path / "s.json")
    assert store.is_granted("https://a.example", 1, 2) is False
    store.grant("https://a.example", 1, 2)
    assert store.is_granted("https://a.example", 1, 2) is True
    assert store.is_granted("https://b.example", 1, 2) is False
    print("test_grant_and_is_granted_round_trip: OK")


def test_grant_is_idempotent():
    import tempfile
    from pathlib import Path
    store = SettingsStore(path=Path(tempfile.mkdtemp()) / "s.json")
    store.grant("https://a.example", 1, 2)
    store.grant("https://a.example", 1, 2)
    grants = store.load_granted_origins()["https://a.example"]
    assert len(grants) == 1
    print("test_grant_is_idempotent: OK")


def test_revoke_removes_only_the_matching_pair(tmp_path):
    store = SettingsStore(path=tmp_path / "s.json")
    store.grant("https://a.example", 1, 2)
    store.grant("https://a.example", 3, 4)
    assert store.revoke("https://a.example", 1, 2) is True
    assert store.is_granted("https://a.example", 1, 2) is False
    assert store.is_granted("https://a.example", 3, 4) is True
    assert store.revoke("https://a.example", 1, 2) is False  # 既に無いものはFalse
    print("test_revoke_removes_only_the_matching_pair: OK")


def test_revoke_all_for_origin(tmp_path):
    store = SettingsStore(path=tmp_path / "s.json")
    store.grant("https://a.example", 1, 2)
    store.grant("https://a.example", 3, 4)
    store.grant("https://b.example", 5, 6)
    assert store.revoke_all_for_origin("https://a.example") is True
    assert store.load_granted_origins() == {"https://b.example": store.load_granted_origins()["https://b.example"]}
    print("test_revoke_all_for_origin: OK")


def test_origins_granted_for_device_reverse_lookup(tmp_path):
    store = SettingsStore(path=tmp_path / "s.json")
    store.grant("https://a.example", 1, 2)
    store.grant("https://b.example", 1, 2)
    store.grant("https://c.example", 9, 9)
    origins = set(store.origins_granted_for_device(1, 2))
    assert origins == {"https://a.example", "https://b.example"}
    print("test_origins_granted_for_device_reverse_lookup: OK")


def test_record_device_usage_increments_connect_count(tmp_path):
    store = SettingsStore(path=tmp_path / "s.json")
    store.record_device_usage(1, 2, "Widget", "Acme")
    store.record_device_usage(1, 2, "Widget", "Acme")
    store.record_device_usage(1, 2, "Widget", "Acme")
    devices = store.load_known_devices()
    assert len(devices) == 1
    assert devices[0]["connectCount"] == 3
    print("test_record_device_usage_increments_connect_count: OK")


def test_settings_persist_across_new_store_instances(tmp_path):
    path = tmp_path / "s.json"
    store1 = SettingsStore(path=path)
    store1.grant("https://a.example", 1, 2)
    store1.record_device_usage(1, 2, "Widget", "Acme")

    store2 = SettingsStore(path=path)
    assert store2.is_granted("https://a.example", 1, 2)
    assert store2.load_known_devices()[0]["productName"] == "Widget"
    print("test_settings_persist_across_new_store_instances: OK")


def test_missing_file_starts_with_empty_defaults(tmp_path):
    store = SettingsStore(path=tmp_path / "does-not-exist" / "s.json")
    assert store.load_granted_origins() == {}
    assert store.load_known_devices() == []
    print("test_missing_file_starts_with_empty_defaults: OK")


def test_corrupted_file_falls_back_to_defaults_without_crashing(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{ this is not valid json", encoding="utf-8")
    store = SettingsStore(path=path)
    assert store.load_granted_origins() == {}
    print("test_corrupted_file_falls_back_to_defaults_without_crashing: OK")


def test_written_file_is_valid_json_on_disk(tmp_path):
    path = tmp_path / "s.json"
    store = SettingsStore(path=path)
    store.grant("https://a.example", 1, 2)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert "granted_origins" in data and "known_devices" in data
    print("test_written_file_is_valid_json_on_disk: OK")


def test_default_settings_path_is_platform_appropriate(monkeypatch):
    from fox_webusb_host import settings_store as ss

    monkeypatch.setattr(ss.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\test\AppData\Roaming")
    p = ss.default_settings_path()
    assert "fox-webusb" in str(p) and "settings.json" in str(p)

    monkeypatch.setattr(ss.sys, "platform", "darwin")
    p2 = ss.default_settings_path()
    assert "Library" in str(p2) and "Application Support" in str(p2)

    monkeypatch.setattr(ss.sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    p3 = ss.default_settings_path()
    assert ".config" in str(p3)
    print("test_default_settings_path_is_platform_appropriate: OK")
