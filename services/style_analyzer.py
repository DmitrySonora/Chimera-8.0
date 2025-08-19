"""
Сервис анализа стиля общения пользователя.
Анализирует сообщения из STM buffer и возвращает 4D вектор стиля.
"""
import re
import time
from typing import Dict, Any, List
import numpy as np
import json

from config.logging import get_logger
from utils.monitoring import measure_latency
from utils.text_matching import normalize_and_match
from config.settings_emo import EMOTION_LABELS
from config.vocabulary_style_analysis import (
    STYLE_ANALYSIS_MARKERS,
    # Основные параметры
    STYLE_ANALYSIS_MIN_MESSAGES,
    STYLE_ANALYSIS_DEFAULT_LIMIT,
    STYLE_ANALYSIS_CONFIDENCE_THRESHOLD,
    STYLE_ANALYSIS_DECAY_FACTOR,
    STYLE_ANALYSIS_TIMEOUT,
    # Параметры игривости
    PLAYFULNESS_EMOJI_WEIGHT,
    PLAYFULNESS_EMOJI_MAX,
    PLAYFULNESS_EXCLAMATION_WEIGHT,
    PLAYFULNESS_INFORMAL_WEIGHT,
    PLAYFULNESS_INFORMAL_MAX,
    PLAYFULNESS_LAUGHTER_WEIGHT,
    # Параметры серьезности
    SERIOUSNESS_SENTENCE_THRESHOLD_1,
    SERIOUSNESS_SENTENCE_THRESHOLD_2,
    SERIOUSNESS_SENTENCE_WEIGHT_1,
    SERIOUSNESS_SENTENCE_WEIGHT_2,
    SERIOUSNESS_FORMAL_WEIGHT,
    SERIOUSNESS_QUESTION_WEIGHT,
    SERIOUSNESS_NO_EMOJI_WEIGHT,
    # Параметры эмоциональности
    EMOTIONALITY_STD_MULTIPLIER,
    EMOTIONALITY_MAX_MULTIPLIER,
    EMOTIONALITY_MAX_FROM_METADATA,
    EMOTIONALITY_INTENSIFIER_WEIGHT,
    EMOTIONALITY_INTENSIFIER_MAX,
    EMOTIONALITY_PUNCTUATION_WEIGHT,
    # Параметры креативности
    CREATIVITY_COMPARISON_WEIGHT,
    CREATIVITY_COMPARISON_MAX,
    CREATIVITY_PUNCTUATION_WEIGHT,
    CREATIVITY_UNIQUENESS_WEIGHT,
    CREATIVITY_LENGTH_THRESHOLD,
    CREATIVITY_LENGTH_WEIGHT,
    CREATIVITY_MIN_WORDS,
    CREATIVITY_GLOBAL_BONUS,
    # Параметры confidence
    CONFIDENCE_SHORT_MESSAGE_THRESHOLD,
    CONFIDENCE_SHORT_RATIO_THRESHOLD,
    CONFIDENCE_SHORT_PENALTY,
    CONFIDENCE_DIVERSITY_SCALE,
    CONFIDENCE_MAX_VALUE,
    CONFIDENCE_BASE_MAX,
    CONFIDENCE_DEFAULT_UNIQUENESS,
    CONFIDENCE_DIVERSITY_MIN,
    CONFIDENCE_DIVERSITY_MAX,
    CONFIDENCE_NEUTRAL_VALUE,
    # Дефолтные значения
    STYLE_NEUTRAL_VALUE,
    STYLE_COMPONENT_MIN,
    STYLE_COMPONENT_MAX,
    # Производительность
    STYLE_ANALYSIS_SLOW_THRESHOLD,
    # Округление
    STYLE_VECTOR_PRECISION
)


class StyleAnalyzer:
    """
    Анализатор стиля общения пользователя.
    Возвращает 4D вектор: [игривость, серьезность, эмоциональность, креативность]
    """
    
    def __init__(self, db_connection):
        """
        Args:
            db_connection: Подключение к БД для получения сообщений из STM
        """
        self.db = db_connection
        self.logger = get_logger("style_analyzer")
        # Компилируем regex паттерны один раз
        self._emoji_pattern = re.compile(STYLE_ANALYSIS_MARKERS["playfulness"]["emoji_patterns"])
        
    @measure_latency
    async def analyze_user_style(
        self, 
        user_id: str, 
        limit: int = None
    ) -> Dict[str, Any]:
        """
        Анализирует стиль общения пользователя.
        
        Args:
            user_id: ID пользователя
            limit: Количество последних сообщений для анализа
            
        Returns:
            {
                "style_vector": {
                    "playfulness": 0.0-1.0,
                    "seriousness": 0.0-1.0,
                    "emotionality": 0.0-1.0,
                    "creativity": 0.0-1.0
                },
                "confidence": 0.0-1.0,
                "messages_analyzed": int,
                "metadata": {
                    "analysis_time_ms": int,
                    "has_sufficient_data": bool
                }
            }
        """
        start_time = time.time()
        
        if limit is None:
            limit = STYLE_ANALYSIS_DEFAULT_LIMIT
            
        self.logger.info(f"Starting style analysis for user {user_id}, limit={limit}")
        
        # Получаем сообщения из STM
        messages = await self._get_user_messages(user_id, limit)
        
        # Проверяем достаточно ли данных
        if len(messages) < STYLE_ANALYSIS_MIN_MESSAGES:
            self.logger.warning(
                f"Insufficient messages for user {user_id}: "
                f"{len(messages)} < {STYLE_ANALYSIS_MIN_MESSAGES}"
            )
            return self._get_neutral_result(len(messages), start_time)
        
        # Анализируем компоненты стиля
        try:
            playfulness = self._analyze_playfulness(messages)
            seriousness = self._analyze_seriousness(messages)
            emotionality = self._analyze_emotionality(messages)
            creativity = self._analyze_creativity(messages)
            
            # Вычисляем confidence
            confidence = self._calculate_confidence(messages)
            
            # Формируем результат
            analysis_time_ms = int((time.time() - start_time) * 1000)
            
            result = {
                "style_vector": {
                    "playfulness": round(playfulness, STYLE_VECTOR_PRECISION),
                    "seriousness": round(seriousness, STYLE_VECTOR_PRECISION),
                    "emotionality": round(emotionality, STYLE_VECTOR_PRECISION),
                    "creativity": round(creativity, STYLE_VECTOR_PRECISION)
                },
                "confidence": round(confidence, STYLE_VECTOR_PRECISION),
                "messages_analyzed": len(messages),
                "metadata": {
                    "analysis_time_ms": analysis_time_ms,
                    "has_sufficient_data": True
                }
            }
            
            self.logger.info(
                f"Style analysis completed for user {user_id}: "
                f"vector={result['style_vector']}, confidence={confidence}, "
                f"time={analysis_time_ms}ms"
            )
            
            if analysis_time_ms > STYLE_ANALYSIS_SLOW_THRESHOLD:
                self.logger.warning(f"Slow style analysis: {analysis_time_ms}ms")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error analyzing style for user {user_id}: {e}")
            return self._get_neutral_result(len(messages), start_time)
    
    async def _get_user_messages(self, user_id: str, limit: int) -> List[Dict[str, Any]]:
        """Получает последние сообщения пользователя из STM buffer."""
        
        query = """
            SELECT content, metadata, timestamp
            FROM stm_buffer
            WHERE user_id = $1 AND message_type = 'user'
            ORDER BY sequence_number DESC
            LIMIT $2
        """
        
        try:
            rows = await self.db.fetch(
                query, user_id, limit,
                timeout=STYLE_ANALYSIS_TIMEOUT
            )
            
            # Конвертируем в список словарей с нужными полями
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
            
            self.logger.debug(f"Retrieved {len(messages)} messages for user {user_id}")
            return messages
            
        except Exception as e:
            self.logger.error(f"Error fetching messages from STM: {e}")
            return []
    
    def _analyze_playfulness(self, messages: List[Dict[str, Any]]) -> float:
        """Анализирует игривость: эмодзи, восклицания, неформальная лексика."""
        
        scores = []
        informal_words = STYLE_ANALYSIS_MARKERS["playfulness"]["informal_words"]
        laughter = STYLE_ANALYSIS_MARKERS["playfulness"]["laughter"]
        exclamations = STYLE_ANALYSIS_MARKERS["playfulness"]["exclamations"]
        
        for i, msg in enumerate(messages):
            content = msg['content'].lower()
            score = STYLE_COMPONENT_MIN
            
            # Эмодзи
            emoji_count = len(self._emoji_pattern.findall(msg['content']))  # Используем оригинальный текст для эмодзи
            if emoji_count > 0:
                score += min(emoji_count * PLAYFULNESS_EMOJI_WEIGHT, PLAYFULNESS_EMOJI_MAX)
            
            # Восклицания
            for excl in exclamations:
                if excl in content:
                    score += PLAYFULNESS_EXCLAMATION_WEIGHT
                    
            # Неформальные слова
            found_informal = normalize_and_match(content, informal_words)
            informal_count = len(found_informal)
            if informal_count > 0:
                score += min(informal_count * PLAYFULNESS_INFORMAL_WEIGHT, PLAYFULNESS_INFORMAL_MAX)
                
            # Уменьшительно-ласкательные
            diminutives = STYLE_ANALYSIS_MARKERS["playfulness"].get("diminutives", [])
            if diminutives:
                found_diminutives = normalize_and_match(content, diminutives)
                diminutive_count = len(found_diminutives)
                if diminutive_count > 0:
                    score += min(diminutive_count * PLAYFULNESS_INFORMAL_WEIGHT, PLAYFULNESS_INFORMAL_MAX)
            
            # Игровые междометия
            playful_interjections = STYLE_ANALYSIS_MARKERS["playfulness"].get("playful_interjections", [])
            for interjection in playful_interjections:
                if interjection.lower() in content:
                    score += PLAYFULNESS_EXCLAMATION_WEIGHT
                    break  # Считаем только одно совпадение
                
            # Смех
            found_laughter = normalize_and_match(content, laughter)
            for _ in found_laughter:
                score += PLAYFULNESS_LAUGHTER_WEIGHT
                    
            # Ограничиваем максимум
            score = min(score, STYLE_COMPONENT_MAX)
            
            # Применяем временной decay
            weight = 1.0 - (i / len(messages)) * STYLE_ANALYSIS_DECAY_FACTOR
            scores.append(score * weight)
        
        # Взвешенное среднее
        if scores:
            total_weight = sum(1.0 - (i / len(messages)) * STYLE_ANALYSIS_DECAY_FACTOR 
                             for i in range(len(messages)))
            return sum(scores) / total_weight
        return STYLE_NEUTRAL_VALUE
    
    def _analyze_seriousness(self, messages: List[Dict[str, Any]]) -> float:
        """Анализирует серьезность: длина предложений, формальная лексика, вопросы."""
        
        scores = []
        formal_markers = STYLE_ANALYSIS_MARKERS["seriousness"]["formal_markers"]
        question_words = STYLE_ANALYSIS_MARKERS["seriousness"]["question_words"]
        
        for i, msg in enumerate(messages):
            content = msg['content']
            content_lower = content.lower()
            score = STYLE_COMPONENT_MIN
            
            # Длина предложений
            sentences = re.split(r'[.!?]+', content)
            sentence_lengths = [len(s.split()) for s in sentences if s.strip()]
            if sentence_lengths:
                avg_sentence_length = np.mean(sentence_lengths)
                if avg_sentence_length > SERIOUSNESS_SENTENCE_THRESHOLD_1:
                    score += SERIOUSNESS_SENTENCE_WEIGHT_1
                if avg_sentence_length > SERIOUSNESS_SENTENCE_THRESHOLD_2:
                    score += SERIOUSNESS_SENTENCE_WEIGHT_2
                
            # Формальные маркеры (максимум 3 совпадения)
            formal_count = 0
            for marker in formal_markers:
                if marker in content_lower:
                    formal_count += 1
                    if formal_count <= 3:  # Ограничиваем
                        score += SERIOUSNESS_FORMAL_WEIGHT
                    
            # Аналитические маркеры (максимум 2 совпадения)
            analytical_markers = STYLE_ANALYSIS_MARKERS["seriousness"].get("analytical_markers", [])
            if analytical_markers:
                found_analytical = normalize_and_match(content_lower, analytical_markers)
                analytical_count = 0
                for _ in found_analytical:
                    analytical_count += 1
                    if analytical_count <= 2:  # Ограничиваем
                        score += SERIOUSNESS_FORMAL_WEIGHT
                    
            # Научная/деловая лексика (максимум 2 совпадения)
            scientific_business = STYLE_ANALYSIS_MARKERS["seriousness"].get("scientific_business", [])
            if scientific_business:
                found_scientific = normalize_and_match(content_lower, scientific_business)
                scientific_count = 0
                for _ in found_scientific:
                    scientific_count += 1
                    if scientific_count <= 2:  # Ограничиваем
                        score += SERIOUSNESS_FORMAL_WEIGHT
                    
            # Серьезные вопросы
            for q_word in question_words:
                if q_word in content_lower:
                    score += SERIOUSNESS_QUESTION_WEIGHT
                    
            # Отсутствие эмодзи и восклицаний
            has_multiple_exclamations = bool(re.search(r'[!]{2,}', content))
            has_emoji = bool(self._emoji_pattern.search(content))
            if not has_multiple_exclamations and not has_emoji:
                score += SERIOUSNESS_NO_EMOJI_WEIGHT
                
            # Ограничиваем максимум
            score = min(score, STYLE_COMPONENT_MAX)
            
            # Применяем временной decay
            weight = 1.0 - (i / len(messages)) * STYLE_ANALYSIS_DECAY_FACTOR
            scores.append(score * weight)
        
        # Взвешенное среднее
        if scores:
            total_weight = sum(1.0 - (i / len(messages)) * STYLE_ANALYSIS_DECAY_FACTOR 
                             for i in range(len(messages)))
            return sum(scores) / total_weight
        return STYLE_NEUTRAL_VALUE
    
    def _analyze_emotionality(self, messages: List[Dict[str, Any]]) -> float:
        """Анализирует эмоциональность: амплитуда эмоций, интенсификаторы."""
        
        scores = []
        intensifiers = STYLE_ANALYSIS_MARKERS["emotionality"]["intensifiers"]
        emotional_punct = STYLE_ANALYSIS_MARKERS["emotionality"]["emotional_punctuation"]
        
        for i, msg in enumerate(messages):
            content = msg['content'].lower()
            metadata = msg['metadata']
            score = STYLE_COMPONENT_MIN
            
            # Эмоции из metadata (если есть)
            if metadata and 'emotions' in metadata and metadata['emotions']:
                emotions = metadata['emotions']
                # Считаем амплитуду - разброс значений
                emotion_values = [emotions.get(e, 0) for e in EMOTION_LABELS if e in emotions]
                if emotion_values:
                    # Стандартное отклонение как мера разброса
                    emotion_std = np.std(emotion_values)
                    # И максимальная эмоция
                    max_emotion = max(emotion_values)
                    score += min(
                        emotion_std * EMOTIONALITY_STD_MULTIPLIER + 
                        max_emotion * EMOTIONALITY_MAX_MULTIPLIER, 
                        EMOTIONALITY_MAX_FROM_METADATA
                    )
            
            # Интенсификаторы
            found_intensifiers = normalize_and_match(content, intensifiers)
            intensifier_count = len(found_intensifiers)
            if intensifier_count > 0:
                score += min(
                    intensifier_count * EMOTIONALITY_INTENSIFIER_WEIGHT, 
                    EMOTIONALITY_INTENSIFIER_MAX
                )
                
            # Эмоционально окрашенные слова
            emotional_words = STYLE_ANALYSIS_MARKERS["emotionality"].get("emotional_words", [])
            if emotional_words:
                found_emotional = normalize_and_match(content, emotional_words)
                emotional_count = len(found_emotional)
                if emotional_count > 0:
                    score += min(
                        emotional_count * EMOTIONALITY_INTENSIFIER_WEIGHT,
                        EMOTIONALITY_INTENSIFIER_MAX
                    )
                    
            # Эмоциональные междометия
            emotional_interjections = STYLE_ANALYSIS_MARKERS["emotionality"].get("emotional_interjections", [])
            for interjection in emotional_interjections:
                if interjection.lower() in content:
                    score += EMOTIONALITY_PUNCTUATION_WEIGHT
                    break  # Считаем только одно совпадение
                
            # Эмоциональная пунктуация
            for punct in emotional_punct:
                if punct in content:
                    score += EMOTIONALITY_PUNCTUATION_WEIGHT
                    
            # Ограничиваем максимум
            score = min(score, STYLE_COMPONENT_MAX)
            
            # Применяем временной decay
            weight = 1.0 - (i / len(messages)) * STYLE_ANALYSIS_DECAY_FACTOR
            scores.append(score * weight)
        
        # Взвешенное среднее
        if scores:
            total_weight = sum(1.0 - (i / len(messages)) * STYLE_ANALYSIS_DECAY_FACTOR 
                             for i in range(len(messages)))
            return sum(scores) / total_weight
        return STYLE_NEUTRAL_VALUE
    
    def _analyze_creativity(self, messages: List[Dict[str, Any]]) -> float:
        """Анализирует креативность: творческая лексика и уникальность слов."""
        
        scores = []
        creative_vocabulary = STYLE_ANALYSIS_MARKERS["creativity"]["creative_vocabulary"]
        
        # Собираем все слова для анализа уникальности
        all_words = []
        
        for i, msg in enumerate(messages):
            content = msg['content']
            content_lower = content.lower()
            score = STYLE_COMPONENT_MIN
            
            # Творческая лексика
            found_creative = normalize_and_match(content_lower, creative_vocabulary)
            creative_count = len(found_creative)
            if creative_count > 0:
                score += min(creative_count * CREATIVITY_COMPARISON_WEIGHT, CREATIVITY_COMPARISON_MAX)
                    
            # Необычная пунктуация (креативный элемент)
            creative_punctuation_patterns = ['?!', '!?', '...', '!!!', '???', '?!?', '!?!']
            for pattern in creative_punctuation_patterns:
                if pattern in content:
                    score += CREATIVITY_PUNCTUATION_WEIGHT
                    break  # Считаем только одно совпадение
                    
            # Уникальность слов в сообщении
            words = re.findall(r'\b\w+\b', content_lower)
            all_words.extend(words)
            if len(words) > CREATIVITY_MIN_WORDS:
                unique_ratio = len(set(words)) / len(words)
                score += unique_ratio * CREATIVITY_UNIQUENESS_WEIGHT
                
            # Длина и сложность предложений (креативные тексты часто длиннее)
            if len(content) > CREATIVITY_LENGTH_THRESHOLD:
                score += CREATIVITY_LENGTH_WEIGHT
                
            # Ограничиваем максимум
            score = min(score, STYLE_COMPONENT_MAX)
            
            # Применяем временной decay
            weight = 1.0 - (i / len(messages)) * STYLE_ANALYSIS_DECAY_FACTOR
            scores.append(score * weight)
        
        # Дополнительный бонус за общую уникальность слов
        if all_words and len(all_words) > 15:   # Пока оставим хардкодом: Минимум ~3-4 предложения для статистической значимости
            global_unique_ratio = len(set(all_words)) / len(all_words)
            creativity_bonus = global_unique_ratio * CREATIVITY_GLOBAL_BONUS
            scores = [min(s + creativity_bonus, STYLE_COMPONENT_MAX) for s in scores]
        
        # Взвешенное среднее
        if scores:
            total_weight = sum(1.0 - (i / len(messages)) * STYLE_ANALYSIS_DECAY_FACTOR 
                             for i in range(len(messages)))
            return min(sum(scores) / total_weight, STYLE_COMPONENT_MAX)
        return STYLE_NEUTRAL_VALUE
    
    def _calculate_confidence(self, messages: List[Dict[str, Any]]) -> float:
        """Вычисляет уверенность в анализе на основе количества и разнообразия сообщений."""
        
        # Базовая уверенность от количества сообщений
        base_confidence = min(len(messages) / STYLE_ANALYSIS_CONFIDENCE_THRESHOLD, CONFIDENCE_BASE_MAX)
        
        # Diversity factor
        unique_words = set()
        total_words = 0
        short_messages = 0
        
        for msg in messages:
            words = re.findall(r'\b\w+\b', msg['content'].lower())
            unique_words.update(words)
            total_words += len(words)
            
            # Считаем короткие сообщения
            if len(words) < CONFIDENCE_SHORT_MESSAGE_THRESHOLD:
                short_messages += 1
        
        # Отношение уникальных слов к общему количеству
        if total_words > 0:
            uniqueness_ratio = len(unique_words) / total_words
        else:
            uniqueness_ratio = CONFIDENCE_DEFAULT_UNIQUENESS
            
        # Diversity factor: низкая уникальность = 0.8, высокая = 1.2
        diversity_factor = CONFIDENCE_DIVERSITY_MIN + (uniqueness_ratio * CONFIDENCE_DIVERSITY_SCALE)
        
        # Снижаем diversity если много коротких сообщений
        if len(messages) > 0:
            short_ratio = short_messages / len(messages)
            if short_ratio > CONFIDENCE_SHORT_RATIO_THRESHOLD:
                diversity_factor *= CONFIDENCE_SHORT_PENALTY
                
        # Ограничиваем диапазон
        diversity_factor = min(max(diversity_factor, CONFIDENCE_DIVERSITY_MIN), CONFIDENCE_DIVERSITY_MAX)
        
        # Финальная уверенность
        confidence = min(base_confidence * diversity_factor, CONFIDENCE_MAX_VALUE)
        
        self.logger.debug(
            f"Confidence calculation: base={base_confidence:.3f}, "
            f"diversity={diversity_factor:.3f}, final={confidence:.3f}"
        )
        
        return confidence
    
    def _get_neutral_result(self, messages_count: int, start_time: float) -> Dict[str, Any]:
        """Возвращает нейтральный результат при недостатке данных."""
        
        analysis_time_ms = int((time.time() - start_time) * 1000)
        
        return {
            "style_vector": {
                "playfulness": STYLE_NEUTRAL_VALUE,
                "seriousness": STYLE_NEUTRAL_VALUE,
                "emotionality": STYLE_NEUTRAL_VALUE,
                "creativity": STYLE_NEUTRAL_VALUE
            },
            "confidence": CONFIDENCE_NEUTRAL_VALUE,
            "messages_analyzed": messages_count,
            "metadata": {
                "analysis_time_ms": analysis_time_ms,
                "has_sufficient_data": False
            }
        }