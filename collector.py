"""Save hourly Open-Meteo current estimates and immutable +24h forecasts in Neon."""
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg
import requests

LATITUDE = 4.36  # Approximate Seri Iskandar coordinates; document this choice.
LONGITUDE = 100.96
LOCAL_TZ = ZoneInfo('Asia/Kuala_Lumpur')
FIELDS = ['temperature_2m', 'relative_humidity_2m', 'precipitation', 'wind_speed_10m']


def collect():
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise RuntimeError('DATABASE_URL missing. Set your private Neon PostgreSQL connection string.')

    now = datetime.now(timezone.utc).astimezone(LOCAL_TZ)
    hour = now.replace(minute=0, second=0, microsecond=0)
    target = hour + timedelta(hours=24)
    params = {
        'latitude': LATITUDE,
        'longitude': LONGITUDE,
        'current': ','.join(FIELDS + ['weather_code']),
        'hourly': ','.join(FIELDS + ['precipitation_probability']),
        'timezone': 'Asia/Kuala_Lumpur',
        'forecast_days': 3,
    }
    response = requests.get('https://api.open-meteo.com/v1/forecast', params=params, timeout=30)
    response.raise_for_status()
    weather = response.json()
    current, hourly = weather['current'], weather['hourly']
    target_label = target.strftime('%Y-%m-%dT%H:%M')
    try:
        idx = hourly['time'].index(target_label)
    except ValueError as exc:
        raise RuntimeError(f'Forecast target {target_label} missing in Open-Meteo response') from exc

    def number(value):
        return None if value is None else float(value)

    observation = (
        hour, datetime.fromisoformat(current['time']).replace(tzinfo=LOCAL_TZ), now,
        number(current.get('temperature_2m')),
        number(current.get('relative_humidity_2m')),
        number(current.get('precipitation')),
        number(current.get('wind_speed_10m')),
        current.get('weather_code'),
    )
    forecast = (
        hour, now, target, 24,
        number(hourly['temperature_2m'][idx]),
        number(hourly['relative_humidity_2m'][idx]),
        number(hourly['precipitation'][idx]),
        number(hourly['wind_speed_10m'][idx]),
        number(hourly['precipitation_probability'][idx]),
    )
    # Both INSERTs commit together. Never overwrite the first forecast for an hour.
    with psycopg.connect(database_url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO observations
                (observed_hour, observed_at, collected_at, temperature_c,
                 humidity_pct, precipitation_mm, wind_speed_kmh, weather_code)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (observed_hour) DO NOTHING
            ''', observation)
            cur.execute('''
                INSERT INTO forecasts
                (issued_hour, issued_at, target_hour, horizon_hours,
                 temperature_c, humidity_pct, precipitation_mm, wind_speed_kmh,
                 rain_probability_pct)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (issued_hour, target_hour) DO NOTHING
            ''', forecast)
    print('Saved/verified observation hour:', hour.isoformat())
    print('Saved/verified +24h forecast target:', target.isoformat())


if __name__ == '__main__':
    collect()
