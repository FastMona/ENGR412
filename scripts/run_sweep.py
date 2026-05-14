"""
run_sweep.py — ENGR412 parametric sweep (single-rotor, co-rotating, contra-rotating)

Datasets
  single      : 1 rotor, varies RPM × pitch  (15 cases, ~30 min @ --parallel 12)
  co_rot      : 2 co-rotating rotors          (525 cases — already complete)
  contra_rot  : 2 counter-rotating rotors     (525 cases)

Output folders (all under /home/david/OpenFOAM/ENGR412/):
  1_single_rotor_sweep/   ← single dataset
  2_co_rot_sweep/         ← co_rot dataset  (rename existing 'sweep/' in WSL first:
                               mv /home/david/OpenFOAM/ENGR412/sweep
                                  /home/david/OpenFOAM/ENGR412/2_co_rot_sweep )
  2_contra_rot_sweep/     ← contra_rot dataset

Usage
  python3 run_sweep.py --dataset single     --parallel 12
  python3 run_sweep.py --dataset co_rot     --parallel 12   # already done
  python3 run_sweep.py --dataset contra_rot --parallel 12
  python3 run_sweep.py --dataset single     --dry_run
"""

import argparse
import itertools
import os
import subprocess
import csv
import json
import shutil
import time
try:
    import fcntl as _fcntl
    def _lock(f):   getattr(_fcntl, "flock")(f, getattr(_fcntl, "LOCK_EX"))
    def _unlock(f): getattr(_fcntl, "flock")(f, getattr(_fcntl, "LOCK_UN"))
except ImportError:
    def _lock(f):   pass  # noqa: E731
    def _unlock(f): pass  # noqa: E731
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# ── Static paths ──────────────────────────────────────────────────────────────
OPENFOAM_BASHRC    = "/usr/lib/openfoam/openfoam2412/etc/bashrc"
BASE_DIR           = "/home/david/OpenFOAM/ENGR412"
TEMPLATE_SINGLE    = f"{BASE_DIR}/singleRotor"
TEMPLATE_DUAL      = f"{BASE_DIR}/coaxialRotor"
GENERATOR          = ("/mnt/c/Users/David/Documents_local/Repository_local"
                      "/PythonProjects/ENGR412/scripts/generate_propeller.py")

# ── Dataset configurations ────────────────────────────────────────────────────
DATASETS = {
    "single": {
        "sweep_dir":    f"{BASE_DIR}/1_single_rotor_sweep",
        "template_dir": TEMPLATE_SINGLE,
        "csv_name":     "single_rotor_results.csv",
    },
    "co_rot": {
        "sweep_dir":    f"{BASE_DIR}/2_co_rot_sweep",
        "template_dir": TEMPLATE_DUAL,
        "csv_name":     "co_rot_results.csv",
    },
    "contra_rot": {
        "sweep_dir":    f"{BASE_DIR}/2_contra_rot_sweep",
        "template_dir": TEMPLATE_DUAL,
        "csv_name":     "contra_rot_results.csv",
    },
}

# ── Fixed parameters ──────────────────────────────────────────────────────────
UPPER_Z      = 5.0    # upper rotor disk height [m]
DIAMETER     = 1.0    # rotor diameter [m]
RPM_UPPER    = 900.0  # upper rotor RPM (fixed)
PITCH_UPPER  = 0.4    # upper rotor pitch [m] (fixed)

# ── Design spaces ─────────────────────────────────────────────────────────────
DESIGN_SPACE_SINGLE = {
    "rpm":   [600, 750, 900, 1050, 1200],
    "pitch": [0.3, 0.4, 0.5],
}

DESIGN_SPACE_DUAL = {
    "spacing_m":   [0.10, 0.20, 0.30, 0.40, 0.60],
    "azimuth_deg": [0, 15, 30, 45, 60, 75, 90],
    "rpm_lower":   [600, 750, 900, 1050, 1200],
    "pitch_lower": [0.3, 0.4, 0.5],
}

# ── CSV headers ───────────────────────────────────────────────────────────────
CSV_HEADER_SINGLE = [
    "case_id",
    "rpm", "pitch",
    "thrust_N", "torque_Nm", "power_W", "fom",
    "iterations", "converged",
]

CSV_HEADER_DUAL = [
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


def last_iter(case_dir):
    log = Path(case_dir) / "simpleFoam.log"
    n = 0
    if log.exists():
        with open(log) as f:
            for line in f:
                if line.startswith("Time = "):
                    try:
                        n = int(line.split("=")[1].strip())
                    except ValueError:
                        pass
    return n


# ── Single-rotor case setup ───────────────────────────────────────────────────
def write_case_configs_single(case_dir, rpm, pitch):
    omega = rpm_to_rads(rpm)
    tri = Path(case_dir) / "constant" / "triSurface"
    tri.mkdir(parents=True, exist_ok=True)
    sys_dir   = Path(case_dir) / "system"
    const_dir = Path(case_dir) / "constant"

    subprocess.run(["python3", GENERATOR,
        "--pitch", str(pitch), "--diameter", str(DIAMETER),
        "--rotor_z", str(UPPER_Z), "--solid_name", "propeller",
        "--output", str(tri / "propeller.stl")],
        check=True, capture_output=True)

    (sys_dir / "surfaceFeatureExtractDict").write_text(
        'FoamFile { version 2.0; format ascii; class dictionary; '
        'object surfaceFeatureExtractDict; }\n'
        'propeller.stl { extractionMethod extractFromSurface; '
        'extractFromSurfaceCoeffs { includedAngle 120; } writeObj yes; }\n'
    )

    (sys_dir / "topoSetDict").write_text(
        f'FoamFile {{ version 2.0; format ascii; class dictionary; object topoSetDict; }}\n'
        f'actions (\n'
        f'  {{ name rotatingZone; type cellZoneSet; action new; source cylinderToCell;\n'
        f'     p1 (0 0 {UPPER_Z-0.125:.3f}); p2 (0 0 {UPPER_Z+0.125:.3f}); radius 0.6; }}\n'
        f');\n'
    )

    (const_dir / "MRFProperties").write_text(
        f'FoamFile {{ version 2.0; format ascii; class dictionary; object MRFProperties; }}\n'
        f'MRF1 {{ cellZone rotatingZone; active true;\n'
        f'        nonRotatingPatches (inlet outlet sides);\n'
        f'        origin (0 0 {UPPER_Z}); axis (0 0 1); omega {omega:.6f}; }}\n'
    )

    (sys_dir / "controlDict").write_text(
        f'FoamFile {{ version 2.0; format ascii; class dictionary; object controlDict; }}\n'
        f'application simpleFoam; startFrom startTime; startTime 0; stopAt endTime;\n'
        f'endTime 500; deltaT 1; writeControl timeStep; writeInterval 500;\n'
        f'purgeWrite 0; writeFormat ascii; writePrecision 6; writeCompression off;\n'
        f'timeFormat general; timePrecision 6; runTimeModifiable true;\n'
        f'functions {{\n'
        f'    forcesRotor {{ type forces; libs (forces); writeControl timeStep; writeInterval 10;\n'
        f'        patches (blade); rho rhoInf; rhoInf 1.225; CofR (0 0 {UPPER_Z}); log yes; }}\n'
        f'}}\n'
    )

    shutil.copy(
        str(Path(TEMPLATE_SINGLE) / "system" / "snappyHexMeshDict"),
        str(sys_dir / "snappyHexMeshDict"),
    )

    (Path(case_dir) / "run_params.json").write_text(json.dumps({
        "dataset": "single", "rpm": rpm, "pitch": pitch,
        "omega": omega, "rotor_z": UPPER_Z,
    }, indent=2))


def extract_results_single(case_dir):
    pp = Path(case_dir) / "postProcessing"
    p_force  = pp / "forcesRotor" / "0" / "force.dat"
    p_moment = pp / "forcesRotor" / "0" / "moment.dat"
    return {
        "thrust_N":  read_last_force(str(p_force),  3) if p_force.exists()  else None,
        "torque_Nm": read_last_force(str(p_moment), 3) if p_moment.exists() else None,
        "iterations": last_iter(case_dir),
    }


# ── Dual-rotor case setup ─────────────────────────────────────────────────────
def write_case_configs_dual(case_dir, spacing, azimuth, rpm_lower, pitch_lower, counter_rot):
    lower_z = UPPER_Z - spacing
    omega_u = rpm_to_rads(RPM_UPPER)
    omega_l = -rpm_to_rads(rpm_lower) if counter_rot else rpm_to_rads(rpm_lower)

    tri = Path(case_dir) / "constant" / "triSurface"
    tri.mkdir(parents=True, exist_ok=True)
    sys_dir   = Path(case_dir) / "system"
    const_dir = Path(case_dir) / "constant"

    subprocess.run(["python3", GENERATOR,
        "--pitch", str(PITCH_UPPER), "--diameter", str(DIAMETER),
        "--rotor_z", str(UPPER_Z), "--solid_name", "upperPropeller",
        "--output", str(tri / "upperPropeller.stl")],
        check=True, capture_output=True)

    mirror = ["--mirror_y"] if counter_rot else []
    subprocess.run(["python3", GENERATOR,
        "--pitch", str(pitch_lower), "--diameter", str(DIAMETER),
        "--rotor_z", str(lower_z), "--solid_name", "lowerPropeller",
        "--azimuth_deg", str(azimuth),
        "--output", str(tri / "lowerPropeller.stl")] + mirror,
        check=True, capture_output=True)

    (sys_dir / "surfaceFeatureExtractDict").write_text(
        'FoamFile { version 2.0; format ascii; class dictionary; '
        'object surfaceFeatureExtractDict; }\n'
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
        str(Path(TEMPLATE_DUAL) / "system" / "snappyHexMeshDict"),
        str(sys_dir / "snappyHexMeshDict"),
    )

    (Path(case_dir) / "run_params.json").write_text(json.dumps({
        "dataset": "dual", "spacing_m": spacing, "azimuth_deg": azimuth,
        "rpm_upper": RPM_UPPER, "rpm_lower": rpm_lower,
        "pitch_upper": PITCH_UPPER, "pitch_lower": pitch_lower,
        "counter_rotating": counter_rot,
        "lower_z": lower_z, "omega_upper": omega_u, "omega_lower": omega_l,
    }, indent=2))


def extract_results_dual(case_dir):
    pp = Path(case_dir) / "postProcessing"

    def fz(name):
        p = pp / name / "0" / "force.dat"
        return read_last_force(str(p), 3) if p.exists() else None

    def mz(name):
        p = pp / name / "0" / "moment.dat"
        return read_last_force(str(p), 3) if p.exists() else None

    return {
        "thrust_upper_N":  fz("forcesUpper"),
        "thrust_lower_N":  fz("forcesLower"),
        "thrust_total_N":  fz("forcesTotal"),
        "torque_upper_Nm": mz("forcesUpper"),
        "torque_lower_Nm": mz("forcesLower"),
        "iterations":      last_iter(case_dir),
    }


# ── Generic case runner ───────────────────────────────────────────────────────
def run_case(args_tuple):
    i, total, case_id, case_dir, params, dataset, template_dir = args_tuple

    print(f"[{i}/{total}] START {case_id}", flush=True)
    t0 = time.time()

    os.makedirs(case_dir, exist_ok=True)
    for sub in ["0", "system", "constant"]:
        dst = os.path.join(case_dir, sub)
        if not os.path.exists(dst):
            shutil.copytree(os.path.join(template_dir, sub), dst)

    try:
        if dataset == "single":
            write_case_configs_single(case_dir, params["rpm"], params["pitch"])
        else:
            write_case_configs_dual(
                case_dir,
                params["spacing_m"], params["azimuth_deg"],
                params["rpm_lower"],  params["pitch_lower"],
                dataset == "contra_rot",
            )
    except Exception as e:
        print(f"[{i}/{total}] ERROR writing configs for {case_id}: {e}", flush=True)
        return None

    steps = [
        ("blockMesh",             "blockMesh > blockMesh.log 2>&1"),
        ("surfaceFeatureExtract", "surfaceFeatureExtract > surfaceFeatureExtract.log 2>&1"),
        ("snappyHexMesh",         "snappyHexMesh > snappyHexMesh.log 2>&1"),
        ("promoteMesh",
         "MESHDIR=$(ls -d [0-9]* | sort -n | tail -1) && "
         "cp -r $MESHDIR/polyMesh constant/ && rm -rf $MESHDIR"),
        ("topoSet",               "topoSet > topoSet.log 2>&1"),
        ("simpleFoam",            "simpleFoam > simpleFoam.log 2>&1"),
    ]

    for step_name, cmd in steps:
        rc, _ = of_run(cmd, case_dir)
        if rc != 0 and step_name not in ("simpleFoam", "promoteMesh"):
            print(f"[{i}/{total}] FAIL {case_id} at {step_name}", flush=True)
            return None

    elapsed = time.time() - t0

    if dataset == "single":
        res = extract_results_single(case_dir)
        t   = res.get("thrust_N")  or 0.0
        q   = res.get("torque_Nm") or 0.0
        iters = res.get("iterations", 0)
        omega = rpm_to_rads(params["rpm"])
        pwr   = abs(q) * omega

        row = {
            "case_id":    case_id,
            "rpm":        params["rpm"],
            "pitch":      params["pitch"],
            "thrust_N":   round(t, 4),
            "torque_Nm":  round(q, 4),
            "power_W":    round(pwr, 2),
            "fom":        figure_of_merit(t, pwr),
            "iterations": iters,
            "converged":  True,
        }
        print(f"[{i}/{total}] DONE  {case_id}  "
              f"T={t:.1f}N  Q={q:.3f}Nm  P={pwr:.0f}W  t={elapsed:.0f}s", flush=True)

    else:
        res = extract_results_dual(case_dir)
        tu  = res.get("thrust_upper_N") or 0.0
        tl  = res.get("thrust_lower_N") or 0.0
        tt  = res.get("thrust_total_N") or 0.0
        qu  = res.get("torque_upper_Nm") or 0.0
        ql  = res.get("torque_lower_Nm") or 0.0
        iters = res.get("iterations", 0)
        omega_u = rpm_to_rads(RPM_UPPER)
        omega_l = rpm_to_rads(params["rpm_lower"])
        pu = abs(qu) * omega_u
        pl = abs(ql) * omega_l

        row = {
            "case_id": case_id,
            "spacing_m":  params["spacing_m"],  "azimuth_deg": params["azimuth_deg"],
            "rpm_upper":  RPM_UPPER,             "rpm_lower":   params["rpm_lower"],
            "pitch_upper": PITCH_UPPER,          "pitch_lower": params["pitch_lower"],
            "counter_rotating": dataset == "contra_rot",
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
def append_row(row, csv_path, header):
    with open(csv_path, "a", newline="") as f:
        _lock(f)
        csv.DictWriter(f, fieldnames=header).writerow(row)
        _unlock(f)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="ENGR412 parametric sweep runner")
    ap.add_argument("--dataset",  required=True,
                    choices=["single", "co_rot", "contra_rot"],
                    help="Which dataset to run")
    ap.add_argument("--parallel", type=int, default=1,
                    help="Parallel workers (default 1; recommended: N_cores/2)")
    ap.add_argument("--dry_run",  action="store_true",
                    help="List cases without running them")
    ap.add_argument("--rpm",      type=float, nargs="+", help="Override RPM values")
    ap.add_argument("--pitch",    type=float, nargs="+", help="Override pitch values")
    ap.add_argument("--spacing",  type=float, nargs="+", help="Override spacing values (dual only)")
    ap.add_argument("--azimuth",  type=float, nargs="+", help="Override azimuth values (dual only)")
    args = ap.parse_args()

    cfg          = DATASETS[args.dataset]
    sweep_dir    = cfg["sweep_dir"]
    results_csv  = os.path.join(sweep_dir, cfg["csv_name"])
    template_dir = cfg["template_dir"]
    header       = CSV_HEADER_SINGLE if args.dataset == "single" else CSV_HEADER_DUAL

    # ── Build case list ───────────────────────────────────────────────────────
    if args.dataset == "single":
        space = dict(DESIGN_SPACE_SINGLE)
        if args.rpm:   space["rpm"]   = args.rpm
        if args.pitch: space["pitch"] = args.pitch
        combos = [
            {"rpm": r, "pitch": p}
            for r, p in itertools.product(space["rpm"], space["pitch"])
        ]
        def case_id_fn(p):
            return f"r{p['rpm']:.0f}_p{p['pitch']:.2f}"
    else:
        space = dict(DESIGN_SPACE_DUAL)
        if args.spacing: space["spacing_m"]   = args.spacing
        if args.azimuth: space["azimuth_deg"] = args.azimuth
        if args.rpm:     space["rpm_lower"]   = args.rpm
        if args.pitch:   space["pitch_lower"] = args.pitch
        rot = "CR" if args.dataset == "contra_rot" else "CO"
        combos = [
            {"spacing_m": s, "azimuth_deg": a, "rpm_lower": r, "pitch_lower": p}
            for s, a, r, p in itertools.product(
                space["spacing_m"], space["azimuth_deg"],
                space["rpm_lower"], space["pitch_lower"],
            )
        ]
        def case_id_fn(p):
            return (f"s{p['spacing_m']:.2f}_a{p['azimuth_deg']:03.0f}"
                    f"_r{p['rpm_lower']:.0f}_p{p['pitch_lower']:.2f}_{rot}")

    total = len(combos)
    print(f"Dataset : {args.dataset}")
    print(f"Cases   : {total}  |  parallel workers: {args.parallel}")
    est_h = total * 120 / args.parallel / 3600
    print(f"Estimated time: {est_h:.1f} h @ 2 min/case with {args.parallel} workers\n")

    # Skip completed cases
    completed = set()
    if os.path.exists(results_csv):
        with open(results_csv) as f:
            for row in csv.DictReader(f):
                completed.add(row["case_id"])
        print(f"Skipping {len(completed)} already-completed cases")

    os.makedirs(sweep_dir, exist_ok=True)
    if not os.path.exists(results_csv):
        with open(results_csv, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=header).writeheader()
    else:
        # Guard: verify existing CSV header matches current header definition.
        # A mismatch means the CSV was created with an older version of the script
        # and rows will be misaligned.  Abort early so data isn't silently corrupted.
        with open(results_csv, newline="") as f:
            existing_header = next(csv.reader(f), [])
        if existing_header != header:
            raise SystemExit(
                f"\nERROR: CSV header mismatch!\n"
                f"  File   ({len(existing_header)} cols): {existing_header}\n"
                f"  Script ({len(header)} cols):           {header}\n"
                f"Fix: repair the CSV header row to match the script, then re-run."
            )

    queue = []
    for i, params in enumerate(combos, 1):
        cid = case_id_fn(params)
        if cid in completed:
            continue
        case_dir = os.path.join(sweep_dir, cid)
        queue.append((i, total, cid, case_dir, params, args.dataset, template_dir))

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
                append_row(row, results_csv, header)
    else:
        with ProcessPoolExecutor(max_workers=args.parallel) as pool:
            futures = {pool.submit(run_case, item): item[2] for item in queue}
            for fut in as_completed(futures):
                row = fut.result()
                if row:
                    append_row(row, results_csv, header)

    print(f"\nAll done. Results: {results_csv}")


if __name__ == "__main__":
    main()
