/*
 * page_polyfill.js
 * ================
 * navigator.usb (WebUSB) のポリフィル、Chromium surface側。
 * content_script.js によって、ページ自身のJS実行コンテキスト(MAIN world)に
 * <script src="..."> として注入される。webusb_core.js が先に同じ
 * MAIN worldへ注入されている前提(README「二重サーフェス」参照)。
 *
 * 移植元: pyside6-webusb (v0.0.4b1) の polyfill.py 内 WEBUSB_POLYFILL_JS。
 * navigator.usbのオブジェクトモデル・エラー変換自体は webusb_core.js
 * (両サーフェス共有)に切り出したので、このファイルに残るのは
 * (1) window.postMessage() を使ったトランスポート、
 * (2) navigator.usb への取り付け方(既存実装への配慮・改ざん耐性)
 * の2つだけである。
 *
 * ============================================================
 * v0.0.0a0: devtoolsでの深い型検証への耐性について
 * ============================================================
 * 実際にF12でnavigator.usbを調べた方から、「'usb' in navigator のような
 * 通常の機能検出は自然に通るが、instanceof EventTarget・
 * Symbol.toStringTag・constructor.name まで掘ると独自実装だと分かる」
 * というフィードバックをいただいた。クラス自体の改ざん耐性
 * (class構文・プライベートフィールド・Symbol.toStringTag・
 * Function.prototype.toString()対策)はwebusb_core.js側で行っている。
 * このファイルの役目は、その結果できあがったnavigator.usbオブジェクト
 * "自体"をどう取り付けるか、という一段外側の話である。
 */
(function () {
  'use strict';

  // 既に注入済み、または既にnavigator.usbが存在する(公式にWebUSBを実装した
  // Firefox、他の拡張機能が既に提供している、等)場合は何もせず道を譲る。
  if (window.__foxWebusbInjected) return;
  if (navigator.usb) return;
  // WebUSB仕様: セキュアコンテキストでのみ利用可能(https/localhost/file://等)。
  if (typeof window.isSecureContext !== 'undefined' && !window.isSecureContext) return;
  if (typeof window.FoxWebusbCore === 'undefined') return; // webusb_core.jsの注入に失敗した場合の保険

  // 🛡️ v0.0.0a1(現行WebUSB仕様[2026年9月時点]との突き合わせで追加):
  // Permissions Policyの`usb`機能。実仕様は`navigator.usb`自体を、
  // Permissions-Policy HTTPレスポンスヘッダーおよび<iframe allow="usb">
  // 属性が許可している文脈にしか公開しない——既定のallowlistは'self'なので、
  // 親ページが明示的に委譲していないクロスオリジンiframeには、そもそも
  // navigator.usbというプロパティ自体が存在しない(個々のデバイスへの
  // 許可の話ですらなく、そのフレームでWebUSB機能自体が有効かどうかという、
  // より手前の話)。これは`usb-unrestricted`とは正反対の、ページ自身が
  // 「このフレームではWebUSBを一切使わせない」と宣言できる、防御を強める
  // 側の仕組みである。
  // document.permissionsPolicyはまだ全ブラウザに実装されているわけではない
  // 実験的なAPIなので、存在しない場合は何も制限せず(=このAPIが無かった
  // これまでの挙動のまま)進む——安全側に倒すとしても、実装されていない
  // ブラウザでWebUSB自体が使えなくなるのは望ましくないため。
  if (typeof document !== 'undefined' && document.permissionsPolicy &&
      typeof document.permissionsPolicy.allowsFeature === 'function') {
    try {
      if (!document.permissionsPolicy.allowsFeature('usb')) return;
    } catch (e) { /* 'usb'を未知の機能名として例外を投げる実装もあり得るので、その場合は制限せず進む */ }
  }

  window.__foxWebusbInjected = true;

  var CHANNEL = '__foxWebusb__';
  var _pending = Object.create(null);
  var _nextId = 1;

  function _onWindowMessage(event) {
    if (event.source !== window) return;
    var data = event.data;
    if (!data || data.channel !== CHANNEL || data.dir !== 'toPage') return;

    if (data.kind === 'response') {
      var resolve = _pending[data.id];
      if (resolve) {
        delete _pending[data.id];
        resolve(data.result);
      }
      return;
    }
    if (data.kind === 'event') {
      core.dispatchConnectionEvent(data.event, data.device);
    }
  }
  window.addEventListener('message', _onWindowMessage);

  function callBridge(method, params) {
    return new Promise(function (resolve) {
      var id = 'p' + (_nextId++);
      _pending[id] = resolve;
      window.postMessage({
        channel: CHANNEL, dir: 'toContent', kind: 'call',
        id: id, method: method, params: params || {},
      }, window.location.origin);
    });
  }

  // 🦊 fox-webusb固有の注記: directionビット(0x80)はcombineRequestType()
  // (webusb_core.js内)では合成しない。controlTransferIn/Outどちらを
  // 呼んだかでホスト側(bridge.py)が強制的に付け外しするため、JS側が
  // directionビットを間違って送っても実際の転送方向には影響しない
  // (bridge.py冒頭のコメント参照)。

  var core = window.FoxWebusbCore.create(callBridge, { requestDeviceNeedsGesture: true });

  // ============================================================
  // navigator.usb への取り付け
  // ============================================================
  // 🛡️ v0.0.0a1: 以前は{ writable: false, configurable: true }で定義して
  // いたため、`delete navigator.usb` がそのまま成功してしまっていた
  // (configurable:trueなプロパティは常にdelete可能——これはJS言語仕様
  // そのものであり、ブラウザによる違いではない)。ページのJSが
  // navigator.usbを一度消してから自前の偽物を差し込む、という
  // なりすまし攻撃を防ぐため、configurable: false に変更した——これにより
  // `delete navigator.usb` は(非strictモードでは黙って)falseを返し、
  // 実際には削除されない。実ブラウザのnavigator上のAPIの多くも同様に
  // configurable:falseである。
  //
  // ただし、これはあくまで「一度取り付けたら壊されない」ためのもので
  // あって、「先に何かがnavigator.usbを提供していたら絶対に上書きしない」
  // という判断(ファイル冒頭の `if (navigator.usb) return;`)の方が先に
  // 効く。実装順序は:
  //   1. 既にnavigator.usbがあるか(公式実装・他の拡張機能)を確認 → あれば
  //      何もせず即return(このファイルの冒頭)。
  //   2. 無ければ、ここで初めて自分のものをconfigurable:falseで定義する。
  // この2段構えにより、「後から本物のFirefox実装や他のWebUSB拡張機能が
  // 現れたら道を譲り、いったん自分が居座ったら生半可なページJSからは
  // 消されない」という、ユーザーの意図どおりの優先順位になる。
  try {
    Object.defineProperty(navigator, 'usb', {
      value: core.usb, writable: false, configurable: false, enumerable: true,
    });
  } catch (e) {
    // 🛡️ 別のスクリプトが既にnavigator.usbをconfigurable:falseで
    // defineしていて再定義できない場合、静かに諦める(navigator.usbが
    // 存在しない元々の状態のままになるだけで、ページの他の動作を
    // 壊さない)。
  }

  // ============================================================
  // window.__foxWebUSB — F12/DevTools向けデバッグヘルパー
  // ============================================================
  // 🛡️ pyside6-webusb版のwindow.__pysideWebUSBと同じ設計方針: ここに置くのは
  // 「navigator.usb経由で呼び出し元オリジンが既に見られる情報を見やすく
  // 整形しただけのもの」と「navigator.usb自体には無い、この実装固有の
  // メタ情報(バージョン等)」だけに限定する。他オリジンの許可状況のような
  // 機微情報は絶対に含めない——page_polyfill.jsはMAIN world(=ページ自身の
  // JSと同じ実行コンテキスト)へ注入されるため、ここに書いたものは事実上
  // どのWebページからも(DevTools越しの人間だけでなく、そのページ自身の
  // スクリプトからも)見える。
  window.__foxWebUSB = {
    // 呼び出し元オリジンが既に許可済みのデバイス一覧を、DevTools上で
    // console.table()を使って見やすく表示するショートカット。中身は
    // navigator.usb.getDevices()と完全に同じデータ(=追加の情報開示は無い)。
    listGrantedDevices: function () {
      return core.usb.getDevices().then(function (devices) {
        var rows = devices.map(function (d) {
          return {
            vendorId: '0x' + d.vendorId.toString(16),
            productId: '0x' + d.productId.toString(16),
            productName: d.productName,
            manufacturerName: d.manufacturerName,
            serialNumber: d.serialNumber,
            opened: d.opened,
          };
        });
        if (typeof console !== 'undefined' && console.table) console.table(rows);
        return rows;
      });
    },

    // 🦊 独自拡張(実Chromeのnavigator.usbには相当機能が無い): このブリッジ
    // 自体のバージョン・Rustアクセラレーションが実際に効いているか・
    // 転送サイズの上限方針。ご依頼の「バージョンチェック用のF12」はこれ
    // ——F12でDevToolsコンソールを開き、`__foxWebUSB.bridgeInfo()` と
    // 打つだけで、今ページに効いているfox-webusbのバージョンを確認できる。
    bridgeInfo: function () {
      return core.isAvailable().then(function (res) {
        if (typeof console !== 'undefined' && console.log) {
          console.log('[fox-webusb] bridge info:', res);
        }
        return res;
      });
    },

    // 🦊 独自拡張: 転送サイズの上限方針をDevTools上で説明する。
    explainTransferLimits: function () {
      return core.isAvailable().then(function (res) {
        var limits = res.transferLimits || {};
        var msg = '[fox-webusb] Transfer size policy: bulk/interrupt transfers up to ' +
          limits.bulkTransferMaxLength + ' bytes and control transfers up to ' +
          limits.controlTransferMaxLength + ' bytes are allowed here. See the fox-webusb ' +
          'README/CHANGELOG for the full reasoning behind these limits.';
        if (typeof console !== 'undefined' && console.log) console.log(msg);
        return limits;
      });
    },

    // ============================================================
    // extensions — mock-webusb系列(pyside6-webusb/tauri-webusb/
    // fox-webusb)だけが持つ、サイト自身のJSからも直接使ってよい機能。
    // ============================================================
    // 🛡️ 上のlistGrantedDevices/bridgeInfo/explainTransferLimitsとの違い:
    // あちらはあくまで「人間がF12コンソールから叩く」ことを想定した、
    // 形式が変わってもよい簡易ヘルパー。こちらの`extensions`配下は、
    // サイト自身のコード(devtoolsを介さない、通常のJavaScript)が機能検出
    // (`if (window.__foxWebUSB && window.__foxWebUSB.extensions.attestation)`)
    // した上で組み込んでよい、安定したAPIとして提供する。実Chromeの
    // navigator.usbには存在しない機能なので、実装しているかどうかを
    // 必ず機能検出してから使うこと——本物のChrome上ではwindow.__foxWebUSB
    // 自体が存在しない。
    extensions: {
      // ローカルアテステーション(Ed25519署名、attestation.py参照)。
      // 使い方の例:
      //   // 初回訪問時:
      //   const pub = await window.__foxWebUSB.extensions.attestation.getPublicKey();
      //   saveToMyBackend(pub); // 例: Base64化してユーザーアカウントに保存
      //   // 以降の訪問時:
      //   const challenge = crypto.getRandomValues(new Uint8Array(32));
      //   const sig = await window.__foxWebUSB.extensions.attestation.sign(challenge);
      //   // challenge・sig をサーバーへ送り、保存しておいた公開鍵で検証する
      //   // (Ed25519の検証自体はNode.js/Web Crypto等、サーバー側の好きな
      //   // 実装で行える——鍵形式はRFC 8032の生バイト列そのもの)。
      attestation: core.attestation,
    },
  };
})();
