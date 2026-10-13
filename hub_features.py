"""Local settings, routine scheduler and opt-in loopback Approvals connector adapter."""
import datetime as dt
import json
from pathlib import Path
from hub_fs import open_file
import plistlib
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from urllib.parse import quote


def fail(status, message):
    from hub import HubError
    raise HubError(status, message)


def next_run(spec, now):
    """Next local wall-clock occurrence, strictly after now; no missed-run replay."""
    if spec['trigger'] == 'interval':
        return now + spec['minutes'] * 60
    current = dt.datetime.fromtimestamp(now)
    hour, minute = map(int, spec['time'].split(':'))
    for offset in range(9):
        day = current.date() + dt.timedelta(days=offset)
        candidate = dt.datetime.combine(day, dt.time(hour, minute))
        if spec['trigger'] == 'weekdays' and candidate.weekday() > 4:
            continue
        if spec['trigger'] == 'weekly' and candidate.weekday() != spec['weekday']:
            continue
        epoch = candidate.timestamp()
        if epoch > now:
            return epoch
    raise ValueError('No next occurrence')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class FeaturesMixin:
    def init_features(self):
        self.clock = time.time
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS routines(id TEXT PRIMARY KEY, spec TEXT NOT NULL,
            enabled INTEGER NOT NULL, next_run REAL NOT NULL, last_run REAL, error TEXT);
          CREATE TABLE IF NOT EXISTS routine_runs(routine_id TEXT, due REAL, job_id INTEGER,
            PRIMARY KEY(routine_id,due));
        ''')
        if 'notice' not in {r['name'] for r in self.db.execute('PRAGMA table_info(routine_runs)')}:
            self.db.execute('ALTER TABLE routine_runs ADD COLUMN notice TEXT')
        self.db.commit()
        self._scheduler_started = False
        self.init_product()

    def extra_post_routes(self):
        routes = self.swarm_post_routes()
        routes.update(self.onboarding_post_routes())
        routes.update(self.browser_post_routes())
        routes.update({'/api/settings': self.save_settings, '/api/routines': self.create_routine,
                       '/api/routines/toggle': self.toggle_routine,
                       '/api/routines/delete': self.delete_routine,
                       '/api/approvals/review': self.approvals_review,
                       '/api/product': self.product_action, '/api/archive': self.archive,
                       '/api/setup': self.bootstrap, '/api/jobs/stop': self.stop_job})
        return routes

    def extra_get_routes(self, query):
        routes = self.swarm_get_routes(query)
        routes.update(self.onboarding_get_routes(query))
        routes.update(self.browser_get_routes())
        routes.update({'/api/settings': self.feature_settings, '/api/routines': self.routines,
                       '/api/approvals/workspace': lambda: self.approvals_request('/api/approvals/workspace'),
                       '/api/approvals/decision': lambda: self.approvals_decision((query.get('id') or [''])[0]),
                       '/api/product': self.product_state,
                       '/api/search': lambda: self.search_messages(query),
                       '/api/setup': self.setup_status, '/api/jobs': self.jobs_board})
        return routes

    def role_defaults(self, role):
        role = {'reviewer/judge': 'reviewer', 'judge': 'reviewer', 'quick replies': 'quick'}.get(role, role)
        value = self.config.get('role_models', {}).get(role)
        if value:
            return dict(value)
        engine = self.default_engine() if callable(getattr(self, 'default_engine', None)) else self.config.get('default_engine', 'claude')
        return {'engine': engine, 'model': self.config.get('default_codex_model', 'gpt-6-luna') if engine == 'codex' else self.config.get('default_model', 'haiku')}

    def feature_settings(self):
        return {'role_models': {r: self.role_defaults(r) for r in ('orchestrator', 'worker', 'reviewer', 'quick')},
                'approvals_url': self.config.get('approvals_url') or None,
                'engines': self.engine_catalog(),
                'default_engine': self.config.get('default_engine', 'claude'),
                'onboarding_scan': self.config.get('onboarding_scan'),
                'full_access_permission_mode': self.config.get('full_access_permission_mode', 'auto'),
                'owner_name': self.config.get('owner_name') or 'You'}

    @staticmethod
    def validate_approvals(value):
        if not value:
            return None
        if not isinstance(value, str): fail(400, 'Approvals connector URL must be a loopback HTTP address.')
        u = urlsplit(value)
        try: port = u.port
        except ValueError: fail(400, 'Invalid Approvals connector port.')
        if u.scheme != 'http' or u.hostname not in ('localhost', '127.0.0.1', '::1') or u.username or u.password or u.path not in ('', '/') or u.query or u.fragment:
            fail(400, 'Enter an HTTP address on this computer, such as http://127.0.0.1:PORT (replace PORT with the connector’s port number).')
        return value.rstrip('/')

    def save_settings(self, body):
        from hub import atomic_json
        changes = {}
        if 'full_access_permission_mode' in body:
            mode = body['full_access_permission_mode']
            if not isinstance(mode, str) or mode not in ('auto', 'inherit'):
                fail(400, 'Choose Auto or Ask nothing new for Full access permission mode.')
            changes['full_access_permission_mode'] = mode
        if 'owner_name' in body:
            name = body['owner_name']
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80: fail(400, 'Use a short display name.')
            changes['owner_name'] = name.strip()
        if 'approvals_url' in body:
            changes['approvals_url'] = self.validate_approvals(body['approvals_url'])
        if 'role_models' in body:
            values = body['role_models']
            if not isinstance(values, dict): fail(400, 'Choose an engine and model for each role.')
            roles = {r: self.role_defaults(r) for r in ('orchestrator', 'worker', 'reviewer', 'quick')}
            for role, choice in values.items():
                if role not in roles or not isinstance(choice, dict): fail(400, 'Unknown role.')
                engine, model = choice.get('engine'), choice.get('model')
                if engine not in ('claude', 'codex') or not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}', model):
                    fail(400, 'Use a valid engine and model identifier.')
                roles[role] = {'engine': engine, 'model': model}
            changes['role_models'] = roles
        with self.lock:
            config = dict(self.config, **changes)
            atomic_json(self.root / 'config.json', config)
            self.config = config
        return self.feature_settings()

    def external_routines(self):
        pattern = self.config.get('external_routine_glob', '')
        if not isinstance(pattern, str) or not pattern or '/' in pattern or '\\' in pattern or pattern.startswith('.'):
            return []
        root = self.path(self.config.get('launch_agents_dir', '~/Library/LaunchAgents'))
        result = []
        for path in sorted(root.glob(pattern)):
            try:
                if not path.is_file() or path.is_symlink(): continue
                with open_file(path, 'rb') as file: value = plistlib.load(file)
                args = value.get('ProgramArguments', [])
                label = str(value.get('Label', path.stem))
                bot = label.split('.')[-2] if '.' in label else label
                for flag in ('--bot', '--agent'):
                    if flag in args and args.index(flag) + 1 < len(args): bot = args[args.index(flag)+1]
                schedule = value.get('StartCalendarInterval')
                if schedule is not None: schedule = human_calendar(schedule)
                elif value.get('StartInterval'): schedule = 'Every %s seconds' % value['StartInterval']
                else: schedule = 'Event/manual trigger'
                result.append({'bot': bot, 'routine': label,
                               'schedule': schedule, 'read_only': True, 'disabled': bool(value.get('Disabled'))})
            except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
                result.append({'bot': 'unknown', 'routine': path.stem, 'schedule': 'Unreadable plist', 'read_only': True})
        return result

    def routines(self):
        with self.lock:
            values = []
            for row in self.db.execute('SELECT * FROM routines ORDER BY rowid'):
                started = self.db.execute('''SELECT MAX(j.started) FROM routine_runs rr
                    JOIN jobs j ON j.id=rr.job_id WHERE rr.routine_id=? AND j.started IS NOT NULL''',
                    (row['id'],)).fetchone()[0]
                values.append(dict(json.loads(row['spec']), id=row['id'], enabled=bool(row['enabled']),
                                   next_run=row['next_run'], last_run=started, error=row['error']))
        return {'routines': values, 'external': self.external_routines(), 'timezone': time.tzname[0],
                'note': 'Hub must remain running. Occurrences missed by more than a minute are skipped and shown in chat; uncertain runs are never replayed. Existing launchd schedules are read-only.'}

    def create_routine(self, body):
        spec = {k: body.get(k) for k in ('agent_id', 'name', 'prompt', 'trigger', 'time', 'minutes', 'weekday')}
        if spec['agent_id'] not in self.agents(): fail(400, 'Choose a known agent.')
        if not isinstance(spec['name'], str) or not 1 <= len(spec['name'].strip()) <= 100: fail(400, 'Name the schedule (1–100 characters).')
        if not isinstance(spec['prompt'], str) or not 1 <= len(spec['prompt'].strip()) <= 12000: fail(400, 'Write the schedule task.')
        if spec['trigger'] not in ('daily', 'weekdays', 'interval', 'weekly'): fail(400, 'Unknown schedule trigger.')
        if spec['trigger'] == 'interval':
            if type(spec['minutes']) is not int or not 1 <= spec['minutes'] <= 525600: fail(400, 'Use a whole number of minutes from 1 to 525600.')
        else:
            if not isinstance(spec['time'], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', spec['time']): fail(400, 'Choose a time in HH:MM format.')
            if spec['trigger'] == 'weekly' and (type(spec['weekday']) is not int or not 0 <= spec['weekday'] <= 6): fail(400, 'Choose a weekday (Monday=0).')
        rid, now = secrets.token_hex(8), self.clock()
        with self.lock:
            self.sync_chats()
            self.db.execute('INSERT INTO routines VALUES(?,?,?,?,?,?)', (rid, json.dumps(spec), 1, next_run(spec, now), None, None))
            self.add_message('agent:' + spec['agent_id'], spec['agent_id'], 'system', 'Schedule created: ' + spec['name'])
            self.db.commit()
        self.emit('message', 'agent:' + spec['agent_id'])
        self.emit('routines')
        return {'routine': next(r for r in self.routines()['routines'] if r['id'] == rid)}

    def toggle_routine(self, body):
        if type(body.get('enabled')) is not bool: fail(400, 'enabled must be true or false.')
        with self.lock:
            row = self.db.execute('SELECT * FROM routines WHERE id=?', (body.get('id'),)).fetchone()
            if not row: fail(404, 'Schedule not found.')
            due = next_run(json.loads(row['spec']), self.clock()) if body['enabled'] else row['next_run']
            self.db.execute('UPDATE routines SET enabled=?,next_run=?,error=NULL WHERE id=?', (int(body['enabled']), due, row['id']))
            self.db.commit()
        self.emit('routines')
        return {'ok': True}

    def tick_routines(self, now=None):
        now = self.clock() if now is None else now
        with self.lock:
            self.reconcile_routine_runs()
            due = self.db.execute('SELECT * FROM routines WHERE enabled=1 AND next_run<=?', (now,)).fetchall()
            for row in due:
                spec = json.loads(row['spec'])
                aid, cid = spec['agent_id'], 'agent:' + spec['agent_id']
                # Reserve occurrence BEFORE handing work to a process. Never catch up in a loop.
                self.db.execute('UPDATE routines SET next_run=? WHERE id=?', (next_run(spec, now), row['id']))
                claim = self.db.execute('INSERT OR IGNORE INTO routine_runs(routine_id,due,job_id) VALUES(?,?,NULL)', (row['id'], row['next_run']))
                if not claim.rowcount:
                    self.db.commit()
                    continue
                self.db.commit()
                try:
                    if aid not in self.agents(): raise ValueError('Schedule Pip is unavailable.')
                    self.sync_chats()
                    if now - row['next_run'] > 60:
                        self.routine_failure(row['id'], row['next_run'], spec, 'Hub was off or unavailable')
                        continue
                    active = self.db.execute("SELECT 1 FROM jobs WHERE agent_id=? AND status IN ('queued','working','typing','held','usage_limited','held_limit')", (aid,)).fetchone()
                    if active:
                        self.routine_failure(row['id'], row['next_run'], spec, 'skipped: agent already has active work')
                        continue
                    mid = self.add_message(cid, aid, 'system', 'Schedule queued: ' + spec['name'])
                    prompt = 'Scheduled task: ' + spec['name'] + '\n' + spec['prompt'] + '\nReply with exactly SILENT if no owner-facing update is needed.'
                    cur = self.db.execute('INSERT INTO jobs(chat_id,agent_id,prompt,reply_to,status,created) VALUES(?,?,?,?,?,?)', (cid, aid, prompt, mid, 'queued', now))
                    jid = cur.lastrowid
                    self.db.execute('UPDATE routine_runs SET job_id=? WHERE routine_id=? AND due=?', (jid, row['id'], row['next_run']))
                    self.db.execute('UPDATE routines SET error=NULL WHERE id=?', (row['id'],))
                    self.db.commit()
                    self.enqueue(aid, jid)
                    self.emit('message', cid)
                except Exception as exc:
                    self.db.rollback()
                    self.routine_failure(row['id'], row['next_run'], spec, 'failed: ' + str(exc)[:500])
        return len(due)

    def routine_failure(self, rid, due, spec, reason):
        """One durable chat notice per failed occurrence; never replay a side effect."""
        with self.lock:
            row = self.db.execute('SELECT notice FROM routine_runs WHERE routine_id=? AND due=?', (rid, due)).fetchone()
            if not row or row['notice']:
                return
            aid, cid = spec['agent_id'], 'agent:' + spec['agent_id']
            when = dt.datetime.fromtimestamp(due).strftime('%H:%M')
            message = spec['name'] + " didn't run at " + when + ' — ' + reason
            # Retain a visible historical chat even when the agent folder disappeared.
            self.db.execute('INSERT OR IGNORE INTO chats(id,name,type,agents) VALUES(?,?,?,?)',
                            (cid, aid, 'direct', json.dumps([aid])))
            self.add_message(cid, aid, 'system', message)
            self.db.execute('UPDATE routine_runs SET notice=? WHERE routine_id=? AND due=?', (reason, rid, due))
            self.db.execute('UPDATE routines SET error=? WHERE id=?', (reason, rid))
            self.db.commit()
        self.emit('message', cid)
        self.emit('routines')

    def reconcile_routine_runs(self):
        """Also reconcile restart interruptions and failures after the scheduler queued a job."""
        with self.lock:
            rows = self.db.execute('''SELECT rr.routine_id,rr.due,r.spec,j.status,j.error
                FROM routine_runs rr JOIN routines r ON r.id=rr.routine_id
                LEFT JOIN jobs j ON j.id=rr.job_id
                WHERE rr.notice IS NULL AND
                (j.status IN ('error','failed','stopped','interrupted','uncertain')
                 OR rr.job_id IS NULL)''').fetchall()
            for row in rows:
                # NULL job IDs are a prior reserved occurrence interrupted before enqueue.
                state = row['status'] or 'uncertain'
                reason = (row['error'] or ('Hub stopped; outcome unknown' if state in ('interrupted', 'uncertain') else state))[:500]
                self.routine_failure(row['routine_id'], row['due'], json.loads(row['spec']),
                                     ('uncertain: ' if state in ('interrupted', 'uncertain') else 'failed: ') + reason)

    def start_scheduler(self):
        with self.lock:
            if self._scheduler_started or self.stop.is_set(): return
            self._scheduler_started = True
            def loop():
                while not self.stop.wait(1):
                    try: self.tick_routines()
                    except Exception:
                        import logging
                        logging.exception('Agent Hub scheduler failed')
            thread = threading.Thread(target=loop, daemon=True, name='hub-routines')
            self.threads.append(thread)
            thread.start()

    def approvals_request(self, path, body=None):
        base = self.validate_approvals(self.config.get('approvals_url'))
        if not base: fail(409, 'Approvals connector is off. Enable its local API in Settings.')
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(req, timeout=10) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024: fail(502, 'Approvals connector response exceeds 2 MiB.')
        except urllib.error.HTTPError as exc:
            raw = exc.read(16384).decode('utf-8', 'replace')
            try:
                parsed = json.loads(raw)
                message = parsed.get('error') or parsed.get('message') or raw
            except (ValueError, AttributeError): message = raw
            fail(exc.code if 400 <= exc.code < 600 else 502, str(message) or 'Approvals connector refused this request.')
        except (OSError, urllib.error.URLError):
            fail(502, 'Approvals connector could not be reached. A review may be uncertain; inspect Approvals connector before trying again.')
        try: return json.loads(raw)
        except (ValueError, UnicodeError): fail(502, 'Approvals connector returned invalid JSON; inspect its outcome before retrying.')

    def approvals_review(self, body):
        if not isinstance(body.get('id'), (str, int)) or isinstance(body.get('id'), bool) or not str(body['id']): fail(400, 'A draft id is required.')
        action = body.get('action')
        if action not in ('approve', 'deny', 'edit'): fail(400, 'Choose approve, deny, or edit.')
        payload = {'id': body['id'], 'action': action}
        field = 'text' if action == 'edit' else 'reason'
        if field in body:
            if not isinstance(body[field], str) or len(body[field]) > 20000: fail(400, 'Invalid review text.')
            payload[field] = body[field]
        if action == 'edit' and not payload.get('text', '').strip(): fail(400, 'Write the edited draft.')
        return self.approvals_request('/api/approvals/review', payload)

    def approvals_decision(self, draft_id):
        if not isinstance(draft_id, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,160}', draft_id):
            fail(400, 'A draft id is required.')
        result = self.approvals_request('/api/decisions?title=' + quote('approvals:' + draft_id, safe=''))
        prefix = 'approvals:'
        decisions = result if isinstance(result, list) else (
            result.get('decisions', result.get('items', result.get('results', [])))
            if isinstance(result, dict) else [])
        if isinstance(decisions, dict): decisions = [decisions]
        if isinstance(result, dict) and result.get('title') == prefix + draft_id:
            decisions = [result]
        if not isinstance(decisions, list): decisions = []
        matching = [d for d in decisions if isinstance(d, dict) and d.get('title') == prefix + draft_id]
        decision = matching[-1] if matching else None
        outcome = decision.get('result') if decision else None
        if isinstance(outcome, str) and outcome.lstrip().startswith('{'):
            try: outcome = json.loads(outcome)
            except ValueError: pass
        if isinstance(outcome, dict): outcome = outcome.get('status') or outcome.get('outcome')
        raw = str(outcome or decision.get('status', '')).lower() if decision else ''
        # A review or approval does not prove publication. Only report explicitly
        # observed scheduling and holds; everything else remains pending.
        status = 'scheduled' if raw == 'scheduled' else 'held' if raw in ('held', 'hold', 'rejected', 'denied') else 'pending'
        return {'id': draft_id, 'status': status, 'decision': decision}


def human_calendar(value):
    """Readable launchd calendar text without pretending unsupported fields are known."""
    days = ('Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday')
    def one(spec):
        if not isinstance(spec, dict): return 'Calendar schedule'
        hour, minute = spec.get('Hour'), spec.get('Minute', 0)
        clock = f'{hour:02d}:{minute:02d}' if type(hour) is int and 0 <= hour <= 23 and type(minute) is int and 0 <= minute <= 59 else 'scheduled time'
        if type(spec.get('Weekday')) is int and 0 <= spec['Weekday'] <= 6:
            return f"{days[spec['Weekday']]} at {clock}"
        if type(spec.get('Day')) is int:
            return f"Day {spec['Day']} of each month at {clock}"
        return f'Daily at {clock}' if hour is not None else 'Calendar schedule'
    if isinstance(value, list):
        rows = [one(item) for item in value]
        return ', '.join(rows) if rows else 'Calendar schedule'
    return one(value)
