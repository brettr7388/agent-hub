"""Durable owner-facing Hub preferences, search, and reversible archives."""
import json
import os
import re
from pathlib import Path
import secrets
from urllib.parse import quote
from hub_handoffs import strip_handoff_marker
from hub_fs import read_bytes, atomic_write_bytes, rename, rmdir


def fail(status, message):
    from hub import HubError
    raise HubError(status, message)


class ProductMixin:
    def init_product(self):
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS product_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS chat_preferences(chat_id TEXT PRIMARY KEY,pinned INTEGER NOT NULL DEFAULT 0,
            last_read_id INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS archives(kind TEXT NOT NULL,id TEXT NOT NULL,
            created REAL NOT NULL DEFAULT (strftime('%s','now')),PRIMARY KEY(kind,id));
        ''')
        self.db.commit()

    def _setting(self, key, default=None):
        row = self.db.execute('SELECT value FROM product_settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def _put_setting(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO product_settings VALUES(?,?)', (key, json.dumps(value)))

    def is_archived_agent(self, aid):
        return bool(self.db.execute("SELECT 1 FROM archives WHERE kind='agent' AND id=?", (aid,)).fetchone())

    def is_archived_chat(self, cid):
        return bool(self.db.execute("SELECT 1 FROM archives WHERE kind='chat' AND id=?", (cid,)).fetchone())

    def is_archived_swarm(self, sid):
        return bool(self.db.execute("SELECT 1 FROM archives WHERE kind='swarm' AND id=?", (sid,)).fetchone())

    def product_state(self):
        with self.lock:
            self.sync_chats()
            visible = {r[0] for r in self.db.execute('SELECT id FROM chats') if not self.is_archived_chat(r[0])}
            pins = [r[0] for r in self.db.execute('SELECT chat_id FROM chat_preferences WHERE pinned=1 ORDER BY rowid') if r[0] in visible]
            unread = {}
            for cid in visible:
                row = self.db.execute('''SELECT count(*) FROM messages WHERE chat_id=? AND id>
                    COALESCE((SELECT last_read_id FROM chat_preferences WHERE chat_id=?),0)
                    AND role IN ('assistant','system')''', (cid, cid)).fetchone()
                if row[0]: unread[cid] = row[0]
            last = self._setting('last_chat')
            return {'getting_started': {'completed': bool(self._setting('getting_started_completed', False)),
                    'dismissed': bool(self._setting('getting_started_dismissed', False))},
                    'pins': pins, 'unread': unread, 'last_chat': last if last in visible else None}

    def product_action(self, body):
        action, cid = body.get('action'), body.get('chat_id')
        if action in ('dismiss_getting_started', 'complete_getting_started'):
            with self.lock:
                self._put_setting('getting_started_' + ('dismissed' if action.startswith('dismiss') else 'completed'), True)
                self.db.commit()
        elif action in ('pin', 'unpin', 'mark_read', 'continue'):
            with self.lock:
                self.sync_chats()
                if not isinstance(cid, str) or not self.db.execute('SELECT 1 FROM chats WHERE id=?', (cid,)).fetchone() or self.is_archived_chat(cid):
                    fail(404, 'Chat not found.')
                if action in ('pin', 'unpin'):
                    self.db.execute('INSERT OR IGNORE INTO chat_preferences(chat_id) VALUES(?)', (cid,))
                    self.db.execute('UPDATE chat_preferences SET pinned=? WHERE chat_id=?', (int(action == 'pin'), cid))
                elif action == 'mark_read':
                    latest = self.db.execute('SELECT COALESCE(max(id),0) FROM messages WHERE chat_id=?', (cid,)).fetchone()[0]
                    upto = body.get('upto_id', latest)
                    if type(upto) is not int or upto < 0 or upto > latest:
                        fail(400, 'Invalid last-read message id.')
                    self.db.execute('INSERT OR IGNORE INTO chat_preferences(chat_id) VALUES(?)', (cid,))
                    self.db.execute('UPDATE chat_preferences SET last_read_id=max(last_read_id,?) WHERE chat_id=?', (upto, cid))
                else: self._put_setting('last_chat', cid)
                self.db.commit()
        else: fail(400, 'Unknown product action.')
        self.emit('product')
        return self.product_state()

    def search_messages(self, query):
        normalize = lambda text: re.sub(r'\s+', ' ', str(text or '')).strip().casefold()
        q = normalize((query.get('q') or [''])[0])
        if not q or len(q) > 200: return {'results': []}
        with self.lock:
            self.db.create_function('hub_search_text', 1, normalize, deterministic=True)
            archived_agents = {row[0] for row in self.db.execute("SELECT id FROM archives WHERE kind='agent'")}
            visible_agents = self.agents()
            hidden_chats = {row[0] for row in self.db.execute("SELECT id FROM archives WHERE kind='chat'")}
            for chat in self.db.execute("SELECT id,agents FROM chats WHERE type='direct'"):
                if any(aid in archived_agents or aid not in visible_agents for aid in json.loads(chat['agents'])):
                    hidden_chats.add(chat['id'])
            for chat in self.db.execute("SELECT id FROM chats WHERE type IN ('direct','group')"):
                self._ensure_version(chat['id'])
            self.db.commit()
            result = []
            title_ids = set()
            for chat in self.db.execute('SELECT id,name FROM chats WHERE instr(hub_search_text(name),?)>0 ORDER BY id LIMIT 100', (q,)):
                if chat['id'] in hidden_chats: continue
                title_ids.add(chat['id'])
                result.append({'chat_id': chat['id'], 'chat_name': chat['name'], 'message_id': None, 'text': 'Conversation'})
            rows = self.db.execute('''SELECT m.id AS message_id,m.chat_id,m.text,m.cards,m.created,c.name AS chat_name
                FROM messages m JOIN chats c ON c.id=m.chat_id
                WHERE (c.type NOT IN ('direct','group') OR c.id LIKE 'group:swarm-%' OR EXISTS (
                    SELECT 1 FROM version_messages vm JOIN chat_versions cv ON cv.id=vm.version_id
                    WHERE vm.message_id=m.id AND cv.chat_id=m.chat_id AND cv.active=1))
                AND (instr(hub_search_text(m.text),?)>0 OR instr(hub_search_text(m.cards),?)>0)
                ORDER BY m.id DESC LIMIT 100''', (q, q)).fetchall()
            for row in rows:
                if row['chat_id'] in hidden_chats or row['chat_id'] in title_ids: continue
                item = dict(row)
                cards = json.loads(item.pop('cards') or '[]')
                if q not in normalize(item['text']):
                    found = next((card for card in cards if isinstance(card, dict) and q in
                                  normalize(str(card.get('title') or '') + ' ' + str(card.get('text') or ''))), None)
                    if found: item['text'] = (str(found.get('title') or '') + ' ' + str(found.get('text') or '')).strip()
                item['text'] = strip_handoff_marker(item['text'])
                result.append(item)
            return {'results': result[:100]}

    def _active_chat(self, cid):
        return bool(self.db.execute("SELECT 1 FROM jobs WHERE chat_id=? AND status IN ('queued','working','typing')", (cid,)).fetchone())

    def _archive_id(self, old):
        while True:
            candidate = old[:46] + '-archived-' + secrets.token_hex(4)
            if not self.db.execute('SELECT 1 FROM chats WHERE id=? OR id=?',
                                   (candidate, 'agent:' + candidate)).fetchone() and not (self.create_dir / candidate).exists():
                return candidate

    def _rekey_chat(self, old, new):
        self.db.execute('UPDATE chats SET id=? WHERE id=?', (new, old))
        for table in ('messages', 'sessions', 'jobs', 'chat_preferences'):
            self.db.execute('UPDATE ' + table + ' SET chat_id=? WHERE chat_id=?', (new, old))
        self.db.execute('UPDATE chat_versions SET chat_id=? WHERE chat_id=?', (new, old))
        for setting in ('last_chat', 'quick_start_chat'):
            if self._setting(setting) == old:
                self._put_setting(setting, new)

    @staticmethod
    def _relocate_path_text(value, old, new):
        """Retarget saved file references without matching similarly named folders."""
        if not isinstance(value, str): return value
        value = value.replace(quote(old, safe='') + '%2F', quote(new, safe='') + '%2F')
        for source, target in ((quote(old, safe=''), quote(new, safe='')),
                               (quote(old), quote(new)), (old, new)):
            value = value.replace(source + '/', target + '/')
        return value

    def _release_agent_name(self, aid, already_archived=False):
        """Move a local agent's history to a durable archive identity."""
        old_folder = self.create_dir / aid
        if not old_folder.is_dir() or old_folder.is_symlink():
            fail(409, 'Archived agent folder needs manual review before its name can be reused.')
        if (self.agents_dir / aid).is_dir() and self.agents_dir != self.create_dir:
            fail(409, 'Imported agent folders cannot be renamed by Hub.')
        new = self._archive_id(aid)
        new_folder = self.create_dir / new
        old_chat, new_chat = 'agent:' + aid, 'agent:' + new
        avatar = old_folder / 'avatar.json'
        try:
            avatar_before = read_bytes(avatar)
        except FileNotFoundError:
            avatar_before = None
        rename(old_folder, new_folder)
        avatar = new_folder / 'avatar.json'
        try:
            self.db.execute('SAVEPOINT archive_agent')
            self._rekey_chat(old_chat, new_chat)
            self.db.execute('UPDATE product_settings SET key=? WHERE key=?',
                            ('pip_style:' + new, 'pip_style:' + aid))
            if self._setting('guide_agent_id') == aid:
                self._put_setting('guide_agent_id', new)
            for table in ('messages', 'sessions', 'jobs'):
                self.db.execute('UPDATE ' + table + ' SET agent_id=? WHERE agent_id=?', (new, aid))
            self.db.execute('UPDATE chats SET agents=? WHERE id=?', (json.dumps([new]), new_chat))
            for row in list(self.db.execute("SELECT id,agents FROM chats WHERE type='group'")):
                members = json.loads(row['agents'])
                if aid in members:
                    # A group's roster is live routing state, not an audit key.
                    # Historical messages/jobs above keep the suffixed identity.
                    remaining = [member for member in members if member != aid]
                    self.db.execute('UPDATE chats SET agents=? WHERE id=?',
                                    (json.dumps(remaining), row['id']))
                    if not remaining:
                        self.db.execute("INSERT OR IGNORE INTO archives(kind,id) VALUES('chat',?)", (row['id'],))
            for routine in list(self.db.execute('SELECT id,spec FROM routines')):
                spec = json.loads(routine['spec'])
                if spec.get('agent_id') == aid:
                    spec['agent_id'] = new
                    self.db.execute('UPDATE routines SET spec=?,enabled=0 WHERE id=?',
                                    (json.dumps(spec), routine['id']))
            old_path, new_path = str(old_folder), str(new_folder)
            for row in list(self.db.execute('SELECT id,text,cards,uploads FROM messages')):
                changed = {}
                for column in ('text', 'cards', 'uploads'):
                    value = row[column]
                    relocated = self._relocate_path_text(value, old_path, new_path)
                    if relocated != value: changed[column] = relocated
                if changed:
                    for column, value in changed.items():
                        self.db.execute('UPDATE messages SET ' + column + '=? WHERE id=?', (value, row['id']))
            for row in list(self.db.execute('SELECT chat_id,agent_id,cwd FROM sessions')):
                cwd = row['cwd'] or ''
                if cwd == old_path or cwd.startswith(old_path + os.sep):
                    self.db.execute('UPDATE sessions SET cwd=? WHERE chat_id=? AND agent_id=?',
                                    (new_path + cwd[len(old_path):], row['chat_id'], row['agent_id']))
            if avatar_before is not None:
                metadata = json.loads(avatar_before.decode('utf-8'))
                workdir = metadata.get('workdir') or ''
                if workdir == old_path or workdir.startswith(old_path + os.sep):
                    metadata['workdir'] = new_path + workdir[len(old_path):]
                    atomic_write_bytes(avatar, json.dumps(metadata, ensure_ascii=False, indent=2).encode('utf-8'))
            if already_archived:
                self.db.execute("DELETE FROM archives WHERE kind='agent' AND id=?", (aid,))
                self.db.execute("DELETE FROM archives WHERE kind='chat' AND id=?", (old_chat,))
            self.db.execute("INSERT INTO archives(kind,id) VALUES('agent',?)", (new,))
            self.db.execute("INSERT INTO archives(kind,id) VALUES('chat',?)", (new_chat,))
            self.db.execute('RELEASE archive_agent')
        except Exception:
            self.db.execute('ROLLBACK TO archive_agent')
            self.db.execute('RELEASE archive_agent')
            try:
                if avatar_before is not None:
                    atomic_write_bytes(avatar, avatar_before)
            finally:
                rename(new_folder, old_folder)
            raise
        return new

    def release_archived_agent_name(self, aid):
        """Upgrade archives made before name reuse was supported."""
        if not self.is_archived_agent(aid): return
        if self.agents_dir != self.create_dir and (self.agents_dir / aid).exists():
            fail(409, 'Archived imported agent name remains reserved by its read-only folder.')
        if (self.create_dir / aid).exists():
            self._release_agent_name(aid, already_archived=True)
            self.db.commit()

    def archive(self, body):
        kind, ident = body.get('kind'), body.get('id')
        if kind not in ('agent', 'group', 'swarm') or not isinstance(ident, str) or not ident:
            fail(400, 'Choose an agent, group, or swarm.')
        with self.lock:
            if kind == 'agent':
                agent = self.agents().get(ident)
                if not agent or agent.get('swarm'): fail(404, 'Agent not found.')
                cid = 'agent:' + ident
                if self.db.execute("SELECT 1 FROM jobs WHERE agent_id=? AND status IN ('queued','working','typing')", (ident,)).fetchone():
                    fail(409, 'Wait for the agent to finish.')
                paused = 0
                for routine in list(self.db.execute('SELECT id,spec FROM routines WHERE enabled=1')):
                    if json.loads(routine['spec']).get('agent_id') == ident:
                        self.db.execute('UPDATE routines SET enabled=0 WHERE id=?', (routine['id'],))
                        paused += 1
                if agent['external']:
                    self.db.execute("INSERT OR IGNORE INTO archives(kind,id) VALUES('agent',?)", (ident,))
                    self.db.execute("INSERT OR IGNORE INTO archives(kind,id) VALUES('chat',?)", (cid,))
                    archived_id = ident
                else:
                    archived_id = self._release_agent_name(ident)
                result = {'ok': True, 'kind': kind, 'id': ident, 'archived_id': archived_id,
                          'files_preserved': True,
                          'external_hidden': bool(agent['external']), 'routines_paused': paused}
            elif kind == 'group':
                row = self.db.execute("SELECT id FROM chats WHERE id=? AND type='group'", (ident,)).fetchone()
                if not row or self.db.execute('SELECT 1 FROM swarms WHERE chat_id=?', (ident,)).fetchone():
                    fail(404, 'Group not found.')
                if self._active_chat(ident): fail(409, 'Wait for the group to finish.')
                archived_id = self._archive_id(ident)
                self._rekey_chat(ident, archived_id)
                self.db.execute("INSERT INTO archives(kind,id) VALUES('chat',?)", (archived_id,))
                result = {'ok': True, 'kind': kind, 'id': ident, 'archived_id': archived_id,
                          'history_preserved': True}
            else:
                swarm = self.swarm(ident)
                if body.get('confirm') is not True: fail(409, 'Confirm team archive and owned worktree cleanup.')
                if swarm['status'] in ('working', 'judging'):
                    fail(409, 'Wait for the team to finish.')
                if self._active_chat(swarm['worker_chat_id']): fail(409, 'Wait for team jobs to finish.')
                for worker in swarm['workers']:
                    if worker['job_id'] and self.db.execute("SELECT 1 FROM jobs WHERE id=? AND status IN ('queued','working','typing')", (worker['job_id'],)).fetchone():
                        fail(409, 'Wait for team jobs to finish.')
                base = self.data / 'worktrees' / ident
                if base.is_symlink(): fail(409, 'Team worktree directory needs manual review.')
                for worker in swarm['workers']:
                    raw = worker['worktree']
                    if not raw: continue
                    tree = Path(raw)
                    if tree.is_symlink() or tree.parent != base or tree.name != str(worker['number']):
                        fail(409, 'Worktree is not owned by this team.')
                    if tree.exists() and self._worktree_dirty(tree) and body.get('confirm_dirty') is not True:
                        fail(409, 'Worktree has changes; confirm discarding those files.')
                for worker in swarm['workers']:
                    raw = worker['worktree']
                    if not raw: continue
                    tree = Path(raw)
                    if tree.exists(): self._git(Path(swarm['working_dir']), 'worktree', 'remove', '--force', str(tree))
                    self.db.execute('UPDATE swarm_workers SET worktree=NULL WHERE agent_id=?', (worker['agent_id'],))
                # Only remove empty Hub-owned containers. Scratch output and
                # untracked/uncertain files remain for the owner to inspect.
                if base.is_dir() and not base.is_symlink():
                    try: rmdir(base)
                    except OSError: pass
                scratch = self.data / 'teams' / ident
                if (Path(swarm['working_dir']) == scratch and scratch.is_dir()
                        and not scratch.is_symlink()):
                    for worker in swarm['workers']:
                        child = scratch / str(worker['number'])
                        if child.is_dir() and not child.is_symlink():
                            try: rmdir(child)
                            except OSError: pass
                    try: rmdir(scratch)
                    except OSError: pass
                self.db.execute("INSERT OR IGNORE INTO archives(kind,id) VALUES('swarm',?)", (ident,))
                self.db.execute("INSERT OR IGNORE INTO archives(kind,id) VALUES('chat',?)", (swarm['worker_chat_id'],))
                for worker in swarm['workers']:
                    self.db.execute("INSERT OR IGNORE INTO archives(kind,id) VALUES('agent',?)", (worker['agent_id'],))
                    self.db.execute("INSERT OR IGNORE INTO archives(kind,id) VALUES('chat',?)", ('agent:' + worker['agent_id'],))
                result = {'ok': True, 'kind': kind, 'id': ident, 'files_preserved': True,
                          'worktrees_removed': True, 'scratch_preserved': scratch.exists(),
                          'worktree_directory_preserved': base.exists()}
            guide_changed = self.reset_guide_proposals_for_archive(kind, ident)
            self.db.commit()
        self.emit('agents')
        self.emit('groups')
        self.emit('swarms')
        self.emit('routines')
        if guide_changed: self.emit('message', self.guide_chat())
        return result

    def unarchive(self, body):
        ident = body.get('id')
        with self.lock:
            agent = self.agents(include_hidden=True).get(ident)
            if not agent or agent.get('swarm'):
                fail(404, 'Pip not found.')
            self.db.execute("DELETE FROM archives WHERE kind='agent' AND id=?", (ident,))
            self.db.execute("DELETE FROM archives WHERE kind='chat' AND id=?", ('agent:' + ident,))
            self.db.commit()
        self.emit('agents')
        return {'ok': True, 'agent': self.public_agent(self.agents()[ident])}

    def delete_routine(self, body):
        rid = body.get('id')
        with self.lock:
            row = self.db.execute('SELECT id FROM routines WHERE id=?', (rid,)).fetchone()
            if not row: fail(404, 'Hub schedule not found.')
            if self.db.execute("""SELECT 1 FROM routine_runs r JOIN jobs j ON j.id=r.job_id
                WHERE r.routine_id=? AND j.status IN ('queued','working','typing')""", (rid,)).fetchone():
                fail(409, 'Wait for the scheduled job to finish.')
            self.db.execute('DELETE FROM routines WHERE id=?', (rid,))
            self.db.commit()
        self.emit('routines')
        return {'ok': True, 'id': rid}
