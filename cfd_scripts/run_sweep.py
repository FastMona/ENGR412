"""
run_sweep.py — ENGR412 parametric sweep (single-rotor, co-rotating variants)

Datasets (--dataset flag; see DATASETS dict below for each one's sweep_dir/template/csv)
  single                   : 1 rotor, varies RPM only (5 cases, ~6 min @ --parallel 5)
  co_rot                   : 2 co-rotating rotors, same pitch (D=1.0 m, NACA 4412, CCW).
                             spacing × azimuth × rpm_lower = 5 × 9 × 5 = 225 cases
                             (multiplied by len(--rpm_upper) if swept — see ml/README.md)
  co_rot_meshcheck         : mesh-sensitivity diagnostic — same geometry as co_rot on a
                             refined snappyHexMeshDict; separate dir/CSV, hand-run only
  co_rot_timecheck         : extended-endTime stability diagnostic on the co_rot mesh
  co_rot_vr12              : Jacobellis et al. (2021) VR-12 literature-match geometry
                             (D=2.216 m, constant-chord/collective blade, matched RPM)
  co_rot_vr12_meshcheck    : mesh-sensitivity check for co_rot_vr12
  co_rot_vr12_gci_lvl45/56 : GCI mesh-convergence series for co_rot_vr12
                             (see analyze_gci_study_vr12.py)

Output folders (all under /home/david/OpenFOAM/ENGR412/ — see DATASETS for the mapping):
  1_single_rotor_sweep/, 2_co_rot_sweep/, 3_co_rot_vr12_sweep/,
  4_co_rot_vr12_meshcheck_sweep/, 5_co_rot_vr12_gci_sweep/{lvl45,lvl56}/,
  6_co_rot_meshcheck_sweep/, 7_co_rot_timecheck_sweep/

Usage
  python3 run_sweep.py --dataset single  --parallel 12
  python3 run_sweep.py --dataset co_rot  --parallel 12
  python3 run_sweep.py --dataset single  --dry_run
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
# Separate template for the VR-12 geometry (D=2.216 m vs. TEMPLATE_DUAL's D=1.0 m) --
# blockMeshDict's domain box and snappyHexMeshDict's locationInMesh are both sized/
# positioned relative to rotor diameter, so they can't be shared with TEMPLATE_DUAL as-is.
# Create this as a copy of TEMPLATE_DUAL with system/blockMeshDict and
# system/snappyHexMeshDict replaced by the rescaled versions (see chat / rescale script).
TEMPLATE_DUAL_VR12 = f"{BASE_DIR}/coaxialRotor_vr12"
TEMPLATE_DUAL_VR12_MESHCHECK = f"{BASE_DIR}/coaxialRotor_vr12_meshcheck"   # refined mesh, same geometry
# Full-scale (D=1.0m, co_rot geometry) mesh-sensitivity check, sibling to the vr12 one above --
# diagnoses whether the spacing=0.10m/azimuth=-20 fom_total variance spike is a real isolated
# BVI effect or a mesh-resolution artifact. See coaxialRotor_meshcheck/system/snappyHexMeshDict
# for the specific refinement changes and the run command.
TEMPLATE_DUAL_MESHCHECK = f"{BASE_DIR}/coaxialRotor_meshcheck"
# GCI (grid-convergence-index) study templates -- clean, single-variable refinement-
# level bumps only (NO added refinementRegions, unlike _meshcheck), so the three levels
# form a valid r=2 geometric-refinement series for the Celik et al. (2008) GCI procedure
# already implemented in scripts/analyze_gci_study.py (on main, adapted for this dataset
# as analyze_gci_study_vr12.py). lvl(3,4) is the existing coaxialRotor_vr12 template --
# no separate dir needed, its data already exists in co_rot_vr12_results.csv.
TEMPLATE_DUAL_VR12_GCI_LVL45 = f"{BASE_DIR}/coaxialRotor_vr12_gci_lvl45"
TEMPLATE_DUAL_VR12_GCI_LVL56 = f"{BASE_DIR}/coaxialRotor_vr12_gci_lvl56"
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
    "co_rot_meshcheck": {
        # Mesh-sensitivity diagnostic (2026-07-29) for the spacing=0.10m/azimuth=-20
        # fom_total variance spike -- separate template dir + sweep_dir + CSV so it can
        # never collide with or silently resume against the real co_rot results. Run with:
        #   python3 scripts/run_sweep.py --dataset co_rot_meshcheck \
        #       --spacing 0.10 --azimuth -45 -20 -10 --rpm 786.1 --rpm_upper 786.1 --parallel 3
        "sweep_dir":    f"{BASE_DIR}/6_co_rot_meshcheck_sweep",
        "template_dir": TEMPLATE_DUAL_MESHCHECK,
        "csv_name":     "co_rot_meshcheck_results.csv",
    },
    "co_rot_timecheck": {
        # Extended-endTime stability diagnostic (2026-07-29), same question as
        # co_rot_meshcheck but testing time-integration length instead of mesh resolution --
        # same TEMPLATE_DUAL mesh, just a longer --end_time. Run with:
        #   python3 scripts/run_sweep.py --dataset co_rot_timecheck \
        #       --spacing 0.10 --azimuth -45 -20 -10 --rpm 786.1 --rpm_upper 786.1 \
        #       --end_time 3000 --parallel 3
        "sweep_dir":    f"{BASE_DIR}/7_co_rot_timecheck_sweep",
        "template_dir": TEMPLATE_DUAL,
        "csv_name":     "co_rot_timecheck_results.csv",
    },
    "co_rot_vr12": {
        "sweep_dir":    f"{BASE_DIR}/3_co_rot_vr12_sweep",
        "template_dir": TEMPLATE_DUAL_VR12,
        "csv_name":     "co_rot_vr12_results.csv",
    },
    "co_rot_vr12_meshcheck": {
        # Mesh-sensitivity check (2026-07-21): same geometry/RPM/collective as
        # co_rot_vr12, different (finer) snappyHexMeshDict, separate template dir +
        # sweep_dir + CSV so it can never collide with or silently resume against the
        # co_rot_vr12 results already collected. Point TEMPLATE_DUAL_VR12_MESHCHECK at a
        # copy of coaxialRotor_vr12 with a refined system/snappyHexMeshDict (bumped
        # refinementSurfaces level and/or an added refinementRegion near the inter-rotor
        # gap) -- see chat for the specific file. Run with, e.g.:
        #   python3 scripts/run_sweep.py --dataset co_rot_vr12_meshcheck \
        #       --azimuth 5.625 11.25 16.875 --parallel 3
        # (16.875 as a control point that wasn't anomalous on the coarse mesh.)
        "sweep_dir":    f"{BASE_DIR}/4_co_rot_vr12_meshcheck_sweep",
        "template_dir": TEMPLATE_DUAL_VR12_MESHCHECK,
        "csv_name":     "co_rot_vr12_meshcheck_results.csv",
    },
    "co_rot_vr12_gci_lvl45": {
        "sweep_dir":    f"{BASE_DIR}/5_co_rot_vr12_gci_sweep/lvl45",
        "template_dir": TEMPLATE_DUAL_VR12_GCI_LVL45,
        "csv_name":     "co_rot_vr12_gci_lvl45_results.csv",
    },
    "co_rot_vr12_gci_lvl56": {
        "sweep_dir":    f"{BASE_DIR}/5_co_rot_vr12_gci_sweep/lvl56",
        "template_dir": TEMPLATE_DUAL_VR12_GCI_LVL56,
        "csv_name":     "co_rot_vr12_gci_lvl56_results.csv",
    },
}

VR12_DATASETS = {"co_rot_vr12", "co_rot_vr12_meshcheck",
                 "co_rot_vr12_gci_lvl45", "co_rot_vr12_gci_lvl56"}   # share geometry/case-id logic

# co_rot and its two diagnostic siblings (meshcheck/timecheck) all share DESIGN_SPACE_DUAL,
# the plain (non-VR12) geometry defaults, and the original case_id format -- they differ only
# in template_dir/sweep_dir/csv_name (registered in DATASETS above) and, for meshcheck, the
# snappyHexMeshDict itself. Checked wherever code previously special-cased `== "co_rot"` so
# the two new datasets don't silently fall through to the VR12 branch instead.
CO_ROT_LIKE_DATASETS = {"co_rot", "co_rot_meshcheck", "co_rot_timecheck"}

# ── Fixed parameters ──────────────────────────────────────────────────────────
UPPER_Z      = 5.0    # upper rotor disk height [m]
DIAMETER     = 1.0    # rotor diameter [m]
RPM_UPPER    = 900.0  # upper rotor RPM (fixed)
PITCH_UPPER  = 0.4    # upper rotor pitch [m] (fixed)

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
MRF_GAP_MARGIN           = 0.02                              # [m] minimum clearance kept between the two zones
MRF_FEASIBLE_MIN_SPACING = 2 * MRF_DZ_MIN + MRF_GAP_MARGIN    # [m]

# ── Design spaces ─────────────────────────────────────────────────────────────
DESIGN_SPACE_SINGLE = {
    "rpm": [600, 750, 900, 1050, 1200],
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
# Existing 700-case CSV rows are untouched -- only overlapping grid points
# (spacing in {0.20, 0.60}, azimuth in {0, 45, 90}) will resolve to the same
# case_id and get skipped as already-done; everything else is new cases.
DESIGN_SPACE_DUAL = {
    "spacing_m":   [0.05, 0.10, 0.20, 0.35, 0.60],
    "azimuth_deg": [-90, -45, -20, -10, 0, 10, 20, 45, 90],
    "rpm_lower":   [524.1, 655.1, 786.1, 917.1, 1048.1],
    # Single value by default -- preserves the existing case_id format exactly
    # when not overridden. The MLP control objective (lower-rotor command as a
    # function of *commanded* upper RPM) needs this varied via --rpm_upper;
    # RPM_UPPER above is kept only as the fallback/default value.
    "rpm_upper":   [RPM_UPPER],
}

# ── VR-12 literature-match geometry (Jacobellis et al. 2021, Aerosp. Sci. Technol.
#    116:106847) -- added 2026-07-21, UNTESTED. Run --dry_run, then smoke-test a single
#    case, before committing to the full sweep below. Does NOT touch DIAMETER, the old
#    DESIGN_SPACE_DUAL, or write_case_configs_dual's default behavior -- the existing
#    700+-case co_rot dataset is unaffected by anything in this block.
VR12_DIAMETER      = 2.216     # [m] R = 1.108 m (Table 1)
VR12_CHORD         = 0.08      # [m] constant chord, untwisted blades (Table 1 -- unlike
                                # our default tapered 0.08->0.025 m blade)
VR12_NACA          = "2211"    # Closest 4-digit NACA to the real VR-12 airfoil: VR-12 is
                                # 10.6% thick at 35% chord with 2.3% camber at 20% chord
                                # (airfoiltools.com/UIUC coords). 4-digit family can't place
                                # max thickness past ~30% chord (fixed by the formula), so
                                # 2211 (2% camber @ 20%c, 11% thickness) is the nearest
                                # achievable match -- notably NOT the project's other
                                # default, NACA 4412 (4% camber @ 40%c, 12% thick), which is
                                # a much poorer match on both camber magnitude and position.
VR12_ROOT_FRACTION = 0.1876    # 18.76% R root cutout (Table 1) vs our default 30% R
VR12_COLLECTIVE    = 12.0      # [deg] constant collective, matches their primary CFD/exp
                                # case (theta0=12 deg) -- overrides the default pitch-based
                                # geometric twist (untwisted blades per Table 1)
VR12_RPM           = 1200.0    # matched upper/lower RPM -- their baseline operating point.
                                # Index-angle sensitivity is only physically comparable to
                                # their result at matched RPM (fixed relative blade phase);
                                # do not conflate with the rpm_lower-sweep dataset's meaning
                                # of azimuth_deg.

VR12_HUB_DEPTH                = HUB_DEPTH_FRAC * VR12_DIAMETER
VR12_MRF_DZ_MIN                = VR12_HUB_DEPTH / 2.0
VR12_MRF_FEASIBLE_MIN_SPACING = 2 * VR12_MRF_DZ_MIN + MRF_GAP_MARGIN   # ~= 0.0865 m
# Their densest CFD benchmark, z/c=0.73 (spacing = 0.73*0.08 = 0.0584 m), falls BELOW this
# floor -- not meshable with the current two-independent-MRF-cylinder method as-is (same
# issue documented in analysis/stacked_rotor_literature_pivot_2026-07-15.md for the
# original design space). z/c=1.5 (spacing=0.12 m) is the nearest literature-tested spacing
# that clears the floor, and Table 2 shows *denser* experimental azimuth coverage there
# than at z/c=0.73 (CFD-Helios only ran the index-angle sweep at 0.73; z/c=1.5 is
# experimental data, arguably a better ground-truth comparison anyway). Revisit z/c=0.73
# only after the MRF floor is tightened or the dual-rotor meshing moves to overset/AMI.
VR12_SPACING_INITIAL = 0.12     # [m], z/c = 1.5
VR12_AZIMUTH_INITIAL = [-45, -28.125, -16.875, -11.25, -5.625, 0,
                         5.625, 11.25, 16.875, 28.125, 45, 90]   # deg, Table 2 @ z/c=1.5

VR12_MRF_RADIUS = 1.3   # [m] rotating-zone radius; must clear the new blade tip
                         # (R=1.108 m) with margin -- was 0.6 m for the old R=0.5 m rotor.

# TEMPLATE_DUAL's blockMeshDict puts the rotor at domain mid-height (5.0 m = 5D for
# D=1.0 m, in a 10D-tall domain) to keep 5D of far-field clearance above and below.
# VR12_UPPER_Z preserves that same 5D clearance at the new diameter -- must match
# whatever z the rescaled TEMPLATE_DUAL_VR12/system/blockMeshDict actually puts the
# domain mid-height at (5 * VR12_DIAMETER = 11.08 m in the rescaled template provided).
VR12_UPPER_Z = 5.0 * (VR12_DIAMETER / DIAMETER)   # = 11.08 m

DESIGN_SPACE_CO_ROT_VR12 = {
    "spacing_m":   [VR12_SPACING_INITIAL],
    "azimuth_deg": VR12_AZIMUTH_INITIAL,
    "rpm_lower":   [VR12_RPM],
    "rpm_upper":   [VR12_RPM],
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
    "spacing_inv_m", "azimuth_folded_deg",
    "convergence_ratio", "data_quality",
    "mesh_diagnostic_flag",
]

# co_rot_vr12 uses a different blade geometry (constant chord + collective, not
# tapered chord + geometric pitch) -- separate header so "pitch" isn't overloaded
# with a degrees value in a column documented/used elsewhere as metres.
CSV_HEADER_DUAL_VR12 = [
    "case_id",
    "spacing_m", "azimuth_deg", "rpm_upper", "rpm_lower",
    "collective_deg", "diameter_m", "chord_m", "naca",
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


def _tail_ratio(dat_path, col=3, tail_frac=0.2, min_points=5):
    """
    Raw tail-window std/mean|value| ratio for a force.dat time-history column -- the same
    quantity force_converged() thresholds against, exposed directly so callers can grade
    convergence quality (CONVERGED_TIGHT/CONVERGED/BORDERLINE/NOT_CONVERGED) instead of just
    getting a pass/fail bool. Returns None if the file is missing or too short to judge.
    """
    if not os.path.exists(dat_path):
        return None
    vals = []
    with open(dat_path) as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith('#') and not s.startswith('/'):
                try:
                    vals.append(float(s.split()[col]))
                except (ValueError, IndexError):
                    pass
    if len(vals) < min_points:
        return None
    n = max(min_points, int(len(vals) * tail_frac))
    tail = vals[-n:]
    mean_abs = sum(abs(v) for v in tail) / len(tail)
    if mean_abs < 1e-6:
        return 0.0
    mean_val = sum(tail) / len(tail)
    std = (sum((v - mean_val) ** 2 for v in tail) / len(tail)) ** 0.5
    return std / mean_abs


def force_converged(dat_path, col=3, tail_frac=0.2, tol=0.02, min_points=5):
    """
    Whether a force.dat time-history column has actually stabilized, checked over the
    last tail_frac of recorded points (std / mean|value| <= tol). Ported from
    run_ct_sweep.py's identical check -- reading only the final line is unreliable for
    these MRF hover cases (some plateau at a stable-but-wrong value quickly, others are
    still slowly settling at end-of-run).
    """
    if not os.path.exists(dat_path):
        return False
    vals = []
    with open(dat_path) as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith('#') and not s.startswith('/'):
                try:
                    vals.append(float(s.split()[col]))
                except (ValueError, IndexError):
                    pass
    if len(vals) < min_points:
        return False
    n = max(min_points, int(len(vals) * tail_frac))
    tail = vals[-n:]
    mean_abs = sum(abs(v) for v in tail) / len(tail)
    if mean_abs < 1e-6:
        return True
    mean_val = sum(tail) / len(tail)
    std = (sum((v - mean_val) ** 2 for v in tail) / len(tail)) ** 0.5
    return (std / mean_abs) <= tol


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
        f'     p1 (0 0 {UPPER_Z-0.25:.3f}); p2 (0 0 {UPPER_Z+0.25:.3f}); radius 0.6; }}\n'
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
def write_case_configs_dual(case_dir, spacing, azimuth, rpm_lower, rpm_upper=RPM_UPPER,
                             diameter=DIAMETER, chord=None, naca="4412",
                             root_fraction=0.30, collective=None, mrf_radius=0.6,
                             upper_z=UPPER_Z, template_dir=TEMPLATE_DUAL, end_time=500):
    """
    diameter/chord/naca/root_fraction/collective/mrf_radius all default to the exact
    values the original (D=1.0 m) co_rot dataset always used implicitly -- passing none
    of them reproduces the pre-2026-07-21 behavior byte-for-byte. They exist so
    co_rot_vr12 (see DESIGN_SPACE_CO_ROT_VR12) can reuse this function instead of forking
    a near-duplicate.
    """
    hub_depth = HUB_DEPTH_FRAC * diameter
    mrf_dz_min = hub_depth / 2.0
    feasible_min_spacing = 2 * mrf_dz_min + MRF_GAP_MARGIN
    if spacing < feasible_min_spacing:
        raise ValueError(
            f"spacing={spacing:.4f} m is below the MRF feasibility floor="
            f"{feasible_min_spacing:.4f} m for diameter={diameter:.3f} m -- the current "
            f"dual-cylinder MRF-zone method can't mesh this validly (the two zones would "
            f"either overlap or be too thin to be numerically meaningful). "
            f"Physical minimum (hub depth) is {hub_depth:.4f} m; reaching spacing between "
            f"that and the feasibility floor needs an overset/AMI rewrite of the "
            f"dual-rotor meshing approach, not attempted yet -- see "
            f"analysis/stacked_rotor_literature_pivot_2026-07-15.md."
        )

    lower_z = upper_z - spacing
    omega_u = rpm_to_rads(rpm_upper)
    omega_l = rpm_to_rads(rpm_lower)   # co-rotating: same direction as upper
    # Dynamic MRF half-height: keeps zones clear of each other at all spacings,
    # guaranteeing a gap of at least MRF_GAP_MARGIN. At spacing=0.20/0.60 m with the
    # default diameter this reduces to the same values the old fixed proportional
    # formula gave (kept for continuity with already-completed cases at those spacings).
    # The 0.25 cap was tuned for diameter=1.0 m; scaled proportionally for other
    # diameters (e.g. VR12_DIAMETER) so it isn't silently wrong at a different rotor scale.
    mrf_dz_cap = 0.25 * (diameter / DIAMETER)
    mrf_dz = min(mrf_dz_cap, spacing * 0.45, (spacing - MRF_GAP_MARGIN) / 2.0)

    tri = Path(case_dir) / "constant" / "triSurface"
    tri.mkdir(parents=True, exist_ok=True)
    sys_dir   = Path(case_dir) / "system"
    const_dir = Path(case_dir) / "constant"

    gen_common = ["--diameter", str(diameter), "--naca", str(naca),
                  "--root_fraction", str(root_fraction)]
    if chord is not None:
        gen_common += ["--chord", str(chord)]
    if collective is not None:
        gen_common += ["--collective", str(collective)]
    else:
        gen_common += ["--pitch", str(PITCH_UPPER)]

    subprocess.run(["python3", GENERATOR, *gen_common,
        "--rotor_z", str(upper_z), "--solid_name", "upperPropeller",
        "--n_pts", "150",
        "--output", str(tri / "upperPropeller.stl")],
        check=True, capture_output=True)

    subprocess.run(["python3", GENERATOR, *gen_common,
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
        f'     p1 (0 0 {upper_z-mrf_dz:.3f}); p2 (0 0 {upper_z+mrf_dz:.3f}); radius {mrf_radius}; }}\n'
        f'  {{ name rotatingZone2; type cellZoneSet; action new; source cylinderToCell;\n'
        f'     p1 (0 0 {lower_z-mrf_dz:.3f}); p2 (0 0 {lower_z+mrf_dz:.3f}); radius {mrf_radius}; }}\n'
        f');\n'
    )

    (const_dir / "MRFProperties").write_text(
        f'FoamFile {{ version 2.0; format ascii; class dictionary; object MRFProperties; }}\n'
        f'MRF1 {{ cellZone rotatingZone1; active true;\n'
        f'        nonRotatingPatches (inlet outlet sides);\n'
        f'        origin (0 0 {upper_z}); axis (0 0 1); omega {omega_u:.6f}; }}\n'
        f'MRF2 {{ cellZone rotatingZone2; active true;\n'
        f'        nonRotatingPatches (inlet outlet sides);\n'
        f'        origin (0 0 {lower_z:.4f}); axis (0 0 1); omega {omega_l:.6f}; }}\n'
    )

    (sys_dir / "controlDict").write_text(
        f'FoamFile {{ version 2.0; format ascii; class dictionary; object controlDict; }}\n'
        f'application simpleFoam; startFrom startTime; startTime 0; stopAt endTime;\n'
        f'endTime {end_time}; deltaT 1; writeControl timeStep; writeInterval {end_time};\n'
        f'purgeWrite 0; writeFormat ascii; writePrecision 6; writeCompression off;\n'
        f'timeFormat general; timePrecision 6; runTimeModifiable true;\n'
        f'functions {{\n'
        f'    forcesUpper {{ type forces; libs (forces); writeControl timeStep; writeInterval 10;\n'
        f'        patches (upperBlade); rho rhoInf; rhoInf 1.225; CofR (0 0 {upper_z}); log yes; }}\n'
        f'    forcesLower {{ type forces; libs (forces); writeControl timeStep; writeInterval 10;\n'
        f'        patches (lowerBlade); rho rhoInf; rhoInf 1.225; CofR (0 0 {lower_z:.4f}); log yes; }}\n'
        f'    forcesTotal {{ type forces; libs (forces); writeControl timeStep; writeInterval 10;\n'
        f'        patches (upperBlade lowerBlade); rho rhoInf; rhoInf 1.225;\n'
        f'        CofR (0 0 {(upper_z+lower_z)/2:.4f}); log yes; }}\n'
        f'}}\n'
    )

    # BUG FIXED 2026-07-21: this used to hardcode Path(TEMPLATE_DUAL) regardless of which
    # template_dir the case actually came from -- meaning co_rot_vr12 cases silently got
    # co_rot's (D=1.0 m) snappyHexMeshDict re-copied over the correct one that run_case()'s
    # initial copytree had already placed. Harmless for the sweep already run (the VR-12
    # rescaled snappyHexMeshDict only differs by locationInMesh's z-value, and (0,0,5.0)
    # still happened to be a valid empty-fluid point in the bigger domain) but would have
    # silently defeated any real snappyHexMeshDict change (e.g. a refinement-level bump for
    # a mesh-sensitivity check) without this fix.
    shutil.copy(
        str(Path(template_dir) / "system" / "snappyHexMeshDict"),
        str(sys_dir / "snappyHexMeshDict"),
    )

    (Path(case_dir) / "run_params.json").write_text(json.dumps({
        "dataset": "dual", "spacing_m": spacing, "azimuth_deg": azimuth,
        "rpm_upper": rpm_upper, "rpm_lower": rpm_lower,
        "pitch": PITCH_UPPER if collective is None else None,
        "collective_deg": collective,
        "diameter": diameter, "chord": chord, "naca": naca,
        "root_fraction": root_fraction, "mrf_radius": mrf_radius,
        "upper_z": upper_z, "lower_z": lower_z, "omega_upper": omega_u, "omega_lower": omega_l,
    }, indent=2))


def extract_results_dual(case_dir):
    pp = Path(case_dir) / "postProcessing"

    def fz(name):
        p = pp / name / "0" / "force.dat"
        return read_last_force(str(p), 3) if p.exists() else None

    def mz(name):
        p = pp / name / "0" / "moment.dat"
        return read_last_force(str(p), 3) if p.exists() else None

    def conv(name):
        p = pp / name / "0" / "force.dat"
        return force_converged(str(p))

    def ratio(name):
        p = pp / name / "0" / "force.dat"
        return _tail_ratio(str(p))

    ratios = [r for r in (ratio("forcesUpper"), ratio("forcesLower"), ratio("forcesTotal")) if r is not None]
    worst_ratio = max(ratios) if ratios else None
    if worst_ratio is None:
        data_quality = "MISSING"
    elif worst_ratio <= 0.005:
        data_quality = "CONVERGED_TIGHT"
    elif worst_ratio <= 0.02:
        data_quality = "CONVERGED"
    elif worst_ratio <= 0.05:
        data_quality = "BORDERLINE"
    else:
        data_quality = "NOT_CONVERGED"

    return {
        "thrust_upper_N":  fz("forcesUpper"),
        "thrust_lower_N":  fz("forcesLower"),
        "thrust_total_N":  fz("forcesTotal"),
        "torque_upper_Nm": mz("forcesUpper"),
        "torque_lower_Nm": mz("forcesLower"),
        "iterations":      last_iter(case_dir),
        "converged":       conv("forcesUpper") and conv("forcesLower") and conv("forcesTotal"),
        "convergence_ratio": worst_ratio,
        "data_quality":    data_quality,
    }


# ── Generic case runner ───────────────────────────────────────────────────────
def run_case(args_tuple):
    i, total, case_id, case_dir, params, dataset, template_dir = args_tuple

    print(f"[{i}/{total}] START {case_id}", flush=True)
    t0 = time.time()

    # Wipe any stale case_dir before starting. A case only gets a CSV row (and
    # therefore only counts as "completed"/skippable) after it finishes, so if this
    # dir already exists it's leftover from a run interrupted mid-blockMesh/
    # snappyHexMesh/simpleFoam (crash, power failure, manual kill). OpenFOAM's forces
    # function object APPENDS to postProcessing/<name>/0/force.dat rather than
    # overwriting -- a leftover partial force.dat would mix old (possibly still-
    # diverging) rows ahead of the new run's data, which force_converged()'s tail-
    # window check reads directly. Always start from a guaranteed-clean template copy.
    if os.path.exists(case_dir):
        shutil.rmtree(case_dir)
    os.makedirs(case_dir, exist_ok=True)
    for sub in ["0", "system", "constant"]:
        shutil.copytree(os.path.join(template_dir, sub), os.path.join(case_dir, sub))

    try:
        if dataset == "single":
            write_case_configs_single(case_dir, params["rpm"])
        else:
            write_case_configs_dual(
                case_dir,
                params["spacing_m"], params["azimuth_deg"],
                params["rpm_lower"], params.get("rpm_upper", RPM_UPPER),
                diameter=params.get("diameter", DIAMETER),
                chord=params.get("chord"),
                naca=params.get("naca", "4412"),
                root_fraction=params.get("root_fraction", 0.30),
                collective=params.get("collective"),
                mrf_radius=params.get("mrf_radius", 0.6),
                upper_z=params.get("upper_z", UPPER_Z),
                template_dir=template_dir,
                end_time=params.get("end_time", 500),
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

        if dataset in VR12_DATASETS:
            row = {
                "case_id": case_id,
                "spacing_m":  params["spacing_m"],  "azimuth_deg": params["azimuth_deg"],
                "rpm_upper":  rpm_upper,             "rpm_lower":   params["rpm_lower"],
                "collective_deg": params.get("collective"),
                "diameter_m": params.get("diameter", DIAMETER),
                "chord_m":    params.get("chord"),
                "naca":       params.get("naca", "4412"),
            }
        else:
            row = {
                "case_id": case_id,
                "spacing_m":  params["spacing_m"],  "azimuth_deg": params["azimuth_deg"],
                "rpm_upper":  rpm_upper,             "rpm_lower":   params["rpm_lower"],
                "pitch":      PITCH_UPPER,
            }
        row.update({
            "thrust_upper_N":  round(tu, 4),
            "thrust_lower_N":  round(tl, 4),
            "thrust_total_N":  round(tt, 4),
            "torque_upper_Nm": round(qu, 4),
            "torque_lower_Nm": round(ql, 4),
            "torque_net_Nm":   round(qu + ql, 4),
            "power_upper_W":   round(pu, 2),
            "power_lower_W":   round(pl, 2),
            "power_total_W":   round(pu + pl, 2),
            "fom_upper":  figure_of_merit(tu, pu, R=params.get("diameter", DIAMETER) / 2.0),
            "fom_lower":  figure_of_merit(tl, pl, R=params.get("diameter", DIAMETER) / 2.0),
            "fom_total":  figure_of_merit(tt, pu + pl, R=params.get("diameter", DIAMETER) / 2.0),
            "iterations": iters,
            "converged":  res.get("converged", False),
        })

        if dataset not in VR12_DATASETS:
            # Extra columns for the co_rot dataset only -- CSV_HEADER_DUAL_VR12 is untouched,
            # so adding these unconditionally would break DictWriter on vr12 rows.
            spacing_val = params["spacing_m"]
            azimuth_val = params["azimuth_deg"]
            row["spacing_inv_m"] = round(1.0 / spacing_val, 4) if spacing_val else None
            # theta ~ theta+180 confirmed empirically (PS 2.25); does NOT assume mirror
            # symmetry theta ~ -theta, which is unconfirmed for a co-rotating system.
            row["azimuth_folded_deg"] = round(azimuth_val % 180, 3)
            row["convergence_ratio"] = (
                round(res["convergence_ratio"], 5)
                if res.get("convergence_ratio") is not None else None
            )
            row["data_quality"] = res.get("data_quality")
            # 2026-07-29 mesh-sensitivity diagnostic (co_rot_meshcheck, 3 cases at
            # spacing=0.10m/azimuth=-45/-20/-10) found fom_total moves 20-99% under mesh
            # refinement at every point tested -- a general tight-spacing under-resolution,
            # not an isolated azimuth=-20 artifact (see PS/pending log for the full writeup).
            # Flagged by spacing alone (the root cause -- inter-rotor gap distance -- doesn't
            # depend on azimuth), NOT extended to spacing=0.05/0.20m, which were never tested
            # despite geometric proximity -- absence of evidence isn't evidence of fitness.
            row["mesh_diagnostic_flag"] = (
                "UNDER_RESOLVED_TIGHT_SPACING" if abs(spacing_val - 0.10) < 1e-9 else ""
            )
        print(f"[{i}/{total}] DONE  {case_id}  "
              f"T={tt:.1f}N  Tu={tu:.1f}N  Tl={tl:.1f}N  "
              f"P={pu+pl:.0f}W  t={elapsed:.0f}s", flush=True)

    return row


# ── CSV writer (file-locked for parallel safety) ──────────────────────────────
def append_row(row, csv_path, header):
    with open(csv_path, "a", newline="") as f:
        _lock(f)
        csv.DictWriter(f, fieldnames=header).writerow(row)
        f.flush()
        os.fsync(f.fileno())
        _unlock(f)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="ENGR412 parametric sweep runner")
    ap.add_argument("--dataset",  required=True,
                    choices=["single", "co_rot", "co_rot_meshcheck", "co_rot_timecheck",
                             "co_rot_vr12", "co_rot_vr12_meshcheck",
                             "co_rot_vr12_gci_lvl45", "co_rot_vr12_gci_lvl56"],
                    help="Which dataset to run")
    ap.add_argument("--parallel", type=int, default=1,
                    help="Parallel workers (default 1; recommended: N_cores/2)")
    ap.add_argument("--dry_run",  action="store_true",
                    help="List cases without running them")
    ap.add_argument("--force_fresh", action="store_true",
                    help="Allow creating a fresh results CSV even if the sweep "
                         "directory already contains a substantial number of case "
                         "subdirectories (safety check, see main()).")
    ap.add_argument("--rpm",      type=float, nargs="+", help="Override RPM values (single: rpm; dual datasets: rpm_lower)")
    ap.add_argument("--spacing",  type=float, nargs="+", help="Override spacing values (any dual-rotor dataset, not single)")
    ap.add_argument("--azimuth",  type=float, nargs="+", help="Override azimuth values (any dual-rotor dataset, not single)")
    ap.add_argument("--rpm_upper", type=float, nargs="+",
                    help="Override upper-rotor RPM values (any dual-rotor dataset, not single). "
                         f"Default is the single fixed value ({RPM_UPPER}) for co_rot-like "
                         "datasets, or the matched VR12_RPM for co_rot_vr12*. Pass multiple "
                         "values (e.g. --rpm_upper 700 900 1100) to build the varying-upper-RPM "
                         "dataset the MLP controller needs -- see ml/README.md.")
    ap.add_argument("--end_time", type=float, default=1500,
                    help="Override endTime (default 1500; was hardcoded 500)")
    args = ap.parse_args()

    cfg          = DATASETS[args.dataset]
    sweep_dir    = cfg["sweep_dir"]
    results_csv  = os.path.join(sweep_dir, cfg["csv_name"])
    template_dir = cfg["template_dir"]
    if args.dataset == "single":
        header = CSV_HEADER_SINGLE
    elif args.dataset in VR12_DATASETS:
        header = CSV_HEADER_DUAL_VR12
    else:
        header = CSV_HEADER_DUAL

    # ── Build case list ───────────────────────────────────────────────────────
    if args.dataset == "single":
        space = dict(DESIGN_SPACE_SINGLE)
        if args.rpm: space["rpm"] = args.rpm
        combos = [{"rpm": r} for r in space["rpm"]]
        def case_id_fn(p):
            return f"r{p['rpm']:.0f}"
    else:
        space = dict(DESIGN_SPACE_DUAL if args.dataset in CO_ROT_LIKE_DATASETS else DESIGN_SPACE_CO_ROT_VR12)
        if args.spacing:   space["spacing_m"]   = args.spacing
        if args.azimuth:   space["azimuth_deg"] = args.azimuth
        if args.rpm:       space["rpm_lower"]   = args.rpm
        if args.rpm_upper: space["rpm_upper"]   = args.rpm_upper
        # co_rot_vr12 cases all carry the same fixed VR-12 geometry -- folded into every
        # combo dict here so run_case/write_case_configs_dual/figure_of_merit can just
        # read params.get("diameter"/"chord"/"naca"/"root_fraction"/"collective"/
        # "mrf_radius") without threading a separate argument through the whole call chain.
        geometry_extra = {} if args.dataset in CO_ROT_LIKE_DATASETS else {
            "diameter": VR12_DIAMETER, "chord": VR12_CHORD, "naca": VR12_NACA,
            "root_fraction": VR12_ROOT_FRACTION, "collective": VR12_COLLECTIVE,
            "mrf_radius": VR12_MRF_RADIUS, "upper_z": VR12_UPPER_Z,
        }
        combos = [
            {"spacing_m": s, "azimuth_deg": a, "rpm_lower": r, "rpm_upper": u, "end_time": args.end_time, **geometry_extra}
            for s, a, r, u in itertools.product(
                space["spacing_m"], space["azimuth_deg"],
                space["rpm_lower"], space["rpm_upper"],
            )
        ]
        # case_id keeps its original format when rpm_upper has a single value, so the
        # existing 140-case dataset/CSV resumes exactly as before; a "u<rpm>_" prefix is
        # only added once rpm_upper is actually swept, so old and new rows never collide.
        # co_rot_vr12 writes to its own sweep_dir/CSV entirely, so no collision risk with
        # co_rot's case_id format either way.
        multi_upper = len(space["rpm_upper"]) > 1
        if args.dataset in VR12_DATASETS:
            # Azimuth values here (e.g. -16.875, 28.125) don't round-trip through the
            # original ":03.0f" integer-degree format -- needs 3 decimal places, plus a
            # "vr12_" prefix (belt-and-suspenders on top of the already-separate CSV/dir).
            def case_id_fn(p):
                base = (f"vr12_s{p['spacing_m']:.3f}_a{p['azimuth_deg']:+08.3f}"
                        f"_r{p['rpm_lower']:.0f}")
                return f"u{p['rpm_upper']:.0f}_{base}" if multi_upper else base
        else:
            # UNCHANGED from before this patch -- must stay byte-identical so the existing
            # 700+-case co_rot CSV's case_id values still match and resume correctly.
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

    # Nothing above this line ever touches disk -- --dry_run always returns before
    # reaching here, so it is now guaranteed side-effect-free no matter what
    # os.path.exists(results_csv) returns. This fixes a real incident: a dry run
    # whose existence check spuriously returned False overwrote a 1124-row results
    # CSV with just a header, because this file-creation code used to run
    # unconditionally before the dry_run check.
    if not os.path.exists(results_csv):
        # Second safety net, independent of the exists() check above: if the sweep
        # directory already has a substantial number of case subdirectories but the
        # CSV is missing, that is much more likely a spurious read (or a wrong path)
        # than a genuinely fresh dataset. Refuse to silently blank it out.
        existing_case_dirs = 0
        if os.path.isdir(sweep_dir):
            existing_case_dirs = sum(
                1 for d in os.listdir(sweep_dir)
                if os.path.isdir(os.path.join(sweep_dir, d))
            )
        if existing_case_dirs > 10 and not args.force_fresh:
            raise SystemExit(
                f"\nERROR: {results_csv} does not exist, but {sweep_dir} already "
                f"contains {existing_case_dirs} case subdirectories -- this looks like "
                f"prior work, not a fresh dataset. Refusing to create a blank results "
                f"CSV over it. If you really want to start fresh, pass --force_fresh."
            )
        os.makedirs(sweep_dir, exist_ok=True)
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
