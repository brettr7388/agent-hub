/* Real event handlers + fake DOM/XHR, entirely offline. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
let fixtureSource = fs.readFileSync(path.join(__dirname, 'ui_smoke.js'), 'utf8').split('const { data, chatTime, quotedText,')[0];
fixtureSource = fixtureSource.replace('globalThis.__test = { setupComposerInteractions,', 'globalThis.__test = { setupAttachments, media, upload, renderUploads, clearUploads, closeImageLightbox, ');
const fixture = { require, __dirname, console, Event, URL, Headers };
vm.runInNewContext(fixtureSource + '\nglobalThis.fixture = { context, document, elements, Node };', fixture);
const { context, document, elements } = fixture.fixture;
const app = context.__test, data = app.data;
const get = (id) => elements.get(id), xhrs = [], revoked = [], blobs = [];
class LocalURL extends URL {
  static createObjectURL(file) { const url = `blob:http://localhost/${blobs.length}`; blobs.push({ url, file }); return url; }
  static revokeObjectURL(url) { revoked.push(url); }
}
class XHR {
  constructor() { this.upload = {}; this.headers = {}; xhrs.push(this); }
  open(method, url) { this.method = method; this.url = url; }
  setRequestHeader(name, value) { this.headers[name] = value; }
  send(file) { this.file = file; }
  abort() { this.aborted = true; }
  progress(value) { this.upload.onprogress({ lengthComputable: true, loaded: value, total: 100 }); }
  finish(status = 200, result = null) {
    this.status = status;
    this.responseText = JSON.stringify(result || { path: `/private/uploads/${this.file.name}`, name: this.file.name, size: this.file.size,
      kind: /\.(png|jpe?g|gif|webp)$/i.test(this.file.name) ? 'image' : 'file', url: `/api/file?path=${encodeURIComponent('/private/uploads/' + this.file.name)}` });
    this.onload();
  }
}
context.URL = LocalURL; context.XMLHttpRequest = XHR;
context.window.events = {}; context.window.addEventListener = (name, callback) => { context.window.events[name] = callback; };
for (const name of ['alert', 'confirm', 'prompt', 'open']) context[name] = context.window[name] = () => { throw new Error('Native dialog/new tab used'); };
data.authenticated = true; get('app').hidden = false; get('composer').hidden = false;
data.chatId = 'agent:writer'; data.agents = [{ id: 'writer', name: 'Writer' }]; data.chats = [{ id: data.chatId, type: 'direct', agents: ['writer'] }];
data.uploadLimit = 10000;
app.setupAttachments();
const file = (name, type = '', size = 2048) => ({ name, type, size });
const event = (transfer, source = 'clipboardData') => ({ [source]: transfer, prevented: false, preventDefault() { this.prevented = true; } });
const paste = (transfer) => { const e = event(transfer); get('messageInput').events.paste(e); return e; };
const drag = (type, transfer = { types: ['Files'], files: [] }) => { const e = event(transfer, 'dataTransfer'); get('conversation').events[type](e); return e; };
const removeFirst = () => get('uploadTray').children[0].querySelector('button').click();
const clear = () => { app.clearUploads(); app.renderUploads(); };

get('messageInput').value = 'Preserve my text';
assert.equal(paste({ files: [], items: [{ kind: 'string', type: 'text/plain' }] }).prevented, false, 'plain text retains native paste');
assert.equal(get('messageInput').value, 'Preserve my text');
const shot = file('screenshot.png', 'image/png');
const pasted = paste({ files: [shot], items: [{ kind: 'file', getAsFile: () => shot }] });
assert.ok(pasted.prevented); assert.equal(xhrs.length, 1, 'files and items are alternative sources, never duplicate');
assert.equal(xhrs[0].file, shot); assert.equal(xhrs[0].method, 'POST');
assert.equal(xhrs[0].url, '/api/upload?name=screenshot.png');
assert.equal(xhrs[0].headers['X-Hub-Request'], '1');
assert.equal(xhrs[0].headers['Content-Type'], 'application/octet-stream');
let chip = get('uploadTray').children[0];
assert.ok(!get('uploadTray').hidden); assert.equal(chip.querySelector('img').src, blobs[0].url);
assert.ok(chip.findText('screenshot.png') && chip.findText('2.0 KB'));
assert.equal(chip.querySelector('progress').value, 0); assert.ok(get('sendButton').disabled);
xhrs[0].progress(42); chip = get('uploadTray').children[0];
assert.equal(chip.querySelector('progress').value, 42); assert.ok(chip.findText('42%'));
xhrs[0].finish(); chip = get('uploadTray').children[0];
assert.ok(chip.findText('Attached ✓')); assert.equal(chip.querySelector('progress'), null);
assert.match(chip.querySelector('img').src, /^http:\/\/localhost\/api\/file\?/);
assert.deepEqual(revoked, [blobs[0].url]); assert.ok(!get('sendButton').disabled);
removeFirst(); assert.ok(xhrs[0].aborted && get('uploadTray').hidden);
// Clipboard items fallback (screenshot-only clipboards need not expose files).
assert.ok(paste({ items: [{ kind: 'file', getAsFile: () => file('clipboard.jpg', 'image/jpeg') }] }).prevented);
const inFlight = xhrs.at(-1), temporary = blobs.at(-1).url;
removeFirst(); assert.ok(inFlight.aborted && revoked.includes(temporary));
inFlight.finish(); inFlight.progress(100); assert.equal(data.uploads.length, 0, 'late upload callbacks cannot resurrect removed chips');

assert.ok(drag('dragenter').prevented && !get('dropOverlay').hidden);
drag('dragenter'); drag('dragleave'); assert.ok(!get('dropOverlay').hidden, 'nested enters do not flicker on child leave');
drag('dragleave'); assert.ok(get('dropOverlay').hidden);
const over = drag('dragover'); assert.ok(over.prevented); assert.equal(over.dataTransfer.dropEffect, 'copy');
const dropFiles = [file('one.png', 'image/png'), file('notes.pdf', 'application/pdf'), file('readme.txt', 'text/plain'), file('two.webp', 'image/webp')];
assert.ok(drag('drop', { types: ['Files'], files: dropFiles }).prevented);
assert.ok(get('dropOverlay').hidden); assert.equal(data.uploads.length, 4, 'multiple drop files share upload path');
assert.equal(get('uploadTray').querySelectorAll('img').length, 2);
for (const request of xhrs.slice(-4)) request.finish();
assert.ok(get('uploadTray').findText('notes.pdf') && get('uploadTray').findText('readme.txt'), 'dropped PDF and text each have a file card');
const htmlName = '<img onerror=bad>.txt'; app.upload(file(htmlName, 'text/plain', 5));
assert.ok(get('uploadTray').findText(htmlName), 'filenames use textContent');
assert.match(xhrs.at(-1).url, /%3Cimg%20onerror%3Dbad%3E.txt/);
clear();
const count = xhrs.length;
app.upload(file('huge.png', 'image/png', 10001)); assert.equal(xhrs.length, count); assert.ok(get('toast').findText('upload limit'));
app.upload(file('empty.txt', 'text/plain', 0)); assert.equal(xhrs.length, count); assert.ok(get('toast').findText('empty'));
for (let i = 0; i < 11; i++) app.upload(file(`file-${i}.txt`, 'text/plain', 10));
assert.equal(data.uploads.length, 10); assert.ok(get('toast').findText('10 files'));
clear();
for (const active of [file('evil.svg', 'image/svg+xml'), file('evil.html', 'text/html'), file('spoof.png', 'image/svg+xml')]) {
  app.upload(active); assert.equal(get('uploadTray').children.at(-1).querySelector('img'), null, 'active types never get blob previews');
}
clear();
app.upload(shot); xhrs.at(-1).finish(413, { error: 'Storage limit reached. Remove unused uploads.' });
assert.ok(get('uploadTray').findText('Failed')); assert.ok(get('toast').findText('Storage limit reached')); removeFirst();
app.upload(shot); xhrs.at(-1).onerror(); assert.ok(get('uploadTray').findText('Failed')); removeFirst();
// Phone picker directly opens from +; desktop preserves the menu.
context.matchMedia = (query) => ({ matches: query === '(max-width: 700px)' });
get('fileInput').clicked = false; get('fileInput').events.click = () => { get('fileInput').clicked = true; };
get('attachButton').click(); assert.ok(get('fileInput').clicked);
get('fileInput').files = [shot, file('notes.txt')]; get('fileInput').value = 'files'; get('fileInput').events.change();
assert.equal(data.uploads.length, 2); assert.equal(get('fileInput').value, '', 'same file can be selected again'); clear();
context.matchMedia = () => ({ matches: false }); get('fileInput').clicked = false;
get('attachButton').click(); assert.equal(get('fileInput').clicked, false); assert.ok(!get('attachMenu').hidden);
get('anyFileInput').clicked = false; get('anyFileInput').events.click = () => { get('anyFileInput').clicked = true; };
get('attachFileButton').click(); assert.ok(get('anyFileInput').clicked && get('attachMenu').hidden);
get('anyFileInput').files = [file('unfiltered.bin')]; get('anyFileInput').events.change(); assert.equal(data.uploads[0].file.name, 'unfiltered.bin'); clear();

const image = { kind: 'image', name: 'screenshot.png', size: 2048, url: '/api/file?path=private.png' };
const imageNode = app.media(image); assert.equal(imageNode.querySelector('a'), null);
imageNode.querySelector('button').click(); assert.ok(get('imageLightbox').open);
assert.equal(get('lightboxImage').src, 'http://localhost/api/file?path=private.png');
assert.equal(get('lightboxName').textContent, 'screenshot.png');
get('imageLightbox').events.click({ target: get('lightboxImage') }); assert.ok(get('imageLightbox').open);
get('lightboxClose').click(); assert.ok(!get('imageLightbox').open); assert.equal(get('lightboxImage').src, undefined);
imageNode.querySelector('button').click(); get('imageLightbox').events.click({ target: get('imageLightbox') }); assert.ok(!get('imageLightbox').open);
imageNode.querySelector('button').click(); get('imageLightbox').close(); get('imageLightbox').events.close();
assert.equal(get('lightboxImage').src, undefined, 'Escape/native close event releases private source');
assert.equal(app.media({ ...image, url: 'https://other.example/private.png' }), null);
assert.equal(app.media({ ...image, url: '/static/example.png' }), null, 'attachments use only authenticated file route');
const doc = app.media({ kind: 'file', name: 'notes.pdf', size: 2048, url: '/api/file?path=notes.pdf' });
assert.ok(doc.findText('notes.pdf') && doc.findText('2.0 KB')); assert.equal(doc.querySelector('img'), null); assert.equal(doc.querySelector('a').download, 'notes.pdf');
const textDoc = app.media({ kind: 'file', name: 'readme.txt', size: 12, url: '/api/file?path=readme.txt' });
assert.ok(textDoc.findText('readme.txt') && textDoc.querySelector('a').download === 'readme.txt');
const sent = app.messageNode({ id: 21, role: 'user', text: '', attachments: [image, image, { kind: 'file', name: 'notes.pdf', url: '/api/file?path=notes.pdf' }, { kind: 'file', name: 'readme.txt', url: '/api/file?path=readme.txt' }] });
assert.equal(sent.querySelector('.attachment-list').querySelectorAll('img').length, 2); assert.ok(sent.findText('notes.pdf') && sent.findText('readme.txt'));
(async () => {
// File-only send keeps previews in the immediate bubble and posts only uploaded paths.
app.upload(file('notes.pdf', 'application/pdf')); app.upload(file('readme.txt', 'text/plain'));
const requests = xhrs.slice(-2); requests.forEach((request) => request.finish());
const attachments = data.uploads.map((entry) => entry.result); let posted;
context.fetch = async (url, options = {}) => {
  if (url === '/api/message') { posted = JSON.parse(options.body); return { ok: true, status: 200, json: async () => ({ message_id: 55, job_id: 56 }) }; }
  return { ok: true, status: 200, json: async () => ({ messages: [{ id: 55, role: 'user', text: '', request_id: posted?.request_id, attachments }] }) };
};
get('messageInput').value = '';
const sending = app.sendMessage({ preventDefault() {} });
assert.equal(data.uploads.length, 0); assert.ok(get('uploadTray').hidden);
const pendingBubble = get('messageList').querySelector('.user');
assert.equal(pendingBubble.querySelectorAll('img').length, 0); assert.ok(pendingBubble.findText('notes.pdf') && pendingBubble.findText('readme.txt'));
await sending;
assert.deepEqual(Array.from(posted.uploads), Array.from(attachments, (attachment) => attachment.path));
assert.equal(posted.text, ''); assert.equal(get('messageList').querySelector('.user'), pendingBubble);
assert.equal(pendingBubble.querySelectorAll('img').length, 0);
// Window exit, outside drops, and sign-out clear visible/private attachment state.
drag('dragenter'); context.window.events.blur(); assert.ok(get('dropOverlay').hidden);
const outside = event({ types: ['Files'] }, 'dataTransfer'); document.events.drop(outside); assert.ok(outside.prevented);
const textDrag = drag('dragenter', { types: ['text/plain'] }); assert.equal(textDrag.prevented, false); assert.ok(get('dropOverlay').hidden);
app.upload(shot); const privateXHR = xhrs.at(-1), privateBlob = blobs.at(-1).url;
imageNode.querySelector('button').click(); drag('dragenter'); app.showLogin();
assert.equal(data.uploads.length, 0); assert.ok(privateXHR.aborted && revoked.includes(privateBlob));
assert.ok(get('dropOverlay').hidden && !get('imageLightbox').open); assert.equal(get('lightboxImage').src, undefined);
assert.equal(paste({ files: [shot] }).prevented, false); assert.equal(data.uploads.length, 0);
console.log('Attachment paste/drop/preview/lightbox smoke checks passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
