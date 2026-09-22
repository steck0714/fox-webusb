#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
install.py
==========
fox-webusb ネイティブメッセージングホストを、現在のユーザー向けにFirefoxへ
登録する。実行する前に、このディレクトリ(native-host/)で
`pip install -e .`(または `pip install .`、PyPI公開後は
`pip install fox-webusb-host`)を済ませ、`fox_webusb_host`がimportできる
状態にしておくこと。

Firefoxのネイティブメッセージングホストは、次の2つが揃って初めて機能する:
  1. 実際に起動されるランチャー。
  2. そのランチャーの絶対パスと、許可する拡張機能IDを記載したJSONマニフェスト
     ファイルを、OSごとに決まった場所(または、Windowsではレジストリキーが
     指す場所)に置くこと。

🆕 v0.0.0.3: 1.の「ランチャー」の決め方を全面的に見直した。以前
(v0.0.0a1)はランチャー自体にこのリポジトリのnative-host/srcへの絶対パスを
PYTHONPATHとして常に埋め込んでいたが、これは「`pip install -e .`が
`--python`で指定した、まさにそのインタプリタに対して正しく効いているか」を
検証しないままの安全網に過ぎず、実機(Windows + LibreWolf、
`checklog2.md`)で`ModuleNotFoundError`が再発した根本原因(=確認していた
のが常にinstall.py自身を実行しているインタプリタの環境で、`--python`で
指定した別のインタプリタの環境ではなかったこと)を覆い隠していただけ
だった。今回は`--python`で指定されたインタプリタに対して実際に
サブプロセスを起動して`import fox_webusb_host`を検証し
(`_inspect_target_python()`)、`pip install`(または`pip install -e .`)が
そのインタプリタに対して実際に生成した`fox-webusb-host`コンソール
スクリプトをそのままネイティブメッセージングの起動パスとして使う
(`_find_pip_console_script()`)。setuptools/pipが生成するこのスクリプトは
生成時のインタプリタ・site-packagesが常に正しく組み込まれているため、
PYTHONPATHのような追加の配線は原理的に不要になる——「pip installに
pythonの通り道を任せる」という今回望まれた対応そのもの。標準的でない
方法でインストールされた等、このスクリプトが見つからない場合にのみ、
フォールバックとして`<python> -m fox_webusb_host`を実行するだけの
最小限のランチャーを書く(詳細は`_write_launcher()`のdocstring参照)。

姉妹プロジェクトpyside6-webusbが環境診断のために追加した
`pyside6-webusb-doctor`(0.0.5a0)と同じ発想の
`fox-webusb-host-doctor`コマンドが、この登録作業とは独立に、
「pip installが今のインタプリタに対して正しく通っているか」を後から
何度でも再確認できる(`diagnostics.py`参照)。

実行例:
    cd native-host
    pip install -e . --break-system-packages   # または venv内で pip install -e .
    python3 install.py

拡張機能側のIDは manifest.json の browser_specific_settings.gecko.id と
一致している必要がある(既定値 "fox-webusb@local" を変更した場合は
--extension-id で指定すること)。

組み合わせて使う拡張機能(.xpi)のバージョンを記録しておきたい場合は
--xpi-version を指定する(例: --xpi-version 0.0.0.3)。pip経由でXPI自体を
インストールすることはできないため動作そのものには影響しない、
`fox-webusb-host-doctor`や本コマンド自身の出力で確認できるようにする
ための任意の記録用メタデータ。
"""
import argparse
import json
import os
import stat
import subprocess
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
    """ランチャースクリプト(フォールバック時のみ)・Windows用マニフェスト・
    xpiバージョンの記録ファイルの置き場所。ブラウザのプロファイルとは無関係な、
    このホスト専用の永続的な場所を使う。"""
    if sys.platform.startswith("win"):
        base = Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    return base / "fox-webusb"


def _inspect_target_python(python_executable: str) -> dict:
    """指定したPythonインタプリタ上で実際に fox_webusb_host / pyusb が
    importできるかを、そのインタプリタ自身をサブプロセスとして起動して
    確認する。

    install.py自身を実行しているインタプリタ(sys.executable)と`--python`
    で指定されたターゲットが異なる場合、`import fox_webusb_host`をこの
    プロセス内で直接試すだけでは、確認しているのが常にinstall.py自身の
    インタプリタの環境になってしまい、実際に起動に使われるインタプリタの
    環境を確認したことには決してならない——これが実機検証(Windows +
    LibreWolf、`checklog2.md`)で見つかった不具合の根本原因であり、
    v0.0.0.3で修正した(詳細はモジュールdocstring、CHANGELOG.md
    [0.0.0.3]、および`_write_launcher()`のdocstring参照)。

    戻り値は {"fox_webusb_host_version": str|None, "pyusb_ok": bool,
    "error": str (起動自体に失敗した場合のみ)} の辞書。
    """
    code = (
        "import json\n"
        "result = {'fox_webusb_host_version': None, 'pyusb_ok': False}\n"
        "try:\n"
        "    import fox_webusb_host\n"
        "    result['fox_webusb_host_version'] = fox_webusb_host.__version__\n"
        "except Exception:\n"
        "    pass\n"
        "try:\n"
        "    import usb.core  # noqa: F401\n"
        "    result['pyusb_ok'] = True\n"
        "except Exception:\n"
        "    pass\n"
        "print(json.dumps(result))\n"
    )
    try:
        proc = subprocess.run(
            [python_executable, "-c", code],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"fox_webusb_host_version": None, "pyusb_ok": False, "error": f"{python_executable} を起動できませんでした: {e}"}
    if not proc.stdout.strip():
        return {
            "fox_webusb_host_version": None, "pyusb_ok": False,
            "error": proc.stderr.strip() or f"終了コード {proc.returncode} (標準出力なし)",
        }
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"fox_webusb_host_version": None, "pyusb_ok": False, "error": f"診断結果の解析に失敗しました: {e}"}


def _console_script_name() -> str:
    return "fox-webusb-host.exe" if sys.platform.startswith("win") else "fox-webusb-host"


def _find_pip_console_script(python_executable: str):
    """`python_executable` に対して実際に`pip install`(または
    `pip install -e .`)が生成したはずの `fox-webusb-host` コンソール
    スクリプトを探す。見つかればそれを返す(`pathlib.Path`)、見つからなければ
    `None`を返す。

    見つかった場合、ランチャーを自前で書く必要が無くなり、PYTHONPATHを
    手動で埋め込む必要も無くなる——これが今回(v0.0.0.3)の
    「pip installでpythonの通り道を通す」対応の中核(`_write_launcher()`
    のdocstring参照)。

    `importlib.metadata`のentry_points()は「pipが何を生成すべきだったか」の
    宣言を返すだけで、実際にどこへ書き出したかは教えてくれないため、
    setuptools/pipが実際に使う2つの標準的な設置先(通常のscheme、および
    `--user`インストール用のscheme)を、ターゲットのインタプリタ自身に
    サブプロセス越しに`sysconfig`で問い合わせて割り出す。
    """
    code = (
        "import os, sysconfig\n"
        "dirs = []\n"
        "try:\n"
        "    dirs.append(sysconfig.get_path('scripts'))\n"
        "except Exception:\n"
        "    pass\n"
        "try:\n"
        "    dirs.append(sysconfig.get_path('scripts', ('nt_user' if os.name == 'nt' else 'posix_user')))\n"
        "except Exception:\n"
        "    pass\n"
        "print(os.pathsep.join(d for d in dirs if d))\n"
    )
    try:
        proc = subprocess.run([python_executable, "-c", code], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    name = _console_script_name()
    for d in proc.stdout.strip().split(os.pathsep):
        if not d:
            continue
        candidate = Path(d) / name
        if candidate.is_file() and (sys.platform.startswith("win") or os.access(candidate, os.X_OK)):
            return candidate.resolve()
    return None


def _write_launcher(python_executable: str) -> Path:
    """🆕 v0.0.0.3: ランチャーの決め方を全面的に見直した。

    旧バージョン(v0.0.0a1)は、ランチャー自体にこのリポジトリの
    native-host/src への絶対パスをPYTHONPATHとして常に埋め込んでいた——
    `pip install -e .` が本当に効いているかどうかを確認する手段が無く、
    「効いていれば無害、効いていなければ安全網」という前提で書かれていた。
    しかし実際にはその確認(旧`main()`のimportチェック)がinstall.py自身を
    実行しているインタプリタに対してしか行われておらず、`--python`で
    別のインタプリタを指定した場合に、そのインタプリタでの実際の
    インストール状態を何も検証していなかった。これが実機
    (Windows + LibreWolf、`checklog2.md`)で`ModuleNotFoundError`が
    再発した根本原因であり、PYTHONPATHの埋め込みはそれを覆い隠す
    対症療法に過ぎなかった。

    v0.0.0.3では、`main()`が`--python`で指定された、まさにそのインタプリタに
    対してサブプロセスで直接importを確認する(`_inspect_target_python()`)
    ように直した上で、ランチャーそのものを自前で書くのを可能な限りやめ、
    `pip install`(または`pip install -e .`)がそのインタプリタに対して
    実際に生成した`fox-webusb-host`コンソールスクリプトをそのまま
    ネイティブメッセージングの起動パスとして使う(`_find_pip_console_script()`)。
    setuptools/pipが生成するこのスクリプトは、生成時のインタプリタと
    site-packagesが常に正しく組み込まれているため、PYTHONPATHのような
    追加の配線は原理的に不要になる——「pipにpythonの通り道を任せる」という、
    今回望まれた対応そのもの。

    コンソールスクリプトが見つからない(setuptools/pip以外の方法で
    インストールされた等、標準的でない構成の)場合にのみ、フォールバックとして
    `<python> -m fox_webusb_host` を実行するだけの最小限のランチャーを書く。
    `main()`が事前にサブプロセスで`import fox_webusb_host`の成功を確認済み
    なので、このフォールバックでもPYTHONPATHの埋め込みは不要と分かっている
    (見つからなかったのはコンソールスクリプトの設置先の話であって、
    パッケージ自体がimportできない訳ではないため)。
    """
    found = _find_pip_console_script(python_executable)
    if found is not None:
        return found

    support_dir = _support_dir()
    support_dir.mkdir(parents=True, exist_ok=True)

    if sys.platform.startswith("win"):
        launcher = support_dir / "fox-webusb-host.bat"
        launcher.write_text(
            f'@echo off\r\n'
            f'"{python_executable}" -m fox_webusb_host %*\r\n',
            encoding="utf-8",
        )
    else:
        launcher = support_dir / "fox-webusb-host.sh"
        launcher.write_text(
            f'#!/bin/sh\n'
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


def _write_xpi_version_record(host_version: str, xpi_version: str) -> Path:
    """`--xpi-version` が指定された場合に、組み合わせを記録しておくための
    小さなJSONファイル。Firefoxが実際に読むネイティブメッセージング
    マニフェスト自体は一切変更しない(未知のフィールドに対するFirefox側の
    スキーマ検証の挙動を確認できていない状態で、既に許諾済みの本番連携を
    壊すリスクを取らないため)——完全に別ファイルとして、記録・
    `fox-webusb-host-doctor`からの参照用にのみ使う。"""
    support_dir = _support_dir()
    support_dir.mkdir(parents=True, exist_ok=True)
    record_path = support_dir / "paired-xpi-version.json"
    record_path.write_text(
        json.dumps({"host_version": host_version, "xpi_version": xpi_version}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return record_path


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
    parser.add_argument(
        "--xpi-version", default=None,
        help="組み合わせて使う fox-webusb 拡張機能(.xpi)のバージョンを記録用に指定する"
             "(例: --xpi-version 0.0.0.3)。pip経由でXPI自体をインストールすることはできないため"
             "動作には影響しない、fox-webusb-host-doctorや本コマンドの出力で確認できるようにする"
             "ための任意の記録用メタデータ。",
    )
    args = parser.parse_args()

    info = _inspect_target_python(args.python)
    if not info.get("fox_webusb_host_version"):
        print(
            f"エラー: 指定したPython ({args.python}) から fox_webusb_host がimportできません。\n"
            "先に、そのインタプリタに対して(このディレクトリ native-host/ で)\n"
            f"  {args.python} -m pip install -e .\n"
            "(または、PyPI公開後の通常のインストールなら)\n"
            f"  {args.python} -m pip install fox-webusb-host\n"
            "を実行してから再度お試しください(仮想環境を使っている場合は、その中の\n"
            "pythonを --python で明示的に指定してください)。",
            file=sys.stderr,
        )
        if info.get("error"):
            print(f"(詳細: {info['error']})", file=sys.stderr)
        sys.exit(1)

    if not info.get("pyusb_ok"):
        print(
            f"警告: 指定したPython ({args.python}) から pyusb がimportできません。fox_webusb_hostは\n"
            f"起動できますが、実際のUSB操作は全て失敗します。`{args.python} -m pip install pyusb` を\n"
            "実行してください。",
            file=sys.stderr,
        )

    launcher_path = _write_launcher(args.python)
    used_pip_console_script = launcher_path.name in ("fox-webusb-host", "fox-webusb-host.exe")
    manifest_path = _write_manifest(launcher_path, args.extension_id)

    if sys.platform.startswith("win"):
        try:
            _register_windows_registry(manifest_path)
        except Exception as e:
            print(f"エラー: Windowsレジストリへの登録に失敗しました: {e}", file=sys.stderr)
            sys.exit(1)

    xpi_record_path = None
    if args.xpi_version:
        xpi_record_path = _write_xpi_version_record(info["fox_webusb_host_version"], args.xpi_version)

    print("fox-webusb ネイティブメッセージングホストを登録しました。")
    launcher_kind = "(pip installが生成したコンソールスクリプトをそのまま使用)" if used_pip_console_script \
        else "(フォールバック: コンソールスクリプトが見つからなかったため自前生成)"
    print(f"  ランチャー       : {launcher_path} {launcher_kind}")
    print(f"  マニフェスト     : {manifest_path}")
    print(f"  許可する拡張機能ID: {args.extension_id}")
    print(f"  ホストのバージョン: {info['fox_webusb_host_version']}")
    if xpi_record_path is not None:
        print(f"  組み合わせるxpiバージョン: {args.xpi_version} ({xpi_record_path} に記録)")
    print(f"  設定ファイル     : {sysconfig.get_path('data')} 配下ではなく "
          f"{Path.home()} 配下のOS標準の設定ディレクトリに保存されます(settings_store.py参照)")
    print()
    print("Firefoxで about:debugging#/runtime/this-firefox を開き、「一時的なアドオンを読み込む」から")
    print("extension/manifest.json を選んで拡張機能を読み込んでください。")
    print()
    print("インストール状態や環境を診断したい場合は `fox-webusb-host-doctor` を実行してください。")


if __name__ == "__main__":
    main()
