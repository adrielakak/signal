"""Flask webhook server to receive TradingView alerts and persist them to CSV.

Endpoint:
  POST /webhook  with JSON body:
    {
      "signal": "BUY" | "SELL",
      "price": 0.0000152,
      "ticker": "CHEEMSCUSD",
      "timestamp": "2025-10-27T14:50:00Z"
    }

Health check:
  GET /health -> {"status": "ok"}
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from flask import Flask, jsonify, request

from signals_storage import ensure_signals_csv, append_signal


def create_app(csv_path: Path) -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.post("/webhook")
    def webhook():
        try:
            payload: Dict[str, Any] = request.get_json(force=True, silent=False)  # type: ignore
        except Exception:
            return jsonify({"error": "Invalid JSON"}), 400

        required = ["signal", "price", "ticker", "timestamp"]
        missing = [k for k in required if k not in payload]
        if missing:
            return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

        signal = str(payload["signal"]).strip().upper()
        if signal not in {"BUY", "SELL"}:
            return jsonify({"error": "signal must be BUY or SELL"}), 400

        try:
            price = float(payload["price"])  # type: ignore[arg-type]
        except Exception:
            return jsonify({"error": "price must be a number"}), 400

        ticker = str(payload["ticker"]).strip()
        timestamp_raw = str(payload["timestamp"]).strip()

        try:
            # Accept both Z and offset formats
            ts = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
        except Exception:
            return jsonify({"error": "timestamp must be ISO8601"}), 400

        ensure_signals_csv(csv_path)
        append_signal(signal=signal, price=price, ticker=ticker, timestamp=ts, csv_path=csv_path)

        return jsonify({"status": "ok"})

    return app


def run_server(host: str = "0.0.0.0", port: int = 5000, csv_path: Path | str = "signals.csv") -> None:
    """Run the Flask development server for receiving webhooks."""
    path = Path(csv_path)
    ensure_signals_csv(path)
    app = create_app(path)
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    run_server()

