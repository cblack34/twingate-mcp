import email.utils
import time
from collections.abc import Awaitable, Callable

import httpx
import stamina

RETRY_STATUSES = frozenset({429, 502, 503, 504})


class TwingateAuthError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__("Token invalid or lacks permission")
        self.status_code = status_code


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if value.isdigit():
            return float(value)
        parsed = email.utils.parsedate_to_datetime(value)
    except ValueError:
        return None
    return max(parsed.timestamp() - time.time(), 0.0)


def _response_of(exc: Exception) -> httpx.Response | None:
    response = getattr(exc, "response", None)
    return response if isinstance(response, httpx.Response) else None


def backoff(exc: Exception) -> bool | float:
    """stamina hook: retry transport errors and 429/5xx, honouring Retry-After."""
    if isinstance(exc, httpx.TransportError):
        return True
    response = _response_of(exc)
    if response is None or response.status_code not in RETRY_STATUSES:
        return False
    delay = _retry_after(response.headers.get("Retry-After"))
    return True if delay is None else delay


def bounded_backoff(max_seconds: float) -> Callable[[Exception], bool | float]:
    """`backoff` with any Retry-After delay capped to what is left of the retry budget."""
    started = time.monotonic()

    def on(exc: Exception) -> bool | float:
        decision = backoff(exc)
        if isinstance(decision, bool):
            return decision
        return min(decision, max(max_seconds - (time.monotonic() - started), 0.0))

    return on


async def with_retry[T](
    call: Callable[[], Awaitable[T]], *, attempts: int, max_seconds: float
) -> T:
    """Run `call` under the retry policy; 401/403 become `TwingateAuthError`."""
    try:
        async for attempt in stamina.retry_context(
            on=bounded_backoff(max_seconds), attempts=attempts, timeout=max_seconds
        ):
            with attempt:
                return await call()
    except Exception as exc:
        response = _response_of(exc)
        if response is not None and response.status_code in (401, 403):
            raise TwingateAuthError(response.status_code) from None
        raise
    raise AssertionError("unreachable")  # pragma: no cover
