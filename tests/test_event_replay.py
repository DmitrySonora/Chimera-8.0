import asyncio
from datetime import datetime, timedelta, timezone
from services.event_replay_service import EventReplayService
from database.connection import db_connection

async def test_service():
    """Тестирование EventReplayService"""
    
    print("🚀 Начинаем тестирование EventReplayService...")
    
    # Подключаемся к БД
    print("📡 Подключаемся к БД...")
    await db_connection.connect()
    print("✅ Подключение установлено")
    
    try:
        # Создаем сервис
        print("🔧 Создаем сервис...")
        service = EventReplayService(db_connection)
        
        # Тестируем с реальным user_id (замени на существующий)
        user_id = "502312936"  # <-- ЗАМЕНИ НА РЕАЛЬНЫЙ ID
        
        # Период для анализа - последние 7 дней
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=7)
        
        # 1. Тест replay_user_events
        print("\n📊 Тестируем replay_user_events...")
        events = await service.replay_user_events(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date
        )
        print(f"✅ Найдено событий: {len(events)}")
        if events:
            print(f"   Первое событие: {events[0].event_type}")
            print(f"   Последнее событие: {events[-1].event_type}")
        
        # 2. Тест get_ltm_usage_stats
        print("\n📈 Тестируем get_ltm_usage_stats...")
        stats = await service.get_ltm_usage_stats(
            user_id=user_id,
            period=(start_date, end_date)
        )
        print("✅ Статистика LTM:")
        print(f"   Всего сообщений: {stats['total_messages']}")
        print(f"   LTM запросов: {stats['ltm_queries']}")
        print(f"   Процент с LTM: {stats['ltm_percentage']:.1f}%")
        print(f"   Сохранено в LTM: {stats['saved_to_ltm']}")
        print(f"   Среднее воспоминаний: {stats['avg_memories_per_query']:.2f}")
        
        # 3. Тест get_trigger_distribution
        print("\n🎯 Тестируем get_trigger_distribution...")
        triggers = await service.get_trigger_distribution()
        print("✅ Распределение триггеров:")
        for trigger, count in triggers.items():
            print(f"   {trigger}: {count}")
        
        # 4. Метрики сервиса
        metrics = service.get_metrics()
        print("\n📊 Метрики сервиса:")
        print(f"   Всего replay: {metrics['total_replays']}")
        print(f"   Обработано событий: {metrics['total_events_processed']}")
        print(f"   Ошибок декомпрессии: {metrics['decompression_errors']}")
        
        print("\n✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
        
    except Exception as e:
        print(f"\n❌ ОШИБКА: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n🔌 Отключаемся от БД...")
        await db_connection.disconnect()
        print("✅ Отключение завершено")

if __name__ == "__main__":
    asyncio.run(test_service())