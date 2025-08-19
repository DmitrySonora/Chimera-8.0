"""
SystemActor - координатор системных задач и мониторинга.

АРХИТЕКТУРНАЯ ЗАМЕТКА (Этап 6.4, январь 2025):
=====================================================
Этот актор создан с минимальным функционалом как задел для фазы 9.

ТЕКУЩАЯ РЕАЛИЗАЦИЯ (6.4):
- Координация архивации событий через PostgresEventStore
- Сбор метрик размера БД через DBMonitoringService  
- Генерация алертов при превышении порогов хранилища
- Периодические задачи через паттерн из LTMCleanupMixin

РИСКИ ПРЕЖДЕВРЕМЕННОЙ АБСТРАКЦИИ:
- НЕ добавляйте сюда бизнес-логику - только системные задачи
- НЕ создавайте сложные зависимости - актор может быть переписан в фазе 9
- НЕ оптимизируйте преждевременно - дождитесь реальных метрик использования
- НЕ усложняйте интерфейс - сохраняйте простоту для будущего рефакторинга

ПЛАНЫ НА ФАЗУ 9 (Dev_Steps_FUTURE.md):
- Health checks всех акторов системы
- Анализ эволюции личности через Event Replay
- Автоматические оптимизации (cache TTL, batch sizes)
- Predictive scaling и capacity planning
- Координация всех maintenance задач

ПОЧЕМУ АКТОР, А НЕ СЕРВИС:
В фазе 9 потребуется message-driven координация между множеством 
акторов. Создаем основу сейчас, чтобы избежать большого рефакторинга.
Пока используем композицию сервисов для фактической работы.

ИНТЕГРАЦИЯ:
- DBMonitoringService - фактический сбор метрик (композиция)
- PostgresEventStore - выполнение архивации (через сообщения)
- EventVersionManager - аудит всех операций

ЕСЛИ ВЫ РАБОТАЕТЕ НАД ФАЗОЙ 9:
Проверьте, что текущий интерфейс все еще актуален.
Возможно, проще переписать с учетом накопленного опыта,
чем адаптировать этот минимальный прототип.

TODO (Фаза 9):
- [ ] Добавить health checks через PING/PONG к каждому актору
- [ ] Реализовать Event Replay для анализа эволюции
- [ ] Добавить предиктивную аналитику роста данных
- [ ] Интегрировать с PersonalityActor для метрик личности
"""

import asyncio
from typing import Optional, Dict, Any
from datetime import datetime

from actors.base_actor import BaseActor
from actors.messages import ActorMessage, MESSAGE_TYPES
from database.connection import db_connection
from utils.db_monitoring import DBMonitoringService
from config.settings import (
    STORAGE_CHECK_INTERVAL,
    SYSTEM_ALERT_COOLDOWN,
    STORAGE_MONITORING_ENABLED
)


class SystemActor(BaseActor):
    """
    Минимальный актор для системных задач:
    - Мониторинг размеров БД
    - Координация архивации событий
    - Генерация алертов о превышении порогов
    """
    
    def __init__(self, event_store=None):
        """
        Инициализация SystemActor.
        
        Args:
            event_store: Ссылка на PostgresEventStore для архивации
        """
        super().__init__("system_actor", "SystemActor")
        self.db_monitor: Optional[DBMonitoringService] = None
        self.event_store = event_store
        self._scheduler_task: Optional[asyncio.Task] = None
        self._last_alert_times: Dict[str, datetime] = {}
        
    async def initialize(self) -> None:
        """Инициализация ресурсов актора"""
        self.logger.info("Initializing SystemActor")
        
        # Создаем сервис мониторинга
        pool = db_connection.get_pool()
        if pool:
            self.db_monitor = DBMonitoringService(connection_pool=pool)
            self.logger.info("DBMonitoringService initialized")
        else:
            self.logger.warning("Database pool not available, monitoring disabled")
        
        # Запускаем периодический мониторинг
        if STORAGE_MONITORING_ENABLED and self.db_monitor:
            self._scheduler_task = asyncio.create_task(self._periodic_monitoring())
            self.logger.info("Periodic monitoring started")
    
    async def shutdown(self) -> None:
        """Освобождение ресурсов актора"""
        # Останавливаем периодический мониторинг
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        
        self.logger.info("SystemActor shutdown completed")
    
    async def handle_message(self, message: ActorMessage) -> Optional[ActorMessage]:
        """
        Обработка входящих сообщений.
        
        Поддерживаемые типы:
        - COLLECT_SYSTEM_METRICS: собрать текущие метрики
        - INITIATE_ARCHIVAL: запустить архивацию событий
        - CHECK_STORAGE_ALERTS: проверить пороги хранилища
        """
        if message.message_type == MESSAGE_TYPES.get('COLLECT_SYSTEM_METRICS'):
            return await self._handle_collect_metrics(message)
            
        elif message.message_type == MESSAGE_TYPES.get('INITIATE_ARCHIVAL'):
            return await self._handle_initiate_archival(message)
            
        elif message.message_type == MESSAGE_TYPES.get('CHECK_STORAGE_ALERTS'):
            return await self._handle_check_alerts(message)
        
        return None
    
    async def _handle_collect_metrics(self, message: ActorMessage) -> ActorMessage:
        """Собрать и вернуть текущие метрики системы"""
        if not self.db_monitor:
            return ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES.get('SYSTEM_METRICS_RESPONSE'),
                payload={'error': 'Monitoring service not available'}
            )
        
        try:
            # Собираем размеры таблиц
            table_sizes = await self.db_monitor.collect_table_sizes()
            
            # Получаем метрики Event Store если доступен
            event_store_metrics = {}
            if self.event_store:
                event_store_metrics = self.event_store.get_metrics()
            
            return ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES.get('SYSTEM_METRICS_RESPONSE'),
                payload={
                    'table_sizes': table_sizes,
                    'event_store_metrics': event_store_metrics,
                    'timestamp': datetime.now().isoformat()
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error collecting metrics: {str(e)}")
            return ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES.get('SYSTEM_METRICS_RESPONSE'),
                payload={'error': str(e)}
            )
    
    async def _handle_initiate_archival(self, message: ActorMessage) -> ActorMessage:
        """Запустить архивацию событий"""
        if not self.event_store:
            return ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES.get('SYSTEM_METRICS_RESPONSE'),
                payload={'error': 'Event store not available'}
            )
        
        try:
            # Запускаем архивацию
            result = await self.event_store.archive_old_events()
            
            # Генерируем событие о завершении архивации
            if result['archived_count'] > 0:
                await self._generate_archival_completed_event(result)
            
            return ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES.get('SYSTEM_METRICS_RESPONSE'),
                payload={
                    'archival_result': result,
                    'timestamp': datetime.now().isoformat()
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error during archival: {str(e)}")
            return ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES.get('SYSTEM_METRICS_RESPONSE'),
                payload={'error': str(e)}
            )
    
    async def _handle_check_alerts(self, message: ActorMessage) -> ActorMessage:
        """Проверить пороги хранилища и вернуть алерты"""
        if not self.db_monitor:
            return ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES.get('SYSTEM_METRICS_RESPONSE'),
                payload={'error': 'Monitoring service not available'}
            )
        
        try:
            # Собираем размеры
            table_sizes = await self.db_monitor.collect_table_sizes()
            
            # Проверяем пороги
            alerts = await self.db_monitor.check_thresholds(table_sizes)
            
            # Генерируем события для алертов с учетом cooldown
            for alert in alerts:
                await self._generate_storage_alert_if_needed(alert)
            
            return ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES.get('SYSTEM_METRICS_RESPONSE'),
                payload={
                    'alerts': alerts,
                    'table_sizes': table_sizes,
                    'timestamp': datetime.now().isoformat()
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error checking alerts: {str(e)}")
            return ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES.get('SYSTEM_METRICS_RESPONSE'),
                payload={'error': str(e)}
            )
    
    async def _periodic_monitoring(self) -> None:
        """
        Периодическая проверка размеров БД и генерация алертов.
        Запускается каждые STORAGE_CHECK_INTERVAL секунд.
        """
        while True:
            try:
                await asyncio.sleep(STORAGE_CHECK_INTERVAL)
                
                if not self.db_monitor:
                    continue
                
                # Собираем метрики
                table_sizes = await self.db_monitor.collect_table_sizes()
                
                # Проверяем пороги
                alerts = await self.db_monitor.check_thresholds(table_sizes)
                
                if alerts:
                    self.logger.warning(f"Storage alerts detected: {len(alerts)} issues")
                    
                    # Генерируем события для критических алертов
                    for alert in alerts:
                        await self._generate_storage_alert_if_needed(alert)
                
                # Логируем общий размер
                total_size = table_sizes.get('_total', {}).get('size_mb', 0)
                self.logger.debug(f"Total database size: {total_size:.2f} MB")
                
                # Раз в сутки запускаем очистку резонансных профилей
                from config.settings_personality import RESONANCE_CLEANUP_ENABLED, RESONANCE_CLEANUP_HOUR
                current_hour = datetime.now().hour
                if (RESONANCE_CLEANUP_ENABLED and 
                    current_hour == RESONANCE_CLEANUP_HOUR and
                    self.get_actor_system()):
                    # Отправляем только если прошло больше 23 часов с последней очистки
                    last_cleanup_key = 'last_resonance_cleanup'
                    now = datetime.now()
                    
                    if last_cleanup_key not in self._last_alert_times:
                        # Первый запуск
                        await self.get_actor_system().send_message(
                            'personality',
                            ActorMessage.create(
                                sender_id=self.actor_id,
                                message_type=MESSAGE_TYPES['CLEANUP_INACTIVE_RESONANCE']
                            )
                        )
                        self._last_alert_times[last_cleanup_key] = now
                        self.logger.info("Initiated resonance cleanup task")
                    else:
                        # Проверяем прошло ли 23 часа
                        hours_since = (now - self._last_alert_times[last_cleanup_key]).total_seconds() / 3600
                        if hours_since >= 23:
                            await self.get_actor_system().send_message(
                                'personality',
                                ActorMessage.create(
                                    sender_id=self.actor_id,
                                    message_type=MESSAGE_TYPES['CLEANUP_INACTIVE_RESONANCE']
                                )
                            )
                            self._last_alert_times[last_cleanup_key] = now
                            self.logger.info("Initiated daily resonance cleanup task")
                
            except asyncio.CancelledError:
                self.logger.info("Periodic monitoring cancelled")
                break
                
            except Exception as e:
                self.logger.error(f"Error in periodic monitoring: {str(e)}")
                # Продолжаем мониторинг несмотря на ошибки
                await asyncio.sleep(60)  # Короткая пауза при ошибке
    
    async def _generate_storage_alert_if_needed(self, alert: Dict[str, Any]) -> None:
        """
        Генерировать StorageAlertEvent с учетом cooldown.
        
        Args:
            alert: Словарь с данными алерта
        """
        # Формируем ключ для cooldown
        alert_key = f"{alert['table_name']}_{alert['level']}"
        
        # Проверяем cooldown
        now = datetime.now()
        last_alert_time = self._last_alert_times.get(alert_key)
        
        if last_alert_time:
            time_since_last = (now - last_alert_time).total_seconds()
            if time_since_last < SYSTEM_ALERT_COOLDOWN:
                # Еще не прошел cooldown
                return
        
        # Генерируем событие
        try:
            from actors.events.system_events import StorageAlertEvent
            from utils.event_utils import EventVersionManager
            
            event = StorageAlertEvent.create(
                table_name=alert['table_name'],
                current_size_mb=alert['current_size_mb'],
                threshold_mb=alert['threshold_mb'],
                alert_level=alert['level']
            )
            
            # Получаем EventVersionManager если есть ActorSystem
            if self.get_actor_system():
                event_manager = EventVersionManager()
                await event_manager.append_event(event, self.get_actor_system())
            
            # Обновляем время последнего алерта
            self._last_alert_times[alert_key] = now
            
            self.logger.warning(
                f"Storage alert generated: {alert['table_name']} "
                f"({alert['current_size_mb']:.2f} MB) exceeds "
                f"{alert['level']} threshold ({alert['threshold_mb']} MB)"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to generate storage alert event: {str(e)}")
    
    async def _generate_archival_completed_event(self, result: Dict[str, Any]) -> None:
        """
        Генерировать ArchivalCompletedEvent после успешной архивации.
        
        Args:
            result: Результат архивации
        """
        try:
            from actors.events.system_events import ArchivalCompletedEvent
            from utils.event_utils import EventVersionManager
            
            event = ArchivalCompletedEvent.create(
                archived_count=result['archived_count'],
                size_before=result['size_before'],
                size_after=result['size_after'],
                duration=result['duration']
            )
            
            # Получаем EventVersionManager если есть ActorSystem
            if self.get_actor_system():
                event_manager = EventVersionManager()
                await event_manager.append_event(event, self.get_actor_system())
            
            self.logger.info(
                f"Archival completed event generated: "
                f"{result['archived_count']} events archived"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to generate archival completed event: {str(e)}")