/*
 * options.js
 * ==========
 * このページは moz-extension://<id>/options/options.html から実行されるため、
 * background.js の isTrustedSender() が真になり、listGrantedOrigins /
 * revokeOriginGrant / revokeAllForOrigin / listKnownDevices /
 * forgetKnownDevice / forgetAllKnownDevices といった「信頼済み専用」
 * メソッドを呼べる(これらは通常のWebページのcontent_script経由では
 * 絶対に呼べない——background.js側のisTrustedSender()を参照)。
 *
 * i18n: 静的な文言はoptions.html側の data-i18n 属性 + 下の
 * applyStaticI18n() で埋める。動的に組み立てる文言(ステータス・テーブルの
 * 見出し・ボタン等)はここで直接 browser.i18n.getMessage() を呼ぶ。
 * _locales/{ja,en,zh_CN}/messages.json 参照。
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

  function clearChildren(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

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

  function loadFailedElement(e) {
    // 🛡️ web-ext lint(UNSAFE_VAR_ASSIGNMENT)対応: 以前はp.outerHTMLで
    // 文字列化したものをcontainer.innerHTMLへ代入していた。textContent→
    // outerHTMLの往復自体はエスケープされるため実際には安全だったが、
    // 実DOM要素をそのままappendChildする形の方が、将来この関数の使われ方が
    // 変わってもinnerHTMLインジェクションのリスクが原理的に生じない。
    var msg = browser.i18n.getMessage('loadFailedMessage', [String(e)]);
    var p = document.createElement('p');
    p.className = 'empty';
    p.textContent = msg;
    return p;
  }

  function renderStatus() {
    var dot = document.getElementById('statusDot');
    var text = document.getElementById('statusText');
    var detail = document.getElementById('statusDetail');
    call('getStatus').then(function (status) {
      if (status && status.nativeAvailable) {
        dot.className = 'dot ok';
        text.textContent = browser.i18n.getMessage('statusConnected');
        detail.textContent = '';
      } else {
        dot.className = 'dot bad';
        text.textContent = browser.i18n.getMessage('statusNotConnected');
        detail.textContent = (status && status.lastNativeError) || browser.i18n.getMessage('statusNotConnectedDetailSetup');
      }
    }).catch(function (e) {
      dot.className = 'dot bad';
      text.textContent = browser.i18n.getMessage('statusUnavailable');
      detail.textContent = String(e);
    });
  }

  function renderOrigins() {
    var container = document.getElementById('origins');
    container.textContent = browser.i18n.getMessage('loadingMessage');
    call('listGrantedOrigins').then(function (res) {
      container.innerHTML = '';
      var origins = (res && res.origins) || {};
      var keys = Object.keys(origins);
      if (!keys.length) {
        var emptyP = document.createElement('p');
        emptyP.className = 'empty';
        emptyP.textContent = browser.i18n.getMessage('noOriginsMessage');
        container.appendChild(emptyP);
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
          btn.textContent = browser.i18n.getMessage('buttonRevoke');
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
        revokeAllBtn.textContent = browser.i18n.getMessage('buttonRevokeAllForOrigin');
        revokeAllBtn.addEventListener('click', function () {
          call('revokeAllForOrigin', { origin: origin }).then(renderOrigins);
        });
        block.appendChild(revokeAllBtn);

        container.appendChild(block);
      });
    }).catch(function (e) {
      clearChildren(container);
      container.appendChild(loadFailedElement(e));
    });
  }

  function renderKnownDevices() {
    var container = document.getElementById('knownDevices');
    container.textContent = browser.i18n.getMessage('loadingMessage');
    call('listKnownDevices').then(function (res) {
      var devices = (res && res.devices) || [];
      if (!devices.length) {
        var emptyP = document.createElement('p');
        emptyP.className = 'empty';
        emptyP.textContent = browser.i18n.getMessage('noKnownDevicesMessage');
        container.innerHTML = '';
        container.appendChild(emptyP);
        return;
      }
      var table = document.createElement('table');
      var thead = document.createElement('thead');
      var headRow = document.createElement('tr');
      ['tableHeaderDevice', 'tableHeaderVidPid', 'tableHeaderConnectCount', 'tableHeaderLastConnected', null].forEach(function (key) {
        var th = document.createElement('th');
        if (key) th.textContent = browser.i18n.getMessage(key);
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);
      var tbody = document.createElement('tbody');
      devices.sort(function (a, b) { return (b.lastConnected || 0) - (a.lastConnected || 0); });
      devices.forEach(function (d) {
        var tr = document.createElement('tr');
        var tdName = document.createElement('td');
        tdName.textContent = d.productName || browser.i18n.getMessage('unknownDeviceName');
        var tdVidPid = document.createElement('td');
        tdVidPid.textContent = vidPid(d.vendorId, d.productId);
        var tdCount = document.createElement('td');
        tdCount.textContent = String(d.connectCount || 0);
        var tdDate = document.createElement('td');
        tdDate.textContent = fmtDate(d.lastConnected);
        var tdAction = document.createElement('td');
        var btn = document.createElement('button');
        btn.textContent = browser.i18n.getMessage('buttonForgetDevice');
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
      clearChildren(container);
      container.appendChild(loadFailedElement(e));
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
