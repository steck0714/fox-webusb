/*
 * content_script.js
 * ==================
 * 各フレーム(all_frames:trueなので、メインフレームだけでなく全iframeにも)
 * document_start で注入される。isolated world(拡張機能専用のJS実行環境。
 * ページ自身のJSからは触れない)で動く、page_polyfill.js とbackground.jsの
 * 間の中継役。
 *
 * オリジンの扱いについて(README「オリジンの検証」も参照):
 *   このスクリプト自身はorigin文字列をどこにも送らない。background.jsは
 *   browser.runtime.onMessageのsender.url(このcontent_scriptが実際に
 *   動いている、ブラウザ自身が把握しているフレームのURL——ページ側JSが
 *   postMessageのdataに何を積んでも書き換えられない値)からoriginを
 *   導出する。これが移植元のFrameOriginTracker(QWebEnginePage.
 *   navigationRequestedを監視する自前のトークン発行機構)を丸ごと
 *   置き換えている部分であり、Firefoxの拡張機能APIが標準で提供する
 *   sender.urlの検証済み性質のおかげで、fox-webusb側で追加のトークン
 *   機構を実装する必要が無くなっている。
 */
(function () {
  'use strict';
  var CHANNEL = '__foxWebusb__';

  // 🛡️ v0.0.0a1(独立したセキュリティ監査を受けて):
  // page_polyfill.js自身のnavigator.userActivation.isActiveチェックは
  // ページのMAIN worldで動いているため、ページ自身のJSが直接
  // window.postMessage()でtoContent/callメッセージを偽造すれば、
  // page_polyfill.jsのrequestDevice()を一度も呼ばずにこのcontent_script
  // (延いてはbackground.js・ネイティブホスト)へ到達できてしまい、
  // ユーザー操作なしでチューザーダイアログを開けてしまっていた。
  //
  // このcontent_script自身はisolated worldで動いており、documentへ
  // capturing listener(第3引数true。ページ側がstopPropagation()しても
  // 必ず先に自分が受け取れる)を張ってevent.isTrustedを直接観測できる。
  // isTrustedは合成(dispatchEvent()で生成された)イベントでは絶対に
  // trueにならない、ブラウザ自身が保証する性質なので、ページ側のJSには
  // これを偽装する手段が無い。HTML仕様の「activation triggering input
  // event」の正確な定義を全て再現しているわけではないが(例えば
  // pointerTypeによる除外等は見ていない)、click/keydown/pointerdown/
  // touchstartという代表的な実操作をここで直接見ることで、実用上
  // 十分な精度で「本物の直近の操作」を判定できる。
  var GESTURE_WINDOW_MS = 5000; // pyside6-webusb版のmintGestureToken()と揃えた保守的な値
  var _lastTrustedGestureAt = 0;
  ['click', 'keydown', 'pointerdown', 'touchstart'].forEach(function (type) {
    document.addEventListener(type, function (event) {
      if (event.isTrusted) _lastTrustedGestureAt = Date.now();
    }, true);
  });
  function _hasRecentTrustedGesture() {
    return (Date.now() - _lastTrustedGestureAt) < GESTURE_WINDOW_MS;
  }

  // background.js側のフレーム登録簿(ホットプラグイベントの配送先を
  // 決めるためのもの)へ、このフレームの存在を伝える。origin自体は
  // background.js が sender.url から自分で求めるので、ここでは何も
  // 付け足さずに「登録して」とだけ伝えれば十分。
  try {
    browser.runtime.sendMessage({ __foxWebusbRegister: true }).catch(function () {});
  } catch (e) { /* 拡張機能コンテキストが既に無効化されている等、稀なケース */ }

  window.addEventListener('pagehide', function () {
    try { browser.runtime.sendMessage({ __foxWebusbUnregister: true }).catch(function () {}); } catch (e) {}
  });

  // ページ(MAIN world)の page_polyfill.js からの呼び出しをbackground.jsへ中継する
  window.addEventListener('message', function (event) {
    if (event.source !== window) return;
    var data = event.data;
    if (!data || data.channel !== CHANNEL || data.dir !== 'toContent' || data.kind !== 'call') return;

    // 🛡️ hasGestureはdataから読むのではなく、必ずこのスクリプト自身が
    // 独立に計算し直す。ページがdata.hasGesture=trueを偽って積んできても
    // ここでは一切参照しないので意味を持たない。
    browser.runtime.sendMessage({
      __foxWebusbCall: true, method: data.method, params: data.params,
      hasGesture: _hasRecentTrustedGesture(),
      // 🌐 チューザーダイアログ(Tkinter)の表示言語選びにだけ使う、Firefox
      // 自体のUI言語(ページ自身のnavigator.languageではない——認可判定には
      // 一切使わない、表示上の好みでしかないことに注意。i18n.py参照)。
      locale: browser.i18n.getUILanguage(),
    })
      .then(function (result) {
        window.postMessage({ channel: CHANNEL, dir: 'toPage', kind: 'response', id: data.id, result: result }, window.location.origin);
      })
      .catch(function (err) {
        window.postMessage({
          channel: CHANNEL, dir: 'toPage', kind: 'response', id: data.id,
          result: { success: false, error: 'NetworkError: ' + (err && err.message ? err.message : String(err)) },
        }, window.location.origin);
      });
  });

  // background.jsが能動的に送ってくるconnect/disconnectイベントをページへ中継する。
  // (これはこのcontent_script自身が送ったsendMessage呼び出しへの「応答」ではなく、
  // background.js側から browser.tabs.sendMessage() で能動的に送られてくる、
  // 独立したメッセージであることに注意——onMessageリスナーはそちらだけを拾う)
  browser.runtime.onMessage.addListener(function (message) {
    if (message && message.__foxWebusbPush) {
      window.postMessage({
        channel: CHANNEL, dir: 'toPage', kind: 'event',
        event: message.event, device: message.device,
      }, window.location.origin);
    }
  });

  // webusb_core.js → page_polyfill.js の順で、実際のページのJS実行コンテキスト
  // (MAIN world)へ注入する。インラインスクリプトではなく拡張機能がホストする
  // 外部ファイルへのsrc参照にしているのは、ページ自身の厳しい
  // Content-Security-Policyでインラインscriptがブロックされるサイトでも
  // 動くようにするため(moz-extension://からのサブリソース読み込みはページの
  // CSPの対象外)。
  // 🛡️ v0.0.0a1: page_polyfill.js自体がwebusb_core.js(navigator.usbの
  // クラス群を定義する共有コア。README「二重サーフェス」参照)へ依存する
  // ようになったため、2つのscriptを直列に(1つ目のonloadを待ってから2つ目を
  // 注入する形で)読み込む。同じMAIN worldへ注入するので、1つ目が定義した
  // グローバル(FoxWebusbCore)を2つ目がそのまま参照できる。
  function injectScript(filename, onDone) {
    try {
      var script = document.createElement('script');
      script.src = browser.runtime.getURL(filename);
      script.onload = function () { this.remove(); if (onDone) onDone(); };
      script.onerror = function () { this.remove(); };
      (document.head || document.documentElement).appendChild(script);
    } catch (e) { /* about: ページ等、注入できない特殊なドキュメントは静かに諦める */ }
  }
  injectScript('webusb_core.js', function () {
    injectScript('page_polyfill.js');
  });
})();
