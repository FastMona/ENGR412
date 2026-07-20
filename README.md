# ENGR412 — Coaxial Rotor Thrust Optimisation

Concordia University Independent Study. OpenFOAM CFD characterises a co-rotating
coaxial rotor pair and builds a training dataset for an MLP-based lower-rotor
controller: given the upper rotor's commanded RPM, the controller outputs the
lower rotor's RPM, axial spacing, and azimuthal (index) angle that maximise total
thrust. A separate Caradonna-Tung hover-rotor validation case sanity-checks the
solver/mesh pipeline against published experimental data.

Two active branches: `main` carries the CFD sweep pipeline and C-T validation;
`mlp-lower-rotor-control`'s work (the `ml/` package — surrogate model, policy
extraction, embeddable controller) has been merged into `main` and is documented
separately in `ml/README.md`.

---

## Project status (as of 2026-07-20)

| Component | State |
| --- | --- |
| Single-rotor baseline sweep | data cleared — re-run pending (`run_sweep.py --dataset single`) |
| Co-rotating coaxial sweep | data cleared — **design space revised 2026-07-15** (see below), re-run pending |
| C-T validation — full geometry, 650 RPM | data cleared — re-run pending |
| C-T validation — full geometry, 1250 RPM | **in progress** (5 angles: 5°/7°/8°/10°/12°) |
| C-T validation — reduced geometry (650 & 1250 RPM) | data cleared — de-prioritised, see [Known issues](#known-issues--pitfalls) |
| GCI mesh-convergence study (θ=8°, full/650) | complete — **inconclusive** (oscillatory convergence at the finest level tested) |
| MLP lower-rotor controller (`ml/`) | scaffolded, not yet trained on real multi-RPM data — see `ml/README.md` |

A prior complete 650 RPM / full-geometry result is archived at
`caradonnaTung_full_650rpm_tier1/ct_results_full_650.csv` (11/11 angles, mean
|CT error| 22.4%) — kept for reference; it is not the path `dash.py` currently
tracks, since a further design-space/mesh revision means it will be superseded by
the next full re-run rather than resumed in place.

CFD case data and results all live on the WSL filesystem or under `results_*/`
(both untracked in git — see `.gitignore`); this repo tracks only the pipeline
code, not generated data.

---

## Repository layout

```text
ENGR412/
├── dash.py                       # dashboard — menu-driven status and launcher
├── scripts/
│   ├── generate_propeller.py     # NACA 4-digit blade STL for snappyHexMesh
│   ├── run_sweep.py              # parametric sweep: single-rotor / co-rotating
│   ├── run_ct_sweep.py            # Caradonna-Tung validation sweep (full / reduced geometry)
│   ├── run_gci_study.sh           # 3-resolution GCI mesh-convergence harness (calls run_ct_sweep.py)
│   ├── analyze_sweep.py           # EDA: plots, coefficients, summary CSV
│   ├── analyze_gci_study.py       # Richardson extrapolation / GCI (Celik et al. 2008)
│   ├── C-T_validation.py          # C-T comparison, 650 RPM (11 angles, 4 figures)
│   └── C-T_comparisonA.py         # Appendix A reproduction, 1250 RPM (CT table + Cp panels)
├── ml/                            # MLP lower-rotor controller — see ml/README.md
├── analysis/                      # dated investigation write-ups (see History, below)
├── results_singleRotor/           # single-rotor EDA output (figures/ + eda_summary.csv)
├── results_2_co_rot/               # co-rotating EDA output
├── results_CT_validation/          # C-T validation figures + summary (650 RPM)
└── results_CT_appendixA/           # C-T Appendix A figures + summary (1250 RPM)
```

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
├── gci_study/                         # lvl_4_5 / lvl_5_6 / lvl_6_7 mesh-convergence cases
├── 1_single_rotor_sweep/              # single-rotor design-space cases
│   └── single_rotor_results.csv
└── 2_co_rot_sweep/                    # co-rotating design-space cases
    └── co_rot_results.csv
```

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
| Azimuth angle | −90, −45, −20, −10, 0, 10, 20, 45, 90 deg | symmetric, denser near 0° |
| Lower rotor RPM | 600, 750, 900, 1050, 1200 | |
| Upper rotor RPM | 900 (default) | overridable via `--rpm_upper` — see below |

Base case count: 5 × 9 × 5 = **225 co-rotating cases** at the default single
upper-RPM value (~38 min @ `--parallel 12`, ~2 min/case). Pass multiple
`--rpm_upper` values (e.g. `--rpm_upper 700 900 1100`) to build the varying-upper-RPM
dataset the MLP controller needs; this multiplies the case count accordingly —
see `ml/README.md` for how that dataset is consumed.

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
python3 scripts/generate_propeller.py \
  --pitch 0.4 --diameter 1.0 --rotor_z 5.0 \
  --solid_name upperPropeller \
  --output /path/to/upperPropeller.stl

# Caradonna-Tung validation blade (NACA 0012, θ=8°)
python3 scripts/generate_propeller.py \
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
5. `simpleFoam` — steady RANS solver, 500 iterations

The script is idempotent: it reads the existing results CSV on startup and skips any case
whose `case_id` is already present. Kill and restart safely at any point.

```bash
# Single-rotor baseline (5 cases, ~6 min)
python3 scripts/run_sweep.py --dataset single --parallel 5

# Co-rotating sweep, default single upper-RPM (225 cases, ~38 min @ 12 workers)
python3 scripts/run_sweep.py --dataset co_rot --parallel 12

# Co-rotating sweep, varying upper RPM (for MLP training data — see ml/README.md)
python3 scripts/run_sweep.py --dataset co_rot --parallel 12 --rpm_upper 700 900 1100

# Dry run — preview cases without running CFD
python3 scripts/run_sweep.py --dataset single --dry_run
```

Forces and moments are read from `postProcessing/forcesUpper/0/force.dat` and
`postProcessing/forcesLower/0/force.dat`. Column 3 (0-indexed) is the total-Z component,
which equals thrust for the upward-pointing rotor axis.

Requesting a spacing below `MRF_FEASIBLE_MIN_SPACING` (0.05 m) raises a `ValueError` —
see [Design space](#design-space-co-rotating-coaxial-sweep).

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
python3 scripts/run_ct_sweep.py \
  --geometry full \
  --sweep_dir /home/david/OpenFOAM/ENGR412/caradonnaTung_full_650rpm \
  --csv /home/david/OpenFOAM/ENGR412/caradonnaTung_full_650rpm/ct_results_full_650.csv

# Reduced geometry
python3 scripts/run_ct_sweep.py --geometry reduced

# 1250 RPM subset, run concurrently
python3 scripts/run_ct_sweep.py --geometry full --rpm 1250 \
  --angles 5 7 8 10 12 --parallel 5 \
  --sweep_dir /home/david/OpenFOAM/ENGR412/caradonnaTung_full_1250rpm \
  --csv /home/david/OpenFOAM/ENGR412/caradonnaTung_full_1250rpm/ct_results_full_1250.csv

# Mesh-convergence (GCI) study — see run_gci_study.sh below
python3 scripts/run_ct_sweep.py --angles 8 --blade_level 6 7 \
  --sweep_dir /home/david/OpenFOAM/ENGR412/gci_study/lvl_6_7 \
  --csv /home/david/OpenFOAM/ENGR412/gci_study/lvl_6_7/ct_results.csv

# Dry run — generate case files only, no solver
python3 scripts/run_ct_sweep.py --dry_run
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
bash scripts/run_gci_study.sh          # theta=8 (default)
bash scripts/run_gci_study.sh 12       # different angle

python3 scripts/analyze_gci_study.py --root /home/david/OpenFOAM/ENGR412/gci_study --angle 8
```

**Current result: inconclusive.** The three levels do not converge monotonically —
thrust and torque move *away* from the medium-mesh value at the finest level tested
(apparent order p ≈ −2.9), which `analyze_gci_study.py` correctly refuses to turn into
a GCI percentage (a negative/oscillatory order means the standard formula doesn't
apply). Per the 2026-07-15 literature-pivot decision, this was not pursued further —
see [Known issues](#known-issues--pitfalls).

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
python3 scripts/analyze_sweep.py \
  --mode single \
  --csv /home/david/OpenFOAM/ENGR412/1_single_rotor_sweep/single_rotor_results.csv \
  --outdir results_singleRotor

# Co-rotating EDA
python3 scripts/analyze_sweep.py \
  --csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results.csv \
  --outdir results_2_co_rot
```

Run this once the co-rotating sweep's revised design space (above) has completed —
the last EDA pass predates the design-space fix and is superseded (see
`ml/README.md` for the azimuth-sensitivity re-check this motivates).

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
python3 scripts/C-T_validation.py --outdir results_CT_validation

# With CFD overlay (full geometry, 650 RPM)
python3 scripts/C-T_validation.py \
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
python3 scripts/C-T_comparisonA.py

# Explicit paths (e.g. for reduced geometry run)
python3 scripts/C-T_comparisonA.py \
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

### GCI mesh study is inconclusive, not pursued further

The three-level GCI study (θ=8°, 650 RPM) shows oscillatory, non-monotonic convergence
at the finest level tested (apparent order p ≈ −2.9) — `analyze_gci_study.py` correctly
refuses to report a GCI percentage in this regime rather than fabricate one. Per the
2026-07-15 pivot decision, further mesh-resolution chasing on `snappyHexMesh` was
deprioritised in favour of the co-rotating sweep; the reduced-geometry C-T preset is
similarly de-prioritised for the same reason.

### `dash.py`'s 1250 RPM angle set is stale relative to the currently-running sweep

The dashboard's built-in "C-T sweep" sub-menu still launches a 3-angle 1250 RPM sweep
(5°/8°/12°); the sweep currently in progress (see status table) was launched by hand
with 5 angles (5°/7°/8°/10°/12°), matching `C-T_comparisonA.py`'s CFD-only-angle
support. Row-count expectations shown in the dashboard's progress bars for the 1250 RPM
case do not yet reflect this.

### Analysis scripts default to a relative `--outdir`

`analyze_sweep.py`, `C-T_validation.py`, and `C-T_comparisonA.py` all write into
`--outdir` relative to the current working directory. Run them from the git repo root
(as `dash.py` always does, passing an explicit absolute `--outdir`) — running them by
hand from a WSL working directory under `/home/david/OpenFOAM/ENGR412/` instead will
silently create a `results_*/` directory there rather than in the tracked repo location.

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
