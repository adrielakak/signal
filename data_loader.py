"""Historical data loader using ccxt (Binance).

Fetches OHLCV for a symbol and timeframe, with optional date range.
Returns a pandas DataFrame with columns: Open, High, Low, Close, Volume and
datetime index in UTC.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List

import pandas as pd


def _tf_to_ms(timeframe: str) -> int:
    t = timeframe.strip().lower()
    if t.endswith("m"):
        return int(t[:-1]) * 60_000
    if t.endswith("h"):
        return int(t[:-1]) * 60 * 60_000
    if t.endswith("d"):
        return int(t[:-1]) * 24 * 60 * 60_000
    if t.endswith("w"):
        return int(t[:-1]) * 7 * 24 * 60 * 60_000
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def _parse_date(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    s = s.strip()
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        # try simple YYYY-MM-DD
        try:
            dt = datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def load_ohlcv(symbol: str, timeframe: str = "1h", start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
    """Load OHLCV data for a symbol from Binance using ccxt.

    This paginates until it reaches the end_date or no more data is returned.
    If start_date is None, it fetches the last ~1000 candles from the end.
    """
    try:
        import ccxt  # type: ignore
    except Exception as e:
        raise RuntimeError("ccxt is required. Install with: pip install ccxt") from e

    tf_ms = _tf_to_ms(timeframe)

    since = _parse_date(start_date)
    until = _parse_date(end_date)

    exchange = ccxt.binance({
        "enableRateLimit": True,
        "options": {"adjustForTimeDifference": True},
    })

    # Attempt to use UTC now if until is None
    if until is None:
        until = int(datetime.now(timezone.utc).timestamp() * 1000)

    limit = 1000  # max per request for many endpoints
    ohlcv: List[list] = []

    # If since is None, fetch the last thousand bars directly
    if since is None:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        ohlcv.extend(data or [])
    else:
        cursor = since
        while True:
            # Stop if we are past until
            if cursor >= until:
                break
            batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=limit)
            if not batch:
                break
            ohlcv.extend(batch)
            # Move cursor by timeframe * (len(batch) - 1) to avoid overlap
            cursor = batch[-1][0] + tf_ms
            # Safety break if huge datasets
            if len(ohlcv) > 100_000:
                break

    if not ohlcv:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])  # empty

    df = pd.DataFrame(ohlcv, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["Date"], unit="ms", utc=True)

    # Trim to end_date if provided
    if until is not None:
        df = df[df["Date"] <= pd.to_datetime(until, unit="ms", utc=True)]

    df = df.set_index("Date")[['Open', 'High', 'Low', 'Close', 'Volume']]
    df.index.name = None
    return df

