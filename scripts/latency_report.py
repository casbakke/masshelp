"""Print p50/p95 time to first token per channel from Event logs (R2).
    uv run scripts/latency_report.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import select  # noqa: E402

from masshelp.services import build_services  # noqa: E402
from masshelp.store.models import Event  # noqa: E402


def pct(values: list[float], p: float) -> float:
    values = sorted(values)
    return values[min(int(round(p * (len(values) - 1))), len(values) - 1)]


def main() -> None:
    services = build_services(seed=False)
    by_channel: dict[str, dict[str, list[float]]] = {}
    with services.db.session() as s:
        for e in s.exec(select(Event).where(Event.type == "turn_latency")):
            p = json.loads(e.payload_json)
            bucket = by_channel.setdefault(p.get("channel", "?"), {"ttft": [], "total": []})
            if p.get("ttft_ms") is not None:
                bucket["ttft"].append(p["ttft_ms"])
            bucket["total"].append(p["total_ms"])
    if not by_channel:
        print("no turns logged yet")
    for channel, b in by_channel.items():
        for name, vals in b.items():
            if vals:
                print(f"{channel:5} {name:5} n={len(vals):3}  p50={pct(vals, .5):6.0f} ms  p95={pct(vals, .95):6.0f} ms"
                      f"  mean={statistics.mean(vals):6.0f} ms")


if __name__ == "__main__":
    main()
