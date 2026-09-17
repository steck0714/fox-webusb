#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
install.py
==========
fox-webusb ネイティブメッセージングホストを、現在のユーザー向けにFirefoxへ
登録する。実行する前に、このディレクトリ(native-host/)で
`pip install -e .`(または `pip install .`)を済ませ、`fox_webusb_host`が
importできる状態にしておくこと。

Firefoxのネイティブメッセージングホストは、次の2つが揃って初めて機能する:
  1. 実際に起動されるランチャー(このスクリプトが生成する、現在のPython
     インタプリタで `python -m fox_webusb_host` を実行するだけの小さな
     スクリプト。Windowsでは.bat、それ以外ではシェルスクリプト)。
  2. そのランチャーの絶対パスと、許可する拡張機能IDを記載したJSONマニフェスト
     ファイルを、OSごとに決まった場所(または、Windowsではレジストリキーが
     指す場所)に置くこと。

実行例:
    cd native-host
    pip install -e . --break-system-packages   # または venv内で pip install -e .
    python3 install.py

拡張機能側のIDは manifest.json の browser_specific_settings.gecko.id と
一致している必要がある(既定値 "fox-webusb@local" を変更した場合は
--extension-id で指定すること)。
"""
import argparse
import json
import stat
import sys
import sysconfig
from pathlib import Path

HOST_NAME = "org.fox_webusb.host"
DEFAULT_EXTENSION_ID = "fox-webusb@local"


def _linux_manifest_dir() -> Path:
    return Path.home() / ".mozilla" / "native-messaging-hosts"


def _macos_manifest_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "Mozilla" / "NativeMessagingHosts"


def _support_dir() -> Path:
    """ランチャースクリプトやWindows用マニフェストの置き場所。ブラウザの
    プロファイルとは無関係な、このホスト専用の永続的な場所を使う。"""
    if sys.platform.startswith("win"):
        base = Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    return base / "fox-webusb"


def _write_launcher(python_executable: str) -> Path:
    """🛡️ v0.0.0a1(実機検証フィードバックに基づく修正): ランチャー自体に
    PYTHONPATH(このリポジトリの native-host/src の絶対パス)を明示的に
    埋め込むようにした。
    以前はランチャーが単に `python -m fox_webusb_host` を実行するだけで、
    `fox_webusb_host` がその python から実際にimportできるかどうかは
    「事前に `pip install -e .` を済ませてあること」に完全に依存していた。
    実際にWindows + LibreWolf環境で検証していただいた際、この前提が
    崩れる形(pip installを飛ばした、あるいは--pythonで指定したものとは
    別のインタプリタでpip installしてしまった等)で
    `ModuleNotFoundError: No module named 'fox_webusb_host'` が発生し、
    ユーザー自身がランチャーへ手動で
    `set "PYTHONPATH=...\\native-host\\src"` を書き足すことで解決する
    しかなかった(`checklog2.md` 参照)。
    この修正は、その手動での対処を自動化するもの——`pip install -e .`が
    正しく効いている場合には無害(既にimportできる場所へPYTHONPATHで
    もう1つ同じ場所を追加で通すだけ)であり、効いていない場合の
    セーフティネットとして働く。あくまでセーフティネットなので、
    `pip install -e .`を実行して依存関係(pyusb等)も含めて正しく
    インストールしておくことが引き続き推奨手順である
    (このスクリプト冒頭のdocstring参照)。"""
    support_dir = _support_dir()
    support_dir.mkdir(parents=True, exist_ok=True)
    src_dir = (Path(__file__).resolve().parent / "src")

    if sys.platform.startswith("win"):
        launcher = support_dir / "fox-webusb-host.bat"
        launcher.write_text(
            f'@echo off\r\n'
            f'set "PYTHONPATH={src_dir};%PYTHONPATH%"\r\n'
            f'"{python_executable}" -m fox_webusb_host %*\r\n',
            encoding="utf-8",
        )
    else:
        launcher = support_dir / "fox-webusb-host.sh"
        launcher.write_text(
            f'#!/bin/sh\n'
            f'export PYTHONPATH="{src_dir}:$PYTHONPATH"\n'
            f'exec "{python_executable}" -m fox_webusb_host "$@"\n',
            encoding="utf-8",
        )
        mode = launcher.stat().st_mode
        launcher.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return launcher.resolve()


def _write_manifest(launcher_path: Path, extension_id: str) -> Path:
    manifest = {
        "name": HOST_NAME,
        "description": "fox-webusb native messaging host: bridges the fox-webusb Firefox "
                        "extension's navigator.usb polyfill to real USB hardware via pyusb/libusb.",
        "path": str(launcher_path),
        "type": "stdio",
        "allowed_extensions": [extension_id],
    }

    if sys.platform.startswith("win"):
        manifest_dir = _support_dir()
    elif sys.platform == "darwin":
        manifest_dir = _macos_manifest_dir()
    else:
        manifest_dir = _linux_manifest_dir()

    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{HOST_NAME}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest_path


def _register_windows_registry(manifest_path: Path):
    import winreg  # Windows専用モジュール。他OSではimportしない。
    key_path = f"Software\\Mozilla\\NativeMessagingHosts\\{HOST_NAME}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValue(key, "", winreg.REG_SZ, str(manifest_path))


def main():
    parser = argparse.ArgumentParser(description="Register the fox-webusb native messaging host with Firefox.")
    parser.add_argument(
        "--extension-id", default=DEFAULT_EXTENSION_ID,
        help=f"extension/manifest.json の browser_specific_settings.gecko.id と一致させること (既定: {DEFAULT_EXTENSION_ID})",
    )
    parser.add_argument(
        "--python", default=sys.executable,
        help="ランチャーが起動するPythonインタプリタ (既定: このinstall.pyを実行しているものと同じ)",
    )
    args = parser.parse_args()

    try:
        import fox_webusb_host  # noqa: F401
    except ImportError:
        print(
            "エラー: fox_webusb_host がimportできません。先に、このディレクトリ(native-host/)で\n"
            "  pip install -e .\n"
            "を実行してから再度お試しください(仮想環境を使っている場合は、その中で実行し、\n"
            "--python でその仮想環境のpythonを明示的に指定してください)。",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        import usb.core  # noqa: F401
    except ImportError:
        print(
            "警告: pyusb がimportできません。fox_webusb_hostは起動できますが、実際のUSB操作は\n"
            "全て失敗します。`pip install pyusb` を実行してください。",
            file=sys.stderr,
        )

    launcher_path = _write_launcher(args.python)
    manifest_path = _write_manifest(launcher_path, args.extension_id)

    if sys.platform.startswith("win"):
        try:
            _register_windows_registry(manifest_path)
        except Exception as e:
            print(f"エラー: Windowsレジストリへの登録に失敗しました: {e}", file=sys.stderr)
            sys.exit(1)

    print("fox-webusb ネイティブメッセージングホストを登録しました。")
    print(f"  ランチャー       : {launcher_path}")
    print(f"  マニフェスト     : {manifest_path}")
    print(f"  許可する拡張機能ID: {args.extension_id}")
    print(f"  設定ファイル     : {sysconfig.get_path('data')} 配下ではなく "
          f"{Path.home()} 配下のOS標準の設定ディレクトリに保存されます(settings_store.py参照)")
    print()
    print("Firefoxで about:debugging#/runtime/this-firefox を開き、「一時的なアドオンを読み込む」から")
    print("extension/manifest.json を選んで拡張機能を読み込んでください。")


if __name__ == "__main__":
    main()
