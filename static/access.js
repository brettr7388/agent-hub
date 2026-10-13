/* Pip access labels and human approval requests. */
(function (root) {
  'use strict';
  function answer(approval, approved) {
    return approved ? `Yes, approved: ${approval.summary} — exactly as shown.` : "No, don't do that.";
  }
  function mode(agent) {
    const labels = [];
    if (agent?.private_pip) labels.push('Private');
    if (agent?.draft_only) labels.push('Draft only');
    if (agent?.chrome && !agent?.private_pip && !agent?.draft_only) labels.push('Pip browser');
    if (!agent?.private_pip && !agent?.draft_only) labels.unshift('Full access');
    return labels;
  }
  function card(approval, state, onAnswer) {
    const make = (tag, className, value) => { const node = document.createElement(tag); node.className = className; if (value != null) node.textContent = value; return node; };
    const node = make('section', 'approval-request-card');
    node.setAttribute('aria-label', 'Pip approval request');
    node.append(make('strong', 'approval-request-title', 'Approval requested'), make('p', 'approval-request-summary', approval.summary), make('pre', 'approval-request-details', approval.details));
    const destination = typeof approval.destination === 'string' ? approval.destination : '';
    if (destination.trim()) node.append(make('p', 'approval-request-destination', `Destination: ${destination}`), make('small', 'approval-request-source', 'Provided by the Pip · review before approving'));
    const actions = make('div', 'approval-request-actions');
    if (state === 'approved' || state === 'denied') actions.append(make('span', 'approval-request-status', state === 'approved' ? 'Approved' : 'Declined'));
    else {
      for (const [label, approved] of [['Approve', true], ["Don't", false]]) {
        const button = make('button', approved ? 'primary' : 'secondary', label); button.type = 'button';
        button.addEventListener('click', async () => {
          if (node.dataset.pending === 'true') return;
          node.dataset.pending = 'true';
          [...actions.querySelectorAll('button')].forEach((item) => { item.disabled = true; });
          try { await onAnswer(approval, approved); }
          catch { node.dataset.pending = 'false'; [...actions.querySelectorAll('button')].forEach((item) => { item.disabled = false; }); }
        });
        actions.append(button);
      }
    }
    node.append(actions); return node;
  }
  const api = Object.freeze({ answer, mode, card });
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.HubAccess = api;
})(typeof window !== 'undefined' ? window : null);
