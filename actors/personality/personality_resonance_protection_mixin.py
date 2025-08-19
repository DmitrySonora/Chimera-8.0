"""
Resonance protection mixin for PersonalityActor - implements safeguards for resonance adaptation
"""
import asyncio
from typing import Dict, Optional, Tuple
from datetime import datetime, timezone

from config.settings import (
    RESONANCE_ENABLED,
    RESONANCE_MAX_DEVIATION,
    RESONANCE_MAX_TOTAL_CHANGE,
    RESONANCE_CORE_TRAIT_FACTOR,
    RESONANCE_NOISE_LEVEL,
    RESONANCE_INACTIVITY_DAYS,
    RESONANCE_CLEANUP_ENABLED,
    PERSONALITY_RECOVERY_RATE,
    PERSONALITY_RECOVERY_DAYS
)
from config.vocabulary_resonance_matrix import (
    add_resonance_noise,
    CORE_TRAITS
)
from actors.events.personality_events import (
    ResonanceDeactivatedEvent,
    AuthenticityCheckEvent
)


class PersonalityResonanceProtectionMixin:
    """
    Mixin providing protection mechanisms for resonance coefficients.
    
    Ensures that resonance adaptation doesn't compromise the authenticity
    of Chimera's personality through excessive user adaptation.
    
    Available attributes from PersonalityActor:
    - logger: logging object
    - _pool: database connection pool
    - _redis: Redis client (optional)
    - _metrics: Dict[str, int] - metrics dictionary
    - _base_traits: Dict[str, Dict[str, Any]] - base personality traits
    - _resonance_profiles: Dict[str, Dict[str, float]] - user_id -> {trait: coefficient}
    - _last_adaptations: Dict[str, datetime] - user_id -> last adaptation timestamp
    - _event_version_manager: EventVersionManager instance
    - get_actor_system: method to get actor system
    """
    
    def _check_resonance_deviation(
        self,
        coefficients: Dict[str, float],
        user_id: str
    ) -> Tuple[bool, Dict[str, float]]:
        """
        Check if resonance coefficients exceed allowed deviation from neutral (1.0).
        
        Args:
            coefficients: Proposed resonance coefficients
            user_id: User ID for logging
            
        Returns:
            Tuple of (is_within_limits, adjusted_coefficients)
        """
        adjusted = coefficients.copy()
        adjustments_made = False
        
        # Check individual trait deviations
        for trait, coefficient in coefficients.items():
            deviation = abs(coefficient - 1.0)
            
            # Check if deviation exceeds maximum allowed
            if deviation > RESONANCE_MAX_DEVIATION:
                # Clamp to maximum allowed deviation
                if coefficient > 1.0:
                    adjusted[trait] = 1.0 + RESONANCE_MAX_DEVIATION
                else:
                    adjusted[trait] = 1.0 - RESONANCE_MAX_DEVIATION
                
                adjustments_made = True
                self.logger.warning(
                    f"Resonance deviation exceeded for {trait}: "
                    f"{coefficient:.3f} -> {adjusted[trait]:.3f} "
                    f"(user: {user_id})"
                )
        
        # Check total deviation constraint
        total_deviation = sum(abs(c - 1.0) for c in adjusted.values())
        
        if total_deviation > RESONANCE_MAX_TOTAL_CHANGE:
            # Scale down all deviations proportionally
            scale_factor = RESONANCE_MAX_TOTAL_CHANGE / total_deviation
            
            for trait in adjusted:
                current_deviation = adjusted[trait] - 1.0
                adjusted[trait] = 1.0 + (current_deviation * scale_factor)
            
            adjustments_made = True
            self.logger.info(
                f"Total resonance deviation scaled down by {scale_factor:.2f} "
                f"for user {user_id}"
            )
        
        # Update metrics
        if adjustments_made:
            if 'resonance_deviations_limited' not in self._metrics:
                self._metrics['resonance_deviations_limited'] = 0
            self._metrics['resonance_deviations_limited'] += 1
        
        return not adjustments_made, adjusted
    
    def _apply_stable_trait_protection(
        self,
        coefficients: Dict[str, float],
        learning_rate: float
    ) -> Dict[str, float]:
        """
        Apply additional protection for stable traits.
        
        Stable traits adapt at half the normal rate to preserve
        core personality characteristics.
        
        Args:
            coefficients: Current resonance coefficients
            learning_rate: Base learning rate
            
        Returns:
            Protected coefficients
        """
        protected = coefficients.copy()
        
        # Get list of stable traits from vocabulary
        stable_traits = CORE_TRAITS  # These are marked as needing extra protection
        
        for trait in stable_traits:
            if trait in protected and protected[trait] != 1.0:
                # Reduce the deviation from neutral by RESONANCE_CORE_TRAIT_FACTOR
                current_deviation = protected[trait] - 1.0
                reduced_deviation = current_deviation * RESONANCE_CORE_TRAIT_FACTOR
                protected[trait] = 1.0 + reduced_deviation
                
                self.logger.debug(
                    f"Stable trait protection applied to {trait}: "
                    f"{coefficients[trait]:.3f} -> {protected[trait]:.3f}"
                )
        
        return protected
    
    def _add_resonance_noise(
        self,
        coefficients: Dict[str, float],
        noise_level: Optional[float] = None
    ) -> Dict[str, float]:
        """
        Add controlled randomness to resonance coefficients.
        
        This prevents mechanical patterns and adds liveliness to interactions.
        Uses the vocabulary function for consistency.
        
        Args:
            coefficients: Base resonance coefficients
            noise_level: Noise level (uses config default if None)
            
        Returns:
            Coefficients with added noise
        """
        if noise_level is None:
            noise_level = RESONANCE_NOISE_LEVEL
        
        if noise_level <= 0:
            return coefficients
        
        # Use vocabulary function for consistency
        noisy_coefficients = add_resonance_noise(coefficients, noise_level)
        
        # Log if significant noise was added
        max_noise = max(
            abs(noisy_coefficients[t] - coefficients[t]) 
            for t in coefficients
        )
        
        if max_noise > 0.02:  # Log if more than 2% change
            self.logger.debug(
                f"Added resonance noise (max change: {max_noise:.3f})"
            )
        
        return noisy_coefficients
    
    async def _reset_resonance_profile(
        self,
        user_id: str,
        partial: bool = False,
        reset_factor: float = 1.0
    ) -> bool:
        """
        Reset or partially reset user's resonance profile.
        
        Args:
            user_id: User to reset
            partial: If True, partial reset towards neutral
            reset_factor: How much to reset (0.0 = no change, 1.0 = full reset)
            
        Returns:
            True if reset was successful
        """
        if not RESONANCE_ENABLED:
            return False
        
        try:
            # Get current profile
            current_profile = self._resonance_profiles.get(user_id, {})
            
            if not current_profile:
                self.logger.info(f"No resonance profile to reset for user {user_id}")
                return False
            
            # Calculate reset profile
            reset_profile = {}
            
            for trait in self._base_traits.keys():
                current_value = current_profile.get(trait, 1.0)
                
                if partial:
                    # Partial reset: interpolate towards neutral
                    reset_value = current_value + (1.0 - current_value) * reset_factor
                else:
                    # Full reset: all coefficients to neutral
                    reset_value = 1.0
                
                reset_profile[trait] = reset_value
            
            # Save reset profile
            if self._pool:
                from actors.personality.personality_resonance_mixin import PersonalityResonanceMixin
                # Use the save method from resonance mixin
                await PersonalityResonanceMixin._save_resonance_profile(
                    self, user_id, reset_profile
                )
            
            # Update in-memory cache
            self._resonance_profiles[user_id] = reset_profile
            
            # Reset interaction counter
            if user_id in self._interaction_counts:
                self._interaction_counts[user_id] = 0
            
            # Generate event
            reason = "partial_reset" if partial else "full_reset"
            event = AuthenticityCheckEvent.create(
                user_id=user_id,
                check_type="resonance_reset",
                authenticity_score=1.0,  # Fully authentic after reset
                adjustments_made={
                    "reset_type": reason,
                    "reset_factor": reset_factor
                },
                traits_affected=list(current_profile.keys())
            )
            
            if self.get_actor_system():
                await self._event_version_manager.append_event(
                    event, self.get_actor_system()
                )
            
            # Update metrics
            if 'resonance_resets' not in self._metrics:
                self._metrics['resonance_resets'] = 0
            self._metrics['resonance_resets'] += 1
            
            self.logger.info(
                f"Resonance {'partially' if partial else 'fully'} reset "
                f"for user {user_id} (factor: {reset_factor:.2f})"
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to reset resonance for user {user_id}: {str(e)}")
            return False
    
    async def _apply_inactivity_decay(
        self,
        user_id: str,
        days_inactive: Optional[int] = None
    ) -> bool:
        """
        Apply gradual decay to resonance after period of inactivity.
        
        Resonance slowly returns to neutral when user is inactive,
        preserving authenticity while maintaining some personalization.
        
        Args:
            user_id: User to check
            days_inactive: Override for days inactive (for testing)
            
        Returns:
            True if decay was applied
        """
        if not RESONANCE_ENABLED:
            return False
        
        # Calculate days inactive if not provided
        if days_inactive is None:
            last_adaptation = self._last_adaptations.get(user_id)
            if not last_adaptation:
                return False
            
            current_time = datetime.now(timezone.utc)
            days_inactive = (current_time - last_adaptation).days
        
        # Check if decay should apply (similar to personality recovery)
        if days_inactive < PERSONALITY_RECOVERY_DAYS:
            return False
        
        # Calculate decay factor (using same rate as personality recovery)
        decay_days = days_inactive - PERSONALITY_RECOVERY_DAYS
        decay_factor = min(1.0, decay_days * PERSONALITY_RECOVERY_RATE)
        
        # Apply partial reset with decay factor
        success = await self._reset_resonance_profile(
            user_id,
            partial=True,
            reset_factor=decay_factor
        )
        
        if success:
            self.logger.info(
                f"Applied inactivity decay to user {user_id}: "
                f"{days_inactive} days inactive, decay factor: {decay_factor:.2f}"
            )
            
            # Update metrics
            if 'resonance_decays_applied' not in self._metrics:
                self._metrics['resonance_decays_applied'] = 0
            self._metrics['resonance_decays_applied'] += 1
        
        return success
    
    async def _check_resonance_authenticity(
        self,
        user_id: str,
        coefficients: Dict[str, float]
    ) -> float:
        """
        Calculate authenticity score for current resonance profile.
        
        Score indicates how much the personality has adapted to the user
        vs maintaining its authentic character.
        
        Args:
            user_id: User ID
            coefficients: Current resonance coefficients
            
        Returns:
            Authenticity score (0.0 = fully adapted, 1.0 = fully authentic)
        """
        if not coefficients:
            return 1.0  # No adaptation = fully authentic
        
        # Calculate average deviation from neutral
        deviations = [abs(c - 1.0) for c in coefficients.values()]
        avg_deviation = sum(deviations) / len(deviations) if deviations else 0.0
        
        # Convert to authenticity score (inverse of deviation)
        # Max deviation is RESONANCE_MAX_DEVIATION (0.3)
        authenticity = 1.0 - (avg_deviation / RESONANCE_MAX_DEVIATION)
        authenticity = max(0.0, min(1.0, authenticity))
        
        # Check if we should generate an event
        if authenticity < 0.5:  # Less than 50% authentic
            event = AuthenticityCheckEvent.create(
                user_id=user_id,
                check_type="low_authenticity_warning",
                authenticity_score=authenticity,
                adjustments_made={
                    "avg_deviation": avg_deviation,
                    "max_allowed": RESONANCE_MAX_DEVIATION
                },
                traits_affected=[
                    trait for trait, coef in coefficients.items()
                    if abs(coef - 1.0) > 0.2  # Significantly adapted traits
                ]
            )
            
            if self.get_actor_system():
                asyncio.create_task(
                    self._event_version_manager.append_event(
                        event, self.get_actor_system()
                    )
                )
            
            self.logger.warning(
                f"Low authenticity score for user {user_id}: {authenticity:.2%}"
            )
        
        return authenticity
    
    async def _deactivate_inactive_resonance_profiles(self) -> int:
        """
        Deactivate resonance profiles for users inactive beyond threshold.
        
        This is a maintenance task that should be called periodically.
        
        Returns:
            Number of profiles deactivated
        """
        if not RESONANCE_ENABLED or not RESONANCE_CLEANUP_ENABLED:
            return 0
        
        if not self._pool:
            return 0
        
        try:
            # Find and deactivate old profiles
            query = """
                UPDATE user_personality_resonance
                SET is_active = FALSE,
                    deactivated_at = CURRENT_TIMESTAMP,
                    deactivation_reason = 'inactivity'
                WHERE is_active = TRUE
                AND last_adaptation < CURRENT_TIMESTAMP - INTERVAL '%s days'
                RETURNING user_id
            """
            
            rows = await self._pool.fetch(query, RESONANCE_INACTIVITY_DAYS)
            deactivated_count = len(rows)
            
            if deactivated_count > 0:
                # Remove from memory cache
                for row in rows:
                    user_id = row['user_id']
                    if user_id in self._resonance_profiles:
                        del self._resonance_profiles[user_id]
                    if user_id in self._interaction_counts:
                        del self._interaction_counts[user_id]
                    if user_id in self._last_adaptations:
                        del self._last_adaptations[user_id]
                    
                    # Generate event
                    event = ResonanceDeactivatedEvent.create(
                        user_id=user_id,
                        reason="inactivity",
                        days_inactive=RESONANCE_INACTIVITY_DAYS
                    )
                    
                    if self.get_actor_system():
                        await self._event_version_manager.append_event(
                            event, self.get_actor_system()
                        )
                
                self.logger.info(
                    f"Deactivated {deactivated_count} inactive resonance profiles"
                )
                
                # Update metrics
                if 'resonance_profiles_deactivated' not in self._metrics:
                    self._metrics['resonance_profiles_deactivated'] = 0
                self._metrics['resonance_profiles_deactivated'] += deactivated_count
            
            return deactivated_count
            
        except Exception as e:
            self.logger.error(f"Failed to deactivate inactive profiles: {str(e)}")
            return 0