/* Sidebar and version-control regression contracts. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const root = path.join(__dirname, '..');
const parity = fs.readFileSync(path.join(root, 'static/chat-parity.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');
assert.match(parity, /fieldLabel:\s*'Chat name'/, 'rename dialog labels its input Chat name');
assert.match(parity, /c\.name\s*\|\|\s*'New chat'/, 'default conversation has a readable name');
assert.doesNotMatch(parity, /Ongoing chat|New chat with \$\{a\.name\}/, 'expanded Pip list has neither the generic label nor duplicate action');
assert.match(html, /<div id="chatVersionBar" class="chat-version-bar" hidden>[^]*id="previousChatVersion"[^]*<details id="chatVersions"[^]*id="nextChatVersion"[^]*<\/div>/, 'controls and Earlier versions details share a horizontal wrapper');
assert.match(parity, /chatVersionSummary'\)\.textContent = `\$\{index \+ 1\}\/\$\{versions\.length\}`/, 'summary shows only current and total counts');
const output = execFileSync(process.execPath, [path.join(__dirname, 'parity_smoke.js')], { encoding: 'utf8' });
assert.match(output, /parity .*smoke checks passed/i, 'behavioral parity smoke passes');
console.log('Version controls smoke checks passed');
