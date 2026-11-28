// The page half of test/review5594_esp32_ui.py: the cards of an ESP32 gateway's things, at a
// desktop's width and a phone's. Prints one JSON line: {bad: [...], said: [...], checked: n}.
const { chromium } = require('playwright');
const cfg = JSON.parse(process.env.H_CFG);
const wait = ms => new Promise(r => setTimeout(r, ms));
const out = {bad: [], said: [], checked: 0};
const ok = (cond, what) => { out.checked++; if (!cond) out.bad.push(what); return cond; };
(async () => {
  const b = await chromium.launch();
  for (const vw of [[1440, 1800, 'desktop'], [390, 2600, 'phone']]) {
    const ctx = await b.newContext({viewport: {width: vw[0], height: vw[1]}, colorScheme: 'dark'});
    const p = await ctx.newPage();
    const errors = [];
    p.on('pageerror', e => errors.push(String(e).slice(0, 200)));
    p.setDefaultTimeout(15000);
    await p.goto(cfg.base + '/');
    await p.evaluate(async () => fetch('?api=login', {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: 'owner', password: 'owner pass 12'})}));
    await p.goto(cfg.base + '/');
    await p.waitForFunction(() => window.STATE && STATE.status && (STATE.status.esp || {}).entities, null, {timeout: 15000});
    await p.evaluate(() => showTab('overview'));
    await wait(1500);
    const W = vw[2] + ': ';
    // ---- the Overview grid
    const card = async id => p.evaluate(id => {
      const c = document.querySelector('#overview-custom .esp-dev[data-esp="' + id + '"]');
      if (!c) return null;
      const q = s => c.querySelector(s);
      const t = s => (q(s) || {}).textContent || '';
      return {text: c.textContent, cls: c.className, tag: t('.dev-band .tag'), main: t('.reading.esp-v .v'),
              mainCls: (q('.reading.esp-v') || {}).className || '', mainL: t('.reading.esp-v .l'),
              last: t('.esp-last-r .v'), lastCls: (q('.esp-last-r') || {}).className || '',
              acts: Array.from(c.querySelectorAll('.esp-acts .btn')).map(x => x.className),
              batt: t('.f-batt'), via: t('.f-via'), sig: t('.f-lqi'), mdl: t('.head .mdl'), sw: !!q('.esp-acts .sw'),
              setbox: !!q('.esp-setbox'), art: (q('.esp-dev-art') || {}).className || ''};
    }, id);
    const fr = await card(cfg.front);
    if (ok(fr, W + 'no card for the lock in the Overview grid')) {
      ok(fr.tag === 'online', W + 'the lock\'s pill: ' + fr.tag);
      ok(fr.mdl === 'ESP32 Gateway · Yeelock locks', W + 'the lock\'s model line: ' + fr.mdl);
      ok(fr.main === 'locked' && / ok/.test(fr.mainCls) && fr.mainL.toLowerCase() === 'lock', W + 'the lock\'s state: ' + JSON.stringify(fr));
      ok(/ok/.test(fr.art), W + 'the lock\'s icon not green: ' + fr.art);
      ok(/✓/.test(fr.last) && / ok/.test(fr.lastCls), W + 'the last action: ' + fr.last);
      ok(['open', 'unlock', 'lock', 'refresh'].every(a => fr.acts.some(c => c.indexOf('esp-act-' + a) >= 0)), W + 'the buttons: ' + fr.acts);
      ok(fr.acts.filter(c => /esp-sensitive/.test(c)).length === 2, W + 'the sensitive ones: ' + fr.acts);
      ok(/^Battery \d+%$/.test(fr.batt.trim()), W + 'the battery: ' + fr.batt);
      ok(fr.via.trim() === 'via Hall', W + 'the way in: ' + fr.via);
      ok(/-58 dBm/.test(fr.sig), W + 'the gateway\'s Wi-Fi: ' + fr.sig);
    }
    const ga = await card(cfg.gar);
    if (ok(ga, W + 'no card for the garage box')) {
      ok(/\bcrit\b/.test(ga.cls) && ga.tag === 'crit', W + 'a low battery not said on the card: ' + ga.cls + ' ' + ga.tag);
    }
    const fan = await card(cfg.fan);
    ok(fan && fan.sw && fan.main === 'off' && fan.mainL.toLowerCase() === 'switch', W + 'the switch: ' + JSON.stringify(fan));
    const lid = await card(cfg.lid);
    ok(lid && lid.main === 'yes' && !lid.acts.length, W + 'the binary sensor: ' + JSON.stringify(lid));
    const box = await card(cfg.box);
    ok(box && /21\.5/.test(box.main) && /°C/.test(box.text), W + 'the sensor: ' + JSON.stringify(box));
    const beam = await card(cfg.beam);
    ok(beam && beam.tag === 'gone' && beam.main === 'gone' && /esp-t-unknown/.test(beam.cls), W + 'the gone thing: ' + JSON.stringify(beam));
    ok(beam && beam.acts.some(c => /danger/.test(c)), W + 'the gone thing has no Remove: ' + JSON.stringify(beam && beam.acts));
    const gw = await p.evaluate(() => { const c = document.querySelector('#overview-custom .esp-gwtile'); return c ? c.textContent : null; });
    ok(gw && /ESP32 Gateway · ESP32-S3/.test(gw) && /online/.test(gw) && /v1\.0\.0/.test(gw) && /synced/.test(gw)
       && /Yeelock locks/.test(gw) && /Relay/.test(gw), W + 'the gateway\'s card: ' + gw);
    ok(await p.evaluate(() => document.getElementById('esp-dash').hidden), W + 'the locks drawn twice on the Overview');
    // an unknown type in a card: a number and a choice by their type
    const kinds = await p.evaluate(() => {
      const st = JSON.parse(JSON.stringify(STATE.status));
      const e0 = st.esp.entities.filter(e => e.type === 'lock')[0];
      const mk = (type, extra) => Object.assign({}, e0, {id: e0.id + type, type: type, actions: [], confirm: [], attrs: [],
                                                         values: {}, last: null}, extra);
      st.esp.entities.push(mk('number', {actions: ['set'], value: 40, unit: '%', min: 0, max: 100}),
                           mk('select', {actions: ['set'], value: 'quiet', options: ['auto', 'quiet', 'boost']}),
                           mk('button', {actions: ['press']}), mk('cover', {actions: ['open', 'close', 'stop'], value: 'open'}),
                           mk('text', {value: 'hello'}));
      const d0 = st.devices.filter(d => d.id === e0.id)[0];
      return ['number', 'select', 'button', 'cover', 'text'].map(t => {
        const c = buildDeviceCard(Object.assign({}, d0, {id: e0.id + t}), st);
        return [t, c.className, (c.querySelector('.reading.esp-v .v') || {}).textContent || '', !!c.querySelector('.esp-setbox'),
                Array.from(c.querySelectorAll('.esp-acts .btn')).map(x => x.textContent.trim()).join(',')];
      });
    });
    const K = {}; kinds.forEach(k => { K[k[0]] = k; });
    ok(/esp-t-number/.test(K.number[1]) && K.number[2] === '40%' && K.number[3], W + 'a number: ' + K.number);
    ok(K.select[2] === 'quiet' && K.select[3], W + 'a select: ' + K.select);
    ok(/Press/.test(K.button[4]), W + 'a button: ' + K.button);
    ok(K.cover[2] === 'open' && /Close/.test(K.cover[4]) && /Stop/.test(K.cover[4]), W + 'a cover: ' + K.cover);
    ok(K.text[2] === 'hello' && !K.text[4], W + 'a text: ' + K.text);
    // the confirm step: Unlock asks, "No" sends nothing
    if (vw[2] === 'desktop') {
      await p.click('#overview-custom .esp-dev[data-esp="' + cfg.front + '"] .esp-act-unlock');
      await wait(400);
      const modal = await p.evaluate(() => { const m = document.getElementById('zmodal'); return m && !m.hidden ? m.textContent : ''; });
      ok(/Unlock Front drawer/.test(modal), W + 'no confirm step for unlock: ' + modal.slice(0, 120));
      await p.click('#zmodal-foot button >> nth=0');
      await wait(1500);
      ok((await card(cfg.front)).main === 'locked', W + 'unlocked after "No"');
      // lock: no confirm, the spinner while it works, then the new last action
      await p.click('#overview-custom .esp-dev[data-esp="' + cfg.front + '"] .esp-act-lock');
      let spun = false;
      for (let i = 0; i < 30 && !spun; i++) {
        spun = await p.evaluate(id => !!document.querySelector('#overview-custom .esp-dev[data-esp="' + id + '"] .esp-wait, '
          + '#overview-custom .esp-dev[data-esp="' + id + '"] .btn.busy'), cfg.front);
        await wait(50);
      }
      ok(spun, W + 'no spinner while it worked');
      await wait(2500);
      const after = await card(cfg.front);
      ok(/locked ✓/.test(after.last), W + 'the last action after Lock: ' + after.last);
      // the object view
      await p.evaluate(id => openObject('device:' + id), cfg.front);
      await wait(1200);
      const pop = await p.evaluate(() => { const x = document.querySelector('.objpop, #objpop, .obj-pop'); return x ? x.textContent : document.body.textContent; });
      ok(['gateway', 'module', 'last_action', 'last_ok', 'available', 'unlock', 'refresh'].every(k => pop.indexOf(k) >= 0),
         W + 'the object view lacks a member');
      await p.keyboard.press('Escape');
      // the Overview picker: a thing taken off the grid is offered under its gateway, and its card is on the locks card
      await p.evaluate(id => { saveOverviewLayout(overviewLayoutIds(STATE.status).filter(x => x !== id)); }, cfg.front);
      await wait(2500);
      const pick = await p.evaluate(id => {
        const o = Array.from(document.querySelectorAll('#ov-add-select option')).filter(x => x.value === id)[0];
        // a long list is grouped by heading: the lock's is its gateway's
        return o ? [o.textContent, optionGroup(id, o.textContent), optionGroup(id.split(':').slice(0, 2).join(':'), '')] : null;
      }, cfg.front);
      ok(pick && /Front drawer/.test(pick[0]) && pick[0].indexOf('🔒') === 0 && pick[1] === 'ESP32 gateway Hall'
         && pick[2] === 'ESP32 gateway Hall', W + 'the picker for the lock: ' + JSON.stringify(pick));
      ok(await p.evaluate(id => !document.getElementById('esp-dash').hidden
         && !!Array.from(document.querySelectorAll('#esp-dash .esp-tile b')).filter(b => b.textContent === 'Front drawer').length, cfg.front),
         W + 'the lock taken off the grid is not on the locks card');
      await p.evaluate(id => { saveOverviewLayout(overviewLayoutIds(STATE.status).concat([id])); }, cfg.front);
      await wait(2000);
    }
    if (vw[2] === 'phone') {
      const over = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      ok(over <= 0, W + 'the page is wider than the phone by ' + over);
    }
    // ---- the Devices tab: the things under their gateway
    await p.evaluate(() => showTab('devices'));
    await wait(1200);
    const rows = await p.evaluate(() => Array.from(document.querySelectorAll('#devices-table tbody tr')).map(tr =>
      [tr.className, (tr.querySelector('td b') || {}).textContent]));
    const at = rows.findIndex(r => r[1] === 'Hall');
    ok(at >= 0 && rows.slice(at + 1, at + 8).every(r => /esp-kid/.test(r[0])), W + 'the Devices tab not grouped: ' + JSON.stringify(rows));
    // ---- Settings - Devices: the gateway, its modules, their things
    await p.evaluate(() => { showTab('control'); showControlSection('dev-devices'); });
    await wait(2500);
    const tree = await p.evaluate(() => {
      const g = document.querySelector('#esp-card .esp-gw');
      if (!g) return null;
      return {mods: Array.from(g.querySelectorAll('.esp-mod-sec')).map(s => [s.querySelector('.section-name').textContent,
                s.querySelectorAll('.esp-ent').length, s.querySelectorAll('.esp-ent.gone').length]),
              switches: g.querySelectorAll('.esp-ent .sw').length, tests: Array.from(g.querySelectorAll('.esp-ent-tools .btn')).map(x => x.textContent.trim()),
              fold: !!g.querySelector('.esp-gw-fold')};
    });
    if (ok(tree, W + 'no gateway in Settings')) {
      const M = {}; tree.mods.forEach(m => { M[m[0]] = m; });
      ok(M['Yeelock locks'] && M['Yeelock locks'][1] === 3 && M['Relay'] && M['Relay'][1] === 2
         && M['Climate'] && M['Climate'][2] === 1, W + 'the modules and their things: ' + JSON.stringify(tree.mods));
      ok(tree.switches >= 6 && tree.tests.filter(x => x === 'Test').length === 3 && tree.tests.indexOf('Remove') >= 0 && tree.fold,
         W + 'the rows\' tools: ' + JSON.stringify(tree));
    }
    // ---- Find anything
    await p.evaluate(() => openFind());
    await p.keyboard.type('Front dr');
    await wait(700);
    const found = await p.evaluate(() => document.getElementById('findlist').textContent);
    ok(/Front drawer/.test(found), W + 'Find anything does not find the lock: ' + found.slice(0, 200));
    await p.keyboard.press('Escape');
    // ---- no secret on the page
    const html = await p.content();
    ok(cfg.key && html.indexOf(cfg.key) < 0, W + 'the device key on the page');
    ok(errors.length === 0, W + 'page errors: ' + errors.join(' | '));
    out.said.push(W + 'checked');
    await ctx.close();
  }
  await b.close();
  console.log(JSON.stringify(out));
})().catch(e => { out.bad.push('the script: ' + String(e).slice(0, 300)); console.log(JSON.stringify(out)); process.exit(0); });
