/*
 * popup.js
 * ========
 * ツールバーアイコンのポップアップ。「ネイティブホストと繋がっているか」を
 * 常に真っ先に見せる——これが繋がっていない限りfox-webusbは何もできないため、
 * ユーザーが最初に気にすべき情報はこれだと考えた。
 *
 * i18n: 静的な文言はpopup.html側の data-i18n 属性 + 下の applyStaticI18n() で
 * 埋める。動的に組み立てる文言(ステータス等)はここで直接
 * browser.i18n.getMessage() を呼ぶ。_locales/{ja,en,zh_CN}/messages.json 参照。
 */
(function () {
  'use strict';

  function applyStaticI18n() {
    document.documentElement.lang = browser.i18n.getUILanguage();
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var msg = browser.i18n.getMessage(el.getAttribute('data-i18n'));
      if (msg) el.textContent = msg;
    });
  }
  applyStaticI18n();

  var statusEl = document.getElementById('status');
  var detailEl = document.getElementById('detail');

  function clearChildren(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function makeStatusContent(text) {
    // 🛡️ web-ext lint(UNSAFE_VAR_ASSIGNMENT)対応: 以前は
    // '<span class="dot"></span>' + text を innerHTML へ直接代入していた。
    // textはbrowser.i18n.getMessage()の戻り値なので実際には常に安全だが、
    // 将来この関数の呼び出し方が変わってもinnerHTMLインジェクションの
    // リスクが原理的に生じないよう、DOM APIだけで組み立てる形にした。
    var frag = document.createDocumentFragment();
    var dot = document.createElement('span');
    dot.className = 'dot';
    frag.appendChild(dot);
    frag.appendChild(document.createTextNode(text));
    return frag;
  }

  function makeDetailRow(labelText, valueText) {
    var row = document.createElement('div');
    row.className = 'row';
    var k = document.createElement('span');
    k.className = 'k';
    k.textContent = labelText;
    var v = document.createElement('span');
    v.textContent = String(valueText);
    row.appendChild(k);
    row.appendChild(v);
    return row;
  }

  function render(status, diag) {
    if (status && status.nativeAvailable) {
      statusEl.className = 'status ok';
      clearChildren(statusEl);
      statusEl.appendChild(makeStatusContent(browser.i18n.getMessage('statusConnected')));
      clearChildren(detailEl);
      if (diag && diag.success) {
        detailEl.appendChild(makeDetailRow(browser.i18n.getMessage('labelDeviceCount'), diag.deviceCount));
        detailEl.appendChild(makeDetailRow(
          browser.i18n.getMessage('labelRustAccel'),
          diag.rustAccel ? browser.i18n.getMessage('rustAccelEnabled') : browser.i18n.getMessage('rustAccelDisabled'),
        ));
      }
    } else {
      statusEl.className = 'status bad';
      clearChildren(statusEl);
      statusEl.appendChild(makeStatusContent(browser.i18n.getMessage('statusNotConnected')));
      detailEl.textContent = (status && status.lastNativeError) || browser.i18n.getMessage('statusNotConnectedDetailFallback');
    }
  }

  function refresh() {
    statusEl.className = 'status';
    statusEl.textContent = browser.i18n.getMessage('statusChecking');
    detailEl.textContent = '';
    browser.runtime.sendMessage({ __foxWebusbCall: true, method: 'getStatus', params: {} }).then(function (status) {
      if (status && status.nativeAvailable) {
        browser.runtime.sendMessage({ __foxWebusbCall: true, method: 'diagnostics', params: {} }).then(function (diag) {
          render(status, diag);
        }).catch(function () { render(status, null); });
      } else {
        render(status, null);
      }
    }).catch(function (e) {
      render({ nativeAvailable: false, lastNativeError: String(e) }, null);
    });
  }

  document.getElementById('openOptions').addEventListener('click', function () {
    browser.runtime.openOptionsPage();
  });
  document.getElementById('retry').addEventListener('click', refresh);

  refresh();
})();
