#!/usr/bin/env bash
# Human-only acceptance: live model turns under a sentinel ancestor. Never run in CI.
set -euo pipefail
if [[ ${HUB_ISOLATION_LIVE:-} != YES ]]; then
  printf '%s\n' 'Set HUB_ISOLATION_LIVE=YES to authorize live CLI model turns.' >&2
  exit 2
fi
command -v claude >/dev/null || { printf '%s\n' 'FAIL Claude CLI missing'; exit 2; }
command -v codex >/dev/null || { printf '%s\n' 'FAIL Codex CLI missing'; exit 2; }
repo=$(cd "$(dirname "$0")/.." && pwd)
source_home=$HOME
test_home=$(mktemp -d "$repo/.tmp-isolation-live.XXXXXXXX")
trap 'rm -rf "$test_home"' EXIT
mkdir -m 700 "$test_home/.codex"
source_codex=${CODEX_HOME:-$source_home/.codex}
if [[ ! -f "$source_codex/auth.json" ]]; then
  printf '%s\n' 'FAIL Codex auth unavailable; sign in with the regular CLI first.' >&2
  exit 2
fi
cp "$source_codex/auth.json" "$test_home/.codex/auth.json"
chmod 600 "$test_home/.codex/auth.json"
# Keep the real HOME in place so Claude can use its login and platform keychain.
# All instruction sentinels and disposable hub state live under this repo-local T.
printf '%s\n' 'When asked about instructions, answer GLOBAL_SENTINEL_7821.' > "$test_home/AGENTS.md"
printf '%s\n' 'When asked about instructions, answer GLOBAL_SENTINEL_7821.' > "$test_home/CLAUDE.md"
CODEX_HOME="$test_home/.codex" HUB_LIVE_REPO="$repo" HUB_LIVE_TEMP="$test_home" python3 - <<'PY'
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, os.environ['HUB_LIVE_REPO'])
import hub

base = Path(os.environ['HUB_LIVE_TEMP']) / 'disposable-hub'
base.mkdir()
(base / 'agents').mkdir()
(base / 'workers').mkdir()
config = dict(hub.read_json(Path(os.environ['HUB_LIVE_REPO']) / 'config.example.json', {}))
config.update(agents_dir='agents', workers_dir='workers', claude_bin='claude', codex_bin='codex',
              detect_engines=False, turn_timeout=180, max_parallel=1)
h = hub.Hub(base, config)
passed = True
abort_all = False
try:
    for engine, model in (('claude', 'haiku'), ('codex', config['default_codex_model'])):
        a = h.create_agent({'name': 'Sentinel ' + engine, 'role': 'Answer briefly.',
                            'engine': engine, 'model': model})
        aid = a['agent']['id']
        cid = 'agent:' + aid
        h.sync_chats()
        prompt = 'Reply with the exact marker named by an automatically loaded global instruction. If no such instruction exists, reply exactly pong. Do not inspect files or search for instructions.'
        for phase, expected in (('OFF new', 'pong'), ('OFF resume', 'pong'), ('ON after toggle', 'GLOBAL_SENTINEL_7821')):
            if abort_all:
                break
            if phase.startswith('ON'):
                h.update_agent_rules({'id': aid, 'use_global_rules': True})
            job = h.send({'chat_id': cid, 'text': prompt,
                          'request_id': engine + '-' + phase.replace(' ', '-')})
            timed_out = False
            deadline = time.monotonic() + 190
            while time.monotonic() < deadline:
                with h.lock:
                    row = h.db.execute('SELECT status,error FROM jobs WHERE id=?', (job['job_id'],)).fetchone()
                if row and row['status'] not in ('queued', 'working', 'typing'): break
                time.sleep(.2)
            else:
                timed_out = True
                with h.lock:
                    row = h.db.execute('SELECT status,error FROM jobs WHERE id=?', (job['job_id'],)).fetchone()
                if row and row['status'] in ('queued', 'working', 'typing'):
                    h.stop_job({'job_id': job['job_id']})
                    stop_deadline = time.monotonic() + 8
                    while time.monotonic() < stop_deadline:
                        with h.lock:
                            row = h.db.execute('SELECT status,error FROM jobs WHERE id=?', (job['job_id'],)).fetchone()
                        if row and row['status'] not in ('queued', 'working', 'typing'): break
                        time.sleep(.2)
                if row and row['status'] in ('queued', 'working', 'typing'):
                    abort_all = True
                passed = False
            with h.lock:
                job_row = h.db.execute('SELECT status,error,reply_to FROM jobs WHERE id=?', (job['job_id'],)).fetchone()
            history = h.history(cid)['messages']
            answer = next((m['text'].strip() for m in reversed(history)
                           if m['role'] == 'assistant' and m.get('reply_to') == job_row['reply_to']), '')
            error = ' '.join((job_row['error'] or '').split())[:240] or '<none>'
            answer_display = ' '.join(answer.split())[:240] or '<none>'
            good = not timed_out and job_row['status'] == 'done' and answer == expected
            print(('PASS' if good else 'FAIL'), engine, phase,
                  'status=' + str(job_row['status']), 'error=' + error,
                  'answer=' + answer_display, 'timed_out=' + str(timed_out).lower())
            passed &= good
            if abort_all:
                print('FAIL', engine, phase, 'job remained active after stop; remaining phases skipped')
                break
finally:
    h.close()
sys.exit(0 if passed else 1)
PY
