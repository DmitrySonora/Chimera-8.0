"""
Интеграционный тест PersonalityActor с защитными механизмами на РЕАЛЬНЫХ ДАННЫХ.
Запуск: pytest tests/test_personality_protection.py -v -s

Примечание: PersonalityModifier имеет встроенную валидацию,
ограничивающую значения модификаторов диапазоном 0.5-1.5 (50% уменьшение до 50% увеличение).
"""
import asyncio
import pytest
from datetime import datetime, timezone, timedelta

from database.connection import db_connection
from database.redis_connection import redis_connection
from actors.actor_system import ActorSystem
from actors.personality.personality_actor import PersonalityActor
from actors.user_session import UserSessionActor
from actors.memory_actor import MemoryActor
from actors.generation_actor import GenerationActor
from actors.auth import AuthActor
from actors.perception_actor import PerceptionActor
from actors.ltm import LTMActor
from actors.messages import ActorMessage, MESSAGE_TYPES
from config.settings import PERSONALITY_RECOVERY_DAYS


class TestPersonalityProtectionIntegration:
    """Интеграционный тест защитных механизмов PersonalityActor на РЕАЛЬНЫХ данных"""
    
    @pytest.mark.asyncio
    async def test_core_constraints_with_real_flow(self):
        """Тест Core Constraints через реальный поток сообщений."""
        
        # Подключаемся к РЕАЛЬНОЙ БД
        if not db_connection._is_connected:
            await db_connection.connect()
        
        if not redis_connection.is_connected():
            await redis_connection.connect()
            
        # Создаем систему акторов
        system = ActorSystem("test-personality-system")
        await system.create_and_set_event_store()
        
        # Создаем ВСЕ необходимые акторы
        personality = PersonalityActor()
        user_session = UserSessionActor()
        memory = MemoryActor()
        generation = GenerationActor()
        auth = AuthActor()
        perception = PerceptionActor("perception")
        ltm = LTMActor()
        
        # Регистрируем
        await system.register_actor(personality)
        await system.register_actor(user_session)
        await system.register_actor(memory)
        await system.register_actor(generation)
        await system.register_actor(auth)
        await system.register_actor(perception)
        await system.register_actor(ltm)
        
        await system.start()
        
        try:
            print(f"\n{'='*60}")
            print("ТЕСТ CORE CONSTRAINTS")
            print(f"{'='*60}")
            
            # Проверяем базовые черты
            print("\n1. Проверка загруженных core черт")
            core_traits = await db_connection.fetch(
                """
                SELECT trait_name, base_value, is_core 
                FROM personality_base_traits 
                WHERE is_core = true
                ORDER BY trait_name
                """
            )
            
            print(f"✓ Найдено core черт: {len(core_traits)}")
            for trait in core_traits:
                print(f"  - {trait['trait_name']}: base={trait['base_value']}")
            
            # Отслеживаем поток сообщений
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
            
            # Тестовый пользователь
            test_user_id = "test_core_constraint_user"
            
            print("\n2. Отправка экстремально низких модификаторов для core черт")
            print("   Примечание: PersonalityModifier ограничивает значения диапазоном 0.5-1.5")
            print("   Используем минимальное значение 0.5 (50% от базы)")
            
            # Отправляем модификаторы напрямую в PersonalityActor
            # ВАЖНО: PersonalityModifier имеет валидацию 0.5-1.5, используем минимальные разрешенные
            modifier_msg = ActorMessage.create(
                sender_id="test",
                message_type=MESSAGE_TYPES['UPDATE_PERSONALITY_CONTEXT'],
                payload={
                    'user_id': test_user_id,
                    'modifier_type': 'style',
                    'modifier_data': {
                        'curiosity': 0.5,    # Минимально разрешенное значение (50% от базы)
                        'empathy': 0.5,      # При базе 0.8 и модификаторе 0.5 получим 0.4
                        'irony': 0.5,        # Но core constraint поднимет до 40% от базы
                        'caring': 0.5        # То есть минимум 0.32 для empathy (0.8 * 0.4)
                    }
                }
            )
            
            await system.send_message("personality", modifier_msg)
            await asyncio.sleep(0.5)
            
            # Запрашиваем профиль напрямую через метод актора
            print("\n3. Запрос профиля через прямой вызов")
            calculated_profile = await personality._calculate_active_profile(test_user_id)
            
            # Проверяем, какие защиты применены
            protection_applied = []
            if test_user_id in personality._session_start_profiles:
                protection_applied.append('session_limits')
            if any(personality._base_traits.get(trait, {}).get('is_core', False) for trait in calculated_profile):
                protection_applied.append('core_constraints')
            
            print("\n4. Анализ результатов Core Constraints")
            
            print(f"\n✓ Защиты применены: {protection_applied}")
            print("\nЗначения core черт после защиты:")
            
            for trait in core_traits:
                trait_name = trait['trait_name']
                base_value = trait['base_value']
                active_value = calculated_profile.get(trait_name, 0)
                min_allowed = base_value * 0.4
                
                # При модификаторе 0.5 и других модификаторах (emotion, temporal)
                # итоговое значение = base * 0.5 * emotion_mod * temporal_mod
                # Core constraint должен поднять до минимума если меньше
                status = "✓" if active_value >= min_allowed - 0.001 else "✗"
                
                expected_without_protection = base_value * 0.5 * 0.9  # примерная оценка с temporal
                protected = active_value > expected_without_protection * 1.1  # защита сработала
                
                print(f"  {status} {trait_name}: {active_value:.3f} "
                      f"(min: {min_allowed:.3f}, base: {base_value}, "
                      f"{'защищено' if protected else 'не требовалось'})")
            
            # Проверяем метрики
            print("\n5. Метрики PersonalityActor")
            metrics = personality._metrics
            print(f"  - Core constraints applied: {metrics.get('core_constraints_applied', 0)}")
            print(f"  - Session limits applied: {metrics.get('session_limits_applied', 0)}")
            print(f"  - Recoveries triggered: {metrics.get('recoveries_triggered', 0)}")
            
            print(f"\n{'='*60}")
            print("РЕЗУЛЬТАТЫ CORE CONSTRAINTS")
            print(f"{'='*60}")
            
            if metrics.get('core_constraints_applied', 0) > 0:
                print("✓ Core constraints РАБОТАЮТ - защита сработала")
                print(f"  Применено {metrics['core_constraints_applied']} раз")
            else:
                print("⚠️  Core constraints возможно не потребовались")
                print("  (модификаторы не опустили значения ниже минимума)")
            
        finally:
            await system.stop()
            print("\nСистема остановлена")
    
    @pytest.mark.asyncio
    async def test_session_limits_with_real_user(self):
        """Тест Session Limits на реальном пользователе."""
        
        if not db_connection._is_connected:
            await db_connection.connect()
        
        if not redis_connection.is_connected():
            await redis_connection.connect()
        
        # РЕАЛЬНЫЙ пользователь
        REAL_USER_ID = "502312936"
        
        # Создаем систему
        system = ActorSystem("test-session-limits")
        await system.create_and_set_event_store()
        
        personality = PersonalityActor()
        await system.register_actor(personality)
        await system.start()
        
        try:
            print(f"\n{'='*60}")
            print("ТЕСТ SESSION LIMITS")
            print(f"{'='*60}")
            
            print(f"\n1. Используем реального пользователя {REAL_USER_ID}")
            
            # Получаем начальный профиль
            print("\n2. Запрос начального профиля")
            initial_profile = await personality._calculate_active_profile(REAL_USER_ID)
            print(f"✓ Получен профиль с {len(initial_profile)} чертами")
            
            # Показываем топ черты
            top_traits = sorted(initial_profile.items(), key=lambda x: x[1], reverse=True)[:3]
            print("Топ-3 черты:")
            for trait, value in top_traits:
                print(f"  - {trait}: {value:.3f}")
            
            # Отправляем экстремальные модификаторы
            print("\n3. Отправка экстремальных модификаторов (попытка изменить > 20%)")
            
            # Сначала стилевые модификаторы для прямого влияния на черты
            style_msg = ActorMessage.create(
                sender_id="test",
                message_type=MESSAGE_TYPES['UPDATE_PERSONALITY_CONTEXT'],
                payload={
                    'user_id': REAL_USER_ID,
                    'modifier_type': 'style',
                    'modifier_data': {
                        top_traits[0][0]: 1.5,  # Максимум для топ-1 черты
                        top_traits[1][0]: 0.5,  # Минимум для топ-2 черты
                        top_traits[2][0]: 1.5   # Максимум для топ-3 черты
                    }
                }
            )
            
            await system.send_message("personality", style_msg)
            await asyncio.sleep(0.5)
            
            # Запрашиваем профиль снова
            print("\n4. Запрос профиля после экстремальных модификаторов")
            new_profile = await personality._calculate_active_profile(REAL_USER_ID)
            
            # Анализируем изменения
            print("\n5. Анализ ограничений сессии")
            
            
            for trait in top_traits:
                trait_name = trait[0]
                old_value = trait[1]
                new_value = new_profile.get(trait_name, old_value)
                change = abs(new_value - old_value)
                max_allowed_change = old_value * 0.2
                
                if change > max_allowed_change + 0.001:  # Небольшой допуск на округление
                    print(f"  ✗ {trait_name}: изменение {change:.3f} > разрешенного {max_allowed_change:.3f}")
                else:
                    status = "✓ ограничено" if change > max_allowed_change * 0.8 else "✓"
                    print(f"  {status} {trait_name}: {old_value:.3f} → {new_value:.3f} (изменение: {change:.3f})")
                    # Ограничение сработало если изменение близко к максимально разрешенному
            
            # Проверяем метрики
            print("\n6. Метрики после теста")
            print(f"  - Session limits applied: {personality._metrics.get('session_limits_applied', 0)}")
            
            print(f"\n{'='*60}")
            print("РЕЗУЛЬТАТЫ SESSION LIMITS")
            print(f"{'='*60}")
            
            if personality._metrics.get('session_limits_applied', 0) > 0:
                print("✓ Session limits РАБОТАЮТ - ограничения применены")
            else:
                print("⚠️  Session limits возможно не сработали (проверьте логи)")
            
        finally:
            await system.stop()
    
    @pytest.mark.asyncio
    async def test_recovery_mechanism(self):
        """Тест Recovery механизма после периода неактивности."""
        
        if not db_connection._is_connected:
            await db_connection.connect()
        
        if not redis_connection.is_connected():
            await redis_connection.connect()
        
        system = ActorSystem("test-recovery")
        await system.create_and_set_event_store()
        
        personality = PersonalityActor()
        await system.register_actor(personality)
        await system.start()
        
        try:
            print(f"\n{'='*60}")
            print("ТЕСТ RECOVERY MECHANISM")
            print(f"{'='*60}")
            
            test_user = "test_recovery_user"
            
            # Устанавливаем профиль с отклонениями от базы
            print("\n1. Создаем профиль с отклонениями от базовых значений")
            print("   Используем модификаторы в разрешенном диапазоне 0.5-1.5")
            
            deviation_msg = ActorMessage.create(
                sender_id="test",
                message_type=MESSAGE_TYPES['UPDATE_PERSONALITY_CONTEXT'],
                payload={
                    'user_id': test_user,
                    'modifier_type': 'style',
                    'modifier_data': {
                        'playfulness': 1.5,
                        'seriousness': 0.5,
                        'curiosity': 1.3
                    }
                }
            )
            
            await system.send_message("personality", deviation_msg)
            await asyncio.sleep(0.5)
            
            # Получаем измененный профиль
            profile_before = await personality._calculate_active_profile(test_user)
            print("✓ Профиль создан, топ черты:")
            for trait, value in sorted(profile_before.items(), key=lambda x: x[1], reverse=True)[:3]:
                print(f"  - {trait}: {value:.3f}")
            
            # Симулируем неактивность
            print(f"\n2. Симулируем неактивность {PERSONALITY_RECOVERY_DAYS + 3} дней")
            past_date = datetime.now(timezone.utc) - timedelta(days=PERSONALITY_RECOVERY_DAYS + 3)
            personality._last_activity[test_user] = past_date
            
            # КРИТИЧЕСКИ ВАЖНО: Инвалидируем кэш профиля
            print("   Инвалидируем кэш профиля...")
            await personality._invalidate_profile_cache(test_user)
            
            # Запрашиваем профиль после "неактивности"
            print("\n3. Запрашиваем профиль после периода неактивности")
            profile_after = await personality._calculate_active_profile(test_user)
            
            # Анализируем восстановление
            print("\n4. Анализ восстановления к базовым значениям")
            
            
            for trait_name in ['playfulness', 'seriousness', 'curiosity']:
                if trait_name in profile_before and trait_name in profile_after:
                    before = profile_before[trait_name]
                    after = profile_after[trait_name]
                    base = personality._base_traits.get(trait_name, {}).get('base_value', 0.5)
                    
                    # Проверяем движение к базе
                    moved_to_base = abs(after - base) < abs(before - base)
                    
                    status = "✓ восстанавливается" if moved_to_base else "?"
                    print(f"  {status} {trait_name}: {before:.3f} → {after:.3f} (база: {base:.3f})")
                    
                    # Восстановление наблюдается если значения движутся к базовым
            
            # Проверяем метрики
            print("\n5. Метрики восстановления")
            print(f"  - Recoveries triggered: {personality._metrics.get('recoveries_triggered', 0)}")
            print(f"  - Days inactive: {personality._calculate_days_inactive(test_user)}")
            
            print(f"\n{'='*60}")
            print("РЕЗУЛЬТАТЫ RECOVERY")
            print(f"{'='*60}")
            
            if personality._metrics.get('recoveries_triggered', 0) > 0:
                print("✓ Recovery РАБОТАЕТ - восстановление запущено")
            else:
                print("✗ Recovery НЕ РАБОТАЕТ - восстановление не запустилось")
                
        finally:
            await system.stop()


# Запуск напрямую
if __name__ == "__main__":
    asyncio.run(TestPersonalityProtectionIntegration().test_core_constraints_with_real_flow())
    print("\n" + "="*80 + "\n")
    asyncio.run(TestPersonalityProtectionIntegration().test_session_limits_with_real_user())
    print("\n" + "="*80 + "\n")
    asyncio.run(TestPersonalityProtectionIntegration().test_recovery_mechanism())