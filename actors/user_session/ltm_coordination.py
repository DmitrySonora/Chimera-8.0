"""
LTMCoordinationMixin - координация сохранения в долговременную память
"""
from typing import Dict, Any, Tuple
from datetime import datetime
import uuid
from config.settings_ltm import (
    LTM_EMOTIONAL_THRESHOLD,
    LTM_EMOTIONAL_PEAK_THRESHOLD,
    LTM_DEFAULT_SEARCH_TYPE,
    LTM_EMOTIONAL_SEARCH_THRESHOLD,
    LTM_TRIGGER_PRIORITIES,
    LTM_CATEGORY_TO_SEARCH_TYPE
)
from config.vocabulary_ltm_semantic import LTM_TRIGGER_KEYWORDS
from actors.messages import ActorMessage, MESSAGE_TYPES
from models.ltm_models import MemoryType, TriggerReason


class LTMTriggerEvaluator:
    """Оценка необходимости LTM по психологическим триггерам"""
    
    def __init__(self):
        """Инициализация с импортом словарей из config.prompts"""
        self.trigger_keywords = LTM_TRIGGER_KEYWORDS
        self.trigger_priorities = LTM_TRIGGER_PRIORITIES
        self.category_to_search_type = LTM_CATEGORY_TO_SEARCH_TYPE
        
        # Порядок разрешения конфликтов при одинаковых приоритетах
        self.conflict_resolution = {
            2: ['unfinished_business', 'memory_recall'],
            3: ['uncertainty_doubt', 'emotional_resonance', 'temporal_acute'],
            4: ['existential_inquiry', 'pattern_recognition', 'metacognitive'],
            5: ['temporal_distant', 'contextual_amplifiers']
        }
    
    def evaluate(self, text: str, emotions: Dict[str, float] = None) -> Tuple[bool, str, str]:
        """
        Оценивает необходимость запроса LTM по тексту и эмоциям
        
        Args:
            text: Текст сообщения пользователя
            emotions: Словарь эмоций {emotion_name: score} или None
        
        Returns:
            (need_ltm, search_type, trigger_category)
            - need_ltm: True если нужен поиск в LTM
            - search_type: Тип поиска из LTM_CATEGORY_TO_SEARCH_TYPE
            - trigger_category: Сработавшая категория триггера
        """
        if not text:
            return False, '', ''
        
        text_lower = text.lower()
        triggered_categories = []
        
        # Проверяем все категории текстовых триггеров
        for category, keywords in self.trigger_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                priority = self.trigger_priorities.get(category, 999)
                triggered_categories.append((priority, category))
        
        # Проверяем эмоциональный триггер
        if emotions:
            meaningful_emotions = {k: v for k, v in emotions.items() if k != 'neutral'}
            if meaningful_emotions:
                max_emotion = max(meaningful_emotions.values())
                max_emotion_name = max(meaningful_emotions, key=meaningful_emotions.get)
                
                # Динамические приоритеты - "камень в озеро алгоритмов"
                if max_emotion > 0.85:
                    # Экстремальная эмоция - высший приоритет
                    triggered_categories.append((0, 'emotional_trigger'))
                    priority_level = "extreme"
                elif max_emotion > 0.75:
                    # Сильная эмоция - равный приоритет с self_related
                    triggered_categories.append((1, 'emotional_trigger'))
                    priority_level = "strong"
                elif max_emotion > LTM_EMOTIONAL_SEARCH_THRESHOLD:  # 0.7
                    # Заметная эмоция - обычный приоритет
                    triggered_categories.append((3, 'emotional_trigger'))
                    priority_level = "notable"
                else:
                    priority_level = None
                
                # Логируем если триггер сработал
                if priority_level:
                    import logging
                    logger = logging.getLogger("actor.user_session")
                    logger.debug(
                        f"Emotional trigger ({priority_level}): {max_emotion_name}={max_emotion:.2f}"
                    )
        
        # Если ничего не сработало
        if not triggered_categories:
            return False, '', ''
        
        # Сортируем по приоритету (меньше = выше приоритет)
        triggered_categories.sort(key=lambda x: x[0])
        
        # Берем все категории с минимальным приоритетом
        min_priority = triggered_categories[0][0]
        top_categories = [cat for pri, cat in triggered_categories if pri == min_priority]
        
        # Разрешаем конфликты если несколько категорий с одинаковым приоритетом
        if len(top_categories) > 1 and min_priority in self.conflict_resolution:
            resolution_order = self.conflict_resolution[min_priority]
            for category in resolution_order:
                if category in top_categories:
                    selected_category = category
                    break
            else:
                # Если ни одна из предпочтительных не найдена, берем первую
                selected_category = top_categories[0]
        else:
            selected_category = top_categories[0]
        
        # Сохраняем реальный приоритет для правильного логирования
        actual_priority = min_priority
        
        # Определяем тип поиска
        if selected_category == 'emotional_trigger':
            search_type = 'vector'  # Эмоциональные триггеры всегда используют векторный поиск
        else:
            search_type = self.category_to_search_type.get(selected_category, LTM_DEFAULT_SEARCH_TYPE)
        
        # Возвращаем также реальный приоритет для логирования
        return True, search_type, selected_category, actual_priority


class LTMCoordinationMixin:
    """Миксин для координации сохранения в LTM"""
    
    def _should_save_to_ltm(self, emotions: Dict[str, float]) -> bool:
        """
        Простая проверка: максимальная эмоция > порога
        Исключаем neutral из проверки
        
        Args:
            emotions: Словарь эмоций {emotion_name: score}
            
        Returns:
            True если нужно сохранить в LTM
        """
        if not emotions:
            return False
        
        # Фильтруем технические эмоции
        meaningful_emotions = {k: v for k, v in emotions.items() if k != 'neutral'}
        
        if not meaningful_emotions:
            return False
            
        max_emotion_value = max(meaningful_emotions.values())
        return max_emotion_value > LTM_EMOTIONAL_THRESHOLD
    
    def _prepare_ltm_evaluation(
        self, 
        session: Any,
        user_text: str,
        bot_response: str,
        emotions_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Подготовить данные для оценки LTM
        
        Args:
            session: Сессия пользователя
            user_text: Полный текст пользователя
            bot_response: Ответ бота
            emotions_data: Данные от PerceptionActor
            
        Returns:
            Payload для EVALUATE_FOR_LTM сообщения
        """
        # Извлекаем эмоциональные данные
        emotions = emotions_data.get('emotions', {})
        dominant_emotions = emotions_data.get('dominant_emotions', [])
        max_emotion_value = max(emotions.values()) if emotions else 0.0
        
        # Определяем тип памяти
        memory_type = MemoryType.SELF_RELATED if 'химера' in user_text.lower() else MemoryType.USER_RELATED
        
        # Определяем причину сохранения
        trigger_reason = TriggerReason.EMOTIONAL_PEAK if max_emotion_value > LTM_EMOTIONAL_PEAK_THRESHOLD else TriggerReason.EMOTIONAL_SHIFT
        
        # Создаем сообщения для conversation_fragment
        user_message = {
            'role': 'user',
            'content': user_text,
            'timestamp': datetime.now(),
            'message_id': str(uuid.uuid4())
        }
        
        bot_message = {
            'role': 'bot',
            'content': bot_response,
            'timestamp': datetime.now(),
            'message_id': str(uuid.uuid4()),
            'mode': session.last_bot_mode,
            'confidence': session.last_bot_confidence
        }
        
        return {
            'user_id': session.user_id,
            'user_text': user_text,
            'bot_response': bot_response,
            'emotions': emotions,
            'dominant_emotions': dominant_emotions,
            'max_emotion_value': max_emotion_value,
            'mode': session.current_mode,
            'timestamp': datetime.now().isoformat(),
            'memory_type': memory_type.value,
            'trigger_reason': trigger_reason.value,
            'messages': [user_message, bot_message],
            'username': session.username
        }
    
    async def _request_ltm_evaluation(self, payload: Dict[str, Any]) -> None:
        """
        Отправить запрос на оценку в LTMActor
        
        Args:
            payload: Данные для оценки
        """
        if not self.get_actor_system():
            self.logger.warning("No actor system available for LTM evaluation")
            return
            
        evaluate_msg = ActorMessage.create(
            sender_id=self.actor_id,
            message_type=MESSAGE_TYPES['EVALUATE_FOR_LTM'],
            payload=payload
        )
        
        # Fire-and-forget - не ждем ответа
        await self.get_actor_system().send_message("ltm", evaluate_msg)
        
        self.logger.info(
            f"Sent EVALUATE_FOR_LTM for user {payload['user_id']} "
            f"(emotion: {payload['max_emotion_value']:.2f})"
        )
    
    def _should_request_ltm(self, text: str, session: Any = None) -> tuple[bool, str]:
        """
        Определить необходимость запроса LTM по тексту сообщения и эмоциям
        
        Args:
            text: Текст сообщения пользователя
            session: Сессия пользователя для доступа к эмоциям (опционально)
            
        Returns:
            (need_ltm, search_type) - нужна ли LTM и тип поиска
        """
        # Извлекаем эмоции из сессии если доступны
        emotions = None
        if session and hasattr(session, 'last_emotion_vector'):
            emotions = session.last_emotion_vector
            # Логируем если используем эмоции из сессии
            if emotions:
                meaningful = {k: v for k, v in emotions.items() if k != 'neutral'}
                if meaningful:
                    max_emotion = max(meaningful.values())
                    if max_emotion > 0.5:  # Логируем только значимые эмоции
                        self.logger.debug(
                            f"Using session emotions for LTM trigger evaluation: "
                            f"max={max_emotion:.2f}"
                        )
        
        # Используем evaluator для оценки
        evaluator = LTMTriggerEvaluator()
        trigger_info = evaluator.evaluate(text, emotions)
        need_ltm, search_type, trigger_category = trigger_info[:3]
        
        # Логируем результат если триггер сработал
        if need_ltm:
            user_id = session.user_id if session else 'unknown'
            # Используем реальный приоритет из evaluator
            actual_priority = trigger_info[3] if len(trigger_info) > 3 else LTM_TRIGGER_PRIORITIES.get(trigger_category, 999)
            
            self.logger.info(
                f"LTM trigger activated: {trigger_category} (priority: {actual_priority}) for user {user_id}"
            )
        
        return need_ltm, search_type