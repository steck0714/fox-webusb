/*
 * options.js
 * ==========
 * このページは moz-extension://<id>/options/options.html から実行されるため、
 * background.js の isTrustedSender() が真になり、listGrantedOrigins /
 * revokeOriginGrant / revokeAllForOrigin / listKnownDevices /
 * forgetKnownDevice / forgetAllKnownDevices といった「信頼済み専用」
 * メソッドを呼べる(これらは通常のWebページのcontent_script経由では
 * 絶対に呼べない——background.js側のisTrustedSender()を参照)。
 */
(function () {
  'use strict';

  function call(method, params) {
    return browser.runtime.sendMessage({ __foxWebusbCall: true, method: method, params: params || {} });
  }

  function fmtDate(ts) {
    if (!ts) return '';
    try { return new Date(ts * 1000).toLocaleString(); } catch (e) { return ''; }
  }

  function vidPid(vendorId, productId) {
    var v = ('0000' + vendorId.toString(16)).slice(-4);
    var p = ('0000' + productId.toString(16)).slice(-4);
    return v + ':' + p;
  }

  function renderStatus() {
    var dot = document.getElementById('statusDot');
    var text = document.getElementById('statusText');
    var detail = document.getElementById('statusDetail');
    call('getStatus').then(function (status) {
      if (status && status.nativeAvailable) {
        dot.className = 'dot ok';
        text.textContent = 'ネイティブホストに接続済み';
        detail.textContent = '';
      } else {
        dot.className = 'dot bad';
        text.textContent = 'ネイティブホストに接続できていません';
        detail.textContent = (status && status.lastNativeError) || '下のセットアップ手順を確認してください。';
      }
    }).catch(function (e) {
      dot.className = 'dot bad';
      text.textContent = 'ステータスを取得できませんでした';
      detail.textContent = String(e);
    });
  }

  function renderOrigins() {
    var container = document.getElementById('origins');
    container.textContent = '読み込み中…';
    call('listGrantedOrigins').then(function (res) {
      container.innerHTML = '';
      var origins = (res && res.origins) || {};
      var keys = Object.keys(origins);
      if (!keys.length) {
        container.innerHTML = '<p class="empty">許可されたオリジンはまだありません。</p>';
        return;
      }
      keys.forEach(function (origin) {
        var block = document.createElement('div');
        block.className = 'origin-block card';

        var title = document.createElement('div');
        title.className = 'origin-title';
        title.textContent = origin;
        block.appendChild(title);

        var table = document.createElement('table');
        var tbody = document.createElement('tbody');
        (origins[origin] || []).forEach(function (grant) {
          var tr = document.createElement('tr');
          var tdDevice = document.createElement('td');
          tdDevice.textContent = vidPid(grant.vendorId, grant.productId);
          var tdDate = document.createElement('td');
          tdDate.textContent = fmtDate(grant.grantedAt);
          var tdAction = document.createElement('td');
          var btn = document.createElement('button');
          btn.className = 'danger';
          btn.textContent = '取り消す';
          btn.addEventListener('click', function () {
            call('revokeOriginGrant', { origin: origin, vendorId: grant.vendorId, productId: grant.productId })
              .then(renderOrigins);
          });
          tdAction.appendChild(btn);
          tr.appendChild(tdDevice); tr.appendChild(tdDate); tr.appendChild(tdAction);
          tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        block.appendChild(table);

        var revokeAllBtn = document.createElement('button');
        revokeAllBtn.className = 'danger';
        revokeAllBtn.style.marginTop = '8px';
        revokeAllBtn.textContent = 'このオリジンの許可を全て取り消す';
        revokeAllBtn.addEventListener('click', function () {
          call('revokeAllForOrigin', { origin: origin }).then(renderOrigins);
        });
        block.appendChild(revokeAllBtn);

        container.appendChild(block);
      });
    }).catch(function (e) {
      container.innerHTML = '<p class="empty">読み込みに失敗しました: ' + String(e) + '</p>';
    });
  }

  function renderKnownDevices() {
    var container = document.getElementById('knownDevices');
    container.textContent = '読み込み中…';
    call('listKnownDevices').then(function (res) {
      var devices = (res && res.devices) || [];
      if (!devices.length) {
        container.innerHTML = '<p class="empty">履歴はまだありません。</p>';
        return;
      }
      var table = document.createElement('table');
      var thead = document.createElement('thead');
      thead.innerHTML = '<tr><th>デバイス</th><th>VID:PID</th><th>接続回数</th><th>最終接続</th><th></th></tr>';
      var tbody = document.createElement('tbody');
      devices.sort(function (a, b) { return (b.lastConnected || 0) - (a.lastConnected || 0); });
      devices.forEach(function (d) {
        var tr = document.createElement('tr');
        var tdName = document.createElement('td');
        tdName.textContent = d.productName || '(不明なデバイス)';
        var tdVidPid = document.createElement('td');
        tdVidPid.textContent = vidPid(d.vendorId, d.productId);
        var tdCount = document.createElement('td');
        tdCount.textContent = String(d.connectCount || 0);
        var tdDate = document.createElement('td');
        tdDate.textContent = fmtDate(d.lastConnected);
        var tdAction = document.createElement('td');
        var btn = document.createElement('button');
        btn.textContent = '履歴から削除';
        btn.addEventListener('click', function () {
          call('forgetKnownDevice', { vendorId: d.vendorId, productId: d.productId }).then(renderKnownDevices);
        });
        tdAction.appendChild(btn);
        [tdName, tdVidPid, tdCount, tdDate, tdAction].forEach(function (td) { tr.appendChild(td); });
        tbody.appendChild(tr);
      });
      table.appendChild(thead);
      table.appendChild(tbody);
      container.innerHTML = '';
      container.appendChild(table);
    }).catch(function (e) {
      container.innerHTML = '<p class="empty">読み込みに失敗しました: ' + String(e) + '</p>';
    });
  }

  document.getElementById('refresh').addEventListener('click', function () {
    renderStatus(); renderOrigins(); renderKnownDevices();
  });
  document.getElementById('forgetAllKnown').addEventListener('click', function () {
    call('forgetAllKnownDevices').then(renderKnownDevices);
  });

  renderStatus();
  renderOrigins();
  renderKnownDevices();
})();
