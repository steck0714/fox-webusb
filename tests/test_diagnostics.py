# -*- coding: utf-8 -*-
"""test_diagnostics.py: diagnostics.py(v0.0.0.3で追加、`fox-webusb-host-doctor`
のバックエンド)の environment_report() / format_environment_report() /
main() を検証する。姉妹プロジェクトpyside6-webusbのtest_diagnostics.pyと
同じ手法(sys.modulesへのNone注入で「未インストール」を模擬する、pytest公式
に文書化された定石)を、fox-webusb-host自身の診断項目(pyusbバックエンド・
ネイティブメッセージングマニフェストの登録状況・コンソールスクリプトの
発見)に合わせて使う。"""
import json
import sys

import fox_webusb_host.diagnostics as diagnostics


def test_environment_report_reflects_the_running_interpreter():
    report = diagnostics.environment_report()
    assert report["fox_webusb_host_version"] == diagnostics.__version__
    assert report["python_executable"] == sys.executable
    assert isinstance(report["problems"], list)
    print("test_environment_report_reflects_the_running_interpreter: OK")


def test_environment_report_detects_missing_pyusb(monkeypatch):
    monkeypatch.setitem(sys.modules, "usb", None)
    report = diagnostics.environment_report()
    assert report["pyusb_version"] is None
    assert report["pyusb_backend"] is None
    assert any("pyusb自体がimportできません" in p for p in report["problems"])
    print("test_environment_report_detects_missing_pyusb: OK")


def _fake_usb_module(libusb1_backend, libusb0_backend, version="1.9.9-fake"):
    """usb / usb.backend / usb.backend.libusb1 / usb.backend.libusb0 の
    連鎖を丸ごと偽物に差し替えるためのヘルパー。`usb`だけ・葉モジュールだけを
    sys.modulesに差し込んでも、他のテスト(test_bridge.py等)が既にこの
    プロセス内で本物のusb.backendを一度importしていると、
    `import usb.backend.libusb1 as _libusb1`が(sys.modulesの葉エントリでは
    なく)`usb.backend`の本物の`.libusb1`属性を辿って本物を掴んでしまい、
    偽装が効かない(実際にこのテストを書く過程で、まさにこの理由で
    最初の実装がこっそり本物のlibusb1を掴んでいたことが判明した——
    sys.modulesの1エントリだけを差し替える版は一見通るが、何を検証しているか
    ズレていた)。usb.backend自体、およびその属性も含めて丸ごと偽物にする
    ことで、どちらの解決経路でも確実に偽物を掴むようにしている。"""
    import types
    fake_usb = types.ModuleType("usb")
    fake_usb.__version__ = version
    fake_backend_pkg = types.ModuleType("usb.backend")
    fake_libusb1 = types.ModuleType("usb.backend.libusb1")
    fake_libusb1.get_backend = lambda *a, **k: libusb1_backend
    fake_libusb0 = types.ModuleType("usb.backend.libusb0")
    fake_libusb0.get_backend = lambda *a, **k: libusb0_backend
    fake_backend_pkg.libusb1 = fake_libusb1
    fake_backend_pkg.libusb0 = fake_libusb0
    fake_usb.backend = fake_backend_pkg
    return fake_usb, fake_backend_pkg, fake_libusb1, fake_libusb0


def test_environment_report_detects_missing_libusb_backend_when_pyusb_present(monkeypatch):
    """pyusb自体はimportできるが、libusb1/libusb0どちらのバックエンドも
    解決できない(OS側の共有ライブラリが無い)ケース。"""
    fake_usb, fake_backend_pkg, fake_libusb1, fake_libusb0 = _fake_usb_module(None, None)
    monkeypatch.setitem(sys.modules, "usb", fake_usb)
    monkeypatch.setitem(sys.modules, "usb.backend", fake_backend_pkg)
    monkeypatch.setitem(sys.modules, "usb.backend.libusb1", fake_libusb1)
    monkeypatch.setitem(sys.modules, "usb.backend.libusb0", fake_libusb0)

    report = diagnostics.environment_report()
    assert report["pyusb_version"] == "1.9.9-fake"
    assert report["pyusb_backend"] is None
    assert any("libusb共有ライブラリが見つかりません" in p for p in report["problems"])
    print("test_environment_report_detects_missing_libusb_backend_when_pyusb_present: OK")


def test_environment_report_detects_a_resolved_libusb1_backend(monkeypatch):
    sentinel = object()
    fake_usb, fake_backend_pkg, fake_libusb1, fake_libusb0 = _fake_usb_module(sentinel, None)
    monkeypatch.setitem(sys.modules, "usb", fake_usb)
    monkeypatch.setitem(sys.modules, "usb.backend", fake_backend_pkg)
    monkeypatch.setitem(sys.modules, "usb.backend.libusb1", fake_libusb1)
    monkeypatch.setitem(sys.modules, "usb.backend.libusb0", fake_libusb0)

    report = diagnostics.environment_report()
    assert report["pyusb_backend"] == "libusb1"
    assert not any("libusb" in p for p in report["problems"])
    print("test_environment_report_detects_a_resolved_libusb1_backend: OK")


def test_rust_accel_status_is_reported_but_never_a_problem(monkeypatch):
    monkeypatch.setitem(sys.modules, "fox_webusb_accel", None)
    report = diagnostics.environment_report()
    assert report["rust_accelerated"] is False
    assert not any("Rust" in p or "accel" in p for p in report["problems"])
    print("test_rust_accel_status_is_reported_but_never_a_problem: OK")


def test_console_script_missing_is_reported_as_a_problem(monkeypatch):
    monkeypatch.setattr(diagnostics, "_installed_console_script_path", lambda: None)
    report = diagnostics.environment_report()
    assert report["console_script_path"] is None
    assert any("コンソールスクリプトが見つかりません" in p for p in report["problems"])
    print("test_console_script_missing_is_reported_as_a_problem: OK")


def test_console_script_found_is_not_a_problem(monkeypatch):
    monkeypatch.setattr(diagnostics, "_installed_console_script_path", lambda: "/fake/bin/fox-webusb-host")
    report = diagnostics.environment_report()
    assert report["console_script_path"] == "/fake/bin/fox-webusb-host"
    assert not any("コンソールスクリプト" in p for p in report["problems"])
    print("test_console_script_found_is_not_a_problem: OK")


def test_native_manifest_status_when_not_registered(tmp_path):
    manifest_path = tmp_path / "org.fox_webusb.host.json"
    registered, launcher_path, launcher_exists, path = diagnostics._native_manifest_status(str(manifest_path))
    assert registered is False
    assert launcher_path is None
    assert path == str(manifest_path)
    print("test_native_manifest_status_when_not_registered: OK")


def test_native_manifest_status_when_registered_and_launcher_exists(tmp_path):
    launcher = tmp_path / "fox-webusb-host"
    launcher.write_text("#!/bin/sh\n")
    manifest_path = tmp_path / "org.fox_webusb.host.json"
    manifest_path.write_text(json.dumps({"path": str(launcher)}))

    registered, launcher_path, launcher_exists, path = diagnostics._native_manifest_status(str(manifest_path))
    assert registered is True
    assert launcher_path == str(launcher)
    assert launcher_exists is True
    print("test_native_manifest_status_when_registered_and_launcher_exists: OK")


def test_native_manifest_status_flags_a_missing_launcher_as_a_problem(tmp_path, monkeypatch):
    """登録済みマニフェストがあるのに、そこが指すランチャーが実在しない
    (削除された・パスが変わった等)ケースは、単なる未登録とは違い明示的な
    問題として報告されるべき。"""
    manifest_path = tmp_path / "org.fox_webusb.host.json"
    manifest_path.write_text(json.dumps({"path": str(tmp_path / "gone")}))
    monkeypatch.setattr(diagnostics, "_default_native_manifest_path", lambda: str(manifest_path))

    report = diagnostics.environment_report()
    assert report["native_manifest_registered"] is True
    assert report["native_manifest_launcher_exists"] is False
    assert any("起動パス" in p and "見つかりません" in p for p in report["problems"])
    print("test_native_manifest_status_flags_a_missing_launcher_as_a_problem: OK")


def test_format_environment_report_lists_problems_when_present():
    report = diagnostics.environment_report()
    report["problems"] = ["ダミーの問題A", "ダミーの問題B"]
    text = diagnostics.format_environment_report(report)
    assert "検出された問題:" in text
    assert "ダミーの問題A" in text and "ダミーの問題B" in text
    print("test_format_environment_report_lists_problems_when_present: OK")


def test_format_environment_report_says_clean_when_no_problems():
    report = diagnostics.environment_report()
    report["problems"] = []
    text = diagnostics.format_environment_report(report)
    assert "問題は検出されませんでした。" in text
    print("test_format_environment_report_says_clean_when_no_problems: OK")


def test_main_returns_zero_when_clean_and_nonzero_when_problems(monkeypatch, capsys):
    monkeypatch.setattr(diagnostics, "environment_report", lambda: {"problems": []})
    monkeypatch.setattr(diagnostics, "format_environment_report", lambda r: "OK-TEXT")
    assert diagnostics.main(argv=[]) == 0
    assert "OK-TEXT" in capsys.readouterr().out

    monkeypatch.setattr(diagnostics, "environment_report", lambda: {"problems": ["x"]})
    assert diagnostics.main(argv=[]) == 1
    print("test_main_returns_zero_when_clean_and_nonzero_when_problems: OK")


def test_main_json_flag_prints_the_raw_report_as_json_with_the_same_exit_code(monkeypatch, capsys):
    fake_report = {"problems": [], "fox_webusb_host_version": "0.0.0.3"}
    monkeypatch.setattr(diagnostics, "environment_report", lambda: fake_report)
    exit_code = diagnostics.main(argv=["--json"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert json.loads(out) == fake_report
    print("test_main_json_flag_prints_the_raw_report_as_json_with_the_same_exit_code: OK")


def test_main_falls_back_to_sys_argv_when_argv_is_none(monkeypatch, capsys):
    """setuptoolsが生成する実際のコンソールスクリプトは`sys.exit(main())`と
    引数無しで呼ぶため、argv=Noneのときにsys.argv[1:]へフォールバックしないと
    `fox-webusb-host-doctor --json`が実際には機能しない
    (pyside6-webusb `__main__.py` のdocstringが指摘しているのと同じ落とし穴)。"""
    fake_report = {"problems": []}
    monkeypatch.setattr(diagnostics, "environment_report", lambda: fake_report)
    monkeypatch.setattr(sys, "argv", ["fox-webusb-host-doctor", "--json"])
    diagnostics.main(argv=None)
    out = capsys.readouterr().out
    assert json.loads(out) == fake_report
    print("test_main_falls_back_to_sys_argv_when_argv_is_none: OK")
