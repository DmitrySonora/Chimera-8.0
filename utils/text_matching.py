"""
Модуль для поиска текстовых маркеров с учетом основ слов.
"""
from typing import List, Set


def normalize_and_match(text: str, markers: List[str]) -> List[str]:
    """
    Найти маркеры в тексте с учетом основ слов.
    
    Логика поиска:
    1. Если маркер содержит пунктуацию (!?.,;:)) - точное вхождение подстроки
    2. Если длина маркера ≤ 3 символов - точное совпадение слова  
    3. Если длина маркера > 3 символов - вхождение маркера в слова текста
    
    Args:
        text: Исходный текст для поиска
        markers: Список маркеров для поиска
        
    Returns:
        Список найденных уникальных маркеров
    """
    if not text or not markers:
        return []
    
    # Приводим текст к нижнему регистру
    text_lower = text.lower()
    
    # Результат - уникальные найденные маркеры
    found_markers: Set[str] = set()
    
    # Разбиваем текст на слова для поиска
    # Простое разбиение по пробелам
    words_raw = text_lower.split()
    
    # Очищаем слова от знаков препинания для обычного поиска
    words_clean = []
    for word in words_raw:
        # Сохраняем слова со скобками как есть (для "хах)", "ага)")
        if ')' in word:
            words_clean.append(word)
        else:
            # Убираем знаки препинания с краев
            cleaned = word.strip('.,!?;:()[]{}"\'-')
            if cleaned:
                words_clean.append(cleaned)
    
    for marker in markers:
        marker_lower = marker.lower()
        
        # Случай 1: Маркер содержит знаки препинания - ищем точное вхождение подстроки
        if any(char in marker for char in '!?.,;:)'):
            if marker_lower in text_lower:
                found_markers.add(marker)
                
        # Случай 2: Короткий маркер (≤ 3 символа) - точное совпадение слова
        elif len(marker) <= 3:
            # Проверяем точное совпадение со словом
            for word in words_clean:
                if word == marker_lower:
                    found_markers.add(marker)
                    break
                    
        # Случай 3: Длинный маркер (> 3 символа) - вхождение в слова
        else:
            for word in words_clean:
                if marker_lower in word:
                    found_markers.add(marker)
                    break  # Один маркер считаем только один раз
    
    return list(found_markers)