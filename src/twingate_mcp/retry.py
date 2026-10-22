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
    if value.isdigit():
        return float(value)
    parsed = email.utils.parsedate_to_datetime(value)
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


async def with_retry[T](
    call: Callable[[], Awaitable[T]], *, attempts: int, max_seconds: float
) -> T:
    """Run `call` under the retry policy; 401/403 become `TwingateAuthError`."""
    try:
        async for attempt in stamina.retry_context(
            on=backoff, attempts=attempts, timeout=max_seconds
        ):
            with attempt:
                return await call()
    except Exception as exc:
        response = _response_of(exc)
        if response is not None and response.status_code in (401, 403):
            raise TwingateAuthError(response.status_code) from None
        raise
    raise AssertionError("unreachable")  # pragma: no cover
