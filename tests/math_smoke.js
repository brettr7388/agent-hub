/* Safe rendering of the supported LaTeX subset. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
class Node {
  constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; this._text = ''; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(n => n.textContent).join(''); }
  get childNodes() { return this.children; }
  append(...nodes) { for (const n of nodes) this.children.push(...(n.tagName === 'fragment' ? n.children : [n])); }
  setAttribute(key, value) { this.attributes[key] = String(value); }
}
const context = { window: {}, document: {
  createElement: tag => new Node(tag),
  createElementNS: (ns, tag) => { const n = new Node(tag); n.namespaceURI = ns; return n; },
  createDocumentFragment: () => new Node('fragment'),
}, URL };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/markdown.js'), 'utf8'), context);
const render = context.window.HubMarkdown.render;
const walk = n => [n, ...n.children.flatMap(walk)];
const formula = 'x=\\frac{-b\\pm\\sqrt{b^2-4ac}}{2a}';
for (const result of [render('$' + formula + '$'), render('$$' + formula + '$$')]) {
  const math = walk(result).find(n => n.tagName === 'math');
  assert.ok(math, 'quadratic formula renders as MathML');
  assert.equal(math.namespaceURI, 'http://www.w3.org/1998/Math/MathML');
  assert.equal(math.attributes.display, result.children[0] === math && result.children[0].tagName === 'math' ? 'block' : 'inline');
  assert.ok(walk(math).some(n => n.tagName === 'mfrac'), 'fraction is represented with mfrac');
  assert.ok(walk(math).some(n => n.tagName === 'msqrt'), 'radical is represented with msqrt');
  assert.ok(walk(math).some(n => n.tagName === 'msup'), 'nested exponent is represented with msup');
  assert.ok(walk(math).some(n => n.tagName === 'mo' && n.textContent === '±'));
  assert.equal(walk(math).some(n => ['script', 'img'].includes(n.tagName)), false);
}
const nested = render('$\\frac{a}{\\sqrt{b^{2}}}$');
assert.ok(walk(nested).some(n => n.tagName === 'msqrt'), 'nested braces work in fraction and radical arguments');
for (const source of ['$\\frac{a}{b}$', '$$\\frac{1}{2}$$', '$$\\sqrt{9}$$']) {
  assert.ok(walk(render(source)).some(n => n.tagName === 'math'), 'fractions and radicals render independently');
}
for (const latex of ['\\unknown{x}', '\\frac{a}', '\\frac{a}{b', 'x^{2']) {
  const rendered = render('$' + latex + '$');
  assert.equal(walk(rendered).some(n => n.tagName === 'math'), false, latex + ' falls back to text');
  assert.equal(rendered.textContent, '$' + latex + '$');
}
console.log('Math rendering smoke checks passed');
