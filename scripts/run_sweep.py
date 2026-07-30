"""
run_sweep.py — ENGR412 parametric sweep (single-rotor, co-rotating)

Datasets
  single  : 1 rotor, varies RPM only (5 cases, ~6 min @ --parallel 5)
  co_rot  : 2 co-rotating rotors, same pitch (140 cases, ~25 min @ --parallel 12)
            spacing × azimuth × rpm_lower = 4 × 7 × 5
            Both rotors NACA 4412, same pitch (0.4 m), CCW.

Output folders (all under /home/david/OpenFOAM/ENGR412/):
  1_single_rotor_sweep/   ← single dataset
  2_co_rot_sweep/         ← co_rot dataset

Design-space RPM grids are now derived from tip Mach number (M_tip), not
hardcoded RPM lists (2026-07-16) -- see rpm_from_mtip()/mtip_from_rpm() and the
M_TIP_GRID_* constants below. DIAMETER is a CFD variable (this project is
computational-only, no physical build); every other geometric constant --
hub-depth spacing floor, MRF zone radius/half-height, RPM grids -- is now
expressed relative to DIAMETER so changing it rescales the whole design space
consistently instead of needing every constant hand-recalculated.

Usage
  python3 run_sweep.py --dataset single  --parallel 12
  python3 run_sweep.py --dataset co_rot  --parallel 12
  python3 run_sweep.py --dataset single  --dry_run
"""

import argparse
import itertools
import math
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
}

# ── Fixed parameters ──────────────────────────────────────────────────────────
DIAMETER     = 1.0    # rotor diameter [m] -- a CFD variable, not tied to any
                       # physical build (this project is computational-only).
                       # D=1.0 was chosen for Caradonna-Tung-comparable CT
                       # validation. Every other geometric/RPM constant below is
                       # now expressed relative to this one number (see
                       # rpm_from_mtip()/mtip_from_rpm() and the M_TIP-based
                       # design-space grids, plus MRF_RADIUS/MRF_DZ_ABS_CAP
                       # further down) so changing D rescales the whole sweep
                       # consistently instead of needing every RPM/spacing/MRF
                       # constant hand-recalculated.
UPPER_Z      = 5.0    # upper rotor disk height [m] -- domain placement; not yet
                       # made D-relative (would also need the blockMeshDict
                       # domain-sizing templates reworked -- flagged, out of
                       # scope for this pass).
RPM_UPPER    = 900.0  # upper rotor RPM (fixed) -- legacy fallback default only,
                       # kept as a literal (not M_tip-derived) so the existing
                       # single-value case_id format is untouched; production
                       # runs always override this via --rpm_upper.
PITCH_UPPER  = 0.4    # upper rotor pitch [m] (fixed)

# ── Tip-Mach-based RPM design space (2026-07-16) ───────────────────────────────
# Raw RPM is meaningless without knowing the rotor size it goes with -- a
# helicopter runs low RPM because its rotor is huge, a hobby-drone prop runs
# high RPM because it's tiny. What actually matters aerodynamically (and for
# keeping simpleFoam's incompressible-flow assumption valid) is tip speed / tip
# Mach number. M_TIP_CEILING is a conservative ceiling for an incompressible
# solver -- compressibility effects become significant well before M=1, 0.30
# keeps real margin. Design-space RPM grids below are defined in M_tip and
# converted via rpm_from_mtip() so that changing DIAMETER automatically
# produces a physically-equivalent RPM range instead of the RPM lists needing
# to be hand-recalculated for whatever rotor size is being explored.
SPEED_OF_SOUND = 343.0   # [m/s], sea level ~20 degC
M_TIP_CEILING  = 0.30    # conservative incompressible-flow ceiling (see above)


def rpm_from_mtip(m_tip: float, diameter: float = DIAMETER) -> float:
    """RPM giving tip Mach number m_tip for a rotor of the given diameter
    (defaults to DIAMETER). V_tip = m_tip * speed_of_sound = Omega * R."""
    v_tip = m_tip * SPEED_OF_SOUND
    omega = v_tip / (diameter / 2.0)
    return omega * 60.0 / (2.0 * math.pi)


def mtip_from_rpm(rpm: float, diameter: float = DIAMETER) -> float:
    """Inverse of rpm_from_mtip() -- tip Mach number for a given RPM/diameter."""
    omega = rpm * 2.0 * math.pi / 60.0
    v_tip = omega * (diameter / 2.0)
    return v_tip / SPEED_OF_SOUND


# ── Physical spacing floor (2026-07-15) ────────────────────────────────────────
# The whole CFD pipeline assumes rigid, non-deflecting blades (no aeroelastic
# deformation under load) and incompressible flow. Under the rigid-blade
# assumption, the hard physical constraint on how close the two rotor planes can
# get isn't blade clearance -- it's the hub, the thickest rigid part of the
# assembly. Given hub depth = 0.03 * D (project owner's spec), the two hubs
# would physically collide below spacing = one full hub depth (each hub occupies
# its own full thickness at its own rotor plane, not half of it).
HUB_DEPTH_FRAC       = 0.03                        # hub axial depth as a fraction of D
HUB_DEPTH            = HUB_DEPTH_FRAC * DIAMETER   # [m]
MIN_SPACING_PHYSICAL = HUB_DEPTH                   # [m] -- true design-intent minimum

# ── MRF-method feasibility floor (separate from the physical floor above) ─────
# The dual-rotor mesh uses two independent cylindrical MRF (frozen-rotor) zones,
# one centered on each rotor plane, which must not overlap. As spacing shrinks
# toward MIN_SPACING_PHYSICAL, each zone's half-height (mrf_dz) has to shrink
# too, and at some point becomes too thin to be a numerically meaningful
# "rotating region" around the blade -- this is very likely why the prior
# 700-case sweep's azimuth sensitivity came back looking negligible (see
# analysis/stacked_rotor_literature_pivot_2026-07-15.md on the main ENGR412
# repo). MRF_DZ_MIN below is a placeholder floor (not yet validated by a mesh-
# convergence study), kept at the same order of magnitude as the hub depth
# itself, just to make the zone-overlap failure explicit and fail fast instead
# of silently meshing a degenerate zone.
#
# NOTE: MRF_FEASIBLE_MIN_SPACING is still larger than MIN_SPACING_PHYSICAL --
# there's a real, currently-unreachable gap between "physically allowed" and
# "meshable with this method". Closing it needs replacing the two independent
# MRF cylinders with an overset/AMI-based approach (not attempted yet); until
# then, spacing below MRF_FEASIBLE_MIN_SPACING is rejected rather than silently
# produced with a bad mesh.
MRF_DZ_MIN               = HUB_DEPTH / 2.0
MRF_GAP_MARGIN_FRAC      = 0.02                              # fraction of D kept clear between the two zones
MRF_GAP_MARGIN           = MRF_GAP_MARGIN_FRAC * DIAMETER    # [m] (=0.02 at D=1.0, same as the prior literal)
MRF_FEASIBLE_MIN_SPACING = 2 * MRF_DZ_MIN + MRF_GAP_MARGIN    # [m]

# Two more geometry constants that were hardcoded in absolute meters (silently
# assuming D=1.0) until this pass -- now expressed as fractions of D so they
# rescale automatically if DIAMETER ever changes:
MRF_DZ_ABS_CAP_FRAC = 0.25                              # fraction of D -- absolute cap on MRF zone half-height
MRF_DZ_ABS_CAP      = MRF_DZ_ABS_CAP_FRAC * DIAMETER    # [m] (=0.25 at D=1.0, was the hardcoded "0.25" in mrf_dz)
MRF_RADIUS_FRAC     = 0.6                               # fraction of D -- MRF cylinder radius
MRF_RADIUS          = MRF_RADIUS_FRAC * DIAMETER        # [m] (=0.6 at D=1.0, was the hardcoded "radius 0.6")

# ── Design spaces ─────────────────────────────────────────────────────────────
# M_tip grids (2026-07-16), chosen to sit safely under M_TIP_CEILING=0.30 while
# spanning roughly the RPM range explored so far (500-1200 RPM at D=1.0) plus a
# bit of headroom at the top end -- see the tip-Mach discussion in
# analysis/stacked_rotor_literature_pivot_2026-07-15.md. At D=1.0 these produce
# a similar-but-not-identical RPM range to the values already in the existing
# CSV (that data is untouched either way -- it's self-describing by its own
# stored rpm_upper/rpm_lower/spacing_m columns, not by however a *future* sweep
# chooses its grid).
M_TIP_GRID_UPPER  = [0.08, 0.10, 0.12, 0.14, 0.16]   # suggested --rpm_upper values (co_rot only)
M_TIP_GRID_LOWER  = [0.10, 0.14, 0.18, 0.22, 0.26]   # rpm_lower / single-dataset rpm grid
SPACING_FRAC_GRID = [0.05, 0.10, 0.20, 0.35, 0.60]   # fraction of D -- same numeric values as the
                                                       # 2026-07-15 revision, now explicitly
                                                       # dimensionless instead of implicitly tied to D=1.0

DESIGN_SPACE_SINGLE = {
    "rpm": [round(rpm_from_mtip(m), 1) for m in M_TIP_GRID_LOWER],
}

# Revised 2026-07-15 (see analysis/stacked_rotor_literature_pivot_2026-07-15.md):
#   - spacing_m now starts at MRF_FEASIBLE_MIN_SPACING (0.05 m) instead of
#     0.20 m, denser toward the close end -- the literature (Hong et al. 2023,
#     Jacobellis et al. 2021) shows the strongest azimuth/spacing interaction
#     effects in this regime, which the old 0.20-0.60 m range mostly missed.
#     spacing_m=0.10 is back in (previously excluded for MRF-zone-overlap
#     reasons the feasibility floor above now handles explicitly).
#   - azimuth_deg is now symmetric (-90..+90, matching both papers' convention)
#     and denser near 0 deg, where both papers report the sharpest thrust/
#     efficiency features -- the old 0-90-only, evenly-spaced-at-15deg grid
#     could easily have straddled right over the interesting region.
# Revised again 2026-07-16: spacing_m and rpm_lower are now derived from
# SPACING_FRAC_GRID/M_TIP_GRID_LOWER instead of being literal lists, for the
# same D-portability reason as above -- numerically identical at D=1.0.
# Existing CSV rows are untouched -- only cases whose (spacing, azimuth,
# rpm_lower, rpm_upper) combo happens to match an already-completed case_id
# get skipped as already-done; everything else is new cases.
DESIGN_SPACE_DUAL = {
    "spacing_m":   [round(f * DIAMETER, 4) for f in SPACING_FRAC_GRID],
    "azimuth_deg": [-90, -45, -20, -10, 0, 10, 20, 45, 90],
    "rpm_lower":   [round(rpm_from_mtip(m), 1) for m in M_TIP_GRID_LOWER],
    # Single value by default -- preserves the existing case_id format exactly
    # when not overridden. The MLP control objective (lower-rotor command as a
    # function of *commanded* upper RPM) needs this varied via --rpm_upper;
    # RPM_UPPER above is kept only as the fallback/default value. For a new
    # sweep, M_tip-consistent --rpm_upper values would be:
    #   --rpm_upper 524.1 655.1 786.1 917.1 1048.1   (from M_TIP_GRID_UPPER)
    "rpm_upper":   [RPM_UPPER],
}

# ── CSV headers ───────────────────────────────────────────────────────────────
CSV_HEADER_SINGLE = [
    "case_id",
    "rpm",
    "thrust_N", "torque_Nm", "power_W", "fom",
    "iterations", "converged",
]

CSV_HEADER_DUAL = [
    "case_id",
    "spacing_m", "azimuth_deg", "rpm_upper", "rpm_lower",
    "pitch",
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
def write_case_configs_single(case_dir, rpm):
    omega = rpm_to_rads(rpm)
    tri = Path(case_dir) / "constant" / "triSurface"
    tri.mkdir(parents=True, exist_ok=True)
    sys_dir   = Path(case_dir) / "system"
    const_dir = Path(case_dir) / "constant"

    subprocess.run(["python3", GENERATOR,
        "--pitch", str(PITCH_UPPER), "--diameter", str(DIAMETER),
        "--rotor_z", str(UPPER_Z), "--solid_name", "propeller",
        "--n_pts", "150",
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
        f'     p1 (0 0 {UPPER_Z-MRF_DZ_ABS_CAP:.3f}); p2 (0 0 {UPPER_Z+MRF_DZ_ABS_CAP:.3f}); radius {MRF_RADIUS:.3f}; }}\n'
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
        "dataset": "single", "rpm": rpm, "pitch": PITCH_UPPER,
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
def write_case_configs_dual(case_dir, spacing, azimuth, rpm_lower, rpm_upper=RPM_UPPER):
    if spacing < MRF_FEASIBLE_MIN_SPACING:
        raise ValueError(
            f"spacing={spacing:.4f} m is below MRF_FEASIBLE_MIN_SPACING="
            f"{MRF_FEASIBLE_MIN_SPACING:.4f} m -- the current dual-cylinder "
            f"MRF-zone method can't mesh this validly (the two zones would "
            f"either overlap or be too thin to be numerically meaningful). "
            f"Physical minimum (hub depth) is {MIN_SPACING_PHYSICAL:.4f} m; "
            f"reaching spacing between that and the feasibility floor needs an "
            f"overset/AMI rewrite of the dual-rotor meshing approach, not "
            f"attempted yet -- see analysis/stacked_rotor_literature_pivot_2026-07-15.md."
        )

    lower_z = UPPER_Z - spacing
    omega_u = rpm_to_rads(rpm_upper)
    omega_l = rpm_to_rads(rpm_lower)   # co-rotating: same direction as upper
    # Dynamic MRF half-height: keeps zones clear of each other at all spacings,
    # guaranteeing a gap of at least MRF_GAP_MARGIN. At spacing=0.20/0.60 m this
    # reduces to the same values the old fixed proportional formula gave (kept
    # for continuity with already-completed cases at those spacings).
    mrf_dz = min(MRF_DZ_ABS_CAP, spacing * 0.45, (spacing - MRF_GAP_MARGIN) / 2.0)

    tri = Path(case_dir) / "constant" / "triSurface"
    tri.mkdir(parents=True, exist_ok=True)
    sys_dir   = Path(case_dir) / "system"
    const_dir = Path(case_dir) / "constant"

    subprocess.run(["python3", GENERATOR,
        "--pitch", str(PITCH_UPPER), "--diameter", str(DIAMETER),
        "--rotor_z", str(UPPER_Z), "--solid_name", "upperPropeller",
        "--n_pts", "150",
        "--output", str(tri / "upperPropeller.stl")],
        check=True, capture_output=True)

    subprocess.run(["python3", GENERATOR,
        "--pitch", str(PITCH_UPPER), "--diameter", str(DIAMETER),
        "--rotor_z", str(lower_z), "--solid_name", "lowerPropeller",
        "--azimuth_deg", str(azimuth),
        "--n_pts", "150",
        "--output", str(tri / "lowerPropeller.stl")],
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
        f'     p1 (0 0 {UPPER_Z-mrf_dz:.3f}); p2 (0 0 {UPPER_Z+mrf_dz:.3f}); radius {MRF_RADIUS:.3f}; }}\n'
        f'  {{ name rotatingZone2; type cellZoneSet; action new; source cylinderToCell;\n'
        f'     p1 (0 0 {lower_z-mrf_dz:.3f}); p2 (0 0 {lower_z+mrf_dz:.3f}); radius {MRF_RADIUS:.3f}; }}\n'
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
        "rpm_upper": rpm_upper, "rpm_lower": rpm_lower,
        "pitch": PITCH_UPPER,
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
            write_case_configs_single(case_dir, params["rpm"])
        else:
            write_case_configs_dual(
                case_dir,
                params["spacing_m"], params["azimuth_deg"],
                params["rpm_lower"], params.get("rpm_upper", RPM_UPPER),
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
        rpm_upper = params.get("rpm_upper", RPM_UPPER)
        omega_u = rpm_to_rads(rpm_upper)
        omega_l = rpm_to_rads(params["rpm_lower"])
        pu = abs(qu) * omega_u
        pl = abs(ql) * omega_l

        row = {
            "case_id": case_id,
            "spacing_m":  params["spacing_m"],  "azimuth_deg": params["azimuth_deg"],
            "rpm_upper":  rpm_upper,             "rpm_lower":   params["rpm_lower"],
            "pitch":      PITCH_UPPER,
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
                    choices=["single", "co_rot"],
                    help="Which dataset to run")
    ap.add_argument("--parallel", type=int, default=1,
                    help="Parallel workers (default 1; recommended: N_cores/2)")
    ap.add_argument("--dry_run",  action="store_true",
                    help="List cases without running them")
    ap.add_argument("--rpm",      type=float, nargs="+", help="Override RPM values")
    ap.add_argument("--spacing",  type=float, nargs="+", help="Override spacing values (co_rot only)")
    ap.add_argument("--azimuth",  type=float, nargs="+", help="Override azimuth values (co_rot only)")
    ap.add_argument("--rpm_upper", type=float, nargs="+",
                    help="Override upper-rotor RPM values (co_rot only). Default is the "
                         f"single fixed value ({RPM_UPPER}). Pass multiple values "
                         "(e.g. --rpm_upper 700 900 1100) to build the varying-upper-RPM "
                         "dataset the MLP controller needs -- see ml/README.md.")
    args = ap.parse_args()

    cfg          = DATASETS[args.dataset]
    sweep_dir    = cfg["sweep_dir"]
    results_csv  = os.path.join(sweep_dir, cfg["csv_name"])
    template_dir = cfg["template_dir"]
    header       = CSV_HEADER_SINGLE if args.dataset == "single" else CSV_HEADER_DUAL

    # ── Build case list ───────────────────────────────────────────────────────
    if args.dataset == "single":
        space = dict(DESIGN_SPACE_SINGLE)
        if args.rpm: space["rpm"] = args.rpm
        combos = [{"rpm": r} for r in space["rpm"]]
        def case_id_fn(p):
            return f"r{p['rpm']:.0f}"
    else:
        space = dict(DESIGN_SPACE_DUAL)
        if args.spacing:   space["spacing_m"]   = args.spacing
        if args.azimuth:   space["azimuth_deg"] = args.azimuth
        if args.rpm:       space["rpm_lower"]   = args.rpm
        if args.rpm_upper: space["rpm_upper"]   = args.rpm_upper
        combos = [
            {"spacing_m": s, "azimuth_deg": a, "rpm_lower": r, "rpm_upper": u}
            for s, a, r, u in itertools.product(
                space["spacing_m"], space["azimuth_deg"],
                space["rpm_lower"], space["rpm_upper"],
            )
        ]
        # case_id keeps its original format when rpm_upper has a single value, so the
        # existing 140-case dataset/CSV resumes exactly as before; a "u<rpm>_" prefix is
        # only added once rpm_upper is actually swept, so old and new rows never collide.
        multi_upper = len(space["rpm_upper"]) > 1
        def case_id_fn(p):
            base = (f"s{p['spacing_m']:.2f}_a{p['azimuth_deg']:03.0f}"
                    f"_r{p['rpm_lower']:.0f}")
            return f"u{p['rpm_upper']:.0f}_{base}" if multi_upper else base

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
