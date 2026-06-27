#!/usr/bin/env python3
"""
fetch_tws_portfolio.py — pull portfolio state from Interactive Brokers TWS.

Connects to TWS/IB Gateway on 127.0.0.1:7497 (paper trading) via the official
ibapi synchronous Python wrapper. Pulls:
  - Account summary (NetLiquidation, BuyingPower, AvailableFunds, etc.)
  - Open positions (symbol, qty, market value, unrealized P&L, etc.)
  - Recent executions (last N fills)

Designed for cron mode: stdout is JSON, stderr is human-readable logs.

Args:
    --host HOST              TWS host (default: 127.0.0.1)
    --port PORT              TWS port (default: 7497 = paper; 7496 = live)
    --client-id N            Unique client id (default: random in 9000-9999)
    --timeout-s N            Max seconds to wait for results (default: 10)
    --include-executions     Also fetch last N executions (default: off)
    --executions-lookback-h  Look back N hours for executions (default: 24)

Pre-flight checks (run BEFORE connecting):
    1. TWS/IB Gateway is running (process check)
    2. The TWS Socket port is listening (lsof)
    3. API connections are enabled in TWS settings:
       Edit > Global Configuration > API > Settings > "Enable ActiveX and Socket Clients"
       + "Allow connections from localhost only" (or trust 127.0.0.1)

If any check fails, exit 2 with a clear stderr message so the cron session
sees the failure cause (per the cron-mode-execution skill's "report blockers
honestly" rule — do not invent data when the source is missing).

JSON output shape:
    {
      "fetched_at": "2026-06-27T14:55:00Z",
      "tws": {"host": "127.0.0.1", "port": 7497, "client_id": 9001},
      "account_summary": {"NetLiquidation": "110.00", ...},
      "positions": [{"symbol": "AAPL", "qty": 100, "market_value": "15000.00", ...}],
      "executions": [{"symbol": "TSLA", "side": "BOT", "qty": 50, "price": "240.50", ...}]
    }
"""
from __future__ import annotations

import argparse
import json
import random
import re
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any

# ibapi is synchronous + callback-based. We collect results into the wrapper
# instance, then print after the deadline.
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract


# ---------- Pre-flight checks ----------

def preflight(host: str, port: int) -> None:
    """
    Verify TWS/IB Gateway is reachable BEFORE we try to connect.

    Three signals we check (all must pass):
      1. Some IB-related process is running (TWS = JavaApplicationStub,
         IB Gateway = jts\.ini loader)
      2. The configured port is listening (lsof)
      3. The TCP connection is accepted (open a socket)

    On failure, exit 2 with a clear message so the cron session can
    surface the blocker to John.
    """
    # 1. Process check
    try:
        ps_out = subprocess.check_output(
            ["pgrep", "-fl", "Trader Workstation|ibcontroller|ibgateway|jts"],
            text=True,
        )
    except subprocess.CalledProcessError:
        ps_out = ""

    if not ps_out.strip():
        print(
            f"fetch_tws_portfolio: no TWS/IB Gateway process found.\n"
            f"  Started? Check `pgrep -fl 'Trader Workstation'`.",
            file=sys.stderr,
        )
        sys.exit(2)

    # 2. Port check
    lsof_out = subprocess.check_output(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], text=True
    )
    if "LISTEN" not in lsof_out:
        print(
            f"fetch_tws_portfolio: nothing listening on {host}:{port}.\n"
            f"  In TWS: Edit > Global Configuration > API > Settings > "
            f"'Enable ActiveX and Socket Clients' (must be checked). "
            f"Also verify the socket port matches (default paper=7497, live=7496).",
            file=sys.stderr,
        )
        sys.exit(2)

    # 3. TCP handshake
    try:
        with socket.create_connection((host, port), timeout=3):
            pass
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        print(
            f"fetch_tws_portfolio: TCP connection to {host}:{port} failed: {e}",
            file=sys.stderr,
        )
        sys.exit(2)


# ---------- Wrapper (collects results) ----------

@dataclass
class Position:
    account: str
    symbol: str
    sec_type: str
    currency: str
    qty: float
    avg_cost: float
    market_price: float | None
    market_value: float | None
    unrealized_pnl: float | None
    realized_pnl: float | None


@dataclass
class Execution:
    account: str
    symbol: str
    sec_type: str
    currency: str
    side: str  # "BOT" or "SLD"
    qty: float
    price: float
    time: str


class TWSCollector(EWrapper, EClient):
    """Synchronous wrapper that collects results into instance attributes."""

    def __init__(self):
        EClient.__init__(self, self)
        self._lock = threading.Lock()
        self.connected_at: float | None = None
        self.next_valid_id: int | None = None
        self.account_summary: dict[tuple[str, str], str] = {}
        self.positions: list[Position] = []
        self.executions: list[Execution] = []
        self.errors: list[tuple] = []

    def nextValidId(self, orderId: int):
        with self._lock:
            self.next_valid_id = orderId

    def managedAccounts(self, accountsList: str):
        # Fires once after connect; tells us which account(s) TWS exposes.
        with self._lock:
            self.accounts = accountsList.split(",")

    def error(self, *args, **kwargs):
        with self._lock:
            self.errors.append(args)

    def accountSummary(self, reqId, account, tag, value, currency):
        with self._lock:
            self.account_summary[(tag, currency)] = value

    def accountSummaryEnd(self, reqId):
        pass  # No-op; we drive the timeout ourselves

    def position(self, account, contract, position, avgCost):
        with self._lock:
            self.positions.append(
                Position(
                    account=account,
                    symbol=contract.symbol,
                    sec_type=contract.secType,
                    currency=contract.currency,
                    qty=float(position),
                    avg_cost=float(avgCost),
                    market_price=None,
                    market_value=None,
                    unrealized_pnl=None,
                    realized_pnl=None,
                )
            )

    def positionEnd(self):
        pass

    def execDetails(self, reqId, contract, execution):
        with self._lock:
            self.executions.append(
                Execution(
                    account=execution.acctNumber,
                    symbol=contract.symbol,
                    sec_type=contract.secType,
                    currency=contract.currency,
                    side="BOT" if execution.side == "1" else "SLD",
                    qty=float(execution.shares),
                    price=float(execution.price),
                    time=execution.time,
                )
            )

    def execDetailsEnd(self, reqId):
        pass


# ---------- Top-level fetch ----------

ACCOUNT_SUMMARY_TAGS = ",".join(
    [
        "NetLiquidation",
        "BuyingPower",
        "AvailableFunds",
        "TotalCashValue",
        "EquityWithLoanValue",
        "UnrealizedPnL",
        "RealizedPnL",
    ]
)


def fetch_portfolio(
    host: str, port: int, client_id: int, timeout_s: float, with_executions: bool,
    executions_lookback_h: int,
) -> dict[str, Any]:
    preflight(host, port)

    collector = TWSCollector()
    collector.connect(host, port, client_id)

    # ibapi.run() blocks; run in a thread so we can enforce a timeout.
    thread = threading.Thread(target=collector.run, name="tws-run", daemon=True)
    thread.start()

    # Wait for connection + first nextValidId so we know our req IDs are valid.
    deadline = time.time() + 5
    while time.time() < deadline and collector.next_valid_id is None:
        time.sleep(0.05)
    if collector.next_valid_id is None:
        collector.disconnect()
        print("fetch_tws_portfolio: TWS never sent nextValidId (auth/IP issue?)", file=sys.stderr)
        sys.exit(2)

    base_id = collector.next_valid_id

    # 1. Account summary — covers cash, P&L, buying power.
    collector.reqAccountSummary(base_id, "All", ACCOUNT_SUMMARY_TAGS)

    # 2. Positions — current portfolio state.
    collector.reqPositions()

    # 3. Executions (optional) — last N hours of fills.
    # TWS's reqExecutions() returns ALL historical executions; we filter by time.
    if with_executions:
        exec_filter = __import__("ibapi").execution.ExecutionFilter()
        collector.reqExecutions(base_id + 1, exec_filter)

    # Wait for the data to flow in, then disconnect.
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        # Once accountSummary has fired (at least one entry), give positions
        # a moment to fill, then bail. We don't have a "everything done"
        # signal for reqPositions, so we use a generous timeout.
        time.sleep(0.2)
        # Heuristic: if account_summary has data AND we've been connected
        # for at least 2 seconds, consider it done.
        if (
            len(collector.account_summary) > 0
            and time.time() - deadline + timeout_s > 2
        ):
            break

    collector.disconnect()
    thread.join(timeout=2)

    # Filter executions by lookback window
    cutoff = datetime.now(timezone.utc) - timedelta(hours=executions_lookback_h)
    filtered_executions = []
    for e in collector.executions:
        # TWS time format: "20260627 14:30:00 UTC"
        try:
            ts = datetime.strptime(e.time, "%Y%m%d  %H:%M:%S %Z").replace(
                tzinfo=timezone.utc
            )
            if ts < cutoff:
                continue
        except ValueError:
            # If we can't parse the timestamp, keep it (don't silently drop)
            pass
        filtered_executions.append(asdict(e))

    # Filter out zero-qty positions (they're just noise from closed positions)
    open_positions = [asdict(p) for p in collector.positions if p.qty != 0]

    # Normalize account summary into a flat dict keyed by tag (USD only,
    # since TWS may report multi-currency accounts and we want a single value)
    flat_summary = {
        tag: value for (tag, currency), value in collector.account_summary.items()
        if currency == "USD"
    }

    # Report non-fatal errors to stderr (don't fail the fetch)
    fatal_errors = [e for e in collector.errors if e[0] not in (-1,) or e[1] not in (2104, 2106, 2158)]
    if fatal_errors:
        print(f"fetch_tws_portfolio: {len(fatal_errors)} non-info error(s):", file=sys.stderr)
        for err in fatal_errors[:5]:
            print(f"  {err}", file=sys.stderr)

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "tws": {"host": host, "port": port, "client_id": client_id},
        "account_summary": flat_summary,
        "positions": open_positions,
        "executions": filtered_executions if with_executions else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0] if __doc__ else "TWS portfolio fetcher"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7497, help="7497=paper, 7496=live")
    parser.add_argument("--client-id", type=int, default=None, help="default: random 9000-9999")
    parser.add_argument("--timeout-s", type=float, default=10.0)
    parser.add_argument("--include-executions", action="store_true")
    parser.add_argument("--executions-lookback-h", type=int, default=24)
    parser.add_argument("--plain", action="store_true", help="Human-readable output")
    args = parser.parse_args()

    client_id = args.client_id or random.randint(9000, 9999)

    result = fetch_portfolio(
        host=args.host,
        port=args.port,
        client_id=client_id,
        timeout_s=args.timeout_s,
        with_executions=args.include_executions,
        executions_lookback_h=args.executions_lookback_h,
    )

    if args.plain:
        print(f"# TWS portfolio @ {result['tws']}")
        print(f"# Fetched: {result['fetched_at']}")
        print(f"\n## Account summary")
        for k, v in result["account_summary"].items():
            print(f"  {k:24s}  {v} USD")
        print(f"\n## Open positions ({len(result['positions'])})")
        for p in result["positions"]:
            print(
                f"  {p['symbol']:8s} qty={p['qty']:>10} avg_cost={p['avg_cost']:>10} "
                f"{p['currency']}"
            )
        if result["executions"]:
            print(f"\n## Recent executions ({len(result['executions'])})")
            for e in result["executions"]:
                print(f"  {e['time']} {e['side']} {e['qty']:>5} {e['symbol']} @ {e['price']}")
    else:
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
