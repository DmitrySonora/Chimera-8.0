"""
Интеграционный тест TalkModelActor на РЕАЛЬНЫХ ДАННЫХ из БД.
Запуск: pytest tests/test_talk_model_actor.py -v -s
"""
import asyncio
import pytest
import json

from database.connection import db_connection
from database.redis_connection import redis_connection
from actors.actor_system import ActorSystem
from actors.talk_model_actor import TalkModelActor
from actors.user_session import UserSessionActor
from actors.memory_actor import MemoryActor
from actors.generation_actor import GenerationActor
from actors.auth import AuthActor
from actors.perception_actor import PerceptionActor
from actors.messages import ActorMessage, MESSAGE_TYPES


class TestTalkModelIntegration:
    """Интеграционный тест на РЕАЛЬНЫХ данных из продакшен БД"""
    
    @pytest.mark.asyncio
    async def test_real_user_partner_persona_flow(self):
        """Тест Partner Persona на РЕАЛЬНОМ пользователе 502312936."""
        
        # Подключаемся к РЕАЛЬНОЙ БД
        if not db_connection._is_connected:
            await db_connection.connect()
        
        if not redis_connection.is_connected():
            await redis_connection.connect()
            
        # РЕАЛЬНЫЙ пользователь из БД
        REAL_USER_ID = "502312936"
        
        # Создаем систему акторов
        system = ActorSystem("test-real-system")
        await system.create_and_set_event_store()
        
        # Создаем ВСЕ акторы
        talk_model = TalkModelActor()
        user_session = UserSessionActor()
        memory = MemoryActor()
        generation = GenerationActor()
        auth = AuthActor()
        perception = PerceptionActor("perception")
        
        # Регистрируем
        await system.register_actor(talk_model)
        await system.register_actor(user_session)
        await system.register_actor(memory)
        await system.register_actor(generation)
        await system.register_actor(auth)
        await system.register_actor(perception)
        
        await system.start()
        
        try:
            print(f"\n{'='*60}")
            print("ТЕСТ НА РЕАЛЬНЫХ ДАННЫХ")
            print(f"{'='*60}")
            
            # 1. Проверяем есть ли реальные данные пользователя
            print(f"\n1. Проверка реальных данных пользователя {REAL_USER_ID}")
            
            # Смотрим сколько сообщений в STM
            msg_count = await db_connection.fetchval(
                "SELECT COUNT(*) FROM stm_buffer WHERE user_id = $1",
                REAL_USER_ID
            )
            print(f"✓ Найдено сообщений в STM: {msg_count}")
            
            # Последние сообщения пользователя
            last_messages = await db_connection.fetch(
                """
                SELECT message_type, content, timestamp 
                FROM stm_buffer 
                WHERE user_id = $1 
                ORDER BY timestamp DESC 
                LIMIT 5
                """,
                REAL_USER_ID
            )
            
            print("\nПоследние сообщения:")
            for msg in last_messages:
                print(f"  [{msg['message_type']}] {msg['timestamp']}: {msg['content'][:50]}...")
            
            # 2. Проверяем есть ли Partner Persona
            print("\n2. Проверка Partner Persona для пользователя")
            
            persona = await db_connection.fetchrow(
                """
                SELECT * FROM partner_personas 
                WHERE user_id = $1 AND is_active = true
                """,
                REAL_USER_ID
            )
            
            if persona:
                print("✓ Найдена активная персона:")
                print(f"  - mode: {persona['recommended_mode']}")
                print(f"  - confidence: {persona['mode_confidence']}")
                print(f"  - version: {persona['version']}")
                print(f"  - analyzed: {persona['messages_analyzed']} messages")
            else:
                print("✗ Активная персона НЕ найдена")
            
            # 3. Отслеживаем поток сообщений
            print("\n3. Отправка реального сообщения через систему")
            
            # Собираем все сообщения
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
            
            # Берем реальный chat_id из последнего сообщения
            chat_id = 502312936  # обычно совпадает с user_id для личных чатов
            
            # Отправляем тестовое сообщение
            test_msg = ActorMessage.create(
                sender_id="telegram",
                message_type=MESSAGE_TYPES['USER_MESSAGE'],
                payload={
                    'user_id': REAL_USER_ID,
                    'chat_id': chat_id,
                    'text': "Тест интеграции Partner Persona",
                    'username': "dmitrii"
                }
            )
            
            await system.send_message("user_session", test_msg)
            
            # Ждем обработки
            await asyncio.sleep(3.0)
            
            # 4. Анализируем поток
            print("\n4. Анализ потока сообщений")
            print(f"Всего сообщений: {len(all_messages)}")
            
            # Ищем запросы Partner Persona
            partner_requests = [m for m in all_messages if m['type'] == 'get_partner_model']
            partner_responses = [m for m in all_messages if m['type'] == 'partner_model_response']
            
            print("\nPartner Persona:")
            print(f"  Запросов: {len(partner_requests)}")
            print(f"  Ответов: {len(partner_responses)}")
            
            if partner_requests:
                print("\n✓ UserSession ЗАПРАШИВАЕТ Partner Persona!")
                for req in partner_requests:
                    print(f"  Запрос для user_id: {req['payload'].get('user_id')}")
            else:
                print("\n✗ UserSession НЕ запрашивает Partner Persona!")
            
            if partner_responses:
                print("\n✓ TalkModel ОТВЕЧАЕТ:")
                for resp in partner_responses:
                    payload = resp['payload']
                    print(f"  - mode: {payload.get('recommended_mode')}")
                    print(f"  - confidence: {payload.get('mode_confidence')}")
                    print(f"  - degraded: {payload.get('degraded_mode')}")
            
            # Детальный поток первых 15 сообщений
            print("\nДетальный поток:")
            for i, msg in enumerate(all_messages[:15]):
                print(f"  {i+1}. {msg['from']} → {msg['to']}: {msg['type']}")
            
            # 5. Проверяем Redis
            print("\n5. Проверка Redis кэша")
            
            redis_client = redis_connection.get_client()
            if redis_client:
                cache_key = f"partner_persona:{REAL_USER_ID}"
                cached = await redis_client.get(cache_key)
                
                if cached:
                    data = json.loads(cached)
                    print("✓ Персона в кэше:")
                    print(f"  - mode: {data.get('recommended_mode')}")
                    print(f"  - confidence: {data.get('mode_confidence')}")
                else:
                    print("✗ Персона НЕ в кэше")
            
            # 6. Метрики
            print("\n6. Метрики TalkModelActor")
            metrics = talk_model._metrics
            print(f"  - Запросов: {metrics['get_partner_model_count']}")
            print(f"  - Cache hits: {metrics['cache_hits']}")
            print(f"  - Cache misses: {metrics['cache_misses']}")
            print(f"  - DB errors: {metrics['db_errors']}")
            
            # 7. Проверяем определение режима
            print("\n7. Анализ определения режима")
            
            # Ищем сообщения про режим
            generate_requests = [m for m in all_messages if m['type'] == 'generate_response']
            
            if generate_requests:
                gen_req = generate_requests[0]['payload']
                print("\nРежим в GENERATE_RESPONSE:")
                print(f"  - mode: {gen_req.get('mode')}")
                print(f"  - confidence: {gen_req.get('mode_confidence')}")
            
            # ПРОВЕРКИ
            print(f"\n{'='*60}")
            print("РЕЗУЛЬТАТЫ")
            print(f"{'='*60}")
            
            if len(partner_requests) > 0:
                print("✓ Partner Persona ИНТЕГРИРОВАНА - запросы отправляются")
            else:
                print("✗ Partner Persona НЕ РАБОТАЕТ - нет запросов")
                print("\nПРОБЛЕМА: UserSession не вызывает _request_partner_persona_with_timeout()")
            
            if persona and len(partner_responses) > 0:
                resp_mode = partner_responses[0]['payload'].get('recommended_mode')
                if resp_mode == persona['recommended_mode']:
                    print("✓ TalkModel возвращает правильные данные из БД")
                else:
                    print(f"✗ Несоответствие: БД={persona['recommended_mode']}, ответ={resp_mode}")
            
            print(f"\n{'='*60}\n")
            
        finally:
            # НЕ УДАЛЯЕМ РЕАЛЬНЫЕ ДАННЫЕ!
            await system.stop()
            print("Система остановлена, реальные данные НЕ тронуты")
    
    @pytest.mark.asyncio
    async def test_multiple_real_users(self):
        """Тест на нескольких реальных пользователях."""
        
        if not db_connection._is_connected:
            await db_connection.connect()
            
        print(f"\n{'='*60}")
        print("ТЕСТ НЕСКОЛЬКИХ РЕАЛЬНЫХ ПОЛЬЗОВАТЕЛЕЙ")
        print(f"{'='*60}")
        
        # Находим реальных пользователей с сообщениями
        real_users = await db_connection.fetch(
            """
            SELECT DISTINCT user_id, COUNT(*) as msg_count
            FROM stm_buffer
            GROUP BY user_id
            HAVING COUNT(*) > 10
            ORDER BY COUNT(*) DESC
            LIMIT 5
            """
        )
        
        print(f"\nНайдено активных пользователей: {len(real_users)}")
        
        for user in real_users:
            user_id = user['user_id']
            msg_count = user['msg_count']
            
            print(f"\nПользователь {user_id} ({msg_count} сообщений):")
            
            # Есть ли персона?
            persona = await db_connection.fetchrow(
                """
                SELECT recommended_mode, mode_confidence, messages_analyzed
                FROM partner_personas
                WHERE user_id = $1 AND is_active = true
                """,
                user_id
            )
            
            if persona:
                print(f"  ✓ Персона: {persona['recommended_mode']} (conf: {persona['mode_confidence']:.2f})")
            else:
                print("  ✗ Персоны нет")
            
            # Последнее сообщение
            last_msg = await db_connection.fetchrow(
                """
                SELECT content, timestamp
                FROM stm_buffer
                WHERE user_id = $1 AND message_type = 'user'
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                user_id
            )
            
            if last_msg:
                print(f"  Последнее: {last_msg['timestamp']}")
                print(f"  Текст: {last_msg['content'][:60]}...")


# Запуск напрямую
if __name__ == "__main__":
    asyncio.run(TestTalkModelIntegration().test_real_user_partner_persona_flow())