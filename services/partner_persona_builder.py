"""
Сервис для построения и обновления модели собеседника на основе стилевого анализа.
Создает PartnerPersona для персонализации режима общения.
"""
import json
from typing import Dict, Any, Tuple, Optional
from uuid import UUID

from config.logging import get_logger
from models.personality_models import StyleVector, PartnerPersona
from config.vocabulary_style_analysis import (
    PERSONA_MODE_THRESHOLDS,
    PERSONA_MODE_MIN_CONFIDENCE
)


class PartnerPersonaBuilder:
    """
    Построитель модели собеседника для персонализации режима общения.
    Анализирует StyleVector и создает оптимальную PartnerPersona.
    """
    
    def __init__(self, db_connection):
        """
        Args:
            db_connection: Подключение к БД для работы с partner_personas таблицей
        """
        self.db = db_connection
        self.logger = get_logger("partner_persona_builder")
    
    async def build_or_update_persona(
        self, 
        user_id: str, 
        style_result: Dict[str, Any]
    ) -> PartnerPersona:
        """
        Строит или обновляет PartnerPersona на основе стилевого анализа.
        
        Args:
            user_id: Telegram ID пользователя
            style_result: Результат StyleAnalyzer с полями:
                - style_vector: Dict с 4 компонентами стиля
                - confidence: float уверенность анализа
                - messages_analyzed: int количество проанализированных сообщений
        
        Returns:
            PartnerPersona: Модель собеседника с оптимальным режимом
        """
        self.logger.info(f"Building persona for user {user_id}")
        
        # 1. Извлечь StyleVector из результата анализа
        style_vector = StyleVector.model_validate(style_result["style_vector"])
        style_confidence = style_result["confidence"]
        messages_analyzed = style_result["messages_analyzed"]
        
        # 2. Определить оптимальный режим общения
        recommended_mode, mode_confidence = self._determine_mode(style_vector)
        
        self.logger.debug(
            f"Mode determination: {recommended_mode} (confidence: {mode_confidence:.3f}) "
            f"for style vector: {style_vector.model_dump()}"
        )
        
        # 3. Проверить существующую активную персону
        existing_persona = await self._get_active_persona(user_id)
        
        # 4. Проверить необходимость создания новой версии
        if existing_persona:
            # Десериализовать старый style_vector
            old_style_data = existing_persona['style_vector']
            if isinstance(old_style_data, str):
                old_style_data = json.loads(old_style_data)
            old_style_vector = StyleVector.model_validate(old_style_data)
            
            # Проверить значительность изменений
            if not old_style_vector.is_significant_change(style_vector):
                self.logger.info(
                    f"Insignificant changes for user {user_id}, returning existing persona"
                )
                return await self._convert_db_row_to_persona(existing_persona)
        
        # 5. Создать новую версию персоны
        new_persona_id = await self._create_new_persona(
            user_id=user_id,
            style_vector=style_vector,
            style_confidence=style_confidence,
            recommended_mode=recommended_mode,
            mode_confidence=mode_confidence,
            messages_analyzed=messages_analyzed
        )
        
        # 6. Получить созданную персону из БД
        persona_row = await self.db.fetchrow(
            "SELECT * FROM partner_personas WHERE persona_id = $1",
            new_persona_id
        )
        
        if not persona_row:
            raise RuntimeError(f"Failed to retrieve created persona {new_persona_id}")
            
        persona = await self._convert_db_row_to_persona(persona_row)
        
        self.logger.info(
            f"Created new persona for user {user_id}: "
            f"version {persona.version}, mode {persona.recommended_mode}"
        )
        
        return persona
    
    def _determine_mode(self, style_vector: StyleVector) -> Tuple[str, float]:
        """
        Определяет оптимальный режим общения на основе StyleVector.
        
        Args:
            style_vector: 4D вектор стиля пользователя
            
        Returns:
            Tuple[str, float]: (режим, уверенность)
        """
        # Алгоритм определения режима по приоритету:
        
        # 1. Высокая креативность → creative режим
        if style_vector.creativity > PERSONA_MODE_THRESHOLDS["creativity_high"]:
            return ("creative", style_vector.creativity)
        
        # 2. Высокая серьезность + низкая игривость → expert режим  
        if (style_vector.seriousness > PERSONA_MODE_THRESHOLDS["seriousness_high"] and 
            style_vector.playfulness < PERSONA_MODE_THRESHOLDS["playfulness_low"]):
            return ("expert", style_vector.seriousness)
        
        # 3. Высокая игривость + низкая серьезность → talk режим
        if (style_vector.playfulness > PERSONA_MODE_THRESHOLDS["playfulness_high"] and 
            style_vector.seriousness < PERSONA_MODE_THRESHOLDS["seriousness_low"]):
            return ("talk", style_vector.playfulness)
        
        # 4. Fallback → talk режим с минимальной уверенностью
        return ("talk", PERSONA_MODE_MIN_CONFIDENCE)
    
    async def _get_active_persona(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Получает текущую активную персону пользователя.
        
        Args:
            user_id: ID пользователя
            
        Returns:
            Dict с данными персоны или None если не найдена
        """
        try:
            return await self.db.fetchrow(
                "SELECT * FROM partner_personas WHERE user_id = $1 AND is_active = TRUE",
                user_id
            )
        except Exception as e:
            self.logger.error(f"Error fetching active persona for user {user_id}: {e}")
            return None
    
    async def _create_new_persona(
        self,
        user_id: str,
        style_vector: StyleVector,
        style_confidence: float,
        recommended_mode: str,
        mode_confidence: float,
        messages_analyzed: int
    ) -> UUID:
        """
        Создает новую версию персоны через БД функцию.
        
        Returns:
            UUID созданной персоны
        """
        # Преобразуем StyleVector в JSON object для БД
        style_vector_json = style_vector.model_dump()
        
        try:
            new_persona_id = await self.db.fetchval(
                "SELECT update_partner_persona($1, $2, $3, $4, $5, $6)",
                user_id,
                json.dumps(style_vector_json),  # Обеспечиваем JSON формат
                style_confidence,
                recommended_mode,
                mode_confidence,
                messages_analyzed
            )
            
            if not new_persona_id:
                raise RuntimeError("Database function returned NULL persona_id")
                
            return new_persona_id
            
        except Exception as e:
            self.logger.error(f"Error creating persona for user {user_id}: {e}")
            raise
    
    async def _convert_db_row_to_persona(self, row: Dict[str, Any]) -> PartnerPersona:
        """
        Конвертирует строку БД в объект PartnerPersona.
        
        Args:
            row: Строка из partner_personas таблицы
            
        Returns:
            PartnerPersona объект
        """
        try:
            # Конвертируем в словарь
            persona_data = dict(row)
            
            # Обрабатываем style_vector JSONB поле
            style_data = persona_data['style_vector']
            if isinstance(style_data, str):
                style_data = json.loads(style_data)
            
            # Создаем StyleVector и заменяем в данных
            persona_data['style_vector'] = StyleVector.model_validate(style_data)
            
            # Устанавливаем предиктивную компоненту (заглушка для Phase 7.3)
            persona_data.setdefault('predicted_interests', [])
            persona_data.setdefault('prediction_confidence', 0.0)
            
            # TODO: Implement predictive model in Phase 7.3
            
            return PartnerPersona.model_validate(persona_data)
            
        except Exception as e:
            self.logger.error(f"Error converting DB row to PartnerPersona: {e}")
            raise