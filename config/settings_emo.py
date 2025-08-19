# ========================================
# EMOTION ANALYSIS (DeBERTa)
# ========================================

# Модель и устройство
EMOTION_MODEL_NAME = "fyaronskiy/deberta-v1-base-russian-go-emotions"
EMOTION_MODEL_DEVICE = "cpu"  # или "cuda" при наличии GPU
EMOTION_MODEL_CACHE_DIR = "./emo/cache"  # Директория для кэша моделей

# Параметры анализа
EMOTION_CONFIDENCE_THRESHOLD = 0.5  # Общий порог (используется для метрик)
EMOTION_MODEL_MAX_LENGTH = 128      # Максимальная длина текста в токенах

# Логирование
EMOTION_LOG_PREDICTIONS = True      # Логировать ли предсказания
EMOTION_LOG_THRESHOLD = 0.3         # Минимальная вероятность для логирования
EMOTION_EMOJI_MAP = {
    'joy': '😊',
    'sadness': '😢',
    'anger': '😠',
    'fear': '😨',
    'surprise': '😮',
    'disgust': '🤮',
    'love': '😍',
    'admiration': '🤩',
    'amusement': '😄',
    'approval': '👍',
    'caring': '🤗',
    'confusion': '😕',
    'curiosity': '🤔',
    'desire': '🫦',
    'disappointment': '😞',
    'disapproval': '👎',
    'embarrassment': '😳',
    'excitement': '🎉',
    'gratitude': '🙏',
    'grief': '😔',
    'nervousness': '😰',
    'optimism': '✨',
    'pride': '😤',
    'realization': '💡',
    'relief': '😌',
    'remorse': '😔',
    'annoyance': '😒',
    'neutral': '😐'
}

# Пороговые значения для каждой эмоции (из документации модели)
EMOTION_THRESHOLDS = [
    0.551,  # admiration
    0.184,  # amusement
    0.102,  # anger
    0.102,  # annoyance
    0.184,  # approval
    0.224,  # caring
    0.204,  # confusion
    0.408,  # curiosity
    0.204,  # desire
    0.224,  # disappointment
    0.245,  # disapproval
    0.306,  # disgust
    0.163,  # embarrassment
    0.286,  # excitement
    0.388,  # fear
    0.327,  # gratitude
    0.020,  # grief
    0.163,  # joy
    0.449,  # love
    0.102,  # nervousness
    0.224,  # optimism
    0.041,  # pride
    0.122,  # realization
    0.061,  # relief
    0.143,  # remorse
    0.429,  # sadness
    0.306,  # surprise
    0.400   # neutral - УВЕЛИЧИТЬ до 0.4 для снижения доминирования
]

EMOTION_LABELS = [
    'admiration', 'amusement', 'anger', 'annoyance', 
    'approval', 'caring', 'confusion', 'curiosity',
    'desire', 'disappointment', 'disapproval', 'disgust',
    'embarrassment', 'excitement', 'fear', 'gratitude',
    'grief', 'joy', 'love', 'nervousness',
    'optimism', 'pride', 'realization', 'relief',
    'remorse', 'sadness', 'surprise', 'neutral'
]

EMOTION_LABELS_RU = {
    'admiration': 'восхищение',
    'amusement': 'веселье',
    'anger': 'гнев',
    'annoyance': 'раздражение',
    'approval': 'одобрение',
    'caring': 'забота',
    'confusion': 'замешательство',
    'curiosity': 'любопытство',
    'desire': 'желание',
    'disappointment': 'разочарование',
    'disapproval': 'неодобрение',
    'disgust': 'отвращение',
    'embarrassment': 'смущение',
    'excitement': 'волнение',
    'fear': 'страх',
    'gratitude': 'благодарность',
    'grief': 'горе',
    'joy': 'радость',
    'love': 'любовь',
    'nervousness': 'нервозность',
    'optimism': 'оптимизм',
    'pride': 'гордость',
    'realization': 'осознание',
    'relief': 'облегчение',
    'remorse': 'раскаяние',
    'sadness': 'грусть',
    'surprise': 'удивление',
    'neutral': 'нейтрально'
}



# ========================================
# Интеграция эмоций с потоком сообщений
# ========================================

EMOTION_ANALYSIS_ENABLED = True          # Включить анализ эмоций для сообщений
EMOTION_PEAK_THRESHOLD = 0.8             # Порог для EmotionalPeakEvent
EMOTION_TEXT_PREVIEW_LENGTH = 50         # Длина превью текста в событии
