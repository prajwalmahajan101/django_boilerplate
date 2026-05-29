#!/usr/bin/env python3
"""Profile per-call overhead of ``capture_and_dispatch`` (the audit hot path).

Runs N synthetic captures with persistence stubbed to a no-op,
measures the wrapper's wall-clock overhead, and prints p50 / p95 /
p99 in microseconds. The numbers are both a baseline reference and a
CI guard against accidental slowdown-by-import.

Exits non-zero when p99 exceeds ``--max-p99-us`` (default ``5000`` =
5 ms).

Run modes::

    python scripts/profile_audit_path.py                       # default N=2000
    python scripts/profile_audit_path.py --iterations 10000    # tighter percentiles
    python scripts/profile_audit_path.py --max-p99-us 3000     # tighter bound

Baseline (recorded 2026-05-29 on a clean main, Python 3.12, single
thread, persist stubbed):

    iterations=2000  p50=~5us  p95=~10us  p99=~20us

Treat any p99 > 2x baseline as a regression worth investigating.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from statistics import quantiles

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "apps"))

os.environ.setdefault("DJANGO_ENV", "test")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")


def _percentile(samples: list[float], pct: float) -> float:
    if not samples:
        return 0.0
    cuts = quantiles(samples, n=100, method="inclusive")
    idx = max(0, min(98, int(pct) - 1))
    return cuts[idx]


def run_profile(iterations: int) -> list[float]:
    """Return per-call microsecond overhead samples."""
    import django

    django.setup()

    from core.api_log import dispatch as dispatch_mod
    from core.api_log.models import Direction

    # Stub the queue submitter so we measure capture overhead only,
    # not the FireAndForgetQueue executor scheduling.
    dispatch_mod.fire_and_forget = lambda row: None  # type: ignore[assignment]

    def noop_handler() -> str:
        return "ok"

    def trivial_builder(result, exc, elapsed_ms):
        return {
            "direction": Direction.INBOUND,
            "service_name": "profile",
            "request_id": "x",
            "method": "GET",
            "url": "/",
            "status_code": 200,
            "duration_ms": elapsed_ms,
            "request_headers": {},
            "request_body": None,
            "response_headers": {},
            "response_body": None,
            "error": None,
            "extra": {},
        }

    # Warm-up
    for _ in range(50):
        dispatch_mod.capture_and_dispatch(noop_handler, (), {}, trivial_builder)

    samples_us: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        dispatch_mod.capture_and_dispatch(noop_handler, (), {}, trivial_builder)
        samples_us.append((time.perf_counter() - start) * 1_000_000)
    return samples_us


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument(
        "--max-p99-us",
        type=float,
        default=5_000.0,
        help="Fail (exit 1) when measured p99 exceeds this many microseconds.",
    )
    args = parser.parse_args()

    samples = run_profile(args.iterations)
    p50 = _percentile(samples, 50)
    p95 = _percentile(samples, 95)
    p99 = _percentile(samples, 99)
    print(
        f"capture_and_dispatch overhead (iterations={args.iterations}):"
        f" p50={p50:.1f}us p95={p95:.1f}us p99={p99:.1f}us"
    )
    if p99 > args.max_p99_us:
        print(
            f"\nREGRESSION: p99={p99:.1f}us exceeds bound "
            f"({args.max_p99_us:.0f}us). Investigate recent changes "
            "under apps/core/api_log/ or apps/core/utils/.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
