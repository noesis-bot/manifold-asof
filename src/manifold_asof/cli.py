"""Command line: `manifold-asof audit ...` and `manifold-asof asof ...`."""
from __future__ import annotations

import argparse
import json
import sys

from . import client
from .core import asof, audit_markets, to_ms


def _load(args) -> list[dict]:
    markets = []
    if args.file:
        with open(args.file) as fh:
            data = json.load(fh)
        markets += data if isinstance(data, list) else data.get("markets", [])
    for mid in args.ids:
        markets.append(client.market(mid))
    return markets


def _snapshots(path):
    """JSON list of {id, closeTime} (ms or ISO), or a ForecastBench question set."""
    if not path:
        return {}
    with open(path) as fh:
        data = json.load(fh)
    rows = data.get("questions", data) if isinstance(data, dict) else data
    out = {}
    for q in rows:
        if not isinstance(q.get("id"), str) or q.get("source", "manifold") != "manifold":
            continue
        val = q.get("closeTime", q.get("market_info_close_datetime"))
        try:
            ms = to_ms(val)
        except ValueError:  # e.g. "N/A" in ForecastBench sets
            ms = None
        if ms is not None:
            out[q["id"]] = ms
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="manifold-asof", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="flag outcome-dependent fields in markets")
    a.add_argument("ids", nargs="*", help="market ids to fetch")
    a.add_argument("--file", help="JSON list of market dicts (a dump) instead of / in addition to ids")
    a.add_argument("--cutoff", help="backtest cutoff (ISO date or ms)")
    a.add_argument("--snapshot", help="older frozen copy with closeTime per id (e.g. a ForecastBench question set)")
    a.add_argument("--summary", action="store_true", help="omit per-market flags")
    s = sub.add_parser("asof", help="rebuild one binary market as of a time")
    s.add_argument("id")
    s.add_argument("--at", required=True, help="ISO date/time or ms")
    args = ap.parse_args(argv)

    if args.cmd == "audit":
        markets = _load(args)
        if not markets:
            ap.error("give market ids or --file")
        rep = audit_markets(markets, args.cutoff, _snapshots(args.snapshot))
        if args.summary:
            rep.pop("per_market")
        json.dump(rep, sys.stdout, indent=1, ensure_ascii=False)
        print()
        return 0
    t = to_ms(args.at)
    m = client.market(args.id)
    bets = client.bets_before(args.id, t) if m.get("outcomeType") == "BINARY" else None
    json.dump(asof(m, t, bets), sys.stdout, indent=1, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
