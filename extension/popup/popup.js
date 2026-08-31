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

  function render(status, diag) {
    if (status && status.nativeAvailable) {
      statusEl.className = 'status ok';
      statusEl.innerHTML = '<span class="dot"></span>ネイティブホストに接続済み';
      if (diag && diag.success) {
        var lines = [];
        lines.push('<div class="row"><span class="k">現在見えているUSBデバイス数</span><span>' + diag.deviceCount + '</span></div>');
        lines.push('<div class="row"><span class="k">Rustアクセラレーション</span><span>' + (diag.rustAccel ? '有効' : '未ビルド(標準base64で動作中)') + '</span></div>');
        detailEl.innerHTML = lines.join('');
      } else {
        detailEl.textContent = '';
      }
    } else {
      statusEl.className = 'status bad';
      statusEl.innerHTML = '<span class="dot"></span>ネイティブホストに接続できません';
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
