"""Password hashing, tokens, rate limiting and configuration."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict, deque

DEV = os.environ.get("SHUINKAN_DEV", "1") == "1"
SECURE_COOKIES = os.environ.get("SHUINKAN_SECURE_COOKIES", "0" if DEV else "1") == "1"
SESSION_COOKIE = "shuinkan_session"
SESSION_DAYS = int(os.environ.get("SHUINKAN_SESSION_DAYS", "30"))
ALLOWED_ORIGINS = {o.strip() for o in os.environ.get("SHUINKAN_ALLOWED_ORIGINS", "").split(",") if o.strip()}

_N, _R, _P = 2 ** 14, 8, 1


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


# A pre-computed hash so failed logins for unknown users take the same time.
DUMMY_HASH = hash_password(secrets.token_hex(8))


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


class RateLimiter:
    """Sliding-window limiter kept in memory (single-process deployment)."""

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self):
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def csp_header() -> str:
    return "; ".join([
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        # Style *attributes* (progress-bar widths etc.) are allowed; <style> blocks and external CSS are not.
        "style-src-attr 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "media-src 'self'",  # word recordings and the built-in voice
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


SECURITY_HEADERS = {
    "Content-Security-Policy": csp_header(),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
if SECURE_COOKIES:
    SECURITY_HEADERS["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
