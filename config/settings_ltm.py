# ========================================
# LONG-TERM MEMORY (LTM)
# ========================================

# Коэффициент влияния maturity на порог
LTM_MATURITY_IMPACT_FACTOR = 0.1  # 0.1 = макс +6% к порогу для молодых профилей

LTM_PERCENTILE_ADJUSTMENT_FACTOR = 0.3  # !!! Коэффициент для расчета динамического порога от 90-го перцентиля: 0.3 для отладки, 0.7 для продакшн

# Эмоциональные пороги
LTM_EMOTIONAL_THRESHOLD = 0.4        # !!! Порог для сохранения в LTM, 0.4 - для наблюдения, 0.55- для продакшн (0.6 = ~1-5% сообщений)
LTM_EMOTIONAL_PEAK_THRESHOLD = 0.77  # Порог для определения эмоционального пика (по умолчанию: 0.8)
LTM_EMOTIONAL_SHIFT_THRESHOLD = 0.55 # Порог для определения эмоционального сдвига (по умолчанию: 0.5)

# Типы памяти и ограничения
LTM_MEMORY_TYPES = ['self_related', 'world_model', 'user_related'] # Допустимые типы воспоминаний
LTM_SCORE_MIN = 0.0 # Мин значение для всех score полей (по умолчанию: 0.0)
LTM_SCORE_MAX = 1.0 # Макс значение для всех score полей (по умолчанию: 1.0)

LTM_USER_ID_MAX_LENGTH = 255        # Макс длина user_id (по умолчанию: 255)
LTM_MEMORY_TYPE_MAX_LENGTH = 50     # Макс длина типа памяти (по умолчанию: 50)
LTM_TRIGGER_REASON_MAX_LENGTH = 100 # Макс длина причины сохранения (по умолчанию: 100)
LTM_DOMINANT_EMOTIONS_MAX_SIZE = 10 # Макс количество доминирующих эмоций (по умолчанию: 10)
LTM_SEMANTIC_TAGS_MAX_SIZE = 20     # Макс количество семантических тегов (по умолчанию: 20)
LTM_CONVERSATION_FRAGMENT_MAX_MESSAGES = 10 # Макс количество сообщений в фрагменте (по умолчанию: 10)
LTM_CONVERSATION_FRAGMENT_DEFAULT_WINDOW = 5 # Размер окна контекста по умолчанию (по умолчанию: 5)
LTM_MESSAGE_CONTENT_MAX_LENGTH = 2000 # Макс длина контента сообщения (по умолчанию: 2000)

# Причины сохранения в LTM
LTM_TRIGGER_REASONS = [
    'emotional_peak',
    'emotional_shift', 
    'self_reference',
    'deep_insight',
    'personal_revelation',
    'relationship_change',
    'creative_breakthrough'
]
LTM_DEFAULT_ACCESS_COUNT = 0 # Начальное количество обращений к воспоминанию (по умолчанию: 0)
LTM_DEFAULT_SELF_RELEVANCE_SCORE = None  # Релевантность для самоидентификации (по умолчанию: None)

# Настройки LTMActor
LTM_QUERY_TIMEOUT = 5.0          # Таймаут запросов к БД в секундах (по умолчанию: 5.0)
LTM_METRICS_ENABLED = False      # Включить сбор метрик (по умолчанию: True)
LTM_METRICS_LOG_INTERVAL = 300   # Интервал логирования метрик (по умолчанию: 300 c)
LTM_SCHEMA_CHECK_TIMEOUT = 5.0   # Таймаут проверки схемы БД в секундах (по умолчанию: 5.0)

# Параметры поиска в LTM
LTM_SEARCH_MAX_LIMIT = 100   # Макс количество результатов за один поиск (по умолчанию: 100)
LTM_SEARCH_DEFAULT_LIMIT = 10 # Количество результатов по умолчанию (по умолчанию: 10)
LTM_SEARCH_TAGS_MODE_ANY = 'any'  # Режим поиска по тегам "хотя бы один" (по умолчанию: 'any')
LTM_SEARCH_TAGS_MODE_ALL = 'all'  # Режим поиска по тегам "все теги" (по умолчанию: 'all')
LTM_SEARCH_RECENT_DAYS_DEFAULT = 7      # Период поиска недавних воспоминаний в днях (по умолчанию: 7)
LTM_SEARCH_MIN_IMPORTANCE_DEFAULT = 0.8 # Мин важность для поиска (по умолчанию: 0.8)



# ========================================
# Настройки векторизации (Embeddings)
# ========================================

# Модель для генерации embeddings
LTM_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
LTM_EMBEDDING_DEVICE = "cpu"  # или "cuda" при наличии GPU
LTM_EMBEDDING_CACHE_DIR = "./models/cache"

# Размерности композитного embedding (768d total)
LTM_EMBEDDING_SEMANTIC_DIM = 384   # Семантический компонент (по умолчанию: 384)
LTM_EMBEDDING_EMOTIONAL_DIM = 128  # Эмоциональный компонент (по умолчанию: 128)
LTM_EMBEDDING_TEMPORAL_DIM = 64    # Временной компонент (по умолчанию: 64)
LTM_EMBEDDING_PERSONAL_DIM = 192   # Персональный компонент (по умолчанию: 192)

# Параметры векторизации
LTM_EMBEDDING_BATCH_SIZE = 32      # Размер батча для обработки (по умолчанию: 32)
LTM_EMBEDDING_MAX_LENGTH = 512     # Макс длина текста в символах (по умолчанию: 512)
LTM_EMBEDDING_NORMALIZE = True     # Нормализовать векторы (по умолчанию: True)

# Параметры генерации embeddings
LTM_EMBEDDING_THREAD_POOL_SIZE = 2 # Размер пула потоков для асинхронной генерации векторов (по умолчанию: 2)
LTM_EMBEDDING_GENERATION_TIMEOUT = 10.0  # Таймаут генерации одного embedding  (по умолчанию: 10.0 с)
LTM_EMBEDDING_REQUEST_TIMEOUT = 2.0  # Таймаут для запроса embedding в секундах
LTM_VECTOR_CACHE_TTL = 3600  # TTL для кэша векторного поиска (1 час)



# ========================================
# Параметры аналитики LTM
# ========================================

LTM_ANALYTICS_SIMILARITY_THRESHOLD = 0.7        # Поиск по эмоциональному сходству
LTM_ANALYTICS_EMOTIONAL_SIMILARITY_LIMIT = 10   # Макс количество результатов (по умолчанию: 10)
LTM_ANALYTICS_PATTERN_MIN_OCCURRENCES = 3       # Детекция паттернов: минимум повторений для паттерна (по умолчанию: 3)

# Эмоциональные траектории
LTM_ANALYTICS_TRAJECTORY_DEFAULT_DAYS = 30      # Временное окно анализа в днях (по умолчанию: 30)
LTM_ANALYTICS_TRAJECTORY_DEFAULT_GRANULARITY = 'day'  # Детализация времени (по умолчанию: 'day'). Варианты: 'hour', 'day', 'week'

# Анализ концептуальных ассоциаций
LTM_ANALYTICS_CONCEPT_ASSOCIATIONS_LIMIT = 20   # Лимит воспоминаний для анализа концепта (по умолчанию: 20)

# Определение трендов
LTM_ANALYTICS_TREND_INCREASE_THRESHOLD = 0.05   # Мин среднее изменение для тренда "рост"
LTM_ANALYTICS_TREND_DECREASE_THRESHOLD = -0.05  # Макс среднее изменение для тренда "спад"

# Поиск по настроению
LTM_ANALYTICS_MOOD_MATCH_THRESHOLD = 0.3        # Мин вес для совпадения настроения (по умолчанию: 0.3)

# Распределение важности
LTM_ANALYTICS_HISTOGRAM_BUCKETS = 10            # Количество интервалов гистограммы (по умолчанию: 10)
LTM_ANALYTICS_ANOMALY_STD_DEVS = 2              # Стандартные отклонения для аномалий (по умолчанию: 2)



# ========================================
# Параметры оценки новизны
# ========================================

# Веса факторов новизны (должны давать в сумме 1.0)
LTM_NOVELTY_SEMANTIC_WEIGHT = 0.4     # Вес семантического расстояния в общей оценке (по умолчанию: 0.4)
LTM_NOVELTY_EMOTIONAL_WEIGHT = 0.15   # Вес эмоциональной редкости 
LTM_NOVELTY_CONTEXT_WEIGHT = 0.2      # Вес редкости семантических тегов (по умолчанию: 0.2)
LTM_NOVELTY_TEMPORAL_WEIGHT = 0.2     # Вес временной новизны (по умолчанию: 0.2)

# Параметры холодного старта
LTM_COLD_START_BUFFER_SIZE = 20       # Количество сообщений для калибровки (по умолчанию: 20)
LTM_COLD_START_MIN_THRESHOLD = 0.4    # !!! Мин порог новизны: 0.4 для отладки, 0.8 для продакшн
LTM_NOVELTY_SCORES_WINDOW = 90        # Размер окна последних оценок (по умолчанию: 90)

# Параметры локальной плотности (KNN)
LTM_KNN_NEIGHBORS = 7                 # Количество ближайших соседей для оценки плотности (по умолчанию: 5).
LTM_KNN_DENSITY_THRESHOLD = 0.18      # Порог расстояния для "плотного" региона (по умолчанию: 0.2)
LTM_KNN_DENSITY_PENALTY = 0.25        # Снижение веса в плотных регионах (по умолчанию: 0.3)

# Пороги обработки эмоций
LTM_EMOTION_FREQUENCY_THRESHOLD = 0.18 # Мин значение эмоции для учета (по умолчанию: 0.1)
LTM_PERCENTILE_MIN_SAMPLES = 15        # Минимум оценок для расчета перцентиля (по умолчанию: 20)
LTM_MATURITY_SIGMOID_RATE = 0.09       # Скорость адаптации профиля (по умолчанию: 0.1)



# ========================================
# Метаданные для логики поиска
# ========================================

# Приоритеты категорий (для определения search_type)
LTM_TRIGGER_PRIORITIES = {
    'self_related': 1,          # Высший приоритет - всегда self_related search
    'unfinished_business': 2,   # Высокий - часто нужен vector search
    'memory_recall': 2,         # Высокий - explicit memory request
    'uncertainty_doubt': 3,     # Высокий-средний - нужна поддержка из памяти
    'emotional_resonance': 3,   # Средний
    'temporal_acute': 3,        # Средний 
    'existential_inquiry': 4,   # Низкий
    'pattern_recognition': 4,   # Низкий
    'metacognitive': 4,         # Низкий
    'temporal_distant': 5,      # Самый низкий
    'contextual_amplifiers': 5  # Самый низкий
}

# Маппинг категорий на типы поиска  
LTM_CATEGORY_TO_SEARCH_TYPE = {
    'self_related': 'self_related',   # Специализированный поиск по идентичности Химеры
    'memory_recall': 'recent',        # Явные запросы часто требуют недавние воспоминания
    'past_reference': 'recent',       # Ссылки на прошлое часто касаются недавних событий
    'unfinished_business': 'vector',  # Нужен сложный семантический поиск
    'uncertainty_doubt': 'vector',    # Нужны семантически похожие ситуации для поддержки
    'emotional_resonance': 'vector',  # Эмоциональное семантическое сходство
    'existential_inquiry': 'vector',  # Глубокие смысловые связи
    'temporal_acute': 'recent',       # Недавнее время = поиск недавних
    'temporal_distant': 'importance', # Далекое время = только важные воспоминания
    'pattern_recognition': 'vector',  # Распознавание паттернов требует семантики
    'metacognitive': 'vector',        # Мыслительные паттерны требуют семантики  
    'contextual_amplifiers': 'vector' # Контекст требует семантического анализа
}



# ========================================
# Настройки запросов к LTM
# ========================================

LTM_REQUEST_TIMEOUT = 0.5  # Макс время ожидания ответа от LTM (по умолчанию: 0.5 с)
LTM_CONTEXT_LIMIT = 3      # Макс количество воспоминаний из LTM (по умолчанию: 3)
LTM_REQUEST_ENABLED = True # Глобальное включение/выключение LTM (по умолчанию: True)
LTM_DEFAULT_SEARCH_TYPE = "recent"     # Тип поиска при отсутствии специфичных триггеров (по умолчанию: "recent")
LTM_EMOTIONAL_SEARCH_THRESHOLD = 0.7 # Порог эмоциональной интенсивности для активации поиска в LTM (по умолчанию: 0.7)



# ========================================
# Основные параметры кэширования LTM
# ========================================

LTM_CACHE_ENABLED = True        # Включение Redis кэширования для LTM (по умолчанию: True)
LTM_CACHE_KEY_PREFIX = "ltm"    # Префикс для всех ключей кэша LTM (по умолчанию: "ltm")
LTM_CACHE_DEFAULT_TTL = 1800    # Время жизни кэша в секундах (по умолчанию: 1800)

# Параметры кэширования результатов новизны
LTM_NOVELTY_CACHE_TTL = 1800    # TTL для финальных результатов оценки новизны (по умолчанию: 1800 с). 
LTM_NOVELTY_CACHE_LOG_INTERVAL = 100 # Интервал логирования статистики кэша (по умолчанию: 100)

# Параметры кэширования промежуточных вычислений
LTM_EMBEDDING_CACHE_TTL = 3600   # TTL для векторных представлений текста (по умолчанию: 3600 с)
LTM_KNN_CACHE_TTL = 900          # TTL для результатов поиска ближайших соседей (по умолчанию: 900 с)
LTM_TEMPORAL_CACHE_TTL = 1200    # TTL для временного анализа по тегам (по умолчанию: 1200 с)
LTM_PROFILE_CACHE_TTL = 21600    # TTL для полного профиля пользователя (по умолчанию: 21600 с)
LTM_PERCENTILE_CACHE_TTL = 3600  # TTL для перцентилей порогов новизны (по умолчанию: 3600 с)
LTM_CALIBRATION_CACHE_TTL = 7200 # TTL для статуса калибровки пользователя (по умолчанию: 7200 с)
LTM_CACHE_METRICS_ENABLED = True # Включение сбора метрик кэширования (по умолчанию: True)
LTM_CACHE_HIT_RATE_ALERT = 0.5   # Порог для предупреждения о низком hit rate (по умолчанию: 0.5)



# ========================================
# Параметры политики хранения (Retention Policy)
# ========================================

LTM_CLEANUP_ENABLED = True          # Включение автоматической очистки (по умолчанию: True)
LTM_RETENTION_DAYS = 365            # Срок хранения воспоминаний в днях (по умолчанию: 365)
LTM_RETENTION_MIN_IMPORTANCE = 0.75 # Мин важность для сохранения после срока (по умолчанию: 0.75)
LTM_RETENTION_CRITICAL_IMPORTANCE = 0.95  # Порог критической важности (по умолчанию: 0.95)
LTM_RETENTION_MIN_ACCESS_COUNT = 5        # Минимум обращений для защиты от удаления (по умолчанию: 5)

# Параметры выполнения очистки (Cleanup Execution)
LTM_CLEANUP_BATCH_SIZE = 1000     # Размер батча для удаления (по умолчанию: 1000)
LTM_CLEANUP_QUERY_TIMEOUT = 30.0  # Таймаут запросов очистки в секундах (по умолчанию: 30.0)
LTM_CLEANUP_SCHEDULE_HOUR = 3     # Час запуска очистки UTC (по умолчанию: 3)
LTM_CLEANUP_SCHEDULE_MINUTE = 0   # Минута запуска (по умолчанию: 0)
LTM_CLEANUP_DRY_RUN = False       # Режим сухого прогона (по умолчанию: False)

# Параметры генерации summary
LTM_SUMMARY_ENABLED = True     # Создавать ли агрегированные summary (по умолчанию: True)
LTM_SUMMARY_PERIOD = 'month'   # Период агрегации (по умолчанию: 'month')
LTM_SUMMARY_MIN_MEMORIES = 5   # Минимум воспоминаний для создания summary (по умолчанию: 5)
LTM_SUMMARY_TOP_EMOTIONS = 5   # Количество топ эмоций в summary (по умолчанию: 5)
LTM_SUMMARY_TOP_TAGS = 10      # Количество топ тегов в summary (по умолчанию: 10)

# Параметры инвалидации кэша
LTM_CLEANUP_INVALIDATE_CACHE = True # Очищать ли кэши после cleanup (по умолчанию: True)
LTM_CLEANUP_INVALIDATE_PATTERNS = [ # Паттерны кэша для очистки (по умолчанию: список)
    "novelty:knn:*",
    "novelty:temporal:*", 
    "novelty:final:*"
]

# Параметры логирования и мониторинга
LTM_CLEANUP_LOG_LEVEL = 'INFO' # Уровень логирования операций cleanup (по умолчанию: 'INFO')
LTM_CLEANUP_EMIT_EVENTS = True # Генерировать ли события для Event Store (по умолчанию: True)