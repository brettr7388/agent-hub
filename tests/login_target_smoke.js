// SEC-02: execute the atomic verified-node fill operation with hostile focus.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../hub_cdp.py'), 'utf8');
const declaration = source.match(/SET_LOGIN_FIELD = r"""([\s\S]*?)"""/)[1];
function fixture() {
  const document = {location: {href: 'https://example.com/login'}, activeElement: {crossOriginIframe:true}};
  const window = {}; window.top = window;
  const calls = [];
  function HTMLInputElement() {}
  Object.defineProperty(HTMLInputElement.prototype, 'value', {set(value) { calls.push([this, value]); }});
  const fill = vm.runInNewContext('(' + declaration + ')', {window, document, HTMLInputElement, Event: class Event {constructor(type) {this.type = type;}}});
  const node = {ownerDocument: document, isConnected: true, tagName: 'INPUT', type: 'password', disabled: false, readOnly: false,
    dispatchEvent(event) {document.activeElement = {crossOriginIframe:true};}};
  return {document, window, calls, fill, node};
}
const good = fixture();
assert.equal(good.fill.call(good.node, 'secret', good.document.location.href, true), true);
assert.equal(good.calls[0][0], good.node, 'focus cannot redirect the native setter');
assert.equal(good.calls[0][1], 'secret');
for (const change of [
  f => {f.node.ownerDocument = {};},
  f => {f.node.isConnected = false;},
  f => {f.document.location.href = 'https://evil.com/';},
  f => {f.window.top = {};},
  f => {f.node.type = 'text';},
  f => {f.node.readOnly = true;},
]) {
  const f = fixture(); change(f);
  assert.equal(f.fill.call(f.node, 'secret', 'https://example.com/login', true), false);
  assert.equal(f.calls.length, 0, 'invalid field/document must not receive any value');
}
console.log('Targeted login fill smoke passed');
