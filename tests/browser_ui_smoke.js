/* Browser UI and copy contracts; run with node tests/browser_ui_smoke.js. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const read = (name) => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');
const html = read('static/index.html');
const app = read('static/app.js');
const Access = require('../static/access.js');

for (const id of ['agentChrome', 'agentBrowserReason', 'searchShortcut']) assert.match(html, new RegExp(`id="${id}"`));
assert.match(app, /chrome: browserCheck\.checked/, 'managed settings persist the browser flag');
assert.match(app, /chrome: \$\('agentChrome'\)\.checked/, 'new and Guide-edited Pip payloads persist the browser flag');
assert.match(app, /privateCheck\?\.addEventListener\('change', syncBrowser\)/);
assert.match(app, /\$\('agentDraftOnly'\)\.addEventListener\('change', syncCreateBrowser\)/);
assert.deepEqual(Access.mode({ chrome: true }), ['Full access', 'Pip browser']);
assert.deepEqual(Access.mode({ chrome: true, private_pip: true }), ['Private']);
assert.deepEqual(Access.mode({ chrome: true, draft_only: true }), ['Draft only']);
assert.equal((html.match(/<summary>Messages, groups, and team tasks<\/summary>/g) || []).length, 1);
assert.doesNotMatch(html, /Full access uses the normal signed-in browser profile|on the Mac|OS Keychain/);
assert.doesNotMatch(read('README.md'), /\(PASS ?\d+\)/);
for (const file of ['README.md', 'SECURITY.md', 'docs/browser-passwords.md']) {
  const content = read(file);
  assert.match(content, /Private Pip/);
  assert.match(content, /credential store|vault CLI/i);
}
console.log('UI smoke passed');
