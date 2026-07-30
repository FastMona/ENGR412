"""
cfd_scripts/check_convergence.py -- classify capped-out simpleFoam cases by residual trend,
automating the by-hand check done in chat on 9 sample cases from the 294-case
non-converged set.

Background (2026-07-22): rerunning capped cases at --new_endtime 1000 does NOT uniformly
fix them. Manual sampling found THREE distinct behaviors:
  - azimuth ~ +-90 deg: residual plateaus/oscillates flat, unmoved by 2x more iterations
    (e.g. Ux initial residual ~1.4-1.6e-3 essentially unchanged from t=200 to t=1000).
    Likely a genuine steady-RANS/frozen-rotor (MRF) limitation at max rotor phase offset,
    not an iteration-budget problem -- more endTime won't fix these.
  - azimuth ~ 10-20 deg: mixed. Some converge cleanly and quickly (one sample: 537
    iterations). Others are borderline -- still measurably decreasing at t=1000 (one
    sample dropped 300e-6 -> 256e-6 -> 220e-6 from t=500->800->1000, i.e. a real
    converger, just slow).
  - No case that hit "SIMPLE solution converged in N iterations" in the log needs any of
    this -- that message means simpleFoam's own residualControl already confirmed
    convergence; trust it.

This script reads each target case's simpleFoam.log directly (no CSV schema changes --
completely decoupled from run_sweep.py/rerun_capped.py's output files) and classifies:
  CONVERGED    - "SIMPLE solution converged" found in the log; trust simpleFoam's own check.
  CONVERGED_RESIDUAL - hit the iteration cap but final max residual is already < --tol
                 anyway (rare edge case, borderline against the tolerance).
  SLOW         - hit the cap, residual still meaningfully decreasing (>= --slow_drop_frac
                 relative drop between the two most recent sample points). Rerunning at a
                 higher --new_endtime is likely to actually help these.
  PLATEAU      - hit the cap, residual roughly flat (neither clearly decreasing nor
                 increasing). More iterations unlikely to help -- candidate for exclusion
                 from the training set, or a transient (pimpleFoam) rerun if it matters.
  DIVERGING    - hit the cap, residual measurably increasing. Same disposition as PLATEAU,
                 arguably worse -- do not just extend endTime on these.

Usage:
    python3 cfd_scripts/check_convergence.py \
        --csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results_rebuilt.csv \
        --sweep_dir /home/david/OpenFOAM/ENGR412/2_co_rot_sweep

    # or against the ORIGINAL (pre-rebuild) csv/dirs, before deciding what to rebuild:
    python3 cfd_scripts/check_convergence.py \
        --csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results.csv \
        --sweep_dir /home/david/OpenFOAM/ENGR412/2_co_rot_sweep --min_iterations 500

Output: prints a per-case classification table, then a summary count by class, then
(optionally, --out_csv) writes case_id,classification,residual_last,residual_prev for
downstream filtering (e.g. build the final training set by dropping PLATEAU/DIVERGING).
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

TIME_RE = re.compile(r"^Time = (\d+)\s*$")
RESID_RE = re.compile(r"Initial residual = ([0-9.eE+-]+)")


def parse_log(log_path: Path):
    """Returns (converged_flag, {time: max_initial_residual_across_fields})."""
    if not log_path.exists():
        return False, {}

    converged = False
    by_time = {}
    cur_time = None
    cur_max = None

    with open(log_path, errors="ignore") as f:
        for line in f:
            if "SIMPLE solution converged" in line:
                converged = True
                continue
            m = TIME_RE.match(line)
            if m:
                if cur_time is not None and cur_max is not None:
                    by_time[cur_time] = cur_max
                cur_time = int(m.group(1))
                cur_max = None
                continue
            m = RESID_RE.search(line)
            if m and cur_time is not None:
                try:
                    val = float(m.group(1))
                except ValueError:
                    continue
                cur_max = val if cur_max is None else max(cur_max, val)
        if cur_time is not None and cur_max is not None:
            by_time[cur_time] = cur_max

    return converged, by_time


def _windowed_mean(by_time, times, center, half_width):
    """Geometric mean of residuals for all logged iterations within
    [center - half_width, center + half_width]. Geometric (not arithmetic) mean
    because residuals are log-distributed -- an arithmetic mean would be dominated
    by rare upward spikes and reintroduce the same noise problem this is meant to fix."""
    vals = [by_time[t] for t in times if abs(t - center) <= half_width]
    if not vals:
        # widen search if the window landed in a gap (shouldn't normally happen
        # given simpleFoam logs every iteration, but be defensive)
        nearest = min(times, key=lambda t: abs(t - center))
        vals = [by_time[nearest]]
    log_mean = sum(__import__("math").log(v) for v in vals) / len(vals)
    return __import__("math").exp(log_mean), len(vals)


def classify(case_id, log_path, tol, slow_drop_frac, min_window=15, window_frac=0.10):
    converged, by_time = parse_log(log_path)
    if converged:
        return {"case_id": case_id, "class": "CONVERGED", "residual_last": None,
                "residual_prev": None, "note": "SIMPLE solution converged (trust it)"}

    if not by_time:
        return {"case_id": case_id, "class": "NO_LOG", "residual_last": None,
                "residual_prev": None, "note": f"no readable data in {log_path}"}

    times = sorted(by_time)
    last_t = times[-1]

    # Single-iteration residual values are noisy (simpleFoam residuals bounce
    # iteration-to-iteration even when the overall trend is flat or decreasing --
    # comparing two individual points produced spurious 300%+ "divergence" readings
    # on cases whose actual multi-hundred-iteration trend was flat). Compare
    # WINDOWED geometric means instead: one window centered at the end of the run,
    # one centered around ~60% of the way through, each spanning window_frac of
    # the total run (floor min_window iterations) -- this averages out iteration
    # noise while still being sensitive to a genuine multi-window trend.
    half_width = max(min_window, int(window_frac * last_t)) // 2
    last_center = last_t - half_width
    prev_center = max(times[0], 0.6 * last_t)

    last_r, last_n = _windowed_mean(by_time, times, last_center, half_width)
    prev_r, prev_n = _windowed_mean(by_time, times, prev_center, half_width)

    if last_r < tol:
        return {"case_id": case_id, "class": "CONVERGED_RESIDUAL", "residual_last": last_r,
                "residual_prev": None,
                "note": f"hit cap at t={last_t} but windowed residual {last_r:.2e} < tol {tol:.0e}"}

    if prev_r <= 0:
        rel_drop = 0.0
    else:
        rel_drop = (prev_r - last_r) / prev_r

    if rel_drop >= slow_drop_frac:
        cls = "SLOW"
        note = (f"windowed residual still dropping: {prev_r:.2e}@~t{int(prev_center)}(n={prev_n}) "
                f"-> {last_r:.2e}@~t{int(last_center)}(n={last_n}) ({rel_drop:+.0%})")
    elif rel_drop < -slow_drop_frac:
        cls = "DIVERGING"
        note = (f"windowed residual increasing: {prev_r:.2e}@~t{int(prev_center)}(n={prev_n}) "
                f"-> {last_r:.2e}@~t{int(last_center)}(n={last_n}) ({rel_drop:+.0%})")
    else:
        cls = "PLATEAU"
        note = (f"windowed residual flat: {prev_r:.2e}@~t{int(prev_center)}(n={prev_n}) "
                f"-> {last_r:.2e}@~t{int(last_center)}(n={last_n}) ({rel_drop:+.0%})")

    return {"case_id": case_id, "class": cls, "residual_last": last_r,
            "residual_prev": prev_r, "note": note}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True, help="Results csv to select target case_ids from")
    ap.add_argument("--sweep_dir", required=True, help="Directory containing per-case folders")
    ap.add_argument("--min_iterations", type=int, default=None,
                     help="Select rows with iterations >= this (default: not applied -- "
                          "checks EVERY row in --csv). Use e.g. 1000 to only re-check cases "
                          "that hit a 1000-cap rebuild.")
    ap.add_argument("--case_ids", nargs="+", default=None,
                     help="Explicit case_id list, overrides --csv row selection entirely")
    ap.add_argument("--tol", type=float, default=1e-4, help="Residual tolerance (default 1e-4, matches fvSolution)")
    ap.add_argument("--slow_drop_frac", type=float, default=0.10,
                     help="Relative residual drop (from ~60%% mark to final) to call SLOW instead of PLATEAU (default 0.10 = 10%%)")
    ap.add_argument("--out_csv", default=None, help="Optional: write classification results here")
    args = ap.parse_args()

    with open(args.csv, newline="") as f:
        rows = list(csv.DictReader(f))

    if args.case_ids:
        wanted = set(args.case_ids)
        targets = [r["case_id"] for r in rows if r["case_id"] in wanted]
    elif args.min_iterations is not None:
        targets = [r["case_id"] for r in rows if int(r["iterations"]) >= args.min_iterations]
    else:
        targets = [r["case_id"] for r in rows]

    print(f"Checking {len(targets)} cases from {args.csv}\n")

    results = []
    for cid in targets:
        log_path = Path(args.sweep_dir) / cid / "simpleFoam.log"
        r = classify(cid, log_path, args.tol, args.slow_drop_frac)
        results.append(r)
        print(f"  {r['class']:<20} {cid:<28} {r['note']}")

    from collections import Counter
    counts = Counter(r["class"] for r in results)
    print(f"\nSummary ({len(results)} total):")
    for cls, n in counts.most_common():
        print(f"  {cls:<20} {n}")

    if args.out_csv:
        with open(args.out_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["case_id", "class", "residual_last", "residual_prev", "note"])
            w.writeheader()
            w.writerows(results)
        print(f"\nWrote classification to {args.out_csv}")


if __name__ == "__main__":
    main()
