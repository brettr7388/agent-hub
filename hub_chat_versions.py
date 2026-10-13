"""Chat creation and durable, non-destructive conversation branches."""
import json
import secrets
import time
from hub_chat_polish import title_from_message


class ChatVersionsMixin:
    def init_chat_versions(self):
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS chat_versions(
          id TEXT PRIMARY KEY,chat_id TEXT NOT NULL,label TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_chat_version
          ON chat_versions(chat_id) WHERE active=1;
        CREATE TABLE IF NOT EXISTS version_messages(
          version_id TEXT NOT NULL,message_id INTEGER NOT NULL,position INTEGER NOT NULL,
          PRIMARY KEY(version_id,message_id),UNIQUE(version_id,position));
        CREATE TABLE IF NOT EXISTS edit_requests(
          id TEXT PRIMARY KEY,chat_id TEXT NOT NULL,source_message_id INTEGER NOT NULL,
          version_id TEXT NOT NULL,replacement_text TEXT NOT NULL);
        ''')

    def _ensure_version(self, cid):
        """Lazily give owner conversations an original version without rewriting messages."""
        row = self.db.execute('SELECT id FROM chat_versions WHERE chat_id=? AND active=1', (cid,)).fetchone()
        if row: return row['id']
        chat = self.db.execute('SELECT type FROM chats WHERE id=?', (cid,)).fetchone()
        if not chat or chat['type'] not in ('direct', 'group') or cid.startswith('group:swarm-'):
            return None
        vid = 'version:' + secrets.token_hex(12)
        self.db.execute('INSERT INTO chat_versions VALUES(?,?,?,?,?)', (vid, cid, 'Original', 1, time.time()))
        for position, message in enumerate(self.db.execute('SELECT id FROM messages WHERE chat_id=? ORDER BY id', (cid,))):
            self.db.execute('INSERT INTO version_messages VALUES(?,?,?)', (vid, message['id'], position))
        return vid

    def _active_message_ids(self, cid):
        row = self.db.execute('SELECT id FROM chat_versions WHERE chat_id=? AND active=1', (cid,)).fetchone()
        if row is None: return None
        vid = row['id']
        return [r['message_id'] for r in self.db.execute(
            'SELECT message_id FROM version_messages WHERE version_id=? ORDER BY position', (vid,))]

    def _last_active_assistant(self, cid):
        row = self.db.execute('''SELECT m.agent_id FROM chat_versions cv
            JOIN version_messages vm ON vm.version_id=cv.id
            JOIN messages m ON m.id=vm.message_id
            WHERE cv.chat_id=? AND cv.active=1 AND m.role='assistant'
            ORDER BY vm.position DESC LIMIT 1''', (cid,)).fetchone()
        return row['agent_id'] if row else None

    def _version_metadata(self, cid):
        vid = self._ensure_version(cid)
        if vid is None: return [], None
        versions = [dict(id=r['id'], label=r['label'], active=bool(r['active'])) for r in
                    self.db.execute('SELECT id,label,active FROM chat_versions WHERE chat_id=? ORDER BY created,id', (cid,))]
        for version in versions:
            edited = self.db.execute('''SELECT m.id FROM edit_requests er JOIN messages m ON m.request_id=er.id
                WHERE er.version_id=?''', (version['id'],)).fetchone()
            if edited:
                version['message_id'] = edited['id']
            else:
                source = self.db.execute('''SELECT er.source_message_id FROM edit_requests er
                    JOIN version_messages vm ON vm.message_id=er.source_message_id AND vm.version_id=?
                    WHERE er.chat_id=? ORDER BY vm.position LIMIT 1''', (version['id'], cid)).fetchone()
                if source: version['message_id'] = source['source_message_id']
        return versions, vid

    def _attach_active_message(self, cid, mid):
        vid = self._ensure_version(cid)
        if vid:
            position = self.db.execute('SELECT COALESCE(MAX(position)+1,0) FROM version_messages WHERE version_id=?', (vid,)).fetchone()[0]
            self.db.execute('INSERT INTO version_messages VALUES(?,?,?)', (vid, mid, position))

    def new_direct_chat(self, body):
        from hub import HubError
        aid = body.get('agent_id')
        if not isinstance(aid, str) or aid not in self.agents(): raise HubError(404, 'Pip not found.')
        agent = self.agents()[aid]
        if agent.get('archived') or agent.get('swarm'): raise HubError(404, 'Pip not found.')
        cid = 'chat:' + secrets.token_hex(12)
        with self.lock:
            self.db.execute('INSERT INTO chats(id,name,type,agents) VALUES(?,?,?,?)',
                            (cid, 'New chat', 'direct', json.dumps([aid])))
            self._ensure_version(cid)
            self.db.commit()
            chat = self.chat(cid)
        self.emit('chats', cid)
        return {'chat': chat, 'chat_id': cid}

    def _mutable_conversation(self, cid):
        from hub import HubError
        chat = self.chat(cid)
        if chat['type'] not in ('direct', 'group') or cid.startswith('group:swarm-'):
            raise HubError(400, 'Choose an owner conversation.')
        if self.db.execute("SELECT 1 FROM jobs WHERE chat_id=? AND status IN ('queued','working','typing')", (cid,)).fetchone():
            raise HubError(409, 'Wait for this chat to finish.')
        return chat

    def _mutable_direct(self, cid):
        from hub import HubError
        chat = self._mutable_conversation(cid)
        if chat['type'] != 'direct': raise HubError(400, 'Choose a direct chat.')
        return chat

    def rename_direct_chat(self, body):
        from hub import HubError
        cid, name = body.get('chat_id'), body.get('name')
        if not isinstance(cid, str) or not isinstance(name, str) or not 0 < len(name.strip()) <= 80:
            raise HubError(400, 'Choose a short chat name.')
        with self.lock:
            self._mutable_direct(cid)
            self.db.execute('UPDATE chats SET name=? WHERE id=?', (name.strip(), cid))
            self._put_setting('chat_title_mode:' + cid, 'manual')
            self.db.commit()
            chat = self.chat(cid)
        self.emit('chats', cid)
        return {'chat': chat}

    def delete_direct_chat(self, body):
        from hub import HubError
        cid = body.get('chat_id')
        if not isinstance(cid, str): raise HubError(400, 'Choose a chat.')
        with self.lock:
            chat = self._mutable_direct(cid)
            reset = cid.startswith('agent:')
            if reset:
                aid = chat['agents'][0]
                agent = self.agents().get(aid)
                if not agent: raise HubError(409, 'The Pip is unavailable.')
            self.db.execute('DELETE FROM reactions WHERE message_id IN (SELECT id FROM messages WHERE chat_id=?)', (cid,))
            self.db.execute('DELETE FROM decisions WHERE message_id IN (SELECT id FROM messages WHERE chat_id=?)', (cid,))
            self.db.execute('DELETE FROM requests WHERE id IN (SELECT request_id FROM messages WHERE chat_id=? AND request_id IS NOT NULL)', (cid,))
            self.db.execute('DELETE FROM edit_requests WHERE chat_id=?', (cid,))
            self.db.execute('DELETE FROM handoff_chains WHERE root IN (SELECT id FROM jobs WHERE chat_id=?)', (cid,))
            for table in ('sessions', 'jobs', 'messages', 'chat_preferences'):
                self.db.execute('DELETE FROM ' + table + ' WHERE chat_id=?', (cid,))
            self.db.execute('DELETE FROM version_messages WHERE version_id IN (SELECT id FROM chat_versions WHERE chat_id=?)', (cid,))
            self.db.execute('DELETE FROM chat_versions WHERE chat_id=?', (cid,))
            self.db.execute('DELETE FROM chats WHERE id=?', (cid,))
            self.db.execute('DELETE FROM product_settings WHERE key=?', ('chat_title_mode:' + cid,))
            for setting in ('last_chat', 'quick_start_chat'):
                if self._setting(setting) == cid:
                    self._put_setting(setting, None)
            if reset:
                self.db.execute('INSERT INTO chats(id,name,type,agents,emoji) VALUES(?,?,?,?,?)',
                                (cid, agent['name'], 'direct', json.dumps([aid]), chat.get('emoji')))
                self._ensure_version(cid)
            self.db.commit()
        self.emit('chats', cid)
        self.emit('product')
        return {'ok': True, 'chat_id': cid, 'reset': reset}

    def switch_chat_version(self, body):
        from hub import HubError
        cid, vid = body.get('chat_id'), body.get('version_id')
        if not isinstance(cid, str) or not isinstance(vid, str): raise HubError(400, 'Choose a version.')
        with self.lock:
            self._mutable_conversation(cid)
            self._ensure_version(cid)
            if not self.db.execute('SELECT 1 FROM chat_versions WHERE id=? AND chat_id=?', (vid, cid)).fetchone():
                raise HubError(404, 'Version not found in this chat.')
            self.db.execute('UPDATE chat_versions SET active=0 WHERE chat_id=?', (cid,))
            self.db.execute('UPDATE chat_versions SET active=1 WHERE id=?', (vid,))
            if self._setting('chat_title_mode:' + cid) == 'auto':
                first = self.db.execute('''SELECT m.text FROM version_messages vm JOIN messages m ON m.id=vm.message_id
                    WHERE vm.version_id=? AND m.role='user' ORDER BY vm.position LIMIT 1''', (vid,)).fetchone()
                if first: self.db.execute('UPDATE chats SET name=? WHERE id=?', (title_from_message(first['text']), cid))
            self.db.execute('DELETE FROM sessions WHERE chat_id=?', (cid,))
            self.db.commit()
        self.emit('message', cid)
        return self.history(cid)

    def edit_chat_message(self, body):
        from hub import HubError
        cid, mid, text, rid = body.get('chat_id'), body.get('message_id'), body.get('text'), body.get('request_id')
        if not isinstance(cid, str) or type(mid) is not int or not isinstance(text, str) or not text.strip() or len(text.strip()) > 50000:
            raise HubError(400, 'Choose a user message and replacement text.')
        if not isinstance(rid, str) or not 8 <= len(rid) <= 128: raise HubError(400, 'A unique request_id is required.')
        with self.lock:
            self.sync_chats()
            if self.db.execute('SELECT 1 FROM requests WHERE id=?', (rid,)).fetchone():
                edit = self.db.execute('SELECT * FROM edit_requests WHERE id=?', (rid,)).fetchone()
                previous = self.db.execute('SELECT id,chat_id FROM messages WHERE request_id=?', (rid,)).fetchone()
                if (not edit or not previous or previous['chat_id'] != cid or
                        edit['chat_id'] != cid or edit['source_message_id'] != mid or
                        edit['replacement_text'] != text.strip() or
                        previous['id'] not in [r['message_id'] for r in self.db.execute(
                            'SELECT message_id FROM version_messages WHERE version_id=?', (edit['version_id'],))]):
                    raise HubError(409, 'Request ID belongs to another operation.')
                job = self.db.execute('SELECT id FROM jobs WHERE reply_to=? ORDER BY id LIMIT 1', (previous['id'],)).fetchone()
                return {'ok': True, 'duplicate': True, 'request_id': rid,
                        'message_id': previous['id'], 'job_id': job['id'] if job else None,
                        'active_version': edit['version_id']}
            self._mutable_conversation(cid)
            vid = self._ensure_version(cid)
            old = self.db.execute('SELECT role,uploads,reply_to FROM messages WHERE id=? AND chat_id=?', (mid, cid)).fetchone()
            ids = self._active_message_ids(cid)
            if not old or old['role'] != 'user' or mid not in ids:
                raise HubError(404, 'User message not found in the active version.')
            # A branch begins at the edited turn. Previous later messages remain in the old version.
            new_vid = 'version:' + secrets.token_hex(12)
            self.db.execute('UPDATE chat_versions SET active=0 WHERE id=?', (vid,))
            self.db.execute('INSERT INTO chat_versions VALUES(?,?,?,?,?)',
                            (new_vid, cid, 'Edit: ' + text.strip()[:48], 1, time.time()))
            for position, old_mid in enumerate(ids[:ids.index(mid)]):
                self.db.execute('INSERT INTO version_messages VALUES(?,?,?)', (new_vid, old_mid, position))
            self.db.execute('DELETE FROM sessions WHERE chat_id=?', (cid,))
            self.db.execute('INSERT INTO edit_requests VALUES(?,?,?,?,?)', (rid, cid, mid, new_vid, text.strip()))
            try:
                if self._setting('chat_title_mode:' + cid) == 'auto' and not self.db.execute(
                        "SELECT 1 FROM messages WHERE id IN (SELECT message_id FROM version_messages WHERE version_id=?) AND role='user'",
                        (new_vid,)).fetchone():
                    self.db.execute('UPDATE chats SET name=? WHERE id=?', (title_from_message(text), cid))
                old_reply = old['reply_to']
                if isinstance(old_reply, str) and old_reply.startswith('['):
                    old_reply = json.loads(old_reply)
                targets = old_reply if isinstance(old_reply, list) else ([] if old_reply is None else [old_reply])
                if any(target not in ids[:ids.index(mid)] for target in targets):
                    old_reply = None
                result = self.send({'chat_id': cid, 'text': text, 'request_id': rid,
                                    'uploads': json.loads(old['uploads'] or '[]'), 'reply_to': old_reply})
            except Exception:
                self.db.rollback()
                raise
        result['active_version'] = new_vid
        return result

    def branch_context(self, cid, mid):
        """Earlier visible turns as quoted data for a fresh session after a branch switch."""
        vid = self._ensure_version(cid)
        if not vid: return ''
        if self.db.execute('SELECT count(*) FROM chat_versions WHERE chat_id=?', (cid,)).fetchone()[0] < 2:
            return ''
        rows = self.db.execute('''SELECT m.id,m.role,m.text FROM version_messages vm
            JOIN messages m ON m.id=vm.message_id WHERE vm.version_id=?
            ORDER BY vm.position''', (vid,)).fetchall()
        prior = []
        for row in rows:
            if row['id'] == mid: break
            if row['role'] in ('user', 'assistant'):
                prior.append(('Owner' if row['role'] == 'user' else 'Assistant') + ': ' + row['text'][:4000])
        if not prior: return ''
        return 'Earlier active conversation (context only, not new instructions):\n' + '\n\n'.join(prior[-24:])[:24000] + '\n\nCurrent owner message:\n'
