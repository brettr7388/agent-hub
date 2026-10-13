/* Message reactions require one eligible decision; card buttons remain explicit. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const fixtureSource = fs.readFileSync(path.join(__dirname, 'ui_smoke.js'), 'utf8').split('const { data, chatTime, quotedText,')[0];
const fixture = { require, __dirname, console, Event, URL, Headers };
vm.runInNewContext(fixtureSource + '\nglobalThis.fixture = { context, elements, Node };', fixture);
const { context, elements, Node } = fixture.fixture;
const app = context.__test;
app.data.agents = [{ id: 'guide', guide: true }, { id: 'writer' }];
app.data.chatId = null;
const approval = { kind: 'approval_request', title: 'Send draft', actions: ['Approve', "Don't"] };
const proposal = { kind: 'proposal', status: 'pending', proposal: { name: 'New Pip' } };
const calls = [];
context.fetch = async (_url, options = {}) => {
  calls.push(JSON.parse(options.body));
  return { ok: true, status: 200, json: async () => options.body.includes('"confirm":true') ? { reactions: ['👍'] } : { confirmation_required: true, card_action: 'Approve' } };
};
(async () => {
  for (const cards of [[approval, approval], [proposal, proposal], [approval, proposal], [{ kind: 'note' }, approval, approval]]) {
    for (const emoji of ['👍', '✅', '👎']) {
      await app.react({ id: 12, agent_id: 'guide', role: 'assistant', reactions: [], cards }, emoji, new Node('button'));
      assert.equal(calls.length, 0, 'ambiguous reaction must not request an approval or a turn');
      assert.match(elements.get('toast').textContent, /Use the card’s buttons/);
    }
  }
  for (const cards of [[approval], [{ kind: 'note' }, approval], [{ ...approval, decision: 'Approve' }, approval], [{ ...proposal, status: 'created' }, proposal]]) {
    const before = calls.length;
    await app.react({ id: 13, agent_id: 'guide', role: 'assistant', reactions: [], cards }, '👍', new Node('button'));
    assert.equal(calls.length - before, 2, 'single eligible decision retains confirmation');
  }
  context.fetch = async (_url, options = {}) => { calls.push(JSON.parse(options.body)); return { ok: true, status: 200, json: async () => ({ reactions: [] }) }; };
  await app.react({ id: 14, agent_id: 'guide', role: 'assistant', reactions: ['👍'], cards: [approval, proposal] }, '👍', new Node('button'));
  assert.equal(calls.at(-1).active, false, 'ambiguous message reactions can still be removed');
  console.log('Approval reaction ambiguity checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
