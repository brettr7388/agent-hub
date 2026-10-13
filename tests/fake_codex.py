#!/usr/bin/env python3
"""Deterministic Codex exec stand-in; never contacts a model."""
import json
import os
from pathlib import Path
import sys
import time

args = sys.argv[1:]
if args == ['features', 'list']:
    print('skip_host_skill_discovery under development false')
    sys.exit(0)
if '--help' in args:
    print('Fake Codex --ignore-user-config --ignore-rules --config')
    sys.exit(0)
if len(args) >= 2 and args[1] == 'resume' and any(flag in args for flag in ('-C', '-s', '--skip-git-repo-check', '--model')):
    print('Unsupported resume option', file=sys.stderr)
    sys.exit(2)
cwd = Path.cwd()
config = Path(os.environ['CODEX_HOME']) / 'config.toml' if os.environ.get('CODEX_HOME') else None
with (cwd / 'fake_codex_calls.jsonl').open('a', encoding='utf-8') as f:
    f.write(json.dumps({'argv': args, 'cwd': str(cwd), 'codex_home': os.environ.get('CODEX_HOME'),
                        'home': os.environ.get('HOME'),
                        'config': config.read_text() if config and config.is_file() else None}) + '\n')
number = len((cwd / 'fake_codex_calls.jsonl').read_text().splitlines())
try: choices = json.loads((cwd / 'fake_codex_responses.json').read_text())
except FileNotFoundError: choices = []
choice = choices[min(number - 1, len(choices) - 1)] if choices else {}
if 'mutate_config' in choice:
    config.write_text(choice['mutate_config'])
time.sleep(choice.get('sleep', 0))
if choice.get('exit'):
    print(choice.get('stderr', 'fake failure'), file=sys.stderr)
    sys.exit(choice['exit'])
thread = choice.get('thread_id', 'codex-thread-' + str(number))
answer = choice.get('result', 'codex: ' + args[-1].split('Owner request:\n')[-1])
print(json.dumps({'type': 'thread.started', 'thread_id': thread}), flush=True)
partial = ''
for chunk in choice.get('stream', [answer]):
    partial += str(chunk)
    print(json.dumps({'type': 'item.updated', 'item': {'id': 'answer-1', 'type': 'agent_message', 'text': partial}}), flush=True)
    time.sleep(choice.get('stream_delay', 0))
if choice.get('stream_exit'):
    print(choice.get('stderr', 'failure after partial answer'), file=sys.stderr)
    sys.exit(choice['stream_exit'])
if choice.get('is_error'):
    print(json.dumps({'type': 'turn.failed', 'error': {'message': 'fake stream failed'}}), flush=True)
    sys.exit(0)
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': answer}}), flush=True)
if '-o' in args and not choice.get('missing_output'):
    Path(args[args.index('-o') + 1]).write_text(choice.get('last', answer), encoding='utf-8')
