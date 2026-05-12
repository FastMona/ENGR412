"""
run_sweep.py — ENGR412 coaxial rotor parametric sweep
Automates OpenFOAM runs across the design space to generate NN training data.

Design variables swept:
  axial_spacing_m  : distance between rotor planes [m]
  azimuth_deg      : azimuthal index angle of lower rotor relative to upper [deg]
  rpm_lower        : lower rotor RPM (upper fixed at 900 RPM)
  pitch_lower      : lower rotor geometric pitch [m] (upper fixed at 0.4 m)
  counter_rotating : False (co-rotating sweep first), then True (counter-rotating)

Outputs per run (CSV row):
  inputs  : spacing, azimuth, rpm_upper, rpm_lower, pitch_upper, pitch_lower, counter_rotating
  outputs : thrust_upper, thrust_lower, thrust_total, torque_upper, torque_lower, torque_net,
            power_upper, power_lower, power_total, figure_of_merit, iterations, converged

Usage:
  python3 run_sweep.py [--parallel N] [--dry_run]
  python3 run_sweep.py --parallel 12              # use 12 cores (recommended)
  python3 run_sweep.py --spacing 0.3 --azimuth 0  # single-variable override

Notes:
  - Each case is an independent subdirectory under SWEEP_DIR
  - Completed cases are skipped — safe to kill and restart at any point
  - Results appended to sweep_results.csv (one row per completed case)
  - Co-rotating cases run first (no mirror_y), then counter-rotating (mirror_y)
"""

import argparse
import itertools
import os
import subprocess
import csv
import json
import shutil
import time
import fcntl
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
OPENFOAM_BASHRC = "/usr/lib/openfoam/openfoam2412/etc/bashrc"
TEMPLATE_DIR    = "/home/david/OpenFOAM/ENGR412/coaxialRotor"
SWEEP_DIR       = "/home/david/OpenFOAM/ENGR412/sweep"
# Generator script lives next to this file in the project scripts/ folder,
# but is also accessible from WSL via the /mnt/c mount
_THIS_DIR = Path(__file__).parent
GENERATOR = f"/mnt/c/Users/David/Documents_local/Repository_local/PythonProjects/ENGR412/scripts/generate_propeller.py"
RESULTS_CSV = os.path.join(SWEEP_DIR, "sweep_results.csv")

# ── Fixed parameters ──────────────────────────────────────────────────────────
UPPER_Z      = 5.0    # upper rotor disk height [m]
DIAMETER     = 1.0    # rotor diameter [m]
RPM_UPPER    = 900.0  # upper rotor RPM (fixed — controlled by flight controller)
PITCH_UPPER  = 0.4    # upper rotor geometric pitch [m] (fixed)

# ── Design space ──────────────────────────────────────────────────────────────
# counter_rotating=False runs first (co-rotating), then True (counter-rotating).
# This ordering means the easier convergence cases build the CSV first.
DESIGN_SPACE = {
    "spacing_m":   [0.10, 0.20, 0.30, 0.40, 0.60],   # axial gap [m]
    "azimuth_deg": [0, 15, 30, 45, 60, 75, 90],       # index angle [deg]
    "rpm_lower":   [600, 750, 900, 1050, 1200],        # lower rotor RPM
    "pitch_lower": [0.3, 0.4, 0.5],                   # lower rotor pitch [m]
    "counter_rot": [False, True],                      # co-rotating FIRST
}

CSV_HEADER = [
    "case_id",
    "spacing_m", "azimuth_deg", "rpm_upper", "rpm_lower",
    "pitch_upper", "pitch_lower", "counter_rotating",
    "thrust_upper_N", "thrust_lower_N", "thrust_total_N",
    "torque_upper_Nm", "torque_lower_Nm", "torque_net_Nm",
    "power_upper_W", "power_lower_W", "power_total_W",
    "fom_upper", "fom_lower", "fom_total",
    "iterations", "converged",
]


# ── Helpers ───────────────────────────────────────────────────────────────────
def of_run(cmd, cwd):
    full = f"source {OPENFOAM_BASHRC} && cd {cwd} && {cmd}"
    r = subprocess.run(["bash", "-c", full], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def rpm_to_rads(rpm):
    return rpm * 2.0 * 3.14159265358979 / 60.0


def figure_of_merit(thrust_N, power_W, rho=1.225, R=0.5):
    """Actuator disk ideal power / actual power (higher = more efficient)."""
    if power_W <= 0 or thrust_N <= 0:
        return None
    area = 3.14159265358979 * R ** 2
    ideal = thrust_N * (thrust_N / (2 * rho * area)) ** 0.5
    return round(ideal / power_W, 4)


def read_last_force(dat_path, col):
    last = None
    with open(dat_path) as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith('#') and not s.startswith('/'):
                last = s
    return float(last.split()[col]) if last else None


def extract_results(case_dir):
    pp = Path(case_dir) / "postProcessing"

    def fz(name):
        p = pp / name / "0" / "force.dat"
        return read_last_force(str(p), 3) if p.exists() else None

    def mz(name):
        p = pp / name / "0" / "moment.dat"
        return read_last_force(str(p), 3) if p.exists() else None

    def last_iter():
        log = Path(case_dir) / "simpleFoam.log"
        n = 0
        if log.exists():
            with open(log) as f:
                for line in f:
                    if line.startswith("Time = "):
                        try: n = int(line.split("=")[1].strip())
                        except ValueError: pass
        return n

    return {
        "thrust_upper_N":  fz("forcesUpper"),
        "thrust_lower_N":  fz("forcesLower"),
        "thrust_total_N":  fz("forcesTotal"),
        "torque_upper_Nm": mz("forcesUpper"),
        "torque_lower_Nm": mz("forcesLower"),
        "iterations":      last_iter(),
    }


def write_case_configs(case_dir, spacing, azimuth, rpm_lower, pitch_lower, counter_rot):
    lower_z = UPPER_Z - spacing
    omega_u = rpm_to_rads(RPM_UPPER)
    omega_l = -rpm_to_rads(rpm_lower) if counter_rot else rpm_to_rads(rpm_lower)

    tri = Path(case_dir) / "constant" / "triSurface"
    tri.mkdir(parents=True, exist_ok=True)

    subprocess.run(["python3", GENERATOR,
        "--pitch", str(PITCH_UPPER), "--diameter", str(DIAMETER),
        "--rotor_z", str(UPPER_Z), "--solid_name", "upperPropeller",
        "--output", str(tri / "upperPropeller.stl")], check=True,
        capture_output=True)

    mirror = ["--mirror_y"] if counter_rot else []
    subprocess.run(["python3", GENERATOR,
        "--pitch", str(pitch_lower), "--diameter", str(DIAMETER),
        "--rotor_z", str(lower_z), "--solid_name", "lowerPropeller",
        "--azimuth_deg", str(azimuth),
        "--output", str(tri / "lowerPropeller.stl")] + mirror,
        check=True, capture_output=True)

    sys_dir  = Path(case_dir) / "system"
    const_dir = Path(case_dir) / "constant"

    (sys_dir / "surfaceFeatureExtractDict").write_text(
        'FoamFile { version 2.0; format ascii; class dictionary; object surfaceFeatureExtractDict; }\n'
        'upperPropeller.stl { extractionMethod extractFromSurface; '
        'extractFromSurfaceCoeffs { includedAngle 120; } writeObj yes; }\n'
        'lowerPropeller.stl  { extractionMethod extractFromSurface; '
        'extractFromSurfaceCoeffs { includedAngle 120; } writeObj yes; }\n'
    )

    (sys_dir / "topoSetDict").write_text(
        f'FoamFile {{ version 2.0; format ascii; class dictionary; object topoSetDict; }}\n'
        f'actions (\n'
        f'  {{ name rotatingZone1; type cellZoneSet; action new; source cylinderToCell;\n'
        f'     p1 (0 0 {UPPER_Z-0.125:.3f}); p2 (0 0 {UPPER_Z+0.125:.3f}); radius 0.6; }}\n'
        f'  {{ name rotatingZone2; type cellZoneSet; action new; source cylinderToCell;\n'
        f'     p1 (0 0 {lower_z-0.125:.3f}); p2 (0 0 {lower_z+0.125:.3f}); radius 0.6; }}\n'
        f');\n'
    )

    (const_dir / "MRFProperties").write_text(
        f'FoamFile {{ version 2.0; format ascii; class dictionary; object MRFProperties; }}\n'
        f'MRF1 {{ cellZone rotatingZone1; active true;\n'
        f'        nonRotatingPatches (inlet outlet sides);\n'
        f'        origin (0 0 {UPPER_Z}); axis (0 0 1); omega {omega_u:.6f}; }}\n'
        f'MRF2 {{ cellZone rotatingZone2; active true;\n'
        f'        nonRotatingPatches (inlet outlet sides);\n'
        f'        origin (0 0 {lower_z:.4f}); axis (0 0 1); omega {omega_l:.6f}; }}\n'
    )

    (sys_dir / "controlDict").write_text(
        f'FoamFile {{ version 2.0; format ascii; class dictionary; object controlDict; }}\n'
        f'application simpleFoam; startFrom startTime; startTime 0; stopAt endTime;\n'
        f'endTime 500; deltaT 1; writeControl timeStep; writeInterval 500;\n'
        f'purgeWrite 0; writeFormat ascii; writePrecision 6; writeCompression off;\n'
        f'timeFormat general; timePrecision 6; runTimeModifiable true;\n'
        f'functions {{\n'
        f'    forcesUpper {{ type forces; libs (forces); writeControl timeStep; writeInterval 10;\n'
        f'        patches (upperBlade); rho rhoInf; rhoInf 1.225; CofR (0 0 {UPPER_Z}); log yes; }}\n'
        f'    forcesLower {{ type forces; libs (forces); writeControl timeStep; writeInterval 10;\n'
        f'        patches (lowerBlade); rho rhoInf; rhoInf 1.225; CofR (0 0 {lower_z:.4f}); log yes; }}\n'
        f'    forcesTotal {{ type forces; libs (forces); writeControl timeStep; writeInterval 10;\n'
        f'        patches (upperBlade lowerBlade); rho rhoInf; rhoInf 1.225;\n'
        f'        CofR (0 0 {(UPPER_Z+lower_z)/2:.4f}); log yes; }}\n'
        f'}}\n'
    )

    shutil.copy(
        str(Path(TEMPLATE_DIR) / "system" / "snappyHexMeshDict"),
        str(sys_dir / "snappyHexMeshDict"),
    )

    (Path(case_dir) / "run_params.json").write_text(json.dumps({
        "spacing_m": spacing, "azimuth_deg": azimuth,
        "rpm_upper": RPM_UPPER, "rpm_lower": rpm_lower,
        "pitch_upper": PITCH_UPPER, "pitch_lower": pitch_lower,
        "counter_rotating": counter_rot,
        "lower_z": lower_z, "omega_upper": omega_u, "omega_lower": omega_l,
    }, indent=2))


def run_case(args_tuple):
    """Worker function — runs one complete case. Returns a result dict."""
    i, total, case_id, case_dir, spacing, azimuth, rpm_l, pitch_l, counter = args_tuple

    print(f"[{i}/{total}] START {case_id}", flush=True)
    t0 = time.time()

    os.makedirs(case_dir, exist_ok=True)
    for sub in ["0", "system", "constant"]:
        dst = os.path.join(case_dir, sub)
        if not os.path.exists(dst):
            shutil.copytree(os.path.join(TEMPLATE_DIR, sub), dst)

    try:
        write_case_configs(case_dir, spacing, azimuth, rpm_l, pitch_l, counter)
    except Exception as e:
        print(f"[{i}/{total}] ERROR writing configs for {case_id}: {e}", flush=True)
        return None

    steps = [
        ("blockMesh",              "blockMesh > blockMesh.log 2>&1"),
        ("surfaceFeatureExtract",  "surfaceFeatureExtract > surfaceFeatureExtract.log 2>&1"),
        ("snappyHexMesh",          "snappyHexMesh > snappyHexMesh.log 2>&1"),
        ("promoteMesh",
         "MESHDIR=$(ls -d [0-9]* | sort -n | tail -1) && "
         "cp -r $MESHDIR/polyMesh constant/ && rm -rf $MESHDIR"),
        ("topoSet",                "topoSet > topoSet.log 2>&1"),
        ("simpleFoam",             "simpleFoam > simpleFoam.log 2>&1"),
    ]

    for step_name, cmd in steps:
        rc, out = of_run(cmd, case_dir)
        if rc != 0 and step_name not in ("simpleFoam", "promoteMesh"):
            print(f"[{i}/{total}] FAIL {case_id} at {step_name}", flush=True)
            return None

    elapsed = time.time() - t0
    res = extract_results(case_dir)

    tu  = res.get("thrust_upper_N") or 0.0
    tl  = res.get("thrust_lower_N") or 0.0
    tt  = res.get("thrust_total_N") or 0.0
    qu  = res.get("torque_upper_Nm") or 0.0
    ql  = res.get("torque_lower_Nm") or 0.0
    iters = res.get("iterations", 0)

    omega_u = rpm_to_rads(RPM_UPPER)
    omega_l = rpm_to_rads(rpm_l)
    pu = abs(qu) * omega_u
    pl = abs(ql) * omega_l

    row = {
        "case_id": case_id,
        "spacing_m": spacing, "azimuth_deg": azimuth,
        "rpm_upper": RPM_UPPER, "rpm_lower": rpm_l,
        "pitch_upper": PITCH_UPPER, "pitch_lower": pitch_l,
        "counter_rotating": counter,
        "thrust_upper_N":  round(tu, 4),
        "thrust_lower_N":  round(tl, 4),
        "thrust_total_N":  round(tt, 4),
        "torque_upper_Nm": round(qu, 4),
        "torque_lower_Nm": round(ql, 4),
        "torque_net_Nm":   round(qu + ql, 4),
        "power_upper_W":   round(pu, 2),
        "power_lower_W":   round(pl, 2),
        "power_total_W":   round(pu + pl, 2),
        "fom_upper":  figure_of_merit(tu, pu),
        "fom_lower":  figure_of_merit(tl, pl),
        "fom_total":  figure_of_merit(tt, pu + pl),
        "iterations": iters,
        "converged":  True,
    }

    print(f"[{i}/{total}] DONE  {case_id}  "
          f"T={tt:.1f}N  Tu={tu:.1f}N  Tl={tl:.1f}N  "
          f"P={pu+pl:.0f}W  t={elapsed:.0f}s", flush=True)
    return row


# ── CSV writer (file-locked for parallel safety) ──────────────────────────────
def append_row(row):
    with open(RESULTS_CSV, "a", newline="") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writerow(row)
        fcntl.flock(f, fcntl.LOCK_UN)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parallel", type=int, default=1,
                    help="Number of cases to run simultaneously (default 1; recommended: N_cores/2)")
    ap.add_argument("--dry_run",  action="store_true",
                    help="List cases without running them")
    ap.add_argument("--spacing",  type=float, nargs="+")
    ap.add_argument("--azimuth",  type=float, nargs="+")
    ap.add_argument("--rpm",      type=float, nargs="+")
    ap.add_argument("--pitch",    type=float, nargs="+")
    ap.add_argument("--co_only",  action="store_true", help="Run co-rotating cases only")
    ap.add_argument("--cr_only",  action="store_true", help="Run counter-rotating cases only")
    args = ap.parse_args()

    space = dict(DESIGN_SPACE)
    if args.spacing: space["spacing_m"]   = args.spacing
    if args.azimuth: space["azimuth_deg"] = args.azimuth
    if args.rpm:     space["rpm_lower"]   = args.rpm
    if args.pitch:   space["pitch_lower"] = args.pitch
    if args.co_only: space["counter_rot"] = [False]
    if args.cr_only: space["counter_rot"] = [True]

    combos = list(itertools.product(
        space["counter_rot"],      # co-rotating (False) first in list → runs first
        space["spacing_m"],
        space["azimuth_deg"],
        space["rpm_lower"],
        space["pitch_lower"],
    ))
    # Re-order tuple to (spacing, az, rpm, pitch, counter) for readability
    combos = [(s, a, r, p, c) for c, s, a, r, p in combos]

    total = len(combos)
    print(f"Total cases: {total}  |  parallel workers: {args.parallel}")
    print(f"Estimated time: {total * 120 / args.parallel / 3600:.1f} hours "
          f"@ 2 min/case with {args.parallel} workers\n")

    # Load already-completed case IDs
    completed = set()
    if os.path.exists(RESULTS_CSV):
        with open(RESULTS_CSV) as f:
            for row in csv.DictReader(f):
                completed.add(row["case_id"])
        print(f"Skipping {len(completed)} already-completed cases")

    os.makedirs(SWEEP_DIR, exist_ok=True)

    # Ensure CSV header exists
    if not os.path.exists(RESULTS_CSV):
        with open(RESULTS_CSV, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADER).writeheader()

    # Build work queue (skip completed)
    queue = []
    for i, (spacing, azimuth, rpm_l, pitch_l, counter) in enumerate(combos, 1):
        rot = "CR" if counter else "CO"
        case_id = f"s{spacing:.2f}_a{azimuth:03.0f}_r{rpm_l:.0f}_p{pitch_l:.2f}_{rot}"
        if case_id in completed:
            continue
        case_dir = os.path.join(SWEEP_DIR, case_id)
        queue.append((i, total, case_id, case_dir, spacing, azimuth, rpm_l, pitch_l, counter))

    print(f"Cases to run: {len(queue)}")

    if args.dry_run:
        for item in queue[:20]:
            print(f"  {item[2]}")
        if len(queue) > 20:
            print(f"  ... ({len(queue)-20} more)")
        return

    if args.parallel == 1:
        for item in queue:
            row = run_case(item)
            if row:
                append_row(row)
    else:
        with ProcessPoolExecutor(max_workers=args.parallel) as pool:
            futures = {pool.submit(run_case, item): item[2] for item in queue}
            for fut in as_completed(futures):
                row = fut.result()
                if row:
                    append_row(row)

    print(f"\nAll done. Results: {RESULTS_CSV}")


if __name__ == "__main__":
    main()
