"""Cross-platform exclusive lock used by ``run`` and ``restore``."""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager

from idle_shutdown.config import ensure_app_dirs, lock_path
from idle_shutdown.errors import AlreadyRunningError


@contextmanager
def acquire_single_instance():  # type: ignore[no-untyped-def]
    ensure_app_dirs()
    path = lock_path()
    fh = open(path, "a+b")
    try:
        if sys.platform == "win32":  # pragma: no cover - Windows only
            import msvcrt
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as e:
                fh.close()
                raise AlreadyRunningError(
                    f"another instance holds {path}"
                ) from e
        else:
            import fcntl
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as e:
                fh.close()
                raise AlreadyRunningError(
                    f"another instance holds {path}"
                ) from e
        try:
            fh.seek(0)
            fh.truncate()
            fh.write(str(os.getpid()).encode())
            fh.flush()
            yield path
        finally:
            try:
                if sys.platform == "win32":  # pragma: no cover
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()
    except AlreadyRunningError:
        raise