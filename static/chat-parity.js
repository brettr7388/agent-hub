/* Local chat controls. No libraries, remote assets, or native dialogs. */
(() => {
  'use strict';
  function create(ctx) {
    const { data, ui, get: findElement, el, agent, currentChat, post, refreshState, refreshChat, openChat, resizeComposer, showToast, appActionDialog, renderReply, renderUploads, clearUploads, activeChatJobs, scrollConversation } = ctx;
    // Version controls move into messages, so keep them even while that subtree is detached.
    const versionElements = new Map(['chatVersionBar','chatVersions','chatVersionOptions','chatVersionSummary','previousChatVersion','nextChatVersion'].map((id) => [id, findElement(id)]));
    const get = (id) => versionElements.get(id) || findElement(id);
    let editing = null, editRequest = null, recognition = null, listening = false, voiceChat = null, voiceBase = '', newChatPending = false, versionChanging = false;
    const expanded = new Set(), rowOrder = new Map();
    let addedRows = new Set();
    let syncVersionControls = () => {};
    let versionResult = null;
    const atBottom = () => !Number.isFinite(ui.viewport.scrollHeight) || ui.viewport.scrollHeight - ui.viewport.scrollTop - ui.viewport.clientHeight <= 80;
    function updateJump() { get('jumpLatest').hidden = !data.chatId || ui.viewport.hidden || ui.viewport.classList.contains('conversation-opening') || atBottom(); }
    function preserveScroll(change) {
      const pinned = atBottom(), top = ui.viewport.scrollTop;
      change();
      if (pinned) scrollConversation(); else ui.viewport.scrollTop = top;
      updateJump();
    }
    function cancelEdit(restore = true) {
      if (editing && restore) { ui.message.value = editing.draft; resizeComposer(); }
      editing = null; editRequest = null; get('editMessageBar').hidden = true;
      ui.send.setAttribute('aria-label', 'Send message'); ui.send.title = 'Send message';
    }
    function startEdit(message) {
      if (!data.authenticated || message?.role !== 'user' || !Number.isSafeInteger(Number(message.id))) return;
      if (activeChatJobs().length || data.pending) { showToast('Stop the current reply before editing a message.'); return; }
      stopVoice();
      const draft = editing?.draft ?? ui.message.value;
      editing = { id: message.id, chatId: data.chatId, draft };
      editRequest = null; clearUploads(); data.replyTo = []; renderReply(); renderUploads();
      ui.message.value = message.text || ''; get('editMessageBar').hidden = false;
      ui.send.setAttribute('aria-label', 'Save edit and resend'); ui.send.title = 'Save edit and resend'; resizeComposer(); ui.message.focus();
    }
    async function submitEdit() {
      if (!editing || data.pending || activeChatJobs().length) return;
      const text = ui.message.value.trim();
      if (!text) { showToast('Enter a message before resending.'); return; }
      const payload = { chat_id: editing.chatId, message_id: editing.id, text };
      const signature = JSON.stringify(payload);
      if (editRequest?.signature !== signature) editRequest = { signature, id: crypto.randomUUID() };
      const selected = editing;
      data.pending = true; ui.send.disabled = true;
      try {
        await post('/api/messages/edit', { ...payload, request_id: editRequest.id });
        if (data.chatId !== selected.chatId || editing !== selected) return;
        cancelEdit(false); ui.message.value = ''; resizeComposer();
        data.messages = []; data.deltas.clear(); data.closedDeltas.clear(); ui.list.replaceChildren();
        await refreshState(); await refreshChat(true);
      } catch (error) { showToast(ctx.errorText(error)); }
      finally { data.pending = false; ctx.renderSend(); }
    }
    async function newChat(a = null) {
      const chosen = a || agent(currentChat()?.agents?.[0]);
      if (!chosen) { ctx.openAgentPicker(true); return; }
      if (newChatPending) return;
      newChatPending = true; stopVoice();
      try { const result = await post('/api/chats/new', { agent_id: chosen.id }); await refreshState(); await openChat(result.chat.id); ui.message.focus(); }
      catch (error) { showToast(ctx.errorText(error)); }
      finally { newChatPending = false; }
    }
    async function chatMenu(item) {
      const panel = get('conversationActionsBody'); panel.replaceChildren();
      const rename = el('button', 'secondary', 'Rename chat'); rename.type = 'button';
      rename.addEventListener('click', async () => {
        get('conversationActionsDialog').close();
        const name = await appActionDialog({ title: 'Rename chat', fieldLabel: 'Chat name', value: item.name || '', accept: 'Save name', singleLine: true });
        if (name == null) return;
        try { await post('/api/chats/rename', { chat_id: item.id, name }); await refreshState(); await refreshChat(); }
        catch (error) { showToast(ctx.errorText(error)); }
      });
      const remove = el('button', 'secondary', 'Delete chat'); remove.type = 'button';
      remove.addEventListener('click', async () => {
        get('conversationActionsDialog').close();
        if (!await appActionDialog({ title: 'Delete chat?', message: 'This removes this conversation and its earlier versions.', accept: 'Delete chat' })) return;
        try {
          await post('/api/chats/delete', { chat_id: item.id });
          if (data.chatId === item.id) { data.chatId = null; data.messages = []; data.deltas.clear(); ui.list.replaceChildren(); }
          await refreshState(); await openChat(`agent:${item.agents[0]}`);
        } catch (error) { showToast(ctx.errorText(error)); }
      });
      panel.append(rename, remove); get('conversationActionsDialog').showModal();
    }
    function pipRow(item, base) {
      const aid = item.agents?.[0], a = agent(aid);
      if (!a) return base;
      const conversations = data.chats.filter((c) => c.type === 'direct' && c.agents?.[0] === aid);
      const normalize = (text) => String(text || '').replace(/\s+/g, ' ').trim().toLowerCase();
      const search = normalize(data.navFilter);
      const open = expanded.has(aid) || !!search && conversations.length > 1;
      const toggle = el('button', 'conversation-toggle', open ? '▾' : '▸'); toggle.type = 'button';
      toggle.setAttribute('aria-label', `Recent conversations with ${a.name}`); toggle.setAttribute('aria-expanded', String(open));
      toggle.addEventListener('click', () => { expanded.has(aid) ? expanded.delete(aid) : expanded.add(aid); ctx.renderNav(); });
      base.classList.add('pip-conversations'); base.append(toggle);
      if (open) {
        const list = el('div', 'pip-conversation-list');
        const recent = conversations.sort((x,y) => Number(y.updated || 0)-Number(x.updated || 0));
        const visible = recent.filter((c) => !search || normalize(c.name).includes(search)).slice(0, 8);
        const selected = recent.find((c) => c.id === data.chatId);
        if (!search && selected && !visible.includes(selected)) visible.push(selected);
        visible.forEach((c) => {
          const row = el('div', 'pip-conversation-row'); row.dataset.chatId = c.id;
          const button = el('button', `conversation-link${data.chatId === c.id ? ' active' : ''}`, c.name || 'New chat'); button.type = 'button';
          button.title = c.name || 'New chat'; button.addEventListener('click', () => openChat(c.id));
          const menu = el('button', 'conversation-more', '⋯'); menu.type = 'button'; menu.setAttribute('aria-label', `Options for ${c.name || 'chat'}`); menu.addEventListener('click', () => chatMenu(c));
          row.append(button, menu); list.append(row);
        });
        base.append(list);
      }
      return base;
    }
    // Keep mounted Pip order stable as messages arrive and new rows are appended.
    function stableOrder(items, key) {
      key += ':' + data.pinned.join(',');
      const known = rowOrder.get(key) || [];
      const current = new Map(items.map((item) => [item.id,item]));
      addedRows = new Set(known.length ? items.filter((item) => !known.includes(item.id)).map((item) => item.id) : []);
      const ids = known.filter((id) => current.has(id));
      for (const item of items) if (!ids.includes(item.id)) ids.push(item.id);
      rowOrder.set(key, ids); return ids.map((id) => current.get(id));
    }
    function renderVersions(result) {
      versionResult = result;
      const versions = Array.isArray(result.versions) ? result.versions : [];
      const panel = get('chatVersions'), options = get('chatVersionOptions'), bar = get('chatVersionBar');
      const hasVersions = versions.length >= 2; panel.hidden = !hasVersions; bar.hidden = !hasVersions;
      const index = Math.max(0, versions.findIndex((v) => v.active || String(v.id) === String(result.active_version)));
      const previous = get('previousChatVersion'), next = get('nextChatVersion');
      previous.hidden = next.hidden = !hasVersions;
      const syncControls = () => {
        previous.disabled = versionChanging || index <= 0;
        next.disabled = versionChanging || index >= versions.length - 1;
        for (const button of options.children) button.disabled = versionChanging || button.dataset?.versionId === String(versions[index]?.id);
      };
      syncVersionControls = syncControls;
      get('chatVersionSummary').textContent = `${index + 1}/${versions.length}`;
      get('chatVersionSummary').setAttribute('aria-label', `Version ${index + 1} of ${versions.length}. Earlier versions`);
      const selectVersion = async (version) => {
          if (versionChanging) return;
          if (activeChatJobs().length || data.pending) { showToast('Stop the current reply before switching versions.'); return; }
          const cid = data.chatId;
          versionChanging = true; syncControls();
          try {
            await post('/api/chats/version', { chat_id: cid, version_id: version.id });
            if (cid !== data.chatId) return;
            stopVoice(); cancelEdit(); data.messages = []; data.deltas.clear(); data.closedDeltas.clear(); ui.list.replaceChildren();
            await refreshState(); await refreshChat(true); panel.open = false;
          } catch (error) { showToast(ctx.errorText(error)); }
          finally { versionChanging = false; syncVersionControls(); }
      };
      previous.onclick = () => index > 0 ? selectVersion(versions[index - 1]) : null;
      next.onclick = () => index < versions.length - 1 ? selectVersion(versions[index + 1]) : null;
      options.replaceChildren(...versions.map((version, i) => {
        const button = el('button', 'secondary', `${i + 1}. ${version.label || 'Earlier conversation'}`); button.type = 'button'; button.dataset.versionId = String(version.id);
        button.addEventListener('click', () => selectVersion(version)); return button;
      }));
      syncControls();
      mountVersions();
    }
    function mountVersions() {
      const bar = get('chatVersionBar');
      if (bar.hidden || !versionResult) return;
      const selected = versionResult.versions?.find((v) => v.active || String(v.id) === String(versionResult.active_version));
      const anchor = data.messages.find((m) => String(m.id) === String(selected?.message_id)) || data.messages.filter((m) => m.role === 'user').at(-1);
      const node = [...ui.list.children].find((item) => item.dataset.messageId === String(anchor?.id));
      const body = node?.querySelector('.message-body');
      if (!body) { bar.hidden = true; return; }
      bar.classList.add('message-version-control');
      body.after(bar);
    }
    function measureRows(container) {
      return new Map([...container.querySelectorAll('.nav-wrap')].map((node) => [node.dataset.chatId, node.getBoundingClientRect().top]));
    }
    function animateReorder(container, positions) {
      if (!positions?.size || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      for (const node of container.querySelectorAll('.nav-wrap')) {
        const old = positions.get(node.dataset.chatId), offset = old - node.getBoundingClientRect().top;
        if (Number.isFinite(offset) && Math.abs(offset) > 1 && typeof node.animate === 'function') node.animate([{ transform: `translateY(${offset}px)` }, { transform: 'translateY(0)' }], { duration: 180, easing: 'ease-out' });
      }
    }
    function stopVoice() {
      if (!recognition || !listening) return;
      listening = false; try { recognition.stop(); } catch { /* recognition may already have ended */ } get('voiceButton').setAttribute('aria-pressed', 'false');
      get('voiceButton').title = 'Voice typing'; get('voiceStatus').hidden = true;
    }
    function setupVoice() {
      const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
      get('voiceButton').hidden = !Speech;
      if (!Speech) return;
      recognition = new Speech(); recognition.continuous = true; recognition.interimResults = true;
      recognition.lang = document.documentElement.lang || 'en-US';
      recognition.onresult = (event) => {
        if (!listening || voiceChat !== data.chatId || !data.authenticated) return;
        let final = '', interim = '';
        for (let i = 0; i < event.results.length; i++) {
          const result = event.results[i], text = String(result[0]?.transcript || '');
          if (result.isFinal) final += text; else interim += text;
        }
        ui.message.value = voiceBase + [final, interim].filter(Boolean).join(' '); resizeComposer();
        get('voiceStatus').textContent = interim || 'Listening…'; get('voiceStatus').hidden = false;
      };
      recognition.onend = () => { listening = false; get('voiceButton').setAttribute('aria-pressed', 'false'); get('voiceButton').title = 'Voice typing'; get('voiceStatus').hidden = true; };
      recognition.onerror = (event) => { stopVoice(); showToast(event.error === 'not-allowed' ? 'Microphone access was denied. Allow it in browser settings to use voice typing.' : 'Voice typing stopped. Try again.'); };
      get('voiceButton').addEventListener('click', () => {
        if (listening) { stopVoice(); return; }
        if (!data.authenticated || ui.composer.hidden) return;
        voiceChat = data.chatId; voiceBase = ui.message.value; if (voiceBase && !/\s$/.test(voiceBase)) voiceBase += ' ';
        listening = true;
        try { recognition.start(); get('voiceButton').setAttribute('aria-pressed', 'true'); get('voiceButton').title = 'Stop voice typing'; }
        catch { listening = false; showToast('Voice typing could not start. Check microphone access.'); }
      });
      // User typing becomes the prefix for subsequent results, avoiding lost edits.
      ui.message.addEventListener('input', () => { if (listening) { stopVoice(); } });
    }
    function shortcut(event) {
      if (!data.authenticated || event.isComposing) return;
      const modifier = event.metaKey || event.ctrlKey, key = String(event.key).toLowerCase();
      if (modifier && event.shiftKey && key === 'o') { event.preventDefault(); newChat(); return; }
      if (modifier && key === '/') { event.preventDefault(); get('shortcutsDialog').showModal(); return; }
      if (event.key === 'Escape') {
        if (ctx.dialogOpen?.()) return;
        if (activeChatJobs().length) { event.preventDefault(); ctx.stopResponse(); }
        else if (editing) { event.preventDefault(); cancelEdit(); }
      }
      if (event.key === 'ArrowUp' && event.target === ui.message && !ui.message.value && !modifier && !event.shiftKey) {
        const last = [...data.messages].reverse().find((message) => message.role === 'user' && Number.isSafeInteger(Number(message.id)));
        if (last) { event.preventDefault(); startEdit(last); }
      }
    }
    function reset() { stopVoice(); voiceBase = ''; cancelEdit(false); versionResult = null; syncVersionControls = () => {}; const bar = get('chatVersionBar'); bar.hidden = true; get('conversation').append(bar); get('previousChatVersion').hidden = true; get('nextChatVersion').hidden = true; get('chatVersions').hidden = true; get('chatVersions').open = false; get('jumpLatest').hidden = true; }
    function setup() {
      get('cancelMessageEdit').addEventListener('click', () => cancelEdit());
      get('newPipChat').addEventListener('click', () => newChat());
      get('jumpLatest').addEventListener('click', () => { scrollConversation(); get('jumpLatest').hidden = true; });
      ui.viewport.addEventListener('scroll', updateJump);
      document.addEventListener('keydown', shortcut);
      setupVoice();
    }
    return { setup, reset, startEdit, submitEdit, get editing() { return editing; }, newChat, pipRow, stableOrder, measureRows, animateReorder, animateRow: (node,id) => { if (addedRows.has(id)) node.classList.add('nav-added'); }, renderVersions, mountVersions, updateJump, atBottom, preserveScroll, shortcut, stopVoice };
  }
  window.HubParity = { create };
})();
