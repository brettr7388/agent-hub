"""Pip access preferences. Imported folders keep their settings in Hub's DB."""
import os
from hub_security import allowed_agent_environment


APPROVAL_RULE = '''Hub approval rule: Before sending a message outside Agent Hub (including a DM or email), posting publicly,
purchasing, deleting data, or changing account settings, show the exact text/item
in an approval request and stop until the owner answers. Use exactly this format:
```agent-hub
{"action":"approval_request","summary":"Send this message","destination":"<actual site/page and recipient>","details":"<the exact text/item>"}
```
Use the destination from your current task and actual page/tool details. Do not guess
a platform from this example or the recipient's name. If the destination is unknown,
say that in the details and ask the owner before proposing the action. Hub displays
your destination as Pip-provided information, not an independently verified target.
An approval covers only the details shown. Never perform the action before approval.
The card only relays the owner's answer; you perform approved work through your normal tools.'''


def codex_exec_command(binary, sid='', draft_only=False, isolated=False):
    """Global sandbox option also applies to exec resume (which has fewer flags)."""
    flags = ['-s', 'read-only'] if draft_only else ([] if isolated else
            ['-s', 'workspace-write', '-c', 'approval_policy="never"'])
    args = [binary] + flags + ['exec']
    return args + (['resume', sid] if sid else [])


class PipAccessMixin:
    def pip_access(self, aid, meta=None):
        meta = meta or {}
        overlay = self._setting('pip_access:' + aid, {})
        if not isinstance(overlay, dict): overlay = {}
        private = overlay.get('private_pip', meta.get('private_pip', False)) is True
        draft = overlay.get('draft_only', meta.get('draft_only', False)) is True
        return {'private_pip': private, 'draft_only': draft,
                'use_global_rules': not private,
                'chrome': not (private or draft) and meta.get('chrome', False) is True}

    def edit_pip_access(self, body):
        from hub import HubError
        aid = body.get('id')
        if not isinstance(aid, str): raise HubError(400, 'Choose a Pip.')
        changes = {key: body[key] for key in ('private_pip', 'draft_only') if key in body}
        if not changes or set(body) - {'id', 'private_pip', 'draft_only'}:
            raise HubError(400, 'Choose Private Pip or Draft only.')
        if any(type(value) is not bool for value in changes.values()):
            raise HubError(400, 'Choose Pip permissions.')
        with self.lock:
            agent = self.agents().get(aid)
            if not agent: raise HubError(404, 'Pip not found.')
            if not (agent.get('linked') or agent.get('swarm')):
                return self.edit_agent(body)
            if self.db.execute("SELECT 1 FROM jobs WHERE agent_id=? AND status IN ('queued','working','typing')", (aid,)).fetchone():
                raise HubError(409, 'Wait for this Pip to finish before editing.')
            overlay = self._setting('pip_access:' + aid, {})
            self._put_setting('pip_access:' + aid, dict(overlay, **changes))
            self.db.execute('DELETE FROM sessions WHERE agent_id=?', (aid,))
            self.db.commit()
        self.emit('agents')
        return {'agent': self.public_agent(self.agents()[aid]), 'session_reset': True}

    def pip_environment(self, engine, sealed=False):
        if sealed and engine == 'codex': return self.codex_environment()
        if sealed: return allowed_agent_environment()
        # Plugins, MCPs and provider auth may use arbitrary environment names.
        return dict(os.environ)
