"""
ml_scripts/policy_extract.py -- build an "optimal lower-rotor command" lookup table by
grid-searching the forward surrogate (ml_scripts/surrogate.py) over (spacing, azimuth,
rpm_lower) for each candidate rpm_upper, then hand that table to ml_scripts/policy_mlp.py for
distillation into the actual embeddable controller.

This two-stage design (forward surrogate -> grid-search optimum -> distilled small
policy net) matches the "three-tier fallback control hierarchy" in the project plan
(adaptive hybrid -> static MLP surrogate -> identical-RPM baseline): this module
produces the middle tier's training labels.

Why not train the policy directly on CFD data: the CFD sweep gives you performance
FOR a design point, not the optimal design point for an arbitrary commanded rpm_upper.
There is no CFD row labeled "if the flight controller demands 823 RPM equivalent
upper-rotor speed, here is the best lower-rotor command" -- that label has to be
constructed by optimizing over the (interpolated) performance surface, which is
exactly what the forward surrogate is for.
"""
from __future__ import annotations

import itertools
import numpy as np
import pandas as pd

from ml_scripts.surrogate import Surrogate


def build_policy_table(
    surrogate: Surrogate,
    rpm_upper_grid: list[float],
    spacing_grid: list[float],
    azimuth_grid: list[float],
    rpm_lower_grid: list[float],
    objective: str = "fom_total",
) -> pd.DataFrame:
    """
    For each rpm_upper in rpm_upper_grid, evaluate the surrogate over the full
    (spacing, azimuth, rpm_lower) grid and keep the row maximizing `objective`.

    objective: one of the surrogate's target_cols ("fom_total") or "plnorm" if you've
    added a plnorm-predicting target -- fom_total is the default here because it's
    already a raw surrogate output, NOT because it's the project's primary metric:
    README names PLnorm (CT/CP) as the actual primary optimisation target, and
    PLnorm is NOT one of the three raw surrogate targets (thrust_total_N,
    power_total_W, fom_total) by default. If you want to optimize PLnorm directly,
    either add it as a fourth surrogate target trained on ml_scripts.dataset's precomputed
    `plnorm` column, or compute CT/CP from the predicted thrust/power here and rank
    by that instead of assuming it's already a column.
    """
    if objective not in surrogate.target_cols:
        raise ValueError(
            f"objective={objective!r} is not one of the surrogate's trained targets "
            f"{surrogate.target_cols}. Retrain the surrogate with this target included, "
            "or compute it from thrust_total_N/power_total_W here before ranking."
        )

    combos = list(itertools.product(spacing_grid, azimuth_grid, rpm_lower_grid))
    rows = []
    for rpm_upper in rpm_upper_grid:
        grid_df = pd.DataFrame(combos, columns=["spacing_m", "azimuth_deg", "rpm_lower"])
        grid_df["rpm_upper"] = rpm_upper
        preds = surrogate.predict(grid_df)
        obj_idx = surrogate.target_cols.index(objective)
        best_i = int(np.argmax(preds[:, obj_idx]))
        best = grid_df.iloc[best_i].to_dict()
        best[objective] = float(preds[best_i, obj_idx])
        rows.append(best)

    return pd.DataFrame(rows)
