"""
PersonalityAnalysisMixin - координатор периодического анализа стиля и черт личности.
Запускается каждые N сообщений для обновления Partner Persona.
"""
import asyncio
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime

from actors.messages import ActorMessage, MESSAGE_TYPES
from config.settings import (
    PERSONALITY_ANALYSIS_BATCH_SIZE,
    PERSONALITY_ANALYSIS_HISTORY_LIMIT,
    PERSONALITY_ANALYSIS_ENABLED
)
from config.logging import get_logger
from database.connection import db_connection

# Импорты сервисов анализа
from services.style_analyzer import StyleAnalyzer
from services.trait_detector import TraitDetector
from services.partner_persona_builder import PartnerPersonaBuilder


class PersonalityAnalysisMixin:
    """
    Миксин для периодического анализа личности в UserSessionActor.
    Координирует работу трех сервисов анализа и обновляет Partner Persona.
    """
    
    def _should_analyze_personality(self, session) -> bool:
        """
        Проверка условий для запуска анализа личности.
        
        Args:
            session: UserSession объект
            
        Returns:
            bool: True если нужно запустить анализ
        """
        # Проверяем включен ли функционал
        if not PERSONALITY_ANALYSIS_ENABLED:
            return False
            
        # Проверяем кратность сообщений
        if session.message_count % PERSONALITY_ANALYSIS_BATCH_SIZE != 0:
            return False
            
        # Проверяем минимальное количество сообщений
        if session.message_count < PERSONALITY_ANALYSIS_BATCH_SIZE:
            return False
            
        return True
    
    async def _run_personality_analysis(self, user_id: str, session) -> None:
        """
        Координация анализа стиля и черт личности.
        Выполняется асинхронно без блокировки основного потока.
        
        Args:
            user_id: ID пользователя
            session: UserSession объект
        """
        analysis_start = datetime.now()
        logger = get_logger("personality_analysis")
        
        logger.info(f"Starting personality analysis for user {user_id} after {session.message_count} messages")
        
        try:
            # 1. Запрашиваем историю сообщений через GET_CONTEXT
            context_messages = await self._request_message_history(user_id, logger)
            if not context_messages:
                logger.warning(f"No messages retrieved for user {user_id}, skipping analysis")
                return
                
            # 2. Разделяем сообщения на user и bot
            user_messages = [msg for msg in context_messages if msg.get('type') == 'user' or msg.get('role') == 'user']
            bot_messages = [msg for msg in context_messages if msg.get('type') == 'bot' or msg.get('role') == 'assistant']
            
            logger.debug(f"Retrieved {len(user_messages)} user messages and {len(bot_messages)} bot messages")
            
            # 3. Анализ стиля пользователя
            style_result = await self._analyze_user_style(user_id, user_messages, logger)
            if not style_result:
                logger.error(f"Style analysis failed for user {user_id}")
                return
                
            # 4. Детекция черт Химеры
            detected_traits = await self._detect_chimera_traits(user_id, bot_messages, logger)
            
            # 5. Построение Partner Persona
            persona_result = await self._build_partner_persona(user_id, style_result, logger)
            if not persona_result:
                logger.error(f"Partner persona building failed for user {user_id}")
                return
                
            # 6. События НЕ создаем в фоновой задаче - это вызывает конфликты версий
            # TalkModelActor сохраняет все данные в БД через UPDATE_PARTNER_MODEL
            
            # 7. Отправка UPDATE_PARTNER_MODEL в TalkModelActor
            await self._send_update_partner_model(
                user_id=user_id,
                style_result=style_result,
                persona_result=persona_result,
                detected_traits=detected_traits,
                messages_analyzed=len(context_messages),
                logger=logger
            )
            
            analysis_time = (datetime.now() - analysis_start).total_seconds()
            logger.info(
                f"Personality analysis completed for user {user_id} in {analysis_time:.2f}s. "
                f"Style: {style_result['style_vector']}, "
                f"Traits detected: {len(detected_traits)}, "
                f"Recommended mode: {persona_result.get('recommended_mode', 'unknown')}"
            )
            
        except Exception as e:
            logger.error(f"Error in personality analysis for user {user_id}: {str(e)}", exc_info=True)
    
    async def _request_message_history(self, user_id: str, logger) -> List[Dict[str, Any]]:
        """
        Запрашивает историю сообщений через GET_CONTEXT.
        
        Returns:
            List[Dict]: Список сообщений или пустой список при ошибке
        """
        # Создаем Future для ожидания ответа
        response_future = asyncio.Future()
        request_id = str(uuid.uuid4())
        
        # Временный обработчик для CONTEXT_RESPONSE
        async def handle_context_response(msg: ActorMessage):
            if (msg.message_type == MESSAGE_TYPES['CONTEXT_RESPONSE'] and 
                msg.payload.get('request_id') == request_id):
                response_future.set_result(msg.payload)
        
        # Сохраняем оригинальный handle_message для восстановления
        original_handle = self.handle_message
        
        # Временно переопределяем handle_message
        async def temporary_handle(msg: ActorMessage):
            await handle_context_response(msg)
            return await original_handle(msg)
        
        self.handle_message = temporary_handle
        
        try:
            # Отправляем запрос на получение контекста
            get_context_msg = ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES['GET_CONTEXT'],
                payload={
                    'user_id': user_id,
                    'request_id': request_id,
                    'limit': PERSONALITY_ANALYSIS_HISTORY_LIMIT,
                    'format_type': 'text'  # Для анализа нужен текстовый формат
                },
                reply_to=self.actor_id
            )
            
            if self.get_actor_system():
                await self.get_actor_system().send_message("memory", get_context_msg)
                
            # Ждем ответ с таймаутом
            context_data = await asyncio.wait_for(response_future, timeout=5.0)
            return context_data.get('messages', [])
            
        except asyncio.TimeoutError:
            logger.warning(f"Context request timeout for user {user_id}")
            return []
        except Exception as e:
            logger.error(f"Error requesting context: {str(e)}")
            return []
        finally:
            # Восстанавливаем оригинальный handle_message
            self.handle_message = original_handle
    
    async def _analyze_user_style(self, user_id: str, user_messages: List[Dict], logger) -> Optional[Dict[str, Any]]:
        """
        Анализирует стиль общения пользователя.
        
        Returns:
            Dict с результатами анализа или None при ошибке
        """
        try:
            # Убеждаемся что БД подключена
            if not db_connection._is_connected:
                await db_connection.connect()
                
            # Создаем анализатор
            style_analyzer = StyleAnalyzer(db_connection.get_pool())
            
            # Передаем сообщения для анализа
            # StyleAnalyzer ожидает сообщения из БД, поэтому адаптируем формат
            adapted_messages = []
            for msg in user_messages:
                adapted_messages.append({
                    'content': msg.get('content', ''),
                    'metadata': msg.get('metadata', {}),
                    'timestamp': msg.get('timestamp', datetime.now())
                })
            
            # Временно заменяем метод _get_user_messages чтобы использовать наши данные
            original_get_messages = style_analyzer._get_user_messages
            
            async def mock_get_messages(uid, limit):
                return adapted_messages[:limit]
            
            style_analyzer._get_user_messages = mock_get_messages
            
            # Выполняем анализ
            result = await style_analyzer.analyze_user_style(user_id, limit=len(adapted_messages))
            
            # Восстанавливаем оригинальный метод
            style_analyzer._get_user_messages = original_get_messages
            
            return result
            
        except Exception as e:
            logger.error(f"Style analysis error: {str(e)}")
            return None
    
    async def _detect_chimera_traits(self, user_id: str, bot_messages: List[Dict], logger) -> List[Dict[str, Any]]:
        """
        Детектирует черты личности Химеры в ее ответах.
        
        Returns:
            List[Dict]: Список обнаруженных черт
        """
        try:
            # Убеждаемся что БД подключена
            if not db_connection._is_connected:
                await db_connection.connect()
                
            # Создаем детектор
            trait_detector = TraitDetector(db_connection.get_pool())
            
            # Адаптируем формат сообщений
            adapted_messages = []
            for msg in bot_messages:
                adapted_messages.append({
                    'content': msg.get('content', ''),
                    'metadata': msg.get('metadata', {}),
                    'timestamp': msg.get('timestamp', datetime.now())
                })
            
            # Временно заменяем метод _get_bot_messages
            original_get_messages = trait_detector._get_bot_messages
            
            async def mock_get_messages(uid, limit):
                return adapted_messages[:limit]
            
            trait_detector._get_bot_messages = mock_get_messages
            
            # Выполняем детекцию
            manifestations = await trait_detector.detect_traits(user_id, limit=len(adapted_messages))
            
            # Восстанавливаем оригинальный метод
            trait_detector._get_bot_messages = original_get_messages
            
            # Конвертируем в формат для UPDATE_PARTNER_MODEL
            detected_traits = []
            for m in manifestations:
                detected_traits.append({
                    'trait_name': m.trait_name,
                    'strength': m.manifestation_strength,
                    'context': f"Mode: {m.mode}, Markers: {', '.join(m.detected_markers[:3])}"
                })
            
            return detected_traits
            
        except Exception as e:
            logger.error(f"Trait detection error: {str(e)}")
            return []
    
    async def _build_partner_persona(self, user_id: str, style_result: Dict[str, Any], logger) -> Optional[Dict[str, Any]]:
        """
        Строит или обновляет Partner Persona.
        
        Returns:
            Dict с данными персоны или None при ошибке
        """
        try:
            # Убеждаемся что БД подключена
            if not db_connection._is_connected:
                await db_connection.connect()
                
            # Создаем builder
            persona_builder = PartnerPersonaBuilder(db_connection.get_pool())
            
            # Строим персону
            persona = await persona_builder.build_or_update_persona(user_id, style_result)
            
            # Конвертируем в словарь для передачи
            return {
                'persona_id': str(persona.persona_id),
                'version': persona.version,
                'recommended_mode': persona.recommended_mode,
                'mode_confidence': persona.mode_confidence,
                'style_vector': persona.style_vector.model_dump()
            }
            
        except Exception as e:
            logger.error(f"Partner persona building error: {str(e)}")
            return None
    
    async def _send_update_partner_model(
        self,
        user_id: str,
        style_result: Dict[str, Any],
        persona_result: Dict[str, Any],
        detected_traits: List[Dict[str, Any]],
        messages_analyzed: int,
        logger
    ) -> None:
        """
        Отправляет UPDATE_PARTNER_MODEL в TalkModelActor.
        """
        try:
            # Формируем payload согласно ТЗ
            update_payload = {
                'user_id': user_id,
                'style_vector': style_result['style_vector'],
                'recommended_mode': persona_result['recommended_mode'],
                'mode_confidence': persona_result['mode_confidence'],
                'detected_traits': detected_traits,
                'analysis_metadata': {
                    'messages_analyzed': messages_analyzed,
                    'timestamp': datetime.now().isoformat(),
                    'version': persona_result['version']
                }
            }
            
            # Создаем сообщение
            update_msg = ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES['UPDATE_PARTNER_MODEL'],
                payload=update_payload
            )
            
            # Отправляем в TalkModelActor
            if self.get_actor_system():
                await self.get_actor_system().send_message("talk_model", update_msg)
                logger.info(f"Sent UPDATE_PARTNER_MODEL for user {user_id}")
            
            # Отправляем стиль в PersonalityActor для резонанса
            # Преобразуем стиль (0.0-1.0) в модификаторы (0.5-1.5)
            style_modifiers = {
                component: 0.5 + value
                for component, value in style_result['style_vector'].items()
            }
            
            personality_style_msg = ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES['UPDATE_PERSONALITY_CONTEXT'],
                payload={
                    'user_id': user_id,
                    'modifier_type': 'style',
                    'modifier_data': style_modifiers
                }
            )
            
            if self.get_actor_system():
                await self.get_actor_system().send_message("personality", personality_style_msg)
                logger.info(f"Sent style vector to PersonalityActor for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error sending UPDATE_PARTNER_MODEL: {str(e)}")