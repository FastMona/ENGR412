"""
run_x2td_validation.py — ENGR412 literature-match validation vs. Qin & Yang (2025)

Runs the OpenFOAM MRF/simpleFoam coaxial pipeline at a handful of collective
angles, bracketing the target thrust coefficient reported for the Sikorsky
X2TD coaxial rotor's baseline (un-optimized) blade, so the resulting figure
of merit can be compared against a published number.

Reference:
  Qin, S.-H., & Yang, A.-M. (2025). Aerodynamic optimization of a coaxial
  rotor system using a deep learning-based multi-fidelity surrogate model.
  Engineering Applications of Computational Fluid Mechanics.
  Baseline-2 (real X2TD blade, pre-optimization): FM = 0.4102 at target
  thrust coefficient CT = 0.005, tip Mach = 0.563, rotor spacing H/D = 0.0568.

WHY NACA 2412, NOT AN EXACT X2TD REPLICA:
  The real X2TD blade is NOT a NACA section at all -- it blends three
  proprietary Sikorsky airfoils by radial station (DBLN-526 root / SC1012R8
  mid-span / SSCA09 tip; Passe et al., 2015). generate_propeller.py only
  supports NACA 4-digit parametric sections (see --naca in generate_propeller.py),
  so an exact reproduction isn't possible without a new arbitrary-coordinate
  loader. Of the three, only SC1012R8 (the mid-span, load-carrying "workhorse"
  section) is worth approximating:
    - DBLN-526 (root, t/c=26%, blunt/double-stepped) exists specifically to
      suppress reverse flow on the retreating blade in forward flight -- this
      project is hover-only / co-rotating-only, so that physics never engages.
    - SSCA09 (tip, t/c=9%) is a transonic section (tested to drag divergence
      up to M=1.07). This project's whole design space tops out at Mtip~0.18
      in production and ~0.44 in the C-T validation cases -- nowhere near
      transonic, so a transonic tip section buys nothing here.
    - SC1012R8 (mid-span) measured geometry (airfoiltools.com / UIUC coords):
      max thickness 12.0% at 27.8% chord, max camber 2.7% at 21.8% chord.
      NACA 2412 (2% camber at 20% chord, 12% thickness) is the closest
      achievable NACA 4-digit match -- notably NOT this project's other
      default, NACA 4412 (4% camber at 40% chord), which is a poorer match
      on both camber magnitude and position. Same reasoning already applied
      to VR12_NACA="2211" for the Jacobellis et al. VR-12 case below.

DEVIATIONS FROM QIN & YANG'S EXACT OPERATING POINT (read before trusting FM):
  1. Diameter: reused this project's own D=1.0 m (TEMPLATE_DUAL) rather than
     X2TD's real scale, which isn't given in absolute units in the paper
     (only non-dimensional ratios: solidity, H/D, tip Mach). This means the
     TEMPLATE_DUAL mesh can be reused as-is -- no new rescaled blockMeshDict/
     snappyHexMeshDict needed (unlike co_rot_vr12, which required one).
  2. Spacing: ABANDONED H/D=0.0568 (Qin & Yang's exact ratio) 2026-07-30 after
     empirical failure. At H/D=0.0568 (spacing=0.0568m), mrf_dz works out to
     only +/-0.0184m (from write_case_configs_dual's own formula) -- and with
     chord=0.08m (see deviation 4 below), the blade's own z-extent (thickness
     + collective-tilt projection of the chord line, ~2-3cm at high
     collective) is in the same ballpark as that zone half-height. Result:
     thrust_upper_N came back NEGATIVE in 5 of 7 collective cases while
     thrust_lower_N stayed a healthy +15N the whole sweep, FM was
     non-monotonic with collective, and the 0 deg case never converged
     (hit the 1500-iteration cap, BORDERLINE). Diagnosis: part of the blade
     was very likely sticking outside its own assigned MRF rotating zone at
     this tight a spacing/chord combination -- treated as stationary
     geometry inside a supposedly-rotating frame, producing nonsensical,
     angle-dependent forces rather than a real (if imperfect) hover result.
     REPLACED WITH: spacing = 0.10 m, matching this project's own
     `co_rot_meshcheck` case exactly (mrf_dz = +/-0.04m at this spacing --
     comfortably larger than the blade's z-extent). This gives up matching
     Qin & Yang's H/D=0.0568 in exchange for landing in a spacing this
     project has already run its own mesh-sensitivity diagnostic against
     (fom_total moves 20-99% under refinement at 0.10m -- a real, but
     CHARACTERIZED, caveat, unlike the previous unexplained failure mode).
     H/D at D=1.0m is now 0.10, not 0.0568 -- one more documented deviation
     from the literature operating point, on top of Mtip and airfoil.
  3. RPM / tip Mach: run at RPM_UPPER=RPM_LOWER=900 (this project's own
     default upper RPM), giving Mtip ~= 0.137 at D=1.0m -- NOT Qin & Yang's
     Mtip=0.563. Actually hitting Mtip=0.563 at D=1.0m needs ~3700 RPM, which
     is both far outside this project's validated RPM range and deep into a
     compressibility regime simpleFoam (incompressible) has never been
     checked against -- the existing C-T validation only characterizes
     ~3% CT bias at Mtip=0.228, and that bias is expected to grow sharply,
     not linearly, well before Mtip=0.563. Matching RPM instead of Mtip
     keeps this case inside the pipeline's already-characterized error
     regime, at the cost of not reproducing Qin & Yang's exact compressible
     operating point. This is a TREND/PLAUSIBILITY check on the airfoil
     approximation, not a wind-tunnel-style exact-condition replication --
     same category as the co_rot_vr12 case's spacing deviation below.
  4. Root cutout / chord: X2TD's absolute chord isn't given either -- only
     "aspect ratio 19.2" (originally interpreted as R/c_mean, giving c ~= 0.026 m
     at R=0.5m). EMPIRICALLY TESTED 2026-07-30 and REJECTED: at c=0.026m the
     blade is thin enough that TEMPLATE_DUAL's existing snappyHexMeshDict
     (tuned for this project's default ~0.08m root-chord blade) fails to
     capture the surface at all -- constant/polyMesh/boundary came back with
     only inlet/outlet/sides, no upperBlade/lowerBlade patches whatsoever, so
     every force was silently 0.0 across the whole collective bracket (and
     wrongly flagged CONVERGED_TIGHT -- see run_sweep.py's _tail_ratio(),
     which short-circuits an all-zero force history to ratio=0.0, a
     convergence-checker blind spot worth fixing separately). c=0.08m (this
     project's own known-meshable root-chord scale) is now the default below
     -- confirmed working: T=14.9N, FM=0.2718, CT~=0.00697 at collective=8 deg,
     same order of magnitude as the CT=0.005 target. This abandons the
     AR=19.2 derivation rather than chasing a refined mesh template for it --
     the interpretation of that ratio was uncertain to begin with (see
     module docstring in the original version), so there's no strong reason
     to prefer 0.026m over a value already known to mesh cleanly and land in
     the right CT range. OVERRIDE with --chord if you have a better source
     for X2TD's actual chord. Root cutout kept at this project's own default
     (0.30), since X2TD's isn't stated in the source paper at all.

Target to compare against (see X2TD_validation.py):
  CT = 0.005, FM = 0.4102 (Qin & Yang, 2025, Baseline-2)

Usage:
  python3 cfd_scripts/run_x2td_validation.py --dry_run
  python3 cfd_scripts/run_x2td_validation.py --parallel 5
  python3 cfd_scripts/run_x2td_validation.py --collectives 4 6 8 10 12 --parallel 5
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
import run_sweep as rs  # reuse of_run, write_case_configs_dual, extract_results_dual,
                          # figure_of_merit, rpm_to_rads -- all already generic over
                          # naca/diameter/chord/collective/spacing, nothing duplicated here

# ── Fixed case parameters (see module docstring for the reasoning behind each) ─
DIAMETER      = rs.DIAMETER          # 1.0 m -- reuse TEMPLATE_DUAL as-is
NACA          = "2412"               # closest NACA 4-digit match to SC1012R8 (see docstring)
SPACING_M     = 0.10                 # m -- matches co_rot_meshcheck, NOT Qin & Yang's H/D=0.0568
                                      # (abandoned 2026-07-30; see docstring deviation 2)
AZIMUTH_DEG   = 0.0                  # baseline FM check, not an azimuth-sensitivity study
RPM           = 900.0                # matched upper/lower; Mtip~=0.137, NOT Qin & Yang's 0.563 -- see docstring (3)
CHORD_M       = 0.08   # m -- confirmed meshable with TEMPLATE_DUAL as-is; see docstring (4) for why the
                        # original AR=19.2-derived 0.026m guess was rejected (blade patches vanished entirely)
ROOT_FRACTION = 0.30                 # project default; X2TD's own root cutout is not stated in the source paper
MRF_RADIUS    = 0.6                  # same as co_rot's default (D=1.0 m), unchanged
UPPER_Z       = rs.UPPER_Z
END_TIME      = 1500.0

DEFAULT_COLLECTIVES = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0]
# Bracket around the expected CT=0.005 point. Widened toward 0 deg (vs. C-T's
# 4-12 deg range) because NACA 2412 is cambered, unlike C-T's symmetric NACA0012 --
# a cambered section produces positive CT even at 0 deg collective, so the real
# collective needed to hit CT=0.005 could plausibly sit below 4 deg. Widen further
# toward negative angles with --collectives if the sweep still doesn't bracket the
# target (X2TD_validation.py will tell you if it doesn't).

SWEEP_DIR   = Path(rs.BASE_DIR) / "8_x2td_validation_sweep"
TEMPLATE_DIR = rs.TEMPLATE_DUAL   # deliberately NOT a new template -- see docstring (1)
RESULTS_CSV = SWEEP_DIR / "x2td_validation_results.csv"

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
    case_id = f"x2td_c{collective_deg:04.1f}"
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
    print(f"[{i}/{total}] DONE  {case_id}  T={tt:.1f}N  P={pu+pl:.0f}W  "
          f"FM={row['fom_total']}  t={elapsed:.0f}s", flush=True)
    return row


def append_row(row, csv_path):
    with open(csv_path, "a", newline="") as f:
        rs._lock(f)
        csv.DictWriter(f, fieldnames=CSV_HEADER).writerow(row)
        f.flush()
        os.fsync(f.fileno())
        rs._unlock(f)


def main():
    global CHORD_M
    ap = argparse.ArgumentParser(description="X2TD (Qin & Yang 2025) literature-match validation sweep")
    ap.add_argument("--collectives", type=float, nargs="+", default=DEFAULT_COLLECTIVES,
                     help=f"Collective angles [deg] to bracket CT=0.005 (default: {DEFAULT_COLLECTIVES})")
    ap.add_argument("--chord", type=float, default=CHORD_M,
                     help=f"Override constant chord [m] (default derived from AR=19.2: {CHORD_M:.4f} m)")
    ap.add_argument("--parallel", type=int, default=1)
    ap.add_argument("--dry_run", action="store_true")
    args = ap.parse_args()

    CHORD_M = args.chord

    # Read-only: safe before the dry_run check. Everything that WRITES to disk
    # (makedirs, CSV header creation) is deliberately kept below the dry_run
    # return -- see run_sweep.py's own "Nothing above this line ever touches
    # disk" comment for the exact incident (a dry run that clobbered a
    # 1124-row results CSV) this ordering is copied from.
    completed = set()
    if RESULTS_CSV.exists():
        with open(RESULTS_CSV) as f:
            for row in csv.DictReader(f):
                completed.add(row["case_id"])
        print(f"Skipping {len(completed)} already-completed cases")

    combos = [c for c in args.collectives if f"x2td_c{c:04.1f}" not in completed]
    total = len(combos)
    print(f"NACA {NACA}  D={DIAMETER}m  spacing={SPACING_M:.4f}m (H/D={SPACING_M/DIAMETER:.4f})  "
          f"RPM={RPM}  chord={CHORD_M:.4f}m  collectives={combos}")
    print(f"Cases to run: {total}")

    if args.dry_run:
        for c in combos:
            print(f"  x2td_c{c:04.1f}")
        return

    os.makedirs(SWEEP_DIR, exist_ok=True)
    write_header = not RESULTS_CSV.exists()
    if write_header:
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
    print("Next: python3 cfd_scripts/X2TD_validation.py "
          f"--csv {RESULTS_CSV} --outdir results_X2TD_validation")


if __name__ == "__main__":
    main()
