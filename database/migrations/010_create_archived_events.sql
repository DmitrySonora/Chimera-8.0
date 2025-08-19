-- Миграция 010: Создание таблицы для архивированных событий
-- Цель: Долгосрочное хранение старых событий в сжатом виде

-- Таблица для архивированных событий
CREATE TABLE IF NOT EXISTS archived_events (
    archive_id BIGSERIAL PRIMARY KEY,
    original_event_id UUID NOT NULL,
    stream_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(255) NOT NULL,
    compressed_data TEXT NOT NULL,  -- gzipped JSON data
    original_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    archived_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Уникальность по оригинальному ID для избежания дубликатов
    CONSTRAINT unique_archived_event UNIQUE(original_event_id)
);

-- Индексы для эффективного поиска
CREATE INDEX IF NOT EXISTS idx_archived_stream 
    ON archived_events(stream_id);
    
CREATE INDEX IF NOT EXISTS idx_archived_type 
    ON archived_events(event_type);
    
CREATE INDEX IF NOT EXISTS idx_archived_timestamp
    ON archived_events(original_timestamp);

-- Индекс для поиска по времени архивации (для maintenance)
CREATE INDEX IF NOT EXISTS idx_archived_at
    ON archived_events(archived_at);

-- Комментарии к таблице и колонкам
COMMENT ON TABLE archived_events IS 'Долгосрочное хранилище архивированных событий со сжатием';
COMMENT ON COLUMN archived_events.compressed_data IS 'Сжатые данные события в формате gzip, закодированные в base64';
COMMENT ON COLUMN archived_events.original_timestamp IS 'Оригинальное время создания события (до архивации)';
COMMENT ON COLUMN archived_events.archived_at IS 'Время переноса события в архив';

-- Добавление метаданных о миграции
INSERT INTO event_store_metadata (key, value) 
VALUES ('migration_010_archived_events', jsonb_build_object(
    'version', '010',
    'description', 'Added archived_events table for long-term storage',
    'applied_at', CURRENT_TIMESTAMP
))
ON CONFLICT (key) DO UPDATE 
SET value = jsonb_set(
    event_store_metadata.value,
    '{applied_at}',
    to_jsonb(CURRENT_TIMESTAMP)
);