# Changelog (fox-webusb)

このファイルは **fox-webusb** 自身の変更履歴です。移植元である
pyside6-webusb の変更履歴(v0.0.1〜v0.0.4b0)は同プロジェクト自身の
CHANGELOG.md を参照してください。fox-webusbはアーキテクチャが別物になった
ため、バージョン番号は移植元の系列を引き継がず 0.0.0 から数え直しています。

## [0.0.0] - 初回リリース(pyside6-webusb v0.0.4b0からの移植)

### 背景

Firefoxは公式に `navigator.usb` (WebUSB) を実装しない方針を明言している
(mozilla/standards-positions#100, position: negative。2026年8月時点で確認
済み)。そのため、pyside6-webusbが採っていた「QtWebEngine(Chromium)へJSを
注入する」というアプローチはFirefoxには存在しない土台に依存しており、
そのままでは移植できない。唯一現実的な経路である「Firefox拡張機能 +
Native Messagingホスト」というアーキテクチャで作り直した。

### 追加

- **Firefox拡張機能** (`extension/`, Manifest V2)
  - `page_polyfill.js`: `navigator.usb` 本体。ページのMAIN worldに注入される。
    移植元 `polyfill.py` の `WEBUSB_POLYFILL_JS` と同じオブジェクトモデル
    (`USBDevice`/`USBConfiguration`/`USBInterface`/`USBEndpoint` 相当)・
    エラー変換規約(`SecurityError:`等のプレフィックスからDOMExceptionへ)を
    保ったまま、トランスポートだけを QWebChannel から `window.postMessage`
    ベースのRPCへ置き換えた。
  - `content_script.js`: 各フレーム(iframe含む)へ`document_start`で注入され、
    ページとbackground.jsの中継を行う。
  - `background.js`: ネイティブメッセージング接続の維持、
    `sender.url`(ブラウザが検証済みの値)からのオリジン導出、タブ/フレーム
    登録簿によるホットプラグイベントのファンアウト、信頼済み送信元判定
    (`isTrustedSender`)を担う。
  - `popup/`・`options/`: 接続状態の表示、許可オリジン/既知デバイス履歴の
    管理UI(信頼済み専用メソッドのみを使用)。
- **ネイティブメッセージングホスト** (`native-host/`, Pythonパッケージ
  `fox_webusb_host`)
  - `bridge.py`: 移植元 `bridge.py` のセキュリティモデル(保護対象
    インターフェースクラス・ブロックリスト・オリジン単位の許可管理・
    control transfer検証等)を、dispatch方式(method名→関数)で再構成。
    `origin` は呼び出し側(background.js)が直接渡す設計に変更し、
    移植元の `FrameOriginTracker`/フレームトークン機構は不要になった
    (README「オリジンの検証」参照)。
  - `hardening.py` / `errors.py`: 移植元から**ロジック無変更**で移植
    (元々Qt非依存の純粋ロジックだったため)。
  - `settings_store.py`: QSettingsの代替となる、OS標準の設定ディレクトリに
    置く1個のJSONファイルストア。
  - `chooser_dialog.py`: PySide6 QDialogの代替となるTkinter製デバイス
    選択ダイアログ。専用のGUIスレッドで動作し、`queue.Queue` +
    `concurrent.futures.Future` でワーカースレッドとの受け渡しを行う。
  - `protocol.py`: ネイティブメッセージングの生ワイヤ形式(4バイト長 + JSON)
    の読み書きと、Firefoxのホスト→拡張機能方向1MB上限
    (developer.mozilla.org、2026年8月時点で確認)を回避するための
    base64+チャンク分割エンベロープ。
  - `__main__.py`: stdin読み取り専用スレッド、リクエストを処理する
    ワーカースレッドプール、1.5秒間隔のホットプラグ監視スレッド、
    Tkinterの永続GUIスレッドを配線するエントリポイント。
  - `install.py`/`uninstall.py`: Linux/macOS/Windows それぞれの流儀での
    ネイティブメッセージングホストマニフェストの配置/削除。
- **Rustアクセラレーション** (`native/fox_webusb_accel/`)
  - 移植元 `native/pyside6_webusb_accel/` (v0.0.4b0)をパッケージ名の変更
    のみでそのまま移植(base64コーデック・ADBワイヤプロトコルのpack/unpack/
    verify/checksum ヘルパー。元々Qt非依存だったため無改造)。
  - rustc/cargo 1.75.0 (Ubuntu 24.04のaptパッケージ)でのビルド・
    `cargo test --release`(10件)を実機で確認。`maturin develop --release`
    で実際にPython拡張として組み込み、標準base64との出力一致・RFC 4648
    テストベクタ・ADBヘッダのpack/unpack/verify往復をクロス検証済み。
- **型定義** (`types/webusb-polyfill.d.ts`)
  - 移植元と同一のAPI形状を記述。モジュールではなくグローバル
    ambient宣言として書き直し(`sample-usage.ts`が無importで`USBDevice`等を
    参照できるようにするため)。`sample-usage.ts`(正しい使い方が型エラーに
    ならないことの確認)・`negative-check.ts`(`@ts-expect-error`で誤った
    使い方が確実に型エラーになることの確認)ともに
    `tsc --noEmit --strict` で確認済み。
- **テスト**(計89件のPython/pytest + 21件のNode + 10件のRust
  ネイティブテスト、全て本リリースで実行・通過を確認)
  - `tests/fake_usb.py`: pyusbの形だけを模したフェイクデバイス
    (実機・libusbバックエンド不要)。
  - `tests/test_bridge.py`(34件): フィルタ照合・grant/revoke・
    claimInterface状態機械・保護対象クラス・bulk/control/isochronous
    転送の検証ロジック・per-handleロックの実スレッド競合テストを含む。
  - `tests/test_hardening.py`(29件)・`tests/test_errors.py`(2件)・
    `tests/test_settings_store.py`(11件)・`tests/test_protocol.py`
    (8件、日本語等マルチバイト文字がチャンク境界を跨いでも壊れないこと
    のテストを含む)。
  - `tests/test_end_to_end_subprocess.py`(5件): `python -m
    fox_webusb_host` を実際に別プロセスとして起動し、本物のネイティブ
    メッセージングのワイヤ形式で疎通確認する統合テスト。
  - `tests/test_page_polyfill.js`(21件): `page_polyfill.js` を
    Node の `vm` モジュールで実際に実行し、`window.postMessage` を
    エミュレートしてcallBridgeの往復を検証する機能テスト。

### 変更(移植元からの意図的な設計変更、詳細はREADME参照)

- 転送メソッドの再入・競合対策を、移植元の `_busy_handles`
  (bulk転送のみ対象、Qtの`processEvents()`による限定的な再入だけを想定)
  から、**全handle操作メソッドに適用される per-handle ロック**
  (`bridge.py` の `_handle_guard`)へ一般化した。fox-webusbのネイティブ
  ホストは本物のスレッドプールで並行処理するため、より広い保護が必要と
  判断した。これにより、移植元がv0.0.4bのCHANGELOGで「スコープ外」と
  明記していた `closeDevice` の穴も副産物として塞がれている。
- v0.0.4b0が追加した「256KiB単位のbulk転送チャンク分割 +
  `QCoreApplication.processEvents()`」によるQt UIフリーズ対策は、
  **意図的に移植していない**。この対策が守ろうとしていたQtメインスレッド
  (共有UIスレッド)がfox-webusbのアーキテクチャには存在せず
  (Tkinterチューザーは専用スレッドで独立に動作する)、加えて
  ctypesベースのpyusbバックエンドはブロッキングI/O呼び出し中にGILを
  解放するため、単一の大きな`dev.read()`/`dev.write()`呼び出しでも
  他のワーカースレッドの処理が止まることはない。
- ホットプラグのconnect/disconnectイベントの配送対象を、移植元の
  「現在のページのトップレベルオリジンのみ」から、**許可済みの全オリジン・
  全フレーム**へ拡大した。移植元は1ページ=1ブリッジインスタンスという
  制約上この範囲に留めていたが、fox-webusbはブラウザ全体で1つの
  常駐ホストであり、タブ/フレーム登録簿(`background.js` の
  `frameRegistry`)を使って複数タブ・iframeへ正しくファンアウトできる。
- `UsbHotplugWatcher` の初回poll()が「起動時点で既に挿さっていたデバイス」
  を丸ごと新規接続として報告してしまう挙動(`_known` が空集合から
  始まるため)は、`hardening.py` 自体はそのまま移植しつつ、
  `WebUsbNativeBridge.__init__` で1回だけ静かにpoll()して基準を作る
  ことで対処した(README「既知の限界」参照——ロジック自体は移植元と
  同一のまま、fox-webusb固有の「ブラウザ全体で1つの常駐プロセス」という
  実行モデルに対して呼び出し側で吸収した)。

### 移植を通じて発見した、移植元(pyside6-webusb v0.0.4b0)側の既知の問題

- `tests/test_bridge.py` に `def
  test_bulk_transfer_reentrant_call_on_busy_handle_is_rejected():` と
  `def test_bulk_and_control_transfer_reject_absurdly_large_length():`
  の`def`行が欠落しており、両テストの本体が直前の
  `test_bulk_transfer_round_trips_realistic_adb_wrte_message` の関数末尾に
  そのまま連結されてしまっている(`ast.parse`で静的に確認)。構文エラーには
  ならない(裸の文字列リテラルは有効な式文であるため)が、pytestは
  この2つを独立したテストとして収集できず、`if __name__ == "__main__":`
  ブロックで直接呼び出そうとすると `NameError` になる。fox-webusb側の
  対応するテストは、この移植とは無関係に最初から正しく独立した関数として
  書き直しているため影響を受けていない。pyside6-webusb側の修正
  (該当2箇所への`def`行の復元)は、本リリースのスコープ外として
  upstream側での対応に委ねる。
