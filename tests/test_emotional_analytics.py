"""
Минимальный тест для EmotionalAnalyticsService
"""
import asyncio
from datetime import datetime, timedelta
from services.event_replay_service import EventReplayService
from services.emotional_analytics_service import EmotionalAnalyticsService
from database.connection import db_connection


async def test():
    """Базовый тест функциональности EmotionalAnalyticsService."""
    
    print("=== Тест EmotionalAnalyticsService ===")
    
    try:
        # Инициализируем подключение к БД
        print("Инициализация подключения к БД...")
        await db_connection.connect()
        
        # Создаем сервисы
        print("Создание сервисов...")
        event_service = EventReplayService(db_connection)
        analytics = EmotionalAnalyticsService(db_connection, event_service)
        
        # Тестируем анализ за последнюю неделю
        period = (datetime.now() - timedelta(days=7), datetime.now())
        print(f"Анализ за период: {period[0].strftime('%Y-%m-%d')} - {period[1].strftime('%Y-%m-%d')}")
        
        # Запуск анализа без кэша
        print("Запуск анализа (без кэша)...")
        result = await analytics.analyze_emotional_patterns(
            user_id="502312936",
            period=period,
            use_cache=False
        )
        
        # Выводим результаты
        print("\n=== РЕЗУЛЬТАТЫ ===")
        print(f"Проанализировано сообщений: {result['baseline_stats']['total_messages']}")
        print(f"Воспоминаний в LTM: {result['peaks_stats']['total_ltm_memories']}")
        print(f"Время обработки: {result['metadata']['processing_time_ms']}ms")
        print(f"Всего событий: {result['metadata']['events_processed']}")
        
        # Показываем распределение триггеров LTM
        trigger_dist = result['peaks_stats'].get('trigger_distribution', {})
        if trigger_dist:
            print(f"Распределение триггеров LTM: {trigger_dist}")
        
        # Кластеры
        clusters = result['patterns'].get('clusters', {})
        if clusters:
            print(f"Найдено кластеров: {clusters.get('n_clusters', 0)}")
            print(f"Силуэт: {clusters.get('silhouette_score', 0):.3f}")
        else:
            print("Кластеризация не выполнена (недостаточно данных)")
        
        # LTM триггеры
        ltm_triggers = result['patterns'].get('ltm_triggers', {})
        if ltm_triggers:
            print("Топ LTM триггеров:")
            for emotion, multiplier in list(ltm_triggers.items())[:3]:
                print(f"  {emotion}: {multiplier:.2f}x")
        else:
            print("LTM триггеры не найдены")
        
        # Аномалии
        anomalies = result['patterns'].get('anomalies', [])
        print(f"Найдено аномалий: {len(anomalies)}")
        
        # Доминирующие эмоции (baseline)
        dominant = result['baseline_stats'].get('dominant_emotions', [])
        if dominant:
            print("Топ-3 эмоций (baseline):")
            for i, emotion_data in enumerate(dominant[:3]):
                emotion = emotion_data.get('emotion', 'unknown')
                score = emotion_data.get('score', 0)
                print(f"  {i+1}. {emotion}: {score:.3f}")
        
        print("\n=== ТЕСТ С КЭШЕМ ===")
        # Повторный запуск с кэшем
        print("Запуск анализа (с кэшем)...")
        cached_result = await analytics.analyze_emotional_patterns(
            user_id="502312936",
            period=period,
            use_cache=True
        )
        
        cache_used = cached_result['metadata'].get('cache_used', False)
        cache_time = cached_result['metadata']['processing_time_ms']
        print(f"Кэш использован: {cache_used}")
        print(f"Время с кэшем: {cache_time}ms")
        
        if cache_used and cache_time < 100:
            print("✅ Кэширование работает корректно!")
        elif not cache_used:
            print("ℹ️  Кэш не использован (возможно, нет данных для кэширования)")
        
        print("\n=== ТЕСТ ЗАВЕРШЕН УСПЕШНО ===")
        
    except Exception as e:
        print(f"❌ Ошибка в тесте: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Закрываем подключение
        try:
            await db_connection.disconnect()
        except Exception:
            pass


async def test_edge_cases():
    """Тест edge cases."""
    
    print("\n=== ТЕСТ EDGE CASES ===")
    
    try:
        # Инициализируем подключение к БД (если еще не инициализировано)
        try:
            await db_connection.connect()
        except Exception:
            pass  # Уже подключено
        
        event_service = EventReplayService(db_connection)
        analytics = EmotionalAnalyticsService(db_connection, event_service)
        
        # Тест с несуществующим пользователем
        print("Тест с несуществующим пользователем...")
        result = await analytics.analyze_emotional_patterns(
            user_id="nonexistent_user_999",
            period=(datetime.now() - timedelta(days=1), datetime.now()),
            use_cache=False
        )
        
        print(f"Сообщений найдено: {result['baseline_stats']['total_messages']}")
        print(f"События обработаны: {result['metadata']['events_processed']}")
        
        if result['baseline_stats']['total_messages'] == 0:
            print("✅ Корректно обработан случай отсутствия данных")
        
        # Тест с очень старым периодом
        print("\nТест с очень старым периодом...")
        old_period = (
            datetime.now() - timedelta(days=365),
            datetime.now() - timedelta(days=300)
        )
        
        old_result = await analytics.analyze_emotional_patterns(
            user_id="502312936",
            period=old_period,
            use_cache=False
        )
        
        print(f"Сообщений в старом периоде: {old_result['baseline_stats']['total_messages']}")
        
        print("\n=== EDGE CASES ТЕСТ ЗАВЕРШЕН ===")
        
    except Exception as e:
        print(f"❌ Ошибка в edge cases тесте: {e}")
    finally:
        # Закрываем подключение
        try:
            await db_connection.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    print("Запуск тестов EmotionalAnalyticsService...")
    
    asyncio.run(test())
    asyncio.run(test_edge_cases())
    
    print("\nВсе тесты завершены!")