"""
Сервис анализа эмоциональных паттернов.
Использует EventReplayService для получения событий и кэширует результаты.
"""
import asyncio
import json
import time
from typing import Dict, Any, Tuple, Optional
from datetime import datetime
import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from scipy import stats

from config.logging import get_logger
from utils.monitoring import measure_latency
from config.settings import (
    ANALYSIS_MAX_EVENTS_PER_USER,
    ANALYSIS_CACHE_TABLE,
    ANOMALY_Z_SCORE_THRESHOLD,
    POSTGRES_COMMAND_TIMEOUT
)
from config.settings_emo import EMOTION_LABELS


class EmotionalAnalyticsService:
    """
    Сервис анализа эмоциональных паттернов.
    Использует EventReplayService для получения событий.
    """
    
    def __init__(self, db_connection, event_replay_service):
        """
        Args:
            db_connection: Подключение к БД для кэша и ltm_memories
            event_replay_service: Инстанс EventReplayService для событий
        """
        self.db = db_connection
        self.event_service = event_replay_service
        self.logger = get_logger("emotional_analytics")
    
    @measure_latency
    async def analyze_emotional_patterns(
        self,
        user_id: str,
        period: Tuple[datetime, datetime],
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Комплексный анализ эмоциональных паттернов.
        
        Returns:
            {
                'metadata': {...},
                'baseline_stats': {...},
                'peaks_stats': {...},
                'patterns': {...}
            }
        """
        start_time = time.time()
        start_date, end_date = period
        
        self.logger.info(
            f"Starting emotional analysis for user {user_id}, "
            f"period {start_date} to {end_date}"
        )
        
        # 1. Проверить кэш если нужно
        if use_cache:
            cached_result = await self._get_from_cache(user_id, period)
            if cached_result:
                self.logger.info(f"Returning cached analysis for user {user_id}")
                return cached_result
        
        # 2. Параллельно получить baseline и peaks данные
        try:
            baseline_data, peaks_data = await asyncio.gather(
                self._get_baseline_data(user_id, start_date, end_date),
                self._get_peaks_data(user_id, start_date, end_date),
                return_exceptions=True
            )
            
            # Проверяем на исключения
            if isinstance(baseline_data, Exception):
                self.logger.error(f"Baseline data error: {baseline_data}")
                baseline_data = {
                    'vectors': np.array([]),
                    'stats': {
                        'total_messages': 0,
                        'avg_emotions': {},
                        'dominant_emotions': []
                    }
                }
            
            if isinstance(peaks_data, Exception):
                self.logger.error(f"Peaks data error: {peaks_data}")
                peaks_data = {
                    'vectors': np.array([]),
                    'stats': {
                        'total_ltm_memories': 0,
                        'trigger_distribution': {},
                        'avg_emotions': {}
                    }
                }
                
        except Exception as e:
            self.logger.error(f"Error getting emotion data: {e}")
            return self._empty_result()
        
        # 3. Выполнить анализ паттернов
        try:
            patterns = await self._analyze_patterns(
                baseline_data['vectors'], 
                peaks_data['vectors']
            )
        except Exception as e:
            self.logger.error(f"Error analyzing patterns: {e}")
            patterns = {}
        
        # 4. Сформировать результат
        processing_time = int((time.time() - start_time) * 1000)
        total_events = len(baseline_data['vectors']) + len(peaks_data['vectors'])
        
        result = {
            'metadata': {
                'user_id': user_id,
                'period_start': start_date.isoformat(),
                'period_end': end_date.isoformat(),
                'processing_time_ms': processing_time,
                'events_processed': total_events,
                'cache_used': False
            },
            'baseline_stats': baseline_data['stats'],
            'peaks_stats': peaks_data['stats'],
            'patterns': patterns
        }
        
        # 5. Сохранить в кэш
        try:
            await self._save_to_cache(user_id, period, result, processing_time, total_events)
        except Exception as e:
            self.logger.error(f"Error saving to cache: {e}")
        
        self.logger.info(
            f"Completed analysis for user {user_id}: "
            f"{total_events} events, {processing_time}ms"
        )
        
        return result
    
    async def _get_baseline_data(
        self, 
        user_id: str, 
        start_date: datetime, 
        end_date: datetime
    ) -> Dict[str, Any]:
        """Получить baseline данные через EventReplayService."""
        
        self.logger.debug(f"Getting baseline data for user {user_id}")
        
        # Получаем события эмоций
        events = await self.event_service.replay_user_events(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            event_types=['EmotionDetectedEvent']
        )
        
        if not events:
            return {
                'vectors': np.array([]),
                'stats': {
                    'total_messages': 0,
                    'avg_emotions': {},
                    'dominant_emotions': []
                }
            }
        
        # Ограничиваем количество событий
        if len(events) > ANALYSIS_MAX_EVENTS_PER_USER:
            events = events[-ANALYSIS_MAX_EVENTS_PER_USER:]
            self.logger.warning(
                f"Limited baseline events to {ANALYSIS_MAX_EVENTS_PER_USER} for user {user_id}"
            )
        
        # Извлекаем 28d векторы эмоций
        vectors = []
        for event in events:
            emotion_scores = event.data.get('emotion_scores', {})
            # Конвертируем в правильном порядке EMOTION_LABELS
            vector = [
                emotion_scores.get(emotion, 0.0) 
                for emotion in EMOTION_LABELS
            ]
            vectors.append(vector)
        
        vectors_array = np.array(vectors)  # shape (N, 28)
        
        # Вычисляем статистику
        if len(vectors_array) > 0:
            avg_emotions = {
                emotion: float(vectors_array[:, i].mean())
                for i, emotion in enumerate(EMOTION_LABELS)
            }
            
            # Топ-5 доминирующих эмоций
            emotion_sums = {
                emotion: float(vectors_array[:, i].sum())
                for i, emotion in enumerate(EMOTION_LABELS)
            }
            dominant_emotions = sorted(
                emotion_sums.items(), 
                key=lambda x: x[1], 
                reverse=True
            )[:5]
            
        else:
            avg_emotions = {}
            dominant_emotions = []
        
        stats = {
            'total_messages': len(events),
            'avg_emotions': avg_emotions,
            'dominant_emotions': [
                {'emotion': emotion, 'score': score} 
                for emotion, score in dominant_emotions
            ]
        }
        
        self.logger.debug(f"Baseline: {len(vectors_array)} vectors extracted")
        
        return {
            'vectors': vectors_array,
            'stats': stats
        }
    
    async def _get_peaks_data(
        self, 
        user_id: str, 
        start_date: datetime, 
        end_date: datetime
    ) -> Dict[str, Any]:
        """Получить peaks данные из ltm_memories."""
        
        self.logger.debug(f"Getting peaks data for user {user_id}")
        
        # Прямой SQL запрос к ltm_memories
        query = """
            SELECT emotional_snapshot, created_at, trigger_reason
            FROM ltm_memories
            WHERE user_id = $1 AND created_at BETWEEN $2 AND $3
            ORDER BY created_at
        """
        
        try:
            rows = await self.db.fetch(
                query, user_id, start_date, end_date,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
        except Exception as e:
            self.logger.error(f"Error querying ltm_memories: {e}")
            rows = []
        
        if not rows:
            return {
                'vectors': np.array([]),
                'stats': {
                    'total_ltm_memories': 0,
                    'trigger_distribution': {},
                    'avg_emotions': {}
                }
            }
        
        # Извлекаем emotional_snapshot (JSONB, но может быть строкой)
        vectors = []
        trigger_counts = {}
        
        for row in rows:
            emotional_snapshot = row['emotional_snapshot']
            trigger_reason = row['trigger_reason'] or 'unknown'
            
            # Парсим JSON-строку в dict если нужно
            if isinstance(emotional_snapshot, str):
                try:
                    emotional_snapshot = json.loads(emotional_snapshot)
                except json.JSONDecodeError:
                    self.logger.error(f"Failed to parse emotional_snapshot: {emotional_snapshot}")
                    continue
            
            # emotional_snapshot должен быть dict с эмоциями
            if isinstance(emotional_snapshot, dict) and emotional_snapshot:
                vector = [
                    emotional_snapshot.get(emotion, 0.0)
                    for emotion in EMOTION_LABELS
                ]
                vectors.append(vector)
                
                # Считаем триггеры
                trigger_counts[trigger_reason] = trigger_counts.get(trigger_reason, 0) + 1
        
        vectors_array = np.array(vectors)  # shape (N, 28)
        
        # Вычисляем статистику
        if len(vectors_array) > 0:
            avg_emotions = {
                emotion: float(vectors_array[:, i].mean())
                for i, emotion in enumerate(EMOTION_LABELS)
            }
        else:
            avg_emotions = {}
        
        stats = {
            'total_ltm_memories': len(rows),
            'trigger_distribution': trigger_counts,
            'avg_emotions': avg_emotions
        }
        
        self.logger.debug(f"Peaks: {len(vectors_array)} vectors extracted")
        
        return {
            'vectors': vectors_array,
            'stats': stats
        }
    
    async def _analyze_patterns(
        self, 
        baseline_vectors: np.ndarray, 
        peaks_vectors: np.ndarray
    ) -> Dict[str, Any]:
        """Анализ паттернов (упрощенная версия)."""
        
        patterns = {}
        
        # K-means кластеризация (если >= 30 событий)
        if len(baseline_vectors) >= 30:
            try:
                kmeans = KMeans(n_clusters=5, random_state=42, n_init=10)
                clusters = kmeans.fit_predict(baseline_vectors)
                
                # Силуэт
                silhouette = silhouette_score(baseline_vectors, clusters)
                
                # Размеры кластеров
                unique, counts = np.unique(clusters, return_counts=True)
                cluster_sizes = {f"cluster_{i}": int(count) for i, count in zip(unique, counts)}
                
                patterns['clusters'] = {
                    'n_clusters': 5,
                    'cluster_sizes': cluster_sizes,
                    'silhouette_score': float(silhouette)
                }
                
                self.logger.debug(f"K-means completed: silhouette={silhouette:.3f}")
                
            except Exception as e:
                self.logger.error(f"K-means clustering failed: {e}")
                patterns['clusters'] = {}
        else:
            patterns['clusters'] = {}
            self.logger.debug(f"Skipping clustering: only {len(baseline_vectors)} baseline events")
        
        # Сравнение baseline vs peaks (LTM triggers)
        if len(baseline_vectors) > 0 and len(peaks_vectors) > 0:
            try:
                # Средние значения по каждой эмоции
                baseline_means = baseline_vectors.mean(axis=0)
                peaks_means = peaks_vectors.mean(axis=0)
                
                # Significance multipliers (сколько раз чаще в LTM)
                ltm_triggers = {}
                for i, emotion in enumerate(EMOTION_LABELS):
                    baseline_val = baseline_means[i] + 0.001  # избегаем деления на 0
                    peaks_val = peaks_means[i]
                    multiplier = peaks_val / baseline_val
                    ltm_triggers[emotion] = float(multiplier)
                
                # Топ-5 триггеров
                top_triggers = sorted(
                    ltm_triggers.items(), 
                    key=lambda x: x[1], 
                    reverse=True
                )[:5]
                
                patterns['ltm_triggers'] = dict(top_triggers)
                
                self.logger.debug(f"LTM triggers calculated: {len(top_triggers)} emotions")
                
            except Exception as e:
                self.logger.error(f"LTM triggers analysis failed: {e}")
                patterns['ltm_triggers'] = {}
        else:
            patterns['ltm_triggers'] = {}
        
        # Детекция аномалий через Z-score
        if len(baseline_vectors) > 10:
            try:
                # Z-scores для каждого события
                z_scores = np.abs(stats.zscore(baseline_vectors, axis=0))
                
                # Находим аномалии (любая эмоция > threshold)
                anomaly_mask = (z_scores > ANOMALY_Z_SCORE_THRESHOLD).any(axis=1)
                anomaly_indices = np.where(anomaly_mask)[0]
                
                # Максимум 10 аномалий, сортируем по максимальному Z-score
                if len(anomaly_indices) > 0:
                    max_z_scores = z_scores[anomaly_indices].max(axis=1)
                    sorted_indices = anomaly_indices[np.argsort(max_z_scores)[::-1]]
                    
                    anomalies = []
                    for idx in sorted_indices[:10]:  # Максимум 10
                        anomalies.append({
                            'event_index': int(idx),
                            'z_score': float(max_z_scores[idx == anomaly_indices][0])
                        })
                    
                    patterns['anomalies'] = anomalies
                else:
                    patterns['anomalies'] = []
                
                self.logger.debug(f"Anomaly detection: {len(patterns['anomalies'])} anomalies found")
                
            except Exception as e:
                self.logger.error(f"Anomaly detection failed: {e}")
                patterns['anomalies'] = []
        else:
            patterns['anomalies'] = []
        
        return patterns
    
    async def _get_from_cache(
        self, 
        user_id: str, 
        period: Tuple[datetime, datetime]
    ) -> Optional[Dict[str, Any]]:
        """Проверить наличие в кэше."""
        
        start_date, end_date = period
        
        query = f"""
            SELECT analysis_data
            FROM {ANALYSIS_CACHE_TABLE}
            WHERE user_id = $1 
              AND analysis_type = 'full'
              AND period_start = $2 
              AND period_end = $3
              AND expires_at > CURRENT_TIMESTAMP
        """
        
        try:
            row = await self.db.fetchrow(
                query, user_id, start_date, end_date,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
            
            if row:
                analysis_data = row['analysis_data']
                
                # Помечаем что использовался кэш
                if isinstance(analysis_data, dict):
                    analysis_data['metadata']['cache_used'] = True
                    self.logger.debug(f"Cache hit for user {user_id}")
                    return analysis_data
                    
        except Exception as e:
            self.logger.error(f"Error reading from cache: {e}")
        
        return None
    
    async def _save_to_cache(
        self, 
        user_id: str, 
        period: Tuple[datetime, datetime], 
        result: Dict[str, Any],
        processing_time_ms: int,
        events_processed: int
    ) -> None:
        """Сохранить результат в кэш."""
        
        start_date, end_date = period
        
        try:
            await self.db.fetchval(
                "SELECT upsert_analysis_cache($1, $2, $3, $4, $5, $6, $7)",
                user_id,
                'full',  # analysis_type
                start_date,
                end_date,
                json.dumps(result),
                processing_time_ms,
                events_processed,
                timeout=POSTGRES_COMMAND_TIMEOUT
            )
            
            self.logger.debug(f"Saved analysis to cache for user {user_id}")
            
        except Exception as e:
            self.logger.error(f"Error saving to cache: {e}")
    
    def _empty_result(self) -> Dict[str, Any]:
        """Возвращает пустой результат при ошибках."""
        return {
            'metadata': {
                'events_processed': 0,
                'processing_time_ms': 0,
                'cache_used': False
            },
            'baseline_stats': {
                'total_messages': 0,
                'avg_emotions': {},
                'dominant_emotions': []
            },
            'peaks_stats': {
                'total_ltm_memories': 0,
                'trigger_distribution': {},
                'avg_emotions': {}
            },
            'patterns': {
                'clusters': {},
                'ltm_triggers': {},
                'anomalies': []
            }
        }