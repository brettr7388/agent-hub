"""Conversation routing and compact, server-side emoji validation."""
from hub_security import allowed_agent_environment
import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path
from hub_process import run_bounded
from hub_fs import open_file

_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = {'the', 'and', 'for', 'you', 'your', 'with', 'this', 'that', 'from', 'have', 'what', 'will', 'about', 'into', 'please', 'help', 'agent', 'assistant'}


def valid_emoji(value):
    if not isinstance(value, str) or not value or len(value.encode('utf-8')) > 64 or len(value) > 24:
        return False
    if any(unicodedata.category(ch)[0] == 'C' and ch != '\u200d' for ch in value):
        return False
    # One grapheme: a base emoji, optionally with variation/skin tone, ZWJ joined
    # emoji, a flag pair, or a keycap. Reject words and multiple unjoined emoji.
    if re.fullmatch(r'[0-9#*]\ufe0f?\u20e3', value): return True
    if len(value) == 2 and all(0x1f1e6 <= ord(ch) <= 0x1f1ff for ch in value): return True
    parts = value.split('\u200d')
    for part in parts:
        if not part: return False
        base = part[0]
        cp = ord(base)
        if not (0x1f000 <= cp <= 0x1faff or 0x2600 <= cp <= 0x27bf or base in '©®™❤♥☺☹⚙✳☑'):
            return False
        suffix = part[1:]
        if suffix and suffix[0] in ('\ufe0e', '\ufe0f'): suffix = suffix[1:]
        if suffix and 0x1f3fb <= ord(suffix[0]) <= 0x1f3ff: suffix = suffix[1:]
        if suffix: return False
    return True


_INTENTS = {
    'writing': ({'write', 'writing', 'tagline', 'copy', 'caption', 'edit', 'draft', 'headline'},
                {'writer', 'writing', 'copywriter', 'editor', 'content', 'marketing'}),
    'coding': ({'fix', 'bug', 'code', 'error', 'function', 'stack', 'trace', 'debug', 'python'},
               {'coder', 'coding', 'developer', 'engineer', 'programmer', 'software'}),
    'research': ({'research', 'find', 'compare', 'source', 'sources', 'investigate', 'study'},
                 {'researcher', 'research', 'analyst', 'investigator'}),
}


def role_words(agent):
    text = ' '.join((agent.get('name', ''), agent.get('title', ''), agent.get('role', '')))
    try:
        path = Path(agent['path']) / 'CLAUDE.md'
        with open_file(path, 'rb') as stream:
            text += ' ' + stream.read(32000).decode('utf-8', 'replace')[:8000]
    except (KeyError, OSError):
        pass
    return set(_WORD.findall(text.lower())) - _STOP


def pick_by_keywords(agents, members, message, last_agent=None):
    """Return a unique best match, or None so the caller can classify a real tie."""
    words = set(_WORD.findall(message.lower())) - _STOP
    profiles = {aid: role_words(agents[aid]) for aid in members}
    frequency = {word: sum(word in profile for profile in profiles.values()) for word in words}
    scores = {}
    for aid in members:
        agent = agents[aid]
        heading = set(_WORD.findall(' '.join(str(agent.get(k, '')) for k in ('name', 'title', 'role')).lower()))
        score = sum((4 if word in heading else 1) / max(1, frequency[word])
                    for word in words if word in profiles[aid])
        for triggers, roles in _INTENTS.values():
            if words & triggers and profiles[aid] & roles:
                score += 6 + len(words & triggers)
        scores[aid] = score
    high = max(scores.values(), default=0)
    candidates = [aid for aid in members if scores[aid] == high]
    if len(candidates) == 1: return candidates[0]
    return None


def cli_choice(config, members, message, profiles=None, hub=None):
    """Single cheap classification turn, with no session and a short hard deadline."""
    if hub is None:
        return None  # An unisolated classifier must never see a user's question.
    profiles = profiles or {}
    names = '; '.join(aid + ' (' + str(profiles.get(aid, {}).get('name') or aid)[:60] + ': ' +
                      str(profiles.get(aid, {}).get('title') or '')[:80] + ' ' +
                      str(profiles.get(aid, {}).get('role') or '')[:180] + ')'
                      for aid in members)
    prompt = 'Choose exactly one agent ID from: ' + names + '. Reply with the ID only. User question: ' + message[:500]
    engine = config.get('classifier_engine', config.get('default_engine', 'claude'))
    model = config.get('classifier_model') or ('haiku' if engine == 'claude' else config.get('default_codex_model', 'gpt-6.1-sol'))
    timeout = max(1, min(120, float(config.get('route_timeout', config.get('classifier_timeout', 15)))))
    # This Codex CLI cannot prove a no-tools invocation: even disabling its
    # shell feature leaves unified_exec enabled. Keep the question local and
    # let the caller use its deterministic tie fallback.
    if engine == 'codex':
        return None
    try:
        binary = os.path.expanduser(config.get('claude_bin', 'claude'))
        env = allowed_agent_environment()
        flags = hub.isolation_flags(engine, binary)
        args = [binary, '-p', prompt, '--output-format', 'json', '--model', model,
                '--permission-mode', 'plan', *flags, '--strict-mcp-config', '--tools', '']
        got = run_bounded(args, timeout=timeout, stdout_limit=65536, stderr_limit=65536,
                          env=env, cwd=str(hub.data))
        if got.returncode: return None
        output = got.stdout.strip()
        try: output = json.loads(output).get('result', '')
        except (ValueError, AttributeError): pass
        answer = output.strip().lower()
        return answer if answer in members else None
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError):
        return None
