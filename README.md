# ENGR412 — Coaxial Rotor Thrust Optimisation

Concordia University Independent Study. OpenFOAM CFD characterises a co-rotating
coaxial rotor pair and builds a training dataset for an MLP-based lower-rotor
controller: given the upper rotor's commanded RPM, the controller outputs the
lower rotor's RPM, axial spacing, and azimuthal (index) angle that maximise total
thrust. A separate Caradonna-Tung hover-rotor validation case sanity-checks the
solver/mesh pipeline against published experimental data.

Two active branches: `main` carries the CFD sweep pipeline and C-T validation;
`mlp-lower-rotor-control`'s work (the `ml_scripts/` package — surrogate model, policy
extraction, embeddable controller) has been merged into `main` and is documented
separately in `ml_scripts/README_ML.md`.

---

## Project status (as of 2026-07-30)

| Component | State |
| --- | --- |
| Single-rotor baseline sweep | data cleared — re-run pending (`run_sweep.py --dataset single`) |
| Co-rotating coaxial sweep | **1625 cases complete**, `co_rot_results.csv` — the original 1125-case grid (5 spacing × 9 azimuth × 5 Mach-derived rpm_lower × 5 Mach-derived rpm_upper) plus 500 cases densifying the azimuth grid's sparse ±45°/±90° flanks (4 new azimuth values × the full spacing/rpm_lower/rpm_upper grid). **1593/1625 (98.0%) `converged=True`**, computed per-row from a real tail-window residual check. See [Design space](#design-space-co-rotating-coaxial-sweep) for the full current grid and the new per-row quality columns; see `PROJECT_STATE_17.md` (WSL, untracked — check for a higher-numbered `PROJECT_STATE_N.md` if this reference looks stale) for the live status log this table is reconciled against |
| Co-rotating mesh-sensitivity / time-integration diagnostics | complete (3/3 cases each) for `co_rot_meshcheck` and `co_rot_timecheck` — found `fom_total` moves 20–99% under mesh refinement at tight spacing, a general under-resolution rather than an isolated azimuth artifact; every `spacing=0.10 m` row in `co_rot_results.csv` now carries `mesh_diagnostic_flag=UNDER_RESOLVED_TIGHT_SPACING` as a result |
| VR-12 literature-match sweep (`co_rot_vr12`) | complete (12/12 azimuth points) — see [VR-12 literature-match sweep](#vr-12-literature-match-sweep---dataset-co_rot_vr12-added-2026-07-21) |
| VR-12 mesh-sensitivity / GCI diagnostics | complete (3/3 meshcheck cases; 1/1 case at each of GCI levels (4,5)/(5,6), reusing `co_rot_vr12` as level (3,4)) |
| C-T validation — full geometry, 650 RPM | data cleared — re-run pending. The two launch failures that blocked this (see below) are now both diagnosed/fixed, but the re-run itself hasn't happened yet — see [C-T validation: re-run pending](#c-t-validation-on-disk-results-currently-cleared-re-run-pending) in Known issues for the mesh-tightened error figures this blocks |
| C-T validation — full geometry, 1250 RPM | results CSV exists but is empty — same re-run-pending status as above. The last two launch attempts failed on a Windows-console Unicode crash and a Windows-vs-WSL Python/path mismatch (both fixed — see [Known issues](#launching-from-native-windows-python-instead-of-wsl-fixed-2026-07-30)) |
| C-T validation — reduced geometry, 650 RPM | **in progress** — an 11-angle sweep (`theta0`…`theta12`) was launched via `dash.py` on 2026-07-30; as of last check all 11 cases had started concurrently with none yet complete. De-prioritised as a validation target since the 2026-07-15 literature pivot (see [Known issues](#gci-mesh-study-is-inconclusive-not-pursued-further)) — this run does not change that prioritisation |
| C-T validation — reduced geometry, 1250 RPM | data cleared — de-prioritised, see [Known issues](#known-issues--pitfalls) |
| GCI mesh-convergence study (θ=8°, full/650) | complete — **inconclusive** (oscillatory convergence at the finest level tested) |
| MLP lower-rotor controller (`ml_scripts/`) | scaffolded; `ml_scripts/README_ML.md` refreshed 2026-07-30 against `PROJECT_STATE_17.md` (1625-case dataset, resolved azimuth question, decided objective) — but the code fixes described in that log live in the separate `mlp-lower-rotor-control` worktree, not in `ml_scripts/` itself; see that file's "Known gaps" section |

A prior complete 650 RPM / full-geometry result is archived at
`caradonnaTung_full_650rpm_tier1/ct_results_full_650.csv` (11/11 angles, mean
|CT error| 22.4%) — kept for reference; it is not the path `dash.py` currently
tracks, since a further design-space/mesh revision means it will be superseded by
the next full re-run rather than resumed in place. A 1250 RPM archive also exists at
`caradonnaTung_full_1250rpm_tier1/`.

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
├── results_CT_validation/          # C-T validation figures + summary (650 RPM)
└── results_CT_appendixA/           # C-T Appendix A figures + summary (1250 RPM)
```

`wsl_backfill_clean_v2.py` and `wsl_patch_items_4_5.sh` (one-shot data-migration scripts,
already applied to `run_sweep.py` / the `co_rot` CSV) have been removed (2026-08-03) —
git history preserves them if ever needed. Both were confirmed dead before removal:
`wsl_backfill_clean_v2.py` targeted the `co_rot_results_CLEAN`/`CLEAN_v2` file lineage,
which no longer exists (`run_sweep.py` now computes those same columns natively per-row
during the sweep); `wsl_patch_items_4_5.sh` self-patched `run_sweep.py`'s source via
exact string match, and its target strings no longer match the current file (the column
order it expects was later manually reordered — see §2.35-equivalent history) — re-running
it today would fail its own assertions.

CFD case data lives on the WSL filesystem (not tracked in git):

```text
/home/david/OpenFOAM/ENGR412/
├── singleRotor/                        # single-rotor template case
├── coaxialRotor/                       # coaxial template case
├── caradonnaTung_full_650rpm/          # C-T full geometry, 650 RPM  (11 angles)
├── caradonnaTung_full_1250rpm/         # C-T full geometry, 1250 RPM (5 angles: 5/7/8/10/12°)
├── caradonnaTung_reduced_650rpm/       # C-T reduced geometry, 650 RPM
├── caradonnaTung_reduced_1250rpm/      # C-T reduced geometry, 1250 RPM
├── caradonnaTung_full_650rpm_tier1/    # archived complete 650 RPM result (see status table)
├── caradonnaTung_full_1250rpm_tier1/   # archived 1250 RPM result (see status table)
├── coaxialRotor_vr12/                  # VR-12 geometry template (D=2.216 m, Jacobellis et al. 2021)
├── coaxialRotor_vr12_meshcheck/        # VR-12 mesh-sensitivity template (finer snappyHexMeshDict)
├── coaxialRotor_vr12_gci_lvl45/        # VR-12 GCI series, level (4,5)
├── coaxialRotor_vr12_gci_lvl56/        # VR-12 GCI series, level (5,6)  — lvl(3,4) reuses coaxialRotor_vr12
├── coaxialRotor_meshcheck/             # full-scale (D=1.0 m) mesh-sensitivity template
├── gci_study/                         # lvl_4_5 / lvl_5_6 / lvl_6_7 mesh-convergence cases (C-T)
├── 1_single_rotor_sweep/              # single-rotor design-space cases
│   └── single_rotor_results.csv
├── 2_co_rot_sweep/                    # co-rotating design-space cases
│   └── co_rot_results.csv
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

The co_rot production sweep also has a set of case-triage intermediate CSVs living
alongside `co_rot_results.csv` in `2_co_rot_sweep/` (convergence classification,
rebuilt/time-averaged results for non-converged cases, and a final merged training
CSV) — produced by `check_convergence.py` → `rerun_capped.py`/`extract_time_averaged.py`
→ `merge_final_dataset.py`, see [Scripts](#scripts) below. These are workflow
intermediates, not part of the tracked repo layout above.

---

## Design space (co-rotating coaxial sweep)

Revised 2026-07-15 after a literature check (Jacobellis et al. 2021; Hong et al.
2023) found azimuth and close axial spacing to be *dominant* physical effects on
stacked-rotor performance — directly contradicting an earlier EDA that found
azimuth "negligible." That result was traced to the design space itself: the old
spacing range (0.20–0.60 m) and coarse, one-sided azimuth grid (0–90°, 15°
steps) missed the close-spacing/near-zero-azimuth region where the interaction
physics is strongest. Full rationale: `analysis/stacked_rotor_literature_pivot_2026-07-15.md`.

| Variable | Values | Notes |
| --- | --- | --- |
| Axial spacing | 0.05, 0.10, 0.20, 0.35, 0.60 m | denser toward the close-spacing end |
| Azimuth angle | −90, −45, −20, −10, 0, 10, 20, 45, 90 deg | `run_sweep.py`'s default `DESIGN_SPACE_DUAL` grid; symmetric, denser near 0° |
| Lower rotor RPM | 524.1, 655.1, 786.1, 917.1, 1048.1 | Mach-derived (tip-Mach-based), not the old fixed {600,750,900,1050,1200} grid |
| Upper rotor RPM | 900 (default, fixed) | overridable via `--rpm_upper` — see below |

Base case count: 5 × 9 × 5 = **225 co-rotating cases** at the default single
upper-RPM value (~38 min @ `--parallel 12`, ~2 min/case). Pass multiple
`--rpm_upper` values (e.g. `--rpm_upper 700 900 1100`) to build the varying-upper-RPM
dataset the MLP controller needs; this multiplies the case count accordingly —
see `ml_scripts/README_ML.md` for how that dataset is consumed.

### Current production dataset (1625 rows)

`co_rot_results.csv` as it stands is **not** just the 225-case base grid — it's two
combined runs, both against `DESIGN_SPACE_DUAL`'s spacing/rpm grid above but sweeping
`rpm_upper` across all 5 Mach-derived values (not just the single 900 default):

```bash
# Base grid: 5 spacing × 9 azimuth × 5 rpm_lower × 5 rpm_upper = 1125 cases
python3 cfd_scripts/run_sweep.py --dataset co_rot --parallel 12 \
    --rpm_upper 524.1 655.1 786.1 917.1 1048.1

# Azimuth-flank densification: bisects the four largest gaps in the azimuth grid
# (±45°/±90°), crossed with the full spacing/rpm_lower/rpm_upper grid = 500 more cases
python3 cfd_scripts/run_sweep.py --dataset co_rot --parallel 12 \
    --azimuth -67.5 -32.5 32.5 67.5 --rpm_upper 524.1 655.1 786.1 917.1 1048.1
```

Combined: **1625 rows**, azimuth ∈ {−90, −67.5, −45, −32.5, −20, −10, 0, +10, +20,
+32.5, +45, +67.5, +90}° (13 values), 1625 unique `case_id`s, 1593/1625 (98.0%)
`converged=True`. `CSV_HEADER_DUAL` also carries, beyond the original performance
columns: `spacing_inv_m` and `azimuth_folded_deg` (physics-informed features —
1/spacing for Biot-Savart falloff, azimuth mod 180° for the confirmed 2-blade
periodicity), a graded `data_quality` (`CONVERGED_TIGHT`/`CONVERGED`/`BORDERLINE`/
`NOT_CONVERGED`) plus `convergence_ratio` (the raw tail-window ratio, not just the
threshold classification), and `mesh_diagnostic_flag` (`UNDER_RESOLVED_TIGHT_SPACING`
on every `spacing=0.10 m` row — see the mesh-sensitivity diagnostics below). The
flank-densification run's 500 new rows converged at a slightly lower rate (97.4%)
than the original grid (98.3%), consistent with sitting in a previously
least-validated region rather than a new problem.

`co_rot_results.csv` supersedes an earlier 1125-row file generated before the
`addLayers` boundary-layer-mesh fix (see `run_sweep.py` under [Scripts](#scripts)
below); do not train against that superseded file going forward.

Fixed: NACA 4412 airfoil, D = 1.0 m, 2 blades, P = 0.4 m (both rotors, same
pitch), CCW rotation, steady-state MRF (`simpleFoam`), k-ω SST.

**Spacing floor.** 0.05 m (`MRF_FEASIBLE_MIN_SPACING` in `run_sweep.py`) is a
*meshing* floor, not the physical one — it's the closest spacing the current
two-independent-MRF-cylinder method can mesh without the zones overlapping or
going degenerately thin. The true physical minimum (hub-to-hub collision, hub
depth = 0.03·D) is 0.03 m; reaching between 0.03 and 0.05 m needs an overset/AMI
rewrite of the dual-rotor meshing approach, not yet attempted. Requesting a
spacing below the feasibility floor raises a `ValueError` rather than silently
meshing an invalid zone.

### VR-12 literature-match sweep (`--dataset co_rot_vr12`, added 2026-07-21)

A second, separate co-rotating design space matching the geometry and operating point
of Jacobellis et al. (2021, *Aerosp. Sci. Technol.* 116:106847) as closely as a NACA
4-digit blade allows, so the azimuth-sensitivity trend can be checked directly against
a paper that used near-identical hardware, rather than only against this project's own
(differently-scaled) `co_rot` dataset.

| Parameter | Value | Notes |
| --- | --- | --- |
| Diameter | 2.216 m (R=1.108 m) | Table 1 |
| Airfoil | NACA 2211 | closest 4-digit match to the real VR-12 section (see `VR12_NACA` in `run_sweep.py`) |
| Chord | 0.08 m constant, untwisted | vs. this project's default tapered blade |
| Root cutout | 18.76% R | |
| Collective | 12° constant | matches their primary CFD/experimental case |
| RPM (both rotors) | 1200, matched | index-angle sensitivity is only comparable to their result at matched RPM |
| Spacing | 0.12 m (z/c=1.5) | their densest tested spacing, z/c=0.73, falls below this project's MRF feasibility floor at VR-12 scale |
| Azimuth | −45, −28.125, −16.875, −11.25, −5.625, 0, 5.625, 11.25, 16.875, 28.125, 45, 90 deg | Table 2 @ z/c=1.5 |

```bash
python3 cfd_scripts/run_sweep.py --dataset co_rot_vr12 --parallel 12
```

Two diagnostics were run against this dataset once an anomalous variance spike showed
up in `fom_total` at close spacing:

- **Mesh-sensitivity check** (`--dataset co_rot_vr12_meshcheck`, and its full-scale
  `co_rot` counterpart `--dataset co_rot_meshcheck`) — same case(s) re-meshed at a
  refined `snappyHexMeshDict`. Found `fom_total` moves 20–99% under refinement at
  every tight-spacing point tested — a general under-resolution at close spacing, not
  an isolated azimuth artifact.
- **GCI mesh-convergence series** (`--dataset co_rot_vr12_gci_lvl45` /
  `co_rot_vr12_gci_lvl56`, analysed by `cfd_scripts/analyze_gci_study_vr12.py`) — a proper
  3-level Celik et al. (2008) study at the same fixed case, reusing the existing
  `co_rot_vr12` run as the coarsest (3,4) level.
- **Time-integration check** (`--dataset co_rot_timecheck`) — same question, testing
  extended `endTime` instead of mesh resolution, on the full-scale `co_rot` mesh.

These four are hand-run diagnostics, not part of `dash.py`'s menu — see `run_sweep.py`'s
`DATASETS` dict for exact invocations.

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

Provides a live status panel and launches all scripts via a numbered menu without needing
to remember arguments or paths.

### Status panel sections

- **STL GEOMETRY** — checks whether each propeller STL has been generated in the WSL
  template case directories. Shows filename on the same line when present.
- **CFD SWEEPS** — progress bar for each sweep CSV (rows completed vs. expected total).
- **EDA / ANALYSIS** — counts PNG figures and summary CSV in each `results_*/` directory.
- **C-T VALIDATION** — two rows: `results_CT_validation/` (650 RPM) and
  `results_CT_appendixA/` (1250 RPM Appendix A).

### Menu actions

| # | Action | Purpose |
| --- | --- | --- |
| 1 | Generate propeller STL | Runs `generate_propeller.py` for any of the four rotor geometries (or a custom C-T collective angle) |
| 2 | Run CFD sweep | Presents 6 options: single-rotor (a), co-rot (b), C-T Reduced (c → RPM sub-menu), dry-run single (d), C-T Full dry-run (e), C-T Full (f → RPM sub-menu). For options a–b, when an existing CSV is found it prompts **Recalculate** or **Resume**. For c and f, a sub-menu first selects RPM (650 → 11 angles, 1250 → 3 angles) |
| 3 | Analyse sweep results | Runs `analyze_sweep.py`, `C-T_validation.py`, or `C-T_comparisonA.py` to produce figures and summary CSVs |
| 4 | Headline statistics | Reads existing CSVs and prints thrust range, FOM range, best case |
| 5 | Clean up | Full reset options — see below |
| q | Quit | Exits and writes SESSION END to output.txt |

> **Known drift:** the currently-running 1250 RPM sweep (see status table) uses 5
> angles (5°/7°/8°/10°/12°, matching `C-T_comparisonA.py`'s CFD-only-angle support);
> the dashboard's own "C-T sweep" sub-menu still launches the older 3-angle set
> (5°/8°/12°). Reconcile before relying on the dashboard's row-count expectations
> for the 1250 RPM case.

### Clean-up system (menu 5)

Each sweep option is a **full blank-sheet reset** — it deletes everything generated by that sweep so it can be re-run from scratch:

| Key | What is deleted |
| --- | --- |
| a | `log.*` files inside every case subdirectory (all sweeps) |
| b | Single-rotor: case dirs + `single_rotor_results.csv` + `propeller.stl` + `results_singleRotor/` |
| c | Co-rotating: case dirs + `co_rot_results.csv` + `upperPropeller.stl` / `lowerPropeller.stl` + `results_2_co_rot/` |
| d | C-T Full geometry: `theta*/` dirs in both `caradonnaTung_full_650rpm/` and `caradonnaTung_full_1250rpm/` + their CSVs + `results_CT_appendixA/` |
| e | C-T Reduced geometry: `theta*/` dirs in both `caradonnaTung_reduced_650rpm/` and `caradonnaTung_reduced_1250rpm/` + their CSVs + `results_CT_validation/` |
| f | Trim `output.txt` to the last 100 lines |
| g | Delete all `__pycache__` directories |

Options b–e require typing `yes` to confirm and show disk usage and a list of every item
(with present/absent status) before deleting. Afterwards the dashboard header returns to
all red crosses.

### Logging

`TeeLogger` replaces `sys.stdout` on startup so every line printed by the dashboard or
any launched script is simultaneously written to `output.txt` with an ISO timestamp prefix.
ANSI colour codes are stripped before writing. Carriage-return overwrites (`\r`) are
collapsed so the file shows only the final state of each terminal line.

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
| `--mirror_y` | off | Mirror blade about X-Z plane (for a counter-rotating/CW rotor — not used by the current co-rotating-only design space, kept for a future counter-rotating study) |
| `--azimuth_deg` | 0 | Index angle offset between upper and lower rotors |
| `--n_pts` | 50 | Chordwise profile points per span station; use 150 for smoother Cp |
| `--n_span` | 25 | Spanwise lofting stations |

---

### `run_sweep.py`

Runs the full OpenFOAM pipeline for each case in the single-rotor or co-rotating design
space (see [Design space](#design-space-co-rotating-coaxial-sweep) above for the current
grid). Cases run in parallel using `ProcessPoolExecutor`; the `--parallel` flag sets the
worker count.

**Pipeline per case:**

1. `blockMesh` — builds a uniform hex background mesh for the outer domain
2. `snappyHexMesh` — refines the mesh around the blade STL surface and snaps to it
3. **promoteMesh** — copies `snappyHexMesh` output from its numbered time directory back to
   `constant/polyMesh`, filtering candidates to those that actually contain a `polyMesh/`
   subdirectory (see [Known issues](#known-issues--pitfalls))
4. `topoSet` — marks the MRF rotating-zone cell set(s)
5. `simpleFoam` — steady RANS solver. `endTime` is hardcoded to 500 for the single-rotor
   dataset; dual-rotor datasets (co_rot and its VR-12/diagnostic siblings) default to
   1500, overridable via `--end_time` (raised from an original hardcoded 500 after triage
   found a meaningful fraction of co_rot cases needed more room — see
   [Non-convergence triage](#non-convergence-triage-co_rot-only) below)

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

Forces and moments are read from `postProcessing/forcesUpper/0/force.dat` and
`postProcessing/forcesLower/0/force.dat`. Column 3 (0-indexed) is the total-Z component,
which equals thrust for the upward-pointing rotor axis.

Requesting a spacing below `MRF_FEASIBLE_MIN_SPACING` (0.05 m) raises a `ValueError` —
see [Design space](#design-space-co-rotating-coaxial-sweep).

---

### Non-convergence triage (`co_rot` only)

**Applies to the superseded 1125-row dataset, not the current 1625-row
`co_rot_results.csv`.** Post-mortem on that earlier `co_rot` production sweep (5
rpm_upper values × 225 base cases, generated before the `addLayers` boundary-layer-mesh
fix — see `run_sweep.py` below) found 294 cases (26%) hit the 500-iteration cap without
meeting `fvSolution`'s residual tolerance. These five scripts, run in sequence, classify
and recover as much of that 26% as possible without discarding it outright or blindly
re-running from scratch. The current `co_rot_results.csv` computes `converged` directly
per-row (only 32/1625, 2.0%, non-converged) and has **not** been run through this triage
pipeline — see [Current production dataset](#current-production-dataset-1625-rows)
above and `merge_final_dataset.py`'s note below for why (its row-accounting assert still
hard-codes the old 1125-row population).

1. **`check_convergence.py`** — reads each case's `simpleFoam.log` directly (no CSV
   dependency) and classifies capped-out cases by residual trend over a windowed
   (geometric-mean) comparison: `CONVERGED_RESIDUAL` (already under tolerance despite
   hitting the cap), `SLOW` (still meaningfully decreasing — a longer run will likely
   help), `PLATEAU` (flat — more iterations won't help), `DIVERGING` (getting worse).

   ```bash
   python3 cfd_scripts/check_convergence.py --csv .../co_rot_results.csv --sweep_dir .../2_co_rot_sweep --out_csv convergence_check.csv
   ```

2. **`rerun_capped.py`** — for `SLOW` cases: a full clean rebuild (fresh mesh + fresh
   `0/` fields, not a restart) at a higher `--new_endtime`, reusing `run_sweep.py`'s own
   `run_case()` so the output is byte-compatible with the original CSV. Supersedes
   `continue_run.py` (restart-from-`latestTime`), which hit an OpenFOAM restart field-size
   incompatibility in practice.
3. **`extract_time_averaged.py`** — for `PLATEAU`/`DIVERGING` cases that don't respond to
   more iterations: treats the existing (already-written) force/torque history as a
   quasi-periodic signal and reports a windowed time-average instead of a single
   last-iteration snapshot. No rerun needed.
4. **`merge_final_dataset.py`** — consolidates original + rebuilt + time-averaged rows
   into one final training CSV, asserting the row-accounting matches exactly (831
   original-converged + rebuilt-converged + time-averaged = 1125) before writing
   anything, so a bug here can't silently corrupt the training set.
   > **Note:** the `data_quality` column collision found 2026-07-30 (see
   > [Known issues](#known-issues--pitfalls) below) was fixed the same day — this
   > script's merge-tier columns are now `merge_quality`/`merge_quality_detail`,
   > distinct from `CSV_HEADER_DUAL`'s per-row `data_quality`. Separately, this
   > script's own row-accounting assert (831+...=1125) still assumes the original
   > 1125-row `co_rot_results.csv` and has NOT been updated for the current 1625-row
   > file — it will refuse to run against it until that's addressed.

`continue_run.py` is superseded by `rerun_capped.py` (kept for the restart-incompatibility
context, not for active use).

---

### `run_ct_sweep.py`

Runs the Caradonna-Tung validation sweep on a NACA 0012 hover rotor across multiple
collective angles. Supports two domain geometry presets selectable with `--geometry`.

**Geometry presets:**

| Preset | Radial extent | z range | MRF Δz | n_pts STL | Cell count |
| --- | --- | --- | --- | --- | --- |
| `full` (default) | ±22.86 m (10D) | −10.860 – 17.715 m (2.5D up/+z, 10D down/−z) | ±1.257 m | 150 | 114 × 114 × 96 |
| `reduced` | ±12 m (5.25D) | 0 – 24 m (symmetric) | ±0.60 m | 50 | 60 × 60 × 80 |

The `full` preset matches Appendix A of Jeon & Lee (Aerospace 2025, 12, 940). The `reduced`
preset is the original smaller domain, kept for comparison but de-prioritised (see
[Known issues](#known-issues--pitfalls)).

**Fixed parameters (both presets):**

| Parameter | Value | Notes |
| --- | --- | --- |
| R | 1.143 m | C-T blade radius |
| c | 0.1905 m | constant chord, untapered |
| ω (650 RPM run) | 68.07 rad/s | Vtip = 78.2 m/s, Mtip = 0.228 |
| ω (1250 RPM run) | 130.90 rad/s | Vtip = 149.6 m/s, Mtip = 0.436 |
| MRF radius | 1.257 m | 1.1D/2, per Jeon & Lee Appendix A's "1.1D radial and axial" convention |
| Rotor z | 12.0 m | fixed in world frame regardless of preset |

**Pipeline per case** is the same as `run_sweep.py` with one addition: `surfaceFeatureExtract`
runs before `snappyHexMesh` to extract feature edges from the blade STL, improving mesh
quality at the leading and trailing edges. `--parallel N` runs N angles concurrently
(each case itself is single-threaded, so this is safe up to the number of physical cores).

At the start of each case setup, stale time directories from any previous `simpleFoam` run
are deleted before meshing begins, so `promoteMesh` can never accidentally pick up old
solver output instead of the fresh snappy mesh.

Convergence is checked from the force time history (last 20% of recorded points, std/mean
≤ 2%), not just the final iteration — some cases plateau at a stable value quickly, others
are still slowly settling near `endTime` (2000 iterations).

Results are appended to the target CSV as each angle completes; the script is idempotent
and will skip angles already present.

```bash
# Full 11-angle sweep — full geometry, 650 RPM (default), one dashboard-style example
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

> Without `--sweep_dir`/`--csv`, case data and the results CSV default to
> `caradonnaTung/` under the WSL OpenFOAM base directory — a convenient default
> for one-off checks, but every named sweep in the status table above (and every
> `dash.py` menu path) always passes explicit `--sweep_dir`/`--csv` per
> geometry/RPM combination instead.

---

### `run_gci_study.sh` + `analyze_gci_study.py`

Three-resolution Grid Convergence Index (GCI) study for the `full`-geometry C-T mesh,
following Celik, Ghia, Roache et al. (2008), ASME J. Fluids Eng. 130(7) — not an ad hoc
two-mesh percent-difference comparison. Fixes the physical case (θ=8°, 650 RPM by
default) and varies only `--blade_level` (coarse (4,5) → baseline (5,6) → fine (6,7),
a geometric refinement ratio r=2), so differences are attributable to discretization
error alone.

```bash
bash cfd_scripts/run_gci_study.sh          # theta=8 (default)
bash cfd_scripts/run_gci_study.sh 12       # different angle

python3 cfd_scripts/analyze_gci_study.py --root /home/david/OpenFOAM/ENGR412/gci_study --angle 8
```

**Current result: inconclusive.** The three levels do not converge monotonically —
thrust and torque move *away* from the medium-mesh value at the finest level tested
(apparent order p ≈ −2.9), which `analyze_gci_study.py` correctly refuses to turn into
a GCI percentage (a negative/oscillatory order means the standard formula doesn't
apply). Per the 2026-07-15 literature-pivot decision, this was not pursued further —
see [Known issues](#known-issues--pitfalls).

The same procedure was adapted for the co-rotating VR-12 dataset as
`cfd_scripts/analyze_gci_study_vr12.py` (invoked with `--base_csv`/`--lvl45_csv`/`--lvl56_csv`
plus `--spacing`/`--azimuth` to select the fixed case, rather than `--root`/`--angle`) —
see [VR-12 literature-match sweep](#vr-12-literature-match-sweep---dataset-co_rot_vr12-added-2026-07-21)
above.

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

Run this once the co-rotating sweep's revised design space (above) has completed —
the last EDA pass predates the design-space fix and is superseded (see
`ml_scripts/README_ML.md` for the azimuth-sensitivity re-check this motivates).

---

### `C-T_validation.py`

Generates comparison plots of CFD results against Caradonna & Tung (1981) experimental
hover data (650 RPM / Mtip = 0.228, 11 collective angles). Can be run in two modes:

- **Experimental only** — plots the published data and a Prandtl-Glauert incompressibility
  correction band. Useful to produce reference figures before CFD cases are ready.
- **With CFD overlay** — reads a `ct_results_*.csv` produced by `run_ct_sweep.py`, computes
  CT and CP using the C-T normalisation convention (ρ A Vtip²), and overlays the CFD
  points on the experimental curves.

Expected CFD vs. experiment agreement at Mtip = 0.228: CT underprediction of ~3%
(Prandtl-Glauert factor ≈ 1.03; `simpleFoam` is incompressible).

```bash
# Experimental reference only
python3 cfd_scripts/C-T_validation.py --outdir results_CT_validation

# With CFD overlay (full geometry, 650 RPM)
python3 cfd_scripts/C-T_validation.py \
  --cfd /home/david/OpenFOAM/ENGR412/caradonnaTung_full_650rpm/ct_results_full_650.csv \
  --outdir results_CT_validation
```

Output figures:

| File | Content |
| --- | --- |
| `CT_vs_collective.png` | CT vs θ: experiment, PG correction band, CFD points |
| `CP_vs_collective.png` | CP vs θ |
| `CT_CP_polar.png` | CT/σ vs CP/σ efficiency polar |
| `FOM_vs_collective.png` | Figure of merit vs collective |

---

### `C-T_comparisonA.py`

Reproduces Appendix A of Jeon & Lee (Aerospace 2025, 12, 940): a comparison at 1250 RPM
(Mtip ≈ 0.436) with collective pitch at 5°, 8°, and 12° (the angles with a published
experimental CT value). Also plots any additional CFD-only angles present in the results
CSV (e.g. 7°, 10°) as trend points with no matching experimental measurement, rather than
silently dropping them. Produces a terminal table of CT vs. collective (experimental + CFD)
and two figures.

```bash
# Auto-detects caradonnaTung_full_1250rpm/ct_results_full_1250.csv and theta5/ if present
python3 cfd_scripts/C-T_comparisonA.py

# Explicit paths (e.g. for reduced geometry run)
python3 cfd_scripts/C-T_comparisonA.py \
  --cfd      /home/david/OpenFOAM/ENGR412/caradonnaTung_reduced_1250rpm/ct_results_reduced_1250.csv \
  --case_dir /home/david/OpenFOAM/ENGR412/caradonnaTung_reduced_1250rpm/theta5 \
  --outdir   results_CT_appendixA
```

Output:

| File | Content |
| --- | --- |
| `CT_vs_collective_appendixA.png` | CT vs θ (4–14°): experimental data + CFD points (including CFD-only angles) + PG band |
| `Cp_sections_appendixA.png` | 5-panel −Cp vs x/c at r/R = 0.50 / 0.68 / 0.80 / 0.89 / 0.96 for θ=5° |

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
belongs to the co-rotating sweep against stacked-rotor literature; see
`analysis/stacked_rotor_literature_pivot_2026-07-15.md`).

- Reference: Caradonna & Tung (1981), NASA TM-81232
- Geometry: NACA 0012, R = 1.143 m, c = 0.1905 m, untwisted, 2 blades, σ = 0.1061
- Coefficient convention: CT = T/(ρ A Vtip²), CP = P/(ρ A Vtip³)

Two test conditions are run:

| RPM | ω [rad/s] | Vtip [m/s] | Mtip | Angles | Script |
| --- | --- | --- | --- | --- | --- |
| ~650 | 68.07 | 78.2 | 0.228 | 0°–12° (11 points) | `C-T_validation.py` |
| 1250 | 130.90 | 149.6 | 0.436 | 5°, 8°, 12° (+ 7°, 10° CFD-only when present) | `C-T_comparisonA.py` |

Compressibility note: `simpleFoam` is incompressible. At Mtip = 0.228 the Prandtl-Glauert
factor is ~1.03 (expected CT underprediction ~3%). At Mtip = 0.436 the factor is ~1.11
(expected underprediction ~10% if purely compressible, but real blades also stall at
high collective — scatter is larger). The plots show a PG correction band below the
experimental curve representing the expected incompressible range.

The archived 650 RPM / full-geometry result (`caradonnaTung_full_650rpm_tier1/`, 11/11
angles) sits at mean |CT error| 22.4%, judged an acceptable baseline for this project's
scope (an undergraduate independent study on open-source tooling, not a research paper)
after a GCI study showed diminishing/inconclusive returns from further mesh refinement
on the current `snappyHexMesh` approach — see `run_gci_study.sh`/`analyze_gci_study.py`
above and `analysis/stacked_rotor_literature_pivot_2026-07-15.md` for the full reasoning.
A structured (O-grid/C-grid) mesh rewrite was scoped as a possible next step
(`analysis/structured_mesh_followup_2026-07-14.md`) but was explicitly dropped in favour
of redirecting remaining validation effort to the co-rotating sweep.

---

## Known issues / pitfalls

### promoteMesh stale-directory bug (fixed)

After `snappyHexMesh` runs, it writes its mesh output into a numbered time directory
(`1/` or `2/`). The promoteMesh step must copy that directory to `constant/polyMesh` so
subsequent tools see the refined mesh. However, if the case was run previously, leftover
`simpleFoam` time directories (`400/`, `500/`) have higher numbers than the snappy output
and would be selected instead — leaving `constant/polyMesh` as a bare blockMesh with no
blade patch. The solver then runs on a cylinder of air, reports zero blade forces, and
writes nothing to `force.dat` (or leaves a stale file from the previous run).

**Fix (applied in both `run_sweep.py` and `run_ct_sweep.py`):** the promoteMesh shell
command now filters candidate directories to only those that actually contain a
`polyMesh/` subdirectory before selecting the highest-numbered one. Additionally,
`run_ct_sweep.py` deletes all time directories greater than zero at the start of each
case setup, so stale solver output can never interfere with a fresh mesh run.

### Launching from native Windows Python instead of WSL (fixed 2026-07-30)

The whole pipeline assumes a WSL Python interpreter: paths like `Path("/home/david/...")`
and `subprocess.run(["bash", "-c", ...])` only resolve correctly under WSL. Launching
`dash.py` (or `run_ct_sweep.py` etc.) with a *native* Windows Python interpreter (e.g. a
Windows-side `python3` earlier in `PATH`) produces two failures at once: Unicode
characters (ω/≈/θ/±) in progress output crash with `UnicodeEncodeError` on the default
cp1252 console codepage, and `/home/...`-style paths get silently reinterpreted as
Windows paths (`\home\...`), causing `FileNotFoundError`s that look like missing
template directories rather than a wrong interpreter. `run_ct_sweep.py` now forces
UTF-8 stdout/stderr at startup so the encoding half no longer crashes outright, but the
path-mismatch half has no code fix — always launch via `wsl python3 dash.py` from a
Windows terminal, or run `python3 dash.py` from inside a WSL shell (dash.py already
warns "WSL filesystem not detected" if launched wrong, but only pauses rather than
blocking).

### C-T validation: on-disk results currently cleared, re-run pending

The mesh-tightened C-T figures cited elsewhere in this file (mean CT error
61.5%→50.0% after tightening `MEDIAL_RATIO` 0.3→0.15 and layers 5→7, with
5°/8°/12° individually at 122.0%/22.8%/5.1%) are the last-confirmed real result but
are **not currently reproducible from on-disk data**: the 650 RPM full-geometry C-T
results have been cleared, and the 1250 RPM results CSV exists but is empty. Both
launch bugs behind this (the Unicode crash and the Windows/WSL path mismatch, above)
are now fixed, so the re-run is unblocked — it just hasn't been done yet. Don't cite
the 122.0%/22.8%/5.1% figures as currently sitting on disk; re-run
`run_ct_sweep.py --geometry full` at both RPMs first.

Two things worth knowing before that re-run:

- **Mesh/domain budget already matches or exceeds the reference.** A prior comparison
  against Jeon & Lee (Aerospace 2025, 12, 940) Appendix A had compared their domain
  against this project's `reduced` preset by mistake — the `full` preset (10D radial,
  2.5D/10D up/downstream, MRF Δz = 1.1D exact match, ~20M cells vs. their ~13.6M) is
  the one every current C-T sweep actually uses, and it already matches or exceeds
  their domain size and cell budget. The real, still-open gap is near-wall treatment
  (7 layers / y+ ≈ 228–346 here vs. their 25 layers / y+ < 1), a deliberate scope
  choice for this project, not an oversight.
- **A genuinely untried lever: LE/root/tip prism-layer coverage.** 4–16% of blade
  faces — concentrated at the leading edge, root, and tip — currently get zero prism
  layers at all, distinct from the average-y+ shortfall above (average y+ is already
  inside the wall-functions' valid 30–300 range, so this is a coverage/snapping
  problem at specific geometric features, not a resolution problem). Worth checking
  `snapControls` (`resolveFeatureAngle`, `nSmoothSurfaceNormals`) and a
  `refinementRegion` wrapping the LE/root/tip specifically, rather than another
  uniform `BLADE_LEVEL`/`maxGlobalCells` bump — a uniform global-refinement lever has
  already been tried (it's how the 61.5%→50.0% improvement above was achieved) and
  diminishing-returns'd out.

### GCI mesh study is inconclusive, not pursued further

The three-level GCI study (θ=8°, 650 RPM) shows oscillatory, non-monotonic convergence
at the finest level tested (apparent order p ≈ −2.9) — `analyze_gci_study.py` correctly
refuses to report a GCI percentage in this regime rather than fabricate one. Per the
2026-07-15 pivot decision, further mesh-resolution chasing on `snappyHexMesh` was
deprioritised in favour of the co-rotating sweep; the reduced-geometry C-T preset is
similarly de-prioritised for the same reason.

### `dash.py`'s 1250 RPM angle set doesn't match `C-T_comparisonA.py`'s 5-angle support

The dashboard's built-in "C-T sweep" sub-menu launches only a 3-angle 1250 RPM sweep
(5°/8°/12°), while `C-T_comparisonA.py` supports plotting extra CFD-only angles
(7°/10°) as trend points with no experimental counterpart. A hand-launched
`run_ct_sweep.py --angles 5 7 8 10 12 ...` gets the full benefit of that support; going
through the dashboard's menu 2 → f → b path does not. Row-count expectations (`3` per
RPM) shown in the dashboard's progress bars for the 1250 RPM case reflect the
dashboard's own 3-angle default, not `C-T_comparisonA.py`'s full capability.

### Analysis scripts default to a relative `--outdir`

`analyze_sweep.py`, `C-T_validation.py`, and `C-T_comparisonA.py` all write into
`--outdir` relative to the current working directory. Run them from the git repo root
(as `dash.py` always does, passing an explicit absolute `--outdir`) — running them by
hand from a WSL working directory under `/home/david/OpenFOAM/ENGR412/` instead will
silently create a `results_*/` directory there rather than in the tracked repo location.

### `merge_final_dataset.py`'s `data_quality` column collision (found and fixed 2026-07-30)

`cfd_scripts/run_sweep.py`'s `CSV_HEADER_DUAL` gained its own `data_quality` column
(2026-07-29, tail-window-ratio grading: `CONVERGED_TIGHT`/`CONVERGED`/`BORDERLINE`/
`NOT_CONVERGED`) after `merge_final_dataset.py` was written (2026-07-22) with its own
`OUT_HEADER = CSV_HEADER_DUAL + ["data_quality", "data_quality_detail"]`. This used to
list `data_quality` twice, with `build_row()`'s explicit `row["data_quality"] = quality`
(`CONVERGED`/`TIME_AVERAGED`, the merge-tier label) silently overwriting whatever
fine-grained value `CSV_HEADER_DUAL`'s own `data_quality` column carried in.

**Fixed same day:** this script's own two output columns are now `merge_quality`/
`merge_quality_detail`, distinct from `CSV_HEADER_DUAL`'s per-row `data_quality`. The
two coexist as separate columns in any file this script produces going forward.

**Still open:** this script's row-accounting assert (`831 + ... = 1125`) still
hard-codes the original 1125-row `co_rot_results.csv` population and has not been
updated for the current 1625-row file (see [Design space](#design-space-co-rotating-coaxial-sweep))
— it will refuse to run (`SystemExit`) against current data until that assert is
revisited.

### Root-directory housekeeping

A few items at the repo root are left over from ad hoc work and worth a cleanup pass:

- `co_rot_full_run.log` (a run log, ~300 lines) is tracked in git despite `.gitignore`
  already excluding `output.txt` for the same reason — likely an oversight; consider
  adding a `*.log` pattern instead of tracking individual log files.
- `wsl_backfill_clean_v2.py` and `wsl_patch_items_4_5.sh` — removed 2026-08-03 (see
  [Repository layout](#repository-layout) above).
- `MLX_board.py` is deleted from the working tree (not yet committed) as of this pass.
- Two `412_Report_Cronin_DRAFT1_v*.docx` report drafts (v6, v7) are currently untracked
  at the repo root — the canonical copy lives on OneDrive, not in this repo. `.gitignore`
  has no rule excluding them, so a broad `git add` would sweep them into a commit;
  left in place for now, but worth a `*.docx` `.gitignore` entry if that's not wanted.

---

## Dependencies (WSL Python)

```bash
sudo apt install python3-pip -y
pip3 install numpy pandas matplotlib seaborn scipy
```

VS Code: use the **Remote - WSL** extension (`ms-vscode-remote.remote-wsl`) and open
the project from inside WSL so the Python extension resolves packages correctly.

---

## History

Chronological investigation log — each entry links the full write-up; this section is a
pointer index, not a replacement for reading them.

- **2026-07-12 — Domain-orientation bug.** Root-caused a spurious ~33-37N θ=0° thrust
  (should be ≈0) to the C-T `full` preset's domain z-extent being backwards relative to
  the wake direction. Fixed alongside a wake-refinement-cylinder direction bug, an STL
  leading-edge degenerate-facet bug, and an MRF-radius inconsistency.
  `analysis/summary_domain_orientation_fix_2026-07-12.md`
- **2026-07-13 — Tier-1 pipeline hardening.** Added a force-history-based convergence
  check (replacing a hardcoded `converged=True`) and doubled `END_TIME` after finding
  cases that were still slowly settling at the old 1000-iteration cutoff. Validated with
  no regression at either RPM.
- **2026-07-14 — Mesh-convergence harness + structured-mesh scoping.** Added
  `--blade_level`/`--layers`/`--medial_ratio` CLI overrides to `run_ct_sweep.py` so a
  proper GCI study could be run, and scoped (but did not build) a structured O-grid/C-grid
  mesh replacement for `snappyHexMesh`. `analysis/structured_mesh_followup_2026-07-14.md`
- **2026-07-15 — Literature pivot.** A five-paper meshing-approach survey found the
  actual C-T benchmark paper (Jeon & Lee 2025) doesn't use an O-grid either — it succeeds
  with prism layers + unstructured background, closer to what `snappyHexMesh` already
  does. Combined with an inconclusive GCI result, this dropped the structured-mesh
  rewrite entirely and redirected validation effort to the co-rotating sweep, whose
  design space was found (and fixed) to have missed the close-spacing/near-zero-azimuth
  regime where stacked-rotor literature reports the strongest effects.
  `analysis/stacked_rotor_literature_pivot_2026-07-15.md`
