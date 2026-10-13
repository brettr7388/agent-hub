(() => {
  'use strict';
  let dialog, link, qr, status, copy, check;
  let phoneUrl = null;
  const node = (tag, className, text) => {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text != null) item.textContent = text;
    return item;
  };
  function addStep(list, title, description) {
    const item = node('li');
    item.append(node('strong', '', title), node('p', '', description));
    list.append(item);
    return item;
  }
  function createDialog() {
    dialog = node('dialog', 'modal wide-modal phone-dialog');
    dialog.id = 'phoneDialog';
    const head = node('div', 'modal-head');
    head.append(node('h2', '', 'Use it on your phone'));
    const close = node('button', 'icon-button', '×');
    close.type = 'button'; close.setAttribute('aria-label', 'Close phone setup');
    close.addEventListener('click', () => dialog.close());
    head.append(close);
    dialog.append(head, node('p', '', 'Connect your own devices privately, then save Agent Hub to your Home Screen. Your Hub access token is still required.'));

    const install = node('section', 'phone-install');
    install.append(node('h3', '', 'Add it to your Home Screen'));
    const iphone = node('p');
    iphone.append(node('strong', '', 'iPhone (Safari): '), document.createTextNode('After opening the phone link, tap Share (the square with an up arrow), scroll to Add to Home Screen, then tap Add.'));
    const android = node('p');
    android.append(node('strong', '', 'Android (Chrome): '), document.createTextNode('After opening the phone link, tap the three-dot menu, choose Add to Home screen or Install app, then confirm.'));
    install.append(iphone, android);
    dialog.append(install);

    const steps = node('ol', 'phone-steps');
    const devices = addStep(steps, 'Connect both devices to Tailscale.', 'Sign in to the same account on this computer and your phone. With only your devices in that Tailscale network, only those devices can reach the private link. Check that Tailscale says Connected on both.');
    const downloads = node('p', 'phone-downloads');
    [['Mac (Hub host)','https://tailscale.com/download/mac'],['Linux (Hub host)','https://tailscale.com/download/linux'],['iPhone (phone app)','https://tailscale.com/download/ios'],['Android (phone app)','https://tailscale.com/download/android']].forEach(([name, url], index) => {
      if (index) downloads.append(document.createTextNode(' · '));
      const anchor = node('a', '', name); anchor.href = url; anchor.target = '_blank'; anchor.rel = 'noopener noreferrer'; downloads.append(anchor);
    });
    devices.append(downloads);
    const prepare = addStep(steps, 'Prepare the private phone address.', 'On the supported macOS or Linux Hub computer, open Terminal in the Agent Hub folder and run the command below. It prints a tailscale serve command. Run that exact command in Terminal, then restart Agent Hub. The HTTPS link appears in the terminal and in Settings → General → Phone setup after restart.');
    const command = node('div', 'phone-command'); command.append(node('code', '', 'python3 hub.py --tailscale'));
    const commandCopy = node('button', 'secondary', 'Copy command'); commandCopy.type = 'button';
    commandCopy.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText('python3 hub.py --tailscale'); commandCopy.textContent = 'Copied'; }
      catch { commandCopy.textContent = 'Select the command to copy'; }
    });
    command.append(commandCopy); prepare.append(command);
    addStep(steps, 'Open Hub on your phone.', 'Keep Agent Hub and Tailscale running on this computer. On your phone, open the HTTPS address below or scan its QR code. Sign in with the same Agent Hub access token you use on this computer.');
    dialog.append(steps);

    const card = node('section', 'phone-setup-card');
    card.append(node('h3', '', 'Your private phone link'));
    link = node('a', 'phone-link');
    link.target = '_blank'; link.rel = 'noopener noreferrer';
    card.append(link);
    qr = node('div', 'phone-qr');
    card.append(qr);
    const actions = node('div', 'phone-actions row-actions');
    copy = node('button', 'secondary', 'Copy link'); copy.type = 'button';
    copy.addEventListener('click', async () => {
      if (!phoneUrl) return;
      try { await navigator.clipboard.writeText(phoneUrl); status.textContent = 'Phone link copied.'; }
      catch { status.textContent = 'Copy failed. Select the link above to copy it.'; }
    });
    check = node('button', 'secondary', 'Check connection'); check.type = 'button';
    check.addEventListener('click', checkConnection);
    actions.append(copy, check);
    card.append(actions);
    status = node('p', 'phone-check-status');
    status.setAttribute('role', 'status'); card.append(status);
    dialog.append(card);

    document.body.append(dialog);
  }
  function validPhoneUrl(value) {
    if (typeof value !== 'string') return null;
    try {
      const parsed = new URL(value);
      if (parsed.protocol !== 'https:' || parsed.username || parsed.password || parsed.search || parsed.hash || parsed.pathname !== '/') return null;
      return parsed.origin + '/';
    } catch { return null; }
  }
  function renderUrl(value) {
    phoneUrl = validPhoneUrl(value);
    qr.replaceChildren();
    link.removeAttribute('href');
    link.textContent = phoneUrl || 'No private HTTPS address is configured yet.';
    copy.disabled = check.disabled = !phoneUrl;
    if (phoneUrl) {
      link.href = phoneUrl;
      try { qr.innerHTML = globalThis.HubQR.svg(phoneUrl); }
      catch (error) { qr.textContent = 'QR code unavailable. Use the link above.'; }
      status.textContent = 'Use Check connection to test this address from your computer. Then open it on your phone with Tailscale connected.';
    } else {
      status.textContent = 'Complete step 2, then reopen this guide. The link and QR code will appear here.';
    }
  }
  async function loadUrl() {
    if (location.protocol === 'https:') renderUrl(location.origin + '/');
    else renderUrl(null);
    try {
      const response = await fetch('/api/setup', { credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) return;
      const setup = await response.json();
      renderUrl(setup.phone_url || (location.protocol === 'https:' ? location.origin + '/' : null));
    } catch { /* The local address can still be displayed when already on HTTPS. */ }
  }
  async function checkConnection() {
    if (!phoneUrl) return;
    status.textContent = 'Checking the HTTPS address…';
    check.disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(new URL('api/phone-check', phoneUrl), { credentials: 'omit', cache: 'no-store', mode: 'cors', signal: controller.signal });
      if (!response.ok) throw new Error('The address did not answer.');
      const result = await response.json();
      if (result.ok !== true || result.service !== 'agent-hub' || result.origin !== new URL(phoneUrl).origin) throw new Error('The address answered with an unexpected service.');
      status.textContent = 'Connected: this computer reached Agent Hub at the private HTTPS address. Now open it on your phone with Tailscale connected.';
    } catch (error) {
      status.textContent = `${error.message || 'Connection failed.'} On this computer, check that Tailscale says Connected, run the exact tailscale serve command printed in step 2, and restart Agent Hub. Then check Tailscale on your phone.`;
    } finally { clearTimeout(timeout); check.disabled = false; }
  }
  function open() {
    if (!dialog) createDialog();
    if (!dialog.open) dialog.showModal();
    loadUrl();
  }
  globalThis.HubPhone = Object.freeze({ open });
})();
