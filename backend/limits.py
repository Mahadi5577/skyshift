"""Per-client request limits for a public server.

Archive-heavy requests (name lookups, archive searches, new downloads, SkyBoT) share one small
budget; everything else (status polls, frames, Hunt) gets a budget 20 times larger, which a person
using the app never reaches. Clients are told how long to wait in a Retry-After header.
"""
import math
import threading
import time

from fastapi import HTTPException, Request


class RateLimiter:
    """Token bucket per client: `per_minute` sustained, bursts of up to `burst` requests."""

    def __init__(self, per_minute, burst=None):
        self.rate = per_minute / 60
        self.burst = burst or max(1, per_minute // 2)
        self._buckets = {}
        self._lock = threading.Lock()

    def wait(self, key, now=None):
        """Take one token for `key`. Returns 0 if allowed, else the seconds until one is free."""
        if self.rate <= 0:
            return 0
        now = time.monotonic() if now is None else now
        with self._lock:
            if len(self._buckets) > 10_000:  # forget clients whose buckets have refilled
                full = self.burst / self.rate
                self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < full}
            tokens, last = self._buckets.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens < 1:
                self._buckets[key] = (tokens, now)
                return (1 - tokens) / self.rate
            self._buckets[key] = (tokens - 1, now)
            return 0


def client(request: Request):
    # Behind a proxy, uvicorn puts the X-Forwarded-For address here (see FORWARDED_ALLOW_IPS).
    return request.client.host if request.client else "unknown"


def dependency(limiter, what):
    def check(request: Request):
        wait = limiter.wait(client(request))
        if wait:
            raise HTTPException(429, f"Too many {what} from your address: please wait {math.ceil(wait)} s",
                                headers={"Retry-After": str(math.ceil(wait))})
    return check
