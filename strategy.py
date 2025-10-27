"""Backtesting strategy that executes based on external BUY/SELL signals.

This strategy expects a DataFrame of signals passed via Backtest.run as a
parameter `signals_df` and will align each signal to the nearest candle.

BUY:
  - If no position is open, open a long position with user-provided SL/TP.
SELL:
  - Close any open long position.

Optional param `allow_short` (default False) to open short on SELL.
"""

from __future__ import annotations

from typing import Optional

from backtesting import Strategy

from signals_storage import generate_signal_series


class SignalStrategy(Strategy):
    # Strategy params set via Backtest.run(...)
    stop_loss: float = 0.05
    take_profit: float = 0.10
    allow_short: bool = False
    signals_df = None  # pandas DataFrame injected at run time

    def init(self):
        # Prepare an indicator that yields the signal vector aligned to price data
        def _indicator():
            # self.data.index is a pandas DatetimeIndex in recent versions
            index = self.data.index  # type: ignore[attr-defined]
            return generate_signal_series(index=index, signals_df=self.signals_df).values

        self.signals = self.I(_indicator)

    def next(self):
        last_sig = int(self.signals[-1])

        if last_sig == 1:  # BUY
            # Open long only if not already in position
            if not self.position:
                price = float(self.data.Close[-1])
                sl_price = price * (1 - float(self.stop_loss))
                tp_price = price * (1 + float(self.take_profit))
                self.buy(sl=sl_price, tp=tp_price)

        elif last_sig == -1:  # SELL
            if self.position:
                # Close any open long
                self.position.close()
            elif self.allow_short:
                # Optional: open short if enabled
                price = float(self.data.Close[-1])
                sl_price = price * (1 + float(self.stop_loss))
                tp_price = price * (1 - float(self.take_profit))
                self.sell(sl=sl_price, tp=tp_price)

