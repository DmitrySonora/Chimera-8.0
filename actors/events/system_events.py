"""
События для SystemActor и мониторинга
"""
from datetime import datetime

from actors.events.base_event import BaseEvent
from pydantic import ConfigDict


class StorageAlertEvent(BaseEvent):
    """Событие о превышении порогов хранилища"""
    model_config = ConfigDict(frozen=True)
    
    @classmethod
    def create(cls, 
               table_name: str, 
               current_size_mb: float,
               threshold_mb: float, 
               alert_level: str) -> 'StorageAlertEvent':
        """
        Создать событие алерта о размере хранилища.
        
        Args:
            table_name: Имя таблицы или '_total'
            current_size_mb: Текущий размер в МБ
            threshold_mb: Превышенный порог в МБ
            alert_level: Уровень алерта ('warning' или 'critical')
        """
        return cls(
            stream_id="system_storage",
            event_type="StorageAlertEvent",
            data={
                "table_name": table_name,
                "current_size_mb": current_size_mb,
                "threshold_mb": threshold_mb,
                "alert_level": alert_level,
                "timestamp": datetime.now().isoformat()
            }
        )


class ArchivalCompletedEvent(BaseEvent):
    """Событие о завершении архивации"""
    model_config = ConfigDict(frozen=True)
    
    @classmethod
    def create(cls,
               archived_count: int,
               size_before: int,
               size_after: int,
               duration: float) -> 'ArchivalCompletedEvent':
        """
        Создать событие о завершении архивации.
        
        Args:
            archived_count: Количество заархивированных событий
            size_before: Размер таблицы events до архивации (байты)
            size_after: Размер таблицы events после архивации (байты)
            duration: Время выполнения архивации (секунды)
        """
        return cls(
            stream_id="system_archival",
            event_type="ArchivalCompletedEvent",
            data={
                "archived_count": archived_count,
                "size_before_mb": round(size_before / 1024 / 1024, 2),
                "size_after_mb": round(size_after / 1024 / 1024, 2),
                "size_saved_mb": round((size_before - size_after) / 1024 / 1024, 2),
                "duration_seconds": round(duration, 2),
                "timestamp": datetime.now().isoformat()
            }
        )