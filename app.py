from fastapi import FastAPI, Query
from typing import List
import yfinance as yf
import numpy as np
import math
import concurrent.futures

app = FastAPI()


# ─────────────────────────────────────────────
# UTILS
# ─────────────────────────────────────────────


def clean_value(v):
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
    except Exception:
        pass
    return v


def get_spot(t):
    spot = None
    try:
        fast_info = t.fast_info
        spot = fast_info.get("lastPrice") or fast_info.get("last_price")
    except Exception:
        pass
    if spot is None:
        try:
            info = t.info or {}
            spot = info.get("currentPrice") or info.get("regularMarketPrice")
        except Exception:
            pass
    if spot is None:
        try:
            hist = t.history(period="5d")
            if hist is not None and not hist.empty:
                spot = float(hist["Close"].dropna().iloc[-1])
        except Exception:
            pass
    return spot


# ─────────────────────────────────────────────
# HEALTH
# ─────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok"}


# ─────────────────────────────────────────────
# /chain  — full option chain for one ticker
# ─────────────────────────────────────────────


@app.get("/chain")
def chain(ticker: str = Query(...), expiry: str | None = Query(None)):
    t = yf.Ticker(ticker)

    expiries = list(t.options)
    if not expiries:
        return {
            "ticker": ticker.upper(),
            "spotPrice": None,
            "expiries": [],
            "calls": [],
        }

    spot = get_spot(t)

    calls = []
    expiries_to_process = [expiry] if expiry else expiries

    for exp in expiries_to_process:
        try:
            option_chain = t.option_chain(exp)
            for _, row in option_chain.calls.iterrows():
                calls.append(
                    {
                        "contractSymbol": clean_value(row.get("contractSymbol")),
                        "strike": clean_value(row.get("strike")),
                        "lastPrice": clean_value(row.get("lastPrice")),
                        "bid": clean_value(row.get("bid")),
                        "ask": clean_value(row.get("ask")),
                        "volume": clean_value(row.get("volume")),
                        "openInterest": clean_value(row.get("openInterest")),
                        "impliedVolatility": clean_value(row.get("impliedVolatility")),
                        "inTheMoney": clean_value(row.get("inTheMoney")),
                        "expiration": exp,
                    }
                )
        except Exception:
            continue

    return {
        "ticker": ticker.upper(),
        "spotPrice": spot,
        "expiries": expiries,
        "calls": calls,
    }


# ─────────────────────────────────────────────
# /stockmetrics  — volatility + sentiment metrics
# ─────────────────────────────────────────────


def compute_metrics(ticker: str):
    try:
        t = yf.Ticker(ticker)

        # 1. spot price
        spot = get_spot(t)

        # 2. 1-year price history for RV
        hist = None
        try:
            hist = t.history(period="1y")
        except Exception:
            pass

        # 3. Realized Volatility (30-day annualised)
        rv_30d = None
        try:
            if hist is not None and len(hist) >= 21:
                close = hist["Close"].dropna()
                log_ret = np.log(close / close.shift(1)).dropna()
                rv_30d = float(round(log_ret.tail(21).std() * np.sqrt(252), 4))
        except Exception:
            pass

        # 4. Option chain — first 4 near-term expiries
        expiries = list(t.options or [])
        call_oi, put_oi = 0, 0
        call_vol, put_vol = 0, 0
        iv_values = []

        for exp in expiries[:4]:
            try:
                oc = t.option_chain(exp)

                for _, row in oc.calls.iterrows():
                    call_oi += int(row.get("openInterest") or 0)
                    call_vol += int(row.get("volume") or 0)
                    iv = row.get("impliedVolatility")
                    if iv and not math.isnan(float(iv)) and float(iv) > 0:
                        iv_values.append(float(iv))

                for _, row in oc.puts.iterrows():
                    put_oi += int(row.get("openInterest") or 0)
                    put_vol += int(row.get("volume") or 0)

            except Exception:
                continue

        # 5. Current IV (median of collected values)
        iv_current = None
        if iv_values:
            s = sorted(iv_values)
            iv_current = round(s[len(s) // 2], 4)

        # 6. IV Rank  — (currentIV − low) / (high − low) × 100
        # True IVR needs daily IV history; we approximate from the
        # distribution of IV values across all fetched contracts.
        iv_rank = iv_52wk_low = iv_52wk_high = None
        if iv_values and iv_current is not None:
            iv_52wk_low = round(min(iv_values), 4)
            iv_52wk_high = round(max(iv_values), 4)
            if iv_52wk_high > iv_52wk_low:
                iv_rank = round(
                    (iv_current - iv_52wk_low) / (iv_52wk_high - iv_52wk_low) * 100, 2
                )

        # 7. IV Change (rising / falling)
        # Compare median IV of first expiry vs last expiry as a proxy.
        iv_change = iv_direction = None
        try:
            if len(expiries) >= 2:

                def median_iv(chain_calls):
                    vals = [
                        float(r.get("impliedVolatility"))
                        for _, r in chain_calls.iterrows()
                        if r.get("impliedVolatility")
                        and not math.isnan(float(r.get("impliedVolatility")))
                    ]
                    return sorted(vals)[len(vals) // 2] if vals else None

                oc_near = t.option_chain(expiries[0])
                oc_far = t.option_chain(expiries[-1])
                iv_near = median_iv(oc_near.calls)
                iv_far = median_iv(oc_far.calls)

                if iv_near is not None and iv_far is not None:
                    iv_change = round(iv_near - iv_far, 4)
                    iv_direction = "rising" if iv_change > 0 else "falling"
        except Exception:
            pass

        # 8. IV vs RV (Volatility Risk Premium)
        vrp = None
        if iv_current is not None and rv_30d is not None:
            vrp = round(iv_current - rv_30d, 4)

        # 9. Put / Call ratios
        pcr_oi = round(put_oi / call_oi, 4) if call_oi > 0 else None
        pcr_vol = round(put_vol / call_vol, 4) if call_vol > 0 else None

        return {
            "ticker": ticker.upper(),
            "price": clean_value(spot),
            # ── Implied Volatility ──
            "ivCurrent": clean_value(iv_current),
            "ivRank": clean_value(iv_rank),  # 0-100
            "iv52wkLow": clean_value(iv_52wk_low),
            "iv52wkHigh": clean_value(iv_52wk_high),
            # ── IV Change (near-term vs long-dated proxy) ──
            "ivChange": clean_value(iv_change),
            "ivDirection": iv_direction,  # "rising" / "falling"
            # ── IV vs Realized Vol (VRP) ──
            "rv30d": clean_value(rv_30d),
            "vrp": clean_value(vrp),  # positive = IV > RV → sell premium
            "vrpSignal": (
                "sell_premium"
                if vrp is not None and vrp > 0
                else "buy_vol" if vrp is not None and vrp < 0 else None
            ),
            # ── Open Interest + Volume ──
            "callOI": call_oi,
            "putOI": put_oi,
            "callVolume": call_vol,
            "putVolume": put_vol,
            # ── Put / Call Ratios ──
            "putCallRatioOI": clean_value(pcr_oi),
            "putCallRatioVolume": clean_value(pcr_vol),
            "putCallSignal": (
                "bearish"
                if pcr_oi is not None and pcr_oi > 1
                else "bullish" if pcr_oi is not None and pcr_oi < 1 else "neutral"
            ),
        }

    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


@app.get("/stockmetrics")
def stock_metrics(tickers: List[str] = Query(...)):
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(compute_metrics, tickers))
    return {"results": results}
