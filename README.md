# ENGR412 — Coaxial Rotor Thrust Optimisation

Concordia University Independent Study. Uses OpenFOAM CFD simulations to build a dataset for training a neural network controller that optimises the thrust of a coaxial motor unit. The lower rotor is controlled by the NN; the upper rotor is managed by a conventional flight controller.

---

## Project overview

1. **CFD sweep** — parametric OpenFOAM simulations across rotor spacing, azimuth angle, RPM, and pitch
2. **EDA** — visualise and validate the sweep data before training
3. **NN training** — train an MLP to predict thrust/efficiency from design variables *(in progress)*
4. **Prototype** — tethered hardware validation *(planned)*

---

## Repository layout

```text
ENGR412/
├── scripts/
│   ├── generate_propeller.py   # generates NACA 4412 blade STL for snappyHexMesh
│   ├── run_sweep.py            # parametric sweep automation (all three datasets)
│   └── analyze_sweep.py        # EDA: violin plots, heatmaps, correlation matrix
└── results/
    ├── eda_summary.csv         # per-group median/IQR/p5/p95 for all metrics
    └── figures/
        ├── violin_PLnorm.png
        ├── thrust_decomp.png
        ├── interaction_heatmap.png
        ├── correlation_matrix.png
        └── convergence_hist.png
```

CFD case data lives on the WSL filesystem (not tracked in git):

```text
/home/david/OpenFOAM/ENGR412/
├── singleRotor/            # baseline single-rotor template case
├── coaxialRotor/           # coaxial two-rotor template case
├── 1_single_rotor_sweep/   # 15 cases: 5 RPM × 3 pitch
│   └── single_rotor_results.csv
├── 2_co_rot_sweep/         # 525 cases: co-rotating sweep (complete)
│   └── co_rot_results.csv
└── 2_contra_rot_sweep/     # 525 cases: counter-rotating sweep (pending)
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

> **Note:** 0.10 m spacing cases have overlapping MRF zones and should be excluded from NN training.

---

## OpenFOAM environment

- OpenFOAM 2412 on WSL2 (Ubuntu 22.04), Windows 11
- Solver: `simpleFoam` (steady-state RANS)
- Turbulence: k-ω SST
- Mesh: `blockMesh` outer domain → `snappyHexMesh` blade refinement → `topoSet` MRF zones
- Forces extracted from `postProcessing/forces*/0/force.dat` and `moment.dat`

---

## Scripts

### `generate_propeller.py`

Generates a 2-blade NACA 4412 propeller as an ASCII STL.

```bash
python3 scripts/generate_propeller.py \
  --pitch 0.4 --diameter 1.0 --rotor_z 5.0 \
  --solid_name upperPropeller \
  --output /path/to/upperPropeller.stl

# Counter-rotating lower rotor (mirrors blade about X-Z plane):
python3 scripts/generate_propeller.py \
  --pitch 0.4 --rotor_z 4.7 --mirror_y \
  --solid_name lowerPropeller \
  --output /path/to/lowerPropeller.stl
```

### `run_sweep.py`

Runs the full OpenFOAM pipeline for each case in a dataset (blockMesh → snappyHexMesh → topoSet → simpleFoam). Idempotent — safe to kill and restart.

```bash
# Single-rotor baseline (15 cases, ~30 min)
python3 scripts/run_sweep.py --dataset single --parallel 12

# Counter-rotating sweep (525 cases, ~18 h)
python3 scripts/run_sweep.py --dataset contra_rot --parallel 12

# Dry run to preview cases
python3 scripts/run_sweep.py --dataset single --dry_run

# Override specific values
python3 scripts/run_sweep.py --dataset contra_rot --spacing 0.3 --rpm 900
```

### `analyze_sweep.py`

Reads a sweep CSV, computes dimensionless coefficients (CT, CP, PLnorm = CT/CP, figure of merit), and writes plots to `results/figures/`.

```bash
# Co-rotating EDA (default paths)
python3 scripts/analyze_sweep.py

# Different dataset
python3 scripts/analyze_sweep.py \
  --csv /home/david/OpenFOAM/ENGR412/2_contra_rot_sweep/contra_rot_results.csv \
  --outdir results/contra_rot
```

---

## Performance metrics

| Metric | Formula | Notes |
| --- | --- | --- |
| CT | T / (ρ n² D⁴) | thrust coefficient |
| CP | P / (ρ n³ D⁵) | power coefficient |
| PLnorm | CT / CP | normalised power loading — primary optimisation target |
| FOM | T √(T/2ρA) / P | figure of merit (ideal actuator disk efficiency / actual) |

---

## Key EDA findings (co-rotating, 525 cases)

- RPM is the dominant driver of PLnorm; azimuth angle has near-zero effect (Pearson r ≈ 0)
- Lower rotor mean thrust is 40–55% of upper rotor thrust due to downwash (interference ratio median 0.71)
- FOM peaks at 0.10 m spacing but those cases are unphysical (MRF zone overlap) — exclude from training
- ~80% of cases ran to the 500-iteration wall; force stabilisation should be verified on a sample

---

## Dependencies (WSL Python)

```bash
sudo apt install python3-pip -y
pip3 install numpy pandas matplotlib seaborn scipy
```
