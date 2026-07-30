"""
ml_scripts/dataset.py -- load and clean the co-rotating coaxial sweep CSV for MLP training.

Reads co_rot_results.csv (produced by cfd_scripts/run_sweep.py --dataset co_rot). As of
2026-07-29 that file has grown to 1625 rows (5 spacing x 13 azimuth x 5 rpm_lower x 5
rpm_upper -- the original 1125-case grid plus 500 cases added to densify the azimuth
grid's sparsely-sampled flanks), 98.0% converged. The azimuth-negligible question this
docstring used to flag as unresolved is now settled the other way: azimuth is a real,
strong, non-monotonic effect and must stay a required controller output -- see
README_ML.md's "Azimuth is a real, strong, non-monotonic effect" section for the
evidence. `ml_scripts/eda_azimuth_sensitivity.py` remains useful as a re-runnable
regression check, not as an open investigation.

Cleaning applied:
  - drop rows where `converged` is falsy. run_sweep.py's dual-rotor path now computes
    this for real via force_converged() (tail-window std/mean check on the force
    history, added 2026-07-29 alongside a graded "data_quality" column --
    CONVERGED_TIGHT/CONVERGED/BORDERLINE/NOT_CONVERGED/MISSING -- and a
    "convergence_ratio" column, both of which this loader does not yet consume; it
    only reads the coarser boolean and hard-drops on it. The project's stated plan is
    to treat convergence as a feature (e.g. `is_converged`) or sample weight instead of
    a hard drop, since sklearn's MLPRegressor.fit() has no sample_weight support -- not
    yet implemented here; see README_ML.md's "Known gaps" section).
  - spacing == 0.10 m was previously excluded by construction (MRF-zone-overlap issue).
    As of 2026-07-15 the design space and MRF zone sizing were revised (see
    analysis/stacked_rotor_literature_pivot_2026-07-15.md on the main ENGR412 repo):
    spacing now starts at MRF_FEASIBLE_MIN_SPACING (0.05 m, derived from the project's
    hub-depth spec) with denser sampling in the close-spacing regime the literature
    says matters most, and azimuth_deg is now a symmetric, zero-dense grid instead of
    0-90 only. Separately, a mesh-refinement study later confirmed spacing == 0.10 m
    rows are geometrically under-resolved on the base mesh (fom_total moves 20-99%
    under a finer mesh at every azimuth tested) -- flagged in the CSV via a
    "mesh_diagnostic_flag" column (UNDER_RESOLVED_TIGHT_SPACING) that, like the graded
    convergence columns above, this loader does not yet read or act on.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd

FEATURE_COLS_FULL = ["rpm_upper", "spacing_m", "azimuth_deg", "rpm_lower"]
TARGET_COLS       = ["thrust_total_N", "power_total_W", "fom_total"]

# CT/CP-style dimensionless normalization (sweep convention: CT = T/(rho n^2 D^4)),
# preferred over raw thrust/power per project memory ("dimensionless coefficients are
# preferred over raw thrust-to-power ratios for generalizability").
RHO = 1.225
D   = 1.0


def _rpm_to_n(rpm: pd.Series) -> pd.Series:
    return rpm / 60.0


def load_co_rot(csv_path: str | Path, require_multi_upper: bool = True) -> pd.DataFrame:
    """
    Load co_rot_results.csv, drop non-converged rows, add PLnorm.

    require_multi_upper: raise if the CSV only contains a single rpm_upper value.
    A forward surrogate trained on a single rpm_upper value cannot learn how the
    optimum shifts with commanded upper RPM, which is the entire point of the "MLP
    controls lower rotor as a function of upper rotor RPM" objective -- this guard
    exists for whatever single-RPM smoke-test CSV you point it at, not because the
    production dataset is still single-valued (the current co_rot CSV already spans
    5 rpm_upper values x 325 base cases = 1625 rows, as of 2026-07-29). Set to False
    only to deliberately smoke-test the pipeline on a single-RPM CSV.
    """
    df = pd.read_csv(csv_path)

    if "converged" in df.columns:
        # Accept both real bools and the string "True"/"False" CSV round-trip.
        conv = df["converged"].astype(str).str.strip().str.lower()
        df = df[conv.isin(["true", "1"])].copy()

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
    """Grouped-ish shuffle split (no group leakage concern here -- each row is an
    independent CFD case, not repeated measurements of the same case)."""
    shuffled = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    n_val = int(len(shuffled) * val_frac)
    return shuffled.iloc[n_val:].reset_index(drop=True), shuffled.iloc[:n_val].reset_index(drop=True)
