# ─────────────────────────────────────────────────────────────
#  spread_backtest.py — does the SILVERMIC calendar-spread
#  mean-reversion rule actually make money after friction?
#
#  Walk-forward, NO LOOKAHEAD: the band at each bar is built from a rolling window
#  of bars strictly BEFORE it (.shift(1)), so an entry never "knows" the extreme it
#  is trading against. Friction is charged on every round trip.
#
#  Rule under test (the same one the live tab shows):
#      position% = (spread − band_min) / (band_max − band_min) × 100
#      pos <= entry_pct        -> LONG the spread  (buy far / sell near)
#      pos >= 100 − entry_pct  -> SHORT the spread (sell far / buy near)
#      exit when pos reverts to exit_pct (the band mid), on a stop, or a time stop
#      entry also requires edge (distance to mid) >= min_edge_mult × cost
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

import pandas as pd

logger = logging.getLogger(__name__)

# Round-trip friction per lot pair when historical bid/ask isn't available:
# both legs' typical bid-ask width + ~₹130 statutory/brokerage. Conservative.
DEFAULT_COST = 300.0


def fetch_spread_series(token: str, near_hist: str, far_hist: str,
                        days: int = 180, resolution: str = "15") -> pd.Series:
    """Aligned far−near spread series over `days`, fetched in chunks (Fyers caps the
    range per intraday request). Returns an empty Series when history is unavailable."""
    from silvermic_continuous import _fetch_one
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    frames_n, frames_f = [], []
    cur, step = start, timedelta(days=60)
    while cur < end:
        chunk_end = min(cur + step, end)
        d_from, d_to = cur.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")
        n = _fetch_one(near_hist, token, resolution, d_from, d_to)
        f = _fetch_one(far_hist, token, resolution, d_from, d_to)
        if n is not None and not n.empty:
            frames_n.append(n)
        if f is not None and not f.empty:
            frames_f.append(f)
        cur = chunk_end
    if not frames_n or not frames_f:
        logger.warning("spread series: no history for %s / %s", near_hist, far_hist)
        return pd.Series(dtype=float)
    near = pd.concat(frames_n).sort_index()
    far = pd.concat(frames_f).sort_index()
    near = near[~near.index.duplicated(keep="last")]
    far = far[~far.index.duplicated(keep="last")]
    return (far["Close"] - near["Close"]).dropna()          # inner-aligns on timestamp


def _metrics(trades: list[dict], series_days: float) -> dict:
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "expectancy": 0.0, "total_pnl": 0.0,
                "avg_win": 0.0, "avg_loss": 0.0, "profit_factor": 0.0,
                "max_drawdown": 0.0, "avg_hold_days": 0.0, "trades_per_month": 0.0}
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trades":          len(trades),
        "win_rate":        round(len(wins) / len(trades) * 100, 1),
        "expectancy":      round(sum(pnls) / len(trades), 0),
        "total_pnl":       round(sum(pnls), 0),
        "avg_win":         round(gross_win / len(wins), 0) if wins else 0.0,
        "avg_loss":        round(-gross_loss / len(losses), 0) if losses else 0.0,
        "profit_factor":   round(gross_win / gross_loss, 2) if gross_loss else float("inf"),
        "max_drawdown":    round(max_dd, 0),
        "avg_hold_days":   round(sum(t["hold_days"] for t in trades) / len(trades), 1),
        "trades_per_month": round(len(trades) / max(series_days / 30.0, 0.1), 1),
    }


def backtest(spread: pd.Series, lookback_days: int = 30, entry_pct: float = 20.0,
             exit_pct: float = 50.0, cost: float = DEFAULT_COST,
             max_hold_days: int = 10, min_edge_mult: float = 1.5,
             stop_rs: float = 0.0) -> dict:
    """Walk-forward simulation of the mean-reversion rule. Returns metrics + trades
    + an equity curve. P&L is ₹ per lot pair (SILVERMIC = 1 kg/lot)."""
    if spread is None or spread.empty or len(spread) < 100:
        return {"error": "Not enough history to backtest (need ~100+ bars).",
                "trades": [], "metrics": _metrics([], 1)}

    roll = spread.rolling(f"{lookback_days}D")
    # shift(1): the band uses only bars STRICTLY BEFORE the current one -> no lookahead
    band_min = roll.min().shift(1)
    band_max = roll.max().shift(1)
    rng = band_max - band_min
    mid = (band_min + band_max) / 2
    pos = (spread - band_min) / rng * 100

    trades: list[dict] = []
    side = None
    entry_px = entry_t = entry_mid = None

    for t, px in spread.items():
        p, m, r = pos.get(t), mid.get(t), rng.get(t)
        if pd.isna(p) or pd.isna(m) or pd.isna(r) or r <= 0:
            continue

        if side is None:
            edge = abs(px - m)
            if edge < min_edge_mult * cost:
                continue                      # can't pay its own friction — skip
            if p <= entry_pct:
                side, entry_px, entry_t, entry_mid = "LONG", px, t, m
            elif p >= 100 - entry_pct:
                side, entry_px, entry_t, entry_mid = "SHORT", px, t, m
            continue

        # open position → check exits
        move = (px - entry_px) if side == "LONG" else (entry_px - px)
        hold_days = (t - entry_t).total_seconds() / 86400
        reason = None
        if side == "LONG" and p >= exit_pct:
            reason = "target (band mid)"
        elif side == "SHORT" and p <= exit_pct:
            reason = "target (band mid)"
        elif stop_rs and move <= -abs(stop_rs):
            reason = "stop"
        elif hold_days >= max_hold_days:
            reason = "time stop"
        if reason:
            trades.append({
                "side": side, "entry_time": entry_t, "exit_time": t,
                "entry": round(entry_px, 0), "exit": round(px, 0),
                "gross": round(move, 0), "pnl": round(move - cost, 0),
                "hold_days": round(hold_days, 1), "reason": reason,
            })
            side = entry_px = entry_t = entry_mid = None

    span_days = (spread.index[-1] - spread.index[0]).total_seconds() / 86400
    equity, curve = 0.0, []
    for tr in trades:
        equity += tr["pnl"]
        curve.append({"time": tr["exit_time"], "equity": round(equity, 0)})
    return {"metrics": _metrics(trades, span_days), "trades": trades,
            "equity": curve, "span_days": round(span_days, 1),
            "bars": len(spread), "open_position": side is not None}


def optimize(spread: pd.Series, cost: float = DEFAULT_COST,
             lookbacks=(20, 30, 45, 60), entries=(10.0, 15.0, 20.0, 25.0, 30.0),
             min_trades: int = 5, **kw) -> list[dict]:
    """Grid-search the band lookback and entry threshold. Returns rows sorted by
    total P&L, keeping only settings with enough trades to mean anything."""
    rows = []
    for lb in lookbacks:
        for ep in entries:
            res = backtest(spread, lookback_days=lb, entry_pct=ep, cost=cost, **kw)
            m = res.get("metrics") or {}
            if m.get("trades", 0) >= min_trades:
                rows.append({"lookback_days": lb, "entry_pct": ep, **m})
    rows.sort(key=lambda r: r["total_pnl"], reverse=True)
    return rows
