"""Serialized SQLite access, including cursor consumption (Python 3.9 safe).

Hub transactions hold the same RLock across execute/commit. No native cursor
escapes this wrapper: callers iterate a detached snapshot outside the lock.
"""
import sqlite3
from pathlib import Path
from hub_fs import SQLiteFileGuard


class Rows:
    def __init__(self, cursor):
        self.lastrowid = cursor.lastrowid
        self.rowcount = cursor.rowcount
        self.description = cursor.description
        self._rows = iter(cursor.fetchall() if cursor.description else ())

    def fetchone(self):
        return next(self._rows, None)

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return self._rows


class LockedDatabase:
    def __init__(self, path, lock):
        self.lock = lock
        self._closed = False
        # Cross-thread use is safe ONLY because every native call and cursor
        # lifetime is protected by lock, also used for Hub transactions.
        self._files = SQLiteFileGuard(Path(path).parent, Path(path).name)
        try:
            self._connection = self._files.connect(check_same_thread=False, timeout=15)
            self._files.check()
        except BaseException:
            if hasattr(self, '_connection'):
                self._connection.close()
            self._files.close()
            raise
        self._connection.row_factory = sqlite3.Row
        self.execute('PRAGMA journal_mode=WAL')
        self.execute('PRAGMA busy_timeout=15000')

    def execute(self, sql, parameters=()):
        with self.lock:
            self._files.check()
            cursor = self._connection.execute(sql, parameters)
            try:
                return Rows(cursor)
            finally:
                cursor.close()

    def executescript(self, sql):
        with self.lock:
            self._files.check()
            cursor = self._connection.executescript(sql)
            cursor.close()

    def commit(self):
        with self.lock:
            self._files.check()
            self._connection.commit()

    def rollback(self):
        with self.lock:
            self._files.check()
            self._connection.rollback()

    def close(self):
        with self.lock:
            if not self._closed:
                try:
                    self._connection.close()
                finally:
                    self._files.close()
                    self._closed = True
