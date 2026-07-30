"""
cfd_scripts/extract_time_averaged.py -- build time-averaged force/torque rows for the
PLATEAU/DIVERGING cases identified by check_convergence.py.

Rationale (2026-07-22, see chat): 213/294 non-converged cases don't respond to more
simpleFoam iterations -- their residuals plateau or oscillate rather than decay. This is
concentrated at spacing=0.35/0.6 (54.7%/25.8% of each spacing's 225 cases respectively)
with a milder azimuth gradient (2.4% at azimuth=45 up to 36% at azimuth=10). Blanket-
excluding these would badly skew the training set away from the two largest spacings.

Standard practice for a "steady" RANS run whose residual plateaus in a bounded
oscillation (rather than diverging without bound) is to treat the force/torque history as
sampling a quasi-periodic state and report the TIME-AVERAGE over a representative window,
rather than a single last-iteration snapshot (which may catch an arbitrary phase of the
oscillation). This reuses the forces function object's ALREADY-WRITTEN postProcessing
data (written every 10 iterations per controlDict) -- no rerun needed, just re-extraction.

This does NOT touch run_sweep.py's CSV_HEADER_DUAL/schema or co_rot_results.csv. Output
goes to a separate file with two extra columns (conv_class, avg_window_iters) so
provenance/confidence is visible downstream. Merge this with co_rot_results.csv (for the
already-CONVERGED rows) and the rebuilt SLOW-case results (from rerun_capped.py) to build
the final training set -- keep the conv_class column through that merge so training code
can filter/weight by it if desired.

Usage:
    python3 cfd_scripts/extract_time_averaged.py \
        --convergence_csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/convergence_check.csv \
        --orig_csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results.csv \
        --sweep_dir /home/david/OpenFOAM/ENGR412/2_co_rot_sweep \
        --out_csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results_timeaveraged.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_sweep import rpm_to_rads, figure_of_merit, last_iter, DIAMETER, PITCH_UPPER, CSV_HEADER_DUAL  # noqa: E402

FORCE_COL = 3   # same convention as run_sweep.py's read_last_force(..., 3) usage for fz/mz


def read_dat_series(dat_path: Path, col=FORCE_COL):
    """Returns list of (time, value) from an OpenFOAM forces/moment .dat file,
    skipping comment/blank lines -- same tokenization convention as run_sweep.py's
    read_last_force (line.split()), just kept for every row instead of only the last."""
    out = []
    if not dat_path.exists():
        return out
    with open(dat_path, errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#') or s.startswith('/'):
                continue
            parts = s.split()
            try:
                t = float(parts[0])
                v = float(parts[col])
            except (ValueError, IndexError):
                continue
            out.append((t, v))
    return out


def windowed_average(series, window_frac=0.15, min_window_iters=150):
    """Average of the value column over the last window (iteration-based, matching
    check_convergence.py's window definition) of a (time, value) series."""
    if not series:
        return None, 0
    last_t = series[-1][0]
    half = max(min_window_iters, window_frac * last_t)
    start = last_t - half
    vals = [v for t, v in series if t >= start]
    if not vals:
        vals = [series[-1][1]]
    return sum(vals) / len(vals), len(vals)


def extract_case(case_dir: Path, window_frac, min_window_iters):
    pp = case_dir / "postProcessing"

    def avg_force(name):
        series = read_dat_series(pp / name / "0" / "force.dat")
        return windowed_average(series, window_frac, min_window_iters)

    def avg_moment(name):
        series = read_dat_series(pp / name / "0" / "moment.dat")
        return windowed_average(series, window_frac, min_window_iters)

    tu, n_tu = avg_force("forcesUpper")
    tl, n_tl = avg_force("forcesLower")
    tt, n_tt = avg_force("forcesTotal")
    qu, n_qu = avg_moment("forcesUpper")
    ql, n_ql = avg_moment("forcesLower")

    n_samples = min(x for x in (n_tu, n_tl, n_tt, n_qu, n_ql) if x) if any((n_tu, n_tl, n_tt, n_qu, n_ql)) else 0

    return {
        "thrust_upper_N": tu, "thrust_lower_N": tl, "thrust_total_N": tt,
        "torque_upper_Nm": qu, "torque_lower_Nm": ql,
        "n_samples_averaged": n_samples,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--convergence_csv", required=True, help="Output of check_convergence.py")
    ap.add_argument("--orig_csv", required=True, help="Original co_rot_results.csv (for spacing/azimuth/rpm params)")
    ap.add_argument("--sweep_dir", required=True)
    ap.add_argument("--out_csv", required=True)
    ap.add_argument("--classes", nargs="+", default=["PLATEAU", "DIVERGING"],
                     help="Which check_convergence.py classes to process (default: PLATEAU DIVERGING)")
    ap.add_argument("--window_frac", type=float, default=0.15,
                     help="Fraction of total iterations to average over at the end of the run (default 0.15)")
    ap.add_argument("--min_window_iters", type=int, default=150,
                     help="Minimum iteration window regardless of window_frac (default 150)")
    args = ap.parse_args()

    with open(args.convergence_csv, newline="") as f:
        conv = {r["case_id"]: r["class"] for r in csv.DictReader(f)}

    with open(args.orig_csv, newline="") as f:
        orig = {r["case_id"]: r for r in csv.DictReader(f)}

    targets = [cid for cid, cls in conv.items() if cls in args.classes]
    print(f"Processing {len(targets)} cases with class in {args.classes}")

    out_header = CSV_HEADER_DUAL + ["conv_class", "n_samples_averaged"]
    rows_written = 0
    skipped = []

    with open(args.out_csv, "w", newline="") as fout:
        w = csv.DictWriter(fout, fieldnames=out_header)
        w.writeheader()

        for cid in targets:
            if cid not in orig:
                skipped.append((cid, "not found in orig_csv"))
                continue
            src = orig[cid]
            case_dir = Path(args.sweep_dir) / cid
            res = extract_case(case_dir, args.window_frac, args.min_window_iters)

            tu = res["thrust_upper_N"] or 0.0
            tl = res["thrust_lower_N"] or 0.0
            tt = res["thrust_total_N"] or 0.0
            qu = res["torque_upper_Nm"] or 0.0
            ql = res["torque_lower_Nm"] or 0.0

            rpm_upper = float(src["rpm_upper"])
            rpm_lower = float(src["rpm_lower"])
            omega_u = rpm_to_rads(rpm_upper)
            omega_l = rpm_to_rads(rpm_lower)
            pu = abs(qu) * omega_u
            pl = abs(ql) * omega_l

            row = {
                "case_id": cid,
                "spacing_m": src["spacing_m"], "azimuth_deg": src["azimuth_deg"],
                "rpm_upper": rpm_upper, "rpm_lower": rpm_lower,
                "pitch": src.get("pitch", PITCH_UPPER),
                "thrust_upper_N": round(tu, 4),
                "thrust_lower_N": round(tl, 4),
                "thrust_total_N": round(tt, 4),
                "torque_upper_Nm": round(qu, 4),
                "torque_lower_Nm": round(ql, 4),
                "torque_net_Nm": round(qu + ql, 4),
                "power_upper_W": round(pu, 2),
                "power_lower_W": round(pl, 2),
                "power_total_W": round(pu + pl, 2),
                "fom_upper": figure_of_merit(tu, pu, R=DIAMETER / 2.0),
                "fom_lower": figure_of_merit(tl, pl, R=DIAMETER / 2.0),
                "fom_total": figure_of_merit(tt, pu + pl, R=DIAMETER / 2.0),
                "iterations": last_iter(case_dir),
                "converged": False,   # honest -- these did NOT meet residualControl tolerance
                "conv_class": conv[cid],
                "n_samples_averaged": res["n_samples_averaged"],
            }
            w.writerow(row)
            rows_written += 1

    print(f"Wrote {rows_written} time-averaged rows to {args.out_csv}")
    if skipped:
        print(f"Skipped {len(skipped)} cases: {skipped[:10]}{' ...' if len(skipped) > 10 else ''}")


if __name__ == "__main__":
    main()
