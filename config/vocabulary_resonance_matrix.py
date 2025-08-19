# ========================================
# СЛОВАРЬ РЕЗОНАНСНОЙ ПЕРСОНАЛИЗАЦИИ
# ========================================

from typing import Dict, Optional
from dataclasses import dataclass
from config.settings import (
    RESONANCE_MAX_TOTAL_CHANGE
)


# === ЗАЩИЩЕННЫЕ ЧЕРТЫ ===

# Черты, которые изменяются медленнее для сохранения идентичности
CORE_TRAITS = [
    "curiosity",      # Любознательность - основа личности Химеры
    "empathy",        # Эмпатия - ключевая черта для отношений
    "philosophical",  # Философичность - глубина мышления
    "caring"          # Заботливость - эмоциональное ядро
]


# === КОНТЕКСТ ДЛЯ РЕЗОНАНСА ===

@dataclass
class ResonanceContext:
    """Контекст для вычисления резонанса"""
    user_style: Dict[str, float]  # StyleVector как словарь
    current_emotion: Optional[str] = None
    emotion_intensity: float = 0.0
    interaction_count: int = 0


# === МАТРИЦА БАЗОВОГО РЕЗОНАНСА ===

# Как стили пользователя влияют на черты Химеры
STYLE_TRAIT_RESONANCE = {
    "playfulness": {
        # Высокая игривость пользователя усиливает/ослабляет:
        "enhance": {
            "playfulness": 0.25,    # Химера становится более игривой
            "irony": 0.15,          # Больше тонкого юмора
            "rebellious": 0.10,     # Легкое бунтарство
            "magical_realism": 0.10 # Фантазийность
        },
        "diminish": {
            "analytical": 0.15,     # Меньше структурированности
            "philosophical": 0.10,  # Меньше глубоких размышлений
            "reflective": 0.10      # Меньше самоанализа
        }
    },
    
    "seriousness": {
        # Высокая серьезность пользователя:
        "enhance": {
            "analytical": 0.25,     # Структурированное мышление
            "philosophical": 0.20,  # Глубокие размышления
            "reflective": 0.15,     # Больше рефлексии
            "curiosity": 0.10       # Исследовательский интерес
        },
        "diminish": {
            "playfulness": 0.20,    # Меньше игривости
            "rebellious": 0.15,     # Меньше бунтарства
            "magical_realism": 0.15,# Меньше фантазийности
            "irony": 0.10           # Меньше иронии
        }
    },
    
    "emotionality": {
        # Высокая эмоциональность пользователя:
        "enhance": {
            "empathy": 0.25,        # Глубокое сопереживание
            "caring": 0.20,         # Больше заботы
            "aesthetics": 0.15,     # Образность речи
            "allusive": 0.10        # Недосказанность
        },
        "diminish": {
            "analytical": 0.10,     # Меньше холодной логики
            "irony": 0.10           # Меньше отстраненной иронии
        }
    },
    
    "creativity": {
        # Высокая креативность пользователя:
        "enhance": {
            "magical_realism": 0.25,# Магический реализм
            "aesthetics": 0.20,     # Художественность
            "allusive": 0.15,       # Многозначность
            "paradoxical": 0.15,    # Парадоксальность
            "rebellious": 0.10      # Нарушение шаблонов
        },
        "diminish": {
            "analytical": 0.10      # Меньше систематичности
        }
    }
}


# === ЭМОЦИОНАЛЬНЫЕ МОДИФИКАТОРЫ ===

# Как текущие эмоции влияют на силу резонанса
EMOTION_RESONANCE_MODIFIERS = {
    # Радостные эмоции усиливают позитивный резонанс
    "joy": {"playfulness": 1.2, "caring": 1.1},
    "excitement": {"playfulness": 1.2, "rebellious": 1.1},
    "optimism": {"caring": 1.1, "philosophical": 1.1},
    
    # Грустные эмоции усиливают эмпатический резонанс
    "sadness": {"empathy": 1.3, "caring": 1.2, "philosophical": 1.1},
    "grief": {"empathy": 1.3, "caring": 1.2},
    
    # Тревожные состояния
    "fear": {"caring": 1.2, "analytical": 0.8},
    "nervousness": {"caring": 1.1, "playfulness": 0.9},
    
    # Интеллектуальные эмоции
    "curiosity": {"curiosity": 1.2, "analytical": 1.1},
    "realization": {"philosophical": 1.2, "reflective": 1.1}
}


# === ОСНОВНАЯ ФУНКЦИЯ РЕЗОНАНСА ===

def calculate_resonance_impact(
    user_style: Dict[str, float],
    current_emotion: Optional[str] = None,
    emotion_intensity: float = 0.0
) -> Dict[str, float]:
    """
    Вычисляет коэффициенты резонанса для черт личности.
    
    Args:
        user_style: Словарь стилей пользователя (playfulness, seriousness, etc.)
        current_emotion: Текущая доминирующая эмоция
        emotion_intensity: Интенсивность эмоции (0.0-1.0)
        
    Returns:
        Dict[str, float]: Коэффициенты изменения черт (1.0 = без изменений)
    """
    
    # Начинаем с нейтрального резонанса
    resonance = {}
    
    # 1. Применяем базовый резонанс по стилю
    for style_component, strength in user_style.items():
        if style_component not in STYLE_TRAIT_RESONANCE:
            continue
            
        # Применяем только если стиль выражен достаточно сильно
        if strength > RESONANCE_STYLE_THRESHOLD:
            rules = STYLE_TRAIT_RESONANCE[style_component]
            
            # Усиливаем черты
            for trait, impact in rules.get("enhance", {}).items():
                current = resonance.get(trait, 1.0)
                # Сила влияния пропорциональна выраженности стиля
                change = impact * strength
                resonance[trait] = min(current + change, RESONANCE_MAX_COEFFICIENT)
            
            # Ослабляем черты
            for trait, impact in rules.get("diminish", {}).items():
                current = resonance.get(trait, 1.0)
                change = impact * strength
                resonance[trait] = max(current - change, RESONANCE_MIN_COEFFICIENT)
    
    # 2. Применяем эмоциональные модификаторы
    if current_emotion and emotion_intensity > RESONANCE_EMOTION_THRESHOLD:
        if current_emotion in EMOTION_RESONANCE_MODIFIERS:
            modifiers = EMOTION_RESONANCE_MODIFIERS[current_emotion]
            for trait, multiplier in modifiers.items():
                if trait in resonance:
                    # Эмоция модулирует существующий резонанс
                    base = resonance[trait]
                    emotion_effect = (multiplier - 1.0) * emotion_intensity
                    resonance[trait] = base * (1.0 + emotion_effect)
    
    # 3. Применяем защиту core traits
    for trait in CORE_TRAITS:
        if trait in resonance:
            # Core черты изменяются в 2 раза медленнее
            current = resonance[trait]
            if current != 1.0:
                # Приближаем к 1.0 (нейтральному значению)
                delta = (current - 1.0) * RESONANCE_CORE_PROTECTION_FACTOR
                resonance[trait] = 1.0 + delta
    
    # 4. Проверяем общее ограничение на сумму изменений
    total_change = sum(abs(coef - 1.0) for coef in resonance.values())
    if total_change > RESONANCE_MAX_TOTAL_CHANGE:
        # Масштабируем все изменения пропорционально
        scale_factor = RESONANCE_MAX_TOTAL_CHANGE / total_change
        for trait in resonance:
            current = resonance[trait]
            delta = (current - 1.0) * scale_factor
            resonance[trait] = 1.0 + delta
    
    # 5. Финальная проверка диапазонов
    for trait in resonance:
        resonance[trait] = max(
            RESONANCE_MIN_COEFFICIENT,
            min(resonance[trait], RESONANCE_MAX_COEFFICIENT)
        )
    
    return resonance


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def add_resonance_noise(
    coefficients: Dict[str, float],
    noise_level: float = 0.05
) -> Dict[str, float]:
    """
    Добавляет небольшую случайность к коэффициентам резонанса.
    
    Args:
        coefficients: Исходные коэффициенты
        noise_level: Уровень шума (0.05 = ±5%)
        
    Returns:
        Dict[str, float]: Коэффициенты с добавленным шумом
    """
    import random
    
    noisy_coefficients = {}
    for trait, coef in coefficients.items():
        # Добавляем случайное отклонение
        noise = random.uniform(-noise_level, noise_level)
        noisy_coef = coef * (1.0 + noise)
        
        # Соблюдаем границы
        noisy_coefficients[trait] = max(
            RESONANCE_MIN_COEFFICIENT,
            min(noisy_coef, RESONANCE_MAX_COEFFICIENT)
        )
    
    return noisy_coefficients


def calculate_resonance_strength(
    user_style: Dict[str, float],
    personality_profile: Dict[str, float]
) -> float:
    """
    Вычисляет общую силу резонанса между стилем пользователя и профилем личности.
    
    Returns:
        float: Сила резонанса от 0.0 до 1.0
    """
    # Простая метрика - среднее совпадение по доминирующим чертам
    resonance_scores = []
    
    # Находим доминирующие черты в профиле
    top_traits = sorted(personality_profile.items(), key=lambda x: x[1], reverse=True)[:5]
    
    for trait, strength in top_traits:
        # Проверяем, резонирует ли черта со стилем
        trait_resonance = 0.0
        
        # Смотрим, усиливается ли эта черта каким-либо стилем
        for style, style_strength in user_style.items():
            if style in STYLE_TRAIT_RESONANCE:
                enhance_traits = STYLE_TRAIT_RESONANCE[style].get("enhance", {})
                if trait in enhance_traits:
                    trait_resonance += style_strength * enhance_traits[trait]
        
        resonance_scores.append(trait_resonance)
    
    # Возвращаем среднюю силу резонанса
    return min(sum(resonance_scores) / len(resonance_scores) if resonance_scores else 0.0, 1.0)


# ========================================
# НАСТРОЙКИ
# ========================================

# === Пороги активации ===

RESONANCE_STYLE_THRESHOLD = 0.6      # Минимальная выраженность стиля для резонанса
RESONANCE_EMOTION_THRESHOLD = 0.5    # Минимальная интенсивность эмоции

# === Ограничения резонанса ===

RESONANCE_MIN_COEFFICIENT = 0.7      # Минимальный коэффициент (-30%)
RESONANCE_MAX_COEFFICIENT = 1.3      # Максимальный коэффициент (+30%)
RESONANCE_CORE_PROTECTION_FACTOR = 0.5  # Core черты меняются в 2 раза медленнее

# === Параметры шума ===

RESONANCE_DEFAULT_NOISE_LEVEL = 0.05  # 5% случайности по умолчанию