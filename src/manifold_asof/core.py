"""Pure functions: no network. A market is the JSON dict from Manifold's `/v0/market/<id>`.

Times are milliseconds since the epoch (UTC), as in the Manifold API.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter

DAY_MS = 86_400_000

# Fields whose current value describes the market *today*, not at an earlier cutoff.
CURRENT_STATE_FIELDS = (
    "probability", "p", "pool", "volume", "volume24Hours", "totalLiquidity", "uniqueBettorCount",
    "lastUpdatedTime", "lastBetTime", "lastCommentTime", "isResolved", "resolution", "resolutionTime",
    "resolutionProbability", "resolverId",
)


def to_ms(value) -> int | None:
    """Accept ms ints, ISO strings ('2024-08-01', '2024-08-01T12:00:00Z') or datetimes."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dt.datetime):
        d = value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
        return int(d.timestamp() * 1000)
    s = str(value).strip().replace("Z", "+00:00")
    if s.isdigit():
        return int(s)
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp() * 1000)


def iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def close_is_outcome_dependent(m: dict) -> bool:
    """True when Manifold overwrote closeTime with the resolution time.

    Manifold documents closeTime as the minimum of the planned close and resolutionTime. When a market is resolved
    before its planned close, both fields become identical (to the millisecond in the data we checked). The planned
    close is then lost from the public API; we only know it was >= closeTime.
    """
    c, r = m.get("closeTime"), m.get("resolutionTime")
    return c is not None and r is not None and abs(c - r) < 1000


def audit_market(m: dict, cutoff=None, snapshot_close=None) -> list[dict]:
    """Return flags for one market. Each flag: {code, severity, detail}.

    cutoff: the point in time your backtest pretends to stand at (optional).
    snapshot_close: closeTime from an older, frozen copy of the market (optional), e.g. a ForecastBench question set.
    """
    flags = []
    t = to_ms(cutoff)
    snap = to_ms(snapshot_close)
    c, r = m.get("closeTime"), m.get("resolutionTime")

    def add(code, severity, detail):
        flags.append({"code": code, "severity": severity, "detail": detail})

    if close_is_outcome_dependent(m):
        add("CLOSE_EQUALS_RESOLUTION", "leak",
            f"closeTime was overwritten with resolutionTime ({iso(r)}); the planned close is unknown (>= this). "
            "Using closeTime or horizon (close - created) as a feature leaks that the market resolved early.")
    if snap is not None and c is not None and abs(snap - c) >= 1000:
        if c < snap:
            add("CLOSE_MOVED_EARLIER", "leak", f"closeTime moved from {iso(snap)} (snapshot) to {iso(c)} (today).")
        else:
            add("CLOSE_EXTENDED", "warn", f"closeTime extended from {iso(snap)} (snapshot) to {iso(c)} (today).")
    if t is not None:
        created = m.get("createdTime")
        if created is not None and created > t:
            add("CREATED_AFTER_CUTOFF", "leak", f"market was created {iso(created)}, after the cutoff {iso(t)}.")
        if m.get("isResolved") and r is not None and r > t:
            add("RESOLVED_AFTER_CUTOFF", "info",
                f"resolved {iso(r)}; at the cutoff the outcome was unknown. Fine as a label, a leak as a feature or filter.")
        if m.get("isResolved") and r is not None and r <= t:
            add("RESOLVED_BEFORE_CUTOFF", "warn", f"already resolved at the cutoff ({iso(r)}); nothing left to forecast.")
        stale = [f for f in ("probability", "volume", "uniqueBettorCount") if f in m]
        if stale and (m.get("lastBetTime") or 0) > t:
            add("CURRENT_STATE_FIELDS", "leak",
                f"{', '.join(stale)} describe the market today (last bet {iso(m.get('lastBetTime'))}), not at the cutoff. "
                "Use asof() for the probability at the cutoff.")
    return flags


def audit_markets(markets: list[dict], cutoff=None, snapshots: dict | None = None) -> dict:
    """Audit a collection and add cohort-level checks (selection on resolution)."""
    snapshots = snapshots or {}
    per = {m["id"]: audit_market(m, cutoff, snapshots.get(m["id"])) for m in markets}
    resolved = [m for m in markets if m.get("isResolved")]
    dep = [m for m in resolved if close_is_outcome_dependent(m)]
    rest = [m for m in resolved if not close_is_outcome_dependent(m)]
    report = {
        "markets": len(markets),
        "resolved": len(resolved),
        "close_equals_resolution": len(dep),
        "outcomes_close_equals_resolution": dict(Counter(m.get("resolution") for m in dep)),
        "outcomes_rest": dict(Counter(m.get("resolution") for m in rest)),
        "flag_counts": dict(Counter(f["code"] for fl in per.values() for f in fl)),
        "cohort": [],
        "per_market": per,
    }
    if markets and len(resolved) == len(markets):
        report["cohort"].append({
            "code": "ONLY_RESOLVED", "severity": "warn",
            "detail": "every market in the set is resolved. If the set was filtered on isResolved, markets that "
                      "were open at the cutoff and are still open today are missing (survivorship).",
        })
    if len(dep) >= 1 and len(rest) >= 1:
        report["cohort"].append({
            "code": "EARLY_RESOLUTION_SUBGROUP", "severity": "info",
            "detail": f"{len(dep)} of {len(resolved)} resolved markets resolved before their planned close. "
                      "Compare outcome shares across the two groups before trusting horizon features.",
        })
    return report


def prob_from_bets(bets_desc: list[dict]) -> tuple[float | None, int | None]:
    """Probability after the most recent effective bet. `bets_desc` is newest first, all before the cutoff."""
    for b in bets_desc:
        # Redemptions are bookkeeping and never move the price. isCancelled is NOT a reason to skip: on a limit
        # order it means the unfilled rest was cancelled, while the filled part did move the price (seen on
        # gGnxdT90w0mxEPTVwD9S, bet 585J6WEFBd8s: 0.381 -> 0.480 with isCancelled=True).
        if b.get("isRedemption"):
            continue
        if b.get("probAfter") is None:
            continue
        return float(b["probAfter"]), b.get("createdTime")
    return None, None


def asof(m: dict, at, bets_before: list[dict] | None = None) -> dict:
    """View of a binary market at time `at`, from today's market JSON plus the bets placed before `at`.

    What cannot be reconstructed is returned as None with a reason, never guessed.
    bets_before: bets with createdTime < at, newest first (as `/v0/bets?contractId=..&beforeTime=..` returns them).
    """
    t = to_ms(at)
    created, c, r = m.get("createdTime"), m.get("closeTime"), m.get("resolutionTime")
    view = {"id": m.get("id"), "question": m.get("question"), "at": iso(t), "unknown": {}}
    if created is not None and created > t:
        view["exists"] = False
        return view
    view["exists"] = True
    view["createdTime"] = iso(created)
    resolved_at_t = bool(m.get("isResolved")) and r is not None and r <= t
    view["isResolved"] = resolved_at_t
    view["resolution"] = m.get("resolution") if resolved_at_t else None
    if close_is_outcome_dependent(m) and not resolved_at_t:
        view["closeTime"] = None
        view["unknown"]["closeTime"] = (f"overwritten by the early resolution; the planned close was at least {iso(c)}. "
                                        "Recover it from an older snapshot if you have one.")
    else:
        view["closeTime"] = iso(c)
        view["unknown"]["closeTime_edits"] = "the creator may have edited closeTime after `at`; the API keeps no history."
    view["isClosed"] = resolved_at_t or (c is not None and c <= t and not close_is_outcome_dependent(m))
    if m.get("outcomeType") != "BINARY":
        view["probability"] = None
        view["unknown"]["probability"] = "only binary markets are supported for now."
    elif bets_before is None:
        view["probability"] = None
        view["unknown"]["probability"] = "no bets given; pass bets placed before `at`."
    else:
        p, when = prob_from_bets(bets_before)
        view["probability"] = p
        view["probability_from_bet_at"] = iso(when)
        if p is None:
            view["unknown"]["probability"] = "no effective bet before `at` (initial probability not in the public API)."
    return view
