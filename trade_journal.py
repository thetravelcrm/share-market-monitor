# ─────────────────────────────────────────────────────────────
#  trade_journal.py  –  Log and track trades vs signals
#  Storage: session_state on Streamlit Cloud (export/import CSV)
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

COLUMNS = [
    "date", "symbol", "name", "action",
    "entry", "stop_loss", "target1", "target2",
    "rr_ratio", "confidence", "edge_type",
    "result", "exit_price", "pnl_pct", "notes",
]


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


def load_journal() -> pd.DataFrame:
    """Load journal from Streamlit session_state."""
    try:
        import streamlit as st
        df = st.session_state.get("trade_journal_df")
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    return _empty_df()


def save_journal(df: pd.DataFrame) -> None:
    """Save journal DataFrame back to session_state."""
    try:
        import streamlit as st
        st.session_state["trade_journal_df"] = df
    except Exception:
        pass


def add_trade(
    symbol: str,
    name: str,
    action: str,
    entry: float,
    stop_loss: float,
    target1: float,
    target2: float,
    rr_ratio: float,
    confidence: int,
    edge_type: str,
    notes: str = "",
) -> None:
    """Add a new trade entry to the journal."""
    df = load_journal()
    row = {
        "date":       datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "symbol":     symbol,
        "name":       name,
        "action":     action,
        "entry":      entry,
        "stop_loss":  stop_loss,
        "target1":    target1,
        "target2":    target2,
        "rr_ratio":   rr_ratio,
        "confidence": confidence,
        "edge_type":  edge_type,
        "result":     "Open",
        "exit_price": 0.0,
        "pnl_pct":    0.0,
        "notes":      notes,
    }
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_journal(df)


def update_trade(idx: int, exit_price: float, result: str) -> None:
    """Mark a trade as WIN/LOSS/BREAK-EVEN with exit price."""
    df = load_journal()
    if idx >= len(df):
        return
    entry = float(df.at[idx, "entry"])
    action = str(df.at[idx, "action"])
    pnl = 0.0
    if entry > 0 and exit_price > 0:
        if action == "BUY":
            pnl = round((exit_price - entry) / entry * 100, 2)
        else:
            pnl = round((entry - exit_price) / entry * 100, 2)
    df.at[idx, "exit_price"] = exit_price
    df.at[idx, "result"]     = result
    df.at[idx, "pnl_pct"]    = pnl
    save_journal(df)


def get_stats(df: Optional[pd.DataFrame] = None) -> dict:
    """Compute win rate, avg return, best/worst trade from closed trades."""
    if df is None:
        df = load_journal()
    closed = df[df["result"].isin(["WIN", "LOSS", "BREAK-EVEN"])].copy()
    if closed.empty:
        return {"total": len(df), "closed": 0, "win_rate": 0, "avg_pnl": 0,
                "best": 0, "worst": 0, "open": len(df)}
    wins     = len(closed[closed["result"] == "WIN"])
    win_rate = round(wins / len(closed) * 100, 1) if len(closed) > 0 else 0
    pnls     = pd.to_numeric(closed["pnl_pct"], errors="coerce").dropna()
    return {
        "total":    len(df),
        "closed":   len(closed),
        "open":     len(df) - len(closed),
        "wins":     wins,
        "win_rate": win_rate,
        "avg_pnl":  round(float(pnls.mean()), 2) if not pnls.empty else 0,
        "best":     round(float(pnls.max()),  2) if not pnls.empty else 0,
        "worst":    round(float(pnls.min()),  2) if not pnls.empty else 0,
    }


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def from_csv_bytes(data: bytes) -> pd.DataFrame:
    try:
        df = pd.read_csv(io.BytesIO(data))
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df[COLUMNS]
    except Exception:
        return _empty_df()
