"""
Главный файл запуска Химеры
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в Python path
sys.path.insert(0, str(Path(__file__).parent))

# ВАЖНО: настраиваем логирование ДО всех импортов
from config.logging import setup_logging
setup_logging()

from config.settings import DEEPSEEK_API_KEY, TELEGRAM_BOT_TOKEN  # noqa: E402
from actors.actor_system import ActorSystem  # noqa: E402

# Импортируем наши акторы
from actors.user_session import UserSessionActor  # noqa: E402
from actors.generation import GenerationActor  # noqa: E402
from actors.telegram_actor import TelegramInterfaceActor  # noqa: E402
from actors.memory_actor import MemoryActor  # noqa: E402
from actors.perception_actor import PerceptionActor  # noqa: E402
from actors.auth import AuthActor  # noqa: E402
from actors.ltm import LTMActor  # noqa: E402
from actors.system_actor import SystemActor  # noqa: E402
from actors.talk_model_actor import TalkModelActor  # noqa: E402
from actors.personality import PersonalityActor # noqa: E402

async def main():
    """Главная функция запуска бота"""
    
    # Проверяем конфигурацию
    if not DEEPSEEK_API_KEY:
        print("ERROR: Please set DEEPSEEK_API_KEY in config/settings.py")
        return
        
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: Please set TELEGRAM_BOT_TOKEN in config/settings.py")
        return
    
    print("\n🐲 🐲 🐲 ХИМЕРА ВОЗВРАЩАЕТСЯ...\n")
    
    # Создаем систему акторов
    system = ActorSystem("chimera-bot")
    
    # Создаем Event Store согласно конфигурации
    await system.create_and_set_event_store()
    
    # Создаем акторы
    session_actor = UserSessionActor()
    generation_actor = GenerationActor()
    memory_actor = MemoryActor()
    perception_actor = PerceptionActor("perception")
    auth_actor = AuthActor()
    ltm_actor = LTMActor()
    talk_model_actor = TalkModelActor()
    personality_actor = PersonalityActor()
    telegram_actor = TelegramInterfaceActor()
    
    # Регистрируем акторы
    await system.register_actor(session_actor)
    await system.register_actor(generation_actor)
    await system.register_actor(memory_actor)
    await system.register_actor(perception_actor)
    await system.register_actor(auth_actor)
    await system.register_actor(ltm_actor)
    await system.register_actor(talk_model_actor)
    await system.register_actor(personality_actor)
    await system.register_actor(telegram_actor)
    
    # Создаем и регистрируем SystemActor
    # Используем приватный атрибут _event_store из ActorSystem
    system_actor = SystemActor(event_store=system._event_store)
    await system.register_actor(system_actor)
    
    # Запускаем систему
    await system.start()
    
    print("\n🐲 🐲 🐲 ХИМЕРА ЗДЕСЬ!\n")
   # print("Press Ctrl+C to stop")
    
    try:
        # Бесконечный цикл
        while True:
            await asyncio.sleep(60)
            
            # Периодически выводим метрики
            dlq_metrics = system.get_dlq_metrics()
            if dlq_metrics['current_size'] > 0:
                print(f"DLQ: {dlq_metrics['current_size']} messages")
                
    except KeyboardInterrupt:
        print("\n🐲 🐲 🐲 ХИМЕРА УХОДИТ...\n")
        
    finally:
            
        # Останавливаем систему
        await system.stop()
        print("\n🐲 🐲 🐲 ХИМЕРА УШЛА\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown completed")