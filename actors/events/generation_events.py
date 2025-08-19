"""
События для GenerationActor и системы инъекций личности
"""
from typing import Optional, List, Dict
from actors.events.base_event import BaseEvent


class InjectionAppliedEvent(BaseEvent):
    """Событие успешного применения инъекции личности"""
    
    @classmethod
    def create(cls,
               user_id: str,
               source: str,
               traits_used: List[str],
               injection_length: int,
               correlation_id: Optional[str] = None) -> 'InjectionAppliedEvent':
        """
        Создать событие применения инъекции
        
        Args:
            user_id: ID пользователя
            source: Источник инъекции (fresh/cached/random)
            traits_used: Список использованных черт личности
            injection_length: Длина инъекции в символах
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"generation_{user_id}",
            event_type="InjectionAppliedEvent",
            data={
                "user_id": user_id,
                "source": source,
                "traits_used": traits_used,
                "injection_length": injection_length
            },
            version=0,  # Версия устанавливается EventVersionManager
            correlation_id=correlation_id
        )


class InjectionMetricsEvent(BaseEvent):
    """Событие с метриками системы инъекций"""
    
    @classmethod
    def create(cls,
               total_injections: int,
               source_distribution: Dict[str, int],
               cache_hit_rate: float,
               correlation_id: Optional[str] = None) -> 'InjectionMetricsEvent':
        """
        Создать событие с метриками
        
        Args:
            total_injections: Общее количество инъекций
            source_distribution: Распределение по источникам
            cache_hit_rate: Процент использования кэша
            correlation_id: ID корреляции
        """
        return cls(
            stream_id="generation_metrics",
            event_type="InjectionMetricsEvent",
            data={
                "total_injections": total_injections,
                "source_distribution": source_distribution,
                "cache_hit_rate": cache_hit_rate
            },
            version=0,  # Версия устанавливается EventVersionManager
            correlation_id=correlation_id
        )