/* Run with: node tests/access_smoke.js */
'use strict';
const assert = require('node:assert/strict');
const Access = require('../static/access.js');
const request = { action: 'approval_request', summary: 'Send DM to @name on Instagram', details: '<b>Exact text</b>\nSecond line' };
assert.equal(Access.answer(request, true), 'Yes, approved: Send DM to @name on Instagram — exactly as shown.');
assert.equal(Access.answer(request, false), "No, don't do that.");
assert.deepEqual(Access.mode({}), ['Full access']);
assert.deepEqual(Access.mode({ private_pip: true }), ['Private']);
assert.deepEqual(Access.mode({ draft_only: true }), ['Draft only']);
assert.deepEqual(Access.mode({ private_pip: true, draft_only: true }), ['Private', 'Draft only']);

class Node {
  constructor(tag) { this.tagName = tag; this.className = ''; this.children = []; this.events = {}; this.dataset = {}; this.disabled = false; this._text = ''; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(''); }
  append(...children) { this.children.push(...children); }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, callback) { this.events[name] = callback; }
  querySelectorAll(tag) { return this.children.flatMap((child) => [child, ...child.querySelectorAll(tag)]).filter((child) => child.tagName === tag); }
}
global.document = { createElement: (tag) => new Node(tag) };
let calls = [];
const card = Access.card(request, null, async (_approval, approved) => { calls.push(approved); });
assert.equal(card.querySelectorAll('pre')[0].textContent, '<b>Exact text</b>\nSecond line', 'details remain literal text');
assert.deepEqual(card.querySelectorAll('button').map((button) => button.textContent), ['Approve', "Don't"]);
const approve = card.querySelectorAll('button')[0];
approve.events.click(); approve.events.click();
assert.deepEqual(calls, [true], 'duplicate click is ignored while decision is pending');
assert.ok(card.querySelectorAll('button').every((button) => button.disabled));
const answered = Access.card(request, 'approved', () => { throw Error('answered'); });
assert.equal(answered.querySelectorAll('button').length, 0);
assert.ok(answered.textContent.includes('Approved'));
const denied = Access.card(request, 'denied', () => { throw Error('answered'); });
assert.ok(denied.textContent.includes('Declined'));
console.log('access smoke passed');
