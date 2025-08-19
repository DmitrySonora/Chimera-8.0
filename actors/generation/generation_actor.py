from typing import Any, Optional, Dict, List, Tuple, Union
import json
from datetime import datetime
from actors.base_actor import BaseActor
from actors.messages import ActorMessage, MESSAGE_TYPES
from actors.events import BaseEvent
from config.prompts import (
    PROMPTS, 
    PROMPT_CONFIG, 
    JSON_SCHEMA_INSTRUCTIONS, 
    MODE_GENERATION_PARAMS, 
    GENERATION_PARAMS_LOG_CONFIG, 
    JSON_STUB_PROMPT, 
    NORMAL_STUB_PROMPT
)
from config.prompts_modulation import (
    PERSONALITY_INJECTIONS_ENABLED
)
from actors.events.generation_events import InjectionAppliedEvent, InjectionMetricsEvent
from config.settings import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT,
    CACHE_HIT_LOG_INTERVAL
)
from utils.monitoring import measure_latency
from utils.circuit_breaker import CircuitBreaker
from utils.event_utils import EventVersionManager
from models.structured_responses import parse_response
from pydantic import ValidationError

# Проверка наличия OpenAI SDK
try:
    from openai import AsyncOpenAI
    from actors.generation.personality_injection_mixin import PersonalityInjectionMixin
except ImportError:
    raise ImportError("Please install openai: pip install openai")


class GenerationActor(BaseActor, PersonalityInjectionMixin):
    """
    Актор для генерации ответов через DeepSeek API.
    Поддерживает JSON-режим, streaming и адаптивные стратегии промптов.
    """
    
    def __init__(self):
        super().__init__("generation", "Generation")
        PersonalityInjectionMixin.__init__(self)
        self._client = None
        self._circuit_breaker = None
        self._generation_count = 0
        self._total_cache_hits = 0
        self._json_failures = 0
        self._injection_count = 0
        self._event_version_manager = EventVersionManager()
        
        # Метрики по режимам
        self._mode_success_counts = {'base': 0, 'talk': 0, 'expert': 0, 'creative': 0}
        self._mode_failure_counts = {'base': 0, 'talk': 0, 'expert': 0, 'creative': 0}
        
    async def initialize(self) -> None:
        """Инициализация клиента DeepSeek"""
        if not DEEPSEEK_API_KEY:
            raise ValueError("DEEPSEEK_API_KEY not set in config/settings.py")
            
        self._client = AsyncOpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            timeout=DEEPSEEK_TIMEOUT
        )
        
        # Circuit Breaker для защиты от сбоев API
        self._circuit_breaker = CircuitBreaker(
            name="deepseek_api",
            failure_threshold=3,
            recovery_timeout=60,
            expected_exception=Exception  # Ловим все ошибки API
        )
        
        self.logger.info("GenerationActor initialized with DeepSeek API")
        
    async def shutdown(self) -> None:
        """Освобождение ресурсов"""
        if self._client:
            await self._client.close()
        self.logger.info(
            f"GenerationActor shutdown. Generated {self._generation_count} responses, "
            f"JSON failures: {self._json_failures}"
        )
        
        # Выводим метрики по режимам
        if sum(self._mode_success_counts.values()) > 0:
            self.logger.info(f"Mode validation success: {self._mode_success_counts}")
            self.logger.info(f"Mode validation failures: {self._mode_failure_counts}")
        
        # Выводим финальные метрики инъекций
        if self._injection_count > 0:
            metrics = self.get_injection_metrics()
            self.logger.info(
                f"Injection system final metrics: "
                f"total={metrics['total_injections']}, "
                f"sources={metrics['source_counts']}, "
                f"cached_profiles={metrics['cached_profiles']}"
            )
            
            if 'source_percentages' in metrics:
                self.logger.info(
                    f"Injection source distribution: "
                    f"fresh={metrics['source_percentages'].get('fresh', 0):.1f}%, "
                    f"cached={metrics['source_percentages'].get('cached', 0):.1f}%, "
                    f"random={metrics['source_percentages'].get('random', 0):.1f}%"
                )
        
    @measure_latency
    async def handle_message(self, message: ActorMessage) -> Optional[ActorMessage]:
        """Обработка запроса на генерацию"""
        if message.message_type != MESSAGE_TYPES['GENERATE_RESPONSE']:
            return None
            
        # Сохраняем payload для доступа в _generate_response
        self._current_message_payload = message.payload
        
        # Извлекаем данные
        user_id = message.payload['user_id']
        
        # Извлекаем данные
        user_id = message.payload['user_id']
        chat_id = message.payload['chat_id']
        text = message.payload['text']
        include_prompt = message.payload.get('include_prompt', True)
        
        # Извлекаем режим из payload (новое в 2.1.2)
        mode = message.payload.get('mode', 'base')
        
        self.logger.info(f"Generating response for user {user_id}")
        try:
            # Генерируем ответ
            response_text = await self._generate_response(
                text=text,
                user_id=user_id,
                include_prompt=include_prompt,
                mode=mode
            )
            
            # Создаем ответное сообщение
            self.logger.info(f"Generated response for user {user_id}: {response_text[:50]}...")
            
            # Применяем постобработку для Telegram
            telegram_text = self._fix_markdown_for_telegram(response_text)
            
            bot_response = ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES['BOT_RESPONSE'],
                payload={
                    'user_id': user_id,
                    'chat_id': chat_id,
                    'text': telegram_text,
                    'generated_at': datetime.now().isoformat()
                }
            )
            
            # Отправляем обратно в TelegramActor
            if self.get_actor_system():
                await self.get_actor_system().send_message("telegram", bot_response)
            
            return None
            
        except Exception as e:
            self.logger.error(f"Generation failed for user {user_id}: {str(e)}")
            
            # Создаем сообщение об ошибке
            error_msg = ActorMessage.create(
                sender_id=self.actor_id,
                message_type=MESSAGE_TYPES['ERROR'],
                payload={
                    'user_id': user_id,
                    'chat_id': chat_id,
                    'error': str(e),
                    'error_type': 'generation_error'
                }
            )
            
            # Отправляем в TelegramActor
            if self.get_actor_system():
                await self.get_actor_system().send_message("telegram", error_msg)
            
            return None
    
    async def _generate_response(
        self, 
        text: str, 
        user_id: str,
        include_prompt: bool = True,
        mode: str = "base"
    ) -> str:
        """Генерация ответа через DeepSeek API"""
        self.logger.info(f"Generating response for user {user_id} in mode: {mode}")
        
        # Получаем исторический контекст из payload (уже запрошен UserSessionActor)
        historical_context = []
        if hasattr(self, '_current_message_payload') and self._current_message_payload:
            historical_context = self._current_message_payload.get('historical_context', [])
            if historical_context:
                self.logger.info(f"Using {len(historical_context)} historical messages for context")
        
        # Извлекаем personality_profile из payload
        personality_profile = None
        if hasattr(self, '_current_message_payload') and self._current_message_payload:
            personality_profile = self._current_message_payload.get('personality_profile')
        
        # Формируем контекст с историей
        messages = await self._format_context(
            text, 
            include_prompt, 
            mode=mode, 
            historical_context=historical_context,
            user_id=user_id,
            personality_profile=personality_profile
        )
        
        # Определяем режим
        use_json = PROMPT_CONFIG["use_json_mode"]
        
        # Первая попытка
        try:
            response = await self._call_api(messages, use_json, mode)
            
            if use_json:
                # Пытаемся извлечь данные из JSON
                full_data = await self._extract_from_json(response, user_id, return_full_dict=True)
                
                # Валидируем структуру (пока только для логирования)
                from config.settings import JSON_VALIDATION_LOG_FAILURES
                if JSON_VALIDATION_LOG_FAILURES and isinstance(full_data, dict):
                    is_valid, errors = await self._validate_structured_response(full_data, mode=mode)
                    if not is_valid:
                        # Создаем событие о неудачной валидации
                        await self._log_validation_failure(user_id, errors, full_data)
                    
                    # Обновляем метрики по режимам
                    if is_valid:
                        self._mode_success_counts[mode] += 1
                    else:
                        self._mode_failure_counts[mode] += 1
                
                # Извлекаем текст ответа
                response_text = full_data['response'] if isinstance(full_data, dict) else str(full_data)
                
                # Логируем использованные параметры если включено
                if GENERATION_PARAMS_LOG_CONFIG.get("log_parameters_usage", True):
                    used_params = MODE_GENERATION_PARAMS.get(mode, MODE_GENERATION_PARAMS["base"])
                    params_event = BaseEvent.create(
                        stream_id=f"generation_{user_id}",
                        event_type="GenerationParametersUsedEvent",
                        data={
                            "user_id": user_id,
                            "mode": mode,
                            "temperature": used_params.get("temperature"),
                            "top_p": used_params.get("top_p"),
                            "max_tokens": used_params.get("max_tokens"),
                            "frequency_penalty": used_params.get("frequency_penalty"),
                            "presence_penalty": used_params.get("presence_penalty"),
                            "response_length": len(response_text) if GENERATION_PARAMS_LOG_CONFIG.get("log_response_length", True) else None,
                            "timestamp": datetime.now().isoformat()
                        }
                    )
                    await self._append_event(params_event)
                
                # Возвращаем только текст (поведение не меняется)
                return response_text
            else:
                # Логируем использованные параметры если включено
                if GENERATION_PARAMS_LOG_CONFIG.get("log_parameters_usage", True):
                    used_params = MODE_GENERATION_PARAMS.get(mode, MODE_GENERATION_PARAMS["base"])
                    params_event = BaseEvent.create(
                        stream_id=f"generation_{user_id}",
                        event_type="GenerationParametersUsedEvent",
                        data={
                            "user_id": user_id,
                            "mode": mode,
                            "temperature": used_params.get("temperature"),
                            "top_p": used_params.get("top_p"),
                            "max_tokens": used_params.get("max_tokens"),
                            "frequency_penalty": used_params.get("frequency_penalty"),
                            "presence_penalty": used_params.get("presence_penalty"),
                            "response_length": len(response),
                            "timestamp": datetime.now().isoformat()
                        }
                    )
                    await self._append_event(params_event)
                
                return response
                
        except json.JSONDecodeError as e:
            # JSON парсинг не удался
            self._json_failures += 1
            
            # Логируем событие
            await self._log_json_failure(user_id, str(e))
            
            # Проверяем fallback
            if PROMPT_CONFIG["json_fallback_enabled"] and use_json:
                self.logger.warning(f"JSON parse failed for user {user_id}, using fallback")
                
                # Повторяем без JSON
                messages = await self._format_context(
                    text, 
                    include_prompt, 
                    force_normal=True, 
                    mode=mode,
                    user_id=user_id,
                    personality_profile=personality_profile
                )
                response = await self._call_api(messages, use_json=False, mode=mode)
                return response
            else:
                # Возвращаем сырой ответ
                return response
    
    async def _format_context(
        self, 
        text: str, 
        include_prompt: bool,
        force_normal: bool = False,
        mode: str = "base",
        historical_context: List[Dict[str, str]] = None,
        user_id: str = None,
        personality_profile: Optional[Dict] = None
    ) -> List[Dict[str, str]]:
        """Форматирование контекста для API"""
        messages = []
        
        # Определяем use_json ДО условий
        use_json = PROMPT_CONFIG["use_json_mode"] and not force_normal
        
        # Системный промпт (если нужен)
        if include_prompt:
            
            # Всегда начинаем с базового промпта
            prompt_key = "json" if use_json else "normal"
            base_prompt = PROMPTS["base"][prompt_key]
            
            # Строим финальный промпт с учетом режима
            system_prompt = self._build_mode_prompt(base_prompt, mode, use_json)
            
            messages.append({
                "role": "system",
                "content": system_prompt
            })
            
            # Логирование промпта если включено
            if PROMPT_CONFIG.get("log_prompt_usage", False):
                prompt_type = f"system + {mode}" if mode != "base" else "system"
                prompt_preview = system_prompt[:PROMPT_CONFIG.get("log_prompt_preview_length", 60)]
                json_mode = "JSON" if use_json else "non-JSON"
                self.logger.info(f'PROMPT: {json_mode} "{prompt_type}" "{prompt_preview}..."')
        
        # JSON-заглушка когда полный промпт не включен
        elif use_json:
            messages.append({
                "role": "system",
                "content": JSON_STUB_PROMPT
            })
            
            # Логирование заглушки если включено
            if PROMPT_CONFIG.get("log_prompt_usage", False):
                prompt_preview = JSON_STUB_PROMPT[:PROMPT_CONFIG.get("log_prompt_preview_length", 60)]
                self.logger.info(f'PROMPT: JSON "stub" "{prompt_preview}..."')
        
        # Normal заглушка когда полный промпт не включен
        elif not use_json:
            messages.append({
                "role": "system",
                "content": NORMAL_STUB_PROMPT
            })
            
            # Логирование заглушки если включено
            if PROMPT_CONFIG.get("log_prompt_usage", False):
                prompt_preview = NORMAL_STUB_PROMPT[:PROMPT_CONFIG.get("log_prompt_preview_length", 60)]
                self.logger.info(f'PROMPT: Normal "stub" "{prompt_preview}..."')
        
        # Добавляем исторический контекст из STM
        if historical_context:
            messages.extend(historical_context)
            self.logger.debug(f"Added {len(historical_context)} historical messages to context")
        
        # Сообщение пользователя
        messages.append({
            "role": "user",
            "content": text
        })
        
        # Добавляем инъекции личности если включены
        if PERSONALITY_INJECTIONS_ENABLED and user_id:
            try:
                # Получаем инъекцию
                injection = await self.get_personality_injection(user_id, personality_profile)
                
                if injection:
                    # Находим системное сообщение и добавляем инъекцию
                    for message in messages:
                        if message["role"] == "system":
                            message["content"] += f"\n\n{injection}"
                            self.logger.debug("Added personality injection to system prompt")
                            break
                    
                    # Отслеживаем применение инъекции
                    # Определяем источник на основе данных
                    source = "unknown"
                    if personality_profile:
                        source = "fresh"
                    elif hasattr(self, '_last_known_profiles') and user_id in self._last_known_profiles:
                        source = "cached"
                    else:
                        source = "random"
                    
                    await self._track_injection_applied(user_id, source, injection)
                else:
                    self.logger.debug("No personality injection generated")
                    
            except Exception as e:
                self.logger.warning(f"Failed to add personality injection: {str(e)}")
        elif not PERSONALITY_INJECTIONS_ENABLED:
            self.logger.debug("Personality injections disabled in config")
        
        return messages
    
    async def _track_injection_applied(
        self,
        user_id: str,
        source: str,
        injection_text: str
    ) -> None:
        """Отслеживание применения инъекции и генерация событий"""
        self._injection_count += 1
        
        # Извлекаем использованные черты из текста инъекции
        # (упрощенный подход - в реальности миксин мог бы возвращать эту информацию)
        traits_used = []
        if hasattr(self, '_last_known_profiles') and user_id in self._last_known_profiles:
            profile = self._last_known_profiles[user_id]
            traits_used = self._get_top_traits_from_dict(profile, n=3)
        
        # Создаем событие применения инъекции
        injection_event = InjectionAppliedEvent.create(
            user_id=user_id,
            source=source,
            traits_used=traits_used,
            injection_length=len(injection_text)
        )
        await self._append_event(injection_event)
        
        # Логируем каждое 10-е применение
        if self._injection_count % 10 == 0:
            metrics = self.get_injection_metrics()
            total = metrics['total_injections']
            percentages = metrics.get('source_percentages', {})
            
            self.logger.info(
                f"Injection metrics after {total} applications: "
                f"fresh={percentages.get('fresh', 0):.1f}%, "
                f"cached={percentages.get('cached', 0):.1f}%, "
                f"random={percentages.get('random', 0):.1f}%"
            )
        
        # Создаем событие метрик каждые 100 инъекций
        if self._injection_count % 100 == 0:
            metrics = self.get_injection_metrics()
            
            # Вычисляем cache hit rate
            cache_hit_rate = 0.0
            if metrics['total_injections'] > 0:
                cached_count = metrics['source_counts'].get('cached', 0)
                cache_hit_rate = (cached_count / metrics['total_injections']) * 100
            
            metrics_event = InjectionMetricsEvent.create(
                total_injections=metrics['total_injections'],
                source_distribution=metrics['source_counts'],
                cache_hit_rate=cache_hit_rate
            )
            await self._append_event(metrics_event)
    
    def _build_mode_prompt(self, base_prompt: str, mode: str, use_json: bool) -> str:
        """
        Построение финального промпта с учетом режима.
        
        Args:
            base_prompt: Базовый промпт Химеры
            mode: Режим генерации
            use_json: Использовать ли JSON формат
            
        Returns:
            Финальный промпт с модификаторами
        """
        # Базовый случай - без модификаций
        if mode == 'base':
            return base_prompt
        
        # Проверяем наличие режимного промпта
        if mode not in PROMPTS:
            self.logger.warning(f"Unknown mode: {mode}, falling back to base")
            return base_prompt
        
        # Получаем модификатор для режима
        prompt_key = "json" if use_json else "normal"
        mode_modifier = PROMPTS[mode].get(prompt_key, "")
        
        # Если модификатор пустой или TODO - используем базовый
        if not mode_modifier or "TODO" in mode_modifier:
            return base_prompt
        
        # Строим финальный промпт: база + модификатор
        final_prompt = f"{base_prompt}\n\n{mode_modifier}"
        
        # Для JSON режима добавляем инструкции структуры (если есть)
        if use_json and mode in JSON_SCHEMA_INSTRUCTIONS:
            final_prompt += f"\n\n{JSON_SCHEMA_INSTRUCTIONS[mode]}"
        
        return final_prompt
    
    async def _call_api(
        self, 
        messages: List[Dict[str, str]], 
        use_json: bool,
        mode: str = "base"
    ) -> str:
        """Вызов DeepSeek API через Circuit Breaker"""
        
        async def api_call():
            # Получаем параметры для режима
            mode_params = MODE_GENERATION_PARAMS.get(mode, MODE_GENERATION_PARAMS["base"])
            
            # Логирование если включено
            if GENERATION_PARAMS_LOG_CONFIG.get("debug_mode_selection", False):
                self.logger.debug(
                    f"Using generation params for mode '{mode}': "
                    f"temp={mode_params.get('temperature')}, "
                    f"max_tokens={mode_params.get('max_tokens')}"
                )
            
            # Параметры вызова
            kwargs = {
                "model": DEEPSEEK_MODEL,
                "messages": messages,
                "temperature": mode_params.get("temperature", 0.82),
                "top_p": mode_params.get("top_p", 0.85),
                "max_tokens": mode_params.get("max_tokens", 1800),
                "frequency_penalty": mode_params.get("frequency_penalty", 0.4),
                "presence_penalty": mode_params.get("presence_penalty", 0.65),
                "stream": True  # Всегда используем streaming
            }
            
            # JSON режим
            if use_json:
                kwargs["response_format"] = {"type": "json_object"}
            
            # Streaming вызов
            response = await self._client.chat.completions.create(**kwargs)
            
            # Собираем ответ из чанков
            full_response = ""
            prompt_cache_hit_tokens = 0
            prompt_cache_miss_tokens = 0
            
            async for chunk in response:
                if chunk.choices[0].delta.content:
                    full_response += chunk.choices[0].delta.content
                    
                    # TODO: Отправлять StreamingChunkEvent для UI
                    
                # Извлекаем метрики кэша (если есть)
                if hasattr(chunk, 'usage') and chunk.usage:
                    prompt_cache_hit_tokens = getattr(
                        chunk.usage, 'prompt_cache_hit_tokens', 0
                    )
                    prompt_cache_miss_tokens = getattr(
                        chunk.usage, 'prompt_cache_miss_tokens', 0
                    )
            
            # Логируем метрики кэша
            await self._log_cache_metrics(
                prompt_cache_hit_tokens,
                prompt_cache_miss_tokens
            )
            
            return full_response
        
        # Вызываем через Circuit Breaker
        return await self._circuit_breaker.call(api_call)
    
    async def _extract_from_json(
        self, 
        response: str, 
        user_id: str,
        return_full_dict: bool = False
    ) -> Union[str, Dict[str, Any]]:
        """
        Извлечение данных из JSON ответа.
        
        Args:
            response: JSON строка
            user_id: ID пользователя для логирования
            return_full_dict: Если True, возвращает весь словарь, иначе только текст
            
        Returns:
            Строку с текстом ответа или полный словарь (в зависимости от return_full_dict)
        """
        try:
            # Парсим JSON
            data = json.loads(response)
            
            # Опционально: валидируем через Pydantic для раннего обнаружения ошибок
            if return_full_dict:
                try:
                    from models.structured_responses import parse_response
                    # Пробуем распарсить для валидации (не используем результат)
                    _ = parse_response(data, mode='base')  # базовая валидация
                except Exception:
                    # Не блокируем работу если Pydantic валидация не прошла
                    pass
            
            # Проверяем наличие обязательного поля response
            if isinstance(data, dict) and 'response' in data:
                if return_full_dict:
                    return data
                else:
                    return data['response']
            else:
                raise ValueError("JSON doesn't contain 'response' field")
                
        except (json.JSONDecodeError, ValueError) as e:
            self.logger.error(f"Failed to parse JSON for user {user_id}: {str(e)}")
            self.logger.debug(f"Raw response: {response[:200]}...")
            raise
    
    def _fix_markdown_for_telegram(self, text: str) -> str:
        """Экранирует специальные символы и исправляет форматирование для Telegram"""
        # Экранируем подчеркивания, чтобы Telegram не интерпретировал их как markdown
        text = text.replace('_', '\\_')
        
        # Заменяем кавычки на ёлочки только для текста с кириллицей
        import re
        
        # Функция проверки наличия кириллицы
        def has_cyrillic(text):
            return bool(re.search(r'[а-яА-ЯёЁ]', text))
        
        # Замена одинарных кавычек
        def replace_quotes_single(match):
            content = match.group(1)
            if has_cyrillic(content):
                return f"«{content}»"
            return match.group(0)
        
        # Замена двойных кавычек
        def replace_quotes_double(match):
            content = match.group(1)
            if has_cyrillic(content):
                return f"«{content}»"
            return match.group(0)
        
        # Защищаем содержимое в фигурных скобках от замены
        import uuid
        placeholders = {}
        
        # Сохраняем содержимое фигурных скобок
        def save_braces(match):
            key = f"__PLACEHOLDER_{uuid.uuid4().hex}__"
            placeholders[key] = match.group(0)
            return key
        
        text = re.sub(r'\{[^{}]+\}', save_braces, text)
        
        # Теперь безопасно заменяем кавычки
        text = re.sub(r"'([^']+)'", replace_quotes_single, text)
        text = re.sub(r'"([^"]+)"', replace_quotes_double, text)
        
        # Восстанавливаем содержимое фигурных скобок
        for key, value in placeholders.items():
            text = text.replace(key, value)
        
        return text
    
    async def _validate_structured_response(
        self, 
        response_dict: Dict[str, Any], 
        mode: str = 'base'
    ) -> Tuple[bool, List[str]]:
        """
        Валидирует структурированный JSON-ответ через Pydantic модель.
        
        Args:
            response_dict: Распарсенный JSON ответ
            mode: Режим генерации для выбора модели
            
        Returns:
            (успех, список_ошибок)
        """
        from config.settings import JSON_VALIDATION_ENABLED
        
        if not JSON_VALIDATION_ENABLED:
            return True, []
        
        try:
            # Используем Pydantic для валидации
            _ = parse_response(response_dict, mode)
            
            # Если дошли сюда - валидация успешна
            return True, []
            
        except ValidationError as e:
            # Парсим ошибки Pydantic напрямую
            errors = []
            
            for error in e.errors():
                field = '.'.join(str(x) for x in error['loc'])
                msg = error['msg']
                errors.append(f"{field}: {msg}")
            
            # Ограничиваем количество ошибок
            from config.prompts import JSON_VALIDATION_CONFIG
            max_errors = JSON_VALIDATION_CONFIG.get('max_validation_errors', 5)
            if len(errors) > max_errors:
                errors = errors[:max_errors] + [f"... and {len(errors) - max_errors} more errors"]
            
            return False, errors
            
        except ValueError as e:
            # Другие ошибки (например, от parse_response при невалидном JSON)
            errors = []
            
            # Проверяем, есть ли ValidationError в цепочке причин
            if hasattr(e, '__cause__') and isinstance(e.__cause__, ValidationError):
                # Если parse_response обернул ValidationError в ValueError
                for error in e.__cause__.errors():
                    field = '.'.join(str(x) for x in error['loc'])
                    msg = error['msg']
                    errors.append(f"{field}: {msg}")
            else:
                # Другие ValueError (например, невалидный JSON)
                errors.append(str(e))
            
            # Ограничиваем количество ошибок
            from config.prompts import JSON_VALIDATION_CONFIG
            max_errors = JSON_VALIDATION_CONFIG.get('max_validation_errors', 5)
            if len(errors) > max_errors:
                errors = errors[:max_errors] + [f"... and {len(errors) - max_errors} more errors"]
            
            return False, errors
    
    async def _log_validation_failure(
        self, 
        user_id: str, 
        errors: List[str], 
        response_data: Dict[str, Any]
    ) -> None:
        """Логирует событие неудачной валидации"""
        event = BaseEvent.create(
            stream_id=f"validation_{user_id}",
            event_type="JSONValidationFailedEvent",
            data={
                "user_id": user_id,
                "errors": errors,
                "response_fields": list(response_data.keys()),
                "timestamp": datetime.now().isoformat()
            }
        )
        
        await self._append_event(event)
        
        self.logger.warning(
            f"JSON validation failed for user {user_id}: {', '.join(errors[:3])}"
        )
    
    async def _log_cache_metrics(
        self, 
        hit_tokens: int, 
        miss_tokens: int
    ) -> None:
        """Логирование метрик кэша"""
        self._generation_count += 1
        
        # Вычисляем cache hit rate
        total_tokens = hit_tokens + miss_tokens
        if total_tokens > 0:
            cache_hit_rate = hit_tokens / total_tokens
            self._total_cache_hits += cache_hit_rate
            
            # Логируем периодически
            if self._generation_count % CACHE_HIT_LOG_INTERVAL == 0:
                avg_cache_hit = self._total_cache_hits / self._generation_count
                self.logger.info(
                    f"Cache metrics - Generations: {self._generation_count}, "
                    f"Avg hit rate: {avg_cache_hit:.2%}, "
                    f"Last hit rate: {cache_hit_rate:.2%}"
                )
            
            # Создаем событие метрики
            event = BaseEvent.create(
                stream_id="metrics",
                event_type="CacheHitMetricEvent",
                data={
                    "prompt_cache_hit_tokens": hit_tokens,
                    "prompt_cache_miss_tokens": miss_tokens,
                    "cache_hit_rate": cache_hit_rate,
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            # Сохраняем событие
            await self._append_event(event)
    
    async def _log_json_failure(self, user_id: str, error: str) -> None:
        """Логирование сбоя JSON парсинга"""
        event = BaseEvent.create(
            stream_id=f"user_{user_id}",
            event_type="JSONModeFailureEvent",
            data={
                "user_id": user_id,
                "error": error,
                "timestamp": datetime.now().isoformat()
            }
        )
        
        await self._append_event(event)
    
    async def _append_event(self, event: BaseEvent) -> None:
        """Добавить событие через менеджер версий"""
        await self._event_version_manager.append_event(event, self.get_actor_system())