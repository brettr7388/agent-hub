"""Descriptor-pinned filesystem operations for Hub-managed local files.

All path components are opened from a pinned directory, without following links.
Callers must still authorize *which* paths belong to their feature.  In particular,
deletion requires either a recognized Hub-generated basename or an explicit set of
approved basenames supplied by the caller.
"""

from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import sys


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_UPLOAD_NAME = re.compile(r"^[0-9a-f]{24}-.+")
_TEMP_NAME = re.compile(r"^\.hub-(?:merge|tmp)-[0-9a-f]{32}$")
_LAST_NAME = re.compile(r"^codex-last-[0-9a-f]{24}\.txt$")
_MANAGED_DIRECTORY_NAMES = frozenset({
    'uploads', 'exports', 'teams', 'worktrees', 'agents', 'agents_dir',
    'create', 'swarms', 'groups', 'media', 'workers', 'managed-pips',
    'codex-home', 'codex-home-v3', 'linked-workspaces', 'onboarding-run',
})


def _absolute(path):
    raw = os.fspath(path)
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    if not raw or '\0' in raw:
        raise ValueError('Invalid filesystem path.')
    # macOS exposes these two root-owned compatibility aliases.  Accept only the
    # exact system targets, never a caller-chosen symlink further down the path.
    if sys.platform == 'darwin' and (raw == '/var' or raw.startswith('/var/')):
        if os.readlink('/var') != 'private/var':
            raise ValueError('Unexpected /var alias.')
        raw = '/private' + raw
    elif sys.platform == 'darwin' and (raw == '/tmp' or raw.startswith('/tmp/')):
        if os.readlink('/tmp') != 'private/tmp':
            raise ValueError('Unexpected /tmp alias.')
        raw = '/private' + raw
    if not raw.startswith('/'):
        raw = os.path.join(os.getcwd(), raw)
    parts = raw.split('/')[1:]
    if any(part in ('.', '..') for part in parts):
        raise ValueError('Relative path components are not allowed.')
    return tuple(part for part in parts if part)


def _entry(name):
    name = os.fspath(name)
    if isinstance(name, bytes):
        name = os.fsdecode(name)
    if not name or name in ('.', '..') or '/' in name or '\0' in name:
        raise ValueError('Expected one filesystem entry name.')
    return name


def _walk(parts):
    fd = os.open('/', _DIR_FLAGS)
    try:
        for part in parts:
            next_fd = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def open_directory(path):
    """Return a caller-owned fd for an ordinary directory, rejecting link ancestors."""
    return _walk(_absolute(path))


def _parent(path):
    parts = _absolute(path)
    if not parts:
        raise ValueError('A file operation requires an entry below root.')
    return _walk(parts[:-1]), parts[-1]


def stat_fd(directory_fd, name):
    """Stat one entry without following a symlink."""
    return os.stat(_entry(name), dir_fd=directory_fd, follow_symlinks=False)


def listdir_fd(directory_fd):
    """List basenames relative to a directory kept open by the caller."""
    return os.listdir(directory_fd)


def listdir(path):
    fd = open_directory(path)
    try:
        return [Path(path) / name for name in os.listdir(fd)]
    finally:
        os.close(fd)


def _regular(fd, mutable=False):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Only ordinary files are allowed.')
    if mutable and info.st_nlink != 1:
        raise ValueError('Refusing to mutate a hard-linked file.')
    return info


def _open_fd(parent, name, mode):
    base = mode[0]
    if base not in 'rwax' or len(mode) > 3 or any(c not in '+bt' for c in mode[1:]):
        raise ValueError('Unsupported file mode.')
    if 'b' in mode and 't' in mode:
        raise ValueError('File mode cannot be both binary and text.')
    mutable = base != 'r' or '+' in mode
    flags = _FILE_FLAGS
    flags |= os.O_RDWR if '+' in mode else (os.O_RDONLY if base == 'r' else os.O_WRONLY)
    if base == 'x':
        flags |= os.O_CREAT | os.O_EXCL
    elif base in 'wa':
        flags |= os.O_CREAT
    if base == 'a':
        flags |= os.O_APPEND
    fd = os.open(name, flags, 0o600, dir_fd=parent)
    try:
        _regular(fd, mutable)
        if base == 'w':
            os.ftruncate(fd, 0)
        elif base == 'a':
            os.lseek(fd, 0, os.SEEK_END)
        return fd
    except BaseException:
        os.close(fd)
        raise


def open_file(path, mode='rb', buffering=-1, encoding=None, errors=None, newline=None):
    """Open a regular file without links; mutable modes reject hard links."""
    parent, name = _parent(path)
    try:
        fd = _open_fd(parent, name, mode)
    finally:
        os.close(parent)
    try:
        return os.fdopen(fd, mode, buffering=buffering, encoding=encoding,
                         errors=errors, newline=newline)
    except BaseException:
        os.close(fd)
        raise


def read_bytes(path, limit=None):
    if limit is not None and limit < 0:
        raise ValueError('Negative read limit.')
    with open_file(path, 'rb') as stream:
        if limit is None:
            return stream.read()
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('File exceeds read limit.')
        return data


def read_text(path, encoding='utf-8', errors='strict', limit=None):
    return read_bytes(path, limit=limit).decode(encoding, errors)


def _existing_regular(parent, name, mutable=True):
    try:
        info = stat_fd(parent, name)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Destination must be an ordinary file.')
    if mutable and info.st_nlink != 1:
        raise ValueError('Refusing a hard-linked destination.')
    return info


def _atomic_at(parent, name, data, mode=0o600):
    _existing_regular(parent, name)
    temporary = '.hub-tmp-' + secrets.token_hex(16)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _FILE_FLAGS,
                 mode, dir_fd=parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _existing_regular(parent, name)
        os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass


def atomic_write_bytes(path, data):
    if not isinstance(data, bytes):
        raise TypeError('Expected bytes.')
    parent, name = _parent(path)
    try:
        _atomic_at(parent, name, data)
    finally:
        os.close(parent)


def atomic_write_text(path, text, encoding='utf-8'):
    if not isinstance(text, str):
        raise TypeError('Expected text.')
    atomic_write_bytes(path, text.encode(encoding))


@contextmanager
def atomic_writer(path, exclusive=False, mode=0o600):
    """Yield a binary stream, then atomically publish it in its pinned directory.

    The destination is touched only after the caller finishes successfully.
    ``exclusive`` prevents replacing a pre-existing upload basename.
    """
    parent, name = _parent(path)
    temporary = '.hub-tmp-' + secrets.token_hex(16)
    created = False
    try:
        prior = _existing_regular(parent, name)
        if exclusive and prior is not None:
            raise FileExistsError(os.fspath(path))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _FILE_FLAGS,
                     mode, dir_fd=parent)
        created = True
        with os.fdopen(fd, 'wb') as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        current = _existing_regular(parent, name)
        if exclusive and current is not None:
            raise FileExistsError(os.fspath(path))
        if exclusive:
            # link(2) publishes the complete inode only if this name is still
            # absent; replace(2) would overwrite a racing upload collision.
            os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent,
                    follow_symlinks=False)
        else:
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        try:
            if created:
                os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass
        finally:
            os.close(parent)


def mkdir(path, parents=False, exist_ok=False, mode=0o700):
    parts = _absolute(path)
    if not parts:
        if exist_ok:
            return
        raise FileExistsError('/')
    if not parents:
        parent = _walk(parts[:-1])
        try:
            try:
                os.mkdir(parts[-1], mode, dir_fd=parent)
            except FileExistsError:
                if not exist_ok:
                    raise
                child = os.open(parts[-1], _DIR_FLAGS, dir_fd=parent)
                os.close(child)
        finally:
            os.close(parent)
        return
    fd = os.open('/', _DIR_FLAGS)
    try:
        for index, part in enumerate(parts):
            try:
                os.mkdir(part, mode, dir_fd=fd)
            except FileExistsError:
                if index == len(parts) - 1 and not exist_ok:
                    raise
            next_fd = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
    finally:
        os.close(fd)


def chmod(path, mode):
    parent, name = _parent(path)
    try:
        fd = os.open(name, os.O_RDONLY | _FILE_FLAGS, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if stat.S_ISREG(info.st_mode):
                if info.st_nlink != 1:
                    raise ValueError('Refusing to chmod a hard-linked file.')
            elif not stat.S_ISDIR(info.st_mode):
                raise ValueError('Only ordinary files and directories can be chmodded.')
            os.fchmod(fd, mode)
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def ensure_file(path, mode=0o600):
    """Create/verify an ordinary single-link file and set mode on that same fd."""
    with open_file(path, 'ab') as stream:
        os.fchmod(stream.fileno(), mode)


def _deletion_allowed(name, generated, approved_names):
    if approved_names is not None and name in approved_names:
        return True
    return generated and bool(_UPLOAD_NAME.fullmatch(name) or _TEMP_NAME.fullmatch(name)
                              or _LAST_NAME.fullmatch(name))


def unlink_fd(directory_fd, name, missing_ok=False, generated=False, approved_names=None):
    """Delete one regular file by pinned parent fd after caller proves ownership."""
    name = _entry(name)
    if not _deletion_allowed(name, generated, approved_names):
        raise PermissionError('Deletion requires a Hub-generated name or approved_names.')
    try:
        info = stat_fd(directory_fd, name)
    except FileNotFoundError:
        if missing_ok:
            return
        raise
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Only ordinary files can be deleted.')
    os.unlink(name, dir_fd=directory_fd)


def unlink(path, missing_ok=False, generated=False, approved_names=None):
    parent, name = _parent(path)
    try:
        unlink_fd(parent, name, missing_ok=missing_ok, generated=generated,
                  approved_names=approved_names)
    finally:
        os.close(parent)


def rmdir(path):
    """Remove one empty directory by pinned parent; never follow a symlink."""
    parent, name = _parent(path)
    try:
        info = stat_fd(parent, name)
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError('Only a real directory can be removed.')
        os.rmdir(name, dir_fd=parent)
    finally:
        os.close(parent)


def rename(source, target):
    source_parent, source_name = _parent(source)
    try:
        target_parent, target_name = _parent(target)
        try:
            source_info = stat_fd(source_parent, source_name)
            if stat.S_ISLNK(source_info.st_mode):
                raise ValueError('Refusing to rename a symlink.')
            try:
                target_info = stat_fd(target_parent, target_name)
            except FileNotFoundError:
                target_info = None
            if target_info is not None:
                if stat.S_ISLNK(target_info.st_mode):
                    raise ValueError('Refusing a symlink destination.')
                if stat.S_ISREG(target_info.st_mode) and target_info.st_nlink != 1:
                    raise ValueError('Refusing a hard-linked destination.')
            os.rename(source_name, target_name, src_dir_fd=source_parent,
                      dst_dir_fd=target_parent)
        finally:
            os.close(target_parent)
    finally:
        os.close(source_parent)


def validate_data_tree(data):
    """Startup guard for managed data: recursively reject directory symlinks.

    Broken links are rejected too.  A symlink to a regular media/export file is
    allowed here, but every subsequent helper read still refuses to follow it.
    """
    root = open_directory(data)
    try:
        def walk(fd):
            for name in os.listdir(fd):
                info = stat_fd(fd, name)
                if stat.S_ISLNK(info.st_mode):
                    if name in _MANAGED_DIRECTORY_NAMES:
                        raise ValueError('Managed data contains a symlinked directory: ' + name)
                    # lstat cannot tell a broken link from a directory link; reject
                    # broken links and all links in directories to avoid ambiguity.
                    try:
                        target = os.stat(name, dir_fd=fd)
                    except (FileNotFoundError, OSError):
                        raise ValueError('Managed data contains a broken symlink: ' + name)
                    if stat.S_ISDIR(target.st_mode):
                        raise ValueError('Managed data contains a symlinked directory: ' + name)
                elif stat.S_ISDIR(info.st_mode):
                    child = os.open(name, _DIR_FLAGS, dir_fd=fd)
                    try:
                        walk(child)
                    finally:
                        os.close(child)
        walk(root)
    finally:
        os.close(root)


@contextmanager
def _merge_parent(root_fd, parts, create=False):
    fd = os.dup(root_fd)
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextmanager
def prepare_merge(tree, main, changes):
    """Pin source files and destination parents for a whole worktree merge."""
    with ExitStack() as stack:
        source_root = open_directory(tree)
        stack.callback(os.close, source_root)
        dest_root = open_directory(main)
        stack.callback(os.close, dest_root)
        prepared = []
        for name, deleted in changes:
            parts = name.split('/')
            if any(p in ('', '.', '..') or p.casefold() == '.git' for p in parts):
                raise ValueError('Unsafe changed file.')
            source = None
            if not deleted:
                parent = stack.enter_context(_merge_parent(source_root, parts[:-1]))
                fd = _open_fd(parent, parts[-1], 'rb')
                source = stack.enter_context(os.fdopen(fd, 'rb'))
            try:
                dest = stack.enter_context(_merge_parent(dest_root, parts[:-1], create=not deleted))
            except FileNotFoundError:
                if deleted:
                    continue
                raise
            # A hard-linked destination is safe here: apply_merge replaces its
            # directory entry without writing through the shared inode.
            _existing_regular(dest, parts[-1], mutable=False)
            prepared.append((dest, parts[-1], source))
        yield prepared


def apply_merge(prepared):
    """Apply prepared worktree changes while their context still owns all fds."""
    for parent, name, source in prepared:
        if source is None:
            # A leaf replaced after preparation may be a symlink.  Unlinking the
            # directory entry itself does not follow it or touch its target.
            try:
                info = stat_fd(parent, name)
            except FileNotFoundError:
                continue
            if stat.S_ISDIR(info.st_mode):
                raise ValueError('Refusing to delete a directory during merge.')
            os.unlink(name, dir_fd=parent)
            continue
        source.seek(0)
        mode = stat.S_IMODE(os.fstat(source.fileno()).st_mode) & 0o777
        temporary = '.hub-merge-' + secrets.token_hex(16)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _FILE_FLAGS,
                     0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, 'wb') as output:
                shutil.copyfileobj(source, output)
                os.fchmod(output.fileno(), mode)
                output.flush()
                os.fsync(output.fileno())
            # Replacing a symlink or hard link mutates only this pinned directory
            # entry.  Neither target nor another hard link's inode is written.
            try:
                info = stat_fd(parent, name)
            except FileNotFoundError:
                info = None
            if info is not None and stat.S_ISDIR(info.st_mode):
                raise ValueError('Destination changed to a directory.')
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


def symlink(path, target):
    """Create Hub's one intentional link: isolated Codex auth.json.

    The target must be an absolute, ordinary auth file.  Existing entries are
    never replaced.  Other Hub paths remain subject to the no-symlink policy.
    """
    parent, name = _parent(path)
    try:
        if name != 'auth.json' or not os.path.isabs(os.fspath(target)):
            raise ValueError('Only an absolute Codex auth.json link is allowed.')
        with open_file(target, 'rb'):
            pass
        os.symlink(os.fspath(target), name, dir_fd=parent)
    finally:
        os.close(parent)


class SQLiteFileGuard:
    """Hold the DB directory and check SQLite's ordinary file entries.

    Python's sqlite3 opens by pathname, so this is a fail-closed startup/per-call
    guard, not a race-free replacement for a custom SQLite VFS.
    """

    def __init__(self, directory, filename='hub.sqlite3'):
        self.directory = os.fspath(directory)
        self.directory_fd = open_directory(directory)
        self.filename = _entry(filename)
        try:
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self):
        current_fd = open_directory(self.directory)
        try:
            pinned = os.fstat(self.directory_fd)
            current = os.fstat(current_fd)
            if (pinned.st_dev, pinned.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError('SQLite directory path changed after startup.')
        finally:
            os.close(current_fd)
        for suffix in ('', '-wal', '-shm', '-journal'):
            name = self.filename + suffix
            try:
                info = stat_fd(self.directory_fd, name)
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('Unsafe SQLite file: ' + name)

    def connect(self, **options):
        """Open through the guarded native SQLite boundary (see class caveat)."""
        import sqlite3
        self.check()
        connection = sqlite3.connect(str(Path(self.directory) / self.filename), **options)
        try:
            self.check()
        except BaseException:
            connection.close()
            raise
        return connection

    def close(self):
        if self.directory_fd is not None:
            os.close(self.directory_fd)
            self.directory_fd = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
