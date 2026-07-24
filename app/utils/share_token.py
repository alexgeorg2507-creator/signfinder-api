"""Share-token generation for /v1/deals (SignfinderLand v2.0.0 Deal Cycle).

See DEAL_CYCLE_SPEC.md §4.5: 32-char URL-safe nanoid, ~192 bits of entropy,
cryptographically strong RNG (nanoid uses `secrets` under the hood).
"""
from __future__ import annotations

from nanoid import generate

_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
_SIZE = 32


def generate_share_token() -> str:
    """32-символьный URL-safe токен, ~192 бита энтропии."""
    return generate(_ALPHABET, size=_SIZE)
