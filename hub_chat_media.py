"""Narrow, message-bound access to images in a Pip's working folder."""
from pathlib import Path
from urllib.parse import quote
import os
import re

from hub_security import validate_safe_workdir, open_validated_file

IMAGE_SUFFIXES = frozenset(('.png', '.jpg', '.jpeg', '.gif', '.webp'))
PRIVATE_PARTS = frozenset(('.claude', '.git', '.ssh', '.aws', '.config', '.codex',
                           '.gnupg', '.kube', '.local', '.npm', '.docker', 'Library', 'Keychains'))
PRIVATE_PARTS_CASEFOLD = frozenset(part.casefold() for part in PRIVATE_PARTS)
FILE_REFERENCE = re.compile(
    r'(?<!\w)FILE:[ \t]*([^\r\n]*?\.(?:png|jpe?g|gif|webp|mp4|mov|m4v|webm))'
    r'(?=$|[\s),.;!?])', re.I | re.M)


def default_agent_folder(hub, aid):
    """The one outside-home workdir exception, owned by this Hub-created Pip."""
    agent = hub.agents().get(aid)
    if not agent or agent.get('external') or agent.get('linked'):
        return None
    expected = hub.create_dir / aid
    actual = Path(agent['path'])
    if actual != expected or actual.is_symlink() or not actual.is_dir():
        return None
    return actual


def validate_agent_workdir(hub, raw, aid):
    """Allow saving the Pip's exact default folder; keep all other home rules."""
    from hub_guide import validate_workdir
    from hub import HubError
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 4096 or '\x00' in raw:
        raise HubError(400, 'Choose a working folder.')
    candidate = hub.path(raw.strip())
    owned = default_agent_folder(hub, aid)
    if owned is not None and candidate == owned:
        return owned
    return validate_workdir(hub, raw, allow_empty=False)


def workdir_for_message(hub, cid, message):
    """Return a validated root only for this assistant message's current Pip."""
    if message['chat_id'] != cid or message['role'] != 'assistant':
        return None
    chat = hub.chat(cid)
    aid = message['agent_id']
    if aid not in chat['agents']:
        return None
    agent = hub.agents().get(aid)
    if not agent:
        return None
    raw = agent.get('workdir')
    owned = default_agent_folder(hub, aid)
    if owned is not None and hub.path(raw) == owned:
        return owned
    try:
        return validate_safe_workdir(hub.path(raw))
    except (ValueError, OSError):
        return None


def file_references(text):
    """Find explicit FILE markers, including those embedded in a sentence."""
    matches = list(FILE_REFERENCE.finditer(text or ''))
    for match in matches:
        raw = match.group(1).strip()
        if raw:
            yield raw, match.start(), match.end()
    # Standalone markers still accept other downloadable outputs such as PDFs.
    for match in re.finditer(r'^\s*FILE:[ \t]*(.+?)[ \t]*$', text or '', re.M):
        if not any(start.start() >= match.start() and start.end() <= match.end() for start in matches):
            yield match.group(1).strip(), match.start(), match.end()


def referenced_paths(text):
    """Only an explicit FILE marker authorizes a workdir image preview."""
    return {raw for raw, _, _ in file_references(text)}


def image_info(hub, cid, message, raw):
    """Validate reference, root, and pinned open; return metadata or None."""
    if not isinstance(raw, str) or not raw or '\x00' in raw or '..' in Path(raw).parts:
        return None
    if raw not in referenced_paths(message['text']):
        return None
    root = workdir_for_message(hub, cid, message)
    if root is None:
        return None
    path = hub.path(raw) if Path(raw).expanduser().is_absolute() else root / raw
    if path.suffix.lower() not in IMAGE_SUFFIXES or path == root:
        return None
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    if any(part.startswith('.') or part.casefold() in PRIVATE_PARTS_CASEFOLD
           for part in relative.parts):
        return None
    from hub import HubError
    try:
        with open_validated_file(path, [root]) as stream:
            size = os.fstat(stream.fileno()).st_size
    except (HubError, OSError, ValueError):
        return None
    return {'path': str(path), 'name': path.name, 'size': size, 'kind': 'image',
            'url': '/api/file?chat_id=' + quote(cid, safe='') + '&message_id=' +
                   str(message['id']) + '&path=' + quote(raw, safe='')}


def unavailable_image(raw):
    name = Path(raw).name if isinstance(raw, str) else 'image'
    return {'name': name or 'image', 'kind': 'unavailable', 'unavailable': True,
            'reason': 'Image unavailable'}
