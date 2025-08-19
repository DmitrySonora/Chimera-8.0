-- ========================================
-- Migration 009: Period summaries for LTM cleanup
-- ========================================

-- Таблица для хранения агрегированных summary удаленных воспоминаний
CREATE TABLE IF NOT EXISTS ltm_period_summaries (
    -- Идентификация
    summary_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    
    -- Временной период
    period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    period_end TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Агрегированные данные
    memories_count INTEGER NOT NULL CHECK (memories_count > 0),
    dominant_emotions TEXT[] NOT NULL,
    frequent_tags TEXT[] NOT NULL,
    avg_importance FLOAT NOT NULL CHECK (avg_importance >= 0 AND avg_importance <= 1),
    
    -- Метаданные
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Уникальность периода для пользователя
    CONSTRAINT ltm_summary_unique_period UNIQUE (user_id, period_start, period_end)
);

-- ========================================
-- Индексы для оптимизации
-- ========================================

-- Основной индекс для выборки по пользователю и времени
CREATE INDEX IF NOT EXISTS idx_ltm_summaries_user_period 
    ON ltm_period_summaries(user_id, period_end DESC);

-- Индекс для поиска по периодам
CREATE INDEX IF NOT EXISTS idx_ltm_summaries_period
    ON ltm_period_summaries(period_start, period_end);

-- GIN индекс для поиска по эмоциям в summary
CREATE INDEX IF NOT EXISTS idx_ltm_summaries_emotions
    ON ltm_period_summaries USING GIN (dominant_emotions);

-- GIN индекс для поиска по тегам в summary  
CREATE INDEX IF NOT EXISTS idx_ltm_summaries_tags
    ON ltm_period_summaries USING GIN (frequent_tags);

-- ========================================
-- Функция для автоматического обновления updated_at
-- ========================================

CREATE OR REPLACE FUNCTION update_ltm_summaries_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Удаляем триггер если существует
DROP TRIGGER IF EXISTS update_ltm_summaries_timestamp ON ltm_period_summaries;

-- Создаем триггер
CREATE TRIGGER update_ltm_summaries_timestamp
    BEFORE UPDATE ON ltm_period_summaries
    FOR EACH ROW
    EXECUTE FUNCTION update_ltm_summaries_updated_at();

-- ========================================
-- Комментарии для документации
-- ========================================

COMMENT ON TABLE ltm_period_summaries IS 'Агрегированные summary удаленных воспоминаний для сохранения исторического контекста';

-- Основные поля
COMMENT ON COLUMN ltm_period_summaries.summary_id IS 'Уникальный идентификатор summary';
COMMENT ON COLUMN ltm_period_summaries.user_id IS 'Telegram ID пользователя';
COMMENT ON COLUMN ltm_period_summaries.period_start IS 'Начало периода агрегации (inclusive)';
COMMENT ON COLUMN ltm_period_summaries.period_end IS 'Конец периода агрегации (exclusive)';

-- Агрегированные данные
COMMENT ON COLUMN ltm_period_summaries.memories_count IS 'Количество воспоминаний, агрегированных в этот summary';
COMMENT ON COLUMN ltm_period_summaries.dominant_emotions IS 'Топ доминирующие эмоции периода (до 5-10 эмоций)';
COMMENT ON COLUMN ltm_period_summaries.frequent_tags IS 'Наиболее частые семантические теги периода (до 10-20 тегов)';
COMMENT ON COLUMN ltm_period_summaries.avg_importance IS 'Средняя важность удаленных воспоминаний (0.0-1.0)';

-- Метаданные
COMMENT ON COLUMN ltm_period_summaries.created_at IS 'Время создания summary';
COMMENT ON COLUMN ltm_period_summaries.updated_at IS 'Время последнего обновления (при повторном cleanup того же периода)';

-- ========================================
-- Вспомогательная функция для получения summary статистики
-- ========================================

CREATE OR REPLACE FUNCTION get_user_summary_stats(
    p_user_id VARCHAR(255),
    p_days_back INTEGER DEFAULT 365
) RETURNS TABLE(
    total_summaries BIGINT,
    total_memories_aggregated BIGINT,
    oldest_period TIMESTAMP WITH TIME ZONE,
    newest_period TIMESTAMP WITH TIME ZONE,
    avg_memories_per_summary FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        COUNT(*) as total_summaries,
        SUM(memories_count) as total_memories_aggregated,
        MIN(period_start) as oldest_period,
        MAX(period_end) as newest_period,
        AVG(memories_count::FLOAT) as avg_memories_per_summary
    FROM ltm_period_summaries
    WHERE 
        user_id = p_user_id 
        AND created_at >= CURRENT_TIMESTAMP - INTERVAL '1 day' * p_days_back;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions if needed
-- GRANT ALL ON ltm_period_summaries TO chimera_user;
-- GRANT EXECUTE ON FUNCTION get_user_summary_stats(VARCHAR, INTEGER) TO chimera_user;