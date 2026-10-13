/* A deliberately small, DOM-only markdown renderer for untrusted agent output. */
(() => {
  'use strict';
  const node = (tag, value) => { const n = document.createElement(tag); if (value != null) n.textContent = value; return n; };
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
    const marker = /(\[([^\]\n]+)\]\(([^)\s]+)\)|\*\*(\S(?:[^*\n]*?\S)?)\*\*|(?<![\p{L}\p{N}_])__(\S(?:[^_\n]*?\S)?)__(?![\p{L}\p{N}_])|(?<!\*)\*(\S(?:[^*\n]*?\S)?)\*(?!\*)|(?<![\p{L}\p{N}_])_(\S(?:[^_\n]*?\S)?)_(?![\p{L}\p{N}_])|(`+)([^`\n]*?)\8)/gu;
    let last = 0, found;
    while ((found = marker.exec(source))) {
      if (found.index > last) out.append(node('span', source.slice(last, found.index)));
      if (found[2] != null) {
        const href = safeLink(found[3]);
        if (href) { const a = node('a', found[2]); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; out.append(a); }
        else out.append(node('span', found[0]));
      } else if (found[5] != null && /^__[a-z][a-z0-9_]*__$/.test(found[0])) {
        // Single-word Python dunder names are common in a coding chat.
        out.append(node('span', found[0]));
      } else if (found[4] != null || found[5] != null) { const strong = node('strong'); strong.append(inline(found[4] ?? found[5], streaming)); out.append(strong); }
      else if (found[6] != null || found[7] != null) { const em = node('em'); em.append(inline(found[6] ?? found[7], streaming)); out.append(em); }
      else out.append(node('code', found[9]));
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
      const fence = line.match(/^\s*(`{3,}|~{3,})([^`]*)$/);
      if (fence) {
        const start = i++, body = [];
        while (i < lines.length && !new RegExp('^\\s*' + fence[1][0] + '{' + fence[1].length + ',}\\s*$').test(lines[i])) body.push(lines[i++]);
        if (i < lines.length) i++;
        // While streaming, an open fence is still shown as code without raw markers.
        const wrap = node('div'); wrap.className = 'code-block';
        const copy = node('button', 'Copy'); copy.type = 'button'; copy.className = 'code-copy';
        copy.addEventListener('click', () => { if (navigator.clipboard?.writeText) navigator.clipboard.writeText(body.join('\n')).then(() => { copy.textContent = 'Copied'; }).catch(() => {}); });
        const pre = node('pre'), code = node('code', body.join('\n'));
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
