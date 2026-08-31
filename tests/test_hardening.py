# -*- coding: utf-8 -*-
"""test_hardening.py: hardening.pyはQt非依存の純粋ロジックだったため
fox-webusbへの移植でもアルゴリズム自体は変更していない(コメントのみ
呼び出し側の変化に合わせて調整)。検証内容も移植元とほぼ同じ。"""
import usb.core

from fox_webusb_host.hardening import (
    PROTECTED_INTERFACE_CLASSES, is_protected_interface_class, protected_class_name,
    KNOWN_SECURITY_KEY_BLOCKLIST, is_blocklisted_device, device_is_fully_blocked,
    bcd_to_version, build_device_descriptor, build_configurations_tree, interface_class_for,
    UsbHotplugWatcher,
    is_valid_usb_device_filter, device_matches_any_usb_filter, device_matches_usb_filter,
    is_stall_error, is_babble_error, safe_error_str,
    CONTROL_TRANSFER_MAX_LENGTH, BULK_TRANSFER_MAX_LENGTH, ISOCHRONOUS_TRANSFER_MAX_TOTAL_LENGTH,
    scaled_transfer_timeout_ms,
)
from fake_usb import FakeUsbUtil, FakeDevice, FakeConfiguration, FakeInterface, FakeEndpoint, make_simple_device


# ============================================================
# 保護対象インターフェースクラス
# ============================================================

def test_all_eight_protected_classes_are_present():
    assert len(PROTECTED_INTERFACE_CLASSES) == 8
    for expected in (0x01, 0x03, 0x08, 0x09, 0x0B, 0x0E, 0x10, 0xE0):
        assert expected in PROTECTED_INTERFACE_CLASSES
    print("test_all_eight_protected_classes_are_present: OK")


def test_is_protected_interface_class_true_and_false_cases():
    assert is_protected_interface_class(0x03) is True   # HID
    assert is_protected_interface_class(0xFF) is False  # vendor-specific
    assert is_protected_interface_class(None) is True   # 判定不能は安全側
    print("test_is_protected_interface_class_true_and_false_cases: OK")


def test_protected_class_name_returns_readable_label():
    assert "HID" in protected_class_name(0x03)
    assert protected_class_name(0xFF) == "Unknown"
    print("test_protected_class_name_returns_readable_label: OK")


# ============================================================
# ブロックリスト
# ============================================================

def test_known_security_keys_are_blocklisted():
    vendor_id, product_id = next(iter(KNOWN_SECURITY_KEY_BLOCKLIST))
    assert is_blocklisted_device(vendor_id, product_id) is True
    print("test_known_security_keys_are_blocklisted: OK")


def test_unknown_device_is_not_blocklisted():
    assert is_blocklisted_device(0xDEAD, 0xBEEF) is False
    print("test_unknown_device_is_not_blocklisted: OK")


def test_device_is_fully_blocked_matches_blocklist():
    vendor_id, product_id = next(iter(KNOWN_SECURITY_KEY_BLOCKLIST))
    dev = make_simple_device(vendor_id=vendor_id, product_id=product_id)
    assert device_is_fully_blocked(dev) is True
    dev2 = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    assert device_is_fully_blocked(dev2) is False
    print("test_device_is_fully_blocked_matches_blocklist: OK")


# ============================================================
# BCDバージョン変換
# ============================================================

def test_bcd_to_version_decodes_standard_values():
    assert bcd_to_version(0x0210) == (2, 1, 0)
    assert bcd_to_version(0x0100) == (1, 0, 0)
    assert bcd_to_version(None) == (0, 0, 0)
    print("test_bcd_to_version_decodes_standard_values: OK")


# ============================================================
# デバイス記述子ビルダー
# ============================================================

def test_build_device_descriptor_includes_strings_and_versions():
    dev = make_simple_device(vendor_id=0x1234, product_id=0x5678, product_name="Widget",
                              manufacturer_name="Acme", serial="SN123")
    desc = build_device_descriptor(dev, FakeUsbUtil(), include_configurations=False)
    assert desc["vendorId"] == 0x1234
    assert desc["productId"] == 0x5678
    assert desc["productName"] == "Widget"
    assert desc["manufacturerName"] == "Acme"
    assert desc["serialNumber"] == "SN123"
    assert desc["usbVersionMajor"] == 2
    print("test_build_device_descriptor_includes_strings_and_versions: OK")


def test_build_device_descriptor_handles_missing_strings_gracefully():
    dev = FakeDevice(0x1111, 0x0001, configurations=[FakeConfiguration(1, [])])
    desc = build_device_descriptor(dev, FakeUsbUtil(), include_configurations=False)
    assert desc["productName"] is None
    assert desc["manufacturerName"] is None
    assert desc["serialNumber"] is None
    print("test_build_device_descriptor_handles_missing_strings_gracefully: OK")


def test_build_configurations_tree_excludes_control_endpoints():
    ep_ctrl = FakeEndpoint(0x00, FakeUsbUtil.ENDPOINT_TYPE_CTRL)
    ep_bulk_in = FakeEndpoint(0x81, FakeUsbUtil.ENDPOINT_TYPE_BULK)
    iface = FakeInterface(0, 0, endpoints=[ep_ctrl, ep_bulk_in])
    cfg = FakeConfiguration(1, [iface])
    dev = FakeDevice(0x1111, 0x0001, configurations=[cfg])
    tree = build_configurations_tree(dev, FakeUsbUtil())
    endpoints = tree[0]["interfaces"][0]["alternates"][0]["endpoints"]
    assert len(endpoints) == 1
    assert endpoints[0]["direction"] == "in"
    assert endpoints[0]["type"] == "bulk"
    print("test_build_configurations_tree_excludes_control_endpoints: OK")


def test_build_configurations_tree_groups_alternates_by_interface_number():
    alt0 = FakeInterface(0, 0, endpoints=[])
    alt1 = FakeInterface(0, 1, endpoints=[])
    cfg = FakeConfiguration(1, [alt0, alt1])
    dev = FakeDevice(0x1111, 0x0001, configurations=[cfg])
    tree = build_configurations_tree(dev, FakeUsbUtil())
    assert len(tree[0]["interfaces"]) == 1
    assert len(tree[0]["interfaces"][0]["alternates"]) == 2
    print("test_build_configurations_tree_groups_alternates_by_interface_number: OK")


def test_interface_class_for_looks_at_active_configuration_only():
    iface_a = FakeInterface(0, 0, interface_class=0x03)
    cfg_a = FakeConfiguration(1, [iface_a])
    iface_b = FakeInterface(0, 0, interface_class=0xFF)
    cfg_b = FakeConfiguration(2, [iface_b])
    dev = FakeDevice(0x1111, 0x0001, configurations=[cfg_a, cfg_b])
    assert interface_class_for(dev, 0) == 0x03  # 既定でアクティブなのはcfg_a
    dev.set_configuration(2)
    assert interface_class_for(dev, 0) == 0xFF
    print("test_interface_class_for_looks_at_active_configuration_only: OK")


def test_interface_class_for_returns_none_when_not_found():
    dev = make_simple_device()
    assert interface_class_for(dev, 99) is None
    print("test_interface_class_for_returns_none_when_not_found: OK")


# ============================================================
# ホットプラグ監視
# ============================================================

def test_hotplug_watcher_first_poll_reports_devices_already_present():
    # _knownは空集合から始まるため、コンストラクタ時点で既に挿さっている
    # デバイスも最初のpoll()では「新規接続」として報告される(基準だけを
    # 静かに作って何も返さない、という挙動ではない)。ホストプロセスは
    # ブラウザ全体で1つの常駐プロセスなので、これが起きるのは実質的に
    # ホスト起動直後の1回だけであり、原作(1ページ=1インスタンスだったため
    # ページ読み込みのたびに起きていた)よりも影響は小さい。
    pool = {(0x1111, 0x0001)}
    watcher = UsbHotplugWatcher(lambda: set(pool))
    connected, disconnected = watcher.poll()
    assert connected == [(0x1111, 0x0001)]
    assert disconnected == []
    print("test_hotplug_watcher_first_poll_reports_devices_already_present: OK")


def test_hotplug_watcher_reports_diffs_after_the_first_poll():
    pool = {(0x1111, 0x0001)}
    watcher = UsbHotplugWatcher(lambda: set(pool))
    watcher.poll()  # 基準を作る(既存デバイスぶんの初回connectを消費する)

    pool.add((0x2222, 0x0002))
    connected, disconnected = watcher.poll()
    assert connected == [(0x2222, 0x0002)]
    assert disconnected == []

    pool.discard((0x1111, 0x0001))
    connected, disconnected = watcher.poll()
    assert connected == []
    assert disconnected == [(0x1111, 0x0001)]
    print("test_hotplug_watcher_reports_diffs_after_the_first_poll: OK")


def test_hotplug_watcher_survives_finder_exceptions():
    def boom():
        raise RuntimeError("usb subsystem unavailable")

    watcher = UsbHotplugWatcher(boom)
    connected, disconnected = watcher.poll()
    assert connected == [] and disconnected == []
    print("test_hotplug_watcher_survives_finder_exceptions: OK")


# ============================================================
# デバイスフィルタ照合
# ============================================================

def test_is_valid_usb_device_filter_rejects_dangling_subfields():
    assert is_valid_usb_device_filter({"productId": 1}) is False  # vendorId無し
    assert is_valid_usb_device_filter({"vendorId": 1, "productId": 1}) is True
    assert is_valid_usb_device_filter({"subclassCode": 1}) is False  # classCode無し
    assert is_valid_usb_device_filter({"classCode": 1, "subclassCode": 1, "protocolCode": 1}) is True
    print("test_is_valid_usb_device_filter_rejects_dangling_subfields: OK")


def test_device_matches_usb_filter_by_vendor_and_product():
    dev = make_simple_device(vendor_id=0x1111, product_id=0x0001)
    assert device_matches_usb_filter(dev, FakeUsbUtil(), {"vendorId": 0x1111}) is True
    assert device_matches_usb_filter(dev, FakeUsbUtil(), {"vendorId": 0x9999}) is False
    assert device_matches_usb_filter(dev, FakeUsbUtil(), {"vendorId": 0x1111, "productId": 0x0002}) is False
    print("test_device_matches_usb_filter_by_vendor_and_product: OK")


def test_device_matches_usb_filter_via_interface_class_even_if_device_class_differs():
    # 複合デバイス(bDeviceClass=0xFF)で、個々のインターフェースが実際の
    # クラスを申告しているケース。
    iface = FakeInterface(0, 0, interface_class=0x03)  # HID
    cfg = FakeConfiguration(1, [iface])
    dev = FakeDevice(0x1111, 0x0001, configurations=[cfg], device_class=0xFF)
    assert device_matches_usb_filter(dev, FakeUsbUtil(), {"classCode": 0x03}) is True
    print("test_device_matches_usb_filter_via_interface_class_even_if_device_class_differs: OK")


def test_device_matches_any_usb_filter_empty_list_matches_nothing():
    dev = make_simple_device()
    assert device_matches_any_usb_filter(dev, FakeUsbUtil(), []) is False
    print("test_device_matches_any_usb_filter_empty_list_matches_nothing: OK")


def test_device_matches_any_usb_filter_empty_object_matches_everything():
    dev = make_simple_device()
    assert device_matches_any_usb_filter(dev, FakeUsbUtil(), [{}]) is True
    print("test_device_matches_any_usb_filter_empty_object_matches_everything: OK")


# ============================================================
# STALL / babble 検出
# ============================================================

def test_is_stall_error_recognizes_errno_32():
    err = usb.core.USBError("Pipe error", errno=32)
    assert is_stall_error(err) is True
    print("test_is_stall_error_recognizes_errno_32: OK")


def test_is_stall_error_false_for_unrelated_errors():
    assert is_stall_error(ValueError("something else")) is False
    print("test_is_stall_error_false_for_unrelated_errors: OK")


def test_is_babble_error_recognizes_errno_75():
    err = usb.core.USBError("Overflow", errno=75)
    assert is_babble_error(err) is True
    print("test_is_babble_error_recognizes_errno_75: OK")


# ============================================================
# 転送上限・タイムアウトスケーリング
# ============================================================

def test_transfer_limits_have_the_expected_orders_of_magnitude():
    assert CONTROL_TRANSFER_MAX_LENGTH == 0xFFFF
    assert BULK_TRANSFER_MAX_LENGTH == 64 * 1024 * 1024
    assert ISOCHRONOUS_TRANSFER_MAX_TOTAL_LENGTH == 16 * 1024 * 1024
    print("test_transfer_limits_have_the_expected_orders_of_magnitude: OK")


def test_safe_error_str_strips_control_characters():
    msg = safe_error_str(Exception("line one\nline two\ttabbed\rcarriage"))
    assert "\n" not in msg and "\t" not in msg and "\r" not in msg
    print("test_safe_error_str_strips_control_characters: OK")


def test_safe_error_str_truncates_long_messages():
    msg = safe_error_str(Exception("x" * 2000), max_len=500)
    assert len(msg) <= 501  # 500文字 + 省略記号1文字
    assert msg.endswith("…")
    print("test_safe_error_str_truncates_long_messages: OK")


def test_safe_error_str_never_raises_on_weird_exceptions():
    class Weird(Exception):
        def __str__(self):
            raise RuntimeError("boom inside __str__")

    msg = safe_error_str(Weird())
    assert isinstance(msg, str)
    print("test_safe_error_str_never_raises_on_weird_exceptions: OK")


def test_scaled_transfer_timeout_has_a_floor_and_a_ceiling():
    assert scaled_transfer_timeout_ms(0) == 5000
    assert scaled_transfer_timeout_ms(10**9) == 120000
    small = scaled_transfer_timeout_ms(1000)
    large = scaled_transfer_timeout_ms(10_000_000)
    assert small < large
    print("test_scaled_transfer_timeout_has_a_floor_and_a_ceiling: OK")
