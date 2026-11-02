import threading
import time
from collections import defaultdict, deque

from fastapi import Request

RATE_LIMIT = 8
RATE_WINDOW_SECONDS = 15 * 60
_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def client_ip(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host


def too_many(ip: str, bucket: str, limit: int = RATE_LIMIT) -> bool:
    # The local site and the API share one address, so a test session
    # would otherwise block the person using the form.
    if ip in {"127.0.0.1", "::1", "localhost"}:
        return False
    now = time.monotonic()
    key = f"{bucket}:{ip}"
    with _lock:
        recent = _hits[key]
        while recent and now - recent[0] > RATE_WINDOW_SECONDS:
            recent.popleft()
        if len(recent) >= limit:
            return True
        recent.append(now)
        return False
