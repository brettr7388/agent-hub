/* Run with: node tests/media_marker_smoke.js. Real message rendering with the shared HTML fixture. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

let fixtureSource = fs.readFileSync(path.join(__dirname, 'ui_smoke.js'), 'utf8').split('const { data, chatTime, quotedText,')[0];
fixtureSource = fixtureSource.replace('vm.runInNewContext(source, context);', "vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'chat-parity.js'), 'utf8'), context); vm.runInNewContext(source, context);");
fixtureSource = fixtureSource.replace('globalThis.__test = { setupComposerInteractions,', 'globalThis.__test = { parity, ');
const fixture = { require, __dirname, console, Event, URL, Headers };
vm.runInNewContext(fixtureSource + '\nglobalThis.fixture = { context, elements };', fixture);
const { context, elements } = fixture.fixture;
const app = context.__test, { data } = app;
data.authenticated = true;
data.agents = [{ id: 'artist', name: 'Artist' }];
data.chats = [{ id: 'agent:artist', type: 'direct', name: 'Artist', agents: ['artist'] }];
data.chatId = 'agent:artist'; data.messages = []; data.statuses = [];
const list = elements.get('messageList');
const validUrl = '/api/file?chat_id=agent%3Aartist&message_id=1&path=chart.png';
const image = (name, spans, url = validUrl) => ({ kind: 'image', name, url, file_marker_spans: spans });
const span = (text, marker, from = 0) => { const start = Array.from(text.slice(0, text.indexOf(marker, from))).length; return [start, start + Array.from(marker).length]; };
const render = (text, attachments, id = 1) => app.messageNode({ id, role: 'assistant', agent_id: 'artist', text, attachments });
const body = node => node.querySelector('.message-body')?.textContent || '';

const inline = 'Here is FILE: chart.png; keep this caption.';
const inlineNode = render(inline, [image('chart.png', [span(inline, 'FILE: chart.png')])]);
assert.equal(body(inlineNode), 'Here is ; keep this caption.', 'midline marker is hidden without losing surrounding words');
assert.ok(inlineNode.querySelector('img'), 'renderable image remains visible');

const repeated = '😀 First FILE: chart.png, then FILE: second.png, done.';
const repeatedNode = render(repeated, [
  image('chart.png', [span(repeated, 'FILE: chart.png')]),
  image('second.png', [span(repeated, 'FILE: second.png')], validUrl.replace('chart.png', 'second.png')),
]);
assert.equal(body(repeatedNode), '😀 First , then , done.', 'multiple Python codepoint spans hide both markers after an emoji');
assert.equal(repeatedNode.querySelectorAll('img').length, 2);

const missing = 'See FILE: missing.png and FILE: chart.png.';
const unavailableNode = render(missing, [
  { kind: 'unavailable', unavailable: true, name: 'missing.png', reason: 'Image unavailable' },
  image('chart.png', [span(missing, 'FILE: chart.png')]),
], 2);
assert.equal(body(unavailableNode), 'See FILE: missing.png and .', 'unavailable marker stays readable');
assert.ok(unavailableNode.querySelector('.attachment-unavailable'));

const rejected = 'FILE: blocked.png stays visible.';
const rejectedNode = render(rejected, [image('blocked.png', [span(rejected, 'FILE: blocked.png')], 'javascript:alert(1)')], 3);
assert.equal(body(rejectedNode), rejected, 'bad URL cannot suppress a marker');
assert.equal(rejectedNode.querySelectorAll('img').length, 0);

const broken = 'Preview FILE: broken.png with context.';
const brokenNode = render(broken, [image('broken.png', [span(broken, 'FILE: broken.png')])], 4);
assert.equal(body(brokenNode), 'Preview  with context.');
brokenNode.querySelector('img').dispatchEvent({ type: 'error' });
assert.equal(body(brokenNode), broken, 'image load failure restores its source marker');

data.messages = [{ id: 50, role: 'system', text: 'Artist was created.' }];
list.replaceChildren(); app.reconcileMessages();
assert.ok(list.findText('Artist was created.'));
data.messages = [{ id: 50, role: 'system', text: 'Creation undone.' }];
app.reconcileMessages();
assert.equal(list.children.length, 1, 'reconcile replaces the mounted receipt in place');
assert.ok(list.findText('Creation undone.'), 'updated receipt appears');
assert.equal(list.findText('Artist was created.'), false, 'old receipt text is removed');

console.log('Media marker and receipt smoke checks passed');
