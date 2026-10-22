"""Private installation records and backed-up, exact hook-file edits."""
import json
import os
from pathlib import Path
import hashlib
import stat
from copy import deepcopy
from contextlib import contextmanager, ExitStack, nullcontext
import secrets
import sys
import fcntl
import errno
from ..domain.errors import ChatChanged, NotAvailable
from ..ports.setup_install import HookChange, InstallRefused
from .hook_json import read, rewrite


def checked(path):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        if parent.is_symlink(): raise InstallRefused()
    if path.exists():
        mode = path.stat()
        if not stat.S_ISREG(mode.st_mode) or mode.st_nlink != 1: raise InstallRefused()
    return path


@contextmanager
def directory(path, create=False):
    """Walk from the filesystem root using pinned, no-follow directories."""
    path = Path(path).absolute()
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            if create:
                try: os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError: pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    except OSError:
        raise InstallRefused() from None
    finally:
        os.close(descriptor)


def snapshot(descriptor, name):
    try: handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
    except FileNotFoundError: return None, None
    try:
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: raise InstallRefused()
        with os.fdopen(os.dup(handle), 'rb') as stream: data = stream.read()
        return data, info
    finally: os.close(handle)


def permission_mode(descriptor, name, info):
    if info is None: return 0o600
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
    try:
        # Refuse ACL-bearing files; extended attributes are copied and verified.
        if sys.platform == 'darwin':
            import ctypes
            libc = ctypes.CDLL(None, use_errno=True)
            libc.acl_get_fd_np.restype = ctypes.c_void_p
            acl = libc.acl_get_fd_np(handle, 0x100)
            if not acl:
                if ctypes.get_errno() != errno.ENOENT: raise InstallRefused()
            else:
                libc.acl_free(ctypes.c_void_p(acl))
                raise InstallRefused()
        if sys.platform != 'darwin' and not hasattr(os, 'listxattr'): raise InstallRefused()
        if info.st_uid != os.getuid() or info.st_gid not in os.getgroups() + [os.getgid()]:
            raise InstallRefused()
        return stat.S_IMODE(info.st_mode)
    finally: os.close(handle)


# macOS stamps every file with the writing app's provenance; no app can set or keep
# it, so it is neither copied nor compared. Every other attribute must survive.
SYSTEM_ATTRIBUTES = frozenset({'com.apple.provenance', b'com.apple.provenance'})


def attributes(descriptor, name):
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
    try:
        if sys.platform != 'darwin':
            return tuple(sorted((n, os.getxattr(handle, n)) for n in os.listxattr(handle) if n not in SYSTEM_ATTRIBUTES))
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        libc.flistxattr.restype = libc.fgetxattr.restype = ctypes.c_ssize_t
        size = libc.flistxattr(handle, None, 0, 0)
        if size < 0: raise InstallRefused()
        names = ctypes.create_string_buffer(size)
        if libc.flistxattr(handle, names, size, 0) != size: raise InstallRefused()
        result = []
        for n in names.raw.split(b'\0'):
            if not n or n in SYSTEM_ATTRIBUTES: continue
            length = libc.fgetxattr(handle, n, None, 0, 0, 0)
            if length < 0: raise InstallRefused()
            value = ctypes.create_string_buffer(length)
            if libc.fgetxattr(handle, n, value, length, 0, 0) != length: raise InstallRefused()
            result.append((n, value.raw))
        return tuple(sorted(result))
    finally: os.close(handle)


def copy_attributes(source, destination):
    if sys.platform != 'darwin':
        for name in os.listxattr(source):
            if name not in SYSTEM_ATTRIBUTES: os.setxattr(destination, name, os.getxattr(source, name))
        return
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    libc.flistxattr.restype = libc.fgetxattr.restype = ctypes.c_ssize_t
    size = libc.flistxattr(source, None, 0, 0)
    if size < 0: raise InstallRefused()
    names = ctypes.create_string_buffer(size)
    if libc.flistxattr(source, names, size, 0) != size: raise InstallRefused()
    for name in names.raw.split(b'\0'):
        if not name or name in SYSTEM_ATTRIBUTES: continue
        length = libc.fgetxattr(source, name, None, 0, 0, 0)
        if length < 0: raise InstallRefused()
        value = ctypes.create_string_buffer(length)
        if libc.fgetxattr(source, name, value, length, 0, 0) != length: raise InstallRefused()
        if libc.fsetxattr(destination, name, value, length, 0, 0) != 0: raise InstallRefused()


def stage(descriptor, text, mode=0o600, info=None, source=None):
    name = '.baton-' + secrets.token_hex(16)
    handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
    try:
        if info is not None:
            os.fchown(handle, info.st_uid, info.st_gid)
            original = os.open(source, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
            try: copy_attributes(original, handle)
            finally: os.close(original)
        with os.fdopen(os.dup(handle), 'wb') as stream:
            stream.write(text.encode()); stream.flush(); os.fsync(stream.fileno())
        os.fchmod(handle, mode)
        staged = os.fstat(handle)
        if stat.S_IMODE(staged.st_mode) != mode or (info is not None and
                (staged.st_uid, staged.st_gid) != (info.st_uid, info.st_gid)):
            raise InstallRefused()
        permission_mode(descriptor, name, staged)
        if info is not None and attributes(descriptor, name) != attributes(descriptor, source):
            raise InstallRefused()
        os.fsync(handle)
        return name
    except BaseException:
        os.unlink(name, dir_fd=descriptor)
        raise
    finally: os.close(handle)


def atomic(path, text, mode=0o600):
    path = Path(path).absolute()
    with directory(path.parent, create=True) as descriptor:
        name = stage(descriptor, text, mode)
        try:
            snapshot(descriptor, path.name)
            try: os.link(name, path.name, src_dir_fd=descriptor, dst_dir_fd=descriptor, follow_symlinks=False)
            except FileExistsError:
                data, _ = snapshot(descriptor, path.name)
                if data != text.encode(): raise InstallRefused()
            os.fsync(descriptor)
        finally:
            try: os.unlink(name, dir_fd=descriptor)
            except FileNotFoundError: pass


_UNSET = object()


class SetupFiles:
    def __init__(self, root, coordinate=None):
        self.root = Path(root)
        self.coordinate = coordinate

    @property
    def coordination_verified(self):
        return self.coordinate is not None

    def command_available(self, executable):
        if not Path(executable).is_absolute(): return False
        path = checked(executable)
        return path.is_absolute() and path.is_file() and os.access(path, os.X_OK)

    def record_path(self, tool):
        if not tool or not all(c.isalnum() or c in '_-' for c in tool): raise InstallRefused()
        return checked(self.root / 'hook-installs' / (tool + '.json'))

    def record_source(self, tool):
        path = self.record_path(tool)
        if not path.exists(): return None
        try:
            with directory(path.parent) as descriptor:
                data, _ = snapshot(descriptor, path.name)
            if data is None: raise InstallRefused()
            return data.decode()
        except (OSError, UnicodeError): raise InstallRefused() from None

    def recorded(self, tool):
        source = self.record_source(tool)
        if source is None: return None
        try:
            record = read(source)
            if set(record) != {'executable', 'path'} or not all(isinstance(v, str) and Path(v).is_absolute() for v in record.values()):
                raise ValueError()
            return record
        except (OSError, ValueError): raise InstallRefused() from None

    def prepare(self, hooks, executable, removing):
        try:
            path = checked(hooks.path)
        except (NotAvailable, ValueError, OSError):
            raise InstallRefused() from None
        try:
            if path.exists():
                with directory(path.parent) as descriptor:
                    data, info = snapshot(descriptor, path.name)
                    if data is None: raise InstallRefused()
                    permission_mode(descriptor, path.name, info)
                before = data.decode('utf-8')
            else: before = None
        except (OSError, UnicodeError):
            raise InstallRefused() from None
        entries = hooks.install_entries(executable)
        if isinstance(entries, str):
            if before is not None and before != entries: raise InstallRefused()
            after = None if removing else entries
        else:
            try:
                settings = read(before) if before is not None else deepcopy(hooks.install_defaults)
                if removing and 'hooks' not in settings:
                    return HookChange(str(path), before, before, entries)
                identities = {}
                def identify(value, location=()):
                    if isinstance(value, (dict, list)):
                        identities[id(value)] = location
                        for key, item in (value.items() if isinstance(value, dict) else enumerate(value)):
                            identify(item, (*location, key))
                identify(settings)
                current = settings.setdefault('hooks', {})
                if not isinstance(current, dict): raise ValueError()
                for event, owned in entries.items():
                    values = current.get(event, [])
                    if not isinstance(values, list) or not all(isinstance(v, dict) for v in values): raise ValueError()
                    if removing and not values: continue
                    if hooks.install_nested:
                        for entry in values:
                            if not isinstance(entry.get('hooks', []), list) or not all(isinstance(h, dict) for h in entry.get('hooks', [])): raise ValueError()
                        command = owned['hooks'][0]['command']
                        if removing:
                            kept = []
                            for entry in values:
                                other = [h for h in entry.get('hooks', []) if h != owned['hooks'][0]]
                                if other == entry.get('hooks', []): kept.append(entry)
                                elif other:
                                    survivor = {**entry, 'hooks': other}
                                    identities[id(survivor)] = identities[id(entry)]
                                    kept.append(survivor)
                            current[event] = kept
                        elif not any(h.get('command') == command for entry in values for h in entry.get('hooks', [])):
                            current[event] = [*values, owned]
                    elif removing:
                        current[event] = [v for v in values if v != owned]
                    elif owned not in values:
                        current[event] = [*values, owned]
                    if removing and current.get(event) == []: current.pop(event, None)
                after = rewrite(before, settings, identities) if before is not None else (None if removing else json.dumps(settings, indent=2) + '\n')
            except (ValueError, TypeError, KeyError): raise InstallRefused() from None
        return HookChange(str(path), before, after, entries)

    def backup_path(self, tool, change):
        digest = hashlib.sha256((change.path + '\0' + change.before).encode()).hexdigest()
        return checked(self.root / 'hook-backups' / (tool + '-' + digest + '.bak'))

    def details(self, tool, executable, change, removing):
        path = self.record_path(tool)
        record = {'executable': executable, 'path': change.path}
        record_source = self.record_source(tool)
        record_after = None if removing else json.dumps(record)
        result = [{'path': str(path), 'action': 'unchanged' if record_source == record_after else
                   'remove' if removing else 'create' if record_source is None else 'change', 'entries': [] if removing else record}]
        if change.before is not None and change.before != change.after:
            backup = self.backup_path(tool, change)
            result.append({'path': str(backup), 'action': 'unchanged' if backup.exists() else 'create', 'entries': []})
        if record_source is not None and record_source != record_after:
            backup = self.backup_path(tool, HookChange(str(path), record_source, record_after, []))
            result.append({'path': str(backup), 'action': 'unchanged' if backup.exists() else 'create', 'entries': []})
        return result

    def apply(self, tool, executable, change, removing, record_before=None, record_source=_UNSET, before_write=None):
        if before_write is not None: before_write()
        try:
            with self.coordinate(change.path) if self.coordinate else nullcontext():
                return self._apply(tool, executable, change, removing, record_before, record_source, before_write)
        except OSError: raise InstallRefused() from None

    def _apply(self, tool, executable, change, removing, record_before, record_source=_UNSET, before_write=None):
        path = Path(change.path)
        record = self.record_path(tool)
        record_text = None if removing else json.dumps({'executable': executable, 'path': change.path})
        backups = []
        with ExitStack() as stack:
            target_fd = stack.enter_context(directory(path.parent, create=True))
            record_fd = stack.enter_context(directory(record.parent, create=True))
            # Cooperative writers must hold flock on the existing configuration
            # inode throughout their write; directory locks serialize installers.
            for descriptor in sorted({target_fd, record_fd}):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            old, info = snapshot(target_fd, path.name)
            old_record, record_info = snapshot(record_fd, record.name)
            if old != (change.before.encode() if change.before is not None else None): raise ChatChanged()
            try: parsed = read(old_record.decode()) if old_record is not None else None
            except (ValueError, UnicodeError): raise ChatChanged() from None
            if parsed != record_before: raise ChatChanged()
            if record_source is not _UNSET and old_record != (record_source.encode() if record_source is not None else None): raise ChatChanged()
            if info is not None:
                handle = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=target_fd)
                stack.callback(os.close, handle)
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            publications = []
            permission_attributes = {}
            for location, descriptor, name, before, after, metadata in (
                (path, target_fd, path.name, old, change.after, info),
                (record, record_fd, record.name, old_record, record_text, record_info)):
                if before == (after.encode() if after is not None else None): continue
                mode = permission_mode(descriptor, name, metadata)
                permission_attributes[location] = attributes(descriptor, name) if metadata is not None else None
                replacement = stage(descriptor, after, mode, metadata, name) if after is not None else None
                rollback = stage(descriptor, before.decode(), mode, metadata, name) if before is not None else None
                for temporary in (replacement, rollback):
                    if temporary is not None:
                        def cleanup(d=descriptor, n=temporary):
                            try: os.unlink(n, dir_fd=d)
                            except FileNotFoundError: pass
                        stack.callback(cleanup)
                publications.append((location, descriptor, name, before, after, metadata, replacement, rollback))
            for location, _, _, before, _, _, _, _ in publications:
                if before is not None:
                    backup_change = HookChange(str(location), before.decode(), None, [])
                    backup = self.backup_path(tool, backup_change)
                    if backup.exists():
                        with directory(backup.parent) as descriptor:
                            saved, _ = snapshot(descriptor, backup.name)
                        if saved != before: raise InstallRefused()
                    else: atomic(backup, before.decode())
                    backups.append(str(backup))
            def revalidate(items):
                for location, descriptor, name, before, _, metadata, _, _ in items:
                    with directory(location.parent) as fresh:
                        if os.fstat(fresh).st_ino != os.fstat(descriptor).st_ino or os.fstat(fresh).st_dev != os.fstat(descriptor).st_dev:
                            raise ChatChanged()
                    data, current = snapshot(descriptor, name)
                    if current is not None:
                        permission_mode(descriptor, name, current)
                        if attributes(descriptor, name) != permission_attributes[location]: raise ChatChanged()
                    if (current is None) != (metadata is None): raise ChatChanged()
                    if data != before or (current is not None and metadata is not None and
                            (current.st_dev, current.st_ino, current.st_mode, current.st_uid, current.st_gid) !=
                            (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_uid, metadata.st_gid)):
                        raise ChatChanged()
            revalidate(publications)
            # Publish durable ownership first: interruption can leave a harmless
            # ownership record, but never changed hooks without their location.
            publications.sort(key=lambda item: item[0] == record if removing else item[0] != record)
            completed = []
            try:
                for item in publications:
                    if before_write is not None: before_write()
                    revalidate([item])
                    _, descriptor, name, _, after, _, replacement, _ = item
                    published = snapshot(descriptor, replacement)[1] if replacement is not None else None
                    published_attributes = attributes(descriptor, replacement) if replacement is not None else None
                    if after is None: os.unlink(name, dir_fd=descriptor)
                    else: os.replace(replacement, name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
                    completed.append((item, published, published_attributes))
                    os.fsync(descriptor)
            except BaseException:
                for item, published, published_attributes in reversed(completed):
                    location, descriptor, name, _, after, _, _, rollback = item
                    if before_write is not None: before_write()
                    permission_attributes[location] = published_attributes
                    revalidate([(location, descriptor, name,
                                 after.encode() if after is not None else None,
                                 None, published, None, None)])
                    if rollback is None: os.unlink(name, dir_fd=descriptor)
                    else: os.replace(rollback, name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
                    os.fsync(descriptor)
                raise
        return backups
