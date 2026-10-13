(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const ui = {
    app: $('app'), login: $('loginScreen'), loginForm: $('loginForm'), loginButton: $('loginButton'), token: $('tokenInput'), loginError: $('loginError'),
    sidebar: $('sidebar'), agentList: $('agentList'), groupList: $('groupList'), title: $('chatTitle'),
    empty: $('emptyChat'), viewport: $('messageViewport'), list: $('messageList'), activity: $('activity'), composer: $('composer'), message: $('messageInput'), send: $('sendButton'), stop: $('stopButton'),
    replyBar: $('replyBar'), replyPreview: $('replyPreview'), uploadTray: $('uploadTray'), file: $('fileInput'), anyFile: $('anyFileInput'),
    agentDialog: $('agentDialog'), agentForm: $('agentForm'), agentError: $('agentError'), groupDialog: $('groupDialog'), groupForm: $('groupForm'), groupAgents: $('groupAgents'), groupError: $('groupError'),
    workersDialog: $('workersDialog'), workersBody: $('workersBody'), workerCount: $('workerCount'), offline: $('offlineBanner'), reconnect: $('reconnectBanner'), toast: $('toast')
  };
  const data = { agents: [], hiddenAgents: [], chats: [], statuses: [], messages: [], workers: null, jobs: [], setup: null, settings: null, product: null, routines: null, approvals: null, approvalsTab: 'timely', approvalsReviews: {}, swarms: [], chatId: null, creatingChatId: null, chatReady: null, replyTo: [], uploads: [], pending: false, eventSource: null, eventRetry: null, pollTimer: null, chatRequest: 0, stateRequest: 0, authenticated: false, toastTimer: null, read: {}, pinned: [], retryRequest: null, uploadLimit: 1073741824, coachStep: 0, searchTimer: null, tourAfterCreate: false, welcomeTemplate: 0, scheduleAfterCreate: null, deltas: new Map(), closedDeltas: new Set(), projectCheck: null, projectTimer: null, composeAgentId: null, teamChatId: null, swarmFocus: null, navFilter: '', navExpanded: {}, navScroll: {}, directoryKind: 'agents', directoryRole: '', directoryPage: 0, directorySelected: new Set(), proposalEdit: null, guideOpened: false };
  const storageKey = 'agent-hub-theme';
  const readStorageKey = 'agent-hub-last-read';
  const pinnedStorageKey = 'agent-hub-pinned';
  const approvalsStorageKey = 'agent-hub-approvals-reviews';
  function persistApprovalsReviews() {
    const saved = Object.fromEntries(Object.entries(data.approvalsReviews).slice(-100).map(([id, review]) => [id, { id, draft: review.draft, action: review.action, phase: review.phase, deadline: review.deadline, decision: review.decision, error: review.error }]));
    try { localStorage.setItem(approvalsStorageKey, JSON.stringify(saved)); } catch { /* storage may be unavailable */ }
  }

  function el(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = String(value);
    return node;
  }
  function icon(name) { const ns = 'http://www.w3.org/2000/svg'; const make = (tag) => (document.createElementNS ? document.createElementNS(ns, tag) : el(tag)); const svg = make('svg'); svg.setAttribute('class', 'icon'); svg.setAttribute('aria-hidden', 'true'); const use = make('use'); use.setAttribute('href', `#i-${name}`); svg.append(use); return svg; }
  function iconButton(name, label, className = '') { const button = el('button', className); button.type = 'button'; button.title = label; button.setAttribute('aria-label', label); button.append(icon(name)); return button; }
  function motionFeedback(node, className) {
    node.classList.add(className);
    setTimeout(() => node.classList.remove(className), 220);
  }
  function plainInline(value) { return plainText(value); }
  async function exportFile(path) { if (!await appActionDialog({ title: 'Export chats?', message: "Exports include your chat text. Review before sharing — we redact obvious secrets but can't catch everything.", accept: 'Export' })) return; const link = el('a'); link.href = path; link.download = ''; document.body.append(link); link.click(); link.remove(); }
  function markdown(value, className = '', streaming = false) { const rendered = window.HubMarkdown?.render(String(value || ''), { streaming }) || el('div', '', value); if (className) rendered.className += ` ${className}`; return rendered; }
  function showToast(message) {
    ui.toast.textContent = message;
    ui.toast.hidden = false;
    positionToast();
    clearTimeout(data.toastTimer);
    data.toastTimer = setTimeout(() => { ui.toast.hidden = true; }, 4300);
  }
  function positionToast() {
    if (ui.toast.hidden) return;
    const top = !ui.composer.hidden && !$('conversation').classList.contains('is-empty') ? ui.composer.getBoundingClientRect().top : window.innerHeight;
    ui.toast.style.bottom = `${Math.max(20, window.innerHeight - top + 12)}px`;
  }
  function errorText(error) {
    if (error instanceof TypeError && /fetch|network|load failed/i.test(error.message)) return 'Cannot reach Agent Hub. Keep its Terminal window open, check your connection, and reload.';
    return error && error.message ? error.message : 'The request failed. Check the connection and review its outcome before trying again.';
  }
  function safeUrl(value) {
    if (typeof value !== 'string') return null;
    try {
      const url = new URL(value, location.origin);
      return url.origin === location.origin && (url.protocol === 'http:' || url.protocol === 'https:') ? url.href : null;
    } catch { return null; }
  }
  function timeOf(seconds) {
    const n = Number(seconds);
    if (!Number.isFinite(n) || n <= 0) return '';
    return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date(n * 1000));
  }
  function dateTime(value) {
    if (value === 0 || value === '0' || value == null || value === '') return '';
    const n = Number(value);
    const ms = Number.isFinite(n) && n > 0 ? (n > 1e12 ? n : n * 1000) : Date.parse(value);
    if (!Number.isFinite(ms)) return '';
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(ms));
  }
  function chatTime(value) {
    if (value === 0 || value === '0' || value == null || value === '') return '';
    const n = Number(value);
    const ms = Number.isFinite(n) && n > 0 ? (n > 1e12 ? n : n * 1000) : Date.parse(value);
    if (!Number.isFinite(ms)) return '';
    const d = new Date(ms);
    return d.toDateString() === new Date().toDateString() ? timeOf(ms / 1000) : new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(d);
  }
  function seconds(value) {
    if (value === 0 || value === '0' || value == null || value === '') return 0;
    const n = Number(value);
    if (Number.isFinite(n) && n > 0) return n > 1e12 ? n / 1000 : n;
    const ms = Date.parse(value);
    return Number.isFinite(ms) ? ms / 1000 : 0;
  }
  function visibleChat() {
    return data.authenticated && !ui.app.hidden && document.visibilityState === 'visible' &&
      (matchMedia('(min-width: 701px)').matches || ui.app.classList.contains('chat-open'));
  }
  function markRead(id) {
    if (!id || !visibleChat()) return;
    const item = chat(id);
    const newestMessage = data.messages.reduce((latest, message) => Math.max(latest, seconds(message.created)), 0);
    const lastMessage = item?.last_message && typeof item.last_message === 'object' ? seconds(item.last_message.created) : 0;
    const timestamp = Math.max(seconds(item?.updated), lastMessage, newestMessage);
    data.read[id] = Math.max(data.read[id] || 0, timestamp);
    try { localStorage.setItem(readStorageKey, JSON.stringify(data.read)); } catch { /* storage may be unavailable */ }
    renderNav();
    const lastId = Number(data.messages.at(-1)?.id);
    if (Number.isSafeInteger(lastId) && lastId > 0) post('/api/product', { action: 'mark_read', chat_id: id, upto_id: lastId }).then((result) => { data.product = result; renderNav(); }).catch(() => {});
  }
  function hasUnread(item) {
    if (data.product?.unread) return Number(data.product.unread[item.id] || 0) > 0;
    if (!item.last_message) return false;
    if (!Object.prototype.hasOwnProperty.call(data.read, item.id)) return true;
    const lastMessage = item.last_message && typeof item.last_message === 'object' ? seconds(item.last_message.created) : 0;
    return Math.max(seconds(item.updated), lastMessage) > data.read[item.id];
  }
  function agent(id) { return data.agents.find((item) => String(item.id) === String(id)); }
  function chat(id) { return data.chats.find((item) => String(item.id) === String(id)); }
  function directId(id) { return `agent:${id}`; }
  function currentChat() { return chat(data.chatId); }
  function avatar(emoji, imageUrl, extraClass, pipAgent = null) {
    const node = el('div', `avatar ${extraClass || ''}`.trim());
    if (pipAgent && window.Pips && pipAgent.avatar_style !== 'emoji') {
      const template = document.createElement('template');
      template.innerHTML = window.Pips.avatarHTML(pipAgent);
      node.append(template.content.firstElementChild);
      return node;
    }
    const src = safeUrl(imageUrl);
    if (src) { const image = el('img'); image.src = src; image.alt = ''; image.loading = 'lazy'; image.onerror = () => { image.src = '/static/mascot.svg'; }; node.append(image); }
    else if (emoji) node.textContent = emoji;
    else { const image = el('img'); image.src = '/static/mascot.svg'; image.alt = ''; node.append(image); }
    return node;
  }
  function setAvatar(node, emoji, url) { const replacement = avatar(emoji, url); node.replaceChildren(...replacement.childNodes); }
  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.method && options.method !== 'GET') headers.set('X-Hub-Request', '1');
    if (options.body && typeof options.body === 'string') headers.set('Content-Type', 'application/json');
    const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...options, headers });
    if (response.status === 401 && path !== '/api/login') { showLogin(); throw new Error('Your session ended. Use the token you saved at first start. If you lost it, stop Hub and run python3 hub.py --reset-token.'); }
    let body;
    try { body = await response.json(); } catch { body = null; }
    if (!response.ok) { const error = new Error(body?.error || `Request failed (${response.status}).`); error.status = response.status; throw error; }
    return body;
  }
  function post(path, body) { return api(path, { method: 'POST', body: JSON.stringify(body) }); }
  function patchAgentAccess(id, privatePip, draftOnly) { return api(`/api/agents/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ private_pip: !!privatePip, draft_only: !!draftOnly }) }); }
  function showLogin() {
    data.authenticated = false;
    clearTimeout(eventRefreshTimer); eventRefreshTimer = null; eventRefreshPending = false; eventRefreshChat = false; eventRefreshJobs = false;
    if (data.eventSource) { data.eventSource.close(); data.eventSource = null; }
    clearTimeout(data.eventRetry);
    clearUploads(); resetDropOverlay(); closeImageLightbox();
    parity?.reset();
    data.guideOpened=false; data.agents = []; data.chats = []; data.statuses = []; data.messages = []; data.workers = null; data.deltas.clear(); data.closedDeltas.clear(); data.chatReady = null;
    sendFeel.optimistic.clear(); sendFeel.receipts.clear(); sendFeel.finishing.clear(); sendFeel.finalMessages.clear(); sendFeel.sending.clear(); clearTimeout(data.toastTimer); ui.toast.replaceChildren(); ui.toast.hidden = true;
    sendFeel.session++; sendFeel.dispatchTail = null;
    ui.stop.dataset.pending = 'false'; ui.stop.hidden = true;
    data.chatId = null; data.creatingChatId = null; data.replyTo = []; data.uploads = []; data.pending = false; data.chatRequest++; data.stateRequest++;
    data.product = null;
    // Keep uncertain review locks across sign-out/sign-in in this owner browser.
    Object.values(data.approvalsReviews).forEach((review) => clearTimeout(review.timer));
    data.retryRequest = null;
    ui.app.classList.remove('chat-open'); ui.agentList.replaceChildren(); ui.groupList.replaceChildren(); ui.list.replaceChildren();
    ui.message.value = ''; ui.message.style.height = ''; ui.file.value = ''; ui.anyFile.value = ''; ui.replyBar.hidden = true; ui.uploadTray.replaceChildren(); ui.uploadTray.hidden = true;
    ui.viewport.hidden = true; ui.composer.hidden = true; ui.empty.hidden = false; ui.activity.hidden = true;
    document.querySelectorAll('dialog').forEach((dialog) => { if (dialog.open) dialog.close(); });
    renderHeader();
    ui.app.hidden = true; ui.login.hidden = false; ui.reconnect.hidden = true;
    ui.token.value = '';
    ui.token.focus();
  }
  function showApp() {
    data.authenticated = true;
    ui.login.hidden = true; ui.app.hidden = false;
    ui.loginError.hidden = true;
  }
  function statusFor(chatId) {
    const directAgent = String(chatId).startsWith('agent:') ? String(chatId).slice(6) : null;
    return data.statuses.filter((item) => String(item.chat_id) === String(chatId) || (directAgent && String(item.agent_id) === directAgent));
  }
  function statusText(chatId) {
    const statuses = statusFor(chatId);
    if (!statuses.length) return '';
    if (statuses.some((s) => s.status === 'choosing')) return 'Choosing who answers…';
    const typing = statuses.filter((s) => s.status === 'typing');
    const working = statuses.filter((s) => s.status === 'working');
    const queued = statuses.filter((s) => s.status === 'queued');
    const chosen = typing.length ? typing : working.length ? working : queued;
    if (!chosen.length) return '';
    const names = [...new Set(chosen.map((s) => agent(s.agent_id)?.name || 'Pip'))];
    const verb = typing.length ? 'typing' : working.length ? 'working' : 'queued';
    return `${names.join(', ')} ${verb}…`;
  }
  function avatarState(chatId) {
    const statuses = statusFor(chatId);
    if (statuses.some((s) => s.status === 'typing')) return 'thinking';
    if (statuses.some((s) => s.status === 'working')) return 'working';
    if (statuses.some((s) => s.status === 'queued')) return 'waiting';
    const directAgent = String(chatId).startsWith('agent:') ? String(chatId).slice(6) : null;
    const latest = data.jobs.find((j) => String(j.chat_id) === String(chatId) || (directAgent && String(j.agent_id) === directAgent));
    if (latest && ['blocked','error','interrupted','stopped'].includes(latest.status)) return 'blocked';
    if (latest?.status === 'done' && Date.now() / 1000 - Number(latest.created || 0) < 300) return 'done';
    return 'idle';
  }
  function displayChat(chatItem, fallbackAgent) {
    const a = fallbackAgent || (chatItem?.type === 'direct' ? agent(chatItem.agents?.[0] || String(chatItem.id).replace(/^agent:/, '')) : null);
    return { name: chatItem?.name || a?.name || 'Conversation', emoji: a?.emoji || (chatItem?.type === 'group' ? chatItem?.emoji || '👥' : '🤖'), avatar: a?.avatar || null };
  }
  function plainText(text) {
    return visibleHandoffText(text).replace(/```[^\n]*\n?/g, '\n').replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
      .replace(/^\s{0,3}(#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)/gm, '').replace(/(\*\*|__|\*|~~|`)/g, '')
      .replace(/\s+/g, ' ').trim();
  }
  function preview(item) {
    const status = statusText(item.id);
    if (status) return status;
    const last = item.last_message;
    if (typeof last === 'string') return plainText(last);
    if (last && typeof last === 'object') return last.text ? plainText(last.text) : 'Attachment';
    return item.type === 'group' ? 'Group conversation' : 'Start a conversation';
  }
  function navButton(item, fallbackAgent) {
    const d = displayChat(item, fallbackAgent);
    const button = el('button', `nav-item${String(data.chatId) === String(item.id) ? ' active' : ''}`);
    button.type = 'button'; button.dataset.chatId = item.id;
    button.setAttribute('aria-label', `Open ${d.name}${fallbackAgent?.linked ? ' · Linked to an existing agent folder, read-only' : ''}`);
    if (String(data.chatId) === String(item.id)) button.setAttribute('aria-current', 'page');
    const face = avatar(d.emoji, fallbackAgent?.avatar_style === 'emoji' ? null : item.avatar || d.avatar, '', fallbackAgent);
    const colorIndex = [...String(fallbackAgent?.id || item.id)].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 4;
    face.classList.add(`avatar-color-${colorIndex}`);
    const state = avatarState(item.id);
    const related = data.jobs.find((job) => String(job.chat_id) === String(item.id) || (fallbackAgent && String(job.agent_id) === String(fallbackAgent.id)));
    face.dataset.state = state; face.title = related && ['queued','working','typing'].includes(related.status) ? (related.task || related.last_event || statusText(item.id)) : statusText(item.id) || `${d.name} · ${state}`;
    let tipTimer;
    face.addEventListener('pointerdown', () => { tipTimer = setTimeout(() => {
      const tip = $('avatarTip'); tip.textContent = face.title;
      tip.hidden = false;
    }, 550); });
    ['pointerup','pointercancel','pointerleave'].forEach((name) => face.addEventListener(name, () => { clearTimeout(tipTimer); setTimeout(() => { $('avatarTip').hidden = true; }, 1600); }));
    button.append(face);
    const copy = el('div', 'nav-copy'); copy.append(el('div', 'nav-name', d.name));
    if (fallbackAgent?.linked) copy.append(sidebarLinkedIcon());
    button.title = [d.name, fallbackAgent?.title, preview(item)].filter(Boolean).join(' · ');
    if (String(item.id).startsWith('group:swarm-') || item.swarm_id) copy.append(el('span', 'team-task-badge', 'Team task'));
    button.append(copy);
    const status = statusText(item.id);
    if (status) {
      const spinner = el('span', 'status-spinner'); spinner.setAttribute('aria-label', status); spinner.setAttribute('role', 'img');
      button.append(spinner);
    }
    if (hasUnread(item)) {
      const dot = el('span', 'unread-dot'); dot.setAttribute('aria-label', 'Unread messages'); dot.setAttribute('role', 'img');
      button.append(dot);
    }
    const when = chatTime(item.updated);
    if (when && !status && !hasUnread(item)) button.append(el('span', 'nav-time', when));
    button.addEventListener('click', () => openChat(item.id));
    return button;
  }
  function sidebarLinkedIcon() {
    const label = 'Linked to an existing agent folder, read-only';
    const mark = el('span', 'nav-linked'); mark.title = label;
    mark.setAttribute('role', 'img'); mark.setAttribute('aria-label', label);
    const svg = icon('link'); svg.setAttribute('viewBox', '0 0 24 24');
    const path = document.createElementNS ? document.createElementNS('http://www.w3.org/2000/svg', 'path') : el('path');
    path.setAttribute('d', 'M10 13a5 5 0 0 0 7.1 0l3-3a5 5 0 0 0-7.1-7.1l-1.7 1.7M14 11a5 5 0 0 0-7.1 0l-3 3a5 5 0 0 0 7.1 7.1l1.7-1.7');
    svg.replaceChildren(path); mark.append(svg); return mark;
  }
  // Fixed row heights reserve the complete scroll extent while only mounting visible rows.
  function windowedRows(items, makeRow, key, rowHeight = 60, threshold = 60) {
    const list = el('div', 'window-list');
    if (items.length <= threshold) { list.append(...items.map(makeRow)); return list; }
    list.classList.add('windowed'); list.style.height = `${Math.min(420, items.length * rowHeight)}px`;
    list.tabIndex = 0; list.setAttribute('aria-label', 'Scrollable list');
    const spacer = el('div', 'window-spacer'); spacer.style.height = `${items.length * rowHeight}px`;
    const rows = el('div', 'window-rows'); spacer.append(rows); list.append(spacer);
    let last = -1;
    const draw = (position = list.scrollTop || 0) => { const start = Math.max(0, Math.floor(position / rowHeight) - 2); if (start === last) return; last = start; rows.style.top = `${start * rowHeight}px`; rows.replaceChildren(...items.slice(start, start + Math.ceil(420 / rowHeight) + 4).map(makeRow)); data.navScroll[key] = position; };
    const saved = Math.min(data.navScroll[key] || 0, Math.max(0, items.length * rowHeight - 420));
    draw(saved); list.addEventListener('scroll', () => draw());
    requestAnimationFrame(() => { list.scrollTop = saved; draw(); }); return list;
  }
  function navRow(c) {
    const a = c.type === 'direct' ? agent(c.agents?.[0]) : null;
    const wrap = el('div', 'nav-wrap'); wrap.dataset.chatId = c.id; const button = navButton(c, a);
    if (data.pinned.includes(c.id)) { const marker = icon('star'); marker.classList.add('nav-pin'); button.querySelector('.nav-name').prepend(marker); }
    wrap.append(button); parity?.animateRow(wrap, c.id);
    const pinned = data.pinned.includes(c.id), label = c.type === 'group' ? 'group' : 'Pip';
    const star = iconButton('star', `${pinned ? 'Unstar' : 'Star'} ${label}`, `pin-button${pinned ? ' pinned' : ''}`);
    star.setAttribute('aria-pressed', String(pinned));
    star.addEventListener('click', () => togglePin(c.id, star)); wrap.append(star); return c.type === 'direct' ? parity?.pipRow(c, wrap) || wrap : wrap;
  }
  function navSections(container, items, kind) {
    const query = normalizeSearch(data.navFilter);
    const name = (c) => c.name || agent(c.agents?.[0])?.name || '';
    const filtered = items.filter((c) => { const a = agent(c.agents?.[0]); return [name(c), a?.title, a?.role, ...data.chats.filter((item) => item.type === 'direct' && item.agents?.[0] === a?.id).map((item) => item.name)].some((text) => normalizeSearch(text).includes(query)); });
    const pinned = filtered.filter((c) => data.pinned.includes(c.id)).sort((a,b) => data.pinned.indexOf(a.id) - data.pinned.indexOf(b.id));
    const unpinned = filtered.filter((c) => !data.pinned.includes(c.id));
    const recent = unpinned.filter((c) => seconds(c.updated) > 0).sort((a,b) => seconds(b.updated)-seconds(a.updated) || name(a).localeCompare(name(b)));
    const rest = unpinned.filter((c) => seconds(c.updated) <= 0).sort((a,b) => name(a).localeCompare(name(b)));
    const ordered = parity?.stableOrder([...pinned, ...recent, ...rest], kind) || [...pinned, ...recent, ...rest];
    const sidebarScroller = ui.sidebar.querySelector('.side-scroll') || ui.sidebar;
    const sidebarPosition = sidebarScroller.scrollTop;
    const positions = parity?.measureRows(container);
    container.replaceChildren();
    container.append(windowedRows(ordered.slice(0, 12), navRow, kind + '-preview', 48));
    if (ordered.length > 12) { const showAll = el('button', 'show-all-row', `Show all ${ordered.length}`); showAll.type = 'button'; showAll.addEventListener('click', () => openDirectory(kind)); container.append(showAll); }
    if (query && !filtered.length) container.append(el('p', 'nav-empty', 'No matches.'));
    sidebarScroller.scrollTop = sidebarPosition;
    parity?.animateReorder(container, positions);
  }
  function renderNav() {
    const chatMap = new Map(data.chats.map((c) => [c.id,c]));
    const directs = data.agents.filter((a) => !a.swarm).map((a) => {
      const base = chatMap.get(directId(a.id)) || { id: directId(a.id), type: 'direct', agents: [a.id] };
      const latest = data.chats.filter((c) => c.type === 'direct' && c.agents?.[0] === a.id).sort((x,y) => seconds(y.updated)-seconds(x.updated))[0] || base;
      return { ...base, updated: latest.updated, last_message: latest.last_message, name: a.name };
    });
    directs.sort((a,b) => seconds(b.updated)-seconds(a.updated) || a.name.localeCompare(b.name));
    navSections(ui.agentList, directs, 'agents');
    const groups = data.chats.filter((c) => c.type === 'group' && (!c.source_chat_id || c.source_chat_id === c.id));
    navSections(ui.groupList, groups, 'groups');
    if (!groups.length) { const empty = el('div', 'nav-empty compact-group-empty'); empty.append(el('span', '', 'No groups yet ·')); const create = el('button', '', 'Make a group'); create.addEventListener('click', () => $('newGroupButton').click()); empty.append(create); ui.groupList.append(empty); }
    renderHeader();
  }
  function pipRole(a) {
    const title = `${a.title || ''} ${a.name || ''}`;
    const categories = [
      ['Writing', /\b(writ\w*|edit\w*|copy\w*|author|summari\w*|content)\b/i],
      ['Research', /\b(research\w*|investigat\w*|sources?|evidence)\b/i],
      ['Coding', /\b(cod\w*|develop\w*|software|debug\w*|programm\w*|test(?:er|ing)?)\b/i],
      ['Ops', /\b(ops|operations?|deploy\w*|infrastructure|automat\w*|schedul\w*)\b/i],
      ['Inbox', /\b(inbox|email\w*|mail|correspondence|messages?)\b/i],
      ['Design', /\b(design\w*|visual\w*|illustrat\w*|ux|ui|brand\w*)\b/i],
      ['Data', /\b(data|analy\w*|spreadsheet\w*|sql|statistics)\b/i]
    ];
    return categories.find(([,pattern])=>pattern.test(title))?.[0] || categories.find(([,pattern])=>pattern.test(a.role || ''))?.[0] || 'Other';
  }
  function openDirectory(kind = 'agents') {
    data.directoryKind = kind; data.directoryRole=''; data.directoryPage=0; data.directorySelected.clear(); $('directorySearch').value = data.navFilter; $('directoryRole').value = ''; $('directoryShowHidden').checked = false; renderDirectory(); $('directoryDialog').showModal();
  }
  function renderDirectory() {
    const isGroup = data.directoryKind === 'groups'; $('directoryTitle').textContent = isGroup ? 'All Groups' : 'All Pips';
    const query = $('directorySearch').value.toLowerCase().trim();
    const source = isGroup ? data.chats.filter((c) => c.type === 'group' && (!c.source_chat_id || c.source_chat_id === c.id)) : [...data.agents.filter((a) => !a.swarm), ...($('directoryShowHidden').checked ? data.hiddenAgents : [])];
    const activity = (a) => seconds(isGroup ? a.updated : chat(directId(a.id))?.updated);
    const roleControl=$('directoryRole');
    const roles = ['Writing','Research','Coding','Ops','Inbox','Design','Data','Other'];
    roleControl.hidden = true; // One set of human role chips, without a duplicate selector.
    const items = source.filter((a) => `${a.name} ${a.title || ''} ${a.role || ''}`.toLowerCase().includes(query) && (isGroup || !data.directoryRole || pipRole(a) === data.directoryRole));
    items.sort($('directorySort').value === 'name' ? (a,b) => a.name.localeCompare(b.name) : (a,b) => activity(b)-activity(a) || a.name.localeCompare(b.name));
    $('directoryChips').hidden = isGroup; $('directoryShowHiddenLabel').hidden = isGroup || !data.hiddenAgents.length;
    $('directoryChips').replaceChildren();
    if (!isGroup) roles.filter((role) => source.some((a) => pipRole(a) === role)).forEach((role) => { const chip = el('button', 'role-chip', role); chip.type='button'; chip.setAttribute('aria-pressed', String(data.directoryRole===role)); chip.addEventListener('click', () => { data.directoryRole=data.directoryRole===role?'':role; data.directoryPage=0; renderDirectory(); }); $('directoryChips').append(chip); });
    const makeCard = (a) => { const cid = isGroup ? a.id : directId(a.id), card = el('div','pip-card'); card.dataset.chatId = cid;
      const open = el('button','pip-card-open'); open.type='button'; open.append(avatar(a.emoji, a.avatar, '', isGroup ? null : a), el('strong','',a.name), el('span','pip-title',a.title || (isGroup ? `${a.agents.length} Pips` : 'Your helper')));
      if(a.linked)open.append(el('span','linked-badge','Linked'));
      if(a.archived)open.append(el('span','hidden-badge','Hidden'));
      const state = avatarState(cid), dot = el('span',`pip-status ${state}`, state); open.append(el('small','',activity(a) ? `Active ${chatTime(activity(a))}` : 'No activity yet'),dot);
      open.addEventListener('click', () => { if(a.archived)return; closeDialog($('directoryDialog')); openChat(cid); });
      card.append(open);
      if(a.archived){const restore=el('button','secondary','Unarchive');restore.type='button';restore.addEventListener('click',async()=>{restore.disabled=true;try{await post('/api/unarchive',{id:a.id});await refreshState();renderDirectory();}catch(error){showToast(errorText(error));restore.disabled=false;}});card.append(restore);}
      else {const label=el('label','directory-select'), check=el('input'); check.type='checkbox'; check.checked=data.directorySelected.has(a.id); check.setAttribute('aria-label',`Select ${a.name}`); check.addEventListener('change',()=>{if(check.checked)data.directorySelected.add(a.id);else data.directorySelected.delete(a.id);$('directoryArchive').disabled=!data.directorySelected.size;});label.append(check,el('span','','Select'));card.append(label);}return card; };
    const columns = window.innerWidth > 700 ? 3 : window.innerWidth > 440 ? 2 : 1;
    // Content-sized pages keep tall linked/hidden cards clickable at every text size.
    const pageSize = 60, pages = Math.max(1, Math.ceil(items.length / pageSize));
    data.directoryPage = Math.min(data.directoryPage || 0, pages - 1);
    const visible = items.slice(data.directoryPage * pageSize, (data.directoryPage + 1) * pageSize);
    const rows = []; for(let i=0;i<visible.length;i+=columns) rows.push(visible.slice(i,i+columns));
    const makeRow = (row) => { const node=el('div','directory-grid-row'); node.style.gridTemplateColumns=`repeat(${columns},minmax(0,1fr))`;node.append(...row.map(makeCard));return node; };
    $('directoryGrid').replaceChildren(...rows.map(makeRow));
    if (pages > 1) {
      const nav=el('div','directory-pages'); nav.append(el('span','',`Page ${data.directoryPage + 1} of ${pages}`));
      [['Previous',-1],['Next',1]].forEach(([label,step])=>{const button=el('button','secondary',label);button.type='button';button.disabled=data.directoryPage+step<0 || data.directoryPage+step>=pages;button.addEventListener('click',()=>{data.directoryPage+=step;renderDirectory();$('directoryGrid').scrollIntoView({block:'start'});});nav.append(button);});
      $('directoryGrid').append(nav);
    }
    if(!items.length)$('directoryGrid').append(el('p','empty-note','No matching Pips or groups.'));
    $('directoryArchive').disabled=!data.directorySelected.size;
  }
  function togglePin(id, trigger) {
    const keyboardFocus = trigger?.matches?.(':focus-visible');
    data.pinned = data.pinned.includes(id) ? data.pinned.filter((x) => x !== id) : [...data.pinned, id];
    try { localStorage.setItem(pinnedStorageKey, JSON.stringify(data.pinned)); } catch { /* private mode */ }
    renderNav();
    const row = [...ui.sidebar.querySelectorAll('.nav-wrap')].find((node) => node.dataset.chatId === id);
    const star = row?.querySelector('.pin-button');
    if (star) {
      if (data.pinned.includes(id)) motionFeedback(star, 'star-pop');
      if (keyboardFocus) star.focus({ preventScroll: true });
    }
    post('/api/product', { action: data.pinned.includes(id) ? 'pin' : 'unpin', chat_id: id }).then((result) => { data.product = result; }).catch((error) => showToast(errorText(error)));
  }
  function composeAgent() {
    const c = currentChat();
    return agent(data.composeAgentId) || agent(c?.agents?.[0]) || agent(String(data.chatId || '').replace(/^agent:/, '')) || data.agents.find((a) => !a.swarm);
  }
  function activeChatJobs() { return data.statuses.filter((job) => data.chatId && String(job.chat_id) === data.chatId && ['queued','working','typing'].includes(job.status)); }
  function renderSend() {
    ui.send.replaceChildren(icon('send'));
    ui.send.title = parity?.editing ? 'Save edit and resend' : 'Send message'; ui.send.setAttribute('aria-label', ui.send.title);
    ui.send.disabled = !!parity?.editing && data.pending || data.uploads.some((x) => x.status === 'uploading');
    ui.stop.hidden = !activeChatJobs().length;
    ui.stop.disabled = ui.stop.dataset.pending === 'true';
  }
  async function stopResponse() {
    const active = activeChatJobs();
    if (!active.length || ui.stop.dataset.pending === 'true') return;
    ui.stop.dataset.pending = 'true'; renderSend();
    try { await Promise.all(active.map((job) => post('/api/jobs/stop', { job_id: job.id }))); await refreshState(); }
    catch (error) { showToast(errorText(error)); }
    finally { ui.stop.dataset.pending = 'false'; renderSend(); }
  }
  let composerDockAnimation = null, composerDockChat = null;
  function queueComposerDock(chatId) {
    if ($('conversation').classList.contains('is-empty')) composerDockChat = String(chatId);
  }
  function renderEmptyIdentity() {
    const c = currentChat(), isGroup = c?.type === 'group' || String(data.chatId || '').startsWith('group:');
    const a = isGroup ? null : agent(c?.agents?.[0] || String(data.chatId || '').replace(/^agent:/, ''));
    const mark = ui.empty.querySelector('.empty-mark');
    if (data.chatId) {
      const d = displayChat(c, a);
      // Emoji overrides stay emoji even if an older custom image remains assigned.
      mark.replaceChildren(avatar(isGroup ? c?.emoji || '👥' : d.emoji, a?.avatar_style === 'emoji' ? null : c?.avatar || d.avatar, 'empty-avatar', a));
    } else {
      const image = el('img'); image.src = '/static/logo.svg'; image.alt = ''; mark.replaceChildren(image);
    }
    const hour = new Date().getHours();
    const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
    $('greeting').textContent = `${greeting} · ${!data.chatId ? 'Ask anything' : isGroup ? 'Ask the group' : `Ask ${a?.name || c?.name || 'this Pip'} anything`}`;
  }
  function renderEmpty() {
    const empty = !data.chatId || !data.messages.length && ![...data.deltas.values()].some((delta) => String(delta.chat_id) === data.chatId && delta.text);
    const conversation = $('conversation'), chatId = String(data.chatId || '');
    const sameChat = conversation.dataset.emptyChatId === chatId;
    // Measure the centered composer before switching to the normal reading layout.
    const dock = sameChat && !empty && composerDockChat === chatId && conversation.classList.contains('is-empty') && !ui.composer.hidden;
    const before = dock ? ui.composer.getBoundingClientRect().top : null;
    if (!sameChat && composerDockAnimation) { composerDockAnimation.cancel(); composerDockAnimation = null; }
    if (!sameChat || !empty) composerDockChat = null;
    conversation.classList.toggle('is-empty', empty); conversation.dataset.emptyChatId = chatId;
    ui.empty.hidden = !empty; $('suggestionChips').hidden = !empty || !!data.chatId && !agent(currentChat()?.agents?.[0])?.guide;
    ui.viewport.hidden = empty; ui.composer.hidden = !data.authenticated;
    if (empty) renderEmptyIdentity();
    positionToast();
    if (dock && typeof ui.composer.animate === 'function' && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
      const offset = before - ui.composer.getBoundingClientRect().top;
      if (offset) {
        composerDockAnimation?.cancel();
        composerDockAnimation = ui.composer.animate([{ transform: `translateY(${offset}px)` }, { transform: 'translateY(0)' }], { duration: 280, easing: 'cubic-bezier(.2,.8,.2,1)' });
      }
    }
  }
  function renderHeader() {
    const c = currentChat();
    $('newPipChat').title = `New chat with ${composeAgent()?.name || 'a Pip'}`; $('newPipChat').setAttribute('aria-label', $('newPipChat').title);
    $('chatManageButton').hidden = !data.chatId;
    ui.title.dataset.fullTitle = data.chatId ? displayChat(c, agent(String(data.chatId).replace(/^agent:/, ''))).name : 'Agent Hub';
    ui.title.title = data.chatId ? `Chat settings · ${ui.title.dataset.fullTitle}` : '';
    fitChatTitle();
    const accessAgent = c?.type === 'direct' ? agent(c.agents?.[0]) : String(data.chatId || '').startsWith('agent:') ? agent(String(data.chatId).slice(6)) : null;
    const chips = $('pipAccessChips');
    chips.hidden = !accessAgent;
    chips.replaceChildren(...(accessAgent ? (window.HubAccess?.mode(accessAgent) || ['Full access']).map((label) => el('span', 'pip-access-chip', label)) : []));
    $('chatSubtitle').hidden = c?.type !== 'group';
    if (c?.type === 'group') $('chatSubtitle').textContent = 'One Pip answers · Ask everyone for more';
    const selected = composeAgent();
    ui.message.placeholder = data.chatId && c?.type !== 'group' && !String(data.chatId).startsWith('group:') ? `Message ${selected?.name || c?.name || 'Pip'}…` : 'Ask anything…';
    const directed = c?.type === 'group' && c.agents?.includes(data.composeAgentId) ? agent(data.composeAgentId) : null;
    $('modelSelector').replaceChildren(el('span', '', c?.type === 'group' ? directed?.name || 'Best fit' : selected ? `${selected.name} · ${selected.model || selected.engine || 'model'}` : 'Choose a Pip'), icon('down'));
    $('askEveryoneButton').hidden = c?.type !== 'group' || String(c.id).startsWith('group:swarm-');
    const status = data.chatId ? statusText(data.chatId) : '';
    ui.activity.hidden = !status || activeChatJobs().length > 0; ui.activity.textContent = status;
    renderSend(); renderEmpty();
    requestAnimationFrame(fitChatTitle);
  }
  // Remove whole words after layout, keeping the full name available in the tooltip.
  function fitChatTitle() {
    const full = ui.title.dataset.fullTitle || 'Agent Hub';
    ui.title.textContent = full;
    if (!ui.title.clientWidth || !Number.isFinite(ui.title.scrollWidth)) return;
    const words = full.trim().split(/\s+/);
    while (words.length && ui.title.scrollWidth > ui.title.clientWidth) {
      words.pop(); ui.title.textContent = words.length ? words.join(' ') + '…' : '…';
    }
  }
  async function refreshState() {
    const request = ++data.stateRequest;
    const result = await api('/api/state');
    if (request !== data.stateRequest) return;
    if (Number.isSafeInteger(result.max_upload_bytes) && result.max_upload_bytes > 0) data.uploadLimit = result.max_upload_bytes;
    data.agents = Array.isArray(result.agents) ? result.agents : [];
    data.hiddenAgents = Array.isArray(result.hidden_agents) ? result.hidden_agents : [];
    data.chats = Array.isArray(result.chats) ? result.chats : [];
    data.statuses = Array.isArray(result.statuses) ? result.statuses : [];
    const activeJobs = new Set(data.statuses.filter((job) => ['queued','working','typing'].includes(job.status)).map((job) => String(job.id)));
    for (const key of data.deltas.keys()) if (!activeJobs.has(key) && !key.startsWith('request:') && !sendFeel.finishing.has(key)) data.deltas.delete(key);
    if (data.chatId && data.chatId !== data.creatingChatId && !data.chats.some((item) => String(item.id) === data.chatId)) {
      data.chatId = null; data.messages = []; data.chatRequest++; ui.app.classList.remove('chat-open');
      ui.viewport.hidden = true; ui.composer.hidden = true; ui.empty.hidden = false;
      history.replaceState({}, '', location.pathname);
    }
    let hasPinnedPreference = false;
    try { hasPinnedPreference = localStorage.getItem(pinnedStorageKey) !== null; } catch { /* private mode */ }
    if (!data.pinned.length && data.agents.length && !hasPinnedPreference) {
      data.pinned = [directId(data.agents[0].id)];
      try { localStorage.setItem(pinnedStorageKey, JSON.stringify(data.pinned)); } catch { /* private mode */ }
    }
    showApp(); renderNav();
    await refreshProduct();
    if (request !== data.stateRequest) return;
    if (!data.chatId && location.hash.startsWith('#chat=')) {
      let fromUrl = ''; try { fromUrl = decodeURIComponent(location.hash.slice(6)); } catch { /* invalid fragment */ }
      if (data.chats.some((c) => String(c.id) === fromUrl) || data.agents.some((a) => directId(a.id) === fromUrl)) { await openChat(fromUrl, false); if (matchMedia('(max-width: 700px)').matches) ui.app.classList.add('chat-open'); }
    }
    if (!data.chatId && !data.creatingChatId && !data.guideOpened && data.agents.some((a)=>a.guide) && !data.product?.last_chat) { data.guideOpened=true; await openChat(directId(data.agents.find((a)=>a.guide).id)); }
    if (!data.chatId && !data.creatingChatId && matchMedia('(min-width: 701px)').matches) {
      const first = data.product?.last_chat || directId(data.agents.find((a) => a.guide)?.id || '');
      if (data.chats.some((c) => c.id === first)) await openChat(first, false);
    }
  }
  async function openChat(id, mobile = true, messageId = null) {
    if (data.chatId === String(id) && !ui.composer.hidden && messageId == null) { await refreshChat(); return; }
    data.stateRequest++;
    parity?.reset();
    clearUploads(); resetDropOverlay(); closeImageLightbox();
    data.composeAgentId = null; data.chatId = String(id); data.replyTo = []; data.uploads = []; renderReply(); renderUploads();
    conversationScrollPending = false;
    ui.viewport.scrollTop = 0; $('conversation').classList.remove('has-scrolled-messages');
    ui.message.value = ''; ui.message.style.height = ''; data.retryRequest = null;
    if (mobile) { ui.app.classList.add('chat-open'); if (matchMedia('(max-width: 700px)').matches && history.state?.chat !== String(id)) history.pushState({ chat: String(id) }, '', `#chat=${encodeURIComponent(id)}`); }
    ui.empty.hidden = true; ui.viewport.hidden = false; ui.composer.hidden = false;
    ui.list.replaceChildren(el('div', 'list-skeleton', 'Loading conversation…')); data.messages = [];
    renderNav();
    const ready = refreshChat(true);
    data.chatReady = { id: String(id), promise: ready };
    await ready;
    if (data.chatId !== String(id)) return;
    if (messageId != null) requestAnimationFrame(() => {
      const target = [...ui.list.children].find((node) => node.dataset.messageId === String(messageId));
      if (target) { target.scrollIntoView({ block: 'center' }); target.classList.add('search-match'); setTimeout(() => target.classList.remove('search-match'), 4000); }
    });
    post('/api/product', { action: 'continue', chat_id: String(id) }).then((result) => { data.product = result; renderNav(); }).catch(() => {});
  }
  async function refreshChat(forceScroll = false) {
    if (!data.chatId || !data.authenticated) return;
    const id = data.chatId, request = ++data.chatRequest;
    try {
      const result = await api(`/api/chat?id=${encodeURIComponent(id)}`);
      if (request !== data.chatRequest || id !== data.chatId) return;
      const nearBottom = followingConversation();
      const previousHeight = ui.viewport.scrollHeight;
      if (result.chat) {
        const index = data.chats.findIndex((c) => String(c.id) === id);
        if (index >= 0) data.chats[index] = { ...data.chats[index], ...result.chat }; else data.chats.push(result.chat);
      }
      data.messages = mergeSentMessages(Array.isArray(result.messages) ? result.messages : [], id);
      reconcileMessages(); window.HubOnboarding?.mountOffer(); markRead(id); renderNav();
      parity?.renderVersions(result);
      if (forceScroll || nearBottom && ui.viewport.scrollHeight !== previousHeight) scrollConversation(!forceScroll);
      parity?.updateJump();
      return true;
    } catch (error) {
      if (request !== data.chatRequest || id !== data.chatId) return false;
      if (data.authenticated) {
        showToast(errorText(error));
        if (!data.messages.length) {
          ui.empty.hidden = true; ui.viewport.hidden = false; $('conversation').classList.remove('is-empty');
          const unavailable = error.status === 404;
          const note = el('div', 'chat-load-error'); note.setAttribute('role', 'status');
          note.append(el('p', '', unavailable ? 'This chat is no longer available. Open Guide to create it again.' : 'Conversation could not load. Check your connection and try again.'));
          const retry = el('button', 'secondary', unavailable ? 'Open Guide' : 'Retry loading'); retry.type = 'button';
          retry.addEventListener('click', () => unavailable ? openGettingStartedGuide() : refreshChat(true)); note.append(retry); ui.list.replaceChildren(note);
          if (unavailable) ui.composer.hidden = true;
        }
      }
      return false;
    }
  }
  function media(attachment) {
    if (attachment?.unavailable || attachment?.kind === 'unavailable') {
      const frame = el('div', 'attachment attachment-unavailable'); frame.setAttribute('role', 'status');
      frame.append(el('strong', '', attachment.name || 'Image'), el('p', '', attachment.reason || 'Image unavailable')); return frame;
    }
    const url = attachmentUrl(attachment?.url);
    if (!url) return null;
    const kind = attachment.kind;
    const frame = el('div', 'attachment');
    if (kind === 'image') {
      frame.classList.add('image-attachment');
      const link = el('button', 'image-open'); link.type = 'button'; link.setAttribute('aria-label', `Open ${attachment.name || 'image'} full size`);
      link.addEventListener('click', () => openImageLightbox(attachment));
      const image = el('img'); image.src = url; image.alt = attachment.name || 'Attached image'; image.loading = 'lazy';
      image.addEventListener('error', () => { frame.replaceChildren(el('strong', '', attachment.name || 'Image'), el('p', '', 'Image unavailable. The file may have moved or its access changed.')); frame.classList.add('attachment-unavailable'); frame.setAttribute('role', 'status'); });
      link.append(image); frame.append(link);
    } else if (kind === 'video') {
      const video = el('video'); video.src = url; video.controls = true; video.preload = 'metadata'; video.playsInline = true; video.setAttribute('aria-label', attachment.name || 'Attached video'); frame.append(video);
    } else {
      const link = el('a', 'file-link'); link.href = url; link.download = attachment.name || '';
      link.append(el('span', 'file-symbol', '↓'));
      const copy = el('span', 'file-copy'); copy.append(el('strong', '', attachment.name || 'Download file'));
      copy.append(el('small', '', attachment.size == null ? 'Download file' : formatFileSize(attachment.size))); link.append(copy); frame.append(link);
    }
    return frame;
  }
  // Attachment previews never accept arbitrary same-origin URLs or active documents.
  function attachmentUrl(value) {
    const url = safeUrl(value);
    return url && new URL(url).pathname === '/api/file' ? url : null;
  }
  function openImageLightbox(attachment) {
    const url = attachmentUrl(attachment?.url);
    if (!data.authenticated || attachment?.kind !== 'image' || !url) return;
    $('lightboxImage').src = url; $('lightboxImage').alt = attachment.name || 'Attached image';
    $('lightboxName').textContent = attachment.name || 'Attached image';
    if (!$('imageLightbox').open) $('imageLightbox').showModal();
  }
  function closeImageLightbox() {
    if ($('imageLightbox').open) $('imageLightbox').close();
    $('lightboxImage').removeAttribute('src'); $('lightboxImage').alt = ''; $('lightboxName').textContent = '';
  }
  async function openTeamResults(id = null) {
    data.swarmFocus = id; $('swarmResultsDialog').showModal(); await refreshSwarms();
  }
  function teamResultCard(card) {
    const node = el('section', 'card team-result-card'); node.dataset.cardIndex = String(card.index); node.dataset.teamSignature = JSON.stringify(card);
    node.append(el('strong', '', card.goal || 'Team task'), markdown(cleanTeamAnswer(card.summary, card.goal) || 'Helpers are working…', 'team-summary'));
    const overall = (card.workers || []).some((worker) => teamStatus(worker.status) === 'Needs review') ? 'Needs review' : teamStatus(card.status);
    node.append(el('span', 'team-status', overall));
    if (teamStatus(card.status) === 'Needs review' || (card.workers || []).some((worker) => teamStatus(worker.status) === 'Needs review')) node.append(el('p', 'team-review-help', 'Needs review means a helper flagged an issue or could not verify its answer. Open each helper below for the reason.'));
    (card.workers || []).forEach((worker) => {
      const details = el('details', 'team-details');
      details.append(el('summary', '', `${worker.role || 'Helper'} · ${teamStatus(worker.status)}`), markdown(cleanTeamAnswer(worker.answer, card.goal) || 'No answer yet.', 'team-answer-text'));
      if (teamStatus(worker.status) === 'Needs review') details.append(el('p','field-help',worker.issue || 'This helper flagged a problem or did not provide the evidence required for a pass. Open results for details.'));
      node.append(details);
    });
    const actions = el('div', 'card-actions');
    const hasChanges = (card.workers || []).some((w) => w.has_changes === true || Number(w.changed_files) > 0);
    [['Compare', 'compare'], ...(hasChanges ? [['Merge', 'merge']] : []), ['Open results', 'results']].forEach(([label, mode]) => {
      const button = el('button', '', label); button.type = 'button';
      button.addEventListener('click', async () => {
        await openTeamResults(card.swarm_id);
        if (mode === 'merge' && !(data.swarms.find((item) => item.id === card.swarm_id)?.workers || []).some((w) => w.worktree && !w.outcome && w.terminal)) showToast('No completed file changes to merge. Compare the answers in these results.');
      }); actions.append(button);
    }); node.append(actions); return node;
  }
  function teamStatus(status) {
    const value = String(status || 'Working').toLowerCase();
    return ({pass:'Done',done:'Done',issues:'Needs review',failed:'Needs review',error:'Needs review',gap:'Incomplete',blocked:'Blocked',working:'Working',judging:'Comparing'})[value] || status;
  }
  function cleanTeamAnswer(value, goal) {
    let text = visibleHandoffText(value).replace(/^\s*Answer:\s*/i,'').replace(/^\s*(?:PASS|ISSUES|BLOCKED)\s*\n?/i,'').replace(/^\s*(?:Status|Evidence|Files):\s*(?:None|N\/A)?\s*$/gmi,'').trim();
    if (goal && text.toLowerCase().startsWith(String(goal).trim().toLowerCase())) text = text.slice(String(goal).trim().length).replace(/^\s*[:—-]?\s*/,'');
    return text;
  }
  function withoutSpeakerPrefix(value, speaker) {
    let text = String(value || '').trimStart();
    const name = String(speaker || '').trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    if (!name) return text;
    // Strip an actual author label/heading; preserve sentences that merely start with a name.
    const prefix = new RegExp(`^(?:#{1,6}\\s+)?(?:\\*\\*|__)?${name}(?:\\*\\*|__)?(?:\\s*:\\s*|[ \\t]*\\n+|[ \\t]*$)`, 'i');
    while (prefix.test(text)) text = text.replace(prefix, '').trimStart();
    return text;
  }
  function quotePreview(value, speaker, limit = 160) {
    const prose = String(value || '').split('\n').filter((line) => !/^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line)).map((line) => line.includes('|') ? line.replace(/^\s*\||\|\s*$/g, '').replace(/\s*\|\s*/g, ' · ') : line).join('\n');
    const text = withoutSpeakerPrefix(plainInline(withoutSpeakerPrefix(prose, speaker)), speaker);
    if (text.length <= limit) return text;
    const end = text.lastIndexOf(' ', limit);
    return (end > 0 ? text.slice(0, end) : '') + '…';
  }
  function friendlyFolder(path) {
    const parts = String(path || '').replace(/\\/g, '/').split('/').filter(Boolean);
    if ((parts[0] === 'Users' || parts[0] === 'home') && parts.length === 2) return 'Home folder';
    return parts.at(-1) || 'Home folder';
  }
  function visibleHandoffText(value) {
    // Never show protocol lines, including a partially streamed final marker.
    return String(value || '').replace(/^@@handoff[^\n]*(?:\n|$)/gm, '').replace(/\n@@(?:h(?:a(?:n(?:d(?:o(?:f(?:f)?)?)?)?)?)?)?$/, '');
  }
  function pipPicker(a, disabled = false) {
    const wrap = el('fieldset','pip-style-picker'); wrap.append(el('legend','','Pip style'));
    const spec = window.Pips?.pipFor(a) || {palette:'blue',accessory:'none',eyes:'dots',antenna:'dot',visor:'round'};
    wrap.dataset.spec = JSON.stringify(spec); wrap.dataset.saved = String(!!a.pip_style);
    const options = {avatar_style:['pip','emoji'],palette:Object.keys(window.Pips?.palettes || {blue:[]}),accessory:window.Pips?.accessories || ['none'],eyes:window.Pips?.eyes || ['dots']};
    const labels={avatar_style:'Avatar',palette:'Colour',accessory:'Accessory',eyes:'Eyes'};
    const preview = el('div','pip-style-preview');
    for(const [key,values] of Object.entries(options)) { const label=el('label','',labels[key]),select=el('select'); select.name=key;select.disabled=disabled;
      select.append(...values.map((value)=>{const option=el('option','',value.replaceAll('_',' '));option.value=value;return option;}));select.value=key==='avatar_style' ? a.avatar_style || 'pip' : spec[key];label.append(select);wrap.append(label);
      select.addEventListener('change',()=>{wrap.dataset.touched='true'; const style=readPipPicker(wrap);preview.replaceChildren(avatar(a.emoji || '🤖',null,'',{...a,...style}));});
    }
    preview.append(avatar(a.emoji || '🤖',null,'',a));wrap.append(preview);return wrap;
  }
  function readPipPicker(wrap) {
    const picker=wrap.classList.contains('pip-style-picker') ? wrap : wrap.querySelector('.pip-style-picker');
    if(!picker)return {avatar_style:'pip'};
    if(picker.dataset.saved !== 'true' && picker.dataset.touched !== 'true')return {avatar_style:picker.querySelector('[name=avatar_style]').value};
    const style=JSON.parse(picker.dataset.spec || '{}');
    ['palette','accessory','eyes'].forEach((key)=>{style[key]=picker.querySelector(`[name=${key}]`).value;});
    return {avatar_style:picker.querySelector('[name=avatar_style]').value,pip_style:style};
  }
  async function openGettingStartedGuide() {
    const guide = data.agents.find((a) => a.guide);
    if (guide) return openChat(directId(guide.id));
    openDirectory('agents');
    $('directoryShowHidden').checked = true; renderDirectory();
    showToast('Restore Guide from All Pips to open your setup helper.');
  }
  async function guidePrompt(text) {
    const guide=data.agents.find((a)=>a.guide);
    if(guide)await openChat(directId(guide.id));
    ui.message.value=text;ui.message.dispatchEvent(new Event('input'));ui.message.focus();
  }
  function guideStarters() {
    const node=el('div','guide-starters');
    ['Make me a Pip that…','Set up a group for…','What can you do?','Try the Chef and Critic demo'].forEach((text)=>{const button=el('button','secondary',text);button.type='button';button.addEventListener('click',()=> text.includes('Chef and Critic') ? proposalDecision(button,'/api/guide/demo',{}) : guidePrompt(text));node.append(button);});return node;
  }
  async function proposalDecision(button,path,payload) {
    if(button.disabled)return;button.disabled=true;
    try { const response=await post(path,payload);showCreatedToast(response);await refreshState();await refreshChat();
      const result=response.result || response;
      if(result.demo_chat_id)await openChat(result.demo_chat_id);
    } catch(error){showToast(errorText(error));} finally{button.disabled=false;}
  }
  function proposalCard(card,message) {
    const node=el('section','card proposal-card');node.dataset.cardIndex=String(card.index);node.dataset.proposalSignature=JSON.stringify(card);
    const p=card.proposal || {}, head=el('div','proposal-head');
    const proposalAgent = card.result?.agent || {...p, id:String(p.name || '').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,''), role:p.instructions};
    head.append(avatar(proposalAgent.emoji,null,'',proposalAgent),el('strong','',p.name || (p.action==='start_team_task' ? 'Team task' : 'New Pip')));node.append(head);
    if(card.demo)node.append(el('span','demo-label','Chef and Critic demo'));
    node.append(el('p','',p.title || p.task || (p.action==='create_group' ? 'A group for your Pips' : '')));
    const members = (p.agents || []).map((a) => typeof a === 'string' ? `Member: ${a}` : `${a.name} · ${a.engine === 'claude' ? 'Claude Code' : 'Codex'} · ${a.model}\n${a.title || ''}\n${a.instructions || ''}${a.workdir ? `\nWorking folder: ${friendlyFolder(a.workdir)}` : ''}`);
    if(p.group) node.append(el('p','proposal-group',`Group: ${p.group}`));
    const details=el('details','proposal-instructions');details.append(el('summary','','Instructions'),el('p','',p.instructions || members.join('\n\n') || p.task || ''));
    node.append(details);
    const chips=el('div','proposal-chips');[p.engine ? `Engine: ${p.engine === 'claude' ? 'Claude Code' : 'Codex'}` : '',p.model ? `Model: ${p.model}` : '',p.mode,p.workdir ? `Folder: ${friendlyFolder(p.workdir)}` : ''].filter(Boolean).forEach((value)=>chips.append(el('span','reply-model',value)));node.append(chips);
    if(card.status==='archived') node.append(el('p','decision','Archived'));
    else if(card.status==='created') { const result=card.result || {},cid=result.chat_id || result.chat?.id || (result.agent?.id ? directId(result.agent.id) : result.source_chat_id);
      const open=el('button','secondary','Created · Open chat →');open.type='button';open.disabled=!cid;open.addEventListener('click',()=>openChat(cid));node.append(open);
      if(card.demo){const archive=el('button','text-button','Archive demo');archive.type='button';archive.addEventListener('click',async()=>{if(!inlineAction(archive,'Confirm archive?'))return;await proposalDecision(archive,'/api/guide/demo/archive',{});});node.append(archive);}
    } else if(card.status==='dismissed')node.append(el('p','decision','No thanks · dismissed'));
    else if(card.status && card.status!=='pending')node.append(el('p','form-error',card.error || 'Creation is in progress. If it was interrupted, inspect existing Pips and groups before continuing.'));
    else { const actions=el('div','card-actions');[['Create','create'],['Edit first','edit'],['No thanks','dismiss']].forEach(([label,action])=>{const button=el('button',action==='create'?'primary':'secondary',label);button.type='button';button.addEventListener('click',()=> {if(action==='edit')return editProposal(card,message);return proposalDecision(button,'/api/guide/proposal',{message_id:message.id,index:card.index,action});});actions.append(button);});node.append(actions);}
    return node;
  }
  function syncBrowserChoice(browser, sealed, external = false) {
    if (sealed) {
      if (browser.dataset.browserSealed !== 'true') browser.dataset.browserChecked = String(browser.checked);
      browser.checked = false;
    } else if (browser.dataset.browserSealed === 'true') browser.checked = browser.dataset.browserChecked === 'true';
    browser.dataset.browserSealed = String(sealed);
    browser.disabled = sealed || external;
  }
  function syncCreateBrowser(reset = false) {
    const sealed = $('agentPrivatePip').checked || $('agentDraftOnly').checked;
    if (reset === true) delete $('agentChrome').dataset.browserSealed;
    syncBrowserChoice($('agentChrome'), sealed);
    $('agentBrowserReason').hidden = !sealed;
  }
  function editProposal(card,message) {
    const p=card.proposal, edit={message_id:message.id,index:card.index,proposal:p};
    if(p.action==='create_agent') { $('newAgentButton').click();data.proposalEdit=edit;
      $('agentName').value=p.name || '';$('agentTitle').value=p.title || '';$('agentEmoji').value=p.emoji || '';$('agentRole').value=p.instructions || '';$('agentEngine').value=p.engine || 'claude';modelSelect($('agentModel'),p.engine,p.model);$('agentWorkdir').value=p.workdir || '';$('agentPrivatePip').checked=!!p.private_pip;$('agentDraftOnly').checked=!!p.draft_only;$('agentChrome').checked=!!p.chrome;syncCreateBrowser(true);
      $('agentPipStyle').replaceChildren(pipPicker({id:`proposal-${message.id}-${card.index}`,...p}));
    } else if(p.action==='create_group') { $('newGroupButton').click();data.proposalEdit=edit;$('groupName').value=p.name || '';$('groupEmoji').value=p.emoji || '👥';
      const names=(p.agents || []).filter((a)=>typeof a==='string').map((a)=>a.toLowerCase());
      ui.groupAgents.querySelectorAll('input').forEach((input)=>{const a=agent(input.value);input.checked=names.includes(input.value.toLowerCase()) || names.includes(a?.name.toLowerCase());});
      (p.agents || []).filter((a)=>typeof a==='object').forEach((a,index)=>{const label=el('label'),check=el('input');check.type='checkbox';check.name='agents';check.value=`new:${index}`;check.checked=true;label.append(check,el('span','',`${a.name} (new Pip)`));ui.groupAgents.append(label);});
    } else { prepareTeam({agents:p.agents || data.chats.find((c)=>c.id===p.group || c.name===p.group)?.agents || [],name:'Proposed team'}).then(()=>{$('swarmGoal').value=p.task || '';$('swarmShape').value=({split:'partition',race:'race',roles:'roles'})[p.mode] || 'partition'; $('swarmShape').dispatchEvent(new Event('change')); if(p.mode==='race')$('swarmRubric').value='Addresses the task\nUses clear reasoning\nIs practical'; data.proposalEdit=edit;}).catch((error)=>showToast(errorText(error))); }
  }
  async function archiveDirectory() {
    const button=$('directoryArchive');if(button.disabled)return;
    if (!inlineAction(button,'Confirm archive?')) return;
    button.disabled=true;
    try { for(const id of [...data.directorySelected]) { await post('/api/archive',{kind:data.directoryKind==='groups'?'group':'agent',id});data.directorySelected.delete(id); } await refreshState();renderDirectory(); }
    catch(error){await refreshState();renderDirectory();showToast(errorText(error));}
    finally{button.disabled=!data.directorySelected.size;}
  }
  function cardNode(card, message) {
    if (card.kind === 'signin_request' || card.kind === 'login_fill_request') return window.HubPipBrowser?.card(card, message) || el('div', 'card');
    if (card.kind === 'proposal') return proposalCard(card, message);
    if (card.kind === 'guide_starters') return guideStarters();
    if (card.kind === 'team_task') return teamResultCard(card);
    if (card.kind === 'approval_request') {
      const node = window.HubAccess.card({ summary: card.summary ?? card.title ?? '', details: card.details ?? card.text ?? '', destination: card.destination }, card.decision ? String(card.decision).toLowerCase().includes('approv') ? 'approved' : 'denied' : null, async (_request, approved) => {
        const action = approved ? 'Approve' : "Don't";
        try {
          await post('/api/card', { chat_id: message.chat_id || data.chatId, message_id: message.id, index: card.index, action, request_id: crypto.randomUUID() });
          await refreshChat();
        } catch (error) { showToast(errorText(error)); throw error; }
      });
      node.classList.add('card'); node.dataset.cardIndex = String(card.index); node.dataset.approvalSignature = JSON.stringify(card);
      return node;
    }
    const node = el('div', 'card'); node.dataset.cardIndex = String(card.index);
    if (card.title) node.append(el('strong', '', card.title));
    if (card.text) node.append(el('p', '', card.text));
    if (card.media) { const attachment = media(card.media); if (attachment) node.append(attachment); }
    const controls = el('div', 'card-controls'); node.append(controls);
    updateCard(node, card, message);
    return node;
  }
  function updateCard(node, card, message) {
    if (card.kind === 'approval_request') { if (node.dataset.approvalSignature !== JSON.stringify(card)) node.replaceWith(cardNode(card, message)); return; }
    if (card.kind === 'signin_request' || card.kind === 'login_fill_request') { window.HubPipBrowser?.updateCard(node, card, message); return; }
    if (card.kind === 'proposal' || card.kind === 'guide_starters') { if (node.dataset.proposalSignature !== JSON.stringify(card)) node.replaceWith(cardNode(card,message)); return; }
    if (card.kind === 'team_task') { if (node.dataset.teamSignature !== JSON.stringify(card)) node.replaceWith(teamResultCard(card)); return; }
    const controls = node.querySelector('.card-controls');
    const decision = card.decision == null ? '' : String(card.decision);
    if (node.dataset.decision === decision && node.dataset.actions === JSON.stringify(card.actions || [])) return;
    node.dataset.decision = decision; node.dataset.actions = JSON.stringify(card.actions || []);
    controls.replaceChildren();
    if (decision) { controls.append(el('div', 'decision', `Decision: ${decision}`)); return; }
    const actions = Array.isArray(card.actions) ? card.actions : [];
    if (!actions.length) return;
    const row = el('div', 'card-actions');
    actions.forEach((action) => {
      const button = el('button', '', action); button.type = 'button';
      button.addEventListener('click', async () => {
        if (row.dataset.pending === 'true') return;
        if (destructiveAction(action) && !inlineAction(button,`Confirm ${action.toLowerCase()}?`)) return;
        row.dataset.pending = 'true'; row.querySelectorAll('button').forEach((b) => { b.disabled = true; }); button.textContent = 'Saving…';
        try {
          await post('/api/card', { chat_id: message.chat_id || data.chatId, message_id: message.id, index: card.index, action, request_id: crypto.randomUUID() });
          await refreshChat();
        } catch (error) { showToast(errorText(error)); row.dataset.pending = 'false'; row.querySelectorAll('button').forEach((b) => { b.disabled = false; }); button.textContent = action; }
      });
      row.append(button);
    });
    controls.append(row);
  }
  function quotedMessages(message) {
    const ids = Array.isArray(message.reply_to) ? message.reply_to : message.reply_to == null ? [] : [message.reply_to];
    return ids.map((id) => ({ id, parent: data.messages.find((m) => String(m.id) === String(id)) || (String(message.reply_parent?.id) === String(id) ? message.reply_parent : null) }));
  }
  function quotedText(message) {
    const first = quotedMessages(message)[0];
    return first?.parent ? (first.parent.text || first.parent.cards?.[0]?.title || first.parent.card_title || first.parent.attachments?.[0]?.name || first.parent.attachment_name || 'Earlier message') : 'Earlier message';
  }
  function agentSettings(body, a) {
    const external = a.linked === true || a.swarm === true || a.source === 'external' || a.external === true || a.managed === false;
    const form = el('form', 'agent-settings-form');
    if (external) form.append(el('p', 'field-help', a.linked ? 'Linked Pip · Instructions are read only. Edit its source folder to change them. Hiding this Pip leaves its source folder untouched.' : 'Imported Pip settings are read only. Edit its source folder to change them.'));
    const field = (labelText, name, value, kind = 'input') => { const label = el('label', '', labelText); const input = el(kind); input.name = name; input.value = value == null ? '' : String(value); input.disabled = external; if (kind === 'textarea') input.rows = 7; label.append(input); form.append(label); return input; };
    field('Name', 'name', a.name); field('One-line title', 'title', a.title);
    const emoji = field('Emoji', 'emoji', a.emoji || '🤖'); emoji.maxLength = 64;
    if (!external) { const picker = iconButton('plus', 'Choose emoji', 'emoji-open'); picker.addEventListener('click', () => window.HubEmoji?.open(emoji)); form.append(picker); }
    const stylePicker = pipPicker(a, external); form.append(stylePicker);
    const engine = field('AI provider', 'engine', a.engine || 'claude', 'select'); engine.replaceChildren(...['claude','codex'].map((name) => { const option = el('option', '', name === 'claude' ? 'Claude' : 'Codex'); option.value = name; return option; })); engine.value = a.engine || 'claude';
    const model = field('Model', 'model', a.model || '', 'select'); modelSelect(model, engine.value, a.model); engine.addEventListener('change', () => modelSelect(model, engine.value));
    const workdir = field('Working folder', 'workdir', a.workdir || '');
    field('Instructions', 'instructions', a.instructions ?? a.role ?? '', 'textarea');
    const check = (labelText, name, checked, help) => { const line = el('label', 'check-line'); const input = el('input'); input.type = 'checkbox'; input.name = name; input.checked = !!checked; input.disabled = external; line.append(input, el('span', '', labelText)); form.append(line, el('small', 'field-help', help)); return input; };
    let privateCheck, draftCheck;
    if (!external) {
      privateCheck = check('Private Pip', 'private_pip', a.private_pip, 'Skips your global instructions, skills, plugins, and MCP configuration. This does not sandbox the computer. Off by default.');
      draftCheck = check('Draft only', 'draft_only', a.draft_only, 'Chat-only prose drafts. No file writes, sends, posts, or team delegation. Incoming group handoffs keep these limits.');
    }
    const browserCheck = check('Can use Pip browser', 'chrome', a.chrome, 'Allows this Pip to use a separate persistent Chrome profile. Off by default.');
    const browserReason = el('small', 'field-help', 'Pip browser is unavailable in Private Pip or Draft only.'); browserReason.hidden = true; form.append(browserReason);
    const syncBrowser = () => { const sealed = !!(privateCheck?.checked || draftCheck?.checked); syncBrowserChoice(browserCheck, sealed, external); browserReason.hidden = !sealed; };
    privateCheck?.addEventListener('change', syncBrowser); draftCheck?.addEventListener('change', syncBrowser); syncBrowser();
    if (!external) { const error = el('p','form-error'); error.hidden=true; error.setAttribute('role','alert'); const save = el('button', 'primary', 'Save Pip settings'); save.type = 'submit'; const actions=el('div','modal-actions');actions.append(error,save);form.append(actions); form.addEventListener('submit', async (event) => { event.preventDefault(); if (save.disabled) return; error.hidden=true;workdir.setAttribute('aria-invalid','false'); save.disabled = true; const payload = { ...readPipPicker(stylePicker), id: a.id, name: form.querySelector('[name=name]').value.trim(), title: form.querySelector('[name=title]').value.trim(), emoji: emoji.value.trim(), engine: engine.value, model: model.value, workdir: workdir.value.trim(), instructions: form.querySelector('[name=instructions]').value, private_pip: privateCheck.checked, draft_only: draftCheck.checked, chrome: browserCheck.checked }; try { await post('/api/agents/update', payload); await refreshState(); closeDialog($('manageDialog')); showToast('Pip settings saved. Changes take effect on the next turn.'); } catch (failure) { error.textContent=errorText(failure);error.hidden=false;if(/working folder|workdir/i.test(error.textContent))workdir.setAttribute('aria-invalid','true');error.scrollIntoView({block:'nearest'}); } finally { save.disabled = false; } }); }
    body.append(form);
    if (external) {
      const access = el('form', 'pip-access-form');
      access.append(el('h3', '', 'Pip access'));
      for (const [name, label, checked, help] of [
        ['private_pip', 'Private Pip', a.private_pip, 'Skips your global instructions, skills, plugins, and MCP configuration. This does not sandbox the computer. Off by default.'],
        ['draft_only', 'Draft only', a.draft_only, 'Chat-only prose drafts. No file writes, sends, posts, or team delegation.']
      ]) {
        const line = el('label', 'check-line'), input = el('input'); input.type = 'checkbox'; input.name = name; input.checked = !!checked;
        line.append(input, el('span', '', label)); access.append(line, el('small', 'field-help', help));
      }
      privateCheck = access.querySelector('[name=private_pip]'); draftCheck = access.querySelector('[name=draft_only]');
      privateCheck.addEventListener('change', syncBrowser); draftCheck.addEventListener('change', syncBrowser); syncBrowser();
      const error = el('p', 'form-error'); error.hidden = true; error.setAttribute('role', 'alert');
      const save = el('button', 'primary', 'Save Pip access'); save.type = 'submit';
      const actions = el('div', 'modal-actions'); actions.append(error, save); access.append(actions);
      access.addEventListener('submit', async (event) => {
        event.preventDefault(); if (save.disabled) return; save.disabled = true; error.hidden = true;
        try { await patchAgentAccess(a.id, access.querySelector('[name=private_pip]').checked, access.querySelector('[name=draft_only]').checked); await refreshState(); closeDialog($('manageDialog')); showToast('Pip access saved. Changes take effect on the next turn.'); }
        catch (failure) { error.textContent = errorText(failure); error.hidden = false; }
        finally { save.disabled = false; }
      });
      body.append(access);
    }
  }
  function quoteStack(message, includeUser = true) {
    const stack = el('div', 'quote-stack');
    quotedMessages(message).forEach(({ id, parent }) => {
      if (!includeUser && parent?.role === 'user') return;
      const speaker = parent?.role === 'user' ? 'You' : agent(parent?.agent_id)?.name || 'Pip';
      const quote = el('button', 'quoted', `${speaker}: ${quotePreview(parent?.text || parent?.cards?.[0]?.title || parent?.card_title || parent?.attachments?.[0]?.name || parent?.attachment_name || 'Earlier message', speaker)}`);
      quote.type = 'button'; quote.addEventListener('click', () => {
        const target = [...ui.list.children].find((child) => child.dataset.messageId === String(id));
        if (target) { target.scrollIntoView({ block: 'center', behavior: 'smooth' }); target.classList.add('message-flash'); setTimeout(() => target.classList.remove('message-flash'), 1500); }
      }); stack.append(quote);
    });
    return stack;
  }
  function addReply(id) {
    if (data.replyTo.includes(id)) return;
    if (data.replyTo.length >= 5) { showToast('Reply to up to 5 messages at once.'); return; }
    data.replyTo.push(id); renderReply(); ui.message.focus();
  }
  function confirmationText(action, title) { const clean = plainInline(title || 'this decision').replace(new RegExp(`^${action}\\s+`, 'i'), ''); return `${action[0].toUpperCase()}${action.slice(1)} ${clean}?`; }
  async function react(message, emoji, button) {
    closeMessagePopover();
    const remove = (message.reactions || []).includes(emoji);
    if (!remove && message.role === 'assistant' && ['👍','✅','👎'].includes(emoji)) {
      const eligible = (message.cards || []).filter((card) => card && !card.decision && (card.kind === 'proposal'
        ? agent(message.agent_id)?.guide && (card.status == null || card.status === 'pending')
        : card.kind === 'approval_request' || Array.isArray(card.actions) && card.actions.length));
      if (eligible.length > 1) { showToast('Use the card’s buttons'); return; }
    }
    button.disabled = true;
    try {
      let result = await post('/api/reaction', { message_id: message.id, emoji, remove, active: !remove, request_id: crypto.randomUUID() });
      if (result.confirmation_required) {
        const action = result.card_action || result.action || (['👍','✅'].includes(emoji) ? 'Approve' : 'Deny');
        if (destructiveAction(action) && !inlineAction(button,confirmationText(action, result.title))) return;
        result = await post('/api/reaction', { message_id: message.id, emoji, remove, active: !remove, confirm: true, request_id: crypto.randomUUID() });
      }
      if (result.guide_result) showCreatedToast(result.guide_result);
      if (Array.isArray(result.reactions)) {
        message.reactions = result.reactions;
        const node = [...ui.list.children].find((item) => item.dataset.messageId === String(message.id));
        if (node) replaceReactions(node, message);
      }
      await refreshChat();
    } catch (error) { showToast(errorText(error)); }
    finally { button.disabled = false; }
  }
  function resizeComposer() {
    ui.message.style.height = 'auto';
    ui.message.style.height = `${Math.min(Math.max(38, ui.message.scrollHeight || 38), window.innerHeight * .4)}px`;
    positionToast();
  }
  function reactionBar(message, previous = []) {
    const wrap = el('div', 'reaction-wrap'), chosen = el('div', 'reaction-chosen');
    [...new Set(message.reactions || [])].forEach((emoji) => { const button = el('button', 'reaction-chip', emoji); button.type = 'button'; button.setAttribute('aria-label', `Remove reaction ${emoji}`); button.addEventListener('click', () => react(currentMessage(message), emoji, button)); if (!previous.includes(emoji)) motionFeedback(button, 'reaction-pop'); chosen.append(button); });
    wrap.hidden = !chosen.children.length; wrap.append(chosen);
    return wrap;
  }
  function replaceReactions(node, message) {
    const wrap = node.querySelector('.reaction-wrap');
    if (!wrap) return;
    const previous = [...wrap.querySelectorAll('.reaction-chip')].map((chip) => chip.textContent);
    const next = [...new Set(message.reactions || [])];
    if (JSON.stringify(previous) !== JSON.stringify(next)) wrap.replaceWith(reactionBar(message, previous));
  }

  // Message actions: two hover buttons, one floating picker/menu, measured folding.
  const quickReactions = ['👍', '👎', '❤️', '❓'];
  let messagePopover = null, messageMeasurePending = false;
  function currentMessage(message) { return data.messages.find((item) => String(item.id) === String(message.id)) || message; }
  function closeMessagePopover(restoreFocus = false) {
    if (!messagePopover) return;
    const { panel, trigger, owner } = messagePopover; messagePopover = null;
    panel.remove(); owner.classList.remove('message-menu-open'); trigger?.setAttribute('aria-expanded', 'false');
    if (restoreFocus) { if (trigger?.isConnected) trigger.focus(); else if (owner.isConnected) owner.focus(); }
  }
  function positionMessagePopover() {
    if (!messagePopover) return;
    const { panel, anchor } = messagePopover, rect = anchor.getBoundingClientRect();
    const view = window.visualViewport, left = view?.offsetLeft || 0, top = view?.offsetTop || 0;
    const width = view?.width || window.innerWidth, height = view?.height || window.innerHeight;
    const w = panel.offsetWidth || 240, h = panel.offsetHeight || 52;
    const x = Math.max(left + 8, Math.min(rect.left, left + width - w - 8));
    const y = rect.top - h - 8 >= top + 8 ? rect.top - h - 8 : Math.min(rect.bottom + 8, top + height - h - 8);
    panel.style.left = `${x}px`; panel.style.top = `${Math.max(top + 8, y)}px`;
  }
  function showMessagePopover(panel, anchor, owner, trigger, touchPointerId = null) {
    // Capture before dismissing: a touch menu's React button is removed on switch.
    const rect = anchor.getBoundingClientRect(); anchor = { getBoundingClientRect: () => rect };
    closeMessagePopover(); panel.setAttribute('role', 'dialog');
    document.body.append(panel); messagePopover = { panel, anchor, owner, trigger, touchPointerId, ignoreOwnerUntil: touchPointerId == null ? 0 : Infinity };
    owner.classList.add('message-menu-open'); trigger?.setAttribute('aria-expanded', 'true');
    positionMessagePopover(); panel.querySelector('button')?.focus();
    panel.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeMessagePopover(true); }
      else if (['ArrowRight','ArrowLeft','ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
        const buttons = [...panel.querySelectorAll('button')], index = buttons.indexOf(document.activeElement);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (['ArrowLeft','ArrowUp'].includes(event.key) ? -1 : 1) + buttons.length) % buttons.length;
        event.preventDefault(); buttons[next]?.focus();
      }
    });
  }
  function openMessageReactions(message, trigger, owner) {
    if (messagePopover?.trigger === trigger) { closeMessagePopover(); return; }
    const panel = el('div', 'message-popover message-reaction-picker'); panel.setAttribute('aria-label', 'Reactions');
    quickReactions.forEach((emoji) => {
      const button = el('button', 'reaction-button', emoji); button.type = 'button'; button.title = `React ${emoji}`;
      button.setAttribute('aria-label', button.title); button.setAttribute('aria-pressed', String((currentMessage(message).reactions || []).includes(emoji)));
      button.addEventListener('click', () => react(currentMessage(message), emoji, button)); panel.append(button);
    });
    const more = iconButton('more', 'More reactions', 'reaction-button');
    more.addEventListener('click', () => { closeMessagePopover(); window.HubEmoji?.open(null, (emoji) => react(currentMessage(message), emoji, more)); }); panel.append(more);
    showMessagePopover(panel, trigger, owner, trigger);
  }
  async function copyMessage(message) {
    closeMessagePopover();
    try { await navigator.clipboard.writeText(currentMessage(message).text || ''); showToast('Copied.'); } catch { showToast('Copy unavailable in this browser.'); }
  }
  function retryMessage(message) {
    closeMessagePopover(); message = currentMessage(message);
    const index = data.messages.findIndex((item) => String(item.id) === String(message.id));
    const parent = quotedMessages(message).map((q) => q.parent).find((item) => item?.role === 'user') || data.messages.slice(0, index < 0 ? undefined : index).reverse().find((item) => item.role === 'user');
    if (!parent) { showToast('No earlier question to retry.'); return; }
    ui.message.value = parent.text || ''; data.replyTo = [parent.id]; renderReply(); ui.composer.requestSubmit();
  }
  function openMessageMenu(message, node, anchor = node.querySelector('.message-body') || node, trigger = null, touchPointerId = null) {
    const panel = el('div', 'message-popover message-context-menu'); panel.setAttribute('aria-label', 'Message actions');
    const action = (name, label, fn) => { const button = iconButton(name, label); button.append(el('span', '', label)); button.addEventListener('click', () => fn(button)); panel.append(button); return button; };
    action('react', 'React', (button) => openMessageReactions(message, button, node));
    action('reply', 'Reply', () => { closeMessagePopover(); addReply(message.id); });
    action('copy', 'Copy message', () => copyMessage(message));
    if (message.role === 'user' && parity) action('edit', 'Edit and resend', () => { closeMessagePopover(); parity.startEdit(message); });
    if (message.role === 'assistant') action('retry', 'Retry answer', () => retryMessage(message));
    showMessagePopover(panel, anchor, node, trigger, touchPointerId);
  }
  function messageActions(message, node) {
    const actions = el('div', 'message-actions'); actions.setAttribute('aria-label', 'Message actions');
    const action = (name, label, fn) => { const button = iconButton(name, label, `message-${name}`); button.addEventListener('click', () => fn(button)); actions.append(button); return button; };
    const reactButton = action('react', 'React', (button) => openMessageReactions(message, button, node));
    reactButton.setAttribute('aria-haspopup', 'dialog'); reactButton.setAttribute('aria-expanded', 'false');
    action('reply', 'Reply', () => { closeMessagePopover(); addReply(message.id); });
    node.tabIndex = 0;
    node.addEventListener('contextmenu', (event) => { if (event.target?.closest?.('button,a,input,video')) return; event.preventDefault(); if (messagePopover?.owner === node && Date.now() < messagePopover.ignoreOwnerUntil) return; openMessageMenu(message, node); });
    node.addEventListener('keydown', (event) => { if (event.target !== node) return; if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) { event.preventDefault(); openMessageMenu(message, node, undefined, reactButton); } });
    return actions;
  }
  function measureMessageOverflow(content) {
    const body = content.querySelector('.message-body'); if (!body || !content.classList.contains('group-answer')) return;
    const expanded = content.classList.contains('expanded'); content.classList.remove('expanded');
    if (!body.clientHeight) { if (expanded) content.classList.add('expanded'); return; }
    const overflows = body.scrollHeight > body.clientHeight + 1;
    let toggle = content.querySelector('.group-show-more');
    if (!overflows) { toggle?.remove(); return; }
    if (expanded) content.classList.add('expanded');
    if (!toggle) { toggle = el('button', 'group-show-more'); toggle.type = 'button'; toggle.addEventListener('click', () => { const open = content.classList.toggle('expanded'); toggle.textContent = open ? 'Show less' : 'Show more'; toggle.setAttribute('aria-expanded', String(open)); }); content.append(toggle); }
    toggle.textContent = expanded ? 'Show less' : 'Show more'; toggle.setAttribute('aria-expanded', String(expanded));
  }
  function scheduleMessageMeasurements() {
    if (messageMeasurePending) return; messageMeasurePending = true;
    requestAnimationFrame(() => { messageMeasurePending = false; ui.list.querySelectorAll('.group-answer').forEach(measureMessageOverflow); });
  }
  function setupMessageInteractions() {
    const touchRelease = (event) => { if (messagePopover?.touchPointerId === event.pointerId) { messagePopover.touchPointerId = null; messagePopover.ignoreOwnerUntil = Date.now() + 400; } };
    const releasedOnOwner = (event) => messagePopover && Date.now() < messagePopover.ignoreOwnerUntil && messagePopover.owner.contains(event.target);
    document.addEventListener('pointerup', touchRelease, true);
    document.addEventListener('pointercancel', touchRelease, true);
    document.addEventListener('click', (event) => { if (releasedOnOwner(event)) { event.preventDefault(); event.stopPropagation(); } }, true);
    document.addEventListener('pointerdown', (event) => { if (messagePopover && !messagePopover.panel.contains(event.target) && !messagePopover.trigger?.contains(event.target)) closeMessagePopover(); });
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeMessagePopover(true); });
    document.addEventListener('focusin', (event) => { if (!releasedOnOwner(event) && messagePopover && !messagePopover.panel.contains(event.target) && !messagePopover.trigger?.contains(event.target)) closeMessagePopover(); });
    const resize = () => { closeMessagePopover(); scheduleMessageMeasurements(); positionToast(); fitChatTitle(); };
    window.addEventListener('resize', resize); window.visualViewport?.addEventListener('resize', resize);
    window.visualViewport?.addEventListener('scroll', positionToast);
    ui.viewport.addEventListener('scroll', () => closeMessagePopover());
    ui.list.addEventListener('load', scheduleMessageMeasurements, true);
    if (typeof ResizeObserver === 'function') { const observer = new ResizeObserver(scheduleMessageMeasurements); observer.observe(ui.list); }
    if (typeof ResizeObserver === 'function') new ResizeObserver(positionToast).observe(ui.composer);
    document.fonts?.ready.then(scheduleMessageMeasurements);
  }
  function routingNote(message, a) {
      const name = message.best_fit_agent_name || a?.name || 'Pip';
      const note = el('div', 'best-fit-note', message.routing_kind === 'directed' ? `${name} answered, you asked for ${name}. ` : `${name} answered — ${message.routing_kind === 'tie' ? 'tie' : 'best fit'}. `);
      const askAgain = (mention) => { const causal = quotedMessages(message).map((x) => x.parent).find((item) => item?.role === 'user'); const index = data.messages.findIndex((item) => String(item.id) === String(message.id)); const earlier = causal || data.messages.slice(0, index < 0 ? undefined : index).reverse().find((item) => item.role === 'user'); data.replyTo = Array.isArray(earlier?.reply_to) ? [...earlier.reply_to] : earlier?.reply_to == null ? [] : [earlier.reply_to]; renderReply(); ui.message.value = `${mention} ${String(earlier?.text || '').replace(/^@(?:all|\S+)\s+/i, '')}`.trim(); ui.message.focus(); if (earlier?.text) ui.composer.requestSubmit(); };
      if (message.routing_kind === 'tie') { const picker = el('select', 'tie-agent-picker'); picker.setAttribute('aria-label', 'Pick another Pip'); const first = el('option', '', 'Pick another ▾'); first.value = ''; picker.append(first); (currentChat()?.agents || []).filter((id) => String(id) !== String(message.agent_id)).forEach((id) => { const candidate = agent(id); if (!candidate) return; const option = el('option', '', candidate.name); option.value = candidate.id; picker.append(option); }); picker.addEventListener('change', () => { if (picker.value) askAgain(`@${picker.value}`); picker.value = ''; }); note.append(picker); }
      const ask = el('button', '', 'Ask everyone'); ask.type = 'button'; ask.addEventListener('click', () => askAgain('@all')); note.append(ask); return note;
  }
  function messageNode(message, target = null) {
    const isUser = message.role === 'user', isSystem = message.role === 'system';
    const node = target || el('article'); if(target)node.replaceChildren(); node.className = `message ${isUser ? 'user' : isSystem ? 'system' : 'assistant'}`; node.dataset.messageId = String(message.id); if(message.request_id)node.dataset.requestId=message.request_id; if(message.job_id)node.dataset.jobId=String(message.job_id); node.dataset.cardsSignature=JSON.stringify(message.cards || []);
    if ((message.cards || []).some((card) => card.kind === 'team_task')) node.classList.add('team-task-message');
    const a = agent(message.agent_id);
    const content = el('div', 'message-content');
    node.dataset.textSignature = message.text || '';
    const files = el('div', 'attachment-list'), renderedImages = [];
    (message.attachments || []).forEach((attachment) => { const item = media(attachment); if (item) { files.append(item); if (attachment.kind === 'image' && item.querySelector('img')) renderedImages.push({ attachment, image: item.querySelector('img') }); } });
    const displayText = () => {
      const characters = Array.from(message.text || '');
      const spans = renderedImages.flatMap(({ attachment }) => attachment.file_marker_spans || []).filter((span) => Array.isArray(span) && span.length === 2 && span.every(Number.isSafeInteger) && span[0] >= 0 && span[1] > span[0] && span[1] <= characters.length).sort((a,b) => b[0]-a[0]);
      let end = characters.length;
      for (const [start, stop] of spans) if (stop <= end) { characters.splice(start, stop-start); end = start; }
      return characters.join('').trim();
    };
    if (!isSystem) {
      const head = el('div', 'message-head');
      if (!isUser) head.append(avatar(a?.emoji, a?.avatar, 'message-avatar', a));
      head.append(el('strong', '', isUser ? 'You' : a?.name || 'Pip'));
      const when = el('time', '', timeOf(message.created));
      if (message.created) when.dateTime = new Date(Number(message.created) * 1000).toISOString();
      when.title = dateTime(message.created); node.title = dateTime(message.created);
      head.append(when); if (!isUser && message.model) head.append(el('span', 'reply-model', message.model)); content.append(head);
    }
    if (message.reply_to && !isSystem) { const quotes = quoteStack(message, isUser); if (quotes.children.length) content.append(quotes); }
    if ((message.best_fit || ['tie','directed'].includes(message.routing_kind)) && !isUser) content.append(routingNote(message, a));
    const textBody = () => isUser ? el('div', 'message-body', displayText()) : markdown(withoutSpeakerPrefix(visibleHandoffText(displayText()), a?.name), 'message-body');
    let body = message.text ? textBody() : null;
    if (body) content.append(body);
    renderedImages.forEach((entry) => entry.image.addEventListener('error', () => { const index = renderedImages.indexOf(entry); if (index >= 0) renderedImages.splice(index, 1); if (body) { const replacement = textBody(); body.replaceWith(replacement); body = replacement; } }));
    if (isSystem && message.usage_limit) { const limit = message.usage_limit; const actions = el('div', 'card-actions usage-actions'); const retry = el('button', '', 'Retry'); retry.addEventListener('click', async () => { retry.disabled = true; try { await post('/api/jobs/retry', { job_id: limit.job_id }); await refreshChat(); } catch (error) { showToast(errorText(error)); } finally { retry.disabled = false; } }); actions.append(retry); if (limit.alternate_engine) { const alternate = el('button', '', `Try with ${limit.alternate_engine === 'codex' ? 'Codex' : 'Claude'}`); alternate.addEventListener('click', async () => { alternate.disabled = true; try { await post('/api/jobs/retry', { job_id: limit.job_id, engine: limit.alternate_engine }); await refreshChat(); } catch (error) { showToast(errorText(error)); } finally { alternate.disabled = false; } }); actions.append(alternate); } content.append(actions); node.classList.add('usage-limit'); }
    if (files.children.length) content.append(files);
    if (a?.guide && message.starters) { content.append(guideStarters()); const scanOffer=window.HubOnboarding?.offerCard(); if(scanOffer)content.append(scanOffer); }
    if (Array.isArray(message.cards) && message.cards.length) {
      const cards = el('div', 'card-list'); message.cards.forEach((card) => cards.append(cardNode(card, message)));
      if (message.cards.filter((card) => card.kind === 'proposal').length > 1 && message.cards.some((card) => card.kind === 'proposal' && card.status === 'pending')) { if(message.cards.some((card)=>card.demo))cards.append(el('p','field-help','This demo uses your signed-in CLI and may take longer than 30 seconds.')); const all = el('button','primary','Create all'); all.type='button'; all.addEventListener('click', () => proposalDecision(all, '/api/guide/create-all', {message_id:message.id})); cards.append(all); } content.append(cards);
    }
    if (isUser) content.append(deliveryNote(message));
    if (!isSystem) {
      const swipeCue = icon('reply'); swipeCue.classList.add('swipe-cue'); node.append(swipeCue);
      content.append(messageActions(message, node), reactionBar(message));
      let pressTimer, touchStart = null, swiping = false;
      node.addEventListener('pointerdown', (event) => { if (event.pointerType !== 'touch' || event.target?.closest?.('button,a,input,video')) return; touchStart = { x: event.clientX, y: event.clientY, id: event.pointerId }; swiping = false; pressTimer = setTimeout(() => { if (touchStart && node.isConnected) { const { x, y, id } = touchStart; touchStart = null; openMessageMenu(message, node, { getBoundingClientRect: () => ({ left: x, top: y, bottom: y }) }, null, id); } }, 550); });
      node.addEventListener('pointermove', (event) => { if (!touchStart || event.pointerId !== touchStart.id) return; const dx = event.clientX - touchStart.x, dy = event.clientY - touchStart.y; if (Math.hypot(dx, dy) > 10) clearTimeout(pressTimer); if (Math.abs(dy) > 18 && Math.abs(dy) > Math.abs(dx)) { touchStart = null; node.classList.remove('swipe-reply'); return; } if (dx > 14 && Math.abs(dx) > Math.abs(dy) * 1.3) { swiping = true; node.classList.add('swipe-reply'); node.style.setProperty('--swipe-x', `${Math.min(dx, 72)}px`); } });
      node.addEventListener('pointerup', (event) => { if (touchStart && event.pointerId === touchStart.id && swiping && event.clientX - touchStart.x >= 56) addReply(message.id); clearTimeout(pressTimer); touchStart = null; swiping = false; node.classList.remove('swipe-reply'); node.style.removeProperty('--swipe-x'); });
      node.addEventListener('pointercancel', () => { clearTimeout(pressTimer); touchStart = null; swiping = false; node.classList.remove('swipe-reply'); node.style.removeProperty('--swipe-x'); });
    }
    if (currentChat()?.type === 'group' && !isUser && !isSystem && !message.best_fit && message.text && (message.independent === true || quotedMessages(message).some(({ parent }) => parent?.role === 'user' && /^@all(?:\s|$)/i.test(parent.text || '')))) content.classList.add('group-answer');
    node.append(content); return node;
  }
  function reconcileMessages() {
    const pinned = followingConversation(), top = ui.viewport.scrollTop;
    const previousHeight = ui.viewport.scrollHeight;
    ui.list.querySelectorAll('.list-skeleton,.message-placeholder').forEach((node) => node.remove());
    const existing = new Map([...ui.list.children].map((node) => [node.dataset.messageId, node]));
    const ids = new Set();
    data.messages.sort(compareMessages);
    data.messages.forEach((message, index) => {
      const id = String(message.id); ids.add(id);
      let node = existing.get(id) || (message.request_id && [...ui.list.children].find((item) => item.dataset.requestId === message.request_id));
      const draft = message.job_id && data.deltas.get(String(message.job_id));
      const replacesDraft = message.job_id && (!draft?.afterMessageId || Number(message.id) > draft.afterMessageId);
      if (!node && message.role === 'assistant' && replacesDraft) {
        node = [...ui.list.children].find((item) => item.classList.contains('streaming-message') && item.dataset.jobId === String(message.job_id));
        if (node) { messageNode(message, node); node.classList.add('stream-final'); }
      }
      if (node) { node.dataset.messageId = id; if(message.request_id)node.dataset.requestId=message.request_id; }
      if (node && node.dataset.textSignature !== (message.text || '')) { const replacement = messageNode(message); node.replaceWith(replacement); node = replacement; }
      if (replacesDraft) { const key=String(message.job_id);data.deltas.delete(key); sendFeel.finishing.delete(key);data.closedDeltas.add(key);sendFeel.finalMessages.set(key,Number(message.id)); }
      if (node && message.cards?.some((c)=>c.kind==='proposal' || c.kind==='signin_request' || c.kind==='login_fill_request') && node.dataset.cardsSignature !== JSON.stringify(message.cards)) { const replacement=messageNode(message); node.replaceWith(replacement); node=replacement; }
      if (!node) { node = messageNode(message); ui.list.append(node); }
      else {
        if (message.role === 'system' && !!message.usage_limit !== node.classList.contains('usage-limit')) { const replacement = messageNode(message); node.replaceWith(replacement); node = replacement; }
        const cards = Array.isArray(message.cards) ? message.cards : [];
        cards.forEach((card) => { const found = [...node.querySelectorAll('.card')].find((c) => c.dataset.cardIndex === String(card.index)); if (found) updateCard(found, card, message); });
        replaceReactions(node, message);
        if (message.role === 'user') updateDelivery(node, message);
      }
      const previous = data.messages[index - 1];
      node.classList.toggle('continued-run', message.role === 'assistant' && previous?.role === 'assistant' && message.agent_id === previous.agent_id);
      const at = ui.list.children[index];
      if (at !== node) ui.list.insertBefore(node, at || null);
    });
    existing.forEach((node) => { if (!ids.has(node.dataset.messageId) && !node.classList.contains('streaming-message')) node.remove(); });
    renderDeltas(false);
    parity?.mountVersions();
    if (messagePopover && !messagePopover.owner.isConnected) closeMessagePopover();
    scheduleMessageMeasurements();
    if (pinned && ui.viewport.scrollHeight !== previousHeight) scrollConversation(); else if (!pinned) ui.viewport.scrollTop = top;
  }
  function renderDeltas(preserve = true) {
    const pinned = followingConversation(), top = ui.viewport.scrollTop;
    const previousHeight = ui.viewport.scrollHeight;
    let changed = false;
    for (const job of activeChatJobs()) if (!data.closedDeltas.has(String(job.id)) && !data.deltas.has(String(job.id))) data.deltas.set(String(job.id), { chat_id: job.chat_id, agent_id: job.agent_id, text: '', afterMessageId:sendFeel.finalMessages.get(String(job.id)) });
    const live = new Set();
    for (const [jobId, delta] of data.deltas) {
      if (String(delta.chat_id) !== data.chatId) continue;
      live.add(jobId);
      let node = [...ui.list.children].find((item) => item.classList.contains('streaming-message') && item.dataset.jobId === jobId);
      const a = agent(delta.agent_id), head = el('div', 'message-head'); head.append(avatar(a?.emoji, a?.avatar, 'message-avatar', a), el('strong', '', a?.name || 'Pip'));
      if (!node) { changed = true; node = el('article', 'message assistant streaming-message'); node.dataset.jobId = jobId; const content = el('div', 'message-content'); content.append(head, el('div', 'stream-context'), el('div', 'stream-body')); node.append(content); ui.list.append(node); }
      const job = data.statuses.find((entry) => String(entry.id) === jobId) || {};
      const streamMessage = { ...job, ...delta, role: 'assistant', agent_id: delta.agent_id };
      const contextKey = JSON.stringify([streamMessage.reply_to, streamMessage.best_fit, streamMessage.routing_kind, delta.agent_id, quotedText(streamMessage)]);
      if (node.dataset.contextKey !== contextKey) {
        node.dataset.contextKey = contextKey;
        let context = node.querySelector('.stream-context');
        if (!context) { context = el('div', 'stream-context'); node.querySelector('.message-content').insertBefore(context, node.querySelector('.stream-body')); }
        context.replaceChildren();
        if (streamMessage.reply_to) { const quotes = quoteStack(streamMessage, false); if (quotes.children.length) context.append(quotes); }
        if (streamMessage.best_fit || ['tie','directed'].includes(streamMessage.routing_kind)) context.append(routingNote(streamMessage, a));
      }
      if(node.dataset.agentId !== String(delta.agent_id)){node.dataset.agentId=String(delta.agent_id);node.querySelector('.message-head')?.replaceWith(head);}
      const previous = data.messages.at(-1); node.classList.toggle('continued-run', previous?.role === 'assistant' && previous.agent_id === delta.agent_id);
      const shown = a?.guide ? delta.text.replace(/```agent-hub[\s\S]*?(?:```|$)/gi, '').replace(/```(?:agent(?:-hub)?)?$/i, '') : delta.text;
      const text = withoutSpeakerPrefix(visibleHandoffText(shown), a?.name), body = node.querySelector('.stream-body');
      if (node.dataset.streamText !== text) { changed = true; node.dataset.streamText = text; body.replaceChildren(text ? markdown(text, 'message-body', true) : typingBubble()); }
      node.classList.toggle('is-typing', !text);
    }
    parity?.updateJump();
    ui.list.querySelectorAll('.streaming-message').forEach((node) => { if(!live.has(node.dataset.jobId))node.remove(); });
    if (live.size) ui.activity.hidden = true;
    renderEmpty(); renderSend();
    if (preserve && pinned && (changed || ui.viewport.scrollHeight !== previousHeight)) scrollConversation(); else if (!pinned) ui.viewport.scrollTop = top;
  }
  function typingBubble() { const bubble = el('div', 'typing-bubble'); bubble.setAttribute('role', 'status'); bubble.setAttribute('aria-label', 'Waiting for reply'); for(let i=0;i<3;i++)bubble.append(el('span')); return bubble; }
  function closeDelta(jobId) {
    if (!jobId) return;
    const key = String(jobId);
    data.deltas.delete(key);
    sendFeel.finishing.delete(key);
    data.closedDeltas.add(key);
    if (data.closedDeltas.size > 200) data.closedDeltas.delete(data.closedDeltas.values().next().value);
    renderDeltas();
  }
  function renderReply() {
    invalidateRetryIfEdited();
    ui.replyBar.hidden = !data.replyTo.length;
    ui.replyPreview.replaceChildren(...data.replyTo.map((id) => {
      const message = data.messages.find((m) => String(m.id) === String(id));
      const chip = el('span', 'reply-chip', quotePreview(message?.text || message?.cards?.[0]?.title || message?.attachments?.[0]?.name || 'Message', agent(message?.agent_id)?.name, 70));
      const remove = iconButton('close', 'Remove reply'); remove.addEventListener('click', () => { data.replyTo = data.replyTo.filter((item) => item !== id); renderReply(); }); chip.append(remove); return chip;
    }));
  }
  function renderUploads() {
    invalidateRetryIfEdited();
    ui.uploadTray.hidden = !data.uploads.length;
    ui.uploadTray.replaceChildren(...data.uploads.map((entry) => {
      const chip = el('div', 'upload-chip');
      const preview = entry.result?.kind === 'image' ? attachmentUrl(entry.result.url) : entry.preview;
      if (preview) { const image = el('img', 'upload-thumbnail'); image.src = preview; image.alt = entry.file.name; chip.append(image); }
      const copy = el('div', 'upload-copy'); copy.append(el('span', 'upload-name', entry.file.name), el('small', 'upload-size', formatFileSize(entry.file.size)));
      if (entry.status === 'uploading') { const progress = el('progress'); progress.max = 100; progress.value = entry.progress || 0; progress.setAttribute('aria-label', `Uploading ${entry.file.name}`); copy.append(progress, el('small', 'upload-status', `${entry.progress || 0}%`)); }
      else if (entry.status === 'error') copy.append(el('small', 'upload-status', 'Failed · remove and try again'));
      else copy.append(el('small', 'upload-status', 'Attached ✓'));
      chip.append(copy);
      const remove = iconButton('close', `Remove ${entry.file.name}`);
      remove.addEventListener('click', () => { data.uploads = data.uploads.filter((x) => x !== entry); releaseUpload(entry); renderUploads(); });
      chip.append(remove); return chip;
    }));
    renderSend();
  }
  function messagePayload() {
    return { chat_id: data.chatId, text: ui.message.value.trim(), reply_to: [...data.replyTo], uploads: data.uploads.filter((x) => x.status === 'done').map((x) => x.result.path) };
  }
  function invalidateRetryIfEdited() {
    if (data.retryRequest && data.retryRequest.signature !== JSON.stringify(messagePayload())) data.retryRequest = null;
  }
  function formatFileSize(size) {
    if (!Number.isFinite(Number(size)) || Number(size) < 0) return '';
    const bytes = Number(size);
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`;
    return `${(bytes / 1073741824).toFixed(1)} GB`;
  }
  function releaseUpload(entry) {
    entry.xhr?.abort();
    if (entry.preview) { URL.revokeObjectURL(entry.preview); entry.preview = null; }
  }
  function clearUploads() {
    const entries = data.uploads; data.uploads = []; entries.forEach(releaseUpload);
  }
  function transferFiles(transfer) {
    const files = [...(transfer?.files || [])];
    if (files.length) return files;
    return [...(transfer?.items || [])].filter((item) => item.kind === 'file').map((item) => item.getAsFile()).filter(Boolean);
  }
  function canAttach() { return data.authenticated && !ui.app.hidden && !ui.composer.hidden; }
  function pasteAttachments(event) {
    if (!canAttach()) return;
    const files = transferFiles(event.clipboardData);
    if (!files.length) return; // Leave ordinary text paste to the textarea/browser.
    event.preventDefault(); files.forEach(upload);
  }
  let dragDepth = 0;
  function resetDropOverlay() { dragDepth = 0; $('dropOverlay').hidden = true; }
  function isFileDrag(event) {
    return [...(event.dataTransfer?.types || [])].includes('Files') || [...(event.dataTransfer?.items || [])].some((item) => item.kind === 'file');
  }
  function attachPicker() {
    if (matchMedia('(max-width: 700px)').matches) { closeMenus(); ui.file.click(); }
    else toggleMenu('attachMenu', 'attachButton');
  }
  function setupAttachments() {
    ui.message.addEventListener('paste', pasteAttachments);
    $('attachButton').addEventListener('click', attachPicker);
    $('attachFileButton').addEventListener('click', () => { closeMenus(); ui.anyFile.click(); });
    [ui.file, ui.anyFile].forEach((picker) => picker.addEventListener('change', () => { [...picker.files].forEach(upload); picker.value = ''; }));
    const area = $('conversation');
    area.addEventListener('dragenter', (event) => { if (!canAttach() || !isFileDrag(event)) return; event.preventDefault(); dragDepth++; $('dropOverlay').hidden = false; });
    area.addEventListener('dragover', (event) => { if (!canAttach() || !isFileDrag(event)) return; event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; $('dropOverlay').hidden = false; });
    area.addEventListener('dragleave', (event) => { if ($('dropOverlay').hidden) return; event.preventDefault(); dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) resetDropOverlay(); });
    area.addEventListener('drop', (event) => { const files = transferFiles(event.dataTransfer); const allowed = canAttach(); resetDropOverlay(); if (!files.length) { if (isFileDrag(event)) event.preventDefault(); return; } event.preventDefault(); if (allowed) files.forEach(upload); });
    // Prevent the browser navigating to a local file dropped outside the chat.
    document.addEventListener('dragover', (event) => { if (isFileDrag(event)) event.preventDefault(); });
    document.addEventListener('drop', (event) => { if (isFileDrag(event)) event.preventDefault(); resetDropOverlay(); });
    document.addEventListener('dragend', resetDropOverlay);
    window.addEventListener('blur', resetDropOverlay);
    $('lightboxClose').addEventListener('click', closeImageLightbox);
    $('imageLightbox').addEventListener('click', (event) => { if (event.target === $('imageLightbox')) closeImageLightbox(); });
    $('imageLightbox').addEventListener('close', () => { $('lightboxImage').removeAttribute('src'); });
  }
  function upload(file) {
    if (!canAttach()) return;
    if (data.uploads.length >= 10) { showToast('Attach up to 10 files per message.'); return; }
    if (file.size > data.uploadLimit) { showToast(`${file.name} exceeds the ${Math.ceil(data.uploadLimit / 1048576)} MB upload limit.`); return; }
    if (!file.size) { showToast(`${file.name} is empty. Choose a file with content.`); return; }
    // Active formats (SVG/HTML) are downloadable files, never local image previews.
    const raster = /\.(png|jpe?g|gif|webp)$/i.test(file.name) && /^(image\/(png|jpeg|gif|webp))?$/.test(file.type || '');
    const entry = { file, status: 'uploading', progress: 0, result: null, xhr: null, preview: raster ? URL.createObjectURL(file) : null };
    data.uploads.push(entry); renderUploads();
    const xhr = new XMLHttpRequest(); entry.xhr = xhr;
    xhr.open('POST', `/api/upload?name=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader('X-Hub-Request', '1'); xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.onprogress = (event) => { if (data.uploads.includes(entry) && event.lengthComputable) { entry.progress = Math.round(event.loaded / event.total * 100); renderUploads(); } };
    xhr.onload = () => {
      if (!data.uploads.includes(entry)) return;
      let result; try { result = JSON.parse(xhr.responseText); } catch { result = null; }
      if (xhr.status === 401) { showLogin(); return; }
      if (xhr.status >= 200 && xhr.status < 300 && result?.path) { entry.status = 'done'; entry.result = result; if (entry.preview) { URL.revokeObjectURL(entry.preview); entry.preview = null; } }
      else { entry.status = 'error'; showToast(result?.error || `Could not upload ${file.name}.`); }
      renderUploads();
    };
    xhr.onerror = xhr.ontimeout = () => { if (data.uploads.includes(entry)) { entry.status = 'error'; renderUploads(); showToast(`Could not upload ${file.name}.`); } };
    xhr.send(file);
  }
  async function sendMessage(event) {
    event.preventDefault();
    if (parity?.editing) { await parity.submitEdit(); return; }
    parity?.stopVoice();
    if (data.uploads.some((entry) => entry.status === 'uploading')) return;
    if (!data.chatId) {
      const chosen = composeAgent(); if (!chosen) { openAgentPicker(); return; }
      const draft = ui.message.value, queued = data.uploads; openChat(directId(chosen.id)).catch((error)=>showToast(errorText(error))); ui.message.value = draft; resizeComposer(); data.uploads = queued; renderUploads();
    }
    const text = ui.message.value.trim(), uploads = data.uploads.filter((x) => x.status === 'done');
    if (!data.chatId || data.uploads.some((x) => x.status === 'uploading') || (!text && !uploads.length)) return;
    if (!navigator.onLine) { showToast('Offline. Reconnect before sending.'); return; }
    motionFeedback(ui.send, 'send-lift');
    const sentChat = data.chatId;
    const sentSession = sendFeel.session;
    queueComposerDock(sentChat);
    const payload = { chat_id: sentChat, text, reply_to: [...data.replyTo], uploads: uploads.map((x) => x.result.path) };
    if (currentChat()?.type === 'group' && currentChat().agents?.includes(data.composeAgentId)) payload.agent_id = data.composeAgentId;
    const signature = JSON.stringify(payload);
    const requestId = crypto.randomUUID();
    data.retryRequest = { signature, id: requestId };
    sendFeel.sending.add(requestId); data.pending = true; ui.composer.dataset.pending = 'true';
    // Display each send immediately, but submit POSTs in the owner's send order.
    const priorDispatch = sendFeel.dispatchTail;
    let releaseDispatch;
    const dispatchDone = new Promise((resolve) => { releaseDispatch = resolve; });
    sendFeel.dispatchTail = dispatchDone;
    const finishDispatch = () => { releaseDispatch(); if (sendFeel.dispatchTail === dispatchDone) sendFeel.dispatchTail = null; };
    const optimistic = optimisticMessage(payload, requestId, uploads);
    ui.message.value = ''; resizeComposer(); data.replyTo = []; clearUploads(); renderReply(); renderUploads(); ui.message.focus({ preventScroll: true });
    try {
      if (priorDispatch) await priorDispatch;
      if (data.chatReady?.id === sentChat && !await data.chatReady.promise) {
        const retry = refreshChat();
        data.chatReady = { id: sentChat, promise: retry };
        if (!await retry) throw new Error('Chat is still loading. Your message is saved here; try sending again.');
      }
      if (data.chatId !== sentChat || sendFeel.session !== sentSession) throw new Error('The conversation changed before sending.');
      await dispatchSentMessage(optimistic);
      finishDispatch();
      if (sendFeel.session !== sentSession) return;
      if (data.retryRequest?.id === requestId) data.retryRequest = null;
      if (data.chatId === sentChat) {
        await refreshChat();
      }
    } catch (error) { failSentMessage(optimistic, error); }
    finally { finishDispatch(); sendFeel.sending.delete(requestId); data.pending = sendFeel.sending.size > 0; ui.composer.dataset.pending = String(data.pending); renderSend(); }
  }
  function setupComposerInteractions() {
    ui.composer.addEventListener('submit', sendMessage);
    ui.stop.addEventListener('click', stopResponse);
    ui.message.addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); ui.composer.requestSubmit(); } });
    ui.message.addEventListener('input', () => { invalidateRetryIfEdited(); resizeComposer(); });
  }
  function askEveryone() {
    const value = ui.message.value.trimStart();
    if (!/^@all(?:\s|$)/i.test(value)) ui.message.value = `@all ${value}`;
    ui.message.focus(); ui.message.setSelectionRange(ui.message.value.length, ui.message.value.length);
    if (value.replace(/^@all(?:\s|$)/i, '').trim()) ui.composer.requestSubmit();
    else showToast('Type a question, then tap Ask everyone to send it to the group.');
  }
  function workerRow(worker, running) {
    const row = el('div', 'worker-row'); row.append(el('strong', '', worker.task || worker.id || 'Worker'));
    const duration = Number.isFinite(Number(worker.elapsed)) && worker.elapsed !== null ? `${Math.floor(Number(worker.elapsed) / 60)}m ${Number(worker.elapsed) % 60}s` : '';
    const details = [worker.bot || worker.agent_id, running ? worker.status || 'Running' : worker.rc === 0 ? 'Done' : `Exit ${worker.rc ?? 'unknown'}`, duration, dateTime(running ? worker.started || worker.created : worker.at)].filter(Boolean).join(' · ');
    if (details) row.append(el('small', '', details));
    if (worker.status === 'held_limit') row.append(el('p', 'routine-error', 'Usage limit reached. This message is saved until you choose Retry.'));
    if (worker.last_event) row.append(el('p', 'worker-event', worker.last_event));
    if (!running && worker.message) row.append(markdown(worker.message, 'worker-answer'));
    if (Array.isArray(worker.files) && worker.files.length) {
      const files = el('div', 'worker-files');
      worker.files.forEach((file) => { const url = safeUrl(file.url); if (!url) return; const link = el('a', '', `↓ ${file.name || 'File'}`); link.href = url; link.target = '_blank'; link.rel = 'noopener'; files.append(link); }); row.append(files);
    }
    return row;
  }
  function renderWorkers() {
    const workers = data.workers || { running: [], done: [] };
    const running = Array.isArray(workers.running) ? workers.running : [], done = Array.isArray(workers.done) ? workers.done : [];
    const hubJobs = data.jobs.filter((job) => ['queued','working','typing','held_limit'].includes(job.status));
    const recent = [...done, ...data.jobs.filter((job) => !['queued','working','typing','held_limit'].includes(job.status))].some((job) => { const when = seconds(job.finished || job.updated || job.at || job.created); return when > 0 && Date.now() / 1000 - when < 86400; }); const held = hubJobs.filter((job) => job.status === 'held_limit').length; const count = running.length + hubJobs.length - held; ui.workerCount.hidden = !count; ui.workerCount.textContent = String(count); $('workersButton').hidden = !(count || recent || held);
    $('chatWorkersButton').hidden = !count;
    ui.workersBody.replaceChildren();
    if (!running.length && !hubJobs.length && !done.length) ui.workersBody.append(el('p', 'empty-note', 'No background jobs yet. Send a Pip a task to see its progress and recent results here.'));
    else if (workers.note) ui.workersBody.append(el('p', 'empty-note', workers.note));
    [[hubJobs, 'Hub tasks', true], [running, 'Other running tasks', true], [done, 'Recent results', false]].forEach(([items, title, live]) => {
      if (!items.length) return;
      const section = el('section', 'worker-section'); section.append(el('h3', '', title));
      items.forEach((item) => {
        const row = workerRow(item, live);
        if (title === 'Hub tasks') {
          if (item.status === 'held_limit') { const retry = el('button', 'secondary', 'Retry'); retry.addEventListener('click', async () => { retry.disabled = true; try { await post('/api/jobs/retry', { job_id: item.id }); await refreshJobs(); await refreshChat(); } catch (error) { showToast(errorText(error)); } finally { retry.disabled = false; } }); row.append(retry); const alternate = item.engine === 'claude' ? 'codex' : 'claude'; if (data.setup?.engines?.[alternate]?.available) { const button = el('button', 'secondary', `Try with ${alternate === 'codex' ? 'Codex' : 'Claude'}`); button.addEventListener('click', async () => { button.disabled = true; try { await post('/api/jobs/retry', { job_id: item.id, engine: alternate }); await refreshJobs(); await refreshChat(); } catch (error) { showToast(errorText(error)); } finally { button.disabled = false; } }); row.append(button); } }
          else { const stop = el('button', 'secondary', 'Stop'); stop.type = 'button'; stop.addEventListener('click', async () => { stop.disabled = true; try { await post('/api/jobs/stop', { job_id: item.id }); await refreshJobs(); } catch (error) { showToast(errorText(error)); stop.disabled = false; } }); row.append(stop); }
        }
        section.append(row);
      });
      ui.workersBody.append(section);
    });
  }
  async function refreshWorkers() {
    if (!data.authenticated) return;
    try { data.workers = await api('/api/workers'); renderWorkers(); refreshJobs(); }
    catch (error) { if (data.authenticated && ui.workersDialog.open) showToast(errorText(error)); }
  }
  let eventRefreshTimer = null, eventRefreshRunning = false, eventRefreshPending = false, eventRefreshChat = false, eventRefreshJobs = false;
  function scheduleEventRefresh({ chat = false, jobs = false } = {}) {
    eventRefreshPending = true;
    eventRefreshChat ||= chat; eventRefreshJobs ||= jobs;
    if (eventRefreshTimer || eventRefreshRunning || !data.authenticated) return;
    eventRefreshTimer = setTimeout(async () => {
      eventRefreshTimer = null; eventRefreshRunning = true;
      const updateChat = eventRefreshChat, updateJobs = eventRefreshJobs;
      eventRefreshPending = false; eventRefreshChat = false; eventRefreshJobs = false;
      try {
        await refreshState();
        if (updateChat) await refreshChat();
        if (updateJobs) await refreshJobs();
      } catch { /* the next event or poll retries */ }
      finally {
        eventRefreshRunning = false;
        if (eventRefreshPending) scheduleEventRefresh();
      }
    }, 250);
  }
  function connectEvents() {
    if (!data.authenticated || data.eventSource) return;
    const events = new EventSource('/api/events'); data.eventSource = events;
    events.addEventListener('ready', () => { ui.reconnect.hidden = true; scheduleEventRefresh({ chat: true }); refreshWorkers(); });
    events.addEventListener('change', (event) => {
      let change; try { change = JSON.parse(event.data); } catch { change = {}; }
      if (change.kind === 'workers') refreshWorkers();
      else if (change.kind === 'seen') markAgentSeen(change);
      else if (change.kind === 'product') refreshProduct();
      else if (change.kind === 'status' && change.status === 'choosing') { if (!change.chat_id || String(change.chat_id) === data.chatId) { const waiting=ui.list.querySelector('.typing-bubble');if(waiting)waiting.setAttribute('aria-label','Choosing who answers');else{ui.activity.hidden = false; ui.activity.textContent = 'Choosing who answers…';} } }
      else if (change.kind === 'status' || change.kind === 'agents' || change.kind === 'groups' || change.kind === 'chats') {
        if (change.kind === 'status' && change.status === 'done') finishDelta(change.job_id);
        if (change.kind === 'status' && ['error','stopped','interrupted','held_limit'].includes(change.status)) closeDelta(change.job_id);
        if (change.kind === 'status' && ['working','typing'].includes(change.status)) { const key=String(change.job_id);if(data.closedDeltas.has(key)){const prior=data.deltas.get(key);if(prior)data.deltas.set(key,{...prior,text:'',afterMessageId:sendFeel.finalMessages.get(key)});sendFeel.finishing.delete(key);}data.closedDeltas.delete(key); }
        if (change.kind === 'status' && ['queued','working','typing'].includes(change.status) && String(change.chat_id) === data.chatId) { const key=String(change.job_id), pending=change.request_id && sendFeel.optimistic.get(change.request_id);if(pending?.chat_id===data.chatId)sentTyping(pending,[change.job_id]); if(!data.deltas.has(key))data.deltas.set(key,{chat_id:change.chat_id,agent_id:change.agent_id || composeAgent()?.id,text:'',afterMessageId:sendFeel.finalMessages.get(key)});else if(change.agent_id)data.deltas.get(key).agent_id=change.agent_id; renderDeltas(); }
        scheduleEventRefresh({ jobs: true, chat: change.kind === 'status' && (!change.chat_id || String(change.chat_id) === data.chatId) });
      }
      else if (change.kind === 'delta') {
        if (change.job_id && change.chat_id && !data.closedDeltas.has(String(change.job_id))) {
          const key=String(change.job_id);data.deltas.set(key, { ...data.deltas.get(key), chat_id: change.chat_id, agent_id: change.agent_id, text: String(change.text || ''), ...(change.reply_to != null ? { reply_to: change.reply_to } : {}), ...(change.best_fit != null ? { best_fit: change.best_fit } : {}), ...(Object.prototype.hasOwnProperty.call(change, 'routing_kind') ? { routing_kind: change.routing_kind } : {}), ...(change.independent != null ? { independent: change.independent } : {}), ...(change.reply_parent ? { reply_parent: change.reply_parent } : {}) });
          if (String(change.chat_id) === data.chatId) renderDeltas();
        }
      }
      else if (change.kind === 'message') {
        finishDelta(change.job_id,change.message_id);
        scheduleEventRefresh({ chat: !change.chat_id || String(change.chat_id) === data.chatId });
      }
      if ($('swarmResultsDialog').open && ['swarms','status','message','groups'].includes(change.kind)) refreshSwarms();
    });
    events.onerror = () => {
      ui.reconnect.hidden = !navigator.onLine;
      if (events.readyState === EventSource.CLOSED) {
        events.close(); data.eventSource = null; ui.reconnect.hidden = false;
        clearTimeout(data.eventRetry); data.eventRetry = setTimeout(connectEvents, 2500);
      } else ui.reconnect.hidden = false;
    };
    events.onopen = () => { ui.reconnect.hidden = true; scheduleEventRefresh({ chat: true }); refreshWorkers(); };
  }
  async function idleCheck() {
    if (!data.authenticated || document.hidden) return;
    try { const session = await api('/api/session'); if (!session.authenticated) showLogin(); }
    catch { /* SSE reconnects and refreshes when the server returns */ }
  }
  async function startSession() {
    const session = await api('/api/session');
    if (!session.authenticated) { showLogin(); return; }
    await refreshState(); connectEvents(); refreshWorkers(); loadSetup();
  }
  function updateConnection() {
    ui.offline.hidden = navigator.onLine;
    if (navigator.onLine && data.authenticated) { ui.reconnect.hidden = false; scheduleEventRefresh({ chat: true }); connectEvents(); }
  }
  function theme(value) {
    document.documentElement.dataset.theme = value;
    document.querySelector('meta[name="theme-color"]').content = value === 'light' ? '#ffffff' : '#212121';
    $('themeSettings').setAttribute('aria-label', value === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
    $('themeSettings').textContent = value === 'dark' ? 'Use light theme' : 'Use dark theme';
    try { localStorage.setItem(storageKey, value); } catch { /* storage may be unavailable */ }
  }
  function closeDialog(dialog) { if (dialog.open) dialog.close(); }
  const models = { claude: ['haiku','sonnet','opus'], codex: ['gpt-6-luna','gpt-6.1-sol','gpt-6-astra'] };
  const modelHints = { haiku: 'Fast everyday work', sonnet: 'Balanced complex work', opus: 'Deep reasoning', 'gpt-6-luna': 'Fast everyday work', 'gpt-6.1-sol': 'Balanced coding and reasoning', 'gpt-6-astra': 'Deep reasoning' };
  function engineLabel(name) {
    const label = name === 'claude' ? 'Claude Code' : 'Codex';
    const detail = data.settings?.engines?.[name] || data.setup?.engines?.[name];
    if (!detail) return `${label} (checking sign-in)`;
    if (!detail.available) return `${label}: Not installed — how to install in Help`;
    if (detail.authenticated === 'ready') return `${label} — signed in`;
    return `${label} (${detail.authenticated === 'login_required' ? 'sign in needed' : 'sign-in not checked'})`;
  }
  function refreshEngineLabels() {
    ['agentEngine', 'swarmAllEngine'].forEach((id) => {
      [...$(id).options].forEach((option) => { option.textContent = engineLabel(option.value); });
    });
    $('engineStatus').replaceChildren(...['claude', 'codex'].map((name) => el('div', 'engine-item', engineLabel(name))));
  }
  function modelSelect(select, engine, chosen) {
    const options = models[engine] || models.claude;
    select.replaceChildren(...options.map((name) => { const option = el('option', '', name); option.value = name; option.title = modelHints[name] || name; return option; }));
    select.value = options.includes(chosen) ? chosen : options[0];
  }
  async function loadSetup() {
    try {
      data.setup = await api('/api/setup');
      refreshEngineLabels();
      try { data.settings = await api('/api/settings'); } catch { /* optional feature */ }
      syncApprovalsButton();
      if (data.settings?.approvals_url) refreshApprovals();
      const first = data.setup.first_run === true;
      if (!data.product) await refreshProduct();
      if (data.agents.some((a) => a.guide)) { if(await window.HubOnboarding?.offer(first)) window.HubOnboarding.mountOffer(); return; }
      if (await window.HubOnboarding?.offer(first)) return;
      if (shouldWelcome()) openWelcome();
    } catch (error) { if (data.authenticated) showToast(errorText(error)); }
  }
  async function refreshProduct() {
    try {
      data.product = await api('/api/product');
      if (Array.isArray(data.product.pins)) data.pinned = data.product.pins;
      $('gettingStarted').hidden = !!data.product.getting_started?.completed || !!data.product.getting_started?.dismissed || (data.agents.length > 0 && data.chats.some((c) => c.last_message));
      renderNav();
    } catch { /* older server still supports local navigation */ }
  }
  const templates = [
    ['Assistant', 'Helps plan, explain, and get everyday work done.', 'Help me make clear plans, answer questions, and complete everyday tasks. Ask when a key detail is missing.'],
    ['Researcher', 'Finds evidence and cites sources.', 'Research questions using reliable sources. Distinguish facts from inference, cite sources, and explain uncertainty.'],
    ['Writer', 'Turns a brief into clear writing.', 'Draft and revise clear writing for the intended audience. Ask for purpose and tone when they are missing.'],
    ['Coder', 'Builds and fixes software.', 'Implement and debug software with clear changes and proportionate verification. Explain any remaining risks.']
  ];
  async function productAction(action, chat_id) {
    try { data.product = await post('/api/product', { action, ...(chat_id ? { chat_id } : {}) }); $('gettingStarted').hidden = !!data.product.getting_started?.completed; renderNav(); }
    catch (error) { showToast(errorText(error)); }
  }
  function shouldWelcome() {
    let dismissed = false;
    try { dismissed = localStorage.getItem('agent-hub-welcome-dismissed') === 'true'; } catch { /* optional storage */ }
    return !data.agents.length && !data.hiddenAgents.length && !dismissed && !data.product?.getting_started?.completed && !data.product?.getting_started?.dismissed && !$('welcomeDialog').open;
  }
  function dismissWelcome() {
    closeDialog($('welcomeDialog'));
    try { localStorage.setItem('agent-hub-welcome-dismissed', 'true'); } catch { /* server stores dismissal too */ }
    return productAction('dismiss_getting_started');
  }
  function openWelcome() {
    data.welcomeTemplate = 0;
    $('welcomeAccounts').replaceChildren(...['claude','codex'].map((name) => el('div', 'engine-item', engineLabel(name))));
    $('welcomeTemplates').replaceChildren(...templates.map(([name, description], index) => {
      const button = el('button', `template-card${index === 0 ? ' selected' : ''}`); button.type = 'button'; button.setAttribute('aria-pressed', index === 0 ? 'true' : 'false');
      button.append(el('strong', '', name), el('small', '', description));
      button.addEventListener('click', () => { data.welcomeTemplate = index; $('welcomeTemplates').querySelectorAll('.template-card').forEach((card, n) => { card.classList.toggle('selected', n === index); card.setAttribute('aria-pressed', n === index ? 'true' : 'false'); }); }); return button;
    }));
    $('welcomeDialog').showModal();
  }
  const coachSteps = [
    ['Create a Pip', 'Give a Pip a name and role, then start a conversation.'],
    ['Make a group', 'A group gives one best-fit answer. Mention one Pip or Ask everyone when needed.'],
    ['Run a team task', 'Use the + menu in a chat to split work, compare answers, or run research → build → review.'],
    ['Reply and react', 'Use Reply to quote several messages. React to give direct feedback.']
  ];
  function closeCoach() {
    $('coachDialog').hidden = true; $('coachSpotlight').hidden = true;
    document.querySelectorAll('.coach-target').forEach((node) => node.classList.remove('coach-target'));
  }
  function positionCoach(target) {
    target.scrollIntoView({ block: 'center', inline: 'nearest' });
    const rect = target.getBoundingClientRect(), coach = $('coachDialog'), spot = $('coachSpotlight');
    const vw = window.innerWidth, vh = window.innerHeight, gap = 12;
    coach.hidden = false; spot.hidden = false;
    const width = Math.min(320, vw - 24);
    coach.style.width = `${width}px`;
    const height = coach.offsetHeight || 180;
    const candidates = [
      { left: rect.right + gap, top: rect.top }, { left: rect.left - width - gap, top: rect.top },
      { left: rect.left, top: rect.bottom + gap }, { left: rect.left, top: rect.top - height - gap }
    ];
    const fit = candidates.find((c) => c.left >= 8 && c.top >= 8 && c.left + width <= vw - 8 && c.top + height <= vh - 8);
    const chosen = fit || { left: Math.max(8, Math.min(vw - width - 8, rect.left)), top: rect.bottom + height + gap <= vh ? rect.bottom + gap : Math.max(8, rect.top - height - gap) };
    if (rect.width <= 0 || rect.height <= 0 || rect.top < 0 || rect.bottom > vh || chosen.top + height > vh ||
        (chosen.left < rect.right && chosen.left + width > rect.left && chosen.top < rect.bottom && chosen.top + height > rect.top)) { closeCoach(); return; }
    coach.style.left = `${chosen.left}px`; coach.style.top = `${chosen.top}px`; coach.style.width = `${width}px`;
    spot.style.left = `${rect.left - 5}px`; spot.style.top = `${rect.top - 5}px`; spot.style.width = `${rect.width + 10}px`; spot.style.height = `${rect.height + 10}px`;
  }
  function showCoach(step = 0) {
    document.querySelectorAll('dialog[open]').forEach((dialog) => closeDialog(dialog));
    if (step === 3 && !data.chatId) {
      if (data.chats[0]?.id) { openChat(data.chats[0].id).then(() => showCoach(step)); }
      else closeCoach();
      return;
    }
    closeCoach(); data.coachStep = step;
    const [title, body] = coachSteps[step], targetId = ['newChatButton','newChatButton', data.chatId ? 'attachButton' : 'newChatButton', data.chatId ? 'composer' : 'newChatButton'][step];
    if (matchMedia('(max-width: 700px)').matches) { if (step >= 2 && data.chatId) ui.app.classList.add('chat-open'); else ui.app.classList.remove('chat-open'); }
    const target = $(targetId); target.classList.add('coach-target');
    $('coachTitle').textContent = `${step + 1} of 4 · ${title}`; $('coachBody').textContent = body;
    $('coachNext').textContent = step === 3 ? 'Finish' : 'Next';
    $('coachDemo').hidden = true; $('coachTry').hidden = step === 3;
    requestAnimationFrame(() => positionCoach(target));
  }
  function paletteEntries() {
    return [
      ...data.agents.filter((a) => !a.swarm).map((a) => ({ label: a.name, detail: a.title || 'Pip', run: () => openChat(directId(a.id)) })),
      ...data.chats.filter((c) => c.type === 'group' && (!c.source_chat_id || c.source_chat_id === c.id)).map((c) => ({ label: c.name, detail: 'Group', run: () => openChat(c.id) })),
      { label: 'New Pip', detail: 'Create', run: () => $('newAgentButton').click() },
      { label: 'New group', detail: 'Create', run: () => $('newGroupButton').click() },
      { label: 'Run a team task', detail: 'Work together', run: openTeam },
      { label: 'Schedules', detail: 'Repeat tasks', run: () => $('routinesButton').click() },
      ...(data.settings?.approvals_url ? [{ label: 'Approvals', detail: 'Review drafts', run: () => $('approvalsButton').click() }] : []),
      { label: 'Background jobs', detail: 'Tasks and results', run: () => $('workersButton').click() },
      { label: 'Settings', detail: 'Models', run: () => $('settingsButton').click() },
      { label: 'Help', detail: 'Guide and tour', run: () => $('helpButton').click() },
      { label: 'Sign out', detail: 'Account', run: () => $('logoutButton').click() }
    ];
  }
  function syncApprovalsButton() {
    const count = approvalsDrafts().filter((draft) => !data.approvalsReviews[draft.id] && !['approved','denied','held','scheduled','published'].includes(String(draft.status || draft.phase || '').toLowerCase())).length; $('approvalCount').textContent = String(count); $('approvalsButton').hidden = !data.settings?.approvals_url || !count;
  }
  async function renderPalette() {
    const query = normalizeSearch($('paletteInput').value);
    const entries = paletteEntries().filter((item) => normalizeSearch(`${item.label} ${item.detail}`).includes(query)).slice(0, 12);
    $('paletteResults').replaceChildren(...entries.map((item) => {
      const button = el('button', 'palette-result'); button.type = 'button';
      button.append(el('strong', '', item.label), el('span', '', item.detail));
      button.addEventListener('click', () => { closeDialog($('paletteDialog')); item.run(); }); return button;
    }));
    if (query.length >= 2) {
      const request = query;
      try {
        const found = await api(`/api/search?q=${encodeURIComponent(query)}`);
        if (normalizeSearch($('paletteInput').value) !== request || !$('paletteDialog').open) return;
        (found.results || []).slice(0, 8).forEach((result) => {
          const button = el('button', 'palette-result'); button.type = 'button';
          button.append(el('strong', '', result.chat_name || 'Conversation'), el('span', '', String(result.text || '').slice(0, 90)));
          button.addEventListener('click', () => { closeDialog($('paletteDialog')); openChat(result.chat_id, true, result.message_id); });
          $('paletteResults').append(button);
        });
      } catch { /* local actions remain available */ }
    }
    if (!$('paletteResults').children.length) $('paletteResults').append(el('p', 'empty-note', 'No results. Try a different name or word.'));
  }
  function openPalette() { $('paletteInput').value = $('searchButton').value; $('paletteDialog').showModal(); renderPalette(); $('paletteInput').focus(); }
  function onPaletteKeydown(event) {
    if (event.key === 'Escape') { event.preventDefault(); closeDialog($('paletteDialog')); }
  }
  function clearSwarmError() { $('swarmError').hidden = true; $('swarmError').textContent = ''; }
  function showSwarmError(message) {
    const error = $('swarmError');
    error.textContent = message;
    error.hidden = false;
    showToast(message);
    error.scrollIntoView({ block: 'start' });
  }
  const modelRoles = [['orchestrator','Plans and coordinates'],['worker','Does the work'],['reviewer','Checks the result'],['quick','Quick tasks']];
  function selectSettingsTab(name) { document.querySelectorAll('[data-settings-panel]').forEach((panel) => { panel.hidden = panel.dataset.settingsPanel !== name; }); document.querySelectorAll('[data-settings-tab]').forEach((tab) => { const selected = tab.dataset.settingsTab === name; tab.setAttribute('aria-selected', String(selected)); tab.tabIndex = selected ? 0 : -1; }); if (name === 'schedules') refreshRoutines(); if (name === 'connections') window.HubPipBrowser?.refresh(); }
  function settingsTabKeydown(event) {
    const tabs = [...document.querySelectorAll('[data-settings-tab]')];
    const index = tabs.indexOf(event.currentTarget);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : -1;
    if (next < 0) return;
    event.preventDefault(); selectSettingsTab(tabs[next].dataset.settingsTab); tabs[next].focus();
  }
  async function openSettings() {
    $('settingsDialog').showModal();
    window.HubPipBrowser?.refresh();
    window.HubOnboarding?.refreshScanLabel();
    try {
      data.settings = await api('/api/settings');
      refreshEngineLabels();
      $('approvalsApi').value = data.settings.approvals_url || '';
      $('ownerName').value = data.settings.owner_name || 'You';
      $('fullAccessPermissionMode').value = data.settings.full_access_permission_mode || 'auto';
      selectSettingsTab('general');
      $('roleModels').replaceChildren(...modelRoles.map(([key, label]) => {
        const row = el('div', 'role-row'); row.append(el('strong', '', label));
        const engine = el('select'); engine.name = `${key}_engine`; engine.setAttribute('aria-label', `${label} AI provider`);
        ['claude','codex'].forEach((name) => { const option = el('option', '', name === 'claude' ? 'Claude' : 'Codex'); option.value = name; engine.append(option); });
        engine.value = data.settings.role_models?.[key]?.engine || 'claude';
        const model = el('select'); model.name = `${key}_model`; model.setAttribute('aria-label', `${label} model`);
        modelSelect(model, engine.value, data.settings.role_models?.[key]?.model);
        engine.addEventListener('change', () => modelSelect(model, engine.value)); row.append(engine, model); return row;
      }));
      if (!data.setup) loadSetup();
    } catch (error) { $('settingsError').textContent = errorText(error); $('settingsError').hidden = false; }
  }
  async function refreshJobs() {
    try { const result = await api('/api/jobs'); data.jobs = Array.isArray(result) ? result : result.jobs || []; renderNav(); renderWorkers(); }
    catch { data.jobs = []; }
  }
  function fillScheduleAgents() {
    $('routineAgent').replaceChildren(...data.agents.filter((a) => !a.swarm && !a.archived).map((a) => { const option = el('option', '', a.name); option.value = a.id; return option; }));
  }
  async function openRoutines() { $('routinesList').replaceChildren(el('div', 'list-skeleton', 'Loading schedules…')); $('routinesDialog').showModal(); await refreshRoutines(); }
  async function refreshRoutines() {
    try { data.routines = await api('/api/routines'); renderRoutines(); }
    catch (error) { $('routinesList').replaceChildren(el('p', 'form-error', errorText(error))); }
  }
  function renderRoutines() {
    const own = data.routines?.routines || [], external = data.routines?.external || [];
    for (const list of [$('routinesList'), $('settingsRoutinesList')]) {
    list.replaceChildren();
    if (!own.length && !external.length) list.append(el('p', 'empty-note', 'No schedules yet. Create one to give a Pip a repeating task.'));
    own.forEach((routine) => {
      const agentName = agent(routine.agent_id)?.name || routine.agent_id;
      const at = routine.time ? ` at ${routine.time}` : '';
      const weekdays = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
      const schedule = routine.trigger === 'daily' ? `Every day${at}` : routine.trigger === 'weekdays' ? `Weekdays${at}` : routine.trigger === 'weekly' ? `Every ${weekdays[Number(routine.weekday)] || 'week'}${at}` : routine.trigger === 'interval' ? `Every ${routine.minutes} minutes` : routine.trigger;
      const row = el('div', 'list-card routine-row'); const failed = !!routine.error || ['failed','skipped','uncertain'].includes(routine.last_status);
      const title = el('strong', '', routine.name); if (failed) { const dot = el('span', 'schedule-error-dot'); dot.title = routine.error || routine.last_status; dot.setAttribute('aria-label', 'Schedule needs attention'); title.prepend(dot); }
      row.append(title, el('small', '', `${agentName} · ${schedule} · ${routine.next_run ? `Next ${dateTime(routine.next_run)}` : 'Awaiting next run'}`));
      if (routine.last_run) row.append(el('small', '', `Last run ${dateTime(routine.last_run)}`));
      if (failed) row.append(el('small', 'routine-error', routine.error || `Schedule ${routine.last_status}`));
      const toggle = el('button', 'secondary', routine.enabled ? 'Pause' : 'Enable'); toggle.type = 'button';
      toggle.addEventListener('click', async () => { toggle.disabled = true; try { await post('/api/routines/toggle', { id: routine.id, enabled: !routine.enabled }); await refreshRoutines(); } catch (error) { showToast(errorText(error)); toggle.disabled = false; } });
      const remove = el('button', 'secondary archive-button', 'Delete'); remove.type = 'button';
      remove.addEventListener('click', async () => {
        if (!inlineAction(remove,'Confirm delete?')) return;
        remove.disabled = true;
        try { await post('/api/routines/delete', { id: routine.id }); showToast('Schedule deleted.'); await refreshRoutines(); }
        catch (error) { showToast(errorText(error)); remove.disabled = false; }
      });
      const actions = el('div', 'row-actions'); actions.append(toggle, remove); row.append(actions); list.append(row);
    });
    external.forEach((routine) => {
      const row = el('div', 'list-card'); const times = String(routine.schedule || 'Scheduled').split(',').map((part) => part.trim()).filter(Boolean);
      const summary = times.length > 2 ? `${times.slice(0, 2).join(', ')} · ${times.length - 2} more times` : times.join(', ');
      const title = el('strong', '', routine.routine || 'Existing schedule'); if (routine.error) { const dot = el('span', 'schedule-error-dot'); dot.title = routine.error; dot.setAttribute('aria-label', 'Schedule needs attention'); title.prepend(dot); }
      row.append(title, el('small', '', `${routine.bot || 'External Pip'} · ${summary} · read only`)); if (routine.error) row.append(el('small', 'routine-error', routine.error));
      if (times.length > 2) { const details = el('details'); details.append(el('summary', '', 'Show every time'), el('p', '', times.join(', '))); row.append(details); }
      list.append(row);
    });
    }
  }
  const approvalsCategories = ['timely','funny','builds','quotes','questions'];
  async function openApprovals() {
    $('approvalsDialog').showModal();
    $('approvalsTabs').replaceChildren();
    $('approvalsBody').replaceChildren(el('div', 'list-skeleton', 'Loading drafts…'));
    if (!data.settings) {
      try { data.settings = await api('/api/settings'); }
      catch (error) { $('approvalsBody').replaceChildren(el('p', 'form-error', errorText(error))); return; }
    }
    if (!data.settings?.approvals_url) {
      const connect = el('button', 'secondary', 'Open settings');
      connect.type = 'button';
      connect.addEventListener('click', () => { closeDialog($('approvalsDialog')); openSettings(); });
      $('approvalsBody').replaceChildren(el('p', 'empty-note', 'Connect an approvals workspace in Settings to review approval drafts here.'), connect);
      return;
    }
    await refreshApprovals();
  }
  async function refreshApprovals() {
    try { data.approvals = await api('/api/approvals/workspace'); renderApprovals(); syncApprovalsButton(); }
    catch (error) { $('approvalsBody').replaceChildren(el('p', 'form-error', errorText(error))); }
  }
  function approvalsDrafts() {
    const source = data.approvals?.workspace || data.approvals || {};
    if (Array.isArray(source.drafts)) return withReviewedDrafts(source.drafts);
    const tabs = source.tabs || source;
    return withReviewedDrafts(approvalsCategories.flatMap((category) => Array.isArray(tabs[category]) ? tabs[category].map((draft) => ({ ...draft, category })) : []));
  }
  function withReviewedDrafts(drafts) {
    const ids = new Set(drafts.map((draft) => String(draft.id || draft.draft_id)));
    return [...drafts.map((draft) => {
      const review = data.approvalsReviews[String(draft.id || draft.draft_id)];
      return review?.draft?.text && review.draft.text !== draft.text ? { ...draft, text: review.draft.text } : draft;
    }), ...Object.values(data.approvalsReviews).filter((review) => review.draft && !ids.has(String(review.id))).map((review) => review.draft)];
  }
  function approvalsDetail(value) {
    if (value == null || value === '') return '';
    if (Array.isArray(value)) return value.map(approvalsDetail).filter(Boolean).join(' · ');
    if (typeof value === 'object') return Object.entries(value).map(([key, item]) => { const detail = approvalsDetail(item); return detail ? `${key}: ${detail}` : ''; }).filter(Boolean).join(' · ');
    return String(value).trim();
  }
  async function checkApprovalsDecision(id) {
    const key = String(id), review = data.approvalsReviews[key]; if (!review || review.checking || review.phase === 'scheduled' || review.phase === 'held') return;
    review.checking = true;
    try {
      const result = await api(`/api/approvals/decision?id=${encodeURIComponent(key)}`);
      review.decision = result?.decision || null;
      if (result?.status === 'scheduled' || result?.status === 'held') review.phase = result.status;
      else review.phase = Date.now() >= review.deadline ? 'pending_timeout' : 'pending';
    } catch (error) { review.phase = Date.now() >= review.deadline ? 'pending_timeout' : 'pending'; review.error = errorText(error); }
    finally {
      review.checking = false;
      persistApprovalsReviews();
      clearTimeout(review.timer);
      if (review.phase === 'pending' && data.authenticated) review.timer = setTimeout(() => checkApprovalsDecision(key), 2000);
      if ($('approvalsDialog').open) renderApprovals();
    }
  }
  async function submitApprovalsReview(draft, action, text, reason) {
    const id = draft.id || draft.draft_id, key = String(id);
    const previous = data.approvalsReviews[key];
    if (!id || (previous && !(previous.action === 'edit' && previous.phase === 'saved'))) return;
    const review = data.approvalsReviews[key] = { id: key, draft, action, phase: 'submitting', deadline: Date.now() + 20000, timer: null, checking: false, decision: null, error: '' };
    persistApprovalsReviews();
    renderApprovals();
    try {
      await post('/api/approvals/review', { id, action, text, reason });
      review.phase = action === 'approve' ? 'pending' : 'saved';
      if (action === 'edit') review.draft = { ...draft, text };
      persistApprovalsReviews();
      showToast(action === 'approve' ? 'Review saved; waiting for scheduling result.' : action === 'deny' ? 'Skip review saved.' : 'Edit review saved.');
      renderApprovals();
      if (action === 'approve') await checkApprovalsDecision(key);
    } catch (error) {
      review.phase = 'uncertain'; review.deadline = Date.now(); review.error = errorText(error);
      persistApprovalsReviews();
      showToast('Review outcome unknown. Check status before taking another action.');
      renderApprovals();
    }
  }
  function renderApprovals() {
    $('approvalsTabs').replaceChildren(...approvalsCategories.map((name) => {
      const button = el('button', `tab${data.approvalsTab === name ? ' selected' : ''}`, name[0].toUpperCase() + name.slice(1)); button.type = 'button';
      button.addEventListener('click', () => { data.approvalsTab = name; renderApprovals(); }); return button;
    }));
    const drafts = approvalsDrafts().filter((draft) => String(draft.category || draft.tab || 'timely').toLowerCase() === data.approvalsTab);
    $('approvalsBody').replaceChildren();
    if (!drafts.length) { $('approvalsBody').append(el('p', 'empty-note', 'Drafts waiting for review will appear in this tab.')); const refresh = el('button', 'secondary', 'Check for drafts'); refresh.addEventListener('click', refreshApprovals); $('approvalsBody').append(refresh); }
    drafts.forEach((draft) => {
      const card = el('article', 'list-card approvals-card'); const id = draft.id || draft.draft_id, review = data.approvalsReviews[String(id)];
      card.append(el('strong', '', draft.title || `Draft ${id || ''}`), el('p', '', draft.text || draft.content || draft.body || ''));
      [['Hold reasons', draft.hold_reasons], ['Holds', draft.holds], ['Reason', draft.reason], ['Error', draft.error]].forEach(([label, value]) => { const detail = approvalsDetail(value); if (detail) card.append(el('p', 'field-help', `${label}: ${detail}`)); });
      if (review) {
        const labels = { submitting: 'Saving review…', pending: 'Review saved; waiting for scheduling result.', pending_timeout: 'Review saved; scheduling result still pending.', uncertain: 'Review outcome unknown. Check status before another action.', scheduled: 'Scheduled by the connected service.', held: 'Held by the connected service.', saved: 'Review saved.' };
        card.append(el('small', 'approvals-status', labels[review.phase] || 'Review saved.'));
        if (review.error) card.append(el('p', 'field-help', `Status check: ${review.error}`));
        const decision = review.decision || {};
        [['Decision reason', decision.reason], ['Decision result', decision.result]].forEach(([label, value]) => { const detail = approvalsDetail(value); if (detail) card.append(el('p', 'field-help', `${label}: ${detail}`)); });
        if (review.phase === 'pending_timeout' || review.phase === 'uncertain') {
          const check = el('button', 'secondary', 'Check status'); check.type = 'button'; check.disabled = review.checking;
          check.addEventListener('click', () => { review.deadline = Date.now(); check.disabled = true; checkApprovalsDecision(id); }); card.append(check);
        }
      }
      const buttons = el('div', 'card-actions');
      buttons.dataset.pending = String(review?.phase === 'submitting');
      [['Approve for schedule','approve'],['Skip','deny'],['Edit','edit']].forEach(([label, action]) => {
        const button = el('button', '', label); button.type = 'button'; button.disabled = !!review && !(review.action === 'edit' && review.phase === 'saved');
        button.addEventListener('click', async () => {
          let text = '', reason = '';
          if (action === 'edit') { text = await appActionDialog({title:'Edit draft',accept:'Save draft',value:draft.text || draft.content || ''}); if (text === null || !text.trim()) return; }
          if (action === 'deny') { reason = await appActionDialog({title:'Skip draft?',accept:'Skip draft',value:'',optional:true}); if(reason===null)return; }
          await submitApprovalsReview(draft, action, text, reason);
        }); buttons.append(button);
      }); card.append(buttons); $('approvalsBody').append(card);
    });
  }
  function renderSwarmWorkers() {
    const count = Math.min(8, Math.max(1, Number($('swarmCount').value) || 1));
    const container = $('swarmWorkers');
    const old = [...container.querySelectorAll('.swarm-worker')].map((row) => ({
      role: row.querySelector('input').value, slice: row.querySelectorAll('input')[1].value, engine: row.querySelector('select').value,
      model: row.querySelectorAll('select')[1].value, source_agent_id: row.dataset.sourceAgentId
    }));
    container.replaceChildren(...Array.from({ length: count }, (_, index) => {
      const row = el('div', 'swarm-worker');
      const role = el('input'); role.type = 'text'; role.maxLength = 80; role.placeholder = `Worker ${index + 1} role`;
      role.value = old[index]?.role || ($('swarmShape').value === 'roles' ? ['Researcher','Builder','Reviewer'][index] : null) || `Worker ${index + 1}`;
      role.setAttribute('aria-label', `Worker ${index + 1} role`);
      const slice = el('input'); slice.type = 'text'; slice.maxLength = 1000; slice.placeholder = 'Specific assignment (optional)'; slice.value = old[index]?.slice || '';
      slice.setAttribute('aria-label', `Worker ${index + 1} assignment`);
      const engine = el('select'); engine.setAttribute('aria-label', `Worker ${index + 1} engine`);
      ['claude','codex'].forEach((name) => { const option = el('option', '', engineLabel(name)); option.value = name; engine.append(option); });
      const roleKey = $('swarmShape').value === 'roles' ? ['orchestrator', 'worker', 'reviewer'][index] || 'worker' : 'worker';
      const roleDefault = data.settings?.role_models?.[roleKey];
      engine.value = old[index]?.engine || roleDefault?.engine || $('swarmAllEngine').value || 'claude';
      const model = el('select'); model.setAttribute('aria-label', `Worker ${index + 1} model`);
      modelSelect(model, engine.value, old[index]?.model || roleDefault?.model || $('swarmAllModel').value);
      engine.addEventListener('change', () => modelSelect(model, engine.value));
      const source = el('select'); source.setAttribute('aria-label', `Worker ${index + 1} Pip`);
      const custom = el('option', '', 'Custom helper'); custom.value = ''; source.append(custom);
      data.agents.filter((a) => !a.swarm).forEach((a) => { const option = el('option', '', a.name); option.value = a.id; source.append(option); });
      row.dataset.sourceAgentId = old[index]?.source_agent_id || ''; source.value = row.dataset.sourceAgentId;
      row.append(role, slice, engine, model, source);
      source.addEventListener('change', () => { const selected = agent(source.value); if (selected) setWorkerAgent(row, selected); else row.dataset.sourceAgentId = ''; });
      return row;
    }));
  }
  async function refreshSwarms() {
    if (!$('swarmResults').children.length) $('swarmResults').append(el('div', 'list-skeleton', 'Loading team task results…'));
    try { const result = await api('/api/swarms'); data.swarms = result.swarms || []; renderSwarmResults(); }
    catch (error) { if ($('swarmResultsDialog').open) $('swarmResults').replaceChildren(el('p', 'form-error', errorText(error))); }
  }
  function renderSwarmResults() {
    const target = $('swarmResults'); target.replaceChildren();
    if (!data.swarms.length) { target.append(el('p', 'empty-note', 'Team tasks split a larger task between Pips and keep their results together.')); const create = el('button', 'secondary', 'Run a team task'); create.addEventListener('click', () => { closeDialog($('swarmResultsDialog')); openTeam(); }); target.append(create); return; }
    if (data.swarmFocus && !data.swarms.some((swarm) => swarm.id === data.swarmFocus)) { target.append(el('p', 'empty-note', 'This team task is archived. Its saved answers remain in the chat.')); return; }
    data.swarms.filter((swarm) => !data.swarmFocus || swarm.id === data.swarmFocus).forEach((swarm) => {
      const group = el('section', 'swarm-result'); group.append(el('h3', '', swarm.goal || `Team task ${swarm.id}`));
      const workers = (swarm.workers || []).filter((worker) => Number(worker.number) !== 0);
      const finished = workers.filter((worker) => worker.terminal === true || ['pass','issues','blocked','gap','done','failed'].includes(String(worker.status).toLowerCase())).length;
      group.append(el('small', '', `${finished} of ${workers.length} helpers finished${swarm.shape ? ` · ${swarm.shape === 'race' ? 'Compare answers' : swarm.shape === 'roles' ? 'Research → Build → Review' : 'Split the work'}` : ''}`));
      if (swarm.judge_pick) group.append(el('div', 'judge-chip', `Recommended: ${swarm.judge_pick}`));
      (swarm.workers || []).forEach((worker) => {
        if (Number(worker.number) === 0) return;
        const card = el('article', 'list-card team-answer');
        const heading = el('div', 'team-answer-heading'); heading.append(el('strong', '', worker.role || `Helper ${worker.number || ''}`));
        const verdict = ['pass','issues','blocked','gap'].includes(String(worker.status).toLowerCase()) ? String(worker.status).toLowerCase() : /^(PASS|ISSUES|BLOCKED)\b/i.exec(String(worker.report || '').trim())?.[1]?.toLowerCase();
        const status = worker.outcome === 'merged' ? 'Merged' : worker.outcome === 'discarded' ? 'Discarded' : teamStatus(verdict || worker.status || 'Queued');
        heading.append(el('span', `team-status ${String(status).toLowerCase().replace(/[^a-z]+/g, '-')}`, status)); card.append(heading);
        const report = worker.report;
        const plainReport = typeof report === 'string' && !/^(?:Status|Evidence|Files|Handoff|Pick|Scores):/mi.test(report) ? report.replace(/^(PASS|ISSUES|BLOCKED)\s*[:—-]?\s*/i, '') : '';
        const answer = worker.answer || (typeof report === 'object' ? report?.summary || report?.text : plainReport);
        card.append(markdown(cleanTeamAnswer(answer, swarm.goal) || (finished === workers.length ? 'No answer was returned.' : 'Working on an answer…'), 'team-answer-text'));
        if (status === 'Needs review') card.append(el('p','field-help',`Needs review: ${worker.issue || 'this helper flagged a problem or did not include the evidence required for a pass.'}`));
        const details = el('details', 'team-details'); details.append(el('summary', '', 'Details and files'));
        if (worker.engine || worker.model) details.append(el('small', '', `${worker.engine || ''} ${worker.model || ''}`.trim()));
        if (report && String(report) !== answer) details.append(markdown(typeof report === 'object' ? JSON.stringify(report, null, 2) : report));
        if (worker.evidence) {
          const evidence = Array.isArray(worker.evidence) ? worker.evidence.join('\n') : typeof worker.evidence === 'object' ? Object.entries(worker.evidence).map(([key,value]) => `${key}: ${value}`).join('\n') : worker.evidence;
          if (evidence && evidence !== answer) details.append(markdown(evidence));
        }
        const files = el('div', 'worker-files');
        (worker.files || []).forEach((file) => { const url = safeUrl(file?.url); if (url) { const link = el('a', '', `↓ ${file.name || 'File'}`); link.href = url; link.target = '_blank'; link.rel = 'noopener'; files.append(link); } else if (typeof file === 'string') files.append(el('span', 'file-path', file)); });
        if (files.children.length) details.append(files);
        if (details.children.length > 1) card.append(details);
        if (worker.outcome === 'merging') card.append(el('p', 'form-error', 'Merge incomplete. Inspect the project before continuing.'));
        const terminal = worker.terminal === true || ['pass','issues','blocked','gap','done','failed'].includes(String(worker.status).toLowerCase());
        if (worker.worktree && !worker.outcome && terminal && (worker.has_changes === true || Number(worker.changed_files) > 0)) {
          const actions = el('div', 'card-actions');
          [['Merge changes','merge'],['Discard changes','discard']].forEach(([label, action]) => {
            const button = el('button', '', label); button.type = 'button';
            button.addEventListener('click', async () => {
              if (!inlineAction(button,action === 'discard' ? 'Confirm discard?' : 'Confirm merge?')) return;
              actions.querySelectorAll('button').forEach((b) => { b.disabled = true; });
              button.textContent = action === 'merge' ? 'Merging…' : 'Discarding…';
              actions.dataset.pending = 'true';
              try { await post('/api/swarms/action', { id: swarm.id, action, worker: worker.agent_id, confirm_dirty: action === 'discard' }); showToast(action === 'merge' ? 'Changes merged into the project.' : 'Worktree discarded.'); await refreshSwarms(); }
              catch (error) { showToast(errorText(error)); actions.dataset.pending = 'false'; await refreshSwarms(); }
            }); actions.append(button);
          }); card.append(actions);
        }
        group.append(card);
      });
      const next = el('button', 'secondary', 'Open chat'); next.type = 'button'; next.addEventListener('click', () => { closeDialog($('swarmResultsDialog')); openChat(swarm.chat_id || `group:swarm-${swarm.id}`); }); group.append(next);
      const archive = el('button', 'secondary archive-button', 'Archive team task'); archive.type = 'button';
      archive.addEventListener('click', async () => {
        if (!inlineAction(archive,'Confirm archive?')) return;
        archive.disabled = true;
        try { await post('/api/archive', { kind: 'swarm', id: swarm.id, confirm: true }); showToast('Team task archived.'); await refreshSwarms(); await refreshState(); }
        catch (error) {
          if (/worktree has changes|confirm discarding/i.test(errorText(error)) && await appActionDialog({title:'Discard unmerged files?',message:'This team task has unmerged changes. Discard those files and archive the task?',accept:'Discard and archive'})) {
            try { await post('/api/archive', { kind: 'swarm', id: swarm.id, confirm: true, confirm_dirty: true }); showToast('Team task archived; unmerged worktree files discarded.'); await refreshSwarms(); await refreshState(); }
            catch (retryError) { showToast(errorText(retryError)); }
          } else showToast(errorText(error));
        }
        finally { archive.disabled = false; }
      }); group.append(archive); target.append(group);
    });
  }
  async function openTeam() {
    data.proposalEdit=null;
    if (!data.settings) { try { data.settings = await api('/api/settings'); } catch (error) { showToast(errorText(error)); } }
    data.teamChatId = data.chatId;
    const members = (currentChat()?.agents || (data.chatId?.startsWith('agent:') ? [data.chatId.slice(6)] : [])).map(agent).filter((a) => a && !a.swarm).slice(0, 8);
    $('swarmWorkingDir').value = ''; $('swarmRubric').value = '';
    $('swarmGoal').value = ui.message.value;
    $('swarmGoal').placeholder = 'What should these helpers accomplish?';
    $('swarmAllEngine').value = data.settings?.role_models?.worker?.engine || 'claude';
    modelSelect($('swarmAllModel'), $('swarmAllEngine').value, data.settings?.role_models?.worker?.model);
    $('swarmCount').value = String(members.length || 2); $('swarmShape').value = 'partition';
    $('swarmWorkers').replaceChildren(); renderSwarmWorkers();
    [...$('swarmWorkers').querySelectorAll('.swarm-worker')].forEach((row, index) => { if (members[index]) setWorkerAgent(row, members[index]); });
    clearSwarmError(); $('swarmWorkingDir').dispatchEvent(new Event('input')); $('swarmDialog').showModal();
  }
  function setWorkerAgent(row, item) {
    row.dataset.sourceAgentId = item.id;
    row.querySelector('input').value = item.name;
    row.querySelectorAll('input')[1].value = String(item.title || '').slice(0, 1000);
    const selects = row.querySelectorAll('select'); selects[0].value = item.engine; modelSelect(selects[1], item.engine, item.model); selects[2].value = item.id;
  }
  async function prepareTeam(team, createdAgents = []) {
    await openTeam();
    const names = Array.isArray(team?.agents) ? team.agents : [];
    const members = names.map((name) => createdAgents.find((entry) => [entry.original_name, entry.name, entry.suggestion?.name].some((value) => String(value || '').toLowerCase() === String(name).toLowerCase())) || data.agents.find((entry) => [entry.name,entry.id].some((value)=>String(value || '').toLowerCase() === String(name).toLowerCase()))).filter(Boolean).slice(0, 8);
    if (members.length) {
      $('swarmCount').value = String(members.length); $('swarmShape').value = 'partition'; $('swarmWorkers').replaceChildren(); renderSwarmWorkers();
      [...$('swarmWorkers').querySelectorAll('.swarm-worker')].forEach((row, index) => {
        const item = members[index], suggestion = item.suggestion || item;
        if (item.id) setWorkerAgent(row, { ...suggestion, ...item });
        row.querySelector('input').value = item.name || suggestion.name || names[index];
        row.querySelectorAll('input')[1].value = String(suggestion.role || suggestion.title || `Contribute your expertise to ${team.name || 'this task'}`).slice(0, 1000);
        const engine = row.querySelector('select'), model = row.querySelectorAll('select')[1];
        engine.value = suggestion.engine || 'claude'; modelSelect(model, engine.value, suggestion.model);
      });
    }
    $('swarmGoal').value = ''; $('swarmGoal').placeholder = `Goal for ${team?.name || 'this team'} (required before launch)`;
    $('swarmGoal').focus();
  }
  function closeMenus() {
    [['newChatMenu','newChatButton'],['attachMenu','attachButton']].forEach(([id, trigger]) => { $(id).hidden = true; $(trigger).setAttribute('aria-expanded', 'false'); });
  }
  function toggleMenu(id, trigger) { const open = $(id).hidden; closeMenus(); $(id).hidden = !open; $(trigger).setAttribute('aria-expanded', String(open)); if (open) { if (id === 'newChatMenu') { const rect = $(trigger).getBoundingClientRect(); $(id).style.top = `${rect.bottom + 4}px`; $(id).style.left = `${Math.max(8, rect.left)}px`; } $(id).querySelector('button')?.focus(); } }
  function openAgentPicker(fresh = false) {
    closeMenus();
    $('agentPickerList').replaceChildren(...data.agents.filter((a) => !a.swarm).map((a) => {
      const button = el('button', 'nav-item'); button.type = 'button'; button.append(avatar(a.emoji, a.avatar, '', a), el('span', '', a.name));
      button.addEventListener('click', async () => { const draft = ui.message.value; closeDialog($('agentPickerDialog')); if (fresh) await parity?.newChat(a); else await openChat(directId(a.id)); ui.message.value = draft; resizeComposer(); ui.message.focus(); }); return button;
    }));
    const create = el('button', 'secondary', 'Create a new Pip'); create.type = 'button'; create.addEventListener('click', () => { closeDialog($('agentPickerDialog')); $('newAgentButton').click(); }); $('agentPickerList').append(create);
    $('agentPickerDialog').showModal();
  }
  function modelAgentChanged() {
    const a = agent($('composerAgent').value); if (!a) return;
    $('composerEngine').value = a.engine; modelSelect($('composerModel'), a.engine, a.model);
    const external = a.external === true || a.source === 'external' || a.managed === false;
    $('composerEngine').disabled = external; $('composerModel').disabled = external;
    $('modelNote').textContent = external ? 'This linked Pip keeps its existing model.' : 'Changing the provider or model starts a fresh AI session. Chat history stays here.';
  }
  function openModelSelector() {
    if (!data.agents.some((a) => !a.swarm)) { openAgentPicker(); return; }
    const members = currentChat()?.type === 'group' ? currentChat().agents : null;
    const options = data.agents.filter((a) => members ? members.includes(a.id) : !a.swarm);
    $('composerAgent').replaceChildren(...options.map((a) => { const option = el('option', '', a.name); option.value = a.id; return option; }));
    $('composerAgent').value = composeAgent()?.id || options[0]?.id || '';
    modelAgentChanged(); $('modelError').hidden = true; $('modelDialog').showModal();
  }
  function setSidebarCollapsed(collapsed) {
    ui.app.classList.toggle('sidebar-collapsed', collapsed);
    $('sidebarCollapseButton').setAttribute('aria-expanded', String(!collapsed));
    $('sidebarCollapseButton').title = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
    $('sidebarCollapseButton').setAttribute('aria-label', $('sidebarCollapseButton').title);
    try { localStorage.setItem('agent-hub-sidebar-collapsed', String(collapsed)); } catch { /* private storage */ }
  }
  function setupSidebarSearch() {
    $('searchButton').addEventListener('input', () => { data.navFilter = $('searchButton').value; renderNav(); });
    $('searchButton').addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); openPalette(); } });
    $('sidebarSearchTrigger').addEventListener('click', () => { if (ui.app.classList.contains('sidebar-collapsed')) { setSidebarCollapsed(false); $('searchButton').focus(); } });
    $('pipsHeading').addEventListener('click', () => openDirectory('agents'));
    $('groupsHeading').addEventListener('click', () => openDirectory('groups'));
    document.addEventListener('keydown', (event) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); $('paletteDialog').open ? closeDialog($('paletteDialog')) : openPalette(); } });
  }
  function setup() {
    parity?.setup();
    setupMessageInteractions();
    try { setSidebarCollapsed(localStorage.getItem('agent-hub-sidebar-collapsed') === 'true'); } catch { /* private storage */ }
    $('sidebarCollapseButton').addEventListener('click', () => setSidebarCollapsed(!ui.app.classList.contains('sidebar-collapsed')));
    $('newChatButton').addEventListener('click', () => toggleMenu('newChatMenu', 'newChatButton'));
    $('pickAgentButton').addEventListener('click', () => openAgentPicker(true));
    document.addEventListener('click', (event) => { if (!event.target.closest('#newChatMenu,#newChatButton,#attachMenu,#attachButton')) closeMenus(); });
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeMenus(); });
    $('suggestionChips').querySelectorAll('button').forEach((button) => button.addEventListener('click', () => guidePrompt(button.dataset.prompt)));
    setupSidebarSearch();
    ['directorySearch','directorySort','directoryRole'].forEach((id) => $(id).addEventListener(id === 'directorySearch' ? 'input' : 'change', () => { data.directoryPage=0; renderDirectory(); }));
    $('directoryArchive').addEventListener('click', archiveDirectory);
    $('directoryShowHidden').addEventListener('change', renderDirectory);
    window.addEventListener('resize', () => { if ($('directoryDialog').open) renderDirectory(); });
    $('modelSelector').addEventListener('click', openModelSelector);
    $('composerAgent').addEventListener('change', modelAgentChanged);
    $('composerEngine').addEventListener('change', () => modelSelect($('composerModel'), $('composerEngine').value));
    $('modelForm').addEventListener('submit', async (event) => {
      event.preventDefault(); const form = $('modelForm'); if (form.dataset.pending === 'true') return;
      const a = agent($('composerAgent').value); if (!a) return;
      form.dataset.pending = 'true'; const button = form.querySelector('button[type="submit"]'); button.disabled = true;
      try {
        if (!$('composerEngine').disabled && (a.engine !== $('composerEngine').value || a.model !== $('composerModel').value)) await post('/api/agents/update', { id: a.id, engine: $('composerEngine').value, model: $('composerModel').value });
        const draft = ui.message.value;
        await refreshState();
        if (data.chatId && currentChat()?.type !== 'group' && data.chatId !== directId(a.id)) { await openChat(directId(a.id)); ui.message.value = draft; resizeComposer(); }
        data.composeAgentId = a.id; renderHeader(); closeDialog($('modelDialog'));
      } catch (error) { $('modelError').textContent = errorText(error); $('modelError').hidden = false; }
      finally { form.dataset.pending = 'false'; button.disabled = false; }
    });
    let saved; try { saved = localStorage.getItem(storageKey); } catch { /* ignore */ }
    theme(saved === 'dark' ? 'dark' : 'light');
    ['themeSettings'].forEach((id) => $(id).addEventListener('click', () => theme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark')));
    $('backButton').addEventListener('click', () => { if (history.state?.chat) history.back(); else { ui.app.classList.remove('chat-open'); renderNav(); } });
    window.addEventListener('popstate', (event) => {
      if (event.state?.chat) openChat(event.state.chat, false).then(() => ui.app.classList.add('chat-open'));
      else { ui.app.classList.remove('chat-open'); renderNav(); }
    });
    $('chatManageButton').addEventListener('click', async () => {
      const c = currentChat(); if (!c) return;
      const a = c.type === 'direct' ? agent(c.agents?.[0] || String(c.id).slice(6)) : null;
      const kind = a ? 'agent' : 'group'; const id = a?.id || c.id;
      const hideOnly = a?.external === true || a?.linked === true;
      $('manageTitle').textContent = `Manage ${a?.name || c.name}`;
      const body = $('manageBody'); body.replaceChildren();
      if(c.demo){ const archiveDemo=el('button','secondary','Archive demo');archiveDemo.type='button';archiveDemo.addEventListener('click',async()=>{if(!inlineAction(archiveDemo,'Confirm archive?'))return;await proposalDecision(archiveDemo,'/api/guide/demo/archive',{});if(!data.chats.some((chat)=>chat.id===c.id))closeDialog($('manageDialog'));});body.append(archiveDemo); }
      const team = el('button', 'secondary', 'Run as a team task…'); team.type = 'button'; team.addEventListener('click', () => { closeDialog($('manageDialog')); openTeam(); }); body.append(team);
      const results = el('button', 'secondary', 'Team task results'); results.type = 'button'; results.addEventListener('click', () => { closeDialog($('manageDialog')); openTeamResults(c.swarm_id || null); }); body.append(results);
      if (a) {
        agentSettings(body, a);
      } else {
        const label = el('label', '', 'Group name');
        const input = el('input'); input.value = c.name || ''; input.maxLength = 80; input.setAttribute('aria-label', 'Group name');
        const rename = el('button', 'secondary', 'Save name'); rename.type = 'button';
        rename.addEventListener('click', async () => {
          const name = input.value.trim();
          if (!name) { showToast('Enter a group name.'); input.focus(); return; }
          rename.disabled = true;
          try { await post('/api/groups/rename', { id: c.id, name, emoji: emojiInput.value.trim() || '👥' }); $('manageTitle').textContent = `Manage ${name}`; await refreshState(); showToast('Group renamed.'); }
          catch (error) { showToast(errorText(error)); }
          finally { rename.disabled = false; }
        });
        const emojiLabel = el('label', '', 'Group emoji'), emojiInput = el('input'); emojiInput.value = c.emoji || '👥'; emojiInput.maxLength = 64; emojiInput.setAttribute('aria-label', 'Group emoji'); const emojiPick = el('button', 'emoji-open', '☺'); emojiPick.type = 'button'; emojiPick.addEventListener('click', () => window.HubEmoji?.open(emojiInput));
        rename.textContent = 'Save group';
        body.append(label, input, emojiLabel, emojiInput, emojiPick, rename);
      }
      const schedule = el('button', 'secondary', 'Schedule this chat'); schedule.type = 'button'; schedule.addEventListener('click', () => { closeDialog($('manageDialog')); $('newRoutineButton').click(); $('routineAgent').value = a?.id || c.agents?.[0] || ''; }); body.append(schedule);
      const jobs = el('button', 'secondary', 'Jobs'); jobs.type = 'button'; jobs.addEventListener('click', () => { closeDialog($('manageDialog')); $('workersButton').click(); }); body.append(jobs);
      const exportMd = el('button', 'secondary', 'Export chat (Markdown)'); exportMd.type = 'button'; exportMd.addEventListener('click', () => exportFile(`/api/export/chat?chat_id=${encodeURIComponent(c.id)}&format=md`)); body.append(exportMd);
      const exportJson = el('button', 'secondary', 'Export chat (JSON)'); exportJson.type = 'button'; exportJson.addEventListener('click', () => exportFile(`/api/export/chat?chat_id=${encodeURIComponent(c.id)}&format=json`)); body.append(exportJson);
      const archive = el('button', 'secondary archive-button', hideOnly ? 'Hide linked Pip' : `Archive ${kind}`); archive.type = 'button'; body.append(archive);
      archive.addEventListener('click', async () => {
        if (!inlineAction(archive,hideOnly ? 'Confirm hide?' : 'Confirm archive?')) return;
        archive.disabled = true;
        try { await post('/api/archive', { kind, id }); closeDialog($('manageDialog')); data.chatId = null; history.replaceState({}, '', location.pathname); ui.app.classList.remove('chat-open'); ui.empty.hidden = false; ui.viewport.hidden = true; ui.composer.hidden = true; showToast(kind === 'agent' ? 'Pip hidden. Restore it from All Pips → Show hidden.' : 'Group archived.'); await refreshState(); }
        catch (error) { showToast(errorText(error)); archive.disabled = false; }
      });
      $('manageDialog').showModal();
    });
    $('helpButton').addEventListener('click', () => $('helpDialog').showModal());
    $('replayTour').addEventListener('click', () => { closeDialog($('helpDialog')); showCoach(); });
    $('coachNext').addEventListener('click', () => { if (data.coachStep < 3) showCoach(data.coachStep + 1); else closeCoach(); });
    $('coachSkip').addEventListener('click', closeCoach);
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !$('coachDialog').hidden) closeCoach(); });
    window.addEventListener('resize', () => { if (!$('coachDialog').hidden) positionCoach($(['newChatButton','newChatButton',data.chatId ? 'attachButton' : 'newChatButton',data.chatId ? 'composer' : 'newChatButton'][data.coachStep])); });
    $('coachTry').addEventListener('click', () => {
      const step = data.coachStep; data.resumeCoach = step + 1; closeCoach();
      if (step === 0) $('newAgentButton').click();
      else if (step === 1) $('newGroupButton').click();
      else if (step === 2) openTeam();
    });
    [ui.agentDialog, ui.groupDialog, $('swarmDialog')].forEach((dialog) => dialog.addEventListener('close', () => {
      if (data.resumeCoach != null && $('coachDialog').hidden) { const next = data.resumeCoach; data.resumeCoach = null; setTimeout(() => showCoach(next), 0); }
    }));
    [['coachApprove','Approved'],['coachHold','Held']].forEach(([id, decision]) => $(id).addEventListener('click', () => { $('coachDecision').textContent = `Demo decision: ${decision}. A real card records your choice in chat.`; $('coachDecision').hidden = false; }));
    $('welcomeLater').addEventListener('click', dismissWelcome);
    $('welcomeDialog').addEventListener('cancel', dismissWelcome);
    $('welcomeCreate').addEventListener('click', () => { const [name, description, role] = templates[data.welcomeTemplate]; closeDialog($('welcomeDialog')); data.tourAfterCreate = true; $('newAgentButton').click(); $('agentName').value = name; $('agentTitle').value = description; $('agentRole').value = role; });
    [['welcomeMorning','morningPreset'],['welcomeWeekly','weeklyPreset']].forEach(([id, preset]) => $(id).addEventListener('click', () => {
      closeDialog($('welcomeDialog'));
      if (data.agents.length) { $('newRoutineButton').click(); $(preset).click(); }
      else { data.scheduleAfterCreate = preset; $('welcomeCreate').click(); data.tourAfterCreate = false; }
    }));
    ui.agentDialog.addEventListener('close', () => { if (ui.agentForm.dataset.pending !== 'true') data.scheduleAfterCreate = null; });
    $('gettingStartedAgent').addEventListener('click', openGettingStartedGuide);
    $('gettingStartedTour').addEventListener('click', () => showCoach());
    ['welcomePhone','helpPhone'].forEach((id) => $(id).addEventListener('click', () => { closeDialog($(id).closest('dialog')); window.HubPhone?.open(); }));
    $('paletteInput').addEventListener('input', () => { clearTimeout(data.searchTimer); data.searchTimer = setTimeout(renderPalette, 180); });
    $('paletteDialog').addEventListener('keydown', onPaletteKeydown, true);
    $('paletteInput').addEventListener('keydown', (event) => { if (event.key === 'Enter') { const first = $('paletteResults').querySelector('button'); if (first) { event.preventDefault(); first.click(); } } });
    $('cancelReply').addEventListener('click', () => { data.replyTo = []; renderReply(); });
    $('askEveryoneButton').addEventListener('click', askEveryone);
    setupComposerInteractions();
    setupAttachments();
    ui.loginForm.addEventListener('submit', async (event) => {
      event.preventDefault(); if (ui.loginForm.dataset.pending === 'true') return; ui.loginForm.dataset.pending = 'true'; ui.loginButton.disabled = true; ui.loginError.hidden = true;
      try { await post('/api/login', { token: ui.token.value }); await refreshState(); connectEvents(); refreshWorkers(); loadSetup(); }
      catch (error) { ui.loginError.textContent = errorText(error); ui.loginError.hidden = false; }
      finally { ui.loginForm.dataset.pending = 'false'; ui.loginButton.disabled = false; }
    });
    $('logoutButton').addEventListener('click', async () => { if(!inlineAction($('logoutButton'),'Confirm sign out?'))return; try { await post('/api/logout', {}); } catch { /* clear local view regardless */ } showLogin(); });
    $('newAgentButton').addEventListener('click', () => { data.proposalEdit = null; closeMenus(); $('agentEngine').value = data.setup?.default_engine || $('agentEngine').value; modelSelect($('agentModel'), $('agentEngine').value); $('agentPrivatePip').checked = false; $('agentDraftOnly').checked = false; $('agentChrome').checked = false; syncCreateBrowser(true); $('agentPipStyle').replaceChildren(pipPicker({id:'new-pip'}, false)); ui.agentDialog.showModal(); $('agentName').focus(); });
    $('agentPrivatePip').addEventListener('change', syncCreateBrowser);
    $('agentDraftOnly').addEventListener('change', syncCreateBrowser);
    $('searchShortcut').textContent = /Mac|iPhone|iPad/.test(navigator.platform || '') ? '⌘ K' : 'Ctrl+K';
    $('agentEmojiPicker').addEventListener('click', () => window.HubEmoji?.open($('agentEmoji')));
    $('groupEmojiPicker').addEventListener('click', () => window.HubEmoji?.open($('groupEmoji')));
    $('agentEngine').addEventListener('change', () => modelSelect($('agentModel'), $('agentEngine').value));
    $('newGroupButton').addEventListener('click', () => { data.proposalEdit = null; closeMenus();
      ui.groupAgents.replaceChildren(...data.agents.map((a) => {
        const label = el('label'); const check = el('input'); check.type = 'checkbox'; check.name = 'agents'; check.value = a.id; label.append(check, avatar(a.emoji,a.avatar,'',a), el('span', '', a.name)); return label;
      })); ui.groupDialog.showModal(); $('groupName').focus();
    });
    document.querySelectorAll('.close-dialog').forEach((button) => button.addEventListener('click', () => closeDialog(button.closest('dialog'))));
    document.querySelectorAll('dialog').forEach((dialog) => dialog.addEventListener('click', (event) => { if (event.target === dialog) closeDialog(dialog); }));
    ui.agentForm.addEventListener('submit', async (event) => {
      event.preventDefault(); if (ui.agentForm.dataset.pending === 'true') return; ui.agentForm.dataset.pending = 'true'; ui.agentError.hidden = true; $('createAgentButton').disabled = true; $('createAgentButton').textContent = 'Creating…';
      const form = new FormData(ui.agentForm);
      try {
        const payload = { name: String(form.get('name')).trim(), title: String(form.get('title')).trim(), emoji: String(form.get('emoji')).trim() || '🤖', role: String(form.get('role')).trim(), engine: String(form.get('engine')), model: String(form.get('model')), private_pip: $('agentPrivatePip').checked, draft_only: $('agentDraftOnly').checked, chrome: $('agentChrome').checked, workdir: $('agentWorkdir').value.trim() || null, ...readPipPicker($('agentPipStyle')) };
        const edit = data.proposalEdit;
        const response = edit ? await post('/api/guide/proposal', {message_id:edit.message_id,index:edit.index,action:'create',proposal:{...edit.proposal,...payload,instructions:payload.role}}) : await post('/api/agents', payload);
        const result=response.result || response; showCreatedToast(edit ? response : {result:response});
        data.proposalEdit=null; closeDialog(ui.agentDialog); ui.agentForm.reset();
        if (result.chat_id) { data.stateRequest++; data.creatingChatId = String(result.chat_id); }
        await refreshState(); if (result.chat_id) await openChat(result.chat_id);
        data.creatingChatId = null;
        await productAction('complete_getting_started');
        if (data.scheduleAfterCreate) { const preset = data.scheduleAfterCreate; data.scheduleAfterCreate = null; $('newRoutineButton').click(); $(preset).click(); }
        else if (data.tourAfterCreate) { data.tourAfterCreate = false; showCoach(); }
      } catch (error) { data.creatingChatId = null; ui.agentError.textContent = errorText(error); ui.agentError.hidden = false; }
      finally { ui.agentForm.dataset.pending = 'false'; $('createAgentButton').disabled = false; $('createAgentButton').textContent = 'Create Pip'; }
    });
    ui.groupForm.addEventListener('submit', async (event) => {
      event.preventDefault(); if (ui.groupForm.dataset.pending === 'true') return; ui.groupError.hidden = true;
      const chosen = [...ui.groupAgents.querySelectorAll('input:checked')].map((x) => x.value);
      if (chosen.length < 2) { ui.groupError.textContent = 'Choose at least two Pips.'; ui.groupError.hidden = false; return; }
      ui.groupForm.dataset.pending = 'true'; $('createGroupButton').disabled = true; $('createGroupButton').textContent = 'Creating…';
      try {
        const payload={name:$('groupName').value.trim(),emoji:$('groupEmoji').value.trim() || '👥',agents:chosen.map((id)=>id.startsWith('new:') ? data.proposalEdit?.proposal.agents.filter((a)=>typeof a==='object')[Number(id.slice(4))] : id)};
        const edit=data.proposalEdit; const response=edit ? await post('/api/guide/proposal',{message_id:edit.message_id,index:edit.index,action:'create',proposal:{...edit.proposal,...payload}}) : await post('/api/groups',payload); const result=response.result || response;showCreatedToast(edit ? response : {result:response}); data.proposalEdit=null;
        closeDialog(ui.groupDialog); ui.groupForm.reset(); if (result.chat?.id) { data.stateRequest++; data.creatingChatId = String(result.chat.id); } await refreshState(); if (result.chat?.id) await openChat(result.chat.id); data.creatingChatId = null;
      } catch (error) { data.creatingChatId = null; ui.groupError.textContent = errorText(error); ui.groupError.hidden = false; }
      finally { ui.groupForm.dataset.pending = 'false'; $('createGroupButton').disabled = false; $('createGroupButton').textContent = 'Create group'; }
    });
    [$('workersButton'), $('chatWorkersButton')].forEach((button) => button.addEventListener('click', () => { renderWorkers(); ui.workersDialog.showModal(); refreshWorkers(); }));
    $('settingsButton').addEventListener('click', openSettings);
    $('exportEverything').addEventListener('click', () => exportFile('/api/export/everything'));
    ui.viewport.addEventListener('scroll', () => $('conversation').classList.toggle('has-scrolled-messages', ui.viewport.scrollTop > 2));
    ui.viewport.addEventListener('wheel', () => { conversationScrollPending = false; }, { passive: true });
    ui.viewport.addEventListener('touchmove', () => { conversationScrollPending = false; }, { passive: true });
    $('routinesButton').addEventListener('click', openRoutines);
    $('approvalsButton').addEventListener('click', openApprovals);
    $('teamTaskButton').addEventListener('click', () => { closeMenus(); openTeam(); });
    $('swarmForm').addEventListener('input', clearSwarmError);
    $('swarmForm').addEventListener('change', clearSwarmError);
    $('swarmCount').addEventListener('input', renderSwarmWorkers);
    $('swarmShape').addEventListener('change', renderSwarmWorkers);
    $('swarmAllEngine').addEventListener('change', () => { modelSelect($('swarmAllModel'), $('swarmAllEngine').value); $('swarmWorkers').querySelectorAll('.swarm-worker').forEach((row) => { row.querySelector('select').value = $('swarmAllEngine').value; modelSelect(row.querySelectorAll('select')[1], $('swarmAllEngine').value); }); });
    $('swarmAllModel').addEventListener('change', () => { $('swarmWorkers').querySelectorAll('.swarm-worker').forEach((row) => { row.querySelector('select').value = $('swarmAllEngine').value; modelSelect(row.querySelectorAll('select')[1], $('swarmAllEngine').value, $('swarmAllModel').value); }); });
    $('swarmWorkingDir').addEventListener('input', () => {
      const folder = $('swarmWorkingDir').value.trim();
      clearTimeout(data.projectTimer); data.projectCheck = null; $('swarmIsolateLine').hidden = true; $('swarmIsolateHelp').hidden = true; $('swarmIsolate').checked = false;
      if (!folder) return;
      data.projectTimer = setTimeout(async () => {
        try {
          const result = await api(`/api/project?path=${encodeURIComponent(folder)}`);
          if ($('swarmWorkingDir').value.trim() !== folder) return;
          data.projectCheck = result; $('swarmIsolateLine').hidden = !result.worktrees_available; $('swarmIsolateHelp').hidden = !result.worktrees_available;
        } catch { /* launch validation gives a specific error */ }
      }, 250);
    });
    $('viewSwarmsButton').addEventListener('click', () => { closeDialog($('swarmDialog')); openTeamResults(); });
    $('swarmForm').addEventListener('submit', async (event) => {
      event.preventDefault(); if ($('swarmForm').dataset.pending === 'true') return; clearSwarmError();
      const count = Number($('swarmCount').value);
      if (!Number.isInteger(count) || count < 1 || count > 8) { showSwarmError('Choose 1–8 workers.'); return; }
      if (count > 5 && !await appActionDialog({title:`Launch ${count} workers?`,message:`${count} workers can use substantial model capacity.`,accept:'Launch workers'})) return;
      const shape = $('swarmShape').value;
      if (data.projectCheck?.worktrees_available && !$('swarmIsolate').checked) { showSwarmError('For this Git project, turn on separate file changes before launching.'); return; }
      const rubric = $('swarmRubric').value.split('\n').map((line) => line.trim()).filter(Boolean);
      if (shape === 'race' && (rubric.length < 3 || rubric.length > 6)) { showSwarmError('Race mode needs 3–6 success criteria, one per line.'); return; }
      const workers = [...$('swarmWorkers').querySelectorAll('.swarm-worker')].map((row, index) => ({
        role: row.querySelector('input').value.trim() || `Worker ${index + 1}`, slice: row.querySelectorAll('input')[1].value.trim(),
        engine: row.querySelector('select').value, model: row.querySelectorAll('select')[1].value, source_agent_id: row.dataset.sourceAgentId || undefined
      }));
      const submittedGoal = $('swarmGoal').value.trim(), submittedChat = data.teamChatId;
      const launch = $('swarmForm').querySelector('button[type="submit"]'); $('swarmForm').dataset.pending = 'true'; launch.disabled = true; launch.textContent = 'Launching…';
      try {
        const folder = $('swarmWorkingDir').value.trim();
        const edit=data.proposalEdit;
        const response = edit?.proposal.action==='start_team_task' ? await post('/api/guide/proposal',{message_id:edit.message_id,index:edit.index,action:'create',proposal:{...edit.proposal,group:null,agents:workers.map((w)=>w.source_agent_id).filter(Boolean),mode:shape==='partition'?'split':shape,task:submittedGoal,team_options:{working_dir:folder,workers,worktrees:!!folder && $('swarmIsolate').checked,confirm_over_five:count>5,rubric}}}) : await post('/api/swarms', { chat_id: submittedChat, goal: submittedGoal, shape, working_dir: folder, workers, worktrees: !!folder && $('swarmIsolate').checked, confirm_over_five: count > 5, rubric });
        const result=response.result || response; data.proposalEdit=null;
        closeDialog($('swarmDialog'));
        if (data.chatId === submittedChat && ui.message.value.trim() === submittedGoal) { ui.message.value = ''; ui.message.style.height = ''; }
        if (result.chat_id) { await refreshState(); await openChat(result.chat_id); }
        showToast('Team task launched. Results will appear in this chat.');
      } catch (error) { showSwarmError(errorText(error)); }
      finally { $('swarmForm').dataset.pending = 'false'; launch.disabled = false; launch.textContent = 'Run team task'; }
    });
    $('newRoutineButton').addEventListener('click', () => {
      fillScheduleAgents();
      $('routineDialog').showModal();
    });
    const routinePresets = {
      morningPreset: { name: 'Morning briefing', prompt: 'Give me a concise briefing for today: my priorities, anything I should follow up on, and one useful next step. Use only information you can actually access, and say when a source is unavailable.', trigger: 'weekdays', time: '08:00' },
      weeklyPreset: { name: 'Weekly summary', prompt: 'Summarize the work from this week that you can verify. List completed items, open items, and the next priorities. Do not invent progress or dates.', trigger: 'weekly', time: '17:00', weekday: '4' }
    };
    Object.entries(routinePresets).forEach(([id, preset]) => $(id).addEventListener('click', () => {
      $('routineName').value = preset.name; $('routinePrompt').value = preset.prompt;
      $('routineTrigger').value = preset.trigger; $('routineTime').value = preset.time;
      if (preset.weekday) $('routineWeekday').value = preset.weekday;
      $('routineTrigger').dispatchEvent(new Event('change')); $('routinePrompt').focus();
    }));
    $('settingsForm').addEventListener('submit', async (event) => {
      event.preventDefault(); if ($('settingsForm').dataset.pending === 'true') return; $('settingsError').hidden = true;
      const form = new FormData($('settingsForm')); const role_models = {};
      modelRoles.forEach(([key]) => { role_models[key] = { engine: form.get(`${key}_engine`), model: form.get(`${key}_model`) }; });
      const save = $('settingsForm').querySelector('button[type="submit"]'); $('settingsForm').dataset.pending = 'true'; save.disabled = true; save.textContent = 'Saving…';
      try { data.settings = await post('/api/settings', { role_models, owner_name: $('ownerName').value.trim() || 'You', full_access_permission_mode: $('fullAccessPermissionMode').value }); syncApprovalsButton(); closeDialog($('settingsDialog')); showToast('Settings saved.'); }
      catch (error) { $('settingsError').textContent = errorText(error); $('settingsError').hidden = false; }
      finally { $('settingsForm').dataset.pending = 'false'; save.disabled = false; save.textContent = 'Save settings'; }
    });
    $('connectionsForm').addEventListener('submit', async (event) => { event.preventDefault(); try { data.settings = await post('/api/settings', { approvals_url: $('approvalsApi').value.trim() || null }); if (data.settings?.approvals_url) await refreshApprovals(); else { data.approvals = null; syncApprovalsButton(); } showToast('Connection saved.'); } catch (error) { showToast(errorText(error)); } });
    document.querySelectorAll('[data-settings-tab]').forEach((button) => {
      button.addEventListener('click', () => selectSettingsTab(button.dataset.settingsTab));
      button.addEventListener('keydown', settingsTabKeydown);
    });
    $('settingsNewRoutine').addEventListener('click', () => { closeDialog($('settingsDialog')); $('newRoutineButton').click(); });
    $('settingsHelp').addEventListener('click', () => $('helpButton').click());
    $('settingsTour').addEventListener('click', () => { closeDialog($('settingsDialog')); showCoach(); });
    $('phoneSettings').addEventListener('click', () => window.HubPhone?.open());
    $('routineForm').addEventListener('submit', async (event) => {
      event.preventDefault(); if ($('routineForm').dataset.pending === 'true') return; $('routineError').hidden = true;
      const body = { name: $('routineName').value.trim(), agent_id: $('routineAgent').value, prompt: $('routinePrompt').value.trim(), trigger: $('routineTrigger').value, time: $('routineTime').value, minutes: Number($('routineMinutes').value), weekday: Number($('routineWeekday').value) };
      const create = $('routineForm').querySelector('button[type="submit"]'); $('routineForm').dataset.pending = 'true'; create.disabled = true; create.textContent = 'Creating…';
      try { await post('/api/routines', body); closeDialog($('routineDialog')); $('routineForm').reset(); await refreshRoutines(); showToast('Schedule created.'); }
      catch (error) { $('routineError').textContent = errorText(error); $('routineError').hidden = false; }
      finally { $('routineForm').dataset.pending = 'false'; create.disabled = false; create.textContent = 'Create schedule'; }
    });
    $('routineTrigger').addEventListener('change', () => {
      const value = $('routineTrigger').value;
      $('routineTime').closest('div').hidden = value === 'interval';
      $('routineMinutes').closest('div').hidden = value !== 'interval';
      $('routineWeekday').hidden = value !== 'weekly';
      document.querySelector('label[for="routineWeekday"]').hidden = value !== 'weekly';
    }); $('routineTrigger').dispatchEvent(new Event('change'));
    window.addEventListener('online', updateConnection); window.addEventListener('offline', updateConnection);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && data.authenticated) {
        scheduleEventRefresh({ chat: true });
        refreshWorkers();
        if ($('swarmResultsDialog').open) refreshSwarms();
        if ($('approvalsDialog').open && data.settings?.approvals_url) refreshApprovals();
      }
    });
    if (window.visualViewport) {
      const fitViewport = () => {
        if (matchMedia('(max-width: 700px)').matches) {
          ui.app.style.setProperty('--app-height', `${window.visualViewport.height}px`);
          document.documentElement.style.setProperty('--visual-height', `${window.visualViewport.height}px`);
          document.documentElement.style.setProperty('--visual-top', `${window.visualViewport.offsetTop}px`);
          document.querySelectorAll('dialog[open]').forEach((dialog) => { dialog.style.maxHeight = `${Math.max(120, window.visualViewport.height - 20)}px`; });
        }
        else ui.app.style.removeProperty('--app-height');
        if (document.activeElement === ui.message) requestAnimationFrame(() => { ui.viewport.scrollTop = ui.viewport.scrollHeight; });
      };
      window.visualViewport.addEventListener('resize', fitViewport);
      window.visualViewport.addEventListener('scroll', fitViewport);
      window.addEventListener('resize', fitViewport);
      fitViewport();
    }
    data.pollTimer = setInterval(idleCheck, 30000);
    updateConnection();
  }
  // Sending feel and app-owned actions. Keep this lane isolated from navigation/setup.
  const sendFeel = { optimistic: new Map(), receipts: new Set(), finishing: new Set(), finalMessages: new Map(), sending: new Set(), dispatchTail: null, session: 0, confirmations: new WeakMap(), dialog: null };
  function destructiveAction(action) { return /archive|discard|delete|sign.?out|export/i.test(action); }
  function inlineAction(button, label) {
    const pending = sendFeel.confirmations.get(button);
    const restore = (state) => { if(state.children.length)button.replaceChildren(...state.children);else button.textContent=state.text; };
    if (pending && pending.label === label) { clearTimeout(pending.timer); restore(pending); button.classList.remove('inline-confirm'); sendFeel.confirmations.delete(button); return true; }
    if (pending) { clearTimeout(pending.timer); restore(pending); }
    const children = [...button.childNodes], text = button.textContent;
    button.textContent = label; button.classList.add('inline-confirm');
    const timer = setTimeout(() => { restore({children,text}); button.classList.remove('inline-confirm'); sendFeel.confirmations.delete(button); }, 4000);
    sendFeel.confirmations.set(button, { label, children, text, timer });
    return false;
  }
  function normalizeSearch(text) { return String(text || '').replace(/\s+/g, ' ').trim().toLowerCase(); }
  function appActionDialog({ title, message = '', accept = 'Continue', value, optional = false, fieldLabel, singleLine = false }) {
    if (sendFeel.dialog) return Promise.resolve(null);
    const dialog = el('dialog', 'modal app-action-dialog'), form = el('form');
    dialog.setAttribute('aria-label', title); form.append(el('h2', '', title));
    if (message) form.append(el('p', '', message));
    let input;
    if (value !== undefined) { const caption = fieldLabel || (optional ? 'Reason (optional)' : 'Draft text'); const label = el('label', '', caption); input = el(singleLine ? 'input' : 'textarea'); if (singleLine) { input.type = 'text'; input.maxLength = 80; } input.value = value; input.setAttribute('aria-label', caption); input.required = !optional; label.append(input); form.append(label); }
    const actions = el('div', 'modal-actions'), cancel = el('button', 'secondary', 'Cancel'), proceed = el('button', 'primary', accept);
    cancel.type = 'button'; proceed.type = 'submit'; actions.append(cancel, proceed); form.append(actions); dialog.append(form); document.body.append(dialog); sendFeel.dialog = dialog;
    const focused = document.activeElement;
    return new Promise((resolve) => {
      let finished = false;
      const finish = (result) => { if (finished) return; finished = true; dialog.close(); dialog.remove(); sendFeel.dialog = null; focused?.focus?.({ preventScroll: true }); resolve(result); };
      cancel.addEventListener('click', () => finish(null));
      dialog.addEventListener('cancel', (event) => { event.preventDefault(); finish(null); });
      dialog.addEventListener('close', () => finish(null));
      form.addEventListener('submit', (event) => { event.preventDefault(); if (input && !optional && !input.value.trim()) return; finish(input ? input.value : true); });
      if (singleLine) input.addEventListener('keydown', (event) => { if (event.isComposing) return; if (event.key === 'Enter') { event.preventDefault(); form.requestSubmit(); } else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation?.(); finish(null); } });
      dialog.showModal(); (input || cancel).focus();
    });
  }
  function showCreatedToast(response) {
    const sourceChatId = data.chatId;
    const results = response.results || [response], created = results.filter((item) => !item.duplicate).map((item) => ({ result: item.result || item.card?.result, proposal: item.card?.proposal }));
    const targets = created.flatMap(({ result, proposal }) => {
      if (result?.agent) return [{ kind: 'agent', id: result.agent.id, name: result.agent.name || proposal?.name }];
      const group = result?.chat;
      if (group?.type === 'group' && !group.swarm_id) {
        const children = (proposal?.agents || []).flatMap((item,index) => typeof item === 'object' && group.agents?.[index] ? [{kind:'agent',id:group.agents[index],name:item.name}] : []);
        return [{ kind: 'group', id: group.id, name: group.name || proposal?.name }, ...children];
      }
      return [];
    });
    if (!targets.length) return;
    ui.toast.replaceChildren(el('span', '', `Created ${targets[0].name || 'Pip'}${results.length > 1 ? ` + ${results.length - 1}` : ''} · `));
    const undo = el('button', 'toast-undo', 'Undo'); undo.type = 'button';
    undo.addEventListener('click', async () => {
      if (undo.disabled) return; undo.disabled = true; clearTimeout(data.toastTimer);
      try {
        for (const target of targets) await post('/api/archive', { kind: target.kind, id: target.id });
        await refreshState();
        if (sourceChatId && data.chats.some((item) => item.id === sourceChatId) && data.chatId !== sourceChatId) await openChat(sourceChatId);
        else await refreshChat();
        showToast('Creation undone.');
      }
      catch (error) { showToast(errorText(error)); }
    });
    ui.toast.append(undo); ui.toast.hidden = false; positionToast(); clearTimeout(data.toastTimer); data.toastTimer = setTimeout(() => { ui.toast.hidden = true; }, 6000);
  }
  let conversationScrollPending = false;
  function followingConversation() { return conversationScrollPending || !Number.isFinite(ui.viewport.scrollHeight) || ui.viewport.scrollHeight - ui.viewport.scrollTop - ui.viewport.clientHeight <= 80; }
  function scrollConversation(smooth = false) {
    conversationScrollPending = true;
    const cid = data.chatId;
    requestAnimationFrame(() => { if (!conversationScrollPending || cid !== data.chatId) return; conversationScrollPending = false; const options = { top: ui.viewport.scrollHeight, behavior: smooth && !matchMedia('(prefers-reduced-motion: reduce)').matches ? 'smooth' : 'auto' }; if (ui.viewport.scrollTo) ui.viewport.scrollTo(options); else ui.viewport.scrollTop = options.top; });
  }
  function deliveryNote(message) {
    const note = el('div', 'message-ack'); note.setAttribute('aria-live', 'polite');
    if (message.delivery === 'failed') { note.classList.add('not-delivered'); note.append(el('span', '', 'Not delivered · ')); const retry = el('button', 'delivery-retry', 'Retry'); retry.type = 'button'; retry.addEventListener('click', () => retrySentMessage(message)); note.append(retry); }
    else note.textContent = message.acknowledged ? 'Seen' : message.delivery === 'sending' ? '' : 'Sent';
    return note;
  }
  function updateDelivery(node, message) { const note = node.querySelector('.message-ack'); if (note) note.replaceWith(deliveryNote(message)); node.classList.toggle('send-failed', message.delivery === 'failed'); }
  function compareMessages(a, b) {
    const aId = Number(a.id), bId = Number(b.id), aSaved = Number.isSafeInteger(aId) && aId > 0, bSaved = Number.isSafeInteger(bId) && bId > 0;
    if (aSaved && bSaved) return aId - bId;
    // Pending local bubbles stay after saved history, even with device clock skew.
    if (aSaved !== bSaved) return aSaved ? -1 : 1;
    return seconds(a.created) - seconds(b.created);
  }
  function mergeSentMessages(messages, chatId) {
    const merged = messages.map((message) => {
      const pending = message.request_id && sendFeel.optimistic.get(message.request_id);
      if (pending) { Object.assign(pending, message, { delivery: 'sent' }); sendFeel.optimistic.delete(message.request_id); message = pending; }
      if (message.role === 'user' && (sendFeel.receipts.has(message.request_id) || sendFeel.receipts.has(`message:${message.id}`))) message.acknowledged = true;
      return message;
    });
    for (const pending of sendFeel.optimistic.values()) if (pending.chat_id === chatId && !merged.some((message) => message.request_id === pending.request_id)) merged.push(pending);
    return merged.sort(compareMessages);
  }
  function sentTyping(message, jobIds) {
    const placeholder = `request:${message.request_id}`;
    if (jobIds?.length) {
      const node = [...ui.list.children].find((item) => item.dataset.jobId === placeholder);
      sendFeel.finishing.delete(placeholder); data.deltas.delete(placeholder);
      if (node && ![...ui.list.children].some((item) => item.dataset.jobId === String(jobIds[0]))) node.dataset.jobId = String(jobIds[0]);
      for (const jobId of jobIds) if (!data.closedDeltas.has(String(jobId)) && !data.messages.some((item) => String(item.job_id) === String(jobId))) {
        if (!data.deltas.has(String(jobId))) data.deltas.set(String(jobId), { chat_id: message.chat_id, agent_id: message.agent_id, text: '', request_id: message.request_id });
      }
    } else if (jobIds) { data.deltas.delete(placeholder); }
    else data.deltas.set(placeholder, { chat_id: message.chat_id, agent_id: message.agent_id, text: '', request_id: message.request_id });
  }
  function optimisticMessage(payload, requestId, uploads) {
    const pinned = !parity || parity.atBottom(), top = ui.viewport.scrollTop;
    const message = { ...payload, id: `request:${requestId}`, request_id: requestId, role: 'user', agent_id: composeAgent()?.id, created: Date.now() / 1000, attachments: uploads.map((entry) => ({ ...entry.result, name: entry.file.name })), acknowledged: false, delivery: 'sending', payload, session: sendFeel.session };
    sendFeel.optimistic.set(requestId, message); data.messages.push(message); sentTyping(message);
    reconcileMessages(); const node = [...ui.list.children].find((item) => item.dataset.requestId === requestId); node?.classList.add('optimistic-send'); if (pinned) scrollConversation(true); else { ui.viewport.scrollTop = top; parity?.updateJump(); }
    return message;
  }
  async function dispatchSentMessage(message) {
    const response = await post('/api/message', { ...message.payload, request_id: message.request_id });
    if (message.session !== sendFeel.session) return response;
    if (response.message_id) message.id = response.message_id;
    message.delivery = 'sent'; sentTyping(message, response.job_ids || (response.job_id ? [response.job_id] : []));
    if (data.chatId === message.chat_id) reconcileMessages();
    return response;
  }
  function failSentMessage(message, error) {
    // A history response or run-start event proves delivery even if the POST response was lost.
    if (message.acknowledged || !sendFeel.optimistic.has(message.request_id)) return;
    message.delivery = 'failed'; data.deltas.delete(`request:${message.request_id}`);
    if (data.chatId === message.chat_id) reconcileMessages(); showToast(errorText(error));
  }
  async function retrySentMessage(message) {
    if (message.delivery !== 'failed') return;
    message.delivery = 'sending'; sentTyping(message); if(data.chatId===message.chat_id)reconcileMessages();
    try { await dispatchSentMessage(message); if (data.chatId === message.chat_id) await refreshChat(); }
    catch (error) { failSentMessage(message, error); }
  }
  function markAgentSeen(change) {
    if (change.request_id) sendFeel.receipts.add(change.request_id);
    if (change.message_id) sendFeel.receipts.add(`message:${change.message_id}`);
    while (sendFeel.receipts.size > 1000) sendFeel.receipts.delete(sendFeel.receipts.values().next().value);
    const pending = sendFeel.optimistic.get(change.request_id);
    const message = pending || data.messages.find((item) => item.role === 'user' && (change.request_id && item.request_id === change.request_id || String(item.id) === String(change.message_id)));
    if (message) { message.acknowledged = true; message.delivery = 'sent'; if(change.message_id)message.id=change.message_id; if(change.job_id)sentTyping(message,[change.job_id]); }
    if (String(change.chat_id) === data.chatId) reconcileMessages();
  }
  function finishDelta(jobId, messageId) {
    if (!jobId) return;
    const key = String(jobId); data.closedDeltas.add(key); sendFeel.finishing.add(key);
    if(messageId)sendFeel.finalMessages.set(key,Number(messageId));
    if(data.closedDeltas.size>200)data.closedDeltas.delete(data.closedDeltas.values().next().value);
  }
  try {
    const stored = JSON.parse(localStorage.getItem(readStorageKey) || '{}');
    if (stored && typeof stored === 'object' && !Array.isArray(stored)) data.read = stored;
  } catch { /* storage may be unavailable */ }
  try { const stored = JSON.parse(localStorage.getItem(pinnedStorageKey) || '[]'); if (Array.isArray(stored)) data.pinned = stored; } catch { /* private mode */ }
  try {
    const stored = JSON.parse(localStorage.getItem(approvalsStorageKey) || '{}');
    if (stored && typeof stored === 'object' && !Array.isArray(stored)) Object.entries(stored).slice(-100).forEach(([id, review]) => {
      if (!review || typeof review !== 'object' || !review.draft || !['approve','deny','edit'].includes(review.action)) return;
      const phase = review.phase === 'submitting' || review.phase === 'pending' ? 'pending_timeout' : review.phase;
      data.approvalsReviews[id] = { ...review, id, phase, timer: null, checking: false };
    });
  } catch { /* private mode */ }
  window.HubApp = { api, post, refreshState, openChat, showToast, prepareTeam };
  const parity = window.HubParity?.create({ data, ui, get: $, el, agent, currentChat, post, refreshState, refreshChat, openChat, resizeComposer, showToast, errorText, appActionDialog, renderReply, renderUploads, clearUploads, activeChatJobs, scrollConversation, renderSend, renderNav, openAgentPicker, stopResponse, dialogOpen: () => !!sendFeel.dialog || [...document.querySelectorAll('dialog')].some((dialog) => dialog.open) });
  window.HubPipBrowser?.setup({ api, post, refreshChat, showToast, errorText });
  setup();
  startSession().catch(() => showLogin());
  if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {}));
})();
