"""Small, deterministic chat title and directed-message helpers."""
import json
import re


def title_from_message(text, limit=60):
    words = re.sub(r'\s+', ' ', text).strip()
    words = re.sub(r'\.{3,}$', '…', words)
    if not words:
        return 'Attachment'
    if len(words) <= limit:
        return words
    boundary = words.rfind(' ', 0, limit + 1)
    if boundary > 0:
        return words[:boundary].rstrip()
    remainder = words.partition(' ')[2]
    return title_from_message(remainder, limit) if remainder else 'Long request'


def backfill_default_titles(hub):
    """Title old default direct chats once, leaving explicit names alone."""
    agents = hub.agents(include_hidden=True)
    for chat in hub.db.execute("SELECT id,name,agents FROM chats WHERE type='direct'").fetchall():
        cid = chat['id']
        mode = hub._setting('chat_title_mode:' + cid)
        if mode == 'auto':
            clean = re.sub(r'\.{3,}$', '…', chat['name'])
            if clean != chat['name']:
                hub.db.execute('UPDATE chats SET name=? WHERE id=?', (clean, cid))
        if mode in ('auto', 'manual'):
            continue
        member_ids = json.loads(chat['agents'])
        default_name = agents.get(member_ids[0], {}).get('name') if member_ids else None
        if chat['name'] not in ('New chat', default_name):
            continue
        row = hub.db.execute("SELECT text FROM messages WHERE chat_id=? AND role='user' ORDER BY id LIMIT 1", (cid,)).fetchone()
        if row and row['text'].strip() and row['text'].strip() != '/new':
            hub.db.execute('UPDATE chats SET name=? WHERE id=?', (title_from_message(row['text']), cid))
            hub._put_setting('chat_title_mode:' + cid, 'auto')


def directed_member(text, members, agents):
    """Resolve a leading `Name: task` or `Name, task`; return None without a prefix.

    Ambiguous exact names return an error. Other colon-prefixed prose follows
    the ordinary group routing path.
    """
    match = re.match(r'^([^:,\n]{1,80})[:,]\s*(\S[\s\S]*)$', text)
    if not match:
        return None
    label = match.group(1).strip().casefold()
    if not label or not label[0].isalpha():
        return None
    matches = [aid for aid in members if label in (aid.casefold(), agents[aid]['name'].casefold())]
    if len(matches) > 1:
        return ('error', 'Ambiguous group member.')
    if not matches:
        return None
    return (matches[0], match.group(2).strip())
