# ─────────────────────────────────────────────────────────────
#  mcx_costs.py — what a spread trade REALLY costs.
#
#  Two things a naive "edge" calculation gets wrong, both of which decide whether a
#  trade actually makes money:
#
#  1. CHARGES. Modelled exactly, not estimated. Verified to the paisa against a real
#     Zerodha MCX contract note (SILVER100 Nov/Aug, 05 Aug 2026 — total ₹19.83):
#         brokerage 13.85 · CTT 2.28 · exchange 0.97 · SEBI 0.05 · GST 2.68
#     Note brokerage is 0.03% of turnover CAPPED at ₹20/order, so small contracts pay
#     proportionally far more: a flat "0.03% of notional" assumption understated
#     SILVER100's round trip by ~3x.
#
#  2. DEPTH. Top-of-book bid/ask is only your price if the size you want is sitting
#     there. With 2 lots on the bid and 6 on the offer, a 10-lot order walks the book
#     and pays materially worse. These helpers price your ACTUAL size by walking the
#     ladder, so "10x edge" can't be reported on a spread nobody will trade with you.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

# Zerodha / MCX futures, as verified against a live contract note.
BROKERAGE_RATE = 0.0003      # 0.03% of turnover…
BROKERAGE_CAP = 20.0         # …capped at ₹20 per executed order
CTT_RATE = 0.0001            # 0.01%, SELL side of futures only
EXCHANGE_RATE = 0.000021     # ~0.0021% of turnover
SEBI_RATE = 0.000001         # ₹10 per crore
STAMP_RATE = 0.00002         # 0.002%, BUY side only
GST_RATE = 0.18              # on brokerage + exchange + SEBI


def order_charges(notional: float, side: str) -> float:
    """Charges for ONE executed futures order. side: 'BUY' | 'SELL'."""
    brokerage = min(BROKERAGE_RATE * notional, BROKERAGE_CAP)
    exchange = EXCHANGE_RATE * notional
    sebi = SEBI_RATE * notional
    ctt = CTT_RATE * notional if side.upper() == "SELL" else 0.0
    stamp = STAMP_RATE * notional if side.upper() == "BUY" else 0.0
    gst = GST_RATE * (brokerage + exchange + sebi)
    return brokerage + exchange + sebi + ctt + stamp + gst


def spread_round_trip_charges(near_notional: float, far_notional: float) -> float:
    """All charges to open AND close a calendar spread (4 orders). Over the round trip
    each leg is bought once and sold once, so direction doesn't change the total."""
    return sum(order_charges(n, s)
               for n in (near_notional, far_notional)
               for s in ("BUY", "SELL"))


def walk_book(levels: list[dict], lots: int) -> tuple[float | None, int]:
    """Average fill price for `lots` walking a depth ladder, and how many lots the
    book can actually fill. levels: [{'price': float, 'volume': int}] best-first
    (volume in LOTS). Returns (vwap, filled) — vwap is None if nothing is available."""
    need, cost, filled = lots, 0.0, 0
    for lvl in levels or []:
        px, vol = float(lvl.get("price", 0) or 0), int(lvl.get("volume", 0) or 0)
        if px <= 0 or vol <= 0:
            continue
        take = min(need, vol)
        cost += take * px
        filled += take
        need -= take
        if need <= 0:
            break
    return ((cost / filled) if filled else None), filled


def execution_cost(near_depth: dict, far_depth: dict, lots: int,
                   multiplier: float) -> dict:
    """True round-trip cost of a calendar spread for a GIVEN SIZE.

    Crossing cost = the effective bid-ask each leg pays for `lots` (buy VWAP − sell
    VWAP, walked through the ladder), which equals what you give up entering and
    exiting. Adds exact charges. Returns ₹ per spread (all `lots`), plus whether the
    book can actually fill you.

    depth dicts: {'bids': [{price, volume}…], 'asks': [{price, volume}…]}
    """
    out: dict = {"lots": lots, "fillable": False}
    n_buy, n_bf = walk_book(near_depth.get("asks"), lots)
    n_sell, n_sf = walk_book(near_depth.get("bids"), lots)
    f_buy, f_bf = walk_book(far_depth.get("asks"), lots)
    f_sell, f_sf = walk_book(far_depth.get("bids"), lots)
    out["fillable_lots"] = min(n_bf, n_sf, f_bf, f_sf)
    if None in (n_buy, n_sell, f_buy, f_sell) or out["fillable_lots"] < lots:
        return out                       # book can't support this size

    out["fillable"] = True
    # Per-unit cost of crossing both legs' books, for this size.
    cross_per_unit = (f_buy - f_sell) + (n_buy - n_sell)
    out["cross_per_unit"] = round(cross_per_unit, 4)
    out["cross_inr"] = round(cross_per_unit * multiplier * lots, 2)
    near_notional = ((n_buy + n_sell) / 2) * multiplier * lots
    far_notional = ((f_buy + f_sell) / 2) * multiplier * lots
    out["charges_inr"] = round(spread_round_trip_charges(near_notional, far_notional), 2)
    out["total_inr"] = round(out["cross_inr"] + out["charges_inr"], 2)
    # Same number expressed per price unit, so it can be compared to a spread edge.
    out["total_per_unit"] = round(out["total_inr"] / (multiplier * lots), 4)
    out["touch_only_per_unit"] = round(
        ((far_depth["asks"][0]["price"] - far_depth["bids"][0]["price"]) +
         (near_depth["asks"][0]["price"] - near_depth["bids"][0]["price"])), 4)
    return out
