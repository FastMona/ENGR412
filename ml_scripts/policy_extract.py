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

`[2026-07-27]` Updated per PROJECT_STATE Sec 2.22 (four gaps found between this
module and settled project decisions):
  - `objective` default changed from "fom_total" to "thrust_total_N" -- Sec 2.10
    settles thrust_total as the objective; FoM is a reporting metric only.
  - Added the power constraint from Sec 2.21 (`power_total <= P_ref`), previously
    entirely absent -- this module used to do a bare unconstrained argmax, which
    is the most likely real explanation for the historical rpm_lower-saturation
    finding (Sec 2.18's pre-fix 700-case run), not anything inherent to the
    objective's form (see Sec 2.24's empirical check on the corrected version).
  - Candidate rows now carry `is_converged=1.0` (dataset.py's new feature, Sec
    2.22) -- we want the surrogate's best estimate of the true, cleanly-converged
    answer for a hypothetical config, not a blend with historical convergence
    noise at that operating point.
  - `rpm_lower` search is now optionally densified past the 5 literal CFD-tested
    values, closing the coarse-grid "cliff" artifact noted in Sec 2.25 (a real
    discontinuity-looking jump that was actually just argmax flipping between
    two coarse candidates on an otherwise-smooth surrogate).
"""
from __future__ import annotations

import itertools
import numpy as np
import pandas as pd

from ml_scripts.surrogate import Surrogate
from ml_scripts.dataset import add_engineered_features

# P_ref's baseline azimuth. The identical-RPM baseline (Sec 2.10/2.21) is defined
# as "both rotors at the commanded rpm_upper" -- azimuth=0 is the natural
# zero-offset reading of that, though PROJECT_STATE Sec 2.21 doesn't spell this
# out explicitly (flagged there and in Sec 2.24). Kept as a module constant so
# it's one documented place, not a silent literal.
BASELINE_AZIMUTH_DEG = 0.0

# Stage-B spacing floor -- decided `[2026-07-27]`, PROJECT_STATE Sec 2.3/5.2/4-13.
# Two candidate floors exist: 0.030 m is the true physical hub-thickness minimum
# (HUB_DEPTH_FRAC=0.03 at D=1.0m, Sec 2.3) -- the real hardware constraint. 0.050 m
# is just where the MRF-feasibility floor happened to land the CFD sweep (a
# numerical meshing constraint, not a physical one) -- but it's also the smallest
# spacing the stage-A surrogate has ever seen.
#
# DECISION: use 0.050 m as the actual stage-B search floor, not 0.030 m. Below
# 50mm the surrogate is extrapolating outside its training distribution, and
# per Sec 2.13's own BVI theory, spacing-vs-interaction-strength gets *more*
# nonlinear as spacing shrinks (near-singular Gamma/(2*pi*d) vortex-induced
# field) -- i.e. 30-50mm is precisely the region where the true physics moves
# fastest and an MLP's extrapolation is least trustworthy. A spurious label
# generated down there would be indistinguishable from a real one in the output
# table. 0.030 m is kept only as the disclosed design-intent bound for the
# paper's limitations section, not as a value stage B is allowed to search.
#
# Current spacing_grid arguments to build_policy_table() are always the literal
# CFD-tested values (0.05/0.10/0.20/0.35/0.60 m), all >= this floor already, so
# this constant is a no-op today -- it exists so that if/when the spacing search
# is ever densified the way rpm_lower_search_points densifies rpm_lower
# (Sec 2.25), whoever does that has an explicit, documented floor to enforce
# rather than silently reaching into the extrapolation region.
SPACING_FLOOR_TRAINED_M = 0.050


def _rpm_lower_search_grid(rpm_lower_grid: list[float], n_points: int | None) -> list[float]:
    """
    Sec 2.25: build_policy_table used to search only the literal CFD-tested
    rpm_lower values (5 points), which produced an apparent discontinuity in the
    policy table (optimal rpm_lower jumping between adjacent grid candidates)
    that wasn't a real physical cliff -- the surrogate itself is smooth. If
    n_points is given, search a dense linspace across the tested range instead;
    if None, fall back to the literal grid (old behaviour, kept as an explicit
    opt-in rather than a silently changed default).
    """
    if n_points is None:
        return list(rpm_lower_grid)
    lo, hi = min(rpm_lower_grid), max(rpm_lower_grid)
    return list(np.linspace(lo, hi, n_points))


def build_policy_table(
    surrogate: Surrogate,
    rpm_upper_grid: list[float],
    spacing_grid: list[float],
    azimuth_grid: list[float],
    rpm_lower_grid: list[float],
    objective: str = "thrust_total_N",
    constrain_power: bool = True,
    rpm_lower_search_points: int | None = 101,
    continuity_bonus_frac: float = 0.0,
) -> pd.DataFrame:
    """
    For each rpm_upper in rpm_upper_grid, evaluate the surrogate over the full
    (spacing, azimuth, rpm_lower) grid and keep the row maximizing `objective`,
    subject to a power constraint (PROJECT_STATE Sec 2.21): predicted
    power_total_W <= P_ref, where P_ref is the power drawn by the identical-RPM
    baseline (rpm_lower=rpm_upper, azimuth=BASELINE_AZIMUTH_DEG) **at the same
    spacing as the candidate row** -- this baseline-spacing choice is an
    assumption (Sec 2.21's text only pins down the RPM equality, not which
    spacing "the" baseline uses; Sec 2.24 flags this same gap), documented here
    as the convention now in force, not something settled elsewhere.

    objective: one of the surrogate's target_cols. Default is "thrust_total_N"
    per Sec 2.10 (the settled objective) -- changed from the old "fom_total"
    default. FoM is a reporting metric only (Sec 2.10/2.21), not the training
    objective.

    constrain_power: if True (default), only candidates with predicted
    power_total_W <= P_ref(rpm_upper, spacing) are eligible for the argmax.
    Requires "power_total_W" in the surrogate's target_cols. If, for some
    rpm_upper, nothing in the search grid is feasible (shouldn't happen -- the
    identical-RPM baseline itself is always feasible, power_total == P_ref
    exactly, since it's what defines P_ref) falls back explicitly to that
    baseline at the first spacing in spacing_grid, rather than silently
    returning an infeasible "best".

    rpm_lower_search_points: if given (default 101), search a dense linspace
    across [min(rpm_lower_grid), max(rpm_lower_grid)] instead of only the
    literal CFD-tested values -- closes the coarse-grid artifact in Sec 2.25.
    Pass None to restore the old literal-grid-only behaviour.

    continuity_bonus_frac: `[2026-07-30]` opt-in, default 0.0 (no behaviour
    change). When > 0, candidates sharing the previous rpm_upper grid point's
    chosen (spacing_m, azimuth_deg) tier get their predicted objective boosted
    by this fraction of the current point's best feasible value before the
    argmax, so a switch to a different (spacing, azimuth) tier only happens
    when it's a clear win, not a razor-thin one. This does not eliminate a
    genuine crossing between two competing optima (confirmed present on this
    project's own data right at the low-rpm_upper edge -- diagnosed via a
    densified rpm_upper sweep, stable on both sides for ~20 RPM, not noisy
    flip-flopping); it exists to suppress *spurious* flip-flopping between
    near-tied candidates (previously observed on CLEAN_v3: 3 switches between
    spacing=0.20m/0.60m rather than 1), which is a different failure mode from
    a real, structural crossing. Requires `rpm_upper_grid` sorted ascending
    (true of every call site so far, which all build it via `np.linspace`).
    """
    if objective not in surrogate.target_cols:
        raise ValueError(
            f"objective={objective!r} is not one of the surrogate's trained targets "
            f"{surrogate.target_cols}. Retrain the surrogate with this target included, "
            "or compute it from thrust_total_N/power_total_W here before ranking."
        )
    if constrain_power and "power_total_W" not in surrogate.target_cols:
        raise ValueError(
            "constrain_power=True requires 'power_total_W' in the surrogate's target_cols "
            "so P_ref can be predicted; retrain with it included or pass constrain_power=False."
        )
    below_floor = [s for s in spacing_grid if s < SPACING_FLOOR_TRAINED_M]
    if below_floor:
        raise ValueError(
            f"spacing_grid contains values below SPACING_FLOOR_TRAINED_M "
            f"({SPACING_FLOOR_TRAINED_M} m): {below_floor}. These are below the surrogate's "
            "trained range (extrapolation, not interpolation -- PROJECT_STATE Sec 2.3/5.2) "
            "and are physically unreachable for the true hub-thickness floor argument to "
            "apply -- 0.030 m is the design-intent bound, not a searchable value. Drop them "
            "from spacing_grid before calling."
        )
    has_is_converged = "is_converged" in surrogate.feature_cols

    search_rpm_lower = _rpm_lower_search_grid(rpm_lower_grid, rpm_lower_search_points)
    combos = list(itertools.product(spacing_grid, azimuth_grid, search_rpm_lower))
    obj_idx = surrogate.target_cols.index(objective)
    power_idx = surrogate.target_cols.index("power_total_W") if constrain_power else None

    def _with_is_converged(df: pd.DataFrame) -> pd.DataFrame:
        # Hypothetical candidates, never actually measured -- ask the surrogate
        # for its best estimate of the clean, converged answer (Sec 2.22), not a
        # blend with historical convergence noise at that operating point.
        if has_is_converged:
            df = df.copy()
            df["is_converged"] = 1.0
        return df

    rows = []
    prev_choice = None  # (spacing_m, azimuth_deg) tier chosen at the previous rpm_upper
    for rpm_upper in rpm_upper_grid:
        grid_df = pd.DataFrame(combos, columns=["spacing_m", "azimuth_deg", "rpm_lower"])
        grid_df["rpm_upper"] = rpm_upper
        grid_df = _with_is_converged(grid_df)
        # `[2026-07-29]` Sec 2.32/2.33: these are hypothetical candidate rows built
        # directly as DataFrames, never routed through ml_scripts/dataset.py::load_co_rot(),
        # so spacing_inv_m/azimuth_folded_deg must be computed here too now that
        # FEATURE_COLS_FULL includes them -- otherwise surrogate.predict()'s
        # X[self.feature_cols] indexing raises a KeyError. Harmless no-op for
        # surrogates trained without these features (extra columns are just ignored
        # by that same indexing).
        grid_df = add_engineered_features(grid_df)
        preds = surrogate.predict(grid_df)

        if constrain_power:
            baseline_df = pd.DataFrame({
                "spacing_m": spacing_grid,
                "azimuth_deg": BASELINE_AZIMUTH_DEG,
                "rpm_lower": rpm_upper,
                "rpm_upper": rpm_upper,
            })
            baseline_df = _with_is_converged(baseline_df)
            baseline_df = add_engineered_features(baseline_df)
            baseline_preds = surrogate.predict(baseline_df)
            p_ref_by_spacing = dict(zip(spacing_grid, baseline_preds[:, power_idx]))

            p_ref = grid_df["spacing_m"].map(p_ref_by_spacing).to_numpy()
            feasible = preds[:, power_idx] <= p_ref

            if not feasible.any():
                fallback_spacing = spacing_grid[0]
                best = {
                    "spacing_m": fallback_spacing,
                    "azimuth_deg": BASELINE_AZIMUTH_DEG,
                    "rpm_lower": rpm_upper,
                    "rpm_upper": rpm_upper,
                    objective: p_ref_by_spacing[fallback_spacing],
                }
                rows.append(best)
                continue

            cand_idx = np.where(feasible)[0]
        else:
            cand_idx = np.arange(len(grid_df))

        cand_scores = preds[cand_idx, obj_idx].copy()
        if continuity_bonus_frac and prev_choice is not None:
            same_tier = (
                np.isclose(grid_df["spacing_m"].to_numpy()[cand_idx], prev_choice[0])
                & np.isclose(grid_df["azimuth_deg"].to_numpy()[cand_idx], prev_choice[1])
            )
            if same_tier.any():
                bonus = continuity_bonus_frac * cand_scores.max()
                cand_scores = cand_scores + np.where(same_tier, bonus, 0.0)

        best_i = int(cand_idx[np.argmax(cand_scores)])

        best = grid_df.iloc[best_i].drop(
            labels=["is_converged", "spacing_inv_m", "azimuth_folded_deg"], errors="ignore"
        ).to_dict()
        best[objective] = float(preds[best_i, obj_idx])
        rows.append(best)
        prev_choice = (best["spacing_m"], best["azimuth_deg"])

    return pd.DataFrame(rows)
