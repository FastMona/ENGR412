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
| Caradonna-Tung CFD validation | in progress — reference plots done, CFD cases pending |
| EDA — single rotor | complete |
| EDA — co-rotating | complete |
| NN training | pending (awaiting contra-rot data) |

---

## Repository layout

```text
ENGR412/
├── dash.py                     # dashboard — menu-driven status and launcher
├── scripts/
│   ├── generate_propeller.py   # NACA 4-digit blade STL for snappyHexMesh
│   ├── run_sweep.py            # parametric sweep automation
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
├── caradonnaTung/            # validation case (NACA 0012, R=1.143 m)
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

> **Note:** 0.10 m spacing cases have overlapping MRF zones — exclude from NN training data.

---

## OpenFOAM environment

- OpenFOAM 2412 on WSL2 (Ubuntu 22.04), Windows 11
- Solver: `simpleFoam` (steady-state RANS)
- Turbulence: k-ω SST
- Mesh: `blockMesh` outer domain → `snappyHexMesh` blade refinement → `topoSet` MRF zones
- Forces extracted from `postProcessing/forces*/0/force.dat` and `moment.dat`

---

## Dashboard

`dash.py` is the primary entry point. Run from the project root inside WSL:

```bash
python3 dash.py
```

Provides a live status panel (STL geometry, sweep progress, EDA outputs) and launches
all scripts via a menu without needing to remember arguments.

---

## Scripts

### `generate_propeller.py`

Generates a 2-blade propeller as an ASCII STL. Supports any NACA 4-digit profile,
constant or tapered chord, and geometric twist or constant collective.

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

### `run_sweep.py`

Runs the full OpenFOAM pipeline for each case (blockMesh → snappyHexMesh → topoSet →
simpleFoam). Idempotent — safe to kill and restart.

```bash
# Single-rotor baseline (15 cases, ~30 min)
python3 scripts/run_sweep.py --dataset single --parallel 12

# Co-rotating sweep (525 cases, ~18 h)
python3 scripts/run_sweep.py --dataset co_rot --parallel 12

# Dry run — preview cases without running CFD
python3 scripts/run_sweep.py --dataset single --dry_run
```

### `analyze_sweep.py`

Reads a sweep CSV, computes dimensionless coefficients (CT, CP, PLnorm, FOM),
and writes plots and a summary CSV to the output directory.

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

`--mode single` selects single-rotor plots (performance grid, CT-CP scatter).
Default mode is `coaxial` (violin plots, interaction heatmap, thrust decomposition).

---

## Performance metrics

| Metric | Formula | Notes |
| --- | --- | --- |
| CT | T / (ρ n² D⁴) | thrust coefficient |
| CP | P / (ρ n³ D⁵) | power coefficient |
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
- Test condition: tip Mach 0.228 (~653 RPM), collective 0°–12°
- Coefficient convention: CT = T/(ρ A Vtip²), CP = P/(ρ A Vtip³)

`scripts/C-T_validation.py` generates four comparison plots from experimental data (already done)
and overlays CFD results once the `caradonnaTung/` OpenFOAM cases have been run:

```bash
# Experimental reference only
python3 scripts/C-T_validation.py --outdir results_CT_validation

# With CFD overlay
python3 scripts/C-T_validation.py \
  --cfd /home/david/OpenFOAM/ENGR412/caradonnaTung/ct_results.csv \
  --outdir results_CT_validation
```

CFD CSV format: `collective_deg, thrust_N, power_W, iterations, converged`

Compressibility note: `simpleFoam` is incompressible. At Mtip = 0.228 the Prandtl-Glauert
factor is ~1.03, so CFD is expected to underpredict CT by only ~3%. The plots show a
correction band below the experimental curve representing the expected incompressible range.

---

## Dependencies (WSL Python)

```bash
sudo apt install python3-pip -y
pip3 install numpy pandas matplotlib seaborn scipy
```

VS Code: use the **Remote - WSL** extension (`ms-vscode-remote.remote-wsl`) and open
the project from inside WSL so the Python extension resolves packages correctly.
