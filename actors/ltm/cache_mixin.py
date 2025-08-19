"""
Redis caching mixin for LTMActor - provides cache infrastructure for novelty assessment
"""
from typing import Optional, Any, List, Dict
import hashlib
import json
import numpy as np
import time
from actors.events.ltm_events import (
    NoveltyCacheHitEvent,
    NoveltyCacheMissEvent,
    CacheInvalidatedEvent
)
from database.redis_connection import redis_connection
from config.settings_ltm import (
    LTM_CACHE_ENABLED,
    LTM_CACHE_KEY_PREFIX,
    LTM_CACHE_DEFAULT_TTL
)


class LTMCacheMixin:
    """Mixin providing Redis caching functionality for LTMActor"""
    
    # These attributes are available from LTMActor
    logger: object
    _metrics: Dict[str, int]
    
    # Cache state
    _cache_enabled: bool = False
    
    async def _initialize_cache(self) -> None:
        """Initialize Redis cache connection and check availability"""
        try:
            # Check if caching is enabled in config
            if not LTM_CACHE_ENABLED:
                self._cache_enabled = False
                self.logger.info("LTM cache disabled by configuration")
                return
            
            # Check Redis connection
            if redis_connection.is_connected():
                self._cache_enabled = True
                self.logger.info("LTM cache enabled")
            else:
                self._cache_enabled = False
                self.logger.warning("LTM cache disabled - Redis not connected")
                
        except Exception as e:
            self._cache_enabled = False
            self.logger.error(f"Failed to initialize cache: {str(e)}")
    
    async def _cache_get(self, key: str) -> Optional[Any]:
        """
        Get value from cache by key
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/disabled
        """
        if not self._cache_enabled:
            return None
            
        start_time = time.time()
        
        try:
            client = redis_connection.get_client()
            if not client:
                return None
                
            value = await client.get(key)
            latency_ms = (time.time() - start_time) * 1000
            
            # Determine cache type and user_id from key
            cache_type = self._get_cache_type_from_key(key)
            # Extract user_id from key (format: chimera:ltm:type:user_id:...)
            key_parts = key.split(':')
            user_id = None
            for i, part in enumerate(key_parts):
                if part.isdigit() and len(part) > 5:  # Likely a user_id
                    user_id = part
                    break
            
            if value:
                self._metrics['cache_hits'] += 1
                # Increment specific cache type counter
                if cache_type != "unknown":
                    metric_key = f'cache_hits_{cache_type}'
                    if metric_key not in self._metrics:
                        self._metrics[metric_key] = 0
                    self._metrics[metric_key] += 1
                
                # Generate cache hit event
                if user_id and hasattr(self, '_event_version_manager') and hasattr(self, 'get_actor_system'):
                    actor_system = self.get_actor_system()
                    if actor_system:
                        event = NoveltyCacheHitEvent.create(
                            user_id=user_id,
                            cache_type=cache_type,
                            key=key,
                            latency_ms=latency_ms
                        )
                        await self._event_version_manager.append_event(event, actor_system)
                
                # Deserialize JSON value
                return json.loads(value)
            else:
                self._metrics['cache_misses'] += 1
                
                # Generate cache miss event
                if user_id and hasattr(self, '_event_version_manager') and hasattr(self, 'get_actor_system'):
                    actor_system = self.get_actor_system()
                    if actor_system:
                        event = NoveltyCacheMissEvent.create(
                            user_id=user_id,
                            cache_type=cache_type,
                            key=key,
                            latency_ms=latency_ms
                        )
                        await self._event_version_manager.append_event(event, actor_system)
                
                return None
                
        except Exception as e:
            self.logger.error(f"Cache get error for key {key}: {str(e)}")
            return None
    
    async def _cache_set(self, key: str, value: Any, ttl: int = None) -> bool:
        """
        Set value in cache with optional TTL
        
        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized)
            ttl: Time to live in seconds (uses default if not specified)
            
        Returns:
            True if successful, False otherwise
        """
        if not self._cache_enabled:
            return False
            
        try:
            client = redis_connection.get_client()
            if not client:
                return False
                
            # Use default TTL if not specified
            if ttl is None:
                ttl = LTM_CACHE_DEFAULT_TTL
                
            # Serialize value to JSON
            json_value = json.dumps(value)
            
            # Set with TTL
            await client.setex(key, ttl, json_value)
            return True
            
        except Exception as e:
            self.logger.error(f"Cache set error for key {key}: {str(e)}")
            return False
    
    async def _cache_delete(self, key: str) -> bool:
        """
        Delete key from cache
        
        Args:
            key: Cache key to delete
            
        Returns:
            True if successful, False otherwise
        """
        if not self._cache_enabled:
            return False
            
        try:
            client = redis_connection.get_client()
            if not client:
                return False
                
            result = await client.delete(key)
            
            # Generate invalidation event for single key deletion
            if result > 0:
                # Extract user_id and cache type
                cache_type = self._get_cache_type_from_key(key)
                key_parts = key.split(':')
                user_id = None
                for part in key_parts:
                    if part.isdigit() and len(part) > 5:
                        user_id = part
                        break
                
                if user_id and hasattr(self, '_event_version_manager') and hasattr(self, 'get_actor_system'):
                    actor_system = self.get_actor_system()
                    if actor_system:
                        event = CacheInvalidatedEvent.create(
                            user_id=user_id,
                            cache_type=cache_type,
                            pattern=key,
                            entries_deleted=1,
                            reason="single_key_deletion"
                        )
                        await self._event_version_manager.append_event(event, actor_system)
            
            return result > 0
            
        except Exception as e:
            self.logger.error(f"Cache delete error for key {key}: {str(e)}")
            return False
    
    async def _cache_delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching pattern
        
        Args:
            pattern: Pattern to match (e.g., "chimera:ltm:*:user_123:*")
            
        Returns:
            Number of deleted keys
        """
        if not self._cache_enabled:
            return 0
            
        try:
            client = redis_connection.get_client()
            if not client:
                return 0
                
            # Find all matching keys
            deleted_count = 0
            async for key in client.scan_iter(match=pattern):
                if await client.delete(key):
                    deleted_count += 1
                    
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Cache delete pattern error for {pattern}: {str(e)}")
            return 0
    
    def _make_cache_key(self, prefix: str, *parts: str) -> str:
        """
        Generate cache key with project prefix
        
        Args:
            prefix: Key prefix (e.g., "novelty", "profile")
            *parts: Additional key parts
            
        Returns:
            Full cache key
            
        Example:
            _make_cache_key("novelty", "final", "user_123", "abc123...")
            -> "chimera:ltm:novelty:final:user_123:abc123..."
        """
        base_key = redis_connection.make_key(LTM_CACHE_KEY_PREFIX, prefix)
        if parts:
            return f"{base_key}:{':'.join(parts)}"
        return base_key
    
    def _hash_text(self, text: str) -> str:
        """
        Generate deterministic hash for text content
        
        Args:
            text: Text to hash
            
        Returns:
            16-character hash string
        """
        if not text:
            return "empty"
        return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
    
    def _hash_embedding(self, embedding: np.ndarray) -> str:
        """
        Generate deterministic hash for numpy embedding
        
        Args:
            embedding: Numpy array to hash
            
        Returns:
            16-character hash string
        """
        if embedding is None:
            return "none"
        # Convert to bytes and hash
        embedding_bytes = embedding.tobytes()
        return hashlib.sha256(embedding_bytes).hexdigest()[:16]
    
    def _hash_tags(self, tags: List[str]) -> str:
        """
        Generate deterministic hash for list of tags
        
        Args:
            tags: List of semantic tags
            
        Returns:
            16-character hash string
        """
        if not tags:
            return "notags"
        # Sort tags for deterministic order
        sorted_tags = sorted(tags)
        tags_string = "|".join(sorted_tags)
        return hashlib.sha256(tags_string.encode('utf-8')).hexdigest()[:16]
    
    def _hash_tags(self, tags: List[str]) -> str:
        """
        Generate deterministic hash for list of tags
        
        Args:
            tags: List of semantic tags
            
        Returns:
            16-character hash string
        """
        if not tags:
            return "notags"
        # Sort tags for deterministic order
        sorted_tags = sorted(tags)
        tags_string = "|".join(sorted_tags)
        return hashlib.sha256(tags_string.encode('utf-8')).hexdigest()[:16]
    
    def _get_cache_type_from_key(self, key: str) -> str:
        """
        Determine cache type from key prefix
        
        Args:
            key: Cache key
            
        Returns:
            Cache type: "final", "embedding", "knn", "profile", etc.
        """
        if "novelty:final" in key:
            return "final"
        elif "novelty:embedding" in key:
            return "embedding"
        elif "novelty:knn" in key:
            return "knn"
        elif "novelty:profile" in key:
            return "profile"
        elif "novelty:percentile" in key:
            return "percentile"
        elif "novelty:calibration" in key:
            return "calibration"
        elif "novelty:temporal" in key:
            return "temporal"
        else:
            return "unknown"