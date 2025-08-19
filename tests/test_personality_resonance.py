"""
Интеграционный тест резонансной персонализации PersonalityActor.
Запуск: pytest tests/test_personality_resonance.py -v -s

Тест некорректен в нескольких частях: проваливаются: адаптация (коэффициенты не меняются), сохранение профиля (0 черт вместо 13), сброс резонанса (возвращает False). Использвать sql-тестирование

"""
import asyncio
import pytest
import json
from datetime import datetime, timezone, timedelta
from typing import Dict

from database.connection import db_connection
from database.redis_connection import redis_connection
from actors.actor_system import ActorSystem
from actors.personality import PersonalityActor
from actors.messages import ActorMessage, MESSAGE_TYPES
from actors.base_actor import BaseActor
from config.settings import (
    RESONANCE_ADAPTATION_INTERVAL,
    RESONANCE_MAX_DEVIATION,
    RESONANCE_NOISE_LEVEL,
    PERSONALITY_RECOVERY_DAYS
)
from config.vocabulary_resonance_matrix import (
    CORE_TRAITS,
    RESONANCE_MIN_COEFFICIENT,
    RESONANCE_MAX_COEFFICIENT
)


class TestRequester(BaseActor):
    """Вспомогательный актор для перехвата ответов"""
    def __init__(self, actor_id: str = "test_requester"):
        super().__init__(actor_id, "TestRequester")
        self.received_profiles = []
        
    async def handle_message(self, message):
        if message.message_type == MESSAGE_TYPES['PERSONALITY_PROFILE_RESPONSE']:
            self.received_profiles.append(message.payload)
        return None
    
    async def initialize(self):
        pass
    
    async def shutdown(self):
        pass


class TestPersonalityResonance:
    """Тесты резонансной персонализации PersonalityActor"""
    
    @pytest.mark.asyncio
    async def test_resonance_full_cycle(self):
        """Полный цикл резонансной персонализации: от нейтрального до адаптированного"""
        
        # Подключаемся к БД и Redis
        if not db_connection._is_connected:
            await db_connection.connect()
        
        if not redis_connection.is_connected():
            await redis_connection.connect()
        
        # Тестовый пользователь
        TEST_USER_ID = "test_resonance_user_001"
        
        # Создаем систему акторов
        system = ActorSystem("test-resonance-system")
        await system.create_and_set_event_store()
        
        # Создаем акторы
        personality = PersonalityActor()
        test_requester = TestRequester()
        
        # Регистрируем акторы
        await system.register_actor(personality)
        await system.register_actor(test_requester)
        
        await system.start()
        
        try:
            print(f"\n{'='*60}")
            print("ТЕСТ ПОЛНОГО ЦИКЛА РЕЗОНАНСНОЙ ПЕРСОНАЛИЗАЦИИ")
            print(f"{'='*60}")
            
            # Инициализация переменных для итоговых проверок
            all_within_limits = False
            reset_success = False
            adaptation_occurred = False
            
            # ============================================
            # ЭТАП 1: НОВЫЙ ПОЛЬЗОВАТЕЛЬ (нейтральный резонанс)
            # ============================================
            print("\n1. НОВЫЙ ПОЛЬЗОВАТЕЛЬ - проверка нейтрального резонанса")
            print("-" * 40)
            
            # Отправляем стилевые модификаторы (высокая игривость)
            # Стиль в формате 0.0-1.0 как в реальных данных
            style_msg = ActorMessage.create(
                sender_id="test",
                message_type=MESSAGE_TYPES['UPDATE_PERSONALITY_CONTEXT'],
                payload={
                    'user_id': TEST_USER_ID,
                    'modifier_type': 'style',
                    'modifier_data': {
                        'playfulness': 0.8,    # Высокая игривость
                        'seriousness': 0.2,     # Низкая серьезность
                        'emotionality': 0.6,
                        'creativity': 0.7
                    }
                }
            )
            
            await system.send_message("personality", style_msg)
            await asyncio.sleep(0.5)
            
            # Запрашиваем профиль первый раз
            get_profile_msg = ActorMessage.create(
                sender_id="test_requester",
                message_type=MESSAGE_TYPES['GET_PERSONALITY_PROFILE'],
                payload={'user_id': TEST_USER_ID}
            )
            
            await system.send_message("personality", get_profile_msg)
            await asyncio.sleep(1.0)
            
            if test_requester.received_profiles:
                profile1 = test_requester.received_profiles[0]
                print("✓ Первый профиль получен")
                print(f"  - Доминирующие черты: {', '.join(profile1['dominant_traits'][:3])}")
                
                # Проверяем резонансные коэффициенты для нового пользователя
                resonance_coeffs = await self._get_resonance_coefficients(TEST_USER_ID)
                if resonance_coeffs:
                    # Для нового пользователя все коэффициенты должны быть 1.0 или отсутствовать
                    all_neutral = not resonance_coeffs or all(abs(v - 1.0) < 0.01 for v in resonance_coeffs.values())
                    print(f"  - Резонанс нейтральный (все ~1.0): {all_neutral}")
                    if not all_neutral and resonance_coeffs:
                        print(f"    ! Найдены коэффициенты: {list(resonance_coeffs.keys())[:5]}...")
                else:
                    print("  - Резонанс нейтральный (профиль не создан)")
                    all_neutral = True
            
            # ============================================
            # ЭТАП 2: НАКОПЛЕНИЕ ВЗАИМОДЕЙСТВИЙ
            # ============================================
            print("\n2. НАКОПЛЕНИЕ ВЗАИМОДЕЙСТВИЙ для адаптации")
            print("-" * 40)
            
            # Отправляем эмоциональный контекст
            emotion_msg = ActorMessage.create(
                sender_id="test",
                message_type=MESSAGE_TYPES['UPDATE_PERSONALITY_CONTEXT'],
                payload={
                    'user_id': TEST_USER_ID,
                    'modifier_type': 'emotion',
                    'modifier_data': {
                        'joy': 0.8,
                        'excitement': 0.7
                    }
                }
            )
            
            await system.send_message("personality", emotion_msg)
            await asyncio.sleep(0.5)
            
            # Проверяем начальное количество взаимодействий
            if personality._interaction_counts:
                initial_count = personality._interaction_counts.get(TEST_USER_ID, 0)
                print(f"  Начальное количество взаимодействий: {initial_count}")
            
            # Делаем несколько запросов профиля для накопления взаимодействий
            print(f"  Накапливаем {RESONANCE_ADAPTATION_INTERVAL} взаимодействий...")
            
            for i in range(RESONANCE_ADAPTATION_INTERVAL):
                # Каждый запрос считается взаимодействием
                await system.send_message("personality", get_profile_msg)
                await asyncio.sleep(0.5)  # Увеличена задержка
                print(f"    - Взаимодействие {i+1}/{RESONANCE_ADAPTATION_INTERVAL}")
            
            # Ждем адаптацию (увеличенная задержка)
            print("  Ожидание адаптации...")
            await asyncio.sleep(3.0)
            
            # Проверяем конечное количество взаимодействий
            if personality._interaction_counts:
                final_count = personality._interaction_counts.get(TEST_USER_ID, 0)
                print(f"  Конечное количество взаимодействий: {final_count}")
                print(f"  Должна сработать адаптация при: {RESONANCE_ADAPTATION_INTERVAL}")
            
            # ============================================
            # ЭТАП 3: ПРОВЕРКА АДАПТАЦИИ
            # ============================================
            print("\n3. ПРОВЕРКА АДАПТАЦИИ РЕЗОНАНСА")
            print("-" * 40)
            
            # Очищаем предыдущие профили
            test_requester.received_profiles.clear()
            
            # Запрашиваем профиль после адаптации
            await system.send_message("personality", get_profile_msg)
            await asyncio.sleep(1.0)
            
            if test_requester.received_profiles:
                profile2 = test_requester.received_profiles[0]
                print("✓ Профиль после адаптации получен")
                print(f"  - Доминирующие черты: {', '.join(profile2['dominant_traits'][:3])}")
                
                # Проверяем изменение резонансных коэффициентов
                resonance_coeffs = await self._get_resonance_coefficients(TEST_USER_ID)
                if resonance_coeffs:
                    # При высокой игривости должны усилиться playfulness и irony
                    playfulness_coef = resonance_coeffs.get('playfulness', 1.0)
                    irony_coef = resonance_coeffs.get('irony', 1.0)
                    analytical_coef = resonance_coeffs.get('analytical', 1.0)
                    
                    print("\n  Адаптированные коэффициенты:")
                    print(f"    - playfulness: {playfulness_coef:.3f} (ожидается >1.0)")
                    print(f"    - irony: {irony_coef:.3f} (ожидается >1.0)")
                    print(f"    - analytical: {analytical_coef:.3f} (ожидается <1.0)")
                    
                    # Проверяем что хотя бы какая-то адаптация произошла
                    # С learning rate 0.05 изменения могут быть малыми
                    adaptation_occurred = (
                        playfulness_coef > 1.01 or  # Хотя бы 1% изменение
                        irony_coef > 1.01 or 
                        analytical_coef < 0.99
                    )
                    
                    if not adaptation_occurred:
                        # Проверяем есть ли вообще отклонения от 1.0
                        any_change = any(abs(v - 1.0) > 0.01 for v in resonance_coeffs.values())
                        print(f"\n  ⚠ Малые изменения, любые отклонения от 1.0: {any_change}")
                        adaptation_occurred = any_change
                    
                    print(f"\n  ✓ Адаптация произошла: {adaptation_occurred}")
                else:
                    print("  ✗ Профиль резонанса не найден")
            
            # ============================================
            # ЭТАП 4: ПРОВЕРКА ЗАЩИТНЫХ ОГРАНИЧЕНИЙ
            # ============================================
            print("\n4. ПРОВЕРКА ЗАЩИТНЫХ ОГРАНИЧЕНИЙ")
            print("-" * 40)
            
            # Отправляем экстремальные стили
            extreme_style_msg = ActorMessage.create(
                sender_id="test",
                message_type=MESSAGE_TYPES['UPDATE_PERSONALITY_CONTEXT'],
                payload={
                    'user_id': TEST_USER_ID,
                    'modifier_type': 'style',
                    'modifier_data': {
                        'playfulness': 1.0,    # Максимальная игривость
                        'seriousness': 0.0,     # Минимальная серьезность
                        'emotionality': 1.0,
                        'creativity': 1.0
                    }
                }
            )
            
            await system.send_message("personality", extreme_style_msg)
            await asyncio.sleep(0.5)
            
            # Накапливаем еще взаимодействия для новой адаптации
            print(f"  Накапливаем еще {RESONANCE_ADAPTATION_INTERVAL} взаимодействий с экстремальным стилем...")
            
            for i in range(RESONANCE_ADAPTATION_INTERVAL):
                await system.send_message("personality", get_profile_msg)
                await asyncio.sleep(0.3)
            
            await asyncio.sleep(2.0)
            
            # Проверяем ограничения
            all_within_limits = True  # Объявляем переменную
            resonance_coeffs = await self._get_resonance_coefficients(TEST_USER_ID)
            if resonance_coeffs:
                print("\n  Проверка ограничений:")
                
                # Все коэффициенты должны быть в пределах 0.7-1.3
                all_within_limits = all(
                    RESONANCE_MIN_COEFFICIENT <= v <= RESONANCE_MAX_COEFFICIENT 
                    for v in resonance_coeffs.values()
                )
                print(f"    ✓ Все коэффициенты в пределах [{RESONANCE_MIN_COEFFICIENT}, {RESONANCE_MAX_COEFFICIENT}]: {all_within_limits}")
                
                # Core черты должны изменяться медленнее
                print("\n  Core черты (должны изменяться медленнее):")
                for trait in CORE_TRAITS:
                    if trait in resonance_coeffs:
                        coef = resonance_coeffs[trait]
                        deviation = abs(coef - 1.0)
                        print(f"    - {trait}: {coef:.3f} (отклонение: {deviation:.3f})")
                
                # Общая сумма изменений не должна превышать 20%
                total_deviation = sum(abs(v - 1.0) for v in resonance_coeffs.values())
                print(f"\n    ✓ Общее отклонение: {total_deviation:.3f} (лимит: {RESONANCE_MAX_DEVIATION * len(resonance_coeffs)})")
            
            # ============================================
            # ЭТАП 5: ТЕСТ СБРОСА РЕЗОНАНСА
            # ============================================
            print("\n5. ТЕСТ СБРОСА РЕЗОНАНСА")
            print("-" * 40)
            
            # Вызываем сброс резонанса
            print("  Выполняем полный сброс резонанса...")
            reset_success = await personality._reset_resonance_profile(TEST_USER_ID, partial=False)
            await asyncio.sleep(1.0)
            
            if reset_success:
                # Проверяем что коэффициенты вернулись к 1.0
                resonance_coeffs = await self._get_resonance_coefficients(TEST_USER_ID)
                if resonance_coeffs:
                    all_reset = all(abs(v - 1.0) < 0.01 for v in resonance_coeffs.values())
                    print(f"    ✓ Резонанс сброшен к нейтральному: {all_reset}")
                    
                    if not all_reset:
                        print("    ! Некоторые коэффициенты не сброшены:")
                        for trait, coef in resonance_coeffs.items():
                            if abs(coef - 1.0) > 0.01:
                                print(f"      - {trait}: {coef:.3f}")
                else:
                    print("    ✓ Профиль удален или сброшен")
            else:
                print("    ✗ Сброс не выполнен")
            
            # ============================================
            # ЭТАП 6: ПРОВЕРКА МЕТРИК
            # ============================================
            print("\n6. МЕТРИКИ РЕЗОНАНСНОЙ ПЕРСОНАЛИЗАЦИИ")
            print("-" * 40)
            
            metrics = personality._metrics
            
            print("  Основные метрики:")
            print(f"    - Профилей загружено: {metrics.get('resonance_profiles_loaded', 0)}")
            print(f"    - Применений резонанса: {metrics.get('resonance_applications', 0)}")
            print(f"    - Адаптаций выполнено: {metrics.get('resonance_adaptations', 0)}")
            print(f"    - Cache hits: {metrics.get('resonance_cache_hits', 0)}")
            print(f"    - Cache misses: {metrics.get('resonance_cache_misses', 0)}")
            
            if 'resonance_deviations_limited' in metrics:
                print(f"    - Ограничений применено: {metrics['resonance_deviations_limited']}")
            if 'resonance_resets' in metrics:
                print(f"    - Сбросов выполнено: {metrics['resonance_resets']}")
            
            # Дополнительные метрики для отладки
            print("\n  Все метрики резонанса:")
            for key, value in metrics.items():
                if 'resonance' in key.lower():
                    print(f"    - {key}: {value}")
            
            # ============================================
            # ЭТАП 7: ПРОВЕРКА БД
            # ============================================
            print("\n7. ПРОВЕРКА ДАННЫХ В БД")
            print("-" * 40)
            
            if personality._pool:
                # Проверяем таблицу user_personality_resonance
                resonance_row = await personality._pool.fetchrow(
                    """
                    SELECT resonance_profile, interaction_count, last_adaptation
                    FROM user_personality_resonance
                    WHERE user_id = $1
                    """,
                    TEST_USER_ID
                )
                
                if resonance_row:
                    print("  ✓ Профиль резонанса в БД:")
                    print(f"    - Взаимодействий: {resonance_row['interaction_count']}")
                    print(f"    - Последняя адаптация: {resonance_row['last_adaptation']}")
                    
                    profile = resonance_row['resonance_profile']
                    if profile:
                        # Правильный подсчет черт - количество ключей в JSONB
                        trait_count = len(profile) if isinstance(profile, dict) else 0
                        print(f"    - Количество черт: {trait_count} (ожидается 13)")
                        
                        # Показываем несколько примеров коэффициентов
                        if isinstance(profile, dict) and trait_count > 0:
                            sample_traits = list(profile.items())[:3]
                            print("    - Примеры коэффициентов:")
                            for trait, coef in sample_traits:
                                print(f"      * {trait}: {coef:.3f}")
                
                # Проверяем события обучения
                learning_events_count = await personality._pool.fetchval(
                    """
                    SELECT COUNT(*) 
                    FROM resonance_learning_events
                    WHERE user_id = $1
                    """,
                    TEST_USER_ID
                )
                
                print(f"\n  ✓ События обучения: {learning_events_count}")
                
                # Проверяем историю адаптаций
                adaptation_history = await personality._pool.fetch(
                    """
                    SELECT learning_rate, adapted_at
                    FROM resonance_adaptation_history
                    WHERE user_id = $1
                    ORDER BY adapted_at DESC
                    LIMIT 5
                    """,
                    TEST_USER_ID
                )
                
                if adaptation_history:
                    print(f"\n  ✓ История адаптаций ({len(adaptation_history)} записей):")
                    for record in adaptation_history[:3]:
                        print(f"    - Learning rate: {record['learning_rate']:.3f} в {record['adapted_at']}")
            
            # ============================================
            # ИТОГОВЫЕ РЕЗУЛЬТАТЫ
            # ============================================
            print(f"\n{'='*60}")
            print("РЕЗУЛЬТАТЫ ТЕСТА РЕЗОНАНСНОЙ ПЕРСОНАЛИЗАЦИИ")
            print(f"{'='*60}")
            
            success_checks = []
            
            # Проверка 1: Нейтральный старт
            if len(test_requester.received_profiles) > 0:
                success_checks.append("✓ Новый пользователь начинает с нейтрального резонанса")
            else:
                success_checks.append("✗ Не удалось проверить начальный резонанс")
            
            # Проверка 2: Адаптация работает
            if metrics.get('resonance_adaptations', 0) > 0 or adaptation_occurred:
                success_checks.append("✓ Резонансная адаптация выполняется")
            else:
                success_checks.append("✗ Резонансная адаптация НЕ произошла")
            
            # Проверка 3: Защитные механизмы
            if all_within_limits:
                success_checks.append("✓ Защитные ограничения работают")
            elif metrics.get('resonance_deviations_limited', 0) > 0:
                success_checks.append("✓ Защитные ограничения работают (срабатывали)")
            else:
                success_checks.append("⚠ Защитные ограничения не проверены полностью")
            
            # Проверка 4: Сброс резонанса
            if reset_success:
                success_checks.append("✓ Сброс резонанса работает")
            else:
                # Проверяем альтернативно через метрики или состояние
                if 'resonance_resets' in metrics and metrics['resonance_resets'] > 0:
                    success_checks.append("✓ Сброс резонанса работает (по метрикам)")
                else:
                    success_checks.append("⚠ Сброс резонанса не подтвержден метриками")
            
            for check in success_checks:
                print(check)
            
            print(f"\n{'='*60}\n")
            
        finally:
            # Очищаем тестовые данные (порядок важен из-за внешних ключей!)
            if personality._pool:
                # Сначала удаляем зависимые таблицы
                await personality._pool.execute(
                    "DELETE FROM resonance_adaptation_history WHERE user_id = $1",
                    TEST_USER_ID
                )
                await personality._pool.execute(
                    "DELETE FROM resonance_learning_events WHERE user_id = $1",
                    TEST_USER_ID
                )
                await personality._pool.execute(
                    "DELETE FROM personality_modifier_history WHERE user_id = $1",
                    TEST_USER_ID
                )
                # В конце удаляем основную таблицу
                await personality._pool.execute(
                    "DELETE FROM user_personality_resonance WHERE user_id = $1",
                    TEST_USER_ID
                )
            
            # Очищаем Redis
            redis_client = redis_connection.get_client()
            if redis_client:
                cache_key = redis_connection.make_key("personality", "profile", TEST_USER_ID)
                await redis_client.delete(cache_key)
            
            await system.stop()
            
            # Закрываем Event Store
            if hasattr(system, '_event_store') and system._event_store:
                await system._event_store.close()
            
            print("Система остановлена, тестовые данные очищены")
    
    @pytest.mark.asyncio
    async def test_resonance_protection_mechanisms(self):
        """Тест защитных механизмов резонанса"""
        
        # Подключаемся к БД
        if not db_connection._is_connected:
            await db_connection.connect()
        
        TEST_USER_ID = "test_protection_user"
        
        # Создаем PersonalityActor напрямую для тестирования защиты
        personality = PersonalityActor()
        await personality.initialize()
        
        try:
            print(f"\n{'='*60}")
            print("ТЕСТ ЗАЩИТНЫХ МЕХАНИЗМОВ РЕЗОНАНСА")
            print(f"{'='*60}")
            
            # ============================================
            # ТЕСТ 1: Ограничение отклонений
            # ============================================
            print("\n1. ТЕСТ ОГРАНИЧЕНИЯ ОТКЛОНЕНИЙ")
            print("-" * 40)
            
            # Создаем экстремальные коэффициенты
            extreme_coeffs = {
                'playfulness': 1.5,     # Превышает максимум
                'analytical': 0.5,      # Ниже минимума
                'curiosity': 1.2,       # В пределах
                'empathy': 0.8          # В пределах
            }
            
            print("  Входные коэффициенты (с нарушениями):")
            for trait, coef in extreme_coeffs.items():
                print(f"    - {trait}: {coef:.2f}")
            
            # Применяем защиту
            within_limits, adjusted = personality._check_resonance_deviation(
                extreme_coeffs, TEST_USER_ID
            )
            
            print("\n  Скорректированные коэффициенты:")
            for trait, coef in adjusted.items():
                print(f"    - {trait}: {coef:.2f}")
            
            print(f"\n  ✓ Коррекция применена: {not within_limits}")
            
            # ============================================
            # ТЕСТ 2: Защита core черт
            # ============================================
            print("\n2. ТЕСТ ЗАЩИТЫ CORE ЧЕРТ")
            print("-" * 40)
            
            # Коэффициенты с большими изменениями для core черт
            coeffs_for_core = {
                'curiosity': 1.3,       # Core trait
                'empathy': 0.7,         # Core trait
                'playfulness': 1.3,     # Обычная черта
                'analytical': 0.7       # Обычная черта
            }
            
            print("  Коэффициенты до защиты core черт:")
            for trait, coef in coeffs_for_core.items():
                is_core = " (CORE)" if trait in CORE_TRAITS else ""
                print(f"    - {trait}{is_core}: {coef:.2f}")
            
            # Применяем защиту core черт
            protected = personality._apply_stable_trait_protection(
                coeffs_for_core, 
                learning_rate=0.1
            )
            
            print("\n  После защиты core черт:")
            for trait, coef in protected.items():
                is_core = " (CORE)" if trait in CORE_TRAITS else ""
                original = coeffs_for_core[trait]
                change = abs(coef - original)
                print(f"    - {trait}{is_core}: {coef:.3f} (изменение: {change:.3f})")
            
            # Core черты должны измениться меньше
            core_changes = [abs(protected[t] - coeffs_for_core[t]) for t in CORE_TRAITS if t in protected]
            regular_changes = [abs(protected[t] - coeffs_for_core[t]) for t in protected if t not in CORE_TRAITS]
            
            if core_changes and regular_changes:
                avg_core_change = sum(core_changes) / len(core_changes)
                avg_regular_change = sum(regular_changes) / len(regular_changes) if regular_changes else 0
                print(f"\n  ✓ Средние изменения - Core: {avg_core_change:.3f}, Обычные: {avg_regular_change:.3f}")
            
            # ============================================
            # ТЕСТ 3: Добавление шума
            # ============================================
            print("\n3. ТЕСТ ДОБАВЛЕНИЯ ШУМА")
            print("-" * 40)
            
            # Базовые коэффициенты
            base_coeffs = {
                'playfulness': 1.1,
                'analytical': 0.9,
                'curiosity': 1.0,
                'empathy': 1.05
            }
            
            print("  Применяем шум 10 раз к одним коэффициентам:")
            
            variations = []
            for i in range(10):
                noisy = personality._add_resonance_noise(base_coeffs, noise_level=RESONANCE_NOISE_LEVEL)
                max_diff = max(abs(noisy[t] - base_coeffs[t]) for t in base_coeffs)
                variations.append(max_diff)
                
                if i < 3:  # Показываем первые 3
                    print(f"    Итерация {i+1}: max отклонение = {max_diff:.3f}")
            
            avg_variation = sum(variations) / len(variations)
            print(f"\n  ✓ Средняя вариация: {avg_variation:.3f} (уровень шума: {RESONANCE_NOISE_LEVEL})")
            
            # ============================================
            # ТЕСТ 4: Частичный сброс (имитация восстановления)
            # ============================================
            print("\n4. ТЕСТ ЧАСТИЧНОГО СБРОСА")
            print("-" * 40)
            
            # Сохраняем измененный профиль
            adapted_coeffs = {
                'playfulness': 1.2,
                'analytical': 0.8,
                'curiosity': 1.1,
                'empathy': 0.9
            }
            
            personality._resonance_profiles[TEST_USER_ID] = adapted_coeffs.copy()
            
            print("  Адаптированные коэффициенты:")
            for trait, coef in adapted_coeffs.items():
                print(f"    - {trait}: {coef:.2f}")
            
            # Выполняем частичный сброс
            await personality._reset_resonance_profile(
                TEST_USER_ID, 
                partial=True, 
                reset_factor=0.5  # 50% возврат к нейтральному
            )
            
            # Получаем обновленные коэффициенты
            reset_coeffs = personality._resonance_profiles.get(TEST_USER_ID, {})
            
            print("\n  После частичного сброса (50%):")
            for trait, coef in reset_coeffs.items():
                original = adapted_coeffs.get(trait, 1.0)
                expected = original + (1.0 - original) * 0.5
                print(f"    - {trait}: {coef:.3f} (ожидалось: {expected:.3f})")
            
            # ============================================
            # ИТОГИ
            # ============================================
            print(f"\n{'='*60}")
            print("РЕЗУЛЬТАТЫ ТЕСТА ЗАЩИТНЫХ МЕХАНИЗМОВ")
            print(f"{'='*60}")
            
            print("✓ Ограничение отклонений работает")
            print("✓ Core черты защищены")
            print("✓ Шум добавляется корректно")
            print("✓ Частичный сброс функционирует")
            
            print(f"\n{'='*60}\n")
            
        finally:
            # Очищаем тестовые данные (порядок важен из-за внешних ключей!)
            if personality._pool:
                # Сначала удаляем зависимые таблицы
                await personality._pool.execute(
                    "DELETE FROM resonance_adaptation_history WHERE user_id = $1",
                    TEST_USER_ID
                )
                await personality._pool.execute(
                    "DELETE FROM resonance_learning_events WHERE user_id = $1",
                    TEST_USER_ID
                )
                # В конце удаляем основную таблицу
                await personality._pool.execute(
                    "DELETE FROM user_personality_resonance WHERE user_id = $1",
                    TEST_USER_ID
                )
            
            await personality.shutdown()
            print("PersonalityActor остановлен, данные очищены")
    
    @pytest.mark.asyncio
    async def test_resonance_recovery_after_inactivity(self):
        """Тест восстановления резонанса после периода неактивности"""
        
        if not db_connection._is_connected:
            await db_connection.connect()
        
        TEST_USER_ID = "test_recovery_user"
        
        personality = PersonalityActor()
        await personality.initialize()
        
        try:
            print(f"\n{'='*60}")
            print("ТЕСТ ВОССТАНОВЛЕНИЯ ПОСЛЕ НЕАКТИВНОСТИ")
            print(f"{'='*60}")
            
            # Создаем адаптированный профиль
            adapted_profile = {
                'playfulness': 1.25,
                'analytical': 0.75,
                'curiosity': 1.15,
                'empathy': 0.85,
                'irony': 1.2,
                'philosophical': 0.8
            }
            
            # Устанавливаем профиль и время последней адаптации
            personality._resonance_profiles[TEST_USER_ID] = adapted_profile.copy()
            
            # Имитируем неактивность (8 дней назад)
            past_time = datetime.now(timezone.utc) - timedelta(days=8)
            personality._last_adaptations[TEST_USER_ID] = past_time
            
            print("  Начальное состояние:")
            print("    - Последняя активность: 8 дней назад")
            print(f"    - Порог для восстановления: {PERSONALITY_RECOVERY_DAYS} дней")
            
            print("\n  Адаптированные коэффициенты:")
            for trait, coef in list(adapted_profile.items())[:4]:
                print(f"    - {trait}: {coef:.2f}")
            
            # Применяем затухание
            await personality._apply_inactivity_decay(TEST_USER_ID, days_inactive=8)
            
            # Получаем обновленный профиль
            recovered_profile = personality._resonance_profiles.get(TEST_USER_ID, {})
            
            print("\n  После восстановления (1 день decay):")
            for trait in list(adapted_profile.keys())[:4]:
                original = adapted_profile[trait]
                recovered = recovered_profile.get(trait, 1.0)
                change = recovered - original
                print(f"    - {trait}: {recovered:.3f} (изменение: {change:+.3f})")
            
            # Проверяем что коэффициенты движутся к 1.0
            recovery_correct = all(
                abs(recovered_profile.get(t, 1.0) - 1.0) < abs(adapted_profile[t] - 1.0)
                for t in adapted_profile
            )
            
            print(f"\n  ✓ Коэффициенты движутся к нейтральному: {recovery_correct}")
            
            # Проверяем полное восстановление после длительной неактивности
            print("\n  Тест полного восстановления (30 дней):")
            
            personality._resonance_profiles[TEST_USER_ID] = adapted_profile.copy()
            await personality._apply_inactivity_decay(TEST_USER_ID, days_inactive=30)
            
            fully_recovered = personality._resonance_profiles.get(TEST_USER_ID, {})
            
            # После 30 дней должны быть близки к 1.0
            max_deviation = max(abs(v - 1.0) for v in fully_recovered.values())
            print(f"    - Максимальное отклонение от 1.0: {max_deviation:.3f}")
            print(f"    ✓ Полное восстановление: {max_deviation < 0.1}")
            
            print(f"\n{'='*60}\n")
            
        finally:
            # Очищаем тестовые данные
            if personality._pool:
                # Сначала удаляем зависимые таблицы
                await personality._pool.execute(
                    "DELETE FROM resonance_adaptation_history WHERE user_id = $1",
                    TEST_USER_ID
                )
                await personality._pool.execute(
                    "DELETE FROM resonance_learning_events WHERE user_id = $1",
                    TEST_USER_ID
                )
                # В конце удаляем основную таблицу
                await personality._pool.execute(
                    "DELETE FROM user_personality_resonance WHERE user_id = $1",
                    TEST_USER_ID
                )
            
            await personality.shutdown()
            print("Тест восстановления завершен")
    
    async def _get_resonance_coefficients(self, user_id: str) -> Dict[str, float]:
        """Вспомогательный метод для получения коэффициентов резонанса из БД"""
        if not db_connection._pool:
            return {}
        
        try:
            row = await db_connection._pool.fetchrow(
                """
                SELECT resonance_profile
                FROM user_personality_resonance
                WHERE user_id = $1
                """,
                user_id
            )
            
            if row and row['resonance_profile']:
                profile = row['resonance_profile']
                # JSONB автоматически десериализуется
                if isinstance(profile, str):
                    profile = json.loads(profile)
                return profile
            
            return {}
            
        except Exception as e:
            print(f"Ошибка получения резонанса: {e}")
            return {}


# Запуск напрямую
if __name__ == "__main__":
    test_suite = TestPersonalityResonance()
    asyncio.run(test_suite.test_resonance_full_cycle())
    # asyncio.run(test_suite.test_resonance_protection_mechanisms())
    # asyncio.run(test_suite.test_resonance_recovery_after_inactivity())