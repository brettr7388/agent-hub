'use strict';
const assert = require('node:assert/strict');
const Pips = require('../static/pips.js');

assert.equal(Object.keys(Pips.palettes).length, 14);
assert.equal(Pips.eyes.length, 5);
assert.equal(Pips.antennaTips.length, 4);
assert.equal(Pips.visors.length, 2);
assert.ok(Pips.accessories.length >= 30);

const guide = Pips.pipFor({ id: 'guide', name: 'Guide' });
assert.deepEqual(guide, { palette: 'blue', accessory: 'compass', eyes: 'dots', antenna: 'dot', visor: 'round' });
assert.deepEqual(Pips.pipFor({ id: 'guide', name: 'Renamed', guide: true }), guide);
const guideSVG = Pips.pipSVG(guide);
assert.match(guideSVG, /rect x="9" y="15" width="46" height="40" rx="17"/);
assert.match(guideSVG, /rect x="15" y="23" width="34" height="22" rx="11"/);
assert.match(guideSVG, /#5BB0FF/);
assert.equal(guideSVG, Pips.pipSVG(guide));

const roles = {
  pencil: 'Writer', magnifier: 'Researcher', code: 'Coder', hard_hat: 'Operations', envelope: 'Inbox',
  calendar: 'Scheduler', chart: 'Analytics', paintbrush: 'Designer', headphones: 'Podcast editor',
  chef_hat: 'Chef', graduation_cap: 'Tutor', wrench: 'Mechanic', shield: 'Security', globe: 'Translator',
  camera: 'Photographer', music_note: 'Musician', dollar_coin: 'Finance', heart: 'Wellness',
  book: 'Book reader', lightbulb: 'Brainstormer', rocket: 'Startup growth', leaf: 'Gardener',
  gamepad: 'Game player', megaphone: 'Marketing'
};
for (const [accessory, name] of Object.entries(roles)) {
  assert.equal(Pips.pipFor({ id: accessory, name }).accessory, accessory, name);
  assert.match(Pips.pipSVG({ accessory }), /<svg /);
}

const malicious = '"/><script>alert(1)</script>';
const svg = Pips.pipSVG({ palette: malicious, accessory: malicious, eyes: malicious, antenna: malicious, visor: malicious });
assert.doesNotMatch(svg, /script|alert/);
assert.match(svg, /#5BB0FF/);
assert.doesNotMatch(Pips.avatarHTML({ avatar_style: 'emoji', emoji: malicious }), /<script>/);
assert.match(Pips.avatarHTML({ avatar_style: 'emoji', emoji: malicious }), /&lt;script&gt;/);
assert.match(Pips.avatarHTML({ id: 'x' }), /^<svg class="pip-avatar" /);
assert.doesNotMatch(Pips.avatarHTML({ id: 'x' }), /data:image|<img/);

const agents = Array.from({ length: 200 }, (_, n) => ({ id: `a${n}`, name: 'Unknown' }));
const assignments = Pips.assignPips(agents);
assert.equal(assignments.length, 200);
assert.equal(new Set(assignments.map(x => JSON.stringify(x.pip_style))).size, 200);
assert.deepEqual(Pips.assignPips(agents.slice().reverse()), assignments);
assert.deepEqual(Pips.assignPips(agents.map((a, n) => ({ ...a, pip_style: assignments[n].pip_style }))), []);
const existing = [{ id: 'a', name: 'Writer', pip_style: { palette: 'coral', accessory: 'pencil', eyes: 'happy', antenna: 'star', visor: 'round' } }];
assert.deepEqual(Pips.pipFor(existing[0]), existing[0].pip_style);
assert.equal(Pips.assignPips(existing).length, 0);
console.log('pips smoke passed');
