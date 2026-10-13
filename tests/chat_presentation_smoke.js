/* Offline regressions for empty chats and sidebar identity. No browser or CLI. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');

class Node {
  constructor(tag = 'div') {
    this.tagName = tag; this.className = ''; this.children = []; this.dataset = {}; this.events = {};
    this.hidden = false; this._text = ''; this.value = ''; this.style = { setProperty() {}, removeProperty() {} };
    this.classList = {
      contains: (name) => this.className.split(' ').includes(name),
      add: (name) => { this.className = [...new Set([...this.className.split(' ').filter(Boolean), name])].join(' '); },
      remove: (name) => { this.className = this.className.split(' ').filter((part) => part !== name).join(' '); },
      toggle: (name, on) => { this.classList[on ? 'add' : 'remove'](name); return on; }
    };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(''); }
  set innerHTML(value) {
    assert.equal(this.tagName, 'template'); assert.match(value, /^<svg class="pip-avatar" /);
    const svg = new Node('svg'); svg.className = 'pip-avatar'; svg.source = value;
    this.content = { firstElementChild: svg };
  }
  get childNodes() { return this.children; }
  append(...children) { children.forEach((child) => { child.parent = this; this.children.push(child); }); }
  insertBefore(child, anchor) { if (child.parent) child.parent.children = child.parent.children.filter((item) => item !== child); const index = anchor ? this.children.indexOf(anchor) : this.children.length; assert.ok(index >= 0); child.parent = this; this.children.splice(index, 0, child); }
  prepend(child) { child.parent = this; this.children.unshift(child); }
  replaceChildren(...children) { this._text = ''; this.children = []; this.append(...children); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((child) => child !== this); }
  replaceWith(other) { if (this.parent) { const index = this.parent.children.indexOf(this); if (index >= 0) { this.parent.children[index] = other; other.parent = this.parent; } } }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, callback) { this.events[name] = callback; }
  focus() { this.focused = true; }
  querySelectorAll(selector) {
    return this.children.flatMap((child) => [child, ...child.querySelectorAll(selector)])
      .filter((child) => selector.split(',').some((part) => part.startsWith('.') ? child.classList.contains(part.slice(1)) : child.tagName === part));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

const elements = new Map();
const html = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');
for (const [, id] of html.matchAll(/\bid="([^"]+)"/g)) elements.set(id, new Node());
const get = (id) => { assert.ok(elements.has(id), `Real index.html contains ${id}`); return elements.get(id); };
const emptyMark = new Node(); emptyMark.className = 'empty-mark'; get('emptyChat').append(emptyMark);
get('conversation').className = 'conversation'; get('composer').hidden = true;
let hour = 20, reduceMotion = false;
class LocalDate extends Date { getHours() { return hour; } }
const animations = [];
get('composer').getBoundingClientRect = () => ({ top: get('conversation').classList.contains('is-empty') ? 400 : 750 });
get('composer').animate = (frames, options) => {
  const animation = { frames, options, cancelled: false, cancel() { this.cancelled = true; } };
  animations.push(animation); return animation;
};
const context = {
  document: { getElementById: get, createElement: (tag) => new Node(tag), body: new Node(), visibilityState: 'hidden', querySelectorAll: () => [] },
  window: { innerHeight: 900 }, location: { origin: 'http://localhost' }, localStorage: {}, navigator: { onLine: true },
  Date: LocalDate, URL, Headers, crypto: { randomUUID: () => 'fake-request-id' },
  matchMedia: (query) => ({ matches: query.includes('prefers-reduced-motion') && reduceMotion }),
  requestAnimationFrame: (callback) => callback(), setTimeout: () => 1, clearTimeout() {}, console
};
vm.runInNewContext(fs.readFileSync(path.join(root, 'static/pips.js'), 'utf8'), context);
let source = fs.readFileSync(path.join(root, 'static/app.js'), 'utf8');
source = source.replace(/  setup\(\);[\s\S]*\}\)\(\);\s*$/, '  globalThis.testApp = { data, renderEmpty, navButton, queueComposerDock, sendMessage };\n})();');
vm.runInNewContext(source, context);
const { data, renderEmpty, navButton, queueComposerDock, sendMessage } = context.testApp;
data.authenticated = true;
const clients = { id: 'clients', name: 'Clients', linked: true, emoji: '📋', avatar_style: 'pip', pip_style: { palette: 'blue', accessory: 'envelope' } };
const writer = { id: 'writer', name: 'Writer', emoji: '✍️', avatar_style: 'pip', pip_style: { palette: 'purple', accessory: 'pencil' } };
const emoji = { id: 'emoji', name: 'Chef', emoji: '👩‍🍳', avatar_style: 'emoji', avatar: '/static/old-image.svg' };
data.agents = [clients, writer, emoji];
data.chats = data.agents.map((a) => ({ id: `agent:${a.id}`, name: a.name, type: 'direct', agents: [a.id] }));
data.chats.push({ id: 'group:crew', type: 'group', name: 'Crew', emoji: '🚀', agents: ['clients', 'writer'] });
const select = (id) => { data.chatId = id; data.messages = []; data.deltas.clear(); renderEmpty(); };

select('agent:clients');
assert.equal(get('greeting').textContent, 'Good evening · Ask Clients anything');
const clientsSVG = emptyMark.querySelector('svg').source;
assert.equal(clientsSVG, context.window.Pips.avatarHTML(clients), 'welcome uses the actual Pip style');
assert.equal(emptyMark.querySelector('img'), null, 'an agent chat never uses the global logo');
assert.ok(get('suggestionChips').hidden, 'non-Guide chats center without suggestion chips');
select('agent:writer');
assert.equal(get('greeting').textContent, 'Good evening · Ask Writer anything');
assert.equal(emptyMark.querySelector('svg').source, context.window.Pips.avatarHTML(writer));
assert.notEqual(emptyMark.querySelector('svg').source, clientsSVG, 'switching Pips changes the welcome avatar');
select('agent:emoji');
assert.equal(emptyMark.textContent, '👩‍🍳', 'an emoji override wins over a stale image');
assert.equal(emptyMark.querySelector('svg'), null);
assert.equal(emptyMark.querySelector('img'), null);
select('group:crew');
assert.equal(get('greeting').textContent, 'Good evening · Ask the group');
assert.equal(emptyMark.textContent, '🚀', 'a group uses its own avatar, never its first member');
data.chats.at(-1).avatar = '/static/group-avatar.svg'; renderEmpty();
assert.equal(emptyMark.querySelector('img').src, 'http://localhost/static/group-avatar.svg');
select(null);
assert.equal(emptyMark.querySelector('img').src, '/static/logo.svg', 'only global home uses the app Pip');
assert.equal(get('greeting').textContent, 'Good evening · Ask anything');
hour = 8; renderEmpty(); assert.match(get('greeting').textContent, /^Good morning ·/);
hour = 14; renderEmpty(); assert.match(get('greeting').textContent, /^Good afternoon ·/);
hour = 20;
select('agent:unloaded');
assert.match(get('greeting').textContent, /Ask this Pip anything$/, 'missing chat data has a neutral fallback');
assert.equal(emptyMark.querySelector('img'), null);
select('group:unloaded');
assert.equal(emptyMark.textContent, '👥', 'loading a group cannot borrow a direct Pip avatar');

const row = navButton(data.chats[0], clients);
assert.equal(row.querySelector('svg').source, clientsSVG, 'sidebar and welcome use the same crisp SVG');
const copy = row.querySelector('.nav-copy'), link = row.querySelector('.nav-linked');
assert.equal(copy.children[0].textContent, 'Clients');
assert.equal(copy.children[1], link, 'link icon sits immediately after the name');
assert.equal(link.title, 'Linked to an existing agent folder, read-only');
assert.equal(link['aria-label'], link.title);
assert.match(row['aria-label'], /read-only/, 'the row accessible name includes linked permissions');
assert.equal(row.querySelector('.linked-badge'), null);
assert.equal(link.querySelector('svg').querySelector('path')?.tagName, 'path', 'icon is standalone, without a missing sprite symbol');
assert.equal(navButton(data.chats[1], writer).querySelector('.nav-linked'), null);
assert.equal(navButton(data.chats[2], emoji).querySelector('.avatar').textContent, '👩‍🍳');
for (const [status, state] of [['working', 'working'], ['typing', 'thinking']]) {
  data.statuses = [{ chat_id: 'agent:clients', agent_id: 'clients', status }];
  assert.equal(navButton(data.chats[0], clients).querySelector('.avatar').dataset.state, state);
}
data.statuses = [];

select('agent:clients');
queueComposerDock(data.chatId); data.messages = [{ id: 1, role: 'user', text: 'Hi' }]; renderEmpty();
assert.ok(!get('conversation').classList.contains('is-empty'));
assert.ok(get('emptyChat').hidden && !get('messageViewport').hidden);
assert.equal(animations.length, 1, 'first send animates from center to bottom');
assert.equal(animations[0].frames[0].transform, 'translateY(-350px)');
assert.equal(animations[0].frames[1].transform, 'translateY(0)');
assert.equal(animations[0].options.duration, 280);
renderEmpty(); assert.equal(animations.length, 1, 'refresh does not replay docking');
select('agent:writer'); assert.ok(animations[0].cancelled, 'switching chats cancels the old composer animation');
reduceMotion = true;
queueComposerDock(data.chatId); data.messages = [{ id: 2 }]; renderEmpty();
assert.equal(animations.length, 1, 'reduced motion docks immediately');
reduceMotion = false;
select('agent:writer'); data.messages = [{ id: 3 }]; renderEmpty();
assert.equal(animations.length, 1, 'opening an existing conversation does not animate as a send');
select('agent:clients'); queueComposerDock(data.chatId); select('agent:writer');
data.messages = [{ id: 4 }]; renderEmpty();
assert.equal(animations.length, 1, 'a queued send cannot animate another chat');
select('agent:clients');
data.deltas.set('elsewhere', { chat_id: 'agent:writer', text: 'Working' }); renderEmpty();
assert.ok(get('conversation').classList.contains('is-empty'), 'another chat stream cannot dismiss the greeting');
queueComposerDock(data.chatId); data.deltas.set('here', { chat_id: data.chatId, text: 'Hello' }); renderEmpty();
assert.equal(animations.length, 2, 'the first local stream also docks the composer');

(async () => {
  // Exercise the real send path with a fake API; docking must be queued by sendMessage.
  select('agent:clients'); get('messageInput').value = 'First question';
  const count = animations.length;
  let sentRequestId = null;
  context.fetch = async (url, options = {}) => {
    if (url === '/api/message') { sentRequestId = JSON.parse(options.body || '{}').request_id; return { ok: true, status: 200, json: async () => ({}) }; }
    assert.match(url, /^\/api\/chat\?id=/);
    // The server echoes the client's request_id, which is how the optimistic bubble is reconciled in place.
    return { ok: true, status: 200, json: async () => ({ chat: data.chats[0], messages: [{ id: 5, role: 'user', text: 'First question', request_id: sentRequestId }] }) };
  };
  await sendMessage({ preventDefault() {} });
  assert.equal(animations.length, count + 1, 'the successful first-message path queues and performs docking');
  assert.equal(get('messageInput').value, '');
  assert.equal(get('composer').dataset.pending, 'false');
  assert.equal(data.messages.length, 1);
  console.log('Chat presentation smoke checks passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
