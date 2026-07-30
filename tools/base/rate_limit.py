import time
import threading
from tools.base.exceptions import RateLimitError


class TokenBucketRateLimiter:
    """
    Simple in-process rate limiter.
    For multi-process production, replace with Redis-backed limiter.
    """

    def __init__(self, rate_per_sec: float, burst: int):
        self.rate = rate_per_sec
        self.capacity = burst
        self.tokens = float(burst)
        self.updated_at = time.time()
        self.lock = threading.Lock()

    def acquire(self, tokens: float = 1.0):
        with self.lock:
            now = time.time()
            elapsed = now - self.updated_at
            self.updated_at = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

            if self.tokens >= tokens:
                self.tokens -= tokens
                return

            raise RateLimitError("Local rate limit exceeded")