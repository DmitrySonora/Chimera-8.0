"""
AuthActor - актор для управления авторизацией и контроля доступа.
Обрабатывает проверку лимитов, авторизацию паролем и админские команды.

АРХИТЕКТУРНОЕ РЕШЕНИЕ: AuthActor использует прямой доступ к БД

Это инфраструктурный сервис, не влияющий на поведение Химеры.
Прямой доступ оправдан производительностью и изоляцией от core.
"""

from typing import Optional
import asyncio
from datetime import datetime, timezone, timedelta
from actors.auth.admin_handler import AuthAdminHandler
from actors.auth.helpers import AuthHelpers
from actors.base_actor import BaseActor
from actors.messages import ActorMessage, MESSAGE_TYPES
from database.connection import db_connection
from utils.monitoring import measure_latency
from utils.event_utils import EventVersionManager
from config.settings import DAILY_MESSAGE_LIMIT
from config.settings_auth import (
    AUTH_SCHEMA_CHECK_TIMEOUT,
    AUTH_CLEANUP_INTERVAL,
    AUTH_METRICS_LOG_INTERVAL
)
import hashlib
from database.redis_connection import redis_connection
from utils.circuit_breaker import CircuitBreaker


class AuthActor(BaseActor, AuthAdminHandler, AuthHelpers):
    """
    Актор для управления авторизацией и контроля доступа.
    
    Основные функции:
    - Проверка дневных лимитов для демо-пользователей
    - Авторизация через временные пароли
    - Управление подписками
    - Администрирование паролей
    - Anti-bruteforce защита
    """
    
    def __init__(self):
        """Инициализация с фиксированным actor_id и именем"""
        super().__init__("auth", "Auth")
        self._pool = None
        self._degraded_mode = False
        self._event_version_manager = EventVersionManager()
        self._redis_connection = None  # Redis подключение
        
        # Метрики для отслеживания работы
        self._metrics = {
            'initialized': False,
            'degraded_mode_entries': 0,
            'check_limit_count': 0,
            'auth_request_count': 0,
            'auth_success_count': 0,
            'auth_failed_count': 0,
            'blocked_users_count': 0,
            'admin_commands_count': 0,
            'db_errors': 0
        }
        
        # Задачи для фоновых операций
        self._cleanup_task = None
        self._metrics_task = None
        self._auth_circuit_breakers = {}  # user_id -> CircuitBreaker
        self._daily_reset_task = None
        
    async def initialize(self) -> None:
        """Инициализация ресурсов актора"""
        try:
            # Проверяем подключение к БД
            if not db_connection._is_connected:
                await db_connection.connect()
            
            # Получаем пул подключений
            self._pool = db_connection.get_pool()
            
            # Проверяем схему БД
            await self._verify_schema()
            
            # Запускаем фоновые задачи
            if AUTH_CLEANUP_INTERVAL > 0:
                self._cleanup_task = asyncio.create_task(self._cleanup_loop())
                
            if AUTH_METRICS_LOG_INTERVAL > 0:
                self._metrics_task = asyncio.create_task(self._metrics_loop())
                
            # Запускаем задачу ежедневного сброса
            from config.settings_auth import AUTH_DAILY_RESET_ENABLED
            if AUTH_DAILY_RESET_ENABLED:
                self._daily_reset_task = asyncio.create_task(self._daily_reset_loop())
                self.logger.info("Started daily reset task")
            
            # Подключаемся к Redis
            await redis_connection.connect()
            self._redis_connection = redis_connection
            
            self._metrics['initialized'] = True
            self.logger.info("AuthActor initialized successfully with Redis support")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize AuthActor: {str(e)}")
            self._degraded_mode = True
            self._metrics['degraded_mode_entries'] += 1
            self._increment_metric('db_errors')
            self.logger.warning("AuthActor entering degraded mode - will work without persistence")
    
    async def shutdown(self) -> None:
        """Освобождение ресурсов актора"""
        # Останавливаем фоновые задачи
        for task in [self._cleanup_task, self._metrics_task, self._daily_reset_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Отключаемся от Redis
        if self._redis_connection:
            await redis_connection.disconnect()
        
        # Логируем финальные метрики
        self.logger.info(
            f"AuthActor shutdown. Metrics: "
            f"Check limits: {self._metrics['check_limit_count']}, "
            f"Auth requests: {self._metrics['auth_request_count']}, "
            f"Auth success: {self._metrics['auth_success_count']}, "
            f"Auth failed: {self._metrics['auth_failed_count']}, "
            f"Blocked users: {self._metrics['blocked_users_count']}, "
            f"Admin commands: {self._metrics['admin_commands_count']}, "
            f"DB errors: {self._metrics['db_errors']}"
        )
    
    @measure_latency
    async def handle_message(self, message: ActorMessage) -> Optional[ActorMessage]:
        """Обработка входящих сообщений - роутер"""
        
        if message.message_type == MESSAGE_TYPES['CHECK_LIMIT']:
            self._metrics['check_limit_count'] += 1
            await self._handle_check_limit(message)
            
        elif message.message_type == MESSAGE_TYPES['AUTH_REQUEST']:
            self._metrics['auth_request_count'] += 1
            await self._process_auth_request(message)
            
        elif message.message_type == MESSAGE_TYPES['LOGOUT_REQUEST']:
            await self._handle_logout_request(message)
            
        elif message.message_type == MESSAGE_TYPES['ADMIN_COMMAND']:
            self._metrics['admin_commands_count'] += 1
            await self._handle_admin_command(message)
            
        else:
            self.logger.warning(
                f"Unknown message type received: {message.message_type}"
            )
        
        return None  # Fire-and-forget паттерн
    
    async def _process_auth_request(self, message: ActorMessage) -> None:
        """Обработка запроса авторизации"""
        user_id = message.payload.get('user_id')
        password = message.payload.get('password')
        chat_id = message.payload.get('chat_id')
        
        if not user_id or not password:
            self.logger.warning("AUTH_REQUEST received without user_id or password")
            return
        
        self.logger.debug(f"Processing AUTH_REQUEST for user {user_id}")
        
        # Проверка Circuit Breaker
        if not await self._check_circuit_breaker_state(user_id, chat_id, message.sender_id):
            return
        
        # Проверка блокировки пользователя
        is_blocked, blocked_until = await self._check_user_blocked(user_id)
        if is_blocked:
            await self._send_auth_response(
                user_id=user_id,
                chat_id=chat_id,
                success=False,
                sender_id=message.sender_id,
                error_type='blocked',
                blocked_until=blocked_until
            )
            return
        
        # Проверка degraded mode
        if self._degraded_mode or not self._pool:
            await self._send_auth_response(
                user_id=user_id,
                chat_id=chat_id,
                success=False,
                sender_id=message.sender_id,
                error_type='temporary_error'
            )
            return
        
        try:
            # Хешируем пароль
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            # Ищем и проверяем пароль
            password_row = await self._find_and_validate_password(password, password_hash)
            
            if not password_row:
                await self._handle_invalid_password(user_id, password, chat_id, message.sender_id)
                return
            
            # Проверяем и привязываем пароль
            bind_success, expires_at = await self._bind_password_to_user(
                password, user_id, password_row
            )
            
            if not bind_success:
                await self._handle_password_already_used(user_id, password, chat_id, message.sender_id)
                return
            
            # Создаем или обновляем подписку
            await self._create_or_update_subscription(
                user_id, password, expires_at, password_row
            )
            
            # Логируем успешную попытку
            await self._log_successful_auth(user_id, password)
            
            # Создаем события
            await self._create_auth_events(user_id, password, expires_at, password_row)
            
            # Отправляем успешный ответ
            await self._send_auth_response(
                user_id=user_id,
                chat_id=chat_id,
                success=True,
                sender_id=message.sender_id,
                expires_at=expires_at,
                days_remaining=(expires_at - datetime.now(timezone.utc)).days,
                description=password_row['description']
            )
            
            # Обновляем метрики и сбрасываем Circuit Breaker
            self._metrics['auth_success_count'] += 1
            await self._reset_circuit_breaker(user_id)
            
            self.logger.info(
                f"User {user_id} successfully authorized until {expires_at.isoformat()}"
            )
            
        except Exception as e:
            self.logger.error(f"Error processing AUTH_REQUEST for user {user_id}: {str(e)}", exc_info=True)
            self._increment_metric('db_errors')
            
            await self._send_auth_response(
                user_id=user_id,
                chat_id=chat_id,
                success=False,
                sender_id=message.sender_id,
                error_type='temporary_error'
            )
    
    async def _check_circuit_breaker_state(self, user_id: str, chat_id: int, sender_id: str) -> bool:
        """Проверка состояния Circuit Breaker для пользователя"""
        from config.settings_auth import AUTH_CIRCUIT_BREAKER_ENABLED, AUTH_CIRCUIT_BREAKER_TIMEOUT
        
        if not AUTH_CIRCUIT_BREAKER_ENABLED:
            return True
        
        try:
            if user_id not in self._auth_circuit_breakers:
                from config.settings_auth import AUTH_CIRCUIT_BREAKER_THRESHOLD
                self._auth_circuit_breakers[user_id] = CircuitBreaker(
                    name=f"auth_{user_id}",
                    failure_threshold=AUTH_CIRCUIT_BREAKER_THRESHOLD,
                    recovery_timeout=AUTH_CIRCUIT_BREAKER_TIMEOUT,
                    expected_exception=Exception
                )
            
            cb = self._auth_circuit_breakers[user_id]
            if cb.state.value == "open":
                self.logger.warning(f"Circuit breaker OPEN for user {user_id}, rejecting auth")
                
                # Создаем событие брутфорса
                from actors.events import BruteforceDetectedEvent
                bruteforce_event = BruteforceDetectedEvent.create(
                    user_id=user_id,
                    attempts_count=cb._failure_count,
                    action_taken="circuit_breaker_rejection"
                )
                await self._event_version_manager.append_event(bruteforce_event, self.get_actor_system())
                
                await self._send_auth_response(
                    user_id=user_id,
                    chat_id=chat_id,
                    success=False,
                    sender_id=sender_id,
                    error_type='blocked',
                    blocked_until=datetime.now(timezone.utc) + timedelta(seconds=AUTH_CIRCUIT_BREAKER_TIMEOUT)
                )
                return False
                
        except Exception as e:
            self.logger.error(f"Circuit breaker check error: {str(e)}")
        
        return True
    
    async def _reset_circuit_breaker(self, user_id: str) -> None:
        """Сбросить Circuit Breaker после успешной авторизации"""
        if user_id in self._auth_circuit_breakers:
            self._auth_circuit_breakers[user_id].reset()
            self.logger.debug(f"Reset circuit breaker for user {user_id}")
    
    async def _find_and_validate_password(self, password: str, password_hash: str) -> Optional[dict]:
        """Найти пароль в БД и проверить его валидность"""
        password_query = """
            SELECT password_hash, duration_days, description, used_by, expires_at
            FROM passwords
            WHERE password = $1 AND is_active = TRUE
        """
        
        password_row = await self._pool.fetchrow(password_query, password)
        
        if not password_row:
            self.logger.debug("Password not found")
            return None
        
        if password_row['password_hash'] != password_hash:
            self.logger.debug("Invalid password hash")
            return None
        
        return password_row
    
    async def _bind_password_to_user(self, password: str, user_id: str, password_row: dict) -> tuple[bool, datetime]:
        """Привязать пароль к пользователю"""
        # Повторная авторизация тем же паролем
        if password_row['used_by'] == user_id:
            self.logger.debug(f"Re-authentication with same password for user {user_id}")
            
            # Получаем существующий expires_at
            auth_query = "SELECT expires_at FROM authorized_users WHERE user_id = $1"
            auth_row = await self._pool.fetchrow(auth_query, user_id)
            
            if auth_row:
                expires_at = auth_row['expires_at'].replace(tzinfo=timezone.utc)
            else:
                expires_at = datetime.now(timezone.utc) + timedelta(days=password_row['duration_days'])
            
            return True, expires_at
        
        # Первое использование или попытка использовать чужой пароль
        expires_at = datetime.now(timezone.utc) + timedelta(days=password_row['duration_days'])
        
        bind_result = await self._pool.fetchval(
            "SELECT bind_password_to_user($1, $2, $3) as success",
            password,
            user_id,
            expires_at
        )
        
        if not bind_result:
            self.logger.debug("Password already used by another user")
            return False, None
        
        self.logger.debug(f"Password bound to user {user_id}")
        return True, expires_at
    
    async def _create_or_update_subscription(self, user_id: str, password: str, 
                                           expires_at: datetime, password_row: dict) -> None:
        """Создать или обновить подписку пользователя"""
        if password_row['used_by'] != user_id:
            # Новый пароль - создаем или обновляем подписку
            await self._pool.execute(
                """
                INSERT INTO authorized_users (user_id, password_used, expires_at, authorized_at, description)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP, $4)
                ON CONFLICT (user_id) DO UPDATE
                SET password_used = $2, 
                    expires_at = $3,
                    updated_at = CURRENT_TIMESTAMP
                """,
                user_id,
                password,
                expires_at,
                password_row['description']
            )
        else:
            # Повторная авторизация - создаем запись если её нет (после logout)
            await self._pool.execute(
                """
                INSERT INTO authorized_users (user_id, password_used, expires_at, authorized_at, description)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP, $4)
                ON CONFLICT (user_id) DO UPDATE
                SET updated_at = CURRENT_TIMESTAMP
                """,
                user_id,
                password,
                expires_at,
                password_row['description']
            )
    
    async def _log_successful_auth(self, user_id: str, password: str) -> None:
        """Логировать успешную попытку авторизации"""
        await self._pool.execute(
            """
            INSERT INTO auth_attempts (user_id, password_attempt, success, timestamp)
            VALUES ($1, $2, TRUE, CURRENT_TIMESTAMP)
            """,
            user_id, password
        )
        self.logger.debug(f"Auth attempt logged for user {user_id}")
    
    async def _create_auth_events(self, user_id: str, password: str, 
                                expires_at: datetime, password_row: dict) -> None:
        """Создать события успешной авторизации"""
        from actors.events.auth_events import AuthSuccessEvent, PasswordUsedEvent
        
        # Событие успешной авторизации
        success_event = AuthSuccessEvent.create(
            user_id=user_id,
            password=password,
            expires_at=expires_at,
            description=password_row['description']
        )
        await self._event_version_manager.append_event(success_event, self.get_actor_system())
        
        # Событие использования пароля (только при первом использовании)
        if password_row['used_by'] is None:
            used_event = PasswordUsedEvent.create(
                password=password,
                used_by=user_id,
                expires_at=expires_at
            )
            await self._event_version_manager.append_event(used_event, self.get_actor_system())
    
    async def _handle_invalid_password(self, user_id: str, password: str, 
                                     chat_id: int, sender_id: str) -> None:
        """Обработать случай неверного пароля"""
        # Логируем неудачную попытку
        await self._pool.execute(
            """
            INSERT INTO auth_attempts (user_id, password_attempt, success, error_reason, timestamp)
            VALUES ($1, $2, FALSE, 'invalid', CURRENT_TIMESTAMP)
            """,
            user_id, password
        )
        
        # Проверяем количество попыток
        from config.settings_auth import AUTH_MAX_ATTEMPTS
        failed_count = await self._increment_failed_attempts(user_id)
        if failed_count >= AUTH_MAX_ATTEMPTS:
            await self._block_user(user_id, failed_count)
        
        self._metrics['auth_failed_count'] += 1
        
        await self._send_auth_response(
            user_id=user_id,
            chat_id=chat_id,
            success=False,
            sender_id=sender_id,
            error_type='invalid_password'
        )
    
    async def _handle_password_already_used(self, user_id: str, password: str,
                                          chat_id: int, sender_id: str) -> None:
        """Обработать случай уже использованного пароля"""
        # Логируем неудачную попытку
        await self._pool.execute(
            """
            INSERT INTO auth_attempts (user_id, password_attempt, success, error_reason, timestamp)
            VALUES ($1, $2, FALSE, 'already_used', CURRENT_TIMESTAMP)
            """,
            user_id, password
        )
        
        # НЕ увеличиваем счетчик попыток для already_used
        self._metrics['auth_failed_count'] += 1
        
        await self._send_auth_response(
            user_id=user_id,
            chat_id=chat_id,
            success=False,
            sender_id=sender_id,
            error_type='already_used'
        )
    
    async def _send_auth_response(self, user_id: str, chat_id: int, success: bool,
                                sender_id: str, error_type: Optional[str] = None,
                                expires_at: Optional[datetime] = None,
                                days_remaining: Optional[int] = None,
                                description: Optional[str] = None,
                                blocked_until: Optional[datetime] = None) -> None:
        """Отправить унифицированный AUTH_RESPONSE"""
        payload = {
            'user_id': user_id,
            'chat_id': chat_id,
            'success': success
        }
        
        if not success:
            payload['error'] = error_type or 'unknown'
            if blocked_until:
                payload['blocked_until'] = blocked_until.isoformat()
        else:
            payload['expires_at'] = expires_at.isoformat()
            payload['days_remaining'] = days_remaining
            payload['description'] = description
        
        response = ActorMessage.create(
            sender_id=self.actor_id,
            message_type=MESSAGE_TYPES['AUTH_RESPONSE'],
            payload=payload
        )
        
        if self.get_actor_system() and sender_id:
            await self.get_actor_system().send_message(sender_id, response)
    
    async def _handle_logout_request(self, message: ActorMessage) -> None:
        """Обработка запроса на выход"""
        user_id = message.payload.get('user_id')
        chat_id = message.payload.get('chat_id')
        
        if not user_id:
            self.logger.warning("LOGOUT_REQUEST without user_id")
            return
        
        try:
            success = False
            
            if self._pool:
                # Проверяем наличие активной подписки
                check_query = """
                    SELECT EXISTS(
                        SELECT 1 FROM authorized_users 
                        WHERE user_id = $1 AND expires_at > CURRENT_TIMESTAMP
                    )
                """
                is_authorized = await self._pool.fetchval(check_query, user_id)
                
                if is_authorized:
                    # Удаляем запись
                    delete_query = "DELETE FROM authorized_users WHERE user_id = $1"
                    await self._pool.execute(delete_query, user_id)
                    
                    # Создаем событие
                    from actors.events import BaseEvent
                    logout_event = BaseEvent.create(
                        stream_id=f"auth_{user_id}",
                        event_type="LogoutEvent",
                        data={
                            "user_id": user_id,
                            "timestamp": datetime.now().isoformat()
                        }
                    )
                    await self._event_version_manager.append_event(logout_event, self.get_actor_system())
                    
                    success = True
                    self.logger.info(f"User {user_id} logged out successfully")
                else:
                    self.logger.debug(f"User {user_id} was not authorized")
                    
        except Exception as e:
            self.logger.error(f"Error processing LOGOUT_REQUEST: {str(e)}")
            self._increment_metric('db_errors')
            success = False
        
        # Отправляем ответ
        response = ActorMessage.create(
            sender_id=self.actor_id,
            message_type=MESSAGE_TYPES['LOGOUT_RESPONSE'],
            payload={
                'user_id': user_id,
                'chat_id': chat_id,
                'success': success
            }
        )
        
        if self.get_actor_system() and message.sender_id:
            await self.get_actor_system().send_message(message.sender_id, response)
    
    async def _handle_check_limit(self, message: ActorMessage) -> None:
        """Обработка запроса на проверку лимитов пользователя"""
        # Извлекаем user_id
        user_id = message.payload.get('user_id')
        if not user_id:
            self.logger.warning("CHECK_LIMIT received without user_id")
            return
        
        self.logger.debug(f"Checking limit for user {user_id}")
        
        # Извлекаем дополнительные данные из запроса
        chat_id = message.payload.get('chat_id')
        is_status_check = message.payload.get('is_status_check', False)
        
        # Значения по умолчанию для демо-пользователя
        response_payload = {
            'user_id': user_id,
            'chat_id': chat_id,
            'is_status_check': is_status_check,
            'is_auth_check': message.payload.get('is_auth_check', False),  # Передаем флаг обратно
            'unlimited': False,
            'messages_today': 0,  # Временно всегда 0
            'limit': DAILY_MESSAGE_LIMIT,
            'expires_at': None,
        }
        
        # Проверяем в БД только если не в degraded mode
        if not self._degraded_mode and self._pool:
            try:
                # Запрос к БД
                query = """
                    SELECT expires_at, password_used 
                    FROM authorized_users 
                    WHERE user_id = $1
                """
                
                row = await self._pool.fetchrow(query, user_id)
                
                if row:
                    expires_at = row['expires_at']
                    # Проверяем, не истекла ли подписка
                    if expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc):
                        # Активная подписка
                        response_payload = {
                            'user_id': user_id,
                            'chat_id': chat_id,
                            'is_status_check': is_status_check,
                            'unlimited': True,
                            'messages_today': 0,  # Временно всегда 0
                            'limit': None,
                            'expires_at': expires_at.isoformat(),
                        }
                        
                        # Проверяем приближение истечения подписки
                        time_remaining = expires_at.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
                        days_remaining = int(time_remaining.total_seconds() / 86400)
                        
                        if days_remaining in [7, 3, 1, 0] and days_remaining >= 0:
                            response_payload['subscription_expiring'] = True
                            response_payload['days_remaining'] = days_remaining
                        
                        self.logger.info(
                            f"User {user_id} has active subscription until {expires_at.isoformat()}"
                        )
                    else:
                        # Подписка истекла
                        self.logger.debug(f"User {user_id} subscription expired at {expires_at.isoformat()}")
                else:
                    # Пользователь не найден
                    self.logger.debug(f"User {user_id} using demo access")
                    
            except Exception as e:
                self.logger.error(f"Database error checking limit for user {user_id}: {str(e)}", exc_info=True)
                self._increment_metric('db_errors')
                # При ошибке БД используем демо-лимит (fail-open)
        
        # Для демо-пользователей проверяем счетчики Redis
        if not response_payload['unlimited']:
            messages_today = await self._get_daily_message_count(user_id)
            if messages_today is None:
                # Redis недоступен - блокируем демо-доступ (fail-closed)
                self.logger.error(f"Redis unavailable, blocking demo user {user_id}")
                messages_today = DAILY_MESSAGE_LIMIT  # Устанавливаем как будто лимит исчерпан
            
            # Обновляем payload
            response_payload['messages_today'] = messages_today
            
            # Если это не просто проверка статуса - увеличиваем счетчик
            if not is_status_check and messages_today < response_payload['limit']:
                new_count = await self._increment_daily_message_count(user_id)
                if new_count is not None:
                    response_payload['messages_today'] = new_count
                else:
                    # Redis недоступен - показываем что лимит исчерпан
                    response_payload['messages_today'] = DAILY_MESSAGE_LIMIT
            
            self.logger.debug(f"Demo user {user_id}: {response_payload['messages_today']}/{response_payload['limit']} messages today")
            
            # Для демо-пользователей проверяем приближение к лимиту
            if not response_payload['unlimited']:
                messages_remaining = response_payload['limit'] - response_payload['messages_today']
                if messages_remaining <= 3 and messages_remaining > 0:
                    response_payload['approaching_limit'] = True
                    response_payload['messages_remaining'] = messages_remaining
            
            # Для авторизованных проверяем истечение подписки
            if response_payload['unlimited'] and response_payload.get('expires_at'):
                expires_dt = datetime.fromisoformat(response_payload['expires_at'].replace('Z', '+00:00'))
                time_remaining = expires_dt - datetime.now(timezone.utc)
                days_remaining = int(time_remaining.total_seconds() / 86400)
                
                if days_remaining in [7, 3, 1, 0] and days_remaining >= 0:
                    response_payload['subscription_expiring'] = True
                    response_payload['days_remaining'] = days_remaining
        
        # Добавляем request_id в payload
        response_payload['request_id'] = message.payload.get('request_id')
        
        # Отправляем ответ
        if self.get_actor_system() and message.sender_id:
            response = ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES['LIMIT_RESPONSE'],
                payload=response_payload
            )
            await self.get_actor_system().send_message(message.sender_id, response)
            self.logger.debug(f"Sent LIMIT_RESPONSE to {message.sender_id} for user {user_id}")
    
    async def _verify_schema(self) -> None:
        """Проверка существования таблиц БД"""
        try:
            if self._pool is None:
                raise RuntimeError("Database pool not initialized")
            
            # Проверяем существование всех таблиц авторизации
            required_tables = ['passwords', 'authorized_users', 'auth_attempts', 'blocked_users']
            
            query = """
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = ANY($1)
            """
            
            rows = await self._pool.fetch(
                query, 
                required_tables,
                timeout=AUTH_SCHEMA_CHECK_TIMEOUT
            )
            
            existing_tables = {row['table_name'] for row in rows}
            missing_tables = set(required_tables) - existing_tables
            
            if missing_tables:
                raise RuntimeError(
                    f"Required auth tables missing: {', '.join(missing_tables)}. "
                    f"Please run migration 003_create_auth_tables.sql"
                )
            
            self.logger.debug("Auth schema verification completed successfully")
            
        except Exception as e:
            self.logger.error(f"Schema verification failed: {str(e)}")
            raise
    
    async def _cleanup_loop(self) -> None:
        """Периодическая очистка старых данных"""
        while self.is_running:
            try:
                await asyncio.sleep(AUTH_CLEANUP_INTERVAL)
                
                # Очистка старых попыток авторизации
                # TODO: реализация в подэтапе 5.1.3
                
                self.logger.debug("Auth cleanup completed")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in cleanup loop: {str(e)}")
    
    async def _metrics_loop(self) -> None:
        """Периодическое логирование метрик"""
        while self.is_running:
            try:
                await asyncio.sleep(AUTH_METRICS_LOG_INTERVAL)
                
                if self._metrics['check_limit_count'] > 0 or self._metrics['auth_request_count'] > 0:
                    self.logger.info(
                        f"AuthActor metrics - "
                        f"Limits checked: {self._metrics['check_limit_count']}, "
                        f"Auth requests: {self._metrics['auth_request_count']}, "
                        f"Success rate: {self._calculate_success_rate():.1%}, "
                        f"Degraded mode: {self._degraded_mode}"
                    )
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in metrics loop: {str(e)}")
    
    async def _daily_reset_loop(self) -> None:
        """Периодический сброс дневных счетчиков"""
        from config.settings_auth import AUTH_DAILY_RESET_HOUR
        
        while self.is_running:
            try:
                # Вычисляем время до следующего сброса
                now = datetime.now()
                next_reset = now.replace(hour=AUTH_DAILY_RESET_HOUR, minute=0, second=0, microsecond=0)
                
                # Если время уже прошло сегодня, планируем на завтра
                if next_reset <= now:
                    next_reset += timedelta(days=1)
                
                # Вычисляем задержку в секундах
                delay = (next_reset - now).total_seconds()
                
                self.logger.info(
                    f"Next daily reset scheduled at {next_reset.isoformat()}, "
                    f"waiting {delay:.0f} seconds"
                )
                
                # Ждем до времени сброса
                await asyncio.sleep(delay)
                
                # Выполняем сброс
                await self._reset_daily_counters()
                
                # Небольшая задержка чтобы не зациклиться
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in daily reset loop: {str(e)}")
                # При ошибке ждем час и пробуем снова
                await asyncio.sleep(3600)
    
    # Вспомогательные методы
    def _increment_metric(self, metric_name: str, value: int = 1) -> None:
        """Инкремент метрики"""
        if metric_name in self._metrics:
            self._metrics[metric_name] += value
    
    def _calculate_success_rate(self) -> float:
        """Вычисление процента успешных авторизаций"""
        total = self._metrics['auth_request_count']
        if total == 0:
            return 0.0
        return self._metrics['auth_success_count'] / total
        
    async def _handle_admin_command(self, message: ActorMessage) -> None:
        """Обработка админских команд"""
        command = message.payload.get('command', '')
        args = message.payload.get('args', [])
        user_id = message.payload.get('user_id')
        chat_id = message.payload.get('chat_id')
        
        self.logger.info(f"Processing admin command '{command}' from user {user_id}")
        
        # В degraded mode не обрабатываем админские команды
        if self._degraded_mode or not self._pool:
            response_text = "⚠️ Система авторизации временно недоступна"
        else:
            # Базовый роутинг команд (будет расширен в следующих частях)
            if command == 'admin_add_password':
                response_text = await self._admin_add_password(args, user_id)
            elif command == 'admin_list_passwords':
                response_text = await self._admin_list_passwords(args)
            elif command == 'admin_deactivate_password':
                response_text = await self._admin_deactivate_password(args, user_id)
            elif command == 'admin_stats':
                response_text = await self._admin_stats()
            elif command == 'admin_auth_log':
                response_text = await self._admin_auth_log(args)
            elif command == 'admin_blocked_users':
                response_text = await self._admin_blocked_users()
            elif command == 'admin_unblock_user':
                response_text = await self._admin_unblock_user(args)
            else:
                from config.messages import ADMIN_MESSAGES
                response_text = ADMIN_MESSAGES["unknown_command"].format(command=command)
        
        # Отправляем ответ обратно в TelegramActor
        response = ActorMessage.create(
            sender_id=self.actor_id,
            message_type=MESSAGE_TYPES['ADMIN_RESPONSE'],
            payload={
                'chat_id': chat_id,
                'text': response_text
            }
        )
        
        if self.get_actor_system() and message.sender_id:
            await self.get_actor_system().send_message(message.sender_id, response)