# ENGR412 — Coaxial Rotor Thrust Optimisation

Concordia University Independent Study. Uses OpenFOAM CFD simulations to characterise
a coaxial rotor system and build a dataset for neural network-based thrust optimisation.
The lower rotor is the controlled variable; the upper rotor runs at fixed conditions.

---

## Project status

| Phase | Status |
| --- | --- |
| Single-rotor baseline sweep (15 cases) | complete |
| Co-rotating coaxial sweep (525 cases) | complete |
| Counter-rotating coaxial sweep (525 cases) | in progress (117 / 525) |
| Caradonna-Tung CFD validation (11 collective angles) | in progress — mesh bug fixed, re-run pending |
| EDA — single rotor | complete |
| EDA — co-rotating | complete |
| EDA — counter-rotating | pending (awaiting full sweep) |
| NN training | pending (awaiting contra-rot data) |

---

## Repository layout

```text
ENGR412/
├── dash.py                     # dashboard — menu-driven status and launcher
├── scripts/
│   ├── generate_propeller.py   # NACA 4-digit blade STL for snappyHexMesh
│   ├── run_sweep.py            # parametric sweep: single / co-rot / contra-rot
│   ├── run_ct_sweep.py         # Caradonna-Tung validation sweep (11 angles)
│   ├── analyze_sweep.py        # EDA: plots, coefficients, summary CSV
│   └── C-T_validation.py       # Caradonna-Tung (1981) CFD vs experiment comparison
├── results_singleRotor/
│   ├── eda_summary.csv
│   └── figures/
│       ├── performance_grid.png   # thrust / FOM / PLnorm vs RPM + CT-CP scatter
│       └── convergence_hist.png
├── results_2_co_rot/
│   ├── eda_summary.csv
│   └── figures/
│       ├── violin_PLnorm.png
│       ├── thrust_decomp.png
│       ├── interaction_heatmap.png
│       ├── correlation_matrix.png
│       └── convergence_hist.png
└── results_CT_validation/
    └── figures/
        ├── CT_vs_collective.png    # CT vs θ: experiment + PG band (+ CFD when run)
        ├── CP_vs_collective.png
        ├── CT_CP_polar.png         # CT/σ vs CP/σ efficiency polar
        └── FOM_vs_collective.png
```

CFD case data lives on the WSL filesystem (not tracked in git):

```text
/home/david/OpenFOAM/ENGR412/
├── singleRotor/              # single-rotor template case
├── coaxialRotor/             # coaxial template case
├── caradonnaTung/            # validation template + sweep output (theta<N>/ subdirs)
│   └── ct_results.csv        # one row per collective angle (written by run_ct_sweep.py)
├── 1_single_rotor_sweep/     # 15 cases: 5 RPM × 3 pitch
│   └── single_rotor_results.csv
├── 2_co_rot_sweep/           # 525 cases: co-rotating (complete)
│   └── co_rot_results.csv
└── 2_contra_rot_sweep/       # 525 cases: counter-rotating (in progress)
    └── contra_rot_results.csv
```

---

## Design space

| Variable | Values | Notes |
| --- | --- | --- |
| Axial spacing | 0.10, 0.20, 0.30, 0.40, 0.60 m | distance between rotor planes |
| Azimuth angle | 0, 15, 30, 45, 60, 75, 90 deg | lower rotor index angle relative to upper |
| Lower rotor RPM | 600, 750, 900, 1050, 1200 | upper fixed at 900 RPM |
| Lower rotor pitch | 0.3, 0.4, 0.5 m | upper fixed at 0.4 m |
| Rotation direction | co-rotating, counter-rotating | |

Fixed: NACA 4412 airfoil, D = 1.0 m, 2 blades, steady-state MRF (simpleFoam), k-ω SST.

> **Note:** 0.10 m and 0.20 m spacing cases have overlapping MRF zones (MRF half-height = ±0.125 m; overlap-free requires spacing ≥ 0.25 m). Exclude both from NN training data — use only spacings 0.30, 0.40, 0.60 m (315 / 525 cases per direction).

---

## OpenFOAM environment

- OpenFOAM 2412 on WSL2 (Ubuntu 22.04), Windows 11
- Solver: `simpleFoam` (steady-state RANS)
- Turbulence: k-ω SST
- Mesh: `blockMesh` outer domain → `snappyHexMesh` blade refinement → `topoSet` MRF zones
- Forces extracted from `postProcessing/forces*/0/force.dat` and `moment.dat`

### Rotor physics

**Co-rotating (CCR):** both rotors spin in the same direction (counter-clockwise viewed from above). Both use identical NACA 4412 geometry. Omega is positive for both rotors. Both produce positive-Z (upward) thrust by convention.

**Counter-rotating (CCtR):** rotors spin in opposite directions. The lower rotor blade is a mirror image of the upper (generated with `--mirror_y`), and its omega is negated. Because the geometry is mirrored and omega is reversed together, both rotors still produce positive-Z thrust.

---

## Dashboard

`dash.py` is the primary entry point. Run from the project root inside WSL:

```bash
python3 dash.py
```

Provides a live status panel and launches all scripts via a numbered menu without needing
to remember arguments or paths.

### Status panel sections

- **STL GEOMETRY** — checks whether each propeller STL has been generated in the WSL
  template case directories. Shows filename on the same line when present.
- **CFD SWEEPS** — progress bar for each sweep CSV (rows completed vs. expected total).
  Shows the CSV filename so you can tell at a glance which file is being read.
- **EDA / ANALYSIS** — counts PNG figures and summary CSV in each `results_*/` directory.
- **C-T VALIDATION** — separate section for the Caradonna-Tung figures.

### Menu actions

| # | Action | Purpose |
| --- | --- | --- |
| 1 | Generate propeller STL | Runs `generate_propeller.py` for any of the four rotor geometries (or a custom C-T collective angle) |
| 2 | Run CFD sweep | Runs a sweep script. When an existing CSV is found, prompts to **Recalculate** (backs up CSV, reruns all cases) or **Resume** (skips already-completed cases) |
| 3 | Analyse sweep results | Runs `analyze_sweep.py` or `C-T_validation.py` to produce figures and summary CSVs |
| 4 | Headline statistics | Reads existing CSVs and prints thrust range, FOM range, best case |
| 5 | Clean up | Full reset options — see below |
| q | Quit | Exits and writes SESSION END to output.txt |

### Clean-up system (menu 5)

Each sweep option is a **full blank-sheet reset** — it deletes everything generated by that sweep so it can be re-run from scratch:

| Key | What is deleted |
| --- | --- |
| a | `log.*` files inside every case subdirectory (all sweeps) |
| b | Single-rotor: case dirs + `single_rotor_results.csv` + `propeller.stl` + `results_singleRotor/` |
| c | Co-rotating: case dirs + `co_rot_results.csv` + `upperPropeller.stl` / `lowerPropeller.stl` + `results_2_co_rot/` |
| d | Counter-rotating: same scope as c, for the contra-rot sweep |
| e | C-T validation: `theta*/` case dirs + `ct_results.csv` + `ctBlade.stl` + `results_CT_validation/` |
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

# Counter-rotating lower rotor (CW mirror)
python3 scripts/generate_propeller.py \
  --pitch 0.4 --rotor_z 4.7 --mirror_y \
  --solid_name lowerPropeller \
  --output /path/to/lowerPropeller.stl

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
| `--mirror_y` | off | Mirror blade for counter-rotating (CW) rotor |
| `--azimuth_deg` | 0 | Index angle offset between upper and lower rotors |

---

### `run_sweep.py`

Runs the full OpenFOAM pipeline for each case in the single-rotor, co-rotating, or
counter-rotating design space. Cases run in parallel using `ProcessPoolExecutor`; the
`--parallel` flag sets the worker count.

**Pipeline per case:**

1. `blockMesh` — builds a uniform hex background mesh for the outer domain
2. `snappyHexMesh` — refines the mesh around the blade STL surface and snaps to it
3. **promoteMesh** — copies `snappyHexMesh` output from its numbered time directory back to
   `constant/polyMesh`. The script filters candidate directories for those that actually
   contain a `polyMesh/` subdirectory, avoiding a bug where leftover `simpleFoam` time
   directories (e.g. `400/`, `500/`) have higher numbers than the snappy output (`1/`, `2/`)
   and would be picked instead.
4. `topoSet` — marks the MRF rotating-zone cell set
5. `simpleFoam` — steady RANS solver, 500 iterations

The script is idempotent: it reads the existing results CSV on startup and skips any case
whose `case_id` is already present. Kill and restart safely at any point.

```bash
# Single-rotor baseline (15 cases, ~30 min)
python3 scripts/run_sweep.py --dataset single --parallel 12

# Co-rotating sweep (525 cases, ~18 h)
python3 scripts/run_sweep.py --dataset co_rot --parallel 12

# Counter-rotating sweep (525 cases, ~18 h)
python3 scripts/run_sweep.py --dataset contra_rot --parallel 12

# Dry run — preview cases without running CFD
python3 scripts/run_sweep.py --dataset single --dry_run
```

Forces and moments are read from `postProcessing/forcesUpper/0/force.dat` and
`postProcessing/forcesLower/0/force.dat`. Column 3 (0-indexed) is the total-Z component,
which equals thrust for the upward-pointing rotor axis.

---

### `run_ct_sweep.py`

Runs the Caradonna-Tung validation sweep: 11 collective angles (0°–12°) on a NACA 0012
hover rotor at Mtip = 0.228. Each angle gets its own OpenFOAM case directory under
`caradonnaTung/theta<N>/`.

**Key constants baked into the script:**

| Parameter | Value | Source |
| --- | --- | --- |
| R | 1.143 m | C-T geometry |
| c | 0.1905 m | constant chord, untapered |
| ω | 68.07 rad/s | Vtip = 78.2 m/s, Mtip = 0.228 |
| Domain | ±12 m × 24 m | ≈ 5.25× diameter each side |
| MRF cylinder | r = 1.40 m, Δz = ±0.60 m at z = 12 m | rotor at domain mid-height |

**Pipeline per case** is the same as `run_sweep.py` with one addition: `surfaceFeatureExtract`
runs before `snappyHexMesh` to extract feature edges from the blade STL, improving mesh
quality at the leading and trailing edges.

At the start of each case setup, stale time directories from any previous `simpleFoam` run
are deleted before meshing begins. This prevents the promoteMesh step from accidentally
picking up old solver output instead of the fresh snappy mesh.

Results are appended to `ct_results.csv` as each angle completes; the script is idempotent
and will skip angles already in the CSV.

```bash
python3 scripts/run_ct_sweep.py                       # full 11-angle sweep
python3 scripts/run_ct_sweep.py --angles 5 8 12       # subset
python3 scripts/run_ct_sweep.py --dry_run             # generate files only, no solver
```

---

### `analyze_sweep.py`

Reads a sweep results CSV, computes dimensionless performance coefficients (CT, CP, PLnorm,
FOM), and writes figures and a summary CSV to the output directory.

**Coaxial mode** (default):

| Output | Description |
| --- | --- |
| `violin_PLnorm.png` | Violin plots of PLnorm broken down by each design variable |
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

# Counter-rotating EDA
python3 scripts/analyze_sweep.py \
  --csv /home/david/OpenFOAM/ENGR412/2_contra_rot_sweep/contra_rot_results.csv \
  --outdir results_2_contra_rot
```

---

### `C-T_validation.py`

Generates comparison plots of CFD results against Caradonna & Tung (1981) experimental
hover data. Can be run in two modes:

- **Experimental only** — plots the published data and a Prandtl-Glauert incompressibility
  correction band. Useful to produce reference figures before CFD cases are ready.
- **With CFD overlay** — reads `ct_results.csv` produced by `run_ct_sweep.py`, computes
  CT and CP using the C-T normalisation convention (ρ A Vtip²), and overlays the CFD
  points on the experimental curves.

Expected CFD vs. experiment agreement at Mtip = 0.228: CT underprediction of ~3%
(Prandtl-Glauert factor ≈ 1.03; `simpleFoam` is incompressible).

```bash
# Experimental reference only
python3 scripts/C-T_validation.py --outdir results_CT_validation

# With CFD overlay
python3 scripts/C-T_validation.py \
  --cfd /home/david/OpenFOAM/ENGR412/caradonnaTung/ct_results.csv \
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

## Key EDA findings

### Single rotor (15 cases, NACA 4412, D = 1 m)

- Thrust range: 4.6 – 26.1 N across RPM 600–1200 and pitch 0.3–0.5 m
- FOM range: 0.355 – 0.371 (narrow — single-rotor efficiency is pitch-insensitive at these Re)
- Best FOM: RPM 1200, pitch 0.40 m (FOM = 0.3705)
- Best PLnorm: RPM 1200, pitch 0.30 m (PLnorm = 2.385)
- All 15 cases hit the 500-iteration wall; forces appear stabilised

### Co-rotating coaxial (525 cases)

- RPM is the dominant driver of PLnorm; azimuth angle has near-zero effect (Pearson r ≈ 0)
- Lower rotor mean thrust is 40–55% of upper rotor thrust (interference ratio median 0.71)
- FOM peaks at 0.10 m spacing but those cases are unphysical (MRF zone overlap)
- ~80% of cases ran to the 500-iteration wall

---

## Caradonna-Tung validation

Validates the MRF + simpleFoam pipeline against published experimental hover data.

- Reference: Caradonna & Tung (1981), NASA TM-81232
- Geometry: NACA 0012, R = 1.143 m, c = 0.1905 m, untwisted, 2 blades, σ = 0.1061
- Test condition: tip Mach 0.228 (~653 RPM, ω = 68.07 rad/s), collective 0°–12°
- Coefficient convention: CT = T/(ρ A Vtip²), CP = P/(ρ A Vtip³)

`scripts/C-T_validation.py` generates four comparison plots from experimental data (already done)
and overlays CFD results once the `caradonnaTung/` OpenFOAM cases have been run.

Compressibility note: `simpleFoam` is incompressible. At Mtip = 0.228 the Prandtl-Glauert
factor is ~1.03, so CFD is expected to underpredict CT by only ~3%. The plots show a
correction band below the experimental curve representing the expected incompressible range.

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

---

## Dependencies (WSL Python)

```bash
sudo apt install python3-pip -y
pip3 install numpy pandas matplotlib seaborn scipy
```

VS Code: use the **Remote - WSL** extension (`ms-vscode-remote.remote-wsl`) and open
the project from inside WSL so the Python extension resolves packages correctly.
