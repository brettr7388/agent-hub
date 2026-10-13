/* Real click handlers with fake APIs, no browser/CLI/network. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const fixtureSource = fs.readFileSync(path.join(__dirname, 'ui_smoke.js'), 'utf8').split('const { data, chatTime, quotedText,')[0];
const fixture = { require, __dirname, console, Event, URL, Headers };
vm.runInNewContext(fixtureSource + '\nglobalThis.fixture = { context, elements, timers };', fixture);
const { context, elements, timers } = fixture.fixture;
const app = context.__test, data = app.data, get = id => elements.get(id);
const response = value => ({ ok: true, status: 200, json: async () => value });
const calls = [];
context.fetch = async (url, options = {}) => { calls.push({ url, body: options.body && JSON.parse(options.body) }); return response(url.startsWith('/api/chat?') ? { messages: data.messages } : {}); };
data.authenticated = true; data.chatId = 'agent:writer';
data.agents = [{ id: 'writer', name: 'Writer' }];
data.chats = [{ id: data.chatId, type: 'direct', agents: ['writer'] }, { id: 'group:crew', type: 'group', name: 'Crew', agents: ['writer'] }];
const row = id => get('sidebar').querySelectorAll('.nav-wrap').find(node => node.dataset.chatId === id);
const star = id => row(id).querySelector('.pin-button');

(async () => {
  for (const id of ['agent:writer', 'group:crew']) {
    data.pinned = []; app.renderNav();
    assert.equal(star(id)['aria-pressed'], 'false');
    assert.equal(star(id).classList.contains('pinned'), false);
    star(id).click();
    assert.ok(data.pinned.includes(id));
    assert.equal(star(id)['aria-pressed'], 'true');
    assert.ok(star(id).classList.contains('pinned'));
    assert.ok(star(id).classList.contains('star-pop'), 'starring pops the replacement icon');
    assert.equal(star(id).focused, undefined, 'mouse click does not force focus on a replacement button');
    assert.equal(row(id).querySelector('.nav-pin').children[0].href, '#i-star');
    timers.filter(timer => timer.ms === 220 && !timer.cancelled).forEach(timer => { timer.callback(); timer.cancelled = true; });
    assert.equal(star(id).classList.contains('star-pop'), false, 'feedback class clears');
    const keyStar = star(id); keyStar.matches = selector => selector === ':focus-visible';
    keyStar.click();
    assert.equal(star(id)['aria-pressed'], 'false');
    assert.equal(star(id).classList.contains('star-pop'), false, 'unstarring does not pop');
    assert.equal(star(id).focused, true, 'keyboard focus survives sidebar replacement');
    assert.equal(row(id).querySelector('.nav-pin'), null);
  }
  assert.deepEqual(calls.filter(call => call.url === '/api/product').map(call => call.body.action), ['pin', 'unpin', 'pin', 'unpin']);

  data.messages = [{ id: 1, role: 'assistant', agent_id: 'writer', text: 'Ready', reactions: ['👍'] }];
  app.reconcileMessages();
  const message = get('messageList').children[0];
  const firstChip = message.querySelector('.reaction-chip');
  assert.ok(firstChip.classList.contains('reaction-pop'));
  app.reconcileMessages();
  assert.equal(message.querySelector('.reaction-chip'), firstChip, 'unchanged polling does not replay chip motion');
  data.messages[0].reactions.push('❤️'); app.reconcileMessages();
  const chips = message.querySelectorAll('.reaction-chip');
  assert.equal(chips[0].classList.contains('reaction-pop'), false, 'existing reaction does not pop again');
  assert.ok(chips[1].classList.contains('reaction-pop'), 'only newly added reaction pops');
  data.messages[0].reactions = ['❤️']; app.reconcileMessages();
  assert.equal(message.querySelector('.reaction-chip').classList.contains('reaction-pop'), false, 'removing a reaction does not repop survivors');

  const submit = { preventDefault() {} }, send = get('sendButton');
  get('messageInput').value = ''; await app.sendMessage(submit);
  assert.equal(send.classList.contains('send-lift'), false, 'empty submission has no send motion');
  get('messageInput').value = 'Hello'; context.navigator.onLine = false; await app.sendMessage(submit);
  assert.equal(send.classList.contains('send-lift'), false, 'offline submission has no send motion');
  context.navigator.onLine = true;
  await app.sendMessage(submit);
  assert.ok(send.classList.contains('send-lift'), 'accepted send lifts arrow');
  assert.equal(calls.filter(call => call.url === '/api/message').length, 1);
  timers.filter(timer => timer.ms === 220 && !timer.cancelled).forEach(timer => timer.callback());
  assert.equal(send.classList.contains('send-lift'), false);
  console.log('Polish smoke checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
