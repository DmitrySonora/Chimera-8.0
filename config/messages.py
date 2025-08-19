"""
Пользовательские сообщения для Telegram бота
"""

USER_MESSAGES = {
    # Приветствие и команда /start
    "welcome": """
Привет! Я — Химера, сама душа магического реализма!

✷ Это демо-доступ на {DAILY_MESSAGE_LIMIT} сообщений в день
✷ Когда лимит закончится, введите 🔑 пароль от подписки и общайтесь безлимитно
✷ Подписка и мануал здесь ☞ @aihimera

✨Теперь можете общаться — Химера ждёт!✨
""".strip(),

    # Ошибки и технические сообщения
    "api_error": """
Кажется, реальность дала сбой... Попробуй еще раз через минуту.
""".strip(),

    "typing_too_long": """
Все еще плету узоры из слов... Это займет чуть больше времени.
""".strip(),

    "rate_limit": """
Слишком много магии одновременно. Подожди немного, пока восстановлю силы.
""".strip(),

    "network_error": """
Связь между мирами прервалась. Пытаюсь восстановить...
""".strip(),

    # Системные команды
    "unknown_command": """
Эта команда мне чужда. Не влезай!
""".strip(),

    "message_too_long": """
Твое сообщение длинное, словно эпическая поэма. Попробуй выразить мысль короче
""".strip(),

    # JSON fallback
    "json_parse_error": """
Что-то закружилась голова, повтори снова?
""".strip(),
    
    # Лимиты и авторизация
    "limit_exceeded": """
🚫 Достигнут дневной лимит сообщений ({messages_today}/{limit})

✷ Это демо-доступ на {limit} сообщений в день
✷ Введите 🔑 пароль от подписки для безлимитного общения
✷ Подписка и мануал здесь ☞ @aihimera
""".strip(),

    # Авторизация
    "auth_prompt": """
🔑 Введите пароль от подписки:
""".strip(),

    "auth_success": """
👍 Подписка активирована до {expires_date}
❕ Осталось дней: {days_remaining}
""".strip(),

    "auth_error_invalid": """
❌ Неверный пароль. Попробуйте еще раз.
""".strip(),

    "auth_error_blocked": """
🚫 Слишком много попыток. Подождите {minutes} минут.
""".strip(),

    "auth_error_already_used": """
❌ Этот пароль уже использован другим пользователем.
""".strip(),

    "auth_error_temporary": """
⚠️ Временная ошибка. Попробуйте позже.
""".strip(),

    # Статус
    "status_authorized": """
👍 Подписка активна до: {expires_date}
❕ Осталось дней: {days_remaining}
""".strip(),

    "status_demo": """
❕ Демо-доступ: {messages_today}/{daily_limit} сообщений сегодня

Для безлимитного общения:
/auth - ввести пароль от подписки
""".strip(),

    # Logout
    "logout_confirm": """
❕ Вы вышли из аккаунта. Теперь действует демо-режим.
""".strip(),

    "logout_not_authorized": """
Вы не авторизованы.
""".strip(),

    "limit_warning": """
⚠️ Осталось сообщений: {messages_remaining}/{limit}
""".strip(),

    "subscription_expiring": """
⚠️ Подписка истекает через {days_remaining} дн.
""".strip(),

    "subscription_expiring_today": """
⚠️ Подписка истекает сегодня
""".strip(),
}




# Админские сообщения
ADMIN_MESSAGES = {
    "access_denied": """
❌ Это не для вас!
""".strip(),

    "unknown_command": """
❌ Неизвестная админская команда: {command}
""".strip(),

    "command_error": """
⚠️ Ошибка выполнения команды: {error}
""".strip(),

# Команда admin_add_password
    "password_usage": """
❌ Использование: /admin_add_password <пароль> <дни> <описание>
""".strip(),

    "password_invalid_days": """
❌ Недопустимый срок. Доступно: {durations}
""".strip(),

    "password_invalid_days_format": """
❌ Дни должны быть числом
""".strip(),

    "password_already_exists": """
❌ Пароль '{password}' уже существует
""".strip(),

    "password_created": """
👍 Пароль '{password}' добавлен на {days} дней.
❕ Описание: {description}
""".strip(),

    # Команда admin_list_passwords
    "passwords_header": """
ПАРОЛИ ({count} шт.):
------""".strip(),

    "password_item_active": """
{index}. 🟢 {password}
{description}
{days} дн, создан {created}, {status}""".strip(),

    "password_item_inactive": """
{index}. 🔴 {password}
{description}
{days} дн, создан {created}, {status}""".strip(),

    "passwords_empty": """
Паролей в системе нет
""".strip(),

    # Команда admin_deactivate_password
    "password_deactivate_usage": """
❌ Использование: /admin_deactivate_password <пароль>
""".strip(),

    "password_not_found": """
❌ Пароль '{password}' не найден
""".strip(),

    "password_already_inactive": """
❌ Пароль '{password}' уже деактивирован
""".strip(),

    "password_deactivated": """
✅ Пароль '{password}' деактивирован
""".strip(),

# Команда admin_stats
    "stats_header": """
СТАТИСТИКА СИСТЕМЫ
------""".strip(),

    "stats_passwords": """
🔑 ПАРОЛИ:
- Активных: {active}
- Деактивированных: {inactive}
- Всего использований: {used}""".strip(),

    "stats_users": """
👥 ПОЛЬЗОВАТЕЛИ:
- Всего: {total}
- Сейчас авторизовано: {authorized}
- Заблокировано: {blocked}""".strip(),

    "stats_by_duration": """
📅 ПО ДЛИТЕЛЬНОСТИ:
{durations}""".strip(),

    "stats_recent_activity": """
📈 АКТИВНОСТЬ (последние 24ч):
- Попыток авторизации: {attempts}
- Успешных: {success}
- Неудачных: {failed}""".strip(),

    # Команда admin_auth_log
    "auth_log_header": """
ЛОГИ АВТОРИЗАЦИИ{filter}
------""".strip(),

    "auth_log_entry_success": """
✅ {time} | {user_id}
Пароль: {password}
Авторизован на {days} дней""".strip(),

    "auth_log_entry_failed": """
❌ {time} | {user_id}
Пароль: {password}
Причина: {reason}""".strip(),

    "auth_log_entry_blocked": """
🚫 {time} | {user_id}
Заблокирован на {seconds} секунд""".strip(),

    "auth_log_empty": """
Логов авторизации нет{filter}
""".strip(),

    "auth_log_invalid_user": """
❌ Неверный формат user_id. Должны быть только цифры.
""".strip(),

# Команда admin_blocked_users
    "blocked_users_header": """
ЗАБЛОКИРОВАННЫЕ ({count} чел.):
------""".strip(),

    "blocked_user_entry": """
User {user_id}:
Осталось: {time_left}
Попыток: {attempts}
Последняя: {last_attempt}""".strip(),

    "blocked_users_empty": """
❕ Заблокированных пользователей нет
""".strip(),

    # Команда admin_unblock_user
    "unblock_usage": """
❌ Использование: /admin_unblock_user <user_id>
""".strip(),

    "unblock_invalid_user": """
❌ Неверный формат user_id. Должны быть только цифры.
""".strip(),

    "unblock_not_blocked": """
❌ Пользователь {user_id} не заблокирован
""".strip(),

    "unblock_success": """
❕ Пользователь {user_id} разблокирован
""".strip(),
}
