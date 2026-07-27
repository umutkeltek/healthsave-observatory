-- 023_moments.sql
-- Personal context annotations — illness, travel, lifestyle events that may
-- explain or confound physiological changes. Host-local and never egresses.
BEGIN;

CREATE TABLE IF NOT EXISTS moments (
    id              BIGSERIAL PRIMARY KEY,
    owner_id        UUID NOT NULL
        DEFAULT '00000000-0000-0000-0000-000000000001',
    kind            TEXT NOT NULL
        CHECK (kind IN (
            'illness', 'alcohol', 'late_meal', 'travel', 'medication_change',
            'supplement_change', 'hard_training', 'stress', 'caffeine',
            'injury', 'menstrual', 'custom'
        )),
    grade           TEXT
        CHECK (grade IS NULL OR grade IN ('mild', 'moderate', 'severe')),
    title           TEXT NOT NULL,
    note            TEXT,
    start_at        TIMESTAMPTZ NOT NULL,
    end_at          TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_moments_owner_start
    ON moments (owner_id, start_at DESC);

COMMIT;
