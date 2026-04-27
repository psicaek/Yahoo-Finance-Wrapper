from fastapi import FastAPI, Query
import yfinance as yf
import math

app = FastAPI()


def clean_value(v):
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
    except Exception:
        pass
    return v


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/chain")
def chain(ticker: str = Query(...), expiry: str | None = Query(None)):
    t = yf.Ticker(ticker)

    expiries = list(t.options)
    if not expiries:
        return {
            "ticker": ticker.upper(),
            "spotPrice": spot,
            "expiries": [],
            "calls": [],
        }

    selected_expiry = expiry or expiries[0]
    chain = t.option_chain(selected_expiry)

    info = {}
    try:
        info = t.fast_info
    except Exception:
        info = {}

    spot = None

    try:
        fast_info = t.fast_info
        if fast_info:
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

    calls = []
    for _, row in chain.calls.iterrows():
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
                "expiration": selected_expiry,
            }
        )

    return {
        "ticker": ticker.upper(),
        "spotPrice": spot,
        "expiries": expiries,
        "selectedExpiry": selected_expiry,
        "calls": calls,
    }
