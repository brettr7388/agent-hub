"""Authenticated, bounded exports with an explicit data allowlist."""
import io
import json
from pathlib import Path
from hub_fs import listdir, read_bytes, read_text
import re
import time
import zipfile


_SECRET_PATTERNS = (
    ('private_key', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*', re.I)),
    ('bearer', re.compile(r'(?i)\b(?:authorization\s*:\s*)?bearer\s+[^\s,;]+')),
    ('assignment', None),
    ('sensitive_field', None),
    ('token', re.compile(r'(?<![A-Za-z0-9_])(?:sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9_]{8,}|xox[baprs]-[A-Za-z0-9-]{8,})(?![A-Za-z0-9_-])')),
    ('entropy', re.compile(r'\S{32,}')),
)
_ASSIGNMENT = re.compile(r'''(?i)(?<![A-Za-z0-9_])(?P<quote>["']?)(?P<name>[A-Za-z_][A-Za-z0-9_-]{0,127})(?P=quote)\s*[:=]\s*''')
_SENSITIVE_NAME = re.compile(r'key|token|secret|password|passwd', re.I)
_PROSE_SECRET = re.compile(
    r'''(?ix)(?<![A-Za-z0-9_])(?:my\s+)?(?:password|pin|api[ _-]?key)\s+(?:is\s+|:\s*|=\s*)'''
)


def _redact_assignments(value):
    """Bounded identifier matching, then a linear scan of each sensitive value."""
    result = []
    position = 0
    count = 0
    for match in _ASSIGNMENT.finditer(value):
        if match.start() < position or not _SENSITIVE_NAME.search(match.group('name')):
            continue
        start = match.end()
        if start >= len(value):
            end = start
        elif value[start] in ('"', "'"):
            quote = value[start]
            end = start + 1
            while end < len(value):
                if value[end] == '\\':
                    end += 2
                elif value[end] == quote:
                    end += 1
                    break
                else:
                    end += 1
            # An unterminated quote consumes the rest of this text field.
            end = min(end, len(value))
        else:
            end = start
            while end < len(value) and not value[end].isspace():
                end += 1
        result.extend((value[position:match.start()], '[redacted]'))
        position = end
        count += 1
    result.append(value[position:])
    return ''.join(result), count


def _redact_prose_secrets(value):
    """Catch common secrets written as prose, including quoted multiword values."""
    result = []
    position = 0
    count = 0
    for match in _PROSE_SECRET.finditer(value):
        if match.start() < position:
            continue
        start = match.end()
        end = start
        if start < len(value) and value[start] in ('"', "'"):
            quote = value[start]
            end = start + 1
            while end < len(value):
                if value[end] == '\\':
                    end += 2
                elif value[end] == quote:
                    end += 1
                    break
                else:
                    end += 1
        else:
            while end < len(value) and not value[end].isspace():
                end += 1
        if end == start:
            continue
        result.extend((value[position:start], '[redacted]'))
        position = end
        count += 1
    result.append(value[position:])
    return ''.join(result), count


def _redact_text(value, counts):
    """Conservatively screen any export string, including nested metadata."""
    if not isinstance(value, str):
        raise TypeError('Export text must be a string')
    for kind, pattern in _SECRET_PATTERNS:
        if kind == 'assignment':
            value, count = _redact_assignments(value)
        elif kind == 'sensitive_field':
            value, count = _redact_prose_secrets(value)
        elif pattern is not None:
            value, count = pattern.subn('[redacted]', value)
        else:
            count = 0
        counts[kind] = counts.get(kind, 0) + count
    return value


def _redact_tree(value, counts):
    if isinstance(value, str):
        return _redact_text(value, counts)
    if isinstance(value, list):
        return [_redact_tree(item, counts) for item in value]
    if isinstance(value, tuple):
        return [_redact_tree(item, counts) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            safe_key = _redact_text(str(key), counts)
            if _SENSITIVE_NAME.search(str(key)):
                result[safe_key] = '[redacted]'
                counts['sensitive_field'] = counts.get('sensitive_field', 0) + 1
            else:
                result[safe_key] = _redact_tree(item, counts)
        return result
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TypeError('Unsupported export field type')


def _redaction_note(counts):
    return 'Redactions: ' + str(sum(counts.values())) + ' (' + ', '.join(
        kind + ': ' + str(counts.get(kind, 0)) for kind, _ in _SECRET_PATTERNS) + ')'


def _merge_counts(total, local):
    if total is not None:
        for key, value in local.items():
            total[key] = total.get(key, 0) + value


def _safe_instruction_bytes(path, counts=None):
    """Redact readable instructions; exclude uncertain or oversized files."""
    try:
        data = read_bytes(path, limit=1024 * 1024)
        value = data.decode('utf-8')
    except (OSError, UnicodeError, ValueError):
        return None
    local = {}
    safe = _redact_text(value, local)
    _merge_counts(counts, local)
    return safe.encode('utf-8')


def conversation(hub, chat_id, include_archived=False, counts=None):
    data = hub.history(chat_id, include_archived=include_archived)
    with hub.lock:
        for item in data['messages']:
            row = hub.db.execute('SELECT uploads,cards FROM messages WHERE id=?', (item['id'],)).fetchone()
            for path in json.loads(row['uploads'] or '[]'):
                if not any(a.get('path') == path for a in item['attachments']):
                    item['attachments'].append({'name': Path(path).name, 'path': path})
            for card, raw in zip(item.get('cards', []), json.loads(row['cards'] or '[]')):
                if raw.get('media') and not card.get('media'):
                    card['media'] = {'name': Path(raw['media']).name, 'path': raw['media']}
    return _redact_tree(data, counts if counts is not None else {})


def markdown_chat(hub, chat_id, include_archived=False, counts=None):
    local = {}
    data = conversation(hub, chat_id, include_archived, local)
    lines = ['# ' + data['chat']['name'], '']
    agents = hub.agents()
    for item in data['messages']:
        who = 'You' if item['role'] == 'user' else _redact_text(
            str(agents.get(item['agent_id'], {}).get('name', 'Hub')), local)
        stamp = time.strftime('%Y-%m-%d %H:%M', time.localtime(item['created']))
        model = ' · ' + item['model'] if item.get('model') else ''
        lines += ['## ' + who + ' · ' + stamp + model, '', item['text'], '']
        for card in item.get('cards', []):
            lines += ['Card: ' + str(card.get('title') or ''),
                      str(card.get('text') or ''),
                      'Decision: ' + str(card['decision']) if card.get('decision') else 'Decision: pending']
            media = card.get('media')
            if media:
                lines.append('Card media: ' + str(media.get('name') or media.get('path') or ''))
            lines.append('')
        for attachment in item.get('attachments', []):
            lines.append('Attachment: ' + attachment['name'] + ' (' + attachment['path'] + ')')
        if item.get('attachments'): lines.append('')
    lines += ['', _redaction_note(local), '']
    _merge_counts(counts, local)
    return '\n'.join(lines).encode('utf-8')


def json_chat(hub, chat_id, include_archived=False, counts=None):
    local = {}
    data = conversation(hub, chat_id, include_archived, local)
    data['export_redactions'] = dict(local)
    _merge_counts(counts, local)
    return json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')


def everything(hub):
    stream = io.BytesIO()
    exclusions = []
    counts = {}
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        with hub.lock:
            hub.sync_chats()
            chats = [dict(row) for row in hub.db.execute('SELECT id,name FROM chats ORDER BY id')]
        for chat in chats:
            cid = chat['id']
            safe = ''.join(c if c.isalnum() or c in '_-' else '_' for c in cid)
            archive.writestr('chats/' + safe + '.md', markdown_chat(hub, cid, True, counts))
            archive.writestr('chats/' + safe + '.json', json_chat(hub, cid, True, counts))
        agents = hub.agents()
        # public_agent is an API view and includes live instruction text. Export
        # metadata only; instruction files below are screened separately.
        archive.writestr('agents.json', json.dumps(_redact_tree([
            {key: value for key, value in hub.public_agent(a).items()
             if key not in ('role', 'instructions')} for a in agents.values()
        ], counts), ensure_ascii=False, indent=2))
        for folder in listdir(hub.create_dir):
            if folder.is_symlink() or not folder.is_dir() or not ((folder / 'CLAUDE.md').is_file() or (folder / 'AGENTS.md').is_file()): continue
            aid = folder.name
            agent = agents.get(aid)
            if agent is None:
                avatar = folder / 'avatar.json'
                try: agent = json.loads(read_text(avatar, limit=1024 * 1024))
                except (OSError, ValueError, UnicodeError): agent = {}
            for name in ('CLAUDE.md', 'AGENTS.md', 'NOTES.md'):
                path = folder / name
                if path.is_file() and not path.is_symlink():
                    safe = _safe_instruction_bytes(path, counts)
                    destination = 'agents/' + aid + '/' + name
                    if safe is None:
                        exclusions.append(destination)
                    else:
                        archive.writestr(destination, safe)
            public_meta = {key: agent.get(key) for key in
                           ('id', 'name', 'emoji', 'engine', 'model', 'title', 'workdir',
                            'use_global_rules', 'chrome', 'draft_only')}
            archive.writestr('agents/' + aid + '/avatar.json', json.dumps(_redact_tree(public_meta, counts), ensure_ascii=False, indent=2))
        safe_settings = {key: hub.config.get(key) for key in
                         ('default_engine', 'default_model', 'default_codex_model', 'role_models', 'route_timeout')}
        archive.writestr('settings.json', json.dumps(_redact_tree(safe_settings, counts), ensure_ascii=False, indent=2))
        if hasattr(hub, 'routines'):
            archive.writestr('schedules.json', json.dumps(_redact_tree(hub.routines(), counts), ensure_ascii=False, indent=2))
        archive.writestr('README.md', '# Agent Hub export\n\n'
                         'Exports include your chat text. Review before sharing — we redact obvious secrets but can\'t catch everything.\n\n'
                         'Readable agent instructions and notes are screened and redacted in place. '
                         'Authentication and token files are never included.\n\n'
                         + _redaction_note(counts) + '\n'
                         'Counts cover occurrences across all included files and formats.\n\n'
                         'Excluded files:\n' +
                         ('\n'.join('- ' + path for path in exclusions) if exclusions else '- None') + '\n')
    return stream.getvalue()
