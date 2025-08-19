from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime
import uuid
from enum import Enum


# Базовые типы сообщений
class MessageType(str, Enum):
    """Типы сообщений в системе акторов"""
    PING = 'ping'
    PONG = 'pong'
    ERROR = 'error'
    SHUTDOWN = 'shutdown'
    DLQ_QUEUED = 'dlq_queued'
    DLQ_PROCESSED = 'dlq_processed'
    DLQ_CLEANUP = 'dlq_cleanup'
    USER_MESSAGE = 'user_message'
    GENERATE_RESPONSE = 'generate_response'
    BOT_RESPONSE = 'bot_response'
    STREAMING_CHUNK = 'streaming_chunk'
    SESSION_CREATED = 'session_created'
    SESSION_UPDATED = 'session_updated'
    CACHE_HIT_METRIC = 'cache_hit_metric'
    PROMPT_INCLUSION = 'prompt_inclusion'
    JSON_MODE_FAILURE = 'json_mode_failure'
    TELEGRAM_MESSAGE_RECEIVED = 'telegram_message_received'
    PROCESS_USER_MESSAGE = 'process_user_message'
    SEND_TELEGRAM_RESPONSE = 'send_telegram_response'
    JSON_VALIDATION_FAILED = 'json_validation_failed'
    STRUCTURED_RESPONSE_GENERATED = 'structured_response_generated'
    MODE_DETECTED = 'mode_detected'
    MODE_FALLBACK = 'mode_fallback'
    GENERATION_PARAMETERS_USED = 'generation_parameters_used'
    PYDANTIC_VALIDATION_SUCCESS = 'pydantic_validation_success'
    PATTERN_DEBUG = 'pattern_debug'
    STORE_MEMORY = 'store_memory'
    GET_CONTEXT = 'get_context'
    CONTEXT_RESPONSE = 'context_response'
    CLEAR_USER_MEMORY = 'clear_user_memory'
    ANALYZE_EMOTION = 'analyze_emotion'
    EMOTION_RESULT = 'emotion_result'
    AUTH_REQUEST = 'auth_request'
    AUTH_RESPONSE = 'auth_response'
    CHECK_LIMIT = 'check_limit'
    LIMIT_RESPONSE = 'limit_response'
    LIMIT_EXCEEDED = 'limit_exceeded'
    ADMIN_COMMAND = 'admin_command'
    ADMIN_RESPONSE = 'admin_response'
    LOGOUT_REQUEST = 'logout_request'
    LOGOUT_RESPONSE = 'logout_response'
    SAVE_TO_LTM = 'save_to_ltm'
    GET_LTM_MEMORY = 'get_ltm_memory'
    DELETE_LTM_MEMORY = 'delete_ltm_memory'
    LTM_RESPONSE = 'ltm_response'
    EVALUATE_FOR_LTM = 'evaluate_for_ltm'
    GENERATE_EMBEDDING = 'generate_embedding'
    EMBEDDING_RESPONSE = 'embedding_response'
    COLLECT_SYSTEM_METRICS = 'collect_system_metrics'
    INITIATE_ARCHIVAL = 'initiate_archival'
    CHECK_STORAGE_ALERTS = 'check_storage_alerts'
    SYSTEM_METRICS_RESPONSE = 'system_metrics_response'
    GET_PARTNER_MODEL = 'get_partner_model'
    PARTNER_MODEL_RESPONSE = 'partner_model_response'
    UPDATE_PARTNER_MODEL = 'update_partner_model'
    UPDATE_PERSONALITY_CONTEXT = 'update_personality_context'
    GET_PERSONALITY_PROFILE = 'get_personality_profile'
    PERSONALITY_PROFILE_RESPONSE = 'personality_profile_response'
    CLEANUP_INACTIVE_RESONANCE = 'cleanup_inactive_resonance'


# Для обратной совместимости
MESSAGE_TYPES = {
    'PING': MessageType.PING,
    'PONG': MessageType.PONG,
    'ERROR': MessageType.ERROR,
    'SHUTDOWN': MessageType.SHUTDOWN,
    'DLQ_QUEUED': MessageType.DLQ_QUEUED,
    'DLQ_PROCESSED': MessageType.DLQ_PROCESSED,
    'DLQ_CLEANUP': MessageType.DLQ_CLEANUP,
    'USER_MESSAGE': MessageType.USER_MESSAGE,
    'GENERATE_RESPONSE': MessageType.GENERATE_RESPONSE,
    'BOT_RESPONSE': MessageType.BOT_RESPONSE,
    'STREAMING_CHUNK': MessageType.STREAMING_CHUNK,
    'SESSION_CREATED': MessageType.SESSION_CREATED,
    'SESSION_UPDATED': MessageType.SESSION_UPDATED,
    'CACHE_HIT_METRIC': MessageType.CACHE_HIT_METRIC,
    'PROMPT_INCLUSION': MessageType.PROMPT_INCLUSION,
    'JSON_MODE_FAILURE': MessageType.JSON_MODE_FAILURE,
    'TELEGRAM_MESSAGE_RECEIVED': MessageType.TELEGRAM_MESSAGE_RECEIVED,
    'PROCESS_USER_MESSAGE': MessageType.PROCESS_USER_MESSAGE,
    'SEND_TELEGRAM_RESPONSE': MessageType.SEND_TELEGRAM_RESPONSE,
    'JSON_VALIDATION_FAILED': MessageType.JSON_VALIDATION_FAILED,
    'STRUCTURED_RESPONSE_GENERATED': MessageType.STRUCTURED_RESPONSE_GENERATED,
    'MODE_DETECTED': MessageType.MODE_DETECTED,
    'MODE_FALLBACK': MessageType.MODE_FALLBACK,
    'GENERATION_PARAMETERS_USED': MessageType.GENERATION_PARAMETERS_USED,
    'PYDANTIC_VALIDATION_SUCCESS': MessageType.PYDANTIC_VALIDATION_SUCCESS,
    'PATTERN_DEBUG': MessageType.PATTERN_DEBUG,
    'STORE_MEMORY': MessageType.STORE_MEMORY,
    'GET_CONTEXT': MessageType.GET_CONTEXT,
    'CONTEXT_RESPONSE': MessageType.CONTEXT_RESPONSE,
    'CLEAR_USER_MEMORY': MessageType.CLEAR_USER_MEMORY,
    'ANALYZE_EMOTION': MessageType.ANALYZE_EMOTION,
    'EMOTION_RESULT': MessageType.EMOTION_RESULT,
    'AUTH_REQUEST': MessageType.AUTH_REQUEST,
    'AUTH_RESPONSE': MessageType.AUTH_RESPONSE,
    'CHECK_LIMIT': MessageType.CHECK_LIMIT,
    'LIMIT_RESPONSE': MessageType.LIMIT_RESPONSE,
    'LIMIT_EXCEEDED': MessageType.LIMIT_EXCEEDED,
    'ADMIN_COMMAND': MessageType.ADMIN_COMMAND,
    'ADMIN_RESPONSE': MessageType.ADMIN_RESPONSE,
    'LOGOUT_REQUEST': MessageType.LOGOUT_REQUEST,
    'LOGOUT_RESPONSE': MessageType.LOGOUT_RESPONSE,
    'SAVE_TO_LTM': MessageType.SAVE_TO_LTM,
    'GET_LTM_MEMORY': MessageType.GET_LTM_MEMORY,
    'DELETE_LTM_MEMORY': MessageType.DELETE_LTM_MEMORY,
    'LTM_RESPONSE': MessageType.LTM_RESPONSE,
    'EVALUATE_FOR_LTM': MessageType.EVALUATE_FOR_LTM,
    'GENERATE_EMBEDDING': MessageType.GENERATE_EMBEDDING,
    'EMBEDDING_RESPONSE': MessageType.EMBEDDING_RESPONSE,
    'COLLECT_SYSTEM_METRICS': MessageType.COLLECT_SYSTEM_METRICS,
    'INITIATE_ARCHIVAL': MessageType.INITIATE_ARCHIVAL,
    'CHECK_STORAGE_ALERTS': MessageType.CHECK_STORAGE_ALERTS,
    'SYSTEM_METRICS_RESPONSE': MessageType.SYSTEM_METRICS_RESPONSE,
    'GET_PARTNER_MODEL': MessageType.GET_PARTNER_MODEL,
    'PARTNER_MODEL_RESPONSE': MessageType.PARTNER_MODEL_RESPONSE,
    'UPDATE_PARTNER_MODEL': MessageType.UPDATE_PARTNER_MODEL,
    'UPDATE_PERSONALITY_CONTEXT': MessageType.UPDATE_PERSONALITY_CONTEXT,
    'GET_PERSONALITY_PROFILE': MessageType.GET_PERSONALITY_PROFILE,
    'PERSONALITY_PROFILE_RESPONSE': MessageType.PERSONALITY_PROFILE_RESPONSE,
    'CLEANUP_INACTIVE_RESONANCE': MessageType.CLEANUP_INACTIVE_RESONANCE
}


class ActorMessage(BaseModel):
    """Базовый класс для всех сообщений между акторами"""
    model_config = ConfigDict(
        # Разрешаем произвольные типы (для datetime)
        arbitrary_types_allowed=True,
        # Для обратной совместимости с существующим кодом
        populate_by_name=True,
        # Валидация при присваивании
        validate_assignment=True
    )
    
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender_id: Optional[str] = None
    message_type: str = ''
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)
    reply_to: Optional[str] = None  # ID актора для ответа
    
    @classmethod
    def create(cls, 
               sender_id: Optional[str] = None,
               message_type: str = '',
               payload: Optional[Dict[str, Any]] = None,
               reply_to: Optional[str] = None) -> 'ActorMessage':
        """Фабричный метод для удобного создания сообщений"""
        return cls(
            sender_id=sender_id,
            message_type=message_type,
            payload=payload or {},
            reply_to=reply_to
        )
    
    # Для обратной совместимости с кодом, который может использовать как dict
    def __getitem__(self, key):
        """Обеспечить доступ как к словарю для обратной совместимости"""
        return getattr(self, key)