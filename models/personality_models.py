"""
Pydantic модели для анализа личности и стиля общения (Фаза 7.1)
"""
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Dict, Optional, Literal
from datetime import datetime
from uuid import UUID

from config.vocabulary_style_analysis import (
    STYLE_VECTOR_MIN,
    STYLE_VECTOR_MAX,
    PERSONALITY_TRAITS_MIN_STRENGTH,
    PERSONALITY_TRAITS_MAX_STRENGTH,
    PARTNER_PERSONA_CHANGE_THRESHOLD
)
from config.settings_emo import EMOTION_LABELS


class StyleVector(BaseModel):
    """
    4D вектор стиля общения пользователя.
    Каждый компонент отражает определенный аспект стиля.
    """
    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )
    
    playfulness: float = Field(
        default=0.5,
        ge=STYLE_VECTOR_MIN,
        le=STYLE_VECTOR_MAX,
        description="Игривость: эмодзи, восклицания, неформальная лексика"
    )
    seriousness: float = Field(
        default=0.5,
        ge=STYLE_VECTOR_MIN,
        le=STYLE_VECTOR_MAX,
        description="Серьезность: длинные предложения, формальность, вопросы о сути"
    )
    emotionality: float = Field(
        default=0.5,
        ge=STYLE_VECTOR_MIN,
        le=STYLE_VECTOR_MAX,
        description="Эмоциональность: амплитуда эмоций из metadata"
    )
    creativity: float = Field(
        default=0.5,
        ge=STYLE_VECTOR_MIN,
        le=STYLE_VECTOR_MAX,
        description="Креативность: метафоры, необычные ассоциации, художественность"
    )
    
    def to_list(self) -> List[float]:
        """
        Конвертировать вектор в список для удобства обработки.
        
        Returns:
            List[float]: [playfulness, seriousness, emotionality, creativity]
        """
        return [self.playfulness, self.seriousness, self.emotionality, self.creativity]
    
    @classmethod
    def from_list(cls, values: List[float]) -> 'StyleVector':
        """
        Создать StyleVector из списка значений.
        
        Args:
            values: Список из 4 float значений
            
        Returns:
            StyleVector: Новый экземпляр вектора
            
        Raises:
            ValueError: Если список не содержит ровно 4 элемента
        """
        if len(values) != 4:
            raise ValueError(f"Expected 4 values for StyleVector, got {len(values)}")
        
        return cls(
            playfulness=values[0],
            seriousness=values[1],
            emotionality=values[2],
            creativity=values[3]
        )
    
    def is_significant_change(self, other: 'StyleVector') -> bool:
        """
        Проверить, отличается ли данный вектор от другого более чем на PARTNER_PERSONA_CHANGE_THRESHOLD.
        
        Args:
            other: StyleVector для сравнения
            
        Returns:
            True если хотя бы один компонент изменился более чем на порог
        """
        if not isinstance(other, StyleVector):
            raise ValueError("Can only compare with another StyleVector")
        
        changes = [
            abs(self.playfulness - other.playfulness),
            abs(self.seriousness - other.seriousness),
            abs(self.emotionality - other.emotionality),
            abs(self.creativity - other.creativity)
        ]
        
        return any(change > PARTNER_PERSONA_CHANGE_THRESHOLD for change in changes)


class PersonalityTrait(BaseModel):
    """
    Описание черты личности Химеры с характеристиками для детекции.
    """
    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )
    
    trait_name: str = Field(
        ...,
        min_length=1,
        description="Название черты (например: любознательность, ирония, эмпатия)"
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Описание черты и как она проявляется"
    )
    linguistic_markers: List[str] = Field(
        default_factory=list,
        description="Ключевые слова и паттерны для детекции черты"
    )
    mode_affinity: Dict[str, float] = Field(
        default_factory=dict,
        description="Связь с режимами общения (talk, expert, creative) - сила 0.0-1.0"
    )
    emotion_associations: Dict[str, float] = Field(
        default_factory=dict,
        description="Эмоциональные корреляции черты - какие эмоции усиливают проявление"
    )
    
    @field_validator('mode_affinity')
    @classmethod
    def validate_mode_affinity(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Проверка режимов и диапазона значений"""
        valid_modes = {'talk', 'expert', 'creative'}
        for mode, affinity in v.items():
            if mode not in valid_modes:
                raise ValueError(f"Invalid mode: {mode}. Must be one of: {valid_modes}")
            if not 0.0 <= affinity <= 1.0:
                raise ValueError(f"Mode affinity must be between 0.0 and 1.0, got {affinity}")
        return v
    
    @field_validator('emotion_associations')
    @classmethod
    def validate_emotion_associations(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Проверка эмоций и диапазона значений"""
        for emotion, strength in v.items():
            if emotion not in EMOTION_LABELS:
                raise ValueError(f"Unknown emotion: {emotion}")
            if not 0.0 <= strength <= 1.0:
                raise ValueError(f"Emotion association must be between 0.0 and 1.0, got {strength}")
        return v


class PartnerPersona(BaseModel):
    """
    Модель собеседника для персонализации режима общения.
    Версионируется при существенных изменениях.
    """
    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )
    
    # Идентификация
    persona_id: UUID = Field(
        ...,
        description="UUID персоны"
    )
    user_id: str = Field(
        ...,
        min_length=1,
        description="Telegram ID пользователя"
    )
    version: int = Field(
        default=1,
        ge=1,
        description="Версия персоны (инкрементируется при изменениях)"
    )
    
    # Стилевой вектор
    style_vector: StyleVector = Field(
        ...,
        description="4D вектор стиля общения пользователя"
    )
    style_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Уверенность в определении стиля"
    )
    
    # Определенный режим
    recommended_mode: str = Field(
        ...,
        pattern="^(talk|expert|creative)$",
        description="Оптимальный режим общения на основе стиля"
    )
    mode_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Уверенность в рекомендации режима"
    )
    
    # Предиктивная компонента
    predicted_interests: List[str] = Field(
        default_factory=list,
        description="Предсказанные будущие интересы пользователя"
    )
    prediction_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Уверенность в предсказаниях"
    )
    
    # Метаданные
    messages_analyzed: int = Field(
        default=0,
        ge=0,
        description="Количество проанализированных сообщений"
    )
    created_at: datetime = Field(
        ...,
        description="Время создания персоны"
    )
    updated_at: datetime = Field(
        ...,
        description="Время последнего обновления"
    )
    is_active: bool = Field(
        default=True,
        description="Активна ли данная версия персоны"
    )
    
    def is_significant_change(self, new_style_vector: StyleVector) -> bool:
        """
        Проверить, требуется ли создание новой версии персоны.
        
        Args:
            new_style_vector: Новый стилевой вектор для сравнения
            
        Returns:
            True если изменения существенны и требуют новой версии
        """
        return self.style_vector.is_significant_change(new_style_vector)


class TraitManifestation(BaseModel):
    """
    Запись о проявлении черты личности в конкретном контексте.
    """
    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )
    
    # Идентификация
    manifestation_id: UUID = Field(
        ...,
        description="UUID проявления"
    )
    user_id: str = Field(
        ...,
        min_length=1,
        description="Telegram ID пользователя"
    )
    
    # Информация о черте
    trait_name: str = Field(
        ...,
        min_length=1,
        description="Название проявившейся черты"
    )
    manifestation_strength: float = Field(
        ...,
        ge=PERSONALITY_TRAITS_MIN_STRENGTH,
        le=PERSONALITY_TRAITS_MAX_STRENGTH,
        description="Сила проявления черты в данном контексте"
    )
    
    # Контекст проявления
    mode: str = Field(
        ...,
        pattern="^(talk|expert|creative|base)$",
        description="Режим общения в момент проявления"
    )
    emotional_context: Dict[str, float] = Field(
        ...,
        description="Эмоциональный контекст в момент проявления"
    )
    message_id: Optional[UUID] = Field(
        None,
        description="ID конкретного сообщения (если есть)"
    )
    
    # Детекция
    detected_markers: List[str] = Field(
        ...,
        min_length=1,
        description="Лингвистические маркеры, по которым выявлена черта"
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Уверенность в детекции"
    )
    
    # Временные метки
    detected_at: datetime = Field(
        ...,
        description="Время обнаружения проявления"
    )
    
    # Группировка
    analysis_batch_id: Optional[UUID] = Field(
        None,
        description="ID пакета анализа для группировки"
    )
    
    @field_validator('emotional_context')
    @classmethod
    def validate_emotional_context(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Проверка эмоционального контекста"""
        if not v:
            raise ValueError("Emotional context cannot be empty")
        
        for emotion, score in v.items():
            if emotion not in EMOTION_LABELS:
                raise ValueError(f"Unknown emotion: {emotion}")
            if not 0.0 <= score <= 1.0:
                raise ValueError(f"Emotion score must be between 0.0 and 1.0, got {score}")
        
        return v


class TraitProfile(BaseModel):
    """
    Агрегированный профиль черт личности для быстрого доступа.
    """
    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )
    
    # Идентификация
    profile_id: UUID = Field(
        ...,
        description="UUID профиля"
    )
    user_id: str = Field(
        ...,
        min_length=1,
        description="Telegram ID пользователя"
    )
    
    # Агрегированные данные
    trait_scores: Dict[str, float] = Field(
        default_factory=dict,
        description="Средние силы проявления каждой черты"
    )
    dominant_traits: List[str] = Field(
        default_factory=list,
        max_length=5,
        description="Топ-5 доминирующих черт"
    )
    
    # Статистика
    total_manifestations: int = Field(
        default=0,
        ge=0,
        description="Общее количество зафиксированных проявлений"
    )
    last_updated: datetime = Field(
        ...,
        description="Время последнего обновления профиля"
    )
    
    @field_validator('trait_scores')
    @classmethod
    def validate_trait_scores(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Проверка оценок черт"""
        for trait, score in v.items():
            if not 0.0 <= score <= 1.0:
                raise ValueError(f"Trait score must be between 0.0 and 1.0, got {score}")
        return v
    
    def get_top_traits(self, n: int = 5) -> List[str]:
        """
        Получить топ N черт по силе проявления.
        
        Args:
            n: Количество черт для возврата (по умолчанию 5)
            
        Returns:
            List[str]: Список названий черт, отсортированных по убыванию силы
        """
        if not self.trait_scores:
            return []
        
        # Сортируем черты по убыванию силы
        sorted_traits = sorted(
            self.trait_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        # Возвращаем топ N названий черт
        return [trait for trait, _ in sorted_traits[:n]]


class PersonalityModifier(BaseModel):
    """
    Модификатор для черт личности от различных источников.
    Используется для передачи контекстных влияний в PersonalityActor.
    """
    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )
    
    modifier_type: Literal['style', 'emotion', 'temporal', 'context'] = Field(
        ...,
        description="Тип модификатора: style (от TalkModelActor), emotion (от PerceptionActor), temporal (время), context (общий контекст)"
    )
    
    modifier_data: Dict[str, float] = Field(
        ...,
        description="Словарь модификаторов черт {trait_name: multiplier}"
    )
    
    source_actor: Optional[str] = Field(
        None,
        description="ID актора-источника модификатора"
    )
    
    @field_validator('modifier_data')
    @classmethod
    def validate_modifier_values(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Проверка диапазона значений модификаторов (0.5 - 1.5)"""
        if not v:
            raise ValueError("Modifier data cannot be empty")
        
        for trait, value in v.items():
            if not isinstance(value, (int, float)):
                raise ValueError(f"Modifier value must be numeric, got {type(value)} for trait {trait}")
            
            if not 0.5 <= value <= 1.5:
                raise ValueError(
                    f"Modifier value must be between 0.5 and 1.5 (50% decrease to 50% increase), "
                    f"got {value} for trait {trait}"
                )
        
        return v