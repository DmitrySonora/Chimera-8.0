"""
Resonance mixin for PersonalityActor - handles long-term personality adaptation
"""
import asyncio
import json
from typing import Optional, Dict
from datetime import datetime, timezone

from config.settings import (
    RESONANCE_ENABLED,
    RESONANCE_LEARNING_RATE,
    RESONANCE_NOISE_LEVEL,
    PERSONALITY_QUERY_TIMEOUT,
    RESONANCE_ADAPTATION_INTERVAL,
    RESONANCE_MIN_ADAPTATION_INTERVAL_HOURS,
    RESONANCE_MAX_TOTAL_CHANGE
)
from config.vocabulary_resonance_matrix import (
    calculate_resonance_impact,
    add_resonance_noise,
    CORE_TRAITS,
    RESONANCE_MIN_COEFFICIENT,
    RESONANCE_MAX_COEFFICIENT
)
from actors.events.personality_events import ResonanceCalculatedEvent, PersonalityAdaptationEvent


class PersonalityResonanceMixin:
    """
    Mixin providing resonance personalization methods for PersonalityActor.
    
    Manages long-term adaptation of personality traits to specific users
    through resonance coefficients that slowly evolve based on interactions.
    
    Available attributes from PersonalityActor:
    - logger: logging object
    - _pool: database connection pool
    - _redis: Redis client (optional)
    - _metrics: Dict[str, int] - metrics dictionary
    - _base_traits: Dict[str, Dict[str, Any]] - base personality traits
    - _current_modifiers: Dict[str, Dict[str, Any]] - current context modifiers
    - _event_version_manager: EventVersionManager instance
    
    Attributes that need to be initialized in PersonalityActor.__init__:
    - _resonance_profiles: Dict[str, Dict[str, float]] - user_id -> {trait: coefficient}
    - _interaction_counts: Dict[str, int] - user_id -> interaction count
    - _last_adaptations: Dict[str, datetime] - user_id -> last adaptation timestamp
    """
    
    async def _load_resonance_profiles(self) -> None:
        """
        Load active resonance profiles from database at startup.
        
        Populates _resonance_profiles with data from user_personality_resonance table.
        Sets default values (1.0) for all traits if no profile exists.
        Implements graceful degradation on database errors.
        """
        if not RESONANCE_ENABLED:
            self.logger.info("Resonance personalization is disabled")
            return
            
        if self._pool is None:
            self.logger.warning("Cannot load resonance profiles: database pool not initialized")
            return
        
        try:
            # Load only active profiles
            query = """
                SELECT user_id, resonance_profile, interaction_count, last_adaptation
                FROM user_personality_resonance  
                WHERE is_active = TRUE
            """
            
            rows = await self._pool.fetch(query, timeout=PERSONALITY_QUERY_TIMEOUT)
            
            loaded_count = 0
            for row in rows:
                user_id = row['user_id']
                
                # resonance_profile is JSONB, should be auto-deserialized to dict
                profile = row['resonance_profile'] or {}
                
                # Ensure profile is dict, not string
                if isinstance(profile, str):
                    try:
                        profile = json.loads(profile)
                    except json.JSONDecodeError:
                        self.logger.error(f"Invalid JSON in resonance_profile for user {user_id}")
                        profile = {}
                
                # Ensure all traits have coefficients
                for trait_name in self._base_traits.keys():
                    if trait_name not in profile:
                        profile[trait_name] = 1.0
                
                # Check and fix any coefficients outside allowed range
                needs_correction = False
                for trait_name, coefficient in profile.items():
                    if coefficient > RESONANCE_MAX_COEFFICIENT:
                        profile[trait_name] = RESONANCE_MAX_COEFFICIENT
                        needs_correction = True
                        self.logger.warning(
                            f"Corrected excessive resonance for {trait_name}: "
                            f"{coefficient:.3f} -> {RESONANCE_MAX_COEFFICIENT} (user: {user_id})"
                        )
                    elif coefficient < RESONANCE_MIN_COEFFICIENT:
                        profile[trait_name] = RESONANCE_MIN_COEFFICIENT
                        needs_correction = True
                        self.logger.warning(
                            f"Corrected low resonance for {trait_name}: "
                            f"{coefficient:.3f} -> {RESONANCE_MIN_COEFFICIENT} (user: {user_id})"
                        )
                
                # Save corrected profile back to DB if needed
                if needs_correction:
                    asyncio.create_task(
                        self._save_resonance_profile(user_id, profile)
                    )
                
                self._resonance_profiles[user_id] = profile
                self._interaction_counts[user_id] = row['interaction_count'] or 0
                
                if row['last_adaptation']:
                    self._last_adaptations[user_id] = row['last_adaptation']
                
                loaded_count += 1
            
            # Update metrics
            self._metrics['resonance_profiles_loaded'] = loaded_count
            
            self.logger.info(f"Loaded {loaded_count} resonance profiles from database")
            
        except Exception as e:
            self.logger.error(f"Failed to load resonance profiles: {str(e)}")
            self._metrics['db_errors'] += 1
            # Continue working without resonance data - graceful degradation
    
    async def _get_user_resonance(self, user_id: str) -> Dict[str, float]:
        """
        Get resonance profile for a specific user.
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Dict mapping trait names to resonance coefficients (0.7-1.3).
            Returns default profile (all 1.0) if user has no stored profile.
        """
        if not RESONANCE_ENABLED:
            # Return neutral resonance when disabled
            return {trait_name: 1.0 for trait_name in list(self._base_traits.keys())}
        
        # Check in-memory cache first
        if user_id in self._resonance_profiles:
            self._metrics['resonance_cache_hits'] += 1
            cached_profile = self._resonance_profiles[user_id]
            
            # Safety check: ensure it's a dict
            if not isinstance(cached_profile, dict):
                self.logger.error(f"Cached profile is not a dict for user {user_id}: {type(cached_profile)}")
                # Reset to default
                cached_profile = {trait_name: 1.0 for trait_name in list(self._base_traits.keys())}
                self._resonance_profiles[user_id] = cached_profile
            
            return cached_profile.copy()
        
        self._metrics['resonance_cache_misses'] += 1
        
        # Create default profile for new user
        default_profile = {
            trait_name: 1.0 
            for trait_name in self._base_traits.keys()
        }
        
        # Cache it in memory
        self._resonance_profiles[user_id] = default_profile.copy()
        self._interaction_counts[user_id] = 0
        
        # Create initial record in DB (fire-and-forget)
        if self._pool:
            asyncio.create_task(self._create_initial_resonance_profile(user_id, default_profile))
        
        # Check if we should apply inactivity decay for existing users
        if user_id in self._last_adaptations:
            asyncio.create_task(self._apply_inactivity_decay(user_id))
        
        self.logger.debug(f"Created default resonance profile for user {user_id}")
        
        return default_profile

    async def _create_initial_resonance_profile(
        self, 
        user_id: str, 
        profile: Dict[str, float]
    ) -> None:
        """
        Create initial resonance profile in database.
        
        Args:
            user_id: Telegram user ID
            profile: Default resonance profile (all 1.0)
        """
        if not self._pool:
            return
            
        try:
            await self._pool.execute(
                """
                INSERT INTO user_personality_resonance 
                (user_id, resonance_profile, interaction_count, created_at, updated_at)
                VALUES ($1, $2::jsonb, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO NOTHING
                """,
                user_id,
                json.dumps(profile)
            )
            self.logger.debug(f"Created initial resonance profile for user {user_id}")
        except Exception as e:
            self.logger.error(f"Failed to create initial resonance profile: {str(e)}")
    
    async def _apply_resonance(
        self, 
        profile: Dict[str, float], 
        user_id: str
    ) -> Dict[str, float]:
        """
        Apply resonance coefficients to personality profile.
        
        This is the main method that modifies personality traits based on
        user-specific resonance. Called as the final step before normalization.
        
        Args:
            profile: Current personality profile {trait: value}
            user_id: Telegram user ID
            
        Returns:
            Modified profile with resonance applied
        """
        if not RESONANCE_ENABLED:
            return profile
        
        try:
            # Ensure we have actor system for fire-and-forget tasks
            if not self.get_actor_system():
                self.logger.warning("No actor system available for fire-and-forget tasks")
            # Get user's resonance coefficients
            resonance_coeffs = await self._get_user_resonance(user_id)
            
            # Check and adjust resonance deviation limits
            within_limits, adjusted_coeffs = self._check_resonance_deviation(
                resonance_coeffs, user_id
            )
            if not within_limits:
                self.logger.info(
                    f"Resonance coefficients adjusted for user {user_id} to maintain authenticity"
                )
                resonance_coeffs = adjusted_coeffs
            
            # Add controlled noise for liveliness
            resonance_coeffs = self._add_resonance_noise(resonance_coeffs)
            
            # Get user style for event data
            user_style = await self._get_user_style(user_id)
            
            # Apply resonance to each trait
            resonated_profile = {}
            for trait, base_value in profile.items():
                coefficient = resonance_coeffs.get(trait, 1.0)
                resonated_value = base_value * coefficient
                
                # Ensure values stay within reasonable bounds (0.0-1.0)
                resonated_profile[trait] = max(0.0, min(1.0, resonated_value))
            
            # Calculate total deviation for metrics
            total_deviation = sum(
                abs(resonance_coeffs.get(trait, 1.0) - 1.0) 
                for trait in profile.keys()
            )
            
            # Create event for tracking
            correlation_id = None
            if hasattr(self, '_current_correlation_id'):
                correlation_id = self._current_correlation_id
            
            event = ResonanceCalculatedEvent.create(
                user_id=user_id,
                resonance_coefficients=resonance_coeffs,
                user_style=user_style or {},
                total_deviation=total_deviation,
                affected_traits=list(resonance_coeffs.keys()),
                correlation_id=correlation_id
            )
            
            await self._event_version_manager.append_event(event, self.get_actor_system())
            
            # Update metrics
            self._metrics['resonance_applications'] += 1
            
            # Increment interaction counter (for future adaptation)
            if user_id in self._interaction_counts:
                self._interaction_counts[user_id] += 1
            
            # Record interaction for future learning (fire-and-forget)
            emotion_data = None
            if user_id in self._current_modifiers and 'emotion' in self._current_modifiers[user_id]:
                emotion_modifier = self._current_modifiers[user_id]['emotion']
                if 'data' in emotion_modifier:
                    emotion_data = emotion_modifier['data']
            
            # Fire-and-forget: record interaction event
            asyncio.create_task(
                self._record_interaction_event(
                    user_id=user_id,
                    resonance_coefficients=resonance_coeffs,
                    user_style=user_style,
                    emotion_data=emotion_data
                )
            )
            
            # Check if adaptation is needed
            if await self._should_adapt_resonance(user_id):
                self.logger.info(
                    f"Resonance adaptation triggered for user {user_id}, "
                    f"interactions: {self._interaction_counts[user_id]}"
                )
                # Fire-and-forget adaptation
                asyncio.create_task(self._adapt_resonance(user_id))
            
            self.logger.debug(
                f"Applied resonance to profile for user {user_id}, "
                f"total deviation: {total_deviation:.3f}"
            )
            
            return resonated_profile
            
        except Exception as e:
            self.logger.error(f"Failed to apply resonance for user {user_id}: {str(e)}")
            # Return unmodified profile on error - graceful degradation
            return profile
    
    async def _save_resonance_profile(
        self, 
        user_id: str, 
        profile: Dict[str, float]
    ) -> Optional[str]:
        """
        Save or update resonance profile in database.
        
        Uses the update_resonance_profile SQL function which handles
        INSERT/UPDATE logic and creates history records.
        
        Args:
            user_id: Telegram user ID
            profile: Resonance coefficients to save
            
        Returns:
            Adaptation ID (UUID as string) if successful, None on error
        """
        if not RESONANCE_ENABLED or self._pool is None:
            return None
        
        try:
            # Get current style and emotion for context
            style_vector = await self._get_user_style(user_id) or {
                'playfulness': 0.5,
                'seriousness': 0.5,
                'emotionality': 0.5,
                'creativity': 0.5
            }
            
            # Get dominant emotion if available
            emotion_data = self._current_modifiers.get(user_id, {}).get('emotion', {}).get('data', {})
            dominant_emotion = None
            if emotion_data:
                dominant_emotion = max(emotion_data.items(), key=lambda x: x[1])[0]
            
            # Call SQL function to update profile
            adaptation_id = await self._pool.fetchval(
                "SELECT update_resonance_profile($1, $2::jsonb, $3::jsonb, $4, $5)",
                user_id,
                json.dumps(profile),
                json.dumps(style_vector),
                RESONANCE_LEARNING_RATE,
                dominant_emotion
            )
            
            # Update in-memory cache
            self._resonance_profiles[user_id] = profile.copy()
            self._last_adaptations[user_id] = datetime.now(timezone.utc)
            
            # Update metrics
            self._metrics['resonance_adaptations'] += 1
            
            self.logger.info(
                f"Saved resonance profile for user {user_id}, "
                f"adaptation_id: {adaptation_id}"
            )
            
            return str(adaptation_id) if adaptation_id else None
            
        except Exception as e:
            self.logger.error(f"Failed to save resonance profile for user {user_id}: {str(e)}")
            self._metrics['db_errors'] += 1
            return None
    
    async def _should_adapt_resonance(self, user_id: str) -> bool:
        """
        Check if resonance adaptation is needed for user.
        
        Criteria:
        1. Interaction count reached RESONANCE_ADAPTATION_INTERVAL
        2. Minimum time passed since last adaptation
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            True if adaptation should be triggered
        """
        if not RESONANCE_ENABLED:
            return False
        
        # Check interaction count
        interaction_count = self._interaction_counts.get(user_id, 0)
        if interaction_count == 0 or interaction_count % RESONANCE_ADAPTATION_INTERVAL != 0:
            return False
        
        # Check time since last adaptation
        last_adaptation = self._last_adaptations.get(user_id)
        if last_adaptation:
            hours_since_last = (datetime.now(timezone.utc) - last_adaptation).total_seconds() / 3600
            if hours_since_last < RESONANCE_MIN_ADAPTATION_INTERVAL_HOURS:
                self.logger.debug(
                    f"Adaptation postponed for user {user_id}: "
                    f"only {hours_since_last:.1f} hours since last adaptation"
                )
                return False
        
        self.logger.info(
            f"Resonance adaptation triggered for user {user_id}: "
            f"{interaction_count} interactions reached"
        )
        return True
    
    async def _adapt_resonance(
        self,
        user_id: str,
        learning_rate: float = None
    ) -> bool:
        """
        Adapt resonance coefficients based on accumulated experience.
        
        Args:
            user_id: Telegram user ID
            learning_rate: Learning rate (uses config default if None)
            
        Returns:
            True if adaptation was successful
        """
        if not RESONANCE_ENABLED or self._pool is None:
            return False
            
        if learning_rate is None:
            learning_rate = RESONANCE_LEARNING_RATE
            
        try:
            # Load recent interaction events (last 100 interactions)
            query = """
                SELECT event_data, occurred_at
                FROM resonance_learning_events
                WHERE user_id = $1 
                AND event_type = 'interaction'
                AND processed = FALSE
                ORDER BY occurred_at DESC
                LIMIT $2
            """
            
            rows = await self._pool.fetch(
                query,
                user_id,
                RESONANCE_ADAPTATION_INTERVAL,
                timeout=PERSONALITY_QUERY_TIMEOUT
            )
            
            if not rows:
                self.logger.warning(f"No interaction events found for user {user_id}")
                return False
            
            self.logger.debug(f"Found {len(rows)} interaction events for adaptation")
            
            # Analyze accumulated data
            style_accumulator = {
                'playfulness': 0.0,
                'seriousness': 0.0,
                'emotionality': 0.0,
                'creativity': 0.0
            }
            emotion_counts = {}
            valid_events = 0
            
            for row in rows:
                event_data = row['event_data']
                
                # Ensure event_data is dict (JSONB auto-deserializes)
                if isinstance(event_data, str):
                    try:
                        event_data = json.loads(event_data)
                    except json.JSONDecodeError:
                        self.logger.warning(f"Invalid JSON in event_data: {event_data}")
                        continue
                
                # Accumulate style vectors
                if 'style' in event_data and event_data['style']:
                    for component, value in event_data['style'].items():
                        if component in style_accumulator:
                            style_accumulator[component] += value
                            valid_events += 1
                
                # Count emotions
                if 'emotion' in event_data and event_data['emotion']:
                    emotion = event_data['emotion']
                    intensity = event_data.get('emotion_intensity', 0.5)
                    if emotion not in emotion_counts:
                        emotion_counts[emotion] = {'count': 0, 'total_intensity': 0.0}
                    emotion_counts[emotion]['count'] += 1
                    emotion_counts[emotion]['total_intensity'] += intensity
            
            # Calculate average style
            if valid_events > 0:
                for component in style_accumulator:
                    style_accumulator[component] /= valid_events
            else:
                # Use neutral style if no valid events
                style_accumulator = {k: 0.5 for k in style_accumulator}
            
            # Find dominant emotion
            dominant_emotion = None
            dominant_intensity = 0.0
            if emotion_counts:
                # Sort by frequency * average intensity
                emotion_scores = {
                    emotion: data['count'] * (data['total_intensity'] / data['count'])
                    for emotion, data in emotion_counts.items()
                }
                dominant_emotion = max(emotion_scores, key=emotion_scores.get)
                dominant_intensity = emotion_counts[dominant_emotion]['total_intensity'] / emotion_counts[dominant_emotion]['count']
            
            # Get current resonance profile
            current_profile = await self._get_user_resonance(user_id)
            
            # Calculate new coefficients based on accumulated experience
            new_coefficients = self._calculate_adaptive_coefficients(
                current_profile,
                style_accumulator,
                dominant_emotion,
                dominant_intensity,
                learning_rate
            )
            
            # Check if changes are significant (at least 1% change in any trait)
            significant_change = any(
                abs(new_coefficients[trait] - current_profile[trait]) > 0.01
                for trait in new_coefficients
            )
            
            if not significant_change:
                self.logger.info(f"No significant changes for user {user_id}, skipping adaptation")
                return False
            
            # Save adapted profile
            adaptation_id = await self._save_resonance_profile(user_id, new_coefficients)
            
            if adaptation_id:
                # Generate adaptation event
                event = PersonalityAdaptationEvent.create(
                    user_id=user_id,
                    old_coefficients=current_profile,
                    new_coefficients=new_coefficients,
                    learning_rate=learning_rate,
                    interactions_since_last=len(rows),
                    trigger_reason='periodic'
                )
                await self._event_version_manager.append_event(event, self.get_actor_system())
                
                # Mark events as processed
                event_ids = [row['occurred_at'] for row in rows]
                await self._mark_events_processed(user_id, event_ids)
                
                # Update in-memory state
                self._resonance_profiles[user_id] = new_coefficients
                self._last_adaptations[user_id] = datetime.now(timezone.utc)
                self._interaction_counts[user_id] = 0  # Reset counter after adaptation
                
                # Update metrics
                self._metrics['resonance_adaptations'] += 1
                self._metrics['resonance_adaptations_pending'] = max(0, self._metrics.get('resonance_adaptations_pending', 0) - 1)
                
                self.logger.info(
                    f"Resonance adapted for user {user_id}, "
                    f"dominant style: {max(style_accumulator, key=style_accumulator.get)}, "
                    f"dominant emotion: {dominant_emotion}"
                )
                
                return True
            else:
                self.logger.error(f"Failed to save adapted profile for user {user_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to adapt resonance for user {user_id}: {str(e)}")
            self._metrics['resonance_adaptation_errors'] = self._metrics.get('resonance_adaptation_errors', 0) + 1
            return False
    
    def _calculate_adaptive_coefficients(
        self,
        current_profile: Dict[str, float],
        avg_style: Dict[str, float],
        dominant_emotion: Optional[str],
        emotion_intensity: float,
        learning_rate: float
    ) -> Dict[str, float]:
        """
        Calculate new resonance coefficients based on experience.
        
        Uses existing resonance matrix but applies learning to strengthen
        patterns that match user's actual behavior.
        
        Args:
            current_profile: Current resonance coefficients
            avg_style: Average style vector from interactions
            dominant_emotion: Most frequent emotion
            emotion_intensity: Average intensity of dominant emotion
            learning_rate: How fast to adapt (0.0-1.0)
            
        Returns:
            New resonance coefficients
        """
        # Start with current profile
        new_profile = current_profile.copy()
        
        # Calculate ideal coefficients based on average style
        ideal_coefficients = calculate_resonance_impact(
            user_style=avg_style,
            current_emotion=dominant_emotion,
            emotion_intensity=emotion_intensity
        )
        
        # Apply learning: move current coefficients toward ideal
        for trait, ideal_value in ideal_coefficients.items():
            if trait not in new_profile:
                new_profile[trait] = 1.0
                
            current_value = new_profile[trait]
            
            # Calculate delta with learning rate
            delta = (ideal_value - current_value) * learning_rate
            
            # Apply delta
            new_value = current_value + delta
            
            # Ensure bounds
            new_profile[trait] = max(
                RESONANCE_MIN_COEFFICIENT,
                min(new_value, RESONANCE_MAX_COEFFICIENT)
            )
        
        # Apply additional protection for core traits
        for trait in CORE_TRAITS:
            if trait in new_profile:
                # Core traits adapt even slower
                current = current_profile.get(trait, 1.0)
                new = new_profile[trait]
                # Reduce change by half
                new_profile[trait] = current + (new - current) * 0.5
        
        # Apply protection for stable traits
        new_profile = self._apply_stable_trait_protection(new_profile, learning_rate)
        
        # Ensure total change constraint
        total_change = sum(abs(new_profile[t] - current_profile.get(t, 1.0)) for t in new_profile)
        if total_change > RESONANCE_MAX_TOTAL_CHANGE:
            # Scale down all changes proportionally
            scale_factor = RESONANCE_MAX_TOTAL_CHANGE / total_change
            for trait in new_profile:
                current = current_profile.get(trait, 1.0)
                new = new_profile[trait]
                new_profile[trait] = current + (new - current) * scale_factor
        
        return new_profile
    
    async def _get_user_style(self, user_id: str) -> Optional[Dict[str, float]]:
        """
        Extract user style vector from current modifiers or database.
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Style vector dict with 4 components or None if not available
        """
        # First check in-memory modifiers
        if user_id in self._current_modifiers:
            style_modifier = self._current_modifiers[user_id].get('style')
            if style_modifier and 'data' in style_modifier:
                style_data = style_modifier['data']
                
                # Validate it has all expected components
                expected_components = ['playfulness', 'seriousness', 'emotionality', 'creativity']
                if all(comp in style_data for comp in expected_components):
                    # Return style data as-is (already in 0.0-1.0 format)
                    return {
                        component: style_data[component]
                        for component in expected_components
                    }
        
        # Fallback: load from database if not in memory
        if self._pool:
            try:
                query = """
                    SELECT modifier_data
                    FROM personality_modifier_history
                    WHERE user_id = $1 AND modifier_type = 'style'
                    ORDER BY applied_at DESC
                    LIMIT 1
                """
                
                row = await self._pool.fetchrow(query, user_id, timeout=PERSONALITY_QUERY_TIMEOUT)
                
                if row and row['modifier_data']:
                    style_data = row['modifier_data']
                    
                    # Ensure it's a dict
                    if isinstance(style_data, str):
                        try:
                            style_data = json.loads(style_data)
                        except json.JSONDecodeError:
                            self.logger.error(f"Invalid JSON in style modifier data for user {user_id}")
                            return None
                    
                    # Validate components
                    expected_components = ['playfulness', 'seriousness', 'emotionality', 'creativity']
                    if all(comp in style_data for comp in expected_components):
                        self.logger.debug(f"Loaded style from database for user {user_id}")
                        # Return style data as-is (already in 0.0-1.0 format)
                        return {
                            component: style_data[component]
                            for component in expected_components
                        }
                    else:
                        self.logger.warning(
                            f"Incomplete style data in DB for user {user_id}: {list(style_data.keys())}"
                        )
                        
            except Exception as e:
                self.logger.warning(f"Failed to load style from database: {str(e)}")
        
        return None
    
    def _calculate_resonance_coefficients(
        self,
        user_style: Dict[str, float],
        personality_profile: Dict[str, float],
        user_id: str  # Добавить параметр
    ) -> Dict[str, float]:
        """
        Calculate resonance coefficients based on user style and context.
        
        Args:
            user_style: User's style vector (4 components)
            personality_profile: Current personality profile (not used in current implementation)
            user_id: User ID to get emotion context
            
        Returns:
            Dict of resonance coefficients for each trait
        """
        # Get emotion for specific user
        emotion_data = None
        dominant_emotion = None
        emotion_intensity = 0.0
        
        if user_id in self._current_modifiers and 'emotion' in self._current_modifiers[user_id]:
            emotion_modifier = self._current_modifiers[user_id]['emotion']
            if 'data' in emotion_modifier:
                emotion_data = emotion_modifier['data']
                if emotion_data:
                    # Find dominant emotion
                    dominant_emotion, emotion_intensity = max(
                        emotion_data.items(), 
                        key=lambda x: x[1]
                    )
        
        # Calculate base resonance using vocabulary function
        coefficients = calculate_resonance_impact(
            user_style=user_style,
            current_emotion=dominant_emotion,
            emotion_intensity=emotion_intensity
        )
        
        # Apply noise if configured
        if RESONANCE_NOISE_LEVEL > 0:
            coefficients = add_resonance_noise(
                coefficients,
                noise_level=RESONANCE_NOISE_LEVEL
            )
        
        # Ensure we have coefficients for all traits
        for trait_name in self._base_traits.keys():
            if trait_name not in coefficients:
                coefficients[trait_name] = 1.0
        
        self.logger.debug(
            f"Calculated resonance coefficients for user {user_id}, "
            f"emotion: {dominant_emotion} ({emotion_intensity:.2f}), "
            f"traits affected: {len([c for c in coefficients.values() if c != 1.0])}"
        )
        
        return coefficients