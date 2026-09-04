# Changelog (fox-webusb)

このファイルは **fox-webusb** 自身の変更履歴です。移植元である
pyside6-webusb の変更履歴(v0.0.1〜v0.0.4b0)は同プロジェクト自身の
CHANGELOG.md を参照してください。fox-webusbはアーキテクチャが別物になった
ため、バージョン番号は移植元の系列を引き継がず 0.0.0 から数え直しています。

## [0.0.0a0] - 実機検証フィードバックに基づく修正リリース

移植元を pyside6-webusb v0.0.4b1 へ追従させつつ、実際にWindows +
LibreWolf環境で動作検証していただいたレポート(`checklog.md`)、および
Firefox devtoolsで`navigator.usb`を深く調べた際の見え方についてのフィード
バックに基づいて修正を行った。

### 修正(実機検証レポート `checklog.md` に基づくもの)

- **Windows上でネイティブホストの標準入出力を明示的にバイナリモード化**
  (`protocol.ensure_binary_stdio()`を追加、`__main__.py`が起動直後に呼ぶ)。
  Windows上のPythonは`sys.stdin.buffer`/`sys.stdout.buffer`経由でも、
  ファイルディスクリプタ自体がWindows Cランタイム(msvcrt)レベルで
  既定の「テキストモード」のままになっていることがあり、0x0D 0x0A の
  並びが黙って書き換えられたり0x1Aで早期にEOF扱いされたりする。
  fox-webusbが使う「4バイト長プレフィックス + 生バイト列」という
  プロトコルにとってこれは致命的で、`requestDevice()`実行中にネイティブ
  ホストが切断される(`NetworkError: fox-webusb native host disconnected`)
  という報告された不具合の原因はこれだと判断した。`msvcrt.setmode(fd,
  os.O_BINARY)`をWindows上でのみ明示的に適用する、Chromeの公式ネイティブ
  メッセージングサンプルでも使われている標準的な対処を追加した。
- **`read_message()`に長さプレフィックスの上限(`MAX_INCOMING_MESSAGE_BYTES`,
  128MiB)を追加**。上記の根本原因への対処に加え、万一何らかの理由で
  フレーミングが再びずれた場合に、実際に読もうとする前に分かりやすい
  `ValueError`として早期に失敗するための安全網。報告された
  `cannot read more than 33554432 bytes`という症状も、この種のフレーミング
  破損と整合する。
- **`manifest.json`の`content_scripts.match_about_blank`を`false`から
  `true`へ変更**。同一オリジンiframeで`navigator.usb`が見えないという
  報告に対する前向きな修正(`about:blank`+`document.write()`のような
  軽量なiframe構築パターンでも注入されるようにする)。ただし報告された
  症状の根本原因が完全に特定できたわけではない点はREADMEに明記した。
- **`usb.core.find()`呼び出し全体を`_enumeration_lock`で排他制御**
  (`bridge.py`)。直接の不具合報告ではないが、上記の原因調査の過程で、
  ワーカースレッドとチューザーダイアログのライブ更新タイマーが同時に
  USB列挙を呼びうる設計だったことに気づき、念のため直列化した。

### 移植元 (pyside6-webusb v0.0.4b1) からの追従

- `hardening.py`の`build_configurations_tree`/`_device_interface_class_tuples`
  内の、記述子の一部が読めなかった際に完全に無言でスキップしていた4箇所へ、
  診断ログ(`print(f"[fox-webusb-host] ...: 例外を無視: {e}")`)を追加
  (移植元のruff指摘を踏襲。制御フロー自体は変更なし)。
- `native/fox_webusb_accel`: `adb_pack_header`のu32キャスト時オーバーフロー
  バグを`u32::try_from(...).unwrap_or(u32::MAX)`で修正
  (移植元のclippy::pedantic指摘を踏襲)。`#[must_use]`属性を各関数へ追加。
  `format_transfer_in_success_json`(移植元が追加したRust側JSON構築の
  高速パス)をクレート自体には無改造で追加したが、**bridge.py側の実転送
  経路には組み込んでいない**——fox-webusbのbridge.pyは各メソッドがJSON
  文字列ではなくdictを返し、シリアライズをprotocol.py側の1箇所に集約する
  設計を採っているため、この関数が前提とする「メソッドがJSON文字列を
  直接返す」という形とは構造が異なり、無理に接続すると壊れやすくなると
  判断した(lib.rs該当箇所のdocコメントに詳細)。
  自前でclippy(`-W clippy::pedantic`含む)を実行し、指摘された
  lossy castの1件(`b as u32` → `u32::from(b)`)も追加で修正した。
  クレートのバージョンを0.2.0へ(新規公開関数の追加のため)。

### 改善: F12 devtoolsでの深い型検証への耐性(コミュニティフィードバックによる)

Firefox devtoolsで`navigator.usb`を深く調べると、`"usb" in navigator`
のような通常のAPI存在チェックは自然に通る一方、`instanceof EventTarget`・
`Symbol.toStringTag`・`Object.prototype.toString.call()`・
`constructor.name`といった深い型検証をすると、Firefox本体が実装している
`navigator.serial`(Web Serial API)とは異なり、独自実装であることが
すぐに分かってしまう、というフィードバックをいただいた。具体的には:

| チェック | 修正前のnavigator.usb | Firefox本体のnavigator.serial |
|---|---|---|
| `instanceof EventTarget` | `false` | `true` |
| `Symbol.toStringTag` | `undefined` | `"Serial"` |
| `Object.prototype.toString.call()` | `[object Object]` | `[object Serial]` |
| `constructor.name` | `"USBSingleton"` | `"Serial"` |

`page_polyfill.js`を以下のように書き直し、いずれも本物のブラウザ実装と
同じ見え方になるようにした:

- `navigator.usb`の実体を、`class USB extends EventTarget`という
  本物のEventTarget継承クラスのインスタンスに変更(旧`USBSingleton`)。
  `super()`で実際のネイティブ`EventTarget`コンストラクタを呼ぶため、
  `addEventListener`/`removeEventListener`/`dispatchEvent`は自前実装を
  やめ、継承した本物のものをそのまま使うようになった(副次的に、
  `once`/`signal`オプション等、ネイティブEventTargetが元々サポートする
  機能もすべて無償で使えるようになっている)。
- connect/disconnectイベントを、プレーンオブジェクトではなく
  `class USBConnectionEvent extends Event`の実インスタンスとして配送する
  ように変更。`instanceof Event`が真になり、`Object.prototype.toString
  .call()`も`"[object USBConnectionEvent]"`になる。
- `onconnect`/`ondisconnect`を、仕様の「イベントハンドラIDL属性」の
  挙動(代入は該当イベントへのaddEventListener登録と等価で、再代入は
  以前のハンドラを自動的に置き換える)に近い形のgetter/setterとして
  実装し直した。
- 各クラスへ`Symbol.toStringTag`を明示的に設定
  (`USB`・`USBDevice`・`USBConfiguration`・`USBInterface`・
  `USBAlternateInterface`・`USBEndpoint`・`USBConnectionEvent`・
  `USBInTransferResult`・`USBOutTransferResult`・
  `USBIsochronousInTransferResult`/`Packet`・
  `USBIsochronousOutTransferResult`/`Packet`)。
- 旧`OpenWebUSBDevice`を仕様どおり`USBDevice`へ、旧
  `USBConfigurationView`/`USBInterfaceView`を`USBConfiguration`/
  `USBInterface`へ改名(実データ構造の変更ではなく、
  `constructor.name`が仕様どおりに見えるようにするための改名)。
  転送結果(`{data, status}`等)もプレーンオブジェクトからそれぞれ専用の
  クラスへ変更した。
- **副次的な修正**: 上記のクラス化作業の過程で、
  `isochronousTransferIn()`が返す各パケットの情報が、実際には
  `{length, status}`(データそのものを含まない)になっていたことに気づいた。
  仕様上はパケットごとに`{data, status}`(結合済みバッファの該当区間への
  DataView)を返すべきで、`types/webusb-polyfill.d.ts`側は既に
  `USBIsochronousInTransferPacket`という`{data, status}`のインター
  フェースを(未使用のまま)定義していたにもかかわらず、実装側は反映
  できていなかった、という内部的な不整合だった。今回あわせて修正し、
  型定義側の未使用インターフェースも正しく使うように直した。

これらの変更は`navigator.usb`が外部から見て「動く」ことには影響しない
(既存のAPI呼び出し方はすべて同じまま動く)が、F12で深く調べた際の
自然さが大きく改善されている。

### 改善(続): F12 devtoolsでの深い型検証への耐性、第2弾

上記の対応後、「実装を覗く別の手段」についても考えられる限り塞いでほしい、
という追加のフィードバックをいただいた。`page_polyfill.js`を全面的に
ES6 class構文へ書き直し、次を追加で対応した:

- **内部状態を本物のプライベートフィールド(`#field`構文)へ移行**。
  以前は`this._handle`・`this._opened`・`this._claimedInterfaces`等、
  アンダースコア接頭辞の「命名規則による自己申告」でしかない疑似
  プライベートだったため、`Object.keys(device)`や
  `Object.getOwnPropertyNames(device)`、あるいは`JSON.stringify(device)`
  で丸見えになっていた。`#`構文の本物のプライベートフィールドは、
  クラス本体の外からは構文的にアクセスする手段が無く、上記のいずれの
  方法でも一切見えない。`USBDevice`・`USB`・`USBConnectionEvent`の
  内部状態すべてに適用した。他クラス(`USBInterface`)から
  `USBDevice`の claim/alternate 状態を問い合わせる必要がある箇所は、
  `_isInterfaceClaimed()`/`_activeAlternateFor()`という橋渡し用の
  メソッド(非enumerable。プライベートフィールドではなくクラス間連携の
  ための最小限の公開メソッド)経由にした。
- **公開メソッドから`.prototype`プロパティを排除**。ES6 classの
  メソッド構文(`class X { foo() {} }`)で定義された関数は仕様上
  非コンストラクタであり、`.prototype`プロパティを最初から持たない
  (旧`X.prototype.foo = function(){}`という代入スタイルでは
  `.prototype`が生えてしまっていた)。`navigator.usb.getDevices.prototype`
  等が`undefined`になり、ネイティブな操作と見分けがつきにくくなった。
- **公開メソッドの非コンストラクタ化**。上と同じ理由により、
  `new navigator.usb.getDevices()`のような呼び出しは
  `TypeError: ... is not a constructor`を投げるようになった
  (以前は素の関数だったため、`new`できてしまっていた)。
- **`Function.prototype.toString()`のネイティブ偽装**。
  monkey-patch検出でよく使われる「メソッドの`.toString()`でソースを
  覗く」手法への対策として、公開メソッド(`getDevices`・`requestDevice`・
  `open`・`claimInterface`・`transferIn`等、`USB`/`USBDevice`双方の
  操作メソッド全て)を`Proxy`で薄くラップし、`.toString()`プロパティへの
  アクセスだけをインターセプトして`"function xxx() { [native code] }"`
  を返すようにした。`get`トラップ以外は一切定義していないため、
  実際の呼び出し(`apply`)・`this`束縛・引数の受け渡しは完全に透過的
  (Proxyの既定のフォールスルー動作がそのまま効く)。`addEventListener`/
  `removeEventListener`は元々ネイティブの`EventTarget`から継承した
  ものをそのまま使っている(Proxyで包んですらいない)ため、これらは
  当然ながら最初からネイティブに見える。
- **メソッドの引数の数(`.length`)を仕様どおりに調整**。例えば
  `controlTransferOut(setup, data)`の`data`は仕様上省略可能な引数
  なので、`data = undefined`という既定値を明示することで
  `.length === 1`になるようにした(既定値を持つ仮引数は`.length`の
  カウント対象から外れる、というECMAScriptの仕様どおりの挙動を利用)。

これらはいずれも「navigator.usbというオブジェクトの実体を外部から見た
形」を本物のブラウザ実装にさらに近づけるためのもので、実際のセキュリティ
モデル(オリジン単位の許可・保護対象インターフェースクラスの拒否等、
ネイティブホスト側で強制されるもの)には一切影響しない。このファイル
自体がFirefox拡張機能の一部として動いている、という事実を隠す意図は
なく、README/CHANGELOGには通常どおり移植の経緯を明記している。

### 改善: 恒久インストールに対応

これまでは`about:debugging`経由の「一時的なアドオン」としてしか読み込む
手順を案内しておらず、Firefox/LibreWolfを再起動するたびに読み込み直す
必要があって不便だという指摘をいただいた。`dist/fox-webusb.xpi`
(`extension/`フォルダをそのままzip化したもの)を同梱し、README
「インストール」に恒久インストール手順を追加した:

- **LibreWolf**: ビルド時点で拡張機能の署名検証そのものが無効化されて
  いるため、`about:config`で`xpinstall.signatures.required`を`false`に
  した上で、`about:addons`から`.xpi`を直接インストールすれば恒久化できる
  ことを確認した(`checklog.md`の検証環境と同一条件)。
- **通常のFirefox(Release/Beta)**: 同じ設定変更では恒久インストールが
  できない仕様になっている(署名チェックがハードコードされているため)ので、
  Developer Edition/Nightly/ESRの使用、またはMozillaのAdd-on Developer
  Hubでの自己配布用署名(unlisted signing)の取得、のいずれかが必要な
  ことをREADMEに明記した。
- 拡張機能のID(`browser_specific_settings.gecko.id: "fox-webusb@local"`)
  は元から固定していたため、一時的インストールと恒久インストールを
  行き来しても、ネイティブメッセージングホスト側の許可設定
  (`allowed_extensions`)を変更する必要はない。

### テスト

Node側のテストを21件→37件へ拡充(EventTarget継承・Symbol.toStringTag・
constructor名・onconnect/ondisconnectの単一スロット挙動・
USBConnectionEventの型・各種toStringTag・プライベートフィールドによる
内部状態の不可視化・`.prototype`の不在・非コンストラクタ化・
`Function.prototype.toString()`のネイティブ偽装・メソッド引数数を検証)。
Python側もWindowsバイナリモード設定・メッセージ長上限まわりの新規
テストを追加し89件→93件。合計 93 (Python) + 37 (Node) + 13 (Rust) = 143件。

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
