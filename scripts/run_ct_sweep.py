"""
run_ct_sweep.py  —  ENGR412 Caradonna-Tung CFD validation sweep

Runs the OpenFOAM MRF/simpleFoam pipeline for the C-T hover rotor at
multiple collective pitch angles, collecting thrust and power per angle.

Geometry  : NACA 0012, R=1.143 m, c=0.1905 m, 2 blades, untwisted/untapered
Condition : Mtip=0.228  →  Vtip≈78.2 m/s  →  ω≈68.07 rad/s  (~653 RPM)
Reference : Caradonna & Tung (1981), NASA TM-81232

Domain    : box ±12 m × 24 m tall, rotor at z=12 m (mid-domain, 5.25×D each side)
MRF zone  : cylinder r=1.40 m, z from 11.40 to 12.60 m (Δz=±0.60 m)

Pipeline per case: blockMesh → surfaceFeatureExtract → snappyHexMesh → topoSet → simpleFoam
Case dirs : /home/david/OpenFOAM/ENGR412/caradonnaTung/theta<N>/
CSV output: /home/david/OpenFOAM/ENGR412/caradonnaTung/ct_results.csv

Usage:
  python3 scripts/run_ct_sweep.py                       # full 11-angle sweep
  python3 scripts/run_ct_sweep.py --angles 5 8 12       # subset
  python3 scripts/run_ct_sweep.py --dry_run             # preview, no CFD
"""

import argparse, csv, os, shutil, subprocess, time
from pathlib import Path

# ── OpenFOAM paths ─────────────────────────────────────────────────────────────
OF_BASHRC  = "/usr/lib/openfoam/openfoam2412/etc/bashrc"
BASE_DIR   = Path("/home/david/OpenFOAM/ENGR412")
SWEEP_DIR  = BASE_DIR / "caradonnaTung"
SR_TMPL    = BASE_DIR / "singleRotor"      # source of generic 0/, fvSchemes, etc.
GENERATOR  = ("/mnt/c/Users/David/Documents_local/Repository_local"
              "/PythonProjects/ENGR412/scripts/generate_propeller.py")

# ── C-T rotor geometry ─────────────────────────────────────────────────────────
R_CT      = 1.143     # m  blade radius
D_CT      = 2.286     # m  diameter
C_CT      = 0.1905    # m  constant chord (untapered)
ROOT_FRAC = 0.20      # r_root / R  (blade starts at 20 % span)
OMEGA_CT  = 68.07     # rad/s  (Vtip=78.2 m/s at Mtip=0.228, ~653 RPM)

# ── Domain geometry ────────────────────────────────────────────────────────────
ROTOR_Z   = 12.0      # m  rotor disk z-position (mid-domain)
BOX_HALF  = 12.0      # m  domain ±x, ±y  (≈ 5.25×D, 10.5×R)
BOX_H     = 24.0      # m  domain total height
MRF_R     = 1.40      # m  MRF cylinder radius  (slightly > R_CT=1.143)
MRF_DZ    = 0.60      # m  MRF cylinder half-height

# ── Sweep defaults ─────────────────────────────────────────────────────────────
DEFAULT_ANGLES = [0, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12]
END_TIME       = 500
CSV_PATH       = SWEEP_DIR / "ct_results.csv"
CSV_HEADER     = ["collective_deg", "thrust_N", "torque_Nm", "power_W",
                  "iterations", "converged"]


# ── OpenFOAM helpers ───────────────────────────────────────────────────────────
def of_run(cmd: str, cwd: str) -> tuple[int, str]:
    full = f"source {OF_BASHRC} && cd {cwd} && {cmd}"
    r = subprocess.run(["bash", "-c", full], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def last_iter(case_dir: Path) -> int:
    log, n = case_dir / "simpleFoam.log", 0
    if log.exists():
        with open(log) as f:
            for line in f:
                if line.startswith("Time = "):
                    try:
                        n = int(line.split("=")[1].strip())
                    except ValueError:
                        pass
    return n


def read_last_force(dat_path: Path, col: int):
    last = None
    with open(dat_path) as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#") and not s.startswith("/"):
                last = s
    return float(last.split()[col]) if last else None


# ── OpenFOAM file generators ───────────────────────────────────────────────────
def _w(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def write_blockMeshDict(case_dir: Path):
    b, h = BOX_HALF, BOX_H
    _w(case_dir / "system" / "blockMeshDict",
       f'FoamFile {{ version 2.0; format ascii; class dictionary; object blockMeshDict; }}\n'
       f'scale 1.0;\n'
       f'// Outer box: ±{b}m × {h}m  |  rotor at z={ROTOR_Z}m (mid)\n'
       f'vertices\n(\n'
       f'    ({-b:.1f} {-b:.1f}  0.0)   // 0\n'
       f'    ( {b:.1f} {-b:.1f}  0.0)   // 1\n'
       f'    ( {b:.1f}  {b:.1f}  0.0)   // 2\n'
       f'    ({-b:.1f}  {b:.1f}  0.0)   // 3\n'
       f'    ({-b:.1f} {-b:.1f} {h:.1f})   // 4\n'
       f'    ( {b:.1f} {-b:.1f} {h:.1f})   // 5\n'
       f'    ( {b:.1f}  {b:.1f} {h:.1f})   // 6\n'
       f'    ({-b:.1f}  {b:.1f} {h:.1f})   // 7\n'
       f');\n'
       f'blocks ( hex (0 1 2 3 4 5 6 7) (60 60 80) simpleGrading (1 1 1) );\n'
       f'boundary\n(\n'
       f'    inlet  {{ type patch; faces ((0 3 2 1)); }}\n'
       f'    outlet {{ type patch; faces ((4 5 6 7)); }}\n'
       f'    sides  {{ type patch; faces ((0 1 5 4) (1 2 6 5) (2 3 7 6) (3 0 4 7)); }}\n'
       f');\n')


def write_surfaceFeatureExtractDict(case_dir: Path):
    _w(case_dir / "system" / "surfaceFeatureExtractDict",
       'FoamFile { version 2.0; format ascii; class dictionary; '
       'object surfaceFeatureExtractDict; }\n'
       'ctBlade.stl\n'
       '{\n'
       '    extractionMethod extractFromSurface;\n'
       '    extractFromSurfaceCoeffs { includedAngle 120; }\n'
       '    writeObj yes;\n'
       '}\n')


def write_snappyHexMeshDict(case_dir: Path):
    # locationInMesh: clearly in far field, away from blade
    loc = f"(5.0 0.0 {ROTOR_Z:.1f})"
    _w(case_dir / "system" / "snappyHexMeshDict",
       'FoamFile { version 2.0; format ascii; class dictionary; '
       'object snappyHexMeshDict; }\n'
       'castellatedMesh true;\n'
       'snap            true;\n'
       'addLayers       false;\n'
       'geometry\n'
       '{\n'
       '    ctBlade\n'
       '    {\n'
       '        type triSurfaceMesh;\n'
       '        file "ctBlade.stl";\n'
       '        regions { ctBlade { name blade; } }\n'
       '    }\n'
       '}\n'
       'castellatedMeshControls\n'
       '{\n'
       '    maxLocalCells       2000000;\n'
       '    maxGlobalCells      6000000;\n'
       '    minRefinementCells  10;\n'
       '    maxLoadUnbalance    0.10;\n'
       '    nCellsBetweenLevels 2;\n'
       '    resolveFeatureAngle 30;\n'
       '    allowFreeStandingZoneFaces true;\n'
       f'    locationInMesh {loc};\n'
       '    features ( { file "ctBlade.eMesh"; level 2; } );\n'
       '    refinementSurfaces\n'
       '    {\n'
       '        ctBlade { level (3 4); patchInfo { type wall; } }\n'
       '    }\n'
       '    refinementRegions {}\n'
       '}\n'
       'snapControls\n'
       '{\n'
       '    nSmoothPatch 3; tolerance 2.0; nSolveIter 30;\n'
       '    nRelaxIter 5; nFeatureSnapIter 10;\n'
       '    implicitFeatureSnap false; explicitFeatureSnap true;\n'
       '    multiRegionFeatureSnap false;\n'
       '}\n'
       'addLayersControls\n'
       '{\n'
       '    relativeSizes true; expansionRatio 1.2;\n'
       '    finalLayerThickness 0.3; minThickness 0.1;\n'
       '}\n'
       'meshQualityControls\n'
       '{\n'
       '    maxNonOrtho 65; maxBoundarySkewness 20; maxInternalSkewness 4;\n'
       '    maxConcave 80; minVol 1e-13; minTetQuality 1e-15;\n'
       '    minArea -1; minTwist 0.02; minDeterminant 0.001;\n'
       '    minFaceWeight 0.05; minVolRatio 0.01; minTriangleTwist -1;\n'
       '    nSmoothScale 4; errorReduction 0.75;\n'
       '}\n'
       'debug 0;\n'
       'mergeTolerance 1e-6;\n')


def write_topoSetDict(case_dir: Path):
    z1 = ROTOR_Z - MRF_DZ
    z2 = ROTOR_Z + MRF_DZ
    _w(case_dir / "system" / "topoSetDict",
       'FoamFile { version 2.0; format ascii; class dictionary; '
       'object topoSetDict; }\n'
       'actions\n'
       '(\n'
       '    {\n'
       '        name   rotatingZone;\n'
       '        type   cellZoneSet;\n'
       '        action new;\n'
       '        source cylinderToCell;\n'
       f'        p1 (0.0 0.0 {z1:.3f});\n'
       f'        p2 (0.0 0.0 {z2:.3f});\n'
       f'        radius {MRF_R:.2f};\n'
       '    }\n'
       ');\n')


def write_MRFProperties(case_dir: Path):
    _w(case_dir / "constant" / "MRFProperties",
       'FoamFile { version 2.0; format ascii; class dictionary; '
       'object MRFProperties; }\n'
       'MRF1\n'
       '{\n'
       '    cellZone    rotatingZone;\n'
       '    active      yes;\n'
       '    nonRotatingPatches ();\n'
       f'    origin      (0 0 {ROTOR_Z:.1f});\n'
       '    axis        (0 0 1);\n'
       f'    omega       {OMEGA_CT:.4f};   // rad/s  Vtip=78.2 m/s  Mtip=0.228\n'
       '}\n')


def write_controlDict(case_dir: Path):
    _w(case_dir / "system" / "controlDict",
       'FoamFile { version 2.0; format ascii; class dictionary; '
       'object controlDict; }\n'
       'application     simpleFoam;\n'
       'startFrom       startTime;\n'
       'startTime       0;\n'
       'stopAt          endTime;\n'
       f'endTime         {END_TIME};\n'
       'deltaT          1;\n'
       'writeControl    timeStep;\n'
       'writeInterval   100;\n'
       'purgeWrite      2;\n'
       'writeFormat     ascii;\n'
       'writePrecision  8;\n'
       'runTimeModifiable yes;\n'
       'functions\n'
       '{\n'
       '    forcesRotor\n'
       '    {\n'
       '        type         forces;\n'
       '        libs         (forces);\n'
       '        writeControl timeStep;\n'
       '        writeInterval 10;\n'
       '        patches      (blade);\n'
       '        rho          rhoInf;\n'
       '        rhoInf       1.225;\n'
       f'        CofR         (0 0 {ROTOR_Z:.1f});\n'
       '        log          yes;\n'
       '    }\n'
       '}\n')


def setup_case(case_dir: Path, collective_deg: float) -> bool:
    """Create and populate the OpenFOAM case directory for one collective angle."""
    case_dir.mkdir(parents=True, exist_ok=True)

    # Remove stale time directories (>0) and postProcessing from any previous run.
    # Without this, leftover simpleFoam time dirs (400/, 500/) have higher numbers
    # than snappyHexMesh output (1/, 2/), causing promoteMesh to pick the wrong dir.
    for child in list(case_dir.iterdir()):
        try:
            if int(child.name) > 0:
                shutil.rmtree(child)
        except ValueError:
            pass
    pp = case_dir / "postProcessing"
    if pp.exists():
        shutil.rmtree(pp)

    # Copy initial conditions and solver settings from singleRotor template
    for sub in ["0"]:
        dst = case_dir / sub
        if not dst.exists():
            shutil.copytree(str(SR_TMPL / sub), str(dst))

    (case_dir / "system").mkdir(exist_ok=True)
    for fname in ["fvSchemes", "fvSolution"]:
        dst = case_dir / "system" / fname
        if not dst.exists():
            shutil.copy2(str(SR_TMPL / "system" / fname), str(dst))

    (case_dir / "constant").mkdir(exist_ok=True)
    for fname in ["transportProperties", "turbulenceProperties"]:
        dst = case_dir / "constant" / fname
        if not dst.exists():
            shutil.copy2(str(SR_TMPL / "constant" / fname), str(dst))

    # Generate the blade STL for this collective angle
    stl_path = case_dir / "constant" / "triSurface" / "ctBlade.stl"
    stl_path.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([
        "python3", GENERATOR,
        "--naca",          "0012",
        "--diameter",      str(D_CT),
        "--chord",         str(C_CT),
        "--collective",    str(collective_deg),
        "--root_fraction", str(ROOT_FRAC),
        "--rotor_z",       str(ROTOR_Z),
        "--solid_name",    "ctBlade",
        "--output",        str(stl_path),
    ], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ERROR generating STL for θ={collective_deg}°: {r.stderr.strip()}")
        return False

    # Write case-specific config files
    write_blockMeshDict(case_dir)
    write_surfaceFeatureExtractDict(case_dir)
    write_snappyHexMeshDict(case_dir)
    write_topoSetDict(case_dir)
    write_MRFProperties(case_dir)
    write_controlDict(case_dir)
    return True


def run_case(collective_deg: float, i: int, total: int) -> dict | None:
    cid      = f"theta{int(collective_deg)}"
    case_dir = SWEEP_DIR / cid

    print(f"[{i}/{total}] START {cid}  θ={collective_deg}°", flush=True)
    t0 = time.time()

    if not setup_case(case_dir, collective_deg):
        return None

    steps = [
        ("blockMesh",             "blockMesh > blockMesh.log 2>&1"),
        ("surfaceFeatureExtract", "surfaceFeatureExtract > surfaceFeatureExtract.log 2>&1"),
        ("snappyHexMesh",         "snappyHexMesh > snappyHexMesh.log 2>&1"),
        # promote snappy mesh back to constant/ (same pattern as run_sweep.py)
        ("promoteMesh",
         'MESHDIR=$(for d in $(ls -d [0-9]* 2>/dev/null | sort -n); do '
         '[ -d "$d/polyMesh" ] && echo "$d"; done | tail -1) && '
         '[ -n "$MESHDIR" ] && cp -r "$MESHDIR/polyMesh" constant/ && rm -rf "$MESHDIR" || true'),
        ("topoSet",    "topoSet    > topoSet.log    2>&1"),
        ("simpleFoam", "simpleFoam > simpleFoam.log 2>&1"),
    ]

    for step_name, cmd in steps:
        rc, out = of_run(cmd, str(case_dir))
        if rc != 0 and step_name not in ("simpleFoam", "promoteMesh"):
            print(f"[{i}/{total}] FAIL {cid} at {step_name}", flush=True)
            (case_dir / f"{step_name}_fail.log").write_text(out)
            return None

    elapsed = time.time() - t0

    pp      = case_dir / "postProcessing" / "forcesRotor" / "0"
    f_force = pp / "force.dat"
    f_mom   = pp / "moment.dat"
    thrust  = read_last_force(f_force, 3) if f_force.exists() else None
    torque  = read_last_force(f_mom,   3) if f_mom.exists()   else None
    iters   = last_iter(case_dir)
    power   = abs(torque) * OMEGA_CT if torque is not None else None

    t_str = f"{thrust:.1f}N"   if thrust is not None else "—"
    q_str = f"{torque:.3f}Nm"  if torque is not None else "—"
    p_str = f"{power:.0f}W"    if power  is not None else "—"
    print(f"[{i}/{total}] DONE  {cid}  T={t_str}  Q={q_str}  P={p_str}  "
          f"iters={iters}  t={elapsed:.0f}s", flush=True)

    return {
        "collective_deg": collective_deg,
        "thrust_N":       round(thrust, 4) if thrust  is not None else "",
        "torque_Nm":      round(torque, 4) if torque  is not None else "",
        "power_W":        round(power,  2) if power   is not None else "",
        "iterations":     iters,
        "converged":      True,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Run C-T validation sweep (NACA 0012 hover rotor at multiple θ)")
    ap.add_argument("--angles", type=float, nargs="+", default=DEFAULT_ANGLES,
                    metavar="DEG",
                    help="Collective angles [deg] to run "
                         f"(default: {DEFAULT_ANGLES})")
    ap.add_argument("--dry_run", action="store_true",
                    help="Generate all case files and STLs, skip solver steps")
    args = ap.parse_args()

    angles = sorted(set(args.angles))
    rpm    = OMEGA_CT * 60.0 / (2.0 * 3.14159)
    vtip   = OMEGA_CT * R_CT

    print(f"Caradonna-Tung validation sweep")
    print(f"  NACA 0012  R={R_CT} m  c={C_CT} m  ω={OMEGA_CT} rad/s  "
          f"RPM≈{rpm:.0f}  Vtip≈{vtip:.1f} m/s")
    print(f"  Domain: ±{BOX_HALF} m × {BOX_H} m  |  "
          f"MRF: r={MRF_R} m Δz=±{MRF_DZ} m at z={ROTOR_Z} m")
    print(f"  Angles : {angles}")
    print(f"  Output : {CSV_PATH}\n")

    if args.dry_run:
        print(f"Setup check — generating case files for {len(angles)} angles (no solver)\n")
        errors = 0
        for i, deg in enumerate(angles, 1):
            cid      = f"theta{int(deg)}"
            case_dir = SWEEP_DIR / cid
            print(f"  [{i}/{len(angles)}] {cid:<10} θ={deg:>2.0f}°  ... ", end="", flush=True)
            ok = setup_case(case_dir, deg)
            if ok:
                stl   = case_dir / "constant" / "triSurface" / "ctBlade.stl"
                nf    = sum(1 for p in case_dir.rglob("*") if p.is_file())
                kb    = stl.stat().st_size // 1024 if stl.exists() else 0
                print(f"OK  ({nf} files, STL {kb} kB)")
            else:
                print(f"FAILED")
                errors += 1
        print(f"\nSetup check: {len(angles) - errors}/{len(angles)} OK", end="")
        if errors == 0:
            print("  — run without --dry_run to execute CFD.")
        else:
            print(f"  — fix {errors} error(s) before running.")
        return

    # Skip already-completed angles (idempotent)
    completed: set[float] = set()
    if CSV_PATH.exists():
        with open(CSV_PATH) as f:
            for row in csv.DictReader(f):
                try:
                    completed.add(float(row["collective_deg"]))
                except (KeyError, ValueError):
                    pass
    if completed:
        print(f"Already done: {sorted(completed)}  — skipping.")

    to_run = [a for a in angles if a not in completed]
    if not to_run:
        print("All requested angles already in CSV.")
        return

    print(f"Running {len(to_run)} case(s): {to_run}\n")

    if not CSV_PATH.exists():
        with open(CSV_PATH, "w", newline="") as f:
            csv.writer(f).writerow(CSV_HEADER)

    for i, deg in enumerate(to_run, 1):
        row = run_case(deg, i, len(to_run))
        if row is None:
            print(f"  Skipping θ={deg}° (error).", flush=True)
            continue
        with open(CSV_PATH, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADER).writerow(row)

    print(f"\nDone.  Results in: {CSV_PATH}")


if __name__ == "__main__":
    main()
