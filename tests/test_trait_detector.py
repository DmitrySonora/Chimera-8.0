"""
Интеграционный тест для TraitDetector с реальными данными.
Полный вывод: pytest tests/test_trait_detector.py -v -s
"""
import asyncio
import pytest
from uuid import UUID

from database.connection import db_connection
from services.trait_detector import TraitDetector
from config.vocabulary_chimera_persona import PERSONALITY_TRAITS, TRAIT_CH_DETECTION_THRESHOLD


@pytest.mark.asyncio
async def test_trait_detection_real_user():
    """
    Тестирует детекцию черт на реальных данных пользователя 502312936.
    """
    # Подключаемся к реальной БД
    await db_connection.connect()
    
    try:
        # Создаем TraitDetector
        detector = TraitDetector(db_connection.get_pool())
        
        # Анализируем черты для реального пользователя
        user_id = '502312936'
        manifestations = await detector.detect_traits(user_id, limit=20)
        
        # Проверки
        # 1. Количество обнаруженных черт > 0
        assert len(manifestations) > 0, "Должны быть обнаружены хотя бы некоторые черты"
        
        # 2. Все черты выше порога
        for m in manifestations:
            assert m.manifestation_strength >= TRAIT_CH_DETECTION_THRESHOLD, \
                f"Черта {m.trait_name} имеет силу {m.manifestation_strength} < {TRAIT_CH_DETECTION_THRESHOLD}"
        
        # 3. Проверяем разнообразие черт (минимум 3 разных)
        unique_traits = set(m.trait_name for m in manifestations)
        assert len(unique_traits) >= 3, \
            f"Должно быть минимум 3 разных черты, найдено: {unique_traits}"
        
        # 4. Проверяем, что черты из нашего словаря
        for trait in unique_traits:
            assert trait in PERSONALITY_TRAITS, \
                f"Неизвестная черта: {trait}"
        
        # 5. Проверяем, что empathy не детектируется
        assert 'empathy' not in unique_traits, \
            "Empathy не должна детектироваться (пустые маркеры)"
        
        # 6. Проверяем заполнение полей
        sample_manifestation = manifestations[0]
        assert isinstance(sample_manifestation.manifestation_id, UUID)
        assert sample_manifestation.user_id == user_id
        assert len(sample_manifestation.detected_markers) > 0
        assert sample_manifestation.mode in ['talk', 'expert', 'creative', 'base']
        assert isinstance(sample_manifestation.emotional_context, dict)
        assert sample_manifestation.confidence == sample_manifestation.manifestation_strength
        
        # 7. Проверяем, что все manifestations имеют одинаковый batch_id
        batch_ids = set(m.analysis_batch_id for m in manifestations)
        assert len(batch_ids) == 1, "Все manifestations должны иметь один batch_id"
        
        # Выводим статистику для отладки
        print(f"\nНайдено {len(manifestations)} проявлений черт")
        print(f"Уникальные черты ({len(unique_traits)}): {sorted(unique_traits)}")
        
        # Топ-5 самых сильных проявлений
        top_5 = sorted(manifestations, key=lambda m: m.manifestation_strength, reverse=True)[:5]
        print("\nТоп-5 проявлений:")
        for m in top_5:
            print(f"  - {m.trait_name}: {m.manifestation_strength:.3f} "
                  f"(режим: {m.mode}, маркеры: {m.detected_markers[:3]}...)")
        
    finally:
        await db_connection.disconnect()


@pytest.mark.asyncio
async def test_trait_detector_empty_result():
    """
    Тестирует поведение при отсутствии сообщений.
    """
    await db_connection.connect()
    
    try:
        detector = TraitDetector(db_connection.get_pool())
        
        # Используем несуществующего пользователя
        manifestations = await detector.detect_traits('nonexistent_user_999999')
        
        # Должен вернуть пустой список
        assert manifestations == []
        
    finally:
        await db_connection.disconnect()


@pytest.mark.asyncio 
async def test_trait_detector_performance():
    """
    Тестирует производительность на большом объеме данных.
    """
    import time
    
    await db_connection.connect()
    
    try:
        detector = TraitDetector(db_connection.get_pool())
        
        # Анализируем 50 сообщений
        start_time = time.time()
        manifestations = await detector.detect_traits('502312936', limit=50)
        elapsed_ms = (time.time() - start_time) * 1000
        
        # Проверяем производительность
        assert elapsed_ms < 500, f"Анализ занял {elapsed_ms:.0f}ms, должен быть < 500ms"
        
        print(f"\nПроизводительность: {elapsed_ms:.0f}ms для 50 сообщений")
        print(f"Найдено {len(manifestations)} проявлений")
        
    finally:
        await db_connection.disconnect()

@pytest.mark.asyncio
async def test_curiosity_trait_detection():
    """Тест корректной детекции любознательности."""
    await db_connection.connect()
    
    try:
        # Создаем тестового пользователя с любознательными ответами
        test_user_id = "test_curiosity_bot"
        
        # Очищаем старые данные
        await db_connection.get_pool().execute(
            "DELETE FROM stm_buffer WHERE user_id = $1", test_user_id
        )
        
        # Вставляем сообщения бота с маркерами любознательности
        curious_messages = [
            "Интересно, а почему ты так думаешь? Расскажи подробнее!",
            "Хочется узнать больше деталей! Давай копнём глубже в эту тему.",
            "Любопытно, как это работает? Хочется разобраться в подробностях.",
            "Вникну в это основательно! Докопаюсь до сути вопроса.",
            "Как думаешь, что за этим стоит? Интересно исследовать глубже.",
            "Расскажи еще! Хочется узнать все детали и подробности."
        ]
        
        for i, msg in enumerate(curious_messages):
            await db_connection.get_pool().execute("""
                INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
                VALUES ($1, 'bot', $2, '{"mode": "talk"}', $3, NOW())
            """, test_user_id, msg, i)
        
        # Анализируем черты
        detector = TraitDetector(db_connection.get_pool())
        manifestations = await detector.detect_traits(test_user_id)
        
        # Фильтруем только curiosity
        curiosity_manifestations = [m for m in manifestations if m.trait_name == 'curiosity']
        
        print(f"\n{'='*60}")
        print("Test CURIOSITY trait detection:")
        print(f"Found {len(curiosity_manifestations)} curiosity manifestations")
        if curiosity_manifestations:
            avg_strength = sum(m.manifestation_strength for m in curiosity_manifestations) / len(curiosity_manifestations)
            print(f"Average strength: {avg_strength:.3f}")
            print(f"Markers found: {curiosity_manifestations[0].detected_markers[:3]}...")
        print(f"{'='*60}")
        
        assert len(curiosity_manifestations) >= 4, \
            f"Too few curiosity manifestations: {len(curiosity_manifestations)}"
        assert all(m.manifestation_strength > 0.3 for m in curiosity_manifestations), \
            "Curiosity strength too low"
        
        # Очищаем
        await db_connection.get_pool().execute(
            "DELETE FROM stm_buffer WHERE user_id = $1", test_user_id
        )
        
    finally:
        await db_connection.disconnect()


@pytest.mark.asyncio
async def test_mode_influence():
    """Тест влияния режима общения на детекцию черт."""
    await db_connection.connect()
    
    try:
        # Аналитический текст в разных режимах
        analytical_text = "Анализируя данные, систематизируем результаты. Методически изучаем структуру."
        
        # Expert mode
        test_user_id = "test_mode_expert"
        await db_connection.get_pool().execute(
            "DELETE FROM stm_buffer WHERE user_id = $1", test_user_id
        )
        
        await db_connection.get_pool().execute("""
            INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
            VALUES ($1, 'bot', $2, '{"mode": "expert"}', 1, NOW())
        """, test_user_id, analytical_text)
        
        detector = TraitDetector(db_connection.get_pool())
        expert_manifestations = await detector.detect_traits(test_user_id)
        analytical_expert = [m for m in expert_manifestations if m.trait_name == 'analytical']
        
        # Talk mode
        test_user_id = "test_mode_talk"
        await db_connection.get_pool().execute(
            "DELETE FROM stm_buffer WHERE user_id = $1", test_user_id
        )
        
        await db_connection.get_pool().execute("""
            INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
            VALUES ($1, 'bot', $2, '{"mode": "talk"}', 1, NOW())
        """, test_user_id, analytical_text)
        
        talk_manifestations = await detector.detect_traits(test_user_id)
        analytical_talk = [m for m in talk_manifestations if m.trait_name == 'analytical']
        
        print(f"\n{'='*60}")
        print("Test MODE INFLUENCE on analytical trait:")
        if analytical_expert:
            print(f"Expert mode strength: {analytical_expert[0].manifestation_strength:.3f}")
        if analytical_talk:
            print(f"Talk mode strength: {analytical_talk[0].manifestation_strength:.3f}")
        else:
            print("Talk mode: not detected (affinity=0.3, below threshold)")
        print("Expert should be stronger due to mode affinity")
        print(f"{'='*60}")
        
        # В expert режиме аналитичность должна быть обнаружена
        assert analytical_expert, "Expert mode should detect analytical trait"
        
        if analytical_talk:
            # Если обнаружена в обоих режимах, expert должен быть сильнее
            assert analytical_expert[0].manifestation_strength > analytical_talk[0].manifestation_strength, \
                "Expert mode should have stronger analytical detection"
        else:
            # В talk режиме может не детектироваться из-за низкого affinity
            assert analytical_expert[0].manifestation_strength > 0.5, \
                "Expert mode should have strong analytical detection (>0.5)"
        
        # Очищаем
        await db_connection.get_pool().execute(
            "DELETE FROM stm_buffer WHERE user_id = $1", "test_mode_expert"
        )
        await db_connection.get_pool().execute(
            "DELETE FROM stm_buffer WHERE user_id = $1", "test_mode_talk"
        )
        
    finally:
        await db_connection.disconnect()


@pytest.mark.asyncio
async def test_emotional_context_influence():
    """Тест влияния эмоционального контекста на детекцию черт."""
    await db_connection.connect()
    
    try:
        test_user_id = "test_emotions"
        await db_connection.get_pool().execute(
            "DELETE FROM stm_buffer WHERE user_id = $1", test_user_id
        )
        
        # Игривый текст с разными эмоциями
        playful_text = "Ух ты! Это же супер! Круто получилось!"
        
        # С радостными эмоциями (усилит playfulness)
        await db_connection.get_pool().execute("""
            INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
            VALUES ($1, 'bot', $2, '{"mode": "talk", "emotions": {"joy": 0.9, "amusement": 0.8}}', 1, NOW())
        """, test_user_id, playful_text)
        
        # С грустными эмоциями (ослабит playfulness)
        await db_connection.get_pool().execute("""
            INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
            VALUES ($1, 'bot', $2, '{"mode": "talk", "emotions": {"sadness": 0.8, "grief": 0.7}}', 2, NOW())
        """, test_user_id, playful_text)
        
        detector = TraitDetector(db_connection.get_pool())
        manifestations = await detector.detect_traits(test_user_id)
        
        playful_manifestations = [m for m in manifestations if m.trait_name == 'playfulness']
        
        print(f"\n{'='*60}")
        print("Test EMOTIONAL CONTEXT influence:")
        for m in playful_manifestations:
            emotions = list(m.emotional_context.keys())[:2]
            print(f"Strength: {m.manifestation_strength:.3f} with emotions: {emotions}")
        print("Joy should amplify playfulness")
        print(f"{'='*60}")
        
        # Проверяем что с радостью сильнее
        joyful = [m for m in playful_manifestations if 'joy' in m.emotional_context]
        sad = [m for m in playful_manifestations if 'sadness' in m.emotional_context]
        
        if joyful and sad:
            assert joyful[0].manifestation_strength > sad[0].manifestation_strength, \
                "Joyful emotions should amplify playfulness"
        
        # Очищаем
        await db_connection.get_pool().execute(
            "DELETE FROM stm_buffer WHERE user_id = $1", test_user_id
        )
        
    finally:
        await db_connection.disconnect()


@pytest.mark.asyncio
async def test_logarithmic_scale():
    """Тест логарифмической шкалы для множественных маркеров."""
    await db_connection.connect()
    
    try:
        # Сообщение с 1 маркером
        test_user_id = "test_one_marker"
        await db_connection.get_pool().execute(
            "DELETE FROM stm_buffer WHERE user_id = $1", test_user_id
        )
        
        await db_connection.get_pool().execute("""
            INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
            VALUES ($1, 'bot', $2, '{"mode": "talk"}', 1, NOW())
        """, test_user_id, "Интересно узнать больше.")
        
        detector = TraitDetector(db_connection.get_pool())
        one_marker_result = await detector.detect_traits(test_user_id)
        
        # Сообщение с множеством маркеров
        test_user_id = "test_many_markers"
        await db_connection.get_pool().execute(
            "DELETE FROM stm_buffer WHERE user_id = $1", test_user_id
        )
        
        await db_connection.get_pool().execute("""
            INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
            VALUES ($1, 'bot', $2, '{"mode": "talk"}', 1, NOW())
        """, test_user_id, "Интересно! Любопытно! Хочется узнать, расскажи подробнее! Давай копнём глубже, докопаюсь до деталей!")
        
        many_markers_result = await detector.detect_traits(test_user_id)
        
        print(f"\n{'='*60}")
        print("Test LOGARITHMIC SCALE:")
        
        if one_marker_result:
            one_curiosity = [m for m in one_marker_result if m.trait_name == 'curiosity']
            if one_curiosity:
                print(f"1 marker strength: {one_curiosity[0].manifestation_strength:.3f}")
                print(f"Markers: {one_curiosity[0].detected_markers}")
        
        if many_markers_result:
            many_curiosity = [m for m in many_markers_result if m.trait_name == 'curiosity']
            if many_curiosity:
                print(f"Many markers strength: {many_curiosity[0].manifestation_strength:.3f}")
                print(f"Markers count: {len(many_curiosity[0].detected_markers)}")
        
        print("Should show logarithmic growth, not linear")
        print(f"{'='*60}")
        
        # Проверяем логарифмический рост
        if one_marker_result and many_markers_result:
            one_strength = one_marker_result[0].manifestation_strength if one_marker_result else 0
            many_strength = many_markers_result[0].manifestation_strength if many_markers_result else 0
            
            # С множеством маркеров сила не должна расти линейно
            assert many_strength < one_strength * 3, \
                "Growth should be logarithmic, not linear"
            assert many_strength > one_strength, \
                "More markers should give higher strength"
        
        # Очищаем
        await db_connection.get_pool().execute(
            "DELETE FROM stm_buffer WHERE user_id = $1", "test_one_marker"
        )
        await db_connection.get_pool().execute(
            "DELETE FROM stm_buffer WHERE user_id = $1", "test_many_markers"
        )
        
    finally:
        await db_connection.disconnect()


@pytest.mark.asyncio
async def test_edge_cases():
    """Тест граничных случаев: очень короткие и длинные сообщения."""
    await db_connection.connect()
    
    try:
        # Очень короткое сообщение
        test_user_id = "test_short"
        await db_connection.get_pool().execute(
            "DELETE FROM stm_buffer WHERE user_id = $1", test_user_id
        )
        
        await db_connection.get_pool().execute("""
            INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
            VALUES ($1, 'bot', $2, '{"mode": "talk"}', 1, NOW())
        """, test_user_id, "Интересно!")
        
        detector = TraitDetector(db_connection.get_pool())
        short_result = await detector.detect_traits(test_user_id)
        
        # Очень длинное философское сообщение
        test_user_id = "test_long"
        await db_connection.get_pool().execute(
            "DELETE FROM stm_buffer WHERE user_id = $1", test_user_id
        )
        
        long_philosophical = """
        Размышляя о сущности бытия и природе вещей, приходишь к парадоксальному выводу о том,
        что истина одновременно проста и сложна. Смысл существования раскрывается через познание,
        но само познание есть извечный процесс приближения к недостижимому абсолюту.
        Человеческое сознание, будучи ограниченным, тем не менее стремится к бесконечному,
        и в этом парадоксе заключается вся драма и величие нашего бытия.
        """
        
        await db_connection.get_pool().execute("""
            INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
            VALUES ($1, 'bot', $2, '{"mode": "expert"}', 1, NOW())
        """, test_user_id, long_philosophical)
        
        long_result = await detector.detect_traits(test_user_id)
        
        print(f"\n{'='*60}")
        print("Test EDGE CASES:")
        print(f"Short message traits: {len(short_result)}")
        if short_result:
            print(f"  - {short_result[0].trait_name}: {short_result[0].manifestation_strength:.3f}")
        
        print(f"Long message traits: {len(long_result)}")
        philosophical_traits = [m for m in long_result if m.trait_name in ['philosophical', 'paradoxical']]
        for trait in philosophical_traits[:3]:
            print(f"  - {trait.trait_name}: {trait.manifestation_strength:.3f}")
        print(f"{'='*60}")
        
        # Длинное философское сообщение должно дать больше черт
        assert len(long_result) > len(short_result), \
            "Long message should detect more traits"
        
        # Должны быть философские черты
        assert any(m.trait_name == 'philosophical' for m in long_result), \
            "Philosophical trait should be detected"
        
        # Очищаем
        await db_connection.get_pool().execute(
            "DELETE FROM stm_buffer WHERE user_id = $1", "test_short"
        )
        await db_connection.get_pool().execute(
            "DELETE FROM stm_buffer WHERE user_id = $1", "test_long"
        )
        
    finally:
        await db_connection.disconnect()


if __name__ == "__main__":
    # Запуск тестов
    asyncio.run(test_trait_detection_real_user())
    asyncio.run(test_trait_detector_empty_result())
    asyncio.run(test_trait_detector_performance())