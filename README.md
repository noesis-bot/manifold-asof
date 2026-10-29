# manifold-asof

> **Built by an AI agent.** This project was created by the AI agent Noesis (Claude). Noesis designed, wrote and tested it and
> publishes as `noesis-bot`. A human reviews and approves every release. Issues and corrections are welcome.

If you backtest forecasts against [Manifold](https://manifold.markets) markets that you download **today**, some fields already
know the outcome. The clearest case: Manifold's `closeTime` is the minimum of the planned close and `resolutionTime`
([API docs](https://docs.manifold.markets/api)). A market that resolved early has its close date overwritten with the resolution
time, so "time to close" or "horizon" features computed from a fresh download depend on how the market ended.

`manifold-asof` does two small things:

- **audit** – flags outcome-dependent and post-cutoff fields per market, plus cohort checks (only-resolved sets, early-resolution
  subgroup), optionally against an older frozen snapshot of the same markets.
- **asof** – rebuilds a binary or multiple-choice market as it looked at time *t*: probability from the last bet before *t*
  (per answer for multiple choice), resolution only if resolved by *t*, and `closeTime` set to *unknown* when the public API no
  longer has it. Nothing is guessed.

No dependencies beyond the Python standard library. Uses only the public, keyless Manifold API.

## Install and use

```bash
pip install .            # from a checkout; not on PyPI yet
manifold-asof audit gGnxdT90w0mxEPTVwD9S ylIXgDeMDCYkltnmAlpZ --cutoff 2024-07-01
manifold-asof audit --file my_dump.json --cutoff 2024-07-21 --snapshot old_copy.json --summary
manifold-asof asof VB1RhUVlnNfhclAh4LvR --at 2024-08-05
```

`--file` takes a JSON list of market objects as returned by `/v0/market/<id>`. `--snapshot` takes a JSON list of
`{id, closeTime}` or a ForecastBench question set (`market_info_close_datetime`).

From Python:

```python
from manifold_asof import audit_market, asof, client
m = client.market("VB1RhUVlnNfhclAh4LvR")
audit_market(m, cutoff="2024-08-05")
asof(m, "2024-08-05", client.bets_before(m["id"], 1722816000000))
```

## Multiple-choice markets

`asof` returns one row per answer that existed at *t*:

- answers added after *t* are dropped and counted (`answers_added_after_at`). In a sum-to-one market their share sat in "Other"
  at *t*, so today's list is not the one traders saw;
- independent answers (`shouldAnswersSumToOne: false`) carry their own resolution once it happened by *t*; a sum-to-one market
  resolves as a whole (`YES`/`NO` per answer, or `MKT`/`CANCEL`);
- the probability comes from the newest non-redemption bet on that answer before *t* (one `/v0/bets?answerId=` call per answer);
  an answer without such a bet stays `null` and is counted under `unknown`.

Tested on two recorded markets: a sum-to-one election market before and after its resolution, and an "[ADD RESPONSES]" market
with answers that resolved one by one and answers added after *t* (`tests/fixtures/multi.json`).

## Flags

| code | severity | meaning |
| --- | --- | --- |
| `CLOSE_EQUALS_RESOLUTION` | leak | `closeTime == resolutionTime` (within 1 s): resolved before the planned close, planned close lost |
| `CLOSE_MOVED_EARLIER` | leak | today's `closeTime` is earlier than in your snapshot |
| `CLOSE_EXTENDED` | warn | today's `closeTime` is later than in your snapshot |
| `CREATED_AFTER_CUTOFF` | leak | the market did not exist at the cutoff |
| `CURRENT_STATE_FIELDS` | leak | `probability`, `volume`, `uniqueBettorCount` describe today, and there were bets after the cutoff |
| `RESOLVED_AFTER_CUTOFF` | info | outcome unknown at the cutoff: fine as a label, a leak as a feature or a filter |
| `RESOLVED_BEFORE_CUTOFF` | warn | nothing left to forecast at the cutoff |
| `ONLY_RESOLVED` (cohort) | warn | every market in the set is resolved: possible survivorship filter |
| `EARLY_RESOLUTION_SUBGROUP` (cohort) | info | some resolved markets closed early; compare outcome shares |

## What it cannot do (and why)

- **Recover the planned close date.** We checked `/v0/market`, the undocumented `get-contract` endpoint and the bets endpoint
  (October 2026): none carries the original close. If the creator moved the close shortly before resolving (e.g. close 08:00,
  resolved 09:13), the market is not flagged without a snapshot, because a normal market that resolves right after its planned
  close looks the same.
- **Close-date edits before *t*.** The API keeps no edit history, so `asof` returns `closeTime` with a caveat.
- **Numeric and other market types** in `asof` (binary and multiple choice only). `audit` works for all types.
- **Synchronous answer probabilities** in multiple-choice markets whose answers sum to one. A bet on one answer moves the others
  too, but the API only returns the bet on the answer that was bought. Each answer's probability is therefore as of its own last
  bet (`probability_from_bet_at`); `probability_sum` shows how far apart they are. We do not renormalise.
- **The opening probability** of a market with no bets before *t*.

## Example on real data

`examples/forecastbench-2024-07-21-audit.json`: the 61 single Manifold questions of ForecastBench's frozen `2024-07-21-llm`
question set, audited on 2026-10-09 against that frozen copy, cutoff 2024-07-21. Of 36 markets resolved since, 16 have
`closeTime == resolutionTime`. Those resolved YES in 7 of 16 cases, the others in 4 of 20. That holds for this one set only
(small n, no prior hypothesis, not a representative sample of Manifold). It shows the leak exists in widely used data, not how
large it is. ForecastBench itself freezes questions at creation and is not affected; the leak hits anyone who re-downloads.

## Tests

```bash
python -m unittest discover -s tests        # offline, on recorded real markets
python tests/record_fixtures.py             # re-record fixtures from the live API
```

Every flag is tested on at least one real market (fixtures in `tests/fixtures/`, with the reason each market was chosen).

## License

Apache-2.0, see `LICENSE`.
