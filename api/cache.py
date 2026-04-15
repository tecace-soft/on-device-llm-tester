"""In-memory TTL cache for expensive aggregate queries.

Architecture: DEPLOYMENT_ARCHITECTURE.md §8
Used by: stats.py (compute_summary, compute_by_model, compute_by_category)
Depends on: cachetools>=5.3.0
"""

from __future__ import annotations

import hashlib
from functools import wraps
from typing import Any

from cachetools import TTLCache

# 최대 100개 항목, 5분 TTL
_cache: TTLCache = TTLCache(maxsize=100, ttl=300)


def cached_query(ttl: int = 300):
    """집계 쿼리 결과를 인메모리 캐시.

    Architecture: DEPLOYMENT_ARCHITECTURE.md §8.2
    Used by: compute_summary, compute_by_model, compute_by_category

    캐시 키: 함수명 + (db 제외한) 인자 해시.
    Why: db 객체는 요청마다 재생성되므로 키에서 제외해야 히트율이 유지됨.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key_data = f"{func.__name__}:{args[1:]}:{sorted(kwargs.items())}"
            cache_key = hashlib.md5(key_data.encode()).hexdigest()

            if cache_key in _cache:
                return _cache[cache_key]

            result = await func(*args, **kwargs)
            _cache[cache_key] = result
            return result
        return wrapper
    return decorator


def invalidate_cache() -> int:
    """캐시 전체 무효화. 삭제된 항목 수 반환.

    Used by: POST /api/cache/invalidate (main.py)
    """
    count = len(_cache)
    _cache.clear()
    return count
