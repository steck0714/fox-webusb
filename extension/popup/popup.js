/*
 * popup.js
 * ========
 * ツールバーアイコンのポップアップ。「ネイティブホストと繋がっているか」を
 * 常に真っ先に見せる——これが繋がっていない限りfox-webusbは何もできないため、
 * ユーザーが最初に気にすべき情報はこれだと考えた。
 */
(function () {
  'use strict';

  var statusEl = document.getElementById('status');
  var detailEl = document.getElementById('detail');

  function clearElement(el) {
    while (el.firstChild) {
      el.removeChild(el.firstChild);
    }
  }

  // <span class="dot"></span> + テキスト、という以前のinnerHTML代入と
  // 同じDOM構造を、安全なDOM APIだけで組み立てる。
  function setStatusLine(el, text) {
    clearElement(el);
    var dot = document.createElement('span');
    dot.className = 'dot';
    el.appendChild(dot);
    el.appendChild(document.createTextNode(text));
  }

  function createDetailRow(label, value) {
    var row = document.createElement('div');
    row.className = 'row';
    var k = document.createElement('span');
    k.className = 'k';
    k.textContent = label;
    var v = document.createElement('span');
    v.textContent = value;
    row.appendChild(k);
    row.appendChild(v);
    return row;
  }

  function render(status, diag) {
    if (status && status.nativeAvailable) {
      statusEl.className = 'status ok';
      setStatusLine(statusEl, 'ネイティブホストに接続済み');
      if (diag && diag.success) {
        clearElement(detailEl);
        detailEl.appendChild(createDetailRow('現在見えているUSBデバイス数', String(diag.deviceCount)));
        detailEl.appendChild(createDetailRow('Rustアクセラレーション', diag.rustAccel ? '有効' : '未ビルド(標準base64で動作中)'));
      } else {
        detailEl.textContent = '';
      }
    } else {
      statusEl.className = 'status bad';
      setStatusLine(statusEl, 'ネイティブホストに接続できません');
      detailEl.textContent = (status && status.lastNativeError) ||
        'fox-webusb-host がインストールされていない可能性があります。オプションページの手順を確認してください。';
    }
  }

  function refresh() {
    statusEl.className = 'status';
    statusEl.textContent = '確認中…';
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
