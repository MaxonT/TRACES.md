"""What: crash-safe file helpers: atomic write, a lock file with backoff, and trace directory discovery.
Why: a crash must never leave a half-written trace, and two agents appending at once must not lose a step.
How: atomic_write(path, text); with file_lock(path): ...; find_trace_dir(). All stdlib.
"""
from __future__ import annotations

import os
import random
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional


class TracesIOError(Exception):
    """A file operation failed; the CLI maps it to exit code 3."""


class LockTimeout(TracesIOError):
    pass


def atomic_write(path, text: str) -> None:
    """Write text to path via a temp file in the same directory, fsync, then rename."""
    p = Path(path)
    tmp = p.with_name(".%s.tmp.%d" % (p.name, os.getpid()))
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except OSError as e:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise TracesIOError("cannot write %s: %s" % (p, e))
    try:  # best effort: make the rename durable
        fd = os.open(str(p.parent), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


@contextmanager
def file_lock(path, timeout: float = 10.0, stale: float = 60.0) -> Iterator[None]:
    """Exclusive lock for appending to path. Exponential backoff, hard timeout, stale reclaim."""
    lock = Path(str(path) + ".lock")
    deadline = time.monotonic() + timeout
    delay = 0.005
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > stale:
                    lock.unlink()
                    continue
            except OSError:
                continue
            if time.monotonic() >= deadline:
                raise LockTimeout("could not lock %s within %.0fs (held by another process; "
                                  "if it is stale, delete %s)" % (path, timeout, lock))
            time.sleep(delay + random.random() * delay)
            delay = min(delay * 2, 0.25)
        except OSError as e:
            raise TracesIOError("cannot create lock %s: %s" % (lock, e))
    try:
        yield
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def find_trace_dir(start: Optional[str] = None) -> Optional[Path]:
    """TRACES_DIR, else the nearest .trace/ walking up from start, else ~/.ai-sync/traces."""
    env = os.environ.get("TRACES_DIR")
    if env:
        return Path(env).expanduser()
    here = Path(start or os.getcwd()).resolve()
    for d in [here] + list(here.parents):
        if (d / ".trace").is_dir():
            return d / ".trace"
    central = Path.home() / ".ai-sync" / "traces"
    return central if central.is_dir() else None


def newest_trace(directory: Path) -> Optional[Path]:
    from . import model
    files = [p for p in directory.iterdir()
             if p.is_file() and model.split_name(p.name)]
    return max(files, key=lambda p: (p.stat().st_mtime, p.name)) if files else None
