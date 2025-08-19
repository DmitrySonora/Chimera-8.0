"""
Сервис для анализа событий резонансной персонализации.
Анализирует эволюцию резонансных профилей и адаптацию личности.
"""
import asyncio
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from config.logging import get_logger
from config.settings import (
    EVENT_REPLAY_DEFAULT_PERIOD_DAYS,
    POSTGRES_COMMAND_TIMEOUT,
    RESONANCE_MAX_DEVIATION,
    RESONANCE_LEARNING_RATE
)
from utils.monitoring import measure_latency


class ResonanceAnalyticsService:
    """
    Сервис для анализа эволюции резонансной персонализации.
    НЕ является актором - это аналитический сервис.
    """
    
    def __init__(self, db_connection):
        """
        Инициализация сервиса.
        
        Args:
            db_connection: Объект подключения к БД
        """
        self.db = db_connection
        self.logger = get_logger("resonance_analytics_service")
        
        # Счетчики метрик
        self._total_analyses = 0
        self._total_events_processed = 0
        self._decompression_errors = 0
    
    @measure_latency
    async def analyze_resonance_evolution(
        self,
        user_id: Optional[str] = None,
        time_period: Optional[timedelta] = None
    ) -> Dict[str, Any]:
        """
        Анализ эволюции резонансных профилей.
        
        Args:
            user_id: ID пользователя (если None - анализ всех пользователей)
            time_period: Период анализа (если None - последние 7 дней)
        
        Returns:
            Словарь с метриками:
            - unique_profiles_count: количество уникальных профилей
            - average_adaptation_rate: средняя скорость адаптации
            - protection_triggers_count: частота срабатывания защит
            - trait_trends: тренды изменения коэффициентов
            - average_deviation: среднее отклонение от нейтрального профиля
            - convergence_speed: скорость конвергенции
        """
        self._total_analyses += 1
        
        # Определяем период анализа
        if time_period is None:
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=EVENT_REPLAY_DEFAULT_PERIOD_DAYS)
        else:
            end_date = datetime.now(timezone.utc)
            start_date = end_date - time_period
        
        # Получаем события резонанса параллельно
        resonance_events_task = self._fetch_resonance_events(
            user_id, start_date, end_date
        )
        adaptation_events_task = self._fetch_adaptation_events(
            user_id, start_date, end_date
        )
        authenticity_events_task = self._fetch_authenticity_events(
            user_id, start_date, end_date
        )
        
        resonance_events, adaptation_events, authenticity_events = await asyncio.gather(
            resonance_events_task,
            adaptation_events_task,
            authenticity_events_task
        )
        
        self._total_events_processed += len(resonance_events) + len(adaptation_events) + len(authenticity_events)
        
        # Анализируем собранные данные
        analysis_result = {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "user_scope": user_id or "all_users",
            "total_events_analyzed": len(resonance_events) + len(adaptation_events) + len(authenticity_events),
            "unique_profiles_count": await self._count_unique_profiles(start_date, end_date, user_id),
            "average_adaptation_rate": self._calculate_adaptation_rate(adaptation_events),
            "protection_triggers_count": self._count_protection_triggers(authenticity_events),
            "trait_trends": self._analyze_trait_trends(resonance_events, adaptation_events),
            "average_deviation": self._calculate_average_deviation(resonance_events),
            "convergence_analysis": self._analyze_convergence(resonance_events, adaptation_events),
            "coefficient_distribution": self._analyze_coefficient_distribution(resonance_events)
        }
        
        self.logger.info(
            f"Resonance analysis completed for {user_id or 'all users'}: "
            f"{analysis_result['total_events_analyzed']} events analyzed"
        )
        
        return analysis_result
    
    @measure_latency
    async def get_user_resonance_history(
        self,
        user_id: str,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Получить историю изменений резонанса конкретного пользователя.
        
        Args:
            user_id: ID пользователя
            limit: Максимальное количество событий
        
        Returns:
            История резонансных коэффициентов и адаптаций
        """
        # Запрос событий резонанса
        resonance_query = """
            SELECT event_type, data, timestamp
            FROM events
            WHERE stream_id = $1
              AND event_type IN ('ResonanceCalculatedEvent', 'PersonalityAdaptationEvent')
              AND archived = FALSE
            ORDER BY timestamp DESC
            LIMIT $2
        """
        
        rows = await self.db.fetch(
            resonance_query,
            f"personality_{user_id}",
            limit,
            timeout=POSTGRES_COMMAND_TIMEOUT
        )
        
        # Формируем историю
        history = {
            "user_id": user_id,
            "timeline": [],
            "current_coefficients": None,
            "total_adaptations": 0,
            "last_adaptation": None
        }
        
        for row in rows:
            event_data = row['data']
            if isinstance(event_data, str):
                event_data = json.loads(event_data)
            
            if row['event_type'] == 'ResonanceCalculatedEvent':
                if history['current_coefficients'] is None:
                    history['current_coefficients'] = event_data.get('resonance_coefficients', {})
                
                history['timeline'].append({
                    "timestamp": row['timestamp'].isoformat(),
                    "type": "calculation",
                    "coefficients": event_data.get('resonance_coefficients', {}),
                    "deviation": event_data.get('total_deviation', 0.0)
                })
            
            elif row['event_type'] == 'PersonalityAdaptationEvent':
                history['total_adaptations'] += 1
                if history['last_adaptation'] is None:
                    history['last_adaptation'] = row['timestamp'].isoformat()
                
                history['timeline'].append({
                    "timestamp": row['timestamp'].isoformat(),
                    "type": "adaptation",
                    "old_coefficients": event_data.get('old_coefficients', {}),
                    "new_coefficients": event_data.get('new_coefficients', {}),
                    "learning_rate": event_data.get('learning_rate', RESONANCE_LEARNING_RATE),
                    "trigger": event_data.get('trigger_reason', 'unknown')
                })
        
        return history
    
    @measure_latency
    async def get_resonance_statistics(
        self,
        time_period: Optional[timedelta] = None
    ) -> Dict[str, Any]:
        """
        Получить общую статистику по резонансной системе.
        
        Args:
            time_period: Период анализа
        
        Returns:
            Статистика использования резонанса
        """
        if time_period is None:
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=EVENT_REPLAY_DEFAULT_PERIOD_DAYS)
        else:
            end_date = datetime.now(timezone.utc)
            start_date = end_date - time_period
        
        # Подсчет активных пользователей с резонансом
        active_users_query = """
            SELECT COUNT(DISTINCT stream_id) as count
            FROM events
            WHERE event_type = 'ResonanceCalculatedEvent'
              AND timestamp BETWEEN $1 AND $2
              AND archived = FALSE
        """
        
        active_users = await self.db.fetchval(
            active_users_query,
            start_date,
            end_date,
            timeout=POSTGRES_COMMAND_TIMEOUT
        ) or 0
        
        # Подсчет адаптаций
        adaptations_query = """
            SELECT COUNT(*) as count
            FROM events
            WHERE event_type = 'PersonalityAdaptationEvent'
              AND timestamp BETWEEN $1 AND $2
              AND archived = FALSE
        """
        
        total_adaptations = await self.db.fetchval(
            adaptations_query,
            start_date,
            end_date,
            timeout=POSTGRES_COMMAND_TIMEOUT
        ) or 0
        
        # Подсчет срабатываний защиты
        protection_query = """
            SELECT COUNT(*) as count
            FROM events
            WHERE event_type = 'AuthenticityCheckEvent'
              AND (data->>'protection_applied')::boolean = true
              AND timestamp BETWEEN $1 AND $2
              AND archived = FALSE
        """
        
        protection_triggers = await self.db.fetchval(
            protection_query,
            start_date,
            end_date,
            timeout=POSTGRES_COMMAND_TIMEOUT
        ) or 0
        
        return {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "active_users_with_resonance": active_users,
            "total_adaptations": total_adaptations,
            "average_adaptations_per_user": total_adaptations / active_users if active_users > 0 else 0,
            "protection_triggers": protection_triggers,
            "protection_rate": protection_triggers / total_adaptations if total_adaptations > 0 else 0
        }
    
    @measure_latency
    async def generate_research_report(
        self,
        time_period: Optional[timedelta] = None,
        user_id: Optional[str] = None,
        include_raw_data: bool = False
    ) -> Dict[str, Any]:
        """
        Генерация исследовательского отчета в JSON формате.
        
        Args:
            time_period: Период анализа (по умолчанию - 7 дней)
            user_id: ID пользователя для фокусированного анализа
            include_raw_data: Включить сырые данные событий
        
        Returns:
            Полный отчет с метриками, трендами и опционально сырыми данными
        """
        # Получаем основную аналитику
        evolution_data = await self.analyze_resonance_evolution(user_id, time_period)
        statistics = await self.get_resonance_statistics(time_period)
        
        # Базовая структура отчета
        report = {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "report_version": "1.0",
                "user_scope": user_id or "all_users",
                "include_raw_data": include_raw_data
            },
            "summary": {
                "period": evolution_data["period"],
                "total_events": evolution_data["total_events_analyzed"],
                "unique_profiles": evolution_data["unique_profiles_count"],
                "active_users": statistics["active_users_with_resonance"]
            },
            "metrics": {
                "adaptation": {
                    "average_rate": evolution_data["average_adaptation_rate"],
                    "total_count": statistics["total_adaptations"],
                    "per_user_average": statistics["average_adaptations_per_user"]
                },
                "protection": {
                    "triggers_count": evolution_data["protection_triggers_count"],
                    "trigger_rate": statistics["protection_rate"]
                },
                "deviation": {
                    "average": evolution_data["average_deviation"],
                    "max_allowed": RESONANCE_MAX_DEVIATION
                }
            },
            "trait_analysis": {
                "trends": evolution_data["trait_trends"],
                "distribution": evolution_data["coefficient_distribution"]
            },
            "convergence": evolution_data["convergence_analysis"]
        }
        
        # Добавляем сырые данные если запрошено
        if include_raw_data:
            # Определяем период
            if time_period is None:
                end_date = datetime.now(timezone.utc)
                start_date = end_date - timedelta(days=EVENT_REPLAY_DEFAULT_PERIOD_DAYS)
            else:
                end_date = datetime.now(timezone.utc)
                start_date = end_date - time_period
            
            # Получаем данные из таблицы адаптаций
            adaptation_history = await self._fetch_adaptation_history_direct(
                user_id, start_date, end_date
            )
            
            report["raw_data"] = {
                "adaptations": adaptation_history[:100],  # Ограничиваем для размера
                "total_raw_records": len(adaptation_history)
            }
        
        # Добавляем рекомендации на основе анализа
        report["insights"] = self._generate_insights(evolution_data, statistics)
        
        return report
    
    def _generate_insights(
        self, 
        evolution_data: Dict[str, Any], 
        statistics: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        """Генерация инсайтов на основе данных."""
        insights = []
        
        # Анализ скорости адаптации
        avg_rate = evolution_data["average_adaptation_rate"]
        if avg_rate > RESONANCE_LEARNING_RATE * 1.5:
            insights.append({
                "type": "warning",
                "message": f"Скорость адаптации ({avg_rate:.3f}) значительно выше базовой ({RESONANCE_LEARNING_RATE})"
            })
        
        # Анализ защитных механизмов
        protection_rate = statistics["protection_rate"]
        if protection_rate > 0.3:
            insights.append({
                "type": "info",
                "message": f"Высокая частота срабатывания защиты ({protection_rate:.1%}). Система активно предотвращает избыточную адаптацию."
            })
        
        # Анализ конвергенции
        convergence = evolution_data["convergence_analysis"]
        if convergence.get("status") != "insufficient_data":
            converging_users = sum(
                1 for m in convergence.get("convergence_metrics", [])
                if m.get("is_converging", False)
            )
            total_analyzed = len(convergence.get("convergence_metrics", []))
            if total_analyzed > 0:
                convergence_rate = converging_users / total_analyzed
                insights.append({
                    "type": "success" if convergence_rate > 0.7 else "info",
                    "message": f"{convergence_rate:.0%} пользователей достигают стабильного резонанса"
                })
        
        return insights
    
    async def _fetch_resonance_events(
        self,
        user_id: Optional[str],
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Получить события ResonanceCalculatedEvent."""
        if user_id:
            query = """
                SELECT data, timestamp
                FROM events
                WHERE stream_id = $1
                  AND event_type = 'ResonanceCalculatedEvent'
                  AND timestamp BETWEEN $2 AND $3
                  AND archived = FALSE
                ORDER BY timestamp ASC
            """
            rows = await self.db.fetch(
                query,
                f"personality_{user_id}",
                start_date,
                end_date,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
        else:
            query = """
                SELECT stream_id, data, timestamp
                FROM events
                WHERE event_type = 'ResonanceCalculatedEvent'
                  AND timestamp BETWEEN $1 AND $2
                  AND archived = FALSE
                ORDER BY timestamp ASC
            """
            rows = await self.db.fetch(
                query,
                start_date,
                end_date,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
        
        events = []
        for row in rows:
            data = row['data']
            if isinstance(data, str):
                data = json.loads(data)
            
            event = {
                'timestamp': row['timestamp'],
                'data': data
            }
            if not user_id:
                # Извлекаем user_id из stream_id
                event['user_id'] = row['stream_id'].replace('personality_', '')
            
            events.append(event)
        
        return events
    
    async def _fetch_adaptation_events(
        self,
        user_id: Optional[str],
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Получить события PersonalityAdaptationEvent."""
        if user_id:
            query = """
                SELECT data, timestamp
                FROM events
                WHERE stream_id = $1
                  AND event_type = 'PersonalityAdaptationEvent'
                  AND timestamp BETWEEN $2 AND $3
                  AND archived = FALSE
                ORDER BY timestamp ASC
            """
            rows = await self.db.fetch(
                query,
                f"personality_{user_id}",
                start_date,
                end_date,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
        else:
            query = """
                SELECT stream_id, data, timestamp
                FROM events
                WHERE event_type = 'PersonalityAdaptationEvent'
                  AND timestamp BETWEEN $1 AND $2
                  AND archived = FALSE
                ORDER BY timestamp ASC
            """
            rows = await self.db.fetch(
                query,
                start_date,
                end_date,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
        
        events = []
        for row in rows:
            data = row['data']
            if isinstance(data, str):
                data = json.loads(data)
            
            event = {
                'timestamp': row['timestamp'],
                'data': data
            }
            if not user_id:
                event['user_id'] = row['stream_id'].replace('personality_', '')
            
            events.append(event)
        
        return events
    
    async def _fetch_authenticity_events(
        self,
        user_id: Optional[str],
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Получить события AuthenticityCheckEvent."""
        if user_id:
            query = """
                SELECT data, timestamp
                FROM events
                WHERE stream_id = $1
                  AND event_type = 'AuthenticityCheckEvent'
                  AND timestamp BETWEEN $2 AND $3
                  AND archived = FALSE
                ORDER BY timestamp ASC
            """
            rows = await self.db.fetch(
                query,
                f"personality_{user_id}",
                start_date,
                end_date,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
        else:
            query = """
                SELECT stream_id, data, timestamp
                FROM events
                WHERE event_type = 'AuthenticityCheckEvent'
                  AND timestamp BETWEEN $1 AND $2
                  AND archived = FALSE
                ORDER BY timestamp ASC
            """
            rows = await self.db.fetch(
                query,
                start_date,
                end_date,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
        
        events = []
        for row in rows:
            data = row['data']
            if isinstance(data, str):
                data = json.loads(data)
            
            event = {
                'timestamp': row['timestamp'],
                'data': data
            }
            if not user_id:
                event['user_id'] = row['stream_id'].replace('personality_', '')
            
            events.append(event)
        
        return events
    
    async def _fetch_adaptation_history_direct(
        self,
        user_id: Optional[str],
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Получить данные напрямую из таблицы истории адаптаций."""
        if user_id:
            query = """
                SELECT 
                    adaptation_id,
                    user_id,
                    old_profile,
                    new_profile,
                    change_delta,
                    style_vector,
                    dominant_emotion,
                    learning_rate,
                    total_change,
                    affected_traits,
                    adapted_at
                FROM resonance_adaptation_history
                WHERE user_id = $1
                  AND adapted_at BETWEEN $2 AND $3
                ORDER BY adapted_at ASC
            """
            rows = await self.db.fetch(
                query,
                user_id,
                start_date,
                end_date,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
        else:
            query = """
                SELECT 
                    adaptation_id,
                    user_id,
                    old_profile,
                    new_profile,
                    change_delta,
                    style_vector,
                    dominant_emotion,
                    learning_rate,
                    total_change,
                    affected_traits,
                    adapted_at
                FROM resonance_adaptation_history
                WHERE adapted_at BETWEEN $1 AND $2
                ORDER BY adapted_at ASC
            """
            rows = await self.db.fetch(
                query,
                start_date,
                end_date,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
        
        # Преобразуем к единому формату
        history_data = []
        for row in rows:
            history_data.append({
                'adaptation_id': str(row['adaptation_id']),
                'user_id': row['user_id'],
                'old_profile': row['old_profile'],
                'new_profile': row['new_profile'],
                'change_delta': row['change_delta'],
                'style_vector': row['style_vector'],
                'dominant_emotion': row['dominant_emotion'],
                'learning_rate': row['learning_rate'],
                'total_change': row['total_change'],
                'affected_traits': row['affected_traits'],
                'timestamp': row['adapted_at']
            })
        
        return history_data
    
    async def _count_unique_profiles(
        self,
        start_date: datetime,
        end_date: datetime,
        user_id: Optional[str]
    ) -> int:
        """Подсчитать количество уникальных профилей резонанса."""
        if user_id:
            # Для конкретного пользователя считаем версии его профиля
            query = """
                SELECT COUNT(DISTINCT profile_version) as count
                FROM user_personality_resonance
                WHERE user_id = $1
                  AND updated_at BETWEEN $2 AND $3
                  AND is_active = true
            """
            count = await self.db.fetchval(
                query,
                user_id,
                start_date,
                end_date,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
        else:
            # Для всех пользователей считаем активные профили
            query = """
                SELECT COUNT(*) as count
                FROM user_personality_resonance
                WHERE updated_at BETWEEN $1 AND $2
                  AND is_active = true
            """
            count = await self.db.fetchval(
                query,
                start_date,
                end_date,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
        
        return count or 0
    
    def _calculate_adaptation_rate(self, adaptation_events: List[Dict[str, Any]]) -> float:
        """Вычислить среднюю скорость адаптации."""
        if not adaptation_events:
            return 0.0
        
        total_rate = 0.0
        count = 0
        
        for event in adaptation_events:
            data = event['data']
            learning_rate = data.get('learning_rate', RESONANCE_LEARNING_RATE)
            total_rate += learning_rate
            count += 1
        
        return total_rate / count if count > 0 else 0.0
    
    def _count_protection_triggers(self, authenticity_events: List[Dict[str, Any]]) -> int:
        """Подсчитать количество срабатываний защиты."""
        count = 0
        for event in authenticity_events:
            data = event['data']
            if data.get('protection_applied', False):
                count += 1
        return count
    
    def _analyze_trait_trends(
        self,
        resonance_events: List[Dict[str, Any]],
        adaptation_events: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Анализировать тренды изменения черт."""
        trait_changes = defaultdict(list)
        
        # Собираем изменения из адаптаций
        for event in adaptation_events:
            data = event['data']
            old_coeffs = data.get('old_coefficients', {})
            new_coeffs = data.get('new_coefficients', {})
            
            for trait in new_coeffs:
                if trait in old_coeffs:
                    change = new_coeffs[trait] - old_coeffs[trait]
                    trait_changes[trait].append({
                        'timestamp': event['timestamp'],
                        'change': change,
                        'new_value': new_coeffs[trait]
                    })
        
        # Вычисляем тренды
        trends = {}
        for trait, changes in trait_changes.items():
            if len(changes) >= 2:
                # Простой линейный тренд
                total_change = sum(c['change'] for c in changes)
                avg_change = total_change / len(changes)
                
                trends[trait] = {
                    'total_change': total_change,
                    'average_change_per_adaptation': avg_change,
                    'direction': 'increasing' if avg_change > 0 else 'decreasing',
                    'adaptations_count': len(changes)
                }
        
        return trends
    
    def _calculate_average_deviation(self, resonance_events: List[Dict[str, Any]]) -> float:
        """Вычислить среднее отклонение от нейтрального профиля."""
        if not resonance_events:
            return 0.0
        
        total_deviation = 0.0
        count = 0
        
        for event in resonance_events:
            data = event['data']
            deviation = data.get('total_deviation', 0.0)
            total_deviation += deviation
            count += 1
        
        return total_deviation / count if count > 0 else 0.0
    
    def _analyze_convergence(
        self,
        resonance_events: List[Dict[str, Any]],
        adaptation_events: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Анализировать скорость конвергенции к стабильному состоянию."""
        if len(adaptation_events) < 2:
            return {
                'status': 'insufficient_data',
                'adaptations_count': len(adaptation_events)
            }
        
        # Группируем по пользователям
        user_adaptations = defaultdict(list)
        for event in adaptation_events:
            user_id = event.get('user_id', event['data'].get('user_id'))
            user_adaptations[user_id].append(event)
        
        convergence_data = {
            'users_analyzed': len(user_adaptations),
            'average_adaptations_per_user': len(adaptation_events) / len(user_adaptations),
            'convergence_metrics': []
        }
        
        # Анализируем конвергенцию для каждого пользователя
        for user_id, user_events in user_adaptations.items():
            if len(user_events) >= 2:
                # Вычисляем изменения между адаптациями
                changes = []
                for i in range(1, len(user_events)):
                    prev_coeffs = user_events[i-1]['data'].get('new_coefficients', {})
                    curr_coeffs = user_events[i]['data'].get('new_coefficients', {})
                    
                    # Вычисляем среднее изменение
                    total_change = 0.0
                    traits_count = 0
                    for trait in curr_coeffs:
                        if trait in prev_coeffs:
                            change = abs(curr_coeffs[trait] - prev_coeffs[trait])
                            total_change += change
                            traits_count += 1
                    
                    if traits_count > 0:
                        avg_change = total_change / traits_count
                        changes.append(avg_change)
                
                if changes:
                    # Проверяем, уменьшаются ли изменения (конвергенция)
                    is_converging = all(changes[i] <= changes[i-1] for i in range(1, len(changes)))
                    
                    convergence_data['convergence_metrics'].append({
                        'user_id': user_id,
                        'is_converging': is_converging,
                        'final_change_rate': changes[-1] if changes else 0.0,
                        'change_reduction': (changes[0] - changes[-1]) / changes[0] if changes[0] > 0 else 0.0
                    })
        
        return convergence_data
    
    def _analyze_coefficient_distribution(self, resonance_events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Анализировать распределение коэффициентов по чертам."""
        trait_coefficients = defaultdict(list)
        
        # Собираем все коэффициенты по чертам
        for event in resonance_events:
            data = event['data']
            coeffs = data.get('resonance_coefficients', {})
            
            for trait, coeff in coeffs.items():
                trait_coefficients[trait].append(coeff)
        
        # Вычисляем статистику для каждой черты
        distribution = {}
        for trait, coeffs in trait_coefficients.items():
            if coeffs:
                avg = sum(coeffs) / len(coeffs)
                min_val = min(coeffs)
                max_val = max(coeffs)
                
                # Вычисляем стандартное отклонение
                variance = sum((x - avg) ** 2 for x in coeffs) / len(coeffs)
                std_dev = variance ** 0.5
                
                distribution[trait] = {
                    'average': avg,
                    'min': min_val,
                    'max': max_val,
                    'std_deviation': std_dev,
                    'samples_count': len(coeffs),
                    'deviation_from_neutral': abs(avg - 1.0)  # 1.0 - нейтральный коэффициент
                }
        
        return distribution
    
    def get_metrics(self) -> Dict[str, int]:
        """
        Получить метрики работы сервиса.
        
        Returns:
            Словарь с метриками
        """
        return {
            "total_analyses": self._total_analyses,
            "total_events_processed": self._total_events_processed,
            "decompression_errors": self._decompression_errors
        }