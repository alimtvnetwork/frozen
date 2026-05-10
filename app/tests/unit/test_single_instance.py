import pytest

from idle_shutdown.errors import AlreadyRunningError
from idle_shutdown.single_instance import acquire_single_instance


def test_lock_releases_after_context(temp_db):
    with acquire_single_instance() as p:
        assert p.exists()
    # second acquisition should now succeed
    with acquire_single_instance():
        pass


def test_concurrent_acquire_raises(temp_db):
    with acquire_single_instance():
        with pytest.raises(AlreadyRunningError):
            with acquire_single_instance():
                pass