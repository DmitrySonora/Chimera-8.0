"""
Event recording mixin for PersonalityActor - handles fire-and-forget resonance events
"""
import json
from typing import Optional, Dict, List
from datetime import datetime

from config.settings import (
    RESONANCE_ENABLED
)


class PersonalityResonanceEventsMixin:
    """
    Mixin providing fire-and-forget event recording methods for resonance.
    
    These methods are called via asyncio.create_task and don't block main flow.
    
    Expected attributes from PersonalityActor:
    - logger: logging object
    - _pool: database connection pool
    - _metrics: Dict[str, int] - metrics dictionary
    - _resonance_profiles: Dict[str, Dict[str, float]]
    - _interaction_counts: Dict[str, int]
    """
    
    async def _record_interaction_event(
        self,
        user_id: str,
        resonance_coefficients: Dict[str, float],
        user_style: Optional[Dict[str, float]],
        emotion_data: Optional[Dict[str, float]]
    ) -> None:
        """
        Record interaction event for future learning (fire-and-forget).
        
        Args:
            user_id: Telegram user ID
            resonance_coefficients: Applied resonance coefficients
            user_style: User style vector (4 components) 
            emotion_data: Emotion distribution if available
        """
        if not RESONANCE_ENABLED or self._pool is None:
            return
        
        try:
            # Get user style (with database fallback)
            style_for_event = await self._get_user_style(user_id)
            
            # Find dominant emotion if available
            dominant_emotion = None
            emotion_intensity = 0.0
            if emotion_data:
                dominant_emotion, emotion_intensity = max(
                    emotion_data.items(), 
                    key=lambda x: x[1]
                )
            
            # Prepare event data
            event_data = {
                'style': style_for_event or {},
                'emotion': dominant_emotion,
                'emotion_intensity': emotion_intensity,
                'applied_coefficients': resonance_coefficients,
                'total_deviation': sum(
                    abs(coeff - 1.0) for coeff in resonance_coefficients.values()
                )
            }
            
            # Get session_id from correlation_id if available
            session_id = None
            if hasattr(self, '_current_correlation_id') and self._current_correlation_id:
                session_id = self._current_correlation_id
            
            # Insert into resonance_learning_events (fire-and-forget)
            query = """
                INSERT INTO resonance_learning_events (
                    user_id,
                    event_type,
                    event_data,
                    session_id,
                    message_count,
                    current_resonance,
                    occurred_at
                ) VALUES ($1, $2, $3::jsonb, $4, $5, $6::jsonb, CURRENT_TIMESTAMP)
            """
            
            await self._pool.execute(
                query,
                user_id,
                'interaction',
                json.dumps(event_data),
                session_id,
                self._interaction_counts.get(user_id, 0),
                json.dumps(resonance_coefficients)
            )
            
            self._metrics['resonance_events_recorded'] = self._metrics.get('resonance_events_recorded', 0) + 1
            
        except Exception as e:
            # Log error but don't fail - this is fire-and-forget
            self.logger.error(f"Failed to record interaction event for user {user_id}: {str(e)}")
            self._metrics['resonance_event_errors'] = self._metrics.get('resonance_event_errors', 0) + 1
    
    async def _mark_events_processed(self, user_id: str, event_timestamps: List[datetime]) -> None:
        """
        Mark interaction events as processed after adaptation.
        
        Args:
            user_id: Telegram user ID
            event_timestamps: List of event timestamps to mark
        """
        if not self._pool or not event_timestamps:
            return
            
        try:
            query = """
                UPDATE resonance_learning_events
                SET processed = TRUE, processed_at = CURRENT_TIMESTAMP
                WHERE user_id = $1 
                AND occurred_at = ANY($2::timestamptz[])
                AND event_type = 'interaction'
            """
            
            await self._pool.execute(query, user_id, event_timestamps)
            
        except Exception as e:
            self.logger.error(f"Failed to mark events as processed: {str(e)}")
    
    async def _create_initial_resonance_profile(self, user_id: str, profile: Dict[str, float]) -> None:
        """
        Create initial resonance profile in database.
        
        Args:
            user_id: Telegram user ID
            profile: Initial profile (all 1.0)
        """
        if not self._pool:
            return
            
        try:
            query = """
                INSERT INTO user_personality_resonance (
                    user_id, 
                    resonance_profile,
                    interaction_count,
                    created_at,
                    updated_at
                ) VALUES ($1, $2::jsonb, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO NOTHING
            """
            
            await self._pool.execute(
                query,
                user_id,
                json.dumps(profile)
            )
            
            self.logger.debug(f"Created initial resonance profile in DB for user {user_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to create initial resonance profile: {str(e)}")