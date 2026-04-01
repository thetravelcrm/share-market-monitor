# ─────────────────────────────────────────────────────────────
#  history_store.py  –  Archive scheduled pipeline runs (signal predictions)
#  Storage: session_state (primary) + signal_history.json (backup)
#  Auto-prunes entries older than 30 days.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

HISTORY_FILE = "signal_history.json"
SESSION_KEY  = "signal_history"
MAX_DAYS     = 30


def signal_to_dict(sig, imp=None) -> dict:
    """Convert a TradeSignal dataclass (+ optional ImpactResult) to a JSON-safe dict."""
    prediction_price = 0.0
    if sig.entry_low > 0 and sig.entry_high > 0:
        prediction_price = round((sig.entry_low + sig.entry_high) / 2, 2)
    elif sig.entry_low > 0:
        prediction_price = sig.entry_low

    d = {
        "symbol":       sig.symbol,
        "name":         sig.name,
        "action":       sig.action,
        "entry_low":    sig.entry_low,
        "entry_high":   sig.entry_high,
        "stop_loss":    sig.stop_loss,
        "target1":      sig.target1,
        "target2":      sig.target2,
        "risk_reward":  sig.risk_reward,
        "confidence":   sig.confidence,
        "time_horizon": sig.time_horizon,
        "edge_type":    sig.edge_type,
        "rationale":    sig.rationale,
        "prediction_price": prediction_price,
        # Impact fields — populated from ImpactResult if provided
        "impact_strength":   "",
        "sector":            "",
        "relation":          "",
        "expected_move_pct": 0.0,
        "news_type":         "Ongoing",
        # Outcome fields — auto-filled later by check_and_update_outcomes()
        "outcome":            None,
        "outcome_return_pct": None,
        "hit_target":         None,
        "hit_stop":           None,
        "outcome_check_date": None,
    }
    if imp is not None:
        d["impact_strength"]   = getattr(imp, "impact_strength", "")
        d["sector"]            = getattr(imp, "sector", "")
        d["relation"]          = getattr(imp, "relation", "")
        d["expected_move_pct"] = getattr(imp, "expected_move_pct", 0.0)
        d["news_type"]         = getattr(imp, "news_type", "Ongoing")
    return d


def _prune(entries: list[dict]) -> list[dict]:
    """Remove entries older than MAX_DAYS."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_DAYS)).isoformat()
    return [e for e in entries if e.get("run_time", "") >= cutoff]


def load_history() -> list[dict]:
    """
    Load history from session_state; fall back to JSON file on first call.
    Always returns a list (may be empty).
    """
    import streamlit as st
    if SESSION_KEY in st.session_state:
        return st.session_state[SESSION_KEY]
    # First call in this session — try loading from file
    entries: list[dict] = []
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as fh:
                entries = _prune(json.load(fh))
    except Exception:
        entries = []
    st.session_state[SESSION_KEY] = entries
    return entries


def save_history(entries: list[dict]) -> None:
    """Persist to session_state and write JSON file backup."""
    import streamlit as st
    entries = _prune(entries)
    st.session_state[SESSION_KEY] = entries
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2, ensure_ascii=False)
    except Exception:
        pass  # Streamlit Cloud filesystem may be read-only — silent fail


def append_run(slot_label: str, signals: list) -> str:
    """
    Archive a new scheduled run. Returns the run_id.
    slot_label: e.g. "09:15 IST" | "13:00 IST" | "15:20 IST" | "Manual"
    signals: list of TradeSignal objects OR list of (TradeSignal, ImpactResult) tuples
    """
    ist_now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    run_id  = ist_now.strftime("%Y%m%d_%H%M%S")

    sig_dicts = []
    for item in signals:
        if isinstance(item, tuple) and len(item) == 2:
            sig, imp = item
            sig_dicts.append(signal_to_dict(sig, imp))
        else:
            sig_dicts.append(signal_to_dict(item))

    entry = {
        "run_id":     run_id,
        "run_time":   datetime.now(timezone.utc).isoformat(),
        "slot_label": slot_label,
        "signals":    sig_dicts,
    }
    history = load_history()
    history.append(entry)
    save_history(history)
    return run_id


def check_and_update_outcomes(entries: list[dict]) -> tuple[list[dict], bool]:
    """
    For HIGH/EXTREME BUY/SHORT signals older than 5 days with no outcome,
    run backtest and persist result. Returns (updated_entries, changed).
    """
    from backtester import backtest_signal
    changed = False
    cutoff = datetime.now(timezone.utc) - timedelta(days=5)

    for entry in entries:
        run_time_str = entry.get("run_time", "")
        if not run_time_str:
            continue
        try:
            run_time = datetime.fromisoformat(run_time_str)
        except ValueError:
            continue
        if run_time.tzinfo is None:
            run_time = run_time.replace(tzinfo=timezone.utc)
        if run_time > cutoff:
            continue  # too recent — wait 5 days

        for sig in entry.get("signals", []):
            if sig.get("outcome"):
                continue  # already verified
            if sig.get("action") not in ("BUY", "SHORT"):
                continue  # no targets to verify
            if sig.get("impact_strength") not in ("HIGH", "EXTREME"):
                continue  # only track top-impact predictions

            pred_entry = sig.get("prediction_price") or sig.get("entry_low", 0)
            if not pred_entry or pred_entry <= 0:
                continue

            try:
                res = backtest_signal(
                    symbol=sig["symbol"],
                    action=sig["action"],
                    entry=pred_entry,
                    target=sig["target2"],
                    stop=sig["stop_loss"],
                    signal_date=run_time,
                    horizon_days=5,
                )
                sig["outcome"]            = res.get("outcome")
                sig["outcome_return_pct"] = res.get("actual_return_pct")
                sig["hit_target"]         = res.get("hit_target")
                sig["hit_stop"]           = res.get("hit_stop")
                sig["outcome_check_date"] = datetime.now(timezone.utc).isoformat()
                changed = True
            except Exception:
                pass

    return entries, changed
