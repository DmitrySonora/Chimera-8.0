"""
Сервис мониторинга размеров таблиц БД
"""
from typing import Dict, List, Any, Optional
import asyncpg
from config.logging import get_logger
from config.settings import (
    STORAGE_ALERT_THRESHOLD_MB,
    STORAGE_CRITICAL_THRESHOLD_MB
)


class DBMonitoringService:
    """
    Сервис для мониторинга размеров таблиц БД.
    НЕ актор, обычный сервис.
    """
    
    # Таблицы для мониторинга
    TABLES_TO_MONITOR = [
        'events',
        'archived_events',
        'ltm_memories',
        'ltm_period_summaries',
        'ltm_user_profiles',
        'stm_buffer',
        'auth_passwords'
    ]
    
    def __init__(self, connection_pool: Optional[asyncpg.Pool] = None):
        """
        Инициализация сервиса.
        
        Args:
            connection_pool: Pool подключений к PostgreSQL
        """
        self.logger = get_logger("db_monitoring")
        self._pool = connection_pool
        
    def set_pool(self, pool: asyncpg.Pool) -> None:
        """Установить pool после создания"""
        self._pool = pool
        
    async def collect_table_sizes(self) -> Dict[str, Dict[str, Any]]:
        """
        Собрать размеры всех таблиц проекта.
        
        Returns:
            Словарь вида:
            {
                'events': {'size_bytes': 12345, 'size_mb': 0.01, 'row_count': 100},
                'ltm_memories': {...},
                ...
            }
        """
        if not self._pool:
            self.logger.warning("Connection pool not available")
            return {}
        
        results = {}
        
        for table_name in self.TABLES_TO_MONITOR:
            try:
                async with self._pool.acquire() as conn:
                    # Получаем размер таблицы (включая индексы)
                    size_query = """
                        SELECT pg_total_relation_size($1::regclass) as size_bytes
                    """
                    size_bytes = await conn.fetchval(size_query, table_name)
                    
                    # Получаем количество строк
                    count_query = f"SELECT COUNT(*) FROM {table_name}"
                    row_count = await conn.fetchval(count_query)
                    
                    if size_bytes is not None:
                        results[table_name] = {
                            'size_bytes': size_bytes,
                            'size_mb': round(size_bytes / 1024 / 1024, 2),
                            'row_count': row_count or 0
                        }
                    else:
                        # Таблица не существует
                        results[table_name] = {
                            'size_bytes': 0,
                            'size_mb': 0.0,
                            'row_count': 0
                        }
                        
            except Exception as e:
                # Таблица не существует или недоступна
                self.logger.debug(f"Cannot get size for {table_name}: {str(e)}")
                results[table_name] = {
                    'size_bytes': 0,
                    'size_mb': 0.0,
                    'row_count': 0
                }
        
        # Считаем общий размер
        total_size_mb = sum(t['size_mb'] for t in results.values())
        results['_total'] = {
            'size_bytes': int(total_size_mb * 1024 * 1024),
            'size_mb': round(total_size_mb, 2),
            'row_count': sum(t['row_count'] for t in results.values())
        }
        
        return results
    
    async def check_thresholds(self, sizes: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Проверить превышение порогов размеров.
        
        Args:
            sizes: Результат collect_table_sizes()
            
        Returns:
            Список алертов с полями: table_name, current_size_mb, threshold_mb, level
        """
        alerts = []
        
        for table_name, info in sizes.items():
            if table_name == '_total':
                continue
                
            size_mb = info['size_mb']
            
            # Проверяем критический порог
            if size_mb >= STORAGE_CRITICAL_THRESHOLD_MB:
                alerts.append({
                    'table_name': table_name,
                    'current_size_mb': size_mb,
                    'threshold_mb': STORAGE_CRITICAL_THRESHOLD_MB,
                    'level': 'critical'
                })
            # Проверяем warning порог
            elif size_mb >= STORAGE_ALERT_THRESHOLD_MB:
                alerts.append({
                    'table_name': table_name,
                    'current_size_mb': size_mb,
                    'threshold_mb': STORAGE_ALERT_THRESHOLD_MB,
                    'level': 'warning'
                })
        
        # Проверяем общий размер
        total_size_mb = sizes.get('_total', {}).get('size_mb', 0)
        
        if total_size_mb >= STORAGE_CRITICAL_THRESHOLD_MB:
            alerts.append({
                'table_name': '_total',
                'current_size_mb': total_size_mb,
                'threshold_mb': STORAGE_CRITICAL_THRESHOLD_MB,
                'level': 'critical'
            })
        elif total_size_mb >= STORAGE_ALERT_THRESHOLD_MB:
            alerts.append({
                'table_name': '_total',
                'current_size_mb': total_size_mb,
                'threshold_mb': STORAGE_ALERT_THRESHOLD_MB,
                'level': 'warning'
            })
        
        return alerts
    
    async def predict_growth(self, window_days: Optional[int] = None) -> Dict[str, float]:
        """
        Прогнозировать рост на основе истории.
        TODO (Phase 9): Implement with proper historical data storage
        
        Args:
            window_days: Окно для анализа (по умолчанию из настроек)
            
        Returns:
            Словарь с прогнозами роста по таблицам
        """
        # Заглушка для фазы 9
        # В будущем здесь будет:
        # 1. Чтение исторических данных из Event Store
        # 2. Линейная регрессия для каждой таблицы
        # 3. Прогноз на window_days вперед
        return {}