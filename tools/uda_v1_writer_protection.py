"""Cooperative legacy writer protection, not mandatory OS-wide exclusion.

The operator must independently freeze manual and external writers, review
uninspectable processes and maintain that freeze until service restoration.
Existing V1 opens its lock with truncation and writes status after unlocking;
holding its flock is supplementary, not a substitute for the freeze.
"""
from contextlib import contextmanager, ExitStack
import fcntl
import os
from pathlib import Path
import stat

from deploy_agent import load_config
from tools.uda_production_backup_scope import scope, process_indicators
from tools.uda_production_admission import directory_review


def legacy_paths(home):
    roots = scope(home)
    config = load_config(roots["config"] / "config.json")
    if "lock_file" not in config:
        raise ValueError("Explicit legacy lock path required")
    path = Path(config["lock_file"]).expanduser()
    if path != roots["state"] / "deploy.lock":
        raise ValueError("Unexpected legacy deployment lock path")
    return (path, roots["state"] / "proxy-migration.lock")


def identity(path, fd):
    info = os.fstat(fd)
    current = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1 or info.st_mode & 0o002
            or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)):
        raise ValueError("Unsafe or replaced legacy lock: " + str(path))
    if any(k.startswith("system.posix_acl_") for k in os.listxattr(fd)):
        raise ValueError("Legacy lock ACL requires review")
    return (info.st_dev, info.st_ino)


@contextmanager
def hold(home, operator_freeze, process_review):
    """Lock existing legacy files only; never create, truncate or unlink them.

    Both callbacks must be independently established. process_review receives
    the entire current scan, including uninspectable process findings; it
    must refuse unexplained access. No PID allowlist is inferred here.
    """
    paths = legacy_paths(home)
    if operator_freeze() is not True:
        raise ValueError("Independent operator freeze missing")
    with ExitStack() as stack:
        locks = []
        for path in paths:
            directory_review(path.parent)
            fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
            stack.callback(os.close, fd)
            expected = identity(path, fd)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("Legacy worker lock busy: " + path.name) from exc
            locks.append((path, fd, expected))
        active = True
        def guard():
            if not active:
                raise ValueError("Legacy protection no longer held")
            if operator_freeze() is not True:
                raise ValueError("Independent operator freeze lost")
            if legacy_paths(home) != paths:
                raise ValueError("Legacy lock configuration drift")
            for path, fd, expected in locks:
                if identity(path, fd) != expected:
                    raise ValueError("Legacy lock identity drift")
            report = process_indicators(scope(home))
            if process_review(report) is not True:
                raise ValueError("Unresolved protected-storage process indicators")
            return True
        try:
            guard()
            yield guard
        finally:
            active = False
