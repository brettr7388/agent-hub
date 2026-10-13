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
  addEventListener(name, fn) { this.listeners ||= {}; this.listeners[name] = fn; }
}
let copied = '';
const mathNS = 'http://www.w3.org/1998/Math/MathML';
const context = { window: {}, navigator: {clipboard:{writeText: async text => { copied = text; }}}, document: {createElement: tag => new Node(tag), createElementNS: (ns, tag) => { const n = new Node(tag); n.namespaceURI = ns; return n; }, createDocumentFragment: () => new Node('fragment')}, URL };
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
console.log('Markdown smoke checks passed');
// PASS 16: every streaming prefix must hide incomplete strong delimiters.
for (const text of ["**You'll need:**", '**Steps:**', 'Intro **bold words** done']) {
  for (let end = 1; end <= text.length; end++) {
    assert.ok(!render(text.slice(0, end), {streaming:true}).textContent.includes('*'), `no star artifacts at ${text.slice(0, end)}`);
  }
  assert.ok(walk(render(text, {streaming:true})).some(n => n.tagName === 'strong'), 'completed streaming bold renders as bold');
}
assert.equal(walk(render('`a ** b`', {streaming:true})).find(n => n.tagName === 'code')?.textContent, 'a ** b');

(async () => {
// Fenced code is safely highlighted and clipboard text remains raw.
const rawCode = 'const x = "<img src=x onerror=alert(1)>";\nreturn x;';
const highlighted = render('```js\n' + rawCode + '\n```');
const codeBlock = walk(highlighted).find(n => n.className === 'code-block');
assert.equal(codeBlock.attributes['data-language'], 'js');
assert.equal(walk(codeBlock).find(n => n.tagName === 'code').textContent, rawCode);
assert.ok(walk(codeBlock).some(n => n.className === 'syntax-keyword' && n.textContent === 'const'));
assert.ok(walk(codeBlock).some(n => n.className === 'syntax-string' && n.textContent.includes('<img')));
assert.equal(walk(codeBlock).some(n => n.tagName === 'img'), false, 'highlighted code cannot create HTML elements');
const copyButton = walk(codeBlock).find(n => n.className === 'code-copy');
await copyButton.listeners.click();
assert.equal(copied, rawCode, 'copy keeps the original code, including newlines');
const unknownCode = walk(render('```mystery\n<x>\n```')).find(n => n.tagName === 'code');
assert.equal(unknownCode.textContent, '<x>');
assert.equal(walk(unknownCode).some(n => n.className?.startsWith('syntax-')), false, 'unknown language remains plain text');
for (const [hint, snippet, expected] of [['python','def f():\n  return 2','keyword'],['json','{"key":true}','property'],['html','<b>text</b>','punct'],['css','a { color: red }','punct'],['bash','echo "ok" # hi','comment'],['sql','SELECT 1 FROM t','keyword'],['ts','const x: number = 1','keyword']]) {
  const result = render('```' + hint + '\n' + snippet + '\n```');
  assert.ok(walk(result).some(n => n.className === 'syntax-' + expected), hint + ' highlighting');
  assert.equal(walk(result).some(n => n.tagName === 'script' || n.tagName === 'img'), false, hint + ' output is safe');
}

// Inline/block math, currency, unsupported LaTeX, and incomplete stream safety.
const inlineMath = render('Area $x^2 + y_1$ costs $5.00.');
assert.ok(walk(inlineMath).some(n => n.tagName === 'math' && n.attributes.display === 'inline'));
const mathRoot = walk(inlineMath).find(n => n.tagName === 'math');
assert.equal(mathRoot.namespaceURI, mathNS, 'MathML uses the MathML namespace');
const power = walk(mathRoot).find(n => n.tagName === 'msup');
assert.deepEqual(power.children.map(n => n.textContent), ['x', '2'], 'the exponent ends before the following operator/term');
assert.ok(walk(mathRoot).some(n => n.tagName === 'mo' && n.textContent === '+'));
assert.ok(inlineMath.textContent.includes('$5.00.'), 'currency-like text stays literal');
const blockMath = render('$$\nx^2 = \\alpha\n$$');
assert.ok(walk(blockMath).some(n => n.tagName === 'math' && n.attributes.display === 'block'));
assert.ok(walk(render('$$x=1$$')).some(n => n.tagName === 'math' && n.attributes.display === 'block'), 'same-line dollar fences render as a block');
assert.ok(walk(render('$\\frac{a}{b}$')).some(n => n.tagName === 'mfrac'), 'simple fractions render as MathML');
assert.ok(render('$\\unknown{a}{b}$').textContent.includes('\\unknown{a}{b}'), 'unsupported LaTeX is readable as plain text');
for (const prefix of ['$', '$x', '$x^', '$$\nx^2']) {
  const partial = render(prefix, {streaming:true});
  assert.ok(!walk(partial).some(n => n.tagName === 'math'), 'incomplete math is never partially interpreted');
  assert.ok(partial.textContent.length >= 0);
}
assert.equal(render('Price is $5.00 today.').textContent, 'Price is $5.00 today.');
console.log('Formatting smoke checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
