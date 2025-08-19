"""
Calculation mixin for PersonalityActor - handles profile computation
"""
import json
import time
from typing import Dict, List, Any
from datetime import datetime, timezone
from config.settings import (
    PERSONALITY_MIN_TRAIT_VALUE,
    PERSONALITY_MAX_TRAIT_VALUE,
    PERSONALITY_PROFILE_CACHE_TTL_SECONDS,
    PERSONALITY_RECOVERY_DAYS,
    PERSONALITY_RECOVERY_RATE
)
from database.redis_connection import redis_connection
from utils.monitoring import measure_latency
from actors.events.personality_events import (
    PersonalityProfileCalculatedEvent,
    TraitDominanceChangedEvent
)


class PersonalityCalculationMixin:
    """Mixin providing profile calculation methods for PersonalityActor"""
    
    # These attributes are available from PersonalityActor
    logger: object
    _base_traits: Dict[str, Dict[str, Any]]
    _current_modifiers: Dict[str, Dict[str, Any]]
    _metrics: Dict[str, int]
    _redis: Any
    
    # Methods from PersonalityProtectionMixin
    _calculate_days_inactive: Any
    _apply_core_constraint: Any
    _apply_session_change_limit: Any
    _apply_recovery_adjustment: Any
    _track_session_start: Any
    _update_activity_time: Any
    
    @measure_latency
    async def _calculate_active_profile(self, user_id: str) -> Dict[str, float]:
        """
        Вычисляет активный профиль личности с учетом всех модификаторов.
        Использует мультипликативную модель: База × Стиль × Эмоции × Время
        с последующим применением защитных механизмов и резонансной персонализации.
        """
        start_time = time.time()
        
        # ВАЖНО: Проверяем неактивность ДО проверки кэша
        days_inactive = self._calculate_days_inactive(user_id)
        
        # Если пользователь неактивен достаточно долго - инвалидируем кэш
        if days_inactive >= PERSONALITY_RECOVERY_DAYS:
            if self._redis:
                try:
                    cache_key = redis_connection.make_key("personality", "profile", user_id)
                    await self._redis.delete(cache_key)
                    self.logger.debug(
                        f"Invalidated cache for user {user_id} due to {days_inactive} days of inactivity"
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to invalidate cache: {str(e)}")
        
        # Проверяем кэш (только если recovery не требуется)
        if self._redis:
            try:
                cache_key = redis_connection.make_key("personality", "profile", user_id)
                cached_data = await self._redis.get(cache_key)
                
                if cached_data:
                    self._metrics['cache_hits'] += 1
                    self.logger.debug(f"Profile cache hit for user {user_id}")
                    return json.loads(cached_data)
                else:
                    self._metrics['cache_misses'] += 1
                    
            except Exception as e:
                self.logger.warning(f"Redis cache error: {str(e)}")
        
        # Вычисляем профиль
        profile = {}
        
        for trait_name, trait_data in self._base_traits.items():
            base_value = trait_data['base_value']
            
            # Получаем модификаторы
            style_mod = self._get_style_modifier(user_id, trait_name)
            emotion_mod = self._get_emotion_modifier(user_id, trait_name)
            temporal_mod = self._get_temporal_modifier(user_id)
            
            # Мультипликативная модель
            active_value = base_value * style_mod * emotion_mod * temporal_mod
            
            # Применяем ограничения (пока просто min/max)
            active_value = max(PERSONALITY_MIN_TRAIT_VALUE, 
                             min(PERSONALITY_MAX_TRAIT_VALUE, active_value))
            
            profile[trait_name] = active_value
        
        # Нормализуем профиль
        profile = self._normalize_profile(profile)
        
        # Применяем защитные механизмы в строгом порядке
        # После них будет применен резонанс (шаг 4)
        protection_applied = False
        
        # 1. Применяем core constraints для каждой черты
        for trait_name in list(profile.keys()):
            if trait_name in self._base_traits:
                base_value = self._base_traits[trait_name]['base_value']
                old_value = profile[trait_name]
                new_value = self._apply_core_constraint(
                    old_value,
                    base_value,
                    trait_name,
                    self._base_traits[trait_name]
                )
                if new_value != old_value:
                    protection_applied = True
                profile[trait_name] = new_value
        
        # 2. Применяем ограничения сессии
        old_profile = profile.copy()
        profile = self._apply_session_change_limit(profile, user_id)
        if profile != old_profile:
            protection_applied = True
        
        # 3. Применяем восстановление после неактивности
        old_profile = profile.copy()
        profile = self._apply_recovery_adjustment(profile, user_id, self._base_traits)
        if profile != old_profile:
            protection_applied = True
        
        # 4. Применяем резонанс как финальный слой персонализации
        if hasattr(self, '_apply_resonance'):
            profile = await self._apply_resonance(profile, user_id)
            # Нормализуем после резонанса, так как коэффициенты могут вывести значения за пределы 0.0-1.0
            profile = self._normalize_profile(profile)
        
        # 5. Отслеживаем начало сессии если это новый пользователь или после восстановления
        self._track_session_start(user_id, profile)
        
        # 6. Обновляем время активности ПОСЛЕ всех защитных механизмов
        self._update_activity_time(user_id)
        
        # Сохраняем в кэш только если защита не применялась
        if not protection_applied and self._redis:
            try:
                cache_key = redis_connection.make_key("personality", "profile", user_id)
                await self._redis.setex(
                    cache_key,
                    PERSONALITY_PROFILE_CACHE_TTL_SECONDS,
                    json.dumps(profile)
                )
                self.logger.debug(
                    f"Cached personality profile for user {user_id} "
                    f"(TTL: {PERSONALITY_PROFILE_CACHE_TTL_SECONDS}s)"
                )
            except Exception as e:
                self.logger.warning(f"Failed to cache profile: {str(e)}")
        elif protection_applied:
            self.logger.debug("Profile not cached due to protection mechanisms applied")
        
        # Обновляем метрики
        self._metrics['profiles_calculated'] += 1
        
        # Логируем медленные вычисления
        calc_time_ms = int((time.time() - start_time) * 1000)
        
        # Генерируем событие вычисления профиля
        dominant_traits = self._get_dominant_traits(profile, n=5)
        
        # Вычисляем метрики профиля
        profile_metrics = {
            'stability': self._calculate_stability(user_id, profile),
            'dominance': self._calculate_dominance(profile, dominant_traits),
            'balance': self._calculate_balance(profile)
        }
        
        # Собираем примененные модификаторы
        modifiers_applied = {}
        if user_id in self._current_modifiers:
            for mod_type, mod_data in self._current_modifiers[user_id].items():
                modifiers_applied[mod_type] = {
                    'source': mod_data.get('source', 'unknown'),
                    'applied_at': mod_data.get('timestamp', datetime.now(timezone.utc)).isoformat()
                }
        
        event = PersonalityProfileCalculatedEvent.create(
            user_id=user_id,
            profile=profile,
            dominant_traits=dominant_traits,
            profile_metrics=profile_metrics,
            modifiers_applied=modifiers_applied,
            calculation_time_ms=calc_time_ms
        )
        
        if self.get_actor_system():
            await self._event_version_manager.append_event(event, self.get_actor_system())
            self._metrics['profile_calculated_events'] += 1
        
        # Проверяем изменение доминирующих черт
        await self._check_dominance_change(user_id, dominant_traits, protection_applied)
        if calc_time_ms > 100:
            self.logger.warning(
                f"Slow profile calculation for user {user_id}: {calc_time_ms}ms"
            )
        
        return profile
    
    def _get_style_modifier(self, user_id: str, trait_name: str) -> float:
        """Получает модификатор стиля для черты личности"""
        if user_id not in self._current_modifiers:
            return 1.0
        
        style_data = self._current_modifiers[user_id].get('style', {}).get('data', {})
        
        # Прямое значение для черты, если есть
        if trait_name in style_data:
            return style_data[trait_name]
        
        return 1.0
    
    def _get_emotion_modifier(self, user_id: str, trait_name: str) -> float:
        """
        Вычисляет эмоциональный модификатор для черты личности.
        Использует TRAIT_EMOTION_ASSOCIATIONS из базы данных.
        """
        if user_id not in self._current_modifiers:
            return 1.0
        
        emotion_data = self._current_modifiers[user_id].get('emotion', {}).get('data', {})
        if not emotion_data:
            return 1.0
        
        # Получаем ассоциации эмоций для этой черты
        trait_data = self._base_traits.get(trait_name, {})
        if not trait_data:
            return 1.0
            
        trait_emotion_associations = trait_data.get('emotion_associations', {})
        
        # Проверяем, если это строка JSON - десериализуем
        if isinstance(trait_emotion_associations, str):
            try:
                trait_emotion_associations = json.loads(trait_emotion_associations)
            except json.JSONDecodeError:
                self.logger.warning(f"Failed to parse emotion_associations for {trait_name}")
                return 1.0
        
        if not trait_emotion_associations:
            return 1.0
        
        # Вычисляем модификатор по алгоритму из ТЗ
        emotion_mod = 1.0
        
        for emotion, strength in emotion_data.items():
            if emotion in trait_emotion_associations:
                influence = trait_emotion_associations[emotion]  # от 0 до 1
                # (influence - 0.5) дает диапазон от -0.5 до 0.5
                # умножаем на strength и на 0.5 для умеренного влияния
                emotion_mod += (influence - 0.5) * strength * 0.5
        
        # Ограничиваем диапазон от 0.5 до 1.5
        emotion_mod = max(0.5, min(1.5, emotion_mod))
        
        return emotion_mod
    
    def _get_temporal_modifier(self, user_id: str) -> float:
        """
        Вычисляет временной модификатор на основе времени суток (UTC).
        Утро (6-11): 0.9, День (11-18): 1.0, Вечер (18-23): 0.95, Ночь (23-6): 0.85
        """
        current_hour = datetime.now(timezone.utc).hour
        
        if 6 <= current_hour < 11:
            return 0.9  # Утро
        elif 11 <= current_hour < 18:
            return 1.0  # День
        elif 18 <= current_hour < 23:
            return 0.95  # Вечер
        else:
            return 0.85  # Ночь
    
    def _normalize_profile(self, profile: Dict[str, float]) -> Dict[str, float]:
        """
        Нормализует профиль, ограничивая значения диапазоном [0.0, 1.0].
        В этом шаге НЕ нормализуем сумму.
        """
        normalized = {}
        
        for trait_name, value in profile.items():
            # Ограничиваем диапазоном
            normalized_value = max(PERSONALITY_MIN_TRAIT_VALUE,
                                 min(PERSONALITY_MAX_TRAIT_VALUE, value))
            normalized[trait_name] = round(normalized_value, 3)  # Округляем для читаемости
        
        return normalized
    
    def _apply_recovery_to_modifiers(self, user_id: str) -> float:
        """
        Вычисляет фактор ослабления модификаторов на основе неактивности.
        Возвращает множитель от 0.0 до 1.0
        """
        days_inactive = self._calculate_days_inactive(user_id)
        
        if days_inactive < PERSONALITY_RECOVERY_DAYS:
            return 1.0  # Полная сила модификаторов
        
        # После PERSONALITY_RECOVERY_DAYS дней модификаторы начинают ослабевать
        recovery_days = days_inactive - PERSONALITY_RECOVERY_DAYS
        # Чем больше дней неактивности, тем слабее модификаторы
        modifier_strength = max(0.0, 1.0 - (recovery_days * PERSONALITY_RECOVERY_RATE))
        
        if modifier_strength < 1.0:
            self.logger.info(
                f"Recovery factor applied for user {user_id}: "
                f"modifiers at {modifier_strength*100:.0f}% strength "
                f"after {days_inactive} days inactive"
            )
            self._metrics['recoveries_triggered'] += 1
        
        return modifier_strength
    
    def _get_dominant_traits(self, profile: Dict[str, float], n: int = 5) -> List[str]:
        """
        Возвращает топ N доминирующих черт личности.
        """
        # Сортируем черты по убыванию значения
        sorted_traits = sorted(profile.items(), key=lambda x: x[1], reverse=True)
        
        # Берем первые n названий черт
        dominant = [trait_name for trait_name, _ in sorted_traits[:n]]
        
        return dominant
    
    async def _check_dominance_change(self, user_id: str, new_dominant: List[str], 
                                     protection_applied: bool) -> None:
        """
        Проверяет изменение доминирующих черт и генерирует событие при необходимости
        
        Args:
            user_id: ID пользователя
            new_dominant: Новые топ-5 доминирующих черт
            protection_applied: Применялись ли защитные механизмы
        """
        # Получаем предыдущие доминирующие черты
        previous_dominant = self._previous_dominant_traits.get(user_id, [])
        
        # Если нет предыдущих данных - сохраняем текущие
        if not previous_dominant:
            self._previous_dominant_traits[user_id] = new_dominant.copy()
            return
        
        # Проверяем изменения
        if previous_dominant != new_dominant:
            # Анализируем какие черты изменили позиции
            changed_traits = []
            
            for trait in set(previous_dominant + new_dominant):
                old_rank = previous_dominant.index(trait) + 1 if trait in previous_dominant else None
                new_rank = new_dominant.index(trait) + 1 if trait in new_dominant else None
                
                if old_rank != new_rank:
                    changed_traits.append({
                        'trait': trait,
                        'old_rank': old_rank,
                        'new_rank': new_rank
                    })
            
            # Определяем триггер
            trigger = 'session_limit' if protection_applied else 'modifiers'
            
            # Генерируем событие
            event = TraitDominanceChangedEvent.create(
                user_id=user_id,
                previous_dominant=previous_dominant,
                new_dominant=new_dominant,
                changed_traits=changed_traits,
                trigger=trigger
            )
            
            if self.get_actor_system():
                await self._event_version_manager.append_event(event, self.get_actor_system())
                self._metrics['dominance_changed_events'] += 1
            
            # Обновляем сохраненные доминирующие черты
            self._previous_dominant_traits[user_id] = new_dominant.copy()
            
            self.logger.info(
                f"Dominant traits changed for user {user_id}: "
                f"{', '.join(previous_dominant[:3])} → {', '.join(new_dominant[:3])}"
            )
    
    def _calculate_stability(self, user_id: str, profile: Dict[str, float]) -> float:
        """Вычисляет стабильность профиля (заглушка для этого этапа)"""
        # TODO: Реализовать на основе истории изменений
        return 0.8
    
    def _calculate_dominance(self, profile: Dict[str, float], dominant_traits: List[str]) -> float:
        """Вычисляет выраженность доминирующих черт"""
        if not dominant_traits:
            return 0.0
        
        # Среднее значение топ-5 черт
        dominance_sum = sum(profile.get(trait, 0.0) for trait in dominant_traits[:5])
        return round(dominance_sum / min(5, len(dominant_traits)), 3)
    
    def _calculate_balance(self, profile: Dict[str, float]) -> float:
        """Вычисляет сбалансированность профиля"""
        if not profile:
            return 1.0
        
        values = list(profile.values())
        avg = sum(values) / len(values)
        
        # Стандартное отклонение
        variance = sum((v - avg) ** 2 for v in values) / len(values)
        std_dev = variance ** 0.5
        
        # Чем меньше отклонение, тем выше баланс
        balance = max(0.0, 1.0 - (std_dev * 2))
        return round(balance, 3)