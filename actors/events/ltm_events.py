"""
События для LTMActor и долговременной памяти
"""
from typing import Optional, Dict, Any
from datetime import datetime
from actors.events.base_event import BaseEvent

class LTMSavedEvent(BaseEvent):
    """Событие успешного сохранения в долговременную память"""
    
    @classmethod
    def create(cls,
               memory_id: str,
               user_id: str,
               memory_type: str,
               importance_score: float,
               trigger_reason: str,
               emotional_intensity: float,
               correlation_id: Optional[str] = None) -> 'LTMSavedEvent':
        """
        Создать событие сохранения в LTM
        
        Args:
            memory_id: UUID сохраненного воспоминания
            user_id: ID пользователя
            memory_type: Тип памяти (self_related/world_model/user_related)
            importance_score: Оценка важности
            trigger_reason: Причина сохранения
            emotional_intensity: Эмоциональная интенсивность
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"ltm_{user_id}",
            event_type="LTMSavedEvent",
            data={
                "memory_id": memory_id,
                "user_id": user_id,
                "memory_type": memory_type,
                "importance_score": importance_score,
                "trigger_reason": trigger_reason,
                "emotional_intensity": emotional_intensity
            },
            version=0,  # Версия устанавливается EventVersionManager
            correlation_id=correlation_id
        )


class LTMErrorEvent(BaseEvent):
    """Событие ошибки операции с долговременной памятью"""
    
    @classmethod
    def create(cls,
               user_id: str,
               operation: str,
               error_type: str,
               error_message: str,
               correlation_id: Optional[str] = None) -> 'LTMErrorEvent':
        """
        Создать событие ошибки LTM
        
        Args:
            user_id: ID пользователя
            operation: Тип операции (save/get/delete)
            error_type: Тип ошибки
            error_message: Сообщение об ошибке
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"ltm_{user_id}",
            event_type="LTMErrorEvent",
            data={
                "user_id": user_id,
                "operation": operation,
                "error_type": error_type,
                "error_message": error_message
            },
            version=0,
            correlation_id=correlation_id
        )


class LTMDegradedModeEvent(BaseEvent):
    """Событие перехода LTMActor в degraded mode"""
    
    @classmethod
    def create(cls,
               reason: str,
               details: str,
               correlation_id: Optional[str] = None) -> 'LTMDegradedModeEvent':
        """
        Создать событие перехода в degraded mode
        
        Args:
            reason: Причина перехода
            details: Детали ошибки
            correlation_id: ID корреляции
        """
        return cls(
            stream_id="ltm_system",
            event_type="LTMDegradedModeEvent",
            data={
                "reason": reason,
                "details": details
            },
            version=0,
            correlation_id=correlation_id
        )
class LTMSearchCompletedEvent(BaseEvent):
    """Событие успешного завершения поиска в долговременной памяти"""
    
    @classmethod
    def create(cls,
               user_id: str,
               search_type: str,
               results_count: int,
               search_time_ms: float,
               query_params: Dict[str, Any],
               correlation_id: Optional[str] = None) -> 'LTMSearchCompletedEvent':
        """
        Создать событие завершения поиска
        
        Args:
            user_id: ID пользователя
            search_type: Тип поиска (vector/tags/recent/etc)
            results_count: Количество найденных результатов
            search_time_ms: Время выполнения поиска в миллисекундах
            query_params: Параметры запроса
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"ltm_{user_id}",
            event_type="LTMSearchCompletedEvent",
            data={
                "user_id": user_id,
                "search_type": search_type,
                "results_count": results_count,
                "search_time_ms": search_time_ms,
                "query_params": query_params
            },
            version=0,
            correlation_id=correlation_id
        )


class LTMSearchErrorEvent(BaseEvent):
    """Событие ошибки поиска в долговременной памяти"""
    
    @classmethod
    def create(cls,
               user_id: str,
               search_type: str,
               error_type: str,
               error_message: str,
               correlation_id: Optional[str] = None) -> 'LTMSearchErrorEvent':
        """
        Создать событие ошибки поиска
        
        Args:
            user_id: ID пользователя
            search_type: Тип поиска
            error_type: Тип ошибки
            error_message: Сообщение об ошибке
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"ltm_{user_id}",
            event_type="LTMSearchErrorEvent",
            data={
                "user_id": user_id,
                "search_type": search_type,
                "error_type": error_type,
                "error_message": error_message
            },
            version=0,
            correlation_id=correlation_id
        )


class EmotionalPatternDetectedEvent(BaseEvent):
    """Событие обнаружения эмоционального паттерна"""
    
    @classmethod
    def create(cls,
               user_id: str,
               pattern_type: str,  # 'association', 'trajectory', 'recurring'
               pattern_data: Dict[str, Any],
               confidence: float,
               correlation_id: Optional[str] = None) -> 'EmotionalPatternDetectedEvent':
        """
        Создать событие обнаружения паттерна
        
        Args:
            user_id: ID пользователя
            pattern_type: Тип паттерна
            pattern_data: Данные паттерна
            confidence: Уверенность в паттерне (0.0-1.0)
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"ltm_{user_id}",
            event_type="EmotionalPatternDetectedEvent",
            data={
                "user_id": user_id,
                "pattern_type": pattern_type,
                "pattern_data": pattern_data,
                "confidence": confidence
            },
            version=0,
            correlation_id=correlation_id
        )


class AnalyticsGeneratedEvent(BaseEvent):
    """Событие успешной генерации аналитики"""
    
    @classmethod
    def create(cls,
               user_id: str,
               analytics_type: str,
               data: Dict[str, Any],
               correlation_id: Optional[str] = None) -> 'AnalyticsGeneratedEvent':
        """
        Создать событие генерации аналитики
        
        Args:
            user_id: ID пользователя
            analytics_type: Тип аналитики
            data: Данные аналитики
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"ltm_{user_id}",
            event_type="AnalyticsGeneratedEvent",
            data={
                "user_id": user_id,
                "analytics_type": analytics_type,
                "data": data
            },
            version=0,
            correlation_id=correlation_id
        )


class ImportanceCalculatedEvent(BaseEvent):
    """Событие оценки важности для сохранения в LTM"""
    
    @classmethod
    def create(cls,
               user_id: str,
               importance_score: float,
               saved: bool,
               threshold: float,
               trigger_reason: Optional[str] = None,
               correlation_id: Optional[str] = None) -> 'ImportanceCalculatedEvent':
        """
        Создать событие оценки важности
        
        Args:
            user_id: ID пользователя
            importance_score: Оценка важности (0.0-1.0)
            saved: Было ли сохранено в LTM
            threshold: Использованный порог
            trigger_reason: Причина сохранения (если saved=True)
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"ltm_{user_id}",
            event_type="ImportanceCalculatedEvent",
            data={
                "user_id": user_id,
                "importance_score": importance_score,
                "saved": saved,
                "threshold": threshold,
                "trigger_reason": trigger_reason
            },
            version=0,
            correlation_id=correlation_id
        )


class NoveltyCalculatedEvent(BaseEvent):
    """Событие расчета новизны для потенциального воспоминания"""
    
    @classmethod
    def create(cls,
               user_id: str,
               novelty_score: float,
               factor_details: Dict[str, float],
               saved: bool,
               correlation_id: Optional[str] = None) -> 'NoveltyCalculatedEvent':
        """
        Создать событие расчета новизны
        
        Args:
            user_id: ID пользователя
            novelty_score: Итоговая оценка новизны (0.0-1.0)
            factor_details: Детализация по факторам
            saved: Было ли сохранено в LTM
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"ltm_{user_id}",
            event_type="NoveltyCalculatedEvent",
            data={
                "user_id": user_id,
                "novelty_score": novelty_score,
                "factor_details": factor_details,
                "saved": saved
            },
            version=0,
            correlation_id=correlation_id
        )


class CalibrationProgressEvent(BaseEvent):
    """Событие прогресса калибровки системы оценки новизны"""
    
    @classmethod
    def create(cls,
               user_id: str,
               messages_processed: int,
               calibration_complete: bool,
               correlation_id: Optional[str] = None) -> 'CalibrationProgressEvent':
        """
        Создать событие прогресса калибровки
        
        Args:
            user_id: ID пользователя
            messages_processed: Количество обработанных сообщений
            calibration_complete: Завершена ли калибровка
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"ltm_{user_id}",
            event_type="CalibrationProgressEvent",
            data={
                "user_id": user_id,
                "messages_processed": messages_processed,
                "calibration_complete": calibration_complete
            },
            version=0,
            correlation_id=correlation_id
        )


class MemoryRejectedEvent(BaseEvent):
    """Событие отклонения воспоминания с высокой новизны"""
    
    @classmethod
    def create(cls,
               user_id: str,
               novelty_score: float,
               threshold: float,
               reason: str,
               correlation_id: Optional[str] = None) -> 'MemoryRejectedEvent':
        """
        Создать событие отклонения воспоминания
        
        Args:
            user_id: ID пользователя
            novelty_score: Оценка новизны
            threshold: Использованный порог
            reason: Причина отклонения
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"ltm_{user_id}",
            event_type="MemoryRejectedEvent",
            data={
                "user_id": user_id,
                "novelty_score": novelty_score,
                "threshold": threshold,
                "reason": reason
            },
            version=0,
            correlation_id=correlation_id
        )


class NoveltyCacheHitEvent(BaseEvent):
    """Событие попадания в кэш при проверке новизны"""
    
    @classmethod
    def create(cls,
               user_id: str,
               cache_type: str,
               key: str,
               latency_ms: float,
               correlation_id: Optional[str] = None) -> 'NoveltyCacheHitEvent':
        """
        Создать событие попадания в кэш
        
        Args:
            user_id: ID пользователя
            cache_type: Тип кэша (final/embedding/knn/profile)
            key: Ключ кэша
            latency_ms: Время операции в миллисекундах
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"ltm_{user_id}",
            event_type="NoveltyCacheHitEvent",
            data={
                "user_id": user_id,
                "cache_type": cache_type,
                "key": key,
                "latency_ms": latency_ms
            },
            version=0,
            correlation_id=correlation_id
        )


class NoveltyCacheMissEvent(BaseEvent):
    """Событие промаха кэша при проверке новизны"""
    
    @classmethod
    def create(cls,
               user_id: str,
               cache_type: str,
               key: str,
               latency_ms: float,
               correlation_id: Optional[str] = None) -> 'NoveltyCacheMissEvent':
        """
        Создать событие промаха кэша
        
        Args:
            user_id: ID пользователя
            cache_type: Тип кэша (final/embedding/knn/profile)
            key: Ключ кэша
            latency_ms: Время операции в миллисекундах
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"ltm_{user_id}",
            event_type="NoveltyCacheMissEvent",
            data={
                "user_id": user_id,
                "cache_type": cache_type,
                "key": key,
                "latency_ms": latency_ms
            },
            version=0,
            correlation_id=correlation_id
        )


class CacheInvalidatedEvent(BaseEvent):
    """Событие инвалидации кэша"""
    
    @classmethod
    def create(cls,
               user_id: str,
               cache_type: str,
               pattern: str,
               entries_deleted: int,
               reason: str,
               correlation_id: Optional[str] = None) -> 'CacheInvalidatedEvent':
        """
        Создать событие инвалидации кэша
        
        Args:
            user_id: ID пользователя
            cache_type: Тип кэша
            pattern: Паттерн удаления
            entries_deleted: Количество удаленных записей
            reason: Причина инвалидации
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"ltm_{user_id}",
            event_type="CacheInvalidatedEvent",
            data={
                "user_id": user_id,
                "cache_type": cache_type,
                "pattern": pattern,
                "entries_deleted": entries_deleted,
                "reason": reason
            },
            version=0,
            correlation_id=correlation_id
        )


class CleanupStartedEvent(BaseEvent):
    """Событие начала процесса очистки старых воспоминаний"""
    
    @classmethod
    def create(cls,
               dry_run: bool,
               scheduled: bool,
               correlation_id: Optional[str] = None) -> 'CleanupStartedEvent':
        """
        Создать событие начала cleanup
        
        Args:
            dry_run: Режим dry run (только логирование)
            scheduled: True если запущено планировщиком
            correlation_id: ID корреляции
        """
        return cls(
            stream_id="ltm_system",
            event_type="CleanupStartedEvent",
            data={
                "dry_run": dry_run,
                "scheduled": scheduled
            },
            version=0,
            correlation_id=correlation_id
        )


class CleanupCompletedEvent(BaseEvent):
    """Событие завершения процесса очистки"""
    
    @classmethod
    def create(cls,
               deleted_count: int,
               summaries_created: int,
               duration_seconds: float,
               dry_run: bool,
               correlation_id: Optional[str] = None) -> 'CleanupCompletedEvent':
        """
        Создать событие завершения cleanup
        
        Args:
            deleted_count: Количество удаленных воспоминаний
            summaries_created: Количество созданных summary
            duration_seconds: Время выполнения в секундах
            dry_run: Был ли режим dry run
            correlation_id: ID корреляции
        """
        return cls(
            stream_id="ltm_system",
            event_type="CleanupCompletedEvent",
            data={
                "deleted_count": deleted_count,
                "summaries_created": summaries_created,
                "duration_seconds": duration_seconds,
                "dry_run": dry_run
            },
            version=0,
            correlation_id=correlation_id
        )


class SummaryCreatedEvent(BaseEvent):
    """Событие создания агрегированного summary для периода"""
    
    @classmethod
    def create(cls,
               user_id: str,
               period_start: datetime,
               period_end: datetime,
               memories_count: int,
               correlation_id: Optional[str] = None) -> 'SummaryCreatedEvent':
        """
        Создать событие создания summary
        
        Args:
            user_id: ID пользователя
            period_start: Начало периода
            period_end: Конец периода
            memories_count: Количество воспоминаний в summary
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"ltm_{user_id}",
            event_type="SummaryCreatedEvent",
            data={
                "user_id": user_id,
                "period_start": period_start.isoformat() if hasattr(period_start, 'isoformat') else period_start,
                "period_end": period_end.isoformat() if hasattr(period_end, 'isoformat') else period_end,
                "memories_count": memories_count
            },
            version=0,
            correlation_id=correlation_id
        )