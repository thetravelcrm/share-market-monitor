# ─────────────────────────────────────────────────────────────
#  history_store.py  –  Archive scheduled pipeline runs (signal predictions)
#  Storage: st.cache_resource (primary) + signal_history.json (backup)
#  Auto-prunes entries older than 30 days.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

HISTORY_FILE = "signal_history.json"
MAX_DAYS     = 30


def signal_to_dict(sig, imp=None) -> dict:
    """Convert a TradeSignal dataclass (+ optional ImpactResult) to a JSON-safe dict."""
    prediction_price = 0.0
    if sig.entry_low > 0 and sig.entry_high > 0:
        prediction_price = round((sig.entry_low + sig.entry_high) / 2, 2)
    elif sig.entry_low > 0:
        prediction_price = sig.entry_low
    # NO TRADE signals have entry=0; save live market price at signal time instead
    if prediction_price == 0.0 and imp is not None:
        _pd = getattr(imp, "price_data", None)
        if _pd is not None:
            prediction_price = round(getattr(_pd, "current_price", 0.0), 2)

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
        "impact_strength":   "",
        "sector":            "",
        "relation":          "",
        "expected_move_pct": 0.0,
        "news_type":         "Ongoing",
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


def _get_history_store():
    """
    Persistent in-memory store via st.cache_resource.
    Survives Streamlit reruns within the same server process.
    Falls back gracefully when called outside Streamlit (e.g., tests).
    """
    try:
        import streamlit as st

        @st.cache_resource
        def _store():
            return {"entries": [], "loaded_from_file": False}

        return _store()
    except Exception:
        # Outside Streamlit — return a plain dict (no persistence)
        return {"entries": [], "loaded_from_file": False}


def load_history() -> list[dict]:
    """
    Load history. Priority: cache_resource (in-process) → JSON file.
    Always returns a list (may be empty).
    """
    store = _get_history_store()

    # If cache_resource already has data, use it (survives reruns)
    if store["entries"]:
        return store["entries"]

    # First time this process has loaded: try the JSON file
    if not store["loaded_from_file"]:
        store["loaded_from_file"] = True
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, "r", encoding="utf-8") as fh:
                    store["entries"] = _prune(json.load(fh))
        except Exception:
            store["entries"] = []

    return store["entries"]


def save_history(entries: list[dict]) -> None:
    """Persist to cache_resource (in-process) and write JSON file backup."""
    store = _get_history_store()
    store["entries"] = _prune(entries)
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as fh:
            json.dump(store["entries"], fh, indent=2, ensure_ascii=False)
    except Exception:
        pass  # Streamlit Cloud filesystem may be read-only — cache_resource still works


def append_run(slot_label: str, signals: list) -> str:
    """
    Archive a new scheduled run. Returns the run_id.
    slot_label: e.g. "09:15 IST" | "13:00 IST" | "Manual"
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
            continue

        for sig in entry.get("signals", []):
            if sig.get("outcome"):
                continue
            if sig.get("action") not in ("BUY", "SHORT"):
                continue
            if sig.get("impact_strength") not in ("HIGH", "EXTREME"):
                continue

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
