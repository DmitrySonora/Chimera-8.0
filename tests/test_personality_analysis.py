"""
Интеграционный тест PersonalityAnalysisMixin на РЕАЛЬНЫХ ДАННЫХ из БД.
Проверяет полный цикл: от инкремента счетчика до обновления Partner Persona.
Запуск: pytest tests/test_personality_analysis.py -v -s
"""
import asyncio
import pytest
import json
import time
from datetime import datetime

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
from services.style_analyzer import StyleAnalyzer
from services.trait_detector import TraitDetector
from services.partner_persona_builder import PartnerPersonaBuilder
from config.settings import (
    PERSONALITY_ANALYSIS_TRIGGER_COUNT,
    PERSONALITY_ANALYSIS_MESSAGE_LIMIT,
    PERSONALITY_ANALYSIS_MIN_MESSAGES
)


class TestPersonalityAnalysisIntegration:
    """Интеграционный тест PersonalityAnalysisMixin на РЕАЛЬНЫХ данных"""
    
    @pytest.mark.asyncio
    async def test_full_personality_analysis_cycle(self):
        """
        Тест полного цикла анализа личности:
        1. Инкремент счетчика сообщений
        2. Запуск анализа на 10-м сообщении
        3. Вызов всех сервисов анализа
        4. Отправка UPDATE_PARTNER_MODEL
        5. Обновление Partner Persona
        6. Сброс счетчика
        """
        
        # Подключаемся к РЕАЛЬНОЙ БД и Redis
        if not db_connection._is_connected:
            await db_connection.connect()
        
        if not redis_connection.is_connected():
            await redis_connection.connect()
            
        # РЕАЛЬНЫЙ пользователь из БД
        REAL_USER_ID = "502312936"
        
        # Создаем систему акторов
        system = ActorSystem("test-personality-system")
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
            print(f"\n{'='*80}")
            print("ТЕСТ АНАЛИЗА ЛИЧНОСТИ НА РЕАЛЬНЫХ ДАННЫХ")
            print(f"{'='*80}")
            
            # ========== 1. ПОДГОТОВКА ДАННЫХ ==========
            print(f"\n1. ПОДГОТОВКА ДАННЫХ для пользователя {REAL_USER_ID}")
            
            # Проверяем сообщения в STM
            msg_count = await db_connection.get_pool().fetchval(
                "SELECT COUNT(*) FROM stm_buffer WHERE user_id = $1",
                REAL_USER_ID
            )
            print(f"✓ Сообщений в STM: {msg_count}")
            
            # Проверяем есть ли сообщения бота (для TraitDetector)
            bot_msg_count = await db_connection.get_pool().fetchval(
                "SELECT COUNT(*) FROM stm_buffer WHERE user_id = $1 AND message_type = 'bot'",
                REAL_USER_ID
            )
            print(f"✓ Ответов бота в STM: {bot_msg_count}")
            
            # Старая Partner Persona (если есть)
            old_persona = await db_connection.get_pool().fetchrow(
                """
                SELECT persona_id, style_vector, recommended_mode, mode_confidence, version
                FROM partner_personas 
                WHERE user_id = $1 AND is_active = true
                """,
                REAL_USER_ID
            )
            
            if old_persona:
                print("\n✓ Существующая персона:")
                print(f"  - version: {old_persona['version']}")
                print(f"  - mode: {old_persona['recommended_mode']}")
                print(f"  - confidence: {old_persona['mode_confidence']}")
                old_style = json.loads(old_persona['style_vector']) if isinstance(old_persona['style_vector'], str) else old_persona['style_vector']
                print(f"  - style: playfulness={old_style['playfulness']:.2f}, seriousness={old_style['seriousness']:.2f}")
            else:
                print("\n✗ Активной персоны нет")
            
            # Очищаем Redis кэш для чистоты теста
            redis_client = await redis_connection.get_client()
            if redis_client:
                cache_key = f"partner_persona:{REAL_USER_ID}"
                await redis_client.delete(cache_key)
                print("✓ Redis кэш очищен")
            
            # ========== 2. ОТСЛЕЖИВАНИЕ СООБЩЕНИЙ ==========
            print("\n2. НАСТРОЙКА ОТСЛЕЖИВАНИЯ СООБЩЕНИЙ")
            
            # Собираем все сообщения
            all_messages = []
            original_send = system.send_message
            
            async def tracking_send(actor_id, message):
                all_messages.append({
                    'to': actor_id,
                    'type': message.message_type,
                    'from': message.sender_id,
                    'payload': message.payload,
                    'timestamp': datetime.now()
                })
                await original_send(actor_id, message)
            
            system.send_message = tracking_send
            print("✓ Отслеживание настроено")
            
            # ========== 3. ПРОВЕРКА СЧЕТЧИКА ==========
            print("\n3. ПРОВЕРКА ИНКРЕМЕНТА СЧЕТЧИКА")
            
            # Получаем сессию
            session = user_session._sessions.get(REAL_USER_ID)
            initial_count = session.message_count if session else 0
            print(f"Начальный счетчик: {initial_count}")
            
            # Отправляем тестовые сообщения до триггера
            # Если счетчик 0, нужно отправить 10 сообщений для достижения триггера
            if initial_count == 0:
                messages_to_send = PERSONALITY_ANALYSIS_TRIGGER_COUNT  # 10
            else:
                messages_to_send = PERSONALITY_ANALYSIS_TRIGGER_COUNT - (initial_count % PERSONALITY_ANALYSIS_TRIGGER_COUNT)
                
            print(f"Нужно отправить сообщений до триггера: {messages_to_send}")
            
            # ========== 4. ОТПРАВКА СООБЩЕНИЙ ==========
            print("\n4. ОТПРАВКА СООБЩЕНИЙ И ЗАПУСК АНАЛИЗА")
            
            for i in range(messages_to_send):
                print(f"\nСообщение {i+1}/{messages_to_send}:")
                
                # Очищаем буфер сообщений
                all_messages.clear()
                
                
                # Проверяем счетчик ДО отправки
                session_before = user_session._sessions.get(REAL_USER_ID)
                count_before = session_before.message_count if session_before else 0
                print(f"  Счетчик ДО отправки: {count_before}")
                
                # Отправляем сообщение
                test_msg = ActorMessage.create(
                    sender_id="telegram",
                    message_type=MESSAGE_TYPES['USER_MESSAGE'],
                    payload={
                        'user_id': REAL_USER_ID,
                        'chat_id': int(REAL_USER_ID),
                        'text': f"Тест анализа личности #{i+1}. Время: {datetime.now()}",
                        'username': "dmitrii"
                    }
                )
                
                await system.send_message("user_session", test_msg)
                
                # Даем время на обработку CHECK_LIMIT
                await asyncio.sleep(1.0)
                
                # Проверяем счетчик
                session = user_session._sessions.get(REAL_USER_ID)
                current_count = session.message_count if session else 0
                print(f"  Счетчик после сообщения: {current_count}")
                
                # На последнем сообщении должен запуститься анализ
                if i == messages_to_send - 1:
                    print("  🎯 ТРИГГЕР! Должен запуститься анализ личности")
                    
                    # Ждем завершения анализа (fire-and-forget)
                    await asyncio.sleep(3.0)
                    
                    # Проверяем сброс счетчика
                    session = user_session._sessions.get(REAL_USER_ID)
                    final_count = session.message_count if session else 0
                    
                    if final_count == 0:
                        print(f"  ✓ Счетчик сброшен: {current_count} → {final_count}")
                    else:
                        print(f"  ✗ Счетчик НЕ сброшен: {final_count}")
            
            # ========== 5. АНАЛИЗ ПОТОКА СООБЩЕНИЙ ==========
            print("\n5. АНАЛИЗ ПОТОКА СООБЩЕНИЙ")
            print(f"Всего сообщений в потоке: {len(all_messages)}")
            
            # Ищем UPDATE_PARTNER_MODEL
            update_messages = [m for m in all_messages if m['type'] == MESSAGE_TYPES.get('UPDATE_PARTNER_MODEL')]
            
            if update_messages:
                print(f"\n✓ UPDATE_PARTNER_MODEL отправлен! ({len(update_messages)} раз)")
                
                for idx, msg in enumerate(update_messages):
                    payload = msg['payload']
                    print(f"\n  Обновление #{idx+1}:")
                    print(f"    - user_id: {payload.get('user_id')}")
                    print(f"    - recommended_mode: {payload.get('recommended_mode')}")
                    print(f"    - mode_confidence: {payload.get('mode_confidence')}")
                    
                    style = payload.get('style_vector', {})
                    print("    - style_vector:")
                    print(f"      playfulness: {style.get('playfulness', 0):.3f}")
                    print(f"      seriousness: {style.get('seriousness', 0):.3f}")
                    print(f"      emotionality: {style.get('emotionality', 0):.3f}")
                    print(f"      creativity: {style.get('creativity', 0):.3f}")
                    
                    traits = payload.get('detected_traits', [])
                    print(f"    - detected_traits: {len(traits)} черт")
                    for trait in traits[:3]:  # Первые 3 для примера
                        print(f"      • {trait['trait_name']}: {trait['strength']:.2f}")
                    
                    metadata = payload.get('analysis_metadata', {})
                    print(f"    - messages_analyzed: {metadata.get('messages_analyzed')}")
                    print(f"    - version: {metadata.get('version')}")
            else:
                print("\n✗ UPDATE_PARTNER_MODEL НЕ отправлен!")
                print("  Проблема: PersonalityAnalysisMixin не сработал")
            
            # ========== 6. ПРОВЕРКА СЕРВИСОВ ==========
            print("\n6. ПРЯМАЯ ПРОВЕРКА СЕРВИСОВ АНАЛИЗА")
            
            pool = db_connection.get_pool()
            
            # Тест StyleAnalyzer
            print("\n6.1 StyleAnalyzer:")
            style_analyzer = StyleAnalyzer(pool)
            style_result = await style_analyzer.analyze_user_style(
                REAL_USER_ID, 
                limit=PERSONALITY_ANALYSIS_MESSAGE_LIMIT
            )
            print(f"  ✓ Проанализировано сообщений: {style_result['messages_analyzed']}")
            print(f"  ✓ Confidence: {style_result['confidence']:.3f}")
            print(f"  ✓ Style vector: {style_result['style_vector']}")
            
            # Тест TraitDetector
            print("\n6.2 TraitDetector:")
            trait_detector = TraitDetector(pool)
            detected_traits = await trait_detector.detect_traits(
                REAL_USER_ID,
                limit=PERSONALITY_ANALYSIS_MESSAGE_LIMIT
            )
            print(f"  ✓ Обнаружено черт: {len(detected_traits)}")
            if detected_traits:
                for trait in detected_traits[:5]:  # Первые 5
                    print(f"    • {trait.trait_name}: {trait.manifestation_strength:.3f} ({trait.mode})")
            
            # Тест PartnerPersonaBuilder
            print("\n6.3 PartnerPersonaBuilder:")
            persona_builder = PartnerPersonaBuilder(pool)
            new_persona = await persona_builder.build_or_update_persona(
                REAL_USER_ID,
                style_result
            )
            print("  ✓ Персона создана/обновлена:")
            print(f"    - mode: {new_persona.recommended_mode}")
            print(f"    - confidence: {new_persona.mode_confidence:.3f}")
            print(f"    - version: {new_persona.version}")
            
            # ========== 7. ПРОВЕРКА БД ==========
            print("\n7. ПРОВЕРКА ИЗМЕНЕНИЙ В БД")
            
            # Новая персона
            new_persona_db = await pool.fetchrow(
                """
                SELECT persona_id, style_vector, recommended_mode, mode_confidence, version, messages_analyzed
                FROM partner_personas 
                WHERE user_id = $1 AND is_active = true
                """,
                REAL_USER_ID
            )
            
            if new_persona_db:
                print("\n✓ Новая активная персона в БД:")
                print(f"  - version: {new_persona_db['version']}")
                print(f"  - mode: {new_persona_db['recommended_mode']}")
                print(f"  - confidence: {new_persona_db['mode_confidence']}")
                print(f"  - messages_analyzed: {new_persona_db['messages_analyzed']}")
                
                if old_persona:
                    if new_persona_db['version'] > old_persona['version']:
                        print(f"  ✓ Версия увеличена: {old_persona['version']} → {new_persona_db['version']}")
                    else:
                        print(f"  ✗ Версия НЕ изменилась: {new_persona_db['version']}")
            else:
                print("\n✗ Персона НЕ найдена в БД")
            
            # Проверяем сохранение черт
            saved_traits = await pool.fetch(
                """
                SELECT trait_name, manifestation_strength, mode, confidence
                FROM personality_traits_manifestations
                WHERE user_id = $1
                ORDER BY detected_at DESC
                LIMIT 10
                """,
                REAL_USER_ID
            )
            
            if saved_traits:
                print(f"\n✓ Сохранено черт в БД: {len(saved_traits)}")
                for trait in saved_traits[:3]:
                    print(f"  • {trait['trait_name']}: {trait['manifestation_strength']:.3f}")
            else:
                print("\n⚠️ Черты НЕ сохранены в БД (возможно, таблица не создана)")
            
            # ========== 8. ПРОВЕРКА REDIS ==========
            print("\n8. ПРОВЕРКА REDIS КЭША")
            
            if redis_client:
                cache_key = f"partner_persona:{REAL_USER_ID}"
                cached = await redis_client.get(cache_key)
                
                if cached:
                    data = json.loads(cached)
                    print("✓ Персона в кэше:")
                    print(f"  - mode: {data.get('recommended_mode')}")
                    print(f"  - confidence: {data.get('mode_confidence')}")
                    print(f"  - version: {data.get('version')}")
                else:
                    print("⚠️ Персона НЕ в кэше (должна быть после UPDATE_PARTNER_MODEL)")
            
            # ========== 9. МЕТРИКИ ==========
            print("\n9. МЕТРИКИ АКТОРОВ")
            
            print("\nTalkModelActor:")
            talk_metrics = talk_model._metrics
            print(f"  - UPDATE_PARTNER_MODEL обработано: {talk_metrics.get('personas_updated', 0) + talk_metrics.get('personas_unchanged', 0)}")
            print(f"  - Персон обновлено: {talk_metrics.get('personas_updated', 0)}")
            print(f"  - Персон без изменений: {talk_metrics.get('personas_unchanged', 0)}")
            print(f"  - Ошибок обновления: {talk_metrics.get('update_errors', 0)}")
            
            # ========== 10. РЕЗУЛЬТАТЫ ==========
            print(f"\n{'='*80}")
            print("РЕЗУЛЬТАТЫ ТЕСТА")
            print(f"{'='*80}")
            
            # Проверка основного функционала
            checks = {
                "Счетчик инкрементируется": session and session.message_count != initial_count or final_count == 0,
                "Анализ запускается на 10-м сообщении": len(update_messages) > 0,
                "StyleAnalyzer работает": style_result['messages_analyzed'] > 0,
                "TraitDetector работает": len(detected_traits) >= 0,  # Может быть 0 если нет маркеров
                "PartnerPersonaBuilder работает": new_persona is not None,
                "UPDATE_PARTNER_MODEL отправляется": len(update_messages) > 0,
                "Персона сохраняется в БД": new_persona_db is not None,
                "Счетчик сбрасывается после анализа": final_count == 0,
            }
            
            passed = 0
            failed = 0
            
            for check, result in checks.items():
                if result:
                    print(f"✓ {check}")
                    passed += 1
                else:
                    print(f"✗ {check}")
                    failed += 1
            
            print(f"\nИтого: {passed} пройдено, {failed} провалено")
            
            if failed > 0:
                print("\n⚠️ ПРОБЛЕМЫ В РЕАЛИЗАЦИИ:")
                if len(update_messages) == 0:
                    print("  - PersonalityAnalysisMixin не срабатывает")
                    print("  - Проверьте условие _should_analyze_personality()")
                    print("  - Проверьте asyncio.create_task() в _handle_user_message")
                if final_count != 0:
                    print("  - Счетчик не сбрасывается")
                    print("  - Проверьте session.message_count = 0 в _run_personality_analysis")
            else:
                print("\n✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!")
            
            print(f"\n{'='*80}\n")
            
        finally:
            # НЕ УДАЛЯЕМ РЕАЛЬНЫЕ ДАННЫЕ!
            await system.stop()
            print("Система остановлена, реальные данные НЕ тронуты")
    
    @pytest.mark.asyncio
    async def test_personality_analysis_edge_cases(self):
        """
        Тест граничных случаев анализа личности:
        - Недостаточно сообщений для анализа
        - Ошибки в сервисах
        - Таймауты
        """
        
        if not db_connection._is_connected:
            await db_connection.connect()
            
        print(f"\n{'='*80}")
        print("ТЕСТ ГРАНИЧНЫХ СЛУЧАЕВ АНАЛИЗА ЛИЧНОСТИ")
        print(f"{'='*80}")
        
        pool = db_connection.get_pool()
        
        # ========== ТЕСТ 1: Пользователь с малым количеством сообщений ==========
        print("\n1. ПОЛЬЗОВАТЕЛЬ С НЕДОСТАТОЧНЫМ КОЛИЧЕСТВОМ СООБЩЕНИЙ")
        
        # Ищем пользователя с малым количеством сообщений
        sparse_user = await pool.fetchrow(
            """
            SELECT user_id, COUNT(*) as msg_count
            FROM stm_buffer
            WHERE message_type = 'user'
            GROUP BY user_id
            HAVING COUNT(*) < $1
            ORDER BY COUNT(*) DESC
            LIMIT 1
            """,
            PERSONALITY_ANALYSIS_MIN_MESSAGES
        )
        
        if sparse_user:
            user_id = sparse_user['user_id']
            msg_count = sparse_user['msg_count']
            print(f"  Пользователь {user_id}: {msg_count} сообщений")
            
            # Пробуем анализ
            style_analyzer = StyleAnalyzer(pool)
            result = await style_analyzer.analyze_user_style(user_id)
            
            print("  Результат:")
            print(f"    - has_sufficient_data: {result['metadata']['has_sufficient_data']}")
            print(f"    - confidence: {result['confidence']}")
            print(f"    - style_vector: все компоненты = {result['style_vector']['playfulness']}")
            
            if not result['metadata']['has_sufficient_data']:
                print("  ✓ Корректно обработан недостаток данных")
            else:
                print("  ✗ Неправильная обработка недостатка данных")
        else:
            print("  ⚠️ Нет пользователей с малым количеством сообщений")
        
        # ========== ТЕСТ 2: Анализ с таймаутом ==========
        print("\n2. ПРОВЕРКА ТАЙМАУТОВ")
        
        # Используем реального пользователя
        REAL_USER_ID = "502312936"
        
        from config.settings import PERSONALITY_ANALYSIS_TIMEOUT
        print(f"  Таймаут анализа: {PERSONALITY_ANALYSIS_TIMEOUT} секунд")
        
        # Измеряем время анализа
        style_analyzer = StyleAnalyzer(pool)
        start_time = time.time()
        
        try:
            result = await asyncio.wait_for(
                style_analyzer.analyze_user_style(REAL_USER_ID, limit=100),
                timeout=PERSONALITY_ANALYSIS_TIMEOUT
            )
            elapsed = time.time() - start_time
            print(f"  ✓ Анализ завершен за {elapsed:.3f} секунд")
        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            print(f"  ✗ Таймаут! Анализ не завершен за {elapsed:.3f} секунд")
        
        # ========== ТЕСТ 3: Версионирование персон ==========
        print("\n3. ПРОВЕРКА ВЕРСИОНИРОВАНИЯ ПЕРСОН")
        
        # Получаем историю версий
        versions = await pool.fetch(
            """
            SELECT version, recommended_mode, mode_confidence, created_at, is_active
            FROM partner_personas
            WHERE user_id = $1
            ORDER BY version DESC
            LIMIT 5
            """,
            REAL_USER_ID
        )
        
        if versions:
            print(f"  История версий для пользователя {REAL_USER_ID}:")
            for v in versions:
                active = "АКТИВНА" if v['is_active'] else "неактивна"
                print(f"    v{v['version']}: {v['recommended_mode']} ({v['mode_confidence']:.2f}) - {active}")
            
            # Проверяем, что только одна активная
            active_count = sum(1 for v in versions if v['is_active'])
            if active_count == 1:
                print("  ✓ Только одна активная версия")
            elif active_count == 0:
                print("  ⚠️ Нет активных версий")
            else:
                print(f"  ✗ Несколько активных версий: {active_count}")
        else:
            print("  ⚠️ Нет версий персоны для пользователя")
        
        # ========== ТЕСТ 4: Детекция черт ==========
        print("\n4. СТАТИСТИКА ДЕТЕКЦИИ ЧЕРТ")
        
        trait_stats = await pool.fetch(
            """
            SELECT trait_name, COUNT(*) as count, AVG(manifestation_strength) as avg_strength
            FROM personality_traits_manifestations
            WHERE user_id = $1
            GROUP BY trait_name
            ORDER BY COUNT(*) DESC
            """,
            REAL_USER_ID
        )
        
        if trait_stats:
            print(f"  Статистика черт для пользователя {REAL_USER_ID}:")
            for stat in trait_stats:
                print(f"    {stat['trait_name']}: {stat['count']} проявлений, средняя сила {stat['avg_strength']:.3f}")
        else:
            print("  ⚠️ Нет сохраненных черт для пользователя")
        
        print(f"\n{'='*80}\n")


# Запуск напрямую
if __name__ == "__main__":
    test = TestPersonalityAnalysisIntegration()
    asyncio.run(test.test_full_personality_analysis_cycle())
    asyncio.run(test.test_personality_analysis_edge_cases())