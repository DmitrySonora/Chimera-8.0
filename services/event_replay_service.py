"""
Сервис для воспроизведения и анализа исторических событий.
Работает с обеими таблицами: events и archived_events.
"""
import asyncio
import gzip
import base64
import json
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone

from actors.events.base_event import BaseEvent
from config.logging import get_logger
from config.settings import (
    EVENT_REPLAY_MAX_EVENTS,
    EVENT_REPLAY_DEFAULT_PERIOD_DAYS,
    POSTGRES_COMMAND_TIMEOUT
)
from utils.monitoring import measure_latency


class EventReplayService:
    """
    Сервис для анализа эволюции личности через исторические события.
    НЕ является актором - это аналитический сервис.
    """
    
    def __init__(self, db_connection):
        """
        Инициализация сервиса.
        
        Args:
            db_connection: Объект подключения к БД
        """
        self.db = db_connection
        self.logger = get_logger("event_replay_service")
        
        # Счетчики метрик
        self._total_replays = 0
        self._total_events_processed = 0
        self._decompression_errors = 0
    
    @measure_latency
    async def replay_user_events(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime,
        event_types: Optional[List[str]] = None
    ) -> List[BaseEvent]:
        """
        Воспроизвести события пользователя из обеих таблиц.
        
        Args:
            user_id: ID пользователя
            start_date: Начало периода
            end_date: Конец периода
            event_types: Фильтр по типам событий (опционально)
        
        Returns:
            Список событий в хронологическом порядке
        """
        self._total_replays += 1
        
        # Получаем события из обеих таблиц параллельно
        current_events_task = self._fetch_current_events(
            user_id, start_date, end_date, event_types
        )
        archived_events_task = self._fetch_archived_events(
            user_id, start_date, end_date, event_types
        )
        
        current_events, archived_events = await asyncio.gather(
            current_events_task,
            archived_events_task
        )
        
        # Объединяем и сортируем по timestamp
        all_events = current_events + archived_events
        all_events.sort(key=lambda e: e.timestamp)
        
        self._total_events_processed += len(all_events)
        
        self.logger.info(
            f"Replayed {len(all_events)} events for user {user_id}: "
            f"{len(current_events)} current, {len(archived_events)} archived"
        )
        
        return all_events[:EVENT_REPLAY_MAX_EVENTS]
    
    @measure_latency
    async def get_ltm_usage_stats(
        self,
        user_id: str,
        period: Tuple[datetime, datetime]
    ) -> Dict[str, Any]:
        """
        Получить статистику использования LTM.
        
        Args:
            user_id: ID пользователя
            period: Кортеж (start_date, end_date)
        
        Returns:
            Словарь с метриками использования LTM
        """
        start_date, end_date = period
        
        # Подсчет total_messages (UserMessageEvent)
        total_messages = await self._count_user_messages(user_id, start_date, end_date)
        
        # Подсчет LTM запросов (LTMSearchCompletedEvent)
        ltm_queries = await self._count_ltm_queries(user_id, start_date, end_date)
        
        # Подсчет сохранений в LTM (ImportanceCalculatedEvent где saved=True)
        saved_to_ltm = await self._count_saved_to_ltm(user_id, start_date, end_date)
        
        # Подсчет среднего количества воспоминаний на запрос
        avg_memories = await self._calculate_avg_memories_per_query(
            user_id, start_date, end_date
        )
        
        # Вычисляем проценты
        ltm_percentage = (ltm_queries / total_messages * 100) if total_messages > 0 else 0.0
        save_percentage = (saved_to_ltm / total_messages * 100) if total_messages > 0 else 0.0
        
        return {
            "total_messages": total_messages,
            "ltm_queries": ltm_queries,
            "ltm_percentage": ltm_percentage,
            "avg_memories_per_query": avg_memories,
            "saved_to_ltm": saved_to_ltm,
            "save_percentage": save_percentage
        }
    
    @measure_latency
    async def get_trigger_distribution(
        self,
        period: Optional[Tuple[datetime, datetime]] = None
    ) -> Dict[str, int]:
        """
        Получить распределение типов триггеров LTM.
        
        Args:
            period: Период анализа (опционально, по умолчанию последние 7 дней)
        
        Returns:
            Словарь {trigger_type: count}
        """
        if period is None:
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=EVENT_REPLAY_DEFAULT_PERIOD_DAYS)
            period = (start_date, end_date)
        else:
            start_date, end_date = period
        
        # Запрос для текущих событий
        query_current = """
            SELECT 
                data->>'trigger_reason' as trigger_reason,
                COUNT(*) as count
            FROM events
            WHERE event_type = 'ImportanceCalculatedEvent'
              AND (data->>'saved')::boolean = true
              AND timestamp BETWEEN $1 AND $2
              AND archived = FALSE
            GROUP BY data->>'trigger_reason'
        """
        
        # Для архивных событий упрощенный запрос
        query_archived = """
            SELECT compressed_data
            FROM archived_events
            WHERE event_type = 'ImportanceCalculatedEvent'
              AND original_timestamp BETWEEN $1 AND $2
        """
        
        # Выполняем запросы параллельно с разными соединениями
        pool = self.db.get_pool()
        
        async def fetch_current():
            async with pool.acquire() as conn:
                return await conn.fetch(
                    query_current, start_date, end_date,
                    timeout=POSTGRES_COMMAND_TIMEOUT
                )
        
        async def fetch_archived():
            async with pool.acquire() as conn:
                return await conn.fetch(
                    query_archived, start_date, end_date,
                    timeout=POSTGRES_COMMAND_TIMEOUT
                )
        
        current_rows, archived_rows = await asyncio.gather(
            fetch_current(),
            fetch_archived()
        )
        
        # Обрабатываем результаты
        distribution = {}
        
        # Текущие события
        for row in current_rows:
            trigger = row['trigger_reason'] or 'unknown'
            distribution[trigger] = distribution.get(trigger, 0) + row['count']
        
        # Архивные события - декомпрессируем и анализируем
        for row in archived_rows:
            data = self._decompress_archived_event(row['compressed_data'])
            if data.get('saved') is True:
                trigger = data.get('trigger_reason', 'unknown')
                distribution[trigger] = distribution.get(trigger, 0) + 1
        
        self.logger.info(
            f"Trigger distribution: {len(distribution)} unique triggers"
        )
        
        return distribution
    
    def _decompress_archived_event(self, compressed_data: str) -> dict:
        """
        Декомпрессировать архивное событие.
        
        Args:
            compressed_data: Сжатые данные (base64 encoded gzip)
        
        Returns:
            Словарь с данными события
        """
        try:
            # base64 decode
            compressed_bytes = base64.b64decode(compressed_data)
            
            # gzip decompress
            decompressed_bytes = gzip.decompress(compressed_bytes)
            
            # Декодируем и парсим JSON
            json_str = decompressed_bytes.decode('utf-8')
            
            # Пытаемся распарсить как JSON
            if json_str.startswith('{') or json_str.startswith('['):
                data = json.loads(json_str)
            else:
                data = {"raw_data": json_str}
            
            return data if isinstance(data, dict) else {"data": data}
            
        except Exception as e:
            self._decompression_errors += 1
            self.logger.error(f"Failed to decompress: {str(e)}")
            return {}
    
    async def _fetch_current_events(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime,
        event_types: Optional[List[str]] = None
    ) -> List[BaseEvent]:
        """Получить события из основной таблицы events."""
        
        if event_types:
            query = """
                SELECT event_id, stream_id, event_type, data, 
                       timestamp, version, correlation_id
                FROM events
                WHERE stream_id LIKE '%' || $1 || '%'
                  AND timestamp BETWEEN $2 AND $3
                  AND event_type = ANY($4)
                  AND archived = FALSE
                ORDER BY timestamp ASC
                LIMIT $5
            """
            rows = await self.db.fetch(
                query, user_id, start_date, end_date, event_types,
                EVENT_REPLAY_MAX_EVENTS,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
        else:
            query = """
                SELECT event_id, stream_id, event_type, data,
                       timestamp, version, correlation_id
                FROM events
                WHERE stream_id LIKE '%' || $1 || '%'
                  AND timestamp BETWEEN $2 AND $3
                  AND archived = FALSE
                ORDER BY timestamp ASC
                LIMIT $4
            """
            rows = await self.db.fetch(
                query, user_id, start_date, end_date,
                EVENT_REPLAY_MAX_EVENTS,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
        
        events = []
        for row in rows:
            # Проверяем тип data
            data = row['data']
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    data = {}
            elif not isinstance(data, dict):
                data = {}
            
            event = BaseEvent(
                event_id=str(row['event_id']),
                stream_id=row['stream_id'],
                event_type=row['event_type'],
                data=data,
                timestamp=row['timestamp'],
                version=row['version'],
                correlation_id=str(row['correlation_id']) if row['correlation_id'] else None
            )
            events.append(event)
        
        return events
    
    async def _fetch_archived_events(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime,
        event_types: Optional[List[str]] = None
    ) -> List[BaseEvent]:
        """Получить события из архивной таблицы с декомпрессией."""
        
        # Для архивных событий используем простой fetch без курсоров
        if event_types:
            query = """
                SELECT original_event_id, stream_id, event_type,
                       compressed_data, original_timestamp
                FROM archived_events
                WHERE stream_id LIKE '%' || $1 || '%'
                  AND original_timestamp BETWEEN $2 AND $3
                  AND event_type = ANY($4)
                ORDER BY original_timestamp ASC
                LIMIT $5
            """
            rows = await self.db.fetch(
                query, user_id, start_date, end_date, event_types,
                EVENT_REPLAY_MAX_EVENTS,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
        else:
            query = """
                SELECT original_event_id, stream_id, event_type,
                       compressed_data, original_timestamp
                FROM archived_events
                WHERE stream_id LIKE '%' || $1 || '%'
                  AND original_timestamp BETWEEN $2 AND $3
                ORDER BY original_timestamp ASC
                LIMIT $4
            """
            rows = await self.db.fetch(
                query, user_id, start_date, end_date,
                EVENT_REPLAY_MAX_EVENTS,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
        
        events = []
        for row in rows:
            # Декомпрессируем данные
            decompressed_data = self._decompress_archived_event(row['compressed_data'])
            
            if decompressed_data:
                # Проверяем тип данных
                if isinstance(decompressed_data, str):
                    try:
                        decompressed_data = json.loads(decompressed_data)
                    except json.JSONDecodeError:
                        decompressed_data = {}
                
                if not isinstance(decompressed_data, dict):
                    decompressed_data = {}
                
                event = BaseEvent(
                    event_id=str(row['original_event_id']),
                    stream_id=row['stream_id'],
                    event_type=row['event_type'],
                    data=decompressed_data,
                    timestamp=row['original_timestamp'],
                    version=0,
                    correlation_id=None
                )
                events.append(event)
        
        return events
    
    async def _count_user_messages(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> int:
        """Подсчитать количество сообщений пользователя."""
        
        query_current = """
            SELECT COUNT(*) as count
            FROM events
            WHERE stream_id = 'user_session_' || $1
              AND event_type = 'UserMessageEvent'
              AND timestamp BETWEEN $2 AND $3
              AND archived = FALSE
        """
        
        query_archived = """
            SELECT COUNT(*) as count
            FROM archived_events
            WHERE stream_id = 'user_session_' || $1
              AND event_type = 'UserMessageEvent'
              AND original_timestamp BETWEEN $2 AND $3
        """
        
        current_count = await self.db.fetchval(
            query_current, user_id, start_date, end_date,
            timeout=POSTGRES_COMMAND_TIMEOUT
        ) or 0
        
        archived_count = await self.db.fetchval(
            query_archived, user_id, start_date, end_date,
            timeout=POSTGRES_COMMAND_TIMEOUT
        ) or 0
        
        return current_count + archived_count
    
    async def _count_ltm_queries(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> int:
        """Подсчитать количество запросов к LTM."""
        
        query_current = """
            SELECT COUNT(*) as count
            FROM events
            WHERE stream_id = 'ltm_' || $1
              AND event_type = 'LTMSearchCompletedEvent'
              AND timestamp BETWEEN $2 AND $3
              AND archived = FALSE
        """
        
        query_archived = """
            SELECT COUNT(*) as count
            FROM archived_events
            WHERE stream_id = 'ltm_' || $1
              AND event_type = 'LTMSearchCompletedEvent'
              AND original_timestamp BETWEEN $2 AND $3
        """
        
        current_count = await self.db.fetchval(
            query_current, user_id, start_date, end_date,
            timeout=POSTGRES_COMMAND_TIMEOUT
        ) or 0
        
        archived_count = await self.db.fetchval(
            query_archived, user_id, start_date, end_date,
            timeout=POSTGRES_COMMAND_TIMEOUT
        ) or 0
        
        return current_count + archived_count
    
    async def _count_saved_to_ltm(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> int:
        """Подсчитать количество сохранений в LTM."""
        
        query_current = """
            SELECT COUNT(*) as count
            FROM events
            WHERE stream_id = 'ltm_' || $1
              AND event_type = 'ImportanceCalculatedEvent'
              AND (data->>'saved')::boolean = true
              AND timestamp BETWEEN $2 AND $3
              AND archived = FALSE
        """
        
        # Для архивных используем простой подход
        query_archived = """
            SELECT compressed_data
            FROM archived_events
            WHERE stream_id = 'ltm_' || $1
              AND event_type = 'ImportanceCalculatedEvent'
              AND original_timestamp BETWEEN $2 AND $3
        """
        
        current_count = await self.db.fetchval(
            query_current, user_id, start_date, end_date,
            timeout=POSTGRES_COMMAND_TIMEOUT
        ) or 0
        
        # Декомпрессируем и проверяем saved
        archived_rows = await self.db.fetch(
            query_archived, user_id, start_date, end_date,
            timeout=POSTGRES_COMMAND_TIMEOUT
        )
        
        archived_count = 0
        for row in archived_rows:
            data = self._decompress_archived_event(row['compressed_data'])
            if data.get('saved') is True:
                archived_count += 1
        
        return current_count + archived_count
    
    async def _calculate_avg_memories_per_query(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> float:
        """Вычислить среднее количество воспоминаний на запрос."""
        
        query_current = """
            SELECT (data->>'results_count')::int as results_count
            FROM events
            WHERE stream_id = 'ltm_' || $1
              AND event_type = 'LTMSearchCompletedEvent'
              AND timestamp BETWEEN $2 AND $3
              AND archived = FALSE
        """
        
        current_rows = await self.db.fetch(
            query_current, user_id, start_date, end_date,
            timeout=POSTGRES_COMMAND_TIMEOUT
        )
        
        query_archived = """
            SELECT compressed_data
            FROM archived_events
            WHERE stream_id = 'ltm_' || $1
              AND event_type = 'LTMSearchCompletedEvent'
              AND original_timestamp BETWEEN $2 AND $3
        """
        
        archived_rows = await self.db.fetch(
            query_archived, user_id, start_date, end_date,
            timeout=POSTGRES_COMMAND_TIMEOUT
        )
        
        # Собираем все results_count
        all_results = []
        
        for row in current_rows:
            if row['results_count'] is not None:
                all_results.append(row['results_count'])
        
        for row in archived_rows:
            data = self._decompress_archived_event(row['compressed_data'])
            if data.get('results_count') is not None:
                all_results.append(data['results_count'])
        
        # Вычисляем среднее
        if all_results:
            return sum(all_results) / len(all_results)
        return 0.0
    
    async def _create_decompress_function(self, conn) -> None:
        """
        Заглушка для функции декомпрессии.
        В реальности декомпрессия происходит в Python коде.
        """
        pass
    
    def get_metrics(self) -> Dict[str, int]:
        """
        Получить метрики работы сервиса.
        
        Returns:
            Словарь с метриками
        """
        return {
            "total_replays": self._total_replays,
            "total_events_processed": self._total_events_processed,
            "decompression_errors": self._decompression_errors
        }