"""Reusable in-memory double for the Redis client.

The Execution Server caches step/execution state in Redis. Unit tests must not
open real Redis connections (UNIT_TEST_PLAN.md Phase 6), so this module provides
a minimal in-memory stand-in supporting the operations the source uses.
"""

from unittest.mock import MagicMock


class FakeRedis:
    """Minimal in-memory implementation of the ``redis.StrictRedis`` subset used
    by ``ingenium_library`` (get/set/hset/hget/hgetall/delete/exists)."""

    def __init__(self):
        self.store = {}
        self.hashes = {}

    # --- simple key/value ---------------------------------------------------
    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        # ``ex`` (expiry seconds) is accepted for API-compatibility; this
        # in-memory double does not expire keys.
        self.store[key] = value
        return True

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                removed += 1
            if key in self.hashes:
                del self.hashes[key]
                removed += 1
        return removed

    def exists(self, key):
        return int(key in self.store or key in self.hashes)

    # --- hash operations ----------------------------------------------------
    def hset(self, name, key=None, value=None, mapping=None):
        bucket = self.hashes.setdefault(name, {})
        if mapping:
            bucket.update(mapping)
        if key is not None:
            bucket[key] = value
        return 1

    def hget(self, name, key):
        return self.hashes.get(name, {}).get(key)

    def hgetall(self, name):
        return dict(self.hashes.get(name, {}))

    def hmset(self, name, mapping):
        self.hashes.setdefault(name, {}).update(mapping)
        return True

    def hmget(self, name, keys):
        bucket = self.hashes.get(name, {})
        # Real redis returns bytes; encode stored strings to mirror that so the
        # source's ``.decode('utf-8')`` calls behave identically.
        result = []
        for key in keys:
            value = bucket.get(key)
            if isinstance(value, str):
                value = value.encode("utf-8")
            result.append(value)
        return result


def make_redis_mock():
    """Return a ``MagicMock`` backed by :class:`FakeRedis` semantics.

    Using a MagicMock (rather than the bare FakeRedis) lets tests assert calls
    while still getting functional get/set behavior.
    """
    fake = FakeRedis()
    mock = MagicMock(name="StrictRedis", wraps=fake)
    return mock
