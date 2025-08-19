-- ========================================
-- Emotional Analysis Cache table
-- ========================================
-- Кэширование результатов анализа эмоциональных паттернов на 30 дней
-- для избежания повторных тяжелых вычислений

CREATE TABLE IF NOT EXISTS emotional_analysis_cache (
    -- Идентификация
    cache_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    
    -- Тип и период анализа
    analysis_type VARCHAR(50) NOT NULL CHECK (analysis_type IN ('baseline', 'peaks', 'full')),
    period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    period_end TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Результаты анализа
    analysis_data JSONB NOT NULL,
    
    -- Метаданные
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP + INTERVAL '30 days',
    
    -- Метрики производительности
    processing_time_ms INTEGER,
    events_processed INTEGER,
    
    -- Уникальность для предотвращения дублей
    CONSTRAINT unique_analysis_per_period UNIQUE (user_id, analysis_type, period_start, period_end)
);

-- ========================================
-- Индексы для оптимизации
-- ========================================

-- Индекс для поиска по пользователю и типу
CREATE INDEX IF NOT EXISTS idx_analysis_cache_user_type 
    ON emotional_analysis_cache(user_id, analysis_type);

-- Индекс для автоочистки expired записей
CREATE INDEX IF NOT EXISTS idx_analysis_cache_expiry 
    ON emotional_analysis_cache(expires_at)
    WHERE expires_at IS NOT NULL;

-- Составной индекс для быстрого поиска в кэше
CREATE INDEX IF NOT EXISTS idx_analysis_cache_lookup 
    ON emotional_analysis_cache(user_id, period_start DESC, period_end DESC);

-- GIN индекс для поиска внутри JSONB (опционально, для будущих query)
CREATE INDEX IF NOT EXISTS idx_analysis_cache_data_gin 
    ON emotional_analysis_cache USING GIN (analysis_data);

-- ========================================
-- Функция автоочистки expired записей
-- ========================================

CREATE OR REPLACE FUNCTION cleanup_expired_analysis_cache()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM emotional_analysis_cache
    WHERE expires_at < CURRENT_TIMESTAMP;
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- ========================================
-- Функция для обновления или вставки кэша (UPSERT)
-- ========================================

CREATE OR REPLACE FUNCTION upsert_analysis_cache(
    p_user_id VARCHAR(255),
    p_analysis_type VARCHAR(50),
    p_period_start TIMESTAMP WITH TIME ZONE,
    p_period_end TIMESTAMP WITH TIME ZONE,
    p_analysis_data JSONB,
    p_processing_time_ms INTEGER DEFAULT NULL,
    p_events_processed INTEGER DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_cache_id UUID;
BEGIN
    INSERT INTO emotional_analysis_cache (
        user_id,
        analysis_type,
        period_start,
        period_end,
        analysis_data,
        processing_time_ms,
        events_processed,
        expires_at
    ) VALUES (
        p_user_id,
        p_analysis_type,
        p_period_start,
        p_period_end,
        p_analysis_data,
        p_processing_time_ms,
        p_events_processed,
        CURRENT_TIMESTAMP + INTERVAL '30 days'
    )
    ON CONFLICT (user_id, analysis_type, period_start, period_end)
    DO UPDATE SET
        analysis_data = EXCLUDED.analysis_data,
        processing_time_ms = EXCLUDED.processing_time_ms,
        events_processed = EXCLUDED.events_processed,
        created_at = CURRENT_TIMESTAMP,
        expires_at = CURRENT_TIMESTAMP + INTERVAL '30 days'
    RETURNING cache_id INTO v_cache_id;
    
    RETURN v_cache_id;
END;
$$ LANGUAGE plpgsql;

-- ========================================
-- Комментарии для документации
-- ========================================

COMMENT ON TABLE emotional_analysis_cache IS 'Кэш результатов анализа эмоциональных паттернов с TTL 30 дней';

COMMENT ON COLUMN emotional_analysis_cache.cache_id IS 'Уникальный идентификатор записи кэша';
COMMENT ON COLUMN emotional_analysis_cache.user_id IS 'Telegram ID пользователя';
COMMENT ON COLUMN emotional_analysis_cache.analysis_type IS 'Тип анализа: baseline (все эмоции), peaks (только LTM), full (комплексный)';
COMMENT ON COLUMN emotional_analysis_cache.period_start IS 'Начало анализируемого периода (inclusive)';
COMMENT ON COLUMN emotional_analysis_cache.period_end IS 'Конец анализируемого периода (exclusive)';
COMMENT ON COLUMN emotional_analysis_cache.analysis_data IS 'JSON с результатами анализа (паттерны, кластеры, инсайты)';
COMMENT ON COLUMN emotional_analysis_cache.processing_time_ms IS 'Время выполнения анализа в миллисекундах';
COMMENT ON COLUMN emotional_analysis_cache.events_processed IS 'Количество обработанных событий';
COMMENT ON COLUMN emotional_analysis_cache.expires_at IS 'Время автоматического удаления записи';

-- ========================================
-- Пример использования
-- ========================================
/*
-- Сохранить результат анализа:
SELECT upsert_analysis_cache(
    '123456789',                    -- user_id
    'full',                          -- analysis_type
    '2024-01-01 00:00:00+00',       -- period_start
    '2024-01-31 23:59:59+00',       -- period_end
    '{"patterns": [...], "insights": [...]}'::jsonb,  -- analysis_data
    8547,                            -- processing_time_ms
    1234                             -- events_processed
);

-- Получить из кэша:
SELECT analysis_data
FROM emotional_analysis_cache
WHERE user_id = '123456789'
    AND analysis_type = 'full'
    AND period_start = '2024-01-01 00:00:00+00'
    AND period_end = '2024-01-31 23:59:59+00'
    AND expires_at > CURRENT_TIMESTAMP;

-- Очистить expired:
SELECT cleanup_expired_analysis_cache();
*/