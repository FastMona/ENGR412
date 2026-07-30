"""
ml_scripts/policy_extract.py -- build an "optimal lower-rotor command" lookup table by
grid-searching the forward surrogate (ml_scripts/surrogate.py) over (spacing, azimuth,
rpm_lower) for each candidate rpm_upper, then hand that table to ml_scripts/policy_mlp.py for
distillation into the actual embeddable controller.

This two-stage design (forward surrogate -> grid-search optimum -> distilled small
policy net) is stage B of the project's three-stage controller-training pipeline
(stage A: forward surrogate; stage B: this module, dense label generation; stage C:
distill into the deployable policy MLP -- see README_ML.md's Pipeline section). An
earlier "three-tier fallback hierarchy" framing (adaptive hybrid -> static MLP
surrogate -> identical-RPM baseline) has since been voided along with the rest of the
project's old two-phase/hybrid-successor framing -- this is one project with one
controller, not a fallback chain.

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
    already a raw surrogate output, NOT because it's the project's decided metric.
    The project's actual decided objective (as of 2026-07-26, see README_ML.md) is
    `thrust_total_N` maximized subject to a power constraint (power held at or below
    the identical-RPM baseline) -- FOM is a *reporting* metric for the paper, not the
    training objective. Neither the `thrust_total_N` default nor the power constraint
    itself is implemented in this function yet -- this is currently a bare,
    unconstrained argmax over whatever `objective` is passed in, which will happily
    saturate `rpm_lower` at the top of its swept range if pointed at `thrust_total_N`
    with nothing holding power in check. See README_ML.md's "Known gaps" section
    before using this for anything beyond a pipeline-mechanics smoke test. Separately,
    if you want to optimize PLnorm (CT/CP) directly instead, either add it as a fourth
    surrogate target trained on ml_scripts.dataset's precomputed `plnorm` column, or
    compute CT/CP from the predicted thrust/power here and rank by that instead of
    assuming it's already a column.
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
