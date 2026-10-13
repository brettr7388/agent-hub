/* A deliberately small, DOM-only markdown renderer for untrusted agent output. */
(() => {
  'use strict';
  const node = (tag, value) => { const n = document.createElement(tag); if (value != null) n.textContent = value; return n; };
  const token = (kind, value) => { const n = node('span', value); n.className = 'syntax-' + kind; return n; };
  function highlighted(code, language) {
    const lang = String(language || '').toLowerCase().replace(/^\{\.([\w+-]+)\}$/, '$1');
    const aliases = { js:'javascript', jsx:'javascript', ts:'typescript', tsx:'typescript', py:'python', jsonc:'json', sh:'bash', zsh:'bash', yml:'yaml', html:'html', xml:'html', css:'css', sql:'sql' };
    const known = new Set(['javascript','typescript','python','json','html','css','bash','shell','yaml','sql']);
    const languageName = aliases[lang] || lang;
    if (!known.has(languageName)) return node('span', code);
    const fragment = document.createDocumentFragment();
    // Tokenize with one pass. Everything is emitted as text nodes inside spans.
    const pattern = languageName === 'json' ? /(\"(?:\\.|[^\"\\])*\"(?=\s*:)|\"(?:\\.|[^\"\\])*\"|\b(?:true|false|null)\b|-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)/gy :
      /(\/\/[^\n]*|#[^\n]*|\/\*[\s\S]*?\*\/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\b(?:const|let|var|function|return|if|else|for|while|class|new|import|from|export|async|await|def|print|True|False|None|and|or|not|in|is|pass|try|except|with|as|lambda|SELECT|FROM|WHERE|INSERT|UPDATE|DELETE|JOIN|CREATE|TABLE|AND|OR|NOT|NULL|PRIMARY|KEY|int|float|str|bool)\b|\b\d+(?:\.\d+)?\b|[{}()[\].,:;=+*/<>!-])/gy;
    let i = 0, m, plain = '';
    const flush = () => { if (plain) { fragment.append(node('span', plain)); plain = ''; } };
    while (i < code.length) {
      pattern.lastIndex = i; m = pattern.exec(code);
      if (!m || m.index !== i) { plain += code[i++]; continue; }
      flush();
      const s = m[0]; let kind = 'punct';
      if (languageName === 'json') kind = s[0] === '"' ? (code.slice(pattern.lastIndex).match(/^\s*:/) ? 'property' : 'string') : /^-?\d/.test(s) ? 'number' : 'literal';
      else if (/^(\/\/|#|\/\*)/.test(s)) kind = 'comment';
      else if (/^["'`]/.test(s)) kind = 'string';
      else if (/^\d/.test(s)) kind = 'number';
      else if (/^(SELECT|FROM|WHERE|INSERT|UPDATE|DELETE|JOIN|CREATE|TABLE|AND|OR|NOT|NULL|PRIMARY|KEY)$/i.test(s) && ['sql'].includes(languageName)) kind = 'keyword';
      else if (/^(const|let|var|function|return|if|else|for|while|class|new|import|from|export|async|await|def|print|True|False|None|and|or|not|in|is|pass|try|except|with|as|lambda)$/.test(s)) kind = 'keyword';
      else if (languageName === 'css' && /^[{}:;,.#]/.test(s)) kind = 'punct';
      fragment.append(token(kind, s)); i = pattern.lastIndex;
    }
    flush();
    return fragment;
  }
  function mathNode(source, block) {
    // Deliberately small safe MathML subset. Unsupported LaTeX stays readable as text.
    const simple = source.trim();
    const fallback = () => node('span', block ? '$$' + source + '$$' : '$' + source + '$');
    if (!simple) return fallback();
    const createMath = (tag, value) => { const n = document.createElementNS ? document.createElementNS('http://www.w3.org/1998/Math/MathML', tag) : node(tag); if (value != null) n.textContent = value; return n; };
    const math = createMath('math'); math.setAttribute('display', block ? 'block' : 'inline');
    const commands = { alpha:['mi','α'], beta:['mi','β'], gamma:['mi','γ'], delta:['mi','δ'], pi:['mi','π'], theta:['mi','θ'], lambda:['mi','λ'], mu:['mi','μ'], sigma:['mi','σ'], infinity:['mo','∞'], times:['mo','×'], cdot:['mo','·'], le:['mo','≤'], ge:['mo','≥'], neq:['mo','≠'], pm:['mo','±'] };
    const parts = simple.match(/\\[a-zA-Z]+|[{}_^]|[A-Za-z]+|\d+(?:\.\d+)?|[=+\-*/<>]|\s+|./g) || [];
    const tokens = parts.filter(p => !/^\s+$/.test(p)); let i = 0;
    const element = (tag, ...children) => { const n = createMath(tag); n.append(...children); return n; };
    const atom = () => {
      const t = tokens[i++];
      if (t == null) throw Error('missing atom');
      if (t === '{') { const group = sequence(true); if (tokens[i++] !== '}') throw Error('unclosed group'); return group; }
      if (t === '}') throw Error('unexpected group end');
      if (t[0] === '\\') {
        const name = t.slice(1);
        if (name === 'frac') return element('mfrac', atom(), atom());
        if (name === 'sqrt') return element('msqrt', atom());
        const entry = commands[name]; if (!entry) throw Error('unsupported command');
        const n = createMath(entry[0]); n.textContent = entry[1]; return n;
      }
      const kind = /^[=+\-*/<>]$/.test(t) ? 'mo' : /^\d/.test(t) ? 'mn' : /^[A-Za-z]+$/.test(t) ? 'mi' : null;
      if (!kind) throw Error('unsupported token');
      const n = createMath(kind); n.textContent = t; return n;
    };
    const sequence = grouped => {
      const items = [];
      while (i < tokens.length && tokens[i] !== '}') {
        let base = atom(), sup = null, sub = null;
        while (tokens[i] === '^' || tokens[i] === '_') {
          const op = tokens[i++], value = atom();
          if (op === '^') { if (sup) throw Error('duplicate script'); sup = value; }
          else { if (sub) throw Error('duplicate script'); sub = value; }
        }
        if (sup && sub) base = element('msubsup', base, sub, sup);
        else if (sup) base = element('msup', base, sup);
        else if (sub) base = element('msub', base, sub);
        items.push(base);
      }
      if (grouped && !items.length) throw Error('empty group');
      return element('mrow', ...items);
    };
    try { const row = sequence(false); if (i !== tokens.length) throw Error('trailing token'); math.append(row); return math; }
    catch { return fallback(); }
  }
  const safeLink = (value) => {
    try { const url = new URL(value); return ['http:', 'https:', 'mailto:'].includes(url.protocol) ? url.href : null; }
    catch { return null; }
  };
  function stripIncomplete(value) {
    // Show the label while a link destination is arriving, never a half URL.
    value = value.replace(/\[([^\]\n]+)\]\([^\)\n]*$/, '$1');
    // An unfinished underscore can be an identifier, so preserve it until a
    // complete emphasis pair arrives. Stars/backticks have no such ambiguity.
    const markers = /(`+|\*+)/gu, stack = []; let match;
    while ((match = markers.exec(value))) {
      // Consume whole runs: a closing ** must not split into two single stars.
      if (match[0][0] === '*' && (stack.at(-1)?.marker[0] === '`' || (/\s/.test(value[match.index - 1] || '') && /\s/.test(value[markers.lastIndex] || '')))) continue;
      const last = stack.at(-1); if (last && last.marker === match[0]) stack.pop(); else stack.push({ marker: match[0], index: match.index }); }
    let clean = value; for (const item of stack.reverse()) clean = clean.slice(0, item.index) + clean.slice(item.index + item.marker.length);
    return clean;
  }
  function inline(text, streaming = false) {
    const out = document.createDocumentFragment();
    const source = streaming ? stripIncomplete(String(text || '')) : String(text || '');
    const marker = /(\[([^\]\n]+)\]\(([^)\s]+)\)|\$([^$\n]+)\$|\*\*(\S(?:[^*\n]*?\S)?)\*\*|(?<![\p{L}\p{N}_])__(\S(?:[^_\n]*?\S)?)__(?![\p{L}\p{N}_])|(?<!\*)\*(\S(?:[^*\n]*?\S)?)\*(?!\*)|(?<![\p{L}\p{N}_])_(\S(?:[^_\n]*?\S)?)_(?![\p{L}\p{N}_])|(`+)([^`\n]*?)\9)/gu;
    let last = 0, found;
    while ((found = marker.exec(source))) {
      if (found.index > last) out.append(node('span', source.slice(last, found.index)));
      if (found[2] != null) {
        const href = safeLink(found[3]);
        if (href) { const a = node('a', found[2]); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; out.append(a); }
        else out.append(node('span', found[0]));
      } else if (found[4] != null) {
        const expression = found[4];
        // Require a math signal so ordinary prices such as $5.00 remain literal.
        if (expression !== expression.trim() || !/[\\^_={}+*/<>]|\b(?:alpha|beta|gamma|pi|sqrt)\b/.test(expression)) out.append(node('span', found[0]));
        else out.append(mathNode(expression, false));
      } else if (found[6] != null && /^__[a-z][a-z0-9_]*__$/.test(found[0])) {
        // Single-word Python dunder names are common in a coding chat.
        out.append(node('span', found[0]));
      } else if (found[5] != null || found[6] != null) { const strong = node('strong'); strong.append(inline(found[5] ?? found[6], streaming)); out.append(strong); }
      else if (found[7] != null || found[8] != null) { const em = node('em'); em.append(inline(found[7] ?? found[8], streaming)); out.append(em); }
      else out.append(node('code', found[10]));
      last = marker.lastIndex;
    }
    if (last < source.length) out.append(node('span', source.slice(last)));
    return out;
  }
  function tableCells(line) {
    const cells = []; let cell = '', ticks = 0, escaped = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '`' && !escaped) {
        let end = i + 1; while (line[end] === '`') end++;
        const run = end - i;
        if (!ticks) ticks = run; else if (ticks === run) ticks = 0;
        cell += line.slice(i, end); i = end - 1; escaped = false; continue;
      }
      if (ch === '|' && !ticks && !escaped) { cells.push(cell.trim()); cell = ''; escaped = false; continue; }
      if (ch === '|' && !ticks && escaped) { cell = cell.slice(0, -1) + '|'; escaped = false; continue; }
      cell += ch;
      if (ch === '\\' && !escaped) escaped = true; else escaped = false;
    }
    cells.push(cell.trim());
    if (/^\s*\|/.test(line)) cells.shift();
    if (/\|\s*$/.test(line) && !/\\\|\s*$/.test(line)) cells.pop();
    return cells;
  }
  const tableRule = cell => /^:?-{3,}:?$/.test(cell.trim());
  const isTableStart = (lines, index) => {
    const header = lines[index] || '';
    if (!header.includes('|') || /^\s{0,3}(?:>|`{3,}|~{3,})/.test(header)) return false;
    const columns = tableCells(header);
    return index + 1 < lines.length && tableCells(lines[index + 1]).length === columns.length && tableCells(lines[index + 1]).every(tableRule);
  };
  function render(value, options = {}) {
    const streaming = !!options.streaming;
    const root = node('div'); root.className = 'markdown';
    const lines = String(value || '').replace(/\r\n?/g, '\n').split('\n');
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      const singleMathBlock = line.match(/^\s*\$\$(.+)\$\$\s*$/);
      if (singleMathBlock) { root.append(mathNode(singleMathBlock[1], true)); i++; continue; }
      if (/^\s*\$\$\s*$/.test(line)) {
        const body = []; i++;
        while (i < lines.length && !/^\s*\$\$\s*$/.test(lines[i])) body.push(lines[i++]);
        const closed = i < lines.length; if (closed) i++;
        const expression = body.join('\n');
        if (streaming && !closed) root.append(node('span', '$$' + (expression ? '\n' + expression : '')));
        else root.append(mathNode(expression, true));
        continue;
      }
      const fence = line.match(/^\s*(`{3,}|~{3,})([^`]*)$/);
      if (fence) {
        const start = i++, body = [];
        while (i < lines.length && !new RegExp('^\\s*' + fence[1][0] + '{' + fence[1].length + ',}\\s*$').test(lines[i])) body.push(lines[i++]);
        if (i < lines.length) i++;
        // While streaming, an open fence is still shown as code without raw markers.
        const wrap = node('div'); wrap.className = 'code-block';
        const language = (fence[2] || '').trim().split(/[\s{]/)[0].toLowerCase(); if (language) wrap.setAttribute('data-language', language);
        const copy = node('button', 'Copy'); copy.type = 'button'; copy.className = 'code-copy';
        copy.addEventListener('click', () => { if (navigator.clipboard?.writeText) navigator.clipboard.writeText(body.join('\n')).then(() => { copy.textContent = 'Copied'; }).catch(() => {}); });
        const pre = node('pre'), code = node('code');
        code.append(highlighted(body.join('\n'), language));
        pre.append(code); wrap.append(copy, pre); root.append(wrap);
        continue;
      }
      if (isTableStart(lines, i)) {
        const headers = tableCells(line), rules = tableCells(lines[i + 1]); i += 2;
        const wrap = node('div'); wrap.className = 'markdown-table-scroll';
        const table = node('table'), thead = node('thead'), headRow = node('tr');
        const align = rules.map(cell => cell.startsWith(':') && cell.endsWith(':') ? 'center' : cell.endsWith(':') ? 'right' : cell.startsWith(':') ? 'left' : '');
        const addCell = (row, tag, text, index) => { const c = node(tag); c.append(inline(text, streaming)); if (align[index]) c.setAttribute('align', align[index]); row.append(c); };
        headers.forEach((text, index) => addCell(headRow, 'th', text, index)); thead.append(headRow); table.append(thead);
        const tbody = node('tbody');
        while (i < lines.length && lines[i].trim() && lines[i].includes('|')) {
          const values = tableCells(lines[i++]), row = node('tr');
          for (let index = 0; index < headers.length; index++) addCell(row, 'td', values[index] || '', index);
          tbody.append(row);
        }
        table.append(tbody); wrap.append(table); root.append(wrap); continue;
      }
      const list = line.match(/^\s{0,3}([-*+]\s+|\d+[.)]\s+)/);
      if (list) {
        const ordered = /^\d/.test(list[1]), listNode = node(ordered ? 'ol' : 'ul');
        if (ordered) listNode.start = Number.parseInt(list[1], 10);
        while (i < lines.length) {
          if (!lines[i].trim()) {
            let next = i;
            while (next < lines.length && !lines[next].trim()) next++;
            const continuation = (lines[next] || '').match(/^\s{0,3}([-*+]\s+|\d+[.)]\s+)/);
            if (!continuation || /^\d/.test(continuation[1]) !== ordered) break;
            i = next;
          }
          const match = lines[i].match(/^\s{0,3}([-*+]\s+|\d+[.)]\s+)(.*)$/);
          if (!match || /^\d/.test(match[1]) !== ordered) break;
          const item = node('li'); item.append(inline(match[2], streaming)); listNode.append(item); i++;
        }
        root.append(listNode); continue;
      }
      if (/^\s{0,3}>\s?/.test(line)) {
        const quote = node('blockquote');
        while (i < lines.length && /^\s{0,3}>\s?/.test(lines[i])) { const p = node('p'); p.append(inline(lines[i++].replace(/^\s{0,3}>\s?/, ''), streaming)); quote.append(p); }
        root.append(quote); continue;
      }
      if (/^\s{0,3}#{1,6}\s+/.test(line)) { const heading = node('div'); heading.className = 'md-heading'; heading.append(inline(line.replace(/^\s{0,3}#{1,6}\s+/, ''), streaming)); root.append(heading); i++; continue; }
      const para = node('p');
      while (i < lines.length && lines[i].trim() && !isTableStart(lines, i) && !/^\s{0,3}(`{3,}|~{3,}|[-*+]\s+|\d+[.)]\s+|>\s?|#{1,6}\s+)/.test(lines[i])) {
        if (para.childNodes.length) para.append(node('br'));
        para.append(inline(lines[i++], streaming));
      }
      if (!para.childNodes.length) { para.append(inline(lines[i++], streaming)); }
      root.append(para);
    }
    return root;
  }
  window.HubMarkdown = { render };
})();
