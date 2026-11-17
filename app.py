"""Streamlit dashboard; the Neon database URL stays private on the server."""
import os
import psycopg
from psycopg.rows import dict_row
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title='Seri Iskandar | Weather Intelligence', page_icon='🌦️', layout='wide')
st.markdown('''<style>
.stApp {background: #0b1220; color: #e8eef8;}
[data-testid="stMetric"] {background: #172338; border: 1px solid #2f4360; padding: 15px; border-radius: 14px;}
h1,h2,h3 {letter-spacing: -0.025em;}
</style>''', unsafe_allow_html=True)

def setting(name):
    try:
        return st.secrets[name]
    except (KeyError, FileNotFoundError):
        return os.getenv(name)

@st.cache_data(ttl=120)
def load(table):
    if table not in ('observations', 'forecasts'):
        raise ValueError('Unknown table')
    database_url = setting('DATABASE_URL')
    if not database_url:
        raise RuntimeError('DATABASE_URL missing. Add your Neon connection string in Streamlit secrets.')
    # Table name comes from a fixed allow-list, never untrusted input.
    with psycopg.connect(database_url, connect_timeout=15, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT * FROM {table} ORDER BY id DESC LIMIT 1000')
            rows = cur.fetchall()
    return pd.DataFrame(rows)

st.title('🌦️ Seri Iskandar Weather Intelligence')
st.caption('TFB2093 IoT project · Perak, Malaysia · Open-Meteo data · Neon PostgreSQL · All times displayed in MYT (UTC+8)')
st.info('Current conditions are Open-Meteo model-based estimates, not measurements from our own physical weather station.')
if st.button('🔄 Refresh saved data'):
    st.cache_data.clear()
try:
    obs, fc = load('observations'), load('forecasts')
except Exception as exc:
    st.error(f'Unable to load database. Check your private Neon DATABASE_URL and project connection.')
    st.stop()
if obs.empty:
    st.warning('No observations yet. Run the GitHub Actions collector once, then refresh.')
    st.stop()
for df in (obs, fc):
    for column in ('observed_hour','observed_at','collected_at','issued_hour','issued_at','target_hour'):
        if column in df.columns:
            df[column] = pd.to_datetime(df[column], utc=True)
obs = obs.sort_values('observed_hour')
latest = obs.iloc[-1]
metric_cols = st.columns(4)
for col, title, key, unit in zip(metric_cols,
                                ['Temperature','Humidity','Precipitation','Wind speed'],
                                ['temperature_c','humidity_pct','precipitation_mm','wind_speed_kmh'],
                                ['°C','%','mm','km/h']):
    with col:
        value = latest[key]
        st.metric(title, f'{value:.1f} {unit}' if pd.notna(value) else 'N/A')
st.caption('Latest current condition time: ' + latest['observed_at'].tz_convert('Asia/Kuala_Lumpur').strftime('%d %b %Y, %I:%M %p MYT'))

st.subheader('📈 Saved weather history')
period = st.selectbox('Display', ['All saved data', 'Last 24 hours', 'Last 72 hours'])
filtered = obs.copy()
if period != 'All saved data':
    hours = 24 if period == 'Last 24 hours' else 72
    cutoff = pd.Timestamp.now(tz='UTC') - pd.Timedelta(hours=hours)
    filtered = filtered[filtered['observed_hour'] >= cutoff]
variable = st.selectbox('Weather variable', ['temperature_c','humidity_pct','precipitation_mm','wind_speed_kmh'],
                        format_func=lambda x: {'temperature_c':'Temperature (°C)', 'humidity_pct':'Humidity (%)',
                                               'precipitation_mm':'Precipitation (mm, API current interval)',
                                               'wind_speed_kmh':'Wind speed (km/h)'}[x])
fig = go.Figure()
fig.add_trace(go.Scatter(x=filtered['observed_hour'].dt.tz_convert('Asia/Kuala_Lumpur'),
                         y=filtered[variable], mode='lines+markers', name='Saved current estimate'))
fig.update_layout(template='plotly_dark', height=350, margin=dict(l=10,r=10,t=20,b=20),
                  xaxis_title='Local time (MYT)', yaxis_title=variable)
st.plotly_chart(fig, use_container_width=True)

st.subheader('🔭 Forecast vs observed estimate (+24 hours)')
st.caption('A forecast is compared only after its target time is reached and a saved current estimate exists for that hour. Earlier predictions are never overwritten.')
if fc.empty:
    paired = pd.DataFrame()
else:
    paired = fc.merge(obs, how='inner', left_on='target_hour', right_on='observed_hour', suffixes=('_forecast','_actual'))
if paired.empty:
    st.warning('No completed +24-hour forecast comparisons yet. Keep the hourly collector running for more than 24 hours.')
else:
    paired = paired.sort_values('target_hour')
    comp = st.selectbox('Compare', ['temperature','humidity','wind_speed'],
                        format_func=lambda x: {'temperature':'Temperature','humidity':'Humidity','wind_speed':'Wind speed'}[x])
    prefix = {'temperature': 'temperature_c','humidity':'humidity_pct','wind_speed':'wind_speed_kmh'}[comp]
    a, b = prefix + '_forecast', prefix + '_actual'
    valid = paired.dropna(subset=[a,b]).copy()
    if valid.empty:
        st.warning('No matching nonempty values yet.')
    else:
        valid['absolute_error'] = (valid[a]-valid[b]).abs()
        mae = valid['absolute_error'].mean()
        rmse = (valid['absolute_error'].pow(2).mean())**0.5
        x = valid['target_hour'].dt.tz_convert('Asia/Kuala_Lumpur')
        chart = go.Figure()
        chart.add_trace(go.Scatter(x=x,y=valid[a],mode='lines+markers',name='Forecast saved 24h earlier'))
        chart.add_trace(go.Scatter(x=x,y=valid[b],mode='lines+markers',name='Observed current estimate'))
        chart.update_layout(template='plotly_dark', height=390, xaxis_title='Target hour (MYT)')
        st.plotly_chart(chart, use_container_width=True)
        c1,c2,c3 = st.columns(3)
        c1.metric('Matched samples', len(valid))
        c2.metric('Mean absolute error (MAE)', f'{mae:.2f}')
        c3.metric('Root mean squared error (RMSE)', f'{rmse:.2f}')
        st.caption('MAE and RMSE are expressed in the selected parameter’s units.')

st.subheader('🌧️ Rain watch (software indicator)')
now = pd.Timestamp.now(tz='UTC')
upcoming = fc[(fc['target_hour'] >= now) & (fc['target_hour'] < now + pd.Timedelta(hours=25))].copy() if not fc.empty else pd.DataFrame()
if upcoming.empty:
    st.info('No upcoming stored +24h rainfall forecast yet.')
else:
    upcoming = upcoming.sort_values('issued_at').drop_duplicates('target_hour', keep='last')
    risky = upcoming[(upcoming['rain_probability_pct'] >= 60) | (upcoming['precipitation_mm'] > 0.2)]
    if risky.empty:
        st.success('No stored forecasts exceed the illustrative rain-watch threshold for the upcoming 24h.')
    else:
        st.warning(f'Rain watch: {len(risky)} future hourly periods exceed the illustrative threshold (≥60% probability or >0.2 mm forecast rainfall).')
    st.caption('Software-only advisory, not an emergency warning or the optional standalone hardware bonus.')

st.subheader('📋 Evidence and downloads')
c1,c2,c3 = st.columns(3)
c1.metric('Saved observation hours', len(obs))
c2.metric('Saved forecast snapshots', len(fc))
c3.metric('Collection span', f'{(obs.iloc[-1]["observed_hour"]-obs.iloc[0]["observed_hour"]).total_seconds()/3600:.1f} hours')
st.download_button('Download observations CSV', obs.to_csv(index=False).encode(), 'observations.csv', 'text/csv')
st.download_button('Download forecast snapshots CSV', fc.to_csv(index=False).encode(), 'forecasts.csv', 'text/csv')
if not paired.empty:
    st.download_button('Download matched comparisons CSV', paired.to_csv(index=False).encode(), 'comparisons.csv', 'text/csv')
st.caption('Source: Open-Meteo Forecast API | This is an academic project. Forecast comparisons use current model-based estimates as the observation reference.')
