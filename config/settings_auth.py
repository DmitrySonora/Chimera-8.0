# ========================================
# AUTH ACTOR SETTINGS
# ========================================

AUTH_SCHEMA_CHECK_TIMEOUT = 5.0     # Таймаут проверки схемы в секундах
AUTH_CLEANUP_INTERVAL = 3600        # Интервал очистки старых данных (1 час)
AUTH_METRICS_LOG_INTERVAL = 300     # Интервал логирования метрик (5 минут)



# ========================================
# AUTHORIZATION SETTINGS
# ========================================

PASSWORD_DURATIONS = [30, 90, 180, 365]

# Anti-bruteforce защита
AUTH_MAX_ATTEMPTS = 5              # Количество попыток до блокировки
AUTH_BLOCK_DURATION = 900          # Длительность блокировки в секундах (15 минут)
AUTH_ATTEMPTS_WINDOW = 900         # Окно подсчета попыток в секундах (15 минут)

# Администраторы системы
ADMIN_USER_IDS = [502312936]       # Список telegram_id администраторов

# Таймауты и лимиты
AUTH_CHECK_TIMEOUT = 2.0           # Таймаут проверки авторизации в секундах
AUTH_FALLBACK_TO_DEMO = True       # Разрешить работу как демо при недоступности AuthActor
AUTH_PASSWORD_WAIT_TIMEOUT = 60  # Таймаут ожидания пароля в секундах

# Периодическая очистка лимитов
AUTH_DAILY_RESET_ENABLED = True      # Включить ежедневный сброс счетчиков
AUTH_DAILY_RESET_HOUR = 0            # Час сброса (0-23, по умолчанию полночь)

# Circuit Breaker для защиты от брутфорса
AUTH_CIRCUIT_BREAKER_ENABLED = True      # Включить Circuit Breaker для AUTH_REQUEST
AUTH_CIRCUIT_BREAKER_THRESHOLD = 3       # Количество ошибок для открытия
AUTH_CIRCUIT_BREAKER_TIMEOUT = 300       # Время восстановления в секундах (5 минут)