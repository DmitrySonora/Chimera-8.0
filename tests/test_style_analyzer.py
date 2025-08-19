"""
Интеграционный тест для StyleAnalyzer с реальной БД.
Полный вывод: pytest tests/test_style_analyzer.py -v -s
"""
import asyncio
import pytest
from database.connection import DatabaseConnection
from services.style_analyzer import StyleAnalyzer


class TestStyleAnalyzer:
    """Интеграционный тест StyleAnalyzer с реальной БД"""
    
    @pytest.mark.asyncio
    async def test_analyze_real_user_style(self):
        """Тест анализа стиля реального пользователя."""
        # Подключение к БД
        db = DatabaseConnection()
        await db.connect()
        
        try:
            # Создание анализатора
            analyzer = StyleAnalyzer(db)
            
            # Анализ стиля реального пользователя
            result = await analyzer.analyze_user_style(
                user_id="502312936",
                limit=50
            )
            
            # Проверки структуры
            assert "style_vector" in result
            assert all(k in result["style_vector"] for k in ["playfulness", "seriousness", "emotionality", "creativity"])
            assert all(0 <= v <= 1 for v in result["style_vector"].values())
            assert 0 <= result["confidence"] <= 1
            assert result["messages_analyzed"] >= 0
            assert "metadata" in result
            assert "analysis_time_ms" in result["metadata"]
            assert "has_sufficient_data" in result["metadata"]
            
            # Логирование результата для визуальной проверки
            print(f"\n{'='*60}")
            print("Style analysis for user 502312936:")
            print(f"{'='*60}")
            print(f"Messages analyzed: {result['messages_analyzed']}")
            print(f"Confidence: {result['confidence']:.3f}")
            print("\nStyle Vector:")
            for component, value in result['style_vector'].items():
                bar = '█' * int(value * 20) + '░' * (20 - int(value * 20))
                print(f"  {component:12s}: [{bar}] {value:.3f}")
            print(f"\nAnalysis time: {result['metadata']['analysis_time_ms']}ms")
            print(f"Sufficient data: {result['metadata']['has_sufficient_data']}")
            print(f"{'='*60}\n")
            
        finally:
            await db.disconnect()

    @pytest.mark.asyncio
    async def test_insufficient_data(self):
        """Тест с недостаточным количеством сообщений."""
        # Подключение к БД
        db = DatabaseConnection()
        await db.connect()
        
        try:
            # Создание анализатора
            analyzer = StyleAnalyzer(db)
            
            # Используем несуществующего пользователя
            result = await analyzer.analyze_user_style(
                user_id="nonexistent_user_123456",
                limit=50
            )
            
            # Должен вернуть нейтральный вектор
            assert result["style_vector"]["playfulness"] == 0.5
            assert result["style_vector"]["seriousness"] == 0.5
            assert result["style_vector"]["emotionality"] == 0.5
            assert result["style_vector"]["creativity"] == 0.5
            assert result["confidence"] == 0.1
            assert result["messages_analyzed"] == 0
            assert result["metadata"]["has_sufficient_data"] is False
            
            print("\nTest insufficient data: PASSED")
            print(f"Neutral vector returned: {result['style_vector']}")
            
        finally:
            await db.disconnect()
    
    @pytest.mark.asyncio
    async def test_performance(self):
        """Тест производительности анализа."""
        # Подключение к БД
        db = DatabaseConnection()
        await db.connect()
        
        try:
            # Создание анализатора
            analyzer = StyleAnalyzer(db)
            
            # Замеряем время для разных объемов
            for limit in [10, 25, 50]:
                result = await analyzer.analyze_user_style(
                    user_id="502312936",
                    limit=limit
                )
                
                analysis_time = result['metadata']['analysis_time_ms']
                print(f"\nPerformance test - {limit} messages: {analysis_time}ms")
                
                # Проверяем что укладываемся в лимит
                if limit <= 50:
                    assert analysis_time < 200, f"Analysis too slow: {analysis_time}ms > 200ms"
                    
        finally:
            await db.disconnect()
    
    @pytest.mark.asyncio
    async def test_playful_style_detection(self):
        """Тест корректного определения игривого стиля."""
        db = DatabaseConnection()
        await db.connect()
        
        try:
            # Создаем тестового пользователя с игривыми сообщениями
            test_user_id = "test_playful_user_123"
            
            # Очищаем старые данные если есть
            await db.execute("DELETE FROM stm_buffer WHERE user_id = $1", test_user_id)
            
            # Вставляем игривые сообщения
            playful_messages = [
                "Ахахах, это же просто бомба! 😂😂😂",
                "Крутяк! Ваще огонь контент получился )))) 🔥",
                "Лол, ну ты даешь, бро! Респект и уважуха 😎",
                "Хихи, прикольно же! Обожаю такое ❤️",
                "Вау!!! Это просто космос какой-то 🚀 кайфово!",
                "Ору с этого))) хахаха, ну ты жжешь 😆",
                "Йоу, братан, это топчик! Имба просто 👍"
            ]
            
            for i, msg in enumerate(playful_messages):
                await db.execute("""
                    INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
                    VALUES ($1, 'user', $2, '{}', $3, NOW())
                """, test_user_id, msg, i)
            
            # Анализируем стиль
            analyzer = StyleAnalyzer(db)
            result = await analyzer.analyze_user_style(test_user_id)
            
            # Проверяем что игривость высокая
            print(f"\n{'='*60}")
            print("Test PLAYFUL style detection:")
            print(f"Playfulness: {result['style_vector']['playfulness']:.3f}")
            print(f"Seriousness: {result['style_vector']['seriousness']:.3f}")
            print(f"Messages: {result['messages_analyzed']}")
            print(f"{'='*60}")
            
            assert result['style_vector']['playfulness'] > 0.6, \
                f"Playfulness too low for playful messages: {result['style_vector']['playfulness']}"
            assert result['style_vector']['seriousness'] < 0.4, \
                f"Seriousness too high for playful messages: {result['style_vector']['seriousness']}"
            
            # Очищаем тестовые данные
            await db.execute("DELETE FROM stm_buffer WHERE user_id = $1", test_user_id)
            
        finally:
            await db.disconnect()
    
    @pytest.mark.asyncio
    async def test_serious_style_detection(self):
        """Тест корректного определения серьезного стиля."""
        db = DatabaseConnection()
        await db.connect()
        
        try:
            test_user_id = "test_serious_user_456"
            
            # Очищаем старые данные
            await db.execute("DELETE FROM stm_buffer WHERE user_id = $1", test_user_id)
            
            # Вставляем серьезные сообщения
            serious_messages = [
                "Следовательно, необходимо рассмотреть данный вопрос более детально и систематически.",
                "В связи с этим, важно отметить ключевые факторы, влияющие на результативность процесса.",
                "Каким образом можно оптимизировать эффективность данной методологии?",
                "Анализируя представленные данные, можно сделать вывод о необходимости структурных изменений.",
                "Безусловно, следует учитывать комплексный характер рассматриваемой проблематики.",
                "Исходя из вышеизложенного, целесообразно применить системный подход к решению."
            ]
            
            for i, msg in enumerate(serious_messages):
                await db.execute("""
                    INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
                    VALUES ($1, 'user', $2, '{}', $3, NOW())
                """, test_user_id, msg, i)
            
            # Анализируем
            analyzer = StyleAnalyzer(db)
            result = await analyzer.analyze_user_style(test_user_id)
            
            print(f"\n{'='*60}")
            print("Test SERIOUS style detection:")
            print(f"Seriousness: {result['style_vector']['seriousness']:.3f}")
            print(f"Playfulness: {result['style_vector']['playfulness']:.3f}")
            print(f"Messages: {result['messages_analyzed']}")
            print(f"{'='*60}")
            
            assert result['style_vector']['seriousness'] > 0.55, \
                f"Seriousness too low: {result['style_vector']['seriousness']}"
            assert result['style_vector']['playfulness'] < 0.3, \
                f"Playfulness too high: {result['style_vector']['playfulness']}"
            
            # Очищаем
            await db.execute("DELETE FROM stm_buffer WHERE user_id = $1", test_user_id)
            
        finally:
            await db.disconnect()
    
    @pytest.mark.asyncio
    async def test_new_vocabulary_categories(self):
        """Тест работы новых категорий словаря (diminutives, emotional_words и т.д.)."""
        db = DatabaseConnection()
        await db.connect()
        
        try:
            # Тестируем diminutives отдельно
            test_user_id = "test_diminutives"
            await db.execute("DELETE FROM stm_buffer WHERE user_id = $1", test_user_id)
            
            diminutive_messages = [
                "Дружочек, солнышко, ты такой милашка!",
                "Котик мой хорошенький, умничка!",
                "Крошка, зайка, славненький такой!",
                "Добренький мой, ласковый, нежненький!",
                "Красотулечка, сладенький мой!",
                "Тепленький, мягонький, хорошенький!"
            ]
            
            for i, msg in enumerate(diminutive_messages):
                await db.execute("""
                    INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
                    VALUES ($1, 'user', $2, '{}', $3, NOW())
                """, test_user_id, msg, i)
            
            analyzer = StyleAnalyzer(db)
            result = await analyzer.analyze_user_style(test_user_id)
            
            print(f"\n{'='*60}")
            print("Test DIMINUTIVES:")
            print(f"Playfulness: {result['style_vector']['playfulness']:.3f}")
            print("Expected: > 0.3 due to diminutives")
            print(f"{'='*60}")
            
            assert result['style_vector']['playfulness'] > 0.3, \
                f"Diminutives not properly detected: {result['style_vector']['playfulness']}"
            
            # Тестируем analytical markers отдельно
            test_user_id = "test_analytical"
            await db.execute("DELETE FROM stm_buffer WHERE user_id = $1", test_user_id)
            
            analytical_messages = [
                "Анализируя данные, систематизируем результаты исследования.",
                "Классифицируя и категоризируя, мы синтезируем выводы.",
                "Методически изучая, рационально оцениваем факторы.",
                "Систематически исследуя, критически интерпретируем данные.",
                "Дедуцируя из предпосылок, индуцируем общие закономерности.",
                "Концептуализируя проблему, операционализируем переменные."
            ]
            
            for i, msg in enumerate(analytical_messages):
                await db.execute("""
                    INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
                    VALUES ($1, 'user', $2, '{}', $3, NOW())
                """, test_user_id, msg, i)
            
            result = await analyzer.analyze_user_style(test_user_id)
            
            print(f"\n{'='*60}")
            print("Test ANALYTICAL MARKERS:")
            print(f"Seriousness: {result['style_vector']['seriousness']:.3f}")
            print("Expected: > 0.4 due to analytical markers")
            print(f"{'='*60}")
            
            assert result['style_vector']['seriousness'] > 0.4, \
                f"Analytical markers not detected: {result['style_vector']['seriousness']}"
            
            # Очищаем
            await db.execute("DELETE FROM stm_buffer WHERE user_id = $1", "test_diminutives")
            await db.execute("DELETE FROM stm_buffer WHERE user_id = $1", "test_analytical")
            
        finally:
            await db.disconnect()
    
    @pytest.mark.asyncio
    async def test_temporal_decay(self):
        """Тест влияния временного decay на анализ."""
        db = DatabaseConnection()
        await db.connect()
        
        try:
            test_user_id = "test_decay_user_321"
            
            # Очищаем
            await db.execute("DELETE FROM stm_buffer WHERE user_id = $1", test_user_id)
            
            # Старые сообщения - серьезные (будут иметь меньший вес)
            old_serious = [
                "Следовательно, необходимо провести детальный анализ.",
                "Методология исследования требует систематизации данных.",
                "В результате оптимизации достигнута высокая эффективность."
            ]
            
            # Новые сообщения - игривые (будут иметь больший вес)
            new_playful = [
                "Ахаха, лол, это же супер! 😂",
                "Круто, бро! Кайф просто 🔥",
                "Вау!!! Обожаю!!! ❤️❤️❤️"
            ]
            
            # Вставляем старые серьезные
            for i, msg in enumerate(old_serious):
                await db.execute("""
                    INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
                    VALUES ($1, 'user', $2, '{}', $3, NOW() - INTERVAL '1 hour')
                """, test_user_id, msg, i)
            
            # Вставляем новые игривые
            for i, msg in enumerate(new_playful):
                await db.execute("""
                    INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
                    VALUES ($1, 'user', $2, '{}', $3, NOW())
                """, test_user_id, msg, i + 3)
            
            # Анализируем
            analyzer = StyleAnalyzer(db)
            result = await analyzer.analyze_user_style(test_user_id)
            
            print(f"\n{'='*60}")
            print("Test TEMPORAL DECAY:")
            print(f"Playfulness: {result['style_vector']['playfulness']:.3f} (should be higher)")
            print(f"Seriousness: {result['style_vector']['seriousness']:.3f} (should be lower)")
            print("Recent playful messages should outweigh old serious ones")
            print(f"{'='*60}")
            
            # Из-за decay игривость должна доминировать
            assert result['style_vector']['playfulness'] > result['style_vector']['seriousness'], \
                f"Temporal decay not working: playfulness {result['style_vector']['playfulness']} <= seriousness {result['style_vector']['seriousness']}"
            
            # Очищаем
            await db.execute("DELETE FROM stm_buffer WHERE user_id = $1", test_user_id)
            
        finally:
            await db.disconnect()
    
    @pytest.mark.asyncio 
    async def test_edge_cases(self):
        """Тест граничных случаев: очень короткие и длинные сообщения."""
        db = DatabaseConnection()
        await db.connect()
        
        try:
            # Тест с очень короткими сообщениями
            test_user_id = "test_short_msgs"
            await db.execute("DELETE FROM stm_buffer WHERE user_id = $1", test_user_id)
            
            short_messages = ["да", "нет", "ок", "хм", "ага", "не", ".", "?"]
            for i, msg in enumerate(short_messages):
                await db.execute("""
                    INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
                    VALUES ($1, 'user', $2, '{}', $3, NOW())
                """, test_user_id, msg, i)
            
            analyzer = StyleAnalyzer(db)
            result = await analyzer.analyze_user_style(test_user_id)
            
            print(f"\n{'='*60}")
            print("Test SHORT MESSAGES:")
            print(f"Confidence: {result['confidence']:.3f} (should be low)")
            print(f"Style: {result['style_vector']}")
            print(f"{'='*60}")
            
            # Confidence должна быть низкой для коротких сообщений
            assert result['confidence'] < 0.5, f"Confidence too high for short messages: {result['confidence']}"
            
            # Тест с очень длинным сообщением
            test_user_id = "test_long_msg"
            await db.execute("DELETE FROM stm_buffer WHERE user_id = $1", test_user_id)
            
            long_message = """
            Это очень длинное сообщение, которое содержит множество различных мыслей и идей.
            Во-первых, необходимо отметить важность систематического подхода к анализу данных.
            Во-вторых, следует учитывать множество факторов, влияющих на конечный результат.
            В-третьих, оптимизация процессов требует комплексного понимания всей системы.
            Кроме того, важно помнить о необходимости постоянного мониторинга и корректировки.
            """
            
            for i in range(5):  # Добавим несколько копий для достаточного количества
                await db.execute("""
                    INSERT INTO stm_buffer (user_id, message_type, content, metadata, sequence_number, timestamp)
                    VALUES ($1, 'user', $2, '{}', $3, NOW())
                """, test_user_id, long_message, i)
            
            result = await analyzer.analyze_user_style(test_user_id)
            
            print(f"\n{'='*60}")
            print("Test LONG MESSAGES:")
            print(f"Seriousness: {result['style_vector']['seriousness']:.3f} (should be high)")
            print(f"Creativity: {result['style_vector']['creativity']:.3f} (should be moderate-high)")
            print(f"{'='*60}")
            
            # Длинные структурированные сообщения должны давать высокую серьезность
            assert result['style_vector']['seriousness'] > 0.6, \
                f"Seriousness too low for long messages: {result['style_vector']['seriousness']}"
            
            # Очищаем
            await db.execute("DELETE FROM stm_buffer WHERE user_id = $1", "test_short_msgs")
            await db.execute("DELETE FROM stm_buffer WHERE user_id = $1", "test_long_msg")
            
        finally:
            await db.disconnect()
    
    


# Запуск тестов напрямую
if __name__ == "__main__":
    async def run_tests():
        test = TestStyleAnalyzer()
        
        print("Running test_analyze_real_user_style...")
        await test.test_analyze_real_user_style()
        
        print("\nRunning test_insufficient_data...")
        await test.test_insufficient_data()
        
        print("\nRunning test_performance...")
        await test.test_performance()
        
        print("\nAll tests completed!")
    
    asyncio.run(run_tests())