# ─────────────────────────────────────────────────────────────
#  history_store.py  –  Archive scheduled pipeline runs (signal predictions)
#
#  Persistence layers (tried in order on save, first-success wins on load):
#    1. GitHub Gist  — requires GITHUB_TOKEN + GIST_HISTORY_ID in Streamlit secrets
#    2. Local JSON   — signal_history.json (works within container lifetime)
#    3. cache_resource — in-memory (survives reruns, not server restarts)
#
#  Auto-prunes entries older than 30 days.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

HISTORY_FILE = "signal_history.json"
MAX_DAYS     = 30
_GIST_FILENAME = "signal_history.json"


# ── GitHub Gist helpers ───────────────────────────────────────

def _gist_headers() -> dict | None:
    """Return auth headers if GITHUB_TOKEN is in Streamlit secrets, else None."""
    try:
        import streamlit as st
        token = st.secrets.get("GITHUB_TOKEN", "")
        return {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"} if token else None
    except Exception:
        return None


def _gist_id() -> str:
    """Return GIST_HISTORY_ID from Streamlit secrets, or '' if not set."""
    try:
        import streamlit as st
        return st.secrets.get("GIST_HISTORY_ID", "")
    except Exception:
        return ""


def gist_configured() -> bool:
    """True if both GITHUB_TOKEN and GIST_HISTORY_ID are in Streamlit secrets."""
    return bool(_gist_headers() and _gist_id())


def _gist_load() -> list[dict] | None:
    """Fetch history from GitHub Gist. Returns None if not configured/failed."""
    headers = _gist_headers()
    gist_id = _gist_id()
    if not headers or not gist_id:
        return None
    try:
        import requests
        r = requests.get(f"https://api.github.com/gists/{gist_id}",
                         headers=headers, timeout=15)
        if r.status_code != 200:
            import logging
            logging.getLogger("history_store").warning(
                "Gist load failed: HTTP %s — %s", r.status_code, r.text[:200])
            return None
        content = r.json().get("files", {}).get(_GIST_FILENAME, {}).get("content", "")
        return json.loads(content) if content else []
    except Exception as e:
        import logging
        logging.getLogger("history_store").warning("Gist load exception: %s", e)
        return None


def _gist_save(entries: list[dict]) -> bool:
    """Write history to GitHub Gist. Returns True on success."""
    headers = _gist_headers()
    gist_id = _gist_id()
    if not headers or not gist_id:
        return False
    try:
        import requests
        payload = {
            "files": {
                _GIST_FILENAME: {
                    "content": json.dumps(entries, indent=2, ensure_ascii=False)
                }
            }
        }
        r = requests.patch(f"https://api.github.com/gists/{gist_id}",
                           json=payload, headers=headers, timeout=20)
        return r.status_code == 200
    except Exception:
        return False


# ── Signal helpers ────────────────────────────────────────────

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
    """
    try:
        import streamlit as st

        @st.cache_resource
        def _store():
            return {"entries": [], "loaded": False}

        return _store()
    except Exception:
        return {"entries": [], "loaded": False}


def load_history() -> list[dict]:
    """
    Load history. Priority: cache_resource → Gist → local JSON file.
    Always returns a list (may be empty).
    """
    store = _get_history_store()

    # Already loaded this process — use cache
    if store["loaded"] and store["entries"]:
        return store["entries"]

    if not store["loaded"]:
        store["loaded"] = True

        # 1. Try GitHub Gist (survives server restarts)
        gist_data = _gist_load()
        if gist_data is not None:
            store["entries"] = _prune(gist_data)
            return store["entries"]

        # 2. Fall back to local JSON file
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, "r", encoding="utf-8") as fh:
                    store["entries"] = _prune(json.load(fh))
        except Exception:
            store["entries"] = []

    return store["entries"]


def save_history(entries: list[dict]) -> None:
    """Persist to Gist (primary) + local JSON file + cache_resource."""
    pruned = _prune(entries)

    # Update in-memory cache
    store = _get_history_store()
    store["entries"] = pruned

    # 1. GitHub Gist — survives server restarts
    _gist_save(pruned)

    # 2. Local JSON file — fast within-container backup
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as fh:
            json.dump(pruned, fh, indent=2, ensure_ascii=False)
    except Exception:
        pass


def get_last_run_utc() -> datetime | None:
    """Return the UTC datetime of the most recent run, or None if no history."""
    history = load_history()
    if not history:
        return None
    latest = max(history, key=lambda e: e.get("run_time", ""), default=None)
    if not latest:
        return None
    try:
        dt = datetime.fromisoformat(latest["run_time"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


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
