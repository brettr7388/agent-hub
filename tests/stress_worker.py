"""Subprocess stress harness: a segfault must fail the parent unittest."""
import faulthandler
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hub import Hub, ROOT


def main():
    faulthandler.enable()
    scratch = ROOT / 'data' / 'test-runs'
    scratch.mkdir(parents=True, exist_ok=True)
    # Keep each run isolated and ensure all test state is removed on failure too.
    with tempfile.TemporaryDirectory(prefix='hub-stress-', dir=scratch) as directory, \
            mock.patch('pathlib.Path.home', return_value=Path(directory)), \
            mock.patch.dict(os.environ, {'HOME': directory}):
        h = Hub(directory, {'agents_dir': 'agents', 'workers_dir': 'workers',
                           'claude_bin': str(Path(__file__).with_name('fake_claude.py')),
                           'default_engine': 'claude', 'max_parallel': 6, 'turn_timeout': 10,
                           'launch_agents_dir': str(Path(directory) / 'no-external-jobs')})
        for n in range(4): h.create_agent({'name': 'Agent ' + str(n), 'role': 'Return a short answer.'})
        h.sync_chats()
        token = h.initial_token
        cookie = h.login(token, 'local')
        errors, counts = queue.Queue(), [0] * 20
        timing = {}
        def begin_workload():
            timing['start'] = time.monotonic()

        barrier = threading.Barrier(21, action=begin_workload, timeout=15)
        stop = threading.Event()
        h.start_scheduler()
        try:
            swarm = h.create_swarm({'goal': 'Each give one useful fact.', 'count': 2})
            h.create_routine({'name': 'Stress schedule', 'agent_id': 'agent-3', 'prompt': 'ping',
                             'trigger': 'interval', 'minutes': 5})
        except BaseException:
            h.close()
            raise

        def worker(index):
            events = queue.Queue(maxsize=128)
            with h.lock: h.subscribers.add(events)
            try:
                barrier.wait()
                while not stop.is_set():
                    counts[index] += 1
                    cid = 'agent:agent-' + str(index % 4)
                    if index < 3:
                        result = h.send({'chat_id': cid, 'text': 'ping',
                                         'request_id': 'stress-%s-%s' % (index, counts[index])})
                        while not stop.is_set():
                            status = h.db.execute('SELECT status FROM jobs WHERE id=?', (result['job_id'],)).fetchone()[0]
                            if status not in ('queued', 'working', 'typing'): break
                            # Status events wake the worker; timeout bounds a lost event.
                            try: events.get(timeout=.25)
                            except queue.Empty: pass
                    elif index % 6 == 0:
                        h.login(token, 'shared-proxy')
                        assert h.authenticated(cookie)
                    elif index % 6 == 1:
                        h.state(); h.product_state()
                    elif index % 6 == 2:
                        h.history(cid); h.workers()
                    elif index % 6 == 3:
                        h.product_action({'action': 'pin' if counts[index] % 2 else 'unpin', 'chat_id': cid})
                        h.product_action({'action': 'mark_read', 'chat_id': cid})
                    elif index % 6 == 4:
                        h.sync_chats(); h.agents(); h.swarms(); h.swarm_tick()
                    else:
                        h.jobs_board(); h.routines(); h.tick_routines()
                    # SSE-style cookie validation, event drain, state reconciliation.
                    assert h.authenticated(cookie)
                    try: events.get_nowait()
                    except queue.Empty: pass
                    # Small cooperative yield keeps this stress run focused on
                    # concurrent Hub work rather than busy-spinning Python loops.
                    stop.wait(.005)
            except BaseException as error:
                errors.put(repr(error))
            finally:
                with h.lock: h.subscribers.discard(events)

        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(20)]
        for thread in threads: thread.start()
        try:
            barrier.wait()
            stop.wait(60)
        finally:
            stop.set()
            join_deadline = time.monotonic() + 15
            for thread in threads:
                thread.join(timeout=max(0, join_deadline - time.monotonic()))
            # If a worker is blocked in Hub work, stop runner threads before
            # the final bounded join and before any database restart.
            if any(thread.is_alive() for thread in threads):
                h.close()
                join_deadline = time.monotonic() + 15
                for thread in threads:
                    thread.join(timeout=max(0, join_deadline - time.monotonic()))
            else:
                h.close()
        # Stop runner threads before integrity/restart checks; preserve queued work.
        assert all(not t.is_alive() for t in threads), 'stress thread stalled'
        assert all(not thread.is_alive() for thread in h.threads), 'Hub runner thread stalled'
        assert errors.empty(), list(errors.queue)
        assert all(n > 0 for n in counts), counts
        start = timing['start']
        assert time.monotonic() - start >= 60
        old_h = h
        h = None
        try:
            h = Hub(directory, old_h.config)
            assert h.db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert not h.db.execute('PRAGMA foreign_key_check').fetchall()
            assert h.authenticated(cookie), 'cookie lost after restart'
            assert h.login(token, 'local'), 'saved token failed after restart'
            failures = [dict(r) for r in h.db.execute("SELECT id,error FROM jobs WHERE status='error'")]
            assert not failures, failures
            assert h.swarm(swarm['id'])['status'] == 'done'
        finally:
            if h is not None:
                h.close()
        print(json.dumps({'threads': 20, 'seconds': round(time.monotonic() - start, 1),
                          'operations': sum(counts), 'integrity': 'ok', 'restart_login': 'ok'}))


if __name__ == '__main__': main()
