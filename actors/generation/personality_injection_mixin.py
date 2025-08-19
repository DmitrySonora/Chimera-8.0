"""
PersonalityInjectionMixin for GenerationActor - dynamic personality modulation
"""
import random
from collections import defaultdict, deque
from typing import Dict, List, Optional, Any
from config.prompts_modulation import (
    MODULATION_PROMPTS,
    PERSONALITY_INJECTION_LOW_THRESHOLD,
    PERSONALITY_INJECTION_HIGH_THRESHOLD,
    PERSONALITY_INJECTION_TRAITS_COUNT,
    PERSONALITY_INJECTION_HISTORY_SIZE,
    PERSONALITY_INJECTION_RANDOM_WEIGHTS,
    PERSONALITY_INJECTION_DEFAULT_TRAIT_VALUE,
    PERSONALITY_INJECTION_LOG_PREVIEW_LENGTH,
    PERSONALITY_INJECTION_DEBUG_PREVIEW_LENGTH
)


class PersonalityInjectionMixin:
    """
    Mixin for GenerationActor that provides dynamic personality injections.
    Selects and combines modulation prompts based on active personality traits.
    """
    
    def __init__(self):
        """Initialize internal data structures for tracking profiles and history"""
        # Cache of last known personality profiles per user
        # Format: {user_id: {"trait_name": value, ...}}
        self._last_known_profiles: Dict[str, Dict[str, float]] = {}
        
        # History of recently used modulations to avoid repetition
        # Key format: "user_id:trait_name", Value: deque of used prompt texts
        self._recent_modulations: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=PERSONALITY_INJECTION_HISTORY_SIZE)
        )
        
        # Track injection source for metrics
        self._injection_source_counts = {
            'fresh': 0,
            'cached': 0,
            'random': 0
        }
    
    async def get_personality_injection(
        self, 
        user_id: str, 
        personality_profile: Optional[Dict] = None
    ) -> str:
        """
        Get personality injection text based on current profile.
        Implements three-level fallback: fresh -> cached -> random.
        
        Args:
            user_id: User identifier for personalization
            personality_profile: Optional fresh profile from PersonalityActor
                Expected format: {
                    'dominant_traits': List[str],
                    'active_traits': Dict[str, float]
                }
        
        Returns:
            Composed injection text (2-3 modulation prompts joined by space)
        """
        injection_text = ""
        source = "unknown"
        
        try:
            # Level 1: Use fresh profile if available
            if personality_profile and self._is_valid_profile(personality_profile):
                self.logger.debug(f"Using fresh personality profile for user {user_id}")
                
                # Extract data from profile
                dominant_traits = personality_profile.get('dominant_traits', [])
                active_traits = personality_profile.get('active_traits', {})
                
                if dominant_traits and active_traits:
                    # Save to cache for future use
                    self._last_known_profiles[user_id] = active_traits.copy()
                    
                    # Compose injection from dominant traits
                    injection_text = self._compose_injection(
                        dominant_traits, 
                        active_traits, 
                        user_id
                    )
                    source = "fresh"
                    self._injection_source_counts['fresh'] += 1
            
            # Level 2: Use cached profile if no fresh data
            if not injection_text and user_id in self._last_known_profiles:
                self.logger.info(f"Using cached personality profile for user {user_id}")
                
                cached_profile = self._last_known_profiles[user_id]
                # Get top traits from cached profile
                dominant_traits = self._get_top_traits_from_dict(
                    cached_profile, 
                    n=5
                )
                
                if dominant_traits:
                    injection_text = self._compose_injection(
                        dominant_traits,
                        cached_profile,
                        user_id
                    )
                    source = "cached"
                    self._injection_source_counts['cached'] += 1
            
            # Level 3: Generate completely random injection
            if not injection_text:
                self.logger.warning(
                    f"No personality data for user {user_id}, using random injection"
                )
                injection_text = self._generate_random_injection()
                source = "random"
                self._injection_source_counts['random'] += 1
            
            # Log the result
            if injection_text:
                if len(injection_text) > PERSONALITY_INJECTION_LOG_PREVIEW_LENGTH:
                    preview = injection_text[:PERSONALITY_INJECTION_LOG_PREVIEW_LENGTH] + "..."
                else:
                    preview = injection_text
                self.logger.info(
                    f"Generated {source} injection for user {user_id}: \"{preview}\""
                )
            
            return injection_text
            
        except Exception as e:
            self.logger.error(f"Error generating personality injection: {str(e)}")
            # Final fallback - return simple random injection
            return self._generate_random_injection()
    
    def _determine_intensity_level(self, value: float) -> str:
        """
        Determine intensity level based on trait value.
        
        Args:
            value: Trait strength value (0.0 - 1.0)
            
        Returns:
            'low', 'medium', or 'high'
        """
        if value < PERSONALITY_INJECTION_LOW_THRESHOLD:
            return 'low'
        elif value < PERSONALITY_INJECTION_HIGH_THRESHOLD:
            return 'medium'
        else:
            return 'high'
    
    def _select_modulation_prompt(
        self, 
        trait: str, 
        level: str, 
        user_id: str
    ) -> str:
        """
        Select a modulation prompt avoiding recent repetitions.
        
        Args:
            trait: Trait name (e.g., 'curiosity', 'empathy')
            level: Intensity level ('low', 'medium', 'high')
            user_id: User identifier for history tracking
            
        Returns:
            Selected modulation prompt text
        """
        # Check if trait exists in modulation prompts
        if trait not in MODULATION_PROMPTS:
            self.logger.warning(f"Unknown trait '{trait}', skipping")
            return ""
        
        # Get available prompts for this trait and level
        trait_prompts = MODULATION_PROMPTS.get(trait, {})
        level_prompts = trait_prompts.get(level, [])
        
        if not level_prompts:
            self.logger.warning(f"No prompts for trait '{trait}' at level '{level}'")
            return ""
        
        # Get history key
        history_key = f"{user_id}:{trait}"
        recent_history = self._recent_modulations[history_key]
        
        # Filter out recently used prompts
        available_prompts = [
            prompt for prompt in level_prompts 
            if prompt not in recent_history
        ]
        
        # If all prompts were recently used, use all prompts (round-robin complete)
        if not available_prompts:
            self.logger.debug(
                f"All prompts for {trait}/{level} recently used for user {user_id}, "
                "resetting rotation"
            )
            available_prompts = level_prompts
        
        # Select random prompt from available
        selected_prompt = random.choice(available_prompts)
        
        # Add to history
        recent_history.append(selected_prompt)
        
        return selected_prompt
    
    def _compose_injection(
        self, 
        traits: List[str], 
        profile: Dict[str, float], 
        user_id: str
    ) -> str:
        """
        Compose injection from multiple trait modulations.
        
        Args:
            traits: List of trait names to use (dominant traits)
            profile: Full trait profile with values
            user_id: User identifier
            
        Returns:
            Composed injection text (space-separated modulations)
        """
        # Take top N traits based on configuration
        traits_to_use = traits[:PERSONALITY_INJECTION_TRAITS_COUNT]
        
        modulations = []
        
        for trait in traits_to_use:
            # Get trait value
            trait_value = profile.get(trait, PERSONALITY_INJECTION_DEFAULT_TRAIT_VALUE)
            
            # Determine intensity level
            level = self._determine_intensity_level(trait_value)
            
            # Select modulation prompt
            modulation = self._select_modulation_prompt(trait, level, user_id)
            
            if modulation:
                modulations.append(modulation)
                if len(modulation) > PERSONALITY_INJECTION_DEBUG_PREVIEW_LENGTH:
                    debug_preview = modulation[:PERSONALITY_INJECTION_DEBUG_PREVIEW_LENGTH] + "..."
                else:
                    debug_preview = modulation
                self.logger.debug(
                    f"Selected {trait}/{level} (value={trait_value:.2f}): "
                    f"\"{debug_preview}\""
                )
        
        # Join modulations with space
        injection = " ".join(modulations)
        
        return injection
    
    def _generate_random_injection(self) -> str:
        """
        Generate completely random injection as ultimate fallback.
        
        Returns:
            Random injection text
        """
        # Select random traits (use configured traits count)
        all_traits = list(MODULATION_PROMPTS.keys())
        num_traits = min(PERSONALITY_INJECTION_TRAITS_COUNT, len(all_traits))
        selected_traits = random.sample(all_traits, num_traits)
        
        modulations = []
        
        for trait in selected_traits:
            # Select random level with configured weights
            level = random.choices(
                ['low', 'medium', 'high'],
                weights=PERSONALITY_INJECTION_RANDOM_WEIGHTS,
                k=1
            )[0]
            
            # Get random prompt for this trait/level
            trait_prompts = MODULATION_PROMPTS.get(trait, {})
            level_prompts = trait_prompts.get(level, [])
            
            if level_prompts:
                modulation = random.choice(level_prompts)
                modulations.append(modulation)
        
        return " ".join(modulations)
    
    def _is_valid_profile(self, profile: Dict) -> bool:
        """
        Validate personality profile structure.
        
        Args:
            profile: Profile dictionary to validate
            
        Returns:
            True if profile has expected structure
        """
        if not isinstance(profile, dict):
            return False
        
        # Check required fields
        if 'dominant_traits' not in profile or 'active_traits' not in profile:
            return False
        
        # Check types
        if not isinstance(profile['dominant_traits'], list):
            return False
        
        if not isinstance(profile['active_traits'], dict):
            return False
        
        return True
    
    def _get_top_traits_from_dict(
        self, 
        traits_dict: Dict[str, float], 
        n: int = 5
    ) -> List[str]:
        """
        Extract top N traits from a traits dictionary.
        
        Args:
            traits_dict: Dictionary of trait names to values
            n: Number of top traits to return
            
        Returns:
            List of trait names sorted by value (descending)
        """
        if not traits_dict:
            return []
        
        # Sort traits by value (descending)
        sorted_traits = sorted(
            traits_dict.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        # Return top N trait names
        return [trait for trait, _ in sorted_traits[:n]]
    
    def get_injection_metrics(self) -> Dict[str, Any]:
        """
        Get metrics about injection system performance.
        
        Returns:
            Dictionary with injection statistics
        """
        total_injections = sum(self._injection_source_counts.values())
        
        metrics = {
            'total_injections': total_injections,
            'source_counts': self._injection_source_counts.copy(),
            'cached_profiles': len(self._last_known_profiles),
            'modulation_history_size': len(self._recent_modulations),
        }
        
        # Calculate percentages if there were injections
        if total_injections > 0:
            metrics['source_percentages'] = {
                source: (count / total_injections) * 100
                for source, count in self._injection_source_counts.items()
            }
        
        return metrics