"""Use observed CLI action events to word stopped-turn notices accurately."""

CODEX_ACTION_ITEMS = frozenset(('command_execution', 'mcp_tool_call', 'file_change'))


def action_observed(engine, event):
    """Recognize action events, never infer action from answer or prompt prose."""
    if not isinstance(event, dict):
        return False
    if engine == 'claude':
        stream = event.get('event') if event.get('type') == 'stream_event' else event
        if isinstance(stream, dict) and stream.get('type') == 'content_block_start':
            block = stream.get('content_block')
            if isinstance(block, dict) and block.get('type') == 'tool_use':
                return True
        if event.get('type') == 'assistant':
            message = event.get('message')
            content = message.get('content') if isinstance(message, dict) else None
            return isinstance(content, list) and any(
                isinstance(part, dict) and part.get('type') == 'tool_use' for part in content)
    elif engine == 'codex' and event.get('type') in ('item.started', 'item.completed'):
        item = event.get('item')
        return isinstance(item, dict) and item.get('type') in CODEX_ACTION_ITEMS
    return False


def stopped_notice(server_stopped, action_seen):
    if server_stopped:
        return ('Server stopped; inspect any side effects before retrying. No automatic replay.'
                if action_seen else 'Server stopped. No automatic replay.')
    return ('Turn stopped; verify any side effects before retrying. No automatic replay.'
            if action_seen else 'Turn stopped. No automatic replay.')
