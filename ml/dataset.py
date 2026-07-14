"""
ml/dataset.py -- load and clean the co-rotating coaxial sweep CSV for MLP training.

Reads co_rot_results.csv (produced by scripts/run_sweep.py --dataset co_rot) and
applies the exclusions/cleaning already established by EDA on the prior (superseded,
525-case) dataset -- see README.md "Key EDA findings" and project memory. These rules
are re-stated here explicitly rather than assumed, because the current 140-case design
space has NOT yet had its own EDA pass (README: "EDA -- co-rotating: pending, awaiting
re-run") -- so azimuth-negligible in particular should be re-checked against the new
data, not taken on faith from the old 525-case study.

Cleaning applied:
  - drop rows where `converged` is falsy (matches the force_converged() check added to
    run_ct_sweep.py on the tier2-structured-mesh branch; run_sweep.py's dual-rotor path
    still hardcodes converged=True at write time, so this is currently a no-op filter
    until that gets the same convergence check -- kept here so it activates for free
    once it does).
  - spacing == 0.10 m is excluded by construction (not in DESIGN_SPACE_DUAL any more --
    the MRF-zone-overlap issue that made those cases unphysical is why it was dropped
    from the design space already; nothing to filter here, just documented).
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
    This is the actual current state of the dataset (RPM_UPPER was fixed at 900 for
    all 140 cases) -- a forward surrogate trained on a single rpm_upper value cannot
    learn how the optimum shifts with commanded upper RPM, which is the entire point
    of the "MLP controls lower rotor as a function of upper rotor RPM" objective. Set
    to False only to smoke-test the pipeline on the existing single-RPM data.
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
            "Re-run scripts/run_sweep.py --dataset co_rot --rpm_upper <v1> <v2> ... to "
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
