# fox-webusb

**バージョン 0.0.0.1** ・ 移植元: pyside6-webusb v0.0.4b1

Firefoxに `navigator.usb`(WebUSB)のポリフィルを追加する拡張機能 + ネイティブ
メッセージングホストです。

> 🦊 **これは実験的なプロジェクトです。** 生のUSBデバイスに素のJavaScriptから
> アクセスできるようにする、という性質上、通常のブラウザ拡張機能よりも
> セキュリティ上の配慮が必要です。「何が・なぜ・どこまで」安全にしてあるかを
> 本READMEで詳しく説明しています。読んだ上でご利用ください。

---

## 目次

1. [これは何か / なぜ必要か](#これは何か--なぜ必要か)
2. [アーキテクチャ](#アーキテクチャ)
3. [インストール](#インストール)
4. [セキュリティモデル](#セキュリティモデル)
5. [pyside6-webusb からの移植で変えたところ](#pyside6-webusb-からの移植で変えたところ)
6. [0.0.0a0: 実機検証(Windows/LibreWolf)で見つかった不具合と修正](#000a0-実機検証windowslibrewolfで見つかった不具合と修正)
7. [既知の限界・未検証事項](#既知の限界未検証事項)
8. [ディレクトリ構成](#ディレクトリ構成)
9. [テスト](#テスト)
10. [ライセンス](#ライセンス)

---

## これは何か / なぜ必要か

pyside6-webusb は、PySide6/QtWebEngineで作るデスクトップアプリの中に
`navigator.usb` を注入するライブラリでした。今回のリクエストは「これをFirefox
で動くように移植してほしい」というものです。

これは見た目以上に難しい移植です。理由は単純で、**Firefoxは
`navigator.usb` を実装していません**。Mozillaの公式なスタンダードポジション
([mozilla/standards-positions#100](https://github.com/mozilla/standards-positions/issues/100))
はWebUSBに対して `position: negative`(=harmful)を明言しており、実装する
予定がないことをはっきり述べています。Safari/WebKitも同様に反対の立場です。
つまり、pyside6-webusbが依存していた「QtWebEngine(Chromium)の中にJSを注入
する」という土台そのものが、Firefoxには存在しません。ブラウザ本体を書き換える
以外の方法で `navigator.usb` をFirefoxに持たせる手段は、実質的に1つしか
ありません:

> **Firefox拡張機能でページに `navigator.usb` 相当のオブジェクトを注入し、
> 実際のUSBアクセスは Native Messaging 経由でローカルの外部プロセスに
> やらせる。**

fox-webusbはこの構成を採っています。pyside6-webusbの「JSポリフィル + Python
ブリッジ + セキュリティ多層防御」という設計そのものは非常に理にかなっていた
ため、**その設計思想はできる限りそのまま踏襲し、トランスポート層(JSと
Pythonの間をどう繋ぐか)だけをFirefoxの拡張機能アーキテクチャに合わせて
作り直しました。**

## アーキテクチャ

```
┌─────────────────────────── Firefox ───────────────────────────┐
│                                                                  │
│  Webページ (例: https://example.com)                            │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ page_polyfill.js (MAIN world)                            │    │
│  │   navigator.usb.requestDevice() / transferIn() 等          │    │
│  │        │ window.postMessage()                             │    │
│  └────────┼───────────────────────────────────────────────┘    │
│           │                                                     │
│  ┌────────▼───────────────────────────────────────────────┐    │
│  │ content_script.js (isolated world, 各フレームに1個)        │    │
│  │   browser.runtime.sendMessage() で中継                    │    │
│  └────────┼───────────────────────────────────────────────┘    │
│           │                                                     │
│  ┌────────▼───────────────────────────────────────────────┐    │
│  │ background.js (persistent background page)                │    │
│  │   ・sender.url からoriginを検証(ページの自己申告は信用しない) │    │
│  │   ・タブ/フレームの登録簿(ホットプラグイベントの配送先)      │    │
│  │   ・browser.runtime.connectNative() でホストと通信          │    │
│  └────────┼───────────────────────────────────────────────┘    │
└───────────┼───────────────────────────────────────────────────┘
            │ Native Messaging (stdin/stdout, 4バイト長プレフィックス)
┌───────────▼───────────────────────────────────────────────────┐
│  fox-webusb-host (別プロセス。Firefoxとは独立したPythonプロセス)   │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ __main__.py: stdin読み取り → ワーカースレッドプール →       │    │
│  │              stdout書き込み(chunk分割) / ホットプラグ監視 /   │    │
│  │              Tkinterチューザーダイアログ(専用GUIスレッド)     │    │
│  ├────────────────────────────────────────────────────────┤    │
│  │ bridge.py: WebUSBのセキュリティモデル本体                    │    │
│  │   (保護対象インターフェースクラス・ブロックリスト・            │    │
│  │    オリジン単位の許可・per-handleロック 等)                  │    │
│  ├────────────────────────────────────────────────────────┤    │
│  │ pyusb (libusb) ──────────► 実USBデバイス                    │    │
│  └────────────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────────┘
```

`page_polyfill.js` から見える `navigator.usb` のAPI形状(メソッド名・引数・
戻り値)は、`types/webusb-polyfill.d.ts` のとおり、**pyside6-webusb版と
完全に同一**です。ページ側のコードは、Chromeでも、pyside6-webusbアプリでも、
fox-webusb(Firefox)でも、一切書き換えずに動きます。

## インストール

1. **Python側(ネイティブホスト)をインストールする:**
   ```bash
   cd native-host
   pip install -e .          # 仮想環境を使わない場合は末尾に --break-system-packages
   python3 install.py        # OSごとのネイティブメッセージングマニフェストを配置する
   ```
   `install.py` は Linux (`~/.mozilla/native-messaging-hosts/`)・
   macOS (`~/Library/Application Support/Mozilla/NativeMessagingHosts/`)・
   Windows (レジストリキー経由) いずれにも対応しています。

2. **(任意・推奨) Rustアクセラレーションをビルドする:**
   ```bash
   cd native/fox_webusb_accel
   pip install maturin
   maturin develop --release
   ```
   ビルドしなくても標準ライブラリのbase64実装へ自動的にフォールバックし、
   完全に動作します(`bridge.py` 冒頭のコメント参照)。速度差が問題になるのは
   WebADB等でMB級のペイロードを頻繁にやり取りする場合です。

3. **拡張機能を読み込む。** 2通りの方法があります。

   ### A) 一時的インストール(お試し用。ブラウザを閉じると消える)

   `about:debugging#/runtime/this-firefox` を開き、「一時的なアドオンを
   読み込む」から `extension/manifest.json` を選択してください。手早く
   試すには便利ですが、**Firefox/LibreWolfを再起動するたびに消える**ため、
   毎回読み込み直す必要があります。

   ### B) 恒久インストール(推奨。一度入れれば再起動しても消えない)

   このリポジトリには署名済みの`.xpi`は含めていません(署名にはMozillaへの
   申請が必要で、このパッケージ側だけでは完結しないため)。代わりに、
   **未署名のアドオンを許可する設定**を使って恒久的にインストールします。
   `dist/fox-webusb.xpi`(`extension/`フォルダをそのままzip化しただけの
   もの。手元で作り直す場合は `cd extension && zip -r -X ../dist/fox-webusb.xpi .`)
   を使います。

   - **LibreWolfの場合(`checklog.md`の検証環境):** LibreWolfは
     ビルド時点で拡張機能の署名検証そのものを無効化しているため、
     以下の手順だけで恒久インストールできます。
     1. `about:config` を開き、`xpinstall.signatures.required` を
        `false` にする。
     2. `about:addons` → 歯車アイコン → 「ファイルからアドオンをインストール」
        → `dist/fox-webusb.xpi` を選択する。
     3. 「ソースを確認できないアドオンの追加」という警告が出ますが、これは
        署名が無いことに対する通常の警告なので、追加を許可してください。
   - **通常のFirefox(Release/Beta)の場合:** Release/Beta版は
     `xpinstall.signatures.required` を無視する仕様になっており、上記の
     方法では恒久インストールできません。次のいずれかが必要です:
     - Firefox Developer Edition・Nightly・ESRのいずれかを使う
       (これらは上記LibreWolfと同じ手順で恒久インストールできます)。
     - または、Mozillaの[Add-on Developer Hub](https://addons.mozilla.org/developers/)
       で自己配布用の署名(unlisted signing)を申請し、署名済み`.xpi`を
       作る(このパッケージ単体では完結しない、Mozilla側の手続きが必要な
       正規の方法です)。

   いずれの方法でも、`browser_specific_settings.gecko.id`
   (`fox-webusb@local`)は固定されているため、一時的インストールと
   恒久インストールを行き来しても、ネイティブメッセージングホスト側の
   許可設定(`allowed_extensions`)を変更する必要はありません。

4. ツールバーのfox-webusbアイコンを開き、「ネイティブホストに接続済み」と
   緑色で表示されれば準備完了です。`examples/quickstart.html` や
   `examples/compatibility_test.html` で動作確認できます。

## セキュリティモデル

WebUSBは仕様策定コミュニティ自身が「取り扱いに最も慎重を要するAPIの1つ」と
位置づけているAPIです。fox-webusbは、Chromiumの実装が採っている多層防御を
可能な限り踏襲しています(詳細は `native-host/src/fox_webusb_host/hardening.py`
冒頭のコメント):

- **保護対象インターフェースクラス**: Audio/HID/Mass Storage/Hub/Smart Card/
  Video/Audio-Video/Wireless Controllerの8クラスは `claimInterface()` 自体を
  拒否します。セキュリティキーやキーボードへの生アクセスを構造的に防ぎます。
- **既知セキュリティキーのブロックリスト**: Chromiumの `usb_blocklist.cc` から
  vendor_id/product_idの組を移植したデバイス単位の拒否リスト。
- **セキュアコンテキストのみ**: `https://`・`localhost`・`file://` 等でのみ動作
  (`window.isSecureContext` を確認)。
- **ユーザー操作からのみ `requestDevice()` を呼べる**: `navigator.userActivation`
  を確認。
- **オリジン単位の許可管理**: 一度 `requestDevice()` で選んだデバイスだけが、
  そのオリジンから `getDevices()`/`open()` できる。

### オリジンの検証(pyside6-webusbとの最大の違い)

pyside6-webusbは `QWebEnginePage.navigationRequested` を監視する自前の
`FrameOriginTracker` を実装し、JSへ「フレームトークン」を配って、それを
毎回一緒に送らせることで「どのフレームからの呼び出しか」を偽装防止していました。

fox-webusbではこの仕組みは丸ごと不要です。**Firefoxの拡張機能API自身が、
`browser.runtime.onMessage` のリスナーに渡される `sender.url`
という形で「実際にメッセージを送ってきたフレームの、ブラウザが検証済みのURL」
を無償で提供してくれる**ためです
(MDN: runtime.MessageSender、2026年8月時点で確認)。ページ側のJavaScriptは、
自分がどのオリジンにいるかを一切申告しません(申告する必要も、申告を受け取る
仕組みも存在しません)。`background.js` が `sender.url` から `origin` を求め、
それをネイティブホストへ渡す——これだけで、pyside6-webusb版と同等以上
(ページ側が改ざんする余地がそもそも存在しないという意味で、より単純かつ堅牢)
のオリジン分離が実現できています。

### 信頼済み専用の操作

「このオリジンの許可を取り消す」「既知デバイス履歴を消す」といった操作は、
Webページから呼べてはいけません(でなければ、悪意あるサイトが他のサイトの
許可を勝手に取り消せてしまいます)。`background.js` の `isTrustedSender()` は
`sender.url` が拡張機能自身のオリジン(`moz-extension://<id>/...`、
すなわちオプションページ)から始まっているかどうかで判定しており、
通常のWebページのcontent_script経由では到達できません。

## pyside6-webusb からの移植で変えたところ

| 項目 | pyside6-webusb (v0.0.4b1) | fox-webusb (v0.0.0a0) |
|---|---|---|
| トランスポート | QWebChannel | postMessage → 拡張機能メッセージング → Native Messaging |
| オリジン検証 | 自前のFrameOriginTracker(トークン発行) | `sender.url`(ブラウザが検証済み) |
| 設定の永続化 | QSettings | JSONファイル1個(`settings_store.py`) |
| デバイス選択UI | PySide6 QDialog | Tkinter(標準ライブラリのみ、追加依存なし) |
| 並行性モデル | Qtメインスレッド1本 + `processEvents()`での限定的な再入 | 本物のスレッドプール |
| 再入・競合対策 | `_busy_handles`(bulk転送のみが対象) | 全handle操作メソッドに一般化した per-handle ロック(`closeDevice`も含む) |
| 大容量転送のUI対策 | 256KiB単位のチャンク分割 + `processEvents()` | **意図的に不採用**(共有UIスレッドが存在せず、GILがブロッキングI/O中に解放されるため、単一の大きな`dev.read()`呼び出しでも他スレッドはブロックしない) |
| ホットプラグ通知の対象 | 現在のページのトップレベルオリジンのみ | 許可済みの**全オリジン・全フレーム**(タブ/フレームの登録簿による) |
| ネイティブメッセージングのサイズ制限対策 | (該当なし) | ホスト→拡張機能方向をbase64+チャンク分割(Firefoxの1MB上限対策。`protocol.py`) |
| Windows標準入出力のバイナリモード | (該当なし。Qt側がI/Oを扱うため無関係) | `ensure_binary_stdio()`で明示的に`O_BINARY`化(下記参照。v0.0.0a0で追加) |
| Rustアクセラレーション | `native/pyside6_webusb_accel/`(base64高速化・ADBフレーミングのテストヘルパー) | 同一ロジックをパッケージ名だけ変更してそのまま移植(元々Qt非依存だったため) |
| isochronous転送の実装詳細 | (非公開内部実装。今回未確認) | `dev.read()`/`dev.write()`を直接使うベストエフォート実装で代替(下記「未検証事項」参照) |

いずれの変更も、原則として「Firefoxの拡張機能アーキテクチャが持つ制約・
提供する保証に合わせて設計し直した」ものであり、思いつきの簡略化では
ありません。理由は各ファイルの該当箇所にコメントで残しています。

## 0.0.0a0: 実機検証(Windows/LibreWolf)で見つかった不具合と修正

v0.0.0は「実機・実Firefoxでの検証をしていない」状態でリリースしました。その後、
実際にWindows + LibreWolf(Firefox系ブラウザ)+ Python 3.14.4という環境で
動作検証していただき、その結果(`checklog.md`)を基に本バージョンで修正を
行いました。検証・報告に感謝します。

### 確認できたこと(検証レポートより)

拡張機能の読み込み、ネイティブメッセージングホストの登録・起動、
セキュアコンテキスト判定、オリジン報告、`navigator.usb`とその主要メソッド
(`getDevices()`・`requestDevice()`・イベントリスナー登録/解除)、
`getDevices()`のPromise→配列という挙動、**ユーザー操作なしでの`requestDevice()`
呼び出しが仕様どおり`SecurityError`で拒否されること**まで、想定どおり動作
していることが実機で確認できました。

### 見つかった不具合と修正

1. **`requestDevice()`実行中にネイティブホストが切断される(最重要)**

   WebADB(実際のWebUSB対応サイト)からの`requestDevice()`呼び出しが、
   `NetworkError: fox-webusb native host disconnected: disconnected` で
   失敗する不具合が報告されました。同時に、ネイティブホストを単独起動した
   際に `cannot read more than 33554432 bytes` という、フレーミングの
   破損を思わせるエラーも観測されています。

   **原因と判断したもの:** Windows上のPythonでは、`sys.stdin.buffer`/
   `sys.stdout.buffer`経由でバイト列を読み書きしていても、ファイル
   ディスクリプタ自体はWindows Cランタイム(msvcrt)レベルで既定の
   「テキストモード」のままになっていることがあります。これは
   Pythonの`io.TextIOWrapper`が行う改行変換(`.buffer`にアクセスすれば
   素通りできる話)とは別の、もう1段階下のモードです。テキストモードの
   ままだと、0x0D 0x0A の並びが黙って0x0Aへ書き換えられたり、0x1A
   (Ctrl-Z、伝統的なMS-DOSのEOFマーカー)に出会うとまだデータが続いて
   いてもストリーム終端とみなされたりします。fox-webusbが使う
   「4バイト長プレフィックス + 生バイト列」というプロトコルにとって、
   この破損は致命的です——小さいメッセージ(`getDevices()`等)はたまたま
   影響を受けない長さだったために動作し、あるメッセージ長で運悪くこれを
   踏むと、以降のフレーミングが丸ごとずれてしまう、という形で両方の
   観測結果が矛盾なく説明できます。

   **修正:** `protocol.py`に`ensure_binary_stdio()`を追加し、Windows上では
   起動直後に`msvcrt.setmode(fd, os.O_BINARY)`をstdin/stdout双方へ明示的に
   適用するようにしました(Chromeの公式ネイティブメッセージングサンプルでも
   使われている、Windows向けPython製ネイティブホストの標準的な対処です)。
   `__main__.py`は標準入出力に1バイトも触れる前にこれを呼びます。
   あわせて、`read_message()`が受け取る長さプレフィックスに現実的な上限
   (`MAX_INCOMING_MESSAGE_BYTES`, 128MiB)を設け、それを超える値は
   「本物の巨大なリクエスト」ではなく「フレーミング破損」とみなして、
   実際に読もうとする前に分かりやすいエラーとして早期に失敗するように
   しました。根本原因(バイナリモード未設定)への対処と、万一別の原因で
   同種の破損が起きた場合の安全網、の二段構えです。

2. **同一オリジンのiframeで`navigator.usb`が見えない**

   検証では、同一オリジンのiframe内で`navigator.usb`が存在しないという
   結果も報告されました(検証者自身も「意図した挙動か、注入の不具合か、
   他のiframe固有の条件かは切り分けられていない」と正直に記載しています)。

   **対応:** `manifest.json`の`content_scripts`設定で`match_about_blank`を
   `false`から`true`に変更しました。これは、`about:blank`/`about:srcdoc`
   として作られた後に`document.write()`等で内容を書き込むタイプのiframe
   (テストハーネスや一部のライブラリがよく使う軽量な手法)では、
   `match_about_blank: false`のままだとcontent_scriptがそもそも注入されない
   ためです。**ただし、これが実際の報告内容の根本原因だったかは検証環境の
   詳細が分からず断定できていません**——sandbox属性つきiframeで
   `allow-same-origin`が無い場合は、たとえ`src`が同一オリジンでも
   opaque-origin(nullオリジン)として扱われ、そもそもcontent_scriptの
   マッチ対象にならない、という(仕様どおりの)可能性も残っています。
   本バージョンでは「より広いケースを拾えるようにする」という前向きな
   修正に留め、次回以降の実機検証で再確認をお願いします。

3. **USB列挙(`usb.core.find()`)呼び出しの排他制御を追加**

   直接の不具合報告ではありませんが、上記1の原因調査の過程で、
   複数スレッド(リクエスト処理用ワーカースレッド・チューザーダイアログの
   ライブ更新タイマー)が同時に`usb.core.find()`を呼びうる設計になっている
   ことに気づきました。libusbバックエンドの初回ロードが複数スレッドから
   同時に走った場合の挙動は環境依存でありうるため、`bridge.py`に
   `_enumeration_lock`を追加し、USB列挙呼び出し全体を排他制御するように
   しました(列挙は頻度・処理時間ともに軽いため、直列化してもUSB転送本体の
   並行性には影響しません)。

4. **記述子解析の一部の例外を可視化**(移植元 v0.0.4b1 のruff指摘を踏襲)

   `hardening.py`の`build_configurations_tree`/`_device_interface_class_tuples`
   内で、記述子の一部が読めなかった際に完全に無言でスキップしていた箇所へ、
   `print(f"[fox-webusb-host] ...: 例外を無視: {e}")`という診断ログを追加
   しました。制御フロー(スキップして列挙を続ける)自体は変えていません。
   壊れた記述子を持つ実機での「一部のendpointだけが見えない」といった
   今後の調査を容易にするためのものです。

これらはいずれも、実機での動作報告があって初めて見つかった問題です。
サンドボックス環境での自動テストだけでは検出できなかったことを踏まえ、
何か気づいた点があれば同様の検証レポートをいただけると、今後の修正に
大いに役立ちます。

## 既知の限界・未検証事項

pyside6-webusb自身がそうであったように、このプロジェクトも「何がどこまで
確認できているか」を誠実に書きます。

- **F12 devtoolsでの深い型検証への耐性には意図的な範囲があります。**
  `instanceof EventTarget`・`Symbol.toStringTag`・`constructor.name`・
  `.prototype`の不在・非コンストラクタ化・`Function.prototype.toString()`
  ・メソッドの`.length`は対応しましたが、これらは「navigator.usbという
  オブジェクトの見た目」を本物のブラウザ実装に近づけるためのものであり、
  実際のセキュリティモデル(オリジン単位の許可・保護対象インターフェース
  クラスの拒否等)には一切影響しません。エンジン内部のスタックトレース
  書式やタイミング差といった、それ以上に踏み込んだフィンガープリンティング
  対策までは行っていません。このファイルがFirefox拡張機能の一部として
  動いているという事実そのものを隠す意図はなく、README/CHANGELOGには
  通常どおり移植の経緯を明記しています。

- **物理USBデバイスでの転送(open/claimInterface/transferIn等)は未検証です。**
  上記の実機検証(Windows/LibreWolf)では認可済みの物理デバイスが無く、
  `getDevices()`が空配列を返すところまでは確認できましたが、実際にデバイスを
  選択・オープンして転送を行う一連の流れは未確認のままです
  (`checklog.md`「15. Next Hardware Test」参照)。フェイクデバイス
  (`tests/fake_usb.py`)によるロジック検証、実サブプロセス越しの
  ネイティブメッセージング疎通確認(`tests/test_end_to_end_subprocess.py`)、
  Rust拡張の実ビルド・実importでの動作確認、Tkinterチューザーの仮想ディスプレイ
  (Xvfb)上での起動確認は行っていますが、実デバイスでの転送そのものは
  お手元での検証をお願いします。
- **isochronous転送はベストエフォート実装です。** 移植元の低レベル実装の
  詳細(どのpyusb/libusb内部APIを直接叩いていたか)をこの移植では確認
  できなかったため、`dev.read()`/`dev.write()`をisochronousエンドポイントへ
  直接呼び出す形で代替しました。pyusbは公式にはisochronous転送の高レベルAPIを
  保証していないため、環境によっては動作しません(その場合はクラッシュせず
  `InvalidAccessError` を返します)。
- **同一VID/PIDの複数台接続は区別しません。** `openDevice()` はvendorId/
  productIdだけで実機を検索し、最初に見つかった1台を返します(シリアル番号
  までは見ません)。これは移植元から引き継いだ簡略化です。
- **ネイティブホストの起動にはFirefoxとは独立したPythonプロセスが必要です。**
  拡張機能をインストールしただけでは動きません(README「インストール」参照)。
- **isTrustedSender の判定基準について。** `sender.url` が
  `moz-extension://<own-id>/` で始まるかどうかで判定しています。拡張機能自身の
  プロセス完全性が前提です(拡張機能自体が乗っ取られた場合の防御は範囲外——
  これは他のあらゆる拡張機能・pyside6-webusb自身にも共通する前提です)。
- **同一オリジンiframeでの挙動は完全には切り分けられていません。** 上記
  「見つかった不具合と修正」2.を参照。`match_about_blank: true`への変更は
  行いましたが、報告された症状の根本原因が完全に特定できたわけではありません。

## ディレクトリ構成

```
fox-webusb/
├── extension/              Firefox拡張機能(WebExtension, Manifest V2)
│   ├── manifest.json
│   ├── background.js       ネイティブメッセージング接続・オリジン検証・イベント配送
│   ├── content_script.js   ページ ⇔ background.js の中継、polyfillの注入
│   ├── page_polyfill.js    navigator.usb 本体(ページのMAIN worldで動く)
│   ├── popup/               ツールバーポップアップ(接続状態の表示)
│   ├── options/              許可オリジン・既知デバイスの管理画面
│   └── icons/
├── native-host/             ネイティブメッセージングホスト(Pythonパッケージ)
│   ├── src/fox_webusb_host/
│   │   ├── bridge.py         WebUSBのセキュリティモデル本体
│   │   ├── hardening.py      保護対象クラス/ブロックリスト/フィルタ照合等の純粋ロジック
│   │   ├── errors.py         DOMException接頭辞ビルダー
│   │   ├── settings_store.py 許可・既知デバイスのJSON永続化
│   │   ├── chooser_dialog.py Tkinter製デバイス選択ダイアログ
│   │   ├── protocol.py       ネイティブメッセージングの生ワイヤ形式+チャンク分割
│   │   └── __main__.py       常駐プロセスのエントリポイント(スレッド配線)
│   ├── install.py / uninstall.py
│   └── native-manifest/      ネイティブメッセージングホストマニフェストのひな形
├── native/fox_webusb_accel/  オプショナルなRust拡張(base64高速化・ADBフレーミング)
├── dist/fox-webusb.xpi      恒久インストール用にzip化した拡張機能(README「インストール」参照)
├── types/webusb-polyfill.d.ts  navigator.usb の型定義(Chrome版と共通の形状)
├── examples/                動作確認用のHTMLページ
└── tests/                   pytest(Python) + Node(page_polyfill.js)の自動テスト
```

## テスト

```bash
# Python側 (bridge.py / hardening.py / errors.py / settings_store.py / protocol.py
#  + 実サブプロセス越しの疎通確認、計93件)
cd native-host && pip install -e . --break-system-packages
pip install pyusb pytest --break-system-packages
cd .. && python3 -m pytest tests/ -v

# page_polyfill.js (window/navigator/postMessageをNodeでモックした機能テスト、37件)
node tests/test_page_polyfill.js

# Rustアクセラレーション(素のRustロジック層、13件)
cd native/fox_webusb_accel && cargo test --release

# 型定義 (.d.ts が正しい使い方を受理し、誤った使い方を型エラーとして拒否することの確認)
cd types && npx tsc --noEmit --strict --lib es2020,dom webusb-polyfill.d.ts sample-usage.ts negative-check.ts
```

いずれも実USBデバイス・実Firefoxを必要としない、ロジック単体の検証です
(前述「既知の限界」参照)。

## ライセンス

MIT。`LICENSE` 参照。移植元 pyside6-webusb と同一ライセンス。
