/* Focused race smoke for asynchronous saved-login card hydration. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.events = {}; this.dataset = {}; this.disabled = false; this.value = ''; this._text = ''; this.isConnected = true; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(''); }
  append(...items) { for (const item of items) { item.parentNode = this; this.children.push(item); } }
  replaceWith(item) { const at = this.parentNode?.children.indexOf(this); if (at >= 0) { this.parentNode.children[at] = item; item.parentNode = this.parentNode; } }
  addEventListener(name, fn) { this.events[name] = fn; }
  setAttribute() {}
  querySelectorAll(selector) { const all = this.children.flatMap((child) => [child, ...child.querySelectorAll(selector)]); return selector === 'button' ? all.filter((item) => item.tagName === 'button') : all.filter((item) => selector.startsWith('.') && item.className?.split(' ').includes(selector.slice(1))); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { let item = this; while (item) { if (item.className?.split(' ').includes(selector.slice(1))) return item; item = item.parentNode; } return null; }
}

const context = { document: { getElementById: () => null, createElement: (tag) => new Element(tag) }, window: {}, module: { exports: {} } };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/pip-browser.js'), 'utf8'), context);
const browser = context.module.exports;
let resolveLogins;
let pendingSaved = true;
let liveEntries = [];
const posts = [];
browser.setup({
  api: (url) => {
    if (url === '/api/pip-browser') return Promise.resolve({ available: true, saved_logins_available: true });
    return pendingSaved ? new Promise((resolve) => { resolveLogins = resolve; }) : Promise.resolve({ available: true, logins: liveEntries });
  },
  post: async (url, body) => posts.push({ url, body }),
  refreshChat: async () => {}, showToast: () => {}
});

(async () => {
  const message = { id: 11 };
  const initial = { kind: 'login_fill_request', index: 2, site: '127.0.0.1:4841', status: 'pending' };
  const stale = browser.card(initial, message);
  const root = new Element('main'); root.append(stale);
  const actions = stale.querySelectorAll('button');
  assert.equal(actions[0].disabled, true, 'approval stays disabled while saved accounts load');
  assert.equal(actions[1].disabled, true, 'decline waits until the card state is current');

  browser.updateCard(stale, { ...initial, status: 'filled' }, message);
  assert.equal(stale.dataset.browserSignature, '', 'replaced card is invalidated');
  resolveLogins({ available: true, logins: [{ id: 'acct', site: '127.0.0.1:4841', username: 'alice', subdomains: [] }] });
  pendingSaved = false;
  await Promise.resolve();
  await Promise.resolve();
  await actions[0].events.click({ currentTarget: actions[0] });
  assert.equal(posts.length, 0, 'a late login response cannot make a replaced card actionable');

  liveEntries = [{ id: 'shown-id', site: 'shop.example', username: 'shown-user', subdomains: [] }];
  await browser.refresh();
  const accountCard = browser.card({ kind: 'login_fill_request', index: 3, site: 'shop.example', status: 'pending' }, message);
  await Promise.resolve();
  assert.match(accountCard.textContent, /Use shown-user on shop\.example\?/);
  liveEntries = [{ id: 'different-id', site: 'shop.example', username: 'different-user', subdomains: [] }];
  await browser.refresh();
  const approve = accountCard.querySelectorAll('button')[0];
  await approve.events.click({ currentTarget: approve });
  assert.equal(posts.at(-1).body.login_id, 'shown-id', 'approval stays bound to the account shown when the user approved');

  liveEntries = [
    { id: 'first', site: 'multi.example', username: 'first-user', subdomains: [] },
    { id: 'second', site: 'multi.example', username: 'second-user', subdomains: [] }
  ];
  await browser.refresh();
  const multiCard = browser.card({ kind: 'login_fill_request', index: 4, site: 'multi.example', status: 'pending' }, message);
  await Promise.resolve();
  liveEntries = [{ id: 'remaining', site: 'multi.example', username: 'remaining-user', subdomains: [] }];
  await browser.refresh();
  const choose = multiCard.querySelectorAll('button')[0];
  await choose.events.click({ currentTarget: choose });
  assert.equal(multiCard.querySelector('.login-chooser').children[0].children[0].children[0].value, 'remaining');
  assert.equal(posts.at(-1).body.index, 3, 'a changed account list still requires chooser confirmation');
  const explicitApprove = multiCard.querySelector('.login-chooser').querySelector('button');
  await explicitApprove.events.click({ currentTarget: explicitApprove });
  assert.equal(posts.at(-1).body.login_id, 'remaining');
  console.log('saved login card race smoke passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
