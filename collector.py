"""Save hourly weather estimates and original +24h forecasts into Neon.

Open-Meteo can be temporarily slow. Retry safe/transient network errors;
never replace an already-stored forecast for an hour.
"""
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg
import requests

LATITUDE = 4.36  # Approximate Seri Iskandar coordinates
LONGITUDE = 100.96
LOCAL_TZ = ZoneInfo('Asia/Kuala_Lumpur')
API_URL = 'https://api.open-meteo.com/v1/forecast'
FIELDS = ['temperature_2m', 'relative_humidity_2m', 'precipitation', 'wind_speed_10m']


def get_weather(params):
    """Retry timeouts, connection errors, and transient HTTP errors."""
    for attempt in range(1, 5):
        try:
            print(f'Open-Meteo request: attempt {attempt}/4', flush=True)
            response = requests.get(API_URL, params=params, timeout=(15, 45))
            if response.status_code == 429 or 500 <= response.status_code <= 599:
                response.raise_for_status()
            response.raise_for_status()  # Fail promptly on other 4xx errors
            return response.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            error = exc
        except requests.exceptions.HTTPError as exc:
            if exc.response is None or not (exc.response.status_code == 429 or 500 <= exc.response.status_code <= 599):
                raise
            error = exc
        if attempt == 4:
            raise RuntimeError('Open-Meteo unavailable after four attempts') from error
        delay = (3, 7, 15)[attempt - 1]
        print(f'Temporary Open-Meteo error: {type(error).__name__}. Retrying in {delay}s.', flush=True)
        time.sleep(delay)
    raise RuntimeError('Unreachable retry state')


def number(value):
    return None if value is None else float(value)


def collect():
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise RuntimeError('DATABASE_URL missing: configure the Neon repository secret.')

    params = {
        'latitude': LATITUDE,
        'longitude': LONGITUDE,
        'current': ','.join(FIELDS + ['weather_code']),
        'hourly': ','.join(FIELDS + ['precipitation_probability']),
        'timezone': 'Asia/Kuala_Lumpur',
        'forecast_days': 3,
    }
    weather = get_weather(params)

    # Use the time of the *successful* API fetch, not an old timestamp
    # from before a network retry.
    now = datetime.now(timezone.utc).astimezone(LOCAL_TZ)
    hour = now.replace(minute=0, second=0, microsecond=0)
    target = hour + timedelta(hours=24)
    current, hourly = weather['current'], weather['hourly']
    target_label = target.strftime('%Y-%m-%dT%H:%M')
    try:
        idx = hourly['time'].index(target_label)
    except ValueError as exc:
        raise RuntimeError(f'Forecast target {target_label} absent from API response') from exc

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

    # Both writes commit together. Duplicate attempts preserve the FIRST forecast.
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
