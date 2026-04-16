"""
streamlit_app.py  –  Global News Monitor & Market Impact Analysis Dashboard

Run locally:   streamlit run streamlit_app.py
Deploy:        share.streamlit.io
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from pipeline        import run_pipeline, PipelineResult
from impact_analyzer import ImpactResult
from signal_engine   import generate_signal
from history_store   import load_history, save_history, append_run, check_and_update_outcomes

# ── Page config ───────────────────────────────────────────────
st.set_page_config(
    page_title="Global News Monitor & Market Impact",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS — matches the HTML design exactly ─────────────────────
st.markdown("""
<style>
/* ── Reset & base ── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0a0e27;
    color: #e0e6ff;
}
.block-container { padding: 0 !important; max-width: 100% !important; }
section[data-testid="stSidebar"] > div { background: #141829; }

/* ── Header ── */
.dash-header {
    background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);
    padding: 64px 28px 18px 28px;
    border-bottom: 2px solid #00d4ff;
    display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px;
}
.dash-header h1 { font-size: 24px; color: #00d4ff; font-weight: 700; letter-spacing: 0.5px; }
.status-pill {
    background: #1a1f3a; padding: 10px 16px; border-radius: 6px;
    border-left: 3px solid #ffd700; font-size: 13px; display: inline-block;
}
.status-pill strong { color: #ffd700; display: block; margin-bottom: 2px; font-size: 11px; text-transform: uppercase; }

/* ── Cards ── */
.card {
    background: #141829; border: 1px solid #1a1f3a; border-radius: 10px;
    padding: 20px; margin-bottom: 16px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.3);
    transition: border-color 0.3s, box-shadow 0.3s;
}
.card:hover { border-color: #00d4ff; box-shadow: 0 8px 32px rgba(0,212,255,0.12); }
.card-title {
    font-size: 16px; font-weight: 600; color: #00d4ff; margin-bottom: 14px;
    display: flex; align-items: center; gap: 8px;
}
.card-title::before {
    content: ''; display: inline-block; width: 4px; height: 18px;
    background: linear-gradient(180deg, #00d4ff, #ffd700); border-radius: 2px;
}

/* ── Summary boxes ── */
.summary-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 4px; }
.summary-box {
    background: #1a1f3a; border-radius: 8px; padding: 14px;
    text-align: center; border: 1px solid #1a1f3a;
    transition: border-color 0.3s;
}
.summary-box:hover { border-color: #00d4ff; }
.summary-number { font-size: 26px; font-weight: 700; color: #ffd700; margin-bottom: 4px; }
.summary-label  { font-size: 11px; color: #a8b0d0; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px; }

/* ── Stock items ── */
.stock-item {
    background: #1a1f3a; padding: 14px; border-radius: 8px; margin-bottom: 10px;
    border-left: 4px solid #00d4ff; transition: background 0.3s, transform 0.2s;
    cursor: pointer;
}
.stock-item:hover { background: #252a45; transform: translateX(4px); }
.stock-item.underreacted { border-left-color: #ffd700; background: rgba(255,215,0,0.06); }

.stock-ticker { font-weight: 700; font-size: 15px; color: #ffd700; }
.stock-name   { font-size: 12px; color: #a8b0d0; }

.price-up   { background: rgba(0,255,136,0.15); color: #00ff88; padding: 3px 10px; border-radius: 4px; font-weight: 600; font-size: 13px; }
.price-down { background: rgba(255,68,85,0.15);  color: #ff4455; padding: 3px 10px; border-radius: 4px; font-weight: 600; font-size: 13px; }
.price-flat { background: rgba(255,170,51,0.15); color: #ffaa33; padding: 3px 10px; border-radius: 4px; font-weight: 600; font-size: 13px; }

/* ── Badges ── */
.badge {
    display: inline-block; padding: 3px 10px; border-radius: 4px;
    font-size: 11px; font-weight: 600; margin: 2px 3px 2px 0;
}
.badge-extreme { background: rgba(255,68,85,0.2);   color: #ff4455; }
.badge-high    { background: rgba(255,170,51,0.2);  color: #ffaa33; }
.badge-medium  { background: rgba(100,200,255,0.2); color: #64c8ff; }
.badge-low     { background: rgba(0,255,136,0.15);  color: #00ff88; }
.badge-pos     { background: rgba(0,255,136,0.15);  color: #00ff88; }
.badge-neg     { background: rgba(255,68,85,0.15);  color: #ff4455; }
.badge-neu     { background: rgba(255,170,51,0.15); color: #ffaa33; }
.badge-teal    { background: rgba(0,212,255,0.15);  color: #00d4ff; }
.badge-gold    { background: rgba(255,215,0,0.15);  color: #ffd700; }
.badge-under   { background: rgba(255,215,0,0.2);   color: #ffd700; font-size: 10px; font-weight: 700; text-transform: uppercase; }

/* ── Signal badges ── */
.sig-strong-buy { background: rgba(0,255,136,0.15); color: #00ff88; padding: 4px 12px; border-radius: 4px; font-weight: 700; font-size: 12px; }
.sig-buy        { background: rgba(100,200,255,0.15);color: #64c8ff; padding: 4px 12px; border-radius: 4px; font-weight: 700; font-size: 12px; }
.sig-short      { background: rgba(255,68,85,0.15); color: #ff4455; padding: 4px 12px; border-radius: 4px; font-weight: 700; font-size: 12px; }
.sig-avoid      { background: rgba(255,170,51,0.15);color: #ffaa33; padding: 4px 12px; border-radius: 4px; font-weight: 700; font-size: 12px; }
.sig-notrade    { background: rgba(136,136,136,0.15);color: #888888; padding: 4px 12px; border-radius: 4px; font-weight: 700; font-size: 12px; }

/* ── Opportunity card ── */
.opp-card {
    background: #1a1f3a; padding: 16px; border-radius: 8px; margin-bottom: 12px;
    border: 2px solid #ffd700; position: relative;
}
.opp-badge {
    position: absolute; top: 10px; right: 10px;
    background: #ffd700; color: #0a0e27;
    padding: 3px 12px; border-radius: 20px;
    font-size: 10px; font-weight: 700; text-transform: uppercase;
}

/* ── Target grid ── */
.target-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
.target-box  {
    background: #0a0e27; padding: 10px; border-radius: 6px;
    border-left: 3px solid #00ff88;
}
.target-box.sl { border-left-color: #ff4455; }
.target-lbl { color: #a8b0d0; font-size: 10px; font-weight: 600; text-transform: uppercase; margin-bottom: 3px; }
.target-val { font-weight: 700; font-size: 14px; color: #e0e6ff; }

/* ── Signal card ── */
.signal-card-buy   { background: #0a1f0f; border: 1px solid #00ff88; border-left: 4px solid #00ff88; border-radius: 8px; padding: 14px; margin-bottom: 10px; }
.signal-card-short { background: #1f0a0a; border: 1px solid #ff4455; border-left: 4px solid #ff4455; border-radius: 8px; padding: 14px; margin-bottom: 10px; }
.signal-card-avoid { background: #1a140a; border: 1px solid #ffaa33; border-left: 4px solid #ffaa33; border-radius: 8px; padding: 14px; margin-bottom: 10px; }

/* ── Sector sentiment ── */
.sector-row {
    display: flex; align-items: center; gap: 12px;
    background: #1a1f3a; padding: 12px; border-radius: 8px; margin-bottom: 10px;
}
.sector-bar-track { width: 80px; height: 6px; background: #0a0e27; border-radius: 3px; overflow: hidden; }
.sector-bar-fill  { height: 100%; background: linear-gradient(90deg, #00d4ff, #ffd700); border-radius: 3px; }

/* ── News card ── */
.news-card {
    background: #1a1f3a; padding: 14px; border-radius: 8px; margin-bottom: 10px;
    border-top: 3px solid #00d4ff;
}
.news-card.neg { border-top-color: #ff4455; }
.news-card.pos { border-top-color: #00ff88; }
.news-headline { font-weight: 600; color: #e0e6ff; font-size: 13px; line-height: 1.4; margin-bottom: 8px; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: #1a1f3a; border-radius: 3px; }
::-webkit-scrollbar-thumb { background: #00d4ff; border-radius: 3px; }

/* ── Metric override ── */
[data-testid="metric-container"] {
    background: #1a1f3a; border: 1px solid #252a45; border-radius: 8px; padding: 12px 16px;
}
[data-testid="metric-container"] label { color: #a8b0d0 !important; font-size: 11px !important; text-transform: uppercase; }
[data-testid="stMetricValue"] { color: #ffd700 !important; font-weight: 700 !important; }

/* ── Sidebar ── */
section[data-testid="stSidebar"] .stButton button {
    background: #00d4ff; color: #0a0e27; font-weight: 700; border: none;
    border-radius: 6px; transition: background 0.3s;
}
section[data-testid="stSidebar"] .stButton button:hover { background: #ffd700; }

/* ── Alert box ── */
.alert-box {
    background: rgba(0,212,255,0.08); border-left: 4px solid #00d4ff;
    padding: 10px 14px; border-radius: 6px; font-size: 13px; margin-bottom: 14px;
}

/* ── Confidence bar ── */
.conf-track { display: inline-block; width: 80px; height: 6px; background: #0a0e27; border-radius: 3px; vertical-align: middle; overflow: hidden; margin-right: 6px; }
.conf-fill  { height: 100%; border-radius: 3px; }

/* Padding wrapper */
.padded { padding: 16px 24px; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
#  PIN Gate  (24-hour session via daily URL token; auto-submits at 4 digits)
# ═══════════════════════════════════════════════════════════════
import hashlib as _hashlib

def _get_pin() -> str:
    try:
        return str(st.secrets["APP_PIN"])
    except Exception:
        return ""

def _daily_token() -> str:
    """Hash of PIN + IST date — changes each midnight IST."""
    ist_today = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    return _hashlib.md5((_get_pin() + ist_today).encode()).hexdigest()[:16]

if "pin_verified" not in st.session_state:
    st.session_state["pin_verified"] = False

# Restore from URL token (persists across page refreshes for today)
_qp = st.query_params
if not st.session_state["pin_verified"] and _qp.get("t") == _daily_token():
    st.session_state["pin_verified"] = True

if not st.session_state["pin_verified"]:
    _, col_pin, _ = st.columns([1, 1, 1])
    with col_pin:
        st.markdown("""
        <div style='text-align:center;padding:60px 0 20px'>
          <div style='font-size:54px'>🔒</div>
          <h2 style='color:#00d4ff;margin:12px 0 4px'>Market Monitor</h2>
          <p style='color:#a8b0d0;font-size:13px'>Type PIN — unlocks automatically after 4 digits</p>
        </div>""", unsafe_allow_html=True)
        pin_val = st.text_input(
            "PIN", max_chars=4, type="password",
            placeholder="● ● ● ●",
            label_visibility="collapsed",
        )
        # Auto-submit when 4 digits entered (no button press needed)
        if len(pin_val) == 4:
            if pin_val == _get_pin():
                st.session_state["pin_verified"] = True
                st.query_params["t"] = _daily_token()   # persist for today
                st.rerun()
            else:
                st.error("Incorrect PIN. Please try again.")
    st.stop()


# ═══════════════════════════════════════════════════════════════
#  Constants & helpers
# ═══════════════════════════════════════════════════════════════
_IMPACT_ORDER = {"EXTREME": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
_IMPACT_SCORE = {"EXTREME": 9.5, "HIGH": 7.5, "MEDIUM": 5.5, "LOW": 3.0}

SECTOR_EMOJI = {
    "Banking": "🏦", "NBFC": "💳", "Insurance": "🛡️",
    "IT": "💻", "Tech (US)": "🖥️",
    "Pharma": "💊", "Healthcare": "🏥",
    "Energy/Conglomerate": "⚡", "Oil & Gas": "🛢️",
    "Power": "🔋", "Conglomerate": "🏢",
    "Automobile": "🚗", "Metals": "⚙️", "Mining": "⛏️",
    "FMCG": "🛒", "Infrastructure": "🏗️",
    "Real Estate": "🏠", "Telecom": "📶",
    "Metals/Mining": "🔩",
}


def badge(text: str, cls: str) -> str:
    return f'<span class="badge {cls}">{text}</span>'

def price_badge(pct: float) -> str:
    arrow = "▲" if pct >= 0.05 else ("▼" if pct <= -0.05 else "●")
    cls   = "price-up" if pct >= 0.05 else ("price-down" if pct <= -0.05 else "price-flat")
    return f'<span class="{cls}">{arrow} {pct:+.2f}%</span>'

def sig_badge(action: str) -> str:
    mapping = {
        "BUY":      ("STRONG BUY", "sig-strong-buy"),
        "SHORT":    ("SHORT / SELL", "sig-short"),
        "AVOID":    ("AVOID", "sig-avoid"),
        "NO TRADE": ("NO TRADE", "sig-notrade"),
    }
    label, cls = mapping.get(action, (action, "sig-avoid"))
    return f'<span class="{cls}">{label}</span>'

def conf_bar_html(score: int) -> str:
    color = "#00ff88" if score >= 70 else ("#ffaa33" if score >= 50 else "#ff4455")
    return (
        f'<span class="conf-track"><span class="conf-fill" '
        f'style="width:{score}%;background:{color}"></span></span>'
        f'<span style="color:{color};font-size:12px;font-weight:600">{score}%</span>'
    )

def impact_score(strength: str) -> float:
    return _IMPACT_SCORE.get(strength, 3.0)


def _render_detail_panel(r, sig=None, all_news=None):
    """Expandable detail panel for a stock — used in Top Impacted & Underreacted tabs."""
    pd_ = r.price_data
    tech = getattr(pd_, "technical", None) if pd_ else None
    sym = cur_sym(pd_)

    col_info, col_price = st.columns([3, 2])

    with col_info:
        # Why this stock was selected
        st.markdown("**🔍 Why Selected**")
        rel_color = {"positive": "#00ff88", "negative": "#ff4455", "mixed": "#ffaa33"}.get(
            (r.relation or "").lower(), "#a8b0d0")
        st.markdown(
            f"**Sector:** {r.sector} &nbsp;|&nbsp; "
            f"**Relation:** <span style='color:{rel_color}'>{r.relation or '—'}</span> &nbsp;|&nbsp; "
            f"**News type:** {r.news_type}",
            unsafe_allow_html=True,
        )
        if r.notes:
            st.caption(r.notes)

        # Triggering news
        if all_news:
            st.markdown("**📰 Triggering News**")
            for item, sent, _ in all_news[:5]:
                sent_col = "#00ff88" if "Bullish" in sent.label else (
                    "#ff4455" if "Bearish" in sent.label else "#ffaa33")
                st.markdown(
                    f"<span style='color:{sent_col};font-size:11px'>● {sent.label}</span> "
                    f"<span style='font-size:12px'>{item.title}</span>",
                    unsafe_allow_html=True,
                )
                if getattr(item, "summary", "") and item.summary != item.title:
                    st.caption(item.summary[:220])

        # Signal rationale
        if sig and getattr(sig, "rationale", ""):
            st.markdown("**💡 Signal Rationale**")
            st.info(sig.rationale, icon="🎯")

    with col_price:
        st.markdown("**📊 Price & Volume**")
        if pd_:
            chg_col = "#00ff88" if pd_.day_change_pct >= 0 else "#ff4455"
            st.markdown(
                f"| | |\n|---|---|\n"
                f"| Price | **{sym}{pd_.current_price:,.2f}** |\n"
                f"| Day Change | <span style='color:{chg_col}'>{pd_.day_change_pct:+.2f}%</span> |\n"
                f"| Prev Close | {sym}{pd_.prev_close:,.2f} |\n"
                f"| 52W High | {sym}{pd_.high_52w:,.2f} |\n"
                f"| 52W Low | {sym}{pd_.low_52w:,.2f} |\n"
                f"| Volume Ratio | {pd_.volume_ratio:.2f}x avg |",
                unsafe_allow_html=True,
            )
        else:
            st.caption("Price data unavailable")

        if tech:
            st.markdown("**📈 Technicals**")
            rsi_col = "#ff4455" if tech.rsi_14 > 70 else ("#00ff88" if tech.rsi_14 < 30 else "#ffaa33")
            trend_col = "#00ff88" if tech.trend == "Uptrend" else (
                "#ff4455" if tech.trend == "Downtrend" else "#a8b0d0")
            st.markdown(
                f"<span style='font-size:12px'>"
                f"RSI: <b style='color:{rsi_col}'>{tech.rsi_14:.1f}</b> &nbsp; "
                f"Trend: <b style='color:{trend_col}'>{tech.trend}</b>"
                f"</span>",
                unsafe_allow_html=True,
            )
            if getattr(tech, "signals", []):
                for ts in tech.signals[:3]:
                    st.caption(f"• {ts}")

def market_status() -> tuple[str, str]:
    """Return (status_label, color) based on IST time."""
    ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    wd  = ist.weekday()
    h, m = ist.hour, ist.minute
    mins = h * 60 + m
    if wd >= 5:
        return "CLOSED (Weekend)", "#ff4455"
    if 9 * 60 + 15 <= mins <= 15 * 60 + 30:
        return "OPEN 🟢", "#00ff88"
    if mins < 9 * 60 + 15:
        return f"Pre-Market (Opens {9*60+15 - mins}m)", "#ffaa33"
    return "CLOSED (After Hours)", "#ff4455"

def cur_sym(price_data) -> str:
    if price_data is None: return "₹"
    return "$" if price_data.currency == "USD" else "₹"

# Only metal futures tracked in MCX tab (no energy)
_MCX_METALS = {"SILVERMIC", "GOLDM", "COPPER", "NICKEL", "ZINC", "ALUMINIUM", "LEAD"}

def _is_mcx_metal(imp) -> bool:
    """True if this impact result is an MCX metal future."""
    return imp.symbol in _MCX_METALS or imp.sector in ("MCX/Silver","MCX/Gold","MCX/Metal")


def _calc_lookback_hours() -> int:
    """Hours from last NSE market close (15:30 IST Mon–Fri) to now."""
    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    candidate = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    # If today's close hasn't happened yet or it's weekend, go to previous weekday close
    if candidate >= now_ist or now_ist.weekday() >= 5:
        candidate -= timedelta(days=1)
        while candidate.weekday() >= 5:   # skip Saturday(5) and Sunday(6)
            candidate -= timedelta(days=1)
    delta_hours = int((now_ist - candidate).total_seconds() / 3600) + 1
    return max(6, min(delta_hours, 120))  # clamp 6 h … 120 h


def why_underreacted(imp: ImpactResult) -> str:
    reasons = []
    if imp.volume_ratio < 1.2:
        reasons.append("volume not yet confirmed — low participation")
    if imp.relation == "Direct" and abs(imp.actual_move_pct) < 1:
        reasons.append("price barely moved despite high-impact news")
    if imp.impact_strength in ("HIGH", "EXTREME"):
        reasons.append(f"{imp.impact_strength.lower()} impact news still digesting")
    return " · ".join(reasons) if reasons else "market still pricing in the event"


# Default schedule slots (used when user hasn't customised)
_DEFAULT_SLOTS = [
    ("08:25 IST", 8 * 60 + 25),     # Pre-market auto-start
    ("09:15 IST", 9 * 60 + 15),     # NSE open
    ("13:00 IST", 13 * 60 + 0),     # NSE midday
    ("15:20 IST", 15 * 60 + 20),    # NSE close
    ("17:30 IST", 17 * 60 + 30),    # MCX evening session
    ("21:00 IST", 21 * 60 + 0),     # MCX metals/energy midpoint
]

# ═══════════════════════════════════════════════════════════════
#  Sidebar
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    # ── Settings popover ──────────────────────────────────────
    with st.popover("⚙️ Settings", use_container_width=True):
        st.markdown("**Analysis**")
        hours        = st.slider("🕐 News lookback (hours)", 2, 120, 12, step=2,
                                 help="For manual runs. Scheduled runs use dynamic lookback from last market close.")
        top_n        = st.slider("📰 Max articles", 5, 100, 50, step=5,
                                 help="Scheduled runs always use max (100).")
        fetch_prices = st.toggle("📈 Live prices", value=True)
        auto_refresh = st.toggle("🔄 Auto-refresh page", value=False)
        refresh_mins = st.slider("⏱ Interval (min)", 5, 60, 15, step=5, disabled=not auto_refresh)

        st.markdown("---")
        st.markdown("**Auto-Run Schedule (IST)**")
        st.caption("Runs fire automatically when app is open near these times.")
        _custom_slots = st.session_state.get("custom_slots", list(_DEFAULT_SLOTS))
        _keep = []
        for _lbl, _mins in _custom_slots:
            _h, _m = divmod(_mins, 60)
            if st.checkbox(f"{_h:02d}:{_m:02d} IST", value=True, key=f"slot_keep_{_lbl}"):
                _keep.append((_lbl, _mins))
        if len(_keep) != len(_custom_slots):
            st.session_state["custom_slots"] = _keep
            _custom_slots = _keep
        _sc1, _sc2 = st.columns(2)
        _new_h = _sc1.number_input("Hour", 0, 23, 9, key="new_slot_h")
        _new_m = _sc2.number_input("Min",  0, 59, 15, step=5, key="new_slot_m")
        if st.button("➕ Add Slot", key="add_slot_btn"):
            _new_lbl = f"{int(_new_h):02d}:{int(_new_m):02d} IST"
            _new_mins = int(_new_h) * 60 + int(_new_m)
            if (_new_lbl, _new_mins) not in _custom_slots:
                _custom_slots = sorted(_custom_slots + [(_new_lbl, _new_mins)], key=lambda x: x[1])
                st.session_state["custom_slots"] = _custom_slots

        st.markdown("---")
        st.markdown("**Display Filters**")
        min_impact   = st.selectbox("Min impact", ["LOW", "MEDIUM", "HIGH", "EXTREME"], index=0)
        only_direct  = st.checkbox("Direct matches only")
        only_signals = st.checkbox("With signals only")

    st.markdown("---")
    run_btn = st.button("▶  Run Analysis", type="primary", use_container_width=True)

    st.markdown("---")

    # ── Fyers Live Data connection ─────────────────────────────
    try:
        from fyers_fetcher import is_configured, get_auth_url, exchange_auth_code, \
                                  auto_login, is_auto_login_configured
        import os as _os, json as _json

        def _fyers_save(token: str) -> None:
            try:
                with open(".fyers_session.json", "w") as _f:
                    _json.dump({"token": token,
                                "date": (datetime.now(timezone.utc)+timedelta(hours=5,minutes=30)).strftime("%Y-%m-%d")}, _f)
            except Exception:
                pass

        def _fyers_load() -> str:
            try:
                if _os.path.exists(".fyers_session.json"):
                    d = _json.load(open(".fyers_session.json"))
                    today = (datetime.now(timezone.utc)+timedelta(hours=5,minutes=30)).strftime("%Y-%m-%d")
                    if d.get("date") == today:
                        return d.get("token", "")
            except Exception:
                pass
            return ""

        if is_configured():
            # Restore token from file if session_state lost it (page refresh)
            if not st.session_state.get("fyers_token"):
                saved = _fyers_load()
                if saved:
                    st.session_state["fyers_token"] = saved

            # Auto-connect silently during all market hours (8:20 AM – 9:30 PM IST) on weekdays
            if not st.session_state.get("fyers_token") and is_auto_login_configured():
                _ist_ac  = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
                _ac_mins = _ist_ac.hour * 60 + _ist_ac.minute
                if _ist_ac.weekday() < 5 and 8 * 60 + 20 <= _ac_mins <= 21 * 60 + 30:
                    _tok_ac, _ = auto_login()
                    if _tok_ac:
                        st.session_state["fyers_token"] = _tok_ac
                        _fyers_save(_tok_ac)

            # Check if auth_code came back in URL after Fyers login
            qp = st.query_params
            if "auth_code" in qp and "fyers_token" not in st.session_state:
                token = exchange_auth_code(qp["auth_code"])
                if token:
                    st.session_state["fyers_token"] = token
                    _fyers_save(token)
                    st.query_params.clear()
                    st.rerun()

            if st.session_state.get("fyers_token"):
                st.markdown(
                    "<div style='color:#00ff88;font-size:12px;font-weight:600'>✅ Fyers Live Data ON</div>",
                    unsafe_allow_html=True,
                )
                if st.button("🔌 Disconnect Fyers", use_container_width=True):
                    del st.session_state["fyers_token"]
                    try: _os.remove(".fyers_session.json")
                    except Exception: pass
                    st.rerun()
            else:
                st.markdown(
                    "<div style='color:#a8b0d0;font-size:12px;font-weight:600'>📡 Fyers Real-Time Prices</div>",
                    unsafe_allow_html=True,
                )
                if is_auto_login_configured():
                    if st.button("🤖 Auto-Connect Fyers", use_container_width=True):
                        with st.spinner("Logging in via TOTP…"):
                            token, _err = auto_login()
                        if token:
                            st.session_state["fyers_token"] = token
                            _fyers_save(token)
                            st.rerun()
                        else:
                            st.error(f"Auto-login failed: {_err}")
                auth_url = get_auth_url()
                st.link_button("🔗 Manual Connect", auth_url, use_container_width=True)
                _caption = "Auto-Connect uses TOTP — no browser needed" if is_auto_login_configured() else "Log in once — token lasts till midnight"
                st.caption(_caption)
    except Exception:
        pass

    st.markdown("---")
    st.markdown(
        "<div style='font-size:11px;color:#6b7280;line-height:1.7'>"
        "📡 Sources: ET · Moneycontrol · BS · Mint · Reuters · CNBC<br>"
        "📊 Prices: Fyers (live) / Yahoo Finance (fallback)<br>"
        "🧠 NLP: VADER + Finance Lexicon<br><br>"
        "⚠️ Not financial advice."
        "</div>",
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════
#  Auto-refresh  —  JS-based timer so _check_schedule() fires
#  even if nobody interacts with the page
# ═══════════════════════════════════════════════════════════════
try:
    from streamlit_autorefresh import st_autorefresh as _st_ar
    _ar_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    _ar_mins = _ar_ist.hour * 60 + _ar_ist.minute
    _ar_weekday = _ar_ist.weekday() < 5   # Mon–Fri
    # During market/extended hours (8:20 AM – 9:30 PM IST on weekdays) refresh
    # every 5 min so scheduled slots never miss by more than 5 min.
    # Outside those hours refresh every 30 min (keeps token alive, cheaper).
    if _ar_weekday and 8 * 60 + 20 <= _ar_mins <= 21 * 60 + 30:
        _ar_interval_ms = (refresh_mins if auto_refresh else 5) * 60 * 1000
    else:
        _ar_interval_ms = 30 * 60 * 1000   # 30 min off-hours
    _st_ar(interval=_ar_interval_ms, key="sched_ar")
except ImportError:
    # Fallback: manual refresh when user has toggle ON
    if auto_refresh:
        import time as _time
        _last = st.session_state.get("_ar_last", 0)
        if _time.time() - _last >= refresh_mins * 60:
            st.session_state["_ar_last"] = _time.time()
            st.rerun()


# ═══════════════════════════════════════════════════════════════
#  App version (must be defined before header and pipeline runner)
# ═══════════════════════════════════════════════════════════════
_APP_VERSION = "v7.6"
_APP_BUILD   = "16 Apr 2026 14:41"   # auto-updated by pre-commit hook

# ═══════════════════════════════════════════════════════════════
#  Header
# ═══════════════════════════════════════════════════════════════
mkt_status, mkt_color = market_status()
_now_utc   = datetime.now(timezone.utc)
_now_ist   = _now_utc + timedelta(hours=5, minutes=30)
ist_now    = _now_ist.strftime("%d %b %Y  %H:%M IST")
refresh_ist = _now_ist.strftime("%H:%M IST")

_last_run_utc = st.session_state.get("last_run")
# If session has no last_run (e.g. after server restart), fall back to history
if not _last_run_utc:
    try:
        from history_store import get_last_run_utc as _glr
        _last_run_utc = _glr()
        if _last_run_utc:
            st.session_state["last_run"] = _last_run_utc
    except Exception:
        pass
if _last_run_utc:
    _last_run_ist = (_last_run_utc + timedelta(hours=5, minutes=30)).strftime("%d %b  %H:%M IST")
else:
    _last_run_ist = "Not run yet"

st.markdown(
    f"""
    <div class="dash-header">
      <div>
        <h1>📡 Global News Monitor & Market Impact Analysis</h1>
        <div style="color:#a8b0d0;font-size:12px;margin-top:4px">
          NSE · BSE · US Markets &nbsp;|&nbsp; Sentiment · Signals · Opportunities
        </div>
      </div>
      <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center">
        <div class="status-pill">
          <strong>Market Status</strong>
          <span style="color:{mkt_color};font-weight:600">{mkt_status}</span>
        </div>
        <div class="status-pill">
          <strong>IST</strong>{ist_now}
        </div>
        <div class="status-pill">
          <strong>Last Run</strong>{_last_run_ist}
        </div>
        <div style="background:rgba(0,212,255,0.08);border:1px solid #00d4ff;border-radius:8px;
                    padding:4px 10px;font-size:11px;color:#00d4ff;font-weight:700;line-height:1.6">
          {_APP_VERSION}
          <span style="color:#7a8bb0;font-weight:400;font-size:10px;display:block">{_APP_BUILD}</span>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ═══════════════════════════════════════════════════════════════
#  Pipeline runner
# ═══════════════════════════════════════════════════════════════
# _APP_VERSION defined above (before header). Cache bust on version change.
if st.session_state.get("_app_version") != _APP_VERSION:
    for _k in ["result", "last_run", "bt_result"]:
        st.session_state.pop(_k, None)
    st.session_state["_app_version"] = _APP_VERSION

if "result"   not in st.session_state: st.session_state["result"]   = None
if "last_run" not in st.session_state: st.session_state["last_run"] = None

def do_run(slot_label: str = "Manual"):
    # Ensure Fyers is connected before running — silently reconnect if token missing
    try:
        from fyers_fetcher import is_auto_login_configured as _fyal_cfg, auto_login as _fyal
        if not st.session_state.get("fyers_token") and _fyal_cfg():
            _t, _ = _fyal()
            if _t:
                st.session_state["fyers_token"] = _t
                _fyers_save(_t)
    except Exception:
        pass

    prog  = st.progress(0, text="Starting…")
    label = st.empty()
    def cb(step, pct):
        prog.progress(min(pct, 1.0), text=step)
        label.caption(step)
    # Scheduled runs use dynamic lookback (last market close → now) + max articles
    if slot_label == "Manual":
        _hours, _top_n = hours, top_n
    else:
        _hours = _calc_lookback_hours()
        _top_n = 100
    result = run_pipeline(hours=_hours, top_n=_top_n, fetch_prices=fetch_prices, progress_cb=cb)
    prog.empty(); label.empty()
    st.session_state["result"]   = result
    st.session_state["last_run"] = datetime.now(tz=timezone.utc)
    # Save every run to MPHR history (manual + scheduled)
    sigs_with_impact = [(s, imp) for _, imp, s in result.all_signals]
    append_run(slot_label, sigs_with_impact)

if run_btn:
    do_run()

# ═══════════════════════════════════════════════════════════════
#  Scheduled Auto-Run  (uses custom or default slots)
# ═══════════════════════════════════════════════════════════════
def _check_schedule() -> None:
    """Fire any due scheduled slot that hasn't run yet today (IST)."""
    ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    today = ist.strftime("%Y-%m-%d")
    cur   = ist.hour * 60 + ist.minute
    if "schedule_log" not in st.session_state:
        st.session_state["schedule_log"] = {}
    log = st.session_state["schedule_log"]
    # Prune stale days
    for k in [k for k in log if k != today]:
        del log[k]
    today_log = log.setdefault(today, {})
    _active_slots = st.session_state.get("custom_slots", list(_DEFAULT_SLOTS))

    # ── Catch-up: run most recent missed slot ───────────────────────
    # Fires if a scheduled slot passed without running — whether result is
    # None (fresh session) or not (tab was closed/backgrounded during window).
    # Guard: only catch up if last run was >45 min ago (avoids double-firing
    # right after a manual or scheduled run).
    _last_run_utc = st.session_state.get("last_run")
    _mins_since_run = (
        (datetime.now(tz=timezone.utc) - _last_run_utc).total_seconds() / 60
        if _last_run_utc else 9999
    )
    if _mins_since_run > 45:
        _past = [(label, sm) for label, sm in _active_slots
                 if sm <= cur and not today_log.get(label, False)]
        if _past:
            _catch_label, _ = max(_past, key=lambda x: x[1])
            today_log[_catch_label] = True
            do_run(slot_label=_catch_label)
            st.rerun()
            return

    # ── Normal window check (fires within 30 min of scheduled time) ─
    for label, slot_mins in _active_slots:
        if slot_mins <= cur < slot_mins + 30 and not today_log.get(label, False):
            today_log[label] = True   # mark before run to prevent double-fire
            do_run(slot_label=label)  # saves to MPHR history inside do_run()
            st.rerun()

_check_schedule()

result: PipelineResult | None = st.session_state.get("result")
if result is None:
    st.markdown("""
    <div style="text-align:center;padding:60px 20px">
      <div style="font-size:52px;margin-bottom:16px">📡</div>
      <h2 style="color:#00d4ff;margin-bottom:10px">Global News Monitor Ready</h2>
      <p style="color:#a8b0d0;font-size:15px;margin-bottom:24px">
        Monitors 331 NSE stocks · GoldBees · SilverBees · SilverMIC MCX<br>
        Sources: Economic Times · Moneycontrol · Reuters · CNBC + more
      </p>
      <p style="color:#ffd700;font-weight:600;font-size:14px">
        👈 Click <b>▶ Run Analysis</b> in the sidebar to start
      </p>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

for w in result.warnings:
    st.warning(w)


# ═══════════════════════════════════════════════════════════════
#  Summary stats row  (matches HTML summary-grid)
# ═══════════════════════════════════════════════════════════════
st.markdown("<div class='padded'>", unsafe_allow_html=True)

total_high = sum(1 for _, _, impacts in result.news_impacts
                 for r in impacts if r.impact_strength in ("HIGH","EXTREME") and r.relation=="Direct")
bullish    = sum(1 for _, s, _ in result.news_impacts if s.label == "Positive")
bearish    = sum(1 for _, s, _ in result.news_impacts if s.label == "Negative")
overall    = "🟢 Bullish" if bullish > bearish else ("🔴 Bearish" if bearish > bullish else "🟡 Mixed")

st.markdown(
    f"""
    <div class="card" style="margin-top:16px">
      <div class="card-title">📊 Today's Summary</div>
      <div class="summary-grid">
        <div class="summary-box"><div class="summary-number">{result.items_total}</div>
             <div class="summary-label">News Analysed</div></div>
        <div class="summary-box"><div class="summary-number">{total_high}</div>
             <div class="summary-label">Critical Impact</div></div>
        <div class="summary-box"><div class="summary-number">{len(result.underreacted)}</div>
             <div class="summary-label">Underreacted Opps</div></div>
        <div class="summary-box"><div class="summary-number">{len(result.all_signals)}</div>
             <div class="summary-label">Trading Signals</div></div>
        <div class="summary-box">
             <div class="summary-number">{sum(1 for _,r,s in result.all_signals if s.action=="BUY")}</div>
             <div class="summary-label">Buy Signals</div></div>
        <div class="summary-box"><div class="summary-number" style="font-size:16px">{overall}</div>
             <div class="summary-label">Market Sentiment</div></div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=300, show_spinner=False)
def _mphr_live_price(symbol: str) -> float:
    """Fetch latest NSE price for MPHR current-price column (cached 5 min)."""
    try:
        import yfinance as yf
        t = yf.Ticker(f"{symbol}.NS")
        p = getattr(t.fast_info, "last_price", None)
        if p and float(p) > 0:
            return round(float(p), 2)
        # fallback to latest daily close
        h = t.history(period="2d", interval="1d", auto_adjust=True)
        if not h.empty:
            return round(float(h["Close"].iloc[-1]), 2)
        return 0.0
    except Exception:
        return 0.0


@st.cache_data(ttl=300, show_spinner=False)
def _mcx_live_price(symbol: str) -> float:
    """Fetch latest MCX futures price via COMEX proxy + conversion (cached 5 min)."""
    try:
        from impact_analyzer import _MCX_PROXY, _MCX_CONV, _MCX_LOCAL_PREMIUM, _fetch_usd_inr
        import yfinance as yf
        proxy = _MCX_PROXY.get(symbol)
        if not proxy:
            return 0.0
        fi = yf.Ticker(proxy).fast_info
        raw = float(fi.last_price) if getattr(fi, "last_price", None) else 0.0
        if raw <= 0:
            return 0.0
        if symbol in _MCX_CONV:
            usd_inr = _fetch_usd_inr()
            raw = raw * _MCX_CONV[symbol] * usd_inr * _MCX_LOCAL_PREMIUM.get(symbol, 1.0)
        return round(raw, 2)
    except Exception:
        return 0.0


# ═══════════════════════════════════════════════════════════════
#  Main tabs
# ═══════════════════════════════════════════════════════════════
tab_impact, tab_opps, tab_signals, tab_mcx, tab_sectors, tab_news, \
tab_nse, tab_journal, tab_backtest, tab_history, tab_silvermic = st.tabs([
    "🔥 Top Impacted",
    "⚡ Underreacted",
    "🎯 Trade Signals",
    "🏅 MCX Metals",
    "📈 Sector Sentiment",
    "📰 News Feed",
    "📊 NSE Data",
    "📓 Trade Journal",
    "🔬 Backtest",
    "📊 MPHR",
    "🥈 SILVERMIC",
])


# ───────────────────────────────────────────────────────────────
#  TAB 1  —  Top 5 Most Impacted Stocks
# ───────────────────────────────────────────────────────────────
with tab_impact:
    col_stocks, col_chart = st.columns([1, 1], gap="medium")

    with col_stocks:
        st.markdown('<div class="card"><div class="card-title">🔥 Top 5 Impacted Stocks</div>',
                    unsafe_allow_html=True)

        if not result.top5:
            st.info("No direct matches yet — try increasing lookback hours.")
        else:
            # Build a lookup: symbol → all (NewsItem, sentiment, ImpactResult) tuples
            _sym_news: dict = {}
            for _ni, _ns, _ni_imps in result.news_impacts:
                for _ni_r in _ni_imps:
                    _sym_news.setdefault(_ni_r.symbol, []).append((_ni, _ns, _ni_r))

            for rank, (headline, r) in enumerate(result.top5, 1):
                pd_  = r.price_data
                sym  = cur_sym(pd_)
                imp_s = impact_score(r.impact_strength)
                is_under = r.reaction_status == "Underreacted"
                price_str = f"{sym}{pd_.current_price:,.2f}" if pd_ else "—"
                act_pct   = r.actual_move_pct if pd_ else 0
                sec_emoji = SECTOR_EMOJI.get(r.sector, "📌")
                under_b   = '<span class="badge badge-under">UNDERREACTED</span>' if is_under else ""
                imp_cls   = {"EXTREME":"badge-extreme","HIGH":"badge-high",
                             "MEDIUM":"badge-medium","LOW":"badge-low"}.get(r.impact_strength,"badge-teal")

                st.markdown(
                    f'<div class="stock-item {"underreacted" if is_under else ""}">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
                    f'  <div>'
                    f'    <span style="color:#a8b0d0;font-size:12px;margin-right:6px">#{rank}</span>'
                    f'    <span class="stock-ticker">{r.symbol}</span>'
                    f'    <span class="stock-name"> — {r.name}</span>'
                    f'  </div>'
                    f'  <div style="display:flex;gap:8px;align-items:center">'
                    f'    {price_badge(act_pct)}'
                    f'    <span style="color:#e0e6ff;font-size:13px">{price_str}</span>'
                    f'  </div>'
                    f'</div>'
                    f'<div style="font-size:12px;color:#a8b0d0;margin-bottom:8px">{sec_emoji} {r.sector}</div>'
                    f'<div style="font-size:12px;color:#a8b0d0;margin-bottom:8px;font-style:italic">'
                    f'  📰 {headline[:70]}</div>'
                    f'<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">'
                    f'  <span class="badge {imp_cls}">Impact: {imp_s}/10</span>'
                    f'  {badge(r.impact_strength, imp_cls)}'
                    f'  {badge("Expected "+str(r.expected_move_pct)+"%","badge-teal")}'
                    f'  {under_b}'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                with st.expander(f"🔍 {r.symbol} — full analysis & news"):
                    _render_detail_panel(r, sig=None, all_news=_sym_news.get(r.symbol, []))
        st.markdown('</div>', unsafe_allow_html=True)

    with col_chart:
        st.markdown('<div class="card"><div class="card-title">📊 Actual vs Expected Move</div>',
                    unsafe_allow_html=True)
        if result.top5:
            syms  = [r.symbol for _, r in result.top5]
            act   = [r.actual_move_pct for _, r in result.top5]
            exp   = [r.expected_move_pct for _, r in result.top5]
            scores= [impact_score(r.impact_strength) for _, r in result.top5]

            fig = go.Figure()
            fig.add_trace(go.Bar(
                name="Actual Move", x=syms, y=act,
                marker_color=["#00ff88" if v >= 0 else "#ff4455" for v in act],
                text=[f"{v:+.2f}%" for v in act], textposition="outside",
            ))
            fig.add_trace(go.Bar(
                name="Expected Move", x=syms, y=exp,
                marker_color=["rgba(255,215,0,0.4)"]*len(exp),
                text=[f"{v:+.1f}%" for v in exp], textposition="outside",
            ))
            fig.update_layout(
                barmode="group", plot_bgcolor="#1a1f3a", paper_bgcolor="#141829",
                font=dict(color="#a8b0d0", size=12),
                legend=dict(orientation="h", y=1.08, font=dict(color="#e0e6ff")),
                xaxis=dict(gridcolor="#252a45", tickfont=dict(color="#ffd700", size=12)),
                yaxis=dict(gridcolor="#252a45", ticksuffix="%", tickfont=dict(color="#a8b0d0")),
                margin=dict(t=40, b=20, l=40, r=20), height=320,
            )
            st.plotly_chart(fig, use_container_width=True)

            # Impact score gauge row
            st.markdown("<div style='margin-top:8px'>", unsafe_allow_html=True)
            cols_g = st.columns(len(result.top5))
            for col, (_, r) in zip(cols_g, result.top5):
                s = impact_score(r.impact_strength)
                col.metric(r.symbol, f"{s}/10", r.impact_strength)
            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)


# ───────────────────────────────────────────────────────────────
#  TAB 2  —  Underreacted Opportunities
# ───────────────────────────────────────────────────────────────
with tab_opps:
    st.markdown(
        '<div class="alert-box">💡 <strong>TRADE THESE NOW:</strong> '
        'News impact is significantly larger than price reaction. '
        'Volume not yet confirmed — smart money entry window open.</div>',
        unsafe_allow_html=True,
    )

    if not result.underreacted:
        st.success("✅ No underreaction detected — market has fully priced in major news.")
    else:
        col_l, col_r = st.columns(2, gap="medium")
        for i, (item, imp, sig) in enumerate(result.underreacted[:6]):
            col = col_l if i % 2 == 0 else col_r
            gap  = abs(imp.expected_move_pct - imp.actual_move_pct)
            sym  = cur_sym(imp.price_data)
            price_now = f"{sym}{imp.price_data.current_price:,.2f}" if imp.price_data else "—"
            act_col  = "#00ff88" if sig.action == "BUY" else ("#888" if sig.action == "NO TRADE" else "#ff4455")
            why = why_underreacted(imp)
            imp_s = impact_score(imp.impact_strength)

            t1_str  = f"{sym}{sig.target1:,.2f}"  if sig.target1 > 0  else "—"
            t2_str  = f"{sym}{sig.target2:,.2f}"  if sig.target2 > 0  else "—"
            sl_str  = f"{sym}{sig.stop_loss:,.2f}" if sig.stop_loss > 0 else "—"
            ent_str = f"{sym}{sig.entry_low:,.2f}–{sym}{sig.entry_high:,.2f}" if sig.entry_low > 0 else "—"

            with col:
                st.markdown(
                    f'<div class="opp-card">'
                    f'<div class="opp-badge">UNDERREACTED</div>'
                    f'<div style="display:flex;align-items:baseline;gap:10px;margin-bottom:8px;padding-right:100px">'
                    f'  <span class="stock-ticker">{imp.symbol}</span>'
                    f'  <span class="stock-name">{imp.name}</span>'
                    f'</div>'
                    f'<div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:10px">'
                    f'  <div><div style="color:#6b7280;font-size:10px;text-transform:uppercase">Price</div>'
                    f'       <div style="font-weight:700;font-size:16px;color:#e0e6ff">{price_now}</div></div>'
                    f'  <div><div style="color:#6b7280;font-size:10px;text-transform:uppercase">Expected</div>'
                    f'       <div style="font-weight:700;font-size:16px;color:#ffaa33">{imp.expected_move_pct:+.1f}%</div></div>'
                    f'  <div><div style="color:#6b7280;font-size:10px;text-transform:uppercase">Actual</div>'
                    f'       <div style="font-weight:700;font-size:16px;color:{"#00ff88" if imp.actual_move_pct>=0 else "#ff4455"}">{imp.actual_move_pct:+.2f}%</div></div>'
                    f'  <div><div style="color:#6b7280;font-size:10px;text-transform:uppercase">Edge Gap</div>'
                    f'       <div style="font-weight:700;font-size:16px;color:#ffd700">{gap:.1f}%</div></div>'
                    f'  <div><div style="color:#6b7280;font-size:10px;text-transform:uppercase">Impact</div>'
                    f'       <div style="font-weight:700;font-size:16px;color:#00d4ff">{imp_s}/10</div></div>'
                    f'</div>'
                    f'<div style="font-size:12px;color:#a8b0d0;margin-bottom:10px;padding:8px;'
                    f'background:#0a0e27;border-radius:6px">'
                    f'  💡 <strong>Why underreacted:</strong> {why}</div>'
                    f'<div class="target-grid">'
                    f'  <div class="target-box"><div class="target-lbl">🎯 Entry</div>'
                    f'       <div class="target-val" style="font-size:12px">{ent_str}</div></div>'
                    f'  <div class="target-box sl"><div class="target-lbl">🛑 Stop Loss</div>'
                    f'       <div class="target-val" style="color:#ff4455">{sl_str}</div></div>'
                    f'  <div class="target-box"><div class="target-lbl">🎯 Target 1</div>'
                    f'       <div class="target-val" style="color:#00ff88">{t1_str}</div></div>'
                    f'  <div class="target-box"><div class="target-lbl">🚀 Target 2</div>'
                    f'       <div class="target-val" style="color:#00ff88">{t2_str}</div></div>'
                    f'</div>'
                    f'<div style="margin-top:12px;display:flex;justify-content:space-between;align-items:center">'
                    f'  <div style="color:{act_col};font-weight:700;font-size:14px">🎯 {sig.action}</div>'
                    f'  <div>R:R &nbsp;<span style="color:#ffd700;font-weight:700">{sig.risk_reward:.1f}x</span></div>'
                    f'  <div>{conf_bar_html(sig.confidence)}</div>'
                    f'</div>'
                    f'<div style="margin-top:8px;font-size:11px;color:#6b7280;font-style:italic">'
                    f'  📰 {item.title[:90]}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                # Build news list for this stock
                _opp_news = [(ni, ns, ni_r)
                             for ni, ns, ni_imps in result.news_impacts
                             for ni_r in ni_imps if ni_r.symbol == imp.symbol]
                with st.expander(f"🔍 {imp.symbol} — full analysis & news"):
                    _render_detail_panel(imp, sig=sig, all_news=_opp_news)

        # Summary table
        with st.expander("📋 All Underreacted — Quick Table"):
            rows = [{
                "Symbol":    sig.symbol, "Name": imp.name, "Action": sig.action,
                "Expected":  f"{imp.expected_move_pct:+.1f}%",
                "Actual":    f"{imp.actual_move_pct:+.2f}%",
                "Gap":       f"{abs(imp.expected_move_pct-imp.actual_move_pct):.1f}%",
                "Vol":       f"{imp.volume_ratio:.1f}x",
                "R:R":       f"{sig.risk_reward:.1f}x",
                "Confidence":f"{sig.confidence}%",
                "Horizon":   sig.time_horizon,
            } for _, imp, sig in result.underreacted]
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ───────────────────────────────────────────────────────────────
#  TAB 3  —  Trading Signals  (Equity / NSE only)
# ───────────────────────────────────────────────────────────────
with tab_signals:
    if not result.all_signals:
        st.info("No signals — try lowering min impact or extending lookback hours.")
    else:
        fc1, fc2, fc3 = st.columns(3)
        sig_action   = fc1.multiselect("Action", ["BUY","SHORT","AVOID"], default=["BUY","SHORT"])
        sig_min_conf = fc2.slider("Min confidence", 0, 100, 40, step=5)
        sig_edges    = fc3.multiselect("Edge",
                         ["Underreaction","Momentum","Macro","Mean-Reversion"],
                         default=["Underreaction","Momentum","Macro","Mean-Reversion"])

        # Equity only (MCX metals handled in dedicated tab)
        _eq_signals = [(item,imp,sig) for item,imp,sig in result.all_signals
                       if not _is_mcx_metal(imp)]

        buys    = [(item,imp,sig) for item,imp,sig in _eq_signals
                   if sig.action=="BUY"   and sig.confidence>=sig_min_conf and sig.edge_type in sig_edges]
        shorts  = [(item,imp,sig) for item,imp,sig in _eq_signals
                   if sig.action=="SHORT" and sig.confidence>=sig_min_conf and sig.edge_type in sig_edges]
        avoids  = [(item,imp,sig) for item,imp,sig in _eq_signals
                   if sig.action=="AVOID" and sig.confidence>=sig_min_conf and sig.edge_type in sig_edges]
        notrades = [(item,imp,sig) for item,imp,sig in _eq_signals
                    if sig.action=="NO TRADE"]

        sub1, sub2, sub3, sub4 = st.tabs([
            f"BUY ({len(buys)})",
            f"SHORT ({len(shorts)})",
            f"AVOID ({len(avoids)})",
            f"NO TRADE ({len(notrades)})",
        ])

        def render_signal_cards(signals, card_class):
            if not signals:
                st.info("No signals in this category.")
                return
            for _card_idx, (item, imp, sig) in enumerate(signals):
                sym      = cur_sym(imp.price_data)
                is_under = imp.reaction_status == "Underreacted"
                tech     = getattr(imp.price_data, "technical", None) if imp.price_data else None

                # ── Badge section ───────────────────────────────
                # NO TRADE cards: mute all badge colors so nothing looks actionable
                is_no_trade = sig.action == "NO TRADE"
                def _bc(active_color: str) -> str:
                    """Badge color: grey if NO TRADE, else original color."""
                    return "#555" if is_no_trade else active_color
                def _tc(active_color: str) -> str:
                    """Text color: grey if NO TRADE, else original color."""
                    return "#888" if is_no_trade else active_color

                rsi_html = ""
                if tech:
                    # ── RSI badge (context-aware color) ────────
                    # Oversold in downtrend = falling knife (orange warning), not a green signal
                    if tech.rsi_14 < 35:
                        if sig.action == "BUY" and tech.trend in ("Uptrend", "Sideways"):
                            _raw_rsi_col = "#00ff88"
                            rsi_label = "Oversold"
                        else:
                            _raw_rsi_col = "#ffaa33"
                            rsi_label = "Oversold \u26a0"
                    elif tech.rsi_14 > 65:
                        if sig.action == "SHORT" and tech.trend in ("Downtrend", "Sideways"):
                            _raw_rsi_col = "#ff4455"
                            rsi_label = "Overbought"
                        else:
                            _raw_rsi_col = "#ffaa33"
                            rsi_label = "Overbought \u26a0"
                    else:
                        _raw_rsi_col = "#a8b0d0"
                        rsi_label = "Neutral"
                    rsi_color = _bc(_raw_rsi_col)
                    rsi_txt   = _tc(_raw_rsi_col)
                    trend_icon = {"Uptrend": "\u2191", "Downtrend": "\u2193", "Sideways": "\u2192"}.get(tech.trend, "\u2192")
                    rsi_html = (
                        f'<span style="background:rgba(255,255,255,0.05);border:1px solid {rsi_color};'
                        f'color:{rsi_txt};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600">'
                        f'RSI {tech.rsi_14:.0f} {rsi_label}</span> '
                        f'<span style="background:rgba(255,255,255,0.05);border:1px solid {_bc("#a8b0d0")};'
                        f'color:{_tc("#a8b0d0")};padding:2px 8px;border-radius:4px;font-size:11px">'
                        f'{trend_icon} {tech.trend}</span> '
                    )
                    if tech.near_support:
                        rsi_html += f'<span style="background:rgba(0,255,136,0.1);border:1px solid {_bc("#00ff88")};color:{_tc("#00ff88")};padding:2px 8px;border-radius:4px;font-size:11px">\U0001f4cd Near Support</span> '
                    if tech.near_resistance:
                        rsi_html += f'<span style="background:rgba(255,68,85,0.1);border:1px solid {_bc("#ff4455")};color:{_tc("#ff4455")};padding:2px 8px;border-radius:4px;font-size:11px">\U0001f4cd Near Resistance</span> '
                    if tech.bb_squeeze:
                        rsi_html += f'<span style="background:rgba(255,215,0,0.1);border:1px solid {_bc("#ffd700")};color:{_tc("#ffd700")};padding:2px 8px;border-radius:4px;font-size:11px">\u26a1 BB Squeeze</span> '

                    # ── MACD badge ──────────────────────────────
                    if getattr(tech, "macd_line", 0.0) != 0.0:
                        _raw_mc = "#00ff88" if tech.macd_bullish else "#ff4455"
                        _ma = "\u2191" if tech.macd_bullish else "\u2193"
                        _ml = "Bullish" if tech.macd_bullish else "Bearish"
                        rsi_html += (
                            f'<span style="background:rgba(255,255,255,0.05);border:1px solid {_bc(_raw_mc)};'
                            f'color:{_tc(_raw_mc)};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600">'
                            f'MACD {_ma} {_ml}</span> '
                        )

                    # ── Stochastic badge ────────────────────────
                    if getattr(tech, "stoch_oversold", False):
                        rsi_html += (
                            f'<span style="background:rgba(0,255,136,0.1);border:1px solid {_bc("#00ff88")};'
                            f'color:{_tc("#00ff88")};padding:2px 8px;border-radius:4px;font-size:11px">'
                            f'Stoch {tech.stoch_k:.0f} Oversold</span> '
                        )
                    elif getattr(tech, "stoch_overbought", False):
                        rsi_html += (
                            f'<span style="background:rgba(255,68,85,0.1);border:1px solid {_bc("#ff4455")};'
                            f'color:{_tc("#ff4455")};padding:2px 8px;border-radius:4px;font-size:11px">'
                            f'Stoch {tech.stoch_k:.0f} Overbought</span> '
                        )

                    # ── OBV badge ───────────────────────────────
                    _obv = getattr(tech, "obv_trend", "Neutral")
                    if _obv == "Rising":
                        rsi_html += f'<span style="background:rgba(0,255,136,0.1);border:1px solid {_bc("#00ff88")};color:{_tc("#00ff88")};padding:2px 8px;border-radius:4px;font-size:11px">OBV \u2191 Rising</span> '
                    elif _obv == "Falling":
                        rsi_html += f'<span style="background:rgba(255,68,85,0.1);border:1px solid {_bc("#ff4455")};color:{_tc("#ff4455")};padding:2px 8px;border-radius:4px;font-size:11px">OBV \u2193 Falling</span> '

                    # ── ATR badge ───────────────────────────────
                    _atr_pct = getattr(tech, "atr_pct", 0.0)
                    if _atr_pct > 2.0:
                        rsi_html += (
                            f'<span style="background:rgba(255,215,0,0.1);border:1px solid {_bc("#ffd700")};'
                            f'color:{_tc("#ffd700")};padding:2px 8px;border-radius:4px;font-size:11px">'
                            f'ATR {_atr_pct:.1f}% Vol</span> '
                        )

                    # ── ADX badge ───────────────────────────────
                    _adx_v = getattr(tech, "adx_14", 0.0)
                    if _adx_v > 0:
                        _raw_adx_col = "#00ff88" if getattr(tech, "adx_trending", False) else "#a8b0d0"
                        _adx_lbl = "Trending" if getattr(tech, "adx_trending", False) else "Weak"
                        rsi_html += (
                            f'<span style="background:rgba(255,255,255,0.05);border:1px solid {_bc(_raw_adx_col)};'
                            f'color:{_tc(_raw_adx_col)};padding:2px 8px;border-radius:4px;font-size:11px">'
                            f'ADX {_adx_v:.0f} {_adx_lbl}</span> '
                        )

                    # ── SuperTrend badge ─────────────────────────
                    _st = getattr(tech, "supertrend_bullish", None)
                    if _st is not None:
                        _raw_st_col = "#00ff88" if _st else "#ff4455"
                        _st_lbl = "↑ Bull" if _st else "↓ Bear"
                        rsi_html += (
                            f'<span style="background:rgba(255,255,255,0.05);border:1px solid {_bc(_raw_st_col)};'
                            f'color:{_tc(_raw_st_col)};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600">'
                            f'SuperTrend {_st_lbl}</span> '
                        )

                    # ── CCI badge ────────────────────────────────
                    _cci_v = getattr(tech, "cci_20", 0.0)
                    if getattr(tech, "cci_oversold", False):
                        rsi_html += (
                            f'<span style="background:rgba(0,255,136,0.1);border:1px solid {_bc("#00ff88")};'
                            f'color:{_tc("#00ff88")};padding:2px 8px;border-radius:4px;font-size:11px">'
                            f'CCI {_cci_v:.0f} Oversold</span> '
                        )
                    elif getattr(tech, "cci_overbought", False):
                        rsi_html += (
                            f'<span style="background:rgba(255,68,85,0.1);border:1px solid {_bc("#ff4455")};'
                            f'color:{_tc("#ff4455")};padding:2px 8px;border-radius:4px;font-size:11px">'
                            f'CCI {_cci_v:.0f} Overbought</span>'
                        )

                    # ── VWAP badge ──────────────────────────────────
                    _vwap = getattr(tech, "vwap_5d", 0.0)
                    if _vwap > 0:
                        _vw_above = getattr(tech, "price_above_vwap", False)
                        _raw_vw_col = "#00ff88" if _vw_above else "#ff4455"
                        _vw_lbl = "Above" if _vw_above else "Below"
                        rsi_html += (
                            f'<span style="background:rgba(255,255,255,0.05);border:1px solid {_bc(_raw_vw_col)};'
                            f'color:{_tc(_raw_vw_col)};padding:2px 8px;border-radius:4px;font-size:11px">'
                            f'VWAP {_vw_lbl}</span> '
                        )

                    # ── Market Regime badge ─────────────────────────
                    _regime = getattr(tech, "market_regime", "Unknown")
                    if _regime != "Unknown":
                        _reg_colors = {"Trending": "#00ff88", "Sideways": "#ffaa33", "HighVol": "#ff4455", "LowLiquidity": "#888"}
                        _raw_reg_col = _reg_colors.get(_regime, "#a8b0d0")
                        rsi_html += (
                            f'<span style="background:rgba(255,255,255,0.05);border:1px solid {_bc(_raw_reg_col)};'
                            f'color:{_tc(_raw_reg_col)};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600">'
                            f'{_regime}</span> '
                        )

                    # ── Volume analysis badges ──────────────────────
                    if getattr(tech, "volume_spike", False):
                        rsi_html += (
                            f'<span style="background:rgba(0,255,136,0.15);border:1px solid {_bc("#00ff88")};'
                            f'color:{_tc("#00ff88")};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600">'
                            'VOL SPIKE</span> '
                        )
                    if getattr(tech, "pre_breakout", False):
                        rsi_html += (
                            f'<span style="background:rgba(255,215,0,0.15);border:1px solid {_bc("#ffd700")};'
                            f'color:{_tc("#ffd700")};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600">'
                            'PRE-BREAKOUT</span> '
                        )

                # ── Corporate event warning ────────────────────
                event_html = ""
                corp_events = getattr(result, "corporate_events", [])
                sym_events  = [e for e in corp_events if e.get("symbol","").upper() == imp.symbol.upper()]
                if sym_events:
                    ev = sym_events[0]
                    event_html = (
                        f'<div style="background:rgba(255,170,51,0.12);border:1px solid #ffaa33;'
                        f'border-radius:6px;padding:6px 10px;margin:6px 0;font-size:11px;color:#ffaa33">'
                        f'⚠️ <b>{ev["purpose"]}</b> — {ev["ex_date"]} '
                        f'({ev["days_away"]} day{"s" if ev["days_away"]!=1 else ""} away) — trade cautiously</div>'
                    )

                price_html = ""
                if sig.entry_low > 0:
                    _lot_s = getattr(imp.price_data, "lot_size", 1) if imp.price_data else 1
                    _lot_u = getattr(imp.price_data, "lot_unit", "")  if imp.price_data else ""
                    _lot_cell = (
                        f'<div><div style="color:#6b7280;font-size:10px;text-transform:uppercase">Lot Size</div>'
                        f'<div style="font-weight:700;color:#00d4ff">{_lot_s} {_lot_u}/lot</div></div>'
                    ) if _lot_s > 1 else ""
                    price_html = (
                        f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:10px 0 8px">'
                        f'<div><div style="color:#6b7280;font-size:10px;text-transform:uppercase">Entry</div>'
                        f'<div style="font-weight:700">{sym}{sig.entry_low:,.2f}–{sym}{sig.entry_high:,.2f}</div></div>'
                        f'<div><div style="color:#6b7280;font-size:10px;text-transform:uppercase">Stop Loss</div>'
                        f'<div style="font-weight:700;color:#ff4455">{sym}{sig.stop_loss:,.2f}</div></div>'
                        f'<div><div style="color:#6b7280;font-size:10px;text-transform:uppercase">Target 1</div>'
                        f'<div style="font-weight:700;color:#00ff88">{sym}{sig.target1:,.2f}</div></div>'
                        f'<div><div style="color:#6b7280;font-size:10px;text-transform:uppercase">Target 2</div>'
                        f'<div style="font-weight:700;color:#00ff88">{sym}{sig.target2:,.2f}</div></div>'
                        f'<div><div style="color:#6b7280;font-size:10px;text-transform:uppercase">R:R Ratio</div>'
                        f'<div style="font-weight:700;color:#ffd700">{sig.risk_reward:.1f}x</div></div>'
                        f'<div><div style="color:#6b7280;font-size:10px;text-transform:uppercase">Horizon</div>'
                        f'<div style="font-weight:700;color:#00d4ff;font-size:11px">{sig.time_horizon}</div></div>'
                        f'{_lot_cell}'
                        f'</div>'
                    )
                under_b = '<span class="badge badge-under">★ UNDERREACTION</span>' if is_under else ""
                imp_s   = impact_score(imp.impact_strength)
                imp_cls = {"EXTREME":"badge-extreme","HIGH":"badge-high",
                           "MEDIUM":"badge-medium","LOW":"badge-low"}.get(imp.impact_strength,"badge-teal")

                # ── Log to journal button ──────────────────────
                log_key = f"log_{card_class}_{_card_idx}_{sig.symbol}"
                st.markdown(
                    f'<div class="{card_class}">'
                    f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">'
                    f'  {sig_badge(sig.action)}'
                    f'  <span style="font-size:17px;font-weight:700;color:#ffd700">{sig.symbol}</span>'
                    f'  <span style="color:#a8b0d0">— {sig.name}</span>'
                    f'  {under_b}'
                    f'</div>'
                    f'<div style="margin-bottom:6px">'
                    f'  {badge(f"Impact {imp_s}/10", imp_cls)}'
                    f'  {badge(imp.impact_strength, imp_cls)}'
                    f'  {badge(imp.sentiment_label, "badge-pos" if imp.sentiment_label=="Positive" else "badge-neg")}'
                    f'  {badge(getattr(imp, "news_type", "Ongoing"), "badge-neg" if getattr(imp, "news_type", "Ongoing") == "Rumor" else ("badge-pos" if getattr(imp, "news_type", "Ongoing") == "Breaking" else "badge-teal"))}'
                    f'  {badge(sig.edge_type, "badge-teal")}'
                    f'  {badge(imp.sector, "badge-gold")}'
                    f'</div>'
                    f'<div style="margin:4px 0 6px">{rsi_html}</div>'
                    f'{event_html}'
                    f'{price_html}'
                    f'<div style="display:flex;align-items:center;gap:16px;margin-top:8px">'
                    f'  <div><span style="color:#6b7280;font-size:11px">CONFIDENCE &nbsp;</span>'
                    f'       {conf_bar_html(sig.confidence)}</div>'
                    f'</div>'
                    f'<div style="margin-top:8px;font-size:11px;color:#6b7280;font-style:italic">{sig.rationale}</div>'
                    f'<div style="margin-top:6px;font-size:11px;color:#4a5568">'
                    f'  📰 {item.title[:95]}  ·  {item.source}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if sig.entry_low > 0:
                    if st.button(f"📓 Log to Journal", key=log_key):
                        from trade_journal import add_trade
                        add_trade(sig.symbol, sig.name, sig.action,
                                  sig.entry_low, sig.stop_loss, sig.target1, sig.target2,
                                  sig.risk_reward, sig.confidence, sig.edge_type)
                        st.success(f"✅ {sig.symbol} logged to Trade Journal")

        with sub1: render_signal_cards(buys,     "signal-card-buy")
        with sub2: render_signal_cards(shorts,   "signal-card-short")
        with sub3: render_signal_cards(avoids,   "signal-card-avoid")
        with sub4: render_signal_cards(notrades, "signal-card-avoid")


# ───────────────────────────────────────────────────────────────
#  TAB 3b  —  MCX Metals (Gold, Silver, Copper, Nickel, Zinc…)
# ───────────────────────────────────────────────────────────────
with tab_mcx:
    _mcx_signals = [(item, imp, sig) for item, imp, sig in result.all_signals
                    if _is_mcx_metal(imp)]

    # Build MCX impacts deduped by symbol (keep highest impact strength per symbol)
    _mcx_sym_best: dict = {}  # symbol → (item, sent, imp)
    for _mi_item, _mi_sent, _mi_impacts in result.news_impacts:
        for _mi_r in _mi_impacts:
            if not _is_mcx_metal(_mi_r):
                continue
            _prev = _mcx_sym_best.get(_mi_r.symbol)
            if _prev is None or (
                _IMPACT_ORDER.get(_mi_r.impact_strength, 0) >
                _IMPACT_ORDER.get(_prev[2].impact_strength, 0)
            ):
                _mcx_sym_best[_mi_r.symbol] = (_mi_item, _mi_sent, _mi_r)
    _mcx_impacts = list(_mcx_sym_best.values())
    _mcx_impacts.sort(key=lambda x: _IMPACT_ORDER.get(x[2].impact_strength, 0), reverse=True)

    if not _mcx_signals and not _mcx_impacts:
        st.info("No MCX metal signals in current analysis. Tracked metals: "
                + ", ".join(sorted(_MCX_METALS)))
    else:
        if _mcx_impacts:
            st.markdown("#### 🔥 Top Impacted Metals")
            for _mi_item, _mi_sent, _mi in _mcx_impacts[:8]:
                _lot_s  = getattr(_mi.price_data, "lot_size", 1) if _mi.price_data else 1
                _lot_u  = getattr(_mi.price_data, "lot_unit", "")  if _mi.price_data else ""
                _price  = (_mi.price_data.current_price
                           if _mi.price_data and _mi.price_data.current_price > 0
                           else _mcx_live_price(_mi.symbol))
                _cv     = round(_price * _lot_s, 0) if _lot_s > 1 and _price > 0 else 0
                _imp_c  = {"EXTREME":"badge-extreme","HIGH":"badge-high",
                           "MEDIUM":"badge-medium","LOW":"badge-low"}.get(_mi.impact_strength,"badge-teal")
                _lot_info = f" · Lot: {_lot_s} {_lot_u}" if _lot_s > 1 else ""
                _cv_info  = f" · Contract ₹{_cv:,.0f}" if _cv > 0 else ""
                _mv_col   = "#00ff88" if _mi.actual_move_pct >= 0 else "#ff4455"
                _price_str = f"₹{_price:,.1f}" if _price > 0 else "—"
                st.markdown(
                    f'<div class="card" style="margin-bottom:8px">'
                    f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
                    f'  {badge(_mi.impact_strength, _imp_c)}'
                    f'  <span style="font-weight:700;color:#ffd700">{_mi.symbol}</span>'
                    f'  <span style="color:#a8b0d0">— {_mi.name}</span>'
                    f'  {badge(_mi.sector, "badge-gold")}'
                    f'</div>'
                    f'<div style="margin-top:4px;font-size:12px;color:#a8b0d0">'
                    f'  {_price_str}{_lot_info}{_cv_info}'
                    f'  · Move: <span style="color:{_mv_col}">{_mi.actual_move_pct:+.2f}%</span>'
                    f'  · Expected: {_mi.expected_move_pct:+.1f}%'
                    f'</div>'
                    f'<div style="margin-top:4px;font-size:11px;color:#6b7280">{_mi_item.title[:90]}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        if _mcx_signals:
            st.markdown("#### 🎯 Metal Signals")
            _mb = [(item, imp, sig) for item, imp, sig in _mcx_signals if sig.action == "BUY"]
            _ms = [(item, imp, sig) for item, imp, sig in _mcx_signals if sig.action == "SHORT"]
            _ma = [(item, imp, sig) for item, imp, sig in _mcx_signals if sig.action == "AVOID"]
            _mn = [(item, imp, sig) for item, imp, sig in _mcx_signals if sig.action == "NO TRADE"]
            _mt1, _mt2, _mt3, _mt4 = st.tabs([
                f"BUY ({len(_mb)})", f"SHORT ({len(_ms)})",
                f"AVOID ({len(_ma)})", f"NO TRADE ({len(_mn)})",
            ])
            with _mt1: render_signal_cards(_mb, "signal-card-buy")
            with _mt2: render_signal_cards(_ms, "signal-card-short")
            with _mt3: render_signal_cards(_ma, "signal-card-avoid")
            with _mt4: render_signal_cards(_mn, "signal-card-avoid")


# ───────────────────────────────────────────────────────────────
#  TAB 4  —  Sector Sentiment (matches HTML design)
# ───────────────────────────────────────────────────────────────
with tab_sectors:
    col_sent, col_rot = st.columns([1, 1], gap="medium")

    with col_sent:
        st.markdown('<div class="card"><div class="card-title">📡 Sector Sentiment Analysis</div>',
                    unsafe_allow_html=True)

        if not result.flat_impacts:
            st.info("Not enough data.")
        else:
            sector_moves: dict[str, list[float]] = {}
            sector_scores_: dict[str, list[int]] = {}
            for _, r in result.flat_impacts:
                sector_moves.setdefault(r.sector, []).append(r.actual_move_pct)
                sector_scores_.setdefault(r.sector, []).append(
                    _IMPACT_ORDER.get(r.impact_strength, 0))

            sector_avg = {s: sum(v)/len(v) for s, v in sector_moves.items()}
            for sector, avg in sorted(sector_avg.items(), key=lambda x: x[1], reverse=True):
                n      = len(sector_moves[sector])
                emoji  = SECTOR_EMOJI.get(sector, "📌")
                if avg > 0.5:
                    sent_lbl, sent_col = "POSITIVE", "#00ff88"
                elif avg < -0.5:
                    sent_lbl, sent_col = "NEGATIVE", "#ff4455"
                else:
                    sent_lbl, sent_col = "NEUTRAL", "#ffaa33"

                strength  = min(10.0, abs(avg) * 2 + len(sector_scores_.get(sector,[])) * 0.3)
                fill_pct  = int(strength / 10 * 100)
                reason    = f"{n} stock{'s' if n>1 else ''} · avg {avg:+.2f}%"

                st.markdown(
                    f'<div class="sector-row">'
                    f'  <div style="font-size:22px">{emoji}</div>'
                    f'  <div style="flex:1">'
                    f'    <div style="font-weight:600;color:#e0e6ff;margin-bottom:2px">{sector}</div>'
                    f'    <div style="font-size:12px;color:#6b7280">{reason}</div>'
                    f'  </div>'
                    f'  <div style="text-align:right">'
                    f'    <div style="font-weight:600;color:{sent_col};font-size:12px;margin-bottom:4px">'
                    f'      {sent_lbl}</div>'
                    f'    <div class="sector-bar-track">'
                    f'      <div class="sector-bar-fill" style="width:{fill_pct}%"></div>'
                    f'    </div>'
                    f'    <div style="font-size:11px;color:#a8b0d0;margin-top:2px">{strength:.1f}/10</div>'
                    f'  </div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        st.markdown('</div>', unsafe_allow_html=True)

    with col_rot:
        st.markdown('<div class="card"><div class="card-title">📈 Sector Rotation Chart</div>',
                    unsafe_allow_html=True)

        if result.flat_impacts:
            sector_moves2: dict[str, list[float]] = {}
            for _, r in result.flat_impacts:
                sector_moves2.setdefault(r.sector, []).append(r.actual_move_pct)
            labels = list(sector_moves2.keys())
            values = [sum(v)/len(v) for v in sector_moves2.values()]
            counts = [len(v) for v in sector_moves2.values()]
            sorted_data = sorted(zip(labels,values,counts), key=lambda x: x[1], reverse=True)
            l2, v2, c2 = zip(*sorted_data) if sorted_data else ([],[],[])

            fig = go.Figure(go.Bar(
                x=list(l2), y=list(v2),
                marker_color=["#00ff88" if v>=0 else "#ff4455" for v in v2],
                text=[f"{v:+.2f}%<br>({c})" for v,c in zip(v2,c2)],
                textposition="outside", textfont=dict(size=10, color="#a8b0d0"),
            ))
            fig.update_layout(
                plot_bgcolor="#1a1f3a", paper_bgcolor="#141829",
                font=dict(color="#a8b0d0"),
                xaxis=dict(tickangle=-30, gridcolor="#252a45", tickfont=dict(color="#ffd700",size=11)),
                yaxis=dict(gridcolor="#252a45", ticksuffix="%"),
                margin=dict(t=20,b=80,l=40,r=20), height=370,
            )
            st.plotly_chart(fig, use_container_width=True)

            # Bubble chart
            heat_rows = []
            for s, vals in sector_moves2.items():
                sc_vals = [_IMPACT_ORDER.get(r.impact_strength,0) for _, r in result.flat_impacts if r.sector==s]
                heat_rows.append({
                    "Sector": s,
                    "Avg Impact": round(sum(sc_vals)/len(sc_vals),2) if sc_vals else 0,
                    "# Stocks": len(vals),
                    "Avg Move %": round(sum(vals)/len(vals),2),
                })
            hdf = pd.DataFrame(heat_rows)
            fig2 = px.scatter(
                hdf, x="Avg Impact", y="Avg Move %", size="# Stocks",
                color="Avg Move %", text="Sector",
                color_continuous_scale=["#ff4455","#ffaa33","#ffd700","#00d4ff","#00ff88"],
                range_color=[-4,4],
                title="Impact Score vs Price Reaction",
            )
            fig2.update_traces(textposition="top center", textfont=dict(size=10,color="#a8b0d0"))
            fig2.update_layout(
                plot_bgcolor="#1a1f3a", paper_bgcolor="#141829",
                font=dict(color="#a8b0d0"),
                title=dict(font=dict(color="#00d4ff",size=13)),
                xaxis=dict(gridcolor="#252a45",title="Avg Impact Score"),
                yaxis=dict(gridcolor="#252a45",ticksuffix="%",title="Avg Price Move"),
                coloraxis_colorbar=dict(ticksuffix="%"),
                margin=dict(t=40,b=30,l=50,r=20), height=320,
            )
            st.plotly_chart(fig2, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)


# ───────────────────────────────────────────────────────────────
#  TAB 5  —  News Feed
# ───────────────────────────────────────────────────────────────
with tab_news:
    if not result.news_impacts:
        st.info("No news to display.")
    else:
        col_a, col_b = st.columns(2, gap="medium")
        for idx, (item, sentiment, impacts) in enumerate(result.news_impacts[:14]):
            max_imp = max((_IMPACT_ORDER.get(r.impact_strength,0) for r in impacts), default=0)
            if _IMPACT_ORDER.get(min_impact, 0) > max_imp: continue
            if only_direct and not any(r.relation=="Direct" for r in impacts): continue
            if only_signals and not any(generate_signal(r) for r in impacts): continue

            nc  = "pos" if sentiment.label=="Positive" else ("neg" if sentiment.label=="Negative" else "")
            sc  = "#00ff88" if sentiment.label=="Positive" else ("#ff4455" if sentiment.label=="Negative" else "#ffaa33")
            imp_lbl = max((r.impact_strength for r in impacts if r.relation=="Direct"),
                          key=lambda x: _IMPACT_ORDER.get(x,0), default="LOW")
            imp_cls = {"EXTREME":"badge-extreme","HIGH":"badge-high",
                       "MEDIUM":"badge-medium","LOW":"badge-low"}.get(imp_lbl,"badge-teal")
            direct_syms = [r.symbol for r in impacts if r.relation=="Direct"][:4]
            sym_tags = " ".join(badge(s,"badge-gold") for s in direct_syms)

            col = col_a if idx % 2 == 0 else col_b
            with col:
                st.markdown(
                    f'<div class="news-card {nc}">'
                    f'<div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap">'
                    f'  {badge(imp_lbl, imp_cls)}'
                    f'  <span class="badge badge-teal">{sentiment.category}</span>'
                    f'  <span style="color:{sc};font-size:12px;font-weight:600">'
                    f'    {sentiment.label} {sentiment.score:+.2f}</span>'
                    f'  <span style="color:#6b7280;font-size:11px;margin-left:auto">'
                    f'    {item.published.strftime("%d %b %H:%M")}</span>'
                    f'</div>'
                    f'<div class="news-headline">{item.title}</div>'
                    f'<div style="font-size:11px;color:#6b7280;margin-bottom:8px">'
                    f'  📡 {item.source}</div>'
                    f'<div>{sym_tags}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if item.summary:
                    with st.expander("Read summary"):
                        st.caption(item.summary[:500])
                        if item.url:
                            st.markdown(f"[Open article →]({item.url})")
                if impacts:
                    show_rows = [r for r in impacts if not only_direct or r.relation=="Direct"][:5]
                    if show_rows:
                        df_rows = [{
                            "Symbol":   r.symbol, "Relation": r.relation,
                            "Impact":   r.impact_strength,
                            "Actual":   f"{r.actual_move_pct:+.2f}%",
                            "Expected": f"{r.expected_move_pct:+.1f}%",
                            "Status":   {"Underreacted":"👉","Overreacted":"⚠️","Reacted":"✅"}.get(r.reaction_status,"") + " " + r.reaction_status,
                        } for r in show_rows]
                        st.dataframe(pd.DataFrame(df_rows), use_container_width=True,
                                     hide_index=True, height=min(38*len(df_rows)+40, 220))


# ───────────────────────────────────────────────────────────────
#  TAB 6  —  NSE Data (FII/DII, Bulk/Block Deals, Corp Events)
# ───────────────────────────────────────────────────────────────
with tab_nse:
    # ── Nifty + FII/DII header row ────────────────────────────
    hc1, hc2, hc3 = st.columns(3, gap="medium")

    nifty = result.nifty_data
    with hc1:
        if nifty:
            chg_col = "#00ff88" if nifty["nifty_change"] >= 0 else "#ff4455"
            st.markdown(
                f'<div class="card"><div class="card-title">📈 Nifty 50</div>'
                f'<div style="font-size:28px;font-weight:700;color:#ffd700">{nifty["nifty_close"]:,.2f}</div>'
                f'<div style="font-size:14px;color:{chg_col};font-weight:600">{nifty["nifty_change"]:+.2f}% today</div>'
                f'<div style="font-size:11px;color:#6b7280;margin-top:4px">Source: {nifty["source"]}</div>'
                f'</div>', unsafe_allow_html=True)
        else:
            st.info("Nifty data unavailable")

    fii = result.fii_dii
    with hc2:
        if fii:
            fii_col = "#00ff88" if fii["fii_net"] >= 0 else "#ff4455"
            st.markdown(
                f'<div class="card"><div class="card-title">🏦 FII Activity</div>'
                f'<div style="font-size:22px;font-weight:700;color:{fii_col}">₹{fii["fii_net"]:,.0f} Cr</div>'
                f'<div style="font-size:11px;color:#a8b0d0">Buy ₹{fii["fii_buy"]:,.0f}  |  Sell ₹{fii["fii_sell"]:,.0f}</div>'
                f'<div style="font-size:13px;color:{fii_col};font-weight:600;margin-top:4px">{fii["sentiment"]} ({fii["date"]})</div>'
                f'</div>', unsafe_allow_html=True)
        else:
            st.info("FII data unavailable")

    with hc3:
        if fii:
            dii_col = "#00ff88" if fii["dii_net"] >= 0 else "#ff4455"
            st.markdown(
                f'<div class="card"><div class="card-title">🏛 DII Activity</div>'
                f'<div style="font-size:22px;font-weight:700;color:{dii_col}">₹{fii["dii_net"]:,.0f} Cr</div>'
                f'<div style="font-size:11px;color:#a8b0d0">Buy ₹{fii["dii_buy"]:,.0f}  |  Sell ₹{fii["dii_sell"]:,.0f}</div>'
                f'</div>', unsafe_allow_html=True)
        else:
            st.info("DII data unavailable")

    # ── Corporate Events ──────────────────────────────────────
    st.markdown('<div class="card"><div class="card-title">📅 Upcoming Corporate Events (next 7 days)</div>',
                unsafe_allow_html=True)
    if result.corporate_events:
        ev_rows = [{"Symbol": e["symbol"], "Company": e["company"],
                    "Event": e["purpose"], "Date": e["ex_date"],
                    "Days Away": e["days_away"]} for e in result.corporate_events]
        st.dataframe(pd.DataFrame(ev_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No upcoming corporate events found or NSE API unavailable.")
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Bulk Deals ────────────────────────────────────────────
    col_bulk, col_block = st.columns(2, gap="medium")
    with col_bulk:
        st.markdown('<div class="card"><div class="card-title">📦 Bulk Deals (Today)</div>',
                    unsafe_allow_html=True)
        if result.bulk_deals:
            bdf = pd.DataFrame(result.bulk_deals)[["symbol","client","buy_sell","qty","price"]]
            bdf.columns = ["Symbol","Client","B/S","Qty","Price"]
            st.dataframe(bdf, use_container_width=True, hide_index=True)
        else:
            st.info("No bulk deals today or NSE API unavailable.")
        st.markdown('</div>', unsafe_allow_html=True)

    with col_block:
        st.markdown('<div class="card"><div class="card-title">🧱 Block Deals (Today)</div>',
                    unsafe_allow_html=True)
        if result.block_deals:
            bldf = pd.DataFrame(result.block_deals)[["symbol","client","buy_sell","qty","price"]]
            bldf.columns = ["Symbol","Client","B/S","Qty","Price"]
            st.dataframe(bldf, use_container_width=True, hide_index=True)
        else:
            st.info("No block deals today or NSE API unavailable.")
        st.markdown('</div>', unsafe_allow_html=True)


# ───────────────────────────────────────────────────────────────
#  TAB 7  —  Trade Journal
# ───────────────────────────────────────────────────────────────
with tab_journal:
    from trade_journal import load_journal, save_journal, get_stats, to_csv_bytes, from_csv_bytes, add_trade

    df_j = load_journal()
    stats = get_stats(df_j)

    # ── Stats row ─────────────────────────────────────────────
    js1, js2, js3, js4, js5 = st.columns(5, gap="small")
    js1.metric("Total Trades",  stats["total"])
    js2.metric("Open",          stats["open"])
    js3.metric("Win Rate",      f"{stats['win_rate']}%")
    js4.metric("Avg P&L",       f"{stats['avg_pnl']:+.1f}%")
    js5.metric("Best Trade",    f"{stats['best']:+.1f}%")

    st.markdown("---")

    # ── Manual trade entry ────────────────────────────────────
    with st.expander("➕ Log a trade manually"):
        jc1, jc2, jc3 = st.columns(3)
        j_sym   = jc1.text_input("Symbol",  key="j_sym")
        j_name  = jc2.text_input("Name",    key="j_name")
        j_act   = jc3.selectbox("Action", ["BUY","SHORT"], key="j_act")
        jc4, jc5, jc6 = st.columns(3)
        j_entry = jc4.number_input("Entry Price",  value=0.0, key="j_entry")
        j_sl    = jc5.number_input("Stop Loss",    value=0.0, key="j_sl")
        j_t1    = jc6.number_input("Target 1",     value=0.0, key="j_t1")
        jc7, jc8 = st.columns(2)
        j_t2    = jc7.number_input("Target 2",     value=0.0, key="j_t2")
        j_rr    = jc8.number_input("R:R Ratio",    value=1.5, key="j_rr")
        j_notes = st.text_input("Notes", key="j_notes")
        if st.button("Log Trade", type="primary"):
            if j_sym and j_entry > 0:
                add_trade(j_sym, j_name, j_act, j_entry, j_sl, j_t1, j_t2, j_rr, 0, "Manual", j_notes)
                st.success(f"✅ {j_sym} logged!")
                st.rerun()

    # ── Journal table (editable) ──────────────────────────────
    if df_j.empty:
        st.info("No trades logged yet. Click '📓 Log to Journal' on any Trade Signal card above.")
    else:
        st.markdown("**Edit results below** — set Result to WIN / LOSS / BREAK-EVEN and add exit price.")
        edited = st.data_editor(df_j, use_container_width=True, hide_index=False, num_rows="dynamic",
                                column_config={
                                    "result":    st.column_config.SelectboxColumn("Result",
                                                   options=["Open","WIN","LOSS","BREAK-EVEN"]),
                                    "action":    st.column_config.SelectboxColumn("Action",
                                                   options=["BUY","SHORT"]),
                                })
        if st.button("💾 Save Changes"):
            save_journal(edited)
            st.success("Saved!")

    st.markdown("---")
    # ── Export / Import ───────────────────────────────────────
    ec1, ec2 = st.columns(2)
    with ec1:
        if not df_j.empty:
            st.download_button("⬇️ Export Journal CSV", to_csv_bytes(df_j),
                               "trade_journal.csv", "text/csv")
    with ec2:
        uploaded = st.file_uploader("⬆️ Import Journal CSV", type="csv", key="j_upload")
        if uploaded:
            imported = from_csv_bytes(uploaded.read())
            save_journal(imported)
            st.success(f"Imported {len(imported)} trades!")
            st.rerun()


# ───────────────────────────────────────────────────────────────
#  TAB 8  —  Backtest
# ───────────────────────────────────────────────────────────────
with tab_backtest:
    from trade_journal import load_journal
    from backtester import run_backtest, backtest_stats

    bt_df_j = load_journal()

    st.markdown('<div class="card"><div class="card-title">🔬 Signal Backtest — Did past signals work?</div>',
                unsafe_allow_html=True)

    if bt_df_j.empty:
        st.info("No trades in your journal yet. Log signals from the Trade Signals tab first, then run the backtest here.")
    else:
        bc1, bc2 = st.columns([2, 1])
        with bc2:
            bt_horizon = st.slider("Hold period (trading days)", 1, 10, 5, key="bt_horizon")
            run_bt = st.button("▶ Run Backtest", type="primary", use_container_width=True)

        if run_bt or st.session_state.get("bt_result") is not None:
            if run_bt:
                prog_bt = st.progress(0, text="Running backtest…")
                def bt_cb(step, pct):
                    prog_bt.progress(min(pct, 1.0), text=step)
                bt_result = run_backtest(bt_df_j, horizon_days=bt_horizon, progress_cb=bt_cb)
                prog_bt.empty()
                st.session_state["bt_result"] = bt_result
            else:
                bt_result = st.session_state["bt_result"]

            bstats = backtest_stats(bt_result)
            if bstats:
                bs1, bs2, bs3, bs4, bs5 = st.columns(5)
                bs1.metric("Trades Tested",  bstats["total"])
                bs2.metric("Win Rate",        f"{bstats['win_rate']}%")
                bs3.metric("Wins / Losses",   f"{bstats['wins']} / {bstats['losses']}")
                bs4.metric("Avg Return",      f"{bstats['avg_return']:+.1f}%")
                bs5.metric("Best / Worst",    f"{bstats['best']:+.1f}% / {bstats['worst']:+.1f}%")

                if bstats.get("by_edge"):
                    st.markdown("**Win rate by edge type:**")
                    edge_cols = st.columns(len(bstats["by_edge"]))
                    for col, (edge, wr) in zip(edge_cols, bstats["by_edge"].items()):
                        col.metric(edge, f"{wr}%")

                # ── Equity curve ──────────────────────────────
                if "actual_return_pct" in bt_result.columns:
                    closed_bt = bt_result[bt_result["outcome"].isin(["WIN","LOSS","BREAK-EVEN"])].copy()
                    if not closed_bt.empty:
                        closed_bt["cumulative"] = pd.to_numeric(
                            closed_bt["actual_return_pct"], errors="coerce").fillna(0).cumsum()
                        fig_bt = px.line(
                            closed_bt.reset_index(), x="index", y="cumulative",
                            title="Cumulative Return (%)",
                            labels={"index": "Trade #", "cumulative": "Cumulative Return %"},
                            color_discrete_sequence=["#00d4ff"],
                        )
                        fig_bt.add_hline(y=0, line_dash="dash", line_color="#ff4455", opacity=0.5)
                        fig_bt.update_layout(
                            plot_bgcolor="#1a1f3a", paper_bgcolor="#141829",
                            font=dict(color="#a8b0d0"),
                            title=dict(font=dict(color="#00d4ff",size=13)),
                            xaxis=dict(gridcolor="#252a45"),
                            yaxis=dict(gridcolor="#252a45", ticksuffix="%"),
                            margin=dict(t=40,b=30,l=50,r=20), height=300,
                        )
                        st.plotly_chart(fig_bt, use_container_width=True)

                # ── Results table ─────────────────────────────
                show_cols = ["symbol","action","entry","target2","stop_loss","outcome",
                             "actual_return_pct","hit_target","hit_stop"]
                show_cols = [c for c in show_cols if c in bt_result.columns]
                st.dataframe(bt_result[show_cols], use_container_width=True, hide_index=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ───────────────────────────────────────────────────────────────
#  TAB 9  —  MPHR (Market Prediction History & Results)
# ───────────────────────────────────────────────────────────────
with tab_history:
    # ── Gist persistence status ──────────────────────────────────
    from history_store import gist_configured as _gist_cfg
    if _gist_cfg():
        st.success("**History persistence:** GitHub Gist connected — history survives server restarts.", icon="☁️")
    else:
        st.warning(
            "**History not persisted across restarts.** "
            "Add `GITHUB_TOKEN` and `GIST_HISTORY_ID` to Streamlit secrets to enable cloud persistence.",
            icon="⚠️"
        )

    history = load_history()
    history, _outcomes_changed = check_and_update_outcomes(history)
    if _outcomes_changed:
        save_history(history)

    # MCX symbol set for correct price routing
    _MPHR_MCX = {"SILVERMIC","GOLDM","CRUDEOIL","NATURALGAS","COPPER","ZINC","ALUMINIUM","NICKEL","LEAD","GOLD","SILVER"}

    def _mphr_price(sym: str) -> float:
        """Get live price routing MCX symbols to their fetcher."""
        return _mcx_live_price(sym) if sym in _MPHR_MCX else _mphr_live_price(sym)

    # Flatten all HIGH/EXTREME signals into a chronological list
    _all_preds: list[dict] = []
    for _entry in history:
        _rt = _entry.get("run_time", "")
        for _s in _entry.get("signals", []):
            if _s.get("action") not in ("BUY", "SHORT", "NO TRADE"):
                continue
            if _s.get("impact_strength") not in ("HIGH", "EXTREME"):
                continue
            _all_preds.append({**_s, "_run_time": _rt, "_slot": _entry.get("slot_label", "")})

    _all_preds.sort(key=lambda x: x["_run_time"], reverse=True)

    # ── Stats ──────────────────────────────────────────────────
    _verified = [p for p in _all_preds if p.get("outcome")]
    _wins     = [p for p in _verified if p.get("outcome") == "WIN"]
    _win_rate = round(len(_wins) / len(_verified) * 100, 1) if _verified else 0.0
    _avg_ret  = round(sum(p.get("outcome_return_pct") or 0 for p in _verified) / len(_verified), 2) if _verified else 0.0

    # Hypothetical: if you took every BUY/SHORT at signal price → current
    _hypo_returns: list[float] = []
    for _hx in _all_preds:
        if _hx.get("action") not in ("BUY", "SHORT"):
            continue
        _hep = float(_hx.get("prediction_price") or 0)
        if _hep <= 0:
            _hlo, _hhi = float(_hx.get("entry_low") or 0), float(_hx.get("entry_high") or 0)
            if _hlo > 0 and _hhi > 0:
                _hep = (_hlo + _hhi) / 2
        if _hep <= 0:
            continue
        _hcp = _mphr_price(_hx.get("symbol", ""))
        if _hcp <= 0:
            continue
        _hpnl = (_hcp - _hep) / _hep * 100 if _hx["action"] == "BUY" else (_hep - _hcp) / _hep * 100
        _hypo_returns.append(_hpnl)

    _hypo_avg  = round(sum(_hypo_returns) / len(_hypo_returns), 2) if _hypo_returns else None
    _hypo_wins = sum(1 for x in _hypo_returns if x > 0)

    _win_col  = "#00ff88" if _win_rate >= 55 else ("#ffaa33" if _win_rate >= 40 else "#ff4455")
    _ret_col  = "#00ff88" if _avg_ret  >= 0 else "#ff4455"
    _hypo_col = "#00ff88" if (_hypo_avg or 0) >= 0 else "#ff4455"

    _hypo_cell = ""
    if _hypo_avg is not None:
        _hypo_cell = (
            f'<div style="background:rgba(255,255,255,0.04);border-radius:8px;padding:10px;text-align:center">'
            f'<div style="color:#6b7280;font-size:10px;text-transform:uppercase">If Taken Avg</div>'
            f'<div style="font-size:22px;font-weight:700;color:{_hypo_col}">{_hypo_avg:+.2f}%</div>'
            f'<div style="font-size:10px;color:#4a5568">{_hypo_wins}/{len(_hypo_returns)} profitable</div>'
            f'</div>'
        )

    _ncols = 5 + (1 if _hypo_avg is not None else 0)
    st.markdown(
        f'<div class="card">'
        f'<div class="card-title">📊 MPHR — Signal Tracker &amp; Trade Simulator</div>'
        f'<div style="color:#6b7280;font-size:12px;margin-bottom:12px">'
        f'See what each signal would have returned if you had taken the trade &nbsp;·&nbsp;'
        f'<b>HIGH</b> &amp; <b>EXTREME</b> impact · BUY / SHORT / NO TRADE'
        f'</div>'
        f'<div style="display:grid;grid-template-columns:repeat({_ncols},1fr);gap:12px;margin-bottom:16px">'
        f'<div style="background:rgba(255,255,255,0.04);border-radius:8px;padding:10px;text-align:center">'
        f'<div style="color:#6b7280;font-size:10px;text-transform:uppercase">Total Signals</div>'
        f'<div style="font-size:22px;font-weight:700">{len(_all_preds)}</div></div>'
        f'<div style="background:rgba(255,255,255,0.04);border-radius:8px;padding:10px;text-align:center">'
        f'<div style="color:#6b7280;font-size:10px;text-transform:uppercase">Verified</div>'
        f'<div style="font-size:22px;font-weight:700">{len(_verified)}</div></div>'
        f'<div style="background:rgba(255,255,255,0.04);border-radius:8px;padding:10px;text-align:center">'
        f'<div style="color:#6b7280;font-size:10px;text-transform:uppercase">Wins</div>'
        f'<div style="font-size:22px;font-weight:700;color:#00ff88">{len(_wins)}</div></div>'
        f'<div style="background:rgba(255,255,255,0.04);border-radius:8px;padding:10px;text-align:center">'
        f'<div style="color:#6b7280;font-size:10px;text-transform:uppercase">Win Rate</div>'
        f'<div style="font-size:22px;font-weight:700;color:{_win_col}">{_win_rate:.1f}%</div></div>'
        f'<div style="background:rgba(255,255,255,0.04);border-radius:8px;padding:10px;text-align:center">'
        f'<div style="color:#6b7280;font-size:10px;text-transform:uppercase">Verified Avg</div>'
        f'<div style="font-size:22px;font-weight:700;color:{_ret_col}">{_avg_ret:+.2f}%</div></div>'
        + _hypo_cell +
        f'</div>',
        unsafe_allow_html=True,
    )

    if not _all_preds:
        st.info(
            "No HIGH/EXTREME impact signals yet. Signals are archived every time you click "
            "**Run Analysis** and at scheduled slots: 09:15, 13:00, 15:20, 17:30, 21:00 IST."
        )
    else:
        # ── Filters ──────────────────────────────────────────
        _fc1, _fc2, _fc3 = st.columns([2, 2, 2])
        with _fc1:
            _imp_filter = st.multiselect("Impact", ["EXTREME", "HIGH"], default=["EXTREME", "HIGH"], key="mphr_imp")
        with _fc2:
            _act_filter = st.multiselect("Action", ["BUY", "SHORT", "NO TRADE"], default=["BUY", "SHORT", "NO TRADE"], key="mphr_act")
        with _fc3:
            _res_filter = st.multiselect("Result", ["Profitable", "Loss", "Pending"], default=["Profitable", "Loss", "Pending"], key="mphr_res")

        _filtered = [
            p for p in _all_preds
            if p.get("impact_strength") in _imp_filter and p.get("action") in _act_filter
        ]

        # ── Signal cards ──────────────────────────────────────
        _oc_badge_map = {
            "WIN":        '<span style="background:#0a2a14;border:1px solid #00ff88;color:#00ff88;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700">WIN</span>',
            "LOSS":       '<span style="background:#2a0a0a;border:1px solid #ff4455;color:#ff4455;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700">LOSS</span>',
            "BREAK-EVEN": '<span style="background:#1a1200;border:1px solid #ffaa33;color:#ffaa33;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700">BREAK-EVEN</span>',
        }
        _pending_badge_html = '<span style="background:rgba(255,255,255,0.05);border:1px solid #555;color:#888;padding:2px 8px;border-radius:4px;font-size:11px">PENDING</span>'

        for _p in _filtered:
            _rt_str = _p.get("_run_time", "")
            _rt_utc = datetime.fromisoformat(_rt_str) if _rt_str else datetime.now(timezone.utc)
            if _rt_utc.tzinfo is None:
                _rt_utc = _rt_utc.replace(tzinfo=timezone.utc)
            _rt_ist = _rt_utc + timedelta(hours=5, minutes=30)
            _ts     = _rt_ist.strftime("%d %b %H:%M IST")

            # Human-readable "X ago"
            _dm = int((datetime.now(timezone.utc) - _rt_utc).total_seconds() / 60)
            if _dm < 60:
                _ago = f"{_dm}m ago"
            elif _dm < 1440:
                _ago = f"{_dm//60}h {_dm%60}m ago"
            else:
                _ago = f"{_dm//1440}d {(_dm%1440)//60}h ago"

            _act    = _p.get("action", "")
            _imp    = _p.get("impact_strength", "")
            _sym    = _p.get("symbol", "")
            _name   = _p.get("name", _sym)
            _sector = _p.get("sector", "")

            _pred_px  = float(_p.get("prediction_price") or 0)
            _entry_lo = float(_p.get("entry_low")  or 0)
            _entry_hi = float(_p.get("entry_high") or 0)
            _stop_px  = float(_p.get("stop_loss")  or 0)
            _tgt1     = float(_p.get("target1")    or 0)
            _tgt2     = float(_p.get("target2")    or 0)
            _exp_pct  = float(_p.get("expected_move_pct") or 0)

            # Best entry price for P&L calc
            _entry_px = _pred_px
            if _entry_px <= 0 and _entry_lo > 0 and _entry_hi > 0:
                _entry_px = (_entry_lo + _entry_hi) / 2.0
            elif _entry_px <= 0 and _entry_lo > 0:
                _entry_px = _entry_lo

            # Entry display string
            if _entry_lo > 0 and _entry_hi > 0 and abs(_entry_lo - _entry_hi) > 0.01:
                _entry_str = f"₹{_entry_lo:,.2f}–{_entry_hi:,.2f}"
            elif _entry_px > 0:
                _entry_str = f"₹{_entry_px:,.2f}"
            else:
                _entry_str = "—"

            # Target display string
            if _tgt1 > 0:
                _tgt_str = f"₹{_tgt1:,.2f}" + (f" / ₹{_tgt2:,.2f}" if _tgt2 > 0 else "")
            elif _entry_px > 0 and _exp_pct:
                _ref_px  = _entry_px * (1 + _exp_pct / 100)
                _tgt_str = f"~₹{_ref_px:,.2f} ({_exp_pct:+.1f}%)"
            else:
                _tgt_str = "—"

            _stop_str = f"₹{_stop_px:,.2f}" if _stop_px > 0 else "—"

            # Live price
            _cur_px  = _mphr_price(_sym)
            _cur_str = f"₹{_cur_px:,.2f}" if _cur_px > 0 else "—"

            # Price change from signal → now
            _chg_html = ""
            if _entry_px > 0 and _cur_px > 0:
                _raw_chg = _cur_px - _entry_px
                _raw_pct = _raw_chg / _entry_px * 100
                _cc      = "#00ff88" if _raw_pct >= 0 else "#ff4455"
                _arrow   = "▲" if _raw_pct >= 0 else "▼"
                _rgb     = "0,255,136" if _raw_pct >= 0 else "255,68,85"
                _chg_html = (
                    f'<div style="background:rgba({_rgb},0.1);color:{_cc};'
                    f'padding:4px 10px;border-radius:6px;font-size:13px;font-weight:700;white-space:nowrap">'
                    f'{_arrow} {abs(_raw_pct):.2f}% (₹{_raw_chg:+,.2f})</div>'
                )

            # IF TAKEN P&L
            _if_pct: float | None = None
            _if_amt: float | None = None
            if _entry_px > 0 and _cur_px > 0:
                if _act == "BUY":
                    _if_pct = (_cur_px - _entry_px) / _entry_px * 100
                    _if_amt = _cur_px - _entry_px
                elif _act == "SHORT":
                    _if_pct = (_entry_px - _cur_px) / _entry_px * 100
                    _if_amt = _entry_px - _cur_px
                else:  # NO TRADE — show hypothetical BUY
                    _if_pct = (_cur_px - _entry_px) / _entry_px * 100
                    _if_amt = _cur_px - _entry_px

            # Result filter
            if _if_pct is not None and _if_pct > 0  and "Profitable" not in _res_filter:
                continue
            if _if_pct is not None and _if_pct <= 0 and "Loss"       not in _res_filter:
                continue
            if _if_pct is None                       and "Pending"    not in _res_filter:
                continue

            # Progress bar toward target (BUY/SHORT only)
            _prog_html = ""
            if _if_pct is not None and _tgt1 > 0 and _entry_px > 0 and _act in ("BUY", "SHORT"):
                if _act == "BUY" and _tgt1 > _entry_px:
                    _prog = min(100, max(0, (_cur_px - _entry_px) / (_tgt1 - _entry_px) * 100))
                    _prog_col = "#00ff88"
                elif _act == "SHORT" and _tgt1 < _entry_px:
                    _prog = min(100, max(0, (_entry_px - _cur_px) / (_entry_px - _tgt1) * 100))
                    _prog_col = "#ff4455"
                else:
                    _prog, _prog_col = 0, "#555"
                _prog_html = (
                    f'<div style="margin-top:8px">'
                    f'<div style="font-size:10px;color:#4a5568;margin-bottom:3px">To target: {_prog:.0f}%</div>'
                    f'<div style="background:#1a2035;border-radius:3px;height:5px">'
                    f'<div style="background:{_prog_col};height:5px;width:{_prog:.0f}%;border-radius:3px"></div>'
                    f'</div></div>'
                )

            # IF TAKEN box: bg/border/color/label/note
            if _if_pct is None:
                _ib_bg, _ib_bdr, _ip_col = "rgba(255,255,255,0.03)", "#2a2a3a", "#555"
                _if_label, _if_note = "No Data", "Price unavailable"
                _if_pct_str, _if_amt_str = "—", ""
            elif _act == "NO TRADE":
                if _if_pct < 0:
                    _ib_bg, _ib_bdr = "rgba(0,255,136,0.06)", "rgba(0,255,136,0.3)"
                    _if_label, _if_note = "Advice Correct", "Market dropped — good call"
                else:
                    _ib_bg, _ib_bdr = "rgba(255,170,51,0.06)", "rgba(255,170,51,0.3)"
                    _if_label, _if_note = "Missed Move", "Market rose despite risk"
                # % color always reflects actual market direction (not advice quality)
                _ip_col = "#ff4455" if _if_pct < 0 else "#00ff88"
                _if_pct_str = f"{_if_pct:+.2f}%"
                _if_amt_str = f"₹{abs(_if_amt):,.2f}/sh hypothetical" if _if_amt is not None else ""
            else:
                if _if_pct > 0:
                    _ib_bg, _ib_bdr, _ip_col = "rgba(0,255,136,0.07)", "rgba(0,255,136,0.35)", "#00ff88"
                    _if_label, _if_note = "In Profit", "Holding above entry"
                elif _if_pct < -0.5:
                    _ib_bg, _ib_bdr, _ip_col = "rgba(255,68,85,0.07)", "rgba(255,68,85,0.35)", "#ff4455"
                    _if_label, _if_note = "In Loss", "Below entry price"
                else:
                    _ib_bg, _ib_bdr, _ip_col = "rgba(255,255,255,0.04)", "#3a3a4a", "#888"
                    _if_label, _if_note = "Flat", "Near entry price"
                _if_pct_str = f"{_if_pct:+.2f}%"
                _if_amt_str = f"₹{abs(_if_amt):,.2f}/share" if _if_amt is not None else ""

            # Action badge
            if _act == "BUY":
                _act_badge = '<span style="background:rgba(0,255,136,0.1);border:1px solid #00ff88;color:#00ff88;padding:2px 10px;border-radius:4px;font-size:12px;font-weight:700">BUY</span>'
                _if_title  = "If You Bought"
            elif _act == "SHORT":
                _act_badge = '<span style="background:rgba(255,68,85,0.1);border:1px solid #ff4455;color:#ff4455;padding:2px 10px;border-radius:4px;font-size:12px;font-weight:700">SHORT</span>'
                _if_title  = "If You Shorted"
            else:
                _act_badge = '<span style="background:rgba(255,255,255,0.04);border:1px solid #555;color:#888;padding:2px 10px;border-radius:4px;font-size:12px;font-weight:700">NO TRADE</span>'
                _if_title  = "If Bought Anyway"

            # Impact badge
            _imp_col = {"EXTREME": "#ff4455", "HIGH": "#ffaa33"}.get(_imp, "#6b7280")
            _imp_badge = (
                f'<span style="background:rgba(255,255,255,0.04);border:1px solid {_imp_col};'
                f'color:{_imp_col};padding:2px 10px;border-radius:4px;font-size:12px;font-weight:700">{_imp}</span>'
            )

            # Outcome badge (for BUY/SHORT)
            if _act == "NO TRADE":
                _oc_html = '<span style="background:rgba(255,255,255,0.03);border:1px solid #444;color:#666;padding:2px 8px;border-radius:4px;font-size:11px">N/A</span>'
            else:
                _oc      = _p.get("outcome")
                _ret_pct = _p.get("outcome_return_pct")
                _oc_html = _oc_badge_map.get(_oc, _pending_badge_html)
                if _ret_pct is not None:
                    _rc = "#00ff88" if _ret_pct >= 0 else "#ff4455"
                    _oc_html += f' <span style="color:{_rc};font-size:11px;font-weight:700">{_ret_pct:+.2f}%</span>'

            st.markdown(
                # Card wrapper
                f'<div style="background:#0d111e;border:1px solid #1a2035;border-radius:12px;padding:16px;margin-bottom:10px">'
                # ── Header: symbol + timestamp ──
                f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">'
                f'  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
                f'    <span style="font-size:17px;font-weight:700;color:#fff">{_sym}</span>'
                f'    <span style="font-size:13px;color:#8892b0">{_name[:28]}</span>'
                f'    <span style="background:#1e293b;color:#64748b;padding:2px 8px;border-radius:4px;font-size:11px">{_sector}</span>'
                f'  </div>'
                f'  <div style="text-align:right;flex-shrink:0;margin-left:12px">'
                f'    <div style="font-size:11px;color:#6b7280">{_ts}</div>'
                f'    <div style="font-size:11px;color:#4a5568">{_ago}</div>'
                f'  </div>'
                f'</div>'
                # ── Badges: action + impact + outcome ──
                f'<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:14px">'
                f'  {_act_badge} {_imp_badge}'
                f'  <span style="margin-left:4px">{_oc_html}</span>'
                f'</div>'
                # ── Body: price journey (left) + IF TAKEN box (right) ──
                f'<div style="display:grid;grid-template-columns:1fr 195px;gap:16px;align-items:start">'
                # Left col: price journey
                f'  <div>'
                f'    <div style="font-size:10px;color:#4a5568;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px">Price Journey</div>'
                f'    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">'
                f'      <div><div style="font-size:10px;color:#6b7280;margin-bottom:2px">Signal Price</div>'
                f'           <div style="font-size:16px;font-weight:700;color:#ffd700">{_entry_str}</div></div>'
                f'      <div style="color:#4a5568;font-size:20px">→</div>'
                f'      <div><div style="font-size:10px;color:#6b7280;margin-bottom:2px">Now</div>'
                f'           <div style="font-size:16px;font-weight:700;color:#00d4ff">{_cur_str}</div></div>'
                + (_chg_html or "")
                + f'    </div>'
                f'    <div style="margin-top:10px;display:flex;gap:20px;font-size:11px;color:#6b7280;flex-wrap:wrap">'
                f'      <span>Stop: <b style="color:#ff4455">{_stop_str}</b></span>'
                f'      <span>Target: <b style="color:#00ff88">{_tgt_str}</b></span>'
                f'    </div>'
                + _prog_html
                + f'  </div>'
                # Right col: IF TAKEN result box
                + f'  <div style="background:{_ib_bg};border:1px solid {_ib_bdr};border-radius:10px;padding:14px;text-align:center">'
                f'    <div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">{_if_title}</div>'
                f'    <div style="font-size:30px;font-weight:700;color:{_ip_col};line-height:1.1">{_if_pct_str}</div>'
                + (f'    <div style="font-size:11px;color:#6b7280;margin-top:4px">{_if_amt_str}</div>' if _if_amt_str else "")
                + f'    <div style="font-size:10px;color:{_ip_col};opacity:0.7;margin-top:6px">{_if_label}</div>'
                f'    <div style="font-size:10px;color:#4a5568;margin-top:3px;font-style:italic">{_if_note}</div>'
                f'  </div>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('</div>', unsafe_allow_html=True)


# ───────────────────────────────────────────────────────────────
#  TAB 11  —  🥈 SILVERMIC  (VWAP + EMA9/21 + SuperTrend MTF)
# ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _sm_live(token: str):
    from silvermic_strategy import analyze
    return analyze(token)


@st.cache_data(ttl=3600, show_spinner=False)
def _sm_backtest(token: str, days: int):
    from silvermic_strategy import backtest
    return backtest(token, days)


with tab_silvermic:
    st.markdown("### 🥈 SILVERMIC — VWAP + EMA9/21 + SuperTrend MTF (Long Only)")

    # Guard: need a Fyers token
    _sm_token = st.session_state.get("fyers_token", "")
    if not _sm_token:
        st.warning("Connect your Fyers account (sidebar) to use this strategy.")
        st.stop()

    # ── Live signal ──────────────────────────────────────────────
    _sm_col_refresh, _sm_col_ts = st.columns([1, 4])
    with _sm_col_refresh:
        if st.button("🔄 Refresh Signal", key="sm_refresh"):
            st.cache_data.clear()

    try:
        _sm_result = _sm_live(_sm_token)

        _htf  = _sm_result.htf
        _ent  = _sm_result.entry
        _sig  = _sm_result.signal
        _ago  = int((datetime.now(timezone.utc) - _sm_result.fetched_at).total_seconds() / 60)

        with _sm_col_ts:
            st.caption(f"Last updated: {_ago}m ago")

        # ── Section 1: 1H Trend Filter ───────────────────────────
        st.markdown("#### 1H Trend Filter")
        _sm_c1, _sm_c2, _sm_c3, _sm_c4 = st.columns(4)

        def _sm_tile(col, label, ok: bool, value: str):
            color = "#00ff88" if ok else "#ff4455"
            icon  = "✅" if ok else "❌"
            col.markdown(
                f"<div style='background:#141829;border:1px solid {color};border-radius:8px;"
                f"padding:12px;text-align:center'>"
                f"<div style='font-size:20px'>{icon}</div>"
                f"<div style='color:#a0aec0;font-size:11px;margin:4px 0'>{label}</div>"
                f"<div style='color:{color};font-weight:700;font-size:13px'>{value}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        _sm_tile(_sm_c1, "Price > ST",    _htf["price_above_st"], f"₹{_htf['close']:,.0f} vs ₹{_htf['st_line']:,.0f}")
        _sm_tile(_sm_c2, "ST Bullish",    _htf["st_bullish"],     "Bullish" if _htf["st_bullish"] else "Bearish")
        _sm_tile(_sm_c3, "EMA9 > EMA21",  _htf["ema_bull"],       f"₹{_htf['ema9']:,.0f} vs ₹{_htf['ema21']:,.0f}")
        _sm_tile(_sm_c4, "RSI > 50",      _htf["rsi_bull"],       f"RSI {_htf['rsi']:.1f}")

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Section 2: Live Signal ───────────────────────────────
        st.markdown("#### 15m Entry Signal")
        _sm_left, _sm_right = st.columns([3, 2])

        with _sm_left:
            def _sm_check(label: str, ok: bool, note: str = "") -> None:
                icon  = "✅" if ok else "❌"
                color = "#00ff88" if ok else "#ff4455"
                st.markdown(
                    f"<div style='display:flex;align-items:center;gap:8px;"
                    f"padding:6px 0;border-bottom:1px solid #1a1f3a'>"
                    f"<span style='font-size:16px'>{icon}</span>"
                    f"<span style='color:#e0e6ff;flex:1'>{label}</span>"
                    f"<span style='color:{color};font-size:12px'>{note}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            _sm_check("HTF Bull (1H)",      _htf["htf_bull"],       "1H OK" if _htf["htf_bull"] else "1H Weak")
            _sm_check("Above VWAP",         _ent["above_vwap"],     f"₹{_ent['close']:,.0f} vs ₹{_ent['vwap']:,.0f}")
            _sm_check("EMA9 > EMA21 (15m)", _ent["ema_above"],      f"₹{_ent['ema9']:,.0f} vs ₹{_ent['ema21']:,.0f}")
            _sm_check("RSI > 52",           _ent["rsi_ok"],         f"RSI {_ent['rsi']:.1f}")
            _sm_check("Bullish Candle",      _ent["bull_candle"],    "")
            _sm_check("Pullback to EMA Zone", _ent["pullback"],      "")
            _sm_check("EMA Spread ≥ 0.09%",  _ent["strong_trend"],  f"{_ent['spread_pct']:.3f}%")

        with _sm_right:
            if _sig == "LONG":
                _box_color  = "#00ff88"
                _box_bg     = "#0a2015"
                _box_border = "#00ff88"
                _box_label  = "LONG SETUP"
            else:
                _box_color  = "#a0aec0"
                _box_bg     = "#141829"
                _box_border = "#2d3748"
                _box_label  = "WAITING..."

            st.markdown(
                f"<div style='background:{_box_bg};border:2px solid {_box_border};"
                f"border-radius:12px;padding:24px;text-align:center;margin-bottom:12px'>"
                f"<div style='color:{_box_color};font-size:32px;font-weight:900;"
                f"letter-spacing:2px'>{_box_label}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

            if _sig == "LONG":
                from silvermic_strategy import LOT_SIZE as _SM_LOT
                _ep   = _ent["entry_price"]
                _sl   = _ent["stop_loss"]
                _atr  = _ent["atr"]
                _c1_p = _ep + 1500 / _SM_LOT
                _c2_p = _ep + 4000 / _SM_LOT
                _c3_p = _ep + 11000 / _SM_LOT
                st.markdown(
                    f"<table style='width:100%;border-collapse:collapse;font-size:12px'>"
                    f"<tr><td style='color:#a0aec0;padding:3px 0'>Entry</td>"
                    f"<td style='color:#e0e6ff;text-align:right;font-weight:600'>₹{_ep:,.2f}</td></tr>"
                    f"<tr><td style='color:#ff4455;padding:3px 0'>Stop Loss</td>"
                    f"<td style='color:#ff4455;text-align:right;font-weight:600'>₹{_sl:,.2f}</td></tr>"
                    f"<tr><td style='color:#f6ad55;padding:3px 0'>Cushion ₹1,500</td>"
                    f"<td style='color:#f6ad55;text-align:right'>₹{_c1_p:,.2f}</td></tr>"
                    f"<tr><td style='color:#68d391;padding:3px 0'>Mid ₹4,000</td>"
                    f"<td style='color:#68d391;text-align:right'>₹{_c2_p:,.2f}</td></tr>"
                    f"<tr><td style='color:#00ff88;padding:3px 0'>Big ₹11,000</td>"
                    f"<td style='color:#00ff88;text-align:right'>₹{_c3_p:,.2f}</td></tr>"
                    f"</table>",
                    unsafe_allow_html=True,
                )

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Section 3: Backtest ──────────────────────────────────
        with st.expander("📊 Backtest Results", expanded=False):
            _sm_days = st.selectbox("Backtest window", [30, 60, 90],
                                    index=2, key="sm_bt_days")
            if st.button("▶ Run Backtest", key="sm_run_bt"):
                with st.spinner("Running backtest…"):
                    try:
                        _bt_trades, _bt_summary = _sm_backtest(_sm_token, _sm_days)

                        # Summary row
                        _bm1, _bm2, _bm3, _bm4, _bm5, _bm6 = st.columns(6)
                        _bm1.metric("Trades",       _bt_summary["total"])
                        _bm2.metric("Win Rate",     f"{_bt_summary['win_rate']}%")
                        _pnl_color = "normal" if _bt_summary["total_pnl"] >= 0 else "inverse"
                        _bm3.metric("Total P&L",    f"₹{_bt_summary['total_pnl']:,.0f}",
                                    delta_color=_pnl_color)
                        _bm4.metric("Avg Win",      f"₹{_bt_summary['avg_win']:,.0f}")
                        _bm5.metric("Avg Loss",     f"₹{_bt_summary['avg_loss']:,.0f}")
                        _bm6.metric("Max Drawdown", f"₹{_bt_summary['max_drawdown']:,.0f}")

                        # Equity curve
                        if _bt_summary["equity"]:
                            st.line_chart(
                                pd.Series(_bt_summary["equity"], name="Equity ₹"),
                                use_container_width=True,
                            )

                        # Trade log
                        if _bt_trades:
                            _log_rows = []
                            from silvermic_strategy import IST_OFFSET as _IST_OFFSET
                            for _t in _bt_trades:
                                _ist_entry = _t.entry_time + _IST_OFFSET if _t.entry_time else None
                                _ist_exit  = _t.exit_time  + _IST_OFFSET if _t.exit_time  else None
                                _log_rows.append({
                                    "Entry (IST)":  _ist_entry.strftime("%d-%b %H:%M") if _ist_entry else "",
                                    "Exit (IST)":   _ist_exit.strftime("%d-%b %H:%M")  if _ist_exit  else "",
                                    "Entry ₹":      f"₹{_t.entry_price:,.2f}",
                                    "Exit ₹":       f"₹{_t.exit_price:,.2f}"  if _t.exit_price else "-",
                                    "P&L ₹":        f"₹{_t.pnl_rs:+,.0f}",
                                    "Reason":       _t.exit_reason,
                                })
                            st.dataframe(pd.DataFrame(_log_rows),
                                         use_container_width=True, hide_index=True)
                        else:
                            st.info("No trades found in this backtest window.")

                    except RuntimeError as _e:
                        st.error(str(_e))

    except RuntimeError as _sm_err:
        st.error(str(_sm_err))
    except Exception as _sm_exc:
        st.error(f"Strategy error: {_sm_exc}")


# ── Footer ────────────────────────────────────────────────────
st.markdown(
    "<div style='text-align:center;color:#4a5568;font-size:11px;padding:16px 0 24px;border-top:1px solid #1a1f3a;margin-top:8px'>"
    "⚠️ For informational purposes only. Not financial advice. Always do your own research before trading.<br>"
    "Data: Economic Times · Moneycontrol · Business Standard · LiveMint · Reuters · CNBC · Yahoo Finance"
    "</div>",
    unsafe_allow_html=True,
)
