"""
Cache mixin for PersonalityActor - handles Redis caching
"""
import json
from typing import Optional, Dict, Any
from database.redis_connection import redis_connection
from config.settings import PERSONALITY_PROFILE_CACHE_TTL_SECONDS


class PersonalityCacheMixin:
    """Mixin providing cache methods for PersonalityActor"""
    
    # These attributes are available from PersonalityActor
    logger: object
    _redis: Any
    _metrics: Dict[str, int]
    
    async def _get_cached_profile(self, user_id: str) -> Optional[Dict[str, float]]:
        """
        Получить профиль личности из кэша
        
        Args:
            user_id: ID пользователя
            
        Returns:
            Словарь с профилем или None если не найден
        """
        if not self._redis:
            return None
            
        try:
            cache_key = redis_connection.make_key("personality", "profile", user_id)
            cached_data = await self._redis.get(cache_key)
            
            if cached_data:
                self._metrics['cache_hits'] += 1
                self.logger.debug(f"Profile cache hit for user {user_id}")
                return json.loads(cached_data)
            else:
                self._metrics['cache_misses'] += 1
                return None
                
        except Exception as e:
            self.logger.warning(f"Redis cache error in _get_cached_profile: {str(e)}")
            return None
    
    async def _cache_profile(self, user_id: str, profile: Dict[str, float]) -> None:
        """
        Сохранить профиль личности в кэш
        
        Args:
            user_id: ID пользователя
            profile: Профиль для сохранения
        """
        if not self._redis:
            return
            
        try:
            cache_key = redis_connection.make_key("personality", "profile", user_id)
            await self._redis.setex(
                cache_key,
                PERSONALITY_PROFILE_CACHE_TTL_SECONDS,
                json.dumps(profile)
            )
            self.logger.debug(
                f"Cached personality profile for user {user_id} "
                f"(TTL: {PERSONALITY_PROFILE_CACHE_TTL_SECONDS}s)"
            )
        except Exception as e:
            self.logger.warning(f"Failed to cache profile: {str(e)}")
    
    async def _invalidate_profile_cache(self, user_id: str) -> None:
        """
        Инвалидировать кэш профиля пользователя
        
        Args:
            user_id: ID пользователя
        """
        if not self._redis:
            return
            
        try:
            cache_key = redis_connection.make_key("personality", "profile", user_id)
            deleted = await self._redis.delete(cache_key)
            
            if deleted:
                self.logger.debug(f"Invalidated profile cache for user {user_id}")
            
        except Exception as e:
            self.logger.warning(f"Failed to invalidate profile cache: {str(e)}")