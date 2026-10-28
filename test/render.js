const { JSDOM } = require('jsdom');
(async () => {
  const base = 'http://127.0.0.1:8099/';
  // Since 5.19 the page is signed in by a cookie the relay sets (HttpOnly):
  // node's fetch keeps none, so the walk keeps the one it is given.
  let JAR = '';
  const jfetch = (url, opts) => {
    opts = Object.assign({}, opts || {});
    opts.headers = Object.assign({}, opts.headers || {});
    if (JAR) opts.headers['Cookie'] = JAR;
    return fetch(url, opts).then(r => {
      const set = r.headers.getSetCookie ? r.headers.getSetCookie() : [];
      set.forEach(c => { const m = /^zigmon_session=([^;]*)/.exec(c); if (m) JAR = m[1] ? 'zigmon_session=' + m[1] : ''; });
      return r;
    });
  };
  const signIn = async (name, password) => (await jfetch(base + 'index.php?api=login', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: name || 'admin', password: password || 'admin pass 1'})})).json();
  const html = await (await fetch(base + 'index.php')).text();
  const errors = [];
  const dom = new JSDOM(html, { url: base + 'index.php', runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true,
    beforeParse(window) {
      window.fetch = (url, opts) => jfetch(new URL(url, base).href, opts);
      window.confirm = () => true;
      window.addEventListener('error', e => errors.push(e.message));
      window.console.error = (...a) => errors.push(a.join(' '));
      Object.defineProperty(window.HTMLElement.prototype, 'clientWidth', { get() { return 600; } });
      Object.defineProperty(window.HTMLElement.prototype, 'clientHeight', { get() { return 240; } });
      Object.defineProperty(window.HTMLElement.prototype, 'offsetParent', { get() { return this.parentNode; } });
    }});
  const w = dom.window, d = w.document;
  // Settings are drawn beside the cards they belong to (4.67): every check
  // that looked in the one settings card looks in all of them.
  const SETQ = sel => d.querySelector('#settings-grid ' + sel) || d.querySelector('.set-host ' + sel);
  const SETQA = sel => Array.from(d.querySelectorAll('#settings-grid ' + sel)).concat(Array.from(d.querySelectorAll('.set-host ' + sel)));
  const wait = ms => new Promise(r => setTimeout(r, ms));
  await wait(1500);
  const txt = id => (d.getElementById(id) || {}).textContent;
  console.log('pill:', txt('pill-text'), '| devices:', txt('m-devices'), '| cards:', d.querySelectorAll('#device-cards .dev').length);
  console.log('ov-temp svg paths:', d.querySelectorAll('#ov-temp path').length, 'legend:', txt('ov-temp-legend'));
  // All values is the last section of Control since 4.69
  for (const tab of ['history','devices','events','control']) {
    d.querySelector('.tabs button[data-tab="'+tab+'"]').click();
    await wait(1200);
  }
  console.log('history charts:', d.querySelectorAll('#h-charts .card').length, '| note:', txt('h-note'));
  console.log('devices rows:', d.querySelectorAll('#devices-table tbody tr').length);
  console.log('events rows:', d.querySelectorAll('#events-table tbody tr').length);
  console.log('health rows:', d.querySelectorAll('#health-kv .kv').length);
  d.querySelector('.tabs button[data-tab="control"]').click(); w.showControlSection('sys-values'); await wait(1500);
  console.log('all cards:', d.querySelectorAll('#all-values .card').length);
  if (!d.querySelectorAll('#all-values .card').length) errors.push('All values drew nothing in Control');
  {
    // a repaint that changes nothing leaves the page alone: the All values
    // cards are kept, and the lock and the header write nothing a second time
    const keep = Array.from(d.querySelectorAll('#all-values .card'));
    w.renderAll(w.STATE.status);
    const again = Array.from(d.querySelectorAll('#all-values .card'));
    if (!keep.length || keep.length !== again.length || keep.some((c, i) => c !== again[i]))
      errors.push('All values built its cards again with nothing changed');
    w.renderLock(); w.renderOverview(w.STATE.status); await wait(30);
    const recs = [];
    const ob = new w.MutationObserver(r => recs.push(...r));
    ob.observe(d.body, {subtree: true, childList: true, attributes: true, characterData: true});
    w.renderLock(); w.renderLock(); w.renderOverview(w.STATE.status); w.renderOverview(w.STATE.status);
    await wait(30); ob.disconnect();
    const moved = recs.filter(r => { const n = r.target.nodeType === 1 ? r.target : r.target.parentElement;
      return !(n && n.closest && n.closest('#lockpill-text, #lock-state')); });
    if (moved.length) errors.push('redrawing the lock and the header with nothing changed rewrote ' + moved.length
      + ' thing(s): ' + moved.slice(0, 3).map(r => (r.target.id || r.target.className || r.target.nodeName) + ' ' + (r.attributeName || r.type)).join(', '));
    const lt = d.getElementById('lock-toggle');
    if (lt && lt.dataset.explains && !lt._explained) errors.push('the lock button is explained without its listeners being marked');
    // a wake that arrives while a status is being fetched rides on that fetch
    const wasBusy = w.STATE.busy; w.STATE.busy = true; w.STATE.pendingForce = false; w.wakeTick();
    if (!w.STATE.pendingForce) errors.push('a change announced during a fetch was not carried by it');
    w.STATE.busy = wasBusy; w.STATE.pendingForce = false;
  }
  // control: reset events with PIN flow
  d.querySelector('.tabs button[data-tab="control"]').click(); await wait(300);
  d.querySelector('[data-reset="events"]').click(); await wait(200);
  console.log('modal shown:', !d.getElementById('pinback').hidden);
  // since 5.19 a name and a password (5.19.1: one click from the PIN boxes, which come first where there is a PIN account)
  if (w.PIN && w.PIN.mode === 'pin') d.getElementById('pin-other-link').click();
  d.getElementById('signin-name').value = 'admin'; d.getElementById('signin-pass').value = 'admin pass 1';
  d.getElementById('pinok').click(); await wait(1200);
  console.log('toast:', txt('toast'));
  // hover a chart
  d.querySelector('.tabs button[data-tab="overview"]').click(); await wait(800);
  const c = d.getElementById('ov-temp');
  c.dispatchEvent(new w.MouseEvent('mousemove', {clientX: 300, clientY: 100, bubbles: true}));
  console.log('tip:', (c.querySelector('.tip')||{}).style && c.querySelector('.tip').style.display, (c.querySelector('.tip')||{}).textContent);
  // A rule dragged by its handle must survive the house reporting while the
  // pointer is down: the guard against redrawing under a drag knew only about
  // the cards, so in a busy house every drag was undone by the next report.
  try {
    const r2 = await signIn();
    if (r2 && r2.who) {
      w.signedInAs(r2.who); w.SIGS = {}; w.tick(true);
      d.querySelector('.tabs button[data-tab="control"]').click(); await wait(400);
      w.showControlSection('automation'); await wait(2500);
      const packs = Array.from(d.querySelectorAll('#rules-list .rule-pack'));
      if (packs.length > 1) {
        const a = packs[0], b = packs[1], parent = a.parentNode;
        const dt = {effectAllowed: '', setData() {}, getData() { return 'row'; }};
        a.querySelector('.rowgrab').dispatchEvent(new w.MouseEvent('mousedown', {bubbles: true}));
        a.dispatchEvent(Object.assign(new w.Event('dragstart', {bubbles: true}), {dataTransfer: dt}));
        // exactly what a report from the house does, and what used to rebuild
        // the list out from under the pointer
        w.SIGS = {}; w.tick(true); await wait(1800);
        if (!d.body.contains(a)) errors.push('the row being dragged was rebuilt out from under the pointer');
        b.dispatchEvent(Object.assign(new w.Event('dragover', {bubbles: true, cancelable: true}), {dataTransfer: dt}));
        const moved = Array.prototype.indexOf.call(parent.children, a)
                    > Array.prototype.indexOf.call(parent.children, b);
        a.dispatchEvent(new w.Event('dragend', {bubbles: true}));
        await wait(400);
        console.log('a rule dragged through a redraw moves:', moved);
        if (!moved) errors.push('a rule could not be dragged while the house was reporting');
      }
    }
  } catch (e) { errors.push('the drag check itself failed: ' + e.message); }

  // Every way in must lead somewhere, and everything meant for a section must
  // be reachable from it. A card filed under a section with no button, or a
  // tab with no panel, is invisible however right the code behind it is.
  try {
    const tabs = Array.from(d.querySelectorAll('.tabs button[data-tab]')).map(b => b.dataset.tab);
    const panels = Array.from(d.querySelectorAll('section.panel[id^="tab-"]')).map(s => s.id.slice(4));
    tabs.forEach(t => { if (panels.indexOf(t) < 0) errors.push('the ' + t + ' tab has no panel'); });
    panels.forEach(p => { if (tabs.indexOf(p) < 0) errors.push('the ' + p + ' panel has no tab button'); });
    const navSecs = Array.from(d.querySelectorAll('#control-nav button[data-sec]')).map(b => b.dataset.sec);
    const cardSecs = Array.from(d.querySelectorAll('#tab-control [data-sec]'))
      .filter(x => x.tagName !== 'BUTTON').map(x => x.dataset.sec);
    cardSecs.forEach(s2 => {
      if (navSecs.indexOf(s2) < 0) errors.push('a card is filed under "' + s2 + '", which has no button');
    });
    navSecs.forEach(s2 => {
      if (cardSecs.indexOf(s2) < 0) errors.push('the "' + s2 + '" button leads to nothing');
    });
    console.log('ways in: %d tab(s), %d section(s), all of them leading somewhere',
                tabs.length, navSecs.length);
  } catch (e) { errors.push('the reachability check itself failed: ' + e.message); }

  // Every column header against the rows it names. Two faults kept appearing
  // one editor at a time: a header without the indent its rows get for the
  // drag handle, so every name sits one notch left of its column; and a
  // header that inherits its row's rounded corners, which lifts the ends of
  // its underline off the line.
  try {
    // The gateways are only there to measure when one is configured, and a
    // check that says nothing when there are none is how their header was
    // wrong three times over. Plant one for the measurement and take it away.
    var plantedGateway = false;
    if (!d.querySelector('.gw-row:not(.gw-head)')) {
      var gwSave = await (await jfetch(base + 'index.php?api=gateways-save', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({pin: '1234', gateways: [{name: 'Measure-Me', host: '127.0.0.1', kind: 'slzb'}]})})).json();
      if (gwSave && gwSave.ok) { plantedGateway = true; w.SIGS = {}; w.tick(true); await wait(1500); }
      else errors.push('no gateway on the page and none could be planted to measure the header');
    }
    // Every card has to be drawn before its header can be measured - and the
    // page measures only the section on screen, on an animation frame jsdom
    // does not have. So each section is shown, then asked for its measurement
    // then and there, with the "nothing has changed since" memo cleared so
    // the ask is not passed over.
    for (var si = 0; si < Object.keys(w.CONTROL_SECTIONS).length; si++) {
      w.showControlSection(Object.keys(w.CONTROL_SECTIONS)[si]);
      await wait(1500);
      if (typeof w.markHeaderIndentNow === 'function') {
        w.markHeaderIndentNow.last = null;
        w.markHeaderIndentNow();
        await wait(60);
      }
    }
    await wait(800);
    var headTrouble = [];
    // Every column header on the page, measured the way the eye measures it:
    // the header stands above the folds and the boxes it names sit inside
    // them, so a fold's own inset moves the boxes and not the names. Some
    // editors fold their rows and some do not, and the header has to follow
    // whichever it is - calling the difference "the fold rather than a
    // misalignment" is how this was waved away twice.
    var headsSeen = 0;
    Array.prototype.forEach.call(d.querySelectorAll('[class*="-head"]'), function (head) {
      var kind = (String(head.className).match(/([a-z0-9]+)-head/) || [])[1];
      if (!kind) return;
      var card = head.closest('.card') || d;
      var rows = Array.prototype.filter.call(card.querySelectorAll('.' + kind + '-row'),
        function (x) { return !x.classList.contains(kind + '-head'); });
      if (!rows.length) return;
      var reach = function (node) {
        var total = 0;
        while (node && node !== card) {
          total += parseFloat(w.getComputedStyle(node).paddingLeft) || 0;
          node = node.parentElement;
        }
        return total;
      };
      headsSeen++;
      // every row, not the first: the gateways mix rows from config.json,
      // which cannot be dragged, with rows made on the page, which can, and
      // a header can only line up with all of them if they agree
      var nameAt = reach(head);
      var offRows = rows.map(function (row) { return reach(row); })
        .filter(function (at) { return at !== nameAt; });
      if (offRows.length) {
        headTrouble.push(kind + ': the names start at ' + nameAt + 'px and ' + offRows.length + ' of '
          + rows.length + ' row(s) start at ' + offRows[0] + 'px'
          + (rows[0].closest('.section-body') ? ' (its rows are in a fold)' : ''));
      }
      // Only a header drawn as a row of its table can curve away from its own
      // underline; a plain caption above a list is not that and has nothing
      // to line up with.
      var hs = w.getComputedStyle(head);
      // (read as numbers: the page's own browser says "0px" for a square
      // corner, the one this runs in says "0", and the test once took the
      // second for a rounded one - five false alarms on every run)
      if (head.classList.contains(kind + '-row')
          && (parseFloat(hs.borderRadius) || 0) > 0 && (parseFloat(hs.borderBottomWidth) || 0) > 0) {
        headTrouble.push(kind + ': rounded header with an underline, which lifts at the ends');
      }
    });
    headTrouble.forEach(function (t) { errors.push('column header - ' + t); });
    if (!d.querySelector('.gw-row:not(.gw-head)')) errors.push('the gateway header was never measured');
    if (plantedGateway) {
      await jfetch(base + 'index.php?api=gateways-save', {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({pin: '1234', gateways: []})});
    }
    console.log('column headers: %d measured, %s', headsSeen,
      headTrouble.length ? 'some out of line' : 'every name over its box');
  } catch (e) { errors.push('the column header check itself failed: ' + e.message); }

  // A link telling something of its own has the same writing desk an alert
  // has: the symbol picker, the fact picker, the completer, and a preview
  // that says what the watch would read out.
  try {
    w.showControlSection('automation');
    await wait(1800);
    var tapRow = d.querySelector('#taps-list .tap-row:not(.tap-head)');
    if (tapRow && (w.TAPS.rows || []).length) {
      var theTap = w.TAPS.rows[0];
      theTap.target = 'tell'; theTap.do = 'own';
      theTap.text = 'Inside {inside_c} and outside {outside_c}.';
      w.TAPS.dirty = true; w.forgetSig('taps'); w.renderTaps(w.STATE.status);
      await wait(300);
      var desk = d.querySelector('.tap-storybox');
      if (!desk || desk.hidden) errors.push('a link of your own has no writing desk');
      else {
        if (!desk.querySelector('textarea')) errors.push('the writing desk has no text area');
        var deskBtns = Array.prototype.map.call(desk.querySelectorAll('button'),
          function (b) { return b.textContent; }).join(' ');
        if (deskBtns.indexOf('Emoji') < 0) errors.push('the writing desk has no symbol picker');
        if (deskBtns.indexOf('Facts') < 0) errors.push('the writing desk has no fact picker');
        // the section sweep above leaves another section showing, so come
        // back to the links before looking for their preview
        w.showControlSection('automation');
        await wait(1200);
        w.scheduleTellPreview();
        // what it must show is a sentence with the {...} filled in - not a
        // digit. A house with no indoor temperature fills {inside_c} with
        // nothing, which is correct and used to be called a failure here.
        var shown = null, says = '';
        for (var pw = 0; pw < 12; pw++) {
          shown = d.querySelector('.tap-preview[data-tap="' + theTap.id + '"]');
          says = (shown && shown.textContent || '').trim();
          if (says.length > 20 && says.indexOf('{') < 0) break;
          await wait(300);
        }
        if (!says) errors.push('the preview says nothing about what the watch would read');
        else if (says.indexOf('{') >= 0) errors.push('the preview left a {fact} standing: ' + says.slice(0, 60));
        // and it must survive a redraw landing in the middle of the asking.
        // The answer used to be written into the box the round began with,
        // which a redraw had thrown away by then: the line stayed empty on
        // that link until something else made the card redraw, which is why
        // it went missing only sometimes and only somewhere.
        // and a prepared report with nothing to say right now must say so.
        // It used to leave the line blank and remember that it had, so the
        // link kept an empty preview until its text or its report changed -
        // indistinguishable from a preview that never arrived.
        var realApi = w.api, wasDo = theTap.do;
        theTap.do = 'house';                 // a prepared report, not a sentence of your own
        w.api = function (what) {
          if (String(what).indexOf('tell&') === 0) return Promise.resolve({said: ''});
          return realApi.apply(null, arguments);
        };
        var quiet = d.querySelector('.tap-preview[data-tap="' + theTap.id + '"]');
        if (quiet) { delete quiet.dataset.shown; quiet.innerHTML = ''; }   // so what appears is this round's
        w.scheduleTellPreview();
        var saidNothing = '';
        for (var pq = 0; pq < 10; pq++) {
          await wait(300);
          var qn = d.querySelector('.tap-preview[data-tap="' + theTap.id + '"]');
          saidNothing = (qn && qn.textContent || '').trim();
          if (saidNothing) break;
        }
        w.api = realApi; theTap.do = wasDo;
        if (!saidNothing) errors.push('a report with nothing to say leaves the preview blank');
      }
      // the row above the desk keeps its shape whatever the link is doing:
      // a switch, a prepared report, or a sentence of your own
      var shapes = [];
      var trials = [['Probe-Plug', 'toggle'], ['tell', 'house'], ['tell', 'own']];
      for (var ti = 0; ti < trials.length; ti++) {
        var pair = trials[ti];
        theTap.target = pair[0]; theTap.do = pair[1];
        w.TAPS.dirty = true; w.forgetSig('taps'); w.renderTaps(w.STATE.status);
        var again = d.querySelector('#taps-list .tap-row:not(.tap-head)');
        var onLine = Array.prototype.filter.call(again.children, function (c) {
          return !c.classList.contains('rowgrab') && !c.classList.contains('row-mark')
            && !c.classList.contains('tap-storybox');
        }).length;
        var area = again.querySelector('.tap-story');
        var tools = again.querySelector('.tap-storytools');
        shapes.push(onLine);
        if (area && tools && area.hidden !== tools.hidden) {
          errors.push('the text box and its buttons do not come and go together');
        }
        // What is on the screen, not what the script believes: display:flex
        // beats the hidden attribute, and that is how the pickers stayed
        // visible however carefully they were hidden.
        var seen = function (node) { return node && w.getComputedStyle(node).display !== 'none'; };
        var own = pair[0] === 'tell' && pair[1] === 'own';
        var telling = pair[0] === 'tell';
        if (seen(tools) !== own) {
          errors.push('the pickers are ' + (own ? 'not shown for' : 'shown outside') + ' a sentence of your own');
        }
        if (seen(area) !== own) {
          errors.push('the text box is ' + (own ? 'not shown for' : 'shown outside') + ' a sentence of your own');
        }
        // an empty preview is hidden by its own rule, so wait for the answer
        // rather than for the element
        var preBox = again.querySelector('.tap-preview');
        if (telling) {
          w.scheduleTellPreview();
          for (var tries = 0; tries < 12 && !(preBox.textContent || '').trim(); tries++) await wait(300);
          if (!(preBox.textContent || '').trim()) errors.push('no preview on a ' + pair[1] + ' link');
        } else if (seen(preBox)) {
          errors.push('a switching link shows a preview of something that has not happened');
        }
      }
      var headCells = d.querySelector('.tap-head').children.length;
      if (shapes.some(function (n) { return n !== headCells; })) {
        errors.push('the link row changes shape: ' + shapes.join(', ') + ' against ' + headCells + ' headings');
      }
      // A link that was already there, edited through the controls rather than
      // by setting the model: a redraw replaces the rows, and a handler that
      // held on to the object it was built with writes into a discarded one.
      // That is why a new link behaved and an old one did not.
      theTap.target = 'Probe-Plug'; theTap.do = 'toggle';
      w.TAPS.dirty = false; w.forgetSig('taps'); w.renderTaps(w.STATE.status);
      await wait(200);
      var liveRow = d.querySelector('#taps-list .tap-row:not(.tap-head)');
      var targetSel = liveRow.querySelectorAll('select')[0];
      if (targetSel) {
        targetSel.value = 'tell';
        targetSel.onchange();
        await wait(150);
        if ((w.TAPS.rows[0] || {}).target !== 'tell') {
          errors.push('editing a link that was already there does not take');
        }
      }
      // A new row must start with nothing chosen, not with whatever happens
      // to be first in the list: that had it showing "tell me something" with
      // "toggle" beside it, a pair that cannot be, until it was clicked away
      // and back again.
      d.getElementById('tap-add').onclick();
      await wait(400);
      var made = Array.prototype.slice.call(d.querySelectorAll('#taps-list .tap-row'))
        .filter(function (x) { return !x.classList.contains('tap-head'); });
      var fresh = made[made.length - 1];
      var freshModel = w.TAPS.rows[w.TAPS.rows.length - 1];
      // A new row may come filled in, but the two lists must agree: it used
      // to offer "tell me something" with "toggle" beside it, a pair that
      // cannot be, until it was clicked away and back again.
      var freshSels = fresh.querySelectorAll('select');
      var offered = Array.prototype.map.call(freshSels[1].options, function (o) { return o.value; });
      if (offered.indexOf(freshModel.do) < 0) {
        errors.push('a new link offers ' + JSON.stringify(freshModel.do) + ' which is not one of its own actions');
      }
      if (freshSels[0].value !== freshModel.target || freshSels[1].value !== freshModel.do) {
        errors.push('a new link shows something other than what it holds');
      }
      w.TAPS.rows.pop(); w.TAPS.dirty = false;

      // and asking the house something belongs to the links alone
      var elsewhere = [];
      ['#bindings-list select', '#rules-list select', '#scenes-list select'].forEach(function (sel) {
        Array.prototype.forEach.call(d.querySelectorAll(sel), function (x) {
          if (Array.prototype.some.call(x.options, function (o) { return o.value === 'tell'; })) {
            elsewhere.push(sel);
          }
        });
      });
      if (elsewhere.length) errors.push('"tell me something" is offered in ' + elsewhere[0]);

      // The preview reads the row as it stands on the screen; until it is
      // saved, the link itself still does the old thing. Both places have to
      // say so, or a preview is just a confident wrong answer.
      // (the new row was taken away again with the list marked saved, so the
      // next report replaced every row with a fresh copy: the link is looked
      // up again, or the change below goes into one the page no longer holds
      // and nothing is ever asked - which this check read as a preview that
      // does not say so)
      theTap = w.TAPS.rows.filter(function (r) { return r.id === theTap.id; })[0] || theTap;
      theTap.target = 'tell'; theTap.do = 'house';
      w.TAPS.dirty = true; w.forgetSig('taps'); w.renderTaps(w.STATE.status);
      await wait(200);
      w.scheduleTellPreview();
      // (waited for until it says so, not for the first words: under load an
      // answer of the round before can land first and be replaced a moment
      // later)
      for (var pt = 0; pt < 20; pt++) {
        var lbl = d.querySelector('.tap-preview .lbl');
        if (lbl && lbl.textContent.indexOf('saved') >= 0) break;
        await wait(300);
      }
      var label = d.querySelector('.tap-preview .lbl');
      if (!label || label.textContent.indexOf('saved') < 0) {
        errors.push('with changes unsaved the preview does not say so: '
          + JSON.stringify(label && label.textContent));
      }
      var told = null;
      var keepToast = w.toast;
      w.toast = function (m) { told = m; };
      w.showTapSetup(theTap);
      await wait(200);
      w.toast = keepToast;
      if (!told || String(told).indexOf('Save') < 0) {
        errors.push('the setup dialog hands out an address that does not match the screen');
      }
      w.TAPS.dirty = false;
      console.log('a telling link: writing desk, pickers and preview all there');
    }
  } catch (e) { errors.push('the telling-link check itself failed: ' + e.message); }

  // Renaming a section that has rows in it must move the rows, not leave them
  // behind under the old name with an empty section beside it. A row holds the
  // object it was built with, and a redraw replaces those with fresh copies -
  // so writing through the row's own copy renamed something already discarded.
  try {
    var storesWithSections = [['taps', w.TAPS], ['messages', w.MESSAGES], ['ptrig', w.PTRIG],
                              ['bindings', w.BINDINGS]];
    var regroupTrouble = [];
    storesWithSections.forEach(function (pair) {
      var store = pair[1];
      if (!store || !(store.rows || []).length) return;
      var was = store.rows[0].group || '';
      var mine = store.rows.filter(function (r) { return (r.group || '') === was; }).length;
      var moved = w.regroupRows(store, was, 'A-New-Name');
      if (moved !== mine) {
        regroupTrouble.push(pair[0] + ': renaming moved ' + moved + ' of ' + mine + ' row(s)');
      }
      var left = store.rows.filter(function (r) { return (r.group || '') === was; }).length;
      if (left) regroupTrouble.push(pair[0] + ': ' + left + ' row(s) stayed under the old name');
      w.regroupRows(store, 'A-New-Name', was);          // put it back
    });
    regroupTrouble.forEach(function (t) { errors.push('renaming a section - ' + t); });
    console.log('renaming a section: %d editor(s) checked, rows follow their section',
      storesWithSections.filter(function (p) { return p[1] && (p[1].rows || []).length; }).length);
  } catch (e) { errors.push('the section-rename check itself failed: ' + e.message); }

  // A scene or a sequence runs its own steps and the daemon takes no notice of
  // what is asked of it, so offering on, off and toggle beside one offers a
  // choice that does not exist. Two editors said so in a note beside the list
  // and the rest quietly did not; it is decided in one place now, so every
  // editor that fills an action list gets it.
  try {
    var st = w.STATE.status || {};
    var runners = [];
    ((st.scenes || [])[0] ? [['a scene', 'scene:' + st.scenes[0].id]] : [])
      .concat((st.sequences || [])[0] ? [['a sequence', 'sequence:' + st.sequences[0].id]] : [])
      .forEach(function (pair) {
        var opts = w.doOptionsFor(st, pair[1], 'on');
        if (opts.length !== 1) {
          errors.push(pair[0] + ' offers ' + opts.length + ' actions, and it has only one: its own steps');
        } else if (opts[0][1].indexOf('own steps') < 0) {
          errors.push(pair[0] + ' does not say that it runs its own steps: ' + JSON.stringify(opts[0][1]));
        }
        runners.push(pair[0]);
      });
    // and a socket must still have its full set, or the rule above is too keen
    var plugName = ((st.plugs || [])[0] || {}).name;
    if (plugName && w.doOptionsFor(st, plugName, 'on').length < 3) {
      errors.push('a socket lost its actions');
    }
    // and it must be a plain line, not a list with one thing in it: nobody
    // should be given a menu to choose from when there is nothing to choose
    var seenAt = w.getComputedStyle.bind(w);
    var shownBeside = [];
    Array.prototype.forEach.call(d.querySelectorAll('select'), function (sel) {
      if (seenAt(sel).display === 'none') return;
      var prev = sel.previousElementSibling;
      if (prev && prev.tagName === 'SELECT' && String(prev.value).indexOf('scene:') === 0) {
        shownBeside.push(((sel.closest('.card') || {}).id || 'a card'));
      }
    });
    if (shownBeside.length) {
      errors.push('a list of actions is still offered beside a scene in ' + shownBeside[0]);
    }
    // The line has to be where the list was, not an extra cell beside it: in a
    // row laid out as a grid an extra cell shifts every column after it, which
    // is how choosing a scene resized the name box next to it.
    Array.prototype.forEach.call(d.querySelectorAll('.tap-row:not(.tap-head)'), function (row) {
      var note = row.querySelector('.scene-note');
      if (!note || seenAt(note).display === 'none') return;
      var onLine = Array.prototype.filter.call(row.children, function (c) {
        return !c.classList.contains('rowgrab') && !c.classList.contains('row-mark')
          && !c.classList.contains('tap-storybox');
      }).length;
      var headings = (d.querySelector('.tap-head') || {children: []}).children.length;
      if (onLine !== headings) {
        errors.push('a link showing the plain line has ' + onLine + ' cells against ' + headings + ' headings');
      }
      if (!note.closest('.tap-act')) {
        errors.push('the plain line sits outside the cell the list was in, so it moves the columns');
      }
    });
    var plainLines = Array.prototype.filter.call(d.querySelectorAll('.scene-note'),
      function (n) { return seenAt(n).display !== 'none'; });
    console.log('what runs its own steps: %s, said as a plain line in %d place(s)',
      runners.join(' and ') || 'nothing', plainLines.length);
  } catch (e) { errors.push('the own-steps check itself failed: ' + e.message); }

  // ---- a road apiece, not a list of combinations ---------------------------
  // Three roads make eight ways of choosing, and the list of combinations
  // offered seven: ntfy and a text but not Telegram could not be said at all.
  try {
    d.querySelector('.tabs button[data-tab="control"]').click(); await wait(400);
    const alerts = d.querySelector('#control-nav button[data-sec="msg-alerts"]');
    if (alerts) { alerts.click(); await wait(1200); }
    const rows = d.querySelectorAll('#notify-systems .notify-sys');
    if (!rows.length) errors.push('no kind of message has its own roads to switch');
    if (d.querySelectorAll('#notify-systems select').length) {
      errors.push('a kind of message is still chosen from a list of combinations');
    }
    const row = rows[0];
    const sw = row.querySelectorAll('.swrow input');
    if (sw.length !== 4) errors.push('a kind of message has ' + sw.length + ' switches, wanted four');
    if (!Array.prototype.slice.call(sw, 1).every(i => i.disabled)) {
      errors.push('the roads can be switched while the kind still follows the house');
    }
    sw[0].checked = true; sw[0].dispatchEvent(new w.Event('change', { bubbles: true }));
    await wait(50);
    const road = k => row.querySelector('input[data-road="' + k + '"]');
    if (road('sms').disabled) errors.push('a kind with its own roads still cannot pick one');
    road('ntfy').checked = true; road('telegram').checked = false; road('sms').checked = true;
    road('sms').dispatchEvent(new w.Event('change', { bubbles: true }));
    await wait(50);
    const picked = Array.prototype.filter.call(row.querySelectorAll('input[data-road]'), b => b.checked)
      .map(b => b.dataset.road).join(',');
    if (picked !== 'ntfy,sms') errors.push('ntfy and a text without Telegram cannot be chosen: got ' + picked);
    road('ntfy').checked = false; road('sms').checked = false;
    road('sms').dispatchEvent(new w.Event('change', { bubbles: true }));
    await wait(50);
    if (!/nothing/.test(row.querySelector('.notify-sys-says').textContent)) {
      errors.push('with no road on, the row does not say it will stay silent');
    }
    console.log('alerts: %d kind(s), a switch per road, all eight ways sayable', rows.length);
  } catch (e) { errors.push('the alert-roads check itself failed: ' + e.message); }

  // ---- what is waiting for somebody to say yes -----------------------------
  try {
    const tab = d.querySelector('.tabs button[data-tab="approvals"]');
    if (!tab) errors.push('there is no place to see what is waiting to be approved');
    else {
      tab.click(); await wait(1200);
      if (!d.getElementById('approvals-live')) errors.push('the approvals tab is empty of itself');
      if (!d.getElementById('approvals-stop-all')) errors.push('there is no way to call them all off');
      if (!d.querySelector('#approvals-past tbody')) errors.push('there is nowhere for the history');
      const order = Array.from(d.querySelectorAll('.tabs button')).map(b => b.dataset.tab);
      if (order.indexOf('approvals') !== order.indexOf('events') + 1) {
        errors.push('the approvals tab does not sit after Events');
      }
      // the habits the rest of the page keeps: an icon on every button, the
      // lock on every button that changes something, and a row that answers
      // the pointer
      const btns = Array.from(d.querySelectorAll('#tab-approvals button'));
      // an icon name nobody drew makes an empty <svg>, which looked like an
      // icon to this check and like nothing at all to a person
      const bare = btns.filter(b => {
        const svg = b.querySelector('svg');
        const drawn = (svg && svg.innerHTML.trim().length > 0) || b.querySelector('img');
        return !drawn && !/[\u2190-\u27bf\ud83c-\udbff]/.test(b.textContent);
      });
      if (bare.length) {
        errors.push('button(s) with no icon on the presses tab: '
          + bare.map(b => b.textContent.trim().slice(0, 20)).join(', '));
      }
      // A button with an icon, wearing the lock, and with nothing behind it
      // looks exactly like one that works. One of these lost its handler in a
      // move and nobody could tell by looking.
      const wired = ['approvals-stop-all', 'approvals-forget-btn', 'blocked-add',
                     'blocked-add-forever', 'blocked-clear', 'blocked-forget',
                     'blocked-forget-counters'];
      const dead = wired.filter(id => {
        const b = d.getElementById(id);
        return b && !b.onclick;
      });
      if (dead.length) errors.push('button(s) with nothing behind them: ' + dead.join(', '));
      const changes = ['approvals-stop-all', 'blocked-add', 'blocked-add-forever', 'blocked-clear',
                       'blocked-forget'];
      const unlocked = changes.filter(id => {
        const b = d.getElementById(id);
        return b && !b.classList.contains('needs-unlock');
      });
      if (unlocked.length) {
        errors.push('button(s) that change something but do not wear the lock: ' + unlocked.join(', '));
      }
      const styled = [];
      Array.from(d.styleSheets || []).forEach(sh => {
        try {
          Array.from(sh.cssRules).forEach(r => {
            if (r.selectorText && /\.appr-row:hover/.test(r.selectorText)) styled.push(r.selectorText);
          });
        } catch (e) { /* a sheet from elsewhere */ }
      });
      if (!styled.length) errors.push('a row on the presses tab does not answer the pointer');
      // and the settings panel for the router's key, which lives elsewhere
      try {
        w.renderSettings(w.STATE.status);
        const panel = SETQ('.subpanel');
        if (panel) {
          const dull = Array.from(panel.querySelectorAll('button')).filter(b => {
            const svg = b.querySelector('svg');
            return !(svg && svg.innerHTML.trim().length);
          });
          if (dull.length) {
            errors.push('the router key panel has button(s) with an empty icon: '
              + dull.map(b => b.textContent.trim()).join(', '));
          }
        }
      } catch (e) { errors.push('the key panel check itself failed: ' + e.message); }
      // Typing in a list's filter must survive the list being drawn afresh,
      // which it is on every update: the box lost the cursor, two letters in.
      try {
        const un0 = await signIn();
        w.signedInAs(un0.who);
        await jfetch(base + 'index.php?api=blocked', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pin: '1234', ip: '89.24.5.8', forever: true }) });
        w.loadApprovals(true); await wait(900);
        Array.from(d.querySelectorAll('#blocked-list .listed-head')).forEach(h => {
          if (h.nextElementSibling && h.nextElementSibling.hidden) h.click(); });
        const box = d.querySelector('#blocked-list [data-keep^="listed-filter"]');
        if (!box) errors.push('the blocked list has no filter box to type in');
        else {
          box.focus(); box.value = '89.24'; box.dispatchEvent(new w.Event('input', { bubbles: true }));
          w.paintBlocked(true); w.loadApprovals(true); await wait(900);
          const at = d.activeElement;
          if (!at || !at.dataset || !String(at.dataset.keep || '').startsWith('listed-filter')) {
            errors.push('typing in the blocked list\u2019s filter lost the cursor when the list was drawn again');
          } else if (at.value !== '89.24') {
            errors.push('what was typed in the blocked list\u2019s filter went when the list was drawn again');
          }
          const again = d.activeElement; again.value = ''; again.dispatchEvent(new w.Event('input', { bubbles: true })); again.blur();
        }
        await jfetch(base + 'index.php?api=blocked', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pin: '1234', remove: '89.24.5.8' }) });
        console.log('typing in a list\u2019s filter keeps the cursor through a redraw');
      } catch (e) { errors.push('the filter-cursor check itself failed: ' + e.message); }
      // taking an address off the list must take its line with it, without
      // waiting for a fetch that may be slow, refused, or held back
      try {
        const un = await signIn();
        w.signedInAs(un.who);
        await jfetch(base + 'index.php?api=blocked', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pin: '1234', ip: '89.24.5.7', forever: true }) });
        w.loadApprovals(true); await wait(900);
        // both kinds live in a fold now, so the rows are inside one - opened
        // here, because a fold that is shut draws nothing until it is
        // (only the shut ones: a head clicked on an open fold shuts it, and
        // the list was being counted with half its folds closed)
        Array.from(d.querySelectorAll('#blocked-list .listed-head')).forEach(h => {
          if (h.nextElementSibling && h.nextElementSibling.hidden) h.click(); });
        const itsRows = () => Array.from(d.querySelectorAll('#blocked-list .appr-row'))
          .filter(r => (r.querySelector('.appr-link') || {}).textContent === '89.24.5.7');
        if (!itsRows().length) errors.push('an address that was blocked does not show on the list');
        // the cross at the end of its own line - not the first button in the
        // list, which is the mark after an address, or its Shodan button
        const cross = itsRows().length ? itsRows()[0].lastElementChild : null;
        if (cross) {
          cross.click(); await wait(300);
          const ok = d.getElementById('pinok');
          if (ok && !d.getElementById('pinback').hidden) {
            d.getElementById('signin-name').value = 'admin'; d.getElementById('signin-pass').value = 'admin pass 1';
            ok.click();
          }
          await wait(1200);
          if (itsRows().length) errors.push('taking an address off the list left its line there');
        }
      } catch (e) { errors.push('the blocked-list check itself failed: ' + e.message); }
      // the variables dialogue: boxes with the page's shape, buttons with
      // icons, and the rule's own names offered only on that rule
      try {
        const row = {phrase: 'unban', vars: [{name: 'ip', from: 'rest', note: ''}]};
        w.editRowVars(row, 'command', function () {});
        await wait(300);
        const box = d.querySelector('#attnbody input');
        if (!box || !box.classList.contains('varbox')) {
          errors.push('the variables dialogue has a box with no shape');
        }
        const bare = Array.from(d.querySelectorAll('#attnbody button')).filter(b => {
          const svg = b.querySelector('svg');
          return !(svg && svg.innerHTML.trim());
        });
        if (bare.length) {
          errors.push('the variables dialogue has button(s) with no icon: '
            + bare.map(b => b.textContent.trim()).join(', '));
        }
        // a name written into the phrase is also kept on the row, so both say
        // it: the list must say it once, and with the braces the list draws
        w.COMPLETE_LOCAL = w.rowVars(row).concat(w.phraseNames('unban {ip}'));
        const mine = w.completerItems('ip').filter(x => x.label === 'ip');
        if (mine.length !== 1) {
          errors.push('a name a rule made up is offered ' + mine.length + ' time(s), not once');
        }
        if (w.completerItems('ip').some(x => /^\{|\}$/.test(x.label || ''))) {
          errors.push('a name is offered with braces the list draws itself');
        }
        if (!w.completerItems('ip.').length) {
          errors.push('a name a rule made up takes no turns of phrase');
        }
        w.COMPLETE_LOCAL = [];
        const shut = d.getElementById('attnback');
        if (shut) shut.hidden = true;
      } catch (e) { errors.push('the variables check itself failed: ' + e.message); }
      // the scripts: their verbs are what the box offers, and their names are
      // what a command may point at - under a heading of their own
      try {
        if (!(w.SCRIPTS.verbs || []).length) {
          errors.push('the script verbs never arrived, so the box can offer none');
        } else {
          w.COMPLETE_LOCAL = w.verbNames();
          if (!w.completerItems('unb').some(x => x.label === 'unban')) {
            errors.push('the script box does not offer its own verbs');
          }
          w.COMPLETE_LOCAL = [];
          // ...and it has to offer them where they are written, which is at
          // the start of a line and not inside braces
          // a house with no script yet has no box; one is added to type in
          if (!d.querySelector('#scripts-list textarea')) {
            const add = d.getElementById('script-add');
            if (add) { add.click(); await wait(400); }
          }
          const box = d.querySelector('#scripts-list textarea');
          if (!box) {
            errors.push('adding a script leaves nothing to type in');
          } else {
            box.value = 'un';
            box.focus();
            box.selectionStart = 2;
            box.dispatchEvent(new w.KeyboardEvent('keydown', {key: ' ', ctrlKey: true, bubbles: true}));
            await wait(400);
            const pop = d.querySelector('.acbox');
            const names = pop ? Array.from(pop.querySelectorAll('.ac-name')).map(x => x.textContent) : [];
            if (names.indexOf('unban') < 0) {
              errors.push('Ctrl+Space at the start of a script line offers no verb: ' + names.slice(0, 3));
            }
            if (names.some(n => /^\{/.test(n))) {
              errors.push('a verb is offered as though it were a fact in braces');
            }
            box.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
            await wait(250);
            if (box.value.indexOf('}') >= 0) errors.push('picking a verb wrote a brace: ' + box.value);
            box.value = '';
          }
          // put the page back as it was found: a row added here and left
          // behind marks the editors as having something unsaved, and the
          // checks that come after are skipped while anything is
          w.SCRIPTS.rows = (w.SCRIPTS.rows || []).filter(one => one.id);
          w.SCRIPTS.dirty = false;
          w.paintScripts();
          const note = d.getElementById('script-note');
          if (note) note.textContent = '';
        }
        ['script-add', 'script-save'].forEach(id => {
          const b = d.getElementById(id), svg = b && b.querySelector('svg');
          if (b && !(svg && svg.innerHTML.trim())) {
            errors.push('the scripts card has a button with no icon: ' + id);
          }
        });
      } catch (e) { errors.push('the scripts check itself failed: ' + e.message); }
      // an escape written into the markup is read out as \u2014 rather than
      // as a dash: the page is PHP, and a backslash there is just a backslash
      // ...read from what is shown, not from the page's own source: the text
      // of a <script> is part of the body's text and is full of them
      const shown = Array.from(d.querySelectorAll('p, h1, h2, h3, li, td, th, label, button, span'))
        .map(n => n.textContent || '').join(' ');
      const loose = shown.match(/\\u[0-9a-fA-F]{4}/g);
      if (loose) errors.push('the page shows escapes as text: ' + loose.slice(0, 3).join(' '));
      // the page's own habits, across every tab and section rather than the
      // one card being worked on: an id used twice makes $('x') pick the
      // wrong one, and a command button with no icon reads as unfinished
      const idsSeen = {}, twice = [];
      d.querySelectorAll('[id]').forEach(n => {
        idsSeen[n.id] = (idsSeen[n.id] || 0) + 1;
        if (idsSeen[n.id] === 2) twice.push(n.id);
      });
      if (twice.length) errors.push('id(s) used more than once: ' + twice.slice(0, 5).join(', '));
      const plainButtons = Array.from(d.querySelectorAll('button.btn')).filter(b =>
        !b.closest('.tabs') && !b.closest('#control-nav') && !b.classList.contains('pg'));
      const noIcon = plainButtons.filter(b => {
        const svg = b.querySelector('svg');
        const drawn = (svg && svg.innerHTML.trim().length > 0) || b.querySelector('img')
          || /[\u2190-\u27bf\ud83c-\udbff]/.test(b.textContent)
          || /^\s*[{}\d]/.test(b.textContent);      // { } Facts, and the 6h/24h chips
        return !drawn && b.textContent.trim();
      }).map(b => b.id || b.textContent.trim().slice(0, 22));
      if (noIcon.length) {
        errors.push('command button(s) with no icon: ' + [...new Set(noIcon)].slice(0, 6).join(', '));
      }
      // The button in a locked card has to survive the polling behind it.
      // This tab asks for its lists once a second and every one of them is
      // refused while editing is locked; redrawing the note on each refusal
      // threw the button away between the press and the release, so the first
      // click did nothing and the second worked.
      try {
        const hold = w.LOCK.who;
        w.LOCK.who = null;
        w.APPROVALS.locked = true;
        w.paintApprovalsLocked();
        const live = d.getElementById('approvals-live');
        const first = live.querySelector('button');
        if (!first) {
          errors.push('the locked press list offers no way to unlock');
        } else {
          w.paintApprovalsLocked();
          w.paintApprovalsLocked();          // as three refusals would
          if (live.querySelector('button') !== first) {
            errors.push('the unlock button is replaced while the tab polls, so a click can miss it');
          }
        }
        w.LOCK.who = hold;
        w.APPROVALS.locked = false;
        if (live) live.dataset.locked = '';
      } catch (e) { errors.push('the locked-card check itself failed: ' + e.message); }
      // The router's own list, joined with what the house knows. Drawn from
      // an answer shaped like the daemon's, so the sheet is checked without a
      // router to read.
      try {
        const now = Date.now() / 1000;
        w.drawRouterSheet({ok: true, list: 'ZigMon', read_in_ms: 37, carrying: [
          {address: '185.234.9.7', family: 'IPv4', ours: true, comment: 'zigmon: kept out',
           known: true, why: '5 in 10 min', how: 'the third time from this address: 24 h',
           since: now - 3600, left: 82800, hits: 14, auto: true, before: 2, from_proxy: true,
           score: 28, bar: 15,
           evidence: [{when: now - 100, kind: 'proxy-poking', words: 'a path that is not there',
                       detail: 'GET /.env'}],
           tried_since: [{when: now - 20, kind: 'shut-road', words: 'a road that is shut',
                          detail: 'POST /tap'}],
           story: [{ts: now - 3600, what: 'blocked', why: '5 in 10 min', by: 'by itself'}]},
          {address: '2a02:1:2::9/128', family: 'IPv6', ours: false, comment: 'theirs',
           known: false, evidence: [], story: []}],
          not_carried: [{address: '10.9.9.9', family: 'IPv4', known: true, why: 'by hand',
                         by: 'by hand', evidence: [], story: []}]});
        await wait(250);
        const cards = Array.from(d.querySelectorAll('.rtr .ak'));
        if (cards.length !== 3) errors.push('the router sheet drew ' + cards.length + ' of 3 cards');
        const marks = cards.map(c => Array.from(c.querySelectorAll('h4 .road'))
          .map(r => r.textContent).join(' '));
        if (!/carried/.test(marks[0] || '')) errors.push('an address on the router is not marked as carried');
        if (!/somebody else/.test(marks[1] || '')) errors.push("another hand's entry is not marked as theirs");
        if (!/not on the router/.test(marks[2] || '')) {
          errors.push('an address kept out here but not on the router is not marked');
        }
        if (!cards[0].querySelector('.proof .pl')) errors.push('the sheet shows no evidence at all');
        // and the two halves are told apart: what earned it, and what it has
        // tried since - one reads as the reason and the other must not
        const heads = Array.from(cards[0].querySelectorAll('.proof .ph')).map(x => x.textContent);
        if (!heads.some(h => /what earned it/.test(h))) {
          errors.push('the evidence is not labelled as what earned the block');
        }
        if (!cards[0].querySelector('.story .s')) errors.push('the sheet shows no story at all');
        // a router carrying a few hundred addresses is a sheet nobody can
        // read: a box to narrow it, and the country beside each address
        const rfind = d.querySelector('#attnbody input');
        if (!rfind) {
          errors.push('the router sheet has no box to filter it with');
        } else {
          const seen = () => d.querySelectorAll('#attnbody .ak').length;
          const was = seen();
          rfind.value = 'nonsense-nothing-matches';
          rfind.oninput();
          if (seen() !== 0) errors.push('a filter matching nothing still shows router cards');
          rfind.value = '';
          rfind.oninput();
          if (seen() !== was) errors.push('clearing the router filter does not bring them back');
        }
        if (!cards[0].querySelector('.cflag')) {
          errors.push('the router sheet says no country beside an address');
        }
        if (!heads.some(h => /since it was kept out/.test(h))) {
          errors.push('what it tried after being kept out is not told apart from the reason');
        }
        const fields = Array.from(cards[0].querySelectorAll('.cell b')).map(b => b.textContent);
        ['why that long', 'kept out before', 'on its account now'].forEach(need => {
          if (fields.indexOf(need) < 0) errors.push('the router sheet leaves out "' + need + '"');
        });
        const close = d.getElementById('attnclose');
        if (close) close.click();
        await wait(200);
      } catch (e) { errors.push('the router-sheet check itself failed: ' + e.message); }
      // Every kind of message the house sends, on one sheet: the categories
      // the daemon offers, where each goes, and an example of each. A sheet
      // that lists a kind without showing one is a list of names.
      try {
        d.querySelector('#control-nav button[data-sec="msg-alerts"]').click();
        await wait(1200);
        // one button per road as well as the one that tries them all: sending
        // down everything tells you something arrived, not which one did not
        ['notify-test', 'notify-test-ntfy', 'notify-test-telegram'].forEach(id => {
          const b = d.getElementById(id);
          if (!b) errors.push('there is no ' + id + ' button');
          else if (!b.querySelector('svg')) errors.push(id + ' has no icon');
        });
        const roads = ((w.STATE.status || {}).notify || {}).channels || [];
        const ntfyBtn = d.getElementById('notify-test-ntfy');
        if (ntfyBtn && ntfyBtn.disabled !== (roads.indexOf('ntfy') < 0)) {
          errors.push('the ntfy test button does not follow whether ntfy is set up');
        }
        const perKind = d.querySelectorAll('#notify-systems .notify-sys').length;
        if (perKind < 15) errors.push('only ' + perKind + ' kinds may take a road of their own');
        d.getElementById('notify-sheet').click();
        await wait(600);
        // the first sheet is the kinds; the second, when there is one, is what
        // was written by hand under Messages
        const allSheets = d.querySelectorAll('#attnbody .alertsheet');
        const cards = Array.from(allSheets[0] ? allSheets[0].querySelectorAll('.ak') : []);
        if (cards.length !== perKind) {
          errors.push('the sheet shows ' + cards.length + ' kinds and the card offers ' + perKind);
        }
        const noExample = cards.filter(c => !c.querySelector('.eg'));
        if (noExample.length) {
          errors.push(noExample.length + ' kind(s) on the sheet show no example: '
            + noExample.slice(0, 3).map(c => c.querySelector('h4').textContent).join(', '));
        }
        const blocked = cards.find(c => /address kept out/i.test(c.querySelector('h4').textContent));
        if (!blocked) errors.push('an address being kept out is not a kind of its own');
        // the ones written by hand under Messages belong on it too: they carry
        // their own words, their own level and their own roads
        const sheets = d.querySelectorAll('#attnbody .alertsheet');
        const written = (w.STATE.status || {}).messages || [];
        if (written.length && sheets.length < 2) {
          errors.push('the sheet leaves out the ' + written.length + ' alert(s) written by hand');
        }
        if (sheets.length > 1 && sheets[1].querySelectorAll('.ak').length !== written.length) {
          errors.push('the sheet shows ' + sheets[1].querySelectorAll('.ak').length
            + ' hand-written alert(s) and there are ' + written.length);
        }
        const close = d.getElementById('attnclose');
        if (close) close.click();
        await wait(200);
      } catch (e) { errors.push('the alert-sheet check itself failed: ' + e.message); }
      // The ladder is built from its steps rather than typed: a box to type a
      // list into is a box to make a mistake in, and one comma out of place
      // is a house that keeps somebody out for a thousand days.
      try {
        const rung = Array.from(SETQA('.set-item'))
          .find(i => i.querySelector('[data-k="block_ladder"]'));
        if (!rung) {
          errors.push('the ladder is not on the settings card');
        } else {
          const field = rung.querySelector('[data-k="block_ladder"]');
          if (field.tagName === 'INPUT' && field.type !== 'hidden') {
            errors.push('the ladder is a box to type a list into');
          }
          const preset = rung.querySelector('select');
          if (!preset || preset.options.length < 4) {
            errors.push('the ladder offers no presets');
          } else {
            preset.value = '10, 60, 1440, forever';
            preset.onchange();
            await wait(150);
            if (field.value !== '10, 60, 1440, forever') {
              errors.push('choosing a preset wrote ' + JSON.stringify(field.value));
            }
            if (rung.querySelectorAll('.ladder-row').length !== 4) {
              errors.push('the ladder drew ' + rung.querySelectorAll('.ladder-row').length
                + ' of 4 steps');
            }
            const add = rung.querySelector('.btnrow button');
            if (add && !add.disabled) {
              errors.push('a step can be added after "for good", which cannot happen');
            }
            // the settings a ladder takes over say so rather than sitting there
            // looking as though they still applied
            const stillOn = ['block_minutes', 'block_minutes_serious', 'block_repeat', 'block_mode']
              .filter(function (k) {
                const box = SETQ('[data-k="' + k + '"]');
                return box && !box.closest('.set-item').classList.contains('idle');
              });
            if (stillOn.length) {
              errors.push('with a ladder set, ' + stillOn.join(', ') + ' still read as in use');
            }
            // "for good" in the middle ends the ladder there
            preset.value = '60, 1440, 10080, forever';
            preset.onchange();
            await wait(120);
            const second = rung.querySelectorAll('.ladder-row select')[1];
            second.value = '0';
            second.onchange();
            await wait(120);
            if (field.value !== '60, forever') {
              errors.push('"for good" in the middle left steps after it: ' + field.value);
            }
            preset.value = '';
            preset.onchange();
            await wait(150);
            // it may still be idle for a broader reason - the whole of the
            // blocking switched off, say - but not for the ladder's
            const why = (SETQ('[data-k="block_minutes"]')
              .closest('.set-item').querySelector('.idle-note') || {}).textContent || '';
            if (/ladder/.test(why)) {
              errors.push('with no ladder, the lengths still say they are taken over by one');
            }
            // ...and the same everywhere else: a setting another one has
            // taken over says which one, rather than sitting there looking
            // exactly like a setting that is doing something.
            const marked = Array.from(SETQA('.set-item.idle'));
            if (marked.length < 10) {
              errors.push('only ' + marked.length + ' setting(s) say they are being ignored; '
                + 'the rest of the card cannot all be in use');
            }
            const speechless = marked.filter(i => !(i.querySelector('.idle-note') || {}).textContent);
            if (speechless.length) {
              errors.push(speechless.length + ' setting(s) are dimmed without saying why');
            }
            // A switch is a checkbox, and a checkbox's value is the word "on"
            // whether it is ticked or not - so every rule that asked whether
            // a switch was off read NaN, answered yes, and marked a whole
            // card as unused while it was plainly working.
            const swOn = Array.from(SETQA('[data-bool]'))
              .filter(b => b.checked);
            const wronglyIdle = swOn.map(b => b.closest('.set-item'))
              .filter(i => i.classList.contains('idle'))
              .map(i => (i.querySelector('[data-k]') || {}).dataset.k);
            if (wronglyIdle.length) {
              errors.push(wronglyIdle.length + ' switch(es) are on and marked as not used: '
                + wronglyIdle.slice(0, 4).join(', '));
            }
            // and the ones a switched-on master governs are in use with it
            ['weather', 'backup_enabled', 'binding_watch'].forEach(master => {
              const box = SETQ('[data-k="' + master + '"]');
              if (!box || !box.checked) return;
              const kin = {weather: 'weather_name', backup_enabled: 'backup_time',
                           binding_watch: 'binding_mend'}[master];
              const item = SETQ('[data-k="' + kin + '"]');
              if (item && item.closest('.set-item').classList.contains('idle')) {
                errors.push(kin + ' reads as unused while ' + master + ' is on');
              }
            });
            // switching the whole of the blocking off takes over all of it
            // a switch is turned off by unticking it, not by setting a value
            const master = SETQ('[data-k="blacklist"]');
            const was = master.checked;
            master.checked = false;
            w.applySettingsWhen();
            await wait(100);
            const score = SETQ('[data-k="block_score"]')
              .closest('.set-item');
            if (!score.classList.contains('idle')) {
              errors.push('with addresses not kept out at all, what earns a block still reads as in use');
            }
            master.checked = was;
            w.applySettingsWhen();
          }
        }
      } catch (e) { errors.push('the ladder check itself failed: ' + e.message); }
      // Every settings item is three bands - label, control, note - so a
      // second line of label, or a note about being taken over, moves only
      // itself. As a flex column, anything added to an item pushed its box
      // up and left the boxes in one row at four different heights.
      try {
        const css = Array.from(d.querySelectorAll('style')).map(x => x.textContent).join('');
        if (css.indexOf(':is(#settings-grid, .set-host) .set-grid > .set-item{display:grid;grid-template-rows:subgrid') < 0) {
          errors.push('the settings items are not laid out in bands, so a note moves its neighbours');
        }
        // every part named to a band, rather than left to the order it was
        // added in - and the switch in the second band, beside the boxes,
        // not up at the label line
        [['> .set-item > label{grid-row:1', 'the label is not pinned to the first band'],
         ['> .set-item > .idle-note{grid-row:3', 'the note is not pinned to the third band'],
         ['.set-bool > .sw{grid-row:2', 'a switch does not sit in the band the boxes are in'],
         ['.set-bool > .idle-note{grid-row:3;grid-column:1/-1', 'a note on a switch row does not span it'],
         ['> .set-head{grid-column:1/-1;grid-row:span 1', 'a section heading is not a band of its own']
        ].forEach(function (pair) {
          if (css.indexOf(pair[0]) < 0) errors.push(pair[1]);
        });
        const crowded = Array.from(SETQA('.set-item'))
          .filter(i => i.children.length > 3);
        if (crowded.length) {
          errors.push(crowded.length + ' settings item(s) have more than three parts, which the '
            + 'three bands cannot hold: '
            + crowded.slice(0, 3).map(i => (i.querySelector('[data-k]') || {dataset: {}}).dataset.k).join(', '));
        }
        // a tall thing takes a line of its own: sharing a row with short
        // boxes stretches their bands to its height and leaves their notes
        // stranded half a screen below the box they are about
        if (css.indexOf('.set-item.set-tall{grid-column:1/-1') < 0) {
          errors.push('a tall setting shares its row, which strands its neighbours\' notes');
        }
        const tall = SETQ('.set-item.set-tall');
        if (!tall) errors.push('nothing on the card is marked as tall, so the ladder shares a row');
        // Things that belong together are in a cluster of their own, so a
        // stream of boxes cannot wrap a user onto one line and its password
        // onto the next with something else in between.
        const clusters = Array.from(SETQA('.set-cluster'));
        if (clusters.length < 25) {
          errors.push('only ' + clusters.length + ' cluster(s); sections have gone back to one stream');
        }
        // not one setting left loose in a section: a loose one is in the
        // section's own stream, which wraps wherever the width runs out
        const strays = [];
        Array.from(SETQA('.set-grid')).forEach(g => {
          Array.from(g.children).filter(c => c.classList.contains('set-item')).forEach(c => {
            strays.push((c.querySelector('[data-k]') || {dataset: {}}).dataset.k || '?');
          });
        });
        if (strays.length) {
          errors.push(strays.length + ' setting(s) are not in any cluster: ' + strays.slice(0, 5).join(', '));
        }
        const keysIn = c => Array.from(c.querySelectorAll('[data-k]')).map(b => b.dataset.k);
        const together = [['proxy_user', 'proxy_password'], ['proxy_log', 'proxy_error_log'],
                          ['ntfy_log', 'ntfy_error_log'], ['ntfy_own_log', 'ntfy_ban_log'],
                          ['ntfy_watch', 'ntfy_log'], ['ntfy_own_watch', 'ntfy_ban_log']];
        together.forEach(pair => {
          const home = clusters.find(c => keysIn(c).indexOf(pair[0]) >= 0);
          if (!home || keysIn(home).indexOf(pair[1]) < 0) {
            errors.push(pair[0] + ' and ' + pair[1] + ' are not in the same cluster');
          }
        });
      } catch (e) { errors.push('the bands check itself failed: ' + e.message); }
      // An ntfy address is a server, a topic and whichever credentials that
      // server wants. Typed as one line it is the colons and the at-sign that
      // get put in the wrong place, once, and are then not found.
      try {
        const round = [
          ['https://ntfy.sh/plain-topic', 'public'],
          ['https://:tk_abc123@ntfy.falco81.net/zigmon-house', 'token'],
          ['https://falco:a%40b@ntfy.falco81.net/zigmon-house', 'login']
        ];
        round.forEach(pair => {
          const p = w.ntfyParts(pair[0]);
          if (p.mode !== pair[1]) errors.push(pair[0] + ' was read as ' + p.mode);
          if (w.ntfyJoin(p) !== pair[0]) {
            errors.push('taking ' + pair[0] + ' apart and back gave ' + w.ntfyJoin(p));
          }
        });
        if (w.ntfyJoin({mode: 'public', base: 'https://x', topic: ''}) !== '') {
          errors.push('half an address is saved as though it were whole');
        }
        const nt = Array.from(SETQA('.set-item'))
          .find(i => i.querySelector('[data-k="notify_ntfy"]'));
        if (!nt) {
          errors.push('the ntfy address is not on the settings card');
        } else {
          const field = nt.querySelector('[data-k="notify_ntfy"]');
          if (field.tagName === 'INPUT' && field.type !== 'hidden') {
            errors.push('the ntfy address is still one box to type a URL into');
          }
          const sel = nt.querySelector('select');
          const shown = () => Array.from(nt.querySelectorAll('.compose-row label'))
            .map(l => l.textContent).join('|');
          sel.value = 'token';
          sel.onchange();
          await wait(80);
          if (!/token/i.test(shown()) || /password/i.test(shown())) {
            errors.push('the token choice shows the wrong boxes: ' + shown());
          }
          sel.value = 'login';
          sel.onchange();
          await wait(80);
          if (!/user/i.test(shown()) || !/password/i.test(shown()) || /token/i.test(shown())) {
            errors.push('the user choice shows the wrong boxes: ' + shown());
          }
          sel.value = 'public';
          sel.onchange();
          await wait(80);
          if (/token|password/i.test(shown())) {
            errors.push('the public choice still asks for credentials: ' + shown());
          }
        }
      } catch (e) { errors.push('the ntfy address check itself failed: ' + e.message); }
      // A panel holds values nobody chose the length of - a list of
      // addresses, a key, a path - and without a rule to break them they run
      // out the side of the box and over whatever is behind it.
      try {
        const sheet = Array.from(d.querySelectorAll('style'))
          .map(x => x.textContent).join('\n');
        const rule = function (selector) {
          const at = sheet.indexOf(selector);
          if (at < 0) return '';
          return sheet.slice(at, sheet.indexOf('}', at));
        };
        [['.sethelp{', 'the help panel'], ['#attnbody, #attnbody *', 'a dialogue']].forEach(function (pair) {
          const body = rule(pair[0]);
          if (!/overflow-wrap|word-break/.test(body)) {
            errors.push(pair[1] + ' has no rule for a word that does not fit');
          }
        });
        if (!/max-width:min\(/.test(rule('.sethelp{'))) {
          errors.push('the help panel can be wider than a narrow window');
        }
      } catch (e) { errors.push('the wrapping check itself failed: ' + e.message); }
      // A setting's words are escaped as text, which is right - that is how a
      // value with a bracket in it stays a value. A few were written with a
      // little markup in them and appeared as markup; three harmless tags are
      // let back in afterwards, and nothing else is.
      try {
        const dressed = w.richText('the list <code>10, 60</code> or <i>forever</i>');
        if (dressed.indexOf('<code>') < 0 || dressed.indexOf('<i>') < 0) {
          errors.push('the help panel shows its own markup as words: ' + dressed);
        }
        const nasty = w.richText('a <script>alert(1)</script> and <img src=x onerror=1>');
        if (nasty.indexOf('<script') >= 0 || nasty.indexOf('<img') >= 0) {
          errors.push('the help panel lets a tag through that is not on the list: ' + nasty);
        }
        const spotted = Array.from(d.querySelectorAll('.sethelp, #attnbody'))
          .map(n => n.textContent).join(' ');
        if (/<(code|i|b|br)>/.test(spotted)) {
          errors.push('a panel is showing a tag as text rather than drawing it');
        }
      } catch (e) { errors.push('the markup check itself failed: ' + e.message); }
      // The shield already means the router is carrying an address. A second
      // meaning on the same mark is worse than no mark - it becomes a mark
      // that has to be asked about - so a list somebody else keeps has one of
      // its own.
      try {
        const page = Array.from(d.querySelectorAll('script')).map(x => x.textContent).join('');
        if (/from_feed \? ' \\ud83d\\udee1/.test(page) || /from_feed\).*udee1/.test(page)) {
          errors.push('a list is marked with the shield, which already means the router carries it');
        }
      } catch (e) { errors.push('the mark check itself failed: ' + e.message); }
      // A label's "for" must name a form element. Five of ours named a span
      // that a switch is drawn into, or an id that is on nothing at all: the
      // browser cannot tie them together, clicking the word does nothing, and
      // a screen reader reads the two as unrelated. Chrome says so in Issues.
      try {
        const FIELDS = 'input,select,textarea,button,meter,output,progress,fieldset';
        const wrong = Array.from(d.querySelectorAll('label[for]')).filter(l => {
          const target = d.getElementById(l.htmlFor);
          return !target || !target.matches(FIELDS);
        });
        if (wrong.length) {
          errors.push(wrong.length + ' label(s) point at something that is not a form field: '
            + wrong.slice(0, 3).map(l => l.htmlFor).join(', '));
        }
      } catch (e) { errors.push('the label check itself failed: ' + e.message); }
      // One kind of explanation, not two. A title left on an element shows the
      // browser's own white box on top of the page's dark one, saying the
      // same thing in a different face - which is what somebody sees.
      try {
        // the page sweeps titles away on a slow beat; a walk that lands
        // between two beats saw whatever was set in that moment, and the
        // check failed for the timing rather than for a fault
        if (w.explainLongTitles) w.explainLongTitles(d);
        const stillTitled = Array.from(d.querySelectorAll('[title]'))
          .filter(n => String(n.getAttribute('title') || '').trim());
        if (stillTitled.length) {
          errors.push(stillTitled.length + ' element(s) still show the browser\'s own tooltip: '
            + stillTitled.slice(0, 3).map(n => n.tagName.toLowerCase() + ' "'
              + String(n.title).slice(0, 28) + '"').join(', '));
        }
        const explained = d.querySelectorAll('[data-explains]');
        if (explained.length < 100) {
          errors.push('only ' + explained.length + ' element(s) explain themselves; the sweep '
            + 'is not reaching the page');
        }
        // and what a screen reader is left with
        const first = explained[0];
        if (first && !first.getAttribute('aria-label')) {
          errors.push('taking the title away left nothing for a screen reader');
        }
      } catch (e) { errors.push('the one-kind-of-tooltip check itself failed: ' + e.message); }
      // Every mark in the Public API section answers the pointer in the same
      // words as the rest of the page. A mark nobody can read is a mark that
      // has to be asked about.
      try {
        const wasApprovals = w.APPROVALS;
        w.APPROVALS = {
          waiting: [{link: 'Osoby', what: 'tell you something', who: '89.24.5.7',
                     left: 60, ticket: 't1'}],
          recent: [{ts: 1, state: 'done', link: 'Osoby', what: 'x', way: 'by a header',
                    factor: 'Duo', device: 'iPhone16', who: '192.168.40.170', country: 'CZ'},
                   {ts: 2, state: 'refused', link: 'Svetla', what: 'x', way: 'by its address',
                    factor: 'none', who: '45.9.148.9', country: 'NL'}],
          matched: 2, total: 2, blocked: [], blockedPast: [], blocklistOn: true};
        if (w.paintApprovals) w.paintApprovals(true);
        // ...and every kind of row the whole tab can show, at once: the
        // blocked lists both ways, the counters, the story, the presses
        w.APPROVALS.blocklistOn = true;
        w.APPROVALS.blocked = [
          {ip: '77.90.185.226', why: 'x', since: 1, hits: 1, forever: true, auto: true, left: 0,
           on_feeds: ['firehol1'], from_feed: 'firehol1', country: 'DE', router: 'yes'},
          {ip: '1.1.1.1', why: 'added by hand', since: 1, hits: 1, left: 600, auto: false,
           country: 'AU', router: 'no', router_trouble: 'x', from_proxy: true},
          {ip: '192.168.40.5', why: 'x', since: 1, hits: 1, left: 600, auto: true, spared: 'the house'}];
        w.APPROVALS.counters = [
          {ip: '5.5.5.5', score: 9, bar: 15, tries: 3, spread: 2, last: 1, from_proxy: true,
           kinds: [{kind: 'proxy-poking', n: 3, words: 'w'}]}];
        w.APPROVALS.blockedPast = [
          {ts: 1, ip: '77.90.185.226', what: 'blocked', why: 'x (seen at the server in front)',
           by: '', auto: 1, country: 'DE', from_feed: 'firehol1'},
          {ts: 2, ip: '6.6.6.6', what: 'blocked', why: 'x (seen at the notification server)',
           by: '', auto: 1},
          {ts: 3, ip: '1.1.1.1', what: 'let back in', why: 'taken off', by: '192.168.40.12', auto: 0}];
        w.BLOCKSTORY.total = 3;
        w.paintBlocked(true);
        if (w.paintWatched) w.paintWatched();
        Array.from(d.querySelectorAll('#blocked-list .listed-head')).forEach(h => h.click());
        const tab = d.getElementById('tab-approvals');
        const shutAgain = () => { if (w.FOLDS) Object.keys(w.FOLDS).forEach(k => { w.FOLDS[k].open = false; }); };
        const marks = Array.from(tab.querySelectorAll('.appr-icon, .cflag, .road'))
          .filter(m => m.textContent.trim());
        if (marks.length < 20) errors.push('the Public API tab draws only ' + marks.length + ' marks');
        const silent = marks.filter(m => !(m.dataset.explains || m.querySelector('[data-explains]')));
        if (silent.length) {
          errors.push(silent.length + ' mark(s) on the Public API tab say nothing to the pointer: '
            + silent.slice(0, 4).map(m => JSON.stringify(m.textContent.slice(0, 12))).join(' '));
        }
        shutAgain();
        w.APPROVALS = wasApprovals;
        if (w.paintApprovals) w.paintApprovals(true);
        w.paintBlocked(true);
      } catch (e) { errors.push('the Public API marks check itself failed: ' + e.message); }
      const wasFetch = w.fetch;
      const wasFetchTop = (u, o) => fetch(new URL(u, base).href, o);
      // Three hundred messages were being fetched on every tick, several
      // times a second, for a log nobody had added to. The daemon says how
      // many there are and when the newest landed; ask only when one of those
      // moves, or when the filter changes, or when something was deleted.
      try {
        let asked = 0;
        const wasF = w.fetch;
        w.fetch = (u, o) => { if (/api=sms-log/.test(String(u))) asked++; return wasF(u, o); };
        const st = {sms: {log_n: 3, log_at: 1789734000}};
        for (let i = 0; i < 8; i++) w.renderSmsLog(st);
        if (asked > 1) errors.push('eight ticks fetched the SMS log ' + asked + ' times');
        asked = 0;
        w.renderSmsLog({sms: {log_n: 4, log_at: 1789734100}});
        if (asked !== 1) errors.push('a new message did not fetch the log: ' + asked);
        asked = 0;
        w.renderSmsLog({sms: {log_n: 4, log_at: 1789734100}}, true);
        if (asked !== 1) errors.push('a forced redraw did not fetch the log: ' + asked);
        w.fetch = wasF;
      } catch (e) { errors.push('the SMS-log fetch check itself failed: ' + e.message); }
      // A list of addresses, one per line: kept as commas for the daemon,
      // shown as lines on the card. Somebody typing untidily - a blank line,
      // a trailing comma, spaces - is not a mistake to be refused.
      try {
        const wrap = w.addressList('never_block',
          {value: '192.168.40.0/24, 2a01:430::/48, 89.24.9.9'}, function () {});
        const box = wrap.querySelector('textarea');
        if (!box) { errors.push('the address list has no box to type in'); }
        else {
          if (box.value.split('\n').length !== 3) {
            errors.push('three addresses came out as ' + box.value.split('\n').length + ' line(s)');
          }
          if (!box.dataset.list) errors.push('the address list would be saved as one line');
          box.value = '192.168.40.0/24\n\n  10.0.0.5  \n2a01:430::/48,\n';
          box.oninput();
          const many = box.value.split(/[\n,]/).map(x => x.trim()).filter(x => x);
          if (many.join(', ') !== '192.168.40.0/24, 10.0.0.5, 2a01:430::/48') {
            errors.push('an untidily typed list came out as: ' + many.join(', '));
          }
          if (!/3 addresses/.test(wrap.querySelector('.addrcount').textContent)) {
            errors.push('the count under the box is wrong: '
              + wrap.querySelector('.addrcount').textContent);
          }
        }
      } catch (e) { errors.push('the address-list check itself failed: ' + e.message); }
      // A button asking for an icon that does not exist gets an empty <svg>
      // and no complaint: the Back and Next inside the folds asked for "left"
      // and "right", which are called prev and next, and came out bare.
      try {
        const named = Array.from(d.querySelectorAll('script'))
          .map(x => x.textContent).join('');
        const iconNames = new Set();
        const block = named.slice(named.indexOf('var ICONS'), named.indexOf('var ICONS') + 14000);
        (block.match(/^\s{2}([a-z][a-z0-9]{1,14}):/gm) || []).forEach(
          m => iconNames.add(m.trim().replace(':', '')));
        const asked = (named.match(/cmdButton\([^,]+,\s*'([a-z][a-z0-9]{1,14})'/g) || [])
          .map(m => m.replace(/.*'([a-z0-9]+)'.*/, '$1'));
        const missing = Array.from(new Set(asked.filter(name => !iconNames.has(name))));
        if (missing.length) {
          errors.push('button(s) ask for icon(s) that do not exist: ' + missing.join(', '));
        }
      } catch (e) { errors.push('the icon-name check itself failed: ' + e.message); }
      // What Suricata said has to reach all three places somebody reads an
      // address: the blocked row, the history, and the box you ask with. It
      // was on the router sheet alone, which is the one nobody opens unless
      // they are already thinking about the router.
      try {
        const wasA = w.APPROVALS;
        const ids = {sid: 2034647, rev: 2, confidence: 'High',
                     rule: {msg: 'ET EXPLOIT log4j', classtype: 'attempted-admin',
                            looks_for: ['${jndi:ldap://']},
                     links: [{what: 'CVE-2021-44228',
                              where: 'https://nvd.nist.gov/vuln/detail/CVE-2021-44228'}]};
        w.APPROVALS = {blocklistOn: true, blocked: [
          {ip: '9.9.9.9', why: 'Suricata saw', since: 1, hits: 1, forever: true, auto: true,
           from_ids: true, from_proxy: true, country: 'US', ids: ids}],
          blockedPast: [{ts: 1, ip: '9.9.9.9', what: 'blocked', why: 'Suricata saw an attack',
                         auto: 1, country: 'US', from_ids: true, ids: ids}]};
        w.BLOCKSTORY.total = 1;
        w.paintBlocked(true);
        Array.from(d.querySelectorAll('#blocked-list .listed-head')).forEach(h => h.click());
        const row = d.querySelector('#blocked-list .appr-row');
        if (!row || row.textContent.indexOf('2034647') < 0) {
          errors.push('a blocked row does not name the rule that fired');
        }
        if (!row || !row.querySelector('a.cve')) {
          errors.push('a blocked row does not link what the rule is about');
        }
        const storyRow = d.querySelector('#blocked-past tbody tr');
        if (!storyRow || storyRow.textContent.indexOf('2034647') < 0) {
          errors.push('the history does not name the rule that fired');
        }
        w.drawLook({ip: '9.9.9.9', known: true, country: 'US', feed: '', blocked: true,
                    forever: true, lines: 3, spread: 2, first: 1, last: 2, score: 16, bar: 15,
                    asked: [], ids: ids});
        const asked = d.getElementById('look-out');
        if (!asked || asked.textContent.indexOf('2034647') < 0) {
          errors.push('the asking box does not say what Suricata saw');
        }
        if (!asked || !asked.querySelector('a.cve')) {
          errors.push('the asking box does not link what the rule is about');
        }
        if (asked) asked.innerHTML = '';
        if (w.FOLDS) Object.keys(w.FOLDS).forEach(k => { w.FOLDS[k].open = false; });
        w.APPROVALS = wasA;
        w.paintBlocked(true);
      } catch (e) { errors.push('the Suricata-in-the-UI check itself failed: ' + e.message); }
      // The relay forwarded the query string and nothing else, as a GET - so
      // a modem POSTing its message in a body, which every one of them does,
      // arrived empty and was refused for having the wrong word.
      try {
        const asJson = await wasFetchTop('index.php?api=sms-incoming', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({secret: 'nope', number: '+420', text: 'aGk='})});
        const said = await asJson.text();
        if (asJson.status === 403 && /wrong|word we agreed|switched off|no word/.test(said)) {
          // it reached the daemon and was judged there, which is the point
        } else if (asJson.status === 404 || asJson.status === 405) {
          errors.push('a pushed message never reaches the daemon: ' + asJson.status);
        }
        const asForm = await wasFetchTop('index.php?api=sms-incoming', {
          method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
          body: 'secret=nope&number=%2B420&text=aGk%3D'});
        if (asForm.status === 404 || asForm.status === 405) {
          errors.push('a pushed message sent as a form never reaches the daemon');
        }
      } catch (e) { errors.push('the SMS push check itself failed: ' + e.message); }
      // Two views hold addresses, so the daemon refuses them without the PIN.
      // The tab asked for them twice a second anyway, locked or not - 1,754
      // refusals from one browser in an afternoon, 594 in the worst hour, and
      // nothing on the screen either way.
      try {
        const wasToken = w.LOCK.who;
        let asked = [];
        // the request is counted and answered here, not let out: a real one
        // lands later and repaints over whatever the next check has set up,
        // which is how this walk started failing in a place it does not touch
        w.fetch = (u, o) => {
          const where = String(u);
          if (/api=(blocked|approvals)/.test(where)) {
            asked.push(where);
            return Promise.resolve({ok: true, status: 200,
                                    json: () => Promise.resolve({ok: true}),
                                    text: () => Promise.resolve('{"ok":true}')});
          }
          return wasFetch(u, o);
        };
        w.LOCK.who = null;
        w.APPROVALS.refused = false;
        w.APPROVALS.inflight = 0; w.APPROVALS.again = false;   // (4.95) nothing of the page's own still on its way
        asked = [];
        for (let i = 0; i < 5; i++) w.loadApprovals(true);
        if (asked.length > 2) {
          errors.push('locked, the tab asked ' + asked.length + ' times for views that are refused');
        }
        w.LOCK.who = wasToken;
        w.APPROVALS.refused = false;
        if (w.isUnlocked()) {
          asked = [];
          w.APPROVALS.inflight = 0; w.APPROVALS.again = false;
          w.loadApprovals(true);
          w.loadApprovals(true);
          // (4.95) one pair at a time: the second ask waits for the first
          // pair to land and is made then - asked, not dropped
          await new Promise(r => setTimeout(r, 100));
          if (asked.length < 4) {
            errors.push('unlocked, the tab stopped asking for them altogether');
          }
        }
        w.fetch = wasFetch;
      } catch (e) {
        errors.push('the locked-polling check itself failed: ' + e.message);
      } finally {
        if (w.fetch !== wasFetch) w.fetch = wasFetch;
      }
      // A search that matches nothing must not take the search box away with
      // it: emptying the whole section on an empty answer left somebody
      // looking at a blank card with no way to clear what they had typed.
      try {
        const wasApprovals = w.APPROVALS;
        const wasText = w.BLOCKSTORY.text;
        w.APPROVALS = {blocked: [], blocklistOn: true, blockedPast: [
          {ts: 1, ip: '89.24.5.7', what: 'blocked', why: 'a wrong secret', by: ''}]};
        w.BLOCKSTORY.total = 1;
        w.BLOCKSTORY.text = '';
        w.paintBlocked(true);
        const box = () => d.querySelector('#blocked-past input[type=search]');
        if (!box()) errors.push('the story has no box to search it with');
        w.BLOCKSTORY.text = 'nonsense';
        w.APPROVALS.blockedPast = [];
        w.paintBlocked(true);
        if (!box()) {
          errors.push('a search matching nothing takes the search box away with it');
        } else if (box().value !== 'nonsense') {
          errors.push('the box forgot what was typed into it');
        }
        if (!d.querySelector('#blocked-past .btnhelp')) {
          errors.push('a search matching nothing says nothing at all');
        }
        w.BLOCKSTORY.text = wasText;
        w.APPROVALS = wasApprovals;
        w.paintBlocked(true);
      } catch (e) { errors.push('the story search check itself failed: ' + e.message); }
      // The ones somebody else's list already knew go into a fold of their
      // own, shut to begin with: there will be a great many of them in time,
      // and a long list of them buries the handful that are here for what
      // they did here.
      try {
        const many = [];
        for (let i = 0; i < 60; i++) {
          many.push({ip: '45.9.148.' + i, why: '1 in 10 min', since: 1, hits: 1, forever: true,
                     on_feeds: i % 3 === 0 ? ['firehol1', 'blocklist_de'] : ['firehol1'],
                     from_feed: 'firehol1', country: i % 2 ? 'NL' : 'CZ', auto: true, left: 0});
        }
        many.push({ip: '89.24.9.9', why: 'a wrong secret', since: 1, hits: 2, left: 600, auto: true});
        const wasApprovals = w.APPROVALS;
        w.APPROVALS = {blocked: many, blockedPast: [], blocklistOn: true};
        w.paintBlocked(true);
        const host = d.getElementById('blocked-list');
        const loose = Array.from(host.children).filter(c => c.classList.contains('appr-row')).length;
        if (loose !== 0) {
          errors.push(loose + ' row(s) loose on the card; every one belongs in one of the two folds');
        }
        const fold = host.querySelector('.listed-fold');
        if (!fold) throw new Error('the ones on a list are not folded away');
        if (!fold.querySelector('.listed-body').hidden) {
          errors.push('the fold is open to begin with');
        }
        fold.querySelector('.listed-head').click();
        const inside = () => fold.querySelectorAll('.listed-body .appr-row').length;
        if (inside() !== 25) errors.push('a page of the fold holds ' + inside() + ' rather than 25');
        // the same marks on a blocked row as anywhere else: the book for a
        // list, and the country. Both were written into the counters list and
        // never into this one - two renderers, one of them missed.
        const first = fold.querySelector('.listed-body .appr-row');
        const marks = Array.from(first.querySelectorAll('.appr-icon')).map(x => x.textContent).join('');
        if (marks.indexOf('\ud83d\udcd5') < 0) {
          errors.push('a blocked row on a list does not wear the book: ' + marks);
        }
        if (!first.querySelector('.cflag') || !first.querySelector('.cflag').textContent) {
          errors.push('a blocked row does not say which country it is in');
        }
        if (fold.querySelector('.listed-head').textContent.indexOf('Blacklisted IPs') < 0) {
          errors.push('the fold is not called what it holds');
        }
        // two folds of the same shape: what a list knew, and what this house
        // decided on its own. Both get a filter and pages.
        // three folds: what a list already knew, what Suricata saw in the
        // packets, and what this house worked out on its own - and a row
        // belongs to the first of those that is true of it, never to two
        w.APPROVALS.blocked = w.APPROVALS.blocked.concat([
          {ip: '8.8.1.1', why: 'Suricata saw an attack it knows', since: 1, hits: 1,
           forever: true, auto: true, from_ids: true, from_proxy: true, country: 'CN'}]);
        w.paintBlocked(true);
        Array.from(d.querySelectorAll('#blocked-list .listed-head')).forEach(h => h.click());
        const folds = Array.from(d.querySelectorAll('.listed-fold'));
        const names = folds.map(f => f.querySelector('.listed-head').textContent);
        if (!names.some(n => /Blocked by system/.test(n))) {
          errors.push('there is no fold for the ones this house decided about itself');
        }
        if (!names.some(n => /Seen by Suricata/.test(n))) {
          errors.push('there is no fold for the ones Suricata saw');
        }
        const idsFold = folds.find(f => /Seen by Suricata/.test(f.textContent));
        if (idsFold) {
          const dishRow = idsFold.querySelector('.appr-row');
          const dishes = dishRow
            ? Array.from(dishRow.querySelectorAll('.appr-icon')).map(x => x.textContent).join('')
            : '';
          if (dishes.indexOf('\ud83d\udce1') < 0) {
            errors.push('a row Suricata saw wears no dish: ' + dishes);
          }
          if (!idsFold.querySelector('input')) {
            errors.push('the Suricata fold has no box to filter it with');
          }
        }
        folds.forEach(f => {
          if (!f.querySelector('input')) {
            errors.push('a fold has no box to filter it with: '
              + f.querySelector('.listed-head').textContent.slice(0, 30));
          }
        });
        // and the country sits in a column of its own in the story, rather
        // than tacked on to a cell whose text is a different width every row
        // the story's marks sit in fixed slots too: five on every row, filled
        // or not, so a column of them reads down the page
        const storyRows = Array.from(d.querySelectorAll('#blocked-past tbody tr'));
        const storyCounts = new Set(storyRows.map(
          r => (r.querySelector('.story-marks') || {children: []}).children.length));
        if (storyRows.length && (storyCounts.size > 1 || !storyCounts.has(6))) {
          errors.push('the story rows carry ' + Array.from(storyCounts).join(' and ')
            + ' mark slots; they want six each');
        }
        const heads = d.querySelectorAll('#blocked-past thead th').length;
        const row = d.querySelector('#blocked-past tbody tr');
        if (row && row.children.length !== heads) {
          errors.push('the story table has ' + heads + ' headings and ' + row.children.length
            + ' cells, so nothing under them lines up');
        }
        const find = fold.querySelector('input');
        find.value = 'blocklist_de';
        find.oninput();
        if (inside() !== 20) errors.push('filtering by a list name gives ' + inside() + ' of 20');
        find.value = 'nonsense';
        find.oninput();
        if (inside() !== 0) errors.push('a filter matching nothing still shows rows');
        find.value = '';
        find.oninput();
        if (inside() !== 25) errors.push('clearing the filter does not bring the page back');
        w.APPROVALS = wasApprovals;
        w.paintBlocked(true);
      } catch (e) { errors.push('the listed-fold check itself failed: ' + e.message); }
      // an escape written into an HTML attribute is five characters of
      // nonsense, not a dash: the box to ask about an address said
      // "ask about one address \u2014 45.9.148.9" in so many letters
      try {
        const boxes = ['look-ip', 'wifi-seen-find', 'blocked-ip'];
        boxes.forEach(id => {
          const b = d.getElementById(id);
          if (b && /\\u[0-9a-f]{4}/i.test(b.placeholder || '')) {
            errors.push(id + ' shows an escape in its placeholder: ' + b.placeholder);
          }
        });
        const visible = Array.from(d.querySelectorAll('input[placeholder], [title]'))
          .map(n => (n.placeholder || '') + ' ' + (n.title || '')).join(' ');
        const anywhere = visible.match(/\\u[0-9a-f]{4}/i);
        if (anywhere) errors.push('an escape is shown to somebody: ' + anywhere[0]);
      } catch (e) { errors.push('the placeholder check itself failed: ' + e.message); }
      // where an address was seen: the globe for anything read off the server
      // in front, the bell beside it for the notification server's own logs,
      // a house for what this machine saw itself
      try {
        const wasA = w.APPROVALS;
        w.APPROVALS = {blocklistOn: true, blockedPast: [], blocked: [
          {ip: '1.1.1.1', why: 'x', since: 1, hits: 1, forever: true, auto: true, from_proxy: true},
          {ip: '2.2.2.2', why: 'x', since: 1, hits: 1, forever: true, auto: true,
           from_proxy: true, from_ntfy: true},
          {ip: '3.3.3.3', why: 'a wrong secret', since: 1, hits: 1, left: 60, auto: true}]};
        w.paintBlocked(true);
        Array.from(d.querySelectorAll('#blocked-list .listed-head')).forEach(h => h.click());
        const marksOf = ip => {
          const row = Array.from(d.querySelectorAll('#blocked-list .appr-row'))
            .find(r => (r.querySelector('.appr-link') || {}).textContent === ip);
          return row ? Array.from(row.querySelectorAll('.appr-slot'))
            .map(x => x.textContent).join('') : '';
        };
        if (marksOf('1.1.1.1').indexOf('\ud83c\udf10') < 0) {
          errors.push('something read off the server in front wears no globe');
        }
        if (marksOf('2.2.2.2').indexOf('\ud83d\udd14') < 0
            || marksOf('2.2.2.2').indexOf('\ud83c\udf10') < 0) {
          errors.push('the notification server wants the globe AND the bell: ' + marksOf('2.2.2.2'));
        }
        if (marksOf('3.3.3.3').indexOf('\ud83c\udfe0') < 0) {
          errors.push('something this machine saw itself wears no house: ' + marksOf('3.3.3.3'));
        }
        if (marksOf('3.3.3.3').indexOf('\ud83c\udf10') >= 0) {
          errors.push('something seen here is marked as read off the server in front');
        }
        if (w.FOLDS) Object.keys(w.FOLDS).forEach(k => { w.FOLDS[k].open = false; });
        w.APPROVALS = wasA;
        w.paintBlocked(true);
      } catch (e) { errors.push('the where-it-was-seen check itself failed: ' + e.message); }
      // two letters into a flag, and a box to ask about one address
      try {
        if (w.flagOf('CZ') !== '\u{1F1E8}\u{1F1FF}') {
          errors.push('two letters do not become a flag: ' + w.flagOf('CZ'));
        }
        // the flag is a picture served from this house, with the two letters
        // beside it - so it looks the same everywhere and needs no internet
        const badge = w.countryBadge('CZ');
        const pic = badge.querySelector('img');
        if (!pic) errors.push('a country badge carries no picture');
        else if (!/^flags\/[a-z]{2}\.svg$/.test(pic.getAttribute('src'))) {
          errors.push('the flag picture is fetched from somewhere other than this house: '
            + pic.getAttribute('src'));
        }
        if (!badge.querySelector('.cflag-cc')) errors.push('a badge has no letters beside the picture');
        if (w.flagOf('') !== '' || w.flagOf('nonsense') !== '') {
          errors.push('something that is not two letters was turned into a flag');
        }
        if (!d.getElementById('look-ip') || !d.getElementById('look-go')) {
          errors.push('there is nowhere to ask about one address');
        }
        // the flag is a picture served from this house, with the two letters
        // beside it - so it looks the same everywhere and needs no internet
        const czBadge = w.countryBadge('CZ');
        const czPic = czBadge.querySelector('img');
        if (!czPic) errors.push('a country badge carries no picture');
        else if (!/^flags\/[a-z]{2}\.svg$/.test(czPic.getAttribute('src'))) {
          errors.push('the flag picture is fetched from somewhere other than this house: '
            + czPic.getAttribute('src'));
        }
        if (!czBadge.querySelector('.cflag-cc')) errors.push('a badge has no letters beside the picture');
        // every blocked row has the same number of mark slots, filled or not,
        // so the addresses start at the same place down the page
        const rowsWithMarks = Array.from(d.querySelectorAll('#blocked-list .appr-row'));
        const counts = new Set(rowsWithMarks.map(r => r.querySelectorAll('.appr-slot').length));
        if (rowsWithMarks.length && counts.size > 1) {
          errors.push('the rows have ' + Array.from(counts).join(' and ')
            + ' mark slots, so the addresses do not line up');
        }
        rowsWithMarks.forEach(r => {
          if (!r.querySelector('.appr-marks')) {
            errors.push('a blocked row draws its marks loose rather than in slots');
          }
        });
      } catch (e) { errors.push('the flag check itself failed: ' + e.message); }
      // the filter over what the air has been heard to carry
      try {
        const heard = [
          {ssid: 'UPC1234567', bssid: 'aa:bb:cc:00:11:22', band: 5, channel: 36,
           security: 'WPA2', best: -61, times: 12, first: 1, last: 2},
          {ssid: 'Sousedi_2G', bssid: 'aa:bb:cc:00:11:33', band: 2.4, channel: 6,
           security: 'WPA2/WPA3', best: -77, times: 3, first: 1, last: 2},
          {ssid: '', bssid: 'de:ad:be:ef:00:01', band: 5, channel: 100,
           security: 'open', best: -88, times: 1, first: 1, last: 2}
        ];
        w.WIFI_SEEN_OPEN = true;
        w.paintWifiSeen(heard);
        const box = d.getElementById('wifi-seen-find');
        if (!box) throw new Error('there is nowhere to type a filter');
        const shown = () => d.querySelectorAll('#wifi-seen .oth-row:not(.head)').length;
        const type = t => { box.value = t; box.oninput(); };
        if (shown() !== 3) errors.push('the history does not draw what it was given');
        type('upc');
        if (shown() !== 1) errors.push('a filter in the wrong case finds nothing: ' + shown());
        type('WPA2 2.4');
        if (shown() !== 1) errors.push('two words are not both required: ' + shown());
        type('de:ad');
        if (shown() !== 1) errors.push('a BSSID is not matched: ' + shown());
        type('nonsense');
        if (shown() !== 0) errors.push('a filter matching nothing still shows rows');
        type('');
        if (shown() !== 3) errors.push('clearing the filter does not bring them back');
        w.WIFI_SEEN_OPEN = false;
      } catch (e) { errors.push('the wifi filter check itself failed: ' + e.message); }
      // Settings: a label of a few words, and the long word under the pointer
      // with the key it has in config.json and whether the file is what is
      // running. A label that runs to a paragraph is the page doing the
      // tooltip's job.
      try {
        d.querySelector('#control-nav button[data-sec="sys-backup"]').click();
        await wait(900);
        const setItems = Array.from(SETQA('.set-item'));
        if (setItems.length < 50) errors.push('the settings drew only ' + setItems.length + ' items');
        const tooLong = setItems
          .map(i => ((i.querySelector('label') || {}).textContent || ''))
          .filter(l => l.length > 60);
        if (tooLong.length) {
          errors.push(tooLong.length + ' setting label(s) longer than a label should be: '
            + tooLong[0].slice(0, 40));
        }
        const heads = Array.from(SETQA('.set-head')).map(h => h.textContent.trim());
        const asKey = heads.filter(h => /^[a-z_]+$/.test(h));
        if (asKey.length) errors.push('a settings section is headed by a key name: ' + asKey.join(', '));
        const probe = setItems.find(i => i.querySelector('[data-k="stale_warn_min"]'));
        if (!probe) {
          errors.push('a known setting is not on the page');
        } else {
          probe.onmouseenter();
          await wait(100);
          const tip = d.querySelector('.sethelp');
          if (!tip || tip.style.display !== 'block') errors.push('no popup on a setting');
          else if (tip.textContent.indexOf('stale_warn_min') < 0
                   || tip.textContent.indexOf('config.json') < 0) {
            errors.push('the popup does not name the key in config.json');
          }
          probe.onmouseleave();
        }
      } catch (e) { errors.push('the settings check itself failed: ' + e.message); }
      // The lists somebody else keeps are three columns of one grid, with the
      // rows themselves display:contents - so a row carrying a fourth cell
      // takes the next row's first column and shifts every list under it.
      // A message about a list that would not download did exactly that.
      try {
        d.querySelector('#control-nav button[data-sec="sec-block"]').click();
        await wait(900);
        const feedRows = Array.from(SETQA('.feedrow'));
        if (feedRows.length < 3) errors.push('the lists somebody else keeps drew only ' + feedRows.length + ' rows');
        feedRows.forEach(row => {
          const cells = Array.from(row.children);
          const loose = cells.slice(3).filter(c => !c.classList.contains('feedbad')
            && !c.classList.contains('feedterms'));
          if (cells.length < 3) errors.push('a list row has only ' + cells.length + ' cells');
          if (loose.length) {
            errors.push('a list row carries ' + loose.length + ' cell(s) past the three columns, '
              + 'which shifts every row under it: ' + (loose[0].className || loose[0].tagName));
          }
          if (cells[0] && cells[0].tagName !== 'LABEL') errors.push('a list row does not start with its name');
          if (cells[1] && !cells[1].classList.contains('switch') && !cells[1].querySelector('input')) {
            errors.push('the second cell of a list row is not its switch');
          }
        });
        // The mark that says a setting needs the internet is a globe beside
        // the label - the icon alone. The word "internet" beside it cost
        // forty pixels in every label that had one, which wrapped the labels
        // and shifted every box under them out of line.
        const netted = Array.from(SETQA('.set-item label .net-mark'));
        if (netted.length < 4) errors.push('only ' + netted.length + ' setting(s) are marked as needing the internet');
        // the title may already have become the page's own panel, which is
        // where the words live then
        const untold = netted.filter(m => !/internet/i.test((m.getAttribute('title') || '')
          + ' ' + (m.dataset.said || '') + ' ' + (m.getAttribute('aria-label') || '')));
        if (untold.length) errors.push(untold.length + ' internet mark(s) say nothing under the pointer');
        const wordy = netted.filter(m => (m.textContent || '').trim().length);
        if (wordy.length) errors.push(wordy.length + ' internet mark(s) carry words as well as the globe');
      } catch (e) { errors.push('the lists check itself failed: ' + e.message); }
      // and the same panel everywhere else: anything carrying more than a
      // label's worth of title says it in the page's own words rather than in
      // the browser's tooltip, which waits a second and cannot be reached at
      // all on a touchscreen
      // the page sweeps titles away on a slow beat; a walk that lands between
      // two beats saw whatever was set in that moment, so it is swept here
      // first and the check is about faults rather than about timing
      if (w.explainLongTitles) w.explainLongTitles(d);
      const plainLong = Array.from(d.querySelectorAll('[title]'))
        .filter(n => !n.dataset.explains && String(n.title).length >= 55);
      if (plainLong.length) {
        errors.push(plainLong.length + ' long tooltip(s) left to the browser: '
          + String(plainLong[0].title).slice(0, 40));
      }
      if (d.querySelectorAll('[data-explains]').length < 30) {
        errors.push('almost nothing on the page carries the help panel');
      }
      // Every control, not only the buttons: a box, a switch, a dropdown, a
      // file picker. One that is wrapped by something already explained is
      // taken as explained - the panel opens over the whole row.
      // the named ones: a control with an id is a control somebody meant,
      // rather than one of hundreds drawn from a list
      await wait(300);                       // the sweep runs a moment after a drawing
      const bareControls = Array.from(d.querySelectorAll('[id]'))
        .filter(n => /^(input|textarea|select)$/i.test(n.tagName)
                  || (n.tagName === 'BUTTON' && n.classList.contains('btn')))
        .filter(n => !n.title && !n.dataset.explains
                  && !n.closest('[data-explains]')
                  && !n.closest('.tabs') && !n.closest('#control-nav'));
      if (bareControls.length > 8) {
        errors.push(bareControls.length + ' control(s) with nothing said about them, e.g. '
          + bareControls.slice(0, 3).map(n => (n.id || n.tagName.toLowerCase())).join(', '));
      }
      // a dropdown that says nothing at all: a list of names with no word
      // about what choosing one of them does
      const bareSelects = Array.from(d.querySelectorAll('select'))
        .filter(x => !x.title && !x.dataset.explains);
      if (bareSelects.length) {
        errors.push(bareSelects.length + ' dropdown(s) with nothing said about them: '
          + bareSelects.map(x => x.id || '(unnamed)').slice(0, 4).join(', '));
      }
      // and the buttons that do something a person might hesitate over
      ['blocked-clear', 'blocked-forget', 'db-prune', 'db-upload', 'backup-export-secrets',
       'stale-drop', 'reset-device-btn', 'join-toggle'].forEach(id => {
        const b = d.getElementById(id);
        if (b && !b.title && !b.dataset.explains) {
          errors.push('a button that cannot be undone says nothing about itself: ' + id);
        }
      });
      console.log('approvals: a tab of its own, %d waiting, %d button(s) all with icons',
        d.querySelectorAll('.appr-row').length, btns.length);
    }
  } catch (e) { errors.push('the approvals check itself failed: ' + e.message); }

  // ---- a secret is never written into its own box --------------------------
  // The daemon says only whether a secret is set, not what it is. Writing
  // what it says into the box put the word "true" there, and saving wrote
  // that word over the secret - every one of them, in four releases.
  try {
    d.querySelector('.tabs button[data-tab="control"]').click(); await wait(300);
    const sys1 = d.querySelector('#control-nav button[data-sec="sys-backup"]');
    if (sys1) { sys1.click(); await wait(1200); }
    const secrets = Array.from(SETQA('input[type="password"][data-k]'));
    if (!secrets.length) errors.push('no secret is drawn in the settings at all');
    const filled = secrets.filter(b => b.value !== '').map(b => b.dataset.k);
    if (filled.length) errors.push('a secret is written into its own box: ' + filled.join(', '));
    if (secrets.some(b => !b.dataset.secret)) {
      errors.push('a secret box is not marked, so saving would send it as empty');
    }
    console.log('settings: %d secret(s), none of them written into its box', secrets.length);
  } catch (e) { errors.push('the secret-box check itself failed: ' + e.message); }

  // ---- a contract SIM has no credit, and is not asked about it -------------
  try {
    d.querySelector('.tabs button[data-tab="control"]').click(); await wait(300);
    const sys0 = d.querySelector('#control-nav button[data-sec="msg-sms"]');
    if (sys0) { sys0.click(); await wait(1200); }
    const was = (((w.STATE.status || {}).runtime_config || {}).sms_sim || {}).value || 'prepaid';
    const setSim = async kind => {
      await jfetch(base + 'index.php?api=config-save', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin: '1234', sms_sim: kind }) });
      w.forgetSig('sms'); w.tick(true);
      // until the house says so, not for a fixed while: under a full walk the
      // status can take two seconds to come round, and a fixed wait read the
      // card as it was before the change
      for (let i = 0; i < 60; i++) {
        await wait(100);
        if ((((w.STATE.status || {}).runtime_config || {}).sms_sim || {}).value === kind) break;
      }
      w.forgetSig('sms'); w.tick(true); await wait(600);
    };
    await setSim('prepaid');
    if (!d.getElementById('sms-f-sms_sim')) errors.push('the SMS card does not ask what kind of SIM it is');
    if (!d.getElementById('sms-f-sms_credit_code')) errors.push('a prepaid SIM is not asked for its credit code');
    await setSim('contract');
    if (d.getElementById('sms-f-sms_credit_code') || d.getElementById('sms-f-sms_credit_every_h')) {
      errors.push('a contract SIM is still asked about credit');
    }
    if (!d.getElementById('sms-credit').hidden) errors.push('a contract SIM still offers to ask the network');
    const every = (((w.STATE.status || {}).runtime_config || {}).sms_credit_every_h || {}).value;
    if (every) errors.push('a contract SIM is still asked every ' + every + ' h');
    console.log('a contract SIM: nothing about credit on the card, and nothing asked');
    await setSim(was);
  } catch (e) { errors.push('the SIM check itself failed: ' + e.message); }

  // ---- a text from a number nobody knows, by whichever roads ---------------
  try {
    d.querySelector('.tabs button[data-tab="control"]').click(); await wait(300);
    const sys = d.querySelector('#control-nav button[data-sec="msg-sms"]');
    if (sys) { sys.click(); await wait(1200); }
    const f = d.getElementById('sms-f-sms_stranger_alert');
    if (!f) errors.push('the SMS card no longer asks about a text from a stranger');
    else if (f.tagName.toLowerCase() === 'select') {
      errors.push('a text from a stranger is still chosen from a list of combinations');
    } else {
      const road = k => f.querySelector('input[data-road="' + k + '"]');
      if (!road('ntfy') || !road('telegram') || !road('sms')) {
        errors.push('a text from a stranger has no switch for every road');
      } else {
        road('ntfy').checked = true; road('telegram').checked = false; road('sms').checked = true;
        road('sms').dispatchEvent(new w.Event('change', { bubbles: true }));
        await wait(50);
        if (w.SMS_EDIT.sms_stranger_alert !== 'ntfy,sms') {
          errors.push('ntfy and a text without Telegram cannot be chosen for a stranger: got '
            + w.SMS_EDIT.sms_stranger_alert);
        }
        road('ntfy').checked = false; road('sms').checked = false;
        road('sms').dispatchEvent(new w.Event('change', { bubbles: true }));
        await wait(50);
        if (w.SMS_EDIT.sms_stranger_alert !== '') errors.push('with no road on it is not written down only');
        console.log('a stranger\u2019s text: a switch per road, all eight ways sayable');
      }
    }
  } catch (e) { errors.push('the stranger-roads check itself failed: ' + e.message); }

  // ---- nothing is taken away while somebody is holding it -----------------
  // A live update rebuilds a card, and what was inside it goes: a dropdown
  // that was open shuts, a run of text being copied is lost. Both are held
  // now, at applyStatus, and let go the moment the dropdown shuts or the
  // selection does.
  try {
    d.querySelector('.tabs button[data-tab="control"]').click(); await wait(400);
    const nav = d.querySelector('#control-nav button[data-sec="auto-rules"]');
    if (nav) { nav.click(); await wait(900); }
    const sel = d.querySelector('#taps-list select') || d.querySelector('select');
    if (!sel) {
      console.log('nothing to hold open here - skipped');
    } else {
      sel.dispatchEvent(new w.MouseEvent('mousedown', { bubbles: true }));
      if (!w.userHolding()) errors.push('a dropdown held open does not hold the page');
      w.applyStatus(JSON.parse(JSON.stringify(w.STATE.status)));
      if (!d.contains(sel)) errors.push('a live update rebuilt the card under an open dropdown');
      sel.dispatchEvent(new w.Event('change', { bubbles: true }));
      await wait(300);
      if (w.userHolding()) errors.push('the page is still held after the dropdown shut');
    }
    const words = d.querySelector('.note') || d.querySelector('p');
    const range = d.createRange();
    range.selectNodeContents(words);
    const picked = w.getSelection();
    picked.removeAllRanges(); picked.addRange(range);
    if (!w.userHolding()) errors.push('a run of selected text does not hold the page');
    w.applyStatus(JSON.parse(JSON.stringify(w.STATE.status)));
    if (!d.contains(words) || !String(w.getSelection()).length) {
      errors.push('a live update took away the text that was being copied');
    }
    picked.removeAllRanges();
    if (w.userHolding()) errors.push('the page is still held after the text was let go');
    console.log('held while open or selected, let go afterwards: yes');
  } catch (e) { errors.push('the holding check itself failed: ' + e.message); }

  // ---- nothing carries an empty title -------------------------------------
  // An empty title is still a title attribute, so the four-second sweep that
  // asks "is there a title left anywhere?" answered yes for ever, and walked
  // a page of twenty-seven thousand nodes five times over every four
  // seconds, finding nothing to do. Ninety-odd settings boxes carried one.
  try {
    for (const sec of ['dev-health', 'sec-block', 'sys-data', 'msg-alerts', 'auto-rooms']) {
      const nav = d.querySelector('#control-nav button[data-sec="' + sec + '"]');
      if (nav) { nav.click(); await wait(500); }
    }
    await wait(600);
    const empty = Array.from(d.querySelectorAll('[title]')).filter(e => !String(e.title).trim());
    if (empty.length) {
      errors.push(empty.length + ' thing(s) carry an empty title, e.g. <'
        + empty[0].tagName.toLowerCase() + ' data-k="' + (empty[0].dataset.k || '') + '">');
    }
    console.log('nothing carries an empty title: ' + (empty.length ? 'no, ' + empty.length : 'yes'));
  } catch (e) { errors.push('the empty-title check itself failed: ' + e.message); }

  // ---- the ask-about buttons are a column ---------------------------------
  // Packed in beside the address they ended wherever that address ended - a
  // house address carries none at all - so a page of them was a ragged edge
  // instead of something the eye can run down.
  try {
    for (const id of ['approvals-past', 'blocked-history']) {
      const t = d.getElementById(id);
      if (!t) continue;
      const heads = t.querySelectorAll('thead th').length;
      const asked = t.querySelectorAll('thead th.story-ask').length;
      if (asked !== 1) errors.push(id + ' has ' + asked + ' column(s) for the ask-about buttons');
      Array.from(t.querySelectorAll('tbody tr')).forEach(function (tr, i) {
        if (tr.children.length !== heads) {
          errors.push(id + ' row ' + i + ' has ' + tr.children.length + ' cells for ' + heads + ' columns');
        }
        const inAddress = tr.querySelector('td:not(.story-ask) .intel-btn');
        if (inAddress) errors.push(id + ' row ' + i + ' keeps its ask-about button outside the column');
      });
    }
    console.log('the ask-about buttons live in a column of their own');
  } catch (e) { errors.push('the ask-column check itself failed: ' + e.message); }

  // ---- a list opened by a button stays open -------------------------------
  // Pressing Examples blurs the box on the way, which starts the "shut the
  // list in 150 ms" timer; the button then opened the list, and the timer
  // shut it again a breath later. The button looked broken everywhere.
  try {
    const nav = d.querySelector('#control-nav button[data-sec="msg-alerts"]');
    if (nav) { nav.click(); await wait(800); }
    const btn = Array.from(d.querySelectorAll('button')).filter(b => /Examples/.test(b.textContent))[0];
    // the box this very button writes into, not whichever box came first
    let box = null;
    for (let up = btn && btn.parentElement; up && !box; up = up.parentElement) {
      box = up.querySelector('textarea');
    }
    if (!box || !btn) {
      console.log('no message box to open a list over - skipped');
    } else {
      box.focus(); box.value = 'Ahoj'; box.selectionStart = box.selectionEnd = 4;
      box.dispatchEvent(new w.FocusEvent('blur', { bubbles: false }));   // as a real press does
      btn.onclick({ stopPropagation() {}, preventDefault() {} });
      const opened = d.querySelectorAll('.acbox .ac-item, .acbox .ac-row').length;
      if (!opened) errors.push('the Examples button opened nothing at all');
      await wait(400);
      const left = d.querySelectorAll('.acbox .ac-item, .acbox .ac-row').length;
      if (opened && !left) errors.push('the list the Examples button opened shut itself');
      if (w.closeCompleter) w.closeCompleter();
      console.log('a list opened by a button stays open: ' + opened + ' then ' + left);
    }
  } catch (e) { errors.push('the opened-list check itself failed: ' + e.message); }

  // ---- a ready-made block carries its own braces --------------------------
  // Ctrl+Alt+Space writes the whole block, braces and all. Asked for after a
  // "{" had already been typed, it wrote the block inside that brace and the
  // message began "{{if …"; and once the list was open, typing anything that
  // was not narrowing it left it standing over the text being written, going
  // back to all sixty every time the space bar was pressed.
  try {
    const btn = Array.from(d.querySelectorAll('button')).filter(b => /Examples/.test(b.textContent))[0];
    let box = null;
    for (let up = btn && btn.parentElement; up && !box; up = up.parentElement) box = up.querySelector('textarea');
    if (!box) {
      console.log('no message box to write a block into - skipped');
    } else {
      const rows = () => d.querySelectorAll('.acbox .ac-item, .acbox .ac-row').length;
      const press = () => box.dispatchEvent(new w.KeyboardEvent('keydown',
        { key: ' ', code: 'Space', ctrlKey: true, altKey: true, bubbles: true }));
      const take = () => box.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      const put = (t) => { box.value += t; box.selectionStart = box.selectionEnd = box.value.length;
                           box.dispatchEvent(new w.Event('input', { bubbles: true })); };
      box.focus(); box.value = ''; box.dispatchEvent(new w.Event('input', { bubbles: true }));
      put('{'); await wait(80); press(); await wait(80);
      if (!rows()) errors.push('Ctrl+Alt+Space after a brace offered nothing');
      take(); await wait(120);
      if (/^\{\{/.test(box.value)) errors.push('a block written after a typed brace began "{{": ' + box.value.slice(0, 20));
      // a script's lines are words, not facts in braces, so only a message
      // box is asked for the brace
      const bare = box.dataset && box.dataset.bareWords === '1';
      if (!bare && !/^\{/.test(box.value)) {
        errors.push('a block was written without its own brace: ' + box.value.slice(0, 20));
      }
      if (bare && /^\{/.test(box.value)) {
        errors.push('a script line was written with a brace round it: ' + box.value.slice(0, 20));
      }
      // the list goes when what is typed stops narrowing it
      box.value = ''; box.dispatchEvent(new w.Event('input', { bubbles: true }));
      press(); await wait(80);
      const all = rows();
      put('Dobry den '); await wait(150);
      if (rows() >= all && all) errors.push('the list of blocks stayed open, and whole, over the words being typed');
      if (w.closeCompleter) w.closeCompleter();
      box.value = ''; box.dispatchEvent(new w.Event('input', { bubbles: true }));
      console.log('a block carries its own braces, and the list goes when it stops narrowing');
    }
  } catch (e) { errors.push('the block-brace check itself failed: ' + e.message); }

  // ---- what a text message already understands ----------------------------
  // Families, not a fixed list: each one fills itself from what the house
  // holds, so a room added this morning is on the card this afternoon with a
  // switch of its own. The card must show them, group them by topic, and
  // give every one of them - and every thing it covers - a switch.
  try {
    const nav = d.querySelector('#control-nav button[data-sec="msg-sms"]');
    if (nav) { nav.click(); await wait(1200); }
    for (let i = 0; i < 12 && (!w.SMSBUILT || w.SMSBUILT.rows === null); i++) await wait(500);
    const host = d.getElementById('smsbuiltin-list');
    if (!host) {
      errors.push('the card of what a text message understands is not on the page');
    } else if (!w.SMSBUILT || w.SMSBUILT.rows === null) {
      errors.push('the card never got its list from the daemon');
    } else {
      const groups = host.querySelectorAll('.smshelp-group').length;
      const rows = host.querySelectorAll('.smshelp-row').length;
      if (groups < 3) errors.push('only ' + groups + ' topic(s) of built-in commands');
      if (rows !== (w.SMSBUILT.rows || []).length) {
        errors.push('the card shows ' + rows + ' of ' + (w.SMSBUILT.rows || []).length + ' commands');
      }
      const noSwitch = Array.from(host.querySelectorAll('.smshelp-row'))
        .filter(r => !r.querySelector('.sw input')).length;
      if (noSwitch) errors.push(noSwitch + ' built-in command(s) with no switch');
      // a family that covers things opens to a switch per thing
      const fold = Array.from(host.querySelectorAll('.smshelp-fold'))[0];
      if (!fold) {
        errors.push('no family offers the things it covers');
      } else {
        fold.click(); await wait(300);
        const chips = host.querySelectorAll('.smshelp-thing input').length;
        if (!chips) errors.push('a family opened but showed none of the things it covers');
        // switching one thing off marks the card unsaved and leaves the rest
        const first = host.querySelector('.smshelp-thing input');
        if (first) {
          first.checked = false; first.onchange();
          await wait(200);
          if (!w.SMSBUILT.dirty) errors.push('switching a thing off did not mark the card unsaved');
          const off = host.querySelectorAll('.smshelp-thing.off').length;
          if (off !== 1) errors.push(off + ' thing(s) went off when one was switched');
          first.checked = true; first.onchange(); await wait(150);
          w.SMSBUILT.dirty = false;
          if (d.getElementById('smsbuiltin-note')) d.getElementById('smsbuiltin-note').textContent = '';
        }
      }
      console.log('what a text message understands: ' + rows + ' command(s) in ' + groups
        + ' topic(s), each with a switch');
    }
  } catch (e) { errors.push('the built-in commands check itself failed: ' + e.message); }

  // Every thing is an object (4.86): a mark after its name everywhere it is
  // named as itself, which opens what it is - and nothing else happens when
  // it is pressed, and nothing underneath closes it.
  try {
    w.showTab('devices'); await wait(1200);
    const rows = d.querySelectorAll('#devices-table tbody tr').length;
    const marked = d.querySelectorAll('#devices-table tbody tr td:first-child .obj-mark').length;
    if (!rows || marked !== rows) errors.push('the devices table marks ' + marked + ' of ' + rows + ' names');
    w.showTab('heating'); await wait(1200);
    const rooms = d.querySelectorAll('.heat-title h3').length;
    if (!rooms || d.querySelectorAll('.heat-title h3 .obj-mark').length !== rooms) errors.push('a room on the Heating tab has no mark');
    const heads = Array.from(d.querySelectorAll('.heat-title h3')).map(h => h.textContent);
    if (heads.some(t => /\u2b21|[^\x20-\u024f]/.test(t))) errors.push('a mark put words into a room\'s name: ' + heads.join(', '));
    // the marks carry no text: a name found by its words is still found
    const one = d.querySelector('.heat-title h3');
    if (one && one.textContent !== (w.STATE.status.heating.rooms || [])[0].name) errors.push('a room\'s title reads ' + one.textContent);
    const mark = d.querySelector('.heat-title .obj-mark');
    let seen = 0;
    const card = mark.closest('.card') || mark.parentNode;
    const spy = () => { seen++; };
    card.addEventListener('click', spy);
    mark.click(); await wait(1500);
    card.removeEventListener('click', spy);
    if (seen) errors.push('pressing a mark also pressed what it sits in');
    const pop = d.getElementById('objpop');
    if (!pop || pop.hidden) errors.push('the mark opened nothing');
    else {
      const kinds = Array.from(pop.querySelectorAll('.op-sec')).map(x => x.textContent);
      if (!kinds.some(k => /Properties/.test(k)) || !kinds.some(k => /Functions/.test(k)) || !kinds.some(k => /Procedures/.test(k)))
        errors.push('a room opened without its properties, functions and procedures: ' + kinds.join(' | '));
      if (!/^room:/.test((pop.querySelector('.op-id') || {}).textContent.replace(/^id\s*/, '')))
        errors.push('the object does not show its address');
      w.renderAll(w.STATE.status); await wait(300);
      if (pop.hidden) errors.push('a redraw underneath closed the object view');
      const find = pop.querySelector('.op-find');
      find.value = 'eco'; find.dispatchEvent(new w.Event('input'));
      const left = Array.from(pop.querySelectorAll('.op-row .op-n')).map(x => x.textContent);
      if (!left.length || left.some(n => n.indexOf('eco') < 0)) errors.push('finding a member left ' + left.join(', '));
      d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
      await wait(100);
      if (!pop.hidden) errors.push('Escape did not close the object view');
    }
    // set in place (4.87): a settable value is a box on a click, and Enter
    // sets it through the daemon - read back, not assumed
    {
      const mk = d.querySelector('.heat-title .obj-mark');
      mk.click(); await wait(1500);
      const pop2 = d.getElementById('objpop');
      const ecoRow = Array.from(pop2.querySelectorAll('.op-row')).filter(r => (r.querySelector('.op-n') || {}).textContent === 'eco_c')[0];
      const val = ecoRow && ecoRow.querySelector('.op-edit');
      if (!val) errors.push('eco_c is not offered to be set in the object view');
      else {
        const before = parseFloat(val.textContent);
        val.click(); await wait(100);
        const box = ecoRow.querySelector('.op-box');
        if (!box) errors.push('clicking a settable value gave no box');
        else {
          const want = before === 18 ? 18.5 : 18;
          box.value = String(want);
          box.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
          await wait(2500);
          const again = Array.from(d.getElementById('objpop').querySelectorAll('.op-row'))
            .filter(r => (r.querySelector('.op-n') || {}).textContent === 'eco_c')[0];
          const now = again && parseFloat((again.querySelector('.op-edit') || {}).textContent);
          if (now !== want) errors.push('setting eco_c in the object view left it at ' + now + ', not ' + want);
          // and back as it was, the same way
          const v2 = again && again.querySelector('.op-edit');
          if (v2 && isFinite(before)) {
            v2.click(); await wait(100);
            const b2 = again.querySelector('.op-box'); b2.value = String(before);
            b2.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
            await wait(2500);
          }
        }
      }
      const runs = d.getElementById('objpop').querySelectorAll('.op-run').length;
      if (!runs) errors.push('a room\'s procedures have nothing to do them with');
      d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
      await wait(100);
    }
    // (4.90) a value with a few possible words is picked from a list, and a
    // script line offers them after its "="
    {
      w.showTab('heating'); await wait(1000);
      const mk = d.querySelector('.heat-title .obj-mark');
      mk.click(); await wait(1500);
      const row = Array.from(d.getElementById('objpop').querySelectorAll('.op-row')).filter(r => (r.querySelector('.op-n') || {}).textContent === 'mode')[0];
      const val = row && row.querySelector('.op-edit');
      if (!val) errors.push('a room\'s mode is not offered to be set');
      else {
        val.click(); await wait(100);
        const box = row.querySelector('select.op-box');
        const opts = box ? Array.from(box.options).map(o => o.value) : [];
        if (['plan', 'comfort', 'eco', 'night', 'off'].some(x => opts.indexOf(x) < 0)) errors.push('the mode is not picked from its words: ' + opts.join(','));
        if (box) box.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
      }
      d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
      const room = (w.STATE.status.heating.rooms || [])[0].name;
      const ta = d.createElement('textarea'); ta.dataset.bareWords = '1'; d.body.appendChild(ta);
      ta.value = room + '.mode = e'; ta.selectionStart = ta.selectionEnd = ta.value.length;
      const ctx = w.completerContext(ta);
      if (!ctx || !ctx.assign) errors.push('a script line after "=" is not read as a setting');
      else {
        w.valueItems(ctx); await wait(1500);
        const got = w.valueItems(ctx).map(i => i.text);
        if (got.indexOf('eco') < 0) errors.push('after "' + ta.value + '" the list offers ' + got.join(', '));
      }
      ta.remove();
    }
    // what a rule acts on carries the mark of that thing, and follows the
    // choice as it is changed (4.89)
    {
      w.showTab('control'); w.showControlSection('auto-rules'); await wait(1200);
      for (let i = 0; i < 20; i++) {
        const h = d.querySelector('#tab-control .section:not(.open) > .section-head');
        if (!h) break;
        h.click(); await wait(200);
      }
      const picks = Array.from(d.querySelectorAll('#tab-control .obj-pick'));
      if (!picks.length) errors.push('no box that chooses what a rule acts on carries a mark');
      const one = picks.filter(p => !p.querySelector('.obj-mark').hidden)[0];
      if (one) {
        const sel = one.querySelector('select'), mk = one.querySelector('.obj-mark');
        const other = Array.from(sel.options).filter(o => o.value !== sel.value && w.targetRef(o.value))[0];
        if (other) {
          const was = sel.value;
          sel.value = other.value; sel.dispatchEvent(new w.Event('change'));
          if (mk.dataset.ref !== w.targetRef(other.value)) errors.push('the mark on a target box did not follow the choice');
          sel.value = was; sel.dispatchEvent(new w.Event('change'));
          if (w.RULES) w.RULES.dirty = false;
        }
      }
      console.log('targets: ' + picks.length + ' box(es) that choose what a rule acts on carry its mark');
    }
    // (4.92) an address on the blocked list and a Wi-Fi client carry a mark
    // that opens them, and a scene's steps are one line that can be set
    {
      const ip = '203.0.113.99';
      const keep = w.APPROVALS.blocked;
      w.APPROVALS.blocked = [{ip: ip, since: Date.now() / 1000, until: 0, why: 'a test', auto: 0, on_feeds: [], left: 0}];
      const wasOpen = w.FOLDS.system.open;
      w.FOLDS.system.open = true;
      w.paintBlockedNow(true);
      w.FOLDS.system.open = wasOpen;
      const am = d.querySelector('#blocked-list .obj-mark[data-ref="address:' + ip + '"]');
      if (!am) errors.push('an address on the blocked list carries no mark');
      else {
        am.click();
        let txt = '';
        for (let i = 0; i < 25; i++) {            // a busy daemon answers late, not wrongly
          await wait(200);
          txt = d.getElementById('objpop').textContent;
          if (txt.indexOf('Reading ') !== 0) break;
        }
        if (txt.indexOf('Blocked address') < 0 || txt.indexOf('unban') < 0) errors.push('an address\'s mark opens: ' + txt.slice(0, 120));
        d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
      }
      w.APPROVALS.blocked = keep; w.paintBlockedNow(true);
      w.renderWifiClients_tab({wifi_detail: {clients: [{mac: '11:22:33:44:55:66', name: 'Pixel'}]}, people: [], presence: {}});
      if (!d.querySelector('#wifi-client-table .obj-mark[data-ref="client:11:22:33:44:55:66"]')) errors.push('a Wi-Fi client carries no mark');
      await w.loadObjects(true);
      const sc = (w.OBJ.list || []).filter(o => o.type === 'scene')[0];
      if (!sc) errors.push('the house has no scene to look at');
      else {
        w.openObject(sc.ref, null, true); await wait(1500);
        const row = Array.from(d.getElementById('objpop').querySelectorAll('.op-row')).filter(r => (r.querySelector('.op-n') || {}).textContent === 'steps')[0];
        if (!row || !row.querySelector('.op-edit')) errors.push('a scene\'s steps cannot be set from its view');
        d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
      }
      // (4.93) typing a scene's steps: names first, then what the step does
      if (sc) {
        const ta = d.createElement('textarea'); ta.dataset.bareWords = '1'; d.body.appendChild(ta);
        ta.value = sc.call + '.steps = '; ta.selectionStart = ta.selectionEnd = ta.value.length;
        let ctx = w.completerContext(ta);
        w.valueItems(ctx); await wait(1500);
        const names = w.valueItems(w.completerContext(ta)).filter(i => !i.hint);
        if (!names.length) errors.push('after "' + ta.value + '" nothing is offered to act on');
        else {
          ta.value += names[0].text + 'o'; ta.selectionStart = ta.selectionEnd = ta.value.length;
          const acts = w.valueItems(w.completerContext(ta)).map(i => i.label);
          if (acts.indexOf('on') < 0 || acts.indexOf('off') < 0) errors.push('after "' + ta.value + '" the list offers ' + acts.join(', '));
        }
        ta.remove();
      }
      // (4.98) a rule switched off is dimmed whole - the second condition and
      // the window with it - and lights up as one thing under the pointer
      {
        w.showTab('control'); w.showControlSection('auto-rules'); await wait(1500);
        const pack = d.querySelector('#rules-list .rule-pack');
        const sw = pack && pack.querySelector('.sw input, .sw button, input[type=checkbox]');
        if (!pack) errors.push('no rule to look at');
        else {
          const was = pack.classList.contains('off');
          if (sw) { sw.click(); await wait(200); }
          if (sw && pack.classList.contains('off') === was) errors.push('switching a rule off did not dim the whole rule');
          if (sw) { sw.click(); await wait(200); }
          if (w.RULES) { w.RULES.dirty = false; w.forgetSig('rules'); }
        }
      }
      // (4.97) a section of an editor carries a mark of its own
      {
        w.showTab('control'); w.showControlSection('auto-rules'); await wait(1500);
        const withName = Array.from(d.querySelectorAll('#rules-list .section-head'))
          .filter(h => (h.querySelector('.section-name') || {}).textContent !== 'Everything else');
        const sm = d.querySelector('#rules-list .section-head .obj-mark.sec-mark');
        if (withName.length && (!sm || !/^section:rules\//.test(sm.dataset.ref))) errors.push('a section of the rules carries no mark of its own');
        console.log('sections: ' + withName.length + ' named section(s) of the rules, marked');
      }
      console.log('objects: a blocked address, a Wi-Fi client and a scene\'s steps');
    }
    // the editors: a name in a box carries its mark inside the box
    w.showTab('control'); w.showControlSection('auto-scenes'); await wait(1200);
    for (let i = 0; i < 20; i++) {
      const h = d.querySelector('#scenes-list .section:not(.open) > .section-head');
      if (!h) break;
      h.click(); await wait(200);
    }
    const boxes = d.querySelectorAll('#scenes-list .obj-in > input');
    if (!boxes.length) errors.push('a scene\'s name box has no mark');
    console.log('objects: ' + marked + ' device name(s), ' + rooms + ' room(s) and ' + boxes.length
      + ' scene box(es) marked; the view opens, finds, survives a redraw and closes');
  } catch (e) { errors.push('the object check itself failed: ' + e.message); }

  // (5.4) what a rule has waiting is on the screen the whole time it waits,
  // counting down, and goes when it is over. Nothing happens in the house
  // while a rule waits, so the page is woken only at the start and at the
  // end: in between the browser counts it down itself. It used to stand
  // still and blink in and out with whatever else came along.
  try {
    w.showTab('control'); w.showControlSection('auto-rules'); await wait(1500);
    const rule = (w.STATE.status.rules || [])[0];
    if (!rule || !rule.id) errors.push('no rule to watch waiting');
    else {
      const spot = () => d.querySelector('#rules-list .now[data-rule="' + rule.id + '"]');
      const shown = () => ((spot() && spot().querySelector('.rule-waiting')) || {}).textContent || '';
      // the daemon as it really answers: a rule that is waiting says how much
      // is left, on every status, and stops saying it when it is done
      const done = Date.now() + 6000;
      const real = w.updateRuleReadings;
      w.updateRuleReadings = function (st) {
        const left = Math.round((done - Date.now()) / 1000);
        if (left > 0 && st && st.rules) {
          st = Object.assign({}, st, {rules: st.rules.map(
            x => x.id === rule.id ? Object.assign({}, x, {waiting_s: left, do: 'off'}) : x)});
        }
        return real.call(this, st);
      };
      w.updateRuleReadings(w.STATE.status);
      const first = shown();
      if (!/off in/.test(first)) errors.push('what a rule has waiting is not shown: ' + first);
      // it is still there two seconds later, with less on it, whether or not
      // the daemon has said anything in between
      await wait(2300);
      const later = shown();
      const leftNow = parseInt(String(later).replace(/[^0-9]/g, ''), 10);
      if (!/off in/.test(later)) errors.push('the countdown went away while it was still waiting: ' + later);
      if (!(leftNow >= 2 && leftNow <= 5)) errors.push('the countdown did not keep up: ' + first + ' then ' + later);
      // a redraw in the middle does not blink it away
      w.forgetSig('rules'); w.RULES.rows = null; w.renderRules(w.STATE.status); await wait(200);
      if (!/off in/.test(shown())) errors.push('a redraw took the countdown away: ' + shown());
      console.log('a rule waiting: ' + first.trim() + ' then ' + later.trim() + ', through a redraw');
      // ...and when its moment comes it goes, by itself
      await wait(4200);
      w.paintRuleWaiting();
      w.updateRuleReadings(w.STATE.status);
      if (shown()) errors.push('the countdown stayed on the screen after it was over: ' + shown());
      w.updateRuleReadings = real;
    }
  } catch (e) { errors.push('the waiting-countdown check itself failed: ' + e.message); }

  // (5.1) a list the daemon would not give us is not an empty list: three
  // editors turned a refusal into "none yet", and the next Save wrote that
  // emptiness over the real thing.
  try {
    const realApi = w.api;
    w.api = function (what, opts) {
      if (/^(action-groups|sensor-groups|sms-commands)(&|$)/.test(String(what))) {
        return Promise.reject(new Error('the daemon said no'));
      }
      return realApi(what, opts);
    };
    w.AGROUPS.rows = null; w.AGROUPS.dirty = false;
    w.SGROUPS.rows = null; w.SGROUPS.dirty = false;
    w.showTab('control'); w.showControlSection('auto-groups'); await wait(1500);
    w.renderAGroups(w.STATE.status); w.renderSGroups(w.STATE.status); await wait(600);
    if (w.AGROUPS.rows !== null) errors.push('a refused list of action groups became an empty one');
    if (w.SGROUPS.rows !== null) errors.push('a refused list of sensor groups became an empty one');
    let refused = false;
    try { w.rowsToSave(w.AGROUPS, 'action groups'); } catch (e) { refused = true; }
    if (!refused) errors.push('a Save would have written the refused list over the real one');
    w.api = realApi;
    w.AGROUPS.rows = null; w.SGROUPS.rows = null;
    w.forgetSig('agroups'); w.forgetSig('sgroups');
    await wait(900);
    console.log('a refused list stays unread: ' + ((w.AGROUPS.rows || []).length) + ' action group(s) once it answers');
  } catch (e) { errors.push('the refused-list check itself failed: ' + e.message); }

  // (5.1) the Overview follows the house again once its own order is saved
  try {
    w.OVERVIEW_LAYOUT_LOCAL = ['a', 'b'];
    await w.saveOverviewLayout(['a', 'b']);
    for (let i = 0; i < 20 && w.OVERVIEW_LAYOUT_LOCAL !== null; i++) await wait(150);
    if (w.OVERVIEW_LAYOUT_LOCAL !== null) errors.push('the Overview kept its own order after saving it');
  } catch (e) { errors.push('the overview-order check itself failed: ' + e.message); }

  // (5.1) the rooms editor writes into its own copy, not into the house
  try {
    w.showControlSection('auto-rooms'); await wait(1200);
    const was = ((w.STATE.status.rooms || [])[0] || {}).name;
    if (was && w.ROOMS.rows && w.ROOMS.rows[0]) {
      w.ROOMS.rows[0].name = was + ' (typing)';
      if (((w.STATE.status.rooms || [])[0] || {}).name !== was) {
        errors.push('typing a room name changed the house itself');
      }
      w.ROOMS.rows = null; w.ROOMS.dirty = false;
    }
  } catch (e) { errors.push('the rooms check itself failed: ' + e.message); }

  // (5.0) every row of every editor is a thing of its own and says so: its
  // own mark at its left edge, where the section's is, not tucked inside the
  // first box (where it looked like the mark of whatever that box points at).
  try {
    w.showTab('control');
    // the editors this house has nothing in yet are given a row, so the check
    // covers every kind rather than only the ones with something in them
    const seed = () => {
      if (w.SCHEDULES) { w.SCHEDULES.rows = [{id: 'sch-x', target: '', do: 'on', at: '07:00', days: ['mon'], enabled: true}]; }
      if (w.SEQUENCES) { w.SEQUENCES.rows = [{id: 'seq-x', name: 'Seq', steps: [], enabled: true}]; }
      if (w.SGROUPS) { w.SGROUPS.rows = [{id: 'sg-x', name: 'Group', members: [], mode: 'any', enabled: true}]; }
      if (w.AGROUPS) { w.AGROUPS.rows = [{id: 'ag-x', name: 'Group', members: [], enabled: true}]; }
      if (w.GATEWAYS && !(w.GATEWAYS.rows || []).length) {
        w.GATEWAYS.rows = [{name: 'Router', host: '192.168.1.1', user: '', target: ''}];
        w.GATEWAYS.dirty = true;                 // so a tick does not read it back as empty
      }
    };
    const kinds = [
      ['auto-rules', '#rules-list', '.rule-pack', 'rule'],
      ['auto-groups', '#bindings-list', '.bind-row:not(.bind-head)', 'binding'],
      ['auto-scenes', '#schedules-list', '.sched-row', 'schedule'],
      ['presence', '#ptrig-list', '.ptrig-row:not(.ptrig-head)', 'presence'],
      ['auto-scenes', '#scenes-list', '.scene-row', 'scene'],
      ['auto-scenes', '#sequences-list', '.seq-row', 'sequence'],
      ['auto-groups', '#sgroups-list', '.sgroup-row:not(.agroup-row)', 'sgroup'],
      ['auto-groups', '#agroups-list', '.agroup-row', 'agroup'],
      ['msg-sms', '#smscmd-list', '.smscmd-row', 'smscmd'],
      ['msg-taps', '#taps-list', '.tap-row:not(.tap-head)', 'tap'],
      ['msg-alerts', '#messages-list', '.msg-card', 'message'],
      ['auto-scripts', '#scripts-list', '.rule-pack', 'script'],
      ['presence', '#people-list', '.person-row:not(.person-head)', 'person'],
      ['dev-zigbee', '#gateways-list', '.gw-row:not(.gw-head)', 'gateway'],
      ['dev-devices', '#managed-list', '.mdev', 'plug'],
      ['auto-rooms', '#rooms-list', '.room-row', 'room']
    ];
    let checked = 0;
    for (const [sec, host, sel, kind] of kinds) {
      w.showControlSection(sec); await wait(900);
      seed();
      if (w.paintSchedules) try { w.paintSchedules(w.STATE.status); } catch (e) {}
      if (w.paintSequences) try { w.paintSequences(w.STATE.status); } catch (e) {}
      if (w.paintSGroups) try { w.paintSGroups(w.STATE.status); } catch (e) {}
      if (w.paintAGroups) try { w.paintAGroups(w.STATE.status); } catch (e) {}
      if (w.paintGateways) try { w.paintGateways(w.STATE.status); } catch (e) {}
      await wait(300);
      for (let i = 0; i < 30; i++) {
        const h = d.querySelector('#tab-control .section:not(.open) > .section-head');
        if (!h) break; h.click();
      }
      await wait(250);
      const rows = Array.from(d.querySelectorAll(host + ' ' + sel));
      if (!rows.length) { errors.push('no ' + kind + ' row to look at (' + host + ')'); continue; }
      const bare = rows.filter(r => {
        const m = r.querySelector(':scope > .obj-mark.row-mark');
        return !m || String(m.dataset.ref || '').split(':')[0] !== kind;
      });
      if (bare.length) errors.push(bare.length + ' of ' + rows.length + ' ' + kind + ' row(s) carry no mark of their own');
      checked += rows.length;
    }
    console.log('rows as objects: ' + checked + ' row(s) in ' + kinds.length + ' editor(s), each with its own mark at its edge');
    // and the boxes inside a rule name what they point at, not the rule
    w.showControlSection('auto-rules'); await wait(1200);
    const pack = d.querySelector('#rules-list .rule-pack');
    if (pack) {
      const refs = Array.from(pack.querySelectorAll('.obj-mark')).map(m => String(m.dataset.ref || ''));
      const own = refs.filter(r => /^rule:/.test(r));
      if (own.length !== 1) errors.push('a rule wears its own mark ' + own.length + ' time(s), not once');
      if (!refs.some(r => /^(device|sensor|plug|sgroup):/.test(r))) errors.push('the box a rule reads from names nothing');
    }
    if (w.SCHEDULES) { w.SCHEDULES.rows = null; w.SCHEDULES.dirty = false; }
    if (w.SEQUENCES) { w.SEQUENCES.rows = null; w.SEQUENCES.dirty = false; }
    if (w.SGROUPS) { w.SGROUPS.rows = null; w.SGROUPS.dirty = false; }
    if (w.AGROUPS) { w.AGROUPS.rows = null; w.AGROUPS.dirty = false; }
    if (w.GATEWAYS) { w.GATEWAYS.rows = null; w.GATEWAYS.dirty = false; }
  } catch (e) { errors.push('the row-mark check itself failed: ' + e.message); }

  // (4.99) the reporting table and the bindings editor are two different
  // things: one global named BINDINGS held both, so opening the editor
  // emptied the table that had just been fetched.
  try {
    w.showTab('control'); w.showControlSection('dev-zigbee'); await wait(2600);
    const before = d.querySelectorAll('#binding-list .bindrow').length;
    w.showControlSection('auto-groups'); await wait(1600);     // the bindings editor
    w.showControlSection('dev-zigbee'); await wait(1200);      // straight back, inside the minute
    const after = d.querySelectorAll('#binding-list .bindrow').length;
    console.log('the reporting table after a visit to the bindings editor: ' + before + ' -> ' + after + ' row(s)');
    if (before && !after) errors.push('opening the bindings editor emptied the Zigbee reporting table');
  } catch (e) { errors.push('the reporting-table check itself failed: ' + e.message); }

  // (4.99) the PIN typed in brings the refused views back at once - no F5.
  // The message log was the one that showed it: its "asked already" mark was
  // written before the ask, so the refusal while locked latched it shut.
  try {
    const hadToken = w.LOCK.who, hadUntil = 0;
    w.LOCK.who = null;          // as if the time had run out
    w.SIGS = {};
    // a page that starts locked: nothing asked for yet, nothing on the screen
    d.getElementById('sms-log').innerHTML = '';
    w.SMSLOG.mark = null;
    w.showTab('sms'); await wait(1800);             // asks, is refused, remembers it asked
    const lockedLines = d.querySelectorAll('#sms-log .sms-line').length;
    if (lockedLines) errors.push('locked, the message log showed ' + lockedLines + ' message(s)');
    // the PIN goes in through the box a person uses, and nothing is reloaded
    w.unlockFlow(); await wait(400);
    if (w.PIN.mode === 'pin') d.getElementById('pin-other-link').click();
    d.getElementById('signin-name').value = 'admin'; d.getElementById('signin-pass').value = 'admin pass 1';
    d.getElementById('pinok').click(); await wait(2600);
    const openLines = d.querySelectorAll('#sms-log .sms-line').length;
    console.log('the PIN typed in: ' + lockedLines + ' message(s) while locked, ' + openLines + ' straight after');
    if (!openLines) errors.push('after the PIN the message log stayed empty until a reload');
    // and locked again, what the PIN showed goes off the screen
    w.lockNow(); await wait(900);
    if (d.querySelectorAll('#sms-log .sms-line').length) errors.push('locked again, the messages stayed on the screen');
    // a dismissed PIN box must not stop the page ever offering it again
    w.VIEWLOCK.asking = true;
    w.unlockFlow(); await wait(300);
    d.getElementById('pincancel').click(); await wait(300);
    if (w.VIEWLOCK.asking) errors.push('one dismissed PIN box stops the page offering the PIN again');
    w.LOCK.who = hadToken;
    if (hadToken && typeof w.lockChanged === 'function') w.lockChanged();
    await wait(600);
  } catch (e) { errors.push('the PIN check itself failed: ' + e.message); }


  // ===== 5.5: what the sweep for bugs, lag and latency found =====================

  // The socket cards are not built again for a new wattage: the figures are
  // written into the cards that are already there, so a hover, a tooltip and
  // the scroll position survive a reading - and a reading arrives from some
  // box every second or two in a house with a dozen of them.
  try {
    w.showTab('plugs'); await wait(1200);
    const cards = () => Array.from(d.querySelectorAll('#sockets [data-plug]'));
    const before = cards();
    if (!before.length) errors.push('the sockets tab drew no cards to check');
    else {
      const st = w.STATE.status, first = (st.plugs || [])[0];
      const node = before[0], power = () => {
        const cell = Array.from(node.querySelectorAll('.socket-figures > div'))
          .filter(x => (x.querySelector('.k') || {}).textContent === 'Power')[0];
        return cell ? (cell.querySelector('.v') || {}).textContent : '';
      };
      const was = power();
      first.values = first.values || {};
      first.values.power = (first.values.power || 0) + 12.5;
      w.renderSockets(st); await wait(30);
      const after = cards();
      if (after.length !== before.length || after.some((c, i) => c !== before[i]))
        errors.push('a new wattage threw away the socket cards and built them again');
      if (power() === was) errors.push('the new wattage never reached the card: still ' + was);
      // ...and a socket that actually switches is drawn afresh
      first.output = first.output === 1 ? 0 : 1;
      w.renderSockets(st); await wait(30);
      const third = cards();
      if (third[0] === before[0]) errors.push('a socket that switched kept the card it had');
    }
  } catch (e) { errors.push('the socket-figures check itself failed: ' + e.message); }

  // A row that has not been saved yet keeps the object column: without it the
  // row stood nineteen pixels to the left of every row around it, and the
  // whole table shifted the moment it was saved.
  try {
    w.showTab('control'); w.showControlSection('sys-rules'); await wait(1200);
    const addAndLook = (button, listId, rowSel) => {
      const add = d.getElementById(button);
      if (!add) return 'no ' + button;
      add.click();
      const rows = Array.from(d.querySelectorAll('#' + listId + ' ' + rowSel));
      const last = rows[rows.length - 1];
      if (!last) return 'no new row in ' + listId;
      return last.classList.contains('hasmark') ? '' : 'a fresh row in ' + listId + ' has no object column';
    };
    let why = addAndLook('binding-add', 'bindings-list', '.bind-row');
    if (why) errors.push(why);
    why = addAndLook('schedule-add', 'schedules-list', '.sched-row');
    if (why) errors.push(why);
    w.BINDINGS.rows = null; w.BINDINGS.dirty = false;
    w.SCHEDULES.rows = null; w.SCHEDULES.dirty = false;
    w.SIGS = {};
  } catch (e) { errors.push('the fresh-row check itself failed: ' + e.message); }

  // A PIN box dismissed leaves nothing behind: the card was painted ahead of
  // the answer ("switching..."), and nothing took that back when the dialogue
  // was closed - the socket sat there half-switched until a reload.
  try {
    w.showTab('plugs'); await wait(900);
    const card = d.querySelector('#sockets .card.socket');
    const btn = card && card.querySelector('button.socket-toggle');
    const plug = (w.STATE.status.plugs || [])[0];
    if (!card || !btn || !plug) errors.push('no socket with a button to check the dismissed PIN on');
    else {
      const hadToken = w.LOCK.who, hadUntil = 0;
      w.LOCK.who = null;            // locked, so the PIN is asked for
      btn.disabled = false;
      w.switchPlug(plug, plug.output !== 1, btn, 'pin');
      if (!card.classList.contains('pending')) errors.push('the card was not painted ahead of the answer at all');
      await wait(400);
      if (d.getElementById('pinback').hidden) errors.push('no PIN box opened for the switch');
      d.getElementById('pincancel').click(); await wait(400);
      if (card.classList.contains('pending')) errors.push('a dismissed PIN box left the socket saying it was switching');
      if (btn.disabled) errors.push('a dismissed PIN box left the socket’s button dead');
      w.LOCK.who = hadToken;
      if (hadToken && typeof w.lockChanged === 'function') w.lockChanged();
      await wait(400);
    }
  } catch (e) { errors.push('the dismissed-PIN check itself failed: ' + e.message); }

  // A list edited somewhere else - another browser, the CLI, a script - is
  // fetched again: the rows in hand were kept for ever, so the card showed
  // yesterday's schedule until somebody reloaded the page.
  try {
    w.SCHEDULES.rows = [{id: 'x', target: '', at: '07:00', do: 'on', days: [0]}];
    w.SCHEDULES.dirty = false; w.SCHEDULES.stamp = 'aaa';
    if (!w.listStale(w.SCHEDULES, 'bbb')) errors.push('a schedule changed elsewhere was not noticed');
    if (w.SCHEDULES.rows !== null) errors.push('a schedule changed elsewhere kept the rows in hand');
    w.SCHEDULES.rows = [{id: 'x'}]; w.SCHEDULES.stamp = 'bbb';
    if (w.listStale(w.SCHEDULES, 'bbb')) errors.push('a list nobody touched was fetched again');
    w.SCHEDULES.rows = [{id: 'x'}]; w.SCHEDULES.dirty = true; w.SCHEDULES.stamp = 'bbb';
    if (w.listStale(w.SCHEDULES, 'ccc') || w.SCHEDULES.rows === null)
      errors.push('unsaved edits were thrown away by a change elsewhere');
    w.SCHEDULES.dirty = false; w.SCHEDULES.rows = null; w.SIGS = {};
    if (w.STATE.status.schedule_stamp === undefined) errors.push('the daemon sends no fingerprint for the schedules');
  } catch (e) { errors.push('the stale-list check itself failed: ' + e.message); }

  // One set of listeners per picker: the Do box is refilled every time the
  // target changes, and the tooltip was hooked up again each time.
  try {
    const sel = d.createElement('select');
    let added = 0;
    const real = sel.addEventListener.bind(sel);
    sel.addEventListener = function () { added++; return real.apply(sel, arguments); };
    w.attachTargetReadings(sel, () => 'scene:one');
    const first = added;
    for (let i = 0; i < 5; i++) w.attachTargetReadings(sel, () => 'scene:two');
    if (added !== first) errors.push('a picker was hooked up ' + added + ' times for six refills');
    if (!first) errors.push('a picker was never hooked up at all');
  } catch (e) { errors.push('the picker-listener check itself failed: ' + e.message); }


  // ===== 5.6: the watched addresses, and filtering by country ===================

  // The addresses on their way to being kept out are a fold of their own, the
  // same shape as the lists below them, with everything a blocked row carries
  // - the marks, the lists, Shodan, Suricata, the flag - plus how near each
  // one is to a block and what it would get.
  try {
    w.showTab('approvals'); await wait(1200);
    w.FOLDS.watch = {open: true, text: '', cc: '', page: 0, per: 25};   // as it is on a fresh page
    w.APPROVALS.counters = [
      {ip: '45.134.26.8', score: 12, bar: 15, tries: 6, spread: 4, blocked: false,
       from_proxy: true, from_ntfy: false, from_house: false, country: 'NL',
       on_feeds: ['firehol1', 'blocklist_de'], from_feed: 'firehol1', from_ids: true,
       ids: {sid: 2400016, rule: {msg: 'ET DROP Spamhaus'}}, intel: 'nginx on 80, 443',
       before: 2, spared: '', runs_out: 420, last: Date.now() / 1000,
       kinds: [{kind: 'bad-secret', n: 4, words: 'a secret that opens nothing'}],
       next: {minutes: 1440, forever: false, words: 'the third time from this address: 24 h'}},
      {ip: '89.24.5.7', score: 2, bar: 45, tries: 1, spread: 1, blocked: false,
       from_proxy: false, from_ntfy: false, from_house: true, country: 'CZ',
       on_feeds: [], from_feed: '', from_ids: false, ids: null, intel: '',
       before: 0, spared: '', runs_out: 600, last: Date.now() / 1000,
       kinds: [{kind: 'locked-read', n: 1, words: 'a read that asks for the PIN'}],
       next: {minutes: 60, forever: false, words: 'the first time from this address: 60 min'}},
      {ip: '2a01:430::9', score: 30, bar: 15, tries: 9, spread: 7, blocked: false,
       from_proxy: true, from_ntfy: true, from_house: false, country: 'ZZ',
       on_feeds: [], from_feed: '', from_ids: false, ids: null, intel: '',
       before: 0, spared: '', runs_out: 300, last: Date.now() / 1000,
       kinds: [{kind: 'probe-path', n: 9, words: 'a road that is shut'}],
       next: {minutes: 0, forever: true, words: 'for good, by the ladder'}},
      {ip: '10.0.0.5', score: 99, bar: 45, tries: 20, spread: 9, blocked: true,
       from_proxy: false, from_house: true, country: 'CZ', on_feeds: [], kinds: [],
       runs_out: 60, next: {minutes: 0, forever: false, words: ''}}
    ];
    w.paintWatched(); await wait(200);
    var watch = d.getElementById('blocked-watch');
    var wrows = watch.querySelectorAll('.appr-row');
    if (wrows.length !== 3) errors.push('the watched fold drew ' + wrows.length + ' row(s), not the 3 not yet blocked');
    var fold = watch.querySelector('.listed-fold');
    if (!fold) errors.push('the watched addresses are not a fold of their own');
    if (!watch.querySelector('.listed-head')) errors.push('the watched fold cannot be shut');
    if (!watch.querySelector('input[data-keep="listed-filter-watch"]')) errors.push('the watched fold has no filter of its own');
    var first = wrows[0];
    var glyphs = Array.prototype.map.call(first.querySelectorAll('.appr-icon'), function (g) { return g.textContent; }).join('');
    ['👁️', '🌐', '📕', '📡'].forEach(function (mark) {
      if (glyphs.indexOf(mark) < 0) errors.push('a watched row is missing the mark ' + mark);
    });
    if (!first.querySelector('.cflag-img, .cflag.letters')) errors.push('a watched row carries no flag');
    if ((first.textContent || '').indexOf('Shodan') < 0) errors.push('a watched row does not say what Shodan said');
    if ((first.textContent || '').indexOf('firehol1') < 0) errors.push('a watched row does not say which lists name it');
    if ((first.textContent || '').indexOf('2400016') < 0) errors.push('a watched row does not say what Suricata saw');
    if (!first.querySelector('.obj-mark')) errors.push('a watched address is not an object like everything else');
    if (!first.querySelector('.iconbtn')) errors.push('a watched row has no way to forget what it has been doing');
    // the bar: how near it is, and what it is heading for
    var bar = first.querySelector('.wbar');
    if (!bar) errors.push('a watched row has no progress towards a block');
    else {
      var fill = bar.querySelector('.wbar-fill');
      if (!fill || fill.style.width !== '80%') errors.push('12 of 15 drew a bar of ' + (fill && fill.style.width));
      if ((bar.textContent || '').indexOf('24 h') < 0) errors.push('the bar does not say what it would get: ' + bar.textContent);
    }
    var third = wrows[2];
    if ((third.querySelector('.wbar') || {}).className.indexOf('close') < 0)
      errors.push('an address over the bar is not drawn as close to it');
    if ((third.querySelector('.appr-left') || {}).textContent !== 'then for good')
      errors.push('one heading for a permanent block says "' + (third.querySelector('.appr-left') || {}).textContent + '"');
    console.log('watched: ' + wrows.length + ' row(s), the first at ' + (first.querySelector('.appr-left') || {}).textContent);
  } catch (e) { errors.push('the watched-list check itself failed: ' + e.message); }

  // Beside every text filter over addresses: the countries in those rows,
  // each with its flag and how many are its.
  try {
    var pick = d.querySelector('#blocked-watch .cpick');
    if (!pick) errors.push('the watched fold has no country picker beside its filter');
    else {
      pick.querySelector('.cpick-btn').click(); await wait(100);
      var ones = pick.querySelectorAll('.cpick-one');
      if (ones.length !== 4) errors.push('the picker offered ' + ones.length + ' choice(s) for 3 rows in 3 countries');
      if (!pick.querySelector('.cpick-one .cflag-img, .cpick-one .cflag.letters'))
        errors.push('the countries are offered without their flags');
      // 'ZZ' - an address no list could place - is one bucket, not none
      var zz = Array.prototype.filter.call(ones, function (o) { return /No country known/.test(o.textContent); })[0];
      if (!zz) errors.push('the addresses with no country are not offered as a choice of their own');
      else {
        zz.click(); await wait(200);
        var left = d.querySelectorAll('#blocked-watch .appr-row').length;
        if (left !== 1) errors.push('picking the countryless left ' + left + ' row(s), not 1');
        if (!/No country known/.test(d.querySelector('#blocked-watch .cpick-btn').textContent))
          errors.push('the picker does not wear what it is set to');
      }
      // and back to everything
      d.querySelector('#blocked-watch .cpick-btn').click(); await wait(100);
      d.querySelector('#blocked-watch .cpick-pop .cpick-one').click(); await wait(200);
      if (d.querySelectorAll('#blocked-watch .appr-row').length !== 3)
        errors.push('going back to every country did not bring the rows back');
    }
    // the filters that were there before have one too
    var pickers = d.querySelectorAll('.cpick').length;
    if (pickers < 2) errors.push('only ' + pickers + ' country picker(s) on the whole card');
    if (!d.querySelector('#presses-filter .cpick')) errors.push('the presses have no country picker');
    console.log('country pickers: ' + pickers + ' on the card');
  } catch (e) { errors.push('the country-picker check itself failed: ' + e.message); }


  // ===== 5.8: what is drawn again, and what is not =============================

  // The socket cards' fast path carried "3 s ago" in the shape of every card,
  // so it never matched and the whole grid was thrown away on every reading -
  // the very thing that shape exists to prevent. The words are shown only
  // when a socket is stale.
  try {
    w.showTab('plugs'); await wait(1100);
    var cards = function () { return Array.prototype.slice.call(d.querySelectorAll('#sockets [data-plug]')); };
    var before = cards();
    if (!before.length) errors.push('the sockets tab drew no cards for the shape check');
    else {
      var st = w.STATE.status;
      (st.plugs || []).forEach(function (p) { p.generated = (p.generated || 0) + 7; p.age = (p.age || 0) + 7; });
      w.renderSockets(st); await wait(30);
      var after = cards();
      if (after.length !== before.length || after.some(function (c, i) { return c !== before[i]; }))
        errors.push('a socket answering again threw away the cards and built them afresh');
      // ...and a socket that goes stale is drawn afresh, words and all
      (st.plugs || [])[0].stale = !(st.plugs || [])[0].stale;
      w.renderSockets(st); await wait(30);
      if (cards()[0] === before[0]) errors.push('a socket that went stale kept the card it had');
      (st.plugs || [])[0].stale = !(st.plugs || [])[0].stale;
      w.renderSockets(st); await wait(30);
    }
  } catch (e) { errors.push('the socket-shape check itself failed: ' + e.message); }

  // A signature that carries how long the last paint took keeps changing by
  // being read: the latency card rebuilt its rows on every tick for ever.
  try {
    w.SIGS = {};
    var latSig = JSON.stringify([w.STATE.status.latency]);
    w.sigChanged('latency', [w.STATE.status.latency]);
    w.TICK.lastMs = (w.TICK.lastMs || 0) + 37;
    if (w.sigChanged('latency', [w.STATE.status.latency]))
      errors.push('the latency card redraws itself because the last paint took a different time');
    if (!latSig) errors.push('no latency in the status to sign');
    // ...and what moves only because time passes is out of every signature
    var quiet = JSON.stringify([{leaving_in: 120, retry_in: 30, age: 9, age_s: 9}], w.SIG_QUIET);
    var quiet2 = JSON.stringify([{leaving_in: 119, retry_in: 29, age: 300, age_s: 300}], w.SIG_QUIET);
    if (quiet !== quiet2) errors.push('a countdown by the second still moves a signature: ' + quiet + ' vs ' + quiet2);
  } catch (e) { errors.push('the signature check itself failed: ' + e.message); }

  // Cards that had no signature at all, and one that spent its signature
  // without drawing anything.
  try {
    w.showTab('control'); w.showControlSection('msg-sms'); await wait(1300);
    var builtIn = d.getElementById('smsbuiltin-card');
    if (!builtIn) errors.push('no built-in SMS command card to check');
    else {
      var rowsNow = d.querySelectorAll('#smsbuiltin-card .smshelp-row, #smsbuiltin-card .swrow');
      var keep = rowsNow[0];
      w.renderTab('control', w.STATE.status); await wait(60);
      w.renderTab('control', w.STATE.status); await wait(60);
      var again = d.querySelectorAll('#smsbuiltin-card .smshelp-row, #smsbuiltin-card .swrow');
      if (keep && again[0] && keep !== again[0])
        errors.push('the built-in commands are rebuilt on every tick');
    }
    // the gateway card: its signature must not be spent while the editor is busy
    w.showControlSection('dev-zigbee'); await wait(900);
    w.SIGS = {};
    w.GATEWAYS.dirty = true;
    w.renderTab('control', w.STATE.status); await wait(40);
    w.GATEWAYS.dirty = false;
    var drew = false;
    var wasRender = w.renderGateways;
    w.renderGateways = function (st) { drew = true; return wasRender(st); };
    w.renderTab('control', w.STATE.status); await wait(40);
    w.renderGateways = wasRender;
    if (!drew) errors.push('the gateway card spent its signature while the editor was busy, and never drew');
  } catch (e) { errors.push('the card-signature check itself failed: ' + e.message); }

  // A list the page draws itself is held open the same way a native dropdown is.
  try {
    w.showTab('approvals'); await wait(900);
    var pick = d.querySelector('#blocked-list .cpick, #blocked-watch .cpick, #blocked-past .cpick');
    if (!pick) errors.push('no country picker on the card to check holding');
    else {
      pick.querySelector('.cpick-btn').click(); await wait(80);
      if (!w.userHolding()) errors.push('an open country picker is not counted as a hand on the page');
      // shut the way a person shuts it: a press anywhere else
      d.body.dispatchEvent(new w.MouseEvent('mousedown', {bubbles: true})); await wait(80);
      if (w.userHolding()) errors.push('the page thinks a hand is still on it after the list was shut');
    }
  } catch (e) { errors.push('the held-list check itself failed: ' + e.message); }

  // Every tab is marked stale when a status lands, Heating and Events too.
  try {
    w.TAB_STALE = {};
    w.applyStatus(w.STATE.status); await wait(60);
    ['heating', 'events', 'overview', 'plugs'].forEach(function (t) {
      if (w.TAB_STALE[t] !== true && w.STATE.tab !== t)
        errors.push('the ' + t + ' tab is not marked for a redraw when a status lands');
    });
  } catch (e) { errors.push('the stale-tab check itself failed: ' + e.message); }


  // ===== 5.10: Max, the level that is not a temperature ========================
  try {
    w.showTab('heating'); await wait(1300);
    var presets = Array.prototype.map.call(d.querySelectorAll('.heat-presets .btn'),
      function (b) { return (b.textContent || '').replace(/\s+/g, ' ').trim(); });
    if (!presets.length) errors.push('the heating tab drew no preset buttons');
    else {
      if (!presets.some(function (t) { return /Max/.test(t); }))
        errors.push('the room cards offer no Max: ' + presets.slice(0, 8).join(' | '));
      if (!presets.some(function (t) { return /Off/.test(t); }))
        errors.push('the room cards lost Off while Max was added');
      var maxBtn = Array.prototype.filter.call(d.querySelectorAll('.heat-presets .btn'),
        function (b) { return /Max/.test(b.textContent || ''); })[0];
      // the page moves a title into its own tooltip and keeps the words in
      // dataset.said, so look where they end up
      var maxWords = maxBtn ? (maxBtn.title || maxBtn.dataset.said
                               || maxBtn.getAttribute('aria-label') || '') : '';
      if (maxBtn && !/wide open|as hard as/.test(maxWords))
        errors.push('the Max button does not say what it does: ' + maxWords.slice(0, 60));
    }
    // ...and the plan editor can put a step on it
    var levels = (w.HEAT_LEVELS || []).map(function (pair) { return pair[0]; });
    if (levels.indexOf('max') < 0) errors.push('a plan step cannot be set to max: ' + levels.join(','));
    if (levels.indexOf('off') < 0) errors.push('the plan lost off');
    var planLevel = d.querySelector('#heat-rooms select.heat-plan-level, .heat-step select');
    if (planLevel) {
      var offered = Array.prototype.map.call(planLevel.options, function (o) { return o.value; });
      if (offered.length && offered.indexOf('max') < 0)
        errors.push('the plan dropdown on the page offers ' + offered.join(',') + ' and not max');
    }
    console.log('heating presets: ' + presets.slice(0, 8).join(' | '));
  } catch (e) { errors.push('the heating Max check itself failed: ' + e.message); }

  // 5.11: the Settings card must follow what changes elsewhere.
  // Two of its editors called mark() while being built, so SETTINGS.dirty was
  // true from the first time Control was opened - and renderSettings refuses
  // to redraw a dirty card. A setting changed from the CLI, from a phone or
  // by "Fetch them now" never appeared again for the rest of the session, and
  // the note was wiped at the end of the same pass so nothing said why.
  try {
    w.SETTINGS.dirty = false;
    w.showTab('control'); w.showControlSection('sys-all'); await wait(1500);
    w.renderSettings(w.STATE.status);
    await wait(300);
    if (w.SETTINGS.dirty) {
      errors.push('the Settings card says "Unsaved changes" before anybody touched it, '
        + 'so it never follows anything again');
    } else {
      // ...and it really does redraw when a value changes under it
      // every box drawn for this setting, because the sections are built into
      // several hosts and only the ones on screen are rebuilt
      const boxes = () => Array.from(d.querySelectorAll('input[data-k="geo_every_d"]'))
        .map(one => String(one.value));
      const was = boxes();
      const live = w.STATE.status.runtime_config || {};
      if (was.length && live.geo_every_d) {
        const other = '44';
        live.geo_every_d = Object.assign({}, live.geo_every_d, {value: 44});
        w.renderSettings(w.STATE.status);
        await wait(300);
        const now = boxes();
        if (now.indexOf(other) < 0) {
          errors.push('a setting changed elsewhere did not reach the card: it says '
            + now.join(',') + ' and not ' + other);
        }
        console.log('the settings card followed a change made elsewhere: '
          + was.join(',') + ' -> ' + now.join(','));
      } else {
        console.log('the settings card is clean on its first draw');
      }
    }
  } catch (e) { errors.push('the settings-card check itself failed: ' + e.message); }

  // ---- a socket's watts do not rebuild the whole device table -------------
  // The table draws names, kinds, levels, batteries and when a device was
  // last heard - not watts. Signed on the whole device record and rebuilt
  // from nothing each time, every socket's reading threw away 65 rows, 2,158
  // nodes and 130 buttons and built them again: 43.5 ms of the browser's one
  // thread, about three times every two seconds, and a press landing in that
  // window waited behind it. The rows that did not change are kept now, the
  // way renderAll keeps its cards.
  try {
    const tab = d.querySelector('.tabs button[data-tab="devices"]');
    if (tab) { tab.click(); await wait(1000); }
    const rowsOf = () => Array.prototype.slice.call(d.querySelectorAll('#devices-table tbody tr'));
    const before = rowsOf();
    if (before.length < 3) {
      console.log('the device table has ' + before.length + ' row(s) here - skipped');
    } else {
      const st = JSON.parse(JSON.stringify(w.STATE.status));
      let touched = null;
      for (const dev of (st.devices || [])) {
        const watts = dev.values && dev.values['switch.apower'];
        if (dev.source === 'plug' && watts) {
          watts.value = (watts.value || 0) + 7;   // the watts alone: last_seen IS drawn
          touched = dev.name;
          break;
        }
      }
      if (!touched) {
        console.log('no socket with watts in this status - the table check is skipped');
      } else {
        w.applyStatus(st); await wait(250);
        const after = rowsOf();
        const kept = after.filter((r, i) => r === before[i]).length;
        if (kept < before.length) {
          errors.push('a socket reporting watts rebuilt ' + (before.length - kept) + ' of the '
            + before.length + ' rows of the device table, which does not show watts at all');
        }
        // ...and a row that really changed IS drawn afresh
        const st2 = JSON.parse(JSON.stringify(st));
        const one = (st2.devices || [])[0];
        if (one) { one.level = one.level === 'ok' ? 'warn' : 'ok'; }
        w.applyStatus(st2); await wait(250);
        const after2 = rowsOf();
        if (after2.length && after2[0] === after[0]) {
          errors.push('a device whose level changed kept the row that said the old one');
        }
        console.log('a socket reporting watts keeps all ' + before.length
          + ' rows of the device table; a device whose level changed gets a fresh row');
      }
    }
  } catch (e) { errors.push('the device-table check itself failed: ' + e.message); }

  // ---- the five-second net stays down while the long poll is answering ----
  // The daemon answers /api/wait the moment anything changes, and answers it
  // anyway every 25 s. The interval beside it was fetching the whole
  // quarter-megabyte status every five seconds regardless - about 2,880
  // fetches and a couple of gigabytes of JSON over an evening, per open tab,
  // which on a phone is radio and battery for nothing.
  try {
    // who is signed in settled first (5.19): a sign-in that changed redraws
    // the page, and that is not the net this looks at
    if (typeof w.whoamiCheck === 'function') { await w.whoamiCheck(); await wait(1500); }
    const realWake = w.wakeTick;
    const realFetch = w.fetch;
    const seen = [];
    w.wakeTick = () => {};                 // so only the interval can fetch
    w.fetch = (url, opts) => { seen.push(String(url)); return realFetch(url, opts); };
    w.WAIT.failures = 0; w.WAIT.answered = Date.now();
    await wait(6200);
    const quiet = seen.filter(u => /api=status/.test(u)).length;
    seen.length = 0;
    w.WAIT.answered = Date.now() - 120000;   // as if the poll had stopped getting through
    await wait(6200);
    const loud = seen.filter(u => /api=status/.test(u)).length;
    w.fetch = realFetch; w.wakeTick = realWake; w.WAIT.answered = Date.now();
    if (quiet > 0) {
      errors.push('the five-second net fetched the whole status ' + quiet
        + ' time(s) while the long poll was answering');
    }
    if (loud < 1) errors.push('the five-second net fetched nothing when the long poll had gone quiet');
    console.log('with the long poll answering, the five-second net fetched ' + quiet
      + ' status(es); with it silent, ' + loud);
  } catch (e) { errors.push('the five-second-net check itself failed: ' + e.message); }

  // ---- one press is one refresh ------------------------------------------
  // The action asks for a refresh and the PIN wrapper around it asks again,
  // in the same turn of the event loop; the second became a THIRD fetch when
  // the first came back. One press, three status fetches and three repaints -
  // 44-47 ms each on wi-fi, 102 ms on LTE.
  try {
    clearInterval(w.STATE.timer); w.STATE.timer = null;
    const realFetch = w.fetch;
    const seen = [];
    w.fetch = (url, opts) => { seen.push(String(url)); return realFetch(url, opts); };
    w.STATE.busy = false; w.STATE.pendingForce = false;
    w.tick(true); w.tick(true);
    await wait(1800);
    const n = seen.filter(u => /api=status/.test(u)).length;
    w.fetch = realFetch;
    if (n > 1) errors.push('an action and its PIN wrapper asked for the whole status ' + n + ' times');
    console.log('an action and the PIN wrapper around it cost ' + n + ' status fetch(es)');
  } catch (e) { errors.push('the one-press-one-refresh check itself failed: ' + e.message); }

  // ---- the approvals clock does not re-fetch the blocked list every turn --
  try {
    const tab = d.querySelector('.tabs button[data-tab="approvals"]');
    if (tab) { tab.click(); await wait(1500); }
    if (!w.isUnlocked()) {
      console.log('editing is locked here, so the approvals lists are not asked for at all - skipped');
    } else {
      const realFetch = w.fetch;
      const seen = [];
      w.fetch = (url, opts) => { seen.push(String(url)); return realFetch(url, opts); };
      w.APPROVALS.inflight = 0; w.APPROVALS.blockedAt = 0;
      w.loadApprovals(true, true); await wait(1200);     // as the tab's own clock asks
      const first = seen.filter(u => /api=blocked/.test(u)).length;
      seen.length = 0;
      w.APPROVALS.inflight = 0;
      w.loadApprovals(true, true); await wait(1200);     // the clock again, a second later
      const second = seen.filter(u => /api=blocked/.test(u)).length;
      seen.length = 0;
      w.APPROVALS.inflight = 0;
      w.loadApprovals(true); await wait(1200);           // somebody asking, not the clock
      const asked = seen.filter(u => /api=blocked/.test(u)).length;
      w.fetch = realFetch;
      if (first < 1) errors.push('the approvals tab never asked for the blocked list at all');
      if (second > 0) {
        errors.push('the approvals clock fetched the 123 KB blocked list again ' + second
          + ' time(s) a second later');
      }
      if (asked < 1) {
        errors.push('the blocked list is held back from somebody who asked for it, not only from '
          + 'the clock - so a block taken off the list would stay on the page');
      }
      console.log('the approvals clock asks for the blocked list once (' + first + '), not again a '
        + 'second later (' + second + '), and somebody asking still gets it (' + asked + ')');
    }
  } catch (e) { errors.push('the approvals-clock check itself failed: ' + e.message); }

  // 5.17: what a device sends is text, wherever it lands. A rule's "now"
  // reading and a chart's unit and colour went into the page as HTML: a
  // converter that reports a string, or a unit in a device's definition, could
  // put markup - and script - into the page of whoever looked.
  try {
    const list = d.getElementById('rules-list');
    if (list) {
      const spot = d.createElement('div'); spot.className = 'now'; spot.dataset.rule = 'xss-probe';
      list.appendChild(spot);
      w.updateRuleReadings({rules: [{id: 'xss-probe', reading: '<img id="xss-reading" src="x">', holds: false}]});
      if (d.getElementById('xss-reading')) errors.push('a rule\'s reading went into the page as HTML');
      spot.remove();
    }
    // a chart of its own, dense enough that every point of it has a reading
    const box = d.createElement('div'); box.id = 'xss-chart'; box.className = 'chart';
    d.body.appendChild(box);
    const now = Math.floor(Date.now() / 1000), pts = [];
    for (let i = 0; i <= 60; i++) pts.push([now - 3600 + i * 60, 20 + (i % 7)]);
    w.drawChart(box, [{name: 'Probe', points: pts, unit: '<img id="xss-unit" src="x">',
                       color: 'red"><img id="xss-color" src="x"><b x="'}], {});
    const svg = box.querySelector('svg');
    let shown = '';
    if (svg) {
      svg.getBoundingClientRect = function () { return {left: 0, top: 0, width: 1000, height: 200, right: 1000, bottom: 200}; };
      for (const x of [300, 500, 700]) {
        svg.dispatchEvent(new w.MouseEvent('mousemove', {clientX: x, clientY: 100, bubbles: true}));
        shown = ((box.querySelector('.tip') || {}).innerHTML || '');
        if (shown) break;
      }
    }
    if (!shown) errors.push('the probe chart showed no readout, so its unit and colour could not be looked at');
    if (d.getElementById('xss-unit') || d.getElementById('xss-color')) {
      errors.push('a chart\'s unit or colour went into the page as HTML');
    }
    box.remove();
    const key = d.createElement('div'); d.body.appendChild(key);
    w.legend(key, [{name: 'Probe', color: 'red"><img id="xss-legend" src="x"><b x="'}]);
    if (d.getElementById('xss-legend')) errors.push('a chart\'s legend put its colour into the page as HTML');
    key.remove();
    console.log('a reading, a unit and a colour from a device stay text');
  } catch (e) { errors.push('the device-text check itself failed: ' + e.message); }

  // 5.17: the live log of a database job is asked for every 0.9 s while the
  // job runs. With the lock run out in the middle of one, its answer "view
  // locked" brought the PIN box up by itself, again and again - and while the
  // box held the focus, no card on the page was drawn again.
  try {
    const keep = {who: w.LOCK.who};
    const pinBack = d.getElementById('pinback');
    w.LOCK.who = null;
    // a box already up - from this very fault, on a page that has it - is
    // put away first, so what is looked at is what the next answer does
    for (let i = 0; i < 5 && !pinBack.hidden; i++) {
      const cancel0 = d.getElementById('pincancel');
      if (cancel0) cancel0.click();
      await wait(200);
    }
    w.VIEWLOCK.asking = false; w.VIEWLOCK.declined = false;
    await w.api('log&lines=40').catch(function () {});
    await wait(300);
    if (!pinBack.hidden) {
      errors.push('the live log of a database job brought the PIN box up by itself');
      const cancel = d.getElementById('pincancel');
      if (cancel) cancel.click();
      await wait(200);
    }
    w.LOCK.who = keep.who; w.VIEWLOCK.asking = false;
    console.log('a database job\'s live log, refused for the PIN, does not ask for it by itself');
  } catch (e) { errors.push('the job-log check itself failed: ' + e.message); }

  // 5.17: the watts are read from where the status carries them - a plain
  // number under values.power. 5.16 read values['switch.apower'].value, which
  // the daemon never sends, so the socket card showed no watts at all.
  // 5.16: the socket controls keep their buttons while the watts move. The
  // whole card - every On and Off button with it - was built again whenever
  // any reading changed, which is nearly every status: a tap whose press and
  // release fell either side of a rebuild landed on a button that was no
  // longer there, and nothing happened.
  try {
    if (typeof w.plugCtlShape !== 'function' || typeof w.refreshPlugFigures !== 'function') {
      errors.push('the socket controls have no way to tell their shape from their figures');
    } else {
      const mk = watts => ({plugs: [{name: 'Probe-Socket', output: 1, online: true, stale: false,
        host: '192.0.2.10', info: {model: 'S3PL'}, values: {power: watts},
        counters: [{type: 'aenergy', label: 'Energy', value: 1234 + watts, help: 'x'}]}],
        pulse_ms: {default: 5000}, pulsing: []});
      const a = mk(41.5), b = mk(87.25);
      if (JSON.stringify(w.plugCtlShape(a)) !== JSON.stringify(w.plugCtlShape(b))) {
        errors.push('the watts moving changes the shape of the socket controls, so the card is rebuilt');
      }
      d.getElementById('plug-control').hidden = false;
      w.renderPlugControls(a);
      const btn = d.querySelector('#plug-control-list .pc-block[data-plug="Probe-Socket"] .pc-btns button');
      w.refreshPlugFigures(b);
      const after = d.querySelector('#plug-control-list .pc-block[data-plug="Probe-Socket"] .pc-btns button');
      const drawn = (d.querySelector('#plug-control-list .pc-block[data-plug="Probe-Socket"] .pc-draw') || {}).textContent || '';
      if (!btn || btn !== after) errors.push('the On/Off button of a socket was replaced when only its watts moved');
      if (drawn.indexOf('87') < 0) errors.push('the socket card did not show the new watts: ' + drawn);
      // ...and a real change of shape still rebuilds it
      const c = mk(87.25); c.plugs[0].output = 0;
      if (JSON.stringify(w.plugCtlShape(c)) === JSON.stringify(w.plugCtlShape(b))) {
        errors.push('switching a socket off does not change the shape of its controls');
      }
      console.log('the socket controls keep their buttons while the watts move, and show the new watts (' + drawn + ')');
    }
  } catch (e) { errors.push('the socket-controls check itself failed: ' + e.message); }

  // php2shell (CVE-2026-109618, CVE-2026-109619, 21 October 2026): the page
  // has to say which PHP is serving it and whether that one carries the fix.
  // On the card about the server in front, because the health card answers
  // without a PIN and the version of PHP is the first thing anybody deciding
  // what to try would like to be told.
  try {
    const un2 = await signIn();
    if (!un2.who) {
      errors.push('could not unlock to look at what the page says about PHP');
    } else {
      w.signedInAs(un2.who);
      const told = await (await jfetch(base + 'index.php?api=proxy')).json();
      const php = told.php || {};
      if (!php.found) {
        console.log('no PHP on this machine to say anything about - skipped');
      } else {
        if (!php.version) errors.push('the page is told nothing about which PHP serves it');
        if (!(php.cves || []).length) errors.push('the page is not told what the two holes are called');
        const panel = w.proxyPanel();
        d.body.appendChild(panel);
        // until the card has said it, or five seconds: on a daemon busy with
        // the rest of this run a fixed second and a half was sometimes short
        const said_now = () => Array.from(panel.querySelectorAll('div'))
          .map(e => e.textContent.trim()).filter(Boolean).join(' ');
        for (let i = 0; i < 50 && said_now().indexOf('PHP ') < 0; i++) await wait(100);
        const said = said_now();
        if (said.indexOf(php.version) < 0) {
          errors.push('the card does not say which PHP serves the page: ' + said.slice(0, 120));
        }
        if (php.vulnerable) {
          if (!panel.querySelector('.bad')) {
            errors.push('a PHP with the two holes of 21 October 2026 is not painted as critical');
          }
          for (const cve of php.cves) {
            if (said.indexOf(cve) < 0) errors.push('the card does not name ' + cve);
          }
        }
        console.log('the card about the server in front says PHP ' + php.version + ', '
          + (php.vulnerable ? 'with the two holes of 21 October 2026, painted as critical'
                            : 'carrying the fix'));
      }
    }
  } catch (e) { errors.push('the PHP-version check itself failed: ' + e.message); }


  // 5.18: the panes root looks after - the firewall and who may reach the
  // pages, the certificate, upgrades, the whole installation - drawn as otp
  // draws them, locked until the PIN, and their popup asking twice before
  // anything that destroys.
  try {
    if (!w.CONTROL_SECTIONS['sec-firewall'] || !w.CONTROL_SECTIONS['sys-certs'] || !w.CONTROL_SECTIONS['sys-upgrade']) {
      errors.push('there is no Firewall, Certificates or Upgrades section in Control');
    } else {
      d.querySelector('.tabs button[data-tab="control"]').click();
      const keepTok = w.LOCK.who;
      w.LOCK.who = null;
      w.showControlSection('sec-firewall'); await wait(300);
      if (!/Sign in/.test((d.getElementById('fw-access') || {}).textContent || '')) {
        errors.push('the firewall pane does not say it is locked while it is');
      }
      const un = await signIn();
      w.signedInAs(un.who);
      w.showControlSection('sec-firewall');
      for (let i = 0; i < 300 && !d.querySelector('#fw-access .fw-acc-row'); i++) await wait(100);
      const rows = d.querySelectorAll('#fw-access .fw-acc-row').length;
      const autos = d.querySelectorAll('#fw-body .fw-auto-card').length;
      if (rows !== 3) errors.push('the access lists drew ' + rows + ' row(s), not 3');
      if (!autos) errors.push('the firewall pane does not show what zigmon lets in by itself');
      if (!d.querySelector('#fw-master .sw')) errors.push('the firewall has no switch to turn it on');
      // a rule of one's own, through the popup and the daemon's own check
      w.fwRuleEdit(w.FW.last, null); await wait(50);
      const zm = d.getElementById('zmodal');
      if (!zm || zm.hidden) errors.push('the rule popup did not open');
      const port = d.querySelector('#zmodal-body input[type=text]');
      if (port) { port.value = '10050'; port.dispatchEvent(new w.Event('input', {bubbles: true})); }
      const add = Array.from(d.querySelectorAll('#zmodal-foot button')).find(b => /Add it/.test(b.textContent));
      if (add) add.click();
      // php -S answers one request at a time, and the page's long poll may
      // hold it for up to 25 s
      for (let i = 0; i < 300 && !zm.hidden; i++) await wait(100);
      if (!zm.hidden) errors.push('the rule popup did not close after Add it: ' + d.getElementById('toast').textContent);
      const mine = Array.from(d.querySelectorAll('#fw-body table.fw-table tbody tr')).map(r => r.textContent).join(' ');
      if (mine.indexOf('10050') < 0) errors.push('the rule added is not in the list of rules of your own');
      if (!/Unsaved/.test(d.getElementById('fw-note').textContent)) errors.push('an unsaved rule is not said to be unsaved');
      // each card saves itself, as every other card of zigmon does
      if (!d.querySelector('#fw-access-card #fw-access-save') || !d.querySelector('#fw-card #fw-save')
          || d.getElementById('fw-savebar')) {
        errors.push('the two firewall cards do not each have a Save of their own');
      }
      if (/Unsaved/.test(d.getElementById('fw-access-note').textContent)) {
        errors.push('a rule of the firewall marked who may reach the pages as unsaved');
      }
      w.FW.dirty = false; w.FW.draft = null; w.loadFw(); await wait(400);
      // anything that destroys asks twice
      let did = 0;
      w.zmodal('Test', null, [{words: 'No', close: true}, {words: 'Destroy', cls: 'danger', close: true, go: () => { did += 1; }}], 'narrow');
      const foot = d.getElementById('zmodal-foot');
      Array.from(foot.querySelectorAll('button')).find(b => /Destroy/.test(b.textContent)).click();
      if (did) errors.push('a destroying button acted on the first click');
      const strip = foot.querySelector('.sure-strip');
      const shown = Array.from(foot.children).filter(c => c !== strip && c.style.display !== 'none');
      if (shown.length) errors.push('"Really?" stands beside the buttons it asks about instead of in their place');
      if (!strip) errors.push('a destroying button did not ask "Really?"');
      else Array.from(strip.querySelectorAll('button')).find(b => /Destroy/.test(b.textContent)).click();
      if (did !== 1 || !zm.hidden) errors.push('the second click did not do it and close the popup');
      // a popup that is itself the question asks it once
      let once = 0;
      w.zconfirm('Test', 'words', 'Throw it away', () => { once += 1; });
      Array.from(d.querySelectorAll('#zmodal-foot button')).find(b => /Throw it away/.test(b.textContent)).click();
      if (once !== 1 || !zm.hidden) errors.push('a question in a popup asked "Really?" a second time');
      w.showControlSection('sys-certs');
      for (let i = 0; i < 300 && !d.querySelector('#web-certs .cert-card'); i++) await wait(100);
      if (!d.querySelector('#web-certs .cert-card')) errors.push('the certificate pane drew no card');
      w.showControlSection('sys-upgrade');
      for (let i = 0; i < 300 && !d.querySelector('#up-nodes table'); i++) await wait(100);
      const verCell = d.querySelector('#up-nodes tbody td.mono');
      if (!verCell || !/^\d+\.\d+\.\d+$/.test(verCell.textContent)) {
        errors.push('the upgrade pane does not say which version runs');
      }
      if (!d.querySelector('#up-drop-slot .drop')) errors.push('there is nowhere to drop a new version');
      w.showControlSection('sys-backup');
      for (let i = 0; i < 300 && !d.querySelector('#full-list table'); i++) await wait(100);
      if (!d.querySelector('#full-list table')) errors.push('the whole-installation backup drew no list');
      if (!d.querySelector('#full-drop-slot .drop')) errors.push('there is nowhere to drop a whole backup');
      console.log('firewall: ' + rows + ' access lists, ' + autos + ' kinds let in by itself; certificate, upgrade and whole-backup panes drawn; destroying asks twice');
      w.LOCK.who = keepTok;
      w.showControlSection('dev-devices');
    }
  } catch (e) { errors.push('the root panes check itself failed: ' + e.message); }

  // 5.19: signing in by name and password, as otp does, in place of the PIN.
  try {
    if (typeof w.signedInAs !== 'function' || !d.getElementById('signin-name') || !d.getElementById('signin-pass')) {
      errors.push('there is no sign-in with a name and a password on the page');
    } else {
      const keepWho = w.LOCK.who;
      // signed out, the pill offers to sign in, and no PIN box is anywhere
      await jfetch(base + 'index.php?api=logout', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
      w.setLocked(null); w.renderLock();
      const pinHouse = w.pinShape().pin;
      w.PIN.prefer = '';                  // the page keeps a name chosen earlier; start where a newcomer would
      if (!(pinHouse ? /Locked/ : /Sign in/).test(d.getElementById('lockpill-text').textContent)) errors.push('signed out, the header does not offer to sign in');
      // through the dialogue a person uses: a wrong password is said, the right one signs in
      w.unlockFlow(); await wait(300);
      const back = d.getElementById('pinback');
      if (back.hidden) errors.push('asking to sign in opened no dialogue');
      // 5.19.1: where there are PIN accounts the dialogue asks for the PIN first, the
      // digit boxes as before; a name and a password are one click away
      if (pinHouse) {
        if (d.getElementById('pindigits').hidden || !d.querySelector('#pindigits input')) errors.push('a house with PIN accounts is not asked for the PIN');
        d.getElementById('pin-other-link').click(); await wait(100);
      }
      if (d.getElementById('signform').hidden) errors.push('the name and the password cannot be typed');
      d.getElementById('signin-name').value = 'admin'; d.getElementById('signin-pass').value = 'not the password';
      d.getElementById('pinok').click();
      for (let i = 0; i < 50 && !d.getElementById('pinerr').textContent; i++) await wait(100);
      if (!/not right/.test(d.getElementById('pinerr').textContent)) errors.push('a wrong password is not said: ' + d.getElementById('pinerr').textContent);
      d.getElementById('signin-pass').value = 'admin pass 1';
      d.getElementById('pinok').click();
      for (let i = 0; i < 50 && !back.hidden; i++) await wait(100);
      if (!back.hidden || !w.isAdmin()) errors.push('the right password did not sign the administrator in');
      if (!/admin/.test(d.getElementById('lockpill-text').textContent)) errors.push('signed in, the header does not say who');
      if (JSON.stringify(w.LOCK).indexOf(JAR.replace('zigmon_session=', '') || '@@') >= 0) errors.push('the page holds its sign-in’s token');
      // an operator uses the house, and is not offered what is an administrator's as theirs
      const op = await signIn('jan', 'operator pass 1');
      w.signedInAs(op.who); await wait(200);
      if (!w.signedIn() || !w.mayOperate() || w.isUnlocked()) errors.push('an operator is not told apart from an administrator');
      const plug = (w.STATE.status.plugs || [])[0];
      if (plug) {
        const r = await w.post('plug-switch', {name: plug.name, on: plug.output === 1});
        if (!r || r.ok !== true) errors.push('an operator cannot switch a socket: ' + JSON.stringify(r));
      }
      let refused = '';
      await w.post('config-save', {battery_warn: 21}).catch(e => { refused = e.message; });
      if (!/administrator/.test(refused)) errors.push('an operator saved a setting, or was not told why not: ' + refused);
      // the accounts are drawn for an administrator
      const ad = await signIn();
      w.signedInAs(ad.who);
      d.querySelector('.tabs button[data-tab="control"]').click();
      w.showControlSection('sec-access');
      for (let i = 0; i < 100 && !d.querySelector('#accounts-list tbody tr'); i++) await wait(100);
      const names = Array.from(d.querySelectorAll('#accounts-list tbody tr b')).map(b => b.textContent);
      if (names.indexOf('admin') < 0 || names.indexOf('jan') < 0) errors.push('the accounts are not listed: ' + names.join(','));
      // a password somebody else gave is changed before anything else
      w.signedInAs(Object.assign({}, ad.who, {must_change: true})); await wait(200);
      if (d.getElementById('zmodal').hidden || !/own password/.test(d.getElementById('zmodal-title').textContent)) {
        errors.push('a password given by somebody else does not ask for one of their own');
      }
      w.closeZModal();
      w.signedInAs(ad.who);
      console.log('signing in: a wrong password said, the administrator and the operator told apart, the accounts listed');
      if (!keepWho) { w.LOCK.who = null; }
      w.showControlSection('dev-devices');
    }
  } catch (e) { errors.push('the sign-in check itself failed: ' + e.message); }

  // 5.19.1: a PIN account unlocks as the PIN always did - a box per digit, the
  // last digit unlocks, "Editing 14:59" counting down, locked when it is up.
  try {
    if (typeof w.pinShape !== 'function' || !d.getElementById('unlock-minutes')) {
      errors.push('the page has no PIN accounts');
    } else if (!w.pinShape().pin) {
      errors.push('the rig has no PIN account, so the PIN unlock is not checked');
    } else {
      await jfetch(base + 'index.php?api=logout', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
      w.setLocked(null); w.PIN.prefer = ''; w.renderLock();
      w.unlockFlow(); await wait(300);
      const boxes = Array.from(d.querySelectorAll('#pindigits input'));
      if (boxes.length !== w.pinShape().length) errors.push('the PIN is not asked for a box per digit: ' + boxes.length);
      '1234'.split('').forEach((c, i) => { boxes[i].value = c; boxes[i].dispatchEvent(new w.Event('input', {bubbles: true})); });
      for (let i = 0; i < 50 && !d.getElementById('pinback').hidden; i++) await wait(100);
      const who = w.LOCK.who || {};
      if (who.kind !== 'pin') errors.push('the last digit did not unlock: ' + d.getElementById('pinerr').textContent);
      w.renderLock();
      const pill = d.getElementById('lockpill-text').textContent;
      if (!/^Editing \d+:\d\d$/.test(pill.trim())) errors.push('unlocked with a PIN, the header does not count down: ' + pill);
      // the end as this browser's clock has it (5.20), from the seconds left
      w.LOCK.who.ends = w.LOCK.who.until = Date.now() / 1000 - 1; w.renderLock(); await wait(300);
      if (w.LOCK.who || !/Locked/.test(d.getElementById('lockpill-text').textContent)) errors.push('the unlock goes on when its time is up');
      // a dialogue closed at once must not leave a hidden box holding the focus,
      // which reads as somebody typing and holds every repaint back
      w.unlockFlow(); w.closePin(null); await wait(150);
      if (d.getElementById('pinback').contains(d.activeElement)) errors.push('a closed PIN dialogue keeps the focus in a hidden box, and the page stops repainting');
      console.log('PIN accounts: a box per digit, the countdown in the header, locked when it is up');
      const ad = await signIn(); w.signedInAs(ad.who);
    }
  } catch (e) { errors.push('the PIN check itself failed: ' + e.message); }
  console.log('errors:', errors.length ? errors : 'none');
  w.close(); process.exit(0);
})().catch(e => { console.error('FAIL', e); process.exit(1); });
