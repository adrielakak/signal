"""Main entry point for the Lazy Backtester project.

Provides an interactive CLI to configure backtests and optional flags to
run a webhook receiver for TradingView alerts.

Usage:
  - Interactive backtest:  python main.py  (and follow prompts)
  - Explicit:               python main.py --mode backtest
  - Webhook server:         python main.py --mode webhook

Requirements:
  pip install flask pandas ccxt backtesting matplotlib pyfiglet rich

Notes:
  - config.yaml is optional. If missing or PyYAML is not installed, sensible
    defaults are used.
  - Reports are saved into the ./reports folder.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from rich.table import Table

try:
    import pyfiglet  # type: ignore
    HAVE_FIGLET = True
except Exception:
    HAVE_FIGLET = False


# Local imports
from signals_storage import (
    DEFAULT_SIGNALS_CSV,
    ensure_signals_csv,
    load_signals,
    filter_signals_for_symbol,
)
from data_loader import load_ohlcv
from strategy import SignalStrategy


def load_config(config_path: Path) -> Dict[str, Any]:
    """Load configuration from YAML if possible; otherwise return defaults.

    The project remains runnable even without PyYAML installed.
    """
    defaults: Dict[str, Any] = {
        "webhook": {"host": "0.0.0.0", "port": 5000},
        "exchange": "binance",
        "defaults": {
            "symbol": "CHEEMSC/USDT",
            "timeframe": "1h",
            "capital": 1000.0,
            "stop_loss": 0.05,
            "take_profit": 0.10,
            "start_date": None,
            "end_date": None,
        },
        "signals_csv": str(DEFAULT_SIGNALS_CSV),
    }

    if not config_path.exists():
        return defaults

    try:
        import yaml  # type: ignore

        with config_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        # Merge shallowly over defaults
        for k, v in defaults.items():
            if isinstance(v, dict):
                cfg.setdefault(k, {})
                for sk, sv in v.items():
                    cfg[k].setdefault(sk, sv)
            else:
                cfg.setdefault(k, v)
        return cfg
    except Exception:
        # If YAML not installed or parse error -> fallback to defaults.
        return defaults


def banner(console: Console) -> None:
    title = "Lazy Backtester"
    if HAVE_FIGLET:
        ascii_art = pyfiglet.figlet_format(title, font="Slant")
        console.print(f"[bold cyan]{ascii_art}[/bold cyan]")
    else:
        console.rule(f"[bold cyan]{title}[/bold cyan]")


def prompt_interactive_defaults(console: Console, defaults: Dict[str, Any]) -> Dict[str, Any]:
    console.print(Panel.fit("Configure your backtest parameters", title="Setup"))

    symbol = Prompt.ask("1) Enter pair", default=str(defaults.get("symbol", "CHEEMSC/USDT")))
    timeframe = Prompt.ask("2) Timeframe (1d, 4h, 1h, 15m, 5m, 1m)", default=str(defaults.get("timeframe", "1h")))

    def _float_prompt(prompt: str, default: float) -> float:
        raw = Prompt.ask(prompt, default=str(default))
        try:
            return float(raw)
        except Exception:
            return float(default)

    capital = _float_prompt("3) Initial capital (base currency units)", float(defaults.get("capital", 1000.0)))
    sl_pct = _float_prompt("4) Stop loss (%)", float(defaults.get("stop_loss", 0.05)) * 100.0) / 100.0
    tp_pct = _float_prompt("5) Take profit (%)", float(defaults.get("take_profit", 0.10)) * 100.0) / 100.0

    start_date = Prompt.ask("6) Start date (YYYY-MM-DD, blank = auto)", default=str(defaults.get("start_date") or ""))
    end_date = Prompt.ask("7) End date (YYYY-MM-DD, blank = now)", default=str(defaults.get("end_date") or ""))

    start_date = start_date.strip() or None
    end_date = end_date.strip() or None

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "capital": capital,
        "stop_loss": sl_pct,
        "take_profit": tp_pct,
        "start_date": start_date,
        "end_date": end_date,
    }


def summarize_config(console: Console, cfg: Dict[str, Any]) -> None:
    table = Table(title="Backtest Configuration", show_header=True, header_style="bold magenta")
    table.add_column("Key")
    table.add_column("Value")
    for k in ["symbol", "timeframe", "capital", "stop_loss", "take_profit", "start_date", "end_date"]:
        table.add_row(k, str(cfg.get(k)))
    console.print(table)


def run_backtest(console: Console, params: Dict[str, Any], signals_csv: Path) -> None:
    # Load market data
    df = load_ohlcv(
        symbol=params["symbol"],
        timeframe=params["timeframe"],
        start_date=params.get("start_date"),
        end_date=params.get("end_date"),
    )

    if df is None or df.empty:
        console.print("[red]No OHLCV data loaded. Check symbol/timeframe/date range.[/red]")
        return

    # Load signals
    ensure_signals_csv(signals_csv)
    sig_df = load_signals(signals_csv)
    sig_df = filter_signals_for_symbol(sig_df, params["symbol"]) if not sig_df.empty else sig_df

    from backtesting import Backtest
    import pandas as pd

    # Create reports dir
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    bt = Backtest(
        df,
        SignalStrategy,
        cash=float(params["capital"]),
        commission=0.0004,  # example commission 0.04%
        exclusive_orders=True,
    )

    # Run with user params and signals_df
    stats = bt.run(
        stop_loss=float(params["stop_loss"]),
        take_profit=float(params["take_profit"]),
        signals_df=sig_df,
        allow_short=False,
    )

    # Print selected metrics robustly
    def _get_stat(keys):
        for k in keys:
            try:
                if isinstance(stats, dict) and k in stats:
                    return stats[k]
                # Backtesting's Stats behaves like a Mapping/Series too
                return stats.get(k)  # type: ignore[attr-defined]
            except Exception:
                continue
        return None

    pnl = _get_stat(["Equity Final [$]", "Return [%]", "Return [%]"])
    win_rate = _get_stat(["Win Rate [%]", "Win rate [%]"])
    sharpe = _get_stat(["Sharpe Ratio", "Sharpe ratio"])
    mdd = _get_stat(["Max. Drawdown [%]", "Max Drawdown [%]"])

    console.print(Panel.fit("Backtest complete", title="Done", border_style="green"))
    metrics = Table(show_header=True, header_style="bold cyan")
    metrics.add_column("Metric")
    metrics.add_column("Value")
    metrics.add_row("PnL / Return", str(pnl))
    metrics.add_row("Win Rate [%]", str(win_rate))
    metrics.add_row("Sharpe Ratio", str(sharpe))
    metrics.add_row("Max Drawdown [%]", str(mdd))
    console.print(metrics)

    # Save results CSV
    import pandas as pd
    res_csv = reports_dir / "backtest_results.csv"
    try:
        pd.Series(stats).to_csv(res_csv)
    except Exception:
        try:
            pd.DataFrame(stats).to_csv(res_csv)
        except Exception:
            with res_csv.open("w", encoding="utf-8") as f:
                f.write(str(stats))

    # Save plot HTML
    plot_html = reports_dir / "backtest_plot.html"
    try:
        bt.plot(filename=str(plot_html), open_browser=False)
    except TypeError:
        # Older versions may not accept filename kwarg
        html = bt.plot(open_browser=False)
        if isinstance(html, str):
            with plot_html.open("w", encoding="utf-8") as f:
                f.write(html)

    console.print(f"[green]Saved results:[/green] {res_csv}")
    console.print(f"[green]Saved plot:[/green]    {plot_html}")


def run_webhook_server(console: Console, cfg: Dict[str, Any], signals_csv: Path) -> None:
    from webhook_server import run_server

    host = cfg.get("webhook", {}).get("host", "0.0.0.0")
    port = int(cfg.get("webhook", {}).get("port", 5000))
    console.print(Panel.fit(f"Starting webhook server at http://{host}:{port}/webhook", title="Webhook"))
    ensure_signals_csv(signals_csv)
    run_server(host=host, port=port, csv_path=signals_csv)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TradingView Webhook Receiver + Configurable Backtester")
    parser.add_argument("--mode", choices=["webhook", "backtest"], default="backtest", help="Run mode")
    parser.add_argument("--config", default="config.yaml", help="Path to YAML config file")
    parser.add_argument("--signals", default=str(DEFAULT_SIGNALS_CSV), help="Path to signals CSV file")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    console = Console()
    banner(console)

    cfg = load_config(Path(args.config))
    signals_csv = Path(args.signals)

    if args.mode == "webhook":
        run_webhook_server(console, cfg, signals_csv)
        return

    # Interactive backtest mode
    defaults = cfg.get("defaults", {})
    params = prompt_interactive_defaults(console, defaults)
    summarize_config(console, params)
    run_backtest(console, params, signals_csv=signals_csv)


if __name__ == "__main__":
    main()

