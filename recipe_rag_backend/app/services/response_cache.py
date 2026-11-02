from collections import OrderedDict
import hashlib
import json
from copy import deepcopy
from threading import Lock
from time import monotonic

from app.core.config import settings


def model_cache_key(model, *values):
    configuration = {"instance": id(model)}
    for field in ("model_name", "temperature", "max_tokens", "n", "model_kwargs"):
        value = getattr(model, field, None)
        if isinstance(value, (str, int, float, bool, dict)):
            configuration[field] = value
    return hashlib.sha256(json.dumps([configuration, *values], sort_keys=True, default=str).encode()).hexdigest()


class ResponseCache:
    def __init__(self, ttl=None, capacity=None, clock=monotonic):
        self.ttl = settings.RECIPE_CACHE_TTL_SECONDS if ttl is None else ttl
        self.capacity = settings.RECIPE_CACHE_MAX_ENTRIES if capacity is None else capacity
        self.clock = clock
        self.entries = OrderedDict()
        self.lock = Lock()
        self.hits = 0
        self.misses = 0

    def _expire(self):
        now = self.clock()
        for key, (expires, _) in list(self.entries.items()):
            if expires <= now:
                del self.entries[key]

    def get(self, key):
        with self.lock:
            self._expire()
            entry = self.entries.get(key) if self.ttl > 0 else None
            if entry is None:
                self.misses += 1
                return None
            self.hits += 1
            self.entries.move_to_end(key)
            return deepcopy(entry[1])

    def put(self, key, value):
        if self.ttl <= 0 or self.capacity <= 0:
            return
        with self.lock:
            self._expire()
            self.entries[key] = (self.clock() + self.ttl, deepcopy(value))
            self.entries.move_to_end(key)
            while len(self.entries) > self.capacity:
                self.entries.popitem(last=False)

    def discard(self, key):
        with self.lock:
            self.entries.pop(key, None)

    def clear(self):
        with self.lock:
            self.entries.clear()
            self.hits = 0
            self.misses = 0

    def stats(self):
        with self.lock:
            self._expire()
            return {"cache_size": len(self.entries), "cache_hits": self.hits, "cache_misses": self.misses,
                    "ttl_seconds": self.ttl, "capacity": self.capacity}
