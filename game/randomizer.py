import hashlib
import hmac

from config import settings


def roll(key: str, upper: int = 100) -> int:
    digest = hmac.new(settings.game_secret.encode(), key.encode(), hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big") % upper


def chance(key: str, percent: int) -> bool:
    return roll(key, 100) < max(0, min(100, percent))


def pick_index(key: str, size: int) -> int:
    if size < 1:
        raise ValueError("size must be positive")
    return roll(key, size)

