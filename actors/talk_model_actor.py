"""
TalkModelActor - актор для управления моделями собеседников (Partner Persona)
Проверить стр. 66 redis
"""
from typing import Optional, Dict, Any
import asyncio
import json
import uuid

from actors.base_actor import BaseActor
from actors.messages import ActorMessage, MESSAGE_TYPES
from config.settings import (
    PARTNER_MODEL_REQUEST_TIMEOUT,
    PARTNER_PERSONA_CACHE_TTL,
    PARTNER_PERSONA_CHANGE_THRESHOLD
)
from config.vocabulary_style_analysis import (
    STYLE_NEUTRAL_VALUE,
    PERSONA_MODE_MIN_CONFIDENCE
)
from database.connection import db_connection
from database.redis_connection import redis_connection
from utils.monitoring import measure_latency
from utils.event_utils import EventVersionManager


class TalkModelActor(BaseActor):
    """
    Актор для управления моделями собеседников (Partner Persona).
    Единственный владелец данных таблицы partner_personas.
    Предоставляет рекомендации по режиму общения на основе стиля пользователя.
    """
    
    def __init__(self):
        super().__init__("talk_model", "TalkModel")
        self._pool = None
        self._redis = None
        self._degraded_mode = False
        self._event_version_manager = EventVersionManager()
        
        # Метрики
        self._metrics = {
            'initialized': False,
            'degraded_mode_entries': 0,
            'get_partner_model_count': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'db_errors': 0,
            'redis_errors': 0,
            'personas_found': 0,
            'personas_not_found': 0
        }
    
    async def initialize(self) -> None:
        """Инициализация актора и проверка схемы БД"""
        try:
            # Подключаемся к БД
            if not db_connection._is_connected:
                await db_connection.connect()
            
            # Получаем пул подключений
            self._pool = db_connection.get_pool()
            
            # Проверяем схему
            await self._verify_schema()
            
            # Подключаемся к Redis
            try:
                # self._redis = await redis_connection.get_connection()
                self._redis = await redis_connection.get_client()
                self.logger.info("Redis connection established for TalkModelActor")
            except Exception as e:
                self.logger.warning(f"Redis unavailable, working without cache: {str(e)}")
                self._redis = None
            
            self._metrics['initialized'] = True
            self.logger.info("TalkModelActor initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize TalkModelActor: {str(e)}")
            self._degraded_mode = True
            self._metrics['degraded_mode_entries'] += 1
            self._increment_metric('db_errors')
            self.logger.warning("TalkModelActor entering degraded mode - will return empty personas")
    
    async def shutdown(self) -> None:
        """Освобождение ресурсов"""
        # Логируем финальные метрики
        self._log_metrics(final=True)
        
        # Закрываем Redis если есть
        if self._redis:
            try:
                await self._redis.close()
            except Exception as e:
                self.logger.error(f"Error closing Redis connection: {str(e)}")
        
        self.logger.info("TalkModelActor shutdown completed")
    
    @measure_latency
    async def handle_message(self, message: ActorMessage) -> Optional[ActorMessage]:
        """Обработка входящих сообщений"""
        
        # Обработка GET_PARTNER_MODEL
        if message.message_type == MESSAGE_TYPES['GET_PARTNER_MODEL']:
            self._metrics['get_partner_model_count'] += 1
            await self._handle_get_partner_model(message)
            return None  # Ответ отправляется внутри метода
        
        # Обработка UPDATE_PARTNER_MODEL
        elif message.message_type == MESSAGE_TYPES.get('UPDATE_PARTNER_MODEL'):
            await self._handle_update_partner_model(message)
        
        else:
            self.logger.warning(
                f"Unknown message type received: {message.message_type}"
            )
        
        return None
    
    async def _verify_schema(self) -> None:
        """Проверка существования таблицы partner_personas"""
        try:
            if self._pool is None:
                raise RuntimeError("Database pool not initialized")
            
            # Проверяем существование таблицы
            query = """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'partner_personas'
                )
            """
            table_exists = await self._pool.fetchval(query, timeout=5.0)
            
            if not table_exists:
                raise RuntimeError("Table partner_personas does not exist. Run migration 012_create_personality_tables.sql first.")
            
            # Проверяем индексы
            index_query = """
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'partner_personas'
            """
            indexes = await self._pool.fetch(index_query, timeout=5.0)
            
            required_indexes = {
                'idx_personas_user_active',
                'idx_personas_user_version',
                'idx_personas_updated'
            }
            
            existing_indexes = {row['indexname'] for row in indexes}
            missing_indexes = required_indexes - existing_indexes
            
            if missing_indexes:
                self.logger.warning(f"Missing indexes: {missing_indexes}")
            
            self.logger.debug("Schema verification completed successfully")
            
        except Exception as e:
            self.logger.error(f"Schema verification failed: {str(e)}")
            raise
    
    async def _handle_get_partner_model(self, message: ActorMessage) -> None:
        """Обработчик получения Partner Persona"""
        user_id = message.payload.get('user_id')
        request_id = message.payload.get('request_id')
        
        # Определяем кому отвечать
        reply_to_actor = message.reply_to or message.sender_id
        if not reply_to_actor:
            self.logger.warning("GET_PARTNER_MODEL message without reply_to or sender_id")
            return
        
        # В degraded mode отправляем пустую персону
        if self._degraded_mode:
            response = ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES['PARTNER_MODEL_RESPONSE'],
                payload={
                    'user_id': user_id,
                    'recommended_mode': None,
                    'mode_confidence': 0.0,
                    'persona_version': None,
                    'degraded_mode': True,
                    'request_id': request_id
                }
            )
            if self.get_actor_system():
                await self.get_actor_system().send_message(reply_to_actor, response)
            return
        
        # Пытаемся получить из кэша
        persona_data = await self._get_from_cache(user_id)
        
        if persona_data is None:
            # Cache miss - загружаем из БД
            self._increment_metric('cache_misses')
            persona_data = await self._load_from_database(user_id)
            
            # Сохраняем в кэш если получили данные
            if persona_data and persona_data['recommended_mode']:
                await self._save_to_cache(user_id, persona_data)
        else:
            # Cache hit
            self._increment_metric('cache_hits')
            self.logger.debug(f"Partner persona cache hit for user {user_id}")
        
        # Подготавливаем ответ
        response = ActorMessage.create(
            sender_id=self.actor_id,
            message_type=MESSAGE_TYPES['PARTNER_MODEL_RESPONSE'],
            payload={
                'user_id': user_id,
                'recommended_mode': persona_data.get('recommended_mode'),
                'mode_confidence': persona_data.get('mode_confidence', 0.0),
                'persona_version': persona_data.get('version'),
                'degraded_mode': False,
                'request_id': request_id
            }
        )
        
        # Отправляем через ActorSystem
        if self.get_actor_system():
            await self.get_actor_system().send_message(reply_to_actor, response)
            
            # Логируем результат
            if persona_data.get('recommended_mode'):
                self._increment_metric('personas_found')
                self.logger.info(
                    f"Sent partner persona for user {user_id}: "
                    f"mode={persona_data['recommended_mode']}, "
                    f"confidence={persona_data['mode_confidence']:.2f}"
                )
            else:
                self._increment_metric('personas_not_found')
                self.logger.debug(f"No active partner persona found for user {user_id}")
    
    async def _get_from_cache(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Получить персону из Redis кэша"""
        if not self._redis:
            return None
        
        try:
            cache_key = f"partner_persona:{user_id}"
            cached_data = await self._redis.get(cache_key)
            
            if cached_data:
                return json.loads(cached_data)
            
            return None
            
        except Exception as e:
            self.logger.warning(f"Redis cache error: {str(e)}")
            self._increment_metric('redis_errors')
            return None
    
    async def _save_to_cache(self, user_id: str, persona_data: Dict[str, Any]) -> None:
        """Сохранить персону в Redis кэш"""
        if not self._redis:
            return
        
        try:
            cache_key = f"partner_persona:{user_id}"
            cache_value = json.dumps(persona_data)
            
            # Сохраняем с TTL
            await self._redis.setex(
                cache_key,
                PARTNER_PERSONA_CACHE_TTL,
                cache_value
            )
            
            self.logger.debug(
                f"Cached partner persona for user {user_id} "
                f"(TTL: {PARTNER_PERSONA_CACHE_TTL}s)"
            )
            
        except Exception as e:
            self.logger.warning(f"Failed to cache partner persona: {str(e)}")
            self._increment_metric('redis_errors')
    
    async def _load_from_database(self, user_id: str) -> Dict[str, Any]:
        """Загрузить активную персону из БД"""
        try:
            if self._pool is None:
                raise RuntimeError("Database pool not initialized")
            
            # SQL запрос из ТЗ
            query = """
                SELECT recommended_mode, mode_confidence, version
                FROM partner_personas
                WHERE user_id = $1 AND is_active = true
                ORDER BY updated_at DESC
                LIMIT 1
            """
            
            row = await self._pool.fetchrow(query, user_id, timeout=PARTNER_MODEL_REQUEST_TIMEOUT)
            
            if row:
                return {
                    'recommended_mode': row['recommended_mode'],
                    'mode_confidence': float(row['mode_confidence']),
                    'version': row['version']
                }
            else:
                # Персоны нет - возвращаем пустой результат
                return {
                    'recommended_mode': None,
                    'mode_confidence': 0.0,
                    'version': None
                }
                
        except asyncio.TimeoutError:
            self.logger.warning(f"Database query timeout for user {user_id}")
            self._increment_metric('db_errors')
            return {
                'recommended_mode': None,
                'mode_confidence': 0.0,
                'version': None
            }
        except Exception as e:
            self.logger.error(f"Failed to load partner persona: {str(e)}")
            self._increment_metric('db_errors')
            return {
                'recommended_mode': None,
                'mode_confidence': 0.0,
                'version': None
            }
    
    async def _invalidate_cache(self, user_id: str) -> None:
        """Инвалидировать кэш для пользователя (для будущего использования)"""
        if not self._redis:
            return
        
        try:
            cache_key = f"partner_persona:{user_id}"
            await self._redis.delete(cache_key)
            self.logger.debug(f"Invalidated cache for user {user_id}")
        except Exception as e:
            self.logger.warning(f"Failed to invalidate cache: {str(e)}")
            self._increment_metric('redis_errors')
    
    async def _handle_update_partner_model(self, message: ActorMessage) -> None:
        """Обработчик обновления Partner Persona с версионированием и сохранением черт"""
        payload = message.payload
        user_id = payload.get('user_id')
        new_style_vector = payload.get('style_vector')
        recommended_mode = payload.get('recommended_mode')
        mode_confidence = payload.get('mode_confidence')
        detected_traits = payload.get('detected_traits', [])
        analysis_metadata = payload.get('analysis_metadata', {})
        
        if not all([user_id, new_style_vector, recommended_mode]):
            self.logger.error("UPDATE_PARTNER_MODEL missing required fields")
            return
            
        try:
            # Получаем текущую активную персону через существующий метод
            existing_persona_data = await self._load_from_database(user_id)
            existing_persona = None
            if existing_persona_data['recommended_mode']:  # Если персона найдена
                existing_persona = existing_persona_data
            
            # Проверяем необходимость создания новой версии
            should_create_new_version = True
            
            if existing_persona:
                # Десериализуем старый style_vector
                old_style_data = existing_persona.get('style_vector', {})
                if isinstance(old_style_data, str):
                    old_style_data = json.loads(old_style_data)
                    
                # Проверяем изменения по каждому компоненту
                max_change = 0.0
                for key in ['playfulness', 'seriousness', 'emotionality', 'creativity']:
                    old_value = old_style_data.get(key, STYLE_NEUTRAL_VALUE)
                    new_value = new_style_vector.get(key, STYLE_NEUTRAL_VALUE)
                    change = abs(new_value - old_value)
                    max_change = max(max_change, change)
                
                # Создаем новую версию только при значительных изменениях
                should_create_new_version = max_change > PARTNER_PERSONA_CHANGE_THRESHOLD
                
                if not should_create_new_version:
                    self.logger.info(
                        f"Style changes for user {user_id} below threshold "
                        f"({max_change:.3f} < {PARTNER_PERSONA_CHANGE_THRESHOLD}), "
                        f"keeping current persona"
                    )
            
            if should_create_new_version:
                # Используем функцию БД для атомарного обновления
                new_persona_id = await self._pool.fetchval(
                    "SELECT update_partner_persona($1, $2, $3, $4, $5, $6)",
                    user_id,
                    json.dumps(new_style_vector),
                    analysis_metadata.get('style_confidence', PERSONA_MODE_MIN_CONFIDENCE),
                    recommended_mode,
                    mode_confidence,
                    analysis_metadata.get('messages_analyzed', 0)
                )
                
                self.logger.info(
                    f"Created new partner persona for user {user_id}: "
                    f"id={new_persona_id}, mode={recommended_mode}, "
                    f"confidence={mode_confidence:.3f}"
                )
                
                # Инвалидируем кэш для этого пользователя
                await self._invalidate_cache(user_id)
            
            # Сохраняем detected_traits в БД
            if detected_traits and self._pool:
                batch_id = str(uuid.uuid4())
                
                async with self._pool.acquire() as conn:
                    # Сохраняем каждую черту
                    for trait in detected_traits:
                        await conn.execute(
                            """
                            INSERT INTO personality_traits_manifestations (
                                user_id, trait_name, manifestation_strength,
                                mode, emotional_context, detected_markers,
                                confidence, analysis_batch_id
                            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                            """,
                            user_id,
                            trait['trait_name'],
                            trait['strength'],
                            recommended_mode,
                            json.dumps({'mode': recommended_mode}),  # Простой контекст
                            [trait.get('context', '')],  # Маркеры как массив
                            trait['strength'],  # confidence = strength
                            batch_id
                        )
                
                self.logger.info(
                    f"Saved {len(detected_traits)} trait manifestations for user {user_id}"
                )
            
            # Обновляем метрики
            self._increment_metric('personas_found' if should_create_new_version else 'personas_not_found')
            
        except Exception as e:
            self.logger.error(f"Error updating partner persona: {str(e)}", exc_info=True)
            self._increment_metric('db_errors')
    
    def _increment_metric(self, metric_name: str, value: int = 1) -> None:
        """Инкремент метрики"""
        if metric_name in self._metrics:
            self._metrics[metric_name] += value
    
    def _log_metrics(self, final: bool = False) -> None:
        """Логирование метрик"""
        log_msg = "TalkModelActor metrics"
        if final:
            log_msg = "TalkModelActor final metrics"
        
        self.logger.info(
            f"{log_msg} - "
            f"Requests: {self._metrics['get_partner_model_count']}, "
            f"Cache hits: {self._metrics['cache_hits']}, "
            f"Cache misses: {self._metrics['cache_misses']}, "
            f"Found: {self._metrics['personas_found']}, "
            f"Not found: {self._metrics['personas_not_found']}, "
            f"DB errors: {self._metrics['db_errors']}, "
            f"Redis errors: {self._metrics['redis_errors']}, "
            f"Degraded mode: {self._degraded_mode}"
        )