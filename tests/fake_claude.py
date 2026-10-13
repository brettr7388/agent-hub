#!/usr/bin/env python3
"""Deterministic Claude CLI stand-in. Reads responses.json and logs calls in cwd."""
import json
import os
from pathlib import Path
import sys
import time

if '--help' in sys.argv:
    print('Fake Claude --safe-mode --setting-sources --append-system-prompt --include-partial-messages')
    print('--permission-mode <mode> Permission mode (choices: "acceptEdits", "auto", "default", "plan")')
    sys.exit(0)

cwd = Path.cwd()
log = cwd / 'fake_calls.jsonl'
args = sys.argv[1:]
prompt = args[args.index('-p') + 1]
attached = prompt.split('Attached local files:\n', 1)[-1].split('\n\n', 1)[0].splitlines() if 'Attached local files:\n' in prompt else []
upload_dir = Path(args[args.index('--add-dir') + 1]) if '--add-dir' in args else None
uploaded_reads = {}
for raw in attached:
    path = Path(raw)
    if upload_dir and path.parent == upload_dir:
        uploaded_reads[raw] = path.read_bytes().hex()
with log.open('a', encoding='utf-8') as f:
    f.write(json.dumps({'argv': args, 'cwd': str(cwd), 'uploaded_reads': uploaded_reads}) + '\n')
calls = log.read_text(encoding='utf-8').splitlines()
try:
    choices = json.loads((cwd / 'fake_responses.json').read_text(encoding='utf-8'))
except FileNotFoundError:
    choices = []
choice = choices[min(len(calls)-1, len(choices)-1)] if choices else {}
time.sleep(choice.get('sleep', 0))
if choice.get('exit'):
    print(choice.get('stderr', 'fake failure'), file=sys.stderr)
    sys.exit(choice['exit'])
if choice.get('invalid_json'):
    print('{bad json')
    sys.exit(0)
answer = choice.get('result', ''.join(map(str, choice['stream'])) if 'stream' in choice
                    else 'echo: ' + sys.argv[sys.argv.index('-p')+1])
print(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 'init-session'}), flush=True)
print(json.dumps({'type': 'stream_event', 'event': {'type': 'message_start'}}), flush=True)
for event in choice.get('events', []):
    print(json.dumps(event), flush=True)
for chunk in choice.get('stream', [answer]):
    print(json.dumps({'type': 'stream_event', 'event': {'type': 'content_block_delta',
        'delta': {'type': 'text_delta', 'text': str(chunk)}}}), flush=True)
    time.sleep(choice.get('stream_delay', 0))
if choice.get('stream_exit'):
    print(choice.get('stderr', 'failure after partial answer'), file=sys.stderr)
    sys.exit(choice['stream_exit'])
print(json.dumps({'type': 'result', 'result': answer,
    'session_id': choice.get('session_id', 'fake-' + str(len(calls))),
    'is_error': choice.get('is_error', False)}), flush=True)
