# Changelog (fox-webusb)

このファイルは **fox-webusb** 自身の変更履歴です。移植元である
pyside6-webusb の変更履歴(v0.0.1〜v0.0.4b0)は同プロジェクト自身の
CHANGELOG.md を参照してください。fox-webusbはアーキテクチャが別物になった
ため、バージョン番号は移植元の系列を引き継がず 0.0.0 から数え直しています。

## [0.0.0.3] - pip installの安定化・環境診断ツール追加(GitHubタグ: v0.0.0a2+)

fox-webusbがFirefoxアドオンとして正式に許諾されたことを受けて、`pip install`
まわりの安定化と、姉妹プロジェクトpyside6-webusb(v0.0.5a0で追加、直近の
`v0.0.5a2`≡`0.0.5.post3`まで確認)から発想を移植した環境診断ツールを追加した
リリース。

### バージョン表記について

`0.0.0.1`/`0.0.0.2`はFirefoxのlinter警告解消のみが目的で、挙動・見た目の
変更が一切無い「コンプライアンスのみ」の修正だったため、GitHubタグは
`v0.0.0a1`のままにしていた。本リリースは新しい振る舞い(下記
`fox-webusb-host-doctor`・`install.py`のロジック刷新・`--xpi-version`)を
追加するため、姉妹プロジェクトpyside6-webusbが`0.0.5a0`エントリで採った
のと同じ理由(「単なるパッチ番号の繰り上げではなく振る舞いを追加するので
アルファ番号を進める」)で、GitHubタグ側のアルファ番号を `a1` → `a2` へ
進めている(`v0.0.0a2+`——さらなるコンプライアンスのみの修正が今後続く
場合は、pyside6-webusbの`.post`運用とは違いFirefoxのmanifest.jsonが
英字を一切許さないため、それらも新しいタグを切らずこの`a2+`の範囲内の
まま4番目のセグメントを伸ばして表す、という意図の「+」)。manifest.json
(および同期させている`__init__.py`/`pyproject.toml`)のバージョン文字列
自体は、`0.0.0.1`/`0.0.0.2`の時と同じ理由(Firefoxの仕様上、バージョン
文字列に英字を含められない)により、GitHubタグとは独立に単純な4番目の
セグメントの継続として`0.0.0.3`としている。

### Added

- **`fox-webusb-host-doctor`(新しいコンソールスクリプト)/
  `python -m fox_webusb_host.diagnostics`。** 姉妹プロジェクト
  pyside6-webusbが`0.0.5a0`で追加した`pyside6-webusb-doctor`と同じ発想——
  「`navigator.usb`が動かない」という報告の多くは、このパッケージ自身の
  ロジックのバグではなく周辺環境に起因する——を、fox-webusbのネイティブ
  メッセージングという文脈に合わせて移植した。`environment_report()`/
  `format_environment_report()`(新規`diagnostics.py`)は、pyusbのバージョン
  ・実際に解決できたlibusbバックエンド(`libusb1`/`libusb0`)・Tkinter
  (チューザーダイアログ用)・cryptography(任意のアテステーション機能用)
  ・Rustアクセラレーションの有無に加えて、**fox-webusb-host固有の項目として、
  「`fox-webusb-host`コンソールスクリプトが今のインタプリタから見て正しい
  場所に実在するか」と「このOSに登録済みのネイティブメッセージング
  マニフェストがあれば、そこに記録された起動パスが今も実在するか」**を
  診断する——これは今回の`install.py`側の変更(下記「Fixed」参照)が前提に
  している「pipにpythonの通り道を任せる」という発想を、`install.py`の
  ロジックとは独立に、インストール作業の後からでも再確認できるようにする
  ためのもの。`--json`オプション(pyside6-webusb版が`0.0.5.post3`で追加した
  ものと同じ)にも対応。`fox_webusb_host.__main__`(Firefoxから標準入出力
  経由で直接起動される、常駐プロセス本体の既存の起動契約)には一切手を
  入れておらず、完全に独立した別モジュール・別コンソールスクリプトとして
  追加した。
- **`install.py --xpi-version`。** 組み合わせて使う fox-webusb 拡張機能
  (`.xpi`)のバージョンを記録用に指定できるようにした。pip経由でXPI自体を
  インストールすることはできないため動作そのものには一切影響しない——
  Firefoxが実際に読むネイティブメッセージングマニフェスト自体は変更せず
  (未知のフィールドに対するFirefox側のスキーマ検証の挙動を検証できていない
  状態で、既に許諾済みの本番連携を壊すリスクを取らないため)、
  `~/.local/share/fox-webusb/paired-xpi-version.json`
  (Windows/macOSはそれぞれの`_support_dir()`配下)という完全に別の
  JSONファイルに`{"host_version": ..., "xpi_version": ...}`として記録する
  だけの、`install.py`自身の出力と`fox-webusb-host-doctor`(将来の拡張)
  からの参照用の任意メタデータ。`uninstall.py`もこのファイルを対象に
  含めるよう更新した。

### Fixed

- **`install.py`が、`--python`で指定したインタプリタではなく、
  install.py自身を実行しているインタプリタに対してしか
  `import fox_webusb_host`を確認していなかった。** 旧バージョン
  (`v0.0.0a1`)は、この抜けを覆い隠すための対症療法として、ランチャー
  自体にこのリポジトリの`native-host/src`への絶対パスを`PYTHONPATH`として
  常に埋め込んでいた(「`pip install -e .`が効いていれば無害、効いて
  いなければ安全網」という前提)。しかし実際には`--python`で別の
  インタプリタ(別のvenv等)を指定した場合、そのインタプリタで本当に
  `pip install`が済んでいるかを一度も検証しないまま、常に自作の
  PYTHONPATH埋め込みランチャーに頼っていた——実機(Windows + LibreWolf、
  `checklog2.md`)で`ModuleNotFoundError`が再発した根本原因はこれで、
  PYTHONPATHの埋め込みはそれを覆い隠していただけだった。実際に本リリース
  の検証中、システムのpython3(パッケージ未インストール)からinstall.pyを
  実行しつつ`--python`で「本当にpipインストール済みの別venv」を指定する
  という、まさにこのシナリオを再現したところ、修正前のコードは
  `エラー: fox_webusb_host がimportできません`と(誤って)報告することを
  確認した。
  新しい`_inspect_target_python()`は、`--python`で指定された、まさにその
  インタプリタをサブプロセスとして実際に起動し、`import fox_webusb_host`
  と`import usb.core`(pyusb)の両方をそのインタプリタ自身に確認させる
  (pyusb側の警告も同じ理由で、これまで確認対象がずれていた)。その上で、
  ランチャーの決め方自体も見直した:`_find_pip_console_script()`が、
  `pip install`(または`pip install -e .`)がそのインタプリタに対して
  実際に生成した`fox-webusb-host`コンソールスクリプトを
  (`sysconfig.get_path('scripts')`と`--user`用schemeの両方をそのインタ
  プリタ自身に問い合わせて)探し出し、見つかればそれをそのままネイティブ
  メッセージングの起動パスとして使う——setuptools/pipが生成するこの
  スクリプトは生成時のインタプリタ・site-packagesが常に正しく組み込まれて
  いるため、PYTHONPATHのような追加の配線が原理的に不要になる。標準的でない
  方法でインストールされた等、このスクリプトが見つからない場合にのみ、
  フォールバックとして`<python> -m fox_webusb_host`を実行するだけの
  (PYTHONPATHを埋め込まない)最小限のランチャーを書く。

### Tests

- `tests/test_diagnostics.py`(新規ファイル、15件): 実際にこの検証環境へ
  インストールされている本物のpyusb/libusb1に対するクリーンな基準点、
  および`sys.modules`への差し替えによる「pyusb自体が無い」
  「pyusbはあるがlibusbバックエンドが無い」「libusb1バックエンドが実際に
  解決できる」の3パターン、コンソールスクリプト検出・ネイティブ
  マニフェスト状態(`tmp_path`によるテスト用の差し替え口
  `_native_manifest_status(manifest_path=...)`経由、
  `settings_store.SettingsStore(path=...)`と同じパターン)、
  `format_environment_report()`の2分岐、`main()`の2つの終了コードと
  `--json`分岐・`argv=None`時の`sys.argv`フォールバックを検証する。
  **この過程で、自分自身が最初に書いたテストの誤りを2件、実際に走らせて
  見つけた**: `usb`単体・葉モジュール単体だけを`sys.modules`へ差し込む
  版は、`test_bridge.py`等が同じプロセス内で既に本物の`usb.backend`を
  importし終えている場合(=フルテストスイートの中でこのファイル単体より
  後ろで収集された場合)、`import usb.backend.libusb1 as _libusb1`が
  `sys.modules`の葉エントリではなく本物の`usb.backend`モジュールが保持する
  本物の`.libusb1`属性を辿ってしまい、偽装がすり抜けて本物のバックエンドを
  掴んでいた——「バックエンドが無いケース」のテストが実際には本物の
  libusb1が見えている環境でこっそり成功し、「libusb1が解決できるケース」
  のテストも(たまたま結論が一致していたために)本当に偽物を検証できて
  いなかった。`usb`・`usb.backend`・`usb.backend.libusb1`・
  `usb.backend.libusb0`の連鎖を丸ごと(`sys.modules`のエントリと相互の
  属性の両方)偽物に差し替える`_fake_usb_module()`ヘルパーに書き直し、
  意図的に本物を先にimportしてから偽装を試す手順で実際に再現・確認した
  上で修正した。
- `tests/` 合計: **122件**(既存107件 + 上記15件、いずれもpass)。
  `node tests/test_page_polyfill.js`(44件)・
  `node tests/test_extension_surface.js`(6件)・
  `cargo test --release`(`native/fox_webusb_accel`、13件)・
  `types/`のTypeScript型チェックは本リリースで対象コードの変更が無いため
  再実行していない。

### Project metadata

- Version: `0.0.0.3`(GitHubタグ: `v0.0.0a2+`)。
- `native-host/pyproject.toml`: `license = { text = "MIT" }` を単一の
  SPDX式(`license = "MIT"`)へ、`build-system.requires`を
  `setuptools>=68`から`setuptools>=77`へ変更。姉妹プロジェクト
  pyside6-webusbが`0.0.5a0`で見つけたのと全く同じ非推奨警告
  (`project.license`のテーブル形式は2027-02-18に削除予定)を、本リリース
  自身の`python -m build`の実行中に実際に検出して対応した(検査だけでなく
  実際にビルドして見つけたもの)。
- 検証環境: **Python `3.12.3`**、**`pyusb` `1.3.1`**(実際に`libusb1`
  バックエンドが解決)。`python -m build`で`sdist`/`wheel`の両方をクリーン
  ビルド(警告無し)し、`twine check`で両方とも合格を確認。ビルドした
  wheelを`--no-deps`を付けずに(=依存関係もPyPIから解決させて)クリーンな
  venvへ実際に`pip install`し、`fox-webusb-host`・`fox-webusb-host-doctor`
  両方のコンソールスクリプトが生成されること、`fox-webusb-host-doctor`が
  問題無しを報告すること、`fox-webusb-host`(pipが生成したコンソール
  スクリプトそのもの)を実際に起動して標準入力を閉じた際に正しく起動ログを
  出して終了することを確認した。さらに、その環境の`fox-webusb-host`/
  `fox-webusb-host-doctor`を一時的に取り除いてから`install.py`を再実行し、
  コンソールスクリプトが見つからない場合のフォールバック用ランチャー
  (`<python> -m fox_webusb_host`)についても、生成されたランチャーを実際に
  起動して同様に確認した。`uninstall.py`が、マニフェスト・
  (使われていた場合)フォールバックランチャー・
  `--xpi-version`指定時の記録ファイルをそれぞれ正しく削除することも
  実際に確認済み。`web-ext lint`相当の`addons-linter`を`extension/`へ
  実際に実行し、`0.0.0.2`の時と同じく errors 0 / warnings 0 / notices 0
  を確認した。

## [0.0.0.2] - Firefoxアドオンlinter警告の解消(v0.0.0a1ベース)

`v0.0.0a1`の機能一式はそのままに、AMO(addons.mozilla.org)のvalidator・
`addons-linter`が検出する警告を解消した、コンプライアンスのみを目的とした
修正リリース。挙動・見た目の変更は一切ない。

### 修正(`manifest.json`)

- **`version`を`"0.0.0a1"`から`"0.0.0.2"`へ変更**(`VERSION_FORMAT_DEPRECATED`)。
  `[0.0.0.1]`と同じ理由(Manifest V3以降、バージョン文字列は「ドット区切りの
  数字1〜4個」のみが許可され、英字を含む表記は将来使えなくなる)による、
  同じパターンの修正。Firefox(Gecko)のバージョン比較規則(未指定の末尾
  セグメントは`0`として扱われる)の下では`0.0.0.1 < 0.0.0.2 < 0.0.1`と
  なるため、`v0.0.0a1`と同じ「0.0.0.1の直後・0.0.1の手前」という位置づけを
  保ったまま、英字を使わずに表現できている。
  `browser_specific_settings`(`gecko.strict_min_version: "140.0"`・
  `gecko_android.strict_min_version: "142.0"`)は`v0.0.0a1`の時点で
  既に`[0.0.0.1]`と同じ値になっていたため、変更なし。

### 確認のみ(`no-unsanitized/property` — `[0.0.0.1]`で修正した箇所)

- `[0.0.0.1]`で`popup/popup.js`・`options/options.js`に加えた、動的な値を
  `innerHTML`へ直接代入する箇所をDOM APIによる安全な構築へ置き換える修正は、
  `v0.0.0a1`のi18n対応実装時に同じ設計(同一の`🛡️ web-ext lint
  (UNSAFE_VAR_ASSIGNMENT)対応`というコメント付き)が本リリースとは独立に
  既に引き継がれており、追加の修正は不要だった。残る`innerHTML`代入は
  いずれも`container.innerHTML = ''`という変数を含まない静的な空文字列
  リテラルのみで、linterには指摘されない。

### 確認のみ(`native-host/pyproject.toml`)

- `readme`フィールド(`"README.md"`、パッケージルート内を指す)は
  `[0.0.0.1]`で報告された`"../README.md"`(パッケージルート外を指す
  不正なパス)の問題を、`v0.0.0a1`の時点で元から抱えていなかった。
  `version`のみ`manifest.json`と揃えて`"0.0.0.2"`へ更新
  (`fox_webusb_host/__init__.py`の`__version__`/docstringも同様)。

### 検証

- `addons-linter`(Mozilla公式パッケージ、npm)を実際にインストールし、
  修正前の`extension/`(`v0.0.0a1`のコードそのもの)に対して実行した
  ところ、`errors 0 / notices 0 / warnings 1`(`VERSION_FORMAT_DEPRECATED`
  のみ)だった。`[0.0.0.1]`のリリースノートが報告していた6件の警告のうち
  5件(`no-unsanitized/property`3件・`strict_min_version`関連2件)は、
  `v0.0.0a1`の開発時点で本リリースとは独立に既に解消されていたことになる。
  上記の`version`修正を適用した`extension/`に対して同じ`addons-linter`を
  再実行し、`errors 0 / notices 0 / warnings 0`になることを確認した。

## [0.0.0a1]

### セキュリティ (pyside6-webusb側の独立した監査で見つかった問題の移植)

fox-webusbは移植元(pyside6-webusb v0.0.4b1)からフォークした時点のコードを
引き継いでいたため、その後pyside6-webusb側で見つかった問題のいくつかを
同様に抱えていないか確認し、実際に抱えていたものを修正した。

- **alternate setting混同による保護対象インターフェースクラスへの回避策
  (pyside6-webusb側No.1相当)。** `_find_claimed_endpoint()`(bulk/interrupt
  転送・endpoint宛てcontrol転送)は元から「claim済みかつ現在選択中の
  alternate setting」だけを見る設計になっていたが、`interface_class_for()`
  自体はalternate settingという概念を知らず、`claim_interface()`の保護対象
  クラス判定と`_control_transfer_validation_error()`のinterface宛て
  (class種別)分岐の2箇所がこれに依存していたため、この2箇所だけ回避策が
  成立し得た。`interface_class_for()`にalternate_setting引数を追加し、
  両呼び出し元がそれぞれ適切な値(claim直後は0、以降は
  `active_alternates`で追跡している実際の値)を明示的に渡すよう修正。
- **`requestDeviceChooser()`にサーバー側のユーザー操作検証が無かった
  (pyside6-webusb側No.2相当、フィルタ構造検証は元から実装済みだった)。**
  `page_polyfill.js`自身の`navigator.userActivation.isActive`チェックは
  ページのMAIN worldで動くため、`content_script.js`が待ち受ける
  `postMessage`の形さえ真似すれば丸ごと迂回できた。pyside6-webusb版とは
  異なる、fox-webusb固有の、より強力な対策を実装した:
  `content_script.js`(isolated world)がdocumentへ直接
  capturing listenerを張り、`event.isTrusted === true`の実操作だけを
  観測して直近の「本物の」ユーザー操作の有無を独立に判定する——ページ側の
  JSはisTrustedがtrueの合成イベントを一切作れないため、これはページ自身に
  偽装しようがない。PySide6/QtWebEngine版ではDOM側のUser Activation状態を
  ホスト側から独立に観測する手段が無く「ハードルを上げる」止まりだったのに
  対し、拡張機能のisolated worldというFirefox固有の仕組みのおかげで、
  こちらの方が実際にページ側から偽装不可能な、より強い保証になっている。
- **デバイス提供文字列(製造者名・製品名・シリアル番号・configurationName・
  interfaceName)が無検査だった(pyside6-webusb側No.3相当)。**
  `sanitize_device_string()`を移植し、制御文字・Unicode双方向オーバーライド
  文字の除去と長さ上限を適用。Tkinterの`Label`はQtの`QLabel`と違いHTML/
  リッチテキストを解釈しないため、pyside6-webusb版で別途必要だった
  「PlainTextを強制する」対応は不要だった。
- **`openDevice()`にオリジンあたりの上限が無かった(pyside6-webusb側No.6
  相当)。** 1オリジンが同時に保持できるハンドル数に上限を設け、超過時は
  そのオリジンの最も古いハンドルをLRU的に自動解放する(openDevice自体は
  常に成功を返し続ける)。fox-webusbは本物のスレッドプールで動くため、
  数える→退去→追加を専用ロックで直列化する必要があった
  (pyside6-webusb版はQtの単一スレッドモデルなので不要だった)。
- `closeDevice()`相当(`close_device()`)・ホットプラグイベントの配送
  (`dispatchDeviceEvent`が`origins`で宛先を絞る設計)は、確認の結果
  pyside6-webusb側で見つかった問題(No.4・No.5)を元々抱えていなかった。

### アーキテクチャ: 二重サーフェス (Chromium surface / Firefox-style surface)

`navigator.usb`のクラス定義・エラー変換・base64変換等を`webusb_core.js`
という単一の共有ファイルへ切り出した。トランスポート(呼び出し方)だけが
異なる2つの「顔」がこれを共有する:

- **Chromium surface** — 従来どおりの`page_polyfill.js`。任意のWebページの
  MAIN worldへ注入され、`window.postMessage()`経由で動く。
- **Firefox-style surface** — 新設。`background.js`自身が`webusb_core.js`を
  `postMessage`/`content_script.js`を一切経由せず直接駆動し、拡張機能自身の
  `navigator`へ`navigator.usb`相当を取り付ける。`browser.runtime.
  getBackgroundPage()`経由で`popup.js`等、拡張機能の他のページからも
  同じインスタンスを参照できる。WICGが実際に提案している
  ["extension service worker" 拡張案](https://github.com/WICG/webusb/blob/main/extension-service-worker-explainer.md)
  (Chrome 118以降、拡張機能のservice workerに`navigator.usb`を公開している
  実際の仕様の方向性)と同じ発想を、Manifest V2の永続的background pageに
  合わせて実装したもの。

両サーフェスは同一の`webusb_core.js`を共有するため、挙動が食い違うことは
構造的に起こり得ない。詳細はREADME「二重サーフェス」参照。

### 仕様追従: WebUSB仕様(2026年9月時点)との突き合わせ

- `USBConnectionEvent`をWICG仕様の現行版(`wicg.github.io/webusb`、2026年6月版)
  のIDLどおりに修正: `USBConnectionEventInit.device`が`required`であることを
  実際に強制するようにした(以前は省略してもdeviceがnullのまま黙って構築
  できてしまっていた)。
- **Permissions Policy(`usb`機能)に対応。** `Permissions-Policy: usb`
  ヘッダーや`<iframe allow="usb">`属性を`document.permissionsPolicy.
  allowsFeature('usb')`で確認し、既定のallowlist(`self`)により許可されて
  いないクロスオリジンiframeには`navigator.usb`自体を一切公開しないように
  した。これは後述の`usb-unrestricted`とは正反対の、ページ側が「このフレーム
  ではWebUSBを使わせない」と宣言できる防御強化の仕組みである。実験的APIな
  ので未実装ブラウザでは何も制限しない。

現行仕様で見つかった`usb-unrestricted`(Isolated Web Appsが保護対象
インターフェースクラス・ブロックリストを迂回できるようにする、Chrome/
ChromeOS固有の新機能)は、**意図的に実装していない。** Isolated Web Appsに
相当する、暗号学的に検証された配布・実行環境がFirefox拡張機能には存在せず、
これを安全に成立させる前提条件そのものが無い。実装すれば「任意のページが
セキュリティキーやキーボードに生アクセスできる」経路を作るだけになり、
このプロジェクト全体が積み上げてきた保護を素通りさせることになるため、
見送るのが正しいと判断した。

### 独自機能: ローカルアテステーション (Ed25519)

`window.__foxWebUSB.extensions.attestation` を新設。オリジンごとの
Ed25519鍵ペア(確立された、広く検証済みの署名方式そのもの——独自の暗号
アルゴリズムは一切自作していない)を使い、サイトが「このレスポンスが本当に
前回と同じローカルブリッジから来たものか」をTOFU方式で検証できる、実Chrome
のWebUSBには存在しない機能。鍵はオリジンごとに完全独立しており、クロス
サイトトラッキングの識別子として悪用できないよう設計している。オプトイン
の依存関係(`cryptography`)が無い環境では機能自体が無効化されるだけで、
基本機能には影響しない。`getAttestationPublicKey`/`signAttestationChallenge`
(いずれも新規PAGE_METHODS)、`native-host/src/fox_webusb_host/attestation.py`
参照。

### 独自コマンド

拡張機能自身の特権ページ(background.js/popup.js/options.js)向けに
`window.__foxWebUsbManagement` を新設。既存のtrusted-onlyな管理系操作
(`listKnownDevices`等)を`getBackgroundPage()`経由で直接呼べるように整理した
——`navigator.usb`自体の形状・挙動には一切手を加えず、新しい権限も追加して
いない、単なる呼び方の糖衣構文。

### F12デバッグヘルパー

`window.__foxWebUSB`(`listGrantedDevices`/`bridgeInfo`/`explainTransferLimits`)
を新設。特に`bridgeInfo()`はご要望の「バージョンチェック用のF12」に対応する
もので、F12でDevToolsコンソールを開き`__foxWebUSB.bridgeInfo()`と打つだけで
現在のブリッジのバージョンを確認できる。

### 実際のUSB接続でありがちな挙動の確認

転送の真っ最中に物理的に切断される(ケーブルが抜ける、ファームウェア更新で
再起動する等、`errno=19`/ENODEV)ケースを実際にシミュレートするテストを
追加した。STALL/Babbleは元々正しく実装されていたことを確認済み。このケース
は特別扱いせず通常のNetworkError相当に落ちる現状の実装が、実際のChromeの
挙動と一致していることも確認した(=修正ではなく、検証によって現状の設計が
正しいと確定させたもの)。

### TypeScript

`window.__foxWebUSB`(`.extensions.attestation`含む)がこれまで型定義に一切
反映されていなかったため、新たに`types/fox-webusb-extensions.d.ts`を作成
(共有の`webusb-polyfill.d.ts`とは意図的に別ファイル——pyside6-webusb版とは
形が異なるため)。`fox-webusb-extensions-sample-usage.ts`/
`fox-webusb-extensions-negative-check.ts`を揃え、`tsc --strict`で実際に
検証済み。

### i18n: UIのja/en/zh_CN対応

- 拡張機能側(popup/options)は標準のWebExtensions i18n API
  (`browser.i18n`、`_locales/{ja,en,zh_CN}/messages.json`)に対応。
  `default_locale`は`ja`。
- ネイティブホスト側のチューザーダイアログ(Tkinter、`browser.i18n`相当の
  仕組みを持たない別プロセス)向けに、簡易な翻訳テーブル`i18n.py`を新設。
  表示言語は`content_script.js`が`browser.i18n.getUILanguage()`で求めた
  Firefox本体のUI言語を、ネイティブメッセージング経由で(認可判定には
  一切使わない、表示上の好みとしてのみ)渡す仕組みにした
  (`request_device_chooser()`のdocstring参照)。

### 修正: `install.py`のPYTHONPATH問題(実機検証で発見)

`checklog2.md`(Windows + LibreWolf環境での実機検証)で報告された
`ModuleNotFoundError: No module named 'fox_webusb_host'`を実際に再現し、
修正を確認した。ランチャースクリプト自体に`native-host/src`へのPYTHONPATHを
明示的に埋め込むようにした——`pip install -e .`を忘れた、または`--python`で
指定したものとは別のインタプリタでインストールしてしまった場合の
セーフティネットになる(正しくインストールされている場合は無害)。

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
