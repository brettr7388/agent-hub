"""Drain both CLI pipes without blocking SSE progress or timeout supervision."""
import json
from hub_process import collect_process


def collect_output(proc, timeout, engine, on_text):
    answer = ['']

    def stdout_line(line):
        try: event = json.loads(line)
        except ValueError: return
        if not isinstance(event, dict): return
        text = None
        if engine == 'claude':
            stream = event.get('event', {}) if event.get('type') == 'stream_event' else event
            if not isinstance(stream, dict): return
            if stream.get('type') == 'message_start':
                text = ''
            if stream.get('type') == 'content_block_delta':
                delta = stream.get('delta') or {}
                if isinstance(delta, dict) and delta.get('type') == 'text_delta':
                    text = answer[0] + str(delta.get('text') or '')
            if event.get('type') == 'assistant':
                message = event.get('message') or {}
                content = message.get('content', []) if isinstance(message, dict) else []
                if isinstance(content, list):
                    parts = [part['text'] for part in content if isinstance(part, dict)
                             and part.get('type') == 'text' and isinstance(part.get('text'), str)]
                    if parts: text = ''.join(parts)
            if event.get('type') == 'result' and not event.get('is_error'):
                text = str(event.get('result') or '')
        else:
            item = event.get('item') or {}
            if isinstance(item, dict) and event.get('type') in ('item.updated', 'item.completed') and item.get('type') == 'agent_message':
                text = str(item.get('text') or '')
        if text is not None and text != answer[0]:
            answer[0] = text
            on_text(text)

    stdout, stderr = collect_process(proc, timeout=timeout,
                                     stdout_limit=8 * 1024 * 1024,
                                     stderr_limit=256 * 1024,
                                     on_stdout_line=stdout_line)
    return stdout.decode('utf-8', 'replace'), stderr.decode('utf-8', 'replace')


def claude_result(stdout):
    """Accept real stream-json results and legacy/fake single JSON results."""
    for line in reversed(stdout.splitlines()):
        try: item = json.loads(line)
        except ValueError: continue
        if isinstance(item, dict) and ('result' in item or item.get('type') == 'result'):
            return item
    raise ValueError('No final Claude result')
