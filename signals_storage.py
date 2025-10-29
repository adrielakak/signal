"""Signals storage utilities: CSV append and load, filtering, and alignment.

The CSV schema is:
  timestamp,ticker,signal,price

Where:
  - timestamp: ISO8601 string
  - ticker: TradingView ticker (e.g., CHEEMSCUSD or CHEEMSCUSDT)
  - signal: BUY or SELL
  - price: numeric price at alert time
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd


DEFAULT_SIGNALS_CSV = Path("signals.csv")


def ensure_signals_csv(csv_path: Path | str = DEFAULT_SIGNALS_CSV) -> Path:
    path = Path(csv_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "ticker", "signal", "price"])  # header
    return path


def append_signal(*, signal: str, price: float, ticker: str, timestamp: datetime | str, csv_path: Path | str = DEFAULT_SIGNALS_CSV) -> None:
    path = ensure_signals_csv(csv_path)
    ts_str = timestamp if isinstance(timestamp, str) else timestamp.isoformat()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([ts_str, ticker, signal.upper(), price])


def load_signals(csv_path: Path | str = DEFAULT_SIGNALS_CSV) -> pd.DataFrame:
    path = ensure_signals_csv(csv_path)
    if path.stat().st_size == 0:
        return pd.DataFrame(columns=["timestamp", "ticker", "signal", "price"]).astype(
            {"timestamp": "datetime64[ns]", "ticker": "string", "signal": "string", "price": "float64"}
        )
    df = pd.read_csv(path, parse_dates=["timestamp"])  # timestamp as datetime64[ns]
    # Normalize case and trim
    if not df.empty:
        df["signal"] = df["signal"].astype(str).str.upper().str.strip()
        df["ticker"] = df["ticker"].astype(str).str.strip()
    return df


def _base_from_symbol(symbol: str) -> str:
    # Convert "CHEEMSC/USDT" -> "CHEEMSC"
    s = symbol.strip().upper()
    if "/" in s:
        return s.split("/")[0]
    return s


def filter_signals_for_symbol(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Filter the raw signals for the provided trading pair.

    Heuristic: match by base asset token, e.g. CHEEMSC for CHEEMSC/USDT. Many
    TradingView tickers come as CHEEMSCUSD or CHEEMSCUSDT; we keep rows whose
    ticker starts with the base symbol.
    """
    if df is None or df.empty:
        return df
    base = _base_from_symbol(symbol)
    mask = df["ticker"].astype(str).str.upper().str.startswith(base)
    return df.loc[mask].copy()


def generate_signal_series(index: pd.DatetimeIndex, signals_df: pd.DataFrame) -> pd.Series:
    """Generate a series of numeric signals aligned to an OHLCV index.

    Mapping:
      BUY -> +1
      SELL -> -1
      otherwise -> 0

    Alignment uses the nearest timestamp in the OHLC index for each signal.
    If multiple signals map to the same bar, the last one wins.
    """
    import numpy as np

    ser = pd.Series(0, index=index, dtype="int8")
    if signals_df is None or signals_df.empty:
        return ser

    # Ensure datetime index for efficient searching
    idx = index
    # Pre-convert deltas to numpy for speed (ns since epoch)
    idx_values = idx.asi8

    for _, row in signals_df.iterrows():
        ts = row["timestamp"]
        if pd.isna(ts):
            continue
        try:
            ts_ns = pd.Timestamp(ts).value
        except Exception:
            continue
        # find nearest index position
        pos = np.argmin(np.abs(idx_values - ts_ns))
        sig = row.get("signal", "").upper()
        val = 1 if sig == "BUY" else (-1 if sig == "SELL" else 0)
        if val != 0:
            ser.iloc[pos] = val
    return ser
