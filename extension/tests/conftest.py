# -*- coding: utf-8 -*-
"""pytestに'tests/'を発見させた際、pip install不要でsrc/レイアウトのパッケージを
importできるようにするための設定。`pip install -e .`済みなら本来不要だが、
素のクローン直後でも `pytest` や `python tests/test_*.py` が動くようにしておく。

移植元(pyside6-webusb)のconftest.pyにあった「DISPLAYが無い環境ではQt_QPA_PLATFORM
をoffscreenへ自動フォールバックする」処理は、fox-webusbのネイティブホストが
Qtに一切依存しないため丸ごと不要になった(Tkinterはテスト側でインスタンス化
しなければそもそも起動しないので、ヘッドレスCIでも通常のテストが素朴に動く。
GUIそのものを操作するテストは別途 `xvfb-run` 等の使用をtests/README等で
案内する)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "native-host", "src"))
sys.path.insert(0, os.path.dirname(__file__))
