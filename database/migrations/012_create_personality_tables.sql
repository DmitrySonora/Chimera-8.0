-- ========================================
-- Personality Analysis tables for Phase 7.1
-- ========================================

-- Таблица моделей собеседников (Partner Personas)
CREATE TABLE IF NOT EXISTS partner_personas (
    -- Идентификация
    persona_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    
    -- Стилевой вектор пользователя
    style_vector JSONB NOT NULL, -- {playfulness, seriousness, emotionality, creativity}
    style_confidence FLOAT NOT NULL DEFAULT 0.5 CHECK (style_confidence >= 0 AND style_confidence <= 1),
    
    -- Определенный оптимальный режим
    recommended_mode VARCHAR(20) NOT NULL CHECK (recommended_mode IN ('talk', 'expert', 'creative')),
    mode_confidence FLOAT NOT NULL DEFAULT 0.5 CHECK (mode_confidence >= 0 AND mode_confidence <= 1),
    
    -- Предиктивная компонента
    predicted_interests TEXT[] DEFAULT '{}',
    prediction_confidence FLOAT DEFAULT 0.0 CHECK (prediction_confidence >= 0 AND prediction_confidence <= 1),
    
    -- Метаданные
    messages_analyzed INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Проверка что хотя бы один элемент стиля заполнен
    CONSTRAINT style_vector_check CHECK (jsonb_typeof(style_vector) = 'object')
);

-- ========================================

-- Таблица проявлений черт личности
CREATE TABLE IF NOT EXISTS personality_traits_manifestations (
    -- Идентификация
    manifestation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    
    -- Информация о черте
    trait_name VARCHAR(50) NOT NULL,
    manifestation_strength FLOAT NOT NULL CHECK (manifestation_strength >= 0 AND manifestation_strength <= 1),
    
    -- Контекст проявления
    mode VARCHAR(20) NOT NULL CHECK (mode IN ('talk', 'expert', 'creative', 'base')),
    emotional_context JSONB NOT NULL, -- снимок эмоций в момент
    message_id UUID, -- ссылка на конкретное сообщение если есть
    
    -- Лингвистические маркеры
    detected_markers TEXT[] NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
    
    -- Временные метки
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Связь с анализом
    analysis_batch_id UUID -- для группировки по batch анализу
);

-- ========================================

-- Таблица агрегированных профилей черт (для быстрого доступа)
CREATE TABLE IF NOT EXISTS personality_trait_profiles (
    -- Идентификация
    profile_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    
    -- Агрегированные черты
    trait_scores JSONB NOT NULL, -- {trait_name: average_strength}
    dominant_traits TEXT[] NOT NULL, -- топ-5 черт
    
    -- Статистика
    total_manifestations INTEGER NOT NULL DEFAULT 0,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Уникальность профиля на пользователя
    CONSTRAINT unique_trait_profile UNIQUE(user_id)
);

-- ========================================
-- Индексы для производительности
-- ========================================

-- Partner Personas индексы
CREATE UNIQUE INDEX IF NOT EXISTS idx_personas_user_active_unique
    ON partner_personas(user_id)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_personas_user_active 
    ON partner_personas(user_id, is_active) 
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_personas_user_version 
    ON partner_personas(user_id, version DESC);

CREATE INDEX IF NOT EXISTS idx_personas_updated 
    ON partner_personas(updated_at DESC);

-- Manifestations индексы
CREATE INDEX IF NOT EXISTS idx_manifestations_user_time 
    ON personality_traits_manifestations(user_id, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_manifestations_trait 
    ON personality_traits_manifestations(trait_name, manifestation_strength DESC);

CREATE INDEX IF NOT EXISTS idx_manifestations_batch 
    ON personality_traits_manifestations(analysis_batch_id)
    WHERE analysis_batch_id IS NOT NULL;

-- GIN индекс для поиска по маркерам
CREATE INDEX IF NOT EXISTS idx_manifestations_markers 
    ON personality_traits_manifestations USING GIN (detected_markers);

-- Trait Profiles индексы
CREATE INDEX IF NOT EXISTS idx_trait_profiles_user 
    ON personality_trait_profiles(user_id);

-- GIN индекс для поиска по доминирующим чертам
CREATE INDEX IF NOT EXISTS idx_trait_profiles_dominant 
    ON personality_trait_profiles USING GIN (dominant_traits);

-- ========================================
-- Функции для работы с личностью
-- ========================================

-- Функция для атомарного обновления Partner Persona
CREATE OR REPLACE FUNCTION update_partner_persona(
    p_user_id VARCHAR(255),
    p_style_vector JSONB,
    p_style_confidence FLOAT,
    p_recommended_mode VARCHAR(20),
    p_mode_confidence FLOAT,
    p_messages_analyzed INTEGER
) RETURNS UUID AS $$
DECLARE
    v_new_persona_id UUID;
BEGIN
    -- Деактивируем текущую активную версию
    UPDATE partner_personas 
    SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
    WHERE user_id = p_user_id AND is_active = TRUE;
    
    -- Создаем новую версию
    INSERT INTO partner_personas (
        user_id,
        version,
        style_vector,
        style_confidence,
        recommended_mode,
        mode_confidence,
        messages_analyzed
    ) VALUES (
        p_user_id,
        COALESCE((SELECT MAX(version) + 1 FROM partner_personas WHERE user_id = p_user_id), 1),
        p_style_vector,
        p_style_confidence,
        p_recommended_mode,
        p_mode_confidence,
        p_messages_analyzed
    ) RETURNING persona_id INTO v_new_persona_id;
    
    RETURN v_new_persona_id;
END;
$$ LANGUAGE plpgsql;

-- Функция для обновления агрегированного профиля черт
CREATE OR REPLACE FUNCTION update_trait_profile(
    p_user_id VARCHAR(255)
) RETURNS VOID AS $$
BEGIN
    INSERT INTO personality_trait_profiles (user_id, trait_scores, dominant_traits, total_manifestations)
    SELECT 
        user_id,
        jsonb_object_agg(trait_name, avg_strength) as trait_scores,
        array_agg(trait_name ORDER BY avg_strength DESC) FILTER (WHERE rank <= 5) as dominant_traits,
        SUM(count)::INTEGER as total_manifestations
    FROM (
        SELECT 
            user_id,
            trait_name,
            AVG(manifestation_strength) as avg_strength,
            COUNT(*) as count,
            ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY AVG(manifestation_strength) DESC) as rank
        FROM personality_traits_manifestations
        WHERE user_id = p_user_id
            AND detected_at > CURRENT_TIMESTAMP - INTERVAL '30 days'
        GROUP BY user_id, trait_name
    ) t
    GROUP BY user_id
    ON CONFLICT (user_id) DO UPDATE SET
        trait_scores = EXCLUDED.trait_scores,
        dominant_traits = EXCLUDED.dominant_traits,
        total_manifestations = EXCLUDED.total_manifestations,
        last_updated = CURRENT_TIMESTAMP;
END;
$$ LANGUAGE plpgsql;

-- ========================================
-- Комментарии для документации
-- ========================================

COMMENT ON TABLE partner_personas IS 'Модели собеседников для персонализации режима общения';
COMMENT ON TABLE personality_traits_manifestations IS 'Проявления черт личности Химеры в диалогах';
COMMENT ON TABLE personality_trait_profiles IS 'Агрегированные профили черт для быстрого доступа';

COMMENT ON COLUMN partner_personas.style_vector IS '4D вектор стиля: [игривость, серьезность, эмоциональность, креативность]';
COMMENT ON COLUMN partner_personas.recommended_mode IS 'Оптимальный режим общения на основе стиля';
COMMENT ON COLUMN partner_personas.predicted_interests IS 'Предсказанные будущие интересы пользователя';

COMMENT ON COLUMN personality_traits_manifestations.trait_name IS 'Название черты (любознательность, ирония, эмпатия и т.д.)';
COMMENT ON COLUMN personality_traits_manifestations.manifestation_strength IS 'Сила проявления черты в данном контексте (0-1)';
COMMENT ON COLUMN personality_traits_manifestations.detected_markers IS 'Лингвистические маркеры, по которым выявлена черта';

-- Grant permissions if needed
-- GRANT ALL ON partner_personas TO chimera_user;
-- GRANT ALL ON personality_traits_manifestations TO chimera_user;
-- GRANT ALL ON personality_trait_profiles TO chimera_user;
-- GRANT EXECUTE ON FUNCTION update_partner_persona TO chimera_user;
-- GRANT EXECUTE ON FUNCTION update_trait_profile TO chimera_user;