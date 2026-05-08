"""Exponential backoff retry."""
from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

from .logging_setup import get_logger

T = TypeVar("T")
log = get_logger(__name__)


class RateLimitError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def with_backoff(
    attempts: int = 3,
    base_delay: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = (RateLimitError,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            last: BaseException | None = None
            for i in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:
                    last = e
                    delay = base_delay * (2**i)
                    log.warning(
                        "Retry %d/%d for %s after %.1fs: %s",
                        i + 1,
                        attempts,
                        fn.__name__,
                        delay,
                        e,
                    )
                    time.sleep(delay)
            assert last is not None
            raise last

        return wrapper

    return decorator
