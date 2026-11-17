-- Run in a NEW, dedicated Neon project using Neon's SQL Editor.
-- Repeatable: does not delete previous data.
CREATE TABLE IF NOT EXISTS observations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    observed_hour TIMESTAMPTZ NOT NULL UNIQUE,
    observed_at TIMESTAMPTZ NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL,
    temperature_c DOUBLE PRECISION,
    humidity_pct DOUBLE PRECISION,
    precipitation_mm DOUBLE PRECISION,
    wind_speed_kmh DOUBLE PRECISION,
    weather_code INTEGER
);

CREATE TABLE IF NOT EXISTS forecasts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    issued_hour TIMESTAMPTZ NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL,
    target_hour TIMESTAMPTZ NOT NULL,
    horizon_hours INTEGER NOT NULL CHECK (horizon_hours > 0),
    temperature_c DOUBLE PRECISION,
    humidity_pct DOUBLE PRECISION,
    precipitation_mm DOUBLE PRECISION,
    wind_speed_kmh DOUBLE PRECISION,
    rain_probability_pct DOUBLE PRECISION,
    CONSTRAINT forecasts_issue_target_unique UNIQUE (issued_hour, target_hour)
);

CREATE INDEX IF NOT EXISTS idx_observations_hour_desc ON observations(observed_hour DESC);
CREATE INDEX IF NOT EXISTS idx_forecasts_target_desc ON forecasts(target_hour DESC);
