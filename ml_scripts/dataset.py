"""
ml_scripts/dataset.py -- load and clean the co-rotating coaxial sweep CSV for MLP training.

Reads co_rot_results.csv (produced by cfd_scripts/run_sweep.py --dataset co_rot). As of
2026-07-29 that file has grown to 1625 rows (5 spacing x 13 azimuth x 5 rpm_lower x 5
rpm_upper -- the original 1125-case grid plus 500 cases added to densify the azimuth
grid's sparsely-sampled flanks), 98.0% converged. Azimuth is a real, strong,
non-monotonic effect and stays a required controller output -- see README_ML.md's
"Azimuth is a real, strong, non-monotonic effect" section for the evidence.
`ml_scripts/eda_azimuth_sensitivity.py` remains useful as a re-runnable regression
check, not as an open investigation.

Cleaning applied:
  - `converged` is no longer hard-dropped. Dropping non-converged rows outright
    thinned the training set unevenly at exactly the two largest spacings (removed
    84-99% of rows at spacing 0.05/0.10/0.20 m but only 40%/72% at 0.35/0.60 m).
    Convergence status is instead exposed as the `is_converged` feature
    (FEATURE_COLS_FULL) so the surrogate learns from every row while still knowing
    which are less trustworthy -- sklearn's MLPRegressor.fit() has no sample_weight
    support, so this uses the feature route rather than weighting. Pass
    drop_unconverged=True to restore the old hard-drop behaviour.
  - spacing == 0.10 m was previously excluded by construction (MRF-zone-overlap
    issue). As of 2026-07-15 the design space and MRF zone sizing were revised (see
    analysis/stacked_rotor_literature_pivot_2026-07-15.md on the main ENGR412 repo):
    spacing now starts at MRF_FEASIBLE_MIN_SPACING (0.05 m, derived from the
    project's hub-depth spec) with denser sampling in the close-spacing regime the
    literature says matters most, and azimuth_deg is now a symmetric, zero-dense
    grid instead of 0-90 only. Separately, a mesh-refinement study later confirmed
    spacing == 0.10 m rows are geometrically under-resolved on the base mesh
    (fom_total moves 20-99% under a finer mesh at every azimuth tested) -- flagged
    in the CSV via a `mesh_diagnostic_flag` column (UNDER_RESOLVED_TIGHT_SPACING).
    Dropped by default (drop_unreliable_mesh=True), per explicit user instruction.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd

FEATURE_COLS_FULL = ["rpm_upper", "spacing_m", "azimuth_deg", "rpm_lower", "is_converged",
                     "spacing_inv_m", "azimuth_folded_deg"]
TARGET_COLS       = ["thrust_total_N", "power_total_W", "fom_total"]

# `[2026-07-29]` PROJECT_STATE Sec 2.32/2.33 (CLEAN_v2/v3.csv): two physics-informed
# features layered on top of the raw design vector.
#   - spacing_inv_m = 1/spacing_m: Biot-Savart induced-velocity falloff between rotors
#     goes as 1/d, not d itself -- gives the surrogate a feature that's linear in the
#     physically-relevant quantity near small spacing, where the raw spacing_m feature
#     is most nonlinear (see policy_extract.py's SPACING_FLOOR_TRAINED_M discussion).
#   - azimuth_folded_deg = azimuth_deg % 180: confirmed 180-degree periodicity for a
#     2-bladed rotor (azimuth=+90/-90 give identical CFD results to 6 decimal places,
#     Sec 2.32) -- folding removes a redundant degree of freedom the raw azimuth_deg
#     feature would otherwise force the MLP to learn from scratch.
#
# Computed unconditionally in load_co_rot() below (not trusted from the CSV even if
# present) so there is exactly one source of truth for the definitions, and so this
# module works identically on CSVs that do/don't already carry these columns. Also
# exposed as add_engineered_features() so any code that constructs a *hypothetical*
# candidate row for surrogate.predict() (ml_scripts/policy_extract.py's grid_df/baseline_df,
# built directly as DataFrames, not read from load_co_rot()) can compute the same two
# columns rather than silently KeyError-ing once FEATURE_COLS_FULL includes them.


def add_engineered_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["spacing_inv_m"] = 1.0 / df["spacing_m"]
    df["azimuth_folded_deg"] = df["azimuth_deg"] % 180.0
    return df

# `is_converged` (1.0 = residual-converged, 0.0 = time-averaged fallback) lets the
# surrogate learn from all rows instead of hard-dropping the ~22% flagged
# TIME_AVERAGED (concentrated at the two largest spacings -- see PROJECT_STATE
# Sec 2.4/2.22) while still telling it which rows are less trustworthy. At
# prediction time for a *hypothetical* candidate config (ml_scripts/policy_extract.py),
# always set this to 1.0 -- we want the surrogate's best estimate of the true,
# cleanly-converged answer, not a blend with historical convergence noise at
# that operating point.

# CT/CP-style dimensionless normalization (sweep convention: CT = T/(rho n^2 D^4)),
# preferred over raw thrust/power per project memory ("dimensionless coefficients are
# preferred over raw thrust-to-power ratios for generalizability").
RHO = 1.225
D   = 1.0


def _rpm_to_n(rpm: pd.Series) -> pd.Series:
    return rpm / 60.0


def load_co_rot(csv_path: str | Path, require_multi_upper: bool = True,
                 drop_unconverged: bool = False,
                 drop_unreliable_mesh: bool = True) -> pd.DataFrame:
    """
    Load co_rot_results.csv, add an `is_converged` feature (or drop unconverged rows
    if explicitly requested), add PLnorm.

    require_multi_upper: raise if the CSV only contains a single rpm_upper value.
    A forward surrogate trained on a single rpm_upper value cannot learn how the
    optimum shifts with commanded upper RPM, which is the entire point of the "MLP
    controls lower rotor as a function of upper rotor RPM" objective -- this guard
    exists for whatever single-RPM smoke-test CSV you point it at, not because the
    production dataset is still single-valued (the current co_rot CSV already spans
    5 rpm_upper values x 325 base cases = 1625 rows, as of 2026-07-29). Set to False
    only to deliberately smoke-test the pipeline on a single-RPM CSV.

    drop_unconverged: `[2026-07-27]` default False -- this used to be a hard,
    unconditional drop of non-`converged` rows, which is *not* a no-op: it removed
    84-99% of rows at spacing 0.05/0.10/0.20 m but only 40%/72% at 0.35/0.60 m,
    silently thinning the training set unevenly at exactly the two largest spacings
    (PROJECT_STATE Sec 2.4/2.22). Default is now to keep every row and expose
    convergence status as the `is_converged` feature (FEATURE_COLS_FULL) instead,
    per Sec 5.2's "feature or sample weight" plan -- sample_weight isn't natively
    supported by sklearn's MLPRegressor, so this uses the feature route. Pass True
    to restore the old hard-drop behaviour.

    drop_unreliable_mesh: `[2026-07-29]` PROJECT_STATE Sec 2.33 -- co_rot_results.csv
    carries a `mesh_diagnostic_flag` column; all 225 spacing=0.10m rows are flagged
    "UNDER_RESOLVED_TIGHT_SPACING" (a CFD mesh-refinement study found fom_total shifts
    20-99% under refinement across that whole tier -- a mesh-resolution problem, not a
    convergence problem, so `converged`/`is_converged` doesn't catch it). Default True:
    drop these rows before training/feature-computation, per explicit user instruction
    ("discard those 225 results"). Dropped rows are simply absent from the returned
    df afterward, so spacing_m==0.10 will not appear in df["spacing_m"].unique() --
    callers that build a stage-B search grid from that (ml_scripts/train.py) correctly stop
    searching that tier too, not just stop training on it. No-op on CSVs without this
    column.
    """
    df = pd.read_csv(csv_path)

    if "converged" in df.columns:
        # Accept both real bools and the string "True"/"False" CSV round-trip.
        conv = df["converged"].astype(str).str.strip().str.lower().isin(["true", "1"])
        if drop_unconverged:
            df = df[conv].copy()
        else:
            df = df.copy()
            df["is_converged"] = conv.astype(float)
    else:
        df = df.copy()
        df["is_converged"] = 1.0

    if drop_unreliable_mesh and "mesh_diagnostic_flag" in df.columns:
        bad = df["mesh_diagnostic_flag"] == "UNDER_RESOLVED_TIGHT_SPACING"
        if bad.any():
            print(f"load_co_rot: dropping {int(bad.sum())} rows flagged "
                  f"UNDER_RESOLVED_TIGHT_SPACING (mesh-refinement-confirmed unreliable, "
                  f"PROJECT_STATE Sec 2.33) out of {len(df)} total.")
            df = df[~bad].copy()

    df = add_engineered_features(df)

    n_upper_vals = df["rpm_upper"].nunique() if "rpm_upper" in df.columns else 1
    if require_multi_upper and n_upper_vals < 2:
        raise ValueError(
            f"co_rot dataset only has {n_upper_vals} distinct rpm_upper value(s) "
            f"({sorted(df['rpm_upper'].unique()) if 'rpm_upper' in df.columns else 'column missing'}). "
            "Re-run cfd_scripts/run_sweep.py --dataset co_rot --rpm_upper <v1> <v2> ... to "
            "build a dataset that actually spans the operating range needed to train "
            "the upper-RPM-conditioned controller. Pass require_multi_upper=False to "
            "proceed anyway for a pipeline smoke test."
        )

    n_u = _rpm_to_n(df["rpm_upper"])
    df["ct_total"] = df["thrust_total_N"] / (RHO * n_u**2 * D**4)
    df["cp_total"] = df["power_total_W"] / (RHO * n_u**3 * D**5)
    df["plnorm"]   = df["ct_total"] / df["cp_total"].replace(0, float("nan"))

    return df.reset_index(drop=True)


def train_val_split(df: pd.DataFrame, val_frac: float = 0.2, seed: int = 0):
    """
    Hold out entire (spacing_m, azimuth_deg) combinations, not random rows.

    `[2026-07-27]`: replaces the previous plain random row shuffle, per
    PROJECT_STATE Sec 4.8/2.22 -- a random split on this dense regular grid mostly
    measures memorization, since near-identical rows (same spacing/azimuth,
    adjacent RPM) end up on both sides of the split. Holding out whole
    (spacing, azimuth) pairs means every row sharing a held-out pair -- across all
    rpm_upper/rpm_lower combinations for it -- moves to validation together, so
    held-out performance actually reflects interpolation onto an unseen spatial
    combination.

    Does not by itself test the other axis Sec 4.8 flags as weakest
    (interpolation in rpm_upper, only 5 levels) -- that needs a separate,
    explicit interior-RPM hold-out, done as its own check (Sec 4.8's validation
    plan), not folded into this default split.
    """
    combo_cols = ["spacing_m", "azimuth_deg"]
    combos = (
        df[combo_cols].drop_duplicates()
        .sample(frac=1.0, random_state=seed)
        .reset_index(drop=True)
    )
    n_val_combos = max(1, int(round(len(combos) * val_frac)))
    val_combos = combos.iloc[:n_val_combos]

    val_index = pd.MultiIndex.from_frame(val_combos[combo_cols])
    row_index = pd.MultiIndex.from_frame(df[combo_cols])
    is_val = row_index.isin(val_index)

    df_val = df[is_val].reset_index(drop=True)
    df_train = df[~is_val].reset_index(drop=True)
    return df_train, df_val
