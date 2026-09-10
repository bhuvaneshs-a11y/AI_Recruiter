import threading
import time

from google.genai import errors

# Gemini's free tier caps gemini-3.5-flash-lite at 15 requests/minute per
# project (GenerateRequestsPerMinutePerProjectPerModel-FreeTier) - confirmed
# live via repeated 429 RESOURCE_EXHAUSTED errors under concurrent candidate
# processing. A small safety margin (14 calls / 61s instead of 15/60) absorbs
# clock drift between our sliding window and Google's own, and the fact that
# a call's actual send time lags slightly behind when acquire() lets it through.
MAX_CALLS_PER_WINDOW = 14
WINDOW_SECONDS = 61


class _RateLimiter:
    """Thread-safe sliding-window limiter - acquire() blocks the calling
    thread until a call can be made without exceeding max_calls calls within
    any rolling `window_seconds` period. Shared across every Gemini call site
    (profile extraction, report generation, search-prompt match-check) since
    they all draw from the same per-project quota."""

    def __init__(self, max_calls, window_seconds):
        self._max_calls = max_calls
        self._window = window_seconds
        self._lock = threading.Lock()
        self._call_times = []

    def acquire(self):
        while True:
            with self._lock:
                now = time.time()
                self._call_times = [t for t in self._call_times if now - t < self._window]
                if len(self._call_times) < self._max_calls:
                    self._call_times.append(now)
                    return
                wait = self._window - (now - self._call_times[0])
            time.sleep(max(wait, 0.05))


_limiter = _RateLimiter(MAX_CALLS_PER_WINDOW, WINDOW_SECONDS)


def _extract_retry_delay(exc):
    """Pulls the server-suggested wait time out of a 429's RetryInfo detail
    (e.g. "Please retry in 31.16s" -> 31.16), falling back to None if the
    response shape doesn't have it."""
    try:
        details = exc.details
        error_obj = details.get("error", details) if isinstance(details, dict) else {}
        for d in error_obj.get("details", []):
            if str(d.get("@type", "")).endswith("RetryInfo"):
                delay = d.get("retryDelay", "")
                if delay.endswith("s"):
                    return float(delay[:-1])
    except Exception:
        pass
    return None


def call_gemini(fn, max_retries=2):
    """Runs a zero-arg callable that makes exactly one Gemini API call,
    waiting for a rate-limiter slot first (see _RateLimiter above) and
    retrying with the server-suggested backoff if a 429 still slips through
    (e.g. another process sharing the same key). Raises on any other error,
    or if still rate-limited after max_retries."""
    for attempt in range(max_retries + 1):
        _limiter.acquire()
        try:
            return fn()
        except errors.ClientError as e:
            if e.code != 429 or attempt == max_retries:
                raise
            delay = _extract_retry_delay(e) or 30
            print(f"Gemini rate limit hit, retrying in {delay:.0f}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(delay)
