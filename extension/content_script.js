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

    browser.runtime.sendMessage({ __foxWebusbCall: true, method: data.method, params: data.params })
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

  // page_polyfill.js を実際のページのJS実行コンテキスト(MAIN world)へ注入する。
  // インラインスクリプトではなく拡張機能がホストする外部ファイルへのsrc参照に
  // しているのは、ページ自身の厳しいContent-Security-Policyでインラインscriptが
  // ブロックされるサイトでも動くようにするため(moz-extension://からの
  // サブリソース読み込みはページのCSPの対象外)。
  try {
    var script = document.createElement('script');
    script.src = browser.runtime.getURL('page_polyfill.js');
    script.onload = function () { this.remove(); };
    (document.head || document.documentElement).appendChild(script);
  } catch (e) { /* about: ページ等、注入できない特殊なドキュメントは静かに諦める */ }
})();
