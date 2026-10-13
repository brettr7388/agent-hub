/* Run with: node tests/full_access_permissions.js */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const read = (name) => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');
const html = read('static/index.html');
const app = read('static/app.js');
const form = /<form id="settingsForm">([\s\S]*?)<\/form>/.exec(html)?.[1];
assert.ok(form, 'General settings form exists');
const advanced = /<details\b([^>]*)>([\s\S]*?)<\/details>/.exec(form);
assert.ok(advanced, 'advanced settings are in the General settings form');
assert.doesNotMatch(advanced[1], /\bopen(?:\s|=|$)/, 'Advanced starts collapsed');
assert.match(advanced[2], /<label for="fullAccessPermissionMode">Full access permission mode<\/label>/);
assert.match(advanced[2], /<option value="auto">Auto \(recommended\)<\/option>/);
assert.match(advanced[2], /<option value="inherit">Ask nothing new \(use my Claude settings\)<\/option>/);
assert.match(advanced[2], /Auto uses Claude safety checks for common tools \(older CLIs allow edits and web tools\)\./);
assert.match(advanced[2], /Inherit uses existing Claude permission settings; new tools may be denied in background runs\./);
assert.match(advanced[2], /full-access Claude Pips only\. Private Pip and Draft only are unaffected\./);

const loadSnippet = /\$\('fullAccessPermissionMode'\)\.value = data\.settings\.full_access_permission_mode \|\| 'auto';/.exec(app)?.[0];
const saveSnippet = /post\('\/api\/settings', (\{ role_models, owner_name: [^}]*full_access_permission_mode: \$\('fullAccessPermissionMode'\)\.value \})\)/.exec(app)?.[1];
assert.ok(loadSnippet, 'settings loader reads the saved permission mode');
assert.ok(saveSnippet, 'settings save includes the permission mode');

const select = { value: '' };
const loadContext = { data: { settings: {} }, $: (id) => (id === 'fullAccessPermissionMode' ? select : null) };
vm.runInNewContext(loadSnippet, loadContext);
assert.equal(select.value, 'auto', 'missing saved value defaults to auto');
loadContext.data.settings.full_access_permission_mode = 'inherit';
vm.runInNewContext(loadSnippet, loadContext);
assert.equal(select.value, 'inherit', 'saved inherit value is loaded');

const role_models = { worker: { engine: 'claude', model: 'sonnet' } };
const ownerName = { value: '  Alex  ' };
select.value = 'inherit';
const payload = vm.runInNewContext(`(${saveSnippet})`, {
  role_models,
  $: (id) => id === 'ownerName' ? ownerName : select,
});
assert.equal(payload.full_access_permission_mode, 'inherit', 'save payload carries selected mode');
assert.equal(payload.owner_name, 'Alex');
assert.equal(payload.role_models, role_models);

console.log('full access permissions smoke passed');
