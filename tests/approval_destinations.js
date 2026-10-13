/* Only explicit Pip metadata produces a destination label. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const fixtureSource = fs.readFileSync(path.join(__dirname, 'ui_smoke.js'), 'utf8').split('const { data, chatTime, quotedText,')[0];
const fixture = { require, __dirname, console, Event, URL, Headers };
vm.runInNewContext(fixtureSource + '\nglobalThis.fixture = { context };', fixture);
const access = fixture.fixture.context.window.HubAccess;
const request = { summary: 'Send draft', details: 'Exact text' };
const destination = '  127.0.0.1:4841/inbox / @testuser <b>local</b>  ';
const card = access.card({ ...request, destination }, null, async () => {});
assert.equal(card.querySelector('.approval-request-destination').textContent, `Destination: ${destination}`);
assert.equal(card.querySelector('b'), null, 'destination markup remains literal text');
for (const input of [request, { ...request, summary: 'Send on Instagram' }, { ...request, destination: '' }]) {
  const missing = access.card(input, null, async () => {});
  assert.equal(missing.querySelector('.approval-request-destination'), null, 'absent destination creates no label');
  assert.equal(missing.querySelector('.approval-request-source'), null);
}
console.log('Approval destination checks passed');
