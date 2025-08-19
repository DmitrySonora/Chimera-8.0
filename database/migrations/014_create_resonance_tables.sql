-- ========================================
-- Resonance Personalization tables for Phase 7.3
-- ========================================

-- Таблица активных профилей резонанса
CREATE TABLE IF NOT EXISTS user_personality_resonance (
    -- Идентификация
    user_id VARCHAR(255) PRIMARY KEY,
    
    -- Профиль резонанса
    resonance_profile JSONB NOT NULL DEFAULT '{}', -- {"trait_name": coefficient}
    
    -- Статистика взаимодействий
    interaction_count INTEGER NOT NULL DEFAULT 0,
    last_adaptation TIMESTAMP WITH TIME ZONE,
    
    -- Версионирование для отката
    profile_version INTEGER NOT NULL DEFAULT 1,
    previous_profile JSONB, -- Для возможности отката
    
    -- Метаданные
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Мягкое удаление (добавлено согласно шагу 11)
    is_active BOOLEAN DEFAULT TRUE,
    deactivated_at TIMESTAMP WITH TIME ZONE,
    deactivation_reason VARCHAR(50), -- 'inactivity' | 'manual' | 'user_request'
    
    -- Проверка диапазона коэффициентов резонанса
    CONSTRAINT resonance_coefficients_range CHECK (
        jsonb_typeof(resonance_profile) = 'object'
    )
);

-- ========================================

-- Таблица истории адаптаций резонанса
CREATE TABLE IF NOT EXISTS resonance_adaptation_history (
    -- Идентификация
    adaptation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL REFERENCES user_personality_resonance(user_id),
    
    -- Данные адаптации
    old_profile JSONB NOT NULL,
    new_profile JSONB NOT NULL,
    change_delta JSONB NOT NULL, -- Разница между профилями
    
    -- Контекст адаптации
    adaptation_reason VARCHAR(100) NOT NULL, -- 'periodic', 'style_change', 'manual'
    style_vector JSONB NOT NULL, -- Стиль пользователя в момент адаптации
    dominant_emotion VARCHAR(50), -- Эмоция, если повлияла
    learning_rate FLOAT NOT NULL DEFAULT 0.05,
    
    -- Метрики
    total_change FLOAT NOT NULL, -- Сумма всех изменений
    affected_traits TEXT[] NOT NULL, -- Список измененных черт
    
    -- Временная метка
    adapted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Валидация
    CONSTRAINT valid_learning_rate CHECK (learning_rate > 0 AND learning_rate <= 1),
    CONSTRAINT valid_total_change CHECK (total_change >= 0)
);

-- ========================================

-- Таблица событий обучения резонанса (для будущего ML)
CREATE TABLE IF NOT EXISTS resonance_learning_events (
    -- Идентификация
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    
    -- Тип события
    event_type VARCHAR(50) NOT NULL, -- 'interaction', 'feedback', 'milestone'
    event_data JSONB NOT NULL, -- Специфичные данные события
    
    -- Контекст
    session_id VARCHAR(255),
    message_count INTEGER,
    current_resonance JSONB, -- Снимок резонанса в момент события
    
    -- Качественные метрики (для будущего анализа)
    user_satisfaction FLOAT, -- Если удастся определить
    conversation_quality FLOAT, -- Если удастся измерить
    
    -- Временная метка
    occurred_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Обработка
    processed BOOLEAN DEFAULT FALSE,
    processed_at TIMESTAMP WITH TIME ZONE,
    
    -- Валидация
    CONSTRAINT valid_metrics CHECK (
        (user_satisfaction IS NULL OR (user_satisfaction >= 0 AND user_satisfaction <= 1)) AND
        (conversation_quality IS NULL OR (conversation_quality >= 0 AND conversation_quality <= 1))
    )
);

-- ========================================
-- Индексы для производительности
-- ========================================

-- Индексы для user_personality_resonance
CREATE INDEX IF NOT EXISTS idx_resonance_active 
    ON user_personality_resonance(user_id) 
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_resonance_updated 
    ON user_personality_resonance(updated_at DESC) 
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_resonance_interaction_count 
    ON user_personality_resonance(interaction_count DESC) 
    WHERE is_active = TRUE;

-- GIN индекс для поиска по резонансным коэффициентам
CREATE INDEX IF NOT EXISTS idx_resonance_profile_gin 
    ON user_personality_resonance USING GIN (resonance_profile);

-- Индексы для resonance_adaptation_history
CREATE INDEX IF NOT EXISTS idx_adaptation_user_time 
    ON resonance_adaptation_history(user_id, adapted_at DESC);

CREATE INDEX IF NOT EXISTS idx_adaptation_reason 
    ON resonance_adaptation_history(adaptation_reason);

-- GIN индекс для поиска по измененным чертам
CREATE INDEX IF NOT EXISTS idx_adaptation_traits 
    ON resonance_adaptation_history USING GIN (affected_traits);

-- Индексы для resonance_learning_events
CREATE INDEX IF NOT EXISTS idx_learning_events_user 
    ON resonance_learning_events(user_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_learning_events_unprocessed 
    ON resonance_learning_events(occurred_at) 
    WHERE processed = FALSE;

CREATE INDEX IF NOT EXISTS idx_learning_events_type 
    ON resonance_learning_events(event_type);

-- ========================================
-- Триггеры
-- ========================================

-- Триггер для автоматического обновления updated_at
CREATE OR REPLACE FUNCTION update_resonance_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_resonance_timestamp ON user_personality_resonance;
CREATE TRIGGER update_resonance_timestamp
    BEFORE UPDATE ON user_personality_resonance
    FOR EACH ROW
    EXECUTE FUNCTION update_resonance_updated_at();

-- ========================================
-- Функции для работы с резонансом
-- ========================================

-- Функция для безопасного обновления резонанса
CREATE OR REPLACE FUNCTION update_resonance_profile(
    p_user_id VARCHAR(255),
    p_new_profile JSONB,
    p_style_vector JSONB,
    p_learning_rate FLOAT DEFAULT 0.05,
    p_emotion VARCHAR(50) DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_old_profile JSONB;
    v_change_delta JSONB;
    v_total_change FLOAT;
    v_affected_traits TEXT[];
    v_adaptation_id UUID;
BEGIN
    -- Получаем текущий профиль
    SELECT resonance_profile INTO v_old_profile
    FROM user_personality_resonance
    WHERE user_id = p_user_id AND is_active = TRUE
    FOR UPDATE;
    
    -- Если профиля нет, создаем новый
    IF v_old_profile IS NULL THEN
        INSERT INTO user_personality_resonance (user_id, resonance_profile)
        VALUES (p_user_id, p_new_profile)
        ON CONFLICT (user_id) DO UPDATE
        SET resonance_profile = EXCLUDED.resonance_profile,
            is_active = TRUE,
            deactivated_at = NULL;
        RETURN NULL;
    END IF;
    
    -- Вычисляем изменения
    v_change_delta = p_new_profile;
    
    -- Вычисляем общее изменение и затронутые черты
    SELECT 
        SUM(ABS((value::text::float) - COALESCE((v_old_profile->>key)::float, 1.0))),
        array_agg(key)
    INTO v_total_change, v_affected_traits
    FROM jsonb_each(p_new_profile)
    WHERE (value::text::float) != COALESCE((v_old_profile->>key)::float, 1.0);
    
    -- Обновляем профиль
    UPDATE user_personality_resonance
    SET 
        resonance_profile = p_new_profile,
        previous_profile = v_old_profile,
        profile_version = profile_version + 1,
        interaction_count = interaction_count + 1,
        last_adaptation = CURRENT_TIMESTAMP
    WHERE user_id = p_user_id;
    
    -- Записываем в историю
    INSERT INTO resonance_adaptation_history (
        user_id,
        old_profile,
        new_profile,
        change_delta,
        adaptation_reason,
        style_vector,
        dominant_emotion,
        learning_rate,
        total_change,
        affected_traits
    ) VALUES (
        p_user_id,
        v_old_profile,
        p_new_profile,
        v_change_delta,
        'periodic',
        p_style_vector,
        p_emotion,
        p_learning_rate,
        COALESCE(v_total_change, 0),
        COALESCE(v_affected_traits, ARRAY[]::TEXT[])
    ) RETURNING adaptation_id INTO v_adaptation_id;
    
    RETURN v_adaptation_id;
END;
$$ LANGUAGE plpgsql;

-- Функция для получения статистики резонанса
CREATE OR REPLACE FUNCTION get_resonance_statistics(
    p_days_back INTEGER DEFAULT 30
) RETURNS TABLE(
    avg_resonance_per_trait JSONB,
    total_adaptations BIGINT,
    avg_change_per_adaptation FLOAT,
    most_volatile_traits TEXT[]
) AS $$
BEGIN
    RETURN QUERY
    WITH trait_changes AS (
        SELECT 
            unnest(affected_traits) as trait,
            total_change
        FROM resonance_adaptation_history
        WHERE adapted_at > CURRENT_TIMESTAMP - INTERVAL '1 day' * p_days_back
    ),
    trait_stats AS (
        SELECT 
            trait,
            COUNT(*) as change_count,
            AVG(total_change) as avg_change
        FROM trait_changes
        GROUP BY trait
    )
    SELECT 
        jsonb_object_agg(trait, avg_change) as avg_resonance_per_trait,
        (SELECT COUNT(*) FROM resonance_adaptation_history WHERE adapted_at > CURRENT_TIMESTAMP - INTERVAL '1 day' * p_days_back),
        (SELECT AVG(total_change) FROM resonance_adaptation_history WHERE adapted_at > CURRENT_TIMESTAMP - INTERVAL '1 day' * p_days_back),
        (SELECT array_agg(trait ORDER BY change_count DESC) FROM trait_stats LIMIT 5)
    FROM trait_stats;
END;
$$ LANGUAGE plpgsql;

-- ========================================
-- Комментарии для документации
-- ========================================

COMMENT ON TABLE user_personality_resonance IS 'Персональные профили резонанса для адаптации черт личности под конкретных пользователей';
COMMENT ON TABLE resonance_adaptation_history IS 'История изменений резонансных профилей для анализа эволюции';
COMMENT ON TABLE resonance_learning_events IS 'События для будущего машинного обучения и улучшения резонанса';

-- Комментарии к полям user_personality_resonance
COMMENT ON COLUMN user_personality_resonance.resonance_profile IS 'JSON с коэффициентами резонанса для каждой черты {trait: 0.7-1.3}';
COMMENT ON COLUMN user_personality_resonance.interaction_count IS 'Количество взаимодействий с момента создания профиля';
COMMENT ON COLUMN user_personality_resonance.profile_version IS 'Версия профиля для возможности отката';
COMMENT ON COLUMN user_personality_resonance.is_active IS 'Флаг активности для мягкого удаления';
COMMENT ON COLUMN user_personality_resonance.deactivation_reason IS 'Причина деактивации: inactivity, manual, user_request';

-- Комментарии к полям resonance_adaptation_history
COMMENT ON COLUMN resonance_adaptation_history.change_delta IS 'Разница между старым и новым профилем для анализа';
COMMENT ON COLUMN resonance_adaptation_history.style_vector IS '4D вектор стиля пользователя в момент адаптации';
COMMENT ON COLUMN resonance_adaptation_history.total_change IS 'Сумма абсолютных изменений всех коэффициентов';
COMMENT ON COLUMN resonance_adaptation_history.affected_traits IS 'Список черт, которые были изменены';

-- Комментарии к полям resonance_learning_events
COMMENT ON COLUMN resonance_learning_events.event_type IS 'Тип события: interaction (взаимодействие), feedback (обратная связь), milestone (веха)';
COMMENT ON COLUMN resonance_learning_events.user_satisfaction IS 'Оценка удовлетворенности пользователя (для будущего ML)';
COMMENT ON COLUMN resonance_learning_events.conversation_quality IS 'Качество диалога (для будущего ML)';

-- Grant permissions if needed
-- GRANT ALL ON user_personality_resonance TO chimera_user;
-- GRANT ALL ON resonance_adaptation_history TO chimera_user;
-- GRANT ALL ON resonance_learning_events TO chimera_user;
-- GRANT EXECUTE ON FUNCTION update_resonance_profile TO chimera_user;
-- GRANT EXECUTE ON FUNCTION get_resonance_statistics TO chimera_user;