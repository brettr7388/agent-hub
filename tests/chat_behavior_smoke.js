/* Run with: node tests/chat_behavior_smoke.js. Exercise the real UI functions in the shared HTML fixture. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

let fixtureSource = fs.readFileSync(path.join(__dirname, 'ui_smoke.js'), 'utf8').split('const { data, chatTime, quotedText,')[0];
fixtureSource = fixtureSource.replace('vm.runInNewContext(source, context);', "vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'chat-parity.js'), 'utf8'), context); vm.runInNewContext(source, context);");
fixtureSource = fixtureSource.replace('globalThis.__test = { setupComposerInteractions,', 'globalThis.__test = { parity, renderPalette, refreshChat, ');
const fixture = { require, __dirname, console, Event, URL, Headers };
vm.runInNewContext(fixtureSource + '\nglobalThis.fixture = { context, document, elements, timers, Node };', fixture);
const { context, document, elements, timers, Node } = fixture.fixture;
Node.prototype.requestSubmit = function () { this.dispatchEvent({ type: 'submit', preventDefault() {} }); };
Node.prototype.after = function (other) { if (other.parent) other.parent.children = other.parent.children.filter(child => child !== other); const index = this.parent.children.indexOf(this); this.parent.children.splice(index + 1, 0, other); other.parent = this.parent; };
const app = context.__test, { data, parity } = app;
const get = id => elements.get(id);
const response = value => ({ ok: true, status: 200, json: async () => value });
const keyEvent = key => ({ type: 'keydown', key, preventDefault() { this.prevented = true; } });
const flush = () => new Promise(setImmediate);

async function main() {
  data.authenticated = true;
  data.agents = [{ id: 'ben', name: 'Ben', engine: 'claude', private_pip: true }, { id: 'dee', name: 'Dee', engine: 'claude', draft_only: true }, { id: 'flo', name: 'Flo', engine: 'claude' }];
  data.chats = [
    { id: 'agent:ben', name: 'Ben', type: 'direct', agents: ['ben'] },
    { id: 'chat:two', name: 'Project Notes', type: 'direct', agents: ['ben'] },
    { id: 'agent:dee', name: 'Dee', type: 'direct', agents: ['dee'] },
    { id: 'agent:flo', name: 'Flo', type: 'direct', agents: ['flo'] },
    { id: 'group:crew', name: 'Crew', type: 'group', agents: ['ben', 'dee'] },
  ];
  data.statuses = []; data.messages = []; data.chatId = 'agent:ben';
  get('app').hidden = false; get('composer').hidden = false;
  for (const [id, expected] of [['agent:ben', 'Private'], ['chat:two', 'Private'], ['agent:dee', 'Draft only'], ['agent:flo', 'Full access']]) {
    data.chatId = id; app.renderHeader();
    assert.equal(get('pipAccessChips').hidden, false, `${id} exposes access status`);
    assert.ok(get('pipAccessChips').textContent.includes(expected), `${id}: ${expected}`);
  }
  data.chatId = 'group:crew'; app.renderHeader();
  assert.equal(get('pipAccessChips').hidden, true, 'group does not borrow one member’s access status');

  const calls = [];
  context.fetch = async (url, options = {}) => { calls.push({ url, body: options.body && JSON.parse(options.body) }); if (url === '/api/state') return response({ agents: data.agents, chats: data.chats, statuses: [] }); if (url.startsWith('/api/chat?')) return response({ messages: [] }); return response({}); };
  const base = new Node(); base.append(app.navButton(data.chats[0], data.agents[0]));
  parity.pipRow(data.chats[0], base); base.querySelector('.conversation-toggle').click();
  const expanded = new Node(); expanded.append(app.navButton(data.chats[0], data.agents[0])); parity.pipRow(data.chats[0], expanded);
  const row = expanded.querySelectorAll('.pip-conversation-row').find(item => item.dataset.chatId === 'chat:two');
  row.querySelector('.conversation-more').click();
  const rename = get('conversationActionsBody').children[0].click();
  const renameDialog = app.sendFeel.dialog, nameInput = renameDialog.querySelector('input');
  assert.ok(nameInput && !renameDialog.querySelector('textarea'), 'Rename chat uses one line');
  nameInput.value = 'Renamed chat'; nameInput.dispatchEvent(keyEvent('Enter'));
  await rename;
  assert.equal(calls.find(call => call.url === '/api/chats/rename')?.body.name, 'Renamed chat', 'Enter saves the name');
  row.querySelector('.conversation-more').click();
  const cancelled = get('conversationActionsBody').children[0].click();
  const escapeInput = app.sendFeel.dialog.querySelector('input'); escapeInput.value = 'Must not save'; escapeInput.dispatchEvent(keyEvent('Escape'));
  await cancelled;
  assert.equal(calls.filter(call => call.url === '/api/chats/rename').length, 1, 'Escape cancels rename');
  const draftDialog = app.appActionDialog({ title: 'Edit draft', value: 'First line\nSecond line' });
  assert.ok(app.sendFeel.dialog.querySelector('textarea'), 'generic draft edit stays multiline');
  app.sendFeel.dialog.querySelector('button').click(); await draftDialog;

  data.navFilter = '  PROJECT   notes  '; app.renderNav();
  assert.ok(get('agentList').findText('Project Notes'), 'sidebar matches whole title after case and whitespace normalization');
  data.navFilter = '  PROJECT   absent  '; app.renderNav();
  assert.equal(get('agentList').findText('Project Notes'), false, 'sidebar excludes an unmatched multiword title');
  data.navFilter = '';
  data.chats.push({ id: 'group:project', name: 'Project Notes', type: 'group', agents: ['ben'] });
  get('paletteInput').value = '  PROJECT   NOTES  ';
  get('paletteDialog').open = true;
  context.fetch = async url => response(url.startsWith('/api/search?') ? { results: [] } : {});
  await app.renderPalette();
  assert.ok(get('paletteResults').findText('Project Notes'), 'palette matches normalized multiword title');

  data.chatId = 'group:crew'; data.messages = [{ id: 10, role: 'user', text: '@ben Explain this' }];
  const directed = app.messageNode({ id: 11, role: 'assistant', agent_id: 'ben', text: 'Here', reply_to: 10, routing_kind: 'directed' });
  assert.ok(directed.querySelector('.best-fit-note').findText('Ben answered, you asked for Ben'), 'directed note explains the requested Pip');
  const bestFit = app.messageNode({ id: 12, role: 'assistant', agent_id: 'ben', text: 'Here', reply_to: 10, best_fit: true, routing_kind: 'best_fit' });
  assert.ok(bestFit.querySelector('.best-fit-note').findText('best fit'), 'best-fit wording remains');

  // A queued Ask everyone status is inserted with later messages in order; scrolling up remains anchored.
  const viewport = get('messageViewport'), list = get('messageList');
  data.messages = [{ id: 20, role: 'user', text: '@all Compare' }, { id: 21, role: 'assistant', agent_id: 'ben', text: 'First' }];
  app.reconcileMessages();
  viewport.scrollHeight = 1500; viewport.clientHeight = 600; viewport.scrollTop = 100;
  let scrolls = 0; viewport.scrollTo = () => { scrolls++; };
  app.connectEvents();
  data.eventSource.listeners.change({ data: JSON.stringify({ kind: 'delta', chat_id: data.chatId, job_id: 71, agent_id: 'dee', status: 'queued', text: '', after_message_id: 20, independent: true }) });
  assert.equal(viewport.scrollTop, 100, 'queued status respects the reader’s scroll position');
  assert.equal(scrolls, 0, 'queued status does not force a jump');
  assert.ok(list.children.findIndex(node => node.dataset.messageId === '21') > list.children.findIndex(node => node.dataset.messageId === '20'), 'following reply stays after the Ask everyone question');
  data.deltas.clear(); viewport.scrollHeight = 1200; viewport.scrollTop = 600;
  const frames = []; context.requestAnimationFrame = callback => { frames.push(callback); };
  const scrollTargets = []; viewport.scrollTo = options => { scrollTargets.push(options.top); viewport.scrollTop = options.top - viewport.clientHeight; };
  data.deltas.set('72', { chat_id: data.chatId, agent_id: 'ben', text: '', independent: true }); app.renderDeltas();
  viewport.scrollHeight = 1450;
  data.deltas.set('73', { chat_id: data.chatId, agent_id: 'dee', text: '', independent: true }); app.renderDeltas();
  assert.equal(scrollTargets.length, 0, 'queued replies wait for layout before following');
  for (const frame of frames.splice(0)) frame();
  assert.equal(scrollTargets.at(-1), 1450, 'burst of queued replies follows the final bottom after layout');
  data.deltas.clear(); app.renderDeltas(); for (const frame of frames.splice(0)) frame();
  viewport.scrollTop = 100; viewport.scrollHeight = 1700; scrollTargets.length = 0;
  data.deltas.set('74', { chat_id: data.chatId, agent_id: 'dee', text: '', independent: true }); app.renderDeltas();
  for (const frame of frames.splice(0)) frame();
  assert.equal(viewport.scrollTop, 100, 'later queued reply leaves an up-scrolled reader in place');
  assert.equal(scrollTargets.length, 0);
  context.requestAnimationFrame = callback => callback();

  // Native FLIP starts at the previous top and returns to the new position.
  const container = new Node(), moved = new Node(); moved.className = 'nav-wrap'; moved.dataset.chatId = 'agent:ben'; moved.rect.top = 90;
  const unchanged = new Node(); unchanged.className = 'nav-wrap'; unchanged.dataset.chatId = 'agent:dee'; unchanged.rect.top = 140;
  container.append(moved, unchanged);
  const animations = [];
  moved.animate = (frames, options) => { animations.push({ frames, options }); };
  unchanged.animate = () => { throw new Error('stationary row animated'); };
  const before = parity.measureRows(container);
  moved.rect.top = 42;
  parity.animateReorder(container, before);
  assert.equal(animations.length, 1);
  assert.equal(animations[0].frames[0].transform, 'translateY(48px)');
  assert.equal(animations[0].frames[1].transform, 'translateY(0)');
  assert.ok(animations[0].options.duration >= 160 && animations[0].options.duration <= 220, 'motion is around 180ms');
  context.matchMedia = () => ({ matches: true });
  moved.rect.top = 0; parity.animateReorder(container, before);
  assert.equal(animations.length, 1, 'reduced motion suppresses reordering animation');
  context.matchMedia = () => ({ matches: false });

  // Version controls follow the selected user message and switch both ways.
  data.chatId = 'agent:ben'; data.messages = [{ id: 30, role: 'user', text: 'Earlier question' }, { id: 31, role: 'assistant', agent_id: 'ben', text: 'Earlier reply' }, { id: 32, role: 'user', text: 'Latest question' }];
  const versionHistory = data.messages.slice();
  list.replaceChildren(); app.reconcileMessages();
  let activeVersion = 'v2'; const versionCalls = [];
  context.fetch = async (url, options = {}) => {
    if (url === '/api/chats/version') { const body = JSON.parse(options.body); versionCalls.push(body); activeVersion = body.version_id; return response({}); }
    if (url === '/api/state') return response({ agents: data.agents, chats: data.chats, statuses: [] });
    if (url.startsWith('/api/chat?')) return data.chatId === 'agent:dee' ? response({ messages: [] }) : response({ messages: activeVersion === 'v1' ? versionHistory.slice(0, 2) : versionHistory, versions: [{ id: 'v1', message_id: 30, label: 'Original', active: activeVersion === 'v1' }, { id: 'v2', message_id: 32, label: 'Edit', active: activeVersion === 'v2' }], active_version: activeVersion });
    return response({});
  };
  parity.renderVersions({ versions: [{ id: 'v1', message_id: 30, label: 'Original' }, { id: 'v2', message_id: 32, label: 'Edit', active: true }], active_version: 'v2' });
  const bar = get('chatVersionBar');
  assert.equal(bar.parent?.parent?.dataset.messageId, '32', 'version bar sits under edited user message');
  assert.equal(get('chatVersionSummary').textContent, '2/2', 'summary is compact');
  assert.ok(!get('previousChatVersion').disabled && get('nextChatVersion').disabled);
  await get('previousChatVersion').onclick();
  assert.equal(versionCalls[0].version_id, 'v1');
  assert.equal(get('chatVersionSummary').textContent, '1/2');
  assert.equal(bar.parent?.parent?.dataset.messageId, '30', 'older version moves controls under its user message');
  await get('nextChatVersion').onclick();
  assert.equal(versionCalls[1].version_id, 'v2');
  assert.equal(get('chatVersionSummary').textContent, '2/2');
  assert.equal(bar.parent?.parent?.dataset.messageId, '32', 'latest version restores the edited message anchor');

  // getElementById must lose nodes removed with a message; the fixture's Map normally hides this.
  const originalGetElementById = document.getElementById.bind(document);
  const versionIds = new Set(['chatVersionBar', 'chatVersions', 'chatVersionSummary', 'chatVersionOptions', 'previousChatVersion', 'nextChatVersion']);
  const attached = node => {
    for (let item = node; item && item !== document.body; item = item.parent) {
      if (!item.parent?.children.includes(item)) return false;
    }
    for (let item = node; item; item = item.parent) if (item === document.body) return true;
    return false;
  };
  document.getElementById = id => { const node = originalGetElementById(id); return versionIds.has(id) && !attached(node) ? null : node; };
  try {
    await get('previousChatVersion').onclick();
    assert.equal(get('chatVersionSummary').textContent, '1/2', 'controls survive removal of their former message subtree');
    assert.ok(attached(bar), 'version bar remains in the live document after switching');
    await app.openChat('agent:dee');
    assert.equal(data.chatId, 'agent:dee');
    assert.ok(attached(bar), 'openChat parks controls before clearing old messages');
    assert.equal(bar.hidden, true, 'new chat without versions hides parked controls');
  } finally { document.getElementById = originalGetElementById; }

  console.log('Chat behavior smoke checks passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
