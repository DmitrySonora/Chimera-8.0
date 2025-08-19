"""
Сервис анализа проявленных черт личности Химеры в её ответах.
"""
import re
import json
import time
from typing import List, Dict, Any, Optional
from uuid import UUID, uuid4
from datetime import datetime

from config.logging import get_logger
from utils.monitoring import measure_latency
from utils.text_matching import normalize_and_match
from models.personality_models import TraitManifestation
from config.vocabulary_chimera_persona import (
    PERSONALITY_TRAITS,
    TRAIT_LINGUISTIC_MARKERS,
    TRAIT_MODE_AFFINITY,
    TRAIT_EMOTION_ASSOCIATIONS,
    TRAIT_BASE_STRENGTH,
    TRAIT_LOG_DIVISOR,
    TRAIT_FREQUENCY_DIVISOR,
    TRAIT_FREQUENCY_MAX_BONUS,
    TRAIT_BASE_STRENGTH_MAX,
    TRAIT_EMOTION_MULTIPLIER,
    TRAIT_DEFAULT_NEUTRAL_EMOTION,
    TRAIT_CH_DETECTION_THRESHOLD
)
from config.vocabulary_style_analysis import (
    STYLE_ANALYSIS_DEFAULT_LIMIT,
    STYLE_ANALYSIS_TIMEOUT
)


class TraitDetector:
    """
    Детектор черт личности Химеры на основе анализа её ответов.
    Анализирует лингвистические маркеры, учитывает режим общения и эмоциональный контекст.
    """
    
    def __init__(self, db_connection):
        """
        Args:
            db_connection: Подключение к БД для получения сообщений из STM
        """
        self.db = db_connection
        self.logger = get_logger("trait_detector")
        
    @measure_latency
    async def detect_traits(
        self, 
        user_id: str, 
        limit: Optional[int] = None
    ) -> List[TraitManifestation]:
        """
        Анализирует проявленные черты личности в ответах Химеры.
        
        Args:
            user_id: ID пользователя
            limit: Количество последних сообщений для анализа
            
        Returns:
            Список обнаруженных проявлений черт (TraitManifestation)
        """
        start_time = time.time()
        
        if limit is None:
            limit = STYLE_ANALYSIS_DEFAULT_LIMIT
            
        self.logger.info(f"Starting trait detection for user {user_id}, limit={limit}")
        
        # Получаем сообщения бота из STM
        messages = await self._get_bot_messages(user_id, limit)
        
        if not messages:
            self.logger.warning(f"No bot messages found for user {user_id}")
            return []
        
        # Генерируем batch_id для группировки
        analysis_batch_id = uuid4()
        
        # Кэш для нормализованных текстов
        normalized_cache = {}
        
        # Результаты
        manifestations = []
        
        try:
            # Анализируем каждое сообщение
            for msg in messages:
                # Анализируем все черты кроме empathy
                for trait_name, trait_info in PERSONALITY_TRAITS.items():
                    if trait_name == 'empathy':
                        continue
                        # Empathy не детектируется лингвистически - это сознательное решение
                        # т.к. эмпатия проявляется через соответствие эмоций, а не через слова
                    
                    # Детектируем черту в сообщении
                    manifestation = self._detect_trait_in_message(
                        trait_name=trait_name,
                        message=msg,
                        user_id=user_id,
                        analysis_batch_id=analysis_batch_id,
                        normalized_cache=normalized_cache
                    )
                    
                    if manifestation:
                        manifestations.append(manifestation)
            
            # Время анализа
            analysis_time_ms = int((time.time() - start_time) * 1000)
            
            self.logger.info(
                f"Trait detection completed for user {user_id}: "
                f"found {len(manifestations)} manifestations in {len(messages)} messages, "
                f"time={analysis_time_ms}ms"
            )
            
            if analysis_time_ms > 100:
                self.logger.warning(f"Slow trait detection: {analysis_time_ms}ms")
            
            return manifestations
            
        except Exception as e:
            self.logger.error(f"Error detecting traits for user {user_id}: {e}")
            return []
    
    async def _get_bot_messages(self, user_id: str, limit: int) -> List[Dict[str, Any]]:
        """Получает последние сообщения бота из STM buffer."""
        
        query = """
            SELECT content, metadata, timestamp
            FROM stm_buffer
            WHERE user_id = $1 AND message_type = 'bot'
            ORDER BY sequence_number DESC
            LIMIT $2
        """
        
        try:
            rows = await self.db.fetch(
                query, user_id, limit,
                timeout=STYLE_ANALYSIS_TIMEOUT
            )
            
            # Конвертируем в список словарей
            messages = []
            for row in rows:
                metadata = row['metadata']
                # Десериализуем JSON если это строка
                if metadata and isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except json.JSONDecodeError:
                        self.logger.warning(f"Failed to parse metadata JSON: {metadata}")
                        metadata = {}
                        
                messages.append({
                    'content': row['content'],
                    'metadata': metadata or {},
                    'timestamp': row['timestamp']
                })
            
            self.logger.debug(f"Retrieved {len(messages)} bot messages for user {user_id}")
            return messages
            
        except Exception as e:
            self.logger.error(f"Error fetching bot messages from STM: {e}")
            return []
    
    def _detect_trait_in_message(
        self,
        trait_name: str,
        message: Dict[str, Any],
        user_id: str,
        analysis_batch_id: UUID,
        normalized_cache: Dict[str, str]
    ) -> Optional[TraitManifestation]:
        """
        Детектирует проявление одной черты в одном сообщении.
        
        Returns:
            TraitManifestation если черта обнаружена с силой > порога, иначе None
        """
        content = message['content']
        metadata = message.get('metadata', {})
        
        # Получаем маркеры для черты
        markers = TRAIT_LINGUISTIC_MARKERS.get(trait_name, [])
        if not markers:
            return None
        
        # Нормализуем текст (с кэшированием)
        content_lower = normalized_cache.get(content)
        if content_lower is None:
            content_lower = content.lower()
            normalized_cache[content] = content_lower
        
        # Ищем маркеры через normalize_and_match
        found_markers = normalize_and_match(content, markers)
        if not found_markers:
            return None
        
        # Считаем слова в тексте (с поддержкой кириллицы)
        words = re.findall(r'\b\w+\b', content_lower, re.UNICODE)
        word_count = len(words)
        if word_count == 0:
            return None
        
        # Для русского языка маркеры встречаются реже, чем в английском
        # Используем логарифмическую шкалу для более реалистичной оценки
        # 1 маркер = 0.3, 2 маркера = 0.45, 3 маркера = 0.55, и т.д.
        import math
        base_strength = TRAIT_BASE_STRENGTH * (1 + math.log(len(found_markers)) / TRAIT_LOG_DIVISOR)
        
        # Учитываем относительную частоту: если маркеров много относительно длины текста
        frequency_bonus = min(len(found_markers) / (word_count / TRAIT_FREQUENCY_DIVISOR), TRAIT_FREQUENCY_MAX_BONUS)
        base_strength = min(base_strength + frequency_bonus, TRAIT_BASE_STRENGTH_MAX)
        
        # Учитываем режим из metadata
        mode = metadata.get('mode', 'talk')  # Меняем дефолт на 'talk'
        # Если режима нет в словаре, используем среднее значение
        trait_affinities = TRAIT_MODE_AFFINITY.get(trait_name, {})
        if mode in trait_affinities:
            mode_affinity = trait_affinities[mode]
        else:
            # Берем среднее по всем режимам для этой черты
            mode_affinity = sum(trait_affinities.values()) / len(trait_affinities) if trait_affinities else 0.5
        strength_with_mode = base_strength * mode_affinity
        
        # Учитываем эмоциональные ассоциации
        emotional_multiplier = 1.0
        emotions = metadata.get('emotions', {})
        if emotions and trait_name in TRAIT_EMOTION_ASSOCIATIONS:
            emotion_associations = TRAIT_EMOTION_ASSOCIATIONS[trait_name]
            # Находим максимальную корреляцию
            for emotion, correlation in emotion_associations.items():
                if emotion in emotions:
                    emotion_strength = emotions[emotion]
                    # Усиливаем если эмоция сильная и корреляция высокая
                    multiplier = 1.0 + (emotion_strength * correlation * TRAIT_EMOTION_MULTIPLIER)
                    emotional_multiplier = max(emotional_multiplier, multiplier)
        
        # Финальная сила с нормализацией
        final_strength = min(strength_with_mode * emotional_multiplier, 1.0)
        
        # Проверяем порог
        if final_strength < TRAIT_CH_DETECTION_THRESHOLD:
            return None
        
        # Создаем TraitManifestation
        # Если эмоций нет, добавляем нейтральную эмоцию
        if not emotions:
            emotions = {"neutral": TRAIT_DEFAULT_NEUTRAL_EMOTION}
            
        manifestation = TraitManifestation(
            manifestation_id=uuid4(),
            user_id=user_id,
            trait_name=trait_name,
            manifestation_strength=final_strength,
            mode=mode,
            emotional_context=emotions,
            message_id=None,  # У нас нет ID сообщения в STM
            detected_markers=found_markers,
            confidence=final_strength,  # confidence = manifestation_strength
            detected_at=datetime.utcnow(),
            analysis_batch_id=analysis_batch_id
        )
        
        self.logger.debug(
            f"Detected trait {trait_name} with strength {final_strength:.3f} "
            f"(base={base_strength:.3f}, mode_affinity={mode_affinity}, "
            f"emotional_multiplier={emotional_multiplier:.2f})"
        )
        
        return manifestation