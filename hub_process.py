"""Bounded, streaming subprocess supervision for Hub-owned CLI calls."""
import os
import signal
import subprocess
import threading
import time


class OutputLimitExceeded(RuntimeError):
    """A child wrote more bytes than its allowed stdout or stderr budget."""


def _kill_group(proc):
    # Every process started by run_bounded has its own session. Streaming agent
    # processes are also started that way by Hub.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        if proc.poll() is None:
            proc.kill()


def collect_process(proc, *, timeout, stdout_limit, stderr_limit, on_stdout_line=None):
    """Drain both raw pipes concurrently, enforcing byte limits and one deadline.

    The deadline includes pipe EOF: a descendant that inherits a pipe cannot
    retain it indefinitely after the direct child exits.
    """
    limits = {'stdout': stdout_limit, 'stderr': stderr_limit}
    chunks = {'stdout': [], 'stderr': []}
    sizes = {'stdout': 0, 'stderr': 0}
    done = {'stdout': False, 'stderr': False}
    failures = []
    lock = threading.Lock()

    def reader(name):
        pipe = getattr(proc, name)
        pending = b''
        try:
            while True:
                block = os.read(pipe.fileno(), 8192)
                if not block:
                    break
                with lock:
                    sizes[name] += len(block)
                    if sizes[name] > limits[name]:
                        failures.append(OutputLimitExceeded(name + ' exceeded ' + str(limits[name]) + ' bytes'))
                    else:
                        chunks[name].append(block)
                    failed = bool(failures)
                if failed:
                    _kill_group(proc)
                    break
                if name == 'stdout' and on_stdout_line is not None:
                    pending += block
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        on_stdout_line((line + b'\n').decode('utf-8', 'replace'))
            if pending and name == 'stdout' and on_stdout_line is not None and not failures:
                on_stdout_line(pending.decode('utf-8', 'replace'))
        except BaseException as exc:
            with lock:
                failures.append(exc)
            _kill_group(proc)
        finally:
            pipe.close()
            with lock:
                done[name] = True

    readers = [threading.Thread(target=reader, args=(name,), daemon=True)
               for name in ('stdout', 'stderr')]
    for worker in readers:
        worker.start()
    deadline = time.monotonic() + timeout
    try:
        while True:
            with lock:
                failed = failures[0] if failures else None
                finished = all(done.values())
            if failed:
                raise failed
            if finished and proc.poll() is not None:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(proc.args, timeout)
            # poll() alone is insufficient when a grandchild retains a pipe.
            time.sleep(min(0.02, remaining))
        proc.wait()
        return b''.join(chunks['stdout']), b''.join(chunks['stderr'])
    except BaseException:
        _kill_group(proc)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        raise
    finally:
        for worker in readers:
            worker.join(timeout=2)


def start_process(args, *, cwd=None, env=None, stdin=subprocess.DEVNULL, text=False):
    """Start a child in its own group, with both output pipes ready to be drained."""
    return subprocess.Popen(args, cwd=cwd, env=env, stdin=stdin,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=text, start_new_session=True)


def run_bounded(args, *, timeout, stdout_limit=65536, stderr_limit=65536,
                cwd=None, env=None, text=True, check=False, stdin=subprocess.DEVNULL):
    """Run a CLI with finite output and lifetime, killing its group on breach."""
    proc = start_process(args, cwd=cwd, env=env, stdin=stdin)
    stdout, stderr = collect_process(proc, timeout=timeout,
                                     stdout_limit=stdout_limit,
                                     stderr_limit=stderr_limit)
    if text:
        stdout = stdout.decode('utf-8', 'replace')
        stderr = stderr.decode('utf-8', 'replace')
    result = subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
    if check:
        result.check_returncode()
    return result
