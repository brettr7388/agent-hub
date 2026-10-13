/* Access switches remember the browser choice and keep disabled labels readable. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
let fixtureSource = fs.readFileSync(path.join(__dirname, 'ui_smoke.js'), 'utf8').split('const { data, chatTime, quotedText,')[0];
fixtureSource = fixtureSource.replace('globalThis.__test = { setupComposerInteractions,', 'globalThis.__test = { syncCreateBrowser, setupComposerInteractions,');
const fixture = { require, __dirname, console, Event, URL, Headers };
vm.runInNewContext(fixtureSource + '\nglobalThis.fixture = { context, elements, Node };', fixture);
const { context, elements, Node } = fixture.fixture;
const app = context.__test;
const body = new Node();
app.agentSettings(body, { id: 'writer', name: 'Writer', engine: 'claude', model: 'haiku', chrome: true });
const browser = body.querySelector('[name=chrome]');
const privatePip = body.querySelector('[name=private_pip]');
const draft = body.querySelector('[name=draft_only]');
const toggle = (input, checked) => { input.checked = checked; input.events.change(); };
toggle(privatePip, true); toggle(draft, true); toggle(privatePip, false);
assert.equal(browser.checked, false); assert.equal(browser.disabled, true);
toggle(draft, false);
assert.equal(browser.checked, true, 'original tick returns after both restrictions are off');
browser.checked = false; toggle(draft, true); toggle(draft, false);
assert.equal(browser.checked, false, 'an unchecked choice stays unchecked');
const createBrowser = elements.get('agentChrome');
const createPrivate = elements.get('agentPrivatePip');
const createDraft = elements.get('agentDraftOnly');
createBrowser.checked = true; createPrivate.checked = true; createDraft.checked = false; app.syncCreateBrowser(true);
createDraft.checked = true; app.syncCreateBrowser(); createPrivate.checked = false; app.syncCreateBrowser();
assert.equal(createBrowser.disabled, true);
createDraft.checked = false; app.syncCreateBrowser();
assert.equal(createBrowser.checked, true, 'Create Pip restores the browser tick');
createPrivate.checked = true; app.syncCreateBrowser(); createPrivate.checked = false; createBrowser.checked = false; app.syncCreateBrowser(true);
assert.equal(createBrowser.checked, false, 'a fresh Create Pip dialog forgets the previous choice');
const css = fs.readFileSync(path.join(__dirname, '../static/style.css'), 'utf8');
assert.match(css, /\.check-line:has\(input:disabled\)\{color:var\(--text\);opacity:1\}/);
assert.match(css, /\.check-line input:disabled\{[^}]*opacity:1[^}]*border:2px solid var\(--muted\)/);
const luminance = hex => {
  const rgb = hex.match(/\w\w/g).map(value => parseInt(value, 16) / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
  return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
};
const color = (rule, name) => {
  const hex = rule.match(new RegExp(`--${name}:#([0-9a-f]+)`))[1];
  return hex.length === 3 ? [...hex].map(c => c + c).join('') : hex;
};
for (const selector of [':root', ':root[data-theme=dark]']) {
  const rule = css.slice(css.indexOf(selector + '{')).split('}')[0];
  const a = luminance(color(rule, 'text')), b = luminance(color(rule, 'panel'));
  assert.ok((Math.max(a, b) + .05) / (Math.min(a, b) + .05) >= 4.5, `${selector} disabled label contrast`);
}
console.log('Pip browser Settings checks passed');
