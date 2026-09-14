#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
setup_env.py
============
fox-webusb ネイティブメッセージングホストの実行環境を、1コマンドで
準備するためのスクリプト。

## これまでの手動セットアップで何が問題だったか

README「インストール」が案内する手順は、次の2ステップに分かれていた:

    cd native-host
    pip install -e .          # (A) どこかのpythonにパッケージをインストールする
    python3 install.py        # (B) --python で「ランチャーが起動するpython」を指定する

(A)と(B)は別々のコマンド実行であり、両方が「同じpythonインタプリタ」を
指している保証はどこにもなかった。実際、checklog2.md の実機検証
(Windows + LibreWolf)では、

  - ある仮想環境(.venv)に対して pip install -e . をした「つもり」で、
  - install.py 側にはそれとは食い違うpythonパスが渡ってしまい、

ランチャーが `python -m fox_webusb_host` を実行した瞬間に

    ModuleNotFoundError: No module named 'fox_webusb_host'

で即座に落ち、Firefox側には単に

    NetworkError: fox-webusb native host disconnected: disconnected

としか伝わらない(なぜ切断されたのかは、ネイティブホストを手動起動して
初めて分かった)、という原因究明に時間のかかる不具合として現れた。

このスクリプトは、(A)(B)を同一のpythonインタプリタに対して自動的に
順番に実行することで、この種の食い違いをそもそも起こり得なくする。

## 仮想環境の置き場所も変更している

`cd native-host && pip install -e .` は、リポジトリ自身のフォルダの中に
(あるいはユーザーが手動で用意した任意の場所に)仮想環境を作る想定だった。
しかしこのリポジトリは、ダウンロードフォルダ等の一時的な場所に展開されて
いることが多い(checklog2.md の検証環境でのパスも
`Downloads\v0.0.0a\fox-webusb\...` だった)。後でそのフォルダを削除・
移動すると、ネイティブメッセージングホストのランチャーが指す仮想環境
ごと消えてしまう。

このスクリプトは、install.py がランチャー/マニフェストの保存先として
既に使っている「ブラウザのプロファイルとは無関係な、このホスト専用の
永続的な場所」(_support_dir()。Windows: %APPDATA%\fox-webusb 等)の中に
仮想環境を作る。加えて、`pip install -e .`(editable)ではなく
`pip install .`(通常インストール)を使う。editableインストールは
ソースディレクトリの場所そのものへの参照を残すため、結局は元の
ダウンロードフォルダに依存し続けてしまうが、通常インストールなら
仮想環境の中にファイルがコピーされ、以後は元のダウンロードフォルダを
削除してもネイティブホストは動き続ける。

## 実行方法

    python3 setup_env.py

Windows:

    py setup_env.py

いずれのOSでも同じこのスクリプト1つを使う(OSで処理を分けている箇所は
install.py側に既にあるため、ここでは意識する必要がない)。

なお、これは「ユーザーがPythonを別途インストールする必要をなくす」
という目標(README「今後やりたいこと」)そのものの達成ではなく、その前段
としての改善である――このスクリプト自身を実行するには、依然として
Python 3.9+が必要。standalone executable化はdevelopmentブランチでの
別課題として残っている。

## オプション

    --extension-id ID   install.py にそのまま渡す(既定: fox-webusb@local)
    --recreate          既存の仮想環境を削除して作り直す
    --no-upgrade        fox-webusb-host のインストール時に --upgrade を付けない
"""
import argparse
import shutil
import subprocess
import sys
import venv
from pathlib import Path

from install import DEFAULT_EXTENSION_ID, _support_dir  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
MIN_PYTHON = (3, 9)


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform.startswith("win"):
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python3"


def _run(cmd) -> None:
    """コマンドを表示してから実行し、失敗したら分かりやすく終了する。
    「何が実行されたか」が常に見えるようにしておくことは、ネイティブ
    ホストの登録のようにブラウザ側からは中身が見えない処理にとって
    特に重要だと考えている。"""
    print(f"$ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=str(SCRIPT_DIR))
    if result.returncode != 0:
        print(f"エラー: 上記コマンドが終了コード {result.returncode} で失敗しました。", file=sys.stderr)
        sys.exit(result.returncode)


def _check_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        print(
            f"エラー: このスクリプトの実行にはPython {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 以上が必要です"
            f"(現在起動しているのは {sys.version.split()[0]})。",
            file=sys.stderr,
        )
        sys.exit(1)


def _create_venv(venv_dir: Path, recreate: bool) -> Path:
    python_path = _venv_python(venv_dir)

    if recreate and venv_dir.exists():
        print(f"既存の仮想環境を削除しています: {venv_dir}")
        shutil.rmtree(venv_dir)

    if python_path.exists():
        print(f"既存の仮想環境を再利用します: {venv_dir}")
        return python_path

    print(f"仮想環境を作成しています: {venv_dir}")
    try:
        venv.EnvBuilder(with_pip=True, clear=False).create(str(venv_dir))
    except Exception as e:
        print(f"エラー: 仮想環境の作成に失敗しました: {e}", file=sys.stderr)
        if sys.platform.startswith("linux"):
            print(
                "Debian/Ubuntu系のディストリビューションでは、先に\n"
                "  sudo apt install python3-venv\n"
                "が必要な場合があります。",
                file=sys.stderr,
            )
        sys.exit(1)

    if not python_path.exists():
        print(
            f"エラー: 仮想環境は作成されましたが、想定した場所にpythonが見つかりません: {python_path}",
            file=sys.stderr,
        )
        sys.exit(1)
    return python_path


def _install_package(venv_python: Path, upgrade: bool) -> None:
    # pip自体の更新(失敗しても致命的にはしない。古いpipのままでも大抵は
    # 動くため、警告だけ出して本体のインストールへ進む)。
    pip_upgrade = subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"],
        cwd=str(SCRIPT_DIR),
    )
    if pip_upgrade.returncode != 0:
        print("警告: pip自体の更新に失敗しました。このまま続行します。", file=sys.stderr)

    print()
    print("fox-webusb-host をインストールしています(依存関係の pyusb を含む)...")
    cmd = [str(venv_python), "-m", "pip", "install"]
    if upgrade:
        cmd.append("--upgrade")
    cmd.append(str(SCRIPT_DIR))  # このディレクトリ(pyproject.tomlの場所)を通常インストール
    _run(cmd)


def _check_libusb_backend(venv_python: Path) -> None:
    """pyusbは正常にimportできても、実行時に読み込む libusb 本体(共有
    ライブラリ)が無いと、実際のデバイス列挙(usb.core.find())は
    usb.core.NoBackendError で失敗する。ここではUSBデバイスを一切操作
    せず、バックエンドが見つかるかどうかだけを確認する(致命的エラーには
    せず、警告のみ――デバイスを後で用意する場合もあるため)。"""
    print()
    print("libusbバックエンドの有無を確認しています...")
    check = subprocess.run(
        [str(venv_python), "-c", "import usb.core; usb.core.find(); print('OK')"],
        cwd=str(SCRIPT_DIR),
        capture_output=True,
        text=True,
    )
    if check.returncode == 0 and "OK" in check.stdout:
        print("  libusbバックエンドが見つかりました。")
        return

    print("  警告: libusbバックエンドが見つかりませんでした。", file=sys.stderr)
    print("  fox-webusb-hostは起動しますが、実際のUSB操作(デバイス列挙等)は失敗します。", file=sys.stderr)
    if sys.platform.startswith("win"):
        print(
            "  Windows: libusb-1.0.dll をPATHの通った場所に配置してください"
            "(https://libusb.info/ の配布物、またはデバイス個別にZadig等でのドライバ差し替えが必要な場合があります)。",
            file=sys.stderr,
        )
    elif sys.platform == "darwin":
        print("  macOS: 'brew install libusb' を実行してください。", file=sys.stderr)
    else:
        print(
            "  Linux: 'sudo apt install libusb-1.0-0'"
            "(ディストリビューションに応じて読み替えてください)。",
            file=sys.stderr,
        )


def _run_install_script(venv_python: Path, extension_id: str) -> None:
    install_py = SCRIPT_DIR / "install.py"
    print()
    print("ネイティブメッセージングホストをFirefoxに登録しています...")
    _run([str(venv_python), str(install_py), "--python", str(venv_python), "--extension-id", extension_id])


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "fox-webusb ネイティブメッセージングホストの実行環境"
            "(仮想環境の作成・fox-webusb-hostのインストール・Firefoxへの登録)"
            "を1コマンドでまとめて準備する。"
        )
    )
    parser.add_argument(
        "--extension-id", default=DEFAULT_EXTENSION_ID,
        help=f"install.py にそのまま渡す拡張機能ID (既定: {DEFAULT_EXTENSION_ID})",
    )
    parser.add_argument(
        "--recreate", action="store_true",
        help="既存の仮想環境を削除してから作り直す(依存関係が壊れた場合等に)",
    )
    parser.add_argument(
        "--no-upgrade", action="store_true",
        help="fox-webusb-host のインストール時に --upgrade を付けない(既定では毎回最新化する)",
    )
    args = parser.parse_args()

    _check_python_version()

    venv_dir = _support_dir() / "venv"
    venv_python = _create_venv(venv_dir, recreate=args.recreate)
    _install_package(venv_python, upgrade=not args.no_upgrade)
    _check_libusb_backend(venv_python)
    _run_install_script(venv_python, args.extension_id)

    print()
    print("=" * 70)
    print("環境の準備が完了しました。")
    print(f"  仮想環境: {venv_dir}")
    print()
    print("この仮想環境は、install.pyがランチャー/マニフェストを保存するのと")
    print("同じ永続的な場所に作られているため、このリポジトリ(今このスクリプト")
    print("が置かれているダウンロード先フォルダ)を後で削除・移動しても影響を")
    print("受けません(editable installではなく通常インストールのため)。")
    print()
    print("全て取り除きたい場合は、native-host/uninstall.py を実行したうえで、")
    print(f"上記の仮想環境フォルダ({venv_dir})も手動で削除してください")
    print("(uninstall.pyはこの仮想環境フォルダを自動では削除しません)。")


if __name__ == "__main__":
    main()
