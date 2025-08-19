"""
Интеграционный тест для PartnerPersonaBuilder с реальной БД.
Полный вывод: pytest tests/test_partner_persona_builder.py -v -s
"""
import asyncio
import pytest
from uuid import UUID
from database.connection import DatabaseConnection
from services.style_analyzer import StyleAnalyzer
from services.partner_persona_builder import PartnerPersonaBuilder
from models.personality_models import StyleVector


class TestPartnerPersonaBuilder:
    """Интеграционный тест PartnerPersonaBuilder с реальной БД"""
    
    @pytest.mark.asyncio
    async def test_persona_building_real_user(self):
        """Тест создания и версионирования персоны реального пользователя 502312936."""
        # Подключение к БД
        db = DatabaseConnection()
        await db.connect()
        
        try:
            # Очищаем старые персоны для чистого теста
            await db.execute(
                "DELETE FROM partner_personas WHERE user_id = $1",
                "502312936"
            )
            print("🧹 Cleaned up old personas for user 502312936")
            # 1. Получить стиль через StyleAnalyzer
            print(f"\n{'='*60}")
            print("STEP 1: Analyzing style for user 502312936")
            print(f"{'='*60}")
            
            analyzer = StyleAnalyzer(db)
            style_result = await analyzer.analyze_user_style(
                user_id="502312936",
                limit=50
            )
            
            print(f"Messages analyzed: {style_result['messages_analyzed']}")
            print(f"Style confidence: {style_result['confidence']:.3f}")
            print("\nStyle Vector:")
            for component, value in style_result['style_vector'].items():
                bar = '█' * int(value * 20) + '░' * (20 - int(value * 20))
                print(f"  {component:12s}: [{bar}] {value:.3f}")
            
            # 2. Создать первую персону через PartnerPersonaBuilder
            print(f"\n{'='*60}")
            print("STEP 2: Building first persona version")
            print(f"{'='*60}")
            
            builder = PartnerPersonaBuilder(db)
            persona_v1 = await builder.build_or_update_persona(
                user_id="502312936",
                style_result=style_result
            )
            
            # Проверки первой версии
            assert persona_v1.user_id == "502312936"
            assert persona_v1.version == 1
            assert persona_v1.is_active
            assert persona_v1.recommended_mode in ["talk", "expert", "creative"]
            assert isinstance(persona_v1.persona_id, UUID)
            assert persona_v1.messages_analyzed == style_result['messages_analyzed']
            
            print("✅ Persona v1 created:")
            print(f"  ID: {persona_v1.persona_id}")
            print(f"  Version: {persona_v1.version}")
            print(f"  Mode: {persona_v1.recommended_mode} (confidence: {persona_v1.mode_confidence:.3f})")
            print(f"  Style confidence: {persona_v1.style_confidence:.3f}")
            print(f"  Messages analyzed: {persona_v1.messages_analyzed}")
            
            # 3. Проверить что незначительные изменения НЕ создают новую версию
            print(f"\n{'='*60}")
            print("STEP 3: Testing insignificant changes (should NOT create new version)")
            print(f"{'='*60}")
            
            # Создаем слегка измененный style_result (< 20%)
            modified_style = style_result.copy()
            old_vector = style_result['style_vector'].copy()
            modified_style['style_vector'] = {
                'playfulness': min(1.0, old_vector['playfulness'] + 0.1),  # +10%
                'seriousness': max(0.0, old_vector['seriousness'] - 0.1),  # -10%
                'emotionality': old_vector['emotionality'],
                'creativity': old_vector['creativity']
            }
            
            print("Minor changes applied:")
            print(f"  playfulness: {old_vector['playfulness']:.3f} → {modified_style['style_vector']['playfulness']:.3f}")
            print(f"  seriousness: {old_vector['seriousness']:.3f} → {modified_style['style_vector']['seriousness']:.3f}")
            
            persona_same = await builder.build_or_update_persona(
                user_id="502312936",
                style_result=modified_style
            )
            
            # Должна вернуться та же версия
            assert persona_same.version == 1, f"Expected version 1, got {persona_same.version}"
            assert persona_same.persona_id == persona_v1.persona_id
            print("✅ Correctly returned existing version (no new version created)")
            
            # 4. Проверить что значительные изменения СОЗДАЮТ новую версию
            print(f"\n{'='*60}")
            print("STEP 4: Testing significant changes (should CREATE new version)")
            print(f"{'='*60}")
            
            # Создаем значительно измененный style_result (> 20%)
            significant_style = style_result.copy()
            significant_style['style_vector'] = {
                'playfulness': min(1.0, old_vector['playfulness'] + 0.3),  # +30%
                'seriousness': max(0.0, old_vector['seriousness'] - 0.25),  # -25%
                'emotionality': min(1.0, old_vector['emotionality'] + 0.25),  # +25%
                'creativity': old_vector['creativity']
            }
            significant_style['messages_analyzed'] = 100  # Больше сообщений проанализировано
            
            print("Significant changes applied:")
            for component in ['playfulness', 'seriousness', 'emotionality', 'creativity']:
                old_val = old_vector[component]
                new_val = significant_style['style_vector'][component]
                change = new_val - old_val
                print(f"  {component:12s}: {old_val:.3f} → {new_val:.3f} (change: {change:+.3f})")
            
            persona_v2 = await builder.build_or_update_persona(
                user_id="502312936",
                style_result=significant_style
            )
            
            # Проверки новой версии
            assert persona_v2.version == 2, f"Expected version 2, got {persona_v2.version}"
            assert persona_v2.persona_id != persona_v1.persona_id
            assert persona_v2.is_active
            assert persona_v2.messages_analyzed == 100
            
            print("\n✅ Persona v2 created:")
            print(f"  ID: {persona_v2.persona_id}")
            print(f"  Version: {persona_v2.version}")
            print(f"  Mode: {persona_v2.recommended_mode} (confidence: {persona_v2.mode_confidence:.3f})")
            print(f"  Messages analyzed: {persona_v2.messages_analyzed}")
            
            # 5. Проверить что старая версия деактивирована
            print(f"\n{'='*60}")
            print("STEP 5: Verifying old version deactivation")
            print(f"{'='*60}")
            
            old_persona_check = await db.fetchrow(
                "SELECT * FROM partner_personas WHERE persona_id = $1",
                persona_v1.persona_id
            )
            
            assert not old_persona_check['is_active'], "Old version should be deactivated"
            print("✅ Version 1 correctly deactivated (is_active = False)")
            
            # 6. Проверить что только одна активная версия существует
            active_count = await db.fetchval(
                "SELECT COUNT(*) FROM partner_personas WHERE user_id = $1 AND is_active = TRUE",
                "502312936"
            )
            
            assert active_count == 1, f"Should have exactly 1 active persona, got {active_count}"
            print("✅ Exactly one active persona exists")
            
            print(f"\n{'='*60}")
            print("✅ ALL TESTS PASSED SUCCESSFULLY!")
            print(f"{'='*60}\n")
            
        finally:
            await db.disconnect()
    
    @pytest.mark.asyncio
    async def test_mode_determination_logic(self):
        """Тест корректного определения режима на основе StyleVector."""
        db = DatabaseConnection()
        await db.connect()
        
        try:
            builder = PartnerPersonaBuilder(db)
            
            print(f"\n{'='*60}")
            print("Testing mode determination algorithm")
            print(f"{'='*60}\n")
            
            # Тест 1: Высокая креативность → creative
            creative_vector = StyleVector(
                playfulness=0.5,
                seriousness=0.5,
                emotionality=0.5,
                creativity=0.8  # > 0.7
            )
            mode, confidence = builder._determine_mode(creative_vector)
            assert mode == "creative", f"Expected 'creative', got '{mode}'"
            assert confidence == 0.8, f"Expected confidence 0.8, got {confidence}"
            print(f"✅ High creativity (0.8) → mode: {mode}, confidence: {confidence:.3f}")
            
            # Тест 2: Высокая серьезность + низкая игривость → expert
            serious_vector = StyleVector(
                playfulness=0.2,  # < 0.3
                seriousness=0.8,  # > 0.7
                emotionality=0.5,
                creativity=0.4
            )
            mode, confidence = builder._determine_mode(serious_vector)
            assert mode == "expert", f"Expected 'expert', got '{mode}'"
            assert confidence == 0.8, f"Expected confidence 0.8, got {confidence}"
            print(f"✅ High seriousness (0.8) + low playfulness (0.2) → mode: {mode}, confidence: {confidence:.3f}")
            
            # Тест 3: Высокая игривость + низкая серьезность → talk
            playful_vector = StyleVector(
                playfulness=0.8,  # > 0.7
                seriousness=0.2,  # < 0.3
                emotionality=0.6,
                creativity=0.4
            )
            mode, confidence = builder._determine_mode(playful_vector)
            assert mode == "talk", f"Expected 'talk', got '{mode}'"
            assert confidence == 0.8, f"Expected confidence 0.8, got {confidence}"
            print(f"✅ High playfulness (0.8) + low seriousness (0.2) → mode: {mode}, confidence: {confidence:.3f}")
            
            # Тест 4: Нейтральный вектор → talk с минимальной уверенностью
            neutral_vector = StyleVector(
                playfulness=0.5,
                seriousness=0.5,
                emotionality=0.5,
                creativity=0.5
            )
            mode, confidence = builder._determine_mode(neutral_vector)
            assert mode == "talk", f"Expected 'talk', got '{mode}'"
            assert confidence == 0.6, f"Expected confidence 0.6, got {confidence}"  # PERSONA_MODE_MIN_CONFIDENCE
            print(f"✅ Neutral vector (all 0.5) → mode: {mode}, confidence: {confidence:.3f}")
            
            print(f"\n{'='*60}")
            print("✅ Mode determination logic works correctly!")
            print(f"{'='*60}\n")
            
        finally:
            await db.disconnect()
    
    @pytest.mark.asyncio
    async def test_new_user_first_persona(self):
        """Тест создания первой персоны для нового пользователя."""
        db = DatabaseConnection()
        await db.connect()
        
        try:
            # Используем тестового пользователя
            test_user_id = "test_persona_builder_999"
            
            # Очищаем старые данные персоны если есть
            await db.execute(
                "DELETE FROM partner_personas WHERE user_id = $1",
                test_user_id
            )
            
            # Очищаем STM буфер
            await db.execute(
                "DELETE FROM stm_buffer WHERE user_id = $1",
                test_user_id
            )
            
            print(f"\n{'='*60}")
            print(f"Testing first persona creation for new user: {test_user_id}")
            print(f"{'='*60}\n")
            
            # Вставляем тестовые сообщения
            test_messages = [
                "Привет! Как дела? 😊",
                "Расскажи что-нибудь интересное!",
                "Ого, это круто! 🔥",
                "А можешь объяснить подробнее?",
                "Спасибо, очень познавательно!",
                "Ахаха, смешно 😂"
            ]
            
            for i, msg in enumerate(test_messages):
                await db.execute("""
                    INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
                    VALUES ($1, 'user', $2, '{}', $3, NOW())
                """, test_user_id, msg, i)
            
            # Анализируем стиль
            analyzer = StyleAnalyzer(db)
            style_result = await analyzer.analyze_user_style(test_user_id)
            
            # Создаем первую персону
            builder = PartnerPersonaBuilder(db)
            first_persona = await builder.build_or_update_persona(
                user_id=test_user_id,
                style_result=style_result
            )
            
            # Проверки
            assert first_persona.user_id == test_user_id
            assert first_persona.version == 1, f"First persona should have version 1, got {first_persona.version}"
            assert first_persona.is_active
            assert first_persona.predicted_interests == []  # Заглушка
            assert first_persona.prediction_confidence == 0.0  # Заглушка
            
            print("✅ First persona created successfully:")
            print(f"  User ID: {first_persona.user_id}")
            print(f"  Version: {first_persona.version}")
            print(f"  Mode: {first_persona.recommended_mode}")
            print(f"  Active: {first_persona.is_active}")
            
            # Очищаем тестовые данные
            await db.execute(
                "DELETE FROM partner_personas WHERE user_id = $1",
                test_user_id
            )
            await db.execute(
                "DELETE FROM stm_buffer WHERE user_id = $1",
                test_user_id
            )
            
            print("\n✅ Test data cleaned up")
            
        finally:
            await db.disconnect()
    
    @pytest.mark.asyncio
    async def test_performance(self):
        """Тест производительности построения персоны."""
        db = DatabaseConnection()
        await db.connect()
        
        try:
            import time
            
            print(f"\n{'='*60}")
            print("Performance test for PartnerPersonaBuilder")
            print(f"{'='*60}\n")
            
            analyzer = StyleAnalyzer(db)
            builder = PartnerPersonaBuilder(db)
            
            # Получаем style_result
            style_result = await analyzer.analyze_user_style("502312936", limit=50)
            
            # Замеряем время создания персоны
            start_time = time.time()
            _ = await builder.build_or_update_persona(
                user_id="502312936",
                style_result=style_result
            )
            build_time = (time.time() - start_time) * 1000  # в миллисекундах
            
            print(f"Build/update time: {build_time:.2f}ms")
            
            # Проверяем что укладываемся в разумные пределы
            assert build_time < 500, f"Persona building too slow: {build_time}ms > 500ms"
            
            if build_time < 50:
                print(f"✅ Excellent performance! ({build_time:.2f}ms)")
            elif build_time < 200:
                print(f"✅ Good performance ({build_time:.2f}ms)")
            else:
                print(f"⚠️ Acceptable but could be optimized ({build_time:.2f}ms)")
            
        finally:
            await db.disconnect()


# Запуск тестов напрямую
if __name__ == "__main__":
    async def run_tests():
        test = TestPartnerPersonaBuilder()
        
        print("\n" + "="*70)
        print(" RUNNING PARTNER PERSONA BUILDER INTEGRATION TESTS ")
        print("="*70)
        
        print("\n[1/4] Running test_persona_building_real_user...")
        await test.test_persona_building_real_user()
        
        print("\n[2/4] Running test_mode_determination_logic...")
        await test.test_mode_determination_logic()
        
        print("\n[3/4] Running test_new_user_first_persona...")
        await test.test_new_user_first_persona()
        
        print("\n[4/4] Running test_performance...")
        await test.test_performance()
        
        print("\n" + "="*70)
        print(" ALL INTEGRATION TESTS COMPLETED SUCCESSFULLY! ")
        print("="*70 + "\n")
    
    asyncio.run(run_tests())