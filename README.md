# ENGR412 — Coaxial Rotor Thrust Optimisation

Concordia University Independent Study. OpenFOAM CFD characterises a co-rotating
coaxial rotor pair and builds a training dataset for an MLP-based lower-rotor
controller: given the upper rotor's commanded RPM, the controller outputs the
lower rotor's RPM, axial spacing, and azimuthal (index) angle that maximise total
thrust. A separate Caradonna-Tung hover-rotor validation case sanity-checks the
solver/mesh pipeline against published experimental data.

`main` carries the CFD sweep pipeline, C-T validation, and the MLP lower-rotor
controller — surrogate model, policy extraction, embeddable controller —
documented separately in `ml_scripts/README_ML.md`.

For decisions, corrections, and open questions not obvious from this file, see
`PROJECT_STATE_*.md` on the WSL filesystem (the live status log; this README
covers layout/usage/mechanics and is assumed already read there).

---

## Project status

| Component | State |
| --- | --- |
| Single-rotor baseline sweep | data cleared — re-run pending (`run_sweep.py --dataset single`) |
| Co-rotating coaxial sweep | 1625 cases, 98.0% converged — see [Design space](#design-space-co-rotating-coaxial-sweep). **Filename gotcha:** canonical `co_rot_results.csv` doesn't exist on WSL; real data is `co_rot_results2.csv` — see [Known issues](#known-issues--pitfalls) |
| Co-rotating mesh-sensitivity / time-integration diagnostics | complete (3/3 cases each) — found under-resolution at tight spacing (`fom_total` moves 20–99% under refinement), not an isolated azimuth artifact |
| VR-12 literature-match sweep | complete (12/12 azimuth points) — see [VR-12 sweep](#vr-12-literature-match-sweep---dataset-co_rot_vr12-added-2026-07-21) |
| VR-12 mesh-sensitivity / GCI diagnostics | complete |
| C-T validation (full/reduced × 650/1250 RPM) | all 4 combos complete — see [Caradonna-Tung validation](#caradonna-tung-validation) for current numbers |
| GCI mesh-convergence study (C-T, θ=8°, 650 RPM) | complete — inconclusive, not pursued further |
| MLP lower-rotor controller (`ml_scripts/`) | merged into `main`, run end-to-end against current dataset — see `ml_scripts/README_ML.md` |

Pre-fix archived C-T results exist under `caradonnaTung_*_tier1/` directories, kept
for reference only — not itemized here.

CFD case data and results all live on the WSL filesystem or under `results_*/`
(both untracked in git — see `.gitignore`); this repo tracks only the pipeline
code, not generated data.

---

## Repository layout

```text
ENGR412/
├── dash.py                       # dashboard — menu-driven status and launcher
├── cfd_scripts/
│   ├── generate_propeller.py     # NACA 4-digit blade STL for snappyHexMesh
│   ├── run_sweep.py              # parametric sweep: single-rotor / co-rotating / VR-12 / diagnostics
│   ├── run_ct_sweep.py            # Caradonna-Tung validation sweep (full / reduced geometry)
│   ├── run_gci_study.sh           # 3-resolution GCI mesh-convergence harness (calls run_ct_sweep.py)
│   ├── analyze_sweep.py           # EDA: plots, coefficients, summary CSV
│   ├── analyze_gci_study.py       # Richardson extrapolation / GCI (Celik et al. 2008) — C-T mesh
│   ├── analyze_gci_study_vr12.py  # same GCI procedure, adapted for the co_rot_vr12 dataset
│   ├── C-T_validation.py          # C-T comparison, 650 RPM (11 angles, 4 figures)
│   ├── C-T_comparisonA.py         # Appendix A reproduction, 1250 RPM (CT table + Cp panels)
│   ├── check_convergence.py       # classify capped-out co_rot cases by residual trend
│   ├── continue_run.py            # restart capped co_rot cases from latestTime (superseded by rerun_capped.py)
│   ├── rerun_capped.py            # clean full rebuild (mesh+solve) of capped co_rot cases at a higher endTime
│   ├── extract_time_averaged.py   # time-averaged force/torque for PLATEAU/DIVERGING (non-responsive) cases
│   └── merge_final_dataset.py     # consolidate original + rebuilt + time-averaged rows into one training CSV
├── ml_scripts/                    # MLP lower-rotor controller — see ml_scripts/README_ML.md
├── analysis/                      # dated investigation write-ups (see History, below)
├── results_singleRotor/           # single-rotor EDA output (figures/ + eda_summary.csv)
├── results_2_co_rot/               # co-rotating EDA output
├── results_CT_validation_full/     # C-T validation, full geometry (650 RPM)
├── results_CT_validation_reduced/  # C-T validation, reduced geometry (650 RPM)
├── results_CT_appendixA_full/      # C-T Appendix A, full geometry (1250 RPM)
└── results_CT_appendixA_reduced/   # C-T Appendix A, reduced geometry (1250 RPM)
```

(`results_CT_validation/` and `results_CT_appendixA/` — the old shared-path
versions of the four dirs above — still exist on disk, superseded, kept for
reference; see [Known issues](#known-issues--pitfalls).)

Two now-dead one-shot data-migration scripts (`wsl_backfill_clean_v2.py`,
`wsl_patch_items_4_5.sh`) were removed 2026-08-03; git history has them if needed.

CFD case data lives on the WSL filesystem (not tracked in git):

```text
/home/david/OpenFOAM/ENGR412/
├── singleRotor/                        # single-rotor template case
├── coaxialRotor/                       # coaxial template case
├── caradonnaTung_full_650rpm/          # C-T full geometry, 650 RPM  (11 angles)
├── caradonnaTung_full_1250rpm/         # C-T full geometry, 1250 RPM (3 angles: 5/8/12°)
├── caradonnaTung_reduced_650rpm/       # C-T reduced geometry, 650 RPM
├── caradonnaTung_reduced_1250rpm/      # C-T reduced geometry, 1250 RPM
├── caradonnaTung_full_*_tier1/         # archived pre-fix results, kept for reference
├── coaxialRotor_vr12/                  # VR-12 geometry template (D=2.216 m, Jacobellis et al. 2021)
├── coaxialRotor_vr12_meshcheck/        # VR-12 mesh-sensitivity template (finer snappyHexMeshDict)
├── coaxialRotor_vr12_gci_lvl45/        # VR-12 GCI series, level (4,5)
├── coaxialRotor_vr12_gci_lvl56/        # VR-12 GCI series, level (5,6)  — lvl(3,4) reuses coaxialRotor_vr12
├── coaxialRotor_meshcheck/             # full-scale (D=1.0 m) mesh-sensitivity template
├── gci_study/                         # lvl_4_5 / lvl_5_6 / lvl_6_7 mesh-convergence cases (C-T)
├── 1_single_rotor_sweep/              # single-rotor design-space cases
│   └── single_rotor_results.csv
├── 2_co_rot_sweep/                    # co-rotating design-space cases
│   └── co_rot_results2.csv             # NOT co_rot_results.csv -- see Known issues
├── 3_co_rot_vr12_sweep/                # VR-12 literature-match sweep (see Design space, below)
│   └── co_rot_vr12_results.csv
├── 4_co_rot_vr12_meshcheck_sweep/      # VR-12 mesh-sensitivity check cases
│   └── co_rot_vr12_meshcheck_results.csv
├── 5_co_rot_vr12_gci_sweep/            # VR-12 GCI study — lvl45/ and lvl56/ subdirs
├── 6_co_rot_meshcheck_sweep/           # full-scale mesh-sensitivity check (spacing=0.10m diagnostic)
│   └── co_rot_meshcheck_results.csv
└── 7_co_rot_timecheck_sweep/           # full-scale extended-endTime stability check
    └── co_rot_timecheck_results.csv
```

`2_co_rot_sweep/` also holds a set of case-triage intermediate CSVs (convergence
classification, rebuilt/time-averaged rows, final merged training CSV) produced by
`check_convergence.py` → `rerun_capped.py`/`extract_time_averaged.py` →
`merge_final_dataset.py` — see [Scripts](#scripts) below. Workflow intermediates,
not part of the tracked layout above.

---

## Design space (co-rotating coaxial sweep)

Revised 2026-07-15 after a literature check (Jacobellis et al. 2021; Hong et al.
2023) found azimuth and close axial spacing to be dominant physical effects that
the original design space's coarse grid had missed. Full rationale:
`analysis/stacked_rotor_literature_pivot_2026-07-15.md`.

| Variable | Values | Notes |
| --- | --- | --- |
| Axial spacing | 0.05, 0.10, 0.20, 0.35, 0.60 m | denser toward the close-spacing end |
| Azimuth angle | −90, −45, −20, −10, 0, 10, 20, 45, 90 deg | `run_sweep.py`'s default `DESIGN_SPACE_DUAL` grid; symmetric, denser near 0° |
| Lower rotor RPM | 524.1, 655.1, 786.1, 917.1, 1048.1 | Mach-derived (tip-Mach-based) |
| Upper rotor RPM | 900 (default, fixed) | overridable via `--rpm_upper` — see below |

Base case count: 5 × 9 × 5 = **225 co-rotating cases** at the default single
upper-RPM value (~38 min @ `--parallel 12`, ~2 min/case). Pass multiple
`--rpm_upper` values (e.g. `--rpm_upper 700 900 1100`) to build the varying-upper-RPM
dataset the MLP controller needs — see `ml_scripts/README_ML.md`.

### Current production dataset (1625 rows)

`co_rot_results.csv` as it stands is two combined runs against `DESIGN_SPACE_DUAL`'s
grid, both sweeping `rpm_upper` across all 5 Mach-derived values:

```bash
# Base grid: 5 spacing × 9 azimuth × 5 rpm_lower × 5 rpm_upper = 1125 cases
python3 cfd_scripts/run_sweep.py --dataset co_rot --parallel 12 \
    --rpm_upper 524.1 655.1 786.1 917.1 1048.1

# Azimuth-flank densification: bisects the four largest gaps in the azimuth grid
# (±45°/±90°), crossed with the full spacing/rpm_lower/rpm_upper grid = 500 more cases
python3 cfd_scripts/run_sweep.py --dataset co_rot --parallel 12 \
    --azimuth -67.5 -32.5 32.5 67.5 --rpm_upper 524.1 655.1 786.1 917.1 1048.1
```

Combined: **1625 rows**, 13 azimuth values (base 9 + 4 flank), 1593/1625 (98.0%)
`converged=True`. `CSV_HEADER_DUAL` also carries `spacing_inv_m` and
`azimuth_folded_deg` (physics-informed features), a graded `data_quality`
(`CONVERGED_TIGHT`/`CONVERGED`/`BORDERLINE`/`NOT_CONVERGED`) plus
`convergence_ratio`, and `mesh_diagnostic_flag` (`UNDER_RESOLVED_TIGHT_SPACING` on
every `spacing=0.10 m` row).

`co_rot_results.csv` supersedes an earlier 1125-row file generated before the
`addLayers` boundary-layer-mesh fix (see `run_sweep.py` below); do not train
against that superseded file.

Fixed: NACA 4412 airfoil, D = 1.0 m, 2 blades, P = 0.4 m (both rotors, same
pitch), CCW rotation, steady-state MRF (`simpleFoam`), k-ω SST.

**Spacing floor.** 0.05 m (`MRF_FEASIBLE_MIN_SPACING` in `run_sweep.py`) is a
*meshing* floor, not the physical one — the closest spacing the current
two-independent-MRF-cylinder method can mesh without the zones overlapping. The
true physical minimum (hub-to-hub collision) is 0.03 m; reaching it needs an
overset/AMI meshing rewrite, not yet attempted. Requesting a spacing below the
feasibility floor raises a `ValueError`.

### VR-12 literature-match sweep (`--dataset co_rot_vr12`, added 2026-07-21)

A second, separate co-rotating design space matching Jacobellis et al. (2021,
*Aerosp. Sci. Technol.* 116:106847) as closely as a NACA 4-digit blade allows, so
the azimuth-sensitivity trend can be checked against a paper using near-identical
hardware, not only this project's own (differently-scaled) `co_rot` dataset.

| Parameter | Value | Notes |
| --- | --- | --- |
| Diameter | 2.216 m (R=1.108 m) | Table 1 |
| Airfoil | NACA 2211 | closest 4-digit match to the real VR-12 section (see `VR12_NACA` in `run_sweep.py`) |
| Chord | 0.08 m constant, untwisted | vs. this project's default tapered blade |
| Root cutout | 18.76% R | |
| Collective | 12° constant | matches their primary CFD/experimental case |
| RPM (both rotors) | 1200, matched | index-angle sensitivity only comparable at matched RPM |
| Spacing | 0.12 m (z/c=1.5) | their densest tested spacing, z/c=0.73, falls below this project's MRF feasibility floor at VR-12 scale |
| Azimuth | −45, −28.125, −16.875, −11.25, −5.625, 0, 5.625, 11.25, 16.875, 28.125, 45, 90 deg | Table 2 @ z/c=1.5 |

```bash
python3 cfd_scripts/run_sweep.py --dataset co_rot_vr12 --parallel 12
```

Three diagnostics ran against an anomalous variance spike in `fom_total` at close
spacing: a mesh-sensitivity re-check (`--dataset co_rot_vr12_meshcheck` /
`co_rot_meshcheck`, found general under-resolution at close spacing, not an
azimuth artifact), a 3-level GCI study (`--dataset co_rot_vr12_gci_lvl45` /
`_lvl56`, via `analyze_gci_study_vr12.py`), and a time-integration check
(`--dataset co_rot_timecheck`). These are hand-run diagnostics, not part of
`dash.py`'s menu — see `run_sweep.py`'s `DATASETS` dict for exact invocations.

---

## OpenFOAM environment

- OpenFOAM 2412 on WSL2 (Ubuntu 22.04), Windows 11
- Solver: `simpleFoam` (steady-state RANS)
- Turbulence: k-ω SST
- Mesh: `blockMesh` outer domain → `snappyHexMesh` blade refinement → `topoSet` MRF zones
- Forces extracted from `postProcessing/forces*/0/force.dat` and `moment.dat`

### Rotor physics

Both rotors spin counter-clockwise (CCW) viewed from above — co-rotating only. Both
use identical NACA 4412 geometry at the same pitch (0.4 m). The lower rotor is
offset by the azimuth angle (index angle) and positioned at `UPPER_Z − spacing`.
Both produce positive-Z (upward) thrust.

---

## Dashboard

`dash.py` is the primary entry point. It must run with a WSL Python interpreter,
since it reads/writes the WSL-side OpenFOAM case directories and shells out to
OpenFOAM tools that only exist there. From a Windows PowerShell prompt in the
project root:

```powershell
wsl python3 dash.py
```

Or, already inside a WSL shell, from the project root:

```bash
python3 dash.py
```

Provides a live status panel and launches all scripts via a numbered menu without
needing to remember arguments or paths.

### Status panel sections

- **STL GEOMETRY** — checks whether each propeller STL has been generated in the WSL
  template case directories. Shows filename on the same line when present.
- **CFD SWEEPS** — progress bar for each sweep CSV (rows completed vs. expected total).
- **EDA / ANALYSIS** — counts PNG figures and summary CSV in each `results_*/` directory.
- **C-T VALIDATION** — four rows, split by geometry: `results_CT_validation_full/` and
  `_reduced` (650 RPM), plus `results_CT_appendixA_full/` and `_reduced` (1250 RPM).

### Menu actions

| # | Action | Purpose |
| --- | --- | --- |
| 1 | Generate propeller STL | Runs `generate_propeller.py` for any of the four rotor geometries (or a custom C-T collective angle) |
| 2 | Run CFD sweep | Presents 6 options: single-rotor (a), co-rot (b), C-T Reduced (c → RPM sub-menu), dry-run single (d), C-T Full dry-run (e), C-T Full (f → RPM sub-menu). For options a–b, when an existing CSV is found it prompts **Recalculate** or **Resume**. For c and f, a sub-menu first selects RPM (650 → 11 angles, 1250 → 3 angles) |
| 3 | Analyse sweep results | Runs `analyze_sweep.py`, `C-T_validation.py`, or `C-T_comparisonA.py` to produce figures and summary CSVs |
| 4 | Headline statistics | Reads existing CSVs and prints thrust range, FOM range, best case |
| 5 | Clean up | Full reset options — see below |
| q | Quit | Exits and writes SESSION END to output.txt |

### Clean-up system (menu 5)

Each sweep option is a **full blank-sheet reset** — it deletes everything generated
by that sweep so it can be re-run from scratch:

| Key | What is deleted |
| --- | --- |
| a | `log.*` files inside every case subdirectory (all sweeps) |
| b | Single-rotor: case dirs + `single_rotor_results.csv` + `propeller.stl` + `results_singleRotor/` |
| c | Co-rotating: case dirs + `co_rot_results.csv` + `upperPropeller.stl` / `lowerPropeller.stl` + `results_2_co_rot/` |
| d | C-T Full geometry: `theta*/` dirs in both `caradonnaTung_full_650rpm/` and `caradonnaTung_full_1250rpm/` + their CSVs + `results_CT_appendixA_full/` |
| e | C-T Reduced geometry: `theta*/` dirs in both `caradonnaTung_reduced_650rpm/` and `caradonnaTung_reduced_1250rpm/` + their CSVs + `results_CT_validation/` (stale path — see [Known issues](#known-issues--pitfalls)) |
| f | Trim `output.txt` to the last 100 lines |
| g | Delete all `__pycache__` directories |

Options b–e require typing `yes` to confirm and show disk usage and a list of every
item before deleting. Afterwards the dashboard header returns to all red crosses.

### Logging

`TeeLogger` replaces `sys.stdout` on startup so every line printed is simultaneously
written to `output.txt`, with ANSI colour stripped and `\r` overwrites collapsed.
No per-line timestamp (only the final `SESSION END` line has one).

---

## Scripts

### `generate_propeller.py`

Generates a 2-blade propeller as an ASCII STL. Supports any NACA 4-digit profile,
constant or tapered chord, and geometric twist or constant collective pitch.

The blade runs from `root_fraction × R` to `R` in the radial direction. Spanwise sections
are interpolated using the NACA camber and thickness equations, then stacked into triangular
facets and written as a named solid so `snappyHexMesh` can map the STL surface to a named
mesh patch.

```bash
# NACA 4412 single rotor
python3 cfd_scripts/generate_propeller.py \
  --pitch 0.4 --diameter 1.0 --rotor_z 5.0 \
  --solid_name upperPropeller \
  --output /path/to/upperPropeller.stl

# Caradonna-Tung validation blade (NACA 0012, θ=8°)
python3 cfd_scripts/generate_propeller.py \
  --naca 0012 --diameter 2.286 --chord 0.1905 \
  --collective 8 --root_fraction 0.20 --rotor_z 0.0 \
  --solid_name ctBlade \
  --output /path/to/ctBlade.stl
```

Key flags:

| Flag | Default | Purpose |
| --- | --- | --- |
| `--naca` | 4412 | Any NACA 4-digit profile |
| `--pitch` | 0.4 m | Geometric pitch → spanwise twist via arctan(P/2πr) |
| `--collective` | — | Constant blade angle [deg], overrides `--pitch` twist |
| `--chord` | tapered | Constant chord [m], overrides linear taper |
| `--root_fraction` | 0.30 | Root cutout as fraction of radius |
| `--mirror_y` | off | Mirror blade about X-Z plane (for a counter-rotating/CW rotor — kept for a future study) |
| `--azimuth_deg` | 0 | Index angle offset between upper and lower rotors |
| `--n_pts` | 50 | Chordwise profile points per span station; use 150 for smoother Cp |
| `--n_span` | 25 | Spanwise lofting stations |

---

### `run_sweep.py`

Runs the full OpenFOAM pipeline for each case in the single-rotor or co-rotating design
space (see [Design space](#design-space-co-rotating-coaxial-sweep) above). Cases run in
parallel using `ProcessPoolExecutor`; `--parallel` sets the worker count.

**Pipeline per case:**

1. `blockMesh` — builds a uniform hex background mesh for the outer domain
2. `snappyHexMesh` — refines the mesh around the blade STL surface and snaps to it
3. **promoteMesh** — copies `snappyHexMesh` output back to `constant/polyMesh`, filtering
   candidates to those actually containing a `polyMesh/` subdirectory (see
   [Known issues](#known-issues--pitfalls))
4. `topoSet` — marks the MRF rotating-zone cell set(s)
5. `simpleFoam` — steady RANS solver. `endTime` is 500 for single-rotor, 1500 (default)
   for dual-rotor datasets, overridable via `--end_time`

The script is idempotent: it reads the existing results CSV on startup and skips any case
whose `case_id` is already present. Kill and restart safely at any point.

```bash
# Single-rotor baseline (5 cases, ~6 min)
python3 cfd_scripts/run_sweep.py --dataset single --parallel 5

# Co-rotating sweep, default single upper-RPM (225 cases, ~38 min @ 12 workers)
python3 cfd_scripts/run_sweep.py --dataset co_rot --parallel 12

# Co-rotating sweep, varying upper RPM (for MLP training data — see ml_scripts/README_ML.md)
python3 cfd_scripts/run_sweep.py --dataset co_rot --parallel 12 --rpm_upper 700 900 1100

# Dry run — preview cases without running CFD
python3 cfd_scripts/run_sweep.py --dataset single --dry_run
```

Forces/moments are read from `postProcessing/forcesUpper/0/force.dat` and
`forcesLower/0/force.dat`; column 3 (0-indexed) is total-Z (thrust). Requesting a
spacing below `MRF_FEASIBLE_MIN_SPACING` (0.05 m) raises a `ValueError`.

---

### Non-convergence triage (`co_rot` only)

**Applies to the superseded 1125-row dataset, not the current 1625-row
`co_rot_results.csv`** (which computes `converged` per-row directly — only 32/1625
non-converged — and hasn't been run through this pipeline). Post-mortem on the
earlier 1125-case sweep found 294 cases (26%) hit the iteration cap without meeting
`fvSolution`'s residual tolerance. Four scripts, run in sequence, classify and
recover as much of that 26% as possible:

1. **`check_convergence.py`** — reads each case's `simpleFoam.log` and classifies
   capped-out cases by residual trend: `CONVERGED_RESIDUAL`, `SLOW`, `PLATEAU`, `DIVERGING`.

   ```bash
   python3 cfd_scripts/check_convergence.py --csv .../co_rot_results.csv --sweep_dir .../2_co_rot_sweep --out_csv convergence_check.csv
   ```

2. **`rerun_capped.py`** — for `SLOW` cases: a full clean rebuild at a higher
   `--new_endtime`. Supersedes `continue_run.py` (restart-from-`latestTime`), which
   hit an OpenFOAM field-size incompatibility.
3. **`extract_time_averaged.py`** — for `PLATEAU`/`DIVERGING` cases: reports a
   windowed time-average of the existing force/torque history instead of rerunning.
4. **`merge_final_dataset.py`** — consolidates original + rebuilt + time-averaged
   rows into one training CSV, asserting the row-accounting matches before writing
   anything. Its row-count assert still hard-codes the old 1125-row population — see
   [Known issues](#known-issues--pitfalls).

---

### `run_ct_sweep.py`

Runs the Caradonna-Tung validation sweep on a NACA 0012 hover rotor across multiple
collective angles. Supports two domain geometry presets selectable with `--geometry`.

**Geometry presets:**

| Preset | Radial extent | z range | MRF Δz | n_pts STL | Cell count |
| --- | --- | --- | --- | --- | --- |
| `full` (default) | ±22.86 m (10D) | −10.860 – 17.715 m (2.5D up/+z, 10D down/−z) | ±1.257 m | 150 | 114 × 114 × 96 |
| `reduced` | ±12 m (5.25D) | 0 – 24 m (symmetric) | ±0.60 m | 50 | 60 × 60 × 80 |

`full` matches Appendix A of Jeon & Lee (Aerospace 2025, 12, 940). `reduced` is the
original smaller domain, kept for comparison but de-prioritised.

**Fixed parameters (both presets):**

| Parameter | Value | Notes |
| --- | --- | --- |
| R | 1.143 m | C-T blade radius |
| c | 0.1905 m | constant chord, untapered |
| ω (650 RPM run) | 68.07 rad/s | Vtip = 78.2 m/s, Mtip = 0.228 |
| ω (1250 RPM run) | 130.90 rad/s | Vtip = 149.6 m/s, Mtip = 0.436 |
| MRF radius | 1.257 m | 1.1D/2, per Jeon & Lee Appendix A convention |
| Rotor z | 12.0 m | fixed in world frame regardless of preset |

**Pipeline per case** matches `run_sweep.py` plus `surfaceFeatureExtract` before
`snappyHexMesh` (feature-edge extraction for LE/TE mesh quality). `--parallel N`
runs N angles concurrently. Stale time directories from any previous run are
deleted before meshing begins each case.

Convergence is checked from the force time history (last 20% of points, std/mean ≤
2%). A near-zero-magnitude tail is only trusted as genuine convergence at θ=0°
(physically expected zero thrust); at every other angle it's flagged `NOT CONVERGED`
instead, since a degenerate all-zero signal there is more likely than real
convergence than the trend check alone can tell.

Results are appended to the target CSV as each angle completes; the script skips
`(angle, rpm, geometry)` combinations already present. If the target CSV predates
the rpm/geometry columns, it's migrated in place (header rewritten, existing rows
backfilled) before anything is appended.

```bash
# Full 11-angle sweep — full geometry, 650 RPM (default)
python3 cfd_scripts/run_ct_sweep.py \
  --geometry full \
  --sweep_dir /home/david/OpenFOAM/ENGR412/caradonnaTung_full_650rpm \
  --csv /home/david/OpenFOAM/ENGR412/caradonnaTung_full_650rpm/ct_results_full_650.csv

# Reduced geometry
python3 cfd_scripts/run_ct_sweep.py --geometry reduced

# 1250 RPM subset, run concurrently
python3 cfd_scripts/run_ct_sweep.py --geometry full --rpm 1250 \
  --angles 5 7 8 10 12 --parallel 5 \
  --sweep_dir /home/david/OpenFOAM/ENGR412/caradonnaTung_full_1250rpm \
  --csv /home/david/OpenFOAM/ENGR412/caradonnaTung_full_1250rpm/ct_results_full_1250.csv

# Mesh-convergence (GCI) study — see run_gci_study.sh below
python3 cfd_scripts/run_ct_sweep.py --angles 8 --blade_level 6 7 \
  --sweep_dir /home/david/OpenFOAM/ENGR412/gci_study/lvl_6_7 \
  --csv /home/david/OpenFOAM/ENGR412/gci_study/lvl_6_7/ct_results.csv

# Dry run — generate case files only, no solver
python3 cfd_scripts/run_ct_sweep.py --dry_run
```

> Without `--sweep_dir`/`--csv`, case data defaults to `caradonnaTung/` under the
> WSL OpenFOAM base directory. Every named sweep and `dash.py` menu path passes
> explicit `--sweep_dir`/`--csv` per geometry/RPM combination instead.

---

### `run_gci_study.sh` + `analyze_gci_study.py`

Three-resolution Grid Convergence Index study for the `full`-geometry C-T mesh,
following Celik, Ghia, Roache et al. (2008), ASME J. Fluids Eng. 130(7). Fixes the
physical case (θ=8°, 650 RPM by default) and varies only `--blade_level` (coarse
(4,5) → baseline (5,6) → fine (6,7), refinement ratio r=2).

```bash
bash cfd_scripts/run_gci_study.sh          # theta=8 (default)
bash cfd_scripts/run_gci_study.sh 12       # different angle

python3 cfd_scripts/analyze_gci_study.py --root /home/david/OpenFOAM/ENGR412/gci_study --angle 8
```

**Current result: inconclusive** — the three levels don't converge monotonically
(apparent order p ≈ −2.9); `analyze_gci_study.py` correctly refuses to report a GCI
percentage in this regime. Not pursued further — see
[Known issues](#known-issues--pitfalls).

Same procedure adapted for the co-rotating VR-12 dataset as
`analyze_gci_study_vr12.py` (`--base_csv`/`--lvl45_csv`/`--lvl56_csv` plus
`--spacing`/`--azimuth`) — see [VR-12 sweep](#vr-12-literature-match-sweep---dataset-co_rot_vr12-added-2026-07-21).

---

### `analyze_sweep.py`

Reads a sweep results CSV, computes dimensionless performance coefficients (CT, CP, PLnorm,
FOM), and writes figures and a summary CSV to the output directory.

**Coaxial mode** (default):

| Output | Description |
| --- | --- |
| `violin_PLnorm.png` | Violin plots of PLnorm vs each design variable (spacing, azimuth, lower RPM) |
| `thrust_decomp.png` | Stacked bar: mean upper / lower thrust contribution by axial spacing |
| `interaction_heatmap.png` | Mean FOM on a spacing × azimuth grid, revealing interaction effects |
| `correlation_matrix.png` | Pearson correlation between all design inputs and performance outputs |
| `convergence_hist.png` | Distribution of final iteration counts across all cases |
| `eda_summary.csv` | Per-group median, IQR, p5/p95, min, max |

**Single-rotor mode** (`--mode single`):

| Output | Description |
| --- | --- |
| `performance_grid.png` | 2×2 grid: thrust, FOM, and PLnorm vs RPM, plus CT-CP scatter |
| `convergence_hist.png` | Iteration count histogram |
| `eda_summary.csv` | Per-group statistics |

```bash
# Single-rotor EDA
python3 cfd_scripts/analyze_sweep.py \
  --mode single \
  --csv /home/david/OpenFOAM/ENGR412/1_single_rotor_sweep/single_rotor_results.csv \
  --outdir results_singleRotor

# Co-rotating EDA
python3 cfd_scripts/analyze_sweep.py \
  --csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results.csv \
  --outdir results_2_co_rot
```

---

### `C-T_validation.py`

Compares CFD results against Caradonna & Tung (1981) experimental hover data (650
RPM / Mtip = 0.228, 11 collective angles). Runs experimental-only (reference plots,
before CFD is ready) or with a `--cfd ct_results_*.csv` overlay, computing CT/CP via
the C-T normalisation (ρ A Vtip²/³). Expected agreement: CT underprediction ~3%
(Prandtl-Glauert factor ≈ 1.03).

**`--rpm` guard:** the script's `EXP_CT`/`EXP_CP` curves are only valid at its fixed
~653 RPM condition. `--rpm` (default: that condition) is checked against the
`--cfd` CSV's own `rpm` column; the run refuses to write a comparison on a mismatch
>2%. Old-format CSVs with no `rpm` column proceed with a warning instead.

**Pass a geometry-specific `--outdir`** — e.g. `results_CT_validation_full` vs.
`_reduced`. `validation_summary.csv` carries `geometry` and `generated_at` columns
so a file is self-identifying even outside its directory — see
[Known issues](#known-issues--pitfalls).

```bash
# Experimental reference only
python3 cfd_scripts/C-T_validation.py --outdir results_CT_validation_full

# With CFD overlay (full geometry, 650 RPM)
python3 cfd_scripts/C-T_validation.py \
  --cfd /home/david/OpenFOAM/ENGR412/caradonnaTung_full_650rpm/ct_results_full_650.csv \
  --outdir results_CT_validation_full
```

Output figures: `CT_vs_collective.png`, `CP_vs_collective.png`, `CT_CP_polar.png`,
`FOM_vs_collective.png`. `validation_summary.csv` columns: `collective_deg, CT_exp,
CT_cfd, CT_error_pct, FOM_exp, FOM_cfd, geometry, generated_at`.

---

### `C-T_comparisonA.py`

Reproduces Appendix A of Jeon & Lee (Aerospace 2025, 12, 940): CT at 1250 RPM
(Mtip≈0.436), collective 5°/8°/12° (plus any CFD-only angles present, e.g. 7°/10°,
plotted as trend points with no experimental counterpart). Produces a terminal
table and two figures.

**Pass a geometry-specific `--outdir`** — e.g. `results_CT_appendixA_full` vs.
`_reduced`; same fix and rationale as `C-T_validation.py` above.
`appendixA_summary.csv` carries `geometry` and `generated_at` columns. `dash.py`'s
"Comparison A" menu already passes the correct `--outdir`; this matters mainly for
direct/manual invocation.

```bash
# Auto-detects caradonnaTung_full_1250rpm/ct_results_full_1250.csv and theta5/ if present
python3 cfd_scripts/C-T_comparisonA.py --outdir results_CT_appendixA_full

# Explicit paths (e.g. for reduced geometry run)
python3 cfd_scripts/C-T_comparisonA.py \
  --cfd      /home/david/OpenFOAM/ENGR412/caradonnaTung_reduced_1250rpm/ct_results_reduced_1250.csv \
  --case_dir /home/david/OpenFOAM/ENGR412/caradonnaTung_reduced_1250rpm/theta5 \
  --outdir   results_CT_appendixA_reduced
```

Output figures: `CT_vs_collective_appendixA.png`, `Cp_sections_appendixA.png`
(5-panel −Cp vs x/c at r/R = 0.50/0.68/0.80/0.89/0.96, θ=5°). `appendixA_summary.csv`
columns: `collective_deg, CT_exp, CT_cfd, CT_error_pct, geometry, generated_at`.

---

## Performance metrics

| Metric | Formula | Notes |
| --- | --- | --- |
| CT | T / (ρ n² D⁴) | thrust coefficient (sweep convention) |
| CP | P / (ρ n³ D⁵) | power coefficient (sweep convention) |
| CT (C-T) | T / (ρ A Vtip²) | Caradonna-Tung normalisation |
| CP (C-T) | P / (ρ A Vtip³) | Caradonna-Tung normalisation |
| PLnorm | CT / CP | normalised power loading — primary optimisation target |
| FOM | T √(T/2ρA) / P | figure of merit (actuator disk efficiency ratio) |

---

## Caradonna-Tung validation

Validates the MRF + simpleFoam pipeline against published experimental hover data —
a solver/mesh sanity check, not the project's primary validation target (that role
belongs to the co-rotating sweep; see `analysis/stacked_rotor_literature_pivot_2026-07-15.md`).

- Reference: Caradonna & Tung (1981), NASA TM-81232
- Geometry: NACA 0012, R = 1.143 m, c = 0.1905 m, untwisted, 2 blades, σ = 0.1061
- Coefficient convention: CT = T/(ρ A Vtip²), CP = P/(ρ A Vtip³)

Two test conditions are run:

| RPM | ω [rad/s] | Vtip [m/s] | Mtip | Angles | Script |
| --- | --- | --- | --- | --- | --- |
| ~650 | 68.07 | 78.2 | 0.228 | 0°–12° (11 points) | `C-T_validation.py` |
| 1250 | 130.90 | 149.6 | 0.436 | 5°, 8°, 12° (+ 7°, 10° CFD-only when present) | `C-T_comparisonA.py` |

Compressibility note: `simpleFoam` is incompressible. Expected underprediction ~3%
at Mtip=0.228, ~10% at Mtip=0.436 (real blades also stall at high collective, so
scatter is larger there). Plots show a PG correction band below the experimental
curve.

**Current results (re-verified 2026-08-07):**

| Geometry | RPM | Mean \|CT error\| | Per-angle | Output |
| --- | --- | --- | --- | --- |
| full | 650 | **19.5%** | (11/11 angles) | `results_CT_validation_full/` |
| reduced | 650 | 23.2% | (11/11 angles) | `results_CT_validation_reduced/` |
| full | 1250 | **50.0%** | 122.0%/22.8%/5.1% at 5°/8°/12° | `results_CT_appendixA_full/` |
| reduced | 1250 | 77.1% | 119.7%/83.3%/28.4% at 5°/8°/12° | `results_CT_appendixA_reduced/` |

An older archived 650 RPM result (`caradonnaTung_full_650rpm_tier1/`) sits at 22.4%,
judged an acceptable baseline for this project's scope after a GCI study showed
diminishing/inconclusive returns from further mesh refinement — see
`analysis/stacked_rotor_literature_pivot_2026-07-15.md`. A structured (O-grid/C-grid)
mesh rewrite was scoped (`analysis/structured_mesh_followup_2026-07-14.md`) but
dropped in favour of the co-rotating sweep.

---

## Known issues / pitfalls

### `co_rot_results.csv` doesn't exist — data is under a different filename

Canonical `2_co_rot_sweep/co_rot_results.csv` (assumed by `ml_scripts/README_ML.md`
and `dash.py`'s default paths) doesn't currently exist on WSL; the real
1625-row/98.0%-converged data is confirmed to be `co_rot_results2.csv`. Point any
`--csv` flag at that file explicitly until the canonical name is restored —
`dash.py`'s status panel and `run_sweep.py --dataset co_rot`'s resume logic both
misreport against the missing canonical name. Several other similarly-named
intermediates also exist in `2_co_rot_sweep/`; not itemized here. Not fixed —
renaming touches live WSL data outside a documentation pass's scope.

### promoteMesh stale-directory bug (fixed)

Leftover `simpleFoam` time directories from a previous run could outrank a fresh
`snappyHexMesh` output directory when selecting what to promote to
`constant/polyMesh`, silently running the solver on an unrefined mesh with no
blade patch. **Fixed** in both `run_sweep.py` and `run_ct_sweep.py`: candidate
directories are now filtered to those actually containing `polyMesh/`;
`run_ct_sweep.py` additionally deletes stale time directories at the start of each
case setup.

### Launching from native Windows Python instead of WSL (fixed 2026-07-30)

A native Windows Python interpreter can't run this pipeline: Unicode in progress
output crashes on the default cp1252 console codepage, and `/home/...`-style paths
get silently reinterpreted as Windows paths. `run_ct_sweep.py` now forces UTF-8
stdout/stderr, but always launch via `wsl python3 dash.py` (Windows terminal) or
`python3 dash.py` (inside WSL) — there's no code fix for the path-mismatch half.

### RPM/geometry mislabeling in `C-T_validation.py` / `C-T_comparisonA.py` (fixed 2026-08-07)

Two bugs, now fixed: (1) `C-T_validation.py` had no RPM awareness and would
silently compare a 1250 RPM CFD CSV against its fixed 650-RPM-condition curve,
producing nonsense error percentages — fixed with the `--rpm` guard described
under [`C-T_validation.py`](#c-t_validationpy) above. (2) both comparison scripts
shared one unlabeled output path across full/reduced geometry, so a later run could
silently overwrite an earlier geometry's result with nothing recording which was
which — fixed with mandatory geometry-specific `--outdir`s and `geometry`/
`generated_at` CSV columns.

This is also what produced a previously-reported "61.3% regression" at 1250 RPM
full geometry — that figure was in fact the already-documented `nGrow=1` dead end
(see `N_GROW` in `run_ct_sweep.py`), read from a stale archived directory via the
unlabeled shared path rather than the live pipeline state. The current,
correctly-labeled result is 50.0% (matching the pre-regression baseline exactly) —
see [Caradonna-Tung validation](#caradonna-tung-validation) for the full table.
No CFD/mesh regression occurred; only the reporting was wrong.

Two mesh-accuracy notes unrelated to the bug above, still relevant to future work:
domain/cell budget already matches or exceeds Jeon & Lee's reference (the real gap
is near-wall treatment, y+≈228–346 vs. their y+<1); and 4–16% of blade faces near
the LE/root/tip get zero prism layers, a genuinely untried lever distinct from the
average-y+ shortfall (a uniform refinement bump already achieved the 61.5%→50.0%
improvement above and diminishing-returns'd out; `nGrow=1` was tried for this
specific lever and reverted).

### `dash.py`'s 1250 RPM angle set doesn't match `C-T_comparisonA.py`'s 5-angle support

The dashboard's "C-T sweep" sub-menu only launches a 3-angle 1250 RPM sweep
(5°/8°/12°); `C-T_comparisonA.py` itself supports plotting extra CFD-only angles
(7°/10°). A hand-launched `run_ct_sweep.py --angles 5 7 8 10 12 ...` gets the full
benefit; the dashboard's menu 2 → f → b path does not.

### Analysis scripts default to a relative `--outdir`

`analyze_sweep.py`, `C-T_validation.py`, and `C-T_comparisonA.py` all write into
`--outdir` relative to the current working directory. Run them from the git repo
root (as `dash.py` always does) — running by hand from a WSL working directory
under `/home/david/OpenFOAM/ENGR412/` instead silently creates a `results_*/`
directory there.

### `merge_final_dataset.py`'s `data_quality` column collision (fixed 2026-07-30)

`run_sweep.py`'s `CSV_HEADER_DUAL` gained its own `data_quality` column after
`merge_final_dataset.py` was already using that name for its own merge-tier label,
causing a silent overwrite. **Fixed:** this script's two output columns are now
`merge_quality`/`merge_quality_detail`, distinct from `CSV_HEADER_DUAL`'s per-row
`data_quality`. **Still open:** the script's row-accounting assert
(`831 + ... = 1125`) still hard-codes the old 1125-row population and refuses to
run against the current 1625-row file until updated.

### Root-directory housekeeping

`co_rot_full_run.log` is tracked in git despite `.gitignore` excluding
`output.txt` for the same reason (likely an oversight). Two
`412_Report_Cronin_DRAFT1_v*.docx` report drafts are untracked at the repo root
with no `.gitignore` rule excluding `.docx` — a broad `git add` would sweep them
into a commit.

---

## Dependencies (WSL Python)

```bash
sudo apt install python3-pip -y
pip3 install numpy pandas matplotlib seaborn scipy
```

`ml_scripts/` additionally needs `scikit-learn`:

```bash
pip3 install scikit-learn
```

VS Code: use the **Remote - WSL** extension (`ms-vscode-remote.remote-wsl`) and open
the project from inside WSL so the Python extension resolves packages correctly.

---

## History

Chronological investigation log — each entry links the full write-up; this section is a
pointer index, not a replacement for reading them.

- **2026-07-12 — Domain-orientation bug.** Spurious θ=0° thrust traced to the C-T
  `full` preset's domain z-extent being backwards relative to the wake; fixed
  alongside three related mesh/geometry bugs.
  `analysis/summary_domain_orientation_fix_2026-07-12.md`
- **2026-07-13 — Tier-1 pipeline hardening.** Added a force-history-based
  convergence check and doubled `END_TIME` after finding cases still settling at
  the old cutoff.
- **2026-07-14 — Mesh-convergence harness + structured-mesh scoping.** Added GCI
  CLI overrides to `run_ct_sweep.py`; scoped (but did not build) a structured
  O-grid/C-grid mesh replacement.
  `analysis/structured_mesh_followup_2026-07-14.md`
- **2026-07-15 — Literature pivot.** Found the actual C-T benchmark paper doesn't
  use an O-grid either; combined with an inconclusive GCI result, dropped the
  structured-mesh rewrite and redirected validation effort to the co-rotating
  sweep, whose design space was found to have missed the close-spacing/near-zero-azimuth regime.
  `analysis/stacked_rotor_literature_pivot_2026-07-15.md`
