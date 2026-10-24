// What Ctrl+Space offers inside {…}, checked against the rules the daemon
// fills a message by. It needs neither the daemon nor php: the functions are
// lifted out of index.php and run against a made-up dashboard.
//
//     node test/completer.js
//
// It exists because {PIR-Chodba.model.nl} could not be typed. A dot after a
// device name offered that device's readings, and a dot after a fact offered
// the turns of phrase - but a dot after a device's READING offered nothing at
// all, which is exactly where .nl belongs. Worse, what was chosen was put
// back over everything after the first dot, so picking a turn there turned
// {Name.model.nl} into {Name.nl}.
const fs = require('fs');
const path = require('path');

const page = fs.readFileSync(path.join(__dirname, '..', 'web', 'index.php'), 'utf8');
const script = page.slice(page.indexOf('<script>')).split('\n');

function grab(name) {                       // a top-level function, brace at column 0
  const start = script.findIndex(l => l.startsWith('function ' + name + '('));
  if (start < 0) throw new Error('index.php no longer has function ' + name);
  let end = start + 1;
  while (end < script.length && script[end] !== '}') end++;
  return script.slice(start, end + 1).join('\n');
}
function grabList(name) {
  const m = script.join('\n').match(new RegExp('var ' + name + ' = \\[[\\s\\S]*?\\n\\];'));
  if (!m) throw new Error('index.php no longer has ' + name);
  return m[0];
}

const lifted = [grabList('FACT_TURN_LIST'), grabList('FACT_TURN_ARGS'), grabList('FACT_BLOCKS'),
  grabList('SCRIPT_BLOCKS'), grabList('DEVICE_FACT_KEYS'), grabList('ROOM_FACT_KEYS'),
  'deviceForFacts', 'roomForFacts', 'isFactTurn', 'factWithoutTurns', 'deviceKeyNames', 'turnItems',
  'blockItems', 'objForFacts', 'lazyObjects', 'objKindOf', 'objMemberItems', 'devRef', 'completerItems']
  .map(x => (x.indexOf('\n') >= 0 ? x : grab(x))).join('\n');

const stand = `
var COMPLETE_LOCAL = [];
var STATE = {status: {devices: [
  {id:'0x01', name:'PIR-Chodba', model:'SBMO-003Z', vendor:'Shelly', battery:88, linkquality:90, age_s:10, source:'zigbee',
   values:{occupancy:{value:true,label:'Occupancy'}, battery:{value:88,unit:'%'}, 'switch.apower':{value:12,unit:'W'}}}
], plugs: []}};
var OBJ_KIND_WORDS = {prop: 'property', func: 'function', proc: 'procedure'};
var OBJ = {types: {scene: {label: 'Scene'}, settings: {label: 'Settings'}, device: {label: 'Device'}, tap: {label: 'One-tap link'}},
  list: [
    {ref: 'scene:ab12', type: 'scene', name: 'Vecer', call: 'Vecer', members: [['name', 'prop', 0], ['actions', 'prop', 0], ['run', 'proc', 0]]},
    {ref: 'settings:settings', type: 'settings', name: 'Settings', call: 'Settings', members: [['sms_poll_s', 'prop', 1], ['pin', 'prop', 0]]},
    {ref: 'tap:66c2', type: 'tap', name: 'Kuchyne', call: 'tap:66c2', members: [['name', 'prop'], ['used', 'func']]},
    {ref: 'device:0x01', type: 'device', name: 'PIR-Chodba', call: 'PIR-Chodba', members: [['vendor', 'prop'], ['occupancy', 'func']]}
  ],
  // an address and a Wi-Fi client are not listed, and share their members
  lazy: {address: [['ip', 'prop', 0], ['blocked', 'prop', 1], ['left_min', 'func', 0], ['ban', 'proc', 0, 'value', '120']],
         client: [['name', 'prop', 0], ['belongs_to', 'func', 0], ['give_to', 'proc', 0, 'value', 'Jan']]}};
function loadObjects(){ return {then: function () {}}; }
var APPROVALS = {blocked: [{ip: '203.0.113.7', why: 'a test'}, {ip: '198.51.100.20', why: 'another'}]};
var WIFI_CLIENTS = [{mac: 'AA:BB:CC:DD:EE:FF', name: 'Pixel', ap_name: 'AP-Hall'}];
function factCatalogue(){ return [['Facts', [['home','who is in','Falco'],['attention_list','what wants a look','A, B']]]]; }
function deviceIcon(){ return ''; }
function ago(){ return '10s ago'; }
`;

const scope = {};
new Function('scope', stand + lifted + '\nscope.completerItems = completerItems; scope.FACT_BLOCKS = FACT_BLOCKS; '
  + 'scope.SCRIPT_BLOCKS = SCRIPT_BLOCKS; scope.blockItems = blockItems; scope.setLocals = function (v) { COMPLETE_LOCAL = v; };')(scope);
const completerItems = scope.completerItems;
const FACT_BLOCKS = scope.FACT_BLOCKS, SCRIPT_BLOCKS = scope.SCRIPT_BLOCKS;
const blockItems = scope.blockItems;

// what the box would hold if the first offer were taken, caret at the end
function accept(token) {
  const items = completerItems(token);
  if (!items.length) return '';
  const it = items[0];
  return ('{' + token).slice(0, 1 + (it.at || 0)) + it.text;
}

const cases = [
  // typed                        first offer          taken, it reads
  ['PIR-Chodba.',                 'state',             '{PIR-Chodba.state}'],
  ['PIR-Chodba.mod',              'model',             '{PIR-Chodba.model}'],
  ['PIR-Chodba.model.',           '.nl',               '{PIR-Chodba.model.nl}'],
  ['PIR-Chodba.model.n',          '.nl',               '{PIR-Chodba.model.nl}'],
  ['PIR-Chodba.model.nl.',        '.nl',               '{PIR-Chodba.model.nl.nl}'],
  ['PIR-Chodba.occupancy.yes',    '.yesno',            '{PIR-Chodba.occupancy.yesno}'],
  ['PIR-Chodba.switch.',          'switch.apower',     '{PIR-Chodba.switch.apower}'],
  ['PIR-Chodba.switch.apower.rou', '.round',           '{PIR-Chodba.switch.apower.round}'],
  ['home.',                       '.nl',               '{home.nl}'],
  ['home.nl.',                    '.nl',               '{home.nl.nl}'],
  ['PIR-Chodba.',                 'state',             '{PIR-Chodba.state}'],
  // every other object, and its members (4.86): a scene, the settings, a
  // link called by its address because a room has its name
  ['Vec',                         'Vecer.',            '{Vecer.'],
  ['Vecer.',                      'name',              '{Vecer.name}'],
  ['Vecer.act',                   'actions',           '{Vecer.actions}'],
  ['Settings.sms',                'sms_poll_s',        '{Settings.sms_poll_s}'],
  ['tap:66c2.us',                 'used',              '{tap:66c2.used}'],
  ['PIR-Chodba.ven',              'vendor',            '{PIR-Chodba.vendor}'],
  // (4.92) an address and a client: the dots and colons of their own are not
  // the dot that asks for a member
  ['address:203.0.113.7.bl',      'blocked',           '{address:203.0.113.7.blocked}'],
  ['address:203.0.113.7.left',    'left_min',          '{address:203.0.113.7.left_min}'],
  ['client:aa:bb:cc:dd:ee:ff.bel', 'belongs_to',       '{client:aa:bb:cc:dd:ee:ff.belongs_to}'],
  // (4.93) the addresses and clients there are, before the address is whole,
  // a client by its name, and an address still being typed is not one
  ['address:203',                 'address:203.0.113.7.', '{address:203.0.113.7.'],
  ['address:198.51.',             'address:198.51.100.20.', '{address:198.51.100.20.'],
  ['client:',                     'client:aa:bb:cc:dd:ee:ff.', '{client:aa:bb:cc:dd:ee:ff.'],
  ['Pix',                         'client:aa:bb:cc:dd:ee:ff.', '{client:aa:bb:cc:dd:ee:ff.'],
  ['Pixel.bel',                   'belongs_to',        '{Pixel.belongs_to}']
];

var bad = 0;
for (const [token, offer, reads] of cases) {
  const items = completerItems(token);
  const first = items.length ? items[0].label : '(nothing)';
  const got = accept(token);
  const ok = first === offer && got === reads;
  if (!ok) bad++;
  console.log('%s {%s%s %s%s',
    ok ? ' ' : '!', token, ' '.repeat(Math.max(1, 30 - token.length)), got || '(nothing offered)',
    ok ? '' : '   <-- wanted ' + reads + ' from ' + offer);
}
// The ready-made blocks: offered where a block can be written, and what they
// write is a whole one - every brace closed, every if and for ended - with
// the part worth changing picked out. A half-written block is worse than
// none: it is a message that quietly says nothing from then on.
function written(item) {
  // a block now carries its own braces: it is written where the caret is,
  // from a key of its own, rather than inside a "{" somebody typed
  return item.text;
}
function balanced(text) {
  var open = (text.match(/\{/g) || []).length, shut = (text.match(/\}/g) || []).length;
  return open === shut;
}
var blocksBad = 0;
[[false, 'a message'], [true, 'a script']].forEach(function (pair) {
  var bare = pair[0];
  var offered = completerItems('if', bare, 'blocks').filter(function (i) { return i.block; });
  if (!offered.length) { console.log('! no ready-made block offered for "if" in ' + pair[1]); blocksBad++; }
  completerItems('', bare, 'blocks').forEach(function (it) {
    var text = written(it);
    if (!bare && !balanced(text)) { console.log('! ' + it.label + ' in ' + pair[1] + ' leaves a brace open: ' + text); blocksBad++; }
    if (bare) {
      var opens = (text.match(/^\s*(if|for|while|repeat)\b/gm) || []).length;
      var ends = (text.match(/^\s*end\b/gm) || []).length;
      if (opens !== ends) { console.log('! ' + it.label + ' in a script opens ' + opens + ' block(s) and ends ' + ends); blocksBad++; }
    } else {
      var ifs = (text.match(/\{\s*(if|unless|for|repeat)\b/g) || []).length;
      var ends2 = (text.match(/\{\s*end\b/g) || []).length;
      if (ifs !== ends2) { console.log('! ' + it.label + ' opens ' + ifs + ' block(s) and ends ' + ends2); blocksBad++; }
    }
    if (!it.pick || text.indexOf(it.pick) < 0) {
      console.log('! ' + it.label + ' has nothing picked out to change'); blocksBad++;
    }
  });
});
// and a turn that carries something writes an example of it, with the part
// to change picked out
completerItems('home.def').filter(function (i) { return i.pick; }).forEach(function (it) {
  if (it.text.indexOf(it.pick) < 0) { console.log('! ' + it.label + ' picks out something it did not write'); blocksBad++; }
});
if (!completerItems('home.def').some(function (i) { return i.label === '.default:'; })) {
  console.log('! .default: is not offered after a fact'); blocksBad++;
}
// a procedure is done, never quoted: it is not offered inside braces; and
// each member says what kind of member it is
if (completerItems('Vecer.').some(function (i) { return i.label === 'run'; })) {
  console.log('! a procedure was offered inside braces'); blocksBad++;
}
if ((completerItems('Vecer.')[0] || {}).kind !== 'prop' || (completerItems('tap:66c2.us')[0] || {}).kind !== 'func') {
  console.log('! a member does not say whether it is a property or a function'); blocksBad++;
}
// at the start of a script line: what can be set, as a setting, and what can
// be done, as a call - and nothing that can only be read
var inScript = completerItems('Vecer.', true).map(function (i) { return i.text; });
if (inScript.join(',') !== 'run()') { console.log('! a script line after a scene offers ' + inScript.join(', ')); blocksBad++; }
var setIn = completerItems('Settings.', true).map(function (i) { return i.text; });
if (setIn.join(',') !== 'sms_poll_s = ') { console.log('! a script line after Settings offers ' + setIn.join(', ')); blocksBad++; }
// (4.92) a script line after an address or a client: set it, or call it
var onAddr = completerItems('address:203.0.113.7.', true).map(function (i) { return i.text; });
if (onAddr.join(',') !== 'blocked = ,ban(120)') { console.log('! a script line after an address offers ' + onAddr.join(', ')); blocksBad++; }
var onClient = completerItems('client:aa:bb:cc:dd:ee:ff.', true).map(function (i) { return i.text; });
if (onClient.join(',') !== 'give_to(Jan)') { console.log('! a script line after a client offers ' + onClient.join(', ')); blocksBad++; }
if (blocksBad) bad += blocksBad;
console.log('%d ready-made block(s) for a message, %d for a script, each one whole and each with its '
  + 'part to change picked out',
  FACT_BLOCKS.length, SCRIPT_BLOCKS.length);
// A word matches a template by its own words, not by any run of letters:
// "un" is the start of "unless", not of "counting", and a list where every
// other row matches is no list at all.
['un', 'time', 'loop'].forEach(function (word) {
  completerItems(word, false, 'blocks').forEach(function (it) {
    var words = (it.label + ' ' + it.desc + ' ' + (it.group || '')).toLowerCase().split(/[^a-z0-9_]+/);
    if (!words.some(function (w) { return w.indexOf(word) === 0; })) {
      console.log('! "' + word + '" brought up "' + it.label + '", which has no such word in it'); bad++;
    }
  });
});
// On a script's line Ctrl+Space is the verbs and the names, never a block.
scope.setLocals([{name: 'unban', why: 'let an address back in', verb: true},
                 {name: 'on', why: 'switch something on', verb: true}]);
var lineStart = completerItems('un', true);
if (!lineStart.length || lineStart.some(function (i) { return i.block; })) {
  console.log('! a script line mixes ready-made blocks into the list of verbs'); bad++;
}
// Two lists on two keys: the facts (Ctrl+Space) hold no ready-made blocks at
// all, and the blocks (Ctrl+Alt+Space) hold every one of them - a list that
// mixed them showed neither whole.
var firstOff = completerItems('', false);
if (firstOff.filter(function (i) { return i.block; }).length) {
  console.log('! a ready-made block turned up in the list of facts'); bad++;
}
if (completerItems('if', false).filter(function (i) { return i.block; }).length) {
  console.log('! a ready-made block turned up in the list of facts while typing'); bad++;
}
var everyBlock = completerItems('', false, 'blocks');
if (everyBlock.length !== FACT_BLOCKS.length) {
  console.log('! the blocks list shows ' + everyBlock.length + ' of ' + FACT_BLOCKS.length); bad++;
}
if (everyBlock.some(function (i) { return !i.block; })) {
  console.log('! the blocks list holds something that is not a block'); bad++;
}
var scriptBlocks = completerItems('', true, 'blocks');
if (scriptBlocks.length !== SCRIPT_BLOCKS.length) {
  console.log('! a script is offered ' + scriptBlocks.length + ' of ' + SCRIPT_BLOCKS.length + ' blocks'); bad++;
}
// and typing narrows that list rather than emptying it
if (!completerItems('for', false, 'blocks').length) {
  console.log('! typing a word in the blocks list finds nothing'); bad++;
}
// and every heading is reachable by typing its own word
['if', 'unless', 'for', 'repeat', 'while', 'time', 'list', 'message'].forEach(function (word) {
  if (!completerItems(word, false, 'blocks').length && !completerItems(word, true, 'blocks').length) {
    console.log('! nothing ready-made comes up for "' + word + '"'); bad++;
  }
});

// a key that is not there is not a fact either: offering turns for it would
// promise something the daemon will fill with nothing
if (completerItems('PIR-Chodba.nosuchkey.').length) {
  console.log('! a key the device does not have is still offered turns');
  bad++;
}
if (bad) {
  console.log('\n' + bad + ' case(s) wrong');
  process.exit(1);
}
console.log('\n' + cases.length + ' completions, each offered and each put where it belongs');

// ---------------------------------------------------------------------------
// The two ways of taking a ready-made block - the "{ } Facts" sheet and the
// Ctrl+Alt+Space list - must write the same thing. They did not: the sheet
// wrapped every block in a pair of braces, including the whole messages that
// are the message rather than a fact in one, and it left the line breaks as
// the two characters they are kept as in the table, so a phone was sent a
// backslash and an n.
// lifted from openFactPicker itself, so that the two really are compared
// rather than the test agreeing with itself
const sheetSource = (function () {
  const all = script.join('\n');
  const at = all.indexOf("groups.unshift(['Ready-made");
  if (at < 0) throw new Error('index.php no longer builds the ready-made groups in the sheet');
  const end = all.indexOf('return [b[0],', at);
  if (end < 0) throw new Error('the sheet no longer returns its entries where it did');
  const body = all.slice(all.indexOf('\n', at), end);
  if (!/whole/.test(body)) throw new Error('the sheet no longer works out a "whole" to insert');
  return body + '\nreturn whole;';
})();
const fromSheet = new Function('b', sheetSource);
const offered = blockItems('', false);
let disagree = [];
FACT_BLOCKS.forEach(function (b) {
  const hit = offered.filter(i => i.label === b[0])[0];
  if (!hit) throw new Error('the list no longer offers "' + b[0] + '"');
  if (hit.text !== fromSheet(b)) disagree.push(b[0]);
});
if (disagree.length) {
  throw new Error(disagree.length + ' block(s) are written differently by the sheet and the list, e.g. '
    + disagree.slice(0, 3).join(', '));
}
// and what the sheet itself writes must be usable: braces balanced, no
// literal backslash-n left in it
FACT_BLOCKS.forEach(function (b) {
  const text = fromSheet(b);
  if (/\\n/.test(text)) throw new Error('"' + b[0] + '" carries a literal backslash-n');
  let depth = 0;
  for (const ch of text) { if (ch === '{') depth++; else if (ch === '}') depth--; if (depth < 0) break; }
  if (depth !== 0) throw new Error('"' + b[0] + '" has ' + depth + ' brace(s) too many');
});
console.log(FACT_BLOCKS.length + ' ready-made blocks, written the same way by the sheet and by the list');

// Nothing carries a character that cannot be seen. A zero-width space in a
// ready-made block goes out in the message, is invisible in the box, and
// cannot be found or deleted by looking at it.
const INVISIBLE = new RegExp('[' + [0x200b, 0x200c, 0x200d, 0x200e, 0x200f, 0x2028, 0x2029, 0xfeff, 0x00ad].map(function (c) { return String.fromCharCode(c); }).join('') + ']');
[['FACT_BLOCKS', FACT_BLOCKS], ['SCRIPT_BLOCKS', SCRIPT_BLOCKS]].forEach(function (pair) {
  pair[1].forEach(function (b) {
    b.forEach(function (part, i) {
      if (typeof part === 'string' && INVISIBLE.test(part)) {
        throw new Error(pair[0] + ' "' + b[0] + '" part ' + i + ' carries an invisible character');
      }
    });
  });
});
console.log('no ready-made block carries a character that cannot be seen');
