# ─────────────────────────────────────────────────────────────
#  backtester.py  –  Historical signal validation using yfinance
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import yfinance as yf


def backtest_signal(
    symbol: str,
    action: str,          # "BUY" | "SHORT"
    entry: float,
    target: float,        # target2 (full target)
    stop: float,
    signal_date: datetime,
    horizon_days: int = 5,
) -> dict:
    """
    Simulate a single trade: did price hit target or stop within horizon_days?
    Returns: {outcome, actual_return_pct, hit_target, hit_stop, max_favourable, max_adverse}
    """
    try:
        ticker_sym = f"{symbol}.NS"
        start = signal_date.date()
        end   = (signal_date + timedelta(days=horizon_days + 5)).date()  # extra buffer for weekends

        hist = yf.Ticker(ticker_sym).history(start=str(start), end=str(end),
                                             interval="1d", auto_adjust=True)
        if hist.empty or len(hist) < 1:
            return {"outcome": "No Data", "actual_return_pct": 0,
                    "hit_target": False, "hit_stop": False,
                    "max_favourable": 0, "max_adverse": 0}

        # Skip first bar (entry day) — check from next day onwards
        check = hist.iloc[1:horizon_days + 1] if len(hist) > 1 else hist

        hit_target = False
        hit_stop   = False
        final_price = float(hist["Close"].iloc[-1])

        for _, row in check.iterrows():
            high_px = float(row["High"])
            low_px  = float(row["Low"])
            if action == "BUY":
                if high_px >= target:
                    hit_target = True; break
                if low_px  <= stop:
                    hit_stop   = True; break
            else:  # SHORT
                if low_px  <= target:
                    hit_target = True; break
                if high_px >= stop:
                    hit_stop   = True; break

        if action == "BUY":
            actual_return = round((final_price - entry) / entry * 100, 2) if entry > 0 else 0
            max_fav = round((check["High"].max() - entry) / entry * 100, 2) if entry > 0 else 0
            max_adv = round((check["Low"].min()  - entry) / entry * 100, 2) if entry > 0 else 0
        else:
            actual_return = round((entry - final_price) / entry * 100, 2) if entry > 0 else 0
            max_fav = round((entry - check["Low"].min())  / entry * 100, 2) if entry > 0 else 0
            max_adv = round((entry - check["High"].max()) / entry * 100, 2) if entry > 0 else 0

        if hit_target:
            outcome = "WIN"
        elif hit_stop:
            outcome = "LOSS"
        else:
            outcome = "WIN" if actual_return > 0 else ("LOSS" if actual_return < -1 else "BREAK-EVEN")

        return {
            "outcome":          outcome,
            "actual_return_pct": actual_return,
            "hit_target":       hit_target,
            "hit_stop":         hit_stop,
            "max_favourable":   max_fav,
            "max_adverse":      max_adv,
        }
    except Exception:
        return {"outcome": "Error", "actual_return_pct": 0,
                "hit_target": False, "hit_stop": False,
                "max_favourable": 0, "max_adverse": 0}


def run_backtest(
    journal_df: pd.DataFrame,
    horizon_days: int = 5,
    progress_cb=None,
) -> pd.DataFrame:
    """
    Run backtest over all closed + open trades in the journal.
    Returns enriched DataFrame with outcome columns added.
    """
    if journal_df.empty:
        return journal_df

    rows = []
    total = len(journal_df)
    for i, (_, row) in enumerate(journal_df.iterrows()):
        if progress_cb:
            progress_cb(f"Backtesting {row.get('symbol', '')}…", i / total)
        try:
            date_str = str(row.get("date", ""))
            sig_date = datetime.strptime(date_str[:16], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except Exception:
            sig_date = datetime.now(tz=timezone.utc) - timedelta(days=10)

        res = backtest_signal(
            symbol      = str(row.get("symbol", "")),
            action      = str(row.get("action", "BUY")),
            entry       = float(row.get("entry", 0) or 0),
            target      = float(row.get("target2", 0) or 0),
            stop        = float(row.get("stop_loss", 0) or 0),
            signal_date = sig_date,
            horizon_days= horizon_days,
        )
        rows.append({**row.to_dict(), **res})

    return pd.DataFrame(rows)


def backtest_stats(bt_df: pd.DataFrame) -> dict:
    """Aggregate stats from a backtest DataFrame."""
    if bt_df.empty or "outcome" not in bt_df.columns:
        return {}
    valid   = bt_df[bt_df["outcome"].isin(["WIN", "LOSS", "BREAK-EVEN"])]
    wins    = len(valid[valid["outcome"] == "WIN"])
    losses  = len(valid[valid["outcome"] == "LOSS"])
    win_rate= round(wins / len(valid) * 100, 1) if len(valid) > 0 else 0
    returns = pd.to_numeric(valid["actual_return_pct"], errors="coerce").dropna()
    by_edge = {}
    if "edge_type" in valid.columns:
        for edge, grp in valid.groupby("edge_type"):
            ew = len(grp[grp["outcome"] == "WIN"])
            by_edge[edge] = round(ew / len(grp) * 100, 1) if len(grp) else 0
    return {
        "total":    len(valid),
        "wins":     wins,
        "losses":   losses,
        "win_rate": win_rate,
        "avg_return": round(float(returns.mean()), 2) if not returns.empty else 0,
        "best":     round(float(returns.max()),  2) if not returns.empty else 0,
        "worst":    round(float(returns.min()),  2) if not returns.empty else 0,
        "by_edge":  by_edge,
    }
