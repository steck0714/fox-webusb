#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""uninstall.py: install.py が作成したランチャー・マニフェスト・
(Windowsの場合)レジストリキーを取り除く。settings_store.py が管理する
許可情報(~/.config/fox-webusb/settings.json 等)はここでは消さない
——単にFirefoxとの接続を切るだけで、許可履歴を消すのは別の操作として
扱うべきだと考えたため。全て消したい場合は、install.pyの出力に表示された
設定ファイルのパスを手動で削除すること。"""
import sys
from pathlib import Path

from install import HOST_NAME, _linux_manifest_dir, _macos_manifest_dir, _support_dir  # noqa: E402


def main():
    removed = []

    if sys.platform.startswith("win"):
        manifest_path = _support_dir() / f"{HOST_NAME}.json"
        launcher_path = _support_dir() / "fox-webusb-host.bat"
        try:
            import winreg
            key_path = f"Software\\Mozilla\\NativeMessagingHosts\\{HOST_NAME}"
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
                removed.append(f"registry key HKCU\\{key_path}")
            except FileNotFoundError:
                pass
        except Exception as e:
            print(f"警告: レジストリキーの削除に失敗しました: {e}", file=sys.stderr)
    elif sys.platform == "darwin":
        manifest_path = _macos_manifest_dir() / f"{HOST_NAME}.json"
        launcher_path = _support_dir() / "fox-webusb-host.sh"
    else:
        manifest_path = _linux_manifest_dir() / f"{HOST_NAME}.json"
        launcher_path = _support_dir() / "fox-webusb-host.sh"

    for path in (manifest_path, launcher_path):
        try:
            path.unlink()
            removed.append(str(path))
        except FileNotFoundError:
            pass

    if removed:
        print("以下を削除しました:")
        for item in removed:
            print(f"  - {item}")
    else:
        print("削除対象が見つかりませんでした(既にアンインストール済みかもしれません)。")


if __name__ == "__main__":
    main()
