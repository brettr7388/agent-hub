"""Strict handoff markers; ordinary quoted text never routes work."""
import re


def parse_handoff(answer):
    """Accept one final top-level @@handoff target: task line only.

    All code fences (including handoff fences), Markdown blockquotes and indented
    code are data. Choosing just one explicit syntax keeps parsing fail-closed.
    """
    fence = None
    candidate = None
    quoted = False
    lines = answer.rstrip().splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            quoted = False
        if line.lstrip().startswith('>'):
            quoted = True
            continue
        if quoted:
            continue
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if match:
            token = match.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not match.group(2).strip():
                fence = None
            continue
        if fence is not None or index != len(lines) - 1:
            continue
        match = re.fullmatch(r'@@handoff ([a-zA-Z0-9_-]{1,64}): ([^\x00-\x1f\x7f]{1,4000})', line)
        if match and match.group(2).strip():
            candidate = (match.group(1).lower(), match.group(2).strip())
    return candidate


def strip_handoff_marker(answer):
    """Remove the final routing instruction from text shown to people or other Pips."""
    if not parse_handoff(answer):
        return answer
    return '\n'.join(answer.rstrip().splitlines()[:-1]).rstrip()
