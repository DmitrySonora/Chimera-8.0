"""
Mixin для управления очисткой старых воспоминаний и генерации summary
"""
from typing import Dict, List, Any
import asyncio
from datetime import datetime, timezone, timedelta
import time
from uuid import UUID

from config.settings_ltm import (
    LTM_RETENTION_DAYS,
    LTM_RETENTION_MIN_IMPORTANCE,
    LTM_RETENTION_CRITICAL_IMPORTANCE,
    LTM_RETENTION_MIN_ACCESS_COUNT,
    LTM_CLEANUP_BATCH_SIZE,
    LTM_CLEANUP_QUERY_TIMEOUT,
    LTM_CLEANUP_SCHEDULE_HOUR,
    LTM_CLEANUP_SCHEDULE_MINUTE,
    LTM_CLEANUP_DRY_RUN,
    LTM_SUMMARY_ENABLED,
    LTM_SUMMARY_PERIOD,
    LTM_SUMMARY_MIN_MEMORIES,
    LTM_SUMMARY_TOP_EMOTIONS,
    LTM_SUMMARY_TOP_TAGS,
    LTM_CLEANUP_INVALIDATE_CACHE,
    LTM_CLEANUP_INVALIDATE_PATTERNS,
    LTM_CLEANUP_EMIT_EVENTS
)


class LTMCleanupMixin:
    """
    Миксин для LTMActor, добавляющий функциональность автоматической
    очистки старых воспоминаний с генерацией summary.
    
    Предполагает наличие:
    - self._pool: asyncpg connection pool
    - self._degraded_mode: bool
    - self.logger: logging.Logger
    - self._event_version_manager: EventVersionManager
    - self._cache_delete_pattern: метод для инвалидации кэша
    - self._make_cache_key: метод для создания ключей кэша
    - self.get_actor_system: метод для получения actor system
    """
    
    async def cleanup_old_memories(self, scheduled: bool = False) -> Dict[str, Any]:
        """
        Основной метод очистки старых воспоминаний с генерацией summary.
        
        Args:
            scheduled: True если вызвано планировщиком, False если вручную
            
        Returns:
            Словарь с результатами: {"deleted": int, "summaries": int, "duration": float}
        """
        if self._pool is None or self._degraded_mode:
            self.logger.warning("Cannot run cleanup: pool not available or degraded mode")
            return {"deleted": 0, "summaries": 0, "duration": 0.0}
        
        start_time = time.time()
        
        # Генерируем событие начала cleanup
        if LTM_CLEANUP_EMIT_EVENTS:
            from actors.events.ltm_events import CleanupStartedEvent
            event = CleanupStartedEvent.create(
                dry_run=LTM_CLEANUP_DRY_RUN,
                scheduled=scheduled
            )
            await self._event_version_manager.append_event(
                event,
                self.get_actor_system()
            )
        
        try:
            # Находим кандидатов на удаление
            candidates = await self._find_cleanup_candidates()
            
            if not candidates:
                self.logger.info("No memories found for cleanup")
                return {"deleted": 0, "summaries": 0, "duration": time.time() - start_time}
            
            total_deleted = 0
            summaries_created = 0
            affected_users = set()
            
            # Обрабатываем каждый период
            for candidate in candidates:
                user_id = candidate['user_id']
                affected_users.add(user_id)
                
                # Создаем summary если достаточно воспоминаний
                if LTM_SUMMARY_ENABLED and candidate['memories_count'] >= LTM_SUMMARY_MIN_MEMORIES:
                    summary_created = await self._create_period_summary(
                        user_id=user_id,
                        period_start=candidate['period_start'],
                        period_end=candidate['period_end'],
                        memory_ids=candidate['memory_ids']
                    )
                    if summary_created:
                        summaries_created += 1
                
                # Удаляем воспоминания (или логируем в dry run)
                if LTM_CLEANUP_DRY_RUN:
                    self.logger.info(
                        f"DRY RUN: Would delete {candidate['memories_count']} memories "
                        f"for user {user_id} from period {candidate['period_start'].date()}"
                    )
                    total_deleted += candidate['memories_count']
                else:
                    deleted = await self._delete_memories_batch(candidate['memory_ids'])
                    total_deleted += deleted
            
            # Инвалидируем кэши затронутых пользователей
            if LTM_CLEANUP_INVALIDATE_CACHE and not LTM_CLEANUP_DRY_RUN:
                await self._invalidate_user_caches(list(affected_users))
            
            duration = time.time() - start_time
            
            # Генерируем событие завершения cleanup
            if LTM_CLEANUP_EMIT_EVENTS:
                from actors.events.ltm_events import CleanupCompletedEvent
                event = CleanupCompletedEvent.create(
                    deleted_count=total_deleted,
                    summaries_created=summaries_created,
                    duration_seconds=duration,
                    dry_run=LTM_CLEANUP_DRY_RUN
                )
                await self._event_version_manager.append_event(
                    event,
                    self.get_actor_system()
                )
            
            self.logger.info(
                f"Cleanup completed: deleted={total_deleted}, "
                f"summaries={summaries_created}, duration={duration:.2f}s"
            )
            
            return {
                "deleted": total_deleted,
                "summaries": summaries_created,
                "duration": duration
            }
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {str(e)}")
            return {"deleted": 0, "summaries": 0, "duration": time.time() - start_time}
    
    async def _find_cleanup_candidates(self) -> List[Dict[str, Any]]:
        """
        Найти воспоминания-кандидаты на удаление, сгруппированные по периодам.
        
        Returns:
            Список словарей с полями: user_id, period_start, period_end, memory_ids, memories_count
        """
        if self._pool is None:
            return []
        
        # SQL для поиска кандидатов с группировкой по периодам
        query = f"""
            WITH cleanup_candidates AS (
                SELECT 
                    memory_id,
                    user_id,
                    created_at,
                    importance_score,
                    accessed_count
                FROM ltm_memories
                WHERE 
                    -- Старше порога retention
                    created_at < CURRENT_TIMESTAMP - INTERVAL '{LTM_RETENTION_DAYS} days'
                    -- И важность ниже минимальной
                    AND importance_score < $1
                    -- И НЕ критически важные
                    AND importance_score < $2
                    -- И НЕ часто используемые
                    AND accessed_count < $3
            )
            SELECT 
                user_id,
                date_trunc($4, created_at) as period_start,
                date_trunc($4, created_at) + INTERVAL '1 {LTM_SUMMARY_PERIOD}' as period_end,
                array_agg(memory_id) as memory_ids,
                COUNT(*) as memories_count
            FROM cleanup_candidates
            GROUP BY user_id, date_trunc($4, created_at)
            ORDER BY user_id, period_start
        """
        
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    query,
                    LTM_RETENTION_MIN_IMPORTANCE,
                    LTM_RETENTION_CRITICAL_IMPORTANCE,
                    LTM_RETENTION_MIN_ACCESS_COUNT,
                    LTM_SUMMARY_PERIOD,
                    timeout=LTM_CLEANUP_QUERY_TIMEOUT
                )
                
                candidates = []
                for row in rows:
                    candidates.append({
                        'user_id': row['user_id'],
                        'period_start': row['period_start'],
                        'period_end': row['period_end'],
                        'memory_ids': row['memory_ids'],  # asyncpg возвращает list
                        'memories_count': row['memories_count']
                    })
                
                self.logger.debug(f"Found {len(candidates)} period candidates for cleanup")
                return candidates
                
        except Exception as e:
            self.logger.error(f"Error finding cleanup candidates: {str(e)}")
            return []
    
    async def _create_period_summary(
        self,
        user_id: str,
        period_start: datetime,
        period_end: datetime,
        memory_ids: List[UUID]
    ) -> bool:
        """
        Создать агрегированный summary для периода перед удалением.
        
        Args:
            user_id: ID пользователя
            period_start: Начало периода
            period_end: Конец периода
            memory_ids: Список ID воспоминаний для агрегации
            
        Returns:
            True если summary создан успешно
        """
        if self._pool is None or not memory_ids:
            return False
        
        # SQL для агрегации данных из воспоминаний
        aggregate_query = """
            SELECT 
                -- Агрегация эмоций (топ N)
                (
                    SELECT array_agg(emotion ORDER BY count DESC)
                    FROM (
                        SELECT unnest(dominant_emotions) as emotion, COUNT(*) as count
                        FROM ltm_memories
                        WHERE memory_id = ANY($1::uuid[])
                        GROUP BY emotion
                        ORDER BY count DESC
                        LIMIT $2
                    ) top_emotions
                ) as dominant_emotions,
                -- Агрегация тегов (топ N)
                (
                    SELECT array_agg(tag ORDER BY count DESC)
                    FROM (
                        SELECT unnest(semantic_tags) as tag, COUNT(*) as count
                        FROM ltm_memories
                        WHERE memory_id = ANY($1::uuid[])
                        GROUP BY tag
                        ORDER BY count DESC
                        LIMIT $3
                    ) top_tags
                ) as frequent_tags,
                -- Средняя важность
                AVG(importance_score) as avg_importance,
                -- Количество воспоминаний
                COUNT(*) as memories_count
            FROM ltm_memories
            WHERE memory_id = ANY($1::uuid[])
        """
        
        # SQL для вставки/обновления summary
        upsert_query = """
            INSERT INTO ltm_period_summaries (
                user_id, period_start, period_end,
                memories_count, dominant_emotions, frequent_tags, avg_importance
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7
            )
            ON CONFLICT (user_id, period_start, period_end) DO UPDATE SET
                memories_count = ltm_period_summaries.memories_count + EXCLUDED.memories_count,
                dominant_emotions = (
                    SELECT array_agg(DISTINCT emotion)
                    FROM (
                        SELECT unnest(ltm_period_summaries.dominant_emotions) as emotion
                        UNION
                        SELECT unnest(EXCLUDED.dominant_emotions) as emotion
                    ) combined
                    LIMIT $8
                ),
                frequent_tags = (
                    SELECT array_agg(DISTINCT tag)
                    FROM (
                        SELECT unnest(ltm_period_summaries.frequent_tags) as tag
                        UNION
                        SELECT unnest(EXCLUDED.frequent_tags) as tag
                    ) combined
                    LIMIT $9
                ),
                avg_importance = (
                    ltm_period_summaries.avg_importance * ltm_period_summaries.memories_count + 
                    EXCLUDED.avg_importance * EXCLUDED.memories_count
                ) / (ltm_period_summaries.memories_count + EXCLUDED.memories_count),
                updated_at = CURRENT_TIMESTAMP
            RETURNING summary_id
        """
        
        try:
            async with self._pool.acquire() as conn:
                # Получаем агрегированные данные
                aggregate_data = await conn.fetchrow(
                    aggregate_query,
                    memory_ids,
                    LTM_SUMMARY_TOP_EMOTIONS,
                    LTM_SUMMARY_TOP_TAGS,
                    timeout=LTM_CLEANUP_QUERY_TIMEOUT
                )
                
                if not aggregate_data or aggregate_data['memories_count'] == 0:
                    self.logger.warning(f"No data to aggregate for period {period_start}")
                    return False
                
                # Создаем или обновляем summary
                result = await conn.fetchrow(
                    upsert_query,
                    user_id,
                    period_start,
                    period_end,
                    aggregate_data['memories_count'],
                    aggregate_data['dominant_emotions'] or [],
                    aggregate_data['frequent_tags'] or [],
                    aggregate_data['avg_importance'] or 0.0,
                    LTM_SUMMARY_TOP_EMOTIONS,
                    LTM_SUMMARY_TOP_TAGS,
                    timeout=LTM_CLEANUP_QUERY_TIMEOUT
                )
                
                if result and LTM_CLEANUP_EMIT_EVENTS:
                    from actors.events.ltm_events import SummaryCreatedEvent
                    event = SummaryCreatedEvent.create(
                        user_id=user_id,
                        period_start=period_start,
                        period_end=period_end,
                        memories_count=aggregate_data['memories_count']
                    )
                    await self._event_version_manager.append_event(
                        event,
                        self.get_actor_system()
                    )
                
                self.logger.info(
                    f"Created summary for user {user_id}, period {period_start.date()} "
                    f"with {aggregate_data['memories_count']} memories"
                )
                return True
                
        except Exception as e:
            self.logger.error(f"Error creating period summary: {str(e)}")
            return False
    
    async def _delete_memories_batch(self, memory_ids: List[UUID]) -> int:
        """
        Удалить воспоминания батчами для избежания долгих блокировок.
        
        Args:
            memory_ids: Список ID воспоминаний для удаления
            
        Returns:
            Количество удаленных записей
        """
        if self._pool is None or not memory_ids:
            return 0
        
        total_deleted = 0
        
        # Разбиваем на батчи
        for i in range(0, len(memory_ids), LTM_CLEANUP_BATCH_SIZE):
            batch = memory_ids[i:i + LTM_CLEANUP_BATCH_SIZE]
            
            delete_query = """
                DELETE FROM ltm_memories
                WHERE memory_id = ANY($1::uuid[])
            """
            
            try:
                async with self._pool.acquire() as conn:
                    result = await conn.execute(
                        delete_query,
                        batch,
                        timeout=LTM_CLEANUP_QUERY_TIMEOUT
                    )
                    # Извлекаем количество удаленных строк из результата
                    deleted_count = int(result.split()[-1]) if result else 0
                    total_deleted += deleted_count
                    
                    self.logger.debug(f"Deleted batch of {deleted_count} memories")
                    
            except Exception as e:
                self.logger.error(f"Error deleting memory batch: {str(e)}")
                # Продолжаем с следующим батчем
                continue
        
        return total_deleted
    
    async def _invalidate_user_caches(self, user_ids: List[str]) -> None:
        """
        Инвалидировать кэши новизны для затронутых пользователей.
        
        Args:
            user_ids: Список ID пользователей
        """
        if not user_ids:
            return
        
        total_invalidated = 0
        
        for user_id in user_ids:
            for pattern_template in LTM_CLEANUP_INVALIDATE_PATTERNS:
                # Заменяем * на user_id для создания паттерна
                if '*' in pattern_template:
                    # Создаем паттерн с user_id
                    pattern = self._make_cache_key(
                        pattern_template.replace('novelty:', '').replace(':*', ''),
                        user_id,
                        '*'
                    )
                else:
                    pattern = self._make_cache_key(pattern_template, user_id)
                
                deleted = await self._cache_delete_pattern(pattern)
                total_invalidated += deleted
                
                if deleted > 0:
                    self.logger.debug(
                        f"Invalidated {deleted} cache entries for pattern {pattern}"
                    )
        
        if total_invalidated > 0:
            self.logger.info(
                f"Invalidated total {total_invalidated} cache entries "
                f"for {len(user_ids)} users after cleanup"
            )
    
    async def _schedule_cleanup(self) -> None:
        """
        Планировщик для автоматического запуска cleanup в заданное время.
        Бесконечный цикл с расчетом времени до следующего запуска.
        """
        while True:
            try:
                # Вычисляем время до следующего запуска
                now = datetime.now(timezone.utc)
                next_run = now.replace(
                    hour=LTM_CLEANUP_SCHEDULE_HOUR,
                    minute=LTM_CLEANUP_SCHEDULE_MINUTE,
                    second=0,
                    microsecond=0
                )
                
                # Если время уже прошло сегодня, планируем на завтра
                if next_run <= now:
                    next_run += timedelta(days=1)
                
                # Вычисляем задержку в секундах
                delay = (next_run - now).total_seconds()
                
                self.logger.info(
                    f"Next cleanup scheduled at {next_run.isoformat()}, "
                    f"waiting {delay:.0f} seconds"
                )
                
                # Ждем до времени запуска
                await asyncio.sleep(delay)
                
                # Запускаем cleanup
                self.logger.info("Starting scheduled cleanup")
                result = await self.cleanup_old_memories(scheduled=True)
                
                self.logger.info(
                    f"Scheduled cleanup completed: "
                    f"deleted={result['deleted']}, "
                    f"summaries={result['summaries']}"
                )
                
            except asyncio.CancelledError:
                # Graceful shutdown
                self.logger.info("Cleanup scheduler cancelled, stopping")
                break
                
            except Exception as e:
                self.logger.error(f"Error in cleanup scheduler: {str(e)}")
                # При ошибке ждем час и пробуем снова
                await asyncio.sleep(3600)