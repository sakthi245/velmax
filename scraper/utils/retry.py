from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union

from tenacity import (
    AsyncRetrying,
    RetryCallState,
    RetryError,
    before_sleep_log,
    retry_if_exception_type,
    retry_if_result,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential_jitter,
    wait_fixed,
    wait_random,
)
from tenacity.stop import stop_base
from tenacity.wait import wait_base


logger = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    jitter_factor: float = 0.1
    retryable_status_codes: Set[int] = field(default_factory=lambda: {408, 429, 500, 502, 503, 504})
    retryable_exceptions: List[str] = field(default_factory=lambda: [
        "TimeoutError",
        "ConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
        "ProxyError",
        "SSLError",
        "TooManyRedirects",
        "ClientError",
        "ServerDisconnectedError",
        "ClientResponseError",
    ])
    retryable_error_patterns: List[str] = field(default_factory=lambda: [
        "timeout",
        "connection",
        "refused",
        "reset",
        "aborted",
        "temporary",
        "unavailable",
        "overloaded",
    ])
    stop_on_status: Set[int] = field(default_factory=lambda: {400, 401, 403, 404})
    max_total_delay: float = 300.0

    def get_retryable_exceptions(self) -> Tuple[Type[BaseException], ...]:
        exception_types = []
        for exc_name in self.retryable_exceptions:
            try:
                if exc_name == "TimeoutError":
                    exception_types.append(TimeoutError)
                elif exc_name == "ConnectionError":
                    exception_types.append(ConnectionError)
                else:
                    exc_cls = getattr(__import__("builtins"), exc_name, None)
                    if exc_cls is None:
                        exc_cls = getattr(__import__("aiohttp", fromlist=[""]), exc_name, None)
                    if exc_cls is None:
                        exc_cls = getattr(__import__("httpx", fromlist=[""]), exc_name, None)
                    if exc_cls:
                        exception_types.append(exc_cls)
            except (ImportError, AttributeError):
                pass
        return tuple(exception_types) if exception_types else (Exception,)

    def is_retryable_status(self, status_code: int) -> bool:
        return status_code in self.retryable_status_codes

    def is_stop_status(self, status_code: int) -> bool:
        return status_code in self.stop_on_status

    def is_retryable_error(self, error: str) -> bool:
        error_lower = error.lower()
        return any(pattern in error_lower for pattern in self.retryable_error_patterns)

    def create_wait_strategy(self) -> wait_base:
        if self.jitter:
            return wait_exponential_jitter(
                initial=self.base_delay,
                max=self.max_delay,
                jitter=self.jitter_factor,
            )
        return wait_fixed(self.base_delay)

    def create_stop_strategy(self) -> stop_base:
        return stop_after_attempt(self.max_attempts) | stop_after_delay(self.max_total_delay)

    def create_retryer(self, **kwargs) -> AsyncRetrying:
        return AsyncRetrying(
            wait=self.create_wait_strategy(),
            stop=self.create_stop_strategy(),
            retry=(
                retry_if_exception_type(self.get_retryable_exceptions())
                | retry_if_result(self._is_retryable_result)
            ),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
            **kwargs,
        )

    def _is_retryable_result(self, result: Any) -> bool:
        if hasattr(result, "status_code"):
            return self.is_retryable_status(result.status_code)
        if hasattr(result, "error") and result.error:
            return self.is_retryable_error(result.error)
        return False


class RetryCondition:
    def __init__(
        self,
        retry_on_status: Optional[Set[int]] = None,
        retry_on_exceptions: Optional[Tuple[Type[BaseException], ...]] = None,
        retry_on_result: Optional[Callable[[Any], bool]] = None,
        stop_on_status: Optional[Set[int]] = None,
    ):
        self.retry_on_status = retry_on_status or set()
        self.retry_on_exceptions = retry_on_exceptions or ()
        self.retry_on_result = retry_on_result
        self.stop_on_status = stop_on_status or set()

    def should_retry(self, result: Any) -> bool:
        if self.retry_on_result and self.retry_on_result(result):
            return True

        if hasattr(result, "status_code"):
            if result.status_code in self.stop_on_status:
                return False
            if result.status_code in self.retry_on_status:
                return True

        if hasattr(result, "error") and result.error:
            return True

        return False


class CircuitBreakerRetryPolicy(RetryPolicy):
    def __init__(self, *args, circuit_breaker=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.circuit_breaker = circuit_breaker

    def create_retryer(self, **kwargs) -> AsyncRetrying:
        base_retryer = super().create_retryer(**kwargs)

        original_retry = base_retryer.retry

        def combined_retry(retry_state: RetryCallState) -> bool:
            if self.circuit_breaker and self.circuit_breaker.get_state() == "open":
                return False
            return original_retry(retry_state)

        base_retryer.retry = combined_retry
        return base_retryer


async def execute_with_retry(
    coro_func: Callable,
    *args,
    policy: Optional[RetryPolicy] = None,
    retry_condition: Optional[RetryCondition] = None,
    on_retry: Optional[Callable[[RetryCallState], None]] = None,
    **kwargs,
) -> Any:
    policy = policy or RetryPolicy()

    retryer = policy.create_retryer()

    if on_retry:
        retryer.before_sleep = on_retry

    if retry_condition:
        original_retry = retryer.retry

        def combined_retry(retry_state: RetryCallState) -> bool:
            if retry_state.outcome.failed:
                return original_retry(retry_state)
            return retry_condition.should_retry(retry_state.outcome.result())

        retryer.retry = combined_retry

    try:
        return await retryer(coro_func, *args, **kwargs)
    except RetryError as e:
        raise e.last_attempt.exception()


async def execute_with_retry_async(
    coro_func: Callable,
    *args,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_exceptions: Optional[Tuple[Type[BaseException], ...]] = None,
    retryable_status_codes: Optional[Set[int]] = None,
    **kwargs,
) -> Any:
    policy = RetryPolicy(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=max_delay,
    )
    if retryable_exceptions:
        policy.retryable_exceptions = [e.__name__ for e in retryable_exceptions]
    if retryable_status_codes:
        policy.retryable_status_codes = retryable_status_codes

    return await execute_with_retry(coro_func, *args, policy=policy, **kwargs)


def create_retry_policy(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    jitter_factor: float = 0.1,
    retryable_status_codes: Optional[Set[int]] = None,
    retryable_exceptions: Optional[List[str]] = None,
    stop_on_status: Optional[Set[int]] = None,
) -> RetryPolicy:
    return RetryPolicy(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        jitter=jitter,
        jitter_factor=jitter_factor,
        retryable_status_codes=retryable_status_codes or {408, 429, 500, 502, 503, 504},
        retryable_exceptions=retryable_exceptions or [
            "TimeoutError",
            "ConnectionError",
            "ConnectTimeout",
            "ReadTimeout",
            "ProxyError",
            "SSLError",
            "TooManyRedirects",
        ],
        stop_on_status=stop_on_status or {400, 401, 403, 404},
    )


class RetryContext:
    def __init__(self, policy: RetryPolicy):
        self.policy = policy
        self.attempt = 0
        self.total_delay = 0.0
        self.last_exception: Optional[Exception] = None
        self.history: List[Dict[str, Any]] = []

    def record_attempt(self, success: bool, delay: float, exception: Optional[Exception] = None):
        self.attempt += 1
        self.total_delay += delay
        self.last_exception = exception
        self.history.append({
            "attempt": self.attempt,
            "success": success,
            "delay": delay,
            "exception": str(exception) if exception else None,
        })

    def should_continue(self) -> bool:
        return self.attempt < self.policy.max_attempts and self.total_delay < self.policy.max_total_delay

    def get_stats(self) -> Dict[str, Any]:
        return {
            "attempts": self.attempt,
            "total_delay": self.total_delay,
            "last_exception": str(self.last_exception) if self.last_exception else None,
            "history": self.history,
        }


async def retry_with_context(
    coro_func: Callable,
    *args,
    context: RetryContext,
    **kwargs,
) -> Any:
    while context.should_continue():
        try:
            result = await coro_func(*args, **kwargs)
            context.record_attempt(True, 0)
            return result
        except Exception as e:
            context.last_exception = e
            if not context.should_continue():
                raise

            delay = min(
                context.policy.base_delay * (context.policy.exponential_base ** (context.attempt - 1)),
                context.policy.max_delay,
            )
            if context.policy.jitter:
                import random
                delay *= (1 + random.uniform(-context.policy.jitter_factor, context.policy.jitter_factor))

            context.record_attempt(False, delay, e)
            await asyncio.sleep(delay)

    raise context.last_exception