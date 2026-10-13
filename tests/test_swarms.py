"""Swarm contract checks with fake CLI output and temporary Git checkouts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hub
import hub_swarms

FAKE = Path(__file__).with_name('fake_claude.py').resolve()


class SwarmCase(unittest.TestCase):
    def setUp(self):
        scratch = hub.ROOT / 'data' / 'test-runs'
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=str(scratch))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        home_patch = mock.patch('pathlib.Path.home', return_value=self.root)
        home_patch.start()
        self.addCleanup(home_patch.stop)
        # Stop Git discovery at this disposable fixture, away from the host checkout.
        (self.root / '.git').write_text('gitdir: nonexistent\n')
        (self.root / 'agents').mkdir()
        (self.root / 'workers').mkdir()
        self.config = {'agents_dir': 'agents', 'workers_dir': 'workers', 'claude_bin': str(FAKE),
                       'default_model': 'haiku', 'max_parallel': 8, 'turn_timeout': 3,
                       'max_upload_bytes': 10000, 'media_allowlist': [], 'chrome_agents': [],
                       'allowed_origins': []}
        self.h = hub.Hub(self.root, self.config)
        self.addCleanup(self.h.close)
        self.work = self.root / 'work'
        self.work.mkdir()

    def finished(self, sid, timeout=6):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            got = self.h.swarm(sid)
            if got['status'] in ('done', 'gap'): return got
            time.sleep(.02)
        self.fail('swarm did not finish')

    def test_git_output_caps_apply_to_text_and_raw_status_calls(self):
        fake_bin = self.root / 'fake-bin'
        fake_bin.mkdir()
        fake_git = fake_bin / 'git'
        for stream, size in (('stdout', 1024 * 1024 + 1), ('stderr', 64 * 1024 + 1)):
            fake_git.write_text('#!/bin/sh\n/usr/bin/head -c ' + str(size) + ' /dev/zero' +
                                (' >&2' if stream == 'stderr' else '') + '\n')
            fake_git.chmod(0o700)
            with mock.patch.object(hub_swarms, 'allowed_agent_environment',
                                   return_value={'PATH': str(fake_bin)}):
                with self.subTest(stream=stream), self.assertRaises(hub.HubError) as error:
                    self.h._git(self.work, 'status')
                self.assertEqual(error.exception.status, 409)
                with self.subTest(stream=stream, raw=True), self.assertRaises(hub.HubError) as error:
                    self.h._worktree_dirty(self.work)
                self.assertEqual(error.exception.status, 409)

    def test_partition_and_roles_report_evidence(self):
        for shape in ('partition', 'roles'):
            made = self.h.create_swarm({'goal': 'Inspect the project', 'shape': shape,
                'working_dir': str(self.work), 'workers': [
                    {'role': 'Researcher', 'slice': 'Find facts'},
                    {'role': 'Reviewer', 'slice': 'Check facts'}]})
            done = self.finished(made['id'])
            self.assertEqual(done['shape'], shape)
            self.assertEqual(len(done['workers']), 2)
            self.assertEqual(len({w['agent_id'] for w in done['workers']}), 2)
            self.assertTrue(all(w['status'] == 'issues' for w in done['workers']))  # echo lacks evidence
            self.assertTrue(all(w['job_id'] for w in done['workers']))
            self.assertEqual(self.h.chat(done['chat_id'])['type'], 'group')
            for w in done['workers']:
                self.assertIn(w['agent_id'], self.h.agents())

    def test_source_group_posts_result_card_and_hides_execution_group(self):
        for name in ('Ada', 'Bea'):
            self.h.create_agent({'name': name, 'role': 'Help with tasks.', 'engine': 'claude', 'model': 'haiku'})
        source = self.h.group({'name': 'Project', 'agents': ['ada', 'bea']})['chat']['id']
        made = self.h.create_swarm({'goal': 'Inspect the project', 'shape': 'partition',
            'chat_id': source, 'working_dir': str(self.work), 'workers': [
                {'source_agent_id': 'ada', 'role': 'Ada', 'slice': 'First part'},
                {'source_agent_id': 'bea', 'role': 'Bea', 'slice': 'Second part'}]})
        done = self.finished(made['id'])
        self.assertEqual(done['chat_id'], source)
        self.assertEqual(done['worker_chat_id'], 'group:swarm-' + done['id'])
        self.assertNotIn(done['worker_chat_id'], [c['id'] for c in self.h.state()['chats']])
        self.assertIn(source, [c['id'] for c in self.h.state()['chats']])
        messages = self.h.history(source)['messages']
        self.assertEqual(len(messages), 1)
        card = messages[0]['cards'][0]
        self.assertEqual(card['kind'], 'team_task')
        self.assertEqual(card['swarm_id'], made['id'])
        self.assertEqual(card['status'], 'done')
        self.assertTrue(card['summary'])
        self.assertEqual([w['source_agent_id'] for w in card['workers']], ['ada', 'bea'])
        self.assertTrue(all(w['answer'] for w in card['workers']))
        self.assertEqual(len(self.h.history(done['worker_chat_id'])['messages']), 4)
        message_id = messages[0]['id']
        with self.assertRaises(hub.HubError) as error:
            self.h.send({'chat_id': source, 'message_id': message_id, 'index': 0,
                         'action': 'Approve', 'request_id': 'team-card-test-1'}, card=True)
        self.assertEqual(error.exception.status, 400)
        job_count = self.h.db.execute('SELECT count(*) FROM jobs').fetchone()[0]
        reacted = self.h.react({'message_id': message_id, 'emoji': '👍', 'confirm': True})
        self.assertTrue(reacted['active'])
        self.assertIsNone(reacted['job_id'])
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM jobs').fetchone()[0], job_count)
        self.assertFalse(self.h.db.execute('SELECT 1 FROM decisions WHERE message_id=?', (message_id,)).fetchone())
        helper_rules = (self.root / 'data' / 'swarms' / done['workers'][0]['agent_id'] / 'CLAUDE.md').read_text()
        self.assertIn('Help with tasks.', helper_rules)
        self.h.archive({'kind': 'swarm', 'id': done['id'], 'confirm': True})
        self.assertEqual(self.h.chat(source)['id'], source)
        self.assertEqual(self.h.history(source)['messages'][0]['cards'][0]['swarm_id'], done['id'])

    def test_direct_source_can_pull_helper_and_invalid_sources_do_not_launch(self):
        for name in ('Ada', 'Bea'):
            self.h.create_agent({'name': name, 'role': 'Help with tasks.', 'engine': 'claude', 'model': 'haiku'})
        source = 'agent:ada'
        body = {'goal': 'Compare notes', 'shape': 'partition', 'chat_id': source,
                'working_dir': str(self.work), 'workers': [
                    {'source_agent_id': 'ada'}, {'source_agent_id': 'bea'}]}
        done = self.finished(self.h.create_swarm(body)['id'])
        self.assertEqual(done['chat_id'], source)
        self.assertEqual(len(self.h.history(source)['messages']), 1)
        custom = self.finished(self.h.create_swarm({**body, 'workers': [{'role': 'Custom helper'}]})['id'])
        self.assertIsNone(custom['workers'][0]['source_agent_id'])
        before = len(self.h.swarms()['swarms'])
        for bad in ({**body, 'chat_id': 'group:missing'},
                    {**body, 'workers': [{'source_agent_id': 'missing'}]},
                    {**body, 'workers': [{'source_agent_id': 5}]}):
            with self.assertRaises(hub.HubError) as error:
                self.h.create_swarm(bad)
            self.assertIn(error.exception.status, (400, 404))
        self.assertEqual(len(self.h.swarms()['swarms']), before)
        legacy = self.finished(self.h.create_swarm({'goal': 'Legacy run', 'count': 1})['id'])
        self.assertEqual(legacy['chat_id'], legacy['worker_chat_id'])
        self.assertIn(legacy['chat_id'], [c['id'] for c in self.h.state()['chats']])

    def test_selected_agent_without_source_chat_keeps_legacy_group(self):
        self.h.create_agent({'name': 'Ada', 'role': 'Inspect carefully.', 'engine': 'claude', 'model': 'haiku'})
        made = self.h.create_swarm({'goal': 'Onboarding task', 'chat_id': None,
            'workers': [{'source_agent_id': 'ada', 'role': 'Inspector'}]})
        done = self.finished(made['id'])
        self.assertEqual(done['chat_id'], done['worker_chat_id'])
        self.assertTrue(self.h.chat(done['chat_id'])['name'].startswith('Team task: '))
        helper_rules = (self.root / 'data' / 'swarms' / done['workers'][0]['agent_id'] / 'CLAUDE.md').read_text()
        self.assertIn('Inspect carefully.', helper_rules)
        with self.assertRaises(hub.HubError) as error:
            self.h.create_swarm({'goal': 'Invalid helper', 'workers': [{'source_agent_id': 'missing'}]})
        self.assertEqual(error.exception.status, 400)

    def test_source_card_updates_after_each_role(self):
        self.h.create_agent({'name': 'Ada', 'role': 'Help.', 'engine': 'claude', 'model': 'haiku'})
        release = threading.Event()
        def result(aid, chat, prompt, jid):
            if aid.endswith('-2'):
                self.assertTrue(release.wait(3))
            return 'Answer: ' + aid + '\nStatus: PASS\nEvidence: checked fixture\nFiles: none'
        self.h.run_engine = result
        made = self.h.create_swarm({'goal': 'Do two roles', 'shape': 'roles',
            'chat_id': 'agent:ada', 'workers': [{}, {}]})
        sid = made['id']
        try:
            end = time.monotonic() + 3
            while time.monotonic() < end:
                card = self.h.history('agent:ada')['messages'][0]['cards'][0]
                if card['summary'] == '1 of 2 helpers finished.': break
                time.sleep(.01)
            self.assertEqual(card['summary'], '1 of 2 helpers finished.')
            self.assertEqual(card['workers'][0]['status'], 'pass')
            self.assertFalse(card['workers'][1]['answer'])
        finally:
            release.set()
        done = self.finished(sid)
        self.assertEqual(done['status'], 'done')
        card = self.h.history('agent:ada')['messages'][0]['cards'][0]
        self.assertEqual(card['status'], 'done')

    def test_roles_run_in_order_and_pass_prior_report(self):
        seen = []
        def result(aid, chat, prompt, jid):
            seen.append((aid, prompt))
            return 'PASS\nEvidence: ' + aid + ' completed\nFiles: none'
        self.h.run_engine = result
        made = self.h.create_swarm({'goal': 'Build a fixture', 'shape': 'roles',
            'working_dir': str(self.work), 'count': 3})
        done = self.finished(made['id'])
        self.assertEqual([aid.rsplit('-', 1)[-1] for aid, _ in seen], ['1', '2', '3'])
        self.assertIn('completed', seen[1][1])
        self.assertIn('completed', seen[2][1])
        self.assertIn(done['workers'][0]['cwd'], seen[1][1])
        self.assertIn('read-only', seen[1][1])
        self.assertTrue(all(w['status'] == 'pass' for w in done['workers']))

    def test_research_without_project_folder_does_not_require_code_verification(self):
        self.assertIn('without code verification', self.h._brief('Research', 'race', 'Researcher', '', 1, 1, scratch=True))
        self.assertIn('never claim PASS without evidence', self.h._brief('Build', 'race', 'Builder', '', 1, 1))
        self.h.run_engine = lambda *args: 'Answer: Critic found three useful points.'
        scratch = self.finished(self.h.create_swarm({'goal': 'Research this question', 'count': 1,
            'working_dir': ''})['id'])
        self.assertEqual(scratch['status'], 'done')
        self.assertEqual(scratch['workers'][0]['status'], 'pass')
        self.assertFalse(scratch['workers'][0]['issue'])

        project = self.finished(self.h.create_swarm({'goal': 'Review project code', 'count': 1,
            'working_dir': str(self.work)})['id'])
        self.assertEqual(project['workers'][0]['status'], 'issues')

        self.h.run_engine = lambda *args: 'Status: ISSUES\nAnswer: A real concern remains.'
        concerned = self.finished(self.h.create_swarm({'goal': 'Research this question', 'count': 1,
            'working_dir': ''})['id'])
        self.assertEqual(concerned['workers'][0]['status'], 'issues')
        self.assertTrue(concerned['workers'][0]['issue'])

        for report, expected in [('Status: PASS\nAnswer: A clear research answer.', 'pass'),
                                 ('Status: PASS\nAnswer:', 'issues'),
                                 ('Status: BLOCKED\nAnswer: Source unavailable.', 'blocked')]:
            self.h.run_engine = lambda *args, report=report: report
            result = self.finished(self.h.create_swarm({'goal': 'Research', 'count': 1, 'working_dir': ''})['id'])
            self.assertEqual(result['workers'][0]['status'], expected)

    def test_concurrent_duplicate_merge_runs_once(self):
        def git(*args):
            subprocess.run(['git', '-C', str(self.work), *args], check=True, capture_output=True)
        git('init')
        git('config', 'user.name', 'Test')
        git('config', 'user.email', 'test@example.invalid')
        (self.work / 'base.txt').write_text('base\n')
        git('add', 'base.txt')
        git('commit', '-m', 'base')
        self.h.run_engine = lambda *args: 'PASS\nEvidence: fixture\nFiles: none'
        made = self.h.create_swarm({'goal': 'Merge once', 'working_dir': str(self.work),
                                    'worktrees': True, 'count': 1})
        worker = self.finished(made['id'])['workers'][0]
        (Path(worker['worktree']) / 'added.txt').write_text('once\n')
        barrier, outcomes = threading.Barrier(3), []
        def attempt():
            barrier.wait()
            try: outcomes.append(self.h.swarm_action({'id': made['id'], 'action': 'merge',
                                                       'worker': worker['agent_id']})['status'])
            except hub.HubError as error: outcomes.append(error.status)
        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads: thread.start()
        barrier.wait()
        for thread in threads: thread.join(5)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertCountEqual(outcomes, ['merged', 409])
        self.assertEqual((self.work / 'added.txt').read_text(), 'once\n')

    def test_concurrent_duplicate_discard_removes_owned_tree_once(self):
        def git(*args):
            subprocess.run(['git', '-C', str(self.work), *args], check=True, capture_output=True)
        git('init')
        git('config', 'user.name', 'Test')
        git('config', 'user.email', 'test@example.invalid')
        (self.work / 'base.txt').write_text('base\n')
        git('add', 'base.txt')
        git('commit', '-m', 'base')
        self.h.run_engine = lambda *args: 'PASS\nEvidence: fixture\nFiles: none'
        made = self.h.create_swarm({'goal': 'Discard once', 'working_dir': str(self.work),
                                    'worktrees': True, 'count': 1})
        worker = self.finished(made['id'])['workers'][0]
        tree = Path(worker['worktree'])
        barrier, outcomes = threading.Barrier(3), []
        def attempt():
            barrier.wait()
            try: outcomes.append(self.h.swarm_action({'id': made['id'], 'action': 'discard',
                                                       'worker': worker['agent_id']})['status'])
            except hub.HubError as error: outcomes.append(error.status)
        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads: thread.start()
        barrier.wait()
        for thread in threads: thread.join(5)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertCountEqual(outcomes, ['discarded', 404])
        self.assertFalse(tree.exists())

    def test_confirmation_and_restart_hold_uncertain_job(self):
        with self.assertRaises(hub.HubError) as e:
            self.h.create_swarm({'goal': 'x', 'working_dir': str(self.work), 'count': 6})
        self.assertEqual(e.exception.status, 409)
        made = self.h.create_swarm({'goal': 'x', 'working_dir': str(self.work), 'count': 1})
        self.finished(made['id'])
        worker = made['workers'][0]
        with self.h.lock:
            self.h.db.execute("UPDATE swarm_workers SET status='working' WHERE agent_id=?", (worker['agent_id'],))
            self.h.db.execute("UPDATE swarms SET status='working' WHERE id=?", (made['id'],))
            self.h.db.commit()
        self.h.close()
        self.h = hub.Hub(self.root, self.config)
        got = self.h.swarm(made['id'])
        self.assertEqual(got['status'], 'gap', got)
        self.assertEqual(got['workers'][0]['status'], 'gap')

    def test_report_evidence_and_dropout_gap(self):
        def result(aid, chat, prompt, jid):
            if aid.endswith('-2'): raise RuntimeError('fake worker lost')
            return 'PASS\nEvidence: verified fixture output\nFiles: /private/tmp/result.txt\nHandoff: ready'
        self.h.run_engine = result
        made = self.h.create_swarm({'goal': 'Check fixtures', 'shape': 'roles',
            'working_dir': str(self.work), 'count': 2})
        got = self.finished(made['id'])
        workers = sorted(got['workers'], key=lambda w: w['number'])
        self.assertEqual(got['status'], 'gap', got)
        self.assertEqual(workers[0]['status'], 'pass')
        self.assertEqual(workers[0]['evidence'], 'verified fixture output')
        self.assertEqual(workers[0]['files'], ['/private/tmp/result.txt'])
        self.assertEqual(workers[1]['status'], 'gap')

    def test_race_judge_pick_and_scores(self):
        self.h.config['codex_bin'] = str(Path(__file__).with_name('fake_codex.py').resolve())
        self.h.config['role_models'] = {'worker': {'engine': 'claude', 'model': 'sonnet'},
                                        'reviewer': {'engine': 'codex', 'model': 'gpt-6-luna'}}
        self.h.engine_auth = {'claude': 'ready', 'codex': 'ready'}
        def result(aid, chat, prompt, jid):
            if aid.endswith('-judge'):
                sid = aid.split('-')[1]
                one, two = 'swarm-' + sid + '-1', 'swarm-' + sid + '-2'
                return ('PASS\nEvidence: compared both candidate reports\nFiles: none\n'
                    'Pick: ' + one + '\nScores: ' + json.dumps({one: {'Correctness': 5, 'Clarity': 4, 'Tests': 5},
                                                               two: {'Correctness': 3, 'Clarity': 4, 'Tests': 3}}))
            return 'PASS\nEvidence: fixture verified\nFiles: none'
        self.h.run_engine = result
        made = self.h.create_swarm({'goal': 'Compare answers', 'shape': 'race',
            'working_dir': str(self.work), 'count': 2,
            'rubric': ['Correctness', 'Clarity', 'Tests']})
        got = self.finished(made['id'])
        self.assertEqual(got['judge_pick'], 'swarm-' + made['id'] + '-1')
        self.assertEqual(got['judge_scores'][got['judge_pick']]['Correctness'], 5)
        self.assertEqual(next(w for w in got['workers'] if w['number'] == 0)['engine'], 'codex')
        self.assertEqual(next(w for w in got['workers'] if w['number'] == 0)['model'], 'gpt-6-luna')

    def test_invalid_judge_scores_are_issues_without_pick(self):
        def result(aid, chat, prompt, jid):
            if aid.endswith('-judge'):
                return 'PASS\nEvidence: compared reports\nFiles: none\nPick: ' + aid.replace('-judge', '-1') + '\nScores: {"bad": {"Correctness": 5}}'
            return 'PASS\nEvidence: fixture verified\nFiles: none'
        self.h.run_engine = result
        made = self.h.create_swarm({'goal': 'Compare answers', 'shape': 'race',
            'working_dir': str(self.work), 'count': 2,
            'rubric': ['Correctness', 'Clarity', 'Tests']})
        got = self.finished(made['id'])
        judge = next(w for w in got['workers'] if w['number'] == 0)
        self.assertIsNone(got['judge_pick'])
        self.assertEqual(got['judge_scores'], {})
        self.assertEqual(judge['status'], 'issues')

    def test_race_judge_and_worktree_merge_guard(self):
        def git(*args):
            return subprocess.run(['git', '-C', str(self.work), *args], check=True, capture_output=True, text=True).stdout.strip()
        git('init')
        git('config', 'user.name', 'Test')
        git('config', 'user.email', 'test@example.invalid')
        (self.work / 'base.txt').write_text('base\n')
        git('add', 'base.txt')
        git('commit', '-m', 'base')
        with self.assertRaises(hub.HubError):
            self.h.create_swarm({'goal': 'Unsafe direct work', 'working_dir': str(self.work), 'count': 1})
        made = self.h.create_swarm({'goal': 'Improve base', 'shape': 'race', 'working_dir': str(self.work),
            'count': 2, 'worktrees': True, 'rubric': ['Correctness', 'Clarity', 'Tests']})
        done = self.finished(made['id'])
        self.assertEqual(len(done['workers']), 3)
        self.assertTrue(done['judge_id'])
        self.assertTrue(all(w['job_id'] for w in done['workers']))
        self.assertEqual((self.work / 'base.txt').read_text(), 'base\n')
        candidate = next(w for w in done['workers'] if w['number'] == 1)
        tree = Path(candidate['worktree'])
        (tree / 'base.txt').write_text('better\n')
        (tree / 'new.txt').write_text('new\n')
        (self.work / 'local.txt').write_text('owner\n')
        with self.assertRaises(hub.HubError):
            self.h.swarm_action({'id': made['id'], 'action': 'merge', 'worker': candidate['agent_id']})
        self.assertEqual((self.work / 'base.txt').read_text(), 'base\n')
        (self.work / 'local.txt').unlink()
        result = self.h.swarm_action({'id': made['id'], 'action': 'merge', 'worker': candidate['agent_id']})
        self.assertEqual(result['status'], 'merged')
        self.assertEqual(next(w for w in self.h.swarm(made['id'])['workers'] if w['agent_id'] == candidate['agent_id'])['outcome'], 'merged')
        with self.assertRaises(hub.HubError):
            self.h.swarm_action({'id': made['id'], 'action': 'merge', 'worker': candidate['agent_id']})
        self.assertEqual((self.work / 'base.txt').read_text(), 'better\n')
        self.assertEqual((self.work / 'new.txt').read_text(), 'new\n')
        with self.assertRaises(hub.HubError):
            self.h.swarm_action({'id': made['id'], 'action': 'discard', 'worker': candidate['agent_id']})
        self.assertEqual(self.h.swarm_action({'id': made['id'], 'action': 'discard',
            'worker': candidate['agent_id'], 'confirm_dirty': True})['status'], 'discarded')
        self.assertEqual(next(w for w in self.h.swarm(made['id'])['workers'] if w['agent_id'] == candidate['agent_id'])['outcome'], 'discarded')


if __name__ == '__main__': unittest.main()
