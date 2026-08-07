import time
from collections import defaultdict
from typing import Dict, List
from fastapi import HTTPException, Request


class RateLimiter:
    """In-memory sliding window rate limiter for IP address throttling."""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.history: Dict[str, List[float]] = defaultdict(list)

    def check(self, request: Request, key_prefix: str = ""):
        client_ip = request.client.host if request.client else "127.0.0.1"
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        key = f"{key_prefix}:{client_ip}"
        now = time.time()
        cutoff = now - self.window_seconds

        self.history[key] = [t for t in self.history[key] if t > cutoff]

        if len(self.history[key]) >= self.max_requests:
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests. Please try again in {self.window_seconds} seconds.",
                headers={"Retry-After": str(self.window_seconds)}
            )

        self.history[key].append(now)


# Default instances for auth endpoints
auth_limiter = RateLimiter(max_requests=5, window_seconds=60)      # 5 attempts per min for login
signup_limiter = RateLimiter(max_requests=3, window_seconds=300)    # 3 signups per 5 mins
