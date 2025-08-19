from typing import Optional, Dict, Any, List, TYPE_CHECKING
from datetime import datetime

from actors.base_actor import BaseActor
from actors.personality.personality_calculation_mixin import PersonalityCalculationMixin
from actors.personality.personality_storage_mixin import PersonalityStorageMixin
from actors.personality.personality_cache_mixin import PersonalityCacheMixin
from actors.personality.personality_protection_mixin import PersonalityProtectionMixin
from actors.personality.personality_resonance_mixin import PersonalityResonanceMixin
from actors.personality.personality_resonance_protection_mixin import PersonalityResonanceProtectionMixin
from actors.personality.personality_resonance_events_mixin import PersonalityResonanceEventsMixin
from actors.personality.personality_api_mixin import PersonalityAPIMixin

if TYPE_CHECKING:
    pass
from actors.messages import ActorMessage, MESSAGE_TYPES
from database.connection import db_connection
from database.redis_connection import redis_connection
from utils.monitoring import measure_latency
from utils.event_utils import EventVersionManager

class PersonalityActor(
    PersonalityCalculationMixin,
    PersonalityStorageMixin,
    PersonalityCacheMixin,
    PersonalityProtectionMixin,
    PersonalityResonanceMixin,
    PersonalityResonanceProtectionMixin,
    PersonalityResonanceEventsMixin,
    PersonalityAPIMixin,
    BaseActor
):
    """
    Актор для управления моделью личности Химеры.
    Хранит базовые черты личности, вычисляет активные профили с учетом контекстных модификаторов.
    """
    
    def __init__(self):
        super().__init__("personality", "Personality")
        self._pool = None
        self._redis = None
        self._degraded_mode = False
        self._event_version_manager = EventVersionManager()
        
        # Внутреннее состояние
        self._base_traits: Dict[str, Dict[str, Any]] = {}  # trait_name -> полная информация о черте
        self._active_profiles: Dict[str, Dict[str, float]] = {}  # user_id -> {trait_name: value}
        self._current_modifiers: Dict[str, Dict[str, Any]] = {}  # user_id -> modifiers
        self._trait_history: Dict[str, List[Dict[str, float]]] = {}  # user_id -> кольцевой буфер истории
        
        # Атрибуты для защитных механизмов (PersonalityProtectionMixin)
        self._session_start_profiles: Dict[str, Dict] = {}  # user_id -> {'profile': Dict, 'started_at': datetime}
        self._last_activity: Dict[str, datetime] = {}  # user_id -> last activity timestamp
        
        # Атрибут для отслеживания изменений доминирующих черт
        self._previous_dominant_traits: Dict[str, List[str]] = {}  # user_id -> previous top-5
        
        # Атрибуты для резонансной персонализации (PersonalityResonanceMixin)
        self._resonance_profiles: Dict[str, Dict[str, float]] = {}  # user_id -> {trait: coefficient}
        self._interaction_counts: Dict[str, int] = {}  # user_id -> interaction count
        self._last_adaptations: Dict[str, datetime] = {}  # user_id -> last adaptation timestamp
        
        # Метрики
        self._metrics = {
            'initialized': False,
            'base_traits_loaded': 0,
            'core_traits_count': 0,
            'active_profiles_count': 0,
            'degraded_mode_entries': 0,
            'unknown_message_count': 0,
            'db_errors': 0,
            'modifiers_received': 0,
            'modifiers_by_type': {
                'style': 0,
                'emotion': 0,
                'temporal': 0,
                'context': 0
            },
            'profiles_calculated': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'core_constraints_applied': 0,
            'session_limits_applied': 0,
            'recoveries_triggered': 0,
            'profile_calculated_events': 0,
            'dominance_changed_events': 0,
            'protection_activated_events': 0,
            'personality_stabilized_events': 0,
            'resonance_profiles_loaded': 0,
            'resonance_applications': 0,
            'resonance_adaptations': 0,
            'resonance_cache_hits': 0,
            'resonance_cache_misses': 0
        }
    
    async def initialize(self) -> None:
        """Инициализация актора, подключение к БД и Redis, загрузка базовых черт"""
        try:
            # Подключаемся к БД если нужно
            if not db_connection._is_connected:
                await db_connection.connect()
            
            # Получаем пул подключений
            self._pool = db_connection.get_pool()
            
            # Подключаемся к Redis (опционально)
            try:
                if not redis_connection.is_connected():
                    await redis_connection.connect()
                self._redis = redis_connection.get_client()
                if self._redis:
                    self.logger.info("Redis connection established for caching")
                else:
                    self.logger.warning("Redis not available, working without cache")
            except Exception as e:
                self.logger.warning(f"Redis connection failed: {str(e)}, continuing without cache")
                self._redis = None
            
            # Проверяем схему БД
            await self._verify_schema()
            
            # Загружаем базовые черты личности
            await self._load_base_traits()
            
            # Загружаем резонансные профили
            await self._load_resonance_profiles()
            
            self._metrics['initialized'] = True
            
            self.logger.info("PersonalityActor initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize PersonalityActor: {str(e)}")
            self._degraded_mode = True
            self._metrics['degraded_mode_entries'] += 1
            self._metrics['db_errors'] += 1
            self.logger.warning("PersonalityActor entering degraded mode - will work without persistence")
    
    async def shutdown(self) -> None:
        """Освобождение ресурсов и логирование финальных метрик"""
        # Логируем финальные метрики
        self._log_metrics(final=True)
        
        self.logger.info("PersonalityActor shutdown completed")
    
    @measure_latency
    async def handle_message(self, message: ActorMessage) -> Optional[ActorMessage]:
        """Обработка входящих сообщений"""
        
        if message.message_type == MESSAGE_TYPES['UPDATE_PERSONALITY_CONTEXT']:
            await self._handle_update_context(message)
        elif message.message_type == MESSAGE_TYPES['GET_PERSONALITY_PROFILE']:
            await self._handle_get_profile(message)
        elif message.message_type == MESSAGE_TYPES['CLEANUP_INACTIVE_RESONANCE']:
            # Запуск очистки неактивных резонансных профилей
            deactivated = await self._deactivate_inactive_resonance_profiles()
            self.logger.info(f"Deactivated {deactivated} resonance profiles")
        else:
            # Считаем неизвестные сообщения
            self._metrics['unknown_message_count'] += 1
            self.logger.warning(
                f"Unknown message type received: {message.message_type}"
            )
        
        return None
    
    def _log_metrics(self, final: bool = False) -> None:
        """Логирование метрик"""
        log_msg = "PersonalityActor metrics"
        if final:
            log_msg = "PersonalityActor final metrics"
        
        # Форматируем счетчики по типам модификаторов
        mod_by_type = ", ".join(
            f"{t}: {c}" for t, c in self._metrics['modifiers_by_type'].items()
        )
        
        self.logger.info(
            f"{log_msg} - "
            f"Base traits loaded: {self._metrics['base_traits_loaded']}, "
            f"Core traits: {self._metrics['core_traits_count']}, "
            f"Active profiles: {self._metrics['active_profiles_count']}, "
            f"Modifiers received: {self._metrics['modifiers_received']} ({mod_by_type}), "
            f"Profiles calculated: {self._metrics['profiles_calculated']}, "
            f"Cache hits: {self._metrics['cache_hits']}, "
            f"Cache misses: {self._metrics['cache_misses']}, "
            f"Protection (core: {self._metrics['core_constraints_applied']}, "
            f"session: {self._metrics['session_limits_applied']}, "
            f"recovery: {self._metrics['recoveries_triggered']}), "
            f"Unknown messages: {self._metrics['unknown_message_count']}, "
            f"DB errors: {self._metrics['db_errors']}, "
            f"Degraded mode: {self._degraded_mode}, "
            f"Resonance (profiles: {self._metrics['resonance_profiles_loaded']}, "
            f"applications: {self._metrics['resonance_applications']}, "
            f"adaptations: {self._metrics['resonance_adaptations']}, "
            f"deviations limited: {self._metrics.get('resonance_deviations_limited', 0)}, "
            f"resets: {self._metrics.get('resonance_resets', 0)})"
        )
    
    @measure_latency
    async def _handle_update_context(self, message: ActorMessage) -> None:
        """Обработка входящих модификаторов личности"""
        user_id = message.payload.get('user_id')
        if not user_id:
            self.logger.warning("UPDATE_PERSONALITY_CONTEXT received without user_id")
            return
        
        try:
            # Импортируем модель здесь, чтобы избежать циклических импортов во время выполнения
            from models.personality_models import PersonalityModifier
            
            # Валидация через Pydantic модель
            modifier = PersonalityModifier(
                modifier_type=message.payload.get('modifier_type'),
                modifier_data=message.payload.get('modifier_data', {}),
                source_actor=message.sender_id
            )
            
            self.logger.debug(
                f"Received {modifier.modifier_type} modifiers from {modifier.source_actor} "
                f"for user {user_id}: {len(modifier.modifier_data)} traits affected"
            )
            
            # Обновляем внутреннее состояние
            if user_id not in self._current_modifiers:
                self._current_modifiers[user_id] = {}
            
            # Сохраняем модификаторы по типу
            self._current_modifiers[user_id][modifier.modifier_type] = {
                'data': modifier.modifier_data,
                'source': modifier.source_actor,
                'timestamp': message.timestamp
            }
            
            # Сохраняем в БД для истории
            await self._store_modifier_history(user_id, modifier)
            
            # Обновляем метрики
            self._metrics['modifiers_received'] += 1
            self._metrics['modifiers_by_type'][modifier.modifier_type] += 1
            
            self.logger.info(
                f"Updated {modifier.modifier_type} modifiers for user {user_id} "
                f"(total modifiers: {self._metrics['modifiers_received']})"
            )
            
            # Инвалидируем кэш профиля при обновлении модификаторов
            await self._invalidate_profile_cache(user_id)
            
        except Exception as e:
            self.logger.error(
                f"Failed to process UPDATE_PERSONALITY_CONTEXT for user {user_id}: {str(e)}"
            )
            self._metrics['db_errors'] += 1
            # Обновляем метрики даже при ошибке
            modifier_type = message.payload.get('modifier_type', 'unknown')
            self._metrics['modifiers_received'] += 1
            self._metrics['modifiers_by_type'][modifier_type] = self._metrics['modifiers_by_type'].get(modifier_type, 0) + 1
