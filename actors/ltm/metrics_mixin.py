"""
Metrics collection mixin for LTMActor - handles metrics and logging
"""
from typing import Optional, Dict
import asyncio
from config.settings_ltm import (
    LTM_METRICS_ENABLED,
    LTM_METRICS_LOG_INTERVAL
)


class LTMMetricsMixin:
    """Mixin providing metrics collection and logging for LTMActor"""
    
    # These attributes are available from LTMActor
    logger: object
    is_running: bool
    _degraded_mode: bool
    
    # This will be set by this mixin but declared in main class
    _metrics: Dict[str, int]
    _metrics_task: Optional[asyncio.Task]
    
    def _initialize_metrics(self) -> None:
        """Initialize metrics dictionary and start metrics task if enabled"""
        # Initialize metrics dictionary
        self._metrics = {
            'initialized': False,
            'degraded_mode_entries': 0,
            'save_memory_count': 0,
            'get_memory_count': 0,
            'delete_memory_count': 0,
            'unknown_message_count': 0,
            'db_errors': 0,
            'validation_errors': 0,
            'evaluation_count': 0,
            'evaluation_saved_count': 0,
            'calibration_skip_count': 0,
            'novelty_rejection_count': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
        
        # Start metrics task if enabled
        if LTM_METRICS_ENABLED:
            self._metrics_task = asyncio.create_task(self._metrics_loop())
            self.logger.debug("Metrics task started")
        else:
            self._metrics_task = None
    
    async def _shutdown_metrics(self) -> None:
        """Stop metrics task and log final metrics"""
        # Stop metrics task
        if self._metrics_task and not self._metrics_task.done():
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass
        
        # Log final metrics
        self._log_metrics(final=True)
    
    def _increment_metric(self, metric_name: str, value: int = 1) -> None:
        """Инкремент метрики"""
        if metric_name in self._metrics:
            self._metrics[metric_name] += value
    
    async def _metrics_loop(self) -> None:
        """Периодическое логирование метрик"""
        while self.is_running:
            try:
                await asyncio.sleep(LTM_METRICS_LOG_INTERVAL)
                self._log_metrics()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in metrics loop: {str(e)}")
    
    def _log_metrics(self, final: bool = False) -> None:
        """Логирование метрик"""
        log_msg = "LTMActor metrics"
        if final:
            log_msg = "LTMActor final metrics"
        
        # Calculate cache hit rate
        total_cache_requests = self._metrics['cache_hits'] + self._metrics['cache_misses']
        cache_hit_rate = 0.0
        if total_cache_requests > 0:
            cache_hit_rate = self._metrics['cache_hits'] / total_cache_requests
        
        # Get specific cache hits
        cache_hits_final = self._metrics.get('cache_hits_final', 0)
        cache_hits_embedding = self._metrics.get('cache_hits_embedding', 0)
        cache_hits_knn = self._metrics.get('cache_hits_knn', 0)
        cache_hits_profile = self._metrics.get('cache_hits_profile', 0)
        
        self.logger.info(
            f"{log_msg} - "
            f"Save: {self._metrics['save_memory_count']}, "
            f"Get: {self._metrics['get_memory_count']}, "
            f"Delete: {self._metrics['delete_memory_count']}, "
            f"Eval: {self._metrics['evaluation_count']} "
            f"(saved: {self._metrics['evaluation_saved_count']}), "
            f"Calibration skip: {self._metrics['calibration_skip_count']}, "
            f"Novelty reject: {self._metrics['novelty_rejection_count']}, "
            f"Cache: {self._metrics['cache_hits']}/{self._metrics['cache_misses']} "
            f"(hit rate: {cache_hit_rate:.2%}), "
            f"Cache detail: final={cache_hits_final}, embed={cache_hits_embedding}, "
            f"knn={cache_hits_knn}, profile={cache_hits_profile}, "
            f"Unknown: {self._metrics['unknown_message_count']}, "
            f"DB errors: {self._metrics['db_errors']}, "
            f"Validation errors: {self._metrics['validation_errors']}, "
            f"Degraded mode: {self._degraded_mode}"
        )