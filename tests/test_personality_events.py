"""
Интеграционный тест для событий анализа личности.
Полный вывод: pytest tests/test_personality_events.py -v -s
"""
import asyncio
import pytest
from datetime import datetime
from uuid import uuid4

from actors.events.personality_events import (
    PersonalityTraitDetectedEvent,
    StyleVectorUpdatedEvent,
    PartnerPersonaUpdatedEvent,
    TraitManifestationEvent
)


class TestPersonalityEvents:
    """Интеграционный тест событий анализа личности"""
    
    @pytest.mark.asyncio
    async def test_personality_trait_detected_event(self):
        """Тест создания события обнаружения черты личности."""
        # Создание события
        event = PersonalityTraitDetectedEvent.create(
            user_id="test_user_123",
            trait_name="curiosity",
            strength=0.75,
            context_mode="talk",
            confidence=0.85,
            trigger_markers=["интересно", "расскажи", "любопытно"],
            message_preview="Мне очень интересно узнать больше об этой теме"
        )
        
        # Проверки структуры
        assert event.stream_id == "personality_test_user_123"
        assert event.event_type == "PersonalityTraitDetectedEvent"
        assert event.version == 0
        assert event.data["trait_name"] == "curiosity"
        assert event.data["strength"] == 0.75
        assert event.data["confidence"] == 0.85
        assert len(event.data["trigger_markers"]) == 3
        
        # Визуальный вывод
        print(f"\n{'='*60}")
        print("PersonalityTraitDetectedEvent Test:")
        print(f"{'='*60}")
        print(f"Stream ID: {event.stream_id}")
        print(f"Trait: {event.data['trait_name']}")
        print(f"Strength: {event.data['strength']:.2f}")
        print(f"Confidence: {event.data['confidence']:.2f}")
        print(f"Mode: {event.data['context_mode']}")
        print(f"Markers: {', '.join(event.data['trigger_markers'])}")
        print(f"Preview: {event.data['message_preview']}")
        print(f"{'='*60}\n")
    
    @pytest.mark.asyncio
    async def test_text_truncation(self):
        """Тест обрезки длинных текстов."""
        # Длинный текст для message_preview (> 100 символов)
        long_preview = "Это очень длинный текст, который определенно превышает лимит в сто символов и должен быть автоматически обрезан системой с добавлением троеточия"
        
        event1 = PersonalityTraitDetectedEvent.create(
            user_id="test_truncation",
            trait_name="philosophical",
            strength=0.9,
            context_mode="expert",
            confidence=0.7,
            trigger_markers=["смысл", "сущность"],
            message_preview=long_preview
        )
        
        # Проверка обрезки preview
        assert event1.data["message_preview"].endswith("...")
        assert len(event1.data["message_preview"]) == 103  # 100 + "..."
        
        # Длинный текст для response_fragment (> 200 символов)
        long_fragment = "Философия — это не просто наука о мудрости, это способ осмысления бытия, поиск ответов на вечные вопросы о природе реальности, сознания, морали и смысла существования. Каждый философ привносит свой уникальный взгляд на эти фундаментальные проблемы."
        
        event2 = TraitManifestationEvent.create(
            user_id="test_truncation",
            trait_name="philosophical",
            manifestation_id=str(uuid4()),
            intensity=0.95,
            emotional_context={"realization": 0.8, "admiration": 0.7},
            mode="creative",
            response_fragment=long_fragment,
            timestamp_utc=datetime.utcnow().isoformat()
        )
        
        # Проверка обрезки fragment
        assert event2.data["response_fragment"].endswith("...")
        assert len(event2.data["response_fragment"]) == 203  # 200 + "..."
        
        print(f"\n{'='*60}")
        print("Text Truncation Test:")
        print(f"{'='*60}")
        print(f"Original preview length: {len(long_preview)}")
        print(f"Truncated preview: {event1.data['message_preview'][:50]}...")
        print(f"\nOriginal fragment length: {len(long_fragment)}")
        print(f"Truncated fragment: {event2.data['response_fragment'][:50]}...")
        print(f"{'='*60}\n")
    
    @pytest.mark.asyncio
    async def test_style_vector_updated_event(self):
        """Тест события обновления стилевого вектора."""
        old_vector = {
            "playfulness": 0.3,
            "seriousness": 0.7,
            "emotionality": 0.4,
            "creativity": 0.5
        }
        
        new_vector = {
            "playfulness": 0.8,
            "seriousness": 0.2,
            "emotionality": 0.6,
            "creativity": 0.9
        }
        
        event = StyleVectorUpdatedEvent.create(
            user_id="style_test_user",
            old_vector=old_vector,
            new_vector=new_vector,
            messages_analyzed=50,
            significant_change=True,
            dominant_style="creative"
        )
        
        # Проверки
        assert event.stream_id == "personality_style_test_user"
        assert event.data["old_vector"] == old_vector
        assert event.data["new_vector"] == new_vector
        assert event.data["significant_change"] is True
        assert event.data["dominant_style"] == "creative"
        
        # Визуальная дельта
        print(f"\n{'='*60}")
        print("StyleVectorUpdatedEvent Test:")
        print(f"{'='*60}")
        print(f"Messages analyzed: {event.data['messages_analyzed']}")
        print(f"Significant change: {event.data['significant_change']}")
        print(f"Dominant style: {event.data['dominant_style']}")
        print("\nVector changes:")
        for component in ["playfulness", "seriousness", "emotionality", "creativity"]:
            old_val = old_vector[component]
            new_val = new_vector[component]
            delta = new_val - old_val
            bar_old = '█' * int(old_val * 10) + '░' * (10 - int(old_val * 10))
            bar_new = '█' * int(new_val * 10) + '░' * (10 - int(new_val * 10))
            sign = "+" if delta > 0 else ""
            print(f"  {component:12s}: [{bar_old}] → [{bar_new}] ({sign}{delta:.2f})")
        print(f"{'='*60}\n")
    
    @pytest.mark.asyncio
    async def test_partner_persona_updated_event(self):
        """Тест события обновления Partner Persona."""
        persona_id = str(uuid4())
        correlation_id = f"batch_analysis_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        event = PartnerPersonaUpdatedEvent.create(
            user_id="persona_test_user",
            persona_id=persona_id,
            version=3,
            previous_mode="expert",
            recommended_mode="talk",
            confidence_score=0.92,
            prediction_data={
                "predicted_interests": ["философия", "юмор", "психология"],
                "prediction_confidence": 0.75,
                "trend": "shift_to_casual"
            },
            reason="significant_change",
            correlation_id=correlation_id
        )
        
        # Проверки
        assert event.correlation_id == correlation_id
        assert event.data["version"] == 3  # версия персоны, не события!
        assert event.data["previous_mode"] == "expert"
        assert event.data["recommended_mode"] == "talk"
        assert "predicted_interests" in event.data["prediction_data"]
        
        print(f"\n{'='*60}")
        print("PartnerPersonaUpdatedEvent Test:")
        print(f"{'='*60}")
        print(f"Persona ID: {event.data['persona_id'][:8]}...")
        print(f"Version: {event.data['version']}")
        print(f"Mode transition: {event.data['previous_mode']} → {event.data['recommended_mode']}")
        print(f"Confidence: {event.data['confidence_score']:.2%}")
        print(f"Reason: {event.data['reason']}")
        print(f"Predicted interests: {', '.join(event.data['prediction_data']['predicted_interests'])}")
        print(f"Prediction confidence: {event.data['prediction_data']['prediction_confidence']:.2%}")
        print(f"Correlation ID: {event.correlation_id}")
        print(f"{'='*60}\n")
    
    @pytest.mark.asyncio
    async def test_trait_manifestation_event(self):
        """Тест события проявления черты в контексте."""
        manifestation_id = str(uuid4())
        timestamp = datetime.utcnow().isoformat()
        
        emotional_context = {
            "amusement": 0.85,
            "joy": 0.7,
            "pride": 0.5
        }
        
        event = TraitManifestationEvent.create(
            user_id="manifestation_test_user",
            trait_name="irony",
            manifestation_id=manifestation_id,
            intensity=0.88,
            emotional_context=emotional_context,
            mode="talk",
            response_fragment="Ну конечно, кто бы мог подумать! Как неожиданно и оригинально.",
            timestamp_utc=timestamp
        )
        
        # Проверки
        assert event.stream_id == "personality_manifestation_test_user"
        assert event.data["trait_name"] == "irony"
        assert event.data["intensity"] == 0.88
        assert event.data["emotional_context"] == emotional_context
        assert event.data["timestamp_utc"] == timestamp
        
        print(f"\n{'='*60}")
        print("TraitManifestationEvent Test:")
        print(f"{'='*60}")
        print(f"Trait: {event.data['trait_name']}")
        print(f"Intensity: {event.data['intensity']:.2f}")
        print(f"Mode: {event.data['mode']}")
        print(f"Timestamp: {event.data['timestamp_utc']}")
        print("\nEmotional context:")
        for emotion, value in emotional_context.items():
            bar = '█' * int(value * 15) + '░' * (15 - int(value * 15))
            print(f"  {emotion:12s}: [{bar}] {value:.2f}")
        print(f"\nResponse: \"{event.data['response_fragment']}\"")
        print(f"{'='*60}\n")
    
    @pytest.mark.asyncio
    async def test_correlation_flow(self):
        """Тест связывания событий через correlation_id."""
        # Симуляция одного цикла анализа
        correlation_id = f"analysis_{uuid4()}"
        user_id = "correlation_test_user"
        
        # 1. Обновился стиль
        style_event = StyleVectorUpdatedEvent.create(
            user_id=user_id,
            old_vector={"playfulness": 0.5, "seriousness": 0.5, "emotionality": 0.5, "creativity": 0.5},
            new_vector={"playfulness": 0.7, "seriousness": 0.3, "emotionality": 0.8, "creativity": 0.6},
            messages_analyzed=25,
            significant_change=True,
            dominant_style="emotional",
            correlation_id=correlation_id
        )
        
        # 2. Обновилась персона
        persona_event = PartnerPersonaUpdatedEvent.create(
            user_id=user_id,
            persona_id=str(uuid4()),
            version=2,
            previous_mode="expert",
            recommended_mode="talk",
            confidence_score=0.8,
            prediction_data=None,
            reason="significant_change",
            correlation_id=correlation_id
        )
        
        # 3. Обнаружены черты
        trait_event = PersonalityTraitDetectedEvent.create(
            user_id=user_id,
            trait_name="empathy",
            strength=0.82,
            context_mode="talk",
            confidence=0.9,
            trigger_markers=["понимаю", "чувствую"],
            message_preview="Я понимаю твои чувства",
            correlation_id=correlation_id
        )
        
        # Проверка связывания
        assert style_event.correlation_id == correlation_id
        assert persona_event.correlation_id == correlation_id
        assert trait_event.correlation_id == correlation_id
        
        print(f"\n{'='*60}")
        print("Correlation Flow Test:")
        print(f"{'='*60}")
        print(f"Correlation ID: {correlation_id}")
        print("\nLinked events:")
        print(f"1. {style_event.event_type} - dominant: {style_event.data['dominant_style']}")
        print(f"2. {persona_event.event_type} - mode: {persona_event.data['recommended_mode']}")
        print(f"3. {trait_event.event_type} - trait: {trait_event.data['trait_name']}")
        print("\n✅ All events properly linked!")
        print(f"{'='*60}\n")
    
    @pytest.mark.asyncio
    async def test_serialization(self):
        """Тест сериализации событий для Event Store."""
        event = PersonalityTraitDetectedEvent.create(
            user_id="serialization_test",
            trait_name="playfulness",
            strength=0.95,
            context_mode="talk",
            confidence=0.88,
            trigger_markers=["ахаха", "лол", "круто!"],
            message_preview="Ахаха, это же просто космос!"
        )
        
        # Сериализация
        event_dict = event.to_dict()
        
        # Проверки
        assert isinstance(event_dict, dict)
        assert "event_id" in event_dict
        assert "timestamp" in event_dict
        assert isinstance(event_dict["timestamp"], str)  # должна быть строка
        assert event_dict["stream_id"] == "personality_serialization_test"
        assert event_dict["event_type"] == "PersonalityTraitDetectedEvent"
        assert event_dict["version"] == 0
        
        print(f"\n{'='*60}")
        print("Serialization Test:")
        print(f"{'='*60}")
        print(f"Event ID: {event_dict['event_id']}")
        print(f"Timestamp: {event_dict['timestamp']}")
        print(f"Stream ID: {event_dict['stream_id']}")
        print(f"Type: {event_dict['event_type']}")
        print(f"Data keys: {list(event_dict['data'].keys())}")
        print("\n✅ Serialization successful!")
        print(f"{'='*60}\n")
    
    @pytest.mark.asyncio
    async def test_all_trait_names(self):
        """Тест создания событий для всех типов черт."""
        trait_names = [
            "curiosity", "irony", "empathy", "philosophical", "playfulness",
            "analytical", "aesthetics", "caring", "allusive", "reflective",
            "paradoxical", "rebellious", "magical_realism"
        ]
        
        print(f"\n{'='*60}")
        print("All Traits Test:")
        print(f"{'='*60}")
        
        for trait_name in trait_names:
            event = PersonalityTraitDetectedEvent.create(
                user_id="all_traits_test",
                trait_name=trait_name,
                strength=0.5,
                context_mode="talk",
                confidence=0.7,
                trigger_markers=["test"],
                message_preview="Test"
            )
            
            assert event.data["trait_name"] == trait_name
            print(f"✓ {trait_name:20s} - OK")
        
        print(f"\n✅ All {len(trait_names)} traits tested successfully!")
        print(f"{'='*60}\n")
    
    @pytest.mark.asyncio
    async def test_edge_cases(self):
        """Тест граничных случаев."""
        # Пустые векторы
        event1 = StyleVectorUpdatedEvent.create(
            user_id="edge_case_user",
            old_vector={},  # Пустой старый вектор (первый раз)
            new_vector={"playfulness": 0.5, "seriousness": 0.5, "emotionality": 0.5, "creativity": 0.5},
            messages_analyzed=0,
            significant_change=False,
            dominant_style="serious"
        )
        assert event1.data["old_vector"] == {}
        
        # Нулевые значения
        event2 = PersonalityTraitDetectedEvent.create(
            user_id="zero_user",
            trait_name="analytical",
            strength=0.0,  # Минимальная сила
            context_mode="expert",
            confidence=0.0,  # Минимальная уверенность
            trigger_markers=[],  # Пустой список маркеров
            message_preview=""  # Пустое превью
        )
        assert event2.data["strength"] == 0.0
        assert event2.data["trigger_markers"] == []
        assert event2.data["message_preview"] == ""
        
        # Максимальные значения
        event3 = TraitManifestationEvent.create(
            user_id="max_user",
            trait_name="empathy",
            manifestation_id=str(uuid4()),
            intensity=1.0,  # Максимальная интенсивность
            emotional_context={"caring": 1.0, "love": 1.0, "gratitude": 1.0},
            mode="talk",
            response_fragment="Perfect empathy",
            timestamp_utc=datetime.utcnow().isoformat()
        )
        assert event3.data["intensity"] == 1.0
        assert all(v == 1.0 for v in event3.data["emotional_context"].values())
        
        # None в optional полях
        event4 = PartnerPersonaUpdatedEvent.create(
            user_id="none_user",
            persona_id=str(uuid4()),
            version=1,
            previous_mode=None,  # Нет предыдущего режима
            recommended_mode="talk",
            confidence_score=0.5,
            prediction_data=None,  # Нет предсказаний
            reason="manual"
        )
        assert event4.data["previous_mode"] is None
        assert event4.data["prediction_data"] is None
        assert event4.correlation_id is None  # Не передан
        
        print(f"\n{'='*60}")
        print("Edge Cases Test:")
        print(f"{'='*60}")
        print("✓ Empty vectors handled")
        print("✓ Zero values accepted")
        print("✓ Maximum values accepted")
        print("✓ None in optional fields handled")
        print("\n✅ All edge cases passed!")
        print(f"{'='*60}\n")


# Запуск тестов напрямую
if __name__ == "__main__":
    async def run_tests():
        test = TestPersonalityEvents()
        
        print("\n🧪 Running PersonalityEvents Tests...\n")
        
        await test.test_personality_trait_detected_event()
        await test.test_text_truncation()
        await test.test_style_vector_updated_event()
        await test.test_partner_persona_updated_event()
        await test.test_trait_manifestation_event()
        await test.test_correlation_flow()
        await test.test_serialization()
        await test.test_all_trait_names()
        await test.test_edge_cases()
        
        print("\n✅ All tests completed successfully!")
    
    asyncio.run(run_tests())