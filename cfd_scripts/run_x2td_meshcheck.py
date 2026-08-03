"""
run_x2td_meshcheck.py — mesh-sensitivity check for the X2TD literature-match
validation case (run_x2td_validation.py), same pattern as this project's own
co_rot_meshcheck / co_rot_vr12_meshcheck diagnostics.

WHY: run_x2td_validation.py's spacing (0.10m) was chosen specifically because
it matches co_rot_meshcheck's already-tested point -- but that prior check
was run on the project's DEFAULT geometry (NACA4412, tapered 0.08->0.025m
chord). This case uses a different blade (NACA2412, constant 0.08m chord),
so co_rot_meshcheck's finding (fom_total moves 20-99% under refinement at
spacing=0.10m) doesn't automatically transfer -- different thickness/camber
distribution could in principle resolve differently. This script re-runs
the SAME x2td case geometry at a refined mesh (TEMPLATE_DUAL_MESHCHECK,
the existing refined snappyHexMeshDict co_rot_meshcheck itself uses) so
fom_total can be compared directly against the baseline run_x2td_validation.py
results at the same collective angles.

SCOPE: only 2 collective angles by default (8, 12 deg) -- the "healthy"
region of the validation sweep, past the low-collective interference dip
(0-4 deg) that was judged not representative of production (production runs
a fixed, calculated collective for a tapered/twisted blade, not a swept flat
collective through the near-zero-thrust region). This is a single mesh-level
comparison (coarse vs. one refined level), the same scope as co_rot_meshcheck
itself -- NOT a 3-level Celik et al. GCI study (see analyze_gci_study.py for
that pattern if a rigorous convergence order is needed later).

Separate sweep_dir/CSV from run_x2td_validation.py's, same reasoning as
co_rot_meshcheck's own separation from co_rot: so a mesh-check run can never
collide with or silently resume against the baseline validation results.

Usage:
  python3 cfd_scripts/run_x2td_meshcheck.py --dry_run
  python3 cfd_scripts/run_x2td_meshcheck.py --parallel 2
  python3 cfd_scripts/run_x2td_meshcheck.py --collectives 8 12 --parallel 2
"""

import argparse
import csv
import os
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_sweep as rs

# ── Same case parameters as run_x2td_validation.py -- ONLY the mesh template differs ─
DIAMETER      = rs.DIAMETER
NACA          = "2412"
SPACING_M     = 0.10
AZIMUTH_DEG   = 0.0
RPM           = 900.0
CHORD_M       = 0.08
ROOT_FRACTION = 0.30
MRF_RADIUS    = 0.6
UPPER_Z       = rs.UPPER_Z
END_TIME      = 1500.0

DEFAULT_COLLECTIVES = [8.0, 12.0]   # the two "healthy" (post-interference-dip) points
                                     # from the baseline run, both CONVERGED_TIGHT there:
                                     # 8 deg -> fom_total=0.4033, 12 deg -> fom_total=0.4820

SWEEP_DIR    = Path(rs.BASE_DIR) / "9_x2td_meshcheck_sweep"
TEMPLATE_DIR = rs.TEMPLATE_DUAL_MESHCHECK   # the SAME refined mesh co_rot_meshcheck uses --
                                             # built for D=1.0m/spacing=0.10m already
RESULTS_CSV  = SWEEP_DIR / "x2td_meshcheck_results.csv"

# Baseline (coarse-mesh) fom_total values from run_x2td_validation.py, for the
# printed % comparison at the end -- update these if the baseline is ever re-run.
BASELINE_FOM = {8.0: 0.4033, 12.0: 0.4820}

CSV_HEADER = [
    "case_id", "collective_deg",
    "spacing_m", "azimuth_deg", "rpm_upper", "rpm_lower",
    "diameter_m", "chord_m", "naca",
    "thrust_upper_N", "thrust_lower_N", "thrust_total_N",
    "torque_upper_Nm", "torque_lower_Nm", "torque_net_Nm",
    "power_upper_W", "power_lower_W", "power_total_W",
    "fom_upper", "fom_lower", "fom_total",
    "iterations", "converged", "convergence_ratio", "data_quality",
]


def run_one_case(args_tuple):
    i, total, collective_deg = args_tuple
    case_id = f"x2tdmesh_c{collective_deg:04.1f}"
    case_dir = SWEEP_DIR / case_id

    print(f"[{i}/{total}] START {case_id}", flush=True)
    t0 = time.time()

    if case_dir.exists():
        shutil.rmtree(case_dir)
    os.makedirs(case_dir, exist_ok=True)
    for sub in ["0", "system", "constant"]:
        shutil.copytree(os.path.join(TEMPLATE_DIR, sub), os.path.join(case_dir, sub))

    try:
        rs.write_case_configs_dual(
            str(case_dir),
            SPACING_M, AZIMUTH_DEG, RPM, rpm_upper=RPM,
            diameter=DIAMETER, chord=CHORD_M, naca=NACA,
            root_fraction=ROOT_FRACTION, collective=collective_deg,
            mrf_radius=MRF_RADIUS, upper_z=UPPER_Z,
            template_dir=TEMPLATE_DIR, end_time=END_TIME,
        )
    except Exception as e:
        print(f"[{i}/{total}] ERROR writing configs for {case_id}: {e}", flush=True)
        return None

    steps = [
        ("blockMesh",             "blockMesh > blockMesh.log 2>&1"),
        ("surfaceFeatureExtract", "surfaceFeatureExtract > surfaceFeatureExtract.log 2>&1"),
        ("snappyHexMesh",         "snappyHexMesh > snappyHexMesh.log 2>&1"),
        ("promoteMesh",
         'MESHDIR=$(for d in $(ls -d [0-9]* 2>/dev/null | sort -n); do '
         '[ -d "$d/polyMesh" ] && echo "$d"; done | tail -1) && '
         '[ -n "$MESHDIR" ] && cp -r "$MESHDIR/polyMesh" constant/ && rm -rf "$MESHDIR" || true'),
        ("topoSet",               "topoSet > topoSet.log 2>&1"),
        ("simpleFoam",            "simpleFoam > simpleFoam.log 2>&1"),
    ]
    for step_name, cmd in steps:
        rc, _ = rs.of_run(cmd, str(case_dir))
        if rc != 0 and step_name not in ("simpleFoam", "promoteMesh"):
            print(f"[{i}/{total}] FAIL {case_id} at {step_name}", flush=True)
            return None

    elapsed = time.time() - t0
    res = rs.extract_results_dual(str(case_dir))
    tu, tl, tt = (res.get(k) or 0.0 for k in ("thrust_upper_N", "thrust_lower_N", "thrust_total_N"))
    qu, ql = (res.get(k) or 0.0 for k in ("torque_upper_Nm", "torque_lower_Nm"))
    omega = rs.rpm_to_rads(RPM)
    pu, pl = abs(qu) * omega, abs(ql) * omega
    R = DIAMETER / 2.0

    row = {
        "case_id": case_id, "collective_deg": collective_deg,
        "spacing_m": SPACING_M, "azimuth_deg": AZIMUTH_DEG,
        "rpm_upper": RPM, "rpm_lower": RPM,
        "diameter_m": DIAMETER, "chord_m": CHORD_M, "naca": NACA,
        "thrust_upper_N": round(tu, 4), "thrust_lower_N": round(tl, 4), "thrust_total_N": round(tt, 4),
        "torque_upper_Nm": round(qu, 4), "torque_lower_Nm": round(ql, 4), "torque_net_Nm": round(qu + ql, 4),
        "power_upper_W": round(pu, 2), "power_lower_W": round(pl, 2), "power_total_W": round(pu + pl, 2),
        "fom_upper": rs.figure_of_merit(tu, pu, R=R),
        "fom_lower": rs.figure_of_merit(tl, pl, R=R),
        "fom_total": rs.figure_of_merit(tt, pu + pl, R=R),
        "iterations": res.get("iterations", 0),
        "converged": res.get("converged", False),
        "convergence_ratio": (round(res["convergence_ratio"], 5)
                               if res.get("convergence_ratio") is not None else None),
        "data_quality": res.get("data_quality"),
    }
    baseline = BASELINE_FOM.get(collective_deg)
    pct_str = ""
    if baseline and row["fom_total"] is not None:
        pct = (row["fom_total"] - baseline) / baseline * 100.0
        pct_str = f"  baseline_fom={baseline}  delta={pct:+.1f}%"
    print(f"[{i}/{total}] DONE  {case_id}  T={tt:.1f}N  P={pu+pl:.0f}W  "
          f"FM={row['fom_total']}  t={elapsed:.0f}s{pct_str}", flush=True)
    return row


def append_row(row, csv_path):
    with open(csv_path, "a", newline="") as f:
        rs._lock(f)
        csv.DictWriter(f, fieldnames=CSV_HEADER).writerow(row)
        f.flush()
        os.fsync(f.fileno())
        rs._unlock(f)


def main():
    ap = argparse.ArgumentParser(description="Mesh-sensitivity check for the X2TD validation case")
    ap.add_argument("--collectives", type=float, nargs="+", default=DEFAULT_COLLECTIVES,
                     help=f"Collective angles [deg] to re-mesh-check (default: {DEFAULT_COLLECTIVES})")
    ap.add_argument("--parallel", type=int, default=1)
    ap.add_argument("--dry_run", action="store_true")
    args = ap.parse_args()

    completed = set()
    if RESULTS_CSV.exists():
        with open(RESULTS_CSV) as f:
            for row in csv.DictReader(f):
                completed.add(row["case_id"])
        print(f"Skipping {len(completed)} already-completed cases")

    combos = [c for c in args.collectives if f"x2tdmesh_c{c:04.1f}" not in completed]
    total = len(combos)
    print(f"Refined-mesh check: NACA {NACA}  D={DIAMETER}m  spacing={SPACING_M}m  "
          f"RPM={RPM}  chord={CHORD_M}m  collectives={combos}  "
          f"template={TEMPLATE_DIR}")
    print(f"Cases to run: {total}")

    if args.dry_run:
        for c in combos:
            print(f"  x2tdmesh_c{c:04.1f}  (baseline fom_total={BASELINE_FOM.get(c, 'n/a')})")
        return

    os.makedirs(SWEEP_DIR, exist_ok=True)
    if not RESULTS_CSV.exists():
        with open(RESULTS_CSV, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADER).writeheader()

    queue = [(i, total, c) for i, c in enumerate(combos, 1)]
    if args.parallel <= 1:
        for item in queue:
            row = run_one_case(item)
            if row:
                append_row(row, RESULTS_CSV)
    else:
        with ProcessPoolExecutor(max_workers=args.parallel) as ex:
            futures = {ex.submit(run_one_case, item): item for item in queue}
            for fut in as_completed(futures):
                row = fut.result()
                if row:
                    append_row(row, RESULTS_CSV)

    print(f"\nResults written to {RESULTS_CSV}")
    print("Compare fom_total against BASELINE_FOM above -- a swing anywhere near "
          "co_rot_meshcheck's own 20-99% range means this geometry inherits the same "
          "under-resolution, not just the default NACA4412 blade.")


if __name__ == "__main__":
    main()
