"""
Response handlers mixin for UserSessionActor - Обработка ответов от других акторов
"""
from typing import Dict, Any
from actors.messages import ActorMessage, MESSAGE_TYPES
from config.settings_ltm import LTM_CONTEXT_LIMIT


class ResponseHandlersMixin:
    """Mixin для обработки ответов от других акторов"""
    
    # These attributes are available from UserSessionActor
    _pending_requests: Dict[str, Dict[str, Any]]
    _sessions: Dict[str, Any]
    logger: object
    actor_id: str
    get_actor_system: callable
    
    # Methods from main class
    _check_ready_to_generate: callable
    
    async def _handle_context_response(self, message: ActorMessage) -> None:
        """Обработка CONTEXT_RESPONSE от MemoryActor"""
        request_id = message.payload.get('request_id')
        if not request_id or request_id not in self._pending_requests:
            self.logger.warning(f"Received CONTEXT_RESPONSE with unknown request_id: {request_id}")
            return None
        
        # Сохраняем STM контекст в pending_request
        pending = self._pending_requests.get(request_id)
        if not pending:
            self.logger.warning(f"No pending request found for {request_id}")
            return None
            
        pending['stm_context'] = message.payload.get('messages', [])
        pending['stm_received'] = True
        
        self.logger.debug(
            f"Received STM context for request {request_id}: "
            f"{len(pending['stm_context'])} messages"
        )
        
        # Проверяем готовность к генерации
        await self._check_ready_to_generate(request_id)
    
    async def _handle_ltm_response(self, message: ActorMessage) -> None:
        """Обработка LTM_RESPONSE от LTMActor"""
        request_id = message.payload.get('request_id')
        if not request_id or request_id not in self._pending_requests:
            self.logger.warning(f"Received LTM_RESPONSE with unknown request_id: {request_id}")
            return None
        
        pending = self._pending_requests.get(request_id)
        if not pending:
            self.logger.warning(f"No pending request found for {request_id}")
            return None
        
        # Сохраняем LTM данные
        if message.payload.get('success', False):
            ltm_results = message.payload.get('results', [])
            pending['ltm_memories'] = ltm_results
            self.logger.info(
                f"Received LTM context for request {request_id}: "
                f"{len(ltm_results)} memories"
            )
        else:
            # В случае ошибки LTM продолжаем без воспоминаний
            pending['ltm_memories'] = []
            self.logger.warning(
                f"LTM search failed for request {request_id}: "
                f"{message.payload.get('error', 'Unknown error')}"
            )
        
        pending['ltm_received'] = True
        
        # Проверяем готовность к генерации
        await self._check_ready_to_generate(request_id)
    
    async def _handle_embedding_response(self, message: ActorMessage) -> None:
        """Обработка EMBEDDING_RESPONSE от LTMActor"""
        request_id = message.payload.get('request_id')
        if not request_id or request_id not in self._pending_requests:
            self.logger.warning(f"Received EMBEDDING_RESPONSE with unknown request_id: {request_id}")
            return None
        
        pending = self._pending_requests.get(request_id)
        if not pending:
            self.logger.warning(f"No pending request found for {request_id}")
            return None
        
        # Проверяем успешность генерации
        if message.payload.get('success', False):
            embedding = message.payload.get('embedding')
            if embedding:
                # Сохраняем embedding
                pending['query_vector'] = embedding
                pending['embedding_received'] = True
                
                self.logger.debug(
                    f"Received {len(embedding)}d embedding for request {request_id}"
                )
                
                # Теперь отправляем запрос на поиск в LTM с вектором
                user_id = pending['user_id']
                ltm_msg = ActorMessage.create(
                    sender_id=self.actor_id,
                    message_type=MESSAGE_TYPES['GET_LTM_MEMORY'],
                    payload={
                        'user_id': user_id,
                        'search_type': 'vector',
                        'query_vector': embedding,
                        'limit': LTM_CONTEXT_LIMIT,
                        'request_id': request_id
                    },
                    reply_to=self.actor_id
                )
                
                await self.get_actor_system().send_message("ltm", ltm_msg)
                self.logger.info(f"Sent vector search request for user {user_id}")
            else:
                # Embedding пустой - fallback на обычный поиск
                self.logger.warning("Received empty embedding, falling back to recent search")
                await self._fallback_to_recent_search(request_id)
        else:
            # Ошибка генерации - fallback
            error = message.payload.get('error', 'Unknown error')
            self.logger.warning(f"Embedding generation failed: {error}, falling back to recent search")
            await self._fallback_to_recent_search(request_id)
    
    async def _handle_partner_model_response(self, message: ActorMessage) -> None:
        """Обработка PARTNER_MODEL_RESPONSE от TalkModelActor"""
        request_id = message.payload.get('request_id')
        if request_id and request_id in self._pending_requests:
            pending = self._pending_requests.get(request_id)
            if pending:
                pending['partner_model_received'] = True
                pending['partner_model_data'] = {
                    'recommended_mode': message.payload.get('recommended_mode'),
                    'mode_confidence': message.payload.get('mode_confidence', 0.0),
                    'degraded_mode': message.payload.get('degraded_mode', False)
                }
                self.logger.debug(
                    f"Received partner model for request {request_id}: "
                    f"mode={message.payload.get('recommended_mode')}, "
                    f"confidence={message.payload.get('mode_confidence', 0.0):.2f}"
                )
                # Проверяем готовность к генерации
                await self._check_ready_to_generate(request_id)
    
    async def _fallback_to_recent_search(self, request_id: str) -> None:
        """
        Fallback на поиск recent при ошибке генерации embedding
        
        Args:
            request_id: ID запроса
        """
        pending = self._pending_requests.get(request_id)
        if not pending:
            return
        
        # Помечаем что embedding получен (хоть и неудачно)
        pending['embedding_received'] = True
        pending['query_vector'] = None
        
        # Отправляем запрос с fallback типом поиска
        user_id = pending['user_id']
        ltm_msg = ActorMessage.create(
            sender_id=self.actor_id,
            message_type=MESSAGE_TYPES['GET_LTM_MEMORY'],
            payload={
                'user_id': user_id,
                'search_type': 'recent',  # Fallback на recent
                'limit': LTM_CONTEXT_LIMIT,
                'request_id': request_id
            },
            reply_to=self.actor_id
        )
        
        await self.get_actor_system().send_message("ltm", ltm_msg)
        self.logger.info(f"Fallback to recent search for user {user_id}")
    
    async def _handle_personality_response(self, message: ActorMessage) -> None:
        """Обработка PERSONALITY_PROFILE_RESPONSE от PersonalityActor"""
        request_id = message.payload.get('request_id')
        if not request_id or request_id not in self._pending_requests:
            self.logger.warning(f"Received PERSONALITY_PROFILE_RESPONSE with unknown request_id: {request_id}")
            return None
        
        pending = self._pending_requests.get(request_id)
        if not pending:
            self.logger.warning(f"No pending request found for {request_id}")
            return None
        
        # Сохраняем данные профиля личности
        pending['personality_received'] = True
        pending['personality_data'] = {
            'active_traits': message.payload.get('active_traits', {}),
            'dominant_traits': message.payload.get('dominant_traits', []),
            'profile_metrics': message.payload.get('profile_metrics', {}),
            'protection_applied': message.payload.get('protection_applied', [])
        }
        
        self.logger.info(
            f"Received personality profile for request {request_id}: "
            f"dominant traits: {', '.join(message.payload.get('dominant_traits', [])[:3])}"
        )
        
        # Проверяем готовность к генерации
        await self._check_ready_to_generate(request_id)