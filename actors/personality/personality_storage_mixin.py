"""
Storage mixin for PersonalityActor - handles database operations
"""
import json
from typing import TYPE_CHECKING, Dict, Any

if TYPE_CHECKING:
    from models.personality_models import PersonalityModifier

from config.settings import PERSONALITY_QUERY_TIMEOUT


class PersonalityStorageMixin:
    """Mixin providing database storage methods for PersonalityActor"""
    
    # These attributes are available from PersonalityActor
    logger: object
    _pool: Any
    _degraded_mode: bool
    _base_traits: Dict[str, Dict[str, Any]]
    _metrics: Dict[str, int]
    
    async def _verify_schema(self) -> None:
        """Проверка существования необходимых таблиц в БД"""
        try:
            if self._pool is None:
                raise RuntimeError("Database pool not initialized")
            
            # Проверяем таблицу personality_base_traits
            query_base = """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'personality_base_traits'
                )
            """
            base_table_exists = await self._pool.fetchval(query_base, timeout=PERSONALITY_QUERY_TIMEOUT)
            
            if not base_table_exists:
                raise RuntimeError("Table personality_base_traits does not exist. Run migration 013 first.")
            
            # Проверяем таблицу personality_active_profiles
            query_profiles = """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'personality_active_profiles'
                )
            """
            profiles_table_exists = await self._pool.fetchval(query_profiles, timeout=PERSONALITY_QUERY_TIMEOUT)
            
            if not profiles_table_exists:
                raise RuntimeError("Table personality_active_profiles does not exist. Run migration 013 first.")
            
            self.logger.debug("Schema verification completed successfully")
            
        except Exception as e:
            self.logger.error(f"Schema verification failed: {str(e)}")
            raise
    
    async def _load_base_traits(self) -> None:
        """Загрузка базовых черт личности из БД"""
        try:
            if self._pool is None:
                raise RuntimeError("Database pool not initialized")
            
            # Загружаем все черты из personality_base_traits
            query = """
                SELECT 
                    trait_name,
                    base_value,
                    description,
                    is_core,
                    mode_affinities,
                    emotion_associations
                FROM personality_base_traits
                ORDER BY trait_name
            """
            
            rows = await self._pool.fetch(query, timeout=PERSONALITY_QUERY_TIMEOUT)
            
            if not rows:
                self.logger.error("No base traits found in database")
                self._degraded_mode = True
                return
            
            # Сохраняем все данные о чертах
            core_count = 0
            for row in rows:
                trait_name = row['trait_name']
                is_core = row['is_core']
                
                self._base_traits[trait_name] = {
                    'base_value': row['base_value'],
                    'is_core': is_core,
                    'mode_affinities': row['mode_affinities'],  # JSONB автоматически десериализуется в dict
                    'emotion_associations': row['emotion_associations'],  # JSONB автоматически десериализуется в dict
                    'description': row['description']
                }
                
                if is_core:
                    core_count += 1
            
            # Обновляем метрики
            self._metrics['base_traits_loaded'] = len(self._base_traits)
            self._metrics['core_traits_count'] = core_count
            
            self.logger.info(
                f"Loaded {len(self._base_traits)} base traits "
                f"({core_count} core traits)"
            )
            
            # Логируем загруженные черты для отладки
            trait_names = list(self._base_traits.keys())
            self.logger.debug(f"Loaded traits: {', '.join(trait_names)}")
            
        except Exception as e:
            self.logger.error(f"Failed to load base traits: {str(e)}")
            self._metrics['db_errors'] += 1
            raise
    
    async def _store_modifier_history(self, user_id: str, modifier: 'PersonalityModifier') -> None:
        """Сохранение модификатора в историю БД"""
        if self._degraded_mode or not self._pool:
            self.logger.warning(
                f"Cannot save modifier history in degraded mode for user {user_id}"
            )
            return
        
        try:
            query = """
                INSERT INTO personality_modifier_history 
                (user_id, modifier_type, modifier_source, modifier_data, applied_at)
                VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
            """
            
            # Преобразуем modifier_data в JSON для JSONB поля
            # Убеждаемся, что modifier_data это dict
            if hasattr(modifier.modifier_data, 'dict'):
                modifier_data_dict = modifier.modifier_data.dict()
            elif isinstance(modifier.modifier_data, dict):
                modifier_data_dict = modifier.modifier_data
            else:
                modifier_data_dict = dict(modifier.modifier_data)
                
            modifier_json = json.dumps(modifier_data_dict)
            
            await self._pool.execute(
                query,
                user_id,
                modifier.modifier_type,
                modifier.source_actor,
                modifier_json,
                timeout=PERSONALITY_QUERY_TIMEOUT
            )
            
            self.logger.info(
                f"Saved {modifier.modifier_type} modifier to history for user {user_id}"
            )
            
        except Exception as e:
            self.logger.error(
                f"Failed to save {modifier.modifier_type} modifier history for user {user_id}: {str(e)}, "
                f"modifier_data type: {type(modifier.modifier_data)}"
            )
            self._metrics['db_errors'] += 1
            # Не пробрасываем исключение - продолжаем работать с in-memory состоянием