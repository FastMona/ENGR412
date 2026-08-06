"""
run_ct_sweep.py  —  ENGR412 Caradonna-Tung CFD validation sweep

Runs the OpenFOAM MRF/simpleFoam pipeline for the C-T hover rotor at
multiple collective pitch angles, collecting thrust and power per angle.

Blade     : NACA 0012, R=1.143 m, c=0.1905 m, 2 blades, untwisted/untapered
Condition : Mtip=0.228  →  Vtip≈78.2 m/s  →  ω≈68.07 rad/s  (~653 RPM)
Reference : Caradonna & Tung (1981), NASA TM-81232

Geometry presets (--geometry flag):
  full     (default) — 10D radial, 2.5D upstream / 10D downstream, MRF Δz=±1.257 m, n_pts=150
                       matches Jeon & Lee (Aerospace 2025, 12, 940) Appendix A
  reduced             — 5.25D radial, symmetric (5.25D each side), MRF Δz=±0.60 m, n_pts=50
                       original smaller domain for comparison

Pipeline per case: blockMesh → surfaceFeatureExtract → snappyHexMesh → topoSet → simpleFoam
Case dirs / CSV : default to /home/david/OpenFOAM/ENGR412/caradonnaTung/ when
  --sweep_dir/--csv are omitted (convenient for one-off checks); every named sweep
  in the top-level README.md and every dash.py menu path instead passes explicit
  --sweep_dir/--csv per geometry/RPM combination, e.g. caradonnaTung_full_650rpm/.

Angles run concurrently by default (--parallel, one process per angle via
ProcessPoolExecutor; each angle's simpleFoam is itself single-threaded, so this is
safe up to the physical core count -- see MAX_PARALLEL/DEFAULT_PARALLEL below).
Pass --parallel 1 for the old sequential behavior.

Usage:
  python3 cfd_scripts/run_ct_sweep.py                            # full 11-angle sweep (full geometry), default paths
  python3 cfd_scripts/run_ct_sweep.py --angles 5 8 12            # subset
  python3 cfd_scripts/run_ct_sweep.py --angles 5 8 12 --parallel 3  # subset, concurrently
  python3 cfd_scripts/run_ct_sweep.py --geometry reduced         # original smaller domain
  python3 cfd_scripts/run_ct_sweep.py --dry_run                  # preview, no CFD
"""

import argparse, csv, os, shutil, subprocess, sys, time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Force UTF-8 stdout/stderr — Windows consoles default to cp1252, which can't
# encode the ω/≈/θ/± characters used in the progress output below.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

# ── OpenFOAM paths ─────────────────────────────────────────────────────────────
OF_BASHRC  = "/usr/lib/openfoam/openfoam2412/etc/bashrc"
BASE_DIR   = Path("/home/david/OpenFOAM/ENGR412")
SWEEP_DIR  = BASE_DIR / "caradonnaTung"
SR_TMPL    = BASE_DIR / "singleRotor"      # source of generic 0/, fvSchemes, etc.
GENERATOR  = ("/mnt/c/Users/David/Documents_local/Repository_local"
              "/PythonProjects/ENGR412/cfd_scripts/generate_propeller.py")

# ── C-T rotor geometry ─────────────────────────────────────────────────────────
R_CT      = 1.143     # m  blade radius
D_CT      = 2.286     # m  diameter
C_CT      = 0.1905    # m  constant chord (untapered)
ROOT_FRAC = 0.20      # r_root / R  (blade starts at 20 % span)
OMEGA_CT  = 68.07     # rad/s  (Vtip=78.2 m/s at Mtip=0.228, ~653 RPM)
TI_PCT    = 5.0       # %  freestream turbulence intensity (k/omega and ReThetat all derive from this)

# ── Domain geometry (defaults = "full" preset; overridden by --geometry in main()) ──
ROTOR_Z   = 12.0        # m  rotor disk z-position (fixed, never changes)
# MRF cylinder: Jeon & Lee (Aerospace 2025, 12, 940) Appendix A specifies "1.1D in both
# the radial and axial directions" -- previously MRF_R was a hardcoded 1.40 m that didn't
# follow this rule (only MRF_DZ did); both are now derived from the same 0.55*D_CT = 1.1D/2
# convention so radial and axial MRF extent are consistent with each other.
MRF_R     = 0.55 * D_CT            # m  1.257 m
BOX_HALF  = 10.0 * D_CT            # m  22.860 m
# z-extent was backwards: thrust is measured +z (T~230N @ theta8), so by Newton's third
# law the wake is pushed toward -z. The short (2.5D) leg belongs on the +z entrainment
# side and the long (10D) leg on the -z wake/downstream side, not the reverse -- the
# reversed layout put the near boundary right in the developing wake's path, producing
# a large spurious pressure-driven thrust even at theta=0 (confirmed via a symmetric-domain
# diagnostic run that collapsed the spurious thrust from ~37N to <1N).
BOX_ZMIN  = ROTOR_Z - 10.0 * D_CT # m -10.860 m  (wake/downstream side, long leg)
BOX_ZMAX  = ROTOR_Z + 2.5 * D_CT  # m  17.715 m  (entrainment/upstream side, short leg)
MRF_DZ    = 1.257                  # m  half-height — Appendix A: 1.1D/2 = 1.257 m
N_PTS_STL = 150                    # chordwise STL points (150 → ~1.3 mm facets at c=0.1905 m)
NX        = 114                    # blockMesh cells in x and y
NZ        = 96                     # blockMesh cells in z
# snappyHexMesh near-blade refinementSurfaces/feature level (min, max). Background cell
# is BOX_HALF*2/NX =~ 0.4 m, so level 6 -> ~6.25 mm near-wall cells vs. the ~1.3 mm STL
# facets from N_PTS_STL=150 -- volume mesh may be under-resolving the input geometry.
BLADE_LEVEL = (5, 6)   # overridable via --blade_level for a GCI mesh-convergence study
N_SURFACE_LAYERS = 7   # overridable via --layers -- was 5; bumped alongside the MEDIAL_RATIO
                        # tightening below so the (now thinner) prism stack still has enough
                        # layers to grow smoothly out to the background cell size instead of
                        # jumping in fewer, larger steps. Jeon & Lee use 25 graded layers, but
                        # that assumes a low-Re wall treatment; this setup uses
                        # kqRWallFunction/omegaWallFunction (log-law wall functions,
                        # valid ~30<y+<300), so matching 25 layers is not automatically
                        # the right target -- see analysis/ note on wall treatment.
MEDIAL_RATIO = 0.15     # overridable via --medial_ratio -- was 0.3 (measured y+ avg=228.5,
                        # max=1231 at that value). This is the actual binding clamp on
                        # first-layer thickness, not firstLayerThickness itself (retuning
                        # firstLayerThickness alone was a dead end -- see session log).
                        # Halved as a "go part way" step: pulls y+ down within the existing
                        # log-law wall-function regime (target: max y+ inside ~30-300,
                        # not the full y+~1-2 rebuild, which needs ~4 micron absolute
                        # first-layer thickness and 20+ layers and was deferred).
N_GROW = 0              # overridable via --n_grow -- DEAD END, tested 2026-07-30, reverted
                        # to the original 0. Hypothesis was that nGrow=1 would close the
                        # LE/root/tip zero-prism-layer coverage gap documented in
                        # analysis/structured_mesh_followup_2026-07-14.md without touching
                        # anything else (--blade_level/--layers/--medial_ratio all held at
                        # their existing values, isolated single-variable test, full
                        # geometry, 1250 rpm, theta=5/8/12 rerun from scratch).
                        # RESULT: made it worse, not better. Mean |CT error| across the 3
                        # angles went 50.0% -> 61.3% (5 deg: 122.0%->146.8%, 8 deg:
                        # 22.8%->33.1%, 12 deg: only 5.1%->3.9% improved). Every angle here
                        # already overpredicts CT; nGrow=1 grows the boundary layer into
                        # the previously-unlayered LE/root/tip cells, adding near-wall
                        # resolution/volume exactly where thrust was already too high,
                        # pushing the overprediction further in 2 of 3 cases rather than
                        # correcting it. Do not re-enable without a different, more
                        # targeted approach (e.g. a --n_grow value other than 1, or a
                        # refinementRegion scoped to just LE/root/tip instead of a global
                        # addLayersControls setting) -- and re-test all 3 angles again
                        # before trusting a single-angle spot check.

# ── Wake / tip-vortex refinement cylinder (independent of --geometry preset) ──
# Direction was backwards (same bug as the BOX_ZMIN/ZMAX fix above): thrust is +z, so the
# wake is pushed toward -z, not +z. WAKE_ZSTART already sat on the correct (-z) MRF face;
# only WAKE_ZEND needs to extend further in -z (was extending into the +z entrainment
# side instead, refining the wrong side of the rotor).
WAKE_R      = 1.2 * R_CT            # m  1.372 m — tip radius + margin for wake contraction
WAKE_ZSTART = ROTOR_Z - MRF_DZ      # m  starts at the MRF zone's downstream (-z) face
WAKE_ZEND   = ROTOR_Z - 3.0 * D_CT  # m  3 diameters downstream (-z) — near-wake / tip-vortex region
WAKE_LEVEL  = 2                     # background(0.4 m)/2^2 = 100 mm cells in the wake cylinder

# ── Geometry presets (applied at runtime by --geometry flag) ──────────────────
_GEOM = {
    "reduced": dict(
        box_half = 12.0,
        box_zmin = ROTOR_Z - 12.0,   # 0.0 m  (5.25D each side)
        box_zmax = ROTOR_Z + 12.0,   # 24.0 m
        mrf_dz   = 0.60,
        n_pts    = 50,
        nx = 60, nz = 80,
        desc = "Reduced: ±12 m (5.25D) radial, z=0–24 m, MRF Δz=±0.60 m, n_pts=50",
    ),
    "full": dict(
        box_half = 10.0 * D_CT,              # 22.860 m
        box_zmin = ROTOR_Z - 10.0 * D_CT,   # -10.860 m  (wake/downstream, long leg)
        box_zmax = ROTOR_Z + 2.5 * D_CT,    #  17.715 m  (entrainment/upstream, short leg)
        mrf_dz   = 1.257,
        n_pts    = 150,
        nx = 114, nz = 96,
        desc = "Full:    ±22.86 m (10D) radial, z=-10.860–17.715 m, 2.5D up(+z)/10D down(-z), MRF Δz=±1.257 m, n_pts=150",
    ),
}

# ── Sweep defaults ─────────────────────────────────────────────────────────────
DEFAULT_ANGLES = [0, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12]
# Was 1000 -- force-history inspection this session showed several cases (e.g. the
# reduced-preset theta0 case) still slowly settling at t=1000, only truly plateauing
# around t~1800. Bumped to give more room; paired with stopAt convergence below so
# cases that genuinely converge early still stop early.
END_TIME       = 2000
CSV_PATH       = SWEEP_DIR / "ct_results.csv"
CSV_HEADER     = ["collective_deg", "rpm", "geometry", "thrust_N", "torque_Nm",
                  "power_W", "iterations", "converged"]

# ── Parallel worker count ──────────────────────────────────────────────────────
# Each case runs simpleFoam undecomposed (single-threaded, no mpirun/decomposePar --
# see --parallel's help text), so concurrent *cases* via ProcessPoolExecutor is what
# actually uses multiple cores here, not MPI ranks within one case. Target machine
# has 24 cores / 48 threads. Hard-capped at 30, not 48: leaves headroom for the OS/
# WSL overhead and whatever else is running, rather than saturating every hyperthread.
# Unlike the other CLI overrides in this file, this DOES change default behavior
# (previously --parallel defaulted to 1, i.e. sequential) -- deliberate, per request,
# not an oversight.
MAX_PARALLEL     = 30
DEFAULT_PARALLEL = min(MAX_PARALLEL, os.cpu_count() or 1)


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


def force_converged(dat_path: Path, col: int = 3,
                     tail_frac: float = 0.2, tol: float = 0.02,
                     min_points: int = 5, collective_deg: float | None = None) -> bool:
    """
    Whether a force.dat time-history column has actually stabilized, checked over
    the last tail_frac of recorded points (std / mean|value| <= tol). Reading only
    the final iteration is unreliable for these MRF hover cases: some plateau at a
    stable (even if wrong) value quickly, others are still slowly settling at
    end-of-run (e.g. the reduced-preset theta0 case needed ~1800 iterations to
    truly plateau, well past the old 1000-iteration cutoff).
    """
    if not dat_path.exists():
        return False
    vals = []
    with open(dat_path) as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#") and not s.startswith("/"):
                try:
                    vals.append(float(s.split()[col]))
                except (ValueError, IndexError):
                    pass
    if len(vals) < min_points:
        return False
    n    = max(min_points, int(len(vals) * tail_frac))
    tail = vals[-n:]
    mean_abs = sum(abs(v) for v in tail) / len(tail)
    if mean_abs < 1e-6:
        # CAVEAT: only theta=0 gets a free pass here. A near-zero tail at any
        # other angle is more likely a degenerate/non-physical signal (e.g. an
        # unresolved thin blade) than genuine convergence, so it is flagged
        # NOT CONVERGED for manual review rather than silently passing.
        if collective_deg == 0:
            return True   # physically expected zero thrust at theta=0
        return False
    mean_val = sum(tail) / len(tail)
    std = (sum((v - mean_val) ** 2 for v in tail) / len(tail)) ** 0.5
    return (std / mean_abs) <= tol


def migrate_csv_header(csv_path: Path, rpm: float, geometry: str) -> None:
    """
    Backfill rpm/geometry onto a pre-fix CSV (old 6-column header, no rpm/geometry
    columns) so it matches the current CSV_HEADER before anything gets appended to
    it. Without this, DictWriter.writerow() with the new 8-column fieldnames against
    a file whose on-disk header is still the old 6 columns silently shifts every
    field in the newly-appended rows by two columns on the next read (reproduced
    directly: thrust_N ends up holding the rpm value, torque_Nm holds the geometry
    string, etc.) -- not a hypothetical, this is what happens.

    Assumption: every row in an existing CSV belongs to the *same* (rpm, geometry)
    combination as the current run. True in practice for every CSV this pipeline
    actually produces -- each --sweep_dir/--csv pair (in dash.py and this file's own
    docstring examples) is dedicated to one RPM/geometry combination by convention,
    never mixed -- but this function has no way to verify that from the file alone,
    so it's trusting the convention, not re-deriving it.
    """
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        old_header = reader.fieldnames
        old_rows = list(reader)

    if old_header == CSV_HEADER:
        return  # already current, nothing to do

    print(f"Migrating {csv_path}: old header {old_header} -> {CSV_HEADER} "
          f"({len(old_rows)} row(s), backfilling rpm={round(rpm, 2)} "
          f"geometry={geometry!r} on all of them).")

    migrated = []
    for row in old_rows:
        new_row = dict(row)
        new_row["rpm"] = round(rpm, 2)
        new_row["geometry"] = geometry
        migrated.append(new_row)

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerows(migrated)


# ── OpenFOAM file generators ───────────────────────────────────────────────────
def _w(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def write_blockMeshDict(case_dir: Path):
    b, zlo, zhi = BOX_HALF, BOX_ZMIN, BOX_ZMAX
    _w(case_dir / "system" / "blockMeshDict",
       f'FoamFile {{ version 2.0; format ascii; class dictionary; object blockMeshDict; }}\n'
       f'scale 1.0;\n'
       f'// Domain: ±{b:.3f} m radial, z={zlo:.3f}–{zhi:.3f} m  |  '
       f'rotor at z={ROTOR_Z} m  |  cells ({NX}×{NX}×{NZ})\n'
       f'vertices\n(\n'
       f'    ({-b:.3f} {-b:.3f} {zlo:.3f})   // 0\n'
       f'    ( {b:.3f} {-b:.3f} {zlo:.3f})   // 1\n'
       f'    ( {b:.3f}  {b:.3f} {zlo:.3f})   // 2\n'
       f'    ({-b:.3f}  {b:.3f} {zlo:.3f})   // 3\n'
       f'    ({-b:.3f} {-b:.3f} {zhi:.3f})   // 4\n'
       f'    ( {b:.3f} {-b:.3f} {zhi:.3f})   // 5\n'
       f'    ( {b:.3f}  {b:.3f} {zhi:.3f})   // 6\n'
       f'    ({-b:.3f}  {b:.3f} {zhi:.3f})   // 7\n'
       f');\n'
       f'blocks ( hex (0 1 2 3 4 5 6 7) ({NX} {NX} {NZ}) simpleGrading (1 1 1) );\n'
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
       'addLayers       true;\n'
       'geometry\n'
       '{\n'
       '    ctBlade\n'
       '    {\n'
       '        type triSurfaceMesh;\n'
       '        file "ctBlade.stl";\n'
       '        regions { ctBlade { name blade; } }\n'
       '    }\n'
       '    wakeZone\n'
       '    {\n'
       '        type searchableCylinder;\n'
       f'        point1 (0 0 {WAKE_ZSTART:.3f});\n'
       f'        point2 (0 0 {WAKE_ZEND:.3f});\n'
       f'        radius {WAKE_R:.3f};\n'
       '    }\n'
       '}\n'
       'castellatedMeshControls\n'
       '{\n'
       '    maxLocalCells       6000000;\n'
       '    maxGlobalCells      20000000;\n'
       '    minRefinementCells  10;\n'
       '    maxLoadUnbalance    0.10;\n'
       '    nCellsBetweenLevels 2;\n'
       '    resolveFeatureAngle 30;\n'
       '    allowFreeStandingZoneFaces true;\n'
       f'    locationInMesh {loc};\n'
       f'    features ( {{ file "ctBlade.eMesh"; level {BLADE_LEVEL[1]}; }} );\n'
       '    refinementSurfaces\n'
       '    {\n'
       '        ctBlade\n'
       '        {\n'
       f'            level ({BLADE_LEVEL[0]} {BLADE_LEVEL[1]});\n'
       '            regions\n'
       '            {\n'
       f'                ctBlade {{ level ({BLADE_LEVEL[0]} {BLADE_LEVEL[1]}); patchInfo {{ type wall; }} }}\n'
       '            }\n'
       '        }\n'
       '    }\n'
       '    refinementRegions\n'
       '    {\n'
       f'        wakeZone {{ mode inside; levels ((1e15 {WAKE_LEVEL})); }}\n'
       '    }\n'
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
       '    // firstLayerThickness is NOT the controlling parameter here: tested 0.015 vs 0.00657\n'
       '    // (2.3x smaller) on theta8 and got bit-identical near-wall cell heights and y+\n'
       '    // (avg 228.5, max 1231 both times) -- maxThicknessToMedialRatio 0.3 is clamping the\n'
       '    // achievable thickness to the local medial-axis distance on this thin/curved airfoil,\n'
       '    // regardless of the nominal request. Left at the original value; the y+~228 average\n'
       '    // is a property of the current surface refinement level, not this setting.\n'
       '    relativeSizes         true;\n'
       '    firstLayerThickness   0.015;\n'
       '    expansionRatio        1.25;\n'
       '    minThickness          0.001;\n'
       '    featureAngle          60;\n'
       '    slipFeatureAngle      30;\n'
       '    nRelaxIter            5;\n'
       '    nSmoothSurfaceNormals 1;\n'
       '    nSmoothNormals        3;\n'
       '    nSmoothThickness      10;\n'
       '    maxFaceThicknessRatio 0.5;\n'
       f'    maxThicknessToMedialRatio {MEDIAL_RATIO};\n'
       '    minMedialAxisAngle    90;\n'
       f'    nGrow                 {N_GROW};\n'
       '    nBufferCellsNoExtrude 0;\n'
       '    nLayerIter            50;\n'
       '    nRelaxedIter          20;\n'
       '    layers\n'
       '    {\n'
       f'        blade {{ nSurfaceLayers {N_SURFACE_LAYERS}; }}\n'
       '    }\n'
       '}\n'
       'meshQualityControls\n'
       '{\n'
       '    maxNonOrtho 65; maxBoundarySkewness 20; maxInternalSkewness 4;\n'
       '    maxConcave 80; minVol 1e-13; minTetQuality 1e-15;\n'
       '    minArea -1; minTwist 0.02; minDeterminant 0.001;\n'
       '    minFaceWeight 0.05; minVolRatio 0.01; minTriangleTwist -1;\n'
       '    nSmoothScale 4; errorReduction 0.75;\n'
       '    // addLayersControls.nRelaxedIter falls back to this sub-dict once layer\n'
       '    // addition passes that many iterations without meeting the strict criteria\n'
       '    // above -- was missing entirely, which was harmless under the old, looser\n'
       '    // medial_ratio/layer count (layer addition always converged before iteration\n'
       '    // 20) but is a hard FOAM FATAL IO ERROR now that the tighter mesh genuinely\n'
       '    // needs the relaxed fallback. Standard OpenFOAM tutorial values.\n'
       '    relaxed\n'
       '    {\n'
       '        maxNonOrtho 75;\n'
       '        minTetQuality -1e30;\n'
       '    }\n'
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
    vtip = OMEGA_CT * R_CT
    mtip = vtip / 340.0
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
       f'    omega       {OMEGA_CT:.4f};   // rad/s  Vtip={vtip:.2f} m/s  Mtip={mtip:.3f}\n'
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
       '    yPlus\n'
       '    {\n'
       '        type         yPlus;\n'
       '        libs         (fieldFunctionObjects);\n'
       '        writeControl writeTime;\n'
       '        log          yes;\n'
       '    }\n'
       '    bladeSurface\n'
       '    {\n'
       '        type            surfaces;\n'
       '        libs            (sampling);\n'
       '        writeControl    onEnd;\n'
       '        fields          (p);\n'
       '        surfaceFormat   raw;\n'
       '        surfaces\n'
       '        {\n'
       '            blade\n'
       '            {\n'
       '                type    patch;\n'
       '                patches (blade);\n'
       '            }\n'
       '        }\n'
       '    }\n'
       '}\n')


def write_k(case_dir: Path):
    """Write 0/k — TKE at TI_PCT% TI scaled to current Vtip (nu_t = k/om = 0.04 m^2/s)."""
    vtip = OMEGA_CT * R_CT
    k    = round(1.5 * (TI_PCT / 100.0 * vtip) ** 2, 1)
    _w(case_dir / "0" / "k",
       'FoamFile { version 2.0; format ascii; class volScalarField; object k; }\n'
       'dimensions      [0 2 -2 0 0 0 0];\n'
       f'internalField   uniform {k};\n'
       'boundaryField\n{\n'
       f'    inlet   {{ type fixedValue;      value uniform {k}; }}\n'
       '    outlet  { type zeroGradient; }\n'
       f'    sides   {{ type fixedValue;      value uniform {k}; }}\n'
       f'    blade   {{ type kqRWallFunction; value uniform {k}; }}\n'
       '}\n')


def write_omega(case_dir: Path):
    """Write 0/omega — specific dissipation rate (nu_t = k/om = 0.04 m^2/s)."""
    vtip = OMEGA_CT * R_CT
    k    = round(1.5 * (TI_PCT / 100.0 * vtip) ** 2, 1)
    om   = round(k / 0.04)   # s^-1
    _w(case_dir / "0" / "omega",
       'FoamFile { version 2.0; format ascii; class volScalarField; object omega; }\n'
       'dimensions      [0 0 -1 0 0 0 0];\n'
       f'internalField   uniform {om};\n'
       'boundaryField\n{\n'
       f'    inlet   {{ type fixedValue;        value uniform {om}; }}\n'
       '    outlet  { type zeroGradient; }\n'
       f'    sides   {{ type fixedValue;        value uniform {om}; }}\n'
       f'    blade   {{ type omegaWallFunction; value uniform {om}; }}\n'
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
        "--n_pts",         str(N_PTS_STL),
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
    write_k(case_dir)
    write_omega(case_dir)
    return True


def run_case(collective_deg: float, i: int, total: int, rpm: float, geometry: str) -> dict | None:
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
            tail = out.strip().splitlines()
            for line in tail[-40:]:
                print(f"    | {line}", flush=True)
            return None

        # After promoteMesh: verify the blade patch was created by snappyHexMesh
        if step_name == "promoteMesh":
            boundary = case_dir / "constant" / "polyMesh" / "boundary"
            if boundary.exists() and "blade" not in boundary.read_text():
                print(f"[{i}/{total}] FAIL {cid}: 'blade' patch missing from mesh "
                      f"— snappyHexMesh completed but did not snap to the STL surface.",
                      flush=True)
                snappy_log = case_dir / "snappyHexMesh.log"
                if snappy_log.exists():
                    tail = snappy_log.read_text(errors="replace").splitlines()
                    print(f"    snappyHexMesh.log (last 30 lines):", flush=True)
                    for line in tail[-30:]:
                        print(f"    | {line}", flush=True)
                return None

    elapsed = time.time() - t0

    # If simpleFoam ran 0 iterations, print its log to surface the error
    iters = last_iter(case_dir)
    if iters == 0:
        sflog = case_dir / "simpleFoam.log"
        if sflog.exists():
            tail = sflog.read_text(errors="replace").splitlines()
            print(f"[{i}/{total}] WARN {cid}: simpleFoam ran 0 iters — log tail:",
                  flush=True)
            for line in tail[-30:]:
                print(f"    | {line}", flush=True)
        else:
            print(f"[{i}/{total}] WARN {cid}: simpleFoam.log not found", flush=True)

    pp      = case_dir / "postProcessing" / "forcesRotor" / "0"
    f_force = pp / "force.dat"
    f_mom   = pp / "moment.dat"
    thrust    = read_last_force(f_force, 3) if f_force.exists() else None
    torque    = read_last_force(f_mom,   3) if f_mom.exists()   else None
    power     = abs(torque) * OMEGA_CT if torque is not None else None
    converged = force_converged(f_force, 3, collective_deg=collective_deg) if f_force.exists() else False

    t_str = f"{thrust:.1f}N"   if thrust is not None else "—"
    q_str = f"{torque:.3f}Nm"  if torque is not None else "—"
    p_str = f"{power:.0f}W"    if power  is not None else "—"
    conv_flag = "" if converged else "  [NOT CONVERGED]"
    print(f"[{i}/{total}] DONE  {cid}  T={t_str}  Q={q_str}  P={p_str}  "
          f"iters={iters}  t={elapsed:.0f}s{conv_flag}", flush=True)

    return {
        "collective_deg": collective_deg,
        "rpm":            round(rpm, 2),
        "geometry":       geometry,
        "thrust_N":       round(thrust, 4) if thrust  is not None else "",
        "torque_Nm":      round(torque, 4) if torque  is not None else "",
        "power_W":        round(power,  2) if power   is not None else "",
        "iterations":     iters,
        "converged":      converged,
    }


def main():
    global OMEGA_CT, CSV_PATH, SWEEP_DIR, BOX_HALF, BOX_ZMIN, BOX_ZMAX, MRF_DZ, N_PTS_STL, NX, NZ
    global BLADE_LEVEL, N_SURFACE_LAYERS, MEDIAL_RATIO, N_GROW
    ap = argparse.ArgumentParser(
        description="Run C-T validation sweep (NACA 0012 hover rotor at multiple θ)")
    ap.add_argument("--angles", type=float, nargs="+", default=DEFAULT_ANGLES,
                    metavar="DEG",
                    help="Collective angles [deg] to run "
                         f"(default: {DEFAULT_ANGLES})")
    ap.add_argument("--dry_run", action="store_true",
                    help="Generate all case files and STLs, skip solver steps")
    ap.add_argument("--rpm", type=float, default=None,
                    metavar="RPM",
                    help="Override rotor RPM (default: ~653, Mtip=0.228)")
    ap.add_argument("--csv", type=str, default=None,
                    metavar="PATH",
                    help="Output CSV path (default: SWEEP_DIR/ct_results.csv)")
    ap.add_argument("--sweep_dir", type=str, default=None,
                    metavar="DIR",
                    help="Override case output directory (default: caradonnaTung/)")
    ap.add_argument("--geometry", choices=["reduced", "full"], default="full",
                    help="Domain/MRF/STL preset — 'full': Appendix A (10D, MRF ±1.257 m, n_pts=150); "
                         "'reduced': original (5.25D, MRF ±0.60 m, n_pts=50)  (default: full)")
    ap.add_argument("--blade_level", type=int, nargs=2, default=None, metavar=("MIN", "MAX"),
                    help="Override snappyHexMesh blade refinementSurfaces/feature level "
                         f"(default: {BLADE_LEVEL}). Use with --csv/--sweep_dir to run a "
                         "GCI mesh-convergence study at fixed angle(s) across resolutions.")
    ap.add_argument("--layers", type=int, default=None, metavar="N",
                    help=f"Override nSurfaceLayers on the blade patch (default: {N_SURFACE_LAYERS})")
    ap.add_argument("--medial_ratio", type=float, default=None, metavar="RATIO",
                    help="Override addLayers maxThicknessToMedialRatio "
                         f"(default: {MEDIAL_RATIO}); this is what actually clamps first-layer "
                         "thickness, not firstLayerThickness itself")
    ap.add_argument("--n_grow", type=int, default=None, metavar="N",
                    help="Override addLayersControls.nGrow "
                         f"(default: {N_GROW}). Targets the LE/root/tip zero-layer "
                         "coverage gap in analysis/structured_mesh_followup_2026-07-14.md "
                         "-- --n_grow 1 was tested 2026-07-30 (full/1250rpm/theta 5,8,12) "
                         "and made mean |CT error| worse (50.0%%->61.3%%), reverted. Left "
                         "as an override for future experiments, not recommended as-is.")
    ap.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL, metavar="N",
                    help="Run N angles concurrently via ProcessPoolExecutor "
                         f"(default: {DEFAULT_PARALLEL}, from min({MAX_PARALLEL}, "
                         "os.cpu_count())). Each case itself is single-threaded "
                         "(simpleFoam runs undecomposed, no mpirun/decomposePar), so this "
                         "is safe up to the number of physical cores available -- not a "
                         f"WSL limitation. Hard-capped at {MAX_PARALLEL} regardless of "
                         "what's requested (--parallel 1 for the old sequential "
                         "behavior).")
    args = ap.parse_args()

    if args.parallel > MAX_PARALLEL:
        print(f"  Note: --parallel {args.parallel} exceeds the hard cap of "
              f"{MAX_PARALLEL}; clamping to {MAX_PARALLEL}.")
        args.parallel = MAX_PARALLEL

    # ── Runtime overrides ─────────────────────────────────────────────────────
    g = _GEOM[args.geometry]
    BOX_HALF, BOX_ZMIN, BOX_ZMAX = g["box_half"], g["box_zmin"], g["box_zmax"]
    MRF_DZ    = g["mrf_dz"]
    N_PTS_STL = g["n_pts"]
    NX, NZ    = g["nx"], g["nz"]

    if args.rpm is not None:
        OMEGA_CT = args.rpm * 2.0 * 3.14159 / 60.0
    if args.sweep_dir is not None:
        SWEEP_DIR = Path(args.sweep_dir)
        SWEEP_DIR.mkdir(parents=True, exist_ok=True)
        CSV_PATH = SWEEP_DIR / "ct_results.csv"
    if args.csv is not None:
        CSV_PATH = Path(args.csv)
    if args.blade_level is not None:
        BLADE_LEVEL = tuple(args.blade_level)
    if args.layers is not None:
        N_SURFACE_LAYERS = args.layers
    if args.medial_ratio is not None:
        MEDIAL_RATIO = args.medial_ratio
    if args.n_grow is not None:
        N_GROW = args.n_grow

    # Ensure the output directory exists -- the --sweep_dir branch above does its own
    # mkdir, but the default SWEEP_DIR (BASE_DIR/"caradonnaTung") was never created
    # anywhere, so a plain run with no --sweep_dir override crashed on CSV_PATH.open("w").
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)

    angles = sorted(set(args.angles))
    rpm    = OMEGA_CT * 60.0 / (2.0 * 3.14159)
    vtip   = OMEGA_CT * R_CT

    print(f"Caradonna-Tung validation sweep")
    print(f"  NACA 0012  R={R_CT} m  c={C_CT} m  ω={OMEGA_CT:.4f} rad/s  "
          f"RPM≈{rpm:.0f}  Vtip≈{vtip:.1f} m/s")
    print(f"  Geometry [{args.geometry}]: {g['desc']}")
    print(f"  MRF zone: r={MRF_R} m  Δz=±{MRF_DZ} m  (z={ROTOR_Z-MRF_DZ:.3f}–{ROTOR_Z+MRF_DZ:.3f} m)")
    print(f"  Mesh    : blade_level={BLADE_LEVEL}  nSurfaceLayers={N_SURFACE_LAYERS}  "
          f"medial_ratio={MEDIAL_RATIO}  n_grow={N_GROW}")
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

    # Skip already-completed (angle, rpm, geometry) combos (idempotent).
    # Old-format CSVs (no rpm/geometry columns) are migrated in place first --
    # see migrate_csv_header() -- so both this read and any later append use a
    # consistent 8-column header throughout.
    if CSV_PATH.exists():
        migrate_csv_header(CSV_PATH, rpm, args.geometry)

    completed: set[tuple[float, float, str]] = set()
    if CSV_PATH.exists():
        with open(CSV_PATH) as f:
            for row in csv.DictReader(f):
                try:
                    completed.add((
                        float(row["collective_deg"]),
                        round(float(row["rpm"]), 2),
                        row["geometry"],
                    ))
                except (KeyError, ValueError):
                    pass
    if completed:
        print(f"Already done: {sorted(completed)}  — skipping.")

    to_run = [a for a in angles if (a, round(rpm, 2), args.geometry) not in completed]
    if not to_run:
        print("All requested angles already in CSV.")
        return

    print(f"Running {len(to_run)} case(s): {to_run}\n")

    if not CSV_PATH.exists():
        with open(CSV_PATH, "w", newline="") as f:
            csv.writer(f).writerow(CSV_HEADER)

    def _append(row):
        with open(CSV_PATH, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADER).writerow(row)

    if args.parallel <= 1:
        for i, deg in enumerate(to_run, 1):
            row = run_case(deg, i, len(to_run), rpm, args.geometry)
            if row is None:
                print(f"  Skipping θ={deg}° (error).", flush=True)
                continue
            _append(row)
    else:
        print(f"  (running {args.parallel} case(s) concurrently)\n", flush=True)
        with ProcessPoolExecutor(max_workers=args.parallel) as pool:
            futures = {
                pool.submit(run_case, deg, i, len(to_run), rpm, args.geometry): deg
                for i, deg in enumerate(to_run, 1)
            }
            for fut in as_completed(futures):
                deg = futures[fut]
                row = fut.result()
                if row is None:
                    print(f"  Skipping θ={deg}° (error).", flush=True)
                    continue
                _append(row)

    print(f"\nDone.  Results in: {CSV_PATH}")


if __name__ == "__main__":
    main()
