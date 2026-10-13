/* PASS 10 P1-1/P1-2/P2-stream: also run by ui_smoke.js. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Node {
  constructor(tag) { this.tagName = tag; this.children = []; this._text = ''; this.attributes = {}; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(n => n.textContent).join(''); }
  get childNodes() { return this.children; }
  append(...nodes) { for (const n of nodes) this.children.push(...(n.tagName === 'fragment' ? n.children : [n])); }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener() {}
}
const context = { window: {}, document: {createElement: tag => new Node(tag), createDocumentFragment: () => new Node('fragment')}, URL };
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname, '../static/markdown.js'), 'utf8'), context);
const render = context.window.HubMarkdown.render;
const walk = n => [n, ...n.children.flatMap(walk)];
const list = render('1. a\n\n2. b\n\n3. c');
assert.equal(list.children.length, 1);
assert.equal(list.children[0].tagName, 'ol');
assert.equal(list.children[0].start, 1);
assert.equal(list.children[0].children.length, 3);
assert.equal(render('7. first\n\n8. second').children[0].start, 7);
assert.equal(render('1. first\n\nA paragraph\n\n2. second').children.length, 3);
for (const text of ['my_file_name_here', 'test_hub_runner.py', 'MAX_RETRY_COUNT', '__init__', '2 * 3 * 4', 'foo__bar__baz', 'é_file_name', 'name_', '_name', '__init']) {
  for (const streaming of [false, true]) {
    const out = render(text, {streaming});
    assert.equal(out.textContent, text, `${text} streaming=${streaming}`);
    assert.equal(walk(out).filter(n => ['strong', 'em'].includes(n.tagName)).length, 0);
  }
}
assert.equal(walk(render('foo*bar*baz')).find(n => n.tagName === 'em').textContent, 'bar');
assert.equal(walk(render('_word_')).find(n => n.tagName === 'em').textContent, 'word');
assert.equal(walk(render('__two words__')).find(n => n.tagName === 'strong').textContent, 'two words');
assert.equal(render('[link](https://exampl', {streaming:true}).textContent, 'link');
assert.equal(render('[link](https://exampl').textContent, '[link](https://exampl');
assert.equal(walk(render('[link](https://example.com)')).find(n => n.tagName === 'a').href, 'https://example.com/');
assert.equal(render('Thinking **bold', {streaming:true}).textContent, 'Thinking bold');
const table = render('| Item | Check | Code |\n|:---|---:|:---:|\n| **Eggs** | yes | `a|b` |\n| A\\|B | <img src=x onerror=alert(1)> | done |');
const tableNodes = walk(table);
const wrapper = tableNodes.find(n => n.className === 'markdown-table-scroll');
assert.ok(wrapper, 'table is inside the mobile scroll wrapper');
const htmlTable = walk(wrapper).find(n => n.tagName === 'table');
assert.ok(htmlTable);
assert.equal(walk(htmlTable).filter(n => n.tagName === 'tr').length, 3);
assert.equal(walk(htmlTable).filter(n => n.tagName === 'th').length, 3);
assert.equal(walk(htmlTable).filter(n => n.tagName === 'td').length, 6);
assert.deepEqual(walk(htmlTable).filter(n => n.tagName === 'th').map(n => n.attributes.align), ['left', 'right', 'center']);
assert.ok(walk(htmlTable).some(n => n.tagName === 'code' && n.textContent === 'a|b'), 'pipes inside code spans do not split cells');
assert.ok(walk(htmlTable).some(n => n.textContent === 'A|B'), 'escaped pipes become literal cell content');
assert.equal(walk(htmlTable).some(n => n.tagName === 'img'), false, 'untrusted HTML stays text');
assert.ok(htmlTable.textContent.includes('<img src=x onerror=alert(1)>'));
const adjacent = render('Intro paragraph\n| A | B |\n| --- | --- |\n| 1 | 2 |');
assert.deepEqual(adjacent.children.map(n => n.tagName), ['p', 'div'], 'table starts a block without needing a blank line');
assert.equal(walk(adjacent).filter(n => n.tagName === 'table').length, 1);
const codeTable = render('```md\n| A | B |\n| --- | --- |\n```');
assert.equal(walk(codeTable).filter(n => n.tagName === 'table').length, 0, 'pipe lines in fenced code stay code');
assert.equal(walk(codeTable).find(n => n.tagName === 'code').textContent, '| A | B |\n| --- | --- |');
const quoteTable = render('> | A | B |\n> | --- | --- |');
assert.equal(walk(quoteTable).filter(n => n.tagName === 'table').length, 0, 'quoted pipe lines stay in the quote');
console.log('Markdown PASS 10 smoke checks passed');
// PASS 16: every streaming prefix must hide incomplete strong delimiters.
for (const text of ["**You'll need:**", '**Steps:**', 'Intro **bold words** done']) {
  for (let end = 1; end <= text.length; end++) {
    assert.ok(!render(text.slice(0, end), {streaming:true}).textContent.includes('*'), `no star artifacts at ${text.slice(0, end)}`);
  }
  assert.ok(walk(render(text, {streaming:true})).some(n => n.tagName === 'strong'), 'completed streaming bold renders as bold');
}
assert.equal(walk(render('`a ** b`', {streaming:true})).find(n => n.tagName === 'code')?.textContent, 'a ** b');
