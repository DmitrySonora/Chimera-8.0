import os
from dotenv import load_dotenv

load_dotenv()

# Отключаем предупреждения от HuggingFace tokenizers
os.environ["TOKENIZERS_PARALLELISM"] = "false"



# ========================================
# Лимиты демо-доступа
# ========================================

DAILY_MESSAGE_LIMIT = 10  # Количество сообщений в день для неавторизованных



# ========================================
# Основное логирование
# ========================================

LOG_LEVEL = "DEBUG" # Уровень логирования (DEBUG, INFO, WARNING, ERROR) 
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s" # Формат сообщений логов
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S" # Формат даты в логах 



# ========================================
# Backend-настройки
# ========================================

# ActorSystem настройки
ACTOR_SYSTEM_NAME = "chimera"
ACTOR_MESSAGE_QUEUE_SIZE = 1000     # Макс размер очереди сообщений
ACTOR_SHUTDOWN_TIMEOUT = 5.0        # Секунды
ACTOR_MESSAGE_TIMEOUT = 1.0         # Таймаут ожидания сообщения в message loop

# Retry настройки
ACTOR_MESSAGE_RETRY_ENABLED = True  # Включить retry механизм
ACTOR_MESSAGE_MAX_RETRIES = 3       # Макс количество попыток
ACTOR_MESSAGE_RETRY_DELAY = 0.1     # Начальная задержка между попытками (сек)
ACTOR_MESSAGE_RETRY_MAX_DELAY = 2.0 # Макс задержка между попытками (сек)

# Circuit Breaker настройки
CIRCUIT_BREAKER_ENABLED = True          # Включить Circuit Breaker
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5   # Количество ошибок для открытия
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60   # Время восстановления в секундах

# JSON логирование
ENABLE_JSON_LOGGING = True  # Включить JSON логирование параллельно с текстовым
JSON_LOG_FILE = "logs/chimera.json"  # Путь к файлу JSON логов

# Ротация логов
LOG_ROTATION_ENABLED = True      # Включить ротацию файлов логов
LOG_MAX_BYTES = 1 * 1024 * 1024  # Макс размер файла логов (1 МБ)
LOG_BACKUP_COUNT = 5  # Количество архивных файлов логов

# Мониторинг
ENABLE_PERFORMANCE_METRICS = True # Включить сбор метрик производительности
METRICS_LOG_INTERVAL = 60  # Интервал логирования метрик в секундах (по умолчанию: 60)
SLOW_OPERATION_THRESHOLD = 0.1  # Порог в секундах для определения медленных операций (по умолчанию: 0.1)

# Dead Letter Queue настройки
DLQ_MAX_SIZE = 1000          # Макс размер очереди перед автоочисткой
DLQ_CLEANUP_INTERVAL = 3600  # Интервал очистки в секундах (1 час)
DLQ_METRICS_ENABLED = True   # Включить метрики DLQ

# Event Store настройки
EVENT_STORE_TYPE = "postgres"            # Тип хранилища ("postgres" или "memory")
EVENT_STORE_MAX_MEMORY_EVENTS = 10000    # Макс событий в памяти
EVENT_STORE_STREAM_CACHE_SIZE = 100      # Размер LRU кэша потоков
EVENT_STORE_CLEANUP_INTERVAL = 3600      # Интервал очистки старых событий (сек)
EVENT_STORE_CLEANUP_BATCH_SIZE = 100     # Размер батча при очистке

# Сериализация событий
EVENT_SERIALIZATION_FORMAT = "json"  # Формат сериализации событий (по умолчанию: "json")
EVENT_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ" # Формат timestamp для сериализации событий



# ========================================
# Event Archival & Storage Monitoring
# ========================================

# Event Archival (Архивация событий)
ARCHIVE_ENABLED = True          # Включить автоматическую архивацию старых событий
ARCHIVE_DAYS_THRESHOLD = 90     # Архивировать события старше указанного количества дней 
ARCHIVE_BATCH_SIZE = 1000       # Количество событий для архивации за одну транзакцию
ARCHIVE_COMPRESSION_LEVEL = 6   # Уровень сжатия gzip (1-9); 6 - баланс скорости и сжатия
ARCHIVE_SCHEDULE_HOUR = 4       # Час запуска архивации в UTC 
ARCHIVE_SCHEDULE_MINUTE = 0     # Минута запуска архивации 
ARCHIVE_QUERY_TIMEOUT = 30.0    # Таймаут для запросов архивации в секундах
ARCHIVE_DRY_RUN = False         # Режим тестирования: только логирование без реального удаления

# Storage Monitoring (Мониторинг хранилища)
STORAGE_MONITORING_ENABLED = True     # Включить мониторинг размеров таблиц БД
STORAGE_CHECK_INTERVAL = 3600         # Интервал проверки размеров в секундах
STORAGE_METRICS_LOG_INTERVAL = 86400  # Интервал логирования метрик в секундах 
STORAGE_ALERT_THRESHOLD_MB = 1000     # Порог предупреждения о размере таблицы в МБ
STORAGE_CRITICAL_THRESHOLD_MB = 5000  # Критический порог размера таблицы в МБ
STORAGE_GROWTH_WINDOW_DAYS = 7        # Окно анализа роста БД в днях для прогнозирования
STORAGE_GROWTH_ALERT_THRESHOLD = 1.5  # Порог алерта при прогнозе роста, 1.5 = рост на 50%



# ========================================
# Аналитика событий
# ========================================

# Настройки Event Replay Service
EVENT_REPLAY_MAX_EVENTS = 10000        # Максимум событий за один запрос
EVENT_REPLAY_BATCH_SIZE = 5000         # Размер батча для чтения
EVENT_REPLAY_DEFAULT_PERIOD_DAYS = 7   # Период по умолчанию
EVENT_REPLAY_CACHE_TTL = 300           # TTL для кэширования метрик (сек)

# Настройки Emotional Analysis
ANALYSIS_CACHE_TTL_DAYS = 30           # Время жизни кэша результатов анализа в днях (по умолчанию: 30)
ANALYSIS_CACHE_TABLE = "emotional_analysis_cache" # Название таблицы для кэширования результатов эмоционального анализа
ANALYSIS_MAX_EVENTS_PER_USER = 10000   # Макс количество эмоциональных событий для анализа одного пользователя
ANALYSIS_BATCH_SIZE = 500              # Размер батча при обработке больших объемов эмоциональных данных

# Clustering parameters
CLUSTERING_MIN_K = 3                   # Мин количество кластеров для K-means анализа
CLUSTERING_MAX_K = 10                  # Макс количество кластеров для K-means анализа
CLUSTERING_SILHOUETTE_THRESHOLD = 0.5  # Мин порог силуэтного коэффициента для валидации качества кластеризации

# Pattern detection
PATTERN_MIN_FREQUENCY = 3     # Мин частота повторения для определения устойчивого эмоционального паттерна
PATTERN_MIN_CONFIDENCE = 0.7  # Мин уровень уверенности для детекции паттернов от 0.0 до 1.0
TEMPORAL_WINDOW_MINUTES = 30  # Временное окно в минутах для группировки связанных эмоциональных событий

# Anomaly detection
ANOMALY_CONTAMINATION = 0.05     # Ожидаемая доля аномалий в данных от 0.0 до 1.0 
ANOMALY_Z_SCORE_THRESHOLD = 3.0  # Порог Z-score для детекции эмоциональных аномалий

# Cycle detection
CYCLE_MIN_PERIOD_DAYS = 3    # Мин период эмоционального цикла в днях
CYCLE_MAX_PERIOD_DAYS = 30   # Макс период эмоционального цикла в днях
CYCLE_MIN_AMPLITUDE = 0.2    # Мин амплитуда эмоциональных колебаний для детекции цикла от 0.0 до 1.0



# ========================================
# PostgreSQL Event Store
# ========================================

# PostgreSQL подключение
POSTGRES_DSN = os.getenv("POSTGRES_DSN", 
    "postgresql://chimera_user:password@localhost:5432/chimera_db")
POSTGRES_POOL_MIN_SIZE = 10        # Минимальный размер пула подключений
POSTGRES_POOL_MAX_SIZE = 20        # Максимальный размер пула подключений
POSTGRES_COMMAND_TIMEOUT = 60      # Таймаут команд в секундах
POSTGRES_CONNECT_TIMEOUT = 10      # Таймаут подключения в секундах
POSTGRES_RETRY_ATTEMPTS = 3        # Количество попыток переподключения
POSTGRES_RETRY_DELAY = 1.0         # Задержка между попытками в секундах

# Батчевая запись событий
EVENT_STORE_BATCH_SIZE = 100       # Размер батча для записи
EVENT_STORE_FLUSH_INTERVAL = 1.0   # Интервал автоматического flush в секундах
EVENT_STORE_MAX_BUFFER_SIZE = 1000 # Максимальный размер буфера записи

# Миграция данных
EVENT_STORE_MIGRATION_BATCH = 1000 # Размер батча при миграции
EVENT_STORE_MIGRATION_DELAY = 0.1  # Задержка между батчами миграции (сек)
EVENT_STORE_MIGRATION_VERIFY = True # Верифицировать данные после миграции

# Advisory lock настройки
USE_DOUBLE_KEY_ADVISORY_LOCK = True  # Использовать два ключа для уменьшения коллизий



# ========================================
# Redis
# ========================================

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_KEY_PREFIX = "chimera"    # Префикс для всех ключей
REDIS_POOL_MIN_SIZE = 5         # Минимальный размер пула подключений
REDIS_POOL_MAX_SIZE = 10        # Максимальный размер пула подключений
REDIS_CONNECT_TIMEOUT = 5       # Таймаут подключения в секундах
REDIS_RETRY_ATTEMPTS = 3        # Количество попыток подключения
REDIS_RETRY_DELAY = 1.0         # Задержка между попытками в секундах
REDIS_DAILY_LIMIT_TTL = 86400   # TTL для счетчиков лимитов (24 часа)



# ========================================
# DeepSeek & Telegram API
# ========================================

# DeepSeek API настройки
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_TIMEOUT = 30  # Сек
DEEPSEEK_MAX_RETRIES = 3

# Telegram Bot настройки
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_POLLING_TIMEOUT = 30 # Таймаут long polling в секундах (по умолчанию: 30)
TELEGRAM_TYPING_UPDATE_INTERVAL = 5  # Интервал обновления typing индикатора (по умолчанию: 5)
TELEGRAM_MAX_MESSAGE_LENGTH = 4096  # Макс длина сообщения Telegram (по умолчанию: 4096)
TELEGRAM_TYPING_CLEANUP_THRESHOLD = 100  # Порог для очистки завершенных typing задач
TELEGRAM_API_DEFAULT_TIMEOUT = 10        # Таймаут по умолчанию для API вызовов
TELEGRAM_MAX_TYPING_TASKS = 1000         # Макс количество одновременных typing задач

# Метрики и адаптивная стратегия
CACHE_HIT_LOG_INTERVAL = 10  # Частота логирования cache hit rate
MIN_CACHE_HIT_RATE = 0.5     # Мин приемлемый cache hit rate для адаптивной стратегии



# ========================================
# Валидация JSON-ответов
# ========================================

JSON_VALIDATION_ENABLED = True         # Включить валидацию структурированных ответов
JSON_VALIDATION_LOG_FAILURES = True    # Логировать неудачные валидации
JSON_VALIDATION_EVENT_BATCH_SIZE = 10  # Размер батча для событий валидации



# ========================================
# Pydantic модели для структурированных ответов
# ========================================

PYDANTIC_RESPONSE_MIN_LENGTH = 1      # Мин длина поля response
PYDANTIC_CONFIDENCE_MIN = 0.0         # Мин значение confidence/engagement_level
PYDANTIC_CONFIDENCE_MAX = 1.0         # Макс значение confidence/engagement_level
PYDANTIC_STRING_LIST_COERCE = True    # Преобразовывать элементы списков в строки
PYDANTIC_VALIDATION_STRICT = False    # Строгий режим валидации (без приведения типов)
PYDANTIC_MESSAGE_TYPE_MIN_LENGTH = 0  # Мин длина message_type (0 = может быть пустым)
PYDANTIC_EVENT_TYPE_MIN_LENGTH = 1    # Мин длина event_type (минимум 1 символ)
PYDANTIC_STREAM_ID_MIN_LENGTH = 0     # Мин длина stream_id (0 = может быть пустым)
PYDANTIC_MODE_HISTORY_MAX_SIZE = 10   # Макс размер истории режимов в UserSession
PYDANTIC_CACHE_METRICS_MAX_SIZE = 100 # Макс размер метрик кэша в UserSession



# ========================================
# Определение режимов общения
# ========================================

# Настройки истории режимов
MODE_HISTORY_SIZE = 5                  # Макс размер истории режимов
MODE_CONFIDENCE_THRESHOLD = 0.3        # Мин уверенность для режима по умолчанию
MODE_SCORE_NORMALIZATION_FACTOR = 1.5  # Делитель для нормализации уверенности

# Веса для контекстных паттернов
CONTEXTUAL_PATTERN_PHRASE_WEIGHT = 2.5          # Вес для точных фраз
CONTEXTUAL_PATTERN_DOMAIN_WEIGHT = 0.5          # Вес для доменных маркеров
CONTEXTUAL_PATTERN_CONTEXT_MULTIPLIER = 1.5     # Множитель для контекстных слов
CONTEXTUAL_PATTERN_SUPPRESSOR_MULTIPLIER = 0.0  # Множитель для подавителей

# Производительность определения режимов
MODE_DETECTION_CACHE_ENABLED = True  # Кэшировать результаты паттернов
MODE_DETECTION_MAX_TIME_MS = 5       # Макс время определения в миллисекундах
MODE_DETECTION_DEBUG_LOGGING = True  # Логировать детали определения



# ========================================
# Short-Term Memory (STM)
# ========================================

STM_CONTEXT_SIZE_FOR_GENERATION = 30  # Количество сообщений для контекста STM
STM_BUFFER_SIZE = 250                 # Количество сообщений для хранения
STM_CLEANUP_BATCH_SIZE = 10           # Количество записей для удаления за одну операцию
STM_QUERY_TIMEOUT = 5.0               # Таймаут запросов к БД в секундах (по умолчанию: 5.0)
STM_CONTEXT_FORMAT = "structured"     # Формат вывода контекста (по умолчанию: "structured")
STM_INCLUDE_METADATA = True           # Включать ли метаданные в контекст
STM_MESSAGE_MAX_LENGTH = 4000         # Макс длина одного сообщения перед обрезкой
STM_DEEPSEEK_ROLE_MAPPING = { # Маппинг ролей для DeepSeek API (по умолчанию: {"user": "user", "bot": "assistant"})
    "user": "user",
    "bot": "assistant"
}
STM_METRICS_ENABLED = True             # Включить сбор метрик
STM_METRICS_LOG_INTERVAL = 300         # Интервал логирования метрик в секундах 
STM_CONTEXT_REQUEST_TIMEOUT = 30       # Таймаут ожидания контекста из памяти в секундах



# ========================================
# Настройки PerceptionActor
# ========================================

# Параметры анализа эмоций в PerceptionActor
PERCEPTION_EMOTION_TIMEOUT = 5.0  # Таймаут для анализа одного текста (секунды)
PERCEPTION_THREAD_POOL_SIZE = 3   # Размер пула потоков для асинхронного анализа
PERCEPTION_LOG_ERRORS = True      # Логировать ли ошибки анализа эмоций



# ========================================
# Настройки TalkModelActor
# ========================================

# Параметры для актора режимов общения
PARTNER_MODEL_REQUEST_TIMEOUT = 0.3  # Макс время ожидания ответа от TalkModelActor (по умолчанию: 0.3 с)
PARTNER_PERSONA_CACHE_TTL = 3600  # Время жизни Partner Persona в Redis кэше (по умолчанию: 3600 с)
PARTNER_MODE_CONFIDENCE_THRESHOLD = 0.55  # Мин уверенность для использования Partner Persona (по умолчанию: 0.55)



# ========================================
# PERSONALITY ANALYSIS - анализ личности
# ========================================

# Параметры для периодического анализа стиля общения и черт личности
PERSONALITY_ANALYSIS_BATCH_SIZE = 10    # Частота запуска анализа в сообщениях (по умолчанию: 10)
PERSONALITY_ANALYSIS_HISTORY_LIMIT = 50 # Количество сообщений для анализа (по умолчанию: 50)
PERSONALITY_ANALYSIS_ENABLED = True # Включение/отключение функционала (по умолчанию: True)
PARTNER_PERSONA_CHANGE_THRESHOLD = 0.2 # Порог изменения стиля для создания новой версии (по умолчанию: 0.2)



# ========================================
# PERSONALITY ACTOR - Модуль личности
# ========================================

# Параметры для управления личности Химеры
RESONANCE_CLEANUP_HOUR = 5         # Час запуска очистки (5 утра UTC)
PERSONALITY_REQUEST_TIMEOUT = 1.0  # 1 секунда для PersonalityActor
RESONANCE_INACTIVITY_DAYS = 365    # Количество дней неактивности до деактивации профиля
RESONANCE_CLEANUP_ENABLED = True   # Автоматическая очистка неактивных профилей

PERSONALITY_MIN_TRAIT_VALUE = 0.0         # Минимальное значение черты личности
PERSONALITY_MAX_TRAIT_VALUE = 1.0         # Максимальное значение черты личности
PERSONALITY_CORE_TRAIT_MINIMUM = 0.4      # Минимум 40% для базовой личности
PERSONALITY_SESSION_CHANGE_LIMIT = 0.2    # Максимум 20% изменений за сессию
PERSONALITY_HISTORY_BUFFER_SIZE = 100     # Размер истории для анализа
PERSONALITY_PROFILE_CACHE_TTL = 86400     # TTL кэша профиля (24 часа)
PERSONALITY_MODIFIER_CACHE_TTL = 3600     # TTL кэша модификаторов (1 час)
PERSONALITY_QUERY_TIMEOUT = 5.0           # Таймаут запросов к БД (секунды)

PERSONALITY_MIN_TRAIT_VALUE = 0.0
PERSONALITY_MAX_TRAIT_VALUE = 1.0
PERSONALITY_PROFILE_CACHE_TTL_SECONDS = 300

PERSONALITY_RECOVERY_DAYS = 7              # Дней неактивности для начала восстановления
PERSONALITY_RECOVERY_RATE = 0.1            # Скорость восстановления (10% в день)
PERSONALITY_SESSION_CLEANUP_HOURS = 24     # Очищать старые сессии через 24 часа

# События PersonalityActor
PERSONALITY_DOMINANCE_CHANGE_THRESHOLD = 0.05  # Минимальное изменение для события
PERSONALITY_BASELINE_CONVERGENCE_THRESHOLD = 0.95  # Порог для события стабилизации
PERSONALITY_EVENT_BATCH_SIZE = 10  # Батч для аналитических событий  - 10 для продакшн, 3 - для отладки

RESONANCE_ENABLED = True  # Включение/отключение резонансной персонализации
RESONANCE_LEARNING_RATE = 0.05  # Скорость обучения резонанса (0.01 - 0.1)
RESONANCE_ADAPTATION_INTERVAL = 30  # Интервал адаптации (количество взаимодействий) - 30 для продакшн, 2 - для отладки
RESONANCE_MAX_DEVIATION = 0.3  # Максимальное отклонение от базового профиля (±30%)
RESONANCE_MAX_TOTAL_CHANGE = 0.2  # Максимальная сумма всех изменений (20%)
RESONANCE_CORE_TRAIT_FACTOR = 0.5  # Фактор защиты core черт (изменяются в 2 раза медленнее)
RESONANCE_NOISE_LEVEL = 0.05  # Уровень случайного шума для живости (5%) 
RESONANCE_MIN_ADAPTATION_INTERVAL_HOURS = 24 # Минимальное время между адаптациями резонанса (часы)



# ========================================
# SystemActor
# ========================================

SYSTEM_ACTOR_ENABLED = True           # Enable SystemActor
SYSTEM_METRICS_CACHE_TTL = 300        # Cache metrics for 5 minutes
SYSTEM_ALERT_COOLDOWN = 3600          # Don't repeat same alert for 1 hour
