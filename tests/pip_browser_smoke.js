/* Focused offline DOM smoke for the Pip browser. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
assert.match(html, /\/static\/pip-browser\.js/);
for (const id of ['pipBrowserStatus','pipBrowserOpen','pipBrowserReset','savedLoginsSection','savedLoginsList','savedLoginForm','savedLoginPassword']) assert.match(html, new RegExp(`id="${id}"`));
assert.match(html, /Browser &amp; passwords/);
class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.events = {}; this.dataset = {}; this.hidden = false; this.disabled = false; this.value = ''; this._text = ''; this.attrs = {}; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(''); }
  append(...children) { for (const child of children) { child.parentNode = this; this.children.push(child); } }
  replaceChildren(...children) { this._text = ''; this.children = []; this.append(...children); }
  replaceWith(other) { const at = this.parentNode?.children.indexOf(this); if (at >= 0) { this.parentNode.children[at] = other; other.parentNode = this.parentNode; } }
  addEventListener(name, fn) { this.events[name] = fn; }
  setAttribute(name, value) { this.attrs[name] = value; }
  querySelectorAll(selector) { const descendants = this.children.flatMap((child) => [child, ...child.querySelectorAll(selector)]); if (selector === 'button') return descendants.filter((child) => child.tagName === 'button'); return descendants.filter((child) => selector.startsWith('.') && child.className?.split(' ').includes(selector.slice(1))); }
  querySelector(selector) { if (selector === 'button[type="submit"]') return this.querySelectorAll('button').find((child) => child.type === 'submit'); return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { let item = this; while (item) { if (item.className?.split(' ').includes(selector.slice(1))) return item; item = item.parentNode; } return null; }
  reset() { for (const child of this.children) if (child.value !== undefined) child.value = ''; }
}
const ids = new Map();
for (const [, id] of html.matchAll(/\bid="([^"]+)"/g)) ids.set(id, new Element());
const $ = (id) => ids.get(id);
const form = $('savedLoginForm'); const submit = new Element('button'); submit.type = 'submit'; form.append(submit);
const context = { document: { getElementById: $, createElement: (tag) => new Element(tag) }, window: {}, module: { exports: {} } };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/pip-browser.js'), 'utf8'), context);
const browser = context.module.exports;
const calls = []; const toasts = [];
let entries = [{ id: 'one', site: 'tiktok.com', username: 'alice', subdomains: [] }, { id: 'two', site: 'tiktok.com', username: 'bob', subdomains: [] }];
let available = true;
const hooks = {
  api: async (url) => url === '/api/pip-browser' ? { available, running: false, saved_logins_available: available } : { available, logins: entries },
  post: async (url, body) => { calls.push({ url, body: structuredClone(body) }); return url === '/api/pip-browser/open' ? { available: true, running: true, opened_on: 'Mac', saved_logins_available: true } : { card: { status: 'filled' } }; },
  refreshChat: async () => {}, showToast: (text) => toasts.push(text)
};
const click = async (button) => button.events.click({ currentTarget: button });
(async () => {
  browser.setup(hooks);
  await browser.refresh();
  assert.equal($('savedLoginsSection').hidden, false);
  assert.equal($('savedLoginsList').children.length, 2);
  $('savedLoginSite').value = 'tiktok.com'; $('savedLoginUsername').value = 'alice'; $('savedLoginPassword').value = 'SECRET'; $('savedLoginSubdomains').value = 'www.tiktok.com';
  const saving = form.events.submit({ preventDefault() {}, currentTarget: form });
  assert.equal($('savedLoginPassword').value, '', 'password clears before request completion');
  await saving;
  assert.deepEqual(calls.at(-1).body, { site: 'tiktok.com', username: 'alice', password: 'SECRET', subdomains: ['www.tiktok.com'] });
  $('savedLoginPassword').value = 'transient'; $('settingsDialog').events.close(); assert.equal($('savedLoginPassword').value, '');
  for (const invalidSite of ['localhost', 'localhost:abc', 'localhost:0', 'localhost:65536', '[::1]']) {
    $('savedLoginSite').value = invalidSite; $('savedLoginUsername').value = 'local'; $('savedLoginPassword').value = 'LOCAL_SECRET';
    const beforeInvalidLocal = calls.length;
    await form.events.submit({ preventDefault() {}, currentTarget: form });
    assert.equal(calls.length, beforeInvalidLocal, `${invalidSite} is rejected before POST`);
  }
  assert.match(form.children.find((child) => child.id === 'savedLoginPortHelp').textContent, /Add the port.*localhost:4841/);
  $('savedLoginSite').value = 'localhost:4841'; $('savedLoginPassword').value = 'LOCAL_SECRET';
  const validLocalSave = form.events.submit({ preventDefault() {}, currentTarget: form }); await validLocalSave;
  assert.equal(calls.at(-1).body.site, 'localhost:4841');
  $('savedLoginSite').value = 'http://localhost:80';
  const defaultPortSave = form.events.submit({ preventDefault() {}, currentTarget: form }); await defaultPortSave;
  assert.equal(calls.at(-1).body.site, 'http://localhost:80');
  const message = { id: 32 };
  const signin = browser.card({ kind: 'signin_request', index: 0, site: 'tiktok.com', reason: 'Please sign in', status: 'pending' }, message);
  assert.match(signin.textContent, /Sign in needed: tiktok.com — Please sign in/);
  assert.equal(signin.children[0].attrs.title, 'Sign in needed: tiktok.com — Please sign in');
  assert.deepEqual(signin.querySelectorAll('button').map((item) => item.textContent), ['Open Pip browser', 'Done']);
  await click(signin.querySelector('button'));
  assert.deepEqual(calls.at(-1).body, { message_id: 32, index: 0, action: 'open' });
  const opened = browser.card({ kind: 'signin_request', index: 0, site: 'tiktok.com', status: 'opened' }, message);
  assert.match(opened.textContent, /opened on the host computer/);
  assert.deepEqual(opened.querySelectorAll('button').map(item => item.textContent), ['Open Pip browser', 'Done']);
  await click(opened.querySelectorAll('button')[0]);
  assert.deepEqual(calls.at(-1).body, { message_id: 32, index: 0, action: 'open' });
  await click(opened.querySelectorAll('button')[1]);
  assert.deepEqual(calls.at(-1).body, { message_id: 32, index: 0, action: 'done' });
  const refused = browser.card({ kind: 'login_fill_request', index: 3, site: 'tiktok.com', status: 'refused', result: 'Missing login fields — refused' }, message);
  assert.match(refused.textContent, /Missing login fields — refused/);
  const precise = 'The Pip login tab navigated away from 127.0.0.1:4841 — refused';
  assert.ok(browser.card({kind:'login_fill_request', site:'127.0.0.1:4841', status:'refused', result:precise}, message).textContent.includes(precise));
  const fill = browser.card({ kind: 'login_fill_request', index: 1, site: 'tiktok.com', status: 'pending' }, message);
  await click(fill.querySelectorAll('button')[0]);
  const chooser = fill.querySelector('.login-chooser');
  assert.ok(chooser, 'multiple accounts require selection');
  const select = chooser.children[0].children[0];
  select.value = 'two';
  await click(chooser.querySelector('button'));
  assert.deepEqual(calls.at(-1).body, { message_id: 32, index: 1, action: 'approve', login_id: 'two' });
  entries = [{ id: 'solo', site: 'solo.example', username: 'visible-user', subdomains: [] }];
  await browser.refresh();
  const single = browser.card({ kind: 'login_fill_request', index: 4, site: 'solo.example', status: 'pending' }, message);
  await Promise.resolve();
  assert.match(single.textContent, /Use visible-user on solo\.example\?/);
  assert.equal(single.querySelectorAll('button')[0].textContent, 'Approve fill');
  await click(single.querySelectorAll('button')[0]);
  assert.deepEqual(calls.at(-1).body, { message_id: 32, index: 4, action: 'approve', login_id: 'solo' });
  assert.match(browser.card({ kind: 'login_fill_request', index: 4, site: 'solo.example', status: 'filled' }, message).textContent, /click Sign in.*Do not reload/);
  entries = [
    { id: 'legacy', site: '127.0.0.1', username: 'old-local', subdomains: [] },
    { id: 'exact', site: '127.0.0.1:4841', username: 'exact-local', subdomains: [] },
    { id: 'other-port', site: '127.0.0.1:4842', username: 'other-port', subdomains: [] },
    { id: 'other-host', site: 'localhost', username: 'other-host', subdomains: [] }
  ];
  await browser.refresh();
  assert.match($('savedLoginsList').textContent, /Add the port to use this saved login/);
  const local = browser.card({ kind: 'login_fill_request', index: 5, site: '127.0.0.1:4841', status: 'pending' }, message);
  await Promise.resolve();
  assert.match(local.textContent, /Use exact-local on 127\.0\.0\.1:4841\?/);
  await click(local.querySelectorAll('button')[0]);
  assert.deepEqual(calls.at(-1).body, { message_id: 32, index: 5, action: 'approve', login_id: 'exact' });
  const otherPort = browser.card({ kind: 'login_fill_request', index: 6, site: '127.0.0.1:4842', status: 'pending' }, message);
  await Promise.resolve();
  assert.match(otherPort.textContent, /Use other-port on 127\.0\.0\.1:4842\?/);
  await click(otherPort.querySelectorAll('button')[0]);
  assert.deepEqual(calls.at(-1).body, { message_id: 32, index: 6, action: 'approve', login_id: 'other-port' });
  const declined = browser.card({ kind: 'login_fill_request', index: 2, site: 'other.com', status: 'pending' }, message);
  await click(declined.querySelectorAll('button')[1]);
  assert.deepEqual(calls.at(-1).body, { message_id: 32, index: 2, action: 'dont' });
  $('pipBrowserReset').events.click({ currentTarget: $('pipBrowserReset') });
  assert.notEqual(calls.at(-1).url, '/api/pip-browser/reset', 'reset needs explicit confirmation');
  await click($('pipBrowserReset'));
  assert.deepEqual(calls.at(-1), { url: '/api/pip-browser/reset', body: { confirm: true } });
  available = false; await browser.refresh();
  assert.equal($('savedLoginsSection').hidden, true, 'unavailable Keychain hides login controls');
  assert.equal($('pipBrowserOpen').disabled, true);
  assert.ok(!toasts.some((text) => text.includes('SECRET')));
  console.log('pip browser smoke passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
