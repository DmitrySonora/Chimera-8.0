"""
События для анализа стиля общения и черт личности
"""
from typing import Optional, Dict, Any, List
from actors.events.base_event import BaseEvent


class PersonalityTraitDetectedEvent(BaseEvent):
    """Событие обнаружения проявления черты личности Химеры"""
    
    @classmethod
    def create(cls,
               user_id: str,
               trait_name: str,
               strength: float,
               context_mode: str,
               confidence: float,
               trigger_markers: List[str],
               message_preview: str,
               correlation_id: Optional[str] = None) -> 'PersonalityTraitDetectedEvent':
        """
        Создать событие обнаружения черты личности
        
        Args:
            user_id: ID пользователя
            trait_name: Название черты (curiosity, irony, empathy и т.д.)
            strength: Сила проявления (0.0-1.0)
            context_mode: Режим общения (talk/expert/creative)
            confidence: Уверенность в детекции (0.0-1.0)
            trigger_markers: Сработавшие лингвистические маркеры
            message_preview: Фрагмент текста где обнаружено (max 100 символов)
            correlation_id: ID корреляции для связывания событий
        """
        return cls(
            stream_id=f"personality_{user_id}",
            event_type="PersonalityTraitDetectedEvent",
            data={
                "user_id": user_id,
                "trait_name": trait_name,
                "strength": strength,
                "context_mode": context_mode,
                "confidence": confidence,
                "trigger_markers": trigger_markers,
                "message_preview": message_preview[:100] + "..." if len(message_preview) > 100 else message_preview
            },
            version=0,
            correlation_id=correlation_id
        )


class StyleVectorUpdatedEvent(BaseEvent):
    """Событие обновления стилевого вектора пользователя"""
    
    @classmethod
    def create(cls,
               user_id: str,
               old_vector: Dict[str, float],
               new_vector: Dict[str, float],
               messages_analyzed: int,
               significant_change: bool,
               dominant_style: str,
               correlation_id: Optional[str] = None) -> 'StyleVectorUpdatedEvent':
        """
        Создать событие обновления стиля общения
        
        Args:
            user_id: ID пользователя
            old_vector: Предыдущий вектор стиля (если был) - словарь с 4 компонентами
            new_vector: Новый вектор стиля - словарь с 4 компонентами
            messages_analyzed: Количество проанализированных сообщений
            significant_change: Изменение > 20% хотя бы по одной компоненте
            dominant_style: Доминирующий стиль (playful/serious/emotional/creative)
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"personality_{user_id}",
            event_type="StyleVectorUpdatedEvent",
            data={
                "user_id": user_id,
                "old_vector": old_vector,
                "new_vector": new_vector,
                "messages_analyzed": messages_analyzed,
                "significant_change": significant_change,
                "dominant_style": dominant_style
            },
            version=0,
            correlation_id=correlation_id
        )


class PartnerPersonaUpdatedEvent(BaseEvent):
    """Событие обновления модели собеседника (Partner Persona)"""
    
    @classmethod
    def create(cls,
               user_id: str,
               persona_id: str,
               version: int,
               previous_mode: Optional[str],
               recommended_mode: str,
               confidence_score: float,
               prediction_data: Optional[Dict[str, Any]],
               reason: str,
               correlation_id: Optional[str] = None) -> 'PartnerPersonaUpdatedEvent':
        """
        Создать событие обновления Partner Persona
        
        Args:
            user_id: ID пользователя
            persona_id: UUID персоны (как строка)
            version: Версия персоны (не путать с version события!)
            previous_mode: Предыдущий рекомендованный режим (если был)
            recommended_mode: Новый рекомендованный режим (talk/expert/creative)
            confidence_score: Уверенность в рекомендации (0.0-1.0)
            prediction_data: Данные предсказания (predicted_interests, prediction_confidence и т.д.)
            reason: Причина обновления (scheduled/significant_change/manual)
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"personality_{user_id}",
            event_type="PartnerPersonaUpdatedEvent",
            data={
                "user_id": user_id,
                "persona_id": persona_id,
                "version": version,
                "previous_mode": previous_mode,
                "recommended_mode": recommended_mode,
                "confidence_score": confidence_score,
                "prediction_data": prediction_data,
                "reason": reason
            },
            version=0,
            correlation_id=correlation_id
        )


class TraitManifestationEvent(BaseEvent):
    """Событие проявления черты личности в конкретном контексте"""
    
    @classmethod
    def create(cls,
               user_id: str,
               trait_name: str,
               manifestation_id: str,
               intensity: float,
               emotional_context: Dict[str, float],
               mode: str,
               response_fragment: str,
               timestamp_utc: str,
               correlation_id: Optional[str] = None) -> 'TraitManifestationEvent':
        """
        Создать событие проявления черты в контексте
        
        Args:
            user_id: ID пользователя
            trait_name: Название черты
            manifestation_id: UUID проявления (как строка)
            intensity: Интенсивность проявления (0.0-1.0)
            emotional_context: Эмоциональный контекст момента (словарь эмоций и их значений)
            mode: Режим общения (talk/expert/creative)
            response_fragment: Фрагмент ответа Химеры (max 200 символов)
            timestamp_utc: Время в ISO формате
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"personality_{user_id}",
            event_type="TraitManifestationEvent",
            data={
                "user_id": user_id,
                "trait_name": trait_name,
                "manifestation_id": manifestation_id,
                "intensity": intensity,
                "emotional_context": emotional_context,
                "mode": mode,
                "response_fragment": response_fragment[:200] + "..." if len(response_fragment) > 200 else response_fragment,
                "timestamp_utc": timestamp_utc
            },
            version=0,
            correlation_id=correlation_id
        )

class PersonalityProfileCalculatedEvent(BaseEvent):
    """Событие вычисления профиля личности"""
    
    @classmethod
    def create(cls,
               user_id: str,
               profile: Dict[str, float],
               dominant_traits: List[str],
               profile_metrics: Dict[str, float],
               modifiers_applied: Dict[str, Any],
               calculation_time_ms: int,
               correlation_id: Optional[str] = None) -> 'PersonalityProfileCalculatedEvent':
        """
        Создать событие вычисления профиля личности
        
        Args:
            user_id: ID пользователя
            profile: Вычисленный профиль {trait_name: value}
            dominant_traits: Топ-5 доминирующих черт
            profile_metrics: Метрики профиля (stability, dominance, balance)
            modifiers_applied: Примененные модификаторы {type: data}
            calculation_time_ms: Время вычисления в миллисекундах
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"personality_{user_id}",
            event_type="PersonalityProfileCalculatedEvent",
            data={
                "user_id": user_id,
                "profile": profile,
                "dominant_traits": dominant_traits,
                "profile_metrics": profile_metrics,
                "modifiers_applied": modifiers_applied,
                "calculation_time_ms": calculation_time_ms
            },
            version=0,
            correlation_id=correlation_id
        )


class TraitDominanceChangedEvent(BaseEvent):
    """Событие изменения доминирующих черт личности"""
    
    @classmethod
    def create(cls,
               user_id: str,
               previous_dominant: List[str],
               new_dominant: List[str],
               changed_traits: List[Dict[str, Any]],
               trigger: str,
               correlation_id: Optional[str] = None) -> 'TraitDominanceChangedEvent':
        """
        Создать событие изменения доминирующих черт
        
        Args:
            user_id: ID пользователя
            previous_dominant: Предыдущие топ-5 черт
            new_dominant: Новые топ-5 черт
            changed_traits: Список изменившихся черт с old_rank/new_rank
            trigger: Триггер изменения (modifiers/recovery/session_limit)
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"personality_{user_id}",
            event_type="TraitDominanceChangedEvent",
            data={
                "user_id": user_id,
                "previous_dominant": previous_dominant,
                "new_dominant": new_dominant,
                "changed_traits": changed_traits,
                "trigger": trigger
            },
            version=0,
            correlation_id=correlation_id
        )


class PersonalityProtectionActivatedEvent(BaseEvent):
    """Событие срабатывания защитного механизма личности"""
    
    @classmethod
    def create(cls,
               user_id: str,
               protection_type: str,
               affected_traits: List[str],
               constraint_details: Dict[str, Any],
               original_values: Dict[str, float],
               protected_values: Dict[str, float],
               correlation_id: Optional[str] = None) -> 'PersonalityProtectionActivatedEvent':
        """
        Создать событие срабатывания защиты
        
        Args:
            user_id: ID пользователя
            protection_type: Тип защиты (core_constraint/session_limit/recovery)
            affected_traits: Затронутые черты
            constraint_details: Детали ограничения
            original_values: Исходные значения черт
            protected_values: Значения после применения защиты
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"personality_{user_id}",
            event_type="PersonalityProtectionActivatedEvent",
            data={
                "user_id": user_id,
                "protection_type": protection_type,
                "affected_traits": affected_traits,
                "constraint_details": constraint_details,
                "original_values": original_values,
                "protected_values": protected_values
            },
            version=0,
            correlation_id=correlation_id
        )


class PersonalityStabilizedEvent(BaseEvent):
    """Событие стабилизации личности после периода неактивности"""
    
    @classmethod
    def create(cls,
               user_id: str,
               days_inactive: int,
               recovery_factor: float,
               baseline_convergence: float,
               stabilized_profile: Dict[str, float],
               correlation_id: Optional[str] = None) -> 'PersonalityStabilizedEvent':
        """
        Создать событие стабилизации личности
        
        Args:
            user_id: ID пользователя
            days_inactive: Количество дней неактивности
            recovery_factor: Фактор восстановления (0.0-1.0)
            baseline_convergence: Степень приближения к базе (0.0-1.0)
            stabilized_profile: Стабилизированный профиль
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"personality_{user_id}",
            event_type="PersonalityStabilizedEvent",
            data={
                "user_id": user_id,
                "days_inactive": days_inactive,
                "recovery_factor": recovery_factor,
                "baseline_convergence": baseline_convergence,
                "stabilized_profile": stabilized_profile
            },
            version=0,
            correlation_id=correlation_id
        )

class ResonanceCalculatedEvent(BaseEvent):
    """Событие вычисления резонанса для пользователя"""
    
    @classmethod
    def create(cls,
               user_id: str,
               resonance_coefficients: Dict[str, float],
               user_style: Dict[str, float],
               total_deviation: float,
               affected_traits: List[str],
               correlation_id: Optional[str] = None) -> 'ResonanceCalculatedEvent':
        """
        Создать событие вычисления резонанса
        
        Args:
            user_id: ID пользователя
            resonance_coefficients: Коэффициенты резонанса {trait: coefficient}
            user_style: Стиль пользователя (4 компонента)
            total_deviation: Суммарное отклонение от базового профиля
            affected_traits: Список затронутых черт
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"personality_{user_id}",
            event_type="ResonanceCalculatedEvent",
            data={
                "user_id": user_id,
                "resonance_coefficients": resonance_coefficients,
                "user_style": user_style,
                "total_deviation": total_deviation,
                "affected_traits": affected_traits
            },
            version=0,
            correlation_id=correlation_id
        )


class PersonalityAdaptationEvent(BaseEvent):
    """Событие адаптации резонанса на основе накопленного опыта"""
    
    @classmethod
    def create(cls,
               user_id: str,
               old_coefficients: Dict[str, float],
               new_coefficients: Dict[str, float],
               learning_rate: float,
               interactions_since_last: int,
               trigger_reason: str,
               correlation_id: Optional[str] = None) -> 'PersonalityAdaptationEvent':
        """
        Создать событие адаптации резонанса
        
        Args:
            user_id: ID пользователя
            old_coefficients: Предыдущие коэффициенты
            new_coefficients: Новые коэффициенты
            learning_rate: Скорость обучения
            interactions_since_last: Взаимодействий с последней адаптации
            trigger_reason: Причина адаптации (periodic/manual/threshold)
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"personality_{user_id}",
            event_type="PersonalityAdaptationEvent",
            data={
                "user_id": user_id,
                "old_coefficients": old_coefficients,
                "new_coefficients": new_coefficients,
                "learning_rate": learning_rate,
                "interactions_since_last": interactions_since_last,
                "trigger_reason": trigger_reason
            },
            version=0,
            correlation_id=correlation_id
        )


class AuthenticityCheckEvent(BaseEvent):
    """Событие проверки сохранения подлинности личности"""
    
    @classmethod
    def create(cls,
               user_id: str,
               check_type: str,
               total_deviation: float,
               max_allowed_deviation: float,
               protection_applied: bool,
               affected_traits: List[str],
               correlation_id: Optional[str] = None) -> 'AuthenticityCheckEvent':
        """
        Создать событие проверки аутентичности
        
        Args:
            user_id: ID пользователя
            check_type: Тип проверки (deviation_limit/noise_application/reset_check)
            total_deviation: Текущее отклонение от базы
            max_allowed_deviation: Максимально допустимое отклонение
            protection_applied: Была ли применена защита
            affected_traits: Затронутые черты
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"personality_{user_id}",
            event_type="AuthenticityCheckEvent",
            data={
                "user_id": user_id,
                "check_type": check_type,
                "total_deviation": total_deviation,
                "max_allowed_deviation": max_allowed_deviation,
                "protection_applied": protection_applied,
                "affected_traits": affected_traits
            },
            version=0,
            correlation_id=correlation_id
        )


class ResonanceDeactivatedEvent(BaseEvent):
    """Событие деактивации резонансного профиля"""
    
    @classmethod
    def create(cls,
               user_id: str,
               reason: str,
               interactions_total: int,
               days_since_last_activity: Optional[int] = None,
               correlation_id: Optional[str] = None) -> 'ResonanceDeactivatedEvent':
        """
        Создать событие деактивации резонанса
        
        Args:
            user_id: ID пользователя
            reason: Причина деактивации (inactivity/manual/user_request)
            interactions_total: Общее количество взаимодействий
            days_since_last_activity: Дней с последней активности
            correlation_id: ID корреляции
        """
        return cls(
            stream_id=f"personality_{user_id}",
            event_type="ResonanceDeactivatedEvent",
            data={
                "user_id": user_id,
                "reason": reason,
                "interactions_total": interactions_total,
                "days_since_last_activity": days_since_last_activity
            },
            version=0,
            correlation_id=correlation_id
        )