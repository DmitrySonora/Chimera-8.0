"""
Интеграционный тест PersonalityActor.
Запуск: pytest tests/test_personality_actor.py -v -s
"""
import asyncio
import pytest
from datetime import datetime, timezone

from database.connection import db_connection
from database.redis_connection import redis_connection
from actors.actor_system import ActorSystem
from actors.personality import PersonalityActor
from actors.user_session import UserSessionActor
from actors.memory_actor import MemoryActor
from actors.generation_actor import GenerationActor
from actors.auth import AuthActor
from actors.perception_actor import PerceptionActor
from actors.talk_model_actor import TalkModelActor
from actors.messages import ActorMessage, MESSAGE_TYPES


class TestPersonalityActorIntegration:
    """Интеграционный тест PersonalityActor"""
    
    @pytest.mark.asyncio
    async def test_personality_computation_flow(self):
        """Тест полного цикла вычисления профиля личности"""
        
        # Подключаемся к БД и Redis
        if not db_connection._is_connected:
            await db_connection.connect()
        
        if not redis_connection.is_connected():
            await redis_connection.connect()
        
        # Тестовый пользователь
        TEST_USER_ID = "test_personality_user"
        
        # Создаем систему акторов
        system = ActorSystem("test-personality-system")
        await system.create_and_set_event_store()
        
        # Создаем все необходимые акторы
        personality = PersonalityActor()
        user_session = UserSessionActor()
        memory = MemoryActor()
        generation = GenerationActor()
        auth = AuthActor()
        perception = PerceptionActor("perception")
        talk_model = TalkModelActor()
        
        # Регистрируем акторы
        await system.register_actor(personality)
        await system.register_actor(user_session)
        await system.register_actor(memory)
        await system.register_actor(generation)
        await system.register_actor(auth)
        await system.register_actor(perception)
        await system.register_actor(talk_model)
        
        await system.start()
        
        try:
            print(f"\n{'='*60}")
            print("ТЕСТ ВЫЧИСЛЕНИЯ ПРОФИЛЯ ЛИЧНОСТИ")
            print(f"{'='*60}")
            
            # Собираем все сообщения для анализа
            all_messages = []
            original_send = system.send_message
            
            async def tracking_send(actor_id, message):
                all_messages.append({
                    'to': actor_id,
                    'type': message.message_type,
                    'from': message.sender_id,
                    'payload': message.payload
                })
                await original_send(actor_id, message)
            
            system.send_message = tracking_send
            
            # 1. Отправляем эмоциональные модификаторы
            print("\n1. Отправка эмоциональных модификаторов")
            
            emotion_msg = ActorMessage.create(
                sender_id="perception",
                message_type=MESSAGE_TYPES['UPDATE_PERSONALITY_CONTEXT'],
                payload={
                    'user_id': TEST_USER_ID,
                    'modifier_type': 'emotion',
                    'modifier_data': {
                        'joy': 0.8,
                        'curiosity': 0.6,
                        'sadness': 0.6,
                        'excitement': 0.7
                    }
                }
            )
            
            await system.send_message("personality", emotion_msg)
            await asyncio.sleep(0.5)
            
            print("✓ Эмоциональные модификаторы отправлены")
            
            # 2. Отправляем стилевые модификаторы
            print("\n2. Отправка стилевых модификаторов")
            
            style_msg = ActorMessage.create(
                sender_id="talk_model",
                message_type=MESSAGE_TYPES['UPDATE_PERSONALITY_CONTEXT'],
                payload={
                    'user_id': TEST_USER_ID,
                    'modifier_type': 'style',
                    'modifier_data': {
                        'playfulness': 1.2,
                        'curiosity': 1.1,
                        'analytical': 0.8,
                        'empathy': 1.15
                    }
                }
            )
            
            await system.send_message("personality", style_msg)
            await asyncio.sleep(0.5)
            
            print("✓ Стилевые модификаторы отправлены")
            
            # 3. Первый запрос профиля (cache miss)
            print("\n3. Первый запрос профиля личности")
            
            # Создаем тестовый актор для получения ответа
            test_actor_id = "test_requester"
            from actors.base_actor import BaseActor
            
            class TestRequester(BaseActor):
                def __init__(self):
                    super().__init__(test_actor_id, "TestRequester")
                    self.received_profiles = []
                    
                async def handle_message(self, message):
                    if message.message_type == MESSAGE_TYPES['PERSONALITY_PROFILE_RESPONSE']:
                        self.received_profiles.append(message.payload)
                    return None
                
                async def initialize(self):
                    pass
                
                async def shutdown(self):
                    pass
            
            test_requester = TestRequester()
            await system.register_actor(test_requester)
            
            get_profile_msg = ActorMessage.create(
                sender_id=test_actor_id,
                message_type=MESSAGE_TYPES['GET_PERSONALITY_PROFILE'],
                payload={'user_id': TEST_USER_ID}
            )
            
            await system.send_message("personality", get_profile_msg)
            await asyncio.sleep(1.0)
            
            # Проверяем результат
            if test_requester.received_profiles:
                profile = test_requester.received_profiles[0]
                print("\n✓ Профиль получен:")
                print(f"  - User ID: {profile['user_id']}")
                print(f"  - Доминирующие черты: {', '.join(profile['dominant_traits'])}")
                print(f"  - Всего черт: {len(profile['active_traits'])}")
                
                # Выводим топ-5 черт с значениями
                print("\n  Топ-5 черт:")
                for trait in profile['dominant_traits']:
                    value = profile['active_traits'][trait]
                    print(f"    - {trait}: {value:.3f}")
            else:
                print("✗ Профиль не получен!")
            
            # 4. Второй запрос (cache hit)
            print("\n4. Повторный запрос профиля (проверка кэша)")
            
            await system.send_message("personality", get_profile_msg)
            await asyncio.sleep(0.5)
            
            # 5. Проверяем Redis кэш
            print("\n5. Проверка Redis кэша")
            
            redis_client = redis_connection.get_client()
            if redis_client:
                cache_key = redis_connection.make_key("personality", "profile", TEST_USER_ID)
                cached_data = await redis_client.get(cache_key)
                
                if cached_data:
                    print("✓ Профиль в кэше Redis:")
                    print(f"  - Ключ: {cache_key}")
                    print(f"  - Размер: {len(cached_data)} байт")
                    
                    # Проверяем TTL
                    ttl = await redis_client.ttl(cache_key)
                    print(f"  - TTL: {ttl} секунд")
                else:
                    print("✗ Профиль НЕ найден в кэше")
            
            # 6. Анализ потока сообщений
            print("\n6. Анализ потока сообщений")
            print(f"Всего сообщений: {len(all_messages)}")
            
            # Фильтруем по типам
            update_contexts = [m for m in all_messages if m['type'] == 'update_personality_context']
            get_profiles = [m for m in all_messages if m['type'] == 'get_personality_profile']
            profile_responses = [m for m in all_messages if m['type'] == 'personality_profile_response']
            
            print(f"  - UPDATE_PERSONALITY_CONTEXT: {len(update_contexts)}")
            print(f"  - GET_PERSONALITY_PROFILE: {len(get_profiles)}")
            print(f"  - PERSONALITY_PROFILE_RESPONSE: {len(profile_responses)}")
            
            # 7. Проверка корректности вычислений
            print("\n7. Проверка корректности вычислений")
            
            if test_requester.received_profiles:
                profile_data = test_requester.received_profiles[0]['active_traits']
                
                # Проверяем диапазон значений
                all_in_range = all(0.0 <= v <= 1.0 for v in profile_data.values())
                print(f"  ✓ Все значения в диапазоне [0.0, 1.0]: {all_in_range}")
                
                # Проверяем влияние модификаторов
                curiosity_value = profile_data.get('curiosity', 0)
                playfulness_value = profile_data.get('playfulness', 0)
                
                print("\n  Влияние модификаторов:")
                print(f"  - curiosity (style: 1.1, emotion: joy+excitement): {curiosity_value:.3f}")
                print(f"  - playfulness (style: 1.2): {playfulness_value:.3f}")
                
                # Проверяем временной модификатор
                current_hour = datetime.now(timezone.utc).hour
                if 6 <= current_hour < 11:
                    temporal = "утро (0.9)"
                elif 11 <= current_hour < 18:
                    temporal = "день (1.0)"
                elif 18 <= current_hour < 23:
                    temporal = "вечер (0.95)"
                else:
                    temporal = "ночь (0.85)"
                print(f"  - Временной модификатор: {temporal}")
            
            # 8. Метрики PersonalityActor
            print("\n8. Метрики PersonalityActor")
            metrics = personality._metrics
            print(f"  - Базовых черт загружено: {metrics['base_traits_loaded']}")
            print(f"  - Core черт: {metrics['core_traits_count']}")
            print(f"  - Профилей вычислено: {metrics['profiles_calculated']}")
            print(f"  - Cache hits: {metrics['cache_hits']}")
            print(f"  - Cache misses: {metrics['cache_misses']}")
            print(f"  - Модификаторов получено: {metrics['modifiers_received']}")
            
            # Детали по типам модификаторов
            print("\n  Модификаторы по типам:")
            for mod_type, count in metrics['modifiers_by_type'].items():
                print(f"    - {mod_type}: {count}")
            
            # 9. Проверка сохранения в БД
            print("\n9. Проверка сохранения истории модификаторов")
            
            if personality._pool:
                history_count = await personality._pool.fetchval(
                    """
                    SELECT COUNT(*) FROM personality_modifier_history
                    WHERE user_id = $1
                    """,
                    TEST_USER_ID
                )
                print(f"  - Записей в истории: {history_count}")
                
                # Детальная разбивка по типам
                type_counts = await personality._pool.fetch(
                    """
                    SELECT modifier_type, COUNT(*) as count
                    FROM personality_modifier_history
                    WHERE user_id = $1
                    GROUP BY modifier_type
                    ORDER BY modifier_type
                    """,
                    TEST_USER_ID
                )
                
                if type_counts:
                    print("  - Разбивка по типам:")
                    for row in type_counts:
                        print(f"    * {row['modifier_type']}: {row['count']}")
                
                # Последние модификаторы
                last_modifiers = await personality._pool.fetch(
                    """
                    SELECT modifier_type, modifier_source, applied_at
                    FROM personality_modifier_history
                    WHERE user_id = $1
                    ORDER BY applied_at DESC
                    LIMIT 5
                    """,
                    TEST_USER_ID
                )
                
                if last_modifiers:
                    print("\n  Последние модификаторы:")
                    for mod in last_modifiers:
                        print(f"    - {mod['modifier_type']} от {mod['modifier_source']} в {mod['applied_at']}")
            
            # ИТОГОВЫЕ ПРОВЕРКИ
            print(f"\n{'='*60}")
            print("РЕЗУЛЬТАТЫ ТЕСТА")
            print(f"{'='*60}")
            
            success_checks = []
            
            # Проверка 1: Профиль вычислен
            if test_requester.received_profiles:
                success_checks.append("✓ Профиль успешно вычислен")
            else:
                success_checks.append("✗ Профиль НЕ вычислен")
            
            # Проверка 2: Кэширование работает
            if metrics['cache_hits'] > 0:
                success_checks.append("✓ Redis кэширование работает")
            else:
                success_checks.append("✗ Redis кэширование НЕ работает")
            
            # Проверка 3: Модификаторы применены
            if metrics['modifiers_received'] >= 2:
                success_checks.append("✓ Модификаторы получены и обработаны")
            else:
                success_checks.append("✗ Модификаторы НЕ обработаны")
            
            # Проверка 4: Мультипликативная модель
            if test_requester.received_profiles:
                # Черты с высокими модификаторами должны быть в топе
                top_traits = test_requester.received_profiles[0]['dominant_traits']
                if 'playfulness' in top_traits[:3] or 'curiosity' in top_traits[:3]:
                    success_checks.append("✓ Мультипликативная модель работает")
                else:
                    success_checks.append("✗ Мультипликативная модель НЕ работает")
            
            for check in success_checks:
                print(check)
            
            print(f"\n{'='*60}\n")
            
        finally:
            # Очищаем тестовые данные
            if personality._pool:
                await personality._pool.execute(
                    "DELETE FROM personality_modifier_history WHERE user_id = $1",
                    TEST_USER_ID
                )
            
            # Очищаем Redis
            if redis_client:
                cache_key = redis_connection.make_key("personality", "profile", TEST_USER_ID)
                await redis_client.delete(cache_key)
            
            await system.stop()
            
            # Закрываем Event Store
            if hasattr(system, '_event_store') and system._event_store:
                await system._event_store.close()
            
            print("Система остановлена, тестовые данные очищены")
    
    @pytest.mark.asyncio
    async def test_personality_degraded_mode(self):
        """Тест работы в degraded mode без Redis"""
        
        if not db_connection._is_connected:
            await db_connection.connect()
        
        # Создаем актор без Redis
        personality = PersonalityActor()
        personality._redis = None  # Имитируем отсутствие Redis
        await personality.initialize()
        
        print(f"\n{'='*60}")
        print("ТЕСТ DEGRADED MODE (без Redis)")
        print(f"{'='*60}")
        
        # Простой тест вычисления без кэша
        test_user_id = "test_degraded_user"
        
        # Отправляем модификаторы
        emotion_msg = ActorMessage.create(
            sender_id="test",
            message_type=MESSAGE_TYPES['UPDATE_PERSONALITY_CONTEXT'],
            payload={
                'user_id': test_user_id,
                'modifier_type': 'emotion',
                'modifier_data': {'joy': 0.9}
            }
        )
        
        await personality.handle_message(emotion_msg)
        
        # Вычисляем профиль
        profile = await personality._calculate_active_profile(test_user_id)
        
        print("\n✓ Профиль вычислен без Redis:")
        print(f"  - Всего черт: {len(profile)}")
        print(f"  - Cache hits: {personality._metrics['cache_hits']} (должно быть 0)")
        print(f"  - Profiles calculated: {personality._metrics['profiles_calculated']}")
        print(f"  - DB errors: {personality._metrics['db_errors']}")
        
        assert len(profile) == 13
        assert personality._metrics['cache_hits'] == 0
        assert personality._metrics['profiles_calculated'] > 0
        
        await personality.shutdown()
        
        print("\n✓ Degraded mode работает корректно")


# Запуск напрямую
if __name__ == "__main__":
    asyncio.run(TestPersonalityActorIntegration().test_personality_computation_flow())