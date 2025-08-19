from typing import Dict, Any
from datetime import datetime
import asyncio
import uuid
from actors.messages import ActorMessage, MESSAGE_TYPES
from actors.events import BaseEvent
from config.settings import (
    STM_CONTEXT_REQUEST_TIMEOUT,
    STM_CONTEXT_SIZE_FOR_GENERATION,
    PERSONALITY_ANALYSIS_ENABLED
)
from config.settings_auth import (
    AUTH_CHECK_TIMEOUT,
    AUTH_FALLBACK_TO_DEMO
)
from config.settings_ltm import (
    LTM_REQUEST_ENABLED, 
    LTM_CONTEXT_LIMIT
)
from config.prompts import PROMPT_CONFIG

class RequestHandlingMixin:
    async def _cleanup_pending_requests_loop(self) -> None:
        """Периодическая очистка зависших запросов"""
        while self.is_running:
            try:
                await asyncio.sleep(10)  # Проверка каждые 10 секунд
                await self._cleanup_expired_requests()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in cleanup loop: {str(e)}")
    
    async def _cleanup_expired_requests(self) -> None:
        """Очистка запросов старше таймаута"""
        now = datetime.now()
        expired = []
        
        for request_id, data in self._pending_requests.items():
            if (now - data['timestamp']).total_seconds() > STM_CONTEXT_REQUEST_TIMEOUT:
                expired.append(request_id)
        
        for request_id in expired:
            pending = self._pending_requests.pop(request_id)
            self.logger.warning(
                f"Context request timeout for user {pending['user_id']}, "
                f"generating without historical context"
            )
            
            # Генерируем без исторического контекста как fallback
            generate_msg = ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES['GENERATE_RESPONSE'],
                payload={
                    'user_id': pending['user_id'],
                    'chat_id': pending['chat_id'],
                    'text': pending['text'],
                    'include_prompt': pending['include_prompt'],
                    'message_count': pending['message_count'],
                    'session_data': pending['session_data'],
                    'mode': pending['mode'],
                    'mode_confidence': pending['mode_confidence'],
                    'historical_context': []  # Пустой контекст при таймауте
                }
            )
            
            if self.get_actor_system():
                await self.get_actor_system().send_message("generation", generate_msg)
        
        # Очистка зависших limit запросов
        
        expired_limits = []
        for request_id, data in self._pending_limits.items():
            if (now - data['timestamp']).total_seconds() > AUTH_CHECK_TIMEOUT:
                expired_limits.append(request_id)
        
        for request_id in expired_limits:
            pending = self._pending_limits.pop(request_id)
            self.logger.warning(
                f"Limit check timeout for user {pending['user_id']}, "
                f"continuing with demo mode"
            )
            
            # Если AUTH_FALLBACK_TO_DEMO включен - продолжить обработку
            if AUTH_FALLBACK_TO_DEMO:
                await self._continue_message_processing(pending)
    
    async def _continue_message_processing(self, pending: Dict[str, Any]) -> None:
        """Продолжить обработку после проверки лимитов"""
        # Восстановить контекст
        user_id = pending['user_id']
        text = pending['text']
        chat_id = pending['chat_id']
        # username = pending['username']
        session = pending['session']
        # message = pending['message']
        
        self.logger.debug(f"Continuing message processing for user {user_id} after limit check")
        
        # Анализ эмоций (fire-and-forget подход)
        if self.get_actor_system():
            analyze_msg = ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES['ANALYZE_EMOTION'],
                payload={
                    'user_id': user_id,
                    'text': text
                },
                reply_to=self.actor_id
            )
            await self.get_actor_system().send_message("perception", analyze_msg)
            self.logger.info("Sent ANALYZE_EMOTION")
        
        # Определение режима перенесено в _check_ready_to_generate
        # чтобы учесть Partner Persona
        
        # Обновляем счетчики
        session.message_count += 1
        session.last_activity = datetime.now()
        
        # Проверяем необходимость анализа личности
        if PERSONALITY_ANALYSIS_ENABLED and self._should_analyze_personality(session):
            # Fire-and-forget запуск анализа
            asyncio.create_task(self._run_personality_analysis(user_id, session))
            self.logger.info(f"Triggered personality analysis for user {user_id} after {session.message_count} messages")
        
        # Определяем необходимость системного промпта
        include_prompt = self._should_include_prompt(session)
        
        # Логируем решение о промпте
        if include_prompt:
            prompt_event = BaseEvent.create(
                stream_id=f"user_{user_id}",
                event_type="PromptInclusionEvent",
                data={
                    "user_id": user_id,
                    "message_count": session.message_count,
                    "strategy": PROMPT_CONFIG["prompt_strategy"],
                    "reason": self._get_prompt_reason(session)
                }
            )
            await self._append_event(prompt_event)
        
        # Сохраняем контекст генерации для последующего использования
        request_id = str(uuid.uuid4())
        self._pending_requests[request_id] = {
            'user_id': user_id,
            'chat_id': chat_id,
            'text': text,
            'include_prompt': include_prompt,
            'message_count': session.message_count,
            'session_data': {
                'username': session.username,
                'created_at': session.created_at.isoformat()
            },
            'mode': None,  # Будет определен позже в _check_ready_to_generate
            'mode_confidence': None,  # Будет определен позже
            'timestamp': datetime.now(),
            # Новые поля для отслеживания Partner Persona
            'partner_model_requested': False,
            'partner_model_received': False,
            'partner_model_data': None,
            # Новые поля для отслеживания PersonalityActor
            'personality_requested': False,
            'personality_received': False,
            'personality_data': None,
            'session': session  # Сохраняем для определения режима позже
        }
        
        # Запрашиваем исторический контекст из MemoryActor
        get_context_msg = ActorMessage.create(
            sender_id=self.actor_id,
            message_type=MESSAGE_TYPES['GET_CONTEXT'],
            payload={
                'user_id': user_id,
                'request_id': request_id,
                'limit': STM_CONTEXT_SIZE_FOR_GENERATION,
                'format_type': 'structured'  # Для DeepSeek API
            },
            reply_to=self.actor_id  # Ответ нужен нам
        )
        
        await self.get_actor_system().send_message("memory", get_context_msg)
        self.logger.info(f"Requested context for user {user_id}")
        
        # Запрашиваем Partner Persona параллельно с контекстом
        partner_model_msg = ActorMessage.create(
            sender_id=self.actor_id,
            message_type=MESSAGE_TYPES['GET_PARTNER_MODEL'],
            payload={
                'user_id': user_id,
                'request_id': request_id
            },
            reply_to=self.actor_id
        )
        await self.get_actor_system().send_message("talk_model", partner_model_msg)
        self._pending_requests[request_id]['partner_model_requested'] = True
        self.logger.info(f"Requested partner model for user {user_id}")
        
        # Запрашиваем профиль личности параллельно
        personality_msg = ActorMessage.create(
            sender_id=self.actor_id,
            message_type=MESSAGE_TYPES['GET_PERSONALITY_PROFILE'],
            payload={
                'user_id': user_id,
                'request_id': request_id
            },
            reply_to=self.actor_id
        )
        await self.get_actor_system().send_message("personality", personality_msg)
        self._pending_requests[request_id]['personality_requested'] = True
        self.logger.info(f"Requested personality profile for user {user_id}")
        
        # Проверяем необходимость запроса LTM
        if LTM_REQUEST_ENABLED:
            need_ltm, search_type = self._should_request_ltm(text, session)
            
            if need_ltm:
                # Обновляем структуру pending_request для отслеживания LTM
                self._pending_requests[request_id]['expecting_ltm'] = True
                self._pending_requests[request_id]['ltm_search_type'] = search_type
                self._pending_requests[request_id]['stm_received'] = False
                self._pending_requests[request_id]['ltm_received'] = False
                self._pending_requests[request_id]['stm_context'] = None
                self._pending_requests[request_id]['ltm_memories'] = None
                self._pending_requests[request_id]['ltm_request_timestamp'] = datetime.now()
                
                # Если векторный поиск - сначала запрашиваем embedding
                if search_type == 'vector':
                    # Помечаем ожидание embedding
                    self._pending_requests[request_id]['expecting_embedding'] = True
                    self._pending_requests[request_id]['embedding_received'] = False
                    
                    # Запрашиваем генерацию embedding
                    embedding_msg = ActorMessage.create(
                        sender_id=self.actor_id,
                        message_type=MESSAGE_TYPES['GENERATE_EMBEDDING'],
                        payload={
                            'text': text,
                            'emotions': session.last_emotion_vector or {},
                            'request_id': request_id
                        },
                        reply_to=self.actor_id
                    )
                    
                    await self.get_actor_system().send_message("ltm", embedding_msg)
                    self.logger.info(f"Requested embedding generation for user {user_id}")
                else:
                    # Для других типов поиска - сразу отправляем запрос
                    ltm_msg = ActorMessage.create(
                        sender_id=self.actor_id,
                        message_type=MESSAGE_TYPES['GET_LTM_MEMORY'],
                        payload={
                            'user_id': user_id,
                            'search_type': search_type,
                            'limit': LTM_CONTEXT_LIMIT,
                            'request_id': request_id
                        },
                        reply_to=self.actor_id
                    )
                    
                    await self.get_actor_system().send_message("ltm", ltm_msg)
                    self.logger.info(f"Requested LTM context for user {user_id} (type: {search_type})")
            else:
                # Если LTM не нужна, помечаем что не ожидаем
                self._pending_requests[request_id]['expecting_ltm'] = False
                self._pending_requests[request_id]['stm_received'] = False
                self._pending_requests[request_id]['ltm_received'] = False
                self._pending_requests[request_id]['stm_context'] = None
                self._pending_requests[request_id]['ltm_memories'] = None