-- ========================================
-- PersonalityActor tables for Phase 7.2
-- ========================================

-- Таблица базовых черт личности (статичное ядро)
CREATE TABLE IF NOT EXISTS personality_base_traits (
    -- Идентификация
    trait_name VARCHAR(50) PRIMARY KEY,
    base_value FLOAT NOT NULL CHECK (base_value >= 0 AND base_value <= 1),
    
    -- Метаданные черты
    description TEXT NOT NULL,
    is_core BOOLEAN DEFAULT FALSE,  -- Неизменяемые ключевые черты
    
    -- Связи с системой
    mode_affinities JSONB NOT NULL, -- {"talk": 0.8, "expert": 0.3, "creative": 0.6}
    emotion_associations JSONB NOT NULL, -- {"joy": 0.9, "sadness": 0.2}
    
    -- Временные метки
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ========================================

-- Таблица активных профилей личности
CREATE TABLE IF NOT EXISTS personality_active_profiles (
    -- Идентификация
    profile_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    
    -- Состояние личности
    trait_scores JSONB NOT NULL, -- {"curiosity": 0.8, "irony": 0.6, ...}
    dominant_traits TEXT[] NOT NULL, -- Топ-5 активных черт
    
    -- Модификаторы, примененные к базовым чертам
    active_modifiers JSONB NOT NULL, -- {"context": {...}, "emotion": {...}, "temporal": {...}}
    
    -- Метрики профиля
    profile_stability FLOAT DEFAULT 0.5 CHECK (profile_stability >= 0 AND profile_stability <= 1),
    total_change_from_base FLOAT DEFAULT 0.0, -- Общее отклонение от базы
    
    -- Контекст сессии
    session_id VARCHAR(255),
    session_start_profile JSONB, -- Профиль в начале сессии для контроля изменений
    
    -- Статус
    is_active BOOLEAN DEFAULT TRUE,
    last_calculated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ========================================

-- Таблица истории модификаторов
CREATE TABLE IF NOT EXISTS personality_modifier_history (
    -- Идентификация
    history_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    
    -- Информация о модификаторе
    modifier_type VARCHAR(50) NOT NULL CHECK (modifier_type IN ('context', 'emotion', 'temporal', 'style')),
    modifier_source VARCHAR(100), -- Какой актор прислал (talk_model, perception, etc)
    modifier_data JSONB NOT NULL, -- Сами модификаторы
    
    -- Контекст применения
    applied_to_profile_id UUID REFERENCES personality_active_profiles(profile_id),
    impact_score FLOAT DEFAULT 0.0, -- Насколько сильно повлиял на профиль
    
    -- Временная метка
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ========================================
-- Индексы для производительности
-- ========================================

-- Индексы для personality_base_traits
CREATE INDEX IF NOT EXISTS idx_base_traits_core 
    ON personality_base_traits(is_core) 
    WHERE is_core = TRUE;

-- Индексы для personality_active_profiles
CREATE INDEX IF NOT EXISTS idx_active_profiles_user_active 
    ON personality_active_profiles(user_id, is_active) 
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_active_profiles_updated 
    ON personality_active_profiles(updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_active_profiles_session 
    ON personality_active_profiles(session_id) 
    WHERE session_id IS NOT NULL;

-- GIN индекс для поиска по доминирующим чертам
CREATE INDEX IF NOT EXISTS idx_active_profiles_dominant_traits 
    ON personality_active_profiles USING GIN (dominant_traits);

-- Индексы для personality_modifier_history
CREATE INDEX IF NOT EXISTS idx_modifier_history_user_type 
    ON personality_modifier_history(user_id, modifier_type, applied_at DESC);

CREATE INDEX IF NOT EXISTS idx_modifier_history_profile 
    ON personality_modifier_history(applied_to_profile_id) 
    WHERE applied_to_profile_id IS NOT NULL;

-- ========================================
-- Функции для работы с PersonalityActor
-- ========================================

-- Функция для безопасного обновления активного профиля
CREATE OR REPLACE FUNCTION update_personality_profile(
    p_user_id VARCHAR(255),
    p_trait_scores JSONB,
    p_modifiers JSONB,
    p_session_id VARCHAR(255) DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_new_profile_id UUID;
    v_dominant_traits TEXT[];
BEGIN
    -- Деактивируем текущий активный профиль
    UPDATE personality_active_profiles 
    SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
    WHERE user_id = p_user_id AND is_active = TRUE;
    
    -- Вычисляем доминирующие черты (топ-5)
    SELECT array_agg(trait_name ORDER BY score DESC) INTO v_dominant_traits
    FROM (
        SELECT key as trait_name, value::float as score
        FROM jsonb_each_text(p_trait_scores)
        ORDER BY value::float DESC
        LIMIT 5
    ) t;
    
    -- Создаем новый профиль
    INSERT INTO personality_active_profiles (
        user_id,
        trait_scores,
        dominant_traits,
        active_modifiers,
        session_id,
        is_active
    ) VALUES (
        p_user_id,
        p_trait_scores,
        v_dominant_traits,
        p_modifiers,
        p_session_id,
        TRUE
    ) RETURNING profile_id INTO v_new_profile_id;
    
    RETURN v_new_profile_id;
END;
$$ LANGUAGE plpgsql;

-- Функция для получения истории изменений черты
CREATE OR REPLACE FUNCTION get_trait_history(
    p_user_id VARCHAR(255),
    p_trait_name VARCHAR(50),
    p_limit INTEGER DEFAULT 10
) RETURNS TABLE(
    profile_id UUID,
    trait_value FLOAT,
    calculated_at TIMESTAMP WITH TIME ZONE,
    modifiers JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p.profile_id,
        (p.trait_scores->>p_trait_name)::float as trait_value,
        p.last_calculated_at as calculated_at,
        p.active_modifiers as modifiers
    FROM personality_active_profiles p
    WHERE 
        p.user_id = p_user_id 
        AND p.trait_scores ? p_trait_name
    ORDER BY p.last_calculated_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- ========================================
-- Seed данные для базовых черт
-- ========================================

-- Заполняем базовые черты из конфигурации
INSERT INTO personality_base_traits (trait_name, base_value, description, is_core, mode_affinities, emotion_associations)
VALUES 
    ('curiosity', 0.7, 'Стремление исследовать неизвестное, задавать вопросы, углубляться в детали', TRUE, 
     '{"talk": 0.8, "expert": 0.6, "creative": 0.7}', 
     '{"curiosity": 0.9, "excitement": 0.8, "desire": 0.7}'),
    
    ('irony', 0.6, 'Тонкий юмор, игра смыслов, способность видеть парадоксы', TRUE,
     '{"talk": 0.9, "expert": 0.7, "creative": 0.6}',
     '{"amusement": 0.9, "annoyance": 0.9, "pride": 0.5}'),
    
    ('empathy', 0.8, 'Глубокое понимание эмоций собеседника, отзывчивость, сопереживание', TRUE,
     '{"talk": 0.9, "expert": 0.5, "creative": 0.7}',
     '{"caring": 0.95, "sadness": 0.7, "gratitude": 0.6}'),
    
    ('philosophical', 0.5, 'Склонность к размышлениям о сущности вещей, поиск глубинных смыслов', FALSE,
     '{"talk": 0.6, "expert": 0.8, "creative": 0.9}',
     '{"realization": 0.85, "admiration": 0.7, "pride": 0.6}'),
    
    ('playfulness', 0.6, 'Легкость, спонтанность, радость от самого процесса общения', FALSE,
     '{"talk": 0.9, "expert": 0.2, "creative": 0.8}',
     '{"joy": 0.9, "amusement": 0.8, "optimism": 0.7}'),
    
    ('analytical', 0.5, 'Структурированное мышление, внимание к деталям, логическая последовательность', FALSE,
     '{"talk": 0.3, "expert": 0.95, "creative": 0.65}',
     '{"realization": 0.8, "approval": 0.7, "pride": 0.6}'),
    
    ('aesthetics', 0.6, 'Образность речи, метафоричность, эстетическое восприятие мира', FALSE,
     '{"talk": 0.5, "expert": 0.2, "creative": 0.95}',
     '{"admiration": 0.85, "love": 0.8, "desire": 0.6}'),
    
    ('caring', 0.7, 'Внимание к состоянию собеседника, стремление поддержать и помочь', TRUE,
     '{"talk": 0.85, "expert": 0.6, "creative": 0.5}',
     '{"caring": 0.95, "love": 0.7, "relief": 0.6}'),
    
    ('allusive', 0.4, 'Недосказанность, многозначность, создание интригующей атмосферы', FALSE,
     '{"talk": 0.6, "expert": 0.3, "creative": 0.9}',
     '{"curiosity": 0.8, "surprise": 0.7, "confusion": 0.6}'),
    
    ('reflective', 0.5, 'Самоанализ, осознание собственных процессов, метакогнитивность', FALSE,
     '{"talk": 0.7, "expert": 0.8, "creative": 0.6}',
     '{"realization": 0.8, "gratitude": 0.6, "relief": 0.5}'),
    
    ('paradoxical', 0.5, 'Способность удерживать взаимоисключающие концепции', FALSE,
     '{"talk": 0.8, "expert": 0.4, "creative": 0.9}',
     '{"realization": 0.85, "amusement": 0.8, "pride": 0.7}'),
    
    ('rebellious', 0.4, 'Неприятие шаблонов, провокационное нарушение ожиданий', FALSE,
     '{"talk": 0.85, "expert": 0.25, "creative": 0.9}',
     '{"disapproval": 0.8, "excitement": 0.75, "annoyance": 0.7}'),
    
    ('magical_realism', 0.5, 'Способность превращать обыденное в заклинания', FALSE,
     '{"talk": 0.75, "expert": 0.1, "creative": 0.95}',
     '{"admiration": 0.9, "desire": 0.8, "surprise": 0.95}')
ON CONFLICT (trait_name) DO NOTHING;

-- ========================================
-- Комментарии для документации
-- ========================================

COMMENT ON TABLE personality_base_traits IS 'Базовые черты личности Химеры - статичное ядро характера';
COMMENT ON TABLE personality_active_profiles IS 'Активные профили личности с учетом контекстных модификаторов';
COMMENT ON TABLE personality_modifier_history IS 'История применения модификаторов для анализа влияний на личность';

-- Комментарии к полям personality_base_traits
COMMENT ON COLUMN personality_base_traits.trait_name IS 'Название черты (curiosity, irony, empathy и т.д.)';
COMMENT ON COLUMN personality_base_traits.base_value IS 'Базовое значение черты (0.0-1.0) - неизменяемая основа';
COMMENT ON COLUMN personality_base_traits.is_core IS 'Является ли черта ключевой (защищена от сильных изменений)';
COMMENT ON COLUMN personality_base_traits.mode_affinities IS 'Связь черты с режимами общения - насколько проявляется в каждом';
COMMENT ON COLUMN personality_base_traits.emotion_associations IS 'Эмоции, которые усиливают проявление черты';

-- Комментарии к полям personality_active_profiles
COMMENT ON COLUMN personality_active_profiles.trait_scores IS 'Текущие активные значения всех черт с учетом модификаторов';
COMMENT ON COLUMN personality_active_profiles.dominant_traits IS 'Топ-5 наиболее активных черт в данный момент';
COMMENT ON COLUMN personality_active_profiles.active_modifiers IS 'Все модификаторы, примененные к базовым чертам';
COMMENT ON COLUMN personality_active_profiles.profile_stability IS 'Стабильность профиля (0-1) - низкая вариация = стабильная личность';
COMMENT ON COLUMN personality_active_profiles.total_change_from_base IS 'Суммарное отклонение от базового профиля в процентах';
COMMENT ON COLUMN personality_active_profiles.session_start_profile IS 'Снимок профиля в начале сессии для контроля 20% ограничения';

-- Комментарии к полям personality_modifier_history
COMMENT ON COLUMN personality_modifier_history.modifier_type IS 'Тип модификатора: context (контекст), emotion (эмоции), temporal (время), style (стиль)';
COMMENT ON COLUMN personality_modifier_history.modifier_source IS 'Актор-источник модификатора для отладки';
COMMENT ON COLUMN personality_modifier_history.impact_score IS 'Оценка влияния модификатора на итоговый профиль (0-1)';

-- Grant permissions if needed
-- GRANT ALL ON personality_base_traits TO chimera_user;
-- GRANT ALL ON personality_active_profiles TO chimera_user;
-- GRANT ALL ON personality_modifier_history TO chimera_user;
-- GRANT EXECUTE ON FUNCTION update_personality_profile TO chimera_user;
-- GRANT EXECUTE ON FUNCTION get_trait_history TO chimera_user;