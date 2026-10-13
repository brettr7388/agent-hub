/* Consent-first, local computer discovery. All discovered content stays text. */
(() => {
  'use strict';
  const state = { dialog: null, body: null, error: null, busy: false, offered: false, offerReady: false, preview: null, results: null, cards: [] };
  const node = (tag, text, className) => {
    const result = document.createElement(tag);
    if (text != null) result.textContent = text;
    if (className) result.className = className;
    return result;
  };
  const app = () => window.HubApp;
  const humanName = (value) => /^[a-z0-9]+(?:[-_][a-z0-9]+)+$/.test(value || '')
    ? value.replace(/[-_]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()) : value;
  function button(text, action, primary = false) {
    const result = node('button', text, primary ? 'primary' : 'secondary');
    result.type = 'button'; result.addEventListener('click', action); return result;
  }
  function check(text, checked = false) {
    const label = node('label', null, 'check-line');
    const input = node('input'); input.type = 'checkbox'; input.checked = checked;
    label.append(input, node('span', text)); return { label, input };
  }
  function ensureDialog() {
    if (state.dialog) return;
    state.dialog = node('dialog', null, 'modal wide-modal scan-dialog'); state.dialog.id = 'scanDialog';
    const head = node('div', null, 'modal-head'); const title = node('h2', 'Find Pips to set up'); title.id = 'scanHeading';
    state.dialog.setAttribute('aria-labelledby', title.id);
    head.append(title);
    state.body = node('div', null, 'scan-body');
    state.error = node('p', null, 'form-error'); state.error.setAttribute('role', 'alert'); state.error.hidden = true;
    state.dialog.append(head, state.body, state.error); document.body.append(state.dialog);
    state.dialog.addEventListener('cancel', (event) => { event.preventDefault(); if (!state.busy) state.dialog.close(); });
  }
  async function work(action) {
    if (state.busy) return;
    state.busy = true; state.error.hidden = true;
    state.dialog.setAttribute('aria-busy', 'true');
    const controls = [...state.body.querySelectorAll('button,input')];
    const disabled = controls.map((item) => item.disabled); controls.forEach((item) => { item.disabled = true; });
    try { await action(); }
    catch (error) { state.error.textContent = error.message || 'Could not finish. Try again.'; state.error.hidden = false; }
    finally {
      controls.forEach((item, i) => { item.disabled = disabled[i]; });
      state.busy = false; state.dialog.setAttribute('aria-busy', 'false');
    }
  }
  async function skip() {
    await work(async () => { await app().post('/api/onboarding/skip', {}); state.offerReady=false; state.dialog.close(); });
  }
  function consent(info) {
    state.preview = null; state.results = null;
    state.body.replaceChildren(node('p', "Agent Hub looks at what's already on this computer and suggests Pips. Nothing is sent anywhere except to your own Claude or Codex, after you review the summary."));
    state.body.append(node('p', 'Choose exactly what to read. Scan stays on this computer; the next screen shows the complete text before anything is sent.', 'field-help'));
    const sources = [];
    (info.sources || []).forEach((source) => {
      const choice = check(source.label, true); choice.input.value = source.id; sources.push(choice.input);
      const section = node('div', null, 'scan-source'); section.append(choice.label);
      const details = Array.isArray(source.details) ? source.details.join('\n') : String(source.details || '');
      section.append(node('p', details, 'field-help')); state.body.append(section);
    });
    state.body.append(node('p', 'Never read: .env, keys, credentials, SSH, browser data, shell history or mail. Token-looking strings are redacted; the summary is limited to 12 KB.', 'field-help'));
    const actions = node('div', null, 'modal-actions');
    actions.append(button('Skip', skip), button('Scan', () => work(async () => {
      const selected = sources.filter((input) => input.checked).map((input) => input.value);
      state.preview = await app().post('/api/onboarding/preview', { sources: selected });
      scanLabel({scanned:true});
      preview(info);
    }), true));
    state.body.append(actions);
  }
  function preview(info) {
    state.body.replaceChildren(node('h3', 'See what will be sent'));
    state.body.append(node('p', 'This exact summary will be sent once to your signed-in AI app to suggest Pips. Discovery text is treated as data, not instructions.'));
    const summary = node('pre', state.preview.summary || '(No findings. Starter templates are available.)', 'scan-preview');
    summary.tabIndex = 0; state.body.append(summary);
    const actions = node('div', null, 'modal-actions');
    actions.append(button('Back', () => consent(info)), button('Skip', skip), button('Suggest Pips', () => work(async () => {
      state.results = await app().post('/api/onboarding/suggest', { token: state.preview.token });
      results();
    }), true)); state.body.append(actions);
  }
  function results() {
    state.cards = [];
    state.body.replaceChildren(node('p', state.results.starter ? 'No useful findings yet. Choose a starter helper below.' : 'Choose the helpers to create. You can edit their names and emoji.'));
    (state.results.suggestions || []).forEach((suggestion, index) => {
      const card = node('section', null, 'list-card scan-result');
      const selected = check(humanName(suggestion.name), index < 3); card.append(selected.label);
      const fields = node('div', null, 'scan-name-row');
      const name = node('input'); name.type = 'text'; name.value = humanName(suggestion.name); name.maxLength = 60; name.setAttribute('aria-label', 'Pip name');
      const emoji = node('input'); emoji.type = 'text'; emoji.value = suggestion.emoji || '🤖'; emoji.setAttribute('aria-label', 'Pip emoji');
      const picker = button('Choose emoji', () => window.HubEmoji?.open(emoji));
      fields.append(emoji, picker, name); card.append(fields);
      card.append(node('p', `${suggestion.engine === 'codex' ? 'Codex' : 'Claude'} · ${suggestion.model}`, 'field-help'));
      card.append(node('p', suggestion.role || '', 'field-help scan-instructions'));
      card.append(node('p', suggestion.why || '', 'field-help'));
      if (suggestion.project_folder) card.append(node('p', `Working folder: ${suggestion.project_folder}`, 'field-help'));
      const global = check('Use my global rules', false); card.append(global.label);
      card.append(node('small', 'Off keeps this helper focused on its own instructions.', 'field-help'));
      state.cards.push({ suggestion, selected: selected.input, name, emoji, global: global.input });
      state.body.append(card);
    });
    let group;
    if (state.results.group) {
      group = check(`Also create group: ${state.results.group.name}`, false); state.body.append(group.label);
    }
    if (state.results.team) state.body.append(node('p', `Suggested team task: ${state.results.team.name}. You can set its goal after creating helpers.`, 'field-help'));
    const actions = node('div', null, 'modal-actions');
    actions.append(button('Skip', skip), button('Create selected', () => work(async () => {
      const suggestions = state.cards.filter((card) => card.selected.checked).map((card) => ({ ...card.suggestion, original_name: card.suggestion.name, selected: true, name: card.name.value.trim(), emoji: card.emoji.value.trim(), use_global_rules: card.global.checked }));
      if (!suggestions.some((card) => card.selected)) throw new Error('Select at least one helper to create.');
      const result = await app().post('/api/onboarding/create', {
        token: state.preview.token, suggestions, group: group?.input.checked ? { ...state.results.group, selected: true } : null
      });
      await app().refreshState();
      complete(result);
    }), true)); state.body.append(actions);
  }
  function complete(result) {
    const count = result.agents?.length || 0;
    state.body.replaceChildren(node('p', `${count} ${count === 1 ? 'helper is' : 'helpers are'} ready.`));
    const actions = node('div', null, 'modal-actions');
    actions.append(button('Open my helpers', async () => {
      state.dialog.close();
      const first = result.agents?.[0]; const id = first?.chat_id || (first?.id ? `agent:${first.id}` : null);
      if (id) await app().openChat(id);
    }, true));
    if (state.results.team) actions.append(button('Set up suggested team task', async () => {
      const selected = state.cards.filter((card) => card.selected.checked);
      const agents = (result.agents || []).map((agent, index) => ({ ...agent, original_name: selected[index]?.suggestion.name, role: selected[index]?.suggestion.role }));
      state.dialog.close(); await app().prepareTeam(state.results.team, agents);
      app().showToast(`Set a goal for ${state.results.team.name} before launching.`);
    }));
    state.body.append(actions);
  }
  function scanLabel(info) {
    const button = document.getElementById('scanComputer');
    if (button) button.textContent = info.scanned || info.status === 'done' ? 'Scan this computer again' : 'Scan this computer';
  }
  async function refreshScanLabel() {
    try { scanLabel(await app().api('/api/onboarding')); } catch { /* keep the initial label when unavailable */ }
  }
  async function open(info) {
    ensureDialog();
    if (state.busy) return;
    try {
      info = info || await app().api('/api/onboarding');
      scanLabel(info);
      document.querySelectorAll('dialog[open]').forEach((dialog) => { if (dialog !== state.dialog) dialog.close(); });
      state.error.hidden = true; consent(info);
      if (!state.dialog.open) state.dialog.showModal();
    } catch (error) { app().showToast(error.message); }
  }
  async function offer(firstRun) {
    if (!firstRun || state.offered) return false;
    const info = await app().api('/api/onboarding');
    if (info.status === 'done' || info.status === 'skipped') return false;
    state.offered = true; state.offerReady = true; return true;
  }
  function offerCard() {
    if (!state.offerReady) return null;
    const card=node('section',null,'card scan-offer');card.append(node('strong','Find Pips for your work'),node('p','You can review a local summary of projects and Pip names before choosing whether to send it to your AI provider.'));
    const actions=node('div',null,'card-actions');actions.append(button('Scan this computer',()=>open(),true),button('Skip',async()=>{try{await app().post('/api/onboarding/skip',{});state.offerReady=false;card.remove();}catch(error){app().showToast(error.message);}}));card.append(actions);return card;
  }
  function mountOffer() {
    if (!state.offerReady || document.querySelector('.scan-offer')) return;
    const starters = document.querySelector('.guide-starters');
    if (starters) starters.after(offerCard());
  }
  window.HubOnboarding = { open, offer, offerCard, mountOffer, refreshScanLabel };
  document.getElementById('scanComputer')?.addEventListener('click', () => open());
})();
