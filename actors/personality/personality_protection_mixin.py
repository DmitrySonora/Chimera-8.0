"""
Protection mixin for PersonalityActor - implements identity preservation mechanisms
"""
from typing import Dict, Any, TYPE_CHECKING
from datetime import datetime, timezone

if TYPE_CHECKING:
    from utils.event_utils import EventVersionManager

from actors.events.personality_events import (
    PersonalityProtectionActivatedEvent,
    PersonalityStabilizedEvent
)
from config.settings import (
    PERSONALITY_CORE_TRAIT_MINIMUM,
    PERSONALITY_SESSION_CHANGE_LIMIT,
    PERSONALITY_RECOVERY_DAYS,
    PERSONALITY_RECOVERY_RATE,
    PERSONALITY_SESSION_CLEANUP_HOURS,
    PERSONALITY_BASELINE_CONVERGENCE_THRESHOLD
)


class PersonalityProtectionMixin:
    """Mixin providing protection mechanisms for personality traits"""
    
    # These attributes are available from PersonalityActor
    logger: object
    _event_version_manager: 'EventVersionManager'
    get_actor_system: Any
    _session_start_profiles: Dict[str, Dict]  # user_id -> {'profile': Dict, 'started_at': datetime}
    _last_activity: Dict[str, datetime]  # user_id -> last activity timestamp
    _metrics: Dict[str, int]
    
    def _apply_core_constraint(self, trait_value: float, base_value: float, 
                              trait_name: str, trait_data: Dict) -> float:
        """
        Применяет ограничение минимального значения для core черт.
        Core черты не могут опускаться ниже 40% от базового значения.
        
        Args:
            trait_value: Текущее вычисленное значение черты
            base_value: Базовое значение черты
            trait_name: Название черты
            trait_data: Полные данные черты из _base_traits
            
        Returns:
            Значение с примененным ограничением
        """
        if trait_data.get('is_core', False):
            min_allowed = base_value * PERSONALITY_CORE_TRAIT_MINIMUM
            
            if trait_value < min_allowed:
                self.logger.info(
                    f"Core constraint applied for {trait_name}: "
                    f"{trait_value:.3f} → {min_allowed:.3f} "
                    f"(base: {base_value:.3f})"
                )
                self._metrics['core_constraints_applied'] += 1
                
                # Генерируем событие защиты
                event = PersonalityProtectionActivatedEvent.create(
                    user_id="unknown",  # user_id будет добавлен в следующей версии
                    protection_type="core_constraint",
                    affected_traits=[trait_name],
                    constraint_details={
                        "minimum": PERSONALITY_CORE_TRAIT_MINIMUM,
                        "trait": trait_name
                    },
                    original_values={trait_name: trait_value},
                    protected_values={trait_name: min_allowed}
                )
                
                if hasattr(self, '_pending_protection_events'):
                    self._pending_protection_events.append(event)
                
                return min_allowed
        
        return trait_value
    
    def _track_session_start(self, user_id: str, profile: Dict[str, float]) -> None:
        """
        Отслеживает начало сессии для пользователя.
        Также выполняет очистку старых сессий.
        
        Args:
            user_id: ID пользователя
            profile: Начальный профиль сессии
        """
        # Очистка старых сессий
        current_time = datetime.now(timezone.utc)
        to_remove = []
        
        for uid, data in self._session_start_profiles.items():
            if (current_time - data['started_at']).total_seconds() > PERSONALITY_SESSION_CLEANUP_HOURS * 3600:
                to_remove.append(uid)
        
        for uid in to_remove:
            del self._session_start_profiles[uid]
            self.logger.debug(f"Cleaned up old session for user {uid}")
        
        # Отслеживаем новую сессию если её еще нет
        if user_id not in self._session_start_profiles:
            self._session_start_profiles[user_id] = {
                'profile': profile.copy(),
                'started_at': current_time
            }
            self.logger.debug(f"Started tracking new session for user {user_id}")
            
            # TODO: В будущем использовать session_id вместо user_id для точного отслеживания сессий
    
    def _apply_session_change_limit(self, new_profile: Dict[str, float], 
                                   user_id: str) -> Dict[str, float]:
        """
        Ограничивает изменения профиля в рамках одной сессии (максимум 20%).
        
        Args:
            new_profile: Новый вычисленный профиль
            user_id: ID пользователя
            
        Returns:
            Профиль с примененными ограничениями
        """
        # Если нет начального профиля, возвращаем как есть
        if user_id not in self._session_start_profiles:
            return new_profile
        
        start_profile = self._session_start_profiles[user_id]['profile']
        limited_profile = {}
        limits_applied = False
        
        for trait_name, new_value in new_profile.items():
            start_value = start_profile.get(trait_name, 0.5)
            max_change = start_value * PERSONALITY_SESSION_CHANGE_LIMIT
            
            # Проверяем превышение лимита
            if abs(new_value - start_value) > max_change:
                # Ограничиваем изменение
                if new_value > start_value:
                    limited_value = start_value + max_change
                else:
                    limited_value = start_value - max_change
                
                limited_profile[trait_name] = limited_value
                limits_applied = True
                
                self.logger.info(
                    f"Session limit applied for {trait_name}: "
                    f"{new_value:.3f} → {limited_value:.3f} "
                    f"(start: {start_value:.3f}, max change: ±{max_change:.3f})"
                )
            else:
                limited_profile[trait_name] = new_value
        
        if limits_applied:
            self._metrics['session_limits_applied'] += 1
            
            # Собираем данные для события
            affected_traits = []
            original_values = {}
            protected_values = {}
            
            for trait_name, new_value in new_profile.items():
                if limited_profile[trait_name] != new_value:
                    affected_traits.append(trait_name)
                    original_values[trait_name] = new_value
                    protected_values[trait_name] = limited_profile[trait_name]
            
            # Генерируем событие защиты
            event = PersonalityProtectionActivatedEvent.create(
                user_id=user_id,
                protection_type="session_limit",
                affected_traits=affected_traits,
                constraint_details={
                    "limit": PERSONALITY_SESSION_CHANGE_LIMIT,
                    "session_start": self._session_start_profiles[user_id]['started_at'].isoformat()
                },
                original_values=original_values,
                protected_values=protected_values
            )
            
            if self.get_actor_system():
                import asyncio
                asyncio.create_task(
                    self._event_version_manager.append_event(event, self.get_actor_system())
                )
                self._metrics['protection_activated_events'] += 1
        
        return limited_profile
    
    def _update_activity_time(self, user_id: str) -> None:
        """
        Обновляет время последней активности пользователя.
        
        Args:
            user_id: ID пользователя
        """
        self._last_activity[user_id] = datetime.now(timezone.utc)
    
    def _calculate_days_inactive(self, user_id: str) -> int:
        """
        Вычисляет количество дней неактивности пользователя.
        
        Args:
            user_id: ID пользователя
            
        Returns:
            Количество дней неактивности (0 для новых пользователей)
        """
        if user_id not in self._last_activity:
            return 0
        
        last_active = self._last_activity[user_id]
        current_time = datetime.now(timezone.utc)
        inactive_seconds = (current_time - last_active).total_seconds()
        
        return int(inactive_seconds / 86400)  # Конвертируем в дни
    
    def _apply_recovery_adjustment(self, profile: Dict[str, float], user_id: str, 
                                  base_traits: Dict[str, Dict]) -> Dict[str, float]:
        """
        Применяет восстановление к базовому профилю после периода неактивности.
        Профиль восстанавливается к базовым значениям со скоростью 10% в день.
        
        Args:
            profile: Текущий профиль
            user_id: ID пользователя
            base_traits: Базовые черты личности
            
        Returns:
            Профиль с примененным восстановлением
        """
        # Сохраняем дни неактивности ДО обновления активности
        days_inactive = self._calculate_days_inactive(user_id)
        
        # Восстановление начинается после PERSONALITY_RECOVERY_DAYS дней
        if days_inactive < PERSONALITY_RECOVERY_DAYS:
            return profile
        
        # Вычисляем фактор восстановления
        recovery_days = days_inactive - PERSONALITY_RECOVERY_DAYS
        recovery_factor = min(1.0, recovery_days * PERSONALITY_RECOVERY_RATE)
        
        # Логируем параметры восстановления
        self.logger.debug(f"Recovery for {user_id}: days_inactive={days_inactive}, "
                         f"recovery_factor={recovery_factor:.2f}")
        
        adjusted_profile = {}
        recovery_applied = False
        
        for trait_name, current_value in profile.items():
            if trait_name in base_traits:
                base_value = base_traits[trait_name]['base_value']
                
                # Интерполируем между текущим и базовым значением
                recovered_value = current_value + (base_value - current_value) * recovery_factor
                
                if abs(recovered_value - current_value) > 0.001:  # Порог значимости
                    recovery_applied = True
                    self.logger.info(
                        f"Recovery applied for {trait_name}: "
                        f"{current_value:.3f} → {recovered_value:.3f} "
                        f"(base: {base_value:.3f}, factor: {recovery_factor:.2f})"
                    )
                
                adjusted_profile[trait_name] = recovered_value
            else:
                adjusted_profile[trait_name] = current_value
        
        if recovery_applied:
            self.logger.info(
                f"Personality recovery triggered for user {user_id} "
                f"after {days_inactive} days of inactivity"
            )
            self._metrics['recoveries_triggered'] += 1
            
            # Генерируем событие защиты recovery
            affected_traits = []
            original_values = {}
            protected_values = {}
            
            for trait_name, current_value in profile.items():
                if trait_name in adjusted_profile and abs(adjusted_profile[trait_name] - current_value) > 0.001:
                    affected_traits.append(trait_name)
                    original_values[trait_name] = current_value
                    protected_values[trait_name] = adjusted_profile[trait_name]
            
            event = PersonalityProtectionActivatedEvent.create(
                user_id=user_id,
                protection_type="recovery",
                affected_traits=affected_traits,
                constraint_details={
                    "days_inactive": days_inactive,
                    "recovery_rate": PERSONALITY_RECOVERY_RATE
                },
                original_values=original_values,
                protected_values=protected_values
            )
            
            if self.get_actor_system():
                import asyncio
                asyncio.create_task(
                    self._event_version_manager.append_event(event, self.get_actor_system())
                )
                self._metrics['protection_activated_events'] += 1
            
            # Проверяем стабилизацию (baseline_convergence > 0.95)
            baseline_convergence = self._calculate_baseline_convergence(adjusted_profile, base_traits)
            
            if baseline_convergence > PERSONALITY_BASELINE_CONVERGENCE_THRESHOLD:
                stabilized_event = PersonalityStabilizedEvent.create(
                    user_id=user_id,
                    days_inactive=days_inactive,
                    recovery_factor=recovery_factor,
                    baseline_convergence=baseline_convergence,
                    stabilized_profile=adjusted_profile
                )
                
                if self.get_actor_system():
                    asyncio.create_task(
                        self._event_version_manager.append_event(stabilized_event, self.get_actor_system())
                    )
                    self._metrics['personality_stabilized_events'] += 1
                
                self.logger.info(
                    f"Personality stabilized for user {user_id} "
                    f"(convergence: {baseline_convergence:.2%})"
                )
        
        return adjusted_profile
    
    def _calculate_baseline_convergence(self, current_profile: Dict[str, float], 
                                       base_traits: Dict[str, Dict]) -> float:
        """
        Вычисляет степень приближения текущего профиля к базовому (0.0-1.0)
        
        Args:
            current_profile: Текущий профиль личности
            base_traits: Базовые черты личности
            
        Returns:
            Значение от 0.0 до 1.0, где 1.0 - полное совпадение с базой
        """
        if not current_profile or not base_traits:
            return 0.0
        
        convergence_values = []
        
        for trait_name, current_value in current_profile.items():
            if trait_name in base_traits:
                base_value = base_traits[trait_name].get('base_value', 0.5)
                
                # Избегаем деления на ноль
                if base_value > 0:
                    # Отношение текущего к базовому (ограничено 1.0)
                    convergence = min(current_value / base_value, 1.0)
                    convergence_values.append(convergence)
        
        if convergence_values:
            # Среднее значение convergence по всем чертам
            return round(sum(convergence_values) / len(convergence_values), 3)
        
        return 0.0