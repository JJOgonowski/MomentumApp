import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import timedelta, datetime, date
import json
import os
import re
import copy
import base64
import requests
from pathlib import Path

# --- 1. FUNKCJE POMOCNICZE ---

# Custom JSON encoder dla numpy types i date objects
class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        # Numpy types
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        # Datetime types
        elif isinstance(obj, (pd.Timestamp, datetime)):
            return obj.isoformat()
        elif isinstance(obj, date):
            return obj.isoformat()
        else:
            try:
                return super().default(obj)
            except TypeError:
                # Fallback - zamień na string
                return str(obj)

# Scenariusze - zarządzanie plikami
SCENARIOS_DIR = Path("scenarios")
SCENARIOS_DIR.mkdir(exist_ok=True)

REQUIRED_PARAMS = ['assets', 'target_currency', 'strategy_type', 'cap_start', 'cap_monthly',
                   'start_date', 'vol_lookback', 'slippage_pct', 'tax_enabled']

# ---------------------------------------------------------------------------
# GitHub Storage Backend
# ---------------------------------------------------------------------------
def _gh_enabled() -> bool:
    """Czy skonfigurowany GitHub jako backend?"""
    try:
        return "github" in st.secrets and "token" in st.secrets["github"]
    except Exception:
        return False

def _gh_headers() -> dict:
    return {
        "Authorization": f"Bearer {st.secrets['github']['token']}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def _gh_base_url() -> str:
    owner = st.secrets["github"]["owner"]
    repo  = st.secrets["github"]["repo"]
    return f"https://api.github.com/repos/{owner}/{repo}/contents/scenarios"

def _gh_branch() -> str:
    return st.secrets["github"].get("branch", "main")

def _gh_get_file_info(filename: str) -> dict | None:
    """Pobierz SHA i zawartość pliku z GitHub (None jeśli nie istnieje)"""
    r = requests.get(
        f"{_gh_base_url()}/{filename}",
        headers=_gh_headers(),
        params={"ref": _gh_branch()},
        timeout=10
    )
    return r.json() if r.status_code == 200 else None

def _gh_list_files() -> list[str]:
    """Zwróć listę plików .json w katalogu scenarios na GitHub"""
    r = requests.get(
        _gh_base_url(),
        headers=_gh_headers(),
        params={"ref": _gh_branch()},
        timeout=10
    )
    if r.status_code == 200:
        return sorted(
            f["name"][:-5] for f in r.json()
            if isinstance(f, dict) and f.get("name", "").endswith(".json")
        )
    if r.status_code == 404:
        return []   # katalog scenarios jeszcze nie istnieje
    r.raise_for_status()
    return []

def _gh_write_file(filename: str, content_str: str) -> tuple[bool, str | None]:
    """Utwórz lub nadpisz plik na GitHub. Zwraca (ok, error_msg)."""
    encoded = base64.b64encode(content_str.encode("utf-8")).decode()
    existing = _gh_get_file_info(filename)
    payload: dict = {
        "message": f"scenario: update {filename}",
        "content": encoded,
        "branch": _gh_branch(),
    }
    if existing and "sha" in existing:
        payload["sha"] = existing["sha"]
    r = requests.put(
        f"{_gh_base_url()}/{filename}",
        headers=_gh_headers(),
        json=payload,
        timeout=15
    )
    if r.status_code in (200, 201):
        return True, None
    try:
        details = r.json()
        message = details.get("message")
    except Exception:
        message = r.text
    return False, f"HTTP {r.status_code}: {message}"

def _gh_read_file(filename: str) -> str | None:
    """Pobierz zawartość pliku z GitHub jako string (None jeśli błąd)"""
    info = _gh_get_file_info(filename)
    if not info or "content" not in info:
        return None
    return base64.b64decode(info["content"]).decode("utf-8")

def _gh_delete_file(filename: str) -> bool:
    """Usuń plik z GitHub. Zwraca True przy sukcesie."""
    info = _gh_get_file_info(filename)
    if not info or "sha" not in info:
        return False
    r = requests.delete(
        f"{_gh_base_url()}/{filename}",
        headers=_gh_headers(),
        json={"message": f"scenario: delete {filename}", "sha": info["sha"], "branch": _gh_branch()},
        timeout=10
    )
    return r.status_code == 200

# ---------------------------------------------------------------------------
# Wspólne narzędzia
# ---------------------------------------------------------------------------
def sanitize_filename(name: str) -> str:
    """Zamień niebezpieczne znaki w nazwie pliku na podkreślenia"""
    return re.sub(r'[^\w\s\-]', '_', name).strip()

def validate_scenario(scenario: dict) -> bool:
    """Sprawdź czy scenariusz ma wszystkie wymagane pola"""
    if not isinstance(scenario, dict):
        return False
    if 'df' not in scenario or 'params' not in scenario or 'timestamp' not in scenario:
        return False
    return all(k in scenario['params'] for k in REQUIRED_PARAMS)

def _serialize_scenario(scenario_data: dict) -> str:
    """Zamień scenariusz (z DataFrame) na JSON string gotowy do zapisu"""
    scenario_copy = copy.deepcopy(scenario_data)
    df_to_save = scenario_data['df'].copy()
    df_to_save.index = df_to_save.index.astype(str)
    for col in df_to_save.columns:
        if df_to_save[col].dtype == 'object':
            df_to_save[col] = df_to_save[col].where(df_to_save[col].notna(), other=None)
    scenario_copy['df'] = df_to_save.to_dict('split')
    scenario_copy['timestamp'] = scenario_data['timestamp'].isoformat()
    return json.dumps(scenario_copy, ensure_ascii=False, indent=2, cls=NumpyEncoder)

def _deserialize_scenario(text: str, source_name: str) -> dict | None:
    """Zamień JSON string z powrotem na scenariusz ze słownikiem DataFrame"""
    try:
        scenario = json.loads(text)
    except json.JSONDecodeError as je:
        st.error(f"❌ Błąd parsowania JSON '{source_name}': {je}")
        return None
    try:
        df_split = scenario.get('df')
        if not df_split or 'data' not in df_split:
            raise ValueError("Struktura DataFrame uszkodzona")
        scenario['df'] = pd.DataFrame(
            df_split['data'], index=df_split['index'], columns=df_split['columns']
        )
        scenario['df'].index = pd.to_datetime(scenario['df'].index)
    except Exception as e:
        st.error(f"❌ Błąd rekonstrukcji DataFrame '{source_name}': {e}")
        return None
    try:
        scenario['timestamp'] = pd.Timestamp(scenario['timestamp'])
    except Exception:
        scenario['timestamp'] = pd.Timestamp.now()
    if not validate_scenario(scenario):
        st.error("❌ Scenariusz ma brakujące lub uszkodzone pola. Zapisz go ponownie.")
        return None
    return scenario

# ---------------------------------------------------------------------------
# Publiczne API zapisu/odczytu — auto-select GitHub lub lokalny dysk
# ---------------------------------------------------------------------------
def save_scenario_to_file(name: str, scenario_data: dict) -> bool:
    """Zapisz scenariusz (GitHub gdy skonfigurowany, inaczej lokalnie)"""
    try:
        safe_name = sanitize_filename(name)
        filename = f"{safe_name}.json"
        content  = _serialize_scenario(scenario_data)
        if _gh_enabled():
            ok, err = _gh_write_file(filename, content)
            if ok:
                list_scenarios.clear()
            else:
                st.error(f"❌ Błąd zapisu na GitHub — {err}")
            return ok
        else:
            filepath = SCENARIOS_DIR / filename
            filepath.write_text(content, encoding="utf-8")
            list_scenarios.clear()
            return True
    except Exception as e:
        st.error(f"❌ Błąd przy zapisie: {e}")
        return False

def load_scenario_from_file(name: str) -> dict | None:
    """Wczytaj scenariusz (GitHub gdy skonfigurowany, inaczej lokalnie)"""
    try:
        filename = f"{name}.json"
        if _gh_enabled():
            text = _gh_read_file(filename)
            if text is None:
                st.warning(f"⚠️ Scenariusz '{name}' nie istnieje na GitHub")
                return None
        else:
            filepath = SCENARIOS_DIR / filename
            if not filepath.exists():
                st.warning(f"⚠️ Plik scenariusza '{name}' nie istnieje")
                return None
            text = filepath.read_text(encoding="utf-8")
        return _deserialize_scenario(text, name)
    except Exception as e:
        st.error(f"❌ Błąd przy wczytaniu: {e}")
        return None

@st.cache_data(ttl=5)
def list_scenarios() -> list:
    """Zwróć posortowaną listę zapisanych scenariuszy (GitHub lub lokalnie)"""
    try:
        if _gh_enabled():
            return _gh_list_files()
        if not SCENARIOS_DIR.exists():
            return []
        return sorted(f.stem for f in SCENARIOS_DIR.glob("*.json"))
    except Exception:
        return []

def delete_scenario_file(name: str) -> bool:
    """Usuń scenariusz (GitHub lub lokalnie)"""
    try:
        filename = f"{name}.json"
        if _gh_enabled():
            ok = _gh_delete_file(filename)
            if ok:
                list_scenarios.clear()
            return ok
        else:
            filepath = SCENARIOS_DIR / filename
            if filepath.exists():
                filepath.unlink()
                list_scenarios.clear()
                return True
            return False
    except Exception as e:
        st.error(f"❌ Błąd przy usuwaniu: {e}")
        return False

@st.cache_data(ttl=86400)
def validate_ticker(symbol):
    if not symbol or len(symbol) < 2: return None
    try:
        t = yf.Ticker(symbol)
        info = t.fast_info
        return {"name": t.info.get('shortName', symbol), "currency": info.get('currency', '???')}
    except: return False

def calculate_drawdown(series):
    if series.empty or len(series) < 2: return 0
    rolling_max = series.cummax()
    drawdowns = (series - rolling_max) / rolling_max
    return drawdowns.min() * 100

def calculate_cagr(start_value, end_value, years):
    """Calculate Compound Annual Growth Rate"""
    if start_value <= 0 or end_value <= 0 or years <= 0: return 0
    # CAGR = (Ending Value / Beginning Value) ^ (1 / Number of Years) - 1
    cagr = (pow(end_value / start_value, 1 / years) - 1) * 100
    return cagr

def calculate_sharpe_ratio(returns_series, risk_free_rate=0.05, periods_per_year=12):
    """Calculate Sharpe Ratio (annualized).
    returns_series: monthly (or daily) returns as decimals
    periods_per_year: 12 for monthly, 252 for daily
    risk_free_rate: annual risk-free rate (default 5%)
    """
    if len(returns_series) < 2: return 0
    n_years = len(returns_series) / periods_per_year
    # Geometryczna roczna stopa zwrotu (CAGR z serii zwrotów)
    annualized_return = (1 + returns_series).prod() ** (1 / n_years) - 1
    # Roczna zmienność
    annual_volatility = returns_series.std() * np.sqrt(periods_per_year)
    if annual_volatility == 0: return 0
    return (annualized_return - risk_free_rate) / annual_volatility

def calculate_sortino_ratio(returns_series, risk_free_rate=0.05, periods_per_year=12):
    """Calculate Sortino Ratio (annualized, standard semi-deviation formula).
    returns_series: monthly (or daily) returns as decimals
    periods_per_year: 12 for monthly, 252 for daily
    risk_free_rate: annual risk-free rate (default 5%)
    """
    if len(returns_series) < 2: return 0
    n_years = len(returns_series) / periods_per_year
    # Geometryczna roczna stopa zwrotu
    annualized_return = (1 + returns_series).prod() ** (1 / n_years) - 1
    # Semi-dewiacja (standard Sortino): sqrt(mean(min(r, 0)^2)) * sqrt(periods)
    # Uwzględnia WSZYSTKIE okresy (nie tylko ujemne), co daje poprawną normalizację
    downside_sq = np.minimum(returns_series, 0) ** 2
    downside_volatility = np.sqrt(downside_sq.mean()) * np.sqrt(periods_per_year)
    if downside_volatility == 0: return 0
    return (annualized_return - risk_free_rate) / downside_volatility

@st.cache_data(ttl=3600)
def get_historical_data(tickers, start_date, vol_lookback=20):
    tickers = [t.strip().upper() for t in tickers]
    all_syms = list(set(tickers + ["PLN=X", "EURPLN=X", "USDPLN=X"]))
    return yf.download(all_syms, start=pd.to_datetime(start_date) - timedelta(days=450), auto_adjust=True, progress=False)

# --- 2. PANEL BOCZNY ---

st.set_page_config(page_title="Momentum Pro - Expert Dashboard", layout="wide")
st.title("🛡️ Momentum Pro: System Inwestycyjny")

with st.sidebar:
    st.header("⚙️ Parametry Portfela")

    # --- RUN BUTTON AT TOP ---
    run_simulation = st.button("🚀 URUCHOM SYMULACJĘ", use_container_width=True, type="primary")

    st.write("---")
    target_currency = st.selectbox("Waluta docelowa portfela:", ["PLN", "USD", "EUR"])
    strategy_type = st.selectbox("Model Momentum:", ["Weighted Scaled Risk Parity", "Simple Momentum (3/6/12M)", "Momentum 12M (n-1, pomiń ostatni miesiąc)"])
    
    st.write("---")
    st.subheader("🚀 Aktywa")
    asset_inputs, defaults = [], ["QQQ", "SPY", "GLD", "IB01.L"]
    for i in range(4):
        label = "Safe Haven" if i == 3 else f"Risk Asset {i+1}"
        ticker = st.text_input(f"{label}:", value=defaults[i], key=f"t_in_{i}").strip().upper()
        if len(ticker) >= 2:
            check = validate_ticker(ticker)
            if check: st.markdown(f"✅ **{check['currency']}** | {check['name']}")
        asset_inputs.append(ticker)

    st.write("---")
    cap_start_pln = st.number_input("Kapitał START (PLN):", value=10000)
    cap_monthly_pln = st.number_input("Dopłata miesięczna (PLN):", value=1000)
    start_date = st.date_input("Data START:", value=datetime(2021, 1, 1))
    vol_lookback = st.slider("Okres zmienności dla wag (dni):", 10, 60, 20)
    
    with st.expander("💰 Koszty Transakcji", expanded=False):
        slippage_pct = st.number_input("Slippage/Prowizja (% wartości):", value=0.0, min_value=0.0, max_value=5.0, step=0.01)
    
    with st.expander("📋 Podatki", expanded=False):
        account_type = st.selectbox("Typ konta:", ["Standardowy (19% PIT)", "IKE (0%)", "IKZE (10%)"], key="account_type_select")
    tax_enabled = account_type.startswith("Standardowy")
    tax_rate = 0.19 if tax_enabled else (0.10 if "IKZE" in account_type else 0.0)
    
    st.write("---")
    st.subheader("💾 Scenariusze")
    
    # Pobierz listę dostępnych scenariuszy
    available_scenarios = list_scenarios()
    # Inicjalizacja load_btn przed tabami
    load_btn = False
    
    scenario_tab1, scenario_tab2 = st.tabs(["💾 Zapisz", "📂 Wczytaj"])
    
    with scenario_tab1:
        save_name = st.text_input("Nazwa scenariusza (opcjonalne):", placeholder="np. Agresywny 2024", key="scenario_save_input")
        if save_name:
            safe_save_name = sanitize_filename(save_name)
            if (SCENARIOS_DIR / f"{safe_save_name}.json").exists():
                st.warning(f"⚠️ Scenariusz '{safe_save_name}' już istnieje — zostanie nadpisany")
            st.session_state['scenario_to_save'] = save_name
            st.info(f"📝 Scenariusz '{safe_save_name}' zostanie zapisany po URUCHOM SYMULACJĘ")
        else:
            # Wyczyść flagę jeśli pole jest puste
            if 'scenario_to_save' in st.session_state:
                del st.session_state['scenario_to_save']
    
    with scenario_tab2:
        if available_scenarios:
            load_name = st.selectbox("Wybierz scenariusz:", available_scenarios, key="scenario_load_select")
            
            col1, col2 = st.columns(2)
            with col1:
                load_btn = st.button("📂 Wczytaj Scenariusz", key="load_scenario_btn")
                if load_btn:
                    st.session_state['scenario_to_load'] = load_name
            with col2:
                if st.button("🗑️ Usuń Scenariusz", key="delete_scenario_btn"):
                    if delete_scenario_file(load_name):
                        st.success(f"✅ Scenariusz '{load_name}' usunięty!")
                        st.rerun()
        else:
            st.info("📭 Brak zapisanych scenariuszy")

    # --- Podsumowanie parametrów + drugi przycisk Run na dole ---
    st.write("---")
    valid_risk = [a for a in asset_inputs[:3] if a]
    safe = asset_inputs[3] if len(asset_inputs) > 3 else "?"
    st.caption(
        f"**{' / '.join(valid_risk)} → {safe}** | {target_currency} | "
        f"{cap_start_pln:,.0f} + {cap_monthly_pln:,.0f}/m | "
        f"{start_date} | {strategy_type[:18]}…"
    )
    st.button("🚀 URUCHOM SYMULACJĘ", use_container_width=True, type="primary", key="run_btn_bottom")

# --- 3. LOGIKA WCZYTYWANIA SCENARIUSZA ---

# Połącz oba przyciski Run (góra i dół sidebara)
run_simulation = run_simulation or st.session_state.get("run_btn_bottom", False)

loaded_scenario = None
# Użyj lokalnej zmiennej load_btn (zwraca True tylko w tej jednej iteracji gdy kliknięto)
if st.session_state.get('scenario_to_load') and load_btn:
    scenario_name = st.session_state.get('scenario_to_load')
    loaded_scenario = load_scenario_from_file(scenario_name)
    if loaded_scenario:
        st.success(f"✅ Scenariusz '{scenario_name}' wczytany!")
        run_simulation = True

# --- Banner aktywnego scenariusza ---
active_scen = st.session_state.get('scenario_to_load')
if active_scen and not run_simulation:
    st.info(f"📂 Aktywny scenariusz: **{active_scen}** — kliknij 🚀 URUCHOM SYMULACJĘ aby wyświetlić wyniki")

# --- 4. SILNIK SYMULACJI ---

if run_simulation or loaded_scenario:
    
    # Jeśli wczytujemy scenariusz, użyj zapisanych danych
    if loaded_scenario:
        df = loaded_scenario['df']
        asset_inputs = loaded_scenario['params']['assets']
        target_currency = loaded_scenario['params']['target_currency']
        strategy_type = loaded_scenario['params']['strategy_type']
        cap_start_pln = loaded_scenario['params']['cap_start']
        cap_monthly_pln = loaded_scenario['params']['cap_monthly']
        start_date = datetime.strptime(loaded_scenario['params']['start_date'], '%Y-%m-%d').date()
        vol_lookback = loaded_scenario['params']['vol_lookback']
        slippage_pct = loaded_scenario['params']['slippage_pct']
        tax_enabled = loaded_scenario['params']['tax_enabled']
        account_type = loaded_scenario['params'].get('account_type', 'Standardowy (19% PIT)' if tax_enabled else 'IKE (0%)')
        tax_rate = 0.19 if tax_enabled else (0.10 if 'IKZE' in account_type else 0.0)
        
        # Przywróć zmienne stanu z zapisanego scenariusza
        prices = None
        kurs_target_pln = None
        kurs_target_pln_n1 = None
        fx_map = None
        portfolio_lots = {}
        pit_total_realized_pln = loaded_scenario['params'].get('pit_total_realized_pln', 0)
        total_invested_target = loaded_scenario['params'].get('total_invested_target', 
            cap_start_pln + cap_monthly_pln * (len(loaded_scenario['df']) - 1))
        pit_roczny_pln = loaded_scenario['params'].get('pit_roczny_pln', {})
        # Konwertuj klucze pit_roczny_pln z powrotem na int (JSON zapisuje jako string)
        pit_roczny_pln = {int(k): v for k, v in pit_roczny_pln.items()}
        val_start_year_target = loaded_scenario['params'].get('val_start_year_target', {})
        val_start_year_target = {int(k): v for k, v in val_start_year_target.items()}
        # Przywróć szczegóły podatkowe (nowe pola, backward-compatible)
        yearly_gains = loaded_scenario['params'].get('yearly_gains', {})
        yearly_gains = {int(k): v for k, v in yearly_gains.items()}
        yearly_losses = loaded_scenario['params'].get('yearly_losses', {})
        yearly_losses = {int(k): v for k, v in yearly_losses.items()}
        loss_carry_forward = loaded_scenario['params'].get('loss_carry_forward', 0)
        per_asset_pl = loaded_scenario['params'].get('per_asset_pl', {a: {'gains': 0, 'losses': 0} for a in asset_inputs})
        tax_breakdown = loaded_scenario['params'].get('tax_breakdown', {})
        tax_breakdown = {int(k): v for k, v in tax_breakdown.items()} if tax_breakdown else {}
        
        status = None
        st.success("✅ Scenariusz załadowany! Wyświetlam zapisane wyniki...")
    else:
        # Normalna symulacja - pobierz dane i uruchom
        with st.status("Przetwarzanie danych rynkowych...", expanded=True) as status:
            data = get_historical_data(asset_inputs, start_date, vol_lookback)
            prices = data['Close'].ffill()
        
            pln_series = pd.Series(1.0, index=prices.index)
            fx_map = {"PLN": pln_series, "USD": prices["PLN=X"], "EUR": prices["EURPLN=X"]}
            kurs_target_pln = fx_map[target_currency]
            kurs_target_pln_n1 = kurs_target_pln.shift(1).ffill()
            
            volatility = np.log(prices / prices.shift(1)).rolling(window=vol_lookback).std() * np.sqrt(252)
            m_prices = prices.resample('BMS').first()
            m_sim = m_prices[m_prices.index >= pd.to_datetime(start_date)]
            
            # --- WALIDACJA DANYCH ---
            if len(m_sim) < 13:
                st.warning(f"⚠️ **Zbyt mało danych do backtestu!** Dostępne &{len(m_sim)} miesięcy, potrzebne ≥13 miesięcy dla kalkulacji 12M momentum.")
        
            portfolio_lots = {a: [] for a in asset_inputs}
            bench_shares = {a: 0.0 for a in asset_inputs}
            total_invested_target = 0 # Śledzenie sumy wpłat w walucie docelowej
            
            historia_log, pit_total_realized_pln = [], 0
            pit_roczny_pln = {}
            val_start_year_target = {}
            # Szczegółowe śledzenie zysków i strat
            yearly_gains = {}   # {rok: suma zysków zrealizowanych (PLN)}
            yearly_losses = {}  # {rok: suma strat zrealizowanych (PLN, wartość bezwzgl.)}
            per_asset_pl = {a: {'gains': 0.0, 'losses': 0.0} for a in asset_inputs}

            for i in range(len(m_sim)):
                dt = m_sim.index[i]
                ts = pd.Timestamp(dt)
                rate_t_pln = kurs_target_pln.asof(ts)
                rate_t_pln_n1 = kurs_target_pln_n1.asof(ts)
                
                wplata_pln = cap_start_pln if i == 0 else cap_monthly_pln
                wplata_target = wplata_pln / rate_t_pln
                total_invested_target += wplata_target
                realized_gain_month = 0.0  # zyski zrealizowane w tym miesiącu (PLN)
                realized_loss_month = 0.0  # straty zrealizowane w tym miesiącu (PLN, wartość bezwzgl.)

                # Momentum Logic
                idx_full = m_prices.index.get_loc(dt)
                scores = {}
                if strategy_type == "Weighted Scaled Risk Parity":
                    for a in asset_inputs[:3]:
                        r = ((m_prices[a].iloc[idx_full]/m_prices[a].iloc[idx_full-1]-1)*12 + 
                             (m_prices[a].iloc[idx_full]/m_prices[a].iloc[idx_full-3]-1)*4 + 
                             (m_prices[a].iloc[idx_full]/m_prices[a].iloc[idx_full-6]-1)*2 + 
                             (m_prices[a].iloc[idx_full]/m_prices[a].iloc[idx_full-12]-1))
                        v = volatility[a].asof(ts)
                        scores[a] = r/v if r>0 and v>0 else 0
                elif strategy_type == "Simple Momentum (3/6/12M)":
                    for a in asset_inputs[:3]:
                        m = ((m_prices[a].iloc[idx_full]/m_prices[a].iloc[idx_full-3]-1) + 
                             (m_prices[a].iloc[idx_full]/m_prices[a].iloc[idx_full-6]-1) + 
                             (m_prices[a].iloc[idx_full]/m_prices[a].iloc[idx_full-12]-1))/3
                        scores[a] = m if m > 0 else 0
                else:  # Momentum 12M (n-1)
                    # Sygnał: zwrot z t-13 do t-1 (pomiń ostatni miesiąc)
                    # Unika efektu short-term reversal (Jegadeesh & Titman)
                    for a in asset_inputs[:3]:
                        if idx_full >= 13:
                            m = m_prices[a].iloc[idx_full-1] / m_prices[a].iloc[idx_full-13] - 1
                        else:
                            m = 0
                        scores[a] = m if m > 0 else 0

                total_score = sum(scores.values())
                target_weights = {a: 0.0 for a in asset_inputs}
                if total_score > 0:
                    for a in scores: target_weights[a] = scores[a] / total_score
                else:
                    target_weights[asset_inputs[3]] = 1.0

                current_equity_target = sum(sum(l[0] for l in portfolio_lots[a]) * m_sim[a].iloc[i] for a in asset_inputs) + wplata_target
                if ts.year not in val_start_year_target:
                    val_start_year_target[ts.year] = current_equity_target - wplata_target if i > 0 else wplata_target

                cash_pool_target = wplata_target
                for a in asset_inputs:
                    curr_p, target_v = m_sim[a].iloc[i], current_equity_target * target_weights[a]
                    actual_v = sum(l[0] for l in portfolio_lots[a]) * curr_p
                    if actual_v > target_v + 0.01:
                        qty_to_sell = (actual_v - target_v) / curr_p
                        while qty_to_sell > 1e-7 and portfolio_lots[a]:
                            l_qty, l_p_t, l_r_n1 = portfolio_lots[a][0]
                            s_q = min(qty_to_sell, l_qty)
                            # Apply slippage costs on sell proceeds
                            sell_proceeds_gross = s_q * curr_p * rate_t_pln_n1
                            sell_proceeds_net = sell_proceeds_gross * (1 - slippage_pct / 100)
                            profit_pln = sell_proceeds_net - (s_q * l_p_t * l_r_n1)
                            # Śledzenie zysków i strat per-asset (do nettingu rocznego)
                            if profit_pln > 0:
                                realized_gain_month += profit_pln
                                per_asset_pl[a]['gains'] += profit_pln
                            else:
                                realized_loss_month += abs(profit_pln)
                                per_asset_pl[a]['losses'] += abs(profit_pln)
                            portfolio_lots[a][0][0] -= s_q
                            if portfolio_lots[a][0][0] <= 1e-7: portfolio_lots[a].pop(0)
                            qty_to_sell -= s_q
                        # Cash received after slippage
                        cash_pool_target += (actual_v - target_v) * (1 - slippage_pct / 100)
                
                yearly_gains[ts.year] = yearly_gains.get(ts.year, 0) + realized_gain_month
                yearly_losses[ts.year] = yearly_losses.get(ts.year, 0) + realized_loss_month

                for a in asset_inputs:
                    curr_p, target_v = m_sim[a].iloc[i], current_equity_target * target_weights[a]
                    actual_v = sum(l[0] for l in portfolio_lots[a]) * curr_p
                    if actual_v < target_v - 0.01:
                        buy_val = min(target_v - actual_v, cash_pool_target)
                        if buy_val > 0.01:
                            # Apply slippage costs on buy (increase effective cost)
                            buy_val_with_slippage = buy_val / (1 - slippage_pct / 100) if slippage_pct > 0 else buy_val
                            portfolio_lots[a].append([buy_val/curr_p, curr_p, rate_t_pln_n1])
                            cash_pool_target -= buy_val_with_slippage

                row = {'Data': dt.date(), 'Rok': ts.year, 'Portfel': round(current_equity_target, 2),
                       'Zysk Real. (PLN)': round(realized_gain_month, 2),
                       'Strata Real. (PLN)': round(realized_loss_month, 2)}
                for a in asset_inputs:
                    row[f'Score {a}'] = scores.get(a, 0)
                    row[f'{a} %'] = f"{target_weights[a]*100:.1f}%"
                    bench_shares[a] += wplata_target / m_sim[a].iloc[i]
                    row[f'Bench {a}'] = round(bench_shares[a] * m_sim[a].iloc[i], 2)
                historia_log.append(row)

            df = pd.DataFrame(historia_log).set_index('Data')
            
            # --- OBLICZENIE PODATKU Z NETTINGIEM ROCZNYM I CARRY-FORWARD ---
            loss_carry_forward = 0.0  # skumulowana strata do przeniesienia (max 5 lat)
            loss_carry_years = []     # [(rok_powstania, kwota_pierwotna, kwota_pozostała)]
            tax_breakdown = {}        # {rok: {gains, losses, net, carry_used, carry_remaining, tax}}
            pit_roczny_pln = {}
            pit_total_realized_pln = 0
            
            if tax_rate > 0:  # Standardowy lub IKZE
                for year in sorted(yearly_gains.keys() | yearly_losses.keys()):
                    g = yearly_gains.get(year, 0)
                    l = yearly_losses.get(year, 0)
                    net_gain = g - l  # netting zysków i strat w roku

                    # --- ODLICZENIE STRAT PRZENIESIONYCH (carry-forward) ---
                    # Przepisy PIT-38: max 50% kwoty PIERWOTNEJ straty w każdym z 5 kolejnych lat
                    # Format loту: (rok_powstania, kwota_pierwotna, kwota_pozostała)
                    carry_used = 0.0
                    if net_gain > 0 and loss_carry_years:
                        new_carry = []
                        for (cy, orig, remaining) in loss_carry_years:
                            if year - cy > 5:
                                continue  # strata wygasła po 5 latach
                            if carry_used < net_gain:
                                # Limit: max 50% kwoty pierwotnej straty w jednym roku podatkowym
                                annual_limit = orig * 0.50
                                usable = min(remaining, annual_limit, net_gain - carry_used)
                                carry_used += usable
                                new_remaining = remaining - usable
                            else:
                                new_remaining = remaining
                            if new_remaining > 0.01:
                                new_carry.append((cy, orig, new_remaining))
                        loss_carry_years = new_carry

                    taxable = max(0, net_gain - carry_used)
                    tax_year = taxable * tax_rate

                    if net_gain < 0:
                        # Nowa strata → dodaj do carry-forward (pierwotna kwota = kwota pozostała)
                        loss_carry_years.append((year, abs(net_gain), abs(net_gain)))

                    loss_carry_forward = sum(remaining for (_, _, remaining) in loss_carry_years)
                    
                    pit_roczny_pln[year] = round(tax_year, 2)
                    pit_total_realized_pln += tax_year
                    
                    tax_breakdown[year] = {
                        'gains': round(g, 2),
                        'losses': round(l, 2),
                        'net': round(net_gain, 2),
                        'carry_used': round(carry_used, 2),
                        'taxable': round(taxable, 2),
                        'tax': round(tax_year, 2),
                        'carry_remaining': round(loss_carry_forward, 2)
                    }
            
            # Obliczenie contribution każdego aktywa co miesiąc
            for a in asset_inputs:
                # Zwrot każdego aktywa (%)
                df[f'Return {a} %'] = df[f'Bench {a}'].pct_change() * 100
                
                # Zmiana wartości benchmarku
                df[f'Change {a}'] = df[f'Bench {a}'].diff().fillna(0)
                
                # Wkład w portfel (%)
                waga_col = f'{a} %'
                wagi_numeric = df[waga_col].str.rstrip('%').astype(float) / 100
                df[f'Contribution {a} %'] = df[f'Return {a} %'] * wagi_numeric
            
            # Save scenario if requested
            scenario_name = st.session_state.get("scenario_to_save", "").strip()
            if scenario_name:
                # Tworzymy obiekt scenariusza z parametrami i wynikami
                scenario_data = {
                    'params': {
                        'assets': asset_inputs,
                        'target_currency': target_currency,
                        'strategy_type': strategy_type,
                        'cap_start': cap_start_pln,
                        'cap_monthly': cap_monthly_pln,
                        'start_date': str(start_date),
                        'vol_lookback': vol_lookback,
                        'slippage_pct': slippage_pct,
                        'tax_enabled': tax_enabled,
                        'account_type': account_type,
                        'tax_rate': tax_rate,
                        # Zapisz dane stanu potrzebne do odtworzenia wyników
                        'pit_total_realized_pln': pit_total_realized_pln,
                        'total_invested_target': total_invested_target,
                        'pit_roczny_pln': pit_roczny_pln,
                        'val_start_year_target': val_start_year_target,
                        # Szczegóły podatkowe
                        'yearly_gains': yearly_gains,
                        'yearly_losses': yearly_losses,
                        'loss_carry_forward': loss_carry_forward,
                        'per_asset_pl': per_asset_pl,
                        'tax_breakdown': tax_breakdown,
                    },
                    'df': df.copy(),
                    'timestamp': pd.Timestamp.now()
                }
                
                # Zapisz do pliku
                if save_scenario_to_file(scenario_name, scenario_data):
                    safe_name = sanitize_filename(scenario_name)
                    st.success(f"✅ Scenariusz '{safe_name}' zapisany!")
                    list_scenarios.clear()  # Wyczyść cache po zapisie
                    # Wyczyść flagę zapisu - bezpieczne bo to nie jest klucz widgetu
                    if 'scenario_to_save' in st.session_state:
                        del st.session_state['scenario_to_save']
            
            status.update(label="✅ Symulacja zakończona!", state="complete")

    # --- 5. PREZENTACJA WYNIKÓW ---
    # Kod poniżej wykonuje się dla obu przypadków: nowej symulacji i wczytanego scenariusza

    last_ts = pd.Timestamp(df.index[-1])
    
    if loaded_scenario:
        # total_invested_target, pit_total_realized_pln itp. już przywrócone powyżej
        # Estymacja niezrealizowanego zysku z zapisanych danych
        unreal_pln = max(0, (df['Portfel'].iloc[-1] - total_invested_target)) if total_invested_target > 0 else 0
        # Odejmij już zrealizowane zyski (netto) aby nie liczyć podwójnie
        total_realized_net = sum(yearly_gains.get(y, 0) - yearly_losses.get(y, 0) for y in yearly_gains) if yearly_gains else 0
        unreal_pln = max(0, unreal_pln - max(0, total_realized_net))
        kurs_target_pln_val = 1.0
    else:
        # Dla nowej symulacji są dostępne zmienne
        last_rate = kurs_target_pln.asof(last_ts)
        kurs_target_pln_val = last_rate
        unreal_pln = sum(max(0, (l[0]*prices[a].asof(last_ts)*kurs_target_pln_n1.asof(last_ts) - l[0]*l[1]*l[2])) for a in asset_inputs for l in portfolio_lots[a]) if portfolio_lots else 0
    
    # Niezrealizowany podatek uwzględnia carry-forward
    unreal_taxable = max(0, unreal_pln - loss_carry_forward) if tax_rate > 0 else 0
    unreal_tax_pln = unreal_taxable * tax_rate
    total_tax_pln = unreal_tax_pln + (pit_total_realized_pln if tax_rate > 0 else 0)
    
    portfel_brutto = df['Portfel'].iloc[-1]
    portfel_netto = portfel_brutto  # Podatki płacone z osobnego konta - nie odejmujemy od portfela
    portfel_zysk_nom = portfel_netto - total_invested_target
    portfel_zysk_pct = (portfel_zysk_nom / total_invested_target) * 100
    portfel_mdd = calculate_drawdown(df['Portfel'])
    
    # Tax info: podatki wyświetlamy informacyjnie (nie odejmowane od portfela)
    brutto_return = portfel_brutto - total_invested_target
    tax_drag_pct = (total_tax_pln / kurs_target_pln_val / brutto_return * 100) if brutto_return > 0 else 0
    
    # Risk Metrics for Portfolio
    portfel_months = len(df)  # Liczba měsięcy z backtesuu
    portfel_years = portfel_months / 12  # Konwertuj na lata
    # CAGR: annualized return od kapitału początkowego do końcowej wartości
    portfel_cagr = calculate_cagr(cap_start_pln, portfel_netto, portfel_years) if portfel_years > 0 else 0
    portfel_returns = (df['Portfel'] / df['Portfel'].shift(1) - 1).dropna()
    portfel_sharpe = calculate_sharpe_ratio(portfel_returns, periods_per_year=12)
    portfel_sortino = calculate_sortino_ratio(portfel_returns, periods_per_year=12)

    st.subheader(f"📊 Podsumowanie Wyników ({target_currency}) — podatki płacone z osobnego konta")

    # --- Obliczenia netto dla benchmarków ---
    bench_pit = {}
    for a in asset_inputs:
        b_val_last = df[f'Bench {a}'].iloc[-1]
        b_gain = b_val_last - total_invested_target
        bench_pit[a] = max(0, b_gain * tax_rate) if tax_rate > 0 else 0

    # MOMENTUM netto = wartość portfela − PIT już zapłacony (z osobnego konta)
    portfel_netto_po_pit = portfel_brutto - (pit_total_realized_pln if tax_rate > 0 else 0)
    portfel_zysk_netto_pct = (portfel_netto_po_pit - total_invested_target) / total_invested_target * 100

    # --- WIERSZ BRUTTO ---
    st.caption("**📈 Wartość Brutto** (portfel bez odliczenia podatku)")
    kpi = st.columns(5)
    kpi[0].metric("MOMENTUM (brutto)", f"{portfel_brutto:,.0f}", f"{portfel_zysk_pct:+.2f}%")
    for idx, a in enumerate(asset_inputs):
        b_val = df[f'Bench {a}'].iloc[-1]
        b_zysk_pct = (b_val - total_invested_target) / total_invested_target * 100
        kpi[idx+1].metric(f"{a} B&H (brutto)", f"{b_val:,.0f}", f"{b_zysk_pct:+.2f}%")

    # --- WIERSZ NETTO ---
    st.caption("**💰 Wartość Netto po PIT** (brutto − suma zapłaconych podatków, również z osobnego konta)")
    kpi2 = st.columns(5)
    kpi2[0].metric(
        "MOMENTUM (netto)",
        f"{portfel_netto_po_pit:,.0f}",
        f"{portfel_zysk_netto_pct:+.2f}%",
        help=f"Brutto {portfel_brutto:,.0f} − PIT zapłacony {pit_total_realized_pln:,.0f} PLN"
    )
    for idx, a in enumerate(asset_inputs):
        b_val = df[f'Bench {a}'].iloc[-1]
        b_netto = b_val - bench_pit[a]
        b_netto_pct = (b_netto - total_invested_target) / total_invested_target * 100
        kpi2[idx+1].metric(
            f"{a} B&H (netto)",
            f"{b_netto:,.0f}",
            f"{b_netto_pct:+.2f}%",
            help=f"Brutto {b_val:,.0f} − PIT niezreal. {bench_pit[a]:,.0f} PLN"
        )

    # --- ROZSZERZONE METRYKI (siatka) ---
    with st.expander("📈 Szczegółowe Metryki Portfela", expanded=True):
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("CAGR", f"{portfel_cagr:+.2f}%")
        m2.metric("Sharpe", f"{portfel_sharpe:+.2f}")
        m3.metric("Sortino", f"{portfel_sortino:+.2f}")
        m4.metric("Max DD", f"{portfel_mdd:.1f}%")
        m5.metric("Zysk nominalny", f"{portfel_zysk_nom:+,.0f}")
        m6.metric("Zainwestowano", f"{total_invested_target:,.0f}")

        if tax_rate > 0:
            t1m, t2m, t3m, t4m = st.columns(4)
            t1m.metric("💰 PIT zapłacony (PLN)", f"{pit_total_realized_pln:,.0f}")
            t2m.metric("📋 PIT niezrealizowany (PLN)", f"{unreal_tax_pln:,.0f}")
            t3m.metric("📉 Tax Drag", f"{tax_drag_pct:.1f}%")
            t4m.metric("↩️ Strata C/F (PLN)", f"{loss_carry_forward:,.0f}")
        else:
            st.success(f"✅ Konto {account_type} — brak podatku Belki")

        st.caption(f"Strategia: {strategy_type} | Konto: {account_type} | Waluta: {target_currency} | Vol lookback: {vol_lookback}d | Slippage: {slippage_pct:.2f}%")

    # --- BENCHMARKI SZCZEGÓŁY ---
    with st.expander("📋 Porównanie z Benchmarkami (Buy & Hold)", expanded=False):
        bench_rows = []
        for a in asset_inputs:
            b_val2 = df[f'Bench {a}'].iloc[-1]
            b_zysk2 = b_val2 - total_invested_target
            b_zysk2_pct = (b_zysk2 / total_invested_target) * 100
            b_mdd2 = calculate_drawdown(df[f'Bench {a}'])
            b_years2 = portfel_years
            b_cagr2 = calculate_cagr(cap_start_pln, b_val2, b_years2) if b_years2 > 0 else 0
            b_returns2 = (df[f'Bench {a}'] / df[f'Bench {a}'].shift(1) - 1).dropna()
            b_sharpe2 = calculate_sharpe_ratio(b_returns2, periods_per_year=12)
            b_sortino2 = calculate_sortino_ratio(b_returns2, periods_per_year=12)
            b_unreal_tax2 = max(0, b_zysk2 * tax_rate) if tax_rate > 0 else 0
            bench_rows.append({
                'Aktywo': a,
                'Wartość': f"{b_val2:,.0f}",
                'Zysk': f"{b_zysk2:+,.0f}",
                'Zysk %': f"{b_zysk2_pct:+.2f}%",
                'CAGR': f"{b_cagr2:+.2f}%",
                'Sharpe': f"{b_sharpe2:+.2f}",
                'Sortino': f"{b_sortino2:+.2f}",
                'Max DD': f"{b_mdd2:.1f}%",
                'PIT (PLN)': f"{b_unreal_tax2:,.0f}"
            })
        bench_df_display = pd.DataFrame(bench_rows)
        st.dataframe(bench_df_display, use_container_width=True, hide_index=True)

    # --- PER-ASSET REALIZED P&L ---
    if per_asset_pl:
        with st.expander("📊 **Zyski/Straty Zrealizowane per Aktywo (PLN)**", expanded=False):
            asset_pl_data = []
            for a in asset_inputs:
                apl = per_asset_pl.get(a, {'gains': 0, 'losses': 0})
                net = apl['gains'] - apl['losses']
                asset_pl_data.append({
                    'Aktywo': a,
                    'Zyski (PLN)': round(apl['gains'], 2),
                    'Straty (PLN)': round(apl['losses'], 2),
                    'Netto (PLN)': round(net, 2),
                    'Efektywność': f"{(apl['gains'] / (apl['gains'] + apl['losses']) * 100):.0f}%" if (apl['gains'] + apl['losses']) > 0 else "N/A"
                })
            df_asset_pl = pd.DataFrame(asset_pl_data)
            st.dataframe(df_asset_pl, use_container_width=True, hide_index=True)

    t1, t2, t3, t4, t5 = st.tabs(["📈 Wykres", "⚖️ Wagi i Sygnały", "🧠 Dane Surowe", "🗓️ Raport Roczny PIT", "📊 Korelacja"])
    
    with t1:
        # WYKRES 1: PORTFEL vs BENCHMARKI
        fig1 = go.Figure()
        
        fig1.add_trace(
            go.Scatter(x=df.index, y=df['Portfel'], name="MOMENTUM", 
                      line=dict(width=3.5, color='#00CC96'),
                      fill='tozeroy', fillcolor='rgba(0,204,150,0.15)',
                      hovertemplate='<b>MOMENTUM</b><br>Data: %{x|%Y-%m-%d}<br>Wartość: %{y:,.0f}<extra></extra>')
        )
        
        colors_bench = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728']
        for idx, a in enumerate(asset_inputs):
            fig1.add_trace(
                go.Scatter(x=df.index, y=df[f'Bench {a}'], name=f"{a} (B&H)",
                          line=dict(width=2, color=colors_bench[idx], dash='dash'),
                          hovertemplate=f'<b>{a}</b><br>Data: %{{x|%Y-%m-%d}}<br>Wartość: %{{y:,.0f}}<extra></extra>')
            )
        
        fig1.update_layout(
            title="📈 Portfel vs Benchmarki",
            xaxis_title="Data",
            yaxis_title="Wartość Portfela",
            height=450,
            hovermode="x unified",
            template="plotly_white",
            legend=dict(
                x=1.01, y=1, xanchor='left', yanchor='top'
            )
        )
        fig1.update_yaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.15)')
        st.plotly_chart(fig1, use_container_width=True)
        
        # WYKRES 2: WAGI PORTFELA
        fig2 = go.Figure()
        
        df_weights = pd.DataFrame()
        for a in asset_inputs:
            col_name = f'{a} %'
            df_weights[a] = df[col_name].str.rstrip('%').astype(float)
        
        cake_colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A']
        
        for idx, a in enumerate(asset_inputs):
            label = f"Waga {a}" if a != asset_inputs[3] else "🛡️ Safe Haven"
            fig2.add_trace(
                go.Scatter(
                    x=df.index, 
                    y=df_weights[a],
                    name=label,
                    mode='lines',
                    stackgroup='weights',
                    line=dict(width=0.5, color=cake_colors[idx]),
                    fillcolor=cake_colors[idx],
                    hovertemplate=(
                        f'<b>{a}</b><br>' +
                        'Data: %{x|%Y-%m-%d}<br>' +
                        'Waga: %{y:.1f}%<br>' +
                        '<extra></extra>'
                    )
                )
            )
        
        fig2.update_layout(
            title="⚖️ Wagi Portfela (Warstwowy Rozkład)",
            xaxis_title="Data",
            yaxis_title="Waga (%)",
            height=450,
            hovermode="x unified",
            template="plotly_white",
            legend=dict(
                x=1.01, y=1, xanchor='left', yanchor='top'
            )
        )
        fig2.update_yaxes(range=[0, 100], showgrid=True, gridwidth=2, gridcolor='rgba(128,128,128,0.2)', nticks=5)
        fig2.update_xaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.1)')
        st.plotly_chart(fig2, use_container_width=True)
        
        # WYKRES 3: DRAWDOWN
        fig3 = go.Figure()
        
        momentum_dd = (df['Portfel'] - df['Portfel'].cummax()) / df['Portfel'].cummax() * 100
        
        fig3.add_trace(
            go.Scatter(x=df.index, y=momentum_dd, name="Drawdown MOMENTUM",
                      line=dict(width=2.5, color='#00CC96'),
                      fill='tozeroy', fillcolor='rgba(0,204,150,0.25)',
                      hovertemplate='<b>DD Momentum</b><br>Data: %{x|%Y-%m-%d}<br>Drawdown: %{y:.2f}%<extra></extra>')
        )
        
        for idx, a in enumerate(asset_inputs):
            rolling_max = df[f'Bench {a}'].cummax()
            dd_series = ((df[f'Bench {a}'] - rolling_max) / rolling_max * 100)
            fig3.add_trace(
                go.Scatter(x=df.index, y=dd_series, name=f"DD {a}",
                          line=dict(width=1.5, color=colors_bench[idx], dash='dash'),
                          hovertemplate=f'<b>DD {a}</b><br>Data: %{{x|%Y-%m-%d}}<br>Drawdown: %{{y:.2f}}%<extra></extra>')
            )
        
        fig3.update_layout(
            title="📉 Drawdown - Maksymalne Spadki",
            xaxis_title="Data",
            yaxis_title="Drawdown (%)",
            height=450,
            hovermode="x unified",
            template="plotly_white",
            legend=dict(
                x=1.01, y=1, xanchor='left', yanchor='top'
            )
        )
        fig3.update_yaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.15)')
        fig3.update_xaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.1)')
        st.plotly_chart(fig3, use_container_width=True)

    with t2:
        st.subheader("⚖️ Wagi, Sygnały i Zyski/Straty")
        
        # WYKRES: Miesięczne zyski i straty zrealizowane
        if 'Zysk Real. (PLN)' in df.columns and 'Strata Real. (PLN)' in df.columns:
            fig_pl = go.Figure()
            fig_pl.add_trace(go.Bar(
                x=df.index, y=df['Zysk Real. (PLN)'],
                name='Zyski (PLN)', marker_color='#00CC96',
                hovertemplate='<b>Zysk</b><br>Data: %{x|%Y-%m-%d}<br>%{y:,.0f} PLN<extra></extra>'
            ))
            fig_pl.add_trace(go.Bar(
                x=df.index, y=-df['Strata Real. (PLN)'],
                name='Straty (PLN)', marker_color='#EF553B',
                hovertemplate='<b>Strata</b><br>Data: %{x|%Y-%m-%d}<br>%{y:,.0f} PLN<extra></extra>'
            ))
            fig_pl.update_layout(
                title='💰 Miesięczne Zyski i Straty Zrealizowane (PLN)',
                barmode='relative', height=300,
                hovermode='x unified', template='plotly_white',
                legend=dict(x=1.01, y=1, xanchor='left')
            )
            fig_pl.update_yaxes(showgrid=True, gridcolor='rgba(128,128,128,0.15)')
            st.plotly_chart(fig_pl, use_container_width=True)
        
        # TABELA: Wagi i sygnały
        df_display = pd.DataFrame()
        
        for a in asset_inputs[:3]:
            col_name = f'{a} %'
            # Konwertuj string z % na float
            df_display[col_name] = df[col_name].str.rstrip('%').astype(float)
        
        df_display['🎯 Total Score'] = df[[f'Score {a}' for a in asset_inputs[:3]]].sum(axis=1)
        df_display['💰 Zysk Real. (PLN)'] = df['Zysk Real. (PLN)'].cumsum()
        df_display['💸 Strata Real. (PLN)'] = df['Strata Real. (PLN)'].cumsum()
        
        # Wyświetlenie z kolorami
        st.dataframe(
            df_display.style
                .background_gradient(cmap='Greens', subset=[f'{a} %' for a in asset_inputs[:3]], vmin=0, vmax=100)
                .background_gradient(cmap='Greens', subset=['💰 Zysk Real. (PLN)'])
                .background_gradient(cmap='Reds', subset=['💸 Strata Real. (PLN)'])
                .highlight_max(subset=['🎯 Total Score'], color='lightgreen')
                .format({col: "{:.1f}%" if '%' in col else "{:,.0f}" for col in df_display.columns}),
            use_container_width=True,
            height=400
        )

    with t3:
        st.subheader("🧠 Dane Surowe - Szczegółowe Metryki")
        
        # Przygotowanie danych
        df_raw = df.copy()
        
        # Konwersja kolumn procentowych - tylko stringi z '%'
        pct_cols = [col for col in df_raw.columns if '%' in col and df_raw[col].dtype == 'object']
        for col in pct_cols:
            df_raw[col] = df_raw[col].str.rstrip('%').astype(float)
        
        # Przygotuj kolumny do wyświetlenia
        portfel_cols = ['Portfel', 'Zysk Real. (PLN)', 'Strata Real. (PLN)']
        benchmark_cols = [col for col in df_raw.columns if 'Bench' in col]
        wagi_cols = [col for col in df_raw.columns if '%' in col and 'Contribution' not in col]
        score_cols = [col for col in df_raw.columns if 'Score' in col]
        
        # TAB A: PORTFEL I PODATKI
        with st.expander("📊 **Portfel i Zyski/Straty**", expanded=True):
            df_portfel = df_raw[portfel_cols].copy()
            st.dataframe(
                df_portfel.style
                    .format({col: "{:,.2f}" for col in df_portfel.columns})
                    .background_gradient(cmap='Greens', subset=['Portfel'])
                    .background_gradient(cmap='Greens', subset=['Zysk Real. (PLN)'])
                    .background_gradient(cmap='Reds', subset=['Strata Real. (PLN)']),
                use_container_width=True,
                height=300
            )
        
        # TAB B: BENCHMARKI
        with st.expander("📈 **Benchmarki (Buy & Hold)**", expanded=False):
            df_bench = df_raw[benchmark_cols].copy()
            st.dataframe(
                df_bench.style
                    .format({col: "{:,.2f}" for col in df_bench.columns})
                    .background_gradient(cmap='BuGn'),
                use_container_width=True,
                height=300
            )
        
        # TAB C: WAGI PORTFELA
        with st.expander("⚖️ **Wagi Portfela (%)**", expanded=False):
            df_wagi = df_raw[wagi_cols].copy()
            st.dataframe(
                df_wagi.style
                    .format({col: "{:.1f}%" for col in df_wagi.columns})
                    .background_gradient(cmap='Greens', vmin=0, vmax=100),
                use_container_width=True,
                height=300
            )
        
        # TAB D: SYGNAŁY MOMENTUM
        with st.expander("🎯 **Sygnały Momentum (Scores)**", expanded=False):
            df_scores = df_raw[score_cols].copy()
            st.dataframe(
                df_scores.style
                    .format({col: "{:.4f}" for col in df_scores.columns})
                    .background_gradient(cmap='Purples'),
                use_container_width=True,
                height=300
            )
        
        # TAB E: WKŁAD AKTYW (CONTRIBUTION)
        contribution_cols = [col for col in df_raw.columns if 'Contribution' in col]
        if contribution_cols:
            with st.expander("💡 **Wkład Aktywów do Portfela (Contribution)**", expanded=False):
                st.info("Pokazuje jak każde aktywo wpłynęło na wynik portfela każdego miesiąca (w procentach).\n"
                       "Pozytywne (zielone) = zwiększyło portfel, Ujemne (czerwone) = zmniejszyło portfel")
                df_contrib = df_raw[contribution_cols].copy()
                
                # Custom coloring dla ujemnych na czerwono, dodatnich na zielono
                def color_contribution(val):
                    if pd.isna(val):
                        return ''
                    try:
                        fval = float(val)
                    except (ValueError, TypeError):
                        return ''
                    if fval < 0:
                        # Bardziej RED dla bardziej negatywnych
                        intensity = min(abs(fval) / 10, 1)  # 0 do 1
                        return f'background-color: rgba(255, {int(100*(1-intensity))}, {int(100*(1-intensity))})'
                    else:
                        # Bardziej GREEN dla bardziej pozytywnych
                        intensity = min(fval / 10, 1)  # 0 do 1
                        return f'background-color: rgba({int(100*(1-intensity))}, 200, {int(100*(1-intensity))})'
                
                st.dataframe(
                    df_contrib.style
                        .format({col: "{:.2f}%" for col in df_contrib.columns})
                        .applymap(color_contribution),
                    use_container_width=True,
                    height=300
                )
        
        # DOWNLOAD SECTION
        st.divider()
        col1, col2 = st.columns([2, 1])
        
        with col1:
            csv = df_raw.to_csv(index=True)
            st.download_button(
                label="📥 Pobierz Dane Surowe (CSV)",
                data=csv,
                file_name=f"momentum_pro_backtest_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        
        with col2:
            # Statystyka liczby rekordów
            st.metric("Liczba miesięcy", len(df_raw))

    with t4:
        st.subheader("🗓️ Raport Roczny PIT-38 (TWR - bez wpływu dopłat)")
        
        annual_stats, pit_cum = [], 0
        for y in sorted(df['Rok'].unique()):
            df_y = df[df['Rok'] == y]
            pit_y = pit_roczny_pln.get(y, 0) if pit_roczny_pln else 0
            pit_cum += pit_y
            v_start = val_start_year_target.get(y, df_y['Portfel'].iloc[0]) if val_start_year_target else df_y['Portfel'].iloc[0]
            v_end = df_y['Portfel'].iloc[-1]
            
            is_first = (y == sorted(df['Rok'].unique())[0])
            num_deposits = len(df_y) - (1 if is_first else 0)
            # Kurs FX: użyj prawdziwego kursu jeśli dostępny, inaczej 1.0 (PLN)
            if kurs_target_pln is not None:
                rate_y = kurs_target_pln.asof(pd.Timestamp(df_y.index[0]))
                fx_mean = fx_map[target_currency].loc[pd.Timestamp(df_y.index[0]):pd.Timestamp(df_y.index[-1])].mean()
                fx_str = f"{fx_mean:.4f}"
            else:
                rate_y = 1.0
                fx_str = "N/A (wczytany scenariusz)"
            deposits_val = (cap_monthly_pln * num_deposits) / rate_y
            
            organic_ret = ((v_end - deposits_val) / v_start - 1) * 100
            
            # Obliczenie drawdown dla roku
            year_mdd = calculate_drawdown(df_y['Portfel'])
            
            # Szczegóły podatkowe z tax_breakdown (jeśli dostępne)
            tb = tax_breakdown.get(y, {}) if tax_breakdown else {}
            gains_y = tb.get('gains', yearly_gains.get(y, 0) if yearly_gains else 0)
            losses_y = tb.get('losses', yearly_losses.get(y, 0) if yearly_losses else 0)
            net_y = tb.get('net', gains_y - losses_y)
            carry_used_y = tb.get('carry_used', 0)
            taxable_y = tb.get('taxable', max(0, net_y))
            carry_remain_y = tb.get('carry_remaining', 0)
            
            annual_stats.append({
                "Rok": int(y),
                "Wycena Start": f"{v_start:,.0f}",
                "Wycena Koniec": f"{v_end:,.0f}",
                "Zwrot TWR %": f"{organic_ret:+.2f}%",
                "Drawdown %": f"{year_mdd:.2f}%",
                "Przychód (PLN)": f"{gains_y:,.0f}",
                "Koszty (PLN)": f"{losses_y:,.0f}",
                "Dochód Netto": f"{net_y:+,.0f}",
                "Odlicz. Strat": f"{carry_used_y:,.0f}",
                "Podstawa": f"{taxable_y:,.0f}",
                "PIT Rok": f"{pit_y:,.0f}",
                "PIT Skum.": f"{pit_cum:,.0f}",
                "Strata C/F": f"{carry_remain_y:,.0f}",
                "Kurs FX": fx_str
            })
        
        df_annual = pd.DataFrame(annual_stats)
        
        # Konwersja wszystkich kolumn numerycznych ze string formatowania na float
        def _str_to_float(series):
            return pd.to_numeric(
                series.astype(str).str.replace(',', '', regex=False).str.replace('+', '', regex=False),
                errors='coerce'
            )
        
        df_annual_style = df_annual.copy()
        df_annual_style['Zwrot TWR %'] = _str_to_float(df_annual['Zwrot TWR %'].str.rstrip('%'))
        df_annual_style['Drawdown %']  = _str_to_float(df_annual['Drawdown %'].str.rstrip('%'))
        for _col in ['Wycena Start', 'Wycena Koniec', 'Przychód (PLN)', 'Koszty (PLN)',
                     'Dochód Netto', 'Odlicz. Strat', 'Podstawa', 'PIT Rok', 'PIT Skum.', 'Strata C/F']:
            df_annual_style[_col] = _str_to_float(df_annual[_col])
        
        _fmt_pln  = lambda v: f"{v:+,.0f}" if v != 0 else "0"
        _fmt_pos  = lambda v: f"{v:,.0f}"
        
        # Główne kolumny roczne
        main_cols = ['Rok', 'Wycena Koniec', 'Zwrot TWR %', 'Drawdown %', 'PIT Rok', 'Strata C/F']
        st.dataframe(
            df_annual_style[main_cols].style
                .background_gradient(cmap='RdYlGn', subset=['Zwrot TWR %'], vmin=-20, vmax=40)
                .background_gradient(cmap='Reds_r', subset=['Drawdown %'])
                .background_gradient(cmap='Oranges', subset=['PIT Rok'])
                .format({
                    'Zwrot TWR %': '{:+.2f}%',
                    'Drawdown %':  '{:.2f}%',
                    'Wycena Koniec': '{:,.0f}',
                    'PIT Rok':     '{:,.0f}',
                    'Strata C/F':  '{:,.0f}',
                }),
            use_container_width=True
        )
        
        # Szczegóły PIT-38 w expander
        with st.expander("🔍 Szczegóły PIT-38 (Przychód / Koszty / Netting)"):
            pit_cols = ['Rok', 'Wycena Start', 'Przychód (PLN)', 'Koszty (PLN)',
                        'Dochód Netto', 'Odlicz. Strat', 'Podstawa', 'PIT Rok', 'PIT Skum.', 'Kurs FX']
            st.dataframe(
                df_annual_style[pit_cols].style
                    .background_gradient(cmap='RdYlGn', subset=['Dochód Netto'])
                    .background_gradient(cmap='Oranges', subset=['PIT Rok', 'PIT Skum.'])
                    .format({
                        'Wycena Start':    '{:,.0f}',
                        'Przychód (PLN)':  '{:,.0f}',
                        'Koszty (PLN)':    '{:,.0f}',
                        'Dochód Netto':    '{:+,.0f}',
                        'Odlicz. Strat':   '{:,.0f}',
                        'Podstawa':        '{:,.0f}',
                        'PIT Rok':         '{:,.0f}',
                        'PIT Skum.':       '{:,.0f}',
                    }),
                use_container_width=True
            )
        
        # Summary statistics
        col1, col2, col3, col4 = st.columns(4)
        
        avg_return = annual_stats[0] if annual_stats else {}
        if annual_stats:
            returns = [float(row['Zwrot TWR %'].rstrip('%')) for row in annual_stats]
            col1.metric("📊 Średni Zwrot Roczny", f"{np.mean(returns):+.2f}%")
            col2.metric("📈 Best Year", f"{max(returns):+.2f}%")
            col3.metric("📉 Worst Year", f"{min(returns):+.2f}%")
            col4.metric("🎯 Volatility", f"{np.std(returns):.2f}%")

    # TAB 5: KORELACJA AKTYWÓW
    with t5:
        st.subheader("📊 Macierz Korelacji Aktywów")
        
        if prices is None:
            st.info("ℹ️ Korelacja dzienna niedostępna dla wczytanego scenariusza. Używam miesięcznych zwrotów benchmarków.")
            corr_data = pd.DataFrame()
            for a in asset_inputs:
                bench_col = f'Bench {a}'
                if bench_col in df.columns:
                    corr_data[a] = df[bench_col].pct_change()
        else:
            # Calculate daily returns for each asset
            corr_data = pd.DataFrame()
            for a in asset_inputs:
                corr_data[a] = prices[a].pct_change()
        
        # Calculate correlation matrix
        corr_matrix = corr_data.corr()
        
        # Create heatmap with Plotly
        fig_corr = go.Figure(data=go.Heatmap(
            z=corr_matrix.values,
            x=corr_matrix.columns,
            y=corr_matrix.columns,
            colorscale='RdBu_r',
            zmid=0,
            zmin=-1,
            zmax=1,
            text=np.round(corr_matrix.values, 3),
            texttemplate='%{text:.3f}',
            textfont={"size": 12},
            colorbar=dict(title="Korelacja")
        ))
        
        fig_corr.update_layout(
            title="Korelacja dziennych stóp zwrotu między aktywami",
            xaxis_title="Aktywo",
            yaxis_title="Aktywo",
            height=500,
            width=700
        )
        
        st.plotly_chart(fig_corr, use_container_width=True)
        
        # Interpretation
        st.write("---")
        st.subheader("💡 Interpretacja")
        st.write("""
        - **Korelacja bliska +1**: Aktywa poruszają się razem (niska dywersyfikacja)
        - **Korelacja bliska 0**: Aktywa poruszają się niezależnie (dobra dywersyfikacja)
        - **Korelacja bliska -1**: Aktywa poruszają się w przeciwnych kierunkach (idealna dywersyfikacja)
        
        **Średnia korelacja w portfelu:**
        """)
        
        # Calculate average correlation (excluding diagonal)
        mask = np.triu(np.ones_like(corr_matrix, dtype=bool), k=1)
        avg_corr = corr_matrix.values[mask].mean()
        
        col1, col2, col3 = st.columns(3)
        col1.metric("🔗 Średnia Korelacja", f"{avg_corr:+.3f}")
        col2.metric("📊 Diversifiacja", "Dobra" if avg_corr < 0.5 else "Średnia" if avg_corr < 0.75 else "Niska")
        
        # Identify strongest correlation pair
        corr_pairs = []
        for i in range(len(corr_matrix)):
            for j in range(i+1, len(corr_matrix)):
                corr_pairs.append((corr_matrix.columns[i], corr_matrix.columns[j], corr_matrix.iloc[i, j]))
        
        if corr_pairs:
            strongest = max(corr_pairs, key=lambda x: abs(x[2]))
            col3.metric("💫 Najsilniejsza powiązanie", f"{strongest[0]} ↔ {strongest[1]} ({strongest[2]:+.3f})")

# --- PORÓWNANIE SCENARIUSZY ---
available_scenarios_for_compare = list_scenarios()
if available_scenarios_for_compare:
    st.write("---")
    st.subheader("📊 Porównanie Scenariuszy")
    
    selected_scenarios = st.multiselect(
        "Wybierz scenariusze do porównania:",
        available_scenarios_for_compare,
        default=available_scenarios_for_compare[-1:] if available_scenarios_for_compare else []
    )
    
    if selected_scenarios:
        # Wczytaj wszystkie scenariusze RAZ (zamiast wielokrotnie)
        scenarios_cache = {}
        for scen_name in selected_scenarios:
            scen = load_scenario_from_file(scen_name)
            if scen:
                scenarios_cache[scen_name] = scen
        
        # Create comparison table
        comparison_data = []
        for scen_name, scen in scenarios_cache.items():
            scen_df = scen['df']
            
            # Calculate metrics for this scenario
            scen_return = ((scen_df['Portfel'].iloc[-1] - scen_df['Portfel'].iloc[0]) / scen_df['Portfel'].iloc[0]) * 100
            scen_dd = calculate_drawdown(scen_df['Portfel'])
            scen_months = len(scen_df)
            scen_years = scen_months / 12  # Konwertuj miesiące na lata
            scen_cagr = calculate_cagr(scen['params']['cap_start'], scen_df['Portfel'].iloc[-1], scen_years)
            scen_returns = (scen_df['Portfel'] / scen_df['Portfel'].shift(1) - 1).dropna()
            scen_sharpe = calculate_sharpe_ratio(scen_returns, periods_per_year=12)
            scen_sortino = calculate_sortino_ratio(scen_returns, periods_per_year=12)
            
            comparison_data.append({
                'Scenariusz': scen_name,
                'Parametry': f"{scen['params']['strategy_type'][:20]} | {','.join(scen['params']['assets'])}",
                'Data zapisu': scen['timestamp'].strftime('%Y-%m-%d %H:%M'),
                'Zwrot %': f"{scen_return:+.2f}%",
                'CAGR %': f"{scen_cagr:+.2f}%",
                'Sharpe': f"{scen_sharpe:+.2f}",
                'Sortino': f"{scen_sortino:+.2f}",
                'Drawdown %': f"{scen_dd:.1f}%"
            })
        
        if comparison_data:
            comparison_df = pd.DataFrame(comparison_data)
            st.dataframe(comparison_df, use_container_width=True, hide_index=True)
            
            # Scenario parameters details (reuse cache)
            with st.expander("📋 Szczegóły parametrów scenariuszy"):
                for scen_name, scen in scenarios_cache.items():
                    st.write(f"**{scen_name}**")
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Strategia", scen['params']['strategy_type'][:15])
                    col2.metric("Slippage", f"{scen['params'].get('slippage_pct', 0):.2f}%")
                    col3.metric("Belka PIT", "✅" if scen['params'].get('tax_enabled', True) else "❌")
                    col4.metric("Waluta", scen['params']['target_currency'])
                    st.divider()
            
            # Comparison charts for selected scenarios (reuse cache)
            if len(scenarios_cache) >= 1:
                st.subheader("📈 Porównanie Ścieżek Portfela")
                
                # Dane już w scenarios_cache
                scenarios_data = scenarios_cache
                
                # WYKRES 1: PORTFEL BRUTTO
                col1, col2 = st.columns(2)
                
                with col1:
                    fig_brutto = go.Figure()
                    colors_scen = ['#00CC96', '#FF6692', '#AB63FA', '#FFA15A', '#00CC96', '#EF553B', '#636EFA']
                    
                    for idx, (scen_name, scen) in enumerate(scenarios_data.items()):
                        scen_df = scen['df']
                        fig_brutto.add_trace(
                            go.Scatter(
                                x=scen_df.index, 
                                y=scen_df['Portfel'], 
                                name=scen_name,
                                line=dict(width=3, color=colors_scen[idx % len(colors_scen)]),
                                hovertemplate='<b>' + scen_name + '</b><br>Data: %{x|%Y-%m-%d}<br>Wartość: %{y:,.0f}<extra></extra>'
                            )
                        )
                    
                    fig_brutto.update_layout(
                        title="💰 Portfel BRUTTO (bez podatków)",
                        xaxis_title="Data",
                        yaxis_title="Wartość",
                        height=450,
                        hovermode='x unified',
                        template='plotly_white',
                        legend=dict(x=1.01, y=1, xanchor='left', yanchor='top'),
                        margin=dict(r=150)
                    )
                    fig_brutto.update_yaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.1)')
                    st.plotly_chart(fig_brutto, use_container_width=True)
                
                # WYKRES 2: PORTFEL NETTO (po podatakach)
                with col2:
                    fig_netto = go.Figure()
                    
                    # Przygotuj dane netto
                    netto_data = []
                    for idx, (scen_name, scen) in enumerate(scenarios_data.items()):
                        scen_df = scen['df']
                        params = scen['params']
                        
                        # Oblicz podatki dla każdego miesiąca
                        # Użyj właściwej bazy kosztowej (total_invested = cap_start + dopłaty)
                        scen_tax_rate = 0.19 if params.get('tax_enabled', True) else (0.10 if 'IKZE' in params.get('account_type', '') else 0.0)
                        total_invested_running = params['cap_start']
                        portfel_netto_series = []
                        
                        for m_idx, portfel_val in enumerate(scen_df['Portfel']):
                            if m_idx > 0:
                                total_invested_running += params['cap_monthly']
                            if scen_tax_rate > 0:
                                estimated_tax = max(0, (portfel_val - total_invested_running) * scen_tax_rate)
                            else:
                                estimated_tax = 0
                            # Podatki informacyjne - nie odejmujemy od portfela
                            portfel_netto_series.append(portfel_val)
                        
                        netto_data.append((scen_name, portfel_netto_series))
                    
                    for idx, (scen_name, portfel_netto) in enumerate(netto_data):
                        scen = scenarios_data[scen_name]
                        scen_df = scen['df']
                        fig_netto.add_trace(
                            go.Scatter(
                                x=scen_df.index, 
                                y=portfel_netto, 
                                name=scen_name,
                                line=dict(width=3, color=colors_scen[idx % len(colors_scen)]),
                                hovertemplate='<b>' + scen_name + '</b><br>Data: %{x|%Y-%m-%d}<br>Wartość netto: %{y:,.0f}<extra></extra>'
                            )
                        )
                    
                    fig_netto.update_layout(
                        title=f"🏦 Portfel (podatki informacyjne, płacone z osobnego konta)",
                        xaxis_title="Data",
                        yaxis_title="Wartość",
                        height=450,
                        hovermode='x unified',
                        template='plotly_white',
                        legend=dict(x=1.01, y=1, xanchor='left', yanchor='top'),
                        margin=dict(r=150)
                    )
                    fig_netto.update_yaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.1)')
                    st.plotly_chart(fig_netto, use_container_width=True)
                
                # TABELA PORÓWNAWCZA WYNIKÓW NETTO
                st.divider()
                st.subheader("📊 Porównanie Wyników NETTO")
                
                netto_comparison = []
                for scen_name, scen in scenarios_data.items():
                    scen_df = scen['df']
                    params = scen['params']
                    
                    # Wartości brutto
                    portfel_start = scen_df['Portfel'].iloc[0]
                    portfel_end = scen_df['Portfel'].iloc[-1]
                    
                    # Podatki - użyj prawidłowej bazy kosztowej (total_invested)
                    scen_tax_rate = 0.19 if params.get('tax_enabled', True) else (0.10 if 'IKZE' in params.get('account_type', '') else 0.0)
                    total_invested = params['cap_start'] + (params['cap_monthly'] * (len(scen_df) - 1))
                    if scen_tax_rate > 0:
                        estimated_tax = max(0, (portfel_end - total_invested) * scen_tax_rate)
                    else:
                        estimated_tax = 0
                    
                    # Podatki informacyjne - nie odejmujemy (płacone z osobnego konta)
                    portfel_end_netto = portfel_end
                    
                    # Metryki
                    zysk_netto = portfel_end_netto - total_invested
                    zysk_pct_netto = (zysk_netto / total_invested * 100) if total_invested > 0 else 0
                    
                    scen_months = len(scen_df)
                    scen_years = scen_months / 12
                    scen_cagr = calculate_cagr(params['cap_start'], portfel_end_netto, scen_years)
                    
                    scen_returns = (scen_df['Portfel'] / scen_df['Portfel'].shift(1) - 1).dropna()
                    scen_sharpe = calculate_sharpe_ratio(scen_returns, periods_per_year=12)
                    scen_sortino = calculate_sortino_ratio(scen_returns, periods_per_year=12)
                    scen_mdd = calculate_drawdown(scen_df['Portfel'])
                    
                    netto_comparison.append({
                        'Strategia': scen_name,
                        'Wartość Start': f"{portfel_start:,.0f}",
                        'Wartość End (Brutto)': f"{portfel_end:,.0f}",
                        'Podatki (szacunek)': f"{estimated_tax:,.0f}",
                        'Wartość End (NETTO)': f"{portfel_end_netto:,.0f}",
                        'Zysk NETTO': f"{zysk_netto:+,.0f}",
                        'Zysk %': f"{zysk_pct_netto:+.2f}%",
                        'CAGR': f"{scen_cagr:+.2f}%",
                        'Sharpe': f"{scen_sharpe:+.2f}",
                        'Sortino': f"{scen_sortino:+.2f}",
                        'Max DD': f"{scen_mdd:.1f}%"
                    })
                
                netto_df = pd.DataFrame(netto_comparison)
                
                # Konwertuj kolumny numeryczne ze stringów na float przed gradientem
                df_display = netto_df.copy()
                for col, strip_char in [('Zysk %', '%'), ('CAGR', '%'), ('Max DD', '%'), ('Sharpe', ''), ('Sortino', '')]:
                    if col in df_display.columns:
                        df_display[col] = df_display[col].str.rstrip('%').astype(float)
                
                st.dataframe(
                    df_display.style
                        .background_gradient(cmap='RdYlGn', subset=['Zysk %', 'CAGR'], vmin=-20, vmax=40)
                        .background_gradient(cmap='Greens', subset=['Sharpe', 'Sortino'])
                        .background_gradient(cmap='Reds_r', subset=['Max DD']),
                    use_container_width=True,
                    hide_index=True
                )

else:
    # --- STAN POWITALNY ---
    st.markdown("""  
    <div style='text-align:center; padding: 60px 20px;'>
        <h2 style='color:#888;'>🛡️ Witaj w Momentum Pro</h2>
        <p style='font-size:1.1em; color:#aaa;'>System Inwestycyjny oparty na Momentum</p>
        <hr style='border-color:#333; width:40%; margin:20px auto;'/>
    </div>
    """, unsafe_allow_html=True)

    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        st.markdown("### 📋 Jak zacząć?")
        st.markdown("""
        | Krok | Akcja |
        |------|-------|
        | **1** | Ustaw aktywa i walutę w panelu bocznym |
        | **2** | Skonfiguruj kapitał, daty i strategię |
        | **3** | Kliknij 🚀 **URUCHOM SYMULACJĘ** |
        | **4** | Przeanalizuj wyniki i porównaj z benchmarkami |
        | **5** | Zapisz scenariusz i porównaj wiele strategii |
        """)
        st.info("💡 Wskaówka: Możesz także wczytać zapisany scenariusz z panelu 💾 Scenariusze")