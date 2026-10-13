/* Run with: node tests/message_actions_smoke.js */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Node {
  constructor(tag = 'div') {
    this.tagName = tag; this.className = ''; this.children = []; this.dataset = {}; this.events = {};
    this.attributes = {}; this.hidden = false; this.disabled = false; this.isConnected = true;
    this.style = { setProperty(k, v) { this[k] = v; }, removeProperty(k) { delete this[k]; } };
    this.rect = { left: 20, top: 20, right: 120, bottom: 64, width: 100, height: 44 };
    this.offsetWidth = 240; this.offsetHeight = 52; this.clientHeight = 0; this.scrollHeight = 0;
    this.classList = {
      add: (name) => { if (!this.classList.contains(name)) this.className = `${this.className} ${name}`.trim(); },
      remove: (name) => { this.className = this.className.split(/\s+/).filter((x) => x && x !== name).join(' '); },
      contains: (name) => this.className.split(/\s+/).includes(name),
      toggle: (name, force) => { const on = force === undefined ? !this.classList.contains(name) : force; this.classList[on ? 'add' : 'remove'](name); return on; }
    };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return (this._text || '') + this.children.map((n) => n.textContent).join(''); }
  get childNodes() { return this.children; }
  set innerHTML(value) { if (this.tagName !== 'template') throw new Error('Unexpected HTML'); this.content = { firstElementChild: new Node('svg') }; }
  append(...nodes) { for (const n of nodes) { if (!n) continue; if (n.tagName === '#fragment') this.append(...n.children); else { n.parent = this; this.children.push(n); } } }
  prepend(...nodes) { for (const n of nodes.reverse()) { n.parent = this; this.children.unshift(n); } }
  replaceChildren(...nodes) { this.children = []; this._text = ''; this.append(...nodes); }
  replaceWith(other) { if (!this.parent) return; const i = this.parent.children.indexOf(this); this.parent.children[i] = other; other.parent = this.parent; this.remove(); }
  remove() { this.isConnected = false; if (this.parent) this.parent.children = this.parent.children.filter((n) => n !== this); }
  addEventListener(type, fn) { (this.events[type] ||= []).push(fn); }
  dispatch(type, props = {}) { const event = { type, target: this, currentTarget: this, preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; }, ...props }; for (const fn of this.events[type] || []) fn(event); return event; }
  click() { return this.dispatch('click'); }
  focus() { document.activeElement = this; this.focused = true; }
  setAttribute(k, v) { this.attributes[k] = String(v); this[k] = String(v); }
  getAttribute(k) { return this.attributes[k] ?? null; }
  getBoundingClientRect() { return this.isConnected ? this.rect : { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 }; }
  querySelectorAll(selector) {
    const parts = selector.split(',').map((s) => s.trim());
    const matches = (n, s) => s.startsWith('.') ? n.classList.contains(s.slice(1)) : s.startsWith('[aria-label=') ? n.getAttribute('aria-label') === s.slice(12, -1).replaceAll('"', '') : n.tagName === s;
    return this.children.flatMap((child) => [child, ...child.querySelectorAll(selector)]).filter((n) => parts.some((s) => matches(n, s)));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  contains(node) { return node === this || this.children.some((child) => child.contains(node)); }
  closest(selector) { for (let n = this; n; n = n.parent) if (selector.split(',').some((s) => s.trim().startsWith('.') && n.classList.contains(s.trim().slice(1)))) return n; return null; }
  scrollIntoView() {}
}

const elements = new Map();
const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8');
for (const m of html.matchAll(/<([a-z][\w-]*)\b([^>]*\bid="([^"]+)"[^>]*)>/gi)) { const n = new Node(m[1].toLowerCase()); n.id = m[3]; elements.set(n.id, n); }
const body = new Node('body');
const document = {
  body, events: {}, activeElement: null, visibilityState: 'visible', fonts: { ready: Promise.resolve() },
  addEventListener(type, fn) { (this.events[type] ||= []).push(fn); },
  getElementById(id) { if (!elements.has(id)) { const n = new Node(); n.id = id; elements.set(id, n); } return elements.get(id); },
  createElement: (tag) => new Node(tag), createElementNS: (_ns, tag) => new Node(tag),
  createDocumentFragment: () => new Node('#fragment'), querySelectorAll: () => [],
};
const timers = [];
const setTimeoutFake = (fn, ms) => { const t = { fn, ms, cancelled: false }; timers.push(t); return t; };
const clearTimeoutFake = (t) => { if (t) t.cancelled = true; };
let resolveFetch, fetchCalls = [], copiedText;
const windowEvents = {};
let resizeObserver, now = 1000;
class TouchDate extends Date { static now() { return now; } }
const context = {
  document, window: { innerWidth: 360, innerHeight: 600, visualViewport: { offsetLeft: 0, offsetTop: 0, width: 360, height: 600, addEventListener() {} }, addEventListener(type, fn) { (windowEvents[type] ||= []).push(fn); } },
  navigator: { onLine: true, clipboard: { writeText: async (text) => { copiedText = text; } } }, localStorage: { getItem: () => null, setItem() {} },
  location: { origin: 'http://localhost' }, history: {}, matchMedia: () => ({ matches: false }),
  requestAnimationFrame: (fn) => { fn(); }, setTimeout: setTimeoutFake, clearTimeout: clearTimeoutFake,
  ResizeObserver: class { constructor(callback) { this.callback = callback; resizeObserver ||= this; } observe(node) { this.observed = node; } },
  crypto: { randomUUID: () => 'request-1' }, Headers, Event, Intl, Date: TouchDate, Number, String, URL, console,
  confirm: () => true, fetch: (url, options) => { fetchCalls.push({ url, options }); return new Promise((resolve) => { resolveFetch = resolve; }); }
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'markdown.js'), 'utf8'), context);
let source = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.js'), 'utf8');
source = source.replace(/  setup\(\);[\s\S]*\}\)\(\);\s*$/, '  globalThis.__test = { messageNode, messageActions, openMessageMenu, closeMessagePopover, react, measureMessageOverflow, setupMessageInteractions, data, addReply, reactionBar, scheduleMessageMeasurements };\n})();');
vm.runInNewContext(source, context);
context.window.HubEmoji = { open(_input, callback) { context.__test.fullPickerCallback = callback; } };
const t = context.__test;
const all = (node) => [node, ...node.children.flatMap(all)];
const labels = (node) => all(node).filter((n) => n.tagName === 'button').map((n) => n.getAttribute('aria-label')).filter(Boolean);
const clickNamed = (node, label) => { const button = all(node).find((n) => n.getAttribute('aria-label') === label); assert.ok(button, `button ${label}`); button.click(); return button; };

// Two persistent hover actions; the reaction picker lives in the floating popover.
const message = { id: 1, role: 'assistant', agent_id: 'a', text: 'Answer', reactions: ['👍', '👍', '❤️'] };
t.data.agents = [{ id: 'a', name: 'Pip', emoji: '🤖' }]; t.data.messages = [message];
const node = t.messageNode(message); document.getElementById('messageList').append(node);
const actions = node.querySelector('.message-actions');
assert.equal(actions.children.length, 2, 'message has exactly React and Reply actions');
assert.deepEqual(labels(actions), ['React', 'Reply']);
assert.equal(node.querySelector('.message-reaction-picker'), null, 'inline picker is absent');
const chips = all(node).filter((n) => n.classList.contains('reaction-chip'));
assert.deepEqual(chips.map((n) => n.textContent), ['👍', '❤️'], 'saved chips are unique');
clickNamed(actions, 'React');
let picker = document.body.querySelector('.message-reaction-picker');
assert.ok(picker, 'quick picker opens in a floating popover');
assert.deepEqual(picker.querySelectorAll('button').slice(0, 4).map((n) => n.textContent), ['👍', '👎', '❤️', '❓']);
assert.equal(picker.querySelectorAll('button').some((n) => ['😂', '✅'].includes(n.textContent)), false);
assert.equal(picker.querySelectorAll('button')[4].getAttribute('aria-label'), 'More reactions');
assert.ok(parseFloat(picker.style.left) >= 8 && parseFloat(picker.style.left) <= 112, 'picker stays within narrow viewport');
assert.ok(parseFloat(picker.style.top) >= 8 && parseFloat(picker.style.top) <= 540, 'picker stays within viewport at top edge');

// Clicking a reaction closes synchronously, before the fake request resolves, then refreshes the saved chip.
const quick = picker.querySelectorAll('button')[1]; quick.click();
assert.equal(document.body.querySelector('.message-reaction-picker'), null, 'picker closes before fetch settles');
assert.equal(fetchCalls.at(-1).url, '/api/reaction');
assert.equal(JSON.parse(fetchCalls.at(-1).options.body).emoji, '👎');
resolveFetch({ status: 200, ok: true, json: async () => ({ reactions: ['👎'] }) });
setImmediate(async () => {
  await Promise.resolve(); await Promise.resolve();
  assert.deepEqual(all(node).filter((n) => n.classList.contains('reaction-chip')).map((n) => n.textContent), ['👎'], 'successful API result updates saved chip');

  // More hands off the callback supplied by the full emoji picker.
  clickNamed(actions, 'React'); picker = document.body.querySelector('.message-reaction-picker');
  picker.querySelectorAll('button')[4].click();
  assert.equal(document.body.querySelector('.message-reaction-picker'), null, 'More closes quick picker');
  t.fullPickerCallback('🧠');
  assert.equal(JSON.parse(fetchCalls.at(-1).options.body).emoji, '🧠', 'full picker callback sends its selected emoji');
  resolveFetch({ status: 200, ok: true, json: async () => ({ reactions: ['👎', '🧠'] }) });

  // Right click and touch long-press open the same floating action menu.
  t.setupMessageInteractions();
  const menuNode = t.messageNode({ id: 2, role: 'assistant', agent_id: 'a', text: 'More', reactions: [] }); document.getElementById('messageList').append(menuNode);
  const contextEvent = menuNode.dispatch('contextmenu', { target: menuNode });
  assert.equal(contextEvent.defaultPrevented, true);
  let menu = document.body.querySelector('.message-context-menu');
  assert.deepEqual(labels(menu), ['React', 'Reply', 'Copy message', 'Retry answer']);
  const reactMenuButton = all(menu).find((n) => n.getAttribute('aria-label') === 'React');
  reactMenuButton.rect = { left: 130, top: 250, right: 174, bottom: 294, width: 44, height: 44 };
  reactMenuButton.click();
  picker = document.body.querySelector('.message-reaction-picker');
  assert.ok(picker && parseFloat(picker.style.left) >= 110, 'switching touch menu React anchors to its own button within viewport bounds');
  t.closeMessagePopover();
  menuNode.dispatch('pointerdown', { pointerType: 'touch', clientX: 41, clientY: 32, pointerId: 7, target: menuNode });
  const press = timers.at(-1); assert.equal(press.ms, 550); press.fn();
  menu = document.body.querySelector('.message-context-menu');
  assert.ok(menu, 'long press opens floating actions');
  assert.ok(labels(menu).includes('Copy message') && labels(menu).includes('Retry answer'));
  menuNode.dispatch('contextmenu', {target:menuNode});
  assert.equal(document.body.querySelector('.message-context-menu'),menu,'native touch contextmenu does not reset the release guard');
  now += 5000; // A finger can stay held well past 400 ms after the menu opened.
  for (const fn of document.events.focusin || []) fn({ target: menuNode.querySelector('.message-body') });
  assert.equal(document.body.querySelector('.message-context-menu'), menu, 'focus during long hold keeps the menu open');
  menuNode.dispatch('pointerup', { pointerId: 7, clientX: 41, clientY: 32 });
  for (const fn of document.events.pointerup || []) fn({ pointerId: 7, target: menuNode });
  const releaseClick = { target: menuNode.querySelector('.message-body'), preventDefault(){this.prevented=true;}, stopPropagation(){this.stopped=true;} };
  for (const fn of document.events.click || []) fn(releaseClick);
  for (const fn of document.events.focusin || []) fn({ target: releaseClick.target });
  assert.ok(releaseClick.prevented && releaseClick.stopped, 'synthetic release click is consumed');
  assert.equal(document.body.querySelector('.message-context-menu'), menu, 'finger lift and synthetic focus leave menu open');
  now += 399;
  for (const fn of document.events.focusin || []) fn({ target: menuNode });
  assert.equal(document.body.querySelector('.message-context-menu'), menu, 'guard lasts 400 ms after release');
  clickNamed(menu, 'React');
  assert.ok(document.body.querySelector('.message-reaction-picker'), 'menu actions work during the release guard');
  t.closeMessagePopover();
  menuNode.dispatch('pointerdown', { pointerType:'touch', pointerId:70, clientX:41, clientY:32, target:menuNode }); timers.at(-1).fn();
  for (const fn of document.events.pointerup || []) fn({pointerId:70,target:menuNode});
  now += 401;
  for (const fn of document.events.focusin || []) fn({target:menuNode});
  assert.equal(document.body.querySelector('.message-context-menu'),null,'owner focus closes normally after the release guard expires');

  // Touch movement cancels long-press; horizontal swipe adds a reply; cancel clears the gesture.
  const gesture = t.messageNode({ id: 3, role: 'user', text: 'Question' }); document.getElementById('messageList').append(gesture);
  gesture.dispatch('pointerdown', { pointerType: 'touch', clientX: 10, clientY: 10, pointerId: 8, target: gesture });
  const cancelledPress = timers.at(-1); gesture.dispatch('pointermove', { pointerId: 8, clientX: 40, clientY: 10 });
  assert.equal(cancelledPress.cancelled, true, 'movement cancels long-press');
  assert.equal(document.body.querySelector('.message-context-menu'), null);
  gesture.dispatch('pointerup', { pointerId: 8, clientX: 40, clientY: 10 });
  gesture.dispatch('pointerdown', { pointerType: 'touch', clientX: 10, clientY: 10, pointerId: 9, target: gesture });
  gesture.dispatch('pointermove', { pointerId: 9, clientX: 76, clientY: 12 });
  gesture.dispatch('pointerup', { pointerId: 9, clientX: 76, clientY: 12 });
  assert.deepEqual(Array.from(t.data.replyTo), [3], 'right swipe adds reply');
  assert.equal(gesture.classList.contains('swipe-reply'), false, 'swipe state clears on pointerup');
  gesture.dispatch('pointerdown', { pointerType: 'touch', clientX: 10, clientY: 10, pointerId: 10, target: gesture });
  const cancelTimer = timers.at(-1); gesture.dispatch('pointercancel', { pointerId: 10 });
  assert.equal(cancelTimer.cancelled, true, 'pointer cancel clears pending long-press');

  // Outside click and Escape both dismiss the popup.
  t.openMessageMenu(message, node);
  const outside = new Node('div');
  for (const fn of document.events.pointerdown || []) fn({ target: outside });
  assert.equal(document.body.querySelector('.message-context-menu'), null, 'outside click dismisses actions');
  t.openMessageMenu(message, node); menu = document.body.querySelector('.message-context-menu');
  menu.dispatch('keydown', { key: 'Escape' });
  assert.equal(document.body.querySelector('.message-context-menu'), null, 'Escape dismisses actions');

  // Menu actions retain their behavior, using the current server snapshot.
  t.data.messages = [{ id: 9, role: 'user', text: 'Original question' }, { ...message, text: 'Fresh answer', reply_to: 9 }];
  t.openMessageMenu(message, node); menu = document.body.querySelector('.message-context-menu');
  clickNamed(menu, 'Copy message');
  assert.equal(copiedText, 'Fresh answer', 'Copy uses the refreshed message rather than the initial closure');
  assert.equal(document.body.querySelector('.message-context-menu'), null, 'Copy dismisses its menu');
  let submitted = 0; document.getElementById('composer').requestSubmit = () => { submitted++; };
  t.openMessageMenu(message, node); clickNamed(document.body.querySelector('.message-context-menu'), 'Retry answer');
  assert.equal(document.getElementById('messageInput').value, 'Original question');
  assert.deepEqual(Array.from(t.data.replyTo), [9]); assert.equal(submitted, 1, 'Retry resends the causal question once');
  t.openMessageMenu(message, node); clickNamed(document.body.querySelector('.message-context-menu'), 'Reply');
  assert.equal(t.data.replyTo.at(-1), message.id, 'Reply quotes the chosen message');

  // Overflow follows measured layout, preserves expansion, and recomputes after resize.
  const content = new Node(); content.classList.add('group-answer');
  const bodyNode = new Node(); bodyNode.className = 'message-body'; bodyNode.clientHeight = 80; bodyNode.scrollHeight = 80; content.append(bodyNode);
  t.measureMessageOverflow(content);
  assert.equal(content.querySelector('.group-show-more'), null, 'fitting message has no control');
  bodyNode.scrollHeight = 300; t.measureMessageOverflow(content);
  let more = content.querySelector('.group-show-more');
  assert.ok(more && more.textContent === 'Show more', 'overflowing short text gets a toggle based on layout');
  more.click(); assert.equal(content.classList.contains('expanded'), true); assert.equal(more.textContent, 'Show less');
  t.measureMessageOverflow(content);
  assert.equal(content.classList.contains('expanded'), true, 'remeasuring an overflowing expanded message keeps it expanded');
  more.click(); assert.equal(content.classList.contains('expanded'), false); assert.equal(more.textContent, 'Show more');
  bodyNode.scrollHeight = 5000; t.measureMessageOverflow(content);
  assert.ok(content.querySelector('.group-show-more'), 'multiline rendered content can overflow regardless of source character count');
  bodyNode.scrollHeight = 80; t.measureMessageOverflow(content);
  assert.equal(content.querySelector('.group-show-more'), null, 'resize into fitting layout hides toggle');
  const scheduled = new Node(); scheduled.classList.add('group-answer'); const scheduledBody = new Node(); scheduledBody.className = 'message-body'; scheduledBody.clientHeight = 50; scheduledBody.scrollHeight = 120; scheduled.append(scheduledBody); document.getElementById('messageList').append(scheduled);
  for (const fn of windowEvents.resize || []) fn();
  assert.ok(scheduled.querySelector('.group-show-more'), 'resize queues and runs overflow measurement');
  scheduledBody.scrollHeight = 50; resizeObserver.callback();
  assert.equal(scheduled.querySelector('.group-show-more'), null, 'observed layout changes remove an unnecessary toggle');
  assert.equal(resizeObserver.observed, document.getElementById('messageList'));

  // Message construction must enroll short multiline content without a length heuristic.
  t.data.chatId = 'group:layout'; t.data.chats = [{ id: 'group:layout', type: 'group' }];
  const shortLines = t.messageNode({ id: 40, role: 'assistant', text: 'a\nb\nc\nd\ne\nf\ng', independent: true });
  document.getElementById('messageList').append(shortLines);
  const shortContent = shortLines.querySelector('.message-content'), shortBody = shortLines.querySelector('.message-body');
  shortBody.clientHeight = 60; shortBody.scrollHeight = 90; t.scheduleMessageMeasurements();
  assert.ok(shortContent.querySelector('.group-show-more'), 'short source with rendered overflow gets Show more');
  const longFits = t.messageNode({ id: 41, role: 'assistant', text: 'Fits in the wide view. '.repeat(30), independent: true });
  document.getElementById('messageList').append(longFits);
  const fitBody = longFits.querySelector('.message-body'); fitBody.clientHeight = fitBody.scrollHeight = 100;
  t.scheduleMessageMeasurements();
  assert.equal(longFits.querySelector('.group-show-more'), null, 'long source that fits rendered height has no Show more');
  console.log('message action smoke checks passed');
});
