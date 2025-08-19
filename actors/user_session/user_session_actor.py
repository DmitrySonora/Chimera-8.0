from typing import Dict, Optional, List, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict
from datetime import datetime
import asyncio
import uuid
from uuid import UUID
from actors.base_actor import BaseActor
from actors.messages import ActorMessage, MESSAGE_TYPES
from actors.events import BaseEvent
from actors.user_session.mode_detection import ModeDetectionMixin
from actors.user_session.prompt_management import PromptManagementMixin
from actors.user_session.request_handling import RequestHandlingMixin
from actors.user_session.ltm_coordination import LTMCoordinationMixin
from actors.user_session.response_handlers_mixin import ResponseHandlersMixin
from actors.user_session.emotion_handler_mixin import EmotionHandlerMixin
from actors.user_session.personality_analysis_mixin import PersonalityAnalysisMixin
from config.settings import (
    DAILY_MESSAGE_LIMIT,
    MODE_HISTORY_SIZE,
    PARTNER_MODEL_REQUEST_TIMEOUT,
    PARTNER_MODE_CONFIDENCE_THRESHOLD,
    PERSONALITY_REQUEST_TIMEOUT
)
from config.settings_ltm import (
    LTM_REQUEST_TIMEOUT
)
from config.messages import USER_MESSAGES
from utils.monitoring import measure_latency
from utils.event_utils import EventVersionManager

class UserSession(BaseModel):
    """Данные сессии пользователя"""
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True
    )
    
    user_id: str
    username: Optional[str] = None
    message_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    last_activity: datetime = Field(default_factory=datetime.now)
    cache_metrics: List[float] = Field(default_factory=list)
    
    # Поля для режимов общения
    current_mode: str = 'talk'
    mode_confidence: float = 0.0
    mode_history: List[str] = Field(default_factory=list)
    last_mode_change: Optional[datetime] = None
    
    # Расширяемость для будущего
    emotional_state: Optional[Any] = None
    style_vector: Optional[Any] = None
    memory_buffer: List[Any] = Field(default_factory=list)
    
    # Поля для эмоций
    last_emotion_vector: Optional[Dict[str, float]] = None
    last_dominant_emotions: List[str] = Field(default_factory=list)
    
    # Поля для координации LTM
    last_user_text: Optional[str] = None
    last_bot_response: Optional[str] = None
    last_bot_mode: Optional[str] = None
    last_bot_confidence: Optional[float] = None
    
    # Поля для анализа личности (Фаза 7.1)
    partner_persona_id: Optional[UUID] = None
    partner_persona_version: Optional[int] = None
    traits_detected_count: int = 0
    
    @field_validator('mode_confidence')
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        from config.settings import PYDANTIC_CONFIDENCE_MIN, PYDANTIC_CONFIDENCE_MAX
        if not PYDANTIC_CONFIDENCE_MIN <= v <= PYDANTIC_CONFIDENCE_MAX:
            raise ValueError(f'Mode confidence must be between {PYDANTIC_CONFIDENCE_MIN} and {PYDANTIC_CONFIDENCE_MAX}')
        return v
    
    @field_validator('current_mode')
    @classmethod
    def validate_mode(cls, v: str) -> str:
        valid_modes = ['talk', 'expert', 'creative', 'base']
        if v not in valid_modes:
            raise ValueError(f'Invalid mode: {v}. Must be one of: {valid_modes}')
        return v
    
    @field_validator('mode_history')
    @classmethod
    def validate_mode_history_size(cls, v: List[str]) -> List[str]:
        from config.settings import PYDANTIC_MODE_HISTORY_MAX_SIZE
        if len(v) > PYDANTIC_MODE_HISTORY_MAX_SIZE:
            # Обрезаем до максимального размера
            return v[-PYDANTIC_MODE_HISTORY_MAX_SIZE:]
        return v
    
    @field_validator('cache_metrics')
    @classmethod
    def validate_cache_metrics_size(cls, v: List[float]) -> List[float]:
        from config.settings import PYDANTIC_CACHE_METRICS_MAX_SIZE
        if len(v) > PYDANTIC_CACHE_METRICS_MAX_SIZE:
            # Обрезаем до максимального размера
            return v[-PYDANTIC_CACHE_METRICS_MAX_SIZE:]
        return v

class UserSessionActor(BaseActor, ModeDetectionMixin, PromptManagementMixin, RequestHandlingMixin, LTMCoordinationMixin, ResponseHandlersMixin, EmotionHandlerMixin, PersonalityAnalysisMixin):
    """
    Координатор сессий пользователей.
    Управляет жизненным циклом сессий и определяет необходимость системного промпта.
    """
    
    def __init__(self):
        super().__init__("user_session", "UserSession")
        self._sessions: Dict[str, UserSession] = {}
        self._event_version_manager = EventVersionManager()
        self._last_detection_details = {}
        self._pending_requests: Dict[str, Dict[str, Any]] = {}  # Для связывания контекстных запросов
        self._pending_limits: Dict[str, Dict[str, Any]] = {}  # Для CHECK_LIMIT запросов
        self._cleanup_task: Optional[asyncio.Task] = None  # Задача очистки зависших запросов
    
    async def initialize(self) -> None:
        """Инициализация актора"""
        # Запускаем периодическую очистку зависших запросов
        self._cleanup_task = asyncio.create_task(self._cleanup_pending_requests_loop())
        self.logger.info("UserSessionActor initialized")
        
    async def shutdown(self) -> None:
        """Освобождение ресурсов"""
        # Останавливаем задачу очистки
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
                
        session_count = len(self._sessions)
        self._sessions.clear()
        self.logger.info(f"UserSessionActor shutdown, cleared {session_count} sessions")
    
    @measure_latency
    async def handle_message(self, message: ActorMessage) -> Optional[ActorMessage]:
        """Обработка входящих сообщений"""
        
        # Обработка USER_MESSAGE
        if message.message_type == MESSAGE_TYPES['USER_MESSAGE']:
            generate_msg = await self._handle_user_message(message)
            # Отправляем в GenerationActor
            if generate_msg and self.get_actor_system():
                await self.get_actor_system().send_message("generation", generate_msg)
            
        # Обработка метрик кэша для адаптивной стратегии
        elif message.message_type == MESSAGE_TYPES['CACHE_HIT_METRIC']:
            await self._update_cache_metrics(message)
            
        # Обработка BOT_RESPONSE для сохранения в память
        elif message.message_type == MESSAGE_TYPES['BOT_RESPONSE']:
            # Сохраняем ответ бота для LTM координации
            user_id = message.payload.get('user_id')
            if user_id and user_id in self._sessions:
                session = self._sessions[user_id]
                session.last_bot_response = message.payload['text']
                session.last_bot_mode = session.current_mode
                session.last_bot_confidence = session.mode_confidence
                
                # Проверяем необходимость сохранения в LTM
                # К этому моменту у нас есть: user_text, emotions, bot_response
                if session.last_emotion_vector and session.last_user_text and session.last_bot_response:
                    if self._should_save_to_ltm(session.last_emotion_vector):
                        # Подготавливаем данные для оценки
                        ltm_payload = self._prepare_ltm_evaluation(
                            session=session,
                            user_text=session.last_user_text,
                            bot_response=session.last_bot_response,
                            emotions_data={
                                'emotions': session.last_emotion_vector,
                                'dominant_emotions': session.last_dominant_emotions
                            }
                        )
                        
                        # Отправляем на оценку в LTMActor
                        await self._request_ltm_evaluation(ltm_payload)
            
            # Сохраняем ответ бота в память
            if self.get_actor_system():
                store_msg = ActorMessage.create(
                    sender_id=self.actor_id,
                    message_type=MESSAGE_TYPES['STORE_MEMORY'],
                    payload={
                        'user_id': message.payload['user_id'],
                        'message_type': 'bot',
                        'content': message.payload['text'],
                        'metadata': {
                            'generated_at': message.payload.get('generated_at', datetime.now().isoformat()),
                            'mode': session.last_bot_mode if session.last_bot_mode else session.current_mode,
                            'mode_confidence': session.last_bot_confidence if session.last_bot_confidence else session.mode_confidence
                        }
                    }
                )
                await self.get_actor_system().send_message("memory", store_msg)
        
        # Обработка CONTEXT_RESPONSE от MemoryActor
        elif message.message_type == MESSAGE_TYPES['CONTEXT_RESPONSE']:
            await self._handle_context_response(message)
            
        # Обработка LTM_RESPONSE от LTMActor
        elif message.message_type == MESSAGE_TYPES['LTM_RESPONSE']:
            await self._handle_ltm_response(message)
            
        # Обработка EMBEDDING_RESPONSE от LTMActor
        elif message.message_type == MESSAGE_TYPES['EMBEDDING_RESPONSE']:
            await self._handle_embedding_response(message)
            
        # Обработка LIMIT_RESPONSE от AuthActor
        elif message.message_type == MESSAGE_TYPES['LIMIT_RESPONSE']:
            # Пропускаем сообщения для команд /status и /auth
            if message.payload.get('is_status_check') or message.payload.get('is_auth_check'):
                return None  # Пропускаем дальше, не обрабатываем
                
            request_id = message.payload.get('request_id')
            if not request_id or request_id not in self._pending_limits:
                self.logger.warning(f"Received LIMIT_RESPONSE with unknown request_id: {request_id}")
                return None
            
            # Извлечь сохраненный контекст
            pending = self._pending_limits.pop(request_id)
            
            # Проверяем предупреждения
            if message.payload.get('approaching_limit'):
                # Отправляем предупреждение о приближении к лимиту
                warning_msg = ActorMessage.create(
                    sender_id=self.actor_id,
                    message_type=MESSAGE_TYPES['BOT_RESPONSE'],
                    payload={
                        'user_id': pending['user_id'],
                        'chat_id': pending['chat_id'],
                        'text': USER_MESSAGES["limit_warning"].format(
                            messages_remaining=message.payload['messages_remaining'],
                            limit=message.payload['limit']
                        )
                    }
                )
                if self.get_actor_system():
                    await self.get_actor_system().send_message("telegram", warning_msg)
            
            if message.payload.get('subscription_expiring'):
                # Отправляем предупреждение об истечении подписки
                days_remaining = message.payload['days_remaining']
                message_key = "subscription_expiring_today" if days_remaining == 0 else "subscription_expiring"
                
                expiry_msg = ActorMessage.create(
                    sender_id=self.actor_id,
                    message_type=MESSAGE_TYPES['BOT_RESPONSE'],
                    payload={
                        'user_id': pending['user_id'],
                        'chat_id': pending['chat_id'],
                        'text': USER_MESSAGES[message_key].format(
                            days_remaining=days_remaining
                        ) if days_remaining > 0 else USER_MESSAGES[message_key]
                    }
                )
                if self.get_actor_system():
                    await self.get_actor_system().send_message("telegram", expiry_msg)
            
            # Проверить лимиты
            unlimited = message.payload.get('unlimited', False)
            messages_today = message.payload.get('messages_today', 0)
            limit = message.payload.get('limit', DAILY_MESSAGE_LIMIT)
            
            # Если демо-пользователь превысил лимит
            if not unlimited and messages_today >= limit:
                self.logger.warning(
                    f"User {pending['user_id']} exceeded daily limit: "
                    f"{messages_today}/{limit} messages"
                )
                
                # Создаем событие превышения лимита
                from actors.events import LimitExceededEvent
                limit_event = LimitExceededEvent.create(
                    user_id=pending['user_id'],
                    messages_today=messages_today,
                    daily_limit=limit
                )
                await self._event_version_manager.append_event(limit_event, self.get_actor_system())
                self.logger.info(f"Created LimitExceededEvent for user {pending['user_id']}")
                
                # Отправить уведомление пользователю
                limit_exceeded_msg = ActorMessage.create(
                    sender_id=self.actor_id,
                    message_type=MESSAGE_TYPES['LIMIT_EXCEEDED'],
                    payload={
                        'user_id': pending['user_id'],
                        'chat_id': pending['chat_id'],
                        'messages_today': messages_today,
                        'limit': limit
                    }
                )
                
                if self.get_actor_system():
                    await self.get_actor_system().send_message("telegram", limit_exceeded_msg)
                    self.logger.info(f"Sent LIMIT_EXCEEDED to telegram for user {pending['user_id']}")
                                
                return None
            
            # Если лимит не превышен - продолжить обработку
            self.logger.info(f"User {pending['user_id']} within limits, processing message")
            await self._continue_message_processing(pending)
            
        # Обработка PARTNER_MODEL_RESPONSE от TalkModelActor
        elif message.message_type == MESSAGE_TYPES['PARTNER_MODEL_RESPONSE']:
            await self._handle_partner_model_response(message)
            
        # Обработка EMOTION_RESULT от PerceptionActor
        elif message.message_type == MESSAGE_TYPES['EMOTION_RESULT']:
            await self._handle_emotion_result(message)
        
        # Обработка PERSONALITY_PROFILE_RESPONSE от PersonalityActor
        elif message.message_type == MESSAGE_TYPES['PERSONALITY_PROFILE_RESPONSE']:
            await self._handle_personality_response(message)
        
        return None
    
    async def _handle_user_message(self, message: ActorMessage) -> ActorMessage:
        """Обработка сообщения от пользователя"""
        user_id = message.payload['user_id']
        username = message.payload.get('username')
        text = message.payload['text']
        chat_id = message.payload['chat_id']
        
        # Получаем или создаем сессию
        session = await self._get_or_create_session(user_id, username)
        
        # Сохраняем полный текст для LTM координации
        session.last_user_text = text
        
        # Отправляем запрос на проверку лимитов
        limit_request_id = str(uuid.uuid4())
        self._pending_limits[limit_request_id] = {
            'user_id': user_id,
            'timestamp': datetime.now(),
            'chat_id': chat_id,
            'text': text,
            'username': username,
            'session': session,
            'message': message
        }
        
        check_limit_msg = ActorMessage.create(
            sender_id=self.actor_id,
            message_type=MESSAGE_TYPES['CHECK_LIMIT'],
            payload={
                'user_id': user_id,
                'request_id': limit_request_id
            }
        )
        
        await self.get_actor_system().send_message("auth", check_limit_msg)
        self.logger.info(f"Sent CHECK_LIMIT for user {user_id}, request_id: {limit_request_id}")
        
        # Ждем LIMIT_RESPONSE перед продолжением
        return None
    
    async def _get_or_create_session(self, user_id: str, username: Optional[str]) -> UserSession:
        """Получить существующую или создать новую сессию"""
        if user_id not in self._sessions:
            session = UserSession(user_id=user_id, username=username)
            self._sessions[user_id] = session
            
            # Событие о создании сессии
            event = BaseEvent.create(
                stream_id=f"user_{user_id}",
                event_type="SessionCreatedEvent",
                data={
                    "user_id": user_id,
                    "username": username,
                    "created_at": session.created_at.isoformat()
                }
            )
            
            # Сохраняем событие
            await self._append_event(event)
            
            self.logger.info(f"Created new session for user {user_id}")
        
        return self._sessions[user_id]
    
    async def _check_ready_to_generate(self, request_id: str) -> None:
        """
        Проверить готовность к генерации и отправить если готово
        
        Args:
            request_id: ID запроса для проверки
        """
        pending = self._pending_requests.get(request_id)
        if not pending:
            return
        
        # Проверяем условия готовности
        stm_ready = pending.get('stm_received', False)
        expecting_ltm = pending.get('expecting_ltm', False)
        ltm_ready = pending.get('ltm_received', False)
        expecting_embedding = pending.get('expecting_embedding', False)
        embedding_received = pending.get('embedding_received', False)
        
        # Проверка готовности Partner Persona
        partner_model_ready = pending.get('partner_model_received', False) or not pending.get('partner_model_requested', False)
        
        # Проверка готовности PersonalityActor
        personality_ready = pending.get('personality_received', False) or not pending.get('personality_requested', False)
        
        # Если ожидаем embedding и он еще не получен - не готовы
        if expecting_embedding and not embedding_received:
            # Проверка таймаута для embedding
            from config.settings_ltm import LTM_EMBEDDING_REQUEST_TIMEOUT
            ltm_timestamp = pending.get('ltm_request_timestamp')
            if ltm_timestamp:
                elapsed = (datetime.now() - ltm_timestamp).total_seconds()
                if elapsed > LTM_EMBEDDING_REQUEST_TIMEOUT:
                    self.logger.debug(f"Embedding timeout for request {request_id} after {elapsed:.2f}s")
                    # Fallback на обычный поиск
                    await self._fallback_to_recent_search(request_id)
                    return
            return  # Еще ждем embedding
        
        # Проверка таймаута LTM
        ltm_timeout = False
        if expecting_ltm and not ltm_ready:
            ltm_timestamp = pending.get('ltm_request_timestamp')
            if ltm_timestamp:
                elapsed = (datetime.now() - ltm_timestamp).total_seconds()
                if elapsed > LTM_REQUEST_TIMEOUT:
                    ltm_timeout = True
                    self.logger.debug(f"LTM timeout for request {request_id} after {elapsed:.2f}s")
        
        # Проверка таймаута Partner Model
        if pending.get('partner_model_requested') and not pending.get('partner_model_received'):
            request_timestamp = pending.get('timestamp')
            if request_timestamp:
                elapsed = (datetime.now() - request_timestamp).total_seconds()
                if elapsed > PARTNER_MODEL_REQUEST_TIMEOUT:
                    self.logger.debug(f"Partner model timeout for request {request_id}")
                    # Обновляем готовность с учетом таймаута
                    partner_model_ready = True
        
        # Проверка таймаута PersonalityActor
        if pending.get('personality_requested') and not pending.get('personality_received'):
            request_timestamp = pending.get('timestamp')
            if request_timestamp:
                elapsed = (datetime.now() - request_timestamp).total_seconds()
                if elapsed > PERSONALITY_REQUEST_TIMEOUT:
                    self.logger.debug(f"Personality profile timeout for request {request_id}")
                    # Обновляем готовность с учетом таймаута
                    personality_ready = True
        
        # Готовы если:
        # 1. STM получен И Partner Persona готова И PersonalityActor готов И (LTM получен ИЛИ не ожидаем LTM ИЛИ таймаут)
        ready = stm_ready and partner_model_ready and personality_ready and (ltm_ready or not expecting_ltm or ltm_timeout)
        
        if not ready:
            return
        
        # Удаляем из pending и создаем сообщение для генерации
        pending = self._pending_requests.pop(request_id)
        
        # Извлекаем данные Partner Persona
        partner_data = pending.get('partner_model_data', {})
        partner_mode = partner_data.get('recommended_mode')
        partner_confidence = partner_data.get('mode_confidence', 0.0)
        
        # Определяем режим с учетом Partner Persona
        session = pending['session']
        text = pending['text']
        new_mode, confidence = self._determine_generation_mode(
            text, 
            session,
            partner_mode=partner_mode,
            partner_confidence=partner_confidence
        )
        
        # Обновляем сессию
        if new_mode != session.current_mode:
            session.last_mode_change = datetime.now()
            session.current_mode = new_mode
            
            # Создаем событие об изменении режима
            mode_event = BaseEvent.create(
                stream_id=f"user_{pending['user_id']}",
                event_type="ModeDetectedEvent",
                data={
                    "user_id": pending['user_id'],
                    "mode": new_mode,
                    "confidence": confidence,
                    "previous_mode": session.mode_history[-2] if len(session.mode_history) > 1 else None,
                    "detection_details": getattr(self, '_last_detection_details', {}),
                    "source": "partner_persona" if partner_mode and partner_confidence > PARTNER_MODE_CONFIDENCE_THRESHOLD else "text_analysis",
                    "timestamp": datetime.now().isoformat()
                }
            )
            await self._append_event(mode_event)
        
        session.mode_confidence = confidence
        session.mode_history.append(new_mode)
        if len(session.mode_history) > MODE_HISTORY_SIZE:
            session.mode_history.pop(0)
        
        # Логирование источника определения режима
        if partner_mode and partner_confidence > PARTNER_MODE_CONFIDENCE_THRESHOLD:
            self.logger.info(
                f"Mode from partner_persona: {new_mode} "
                f"(confidence: {confidence:.2f})"
            )
        else:
            self.logger.info(
                f"Mode from text_analysis: {new_mode} "
                f"(confidence: {confidence:.2f})"
            )
        
        # Теперь используем определенный режим
        pending['mode'] = new_mode
        pending['mode_confidence'] = confidence
        
        # Подготавливаем payload с LTM если есть
        generate_payload = {
            'user_id': pending['user_id'],
            'chat_id': pending['chat_id'],
            'text': pending['text'],
            'include_prompt': pending['include_prompt'],
            'message_count': pending['message_count'],
            'session_data': pending['session_data'],
            'mode': pending['mode'],
            'mode_confidence': pending['mode_confidence'],
            'historical_context': pending.get('stm_context', []),
            'ltm_memories': pending.get('ltm_memories', []),
            'personality_profile': pending.get('personality_data')
        }
        
        # Логируем использование LTM
        if pending.get('ltm_memories'):
            self.logger.info(
                f"Generated with LTM: {len(pending['ltm_memories'])} memories for user {pending['user_id']}"
            )
        
        # Создаем и отправляем сообщение
        generate_msg = ActorMessage.create(
            sender_id=self.actor_id,
            message_type=MESSAGE_TYPES['GENERATE_RESPONSE'],
            payload=generate_payload
        )
        
        if self.get_actor_system():
            await self.get_actor_system().send_message("generation", generate_msg)
    
    async def _append_event(self, event: BaseEvent) -> None:
        """Добавить событие через менеджер версий"""
        await self._event_version_manager.append_event(event, self.get_actor_system())