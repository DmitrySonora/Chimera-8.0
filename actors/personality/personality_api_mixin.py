"""
API mixin for PersonalityActor - provides interface for other actors
"""
import math
from typing import Dict, List, Any
from datetime import datetime, timezone
from actors.messages import ActorMessage, MESSAGE_TYPES
from utils.monitoring import measure_latency
from config.settings import PERSONALITY_RECOVERY_DAYS


class PersonalityAPIMixin:
    """Mixin providing API methods for PersonalityActor"""
    
    # These attributes are available from PersonalityActor
    logger: object
    actor_id: str
    get_actor_system: Any
    _base_traits: Dict[str, Dict[str, Any]]
    _trait_history: Dict[str, List[Dict[str, float]]]
    _metrics: Dict[str, int]
    _session_start_profiles: Dict[str, Dict]
    
    # Methods from other mixins
    _calculate_active_profile: Any
    _get_dominant_traits: Any
    _calculate_days_inactive: Any
    
    @measure_latency
    async def _handle_get_profile(self, message: ActorMessage) -> None:
        """Обработчик получения профиля личности"""
        user_id = message.payload.get('user_id')
        if not user_id:
            self.logger.warning("GET_PERSONALITY_PROFILE received without user_id")
            return
        
        # Определяем кому отвечать
        reply_to_actor = message.reply_to or message.sender_id
        if not reply_to_actor:
            self.logger.warning("GET_PERSONALITY_PROFILE message without reply_to or sender_id")
            return
        
        try:
            # Получаем профиль (из кэша или вычисляем)
            profile = await self._calculate_active_profile(user_id)
            
            # Определяем доминирующие черты
            dominant_traits = self._get_dominant_traits(profile, n=5)
            
            # Вычисляем метрики профиля
            profile_metrics = self._calculate_profile_metrics(profile)
            
            # Проверяем какие защиты были применены
            protection_applied = []
            days_inactive = self._calculate_days_inactive(user_id)
            
            if user_id in self._session_start_profiles:
                protection_applied.append('session_limits')
            if days_inactive >= PERSONALITY_RECOVERY_DAYS:
                protection_applied.append('recovery')
            # Core constraints проверяем по факту наличия core черт
            if any(self._base_traits.get(trait, {}).get('is_core', False) for trait in profile):
                protection_applied.append('core_constraints')
            
            # Подготавливаем ответ
            response_data = {
                'user_id': user_id,
                'request_id': message.payload.get('request_id'),
                'active_traits': profile,
                'dominant_traits': dominant_traits,
                'profile_metrics': profile_metrics,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'protection_applied': protection_applied,
                'days_inactive': days_inactive
            }
            
            # Если запрошена история
            if message.payload.get('include_history', False):
                response_data['trait_history'] = {
                    trait: self.get_trait_history(user_id, trait, limit=10)
                    for trait in dominant_traits[:3]  # История только для топ-3 черт
                }
            
            # Создаем и отправляем ответ
            response = ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES['PERSONALITY_PROFILE_RESPONSE'],
                payload=response_data
            )
            
            self.logger.debug(f"Sending message_type: {MESSAGE_TYPES['PERSONALITY_PROFILE_RESPONSE']}")
            
            if self.get_actor_system():
                await self.get_actor_system().send_message(reply_to_actor, response)
                
                self.logger.info(
                    f"Sent personality profile for user {user_id} to {reply_to_actor}: "
                    f"dominant traits: {', '.join(dominant_traits[:3])}"
                )
            
        except Exception as e:
            self.logger.error(
                f"Failed to get personality profile for user {user_id}: {str(e)}"
            )
    
    def get_trait_history(self, user_id: str, trait_name: str, limit: int = 10) -> List[Dict]:
        """
        Получить историю изменений конкретной черты.
        
        Args:
            user_id: ID пользователя
            trait_name: Название черты личности
            limit: Максимальное количество записей
            
        Returns:
            Список словарей с историей изменений черты
        """
        if user_id not in self._trait_history:
            return []
        
        history = self._trait_history[user_id]
        # Если история хранит полные профили (Dict[str, float])
        if history and isinstance(history[0], dict):
            trait_values = []
            for i, snapshot in enumerate(history[-limit:]):
                if trait_name in snapshot:
                    trait_values.append({
                        'value': snapshot[trait_name],
                        'timestamp': i  # TODO: добавить реальные timestamps если есть
                    })
            return trait_values
        return []
    
    def get_trait_emotional_context(self, user_id: str, trait_name: str) -> Dict[str, Any]:
        """
        Получить эмоциональный контекст черты личности.
        Возвращает историю эмоциональных ассоциаций с этой чертой.
        
        Args:
            user_id: ID пользователя
            trait_name: Название черты личности
            
        Returns:
            Словарь с эмоциональным контекстом черты
        """
        # TODO: Реализация будет добавлена в фазе квалиа
        # Сейчас возвращаем заглушку
        return {
            'trait_name': trait_name,
            'emotional_associations': {},
            'context_available': False,
            'note': 'Will be implemented in qualia phase'
        }
    
    def get_trait_manifestation_strength(self, user_id: str, trait_name: str) -> float:
        """
        Получить силу проявления черты (0.0-1.0).
        Учитывает частоту активации и средний уровень.
        
        Args:
            user_id: ID пользователя
            trait_name: Название черты личности
            
        Returns:
            Сила проявления черты от 0.0 до 1.0
        """
        # TODO: Реализация будет добавлена в фазе квалиа
        # Сейчас возвращаем базовое значение если есть
        if trait_name in self._base_traits:
            return self._base_traits[trait_name].get('base_value', 0.5)
        return 0.5
    
    def _calculate_profile_metrics(self, profile: Dict[str, float]) -> Dict[str, float]:
        """
        Вычислить метрики профиля личности.
        
        Args:
            profile: Словарь активных черт личности
            
        Returns:
            Dict с метриками:
            - stability: низкая вариация = стабильная личность (0.0-1.0)
            - dominance: выраженность топ-черт (0.0-1.0)
            - balance: равномерность распределения (0.0-1.0)
        """
        values = list(profile.values())
        
        if not values:
            return {
                'stability': 0.5,
                'dominance': 0.5,
                'balance': 0.5
            }
        
        # Стабильность - обратная величина от стандартного отклонения
        if len(values) > 1:
            mean = sum(values) / len(values)
            variance = sum((x - mean) ** 2 for x in values) / len(values)
            std_dev = variance ** 0.5
            # Нормализуем std_dev (максимум около 0.5 для диапазона 0-1)
            stability = 1.0 - min(std_dev * 2, 1.0)
        else:
            stability = 1.0
        
        # Доминантность - разница между топ-3 и остальными
        sorted_values = sorted(values, reverse=True)
        if len(sorted_values) >= 3:
            top3_avg = sum(sorted_values[:3]) / 3
            rest = sorted_values[3:]
            rest_avg = sum(rest) / len(rest) if rest else 0
            # Нормализуем разницу
            dominance = min((top3_avg - rest_avg) * 2, 1.0)
        else:
            dominance = 0.5
        
        # Сбалансированность через нормализованную энтропию Шеннона
        if len(values) > 1:
            # Нормализуем значения чтобы сумма была 1
            sum_values = sum(values)
            if sum_values > 0:
                norm_values = [v / sum_values for v in values]
                # Энтропия Шеннона
                entropy = -sum(p * math.log(p) for p in norm_values if p > 0)
                # Нормализуем энтропию (max_entropy = log(n))
                max_entropy = math.log(len(values))
                balance = entropy / max_entropy if max_entropy > 0 else 0.5
            else:
                balance = 0.5
        else:
            balance = 0.5
        
        return {
            'stability': round(stability, 3),
            'dominance': round(dominance, 3),
            'balance': round(balance, 3)
        }