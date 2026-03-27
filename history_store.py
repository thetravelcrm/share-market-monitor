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


def signal_to_dict(sig) -> dict:
    """Convert a TradeSignal dataclass to a JSON-safe dict."""
    return {
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
    }


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
    signals: list of TradeSignal objects
    """
    ist_now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    run_id  = ist_now.strftime("%Y%m%d_%H%M%S")
    entry   = {
        "run_id":     run_id,
        "run_time":   datetime.now(timezone.utc).isoformat(),
        "slot_label": slot_label,
        "signals":    [signal_to_dict(s) for s in signals],
    }
    history = load_history()
    history.append(entry)
    save_history(history)
    return run_id
