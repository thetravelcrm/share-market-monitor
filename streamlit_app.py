"""
streamlit_app.py  –  Web Dashboard for News Monitor + Stock Impact + Trading Signals

Run locally:   streamlit run streamlit_app.py
Deploy:        Push to GitHub → connect at share.streamlit.io
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from pipeline      import run_pipeline, PipelineResult
from impact_analyzer import ImpactResult
from signal_engine import generate_signal

# ── Page config ───────────────────────────────────────────────
st.set_page_config(
    page_title="📡 Market Intelligence Dashboard",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS (dark finance theme) ──────────────────────────
st.markdown("""
<style>
html, body, [class*="css"] { font-family: 'Inter', 'Segoe UI', sans-serif; }
.block-container { padding-top: 1.2rem; padding-bottom: 1rem; }

.news-card {
    background:#0f1923; border:1px solid #1e3448;
    border-left:4px solid #2196F3; border-radius:8px;
    padding:14px 18px; margin-bottom:10px;
}
.news-card-negative { border-left-color:#f44336; }
.news-card-positive { border-left-color:#4caf50; }
.news-card-neutral  { border-left-color:#ff9800; }

.signal-buy   { background:#0a1f0f; border:1px solid #2e7d32; border-left:4px solid #4caf50;
                border-radius:8px; padding:14px 18px; margin:6px 0; }
.signal-short { background:#1f0a0a; border:1px solid #7d2c2c; border-left:4px solid #f44336;
                border-radius:8px; padding:14px 18px; margin:6px 0; }
.signal-avoid { background:#1a1a0a; border:1px solid #4a4a1a; border-left:4px solid #ff9800;
                border-radius:8px; padding:14px 18px; margin:6px 0; }

.opp-card {
    background:#0a1928; border:1px solid #00bcd4;
    border-left:4px solid #00e5ff; border-radius:8px;
    padding:14px 18px; margin-bottom:8px;
}

.badge {
    display:inline-block; padding:2px 10px; border-radius:12px;
    font-size:12px; font-weight:600; margin:2px 4px 2px 0;
}
.badge-extreme  { background:#7f0000; color:#ff8a80; }
.badge-high     { background:#4e0000; color:#ff6659; }
.badge-medium   { background:#4a3600; color:#ffd740; }
.badge-low      { background:#1a3300; color:#b9f6ca; }
.badge-positive { background:#003300; color:#69f0ae; }
.badge-negative { background:#330000; color:#ff6659; }
.badge-neutral  { background:#332b00; color:#ffd740; }
.badge-direct   { background:#001a33; color:#64b5f6; }
.badge-sectoral { background:#0d0d33; color:#9fa8da; }
.badge-macro    { background:#1a0d33; color:#ce93d8; }
.badge-under    { background:#003333; color:#00e5ff; font-size:11px; }

[data-testid="metric-container"] {
    background:#0f1923; border:1px solid #1e3448; border-radius:8px; padding:10px 16px;
}
.section-header {
    color:#90caf9; font-size:16px; font-weight:700; letter-spacing:0.5px;
    margin:18px 0 8px 0; padding-bottom:4px; border-bottom:1px solid #1e3448;
}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
#  Helper functions  (defined before any tab content)
# ═══════════════════════════════════════════════════════════════

_IMPACT_COLOR = {"EXTREME":"badge-extreme","HIGH":"badge-high","MEDIUM":"badge-medium","LOW":"badge-low"}
_SENT_COLOR   = {"Positive":"badge-positive","Negative":"badge-negative","Neutral":"badge-neutral"}
_REL_COLOR    = {"Direct":"badge-direct","Sectoral":"badge-sectoral","Macro":"badge-macro"}
_ACTION_BG    = {"BUY":"signal-buy","SHORT":"signal-short","AVOID":"signal-avoid"}
_REACT_ICON   = {"Underreacted":"👉 UNDERREACTED","Overreacted":"⚠️ OVERREACTED","Reacted":"✅ REACTED"}
_REACT_HEX    = {"Underreacted":"#00e5ff","Overreacted":"#ff9800","Reacted":"#9e9e9e"}
_IMPACT_ORDER = {"EXTREME":4,"HIGH":3,"MEDIUM":2,"LOW":1}


def badge(text: str, cls: str) -> str:
    return f'<span class="badge {cls}">{text}</span>'

def chg_color(pct: float) -> str:
    return "#4caf50" if pct >= 0 else "#f44336"

def conf_bar(score: int) -> str:
    filled = score // 10
    bar    = "█" * filled + "░" * (10 - filled)
    color  = "#4caf50" if score >= 70 else ("#ff9800" if score >= 50 else "#f44336")
    return f'<span style="color:{color};font-family:monospace">{bar} {score}%</span>'

def cur_sym(price_data) -> str:
    if price_data is None: return "₹"
    return "$" if price_data.currency == "USD" else "₹"

def show_impact_table(impacts: list[ImpactResult], only_direct: bool = False):
    rows = []
    for r in impacts:
        if only_direct and r.relation != "Direct":
            continue
        pd_ = r.price_data
        sym = cur_sym(pd_)
        price_str = f"{sym}{pd_.current_price:,.2f}" if pd_ else "—"
        rows.append({
            "Symbol":    r.symbol,
            "Name":      r.name[:18],
            "Sector":    r.sector[:14],
            "Relation":  r.relation,
            "Impact":    r.impact_strength,
            "Price":     price_str,
            "Expected":  f"{r.expected_move_pct:+.1f}%",
            "Actual":    f"{r.actual_move_pct:+.2f}%",
            "Vol Ratio": f"{r.volume_ratio:.1f}x",
            "Status":    _REACT_ICON.get(r.reaction_status, r.reaction_status),
        })
    if not rows:
        return
    df = pd.DataFrame(rows)

    def _color_impact(val):
        c = {"EXTREME":"#b71c1c","HIGH":"#c62828","MEDIUM":"#f57f17","LOW":"#2e7d32"}.get(val,"")
        return f"color:{c};font-weight:bold" if c else ""

    def _color_actual(val):
        try:
            pct = float(str(val).replace("%",""))
            return f"color:{'#4caf50' if pct>=0 else '#f44336'};font-weight:bold"
        except: return ""

    def _color_status(val):
        if "UNDER" in str(val): return "color:#00e5ff;font-weight:bold"
        if "OVER"  in str(val): return "color:#ff9800"
        return "color:#9e9e9e"

    styled = (
        df.style
        .map(_color_impact, subset=["Impact"])
        .map(_color_actual, subset=["Actual"])
        .map(_color_status, subset=["Status"])
        .set_properties(**{"font-size": "12px"})
    )
    st.dataframe(styled, use_container_width=True, hide_index=True,
                 height=min(38 * len(rows) + 42, 320))


# ═══════════════════════════════════════════════════════════════
#  Sidebar
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    st.markdown("---")

    hours         = st.slider("🕐 News lookback (hours)", 2, 48, 12, step=2)
    top_n         = st.slider("📰 Max articles to analyse", 5, 50, 20, step=5)
    fetch_prices  = st.toggle("📈 Fetch live prices (slower)", value=True)
    auto_refresh  = st.toggle("🔄 Auto-refresh", value=False)
    refresh_mins  = st.slider("⏱ Refresh interval (min)", 5, 60, 15, step=5,
                               disabled=not auto_refresh)

    st.markdown("---")
    run_btn = st.button("▶ Run Analysis", type="primary", use_container_width=True)

    st.markdown("---")
    st.markdown("**Display Filters**")
    min_impact   = st.selectbox("Min impact strength", ["LOW","MEDIUM","HIGH","EXTREME"], index=0)
    only_direct  = st.checkbox("Direct matches only")
    only_signals = st.checkbox("Only stocks with signals")

    st.markdown("---")
    st.markdown(
        "<div style='font-size:11px;color:#546e7a'>"
        "Sources: ET · Moneycontrol · BS · Mint · Reuters · CNBC<br>"
        "Prices: Yahoo Finance (NSE.NS / US tickers)<br>"
        "Sentiment: VADER + Finance Lexicon<br><br>"
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
        st_autorefresh(interval=refresh_mins * 60 * 1000, key="autorefresh")
    except ImportError:
        st.sidebar.warning("Install `streamlit-autorefresh` for auto-refresh.")


# ═══════════════════════════════════════════════════════════════
#  Header
# ═══════════════════════════════════════════════════════════════
st.markdown(
    "<h1 style='margin-bottom:0;color:#e3f2fd'>📡 Market Intelligence Dashboard</h1>"
    "<p style='color:#546e7a;margin-top:4px'>"
    "Real-Time News Monitor &nbsp;·&nbsp; Stock Impact Analysis &nbsp;·&nbsp; "
    "Trading Signals &nbsp;·&nbsp; NSE/BSE + Global Majors</p>",
    unsafe_allow_html=True,
)
st.markdown("---")


# ═══════════════════════════════════════════════════════════════
#  Pipeline runner
# ═══════════════════════════════════════════════════════════════
if "result"   not in st.session_state: st.session_state["result"]   = None
if "last_run" not in st.session_state: st.session_state["last_run"] = None


def do_run():
    prog  = st.progress(0, text="Starting…")
    label = st.empty()

    def cb(step: str, pct: float):
        prog.progress(min(pct, 1.0), text=step)
        label.caption(step)

    result = run_pipeline(hours=hours, top_n=top_n,
                          fetch_prices=fetch_prices, progress_cb=cb)
    prog.empty(); label.empty()
    st.session_state["result"]   = result
    st.session_state["last_run"] = datetime.now(tz=timezone.utc)


if run_btn:
    do_run()
elif st.session_state["result"] is None:
    do_run()   # auto-run on first load


result: PipelineResult | None = st.session_state.get("result")

if result is None:
    st.info("Click **▶ Run Analysis** in the sidebar to start.")
    st.stop()

for w in result.warnings:
    st.warning(w)

last_run = st.session_state["last_run"]


# ═══════════════════════════════════════════════════════════════
#  Summary metrics row
# ═══════════════════════════════════════════════════════════════
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("📰 Articles Fetched",  result.items_total)
m2.metric("🔍 Items Analysed",    result.items_analyzed)
m3.metric("💰 Signals Generated", len(result.all_signals))
m4.metric("👉 Underreacted",      len(result.underreacted))
m5.metric("🕐 Last Updated",      last_run.strftime("%H:%M UTC") if last_run else "—")

st.markdown("<br>", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
#  Tabs
# ═══════════════════════════════════════════════════════════════
tab_news, tab_signals, tab_opps, tab_top5, tab_sectors = st.tabs([
    "📰 News & Impact",
    "💰 Trade Signals",
    "👉 Underreacted",
    "🔥 Top 5 Stocks",
    "📈 Sector Rotation",
])


# ───────────────────────────────────────────────────────────────
#  TAB 1 — News & Impact
# ───────────────────────────────────────────────────────────────
with tab_news:
    if not result.news_impacts:
        st.info("No significant news-stock matches found. Try increasing the lookback hours.")
    else:
        shown = 0
        for idx, (item, sentiment, impacts) in enumerate(result.news_impacts[:15], 1):

            # Filters
            max_imp = max((_IMPACT_ORDER.get(r.impact_strength,0) for r in impacts), default=0)
            if _IMPACT_ORDER.get(min_impact, 0) > max_imp:
                continue
            if only_direct and not any(r.relation=="Direct" for r in impacts):
                continue
            if only_signals and not any(generate_signal(r) for r in impacts):
                continue

            nc  = sentiment.label.lower()
            sc  = _SENT_COLOR.get(sentiment.label, "badge-neutral")

            st.markdown(
                f'<div class="news-card news-card-{nc}">'
                f'<div style="font-size:15px;font-weight:600;color:#e3f2fd;margin-bottom:6px">'
                f'#{idx} &nbsp; {item.title}</div>'
                f'<div style="font-size:12px;color:#78909c">'
                f'<b style="color:#90a4ae">{item.source}</b> &nbsp;·&nbsp; '
                f'{badge(sentiment.category,"badge-direct")} '
                f'{badge(sentiment.label, sc)} '
                f'<span style="color:#546e7a">score {sentiment.score:+.2f}</span>'
                f'&nbsp;·&nbsp;<span style="color:#546e7a">{item.published.strftime("%d %b %H:%M")}</span>'
                f'</div></div>',
                unsafe_allow_html=True,
            )

            if item.summary:
                with st.expander("📄 Read summary & source link"):
                    st.caption(item.summary[:600])
                    if item.url:
                        st.markdown(f"[Open full article →]({item.url})")

            show_impact_table(impacts, only_direct)

            # Inline signal for high-confidence direct matches
            for r in impacts[:3]:
                sig = generate_signal(r)
                if sig and sig.confidence >= 50 and r.relation == "Direct":
                    ac = _ACTION_BG.get(sig.action, "signal-avoid")
                    act_col = {"BUY":"#4caf50","SHORT":"#f44336","AVOID":"#ff9800"}.get(sig.action,"#fff")
                    under_b = '<span class="badge badge-under">★ UNDERREACTION</span>' \
                              if r.reaction_status == "Underreacted" else ""
                    sym = cur_sym(r.price_data)
                    price_html = ""
                    if sig.entry_low > 0:
                        price_html = (
                            f'<div style="display:flex;gap:20px;flex-wrap:wrap;margin:8px 0 4px">'
                            f'<div><span style="color:#546e7a;font-size:11px">ENTRY</span><br>'
                            f'<b>{sym}{sig.entry_low:,.2f}–{sym}{sig.entry_high:,.2f}</b></div>'
                            f'<div><span style="color:#546e7a;font-size:11px">SL</span><br>'
                            f'<b style="color:#f44336">{sym}{sig.stop_loss:,.2f}</b></div>'
                            f'<div><span style="color:#546e7a;font-size:11px">T1</span><br>'
                            f'<b style="color:#81c784">{sym}{sig.target1:,.2f}</b></div>'
                            f'<div><span style="color:#546e7a;font-size:11px">T2</span><br>'
                            f'<b style="color:#4caf50">{sym}{sig.target2:,.2f}</b></div>'
                            f'<div><span style="color:#546e7a;font-size:11px">R:R</span><br>'
                            f'<b>{sig.risk_reward:.1f}x</b></div>'
                            f'</div>'
                        )
                    st.markdown(
                        f'<div class="{ac}" style="margin-top:4px">'
                        f'<b style="color:{act_col}">{sig.action}</b> &nbsp;'
                        f'<b style="color:#e3f2fd">{sig.symbol}</b> &nbsp;{under_b}'
                        f'&nbsp;&nbsp;{conf_bar(sig.confidence)}'
                        f'{price_html}'
                        f'<div style="font-size:11px;color:#546e7a;font-style:italic;margin-top:4px">'
                        f'{sig.rationale}</div></div>',
                        unsafe_allow_html=True,
                    )

            st.markdown("<br>", unsafe_allow_html=True)
            shown += 1

        if shown == 0:
            st.info("No items match your current filters.")


# ───────────────────────────────────────────────────────────────
#  TAB 2 — Trade Signals
# ───────────────────────────────────────────────────────────────
with tab_signals:
    if not result.all_signals:
        st.info("No trade signals generated. Try lowering min impact or extending lookback hours.")
    else:
        st.caption(f"{len(result.all_signals)} signals · use filters below")
        fc1, fc2, fc3 = st.columns(3)
        sig_action   = fc1.multiselect("Action", ["BUY","SHORT","AVOID"], default=["BUY","SHORT"])
        sig_min_conf = fc2.slider("Min Confidence", 0, 100, 40, step=5)
        sig_edges    = fc3.multiselect("Edge Type",
                         ["Underreaction","Momentum","Macro","Mean-Reversion"],
                         default=["Underreaction","Momentum","Macro","Mean-Reversion"])

        shown = 0
        for item, imp, sig in result.all_signals:
            if sig.action   not in sig_action:  continue
            if sig.confidence < sig_min_conf:    continue
            if sig.edge_type not in sig_edges:   continue

            is_under = imp.reaction_status == "Underreacted"
            card_cls = _ACTION_BG.get(sig.action, "signal-avoid")
            act_col  = {"BUY":"#4caf50","SHORT":"#f44336","AVOID":"#ff9800"}.get(sig.action,"#fff")
            sym      = cur_sym(imp.price_data)

            price_html = ""
            if sig.entry_low > 0:
                price_html = (
                    f'<div style="display:flex;gap:28px;flex-wrap:wrap;margin:10px 0 6px">'
                    f'<div><span style="color:#546e7a;font-size:11px">ENTRY</span><br>'
                    f'<b style="color:#e3f2fd">{sym}{sig.entry_low:,.2f} – {sym}{sig.entry_high:,.2f}</b></div>'
                    f'<div><span style="color:#546e7a;font-size:11px">STOP LOSS</span><br>'
                    f'<b style="color:#f44336">{sym}{sig.stop_loss:,.2f}</b></div>'
                    f'<div><span style="color:#546e7a;font-size:11px">TARGET 1</span><br>'
                    f'<b style="color:#81c784">{sym}{sig.target1:,.2f}</b></div>'
                    f'<div><span style="color:#546e7a;font-size:11px">TARGET 2</span><br>'
                    f'<b style="color:#4caf50">{sym}{sig.target2:,.2f}</b></div>'
                    f'<div><span style="color:#546e7a;font-size:11px">R:R RATIO</span><br>'
                    f'<b style="color:#fff">{sig.risk_reward:.1f}x</b></div>'
                    f'<div><span style="color:#546e7a;font-size:11px">HORIZON</span><br>'
                    f'<b style="color:#90caf9">{sig.time_horizon}</b></div>'
                    f'</div>'
                )

            under_b = '<span class="badge badge-under">★ UNDERREACTION</span>' if is_under else ""

            st.markdown(
                f'<div class="{card_cls}">'
                f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">'
                f'<span style="font-size:20px;font-weight:700;color:{act_col}">{sig.action}</span>'
                f'<span style="font-size:17px;font-weight:700;color:#e3f2fd">{sig.symbol}</span>'
                f'<span style="color:#78909c">— {sig.name}</span>'
                f'{under_b}</div>'
                f'<div>{badge(imp.impact_strength,_IMPACT_COLOR.get(imp.impact_strength,""))}'
                f'     {badge(imp.sentiment_label,_SENT_COLOR.get(imp.sentiment_label,""))}'
                f'     {badge(sig.edge_type,"badge-direct")}'
                f'     {badge(imp.sector,"badge-sectoral")}</div>'
                f'{price_html}'
                f'<div style="margin-top:8px"><span style="color:#546e7a;font-size:11px">CONFIDENCE &nbsp;</span>'
                f'{conf_bar(sig.confidence)}</div>'
                f'<div style="margin-top:8px;font-size:11px;color:#546e7a;font-style:italic">{sig.rationale}</div>'
                f'<div style="margin-top:6px;font-size:11px;color:#37474f">'
                f'📰 {item.title[:90]}…&nbsp;·&nbsp;{item.source}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            shown += 1

        if shown == 0:
            st.info("No signals match the current filters.")


# ───────────────────────────────────────────────────────────────
#  TAB 3 — Underreacted Opportunities
# ───────────────────────────────────────────────────────────────
with tab_opps:
    st.markdown(
        "<div class='section-header'>👉 Underreacted Trade Opportunities</div>"
        "<p style='color:#78909c;font-size:13px'>"
        "Stocks where news impact is significantly larger than price reaction. "
        "Volume not yet confirmed — potential smart-money entry window.</p>",
        unsafe_allow_html=True,
    )

    if not result.underreacted:
        st.success("✅ Market has priced in all major news — no underreaction detected.")
    else:
        for i, (item, imp, sig) in enumerate(result.underreacted[:5], 1):
            gap     = abs(imp.expected_move_pct - imp.actual_move_pct)
            act_col = {"BUY":"#4caf50","SHORT":"#f44336"}.get(sig.action,"#ff9800")
            sym     = cur_sym(imp.price_data)
            price_now = f"{sym}{imp.price_data.current_price:,.2f}" if imp.price_data else "—"

            st.markdown(
                f'<div class="opp-card">'
                f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
                f'<div><span style="font-size:22px;font-weight:700;color:#00e5ff">#{i}</span>'
                f'  <span style="font-size:18px;font-weight:700;color:#e3f2fd;margin-left:8px">{sig.symbol}</span>'
                f'  <span style="color:#78909c"> — {sig.name}</span>'
                f'  {badge(imp.sector,"badge-sectoral")}</div>'
                f'<span style="color:#546e7a;font-size:12px">{item.published.strftime("%d %b %H:%M")}</span>'
                f'</div>'
                f'<div style="display:flex;gap:24px;flex-wrap:wrap;margin:12px 0 8px">'
                f'<div><span style="color:#546e7a;font-size:11px">PRICE NOW</span><br>'
                f'     <b style="font-size:16px;color:#e3f2fd">{price_now}</b></div>'
                f'<div><span style="color:#546e7a;font-size:11px">EXPECTED MOVE</span><br>'
                f'     <b style="font-size:16px;color:#ff9800">{imp.expected_move_pct:+.1f}%</b></div>'
                f'<div><span style="color:#546e7a;font-size:11px">ACTUAL MOVE</span><br>'
                f'     <b style="font-size:16px;color:{"#4caf50" if imp.actual_move_pct>=0 else "#f44336"}">'
                f'     {imp.actual_move_pct:+.2f}%</b></div>'
                f'<div><span style="color:#546e7a;font-size:11px">EDGE (GAP)</span><br>'
                f'     <b style="font-size:16px;color:#00e5ff">{gap:.1f}%</b></div>'
                f'<div><span style="color:#546e7a;font-size:11px">VOL RATIO</span><br>'
                f'     <b style="font-size:16px;color:#e3f2fd">{imp.volume_ratio:.1f}x</b></div>'
                f'<div><span style="color:#546e7a;font-size:11px">SIGNAL</span><br>'
                f'     <b style="font-size:16px;color:{act_col}">{sig.action}</b></div>'
                f'<div><span style="color:#546e7a;font-size:11px">CONFIDENCE</span><br>'
                f'     {conf_bar(sig.confidence)}</div>'
                f'</div>'
                f'<div style="color:#455a64;font-size:12px">📰 {item.title[:110]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        # Summary table
        st.markdown("<br>", unsafe_allow_html=True)
        rows = [{
            "Symbol":    sig.symbol,
            "Name":      imp.name,
            "Action":    sig.action,
            "Expected":  f"{imp.expected_move_pct:+.1f}%",
            "Actual":    f"{imp.actual_move_pct:+.2f}%",
            "Gap":       f"{abs(imp.expected_move_pct-imp.actual_move_pct):.1f}%",
            "Vol Ratio": f"{imp.volume_ratio:.1f}x",
            "Conf":      f"{sig.confidence}%",
            "Horizon":   sig.time_horizon,
        } for _, imp, sig in result.underreacted]

        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ───────────────────────────────────────────────────────────────
#  TAB 4 — Top 5 Most Impacted Stocks
# ───────────────────────────────────────────────────────────────
with tab_top5:
    st.markdown("<div class='section-header'>🔥 Top 5 Most Impacted Stocks Today</div>",
                unsafe_allow_html=True)

    if not result.top5:
        st.info("No direct stock matches yet.")
    else:
        for rank, (headline, r) in enumerate(result.top5, 1):
            pd_     = r.price_data
            sym     = cur_sym(pd_)
            price_s = f"{sym}{pd_.current_price:,.2f}" if pd_ else "—"
            chg_col = chg_color(r.actual_move_pct)
            imp_col = {"EXTREME":"#b71c1c","HIGH":"#c62828","MEDIUM":"#f57f17","LOW":"#2e7d32"}.get(r.impact_strength,"#fff")

            left, right = st.columns([1, 3])
            with left:
                st.markdown(
                    f'<div style="text-align:center;background:#0f1923;border:1px solid #1e3448;'
                    f'border-radius:8px;padding:16px 8px">'
                    f'<div style="font-size:28px;font-weight:700;color:#90caf9">#{rank}</div>'
                    f'<div style="font-size:20px;font-weight:700;color:#e3f2fd">{r.symbol}</div>'
                    f'<div style="font-size:12px;color:#78909c">{r.name}</div>'
                    f'<div style="font-size:22px;font-weight:700;color:{chg_col};margin-top:8px">'
                    f'{r.actual_move_pct:+.2f}%</div>'
                    f'<div style="font-size:13px;color:#546e7a">{price_s}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with right:
                st.markdown(
                    f'<div style="background:#0f1923;border:1px solid #1e3448;border-radius:8px;'
                    f'padding:16px 20px">'
                    f'<div style="margin-bottom:10px">'
                    f'{badge(r.impact_strength,_IMPACT_COLOR.get(r.impact_strength,""))}'
                    f'{badge(r.sentiment_label,_SENT_COLOR.get(r.sentiment_label,""))}'
                    f'{badge(r.sector,"badge-sectoral")}'
                    f'</div>'
                    f'<div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:10px">'
                    f'<div><span style="color:#546e7a;font-size:11px">EXPECTED MOVE</span><br>'
                    f'     <b style="color:#ff9800">{r.expected_move_pct:+.1f}%</b></div>'
                    f'<div><span style="color:#546e7a;font-size:11px">VOL RATIO</span><br>'
                    f'     <b style="color:#e3f2fd">{r.volume_ratio:.1f}x</b></div>'
                    f'<div><span style="color:#546e7a;font-size:11px">STATUS</span><br>'
                    f'     <b style="color:{_REACT_HEX.get(r.reaction_status,"#fff")}">'
                    f'     {_REACT_ICON.get(r.reaction_status,r.reaction_status)}</b></div>'
                    f'</div>'
                    f'<div style="color:#546e7a;font-size:12px;font-style:italic">📰 {headline}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            st.markdown("<br>", unsafe_allow_html=True)

        # Quick comparison chart
        syms  = [r.symbol for _, r in result.top5]
        moves = [r.actual_move_pct for _, r in result.top5]
        exp   = [r.expected_move_pct for _, r in result.top5]

        fig = go.Figure()
        fig.add_trace(go.Bar(name="Actual Move", x=syms, y=moves,
                             marker_color=["#4caf50" if v>=0 else "#f44336" for v in moves]))
        fig.add_trace(go.Bar(name="Expected Move", x=syms, y=exp,
                             marker_color=["rgba(255,152,0,0.4)"]*len(exp)))
        fig.update_layout(
            barmode="group", plot_bgcolor="#0a1218", paper_bgcolor="#0a1218",
            font=dict(color="#b0bec5"), legend=dict(orientation="h", y=1.1),
            yaxis=dict(ticksuffix="%", gridcolor="#1e2d3d"),
            margin=dict(t=30,b=30,l=40,r=20), height=280,
        )
        st.plotly_chart(fig, use_container_width=True)


# ───────────────────────────────────────────────────────────────
#  TAB 5 — Sector Rotation
# ───────────────────────────────────────────────────────────────
with tab_sectors:
    st.markdown("<div class='section-header'>📈 Sector Rotation Trends</div>",
                unsafe_allow_html=True)

    if not result.flat_impacts:
        st.info("Not enough data for sector analysis.")
    else:
        sector_moves: dict[str, list[float]] = {}
        sector_scores: dict[str, list[int]]  = {}
        for _, r in result.flat_impacts:
            sector_moves.setdefault(r.sector, []).append(r.actual_move_pct)
            sector_scores.setdefault(r.sector, []).append(
                {"EXTREME":4,"HIGH":3,"MEDIUM":2,"LOW":1}.get(r.impact_strength,0))

        sector_avg  = {s: round(sum(v)/len(v),2) for s,v in sector_moves.items()}
        sorted_secs = sorted(sector_avg.items(), key=lambda x: x[1], reverse=True)
        labels  = [s for s,_ in sorted_secs]
        values  = [v for _,v in sorted_secs]
        counts  = [len(sector_moves[s]) for s in labels]
        colors  = ["#4caf50" if v>=0 else "#f44336" for v in values]

        # Bar chart — avg move
        fig1 = go.Figure(go.Bar(
            x=labels, y=values, marker_color=colors,
            text=[f"{v:+.2f}%  ({c})" for v,c in zip(values,counts)],
            textposition="outside", textfont=dict(size=11, color="#b0bec5"),
        ))
        fig1.update_layout(
            title=dict(text="Average Price Move by Sector", font=dict(color="#90caf9")),
            plot_bgcolor="#0a1218", paper_bgcolor="#0a1218",
            font=dict(color="#b0bec5"),
            xaxis=dict(tickangle=-30, gridcolor="#1e2d3d"),
            yaxis=dict(gridcolor="#1e2d3d", ticksuffix="%"),
            margin=dict(t=50,b=90,l=40,r=20), height=380,
        )
        st.plotly_chart(fig1, use_container_width=True)

        # Scatter — Impact Score vs Move (bubble = # stocks)
        heat_rows = [{
            "Sector":           s,
            "Avg Impact Score": round(sum(sector_scores[s])/len(sector_scores[s]),2),
            "# Stocks":         len(sector_scores[s]),
            "Avg Move %":       round(sector_avg.get(s,0),2),
        } for s in sector_avg]
        heat_df = pd.DataFrame(heat_rows).sort_values("Avg Impact Score", ascending=False)

        fig2 = px.scatter(
            heat_df, x="Avg Impact Score", y="Avg Move %",
            size="# Stocks", color="Avg Move %",
            color_continuous_scale=["#b71c1c","#f44336","#ff9800","#4caf50","#1b5e20"],
            text="Sector", range_color=[-5, 5],
            title="Impact vs Price Reaction (bubble size = # stocks affected)",
        )
        fig2.update_traces(textposition="top center", textfont=dict(size=10, color="#b0bec5"))
        fig2.update_layout(
            plot_bgcolor="#0a1218", paper_bgcolor="#0a1218",
            font=dict(color="#b0bec5", size=12),
            title=dict(font=dict(color="#90caf9")),
            xaxis=dict(gridcolor="#1e2d3d", title="Impact Score  (1=Low → 4=Extreme)"),
            yaxis=dict(gridcolor="#1e2d3d", ticksuffix="%", title="Avg Price Move"),
            coloraxis_colorbar=dict(title="Move %", ticksuffix="%"),
            margin=dict(t=50,b=40,l=60,r=20), height=420,
        )
        st.plotly_chart(fig2, use_container_width=True)

        with st.expander("📊 Raw Sector Table"):
            st.dataframe(heat_df.sort_values("Avg Impact Score", ascending=False),
                         use_container_width=True, hide_index=True)


# ───────────────────────────────────────────────────────────────
#  Footer
# ───────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#37474f;font-size:11px'>"
    "⚠️ For informational purposes only. Not financial advice. Always do your own research.<br>"
    "Data: Economic Times · Moneycontrol · Business Standard · LiveMint · Reuters · CNBC · Yahoo Finance"
    "</div>",
    unsafe_allow_html=True,
)
