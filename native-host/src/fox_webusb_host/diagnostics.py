# -*- coding: utf-8 -*-
"""
diagnostics.py
==============
🆕 v0.0.0.3: fox-webusb-host 版の環境診断ユーティリティ。

姉妹プロジェクト pyside6-webusb の `diagnostics.py`(v0.0.5a0で追加、
`pyside6-webusb-doctor` として公開)と同じ発想——「navigator.usbが動かない」
という報告の多くは、このパッケージ自身のロジックのバグではなく周辺環境に
起因する——を、fox-webusbのネイティブメッセージングホストという文脈に
合わせて移植したもの。pyside6-webusb版が主にPySide6/QtWebEngine自体の
有無を診断するのに対し、こちらは以下を診断する:

  - pyusb / OS側libusbバックエンドの有無(pyside6-webusb版と共通の切り分け方)
  - Tkinter(デバイス選択ダイアログ用)・cryptography(任意のアテステーション
    機能用)・Rustアクセラレーションの有無
  - **`pip install`(または`pip install -e .`)が実際にこのinterpreterへ
    `fox-webusb-host`コンソールスクリプトを正しく生成しているか**——今回
    (v0.0.0.3)のinstall.py側の修正([[CHANGELOG.md `[0.0.0.3]`]]参照)が
    前提にしている「pipにpythonの通り道を任せる」という発想を、診断ツール
    自身の側からも独立に再確認できるようにするための項目
  - このOSにネイティブメッセージングマニフェストが登録済みか、登録済みの
    場合はそこに記録された起動パスが今も実在するか(install.pyを再実行せず
    にいきなり`fox-webusb-host-doctor`を叩いても、何が足りないか分かるように)

- `environment_report()`: 診断結果をJSON化可能なプリミティブ型のみの辞書として
  返す。
- `format_environment_report()`: 上記を人間が読むためのテキストに整形する。
- `python -m fox_webusb_host.diagnostics`、または pip install 後は
  `fox-webusb-host-doctor` コマンドから直接実行できる。

⚠️ `fox_webusb_host.__main__`(ネイティブメッセージングホスト本体、Firefoxが
標準入出力経由で直接起動する既存の契約)とは意図的に完全に分離した別モジュール・
別コンソールスクリプトにしている。本体側の起動契約(引数無しでスレッド配線を
開始しstdinを読み続ける)には一切手を入れていない。
"""
import json
import os
import platform
import shutil
import sys
import sysconfig

from . import __version__

HOST_MANIFEST_NAME = "org.fox_webusb.host"


def _pyusb_backend_info():
    """(pyusb_version, backend_name_or_None, problem_or_None) を返す。

    pyside6-webusb `diagnostics.py` の `_pyusb_backend_info()` と同じ切り分け方
    (「importできる」ことと「実際にUSBデバイスへアクセスできる」ことは別問題)
    をそのまま踏襲している——両プロジェクトとも同じpyusbを同じように使うため、
    診断すべき失敗モードも同一。
    """
    pyusb_version = None
    try:
        import usb
        pyusb_version = getattr(usb, "__version__", None)
    except Exception as e:
        return None, None, f"pyusb自体がimportできません('pip install pyusb'を確認してください): {e}"

    backend_name = None
    try:
        import usb.backend.libusb1 as _libusb1
        if _libusb1.get_backend() is not None:
            backend_name = "libusb1"
    except Exception:
        pass
    if backend_name is None:
        try:
            import usb.backend.libusb0 as _libusb0
            if _libusb0.get_backend() is not None:
                backend_name = "libusb0"
        except Exception:
            pass

    problem = None
    if backend_name is None:
        problem = (
            "OS側のlibusb共有ライブラリが見つかりません(pyusb自体は正しくimportできています)。"
            "Linux: 'libusb-1.0-0' パッケージ / macOS: 'brew install libusb' / "
            "Windows: libusbのDLLを配置、のいずれかが必要です。"
        )
    return pyusb_version, backend_name, problem


def _rust_accel_status():
    """(rust_accelerated: bool, rust_accel_version_or_None) を返す。未ビルドでも
    本パッケージは標準ライブラリのbase64実装へ完全にフォールバックする
    (README「Rustアクセラレーション(任意)」参照)ため、problemsには含めない。"""
    try:
        import fox_webusb_accel
        return True, getattr(fox_webusb_accel, "__version__", None)
    except ImportError:
        return False, None


def _tkinter_status():
    """(available, note_or_None) を返す。Tkinterが無くてもホスト自体は動作し、
    requestDevice()呼び出し時にのみ分かりやすいエラーで失敗するだけ
    (__main__.py の _ChooserGui 参照)なので problems には含めない。"""
    try:
        import tkinter  # noqa: F401
        return True, None
    except Exception as e:
        return False, (
            f"Tkinterが利用できません({e})。デバイス選択ダイアログ(チューザー)は"
            "無効化されますが、ホスト自体は動作を続けます"
            "(requestDevice()呼び出し時のみ分かりやすいエラーになります)。"
        )


def _attestation_status():
    """(available, note_or_None) を返す。ローカルアテステーション機能
    (attestation.py)専用の任意依存で、基本機能には一切影響しない
    (pyproject.tomlの[project.optional-dependencies].attestation参照)。"""
    try:
        import cryptography  # noqa: F401
        return True, None
    except ImportError:
        return False, (
            "cryptographyがインストールされていません(任意機能。"
            "'pip install fox-webusb-host[attestation]' で有効化できます)。"
        )


def _console_script_name() -> str:
    return "fox-webusb-host.exe" if os.name == "nt" else "fox-webusb-host"


def _installed_console_script_path():
    """`fox-webusb-host` コンソールスクリプトが、今まさにこの診断を実行している
    インタプリタから見て「正しい」場所——このインタプリタのsysconfig scripts dir、
    または`--user`インストール用のscripts dir——に実在するかどうかを調べる。

    ここがまさに「pip installがpythonの通り道を正しく通しているか」を診断ツール
    自身が独立に確認する箇所であり、install.py側の`_find_pip_console_script()`
    (native-host/install.py)と同じ考え方を、インストール作業とは無関係に
    後から単体で再確認できるようにするためのもの。見つかった場合はそのパスの
    文字列を、見つからない場合はNoneを返す。
    """
    name = _console_script_name()
    candidates = []
    try:
        candidates.append(sysconfig.get_path("scripts"))
    except Exception:
        pass
    try:
        candidates.append(sysconfig.get_path("scripts", "nt_user" if os.name == "nt" else "posix_user"))
    except Exception:
        pass
    for d in candidates:
        if not d:
            continue
        p = os.path.join(d, name)
        if os.path.isfile(p) and (os.name == "nt" or os.access(p, os.X_OK)):
            return p
    # 標準的な2つのscheme以外の非標準な設置先に対する最後の保険(現在のPATH上に
    # あるものを探す。--user系のディレクトリがPATHに無い場合はこれでも
    # 見つからないことがあるが、その場合でも上記2つのscheme確認が本筋)。
    return shutil.which("fox-webusb-host")


def _default_native_manifest_path() -> str:
    """install.pyが実際にマニフェストを書き出す場所を、install.py自体を
    importせずここでも独立に計算する(このモジュール単体で診断できるように、
    意図的にパスの計算方法を複製している——install.pyはnative-host/直下の
    パッケージ外スクリプトであり、pip installでは配布されないため、常に
    importできるとは限らない)。"""
    home = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        return os.path.join(home, "AppData", "Roaming", "fox-webusb", f"{HOST_MANIFEST_NAME}.json")
    if sys.platform == "darwin":
        return os.path.join(
            home, "Library", "Application Support", "Mozilla", "NativeMessagingHosts",
            f"{HOST_MANIFEST_NAME}.json",
        )
    return os.path.join(home, ".mozilla", "native-messaging-hosts", f"{HOST_MANIFEST_NAME}.json")


def _native_manifest_status(manifest_path=None):
    """(registered, launcher_path_or_None, launcher_exists_or_None, manifest_path) を返す。
    `manifest_path`はテスト用の差し替え口(settings_store.SettingsStoreの
    `path=`引数と同じパターン)——省略時は`_default_native_manifest_path()`を使う。"""
    if manifest_path is None:
        manifest_path = _default_native_manifest_path()

    if not os.path.isfile(manifest_path):
        return False, None, None, manifest_path

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        launcher_path = data.get("path")
    except Exception:
        return True, None, None, manifest_path

    launcher_exists = bool(launcher_path) and os.path.isfile(launcher_path)
    return True, launcher_path, launcher_exists, manifest_path


def environment_report() -> dict:
    """現在の実行環境の診断結果を辞書として返す。JSON化可能なプリミティブ型
    (str/bool/None)のみで構成する。

    "problems" は今すぐ対処が要る項目のみ(libusbバックエンドが無い、
    コンソールスクリプトが見つからない、登録済みマニフェストの起動パスが
    消えている、等)。Rustアクセラレーション未ビルド・Tkinter/cryptography
    未インストールはproblemsに含めない——いずれも正常にフォールバックする
    任意機能であるため(pyside6-webusb版がRustアクセラレーションを
    problemsに含めていないのと同じ扱い)。
    """
    pyusb_version, pyusb_backend, pyusb_problem = _pyusb_backend_info()
    rust_accelerated, rust_accel_version = _rust_accel_status()
    tkinter_available, tkinter_note = _tkinter_status()
    attestation_available, attestation_note = _attestation_status()
    console_script_path = _installed_console_script_path()
    manifest_registered, manifest_launcher_path, manifest_launcher_exists, manifest_path = (
        _native_manifest_status()
    )

    problems = []
    if pyusb_problem is not None:
        problems.append(pyusb_problem)
    if console_script_path is None:
        problems.append(
            "`fox-webusb-host` コンソールスクリプトが見つかりません。"
            "このPythonインタプリタに対して 'pip install -e .'(native-host/ディレクトリで、"
            "またはPyPI公開後は 'pip install fox-webusb-host')が正しく完了しているか"
            "確認してください。"
        )
    if manifest_registered and manifest_launcher_exists is False:
        problems.append(
            f"ネイティブメッセージングマニフェスト({manifest_path})は登録済みですが、"
            f"そこに記録された起動パス({manifest_launcher_path})が見つかりません。"
            "'python3 install.py' を再実行してください。"
        )

    return {
        "fox_webusb_host_version": __version__,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "pyusb_version": pyusb_version,
        "pyusb_backend": pyusb_backend,
        "rust_accelerated": rust_accelerated,
        "rust_accel_version": rust_accel_version,
        "tkinter_available": tkinter_available,
        "tkinter_note": tkinter_note,
        "attestation_available": attestation_available,
        "attestation_note": attestation_note,
        "console_script_path": console_script_path,
        "native_manifest_registered": manifest_registered,
        "native_manifest_path": manifest_path,
        "native_manifest_launcher_path": manifest_launcher_path,
        "native_manifest_launcher_exists": manifest_launcher_exists,
        "problems": problems,
    }


def format_environment_report(report: dict = None) -> str:
    """environment_report()の結果を、人間が読むためのテキストレポートに整形する。
    reportを省略した場合はその場でenvironment_report()を呼ぶ。"""
    if report is None:
        report = environment_report()

    pyusb_line = f"pyusb: {report['pyusb_version'] or '見つかりません'} (backend: {report['pyusb_backend'] or '見つかりません'})"

    if report["rust_accelerated"]:
        rust_line = "Rust acceleration: 有効"
        if report["rust_accel_version"]:
            rust_line += f" ({report['rust_accel_version']})"
    else:
        rust_line = "Rust acceleration: 無効(標準のPython実装にフォールバック中。動作には支障ありません)"

    tkinter_line = (
        "デバイス選択ダイアログ(Tkinter): 利用可能" if report["tkinter_available"]
        else "デバイス選択ダイアログ(Tkinter): 利用不可(requestDevice()はエラーになりますが、他は動作します)"
    )
    attestation_line = (
        "ローカルアテステーション(cryptography): 利用可能" if report["attestation_available"]
        else "ローカルアテステーション(cryptography): 未インストール(任意機能)"
    )
    console_script_line = f"fox-webusb-host コンソールスクリプト: {report['console_script_path'] or '見つかりません'}"

    if report["native_manifest_registered"]:
        manifest_line = f"ネイティブメッセージングマニフェスト: 登録済み ({report['native_manifest_path']})"
        launcher_line = (
            f"  → 起動パス: {report['native_manifest_launcher_path']} "
            f"({'実在します' if report['native_manifest_launcher_exists'] else '見つかりません'})"
        )
    else:
        manifest_line = (
            f"ネイティブメッセージングマニフェスト: 未登録 "
            f"({report['native_manifest_path']} が見つかりません。'python3 install.py' を実行してください)"
        )
        launcher_line = None

    lines = [
        f"fox-webusb-host {report['fox_webusb_host_version']}",
        f"Python: {report['python_version']} ({report['python_implementation']}) on {report['platform']}",
        f"  実行ファイル: {report['python_executable']}",
        pyusb_line,
        rust_line,
        tkinter_line,
        attestation_line,
        console_script_line,
        manifest_line,
    ]
    if launcher_line:
        lines.append(launcher_line)
    lines.append("")
    if report["problems"]:
        lines.append("検出された問題:")
        for p in report["problems"]:
            lines.append(f"  - {p}")
    else:
        lines.append("問題は検出されませんでした。")
    return "\n".join(lines)


def main(argv=None) -> int:
    """`fox-webusb-host-doctor` / `python -m fox_webusb_host.diagnostics` の
    エントリポイント。問題が検出された場合は終了コード1、無ければ0を返す
    ——pyside6-webusb版の`python -m pyside6_webusb`と同じ約束。

    ⚠️ argv=Noneのときsys.argv[1:]へフォールバックしているのは飾りではない:
    setuptoolsが生成する実際のコンソールスクリプトは`sys.exit(main())`と
    引数無しで呼ぶため、ここでフォールバックしないと
    `fox-webusb-host-doctor --json`と打っても`--json`がmain()に一切届かない
    (pyside6-webusb `__main__.py` のdocstringが実際のスクリプトを読んで
    確認した内容と同じ)。
    """
    if argv is None:
        argv = sys.argv[1:]
    report = environment_report()
    if "--json" in argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_environment_report(report))
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
