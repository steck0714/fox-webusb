# -*- coding: utf-8 -*-
"""
test_bridge.py
==============
fox_webusb_host.bridge.WebUsbNativeBridge を、実機やlibusbバックエンドを
使わずに検証する。フェイクデバイス(fake_usb.py)を注入し、bridge.py内の
`usb_util`参照をFakeUsbUtilへ差し替える(monkeypatch)ことで、pyusbの
実バックエンドが必要な箇所(claim_interface等)も含めて丸ごとテストできる。

移植元(pyside6-webusb)のtest_bridge.pyで確認できたテスト名一覧を
チェックリストとして、fox-webusb向けのアーキテクチャ(オリジンは呼び出し元が
直接渡す/QSettingsではなくJSONファイル/PySide6ではなくTkinter/単一Qtスレッド
ではなくハンドル単位ロック)に合わせて書き直したもの。フレームトークン関連の
テスト(test_frame_tracker_wired_*)は、fox-webusbにはフレームトークンという
概念自体が無い(オリジンはbackground.js側でブラウザ自身が検証する)ため
対応するテストが無く、代わりに「別オリジンのhandleは触れない」という
同じ安全性を _get_open_device_and_info 単体で検証している。
"""
import tempfile
from pathlib import Path

import pytest

import fox_webusb_host.bridge as bridge_module
from fox_webusb_host.bridge import WebUsbNativeBridge
from fox_webusb_host.settings_store import SettingsStore
from fake_usb import FakeUsbUtil, FakeDevice, FakeConfiguration, FakeInterface, FakeEndpoint, make_simple_device


@pytest.fixture(autouse=True)
def _fake_usb_util(monkeypatch):
    monkeypatch.setattr(bridge_module, "usb_util", FakeUsbUtil())


@pytest.fixture
def tmp_settings(tmp_path):
    return SettingsStore(path=tmp_path / "settings.json")


def make_bridge(devices, tmp_settings, chooser_fn=None, event_sink=None):
    return WebUsbNativeBridge(
        settings_store=tmp_settings,
        chooser_fn=chooser_fn,
        event_sink=event_sink,
        usb_finder=lambda: list(devices),
    )


ORIGIN_A = "https://a.example.com"
ORIGIN_B = "https://b.example.com"


# ============================================================
# フィルタ照合 (requestDeviceChooser)
# ============================================================

def test_filters_narrow_the_candidate_list(tmp_settings):
    dev1 = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    dev2 = make_simple_device(vendor_id=0x2222, product_id=0x0002)
    seen = {}

    def chooser(devices, origin, refresh):
        seen["devices"] = devices
        return None  # キャンセル

    b = make_bridge([dev1, dev2], tmp_settings, chooser_fn=chooser)
    b.dispatch("requestDeviceChooser", ORIGIN_A, False, {"filters": [{"vendorId": 0x1111}]})
    assert [d["vendorId"] for d in seen["devices"]] == [0x1111]
    print("test_filters_narrow_the_candidate_list: OK")


def test_empty_filters_array_matches_nothing(tmp_settings):
    dev1 = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    seen = {}

    def chooser(devices, origin, refresh):
        seen["devices"] = devices
        return None

    b = make_bridge([dev1], tmp_settings, chooser_fn=chooser)
    b.dispatch("requestDeviceChooser", ORIGIN_A, False, {"filters": []})
    assert seen["devices"] == []
    print("test_empty_filters_array_matches_nothing: OK")


def test_exclusion_filters_remove_a_match(tmp_settings):
    dev1 = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    dev2 = make_simple_device(vendor_id=0x1111, product_id=0x0002)
    seen = {}

    def chooser(devices, origin, refresh):
        seen["devices"] = devices
        return None

    b = make_bridge([dev1, dev2], tmp_settings, chooser_fn=chooser)
    b.dispatch("requestDeviceChooser", ORIGIN_A, False, {
        "filters": [{"vendorId": 0x1111}],
        "exclusionFilters": [{"vendorId": 0x1111, "productId": 0x0002}],
    })
    assert [d["productId"] for d in seen["devices"]] == [0x0001]
    print("test_exclusion_filters_remove_a_match: OK")


def test_selected_device_gets_rich_descriptor(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001, product_name="Widget")

    def chooser(devices, origin, refresh):
        return devices[0]

    b = make_bridge([dev], tmp_settings, chooser_fn=chooser)
    res = b.dispatch("requestDeviceChooser", ORIGIN_A, False, {"filters": [{}]})
    assert res["success"] is True
    assert res["device"]["productName"] == "Widget"
    assert len(res["device"]["configurations"]) == 1
    assert res["device"]["configurations"][0]["interfaces"][0]["alternates"][0]["endpoints"]
    print("test_selected_device_gets_rich_descriptor: OK")


def test_grant_recorded_only_on_selection(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001)

    def cancel_chooser(devices, origin, refresh):
        return None

    b = make_bridge([dev], tmp_settings, chooser_fn=cancel_chooser)
    res = b.dispatch("requestDeviceChooser", ORIGIN_A, False, {"filters": [{}]})
    assert res["success"] is False
    assert tmp_settings.load_granted_origins() == {}

    def accept_chooser(devices, origin, refresh):
        return devices[0]

    b2 = make_bridge([dev], tmp_settings, chooser_fn=accept_chooser)
    res2 = b2.dispatch("requestDeviceChooser", ORIGIN_A, False, {"filters": [{}]})
    assert res2["success"] is True
    assert tmp_settings.is_granted(ORIGIN_A, 0x1111, 0x0001)
    print("test_grant_recorded_only_on_selection: OK")


def test_origin_is_passed_to_the_dialog(tmp_settings):
    dev = make_simple_device()
    seen = {}

    def chooser(devices, origin, refresh):
        seen["origin"] = origin
        return None

    b = make_bridge([dev], tmp_settings, chooser_fn=chooser)
    b.dispatch("requestDeviceChooser", "https://origin-under-test.example", False, {"filters": [{}]})
    assert seen["origin"] == "https://origin-under-test.example"
    print("test_origin_is_passed_to_the_dialog: OK")


def test_refresh_callback_reflects_newly_plugged_device(tmp_settings):
    dev1 = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    pool = [dev1]

    def chooser(devices, origin, refresh):
        assert len(devices) == 1
        dev2 = make_simple_device(vendor_id=0x1111, product_id=0x0002)
        pool.append(dev2)
        refreshed = refresh()
        assert len(refreshed) == 2
        return None

    b = make_bridge(pool, tmp_settings, chooser_fn=chooser)
    b.dispatch("requestDeviceChooser", ORIGIN_A, False, {"filters": [{"vendorId": 0x1111}]})
    print("test_refresh_callback_reflects_newly_plugged_device: OK")


def test_requestDeviceChooser_reentrancy_guard(tmp_settings):
    dev = make_simple_device()
    shared = {}

    def chooser(devices, origin, refresh):
        res = shared["bridge"].dispatch("requestDeviceChooser", ORIGIN_A, False, {"filters": [{}]})
        shared["inner"] = res
        return None

    b = make_bridge([dev], tmp_settings, chooser_fn=chooser)
    shared["bridge"] = b
    b.dispatch("requestDeviceChooser", ORIGIN_A, False, {"filters": [{}]})
    assert shared["inner"]["success"] is False
    assert "already open" in shared["inner"]["error"]
    print("test_requestDeviceChooser_reentrancy_guard: OK")


def test_full_flow_persists_grant_and_usage_without_mocking_internals(tmp_path):
    """SettingsStoreを一切モックせず、実際のJSONファイルへの読み書きを
    経由して許可・既知デバイス情報が正しく往復することを確認する。"""
    store_path = tmp_path / "settings.json"
    store1 = SettingsStore(path=store_path)
    dev = make_simple_device(vendor_id=0x9999, product_id=0x0001, product_name="Persisted Gadget")

    def chooser(devices, origin, refresh):
        return devices[0]

    b1 = make_bridge([dev], store1, chooser_fn=chooser)
    res = b1.dispatch("requestDeviceChooser", ORIGIN_A, False, {"filters": [{}]})
    assert res["success"] is True

    # 新しいSettingsStoreインスタンス(=プロセス再起動を模す)で同じファイルを開く
    store2 = SettingsStore(path=store_path)
    assert store2.is_granted(ORIGIN_A, 0x9999, 0x0001)
    known = store2.load_known_devices()
    assert any(d["vendorId"] == 0x9999 and d["connectCount"] == 1 for d in known)
    print("test_full_flow_persists_grant_and_usage_without_mocking_internals: OK")


# ============================================================
# open/claim/configuration の状態機械
# ============================================================

def test_open_device_requires_prior_grant(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    b = make_bridge([dev], tmp_settings)
    res = b.dispatch("openDevice", ORIGIN_A, False, {"vendorId": 0x1111, "productId": 0x0001})
    assert res["success"] is False
    assert res["error"].startswith("SecurityError")
    print("test_open_device_requires_prior_grant: OK")


def test_claimInterface_and_releaseInterface_require_configuration_selected(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001, interface_class=0xFF)
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    b = make_bridge([dev], tmp_settings)
    handle = b.dispatch("openDevice", ORIGIN_A, False, {"vendorId": 0x1111, "productId": 0x0001})["handle"]

    res = b.dispatch("claimInterface", ORIGIN_A, False, {"handle": handle, "interfaceNumber": 0})
    assert res["success"] is False
    assert res["error"].startswith("InvalidStateError")

    assert b.dispatch("selectConfiguration", ORIGIN_A, False, {"handle": handle, "configurationValue": 1})["success"]
    ok = b.dispatch("claimInterface", ORIGIN_A, False, {"handle": handle, "interfaceNumber": 0})
    assert ok["success"] is True
    print("test_claimInterface_and_releaseInterface_require_configuration_selected: OK")


def test_selectAlternateInterface_requires_claimed_interface(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    b = make_bridge([dev], tmp_settings)
    handle = b.dispatch("openDevice", ORIGIN_A, False, {"vendorId": 0x1111, "productId": 0x0001})["handle"]
    b.dispatch("selectConfiguration", ORIGIN_A, False, {"handle": handle, "configurationValue": 1})

    res = b.dispatch("selectAlternateInterface", ORIGIN_A, False, {"handle": handle, "interfaceNumber": 0, "alternateSetting": 0})
    assert res["success"] is False and res["error"].startswith("InvalidStateError")

    b.dispatch("claimInterface", ORIGIN_A, False, {"handle": handle, "interfaceNumber": 0})
    res2 = b.dispatch("selectAlternateInterface", ORIGIN_A, False, {"handle": handle, "interfaceNumber": 0, "alternateSetting": 0})
    assert res2["success"] is True
    print("test_selectAlternateInterface_requires_claimed_interface: OK")


def test_different_origin_cannot_touch_another_origins_handle(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    b = make_bridge([dev], tmp_settings)
    handle = b.dispatch("openDevice", ORIGIN_A, False, {"vendorId": 0x1111, "productId": 0x0001})["handle"]

    res = b.dispatch("selectConfiguration", ORIGIN_B, False, {"handle": handle, "configurationValue": 1})
    assert res["success"] is False
    assert res["error"].startswith("NotFoundError")  # 存在の有無自体を漏らさない
    print("test_different_origin_cannot_touch_another_origins_handle: OK")


# ============================================================
# claimInterfaceの保護対象クラス/ブロックリスト
# ============================================================

def test_claimInterface_rejects_protected_interface_class(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001, interface_class=0x03)  # HID
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    b = make_bridge([dev], tmp_settings)
    handle = b.dispatch("openDevice", ORIGIN_A, False, {"vendorId": 0x1111, "productId": 0x0001})["handle"]
    b.dispatch("selectConfiguration", ORIGIN_A, False, {"handle": handle, "configurationValue": 1})
    res = b.dispatch("claimInterface", ORIGIN_A, False, {"handle": handle, "interfaceNumber": 0})
    assert res["success"] is False
    assert res["error"].startswith("SecurityError")
    assert "HID" in res["error"]
    print("test_claimInterface_rejects_protected_interface_class: OK")


# ============================================================
# bulk transfer
# ============================================================

def _open_and_claim(b, origin, vendor_id, product_id, interface_number=0):
    handle = b.dispatch("openDevice", origin, False, {"vendorId": vendor_id, "productId": product_id})["handle"]
    b.dispatch("selectConfiguration", origin, False, {"handle": handle, "configurationValue": 1})
    b.dispatch("claimInterface", origin, False, {"handle": handle, "interfaceNumber": interface_number})
    return handle


def test_bulkTransferIn_adds_the_in_direction_bit(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001, num_endpoints_bulk=(2, 2))
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    seen = {}

    def on_read(endpoint, length, timeout):
        seen["endpoint"] = endpoint
        return b"hello"

    dev.on_read = on_read
    b = make_bridge([dev], tmp_settings)
    handle = _open_and_claim(b, ORIGIN_A, 0x1111, 0x0001)
    res = b.dispatch("bulkTransferIn", ORIGIN_A, False, {"handle": handle, "endpoint": 2, "length": 64})
    assert res["success"] is True
    assert seen["endpoint"] == 0x82
    import base64
    assert base64.b64decode(res["data"]) == b"hello"
    print("test_bulkTransferIn_adds_the_in_direction_bit: OK")


def test_bulk_transfer_and_clearHalt_require_claimed_interface(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    b = make_bridge([dev], tmp_settings)
    handle = b.dispatch("openDevice", ORIGIN_A, False, {"vendorId": 0x1111, "productId": 0x0001})["handle"]
    b.dispatch("selectConfiguration", ORIGIN_A, False, {"handle": handle, "configurationValue": 1})

    res = b.dispatch("bulkTransferIn", ORIGIN_A, False, {"handle": handle, "endpoint": 1, "length": 8})
    assert res["success"] is False and res["error"].startswith("NotFoundError")

    res2 = b.dispatch("clearHalt", ORIGIN_A, False, {"handle": handle, "direction": "in", "endpointNumber": 1})
    assert res2["success"] is False and res2["error"].startswith("NotFoundError")
    print("test_bulk_transfer_and_clearHalt_require_claimed_interface: OK")


def test_bulk_transfer_rejects_out_of_range_endpoint_number(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    b = make_bridge([dev], tmp_settings)
    handle = _open_and_claim(b, ORIGIN_A, 0x1111, 0x0001)
    res = b.dispatch("bulkTransferIn", ORIGIN_A, False, {"handle": handle, "endpoint": 99, "length": 8})
    assert res["success"] is False and res["error"].startswith("IndexSizeError")
    print("test_bulk_transfer_rejects_out_of_range_endpoint_number: OK")


def test_bulk_transfer_rejects_absurdly_large_length(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    b = make_bridge([dev], tmp_settings)
    handle = _open_and_claim(b, ORIGIN_A, 0x1111, 0x0001)
    res = b.dispatch("bulkTransferIn", ORIGIN_A, False, {"handle": handle, "endpoint": 1, "length": 10**12})
    assert res["success"] is False and res["error"].startswith("IndexSizeError")
    print("test_bulk_transfer_rejects_absurdly_large_length: OK")


def test_bulk_transfer_reports_stall_as_successful_status(tmp_settings):
    import usb.core

    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)

    def on_read(endpoint, length, timeout):
        raise usb.core.USBError("Pipe error", errno=32)

    dev.on_read = on_read
    b = make_bridge([dev], tmp_settings)
    handle = _open_and_claim(b, ORIGIN_A, 0x1111, 0x0001)
    res = b.dispatch("bulkTransferIn", ORIGIN_A, False, {"handle": handle, "endpoint": 1, "length": 8})
    assert res["success"] is True
    assert res["status"] == "stall"
    print("test_bulk_transfer_reports_stall_as_successful_status: OK")


def test_bulk_transfer_round_trips_realistic_payload(tmp_settings):
    """WebADB規模のペイロード(300KB)がbulkTransferOut→bulkTransferInの往復で
    1バイトも壊れずに転送できることを確認する(Rustアクセラレーションが
    ビルドされていればそちらの、無ければ標準base64のパスを通る)。"""
    import random
    random.seed(20260830)
    payload = bytes(random.randrange(256) for _ in range(300_000))

    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001, num_endpoints_bulk=(2, 2))
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    captured = {}

    def on_write(endpoint, data, timeout):
        captured["written"] = bytes(data)
        return len(data)

    def on_read(endpoint, length, timeout):
        return captured["written"]

    dev.on_write = on_write
    dev.on_read = on_read
    b = make_bridge([dev], tmp_settings)
    handle = _open_and_claim(b, ORIGIN_A, 0x1111, 0x0001)

    import base64
    out_res = b.dispatch("bulkTransferOut", ORIGIN_A, False, {
        "handle": handle, "endpoint": 2, "data": base64.b64encode(payload).decode("ascii"),
    })
    assert out_res["success"] is True and out_res["bytesWritten"] == len(payload)

    in_res = b.dispatch("bulkTransferIn", ORIGIN_A, False, {"handle": handle, "endpoint": 2, "length": len(payload)})
    assert in_res["success"] is True
    assert base64.b64decode(in_res["data"]) == payload
    print("test_bulk_transfer_round_trips_realistic_payload: OK")


def test_bulk_transfer_reentrant_call_on_busy_handle_is_rejected(tmp_settings):
    """🆕 fox-webusb: 原作のQt processEvents()経由の再入対策(_busy_handles)を、
    本物のスレッド並行性向けに一般化したper-handleロックの検証。転送の
    最中に別スレッドから同じhandleへ操作しようとすると弾かれる。"""
    import threading

    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    release_read = threading.Event()
    read_started = threading.Event()

    def on_read(endpoint, length, timeout):
        read_started.set()
        release_read.wait(timeout=5)
        return b"data"

    dev.on_read = on_read
    b = make_bridge([dev], tmp_settings)
    handle = _open_and_claim(b, ORIGIN_A, 0x1111, 0x0001)

    results = {}

    def do_read():
        results["read"] = b.dispatch("bulkTransferIn", ORIGIN_A, False, {"handle": handle, "endpoint": 1, "length": 8})

    t = threading.Thread(target=do_read)
    t.start()
    assert read_started.wait(timeout=5)

    busy_res = b.dispatch("claimInterface", ORIGIN_A, False, {"handle": handle, "interfaceNumber": 0})
    assert busy_res["success"] is False
    assert busy_res["error"].startswith("InvalidStateError")
    assert "busy" in busy_res["error"]

    release_read.set()
    t.join(timeout=5)
    assert results["read"]["success"] is True
    print("test_bulk_transfer_reentrant_call_on_busy_handle_is_rejected: OK")


# ============================================================
# control transfer
# ============================================================

def test_control_transfer_class_request_to_protected_interface_is_blocked(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001, interface_class=0x03)  # HID
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    b = make_bridge([dev], tmp_settings)
    handle = b.dispatch("openDevice", ORIGIN_A, False, {"vendorId": 0x1111, "productId": 0x0001})["handle"]
    b.dispatch("selectConfiguration", ORIGIN_A, False, {"handle": handle, "configurationValue": 1})
    # claimInterfaceは保護対象クラスなので失敗する。狙った分岐(クラス保護)を
    # 検証するため、テスト用にclaimed_interfacesへ直接注入しておく。
    b._open_devices[handle]["claimed_interfaces"].add(0)
    RECIPIENT_INTERFACE = 0x01
    TYPE_CLASS = 0x20
    res = b.dispatch("controlTransferOut", ORIGIN_A, False, {
        "handle": handle, "requestType": TYPE_CLASS | RECIPIENT_INTERFACE,
        "request": 0x01, "value": 0, "index": 0, "data": "",
    })
    assert res["success"] is False
    assert res["error"].startswith("SecurityError")
    print("test_control_transfer_class_request_to_protected_interface_is_blocked: OK")


def test_control_transfer_interface_recipient_requires_claim(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    b = make_bridge([dev], tmp_settings)
    handle = b.dispatch("openDevice", ORIGIN_A, False, {"vendorId": 0x1111, "productId": 0x0001})["handle"]
    b.dispatch("selectConfiguration", ORIGIN_A, False, {"handle": handle, "configurationValue": 1})
    RECIPIENT_INTERFACE = 0x01
    TYPE_VENDOR = 0x40
    res = b.dispatch("controlTransferOut", ORIGIN_A, False, {
        "handle": handle, "requestType": TYPE_VENDOR | RECIPIENT_INTERFACE,
        "request": 0x01, "value": 0, "index": 0, "data": "",
    })
    assert res["success"] is False and res["error"].startswith("InvalidStateError")

    b.dispatch("claimInterface", ORIGIN_A, False, {"handle": handle, "interfaceNumber": 0})
    res2 = b.dispatch("controlTransferOut", ORIGIN_A, False, {
        "handle": handle, "requestType": TYPE_VENDOR | RECIPIENT_INTERFACE,
        "request": 0x01, "value": 0, "index": 0, "data": "",
    })
    assert res2["success"] is True
    print("test_control_transfer_interface_recipient_requires_claim: OK")


def test_control_transfer_standard_request_restrictions(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    b = make_bridge([dev], tmp_settings)
    handle = b.dispatch("openDevice", ORIGIN_A, False, {"vendorId": 0x1111, "productId": 0x0001})["handle"]
    b.dispatch("selectConfiguration", ORIGIN_A, False, {"handle": handle, "configurationValue": 1})
    TYPE_STANDARD = 0x00
    RECIPIENT_DEVICE = 0x00
    SET_CONFIGURATION = 0x09
    res = b.dispatch("controlTransferOut", ORIGIN_A, False, {
        "handle": handle, "requestType": TYPE_STANDARD | RECIPIENT_DEVICE,
        "request": SET_CONFIGURATION, "value": 1, "index": 0, "data": "",
    })
    assert res["success"] is False and res["error"].startswith("SecurityError")
    print("test_control_transfer_standard_request_restrictions: OK")


def test_control_transfer_length_is_capped_at_unsigned_short(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    b = make_bridge([dev], tmp_settings)
    handle = b.dispatch("openDevice", ORIGIN_A, False, {"vendorId": 0x1111, "productId": 0x0001})["handle"]
    res = b.dispatch("controlTransferIn", ORIGIN_A, False, {
        "handle": handle, "requestType": 0x40, "request": 1, "value": 0, "index": 0, "length": 0x10000,
    })
    assert res["success"] is False and res["error"].startswith("IndexSizeError")
    print("test_control_transfer_length_is_capped_at_unsigned_short: OK")


# ============================================================
# isochronous transfer
# ============================================================

def _device_with_iso_endpoint(vendor_id=0x1111, product_id=0x0001):
    endpoints = [FakeEndpoint(1 | 0x80, FakeUsbUtil.ENDPOINT_TYPE_ISO), FakeEndpoint(1, FakeUsbUtil.ENDPOINT_TYPE_BULK)]
    iface = FakeInterface(0, 0, interface_class=0xFF, endpoints=endpoints)
    cfg = FakeConfiguration(1, [iface])
    return FakeDevice(vendor_id, product_id, configurations=[cfg])


def test_isochronousTransfer_rejects_non_uniform_packet_lengths(tmp_settings):
    dev = _device_with_iso_endpoint()
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    b = make_bridge([dev], tmp_settings)
    handle = _open_and_claim(b, ORIGIN_A, 0x1111, 0x0001)
    res = b.dispatch("isochronousTransferIn", ORIGIN_A, False, {"handle": handle, "endpoint": 1, "packetLengths": [8, 16]})
    assert res["success"] is False and res["error"].startswith("InvalidAccessError")
    print("test_isochronousTransfer_rejects_non_uniform_packet_lengths: OK")


def test_isochronousTransfer_requires_claimed_isochronous_endpoint(tmp_settings):
    dev = _device_with_iso_endpoint()
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    b = make_bridge([dev], tmp_settings)
    handle = b.dispatch("openDevice", ORIGIN_A, False, {"vendorId": 0x1111, "productId": 0x0001})["handle"]
    b.dispatch("selectConfiguration", ORIGIN_A, False, {"handle": handle, "configurationValue": 1})
    res = b.dispatch("isochronousTransferIn", ORIGIN_A, False, {"handle": handle, "endpoint": 1, "packetLengths": [8, 8]})
    assert res["success"] is False and res["error"].startswith("NotFoundError")
    print("test_isochronousTransfer_requires_claimed_isochronous_endpoint: OK")


def test_isochronousTransfer_success_path_with_fake_backend(tmp_settings):
    dev = _device_with_iso_endpoint()
    dev.on_read = lambda endpoint, length, timeout: b"A" * length
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    b = make_bridge([dev], tmp_settings)
    handle = _open_and_claim(b, ORIGIN_A, 0x1111, 0x0001)
    res = b.dispatch("isochronousTransferIn", ORIGIN_A, False, {"handle": handle, "endpoint": 1, "packetLengths": [4, 4]})
    assert res["success"] is True
    assert len(res["packets"]) == 2
    import base64
    assert base64.b64decode(res["packets"][0]["data"]) == b"AAAA"
    print("test_isochronousTransfer_success_path_with_fake_backend: OK")


def test_isochronousTransfer_rejects_oversized_total_packet_lengths(tmp_settings):
    dev = _device_with_iso_endpoint()
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    b = make_bridge([dev], tmp_settings)
    handle = _open_and_claim(b, ORIGIN_A, 0x1111, 0x0001)
    huge = [1024 * 1024] * 20  # 20MB > ISOCHRONOUS_TRANSFER_MAX_TOTAL_LENGTH(16MiB)
    res = b.dispatch("isochronousTransferIn", ORIGIN_A, False, {"handle": handle, "endpoint": 1, "packetLengths": huge})
    assert res["success"] is False and res["error"].startswith("IndexSizeError")
    print("test_isochronousTransfer_rejects_oversized_total_packet_lengths: OK")


# ============================================================
# 信頼済み専用メソッド (origin管理)
# ============================================================

def test_trusted_only_methods_reject_untrusted_caller(tmp_settings):
    b = make_bridge([], tmp_settings)
    res = b.dispatch("listGrantedOrigins", None, False, {})
    assert res["success"] is False and res["error"].startswith("SecurityError")
    print("test_trusted_only_methods_reject_untrusted_caller: OK")


def test_revoke_origin_grant_and_list_granted_origins(tmp_settings):
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    tmp_settings.grant(ORIGIN_A, 0x2222, 0x0002)
    b = make_bridge([], tmp_settings)
    listed = b.dispatch("listGrantedOrigins", None, True, {})
    assert ORIGIN_A in listed["origins"]
    assert len(listed["origins"][ORIGIN_A]) == 2

    revoked = b.dispatch("revokeOriginGrant", None, True, {"origin": ORIGIN_A, "vendorId": 0x1111, "productId": 0x0001})
    assert revoked["success"] is True
    assert not tmp_settings.is_granted(ORIGIN_A, 0x1111, 0x0001)
    assert tmp_settings.is_granted(ORIGIN_A, 0x2222, 0x0002)
    print("test_revoke_origin_grant_and_list_granted_origins: OK")


def test_origin_closed_releases_open_handles(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    b = make_bridge([dev], tmp_settings)
    handle = _open_and_claim(b, ORIGIN_A, 0x1111, 0x0001)
    assert handle in b._open_devices

    res = b.dispatch("originClosed", None, True, {"origin": ORIGIN_A})
    assert res["success"] is True
    assert handle not in b._open_devices
    print("test_origin_closed_releases_open_handles: OK")


# ============================================================
# ホットプラグ
# ============================================================

def test_poll_hotplug_events_notifies_only_granted_origins(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    tmp_settings.grant(ORIGIN_A, 0x1111, 0x0001)
    events = []
    pool = []
    b = make_bridge(pool, tmp_settings, event_sink=events.append)

    pool.append(dev)
    b.poll_hotplug_events()
    assert len(events) == 1
    assert events[0]["event"] == "connect"
    assert events[0]["origins"] == [ORIGIN_A]

    pool.remove(dev)
    b.poll_hotplug_events()
    assert len(events) == 2
    assert events[1]["event"] == "disconnect"
    print("test_poll_hotplug_events_notifies_only_granted_origins: OK")


def test_poll_hotplug_events_ignores_ungranted_devices(tmp_settings):
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    events = []
    pool = []
    b = make_bridge(pool, tmp_settings, event_sink=events.append)
    pool.append(dev)
    b.poll_hotplug_events()
    assert events == []
    print("test_poll_hotplug_events_ignores_ungranted_devices: OK")
