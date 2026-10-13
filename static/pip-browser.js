/* Pip browser and host credential-store controls. */
(() => {
  'use strict';
  let hooks;
  let status = null;
  let logins = [];
  let loginsLoaded = false;
  let loginsRequest = null;
  let loginsRequestId = 0;
  const $ = (id) => document.getElementById(id);
  const node = (tag, className, value) => {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (value !== undefined) item.textContent = String(value);
    return item;
  };
  const safeError = () => hooks?.showToast('That browser action could not be completed. Check its status before trying again.');
  const siteName = (site) => String(site || 'this site');
  function renderSettings() {
    if (!$('pipBrowserStatus')) return;
    $('pipBrowserStatus').textContent = !status?.available ? 'Pip browser is unavailable on this computer.' : status.running ? 'Pip browser is running on this computer.' : 'Pip browser is ready on this computer.';
    $('pipBrowserOpen').disabled = !status?.available;
    $('pipBrowserReset').disabled = !status?.available;
    const section = $('savedLoginsSection');
    section.hidden = !status?.saved_logins_available;
    if (section.hidden) return;
    const list = $('savedLoginsList');
    list.replaceChildren();
    if (!logins.length) list.append(node('p', 'field-help', 'No saved logins yet.'));
    for (const login of logins) {
      const row = node('div', 'saved-login-row');
      const local = localAddress(login.site);
      row.append(node('span', '', `${login.site} · ${login.username}${login.needs_port || (local && !local.validPort) ? ' · Add the port to use this saved login.' : ''}`));
      const remove = node('button', 'secondary', 'Delete');
      remove.type = 'button';
      remove.setAttribute('aria-label', `Delete saved login for ${login.username} on ${login.site}`);
      remove.addEventListener('click', async () => {
        if (remove.dataset.confirm !== 'true') { remove.dataset.confirm = 'true'; remove.textContent = 'Confirm delete'; return; }
        remove.disabled = true;
        try { await hooks.post('/api/saved-logins/delete', { id: login.id }); await refresh(); }
        catch { safeError(); remove.disabled = false; }
      });
      row.append(remove);
      list.append(row);
    }
  }
  async function refresh() {
    if (!hooks) return;
    try {
      status = await hooks.api('/api/pip-browser');
      if (status?.saved_logins_available) {
        await loadLogins(true);
      } else {
        loginsRequestId++;
        loginsRequest = null;
        logins = [];
        loginsLoaded = true;
      }
      renderSettings();
    } catch {
      loginsRequestId++;
      loginsRequest = null;
      status = { available: false, saved_logins_available: false };
      logins = [];
      loginsLoaded = true;
      renderSettings();
    }
  }
  function clearSecret() { if ($('savedLoginPassword')) $('savedLoginPassword').value = ''; }
  function localAddress(value) {
    let text = String(value || '').trim().toLowerCase();
    if (/^[a-z][a-z\d+.-]*:\/\//i.test(text)) {
      text = text.replace(/^[a-z][a-z\d+.-]*:\/\//i, '').split(/[/?#]/, 1)[0].replace(/^.*@/, '');
    }
    const match = text.match(/^(localhost|127\.0\.0\.1|\[::1\]|(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+localhost)(?::([^:/?#]*))?$/);
    if (!match) return null;
    const hasPort = match[2] !== undefined;
    const port = hasPort && /^\d+$/.test(match[2]) ? Number(match[2]) : null;
    return { host: match[1], port, validPort: hasPort && port !== null && port >= 1 && port <= 65535 };
  }
  function portHelp() {
    let help = $('savedLoginPortHelp');
    if (help) return help;
    help = node('p', 'field-help', 'Add the port, e.g. localhost:4841.');
    help.id = 'savedLoginPortHelp';
    help.setAttribute('role', 'status');
    $('savedLoginSite')?.insertAdjacentElement?.('afterend', help);
    if (!help.parentNode) $('savedLoginForm')?.append(help);
    return help;
  }
  function loadLogins(force = false) {
    if (loginsLoaded && !force) return Promise.resolve(logins);
    if (loginsRequest && !force) return loginsRequest;
    if (force) loginsLoaded = false;
    const requestId = ++loginsRequestId;
    const request = hooks.api('/api/saved-logins').then((result) => {
      const loaded = result.available && Array.isArray(result.logins) ? result.logins : [];
      if (requestId === loginsRequestId) {
        logins = loaded;
        loginsLoaded = true;
        if (status) status.saved_logins_available = !!result.available;
        renderSettings();
      }
      return loaded;
    }).finally(() => { if (loginsRequest === request) loginsRequest = null; });
    loginsRequest = request;
    return loginsRequest;
  }
  function setup(nextHooks) {
    hooks = nextHooks;
    const dialog = $('settingsDialog');
    if (!dialog || !$('pipBrowserOpen')) return;
    dialog.addEventListener('close', clearSecret);
    $('pipBrowserOpen').addEventListener('click', async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        const result = await hooks.post('/api/pip-browser/open', {});
        status = result;
        renderSettings();
        hooks.showToast(`Pip browser window opened on ${result.opened_on || 'the host computer'}.`);
      } catch { safeError(); }
      finally { button.disabled = !status?.available; }
    });
    $('pipBrowserReset').addEventListener('click', async (event) => {
      const button = event.currentTarget;
      if (button.dataset.confirm !== 'true') {
        button.dataset.confirm = 'true';
        button.textContent = 'Confirm sign out everywhere in Pip browser';
        return;
      }
      button.disabled = true;
      try { await hooks.post('/api/pip-browser/reset', { confirm: true }); hooks.showToast('Pip browser profile reset.'); await refresh(); }
      catch { safeError(); }
      finally { button.dataset.confirm = ''; button.textContent = 'Sign out everywhere'; button.disabled = !status?.available; }
    });
    $('savedLoginForm').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      if (form.dataset.pending === 'true') return;
      const submit = form.querySelector('button[type="submit"]');
      const passwordInput = $('savedLoginPassword');
      const payload = {
        site: $('savedLoginSite').value.trim(),
        username: $('savedLoginUsername').value.trim(),
        password: passwordInput.value,
        subdomains: $('savedLoginSubdomains').value.split(',').map((part) => part.trim()).filter(Boolean)
      };
      passwordInput.value = '';
      const local = localAddress(payload.site);
      if (local && !local.validPort) {
        portHelp().hidden = false;
        payload.password = '';
        form.dataset.pending = 'false';
        submit.disabled = false;
        return;
      }
      const help = $('savedLoginPortHelp');
      if (help) help.hidden = true;
      form.dataset.pending = 'true';
      submit.disabled = true;
      try { await hooks.post('/api/saved-logins/add', payload); form.reset(); hooks.showToast('Saved login added.'); await refresh(); }
      catch { safeError(); }
      finally { payload.password = ''; form.dataset.pending = 'false'; submit.disabled = false; clearSecret(); }
    });
  }
  function matchingLogins(site) {
    const target = String(site || '').toLowerCase();
    const targetLocal = localAddress(target);
    return logins.filter((login) => {
      if (login.needs_port) return false;
      const saved = String(login.site || '').toLowerCase();
      const savedLocal = localAddress(saved);
      if (targetLocal || savedLocal) return !!(targetLocal?.validPort && savedLocal?.validPort && targetLocal.host === savedLocal.host && targetLocal.port === savedLocal.port);
      if (saved === target || (login.subdomains || []).some((name) => String(name).toLowerCase() === target)) return true;
      return false;
    });
  }
  async function decision(cardData, message, action, button, loginId) {
    const row = button.closest('.pip-browser-card');
    if (row.dataset.pending === 'true') return;
    row.dataset.pending = 'true';
    for (const item of row.querySelectorAll('button')) item.disabled = true;
    try {
      const body = { message_id: message.id, index: cardData.index, action };
      if (loginId) body.login_id = loginId;
      await hooks.post('/api/browser-card', body);
      await hooks.refreshChat();
      // Reopening an already-open card may keep the same rendered signature.
      row.dataset.pending = 'false';
      for (const item of row.querySelectorAll('button')) item.disabled = false;
    } catch { safeError(); try { await hooks.refreshChat(); } catch { /* status can be checked on reload */ } }
  }
  function isCurrentCard(element, cardData) {
    return element.dataset.browserSignature === JSON.stringify(cardData) && element.isConnected !== false;
  }
  function card(cardData, message) {
    const element = node('section', 'card pip-browser-card');
    element.dataset.cardIndex = String(cardData.index);
    element.dataset.browserSignature = JSON.stringify(cardData);
    const site = siteName(cardData.site);
    const signin = cardData.kind === 'signin_request';
    const title = signin ? `Sign in needed: ${site}${cardData.reason ? ` — ${cardData.reason}` : ''}` : `Use your saved login for ${site}?`;
    const heading = node('strong', '', title);
    heading.setAttribute('title', title);
    element.append(heading);
    const state = String(cardData.status || 'pending');
    if (state !== 'pending') {
      const labels = { opening: 'Opening Pip browser…', opened: 'Pip browser window opened on the host computer. Sign in there, then tap Done.', filling: 'Filling saved login…', filled: 'Filled — now click Sign in in the current tab. Do not reload the page.', refused: 'Login fill was refused.', declined: 'Declined.', done: 'Sign-in complete.', interrupted: 'Action interrupted. Check the browser before trying again.' };
      // Result is a fixed Hub-generated status, rendered as text. Keep the exact refusal visible.
      const refusal = state === 'refused' && typeof cardData.result === 'string' && cardData.result.length <= 400 && cardData.result.includes(' — refused');
      element.append(node('p', 'decision', refusal ? cardData.result : labels[state] || state));
    }
    if (cardData.notification === 'pending') {
      const retry = node('button', 'secondary', 'Send status to Pip'); retry.type = 'button';
      retry.addEventListener('click', () => decision(cardData, message, signin ? 'done' : 'approve', retry));
      element.append(retry);
    }
    if (signin && (state === 'pending' || state === 'opened')) {
      const row = node('div', 'card-actions');
      {
        const open = node('button', 'primary', 'Open Pip browser'); open.type = 'button';
        open.addEventListener('click', () => decision(cardData, message, 'open', open)); row.append(open);
      }
      const done = node('button', 'secondary', 'Done'); done.type = 'button';
      done.addEventListener('click', () => decision(cardData, message, 'done', done)); row.append(done);
      element.append(row);
    }
    if (!signin && state === 'pending') {
      const row = node('div', 'card-actions');
      const approve = node('button', 'primary', 'Loading saved accounts…'); approve.type = 'button'; approve.disabled = true;
      const dont = node('button', 'secondary', "Don't"); dont.type = 'button'; dont.disabled = true;
      let shownLogin = null;
      approve.addEventListener('click', async () => {
        try {
          await loadLogins();
          if (!isCurrentCard(element, cardData) || state !== 'pending') return;
          if (shownLogin) { await decision(cardData, message, 'approve', approve, shownLogin.id); return; }
          const choices = matchingLogins(site);
          if (!choices.length) { hooks.showToast('No saved login matches this site. Add one in Settings → Connections.'); return; }
          let chooser = element.querySelector('.login-chooser');
          if (chooser) return;
          chooser = node('div', 'login-chooser');
          {
            const label = node('label', '', 'Choose an account');
            const select = node('select');
            select.setAttribute('aria-label', `Saved account for ${site}`);
            for (const login of choices) { const option = node('option', '', login.username); option.value = login.id; select.append(option); }
            select.value = choices[0].id;
            label.append(select); chooser.append(label);
            const use = node('button', 'primary', 'Approve fill'); use.type = 'button';
            use.addEventListener('click', () => decision(cardData, message, 'approve', use, select.value));
            chooser.append(use);
          }
          element.append(chooser);
        } catch { safeError(); }
      });
      dont.addEventListener('click', () => decision(cardData, message, 'dont', dont));
      row.append(approve, dont); element.append(row);
      loadLogins().then(() => {
        if (!isCurrentCard(element, cardData) || state !== 'pending') return;
        const choices = matchingLogins(site);
        dont.disabled = false;
        approve.disabled = false;
        if (choices.length === 1) {
          shownLogin = { id: choices[0].id, username: choices[0].username };
          const summary = node('p', 'decision', `Use ${choices[0].username} on ${site}?`);
          row.append(summary);
          approve.textContent = 'Approve fill';
        } else approve.textContent = choices.length > 1 ? 'Choose account' : 'No matching account';
        approve.disabled = choices.length === 0;
      }).catch(() => {
        if (isCurrentCard(element, cardData) && state === 'pending') { approve.textContent = 'Saved accounts unavailable'; approve.disabled = true; dont.disabled = false; }
      });
    }
    return element;
  }
  function updateCard(element, cardData, message) {
    if (element.dataset.browserSignature !== JSON.stringify(cardData)) {
      element.dataset.browserSignature = '';
      for (const button of element.querySelectorAll('button')) button.disabled = true;
      element.replaceWith(card(cardData, message));
    }
  }
  const exported = { setup, refresh, card, updateCard };
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
  if (typeof window !== 'undefined') window.HubPipBrowser = exported;
})();
