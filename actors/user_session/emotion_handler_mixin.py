"""
Emotion handler mixin for UserSessionActor - Обработка эмоциональных результатов
"""
from typing import Dict, Any
from datetime import datetime
from actors.messages import ActorMessage, MESSAGE_TYPES
from actors.events import EmotionDetectedEvent
from config.settings_emo import EMOTION_EMOJI_MAP


class EmotionHandlerMixin:
    """Mixin для обработки эмоциональных результатов"""
    
    # These attributes are available from UserSessionActor
    _sessions: Dict[str, Any]
    _event_version_manager: object
    logger: object
    actor_id: str
    get_actor_system: callable
    
    async def _handle_emotion_result(self, message: ActorMessage) -> None:
        """Обработка EMOTION_RESULT от PerceptionActor"""
        user_id = message.payload.get('user_id')
        if not user_id:
            self.logger.warning("Received EMOTION_RESULT without user_id")
            return None
        
        # Извлекаем эмоции для логирования
        dominant_emotions = message.payload.get('dominant_emotions', [])
        emotion_scores = message.payload.get('emotions', {})
        
        # Находим топ-3 эмоции с их вероятностями
        if emotion_scores:
            top_emotions = sorted(emotion_scores.items(), key=lambda x: x[1], reverse=True)[:3]
            emotions_str = ", ".join([f"{emotion}: {score:.2f}" for emotion, score in top_emotions])
            
            emoji = EMOTION_EMOJI_MAP.get(dominant_emotions[0], '🎭') if dominant_emotions else '🎭'
            self.logger.info(
                # f"{emoji} Emotions for user {user_id}: [{emotions_str}] | Dominant: {dominant_emotions}"
                f"{emoji} [{emotions_str}] → {dominant_emotions}"
            )
        else:
            self.logger.info(f"Received EMOTION_RESULT for user {user_id} (no emotions detected)")
        
        # Получаем сессию
        if user_id in self._sessions:
            session = self._sessions[user_id]
            
            # Сохраняем эмоции в сессии
            session.last_emotion_vector = message.payload.get('emotions', {})
            session.last_dominant_emotions = message.payload.get('dominant_emotions', [])
            
            # Форвардинг эмоций в PersonalityActor (fire-and-forget)
            if session.last_emotion_vector and self.get_actor_system():
                # Преобразуем эмоции (0.0-1.0) в модификаторы (0.5-1.5)
                # Формула: modifier = 0.5 + emotion_value * 1.0
                emotion_modifiers = {
                    emotion: 0.5 + value
                    for emotion, value in session.last_emotion_vector.items()
                }
                
                personality_msg = ActorMessage.create(
                    sender_id=self.actor_id,
                    message_type=MESSAGE_TYPES['UPDATE_PERSONALITY_CONTEXT'],
                    payload={
                        'user_id': user_id,
                        'modifier_type': 'emotion',
                        'modifier_data': emotion_modifiers
                    }
                )
                await self.get_actor_system().send_message("personality", personality_msg)
                self.logger.debug(f"Forwarded emotions to PersonalityActor for user {user_id}")
            
            # Сохраняем user-сообщение в память с эмоциями
            if session.last_user_text and self.get_actor_system():
                store_msg = ActorMessage.create(
                    sender_id=self.actor_id,
                    message_type=MESSAGE_TYPES['STORE_MEMORY'],
                    payload={
                        'user_id': user_id,
                        'message_type': 'user',
                        'content': session.last_user_text,
                        'metadata': {
                            'username': session.username,
                            'timestamp': datetime.now().isoformat(),
                            'emotions': session.last_emotion_vector,
                            'dominant_emotions': session.last_dominant_emotions
                        }
                    }
                )
                await self.get_actor_system().send_message("memory", store_msg)
                self.logger.debug(f"Saved user message with emotions for {user_id}")
            
            # Создаем событие
            try:
                event = EmotionDetectedEvent.create(
                    user_id=user_id,
                    dominant_emotions=session.last_dominant_emotions,
                    emotion_scores=session.last_emotion_vector,
                    text_preview=message.payload.get('text', '')
                )
                
                await self._event_version_manager.append_event(event, self.get_actor_system())
                self.logger.info(f"Saved EmotionDetectedEvent for user {user_id}")
                
            except Exception as e:
                self.logger.error(f"Failed to save EmotionDetectedEvent: {str(e)}")
            
            except Exception as e:
                self.logger.error(f"Failed to save EmotionDetectedEvent: {str(e)}")
        else:
            self.logger.warning(f"No session found for user {user_id}")