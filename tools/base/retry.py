import random
import time
from typing import Callable, TypeVar

from tools.base.exceptions import ToolError

T = TypeVar("T")


class RetryPolicy:
    def __init__(self, max_retries: int = 3, base_delay: float = 0.5, max_delay: float = 4.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def run(self, fn: Callable[[], T]) -> T:
        attempt = 0
        last_error = None

        while attempt <= self.max_retries:
            try:
                return fn()
            except ToolError as e:
                last_error = e
                if not e.retryable or attempt == self.max_retries:
                    raise
                delay = min(self.max_delay, self.base_delay * (2 ** attempt))
                delay = delay * (0.8 + random.random() * 0.4)  # jitter
                time.sleep(delay)
                attempt += 1

        if last_error:
            raise last_error
        raise ToolError("Retry failed")