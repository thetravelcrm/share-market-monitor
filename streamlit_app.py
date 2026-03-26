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
    padding: 18px 28px;
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
        "BUY":   ("STRONG BUY", "sig-strong-buy"),
        "SHORT": ("SHORT / SELL", "sig-short"),
        "AVOID": ("AVOID", "sig-avoid"),
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

def why_underreacted(imp: ImpactResult) -> str:
    reasons = []
    if imp.volume_ratio < 1.2:
        reasons.append("volume not yet confirmed — low participation")
    if imp.relation == "Direct" and abs(imp.actual_move_pct) < 1:
        reasons.append("price barely moved despite high-impact news")
    if imp.impact_strength in ("HIGH", "EXTREME"):
        reasons.append(f"{imp.impact_strength.lower()} impact news still digesting")
    return " · ".join(reasons) if reasons else "market still pricing in the event"


# ═══════════════════════════════════════════════════════════════
#  Sidebar
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown(
        "<div style='padding:10px 0 6px;color:#00d4ff;font-weight:700;font-size:15px'>⚙️ Settings</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")
    hours        = st.slider("🕐 News lookback (hours)", 2, 48, 12, step=2)
    top_n        = st.slider("📰 Max articles", 5, 50, 20, step=5)
    fetch_prices = st.toggle("📈 Live prices", value=True)
    auto_refresh = st.toggle("🔄 Auto-refresh", value=False)
    refresh_mins = st.slider("⏱ Interval (min)", 5, 60, 15, step=5, disabled=not auto_refresh)

    st.markdown("---")
    run_btn = st.button("▶  Run Analysis", type="primary", use_container_width=True)

    st.markdown("---")
    st.markdown("<div style='color:#a8b0d0;font-size:12px;font-weight:600'>DISPLAY FILTERS</div>",
                unsafe_allow_html=True)
    min_impact   = st.selectbox("Min impact", ["LOW", "MEDIUM", "HIGH", "EXTREME"], index=0)
    only_direct  = st.checkbox("Direct matches only")
    only_signals = st.checkbox("With signals only")

    st.markdown("---")
    st.markdown(
        "<div style='font-size:11px;color:#6b7280;line-height:1.7'>"
        "📡 Sources: ET · Moneycontrol · BS · Mint · Reuters · CNBC<br>"
        "📊 Prices: Yahoo Finance (NSE / US)<br>"
        "🧠 NLP: VADER + Finance Lexicon<br><br>"
        "⚠️ Not financial advice."
        "</div>",
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════
#  Auto-refresh
# ═══════════════════════════════════════════════════════════════
if auto_refresh:
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=refresh_mins * 60 * 1000, key="ar")
    except ImportError:
        pass


# ═══════════════════════════════════════════════════════════════
#  Header
# ═══════════════════════════════════════════════════════════════
mkt_status, mkt_color = market_status()
ist_now = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%d %b %Y  %H:%M IST")
utc_now = datetime.now(timezone.utc).strftime("%H:%M UTC")

st.markdown(
    f"""
    <div class="dash-header">
      <div>
        <h1>📡 Global News Monitor & Market Impact Analysis</h1>
        <div style="color:#a8b0d0;font-size:12px;margin-top:4px">
          NSE · BSE · US Markets &nbsp;|&nbsp; Sentiment · Signals · Opportunities
        </div>
      </div>
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <div class="status-pill">
          <strong>Market Status</strong>
          <span style="color:{mkt_color};font-weight:600">{mkt_status}</span>
        </div>
        <div class="status-pill">
          <strong>IST Time</strong>{ist_now}
        </div>
        <div class="status-pill">
          <strong>Last Refresh</strong>{utc_now}
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ═══════════════════════════════════════════════════════════════
#  Pipeline runner
# ═══════════════════════════════════════════════════════════════
if "result"   not in st.session_state: st.session_state["result"]   = None
if "last_run" not in st.session_state: st.session_state["last_run"] = None

def do_run():
    prog  = st.progress(0, text="Starting…")
    label = st.empty()
    def cb(step, pct):
        prog.progress(min(pct, 1.0), text=step)
        label.caption(step)
    result = run_pipeline(hours=hours, top_n=top_n, fetch_prices=fetch_prices, progress_cb=cb)
    prog.empty(); label.empty()
    st.session_state["result"]   = result
    st.session_state["last_run"] = datetime.now(tz=timezone.utc)

if run_btn:
    do_run()

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


# ═══════════════════════════════════════════════════════════════
#  Main tabs
# ═══════════════════════════════════════════════════════════════
tab_impact, tab_opps, tab_signals, tab_sectors, tab_news = st.tabs([
    "🔥 Top Impacted",
    "⚡ Underreacted",
    "🎯 Trade Signals",
    "📈 Sector Sentiment",
    "📰 News Feed",
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
            st.plotly_chart(fig, width='stretch')

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
            act_col  = "#00ff88" if sig.action == "BUY" else "#ff4455"
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
                st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)


# ───────────────────────────────────────────────────────────────
#  TAB 3  —  Trading Signals
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

        # Group by action for the tab layout
        buys    = [(item,imp,sig) for item,imp,sig in result.all_signals
                   if sig.action=="BUY"   and sig.confidence>=sig_min_conf and sig.edge_type in sig_edges]
        shorts  = [(item,imp,sig) for item,imp,sig in result.all_signals
                   if sig.action=="SHORT" and sig.confidence>=sig_min_conf and sig.edge_type in sig_edges]
        avoids  = [(item,imp,sig) for item,imp,sig in result.all_signals
                   if sig.action=="AVOID" and sig.confidence>=sig_min_conf and sig.edge_type in sig_edges]

        sub1, sub2, sub3 = st.tabs([
            f"✅ BUY ({len(buys)})",
            f"🔴 SHORT ({len(shorts)})",
            f"⚠️ AVOID ({len(avoids)})",
        ])

        def render_signal_cards(signals, card_class):
            if not signals:
                st.info("No signals in this category.")
                return
            for item, imp, sig in signals:
                sym      = cur_sym(imp.price_data)
                is_under = imp.reaction_status == "Underreacted"
                price_html = ""
                if sig.entry_low > 0:
                    price_html = (
                        f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;'
                        f'margin:10px 0 8px">'
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
                        f'</div>'
                    )
                under_b = '<span class="badge badge-under">★ UNDERREACTION</span>' if is_under else ""
                imp_s   = impact_score(imp.impact_strength)
                imp_cls = {"EXTREME":"badge-extreme","HIGH":"badge-high",
                           "MEDIUM":"badge-medium","LOW":"badge-low"}.get(imp.impact_strength,"badge-teal")

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
                    f'  {badge(sig.edge_type, "badge-teal")}'
                    f'  {badge(imp.sector, "badge-gold")}'
                    f'</div>'
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

        with sub1: render_signal_cards(buys,   "signal-card-buy")
        with sub2: render_signal_cards(shorts,  "signal-card-short")
        with sub3: render_signal_cards(avoids,  "signal-card-avoid")


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
            st.plotly_chart(fig, width='stretch')

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
            st.plotly_chart(fig2, width='stretch')
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
                        st.dataframe(pd.DataFrame(df_rows), width='stretch',
                                     hide_index=True, height=min(38*len(df_rows)+40, 220))


# ── Footer ────────────────────────────────────────────────────
st.markdown(
    "<div style='text-align:center;color:#4a5568;font-size:11px;padding:16px 0 24px;border-top:1px solid #1a1f3a;margin-top:8px'>"
    "⚠️ For informational purposes only. Not financial advice. Always do your own research before trading.<br>"
    "Data: Economic Times · Moneycontrol · Business Standard · LiveMint · Reuters · CNBC · Yahoo Finance"
    "</div>",
    unsafe_allow_html=True,
)
