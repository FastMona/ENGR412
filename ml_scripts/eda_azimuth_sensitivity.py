"""
ml_scripts/eda_azimuth_sensitivity.py -- check whether the real co_rot sweep reproduces the
azimuth-sensitivity trends reported in the stacked/co-rotating rotor literature.

Why this exists: ml_scripts/README.md carries an open flag from the prior (525-case,
superseded) EDA that found azimuth angle "aerodynamically negligible", with an
explicit note not to trust that until the real 700-case sweep gets its own EDA.
Two directly-relevant papers have since been reviewed (Jacobellis et al. 2021,
Aerosp. Sci. Technol. 116:106847; Hong et al. 2023, Aerosp. Sci. Technol.
141:108557) -- both stacked/co-rotating coaxial rotor studies sweeping essentially
the same design variables (azimuthal/index angle, axial/stacking spacing) as this
project's co_rot dataset. Both report azimuth as one of the two dominant physical
effects on rotor performance:

  - Jacobellis: 17.1% total-thrust swing over a 22.5 deg azimuth change at fixed
    collective/spacing (0.76%/deg sensitivity); minimum near phi=0, rising toward
    phi=+17 deg at z/c=0.73.
  - Hong: azimuth-dependent efficiency (PLnorm) optimum whose *location* shifts
    with stacking distance (small Z -> optimum near phi=+90; larger Z -> optimum
    migrates to moderate positive index angles as the blade-vortex-interaction
    effect starts to dominate over near-field airfoil interaction).

If azimuth comes back negligible in *our* real sweep despite this, that's grounds
to suspect the sweep itself (near-body resolution in the blade-blade gap, azimuth
sampling density, MRF/domain sizing) rather than to conclude azimuth doesn't
matter for our geometry -- see analysis/stacked_rotor_literature_pivot_2026-07-15.md
on the main ENGR412 repo for the full writeup.

Usage:
    python3 -m ml_scripts.eda_azimuth_sensitivity --csv /path/to/co_rot_results.csv
"""
from __future__ import annotations

import argparse

import pandas as pd

from ml_scripts.dataset import load_co_rot

# Literature-derived sanity thresholds (not hard pass/fail gates -- our geometry,
# RPM range, and CFD fidelity all differ from these papers -- but if we land far
# outside these, it's worth a second look, not a shrug).
LIT_THRUST_SWING_PCT_LOW = 5.0    # Jacobellis saw 17.1% at just 22.5 deg of sweep;
                                  # our full +/-azimuth range should plausibly beat this.
LIT_EFFICIENCY_GAIN_PCT_LOW = 1.0  # Both papers: 2-12% achievable efficiency gain
                                   # from azimuth/spacing alone.


def swing_pct(series: pd.Series) -> float:
    mean = series.mean()
    if mean == 0 or pd.isna(mean):
        return float("nan")
    return (series.max() - series.min()) / abs(mean) * 100.0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", required=True, help="Path to co_rot_results.csv")
    args = ap.parse_args()

    df = load_co_rot(args.csv, require_multi_upper=False)
    print(f"Loaded {len(df)} converged rows from {args.csv}\n")

    group_cols = [c for c in ["rpm_upper", "spacing_m", "rpm_lower"] if c in df.columns]
    if not group_cols:
        raise SystemExit("Expected at least one of rpm_upper/spacing_m/rpm_lower in the CSV.")

    print("=== Azimuth sensitivity, held fixed at each (rpm_upper, spacing_m, rpm_lower) ===\n")
    rows = []
    for keys, g in df.groupby(group_cols):
        if g["azimuth_deg"].nunique() < 2:
            continue  # nothing to sweep against within this group
        t_swing = swing_pct(g["thrust_total_N"])
        pl_swing = swing_pct(g["plnorm"])
        best_row = g.loc[g["plnorm"].idxmax()]
        rows.append({
            **dict(zip(group_cols, keys if isinstance(keys, tuple) else (keys,))),
            "n_azimuth_points": g["azimuth_deg"].nunique(),
            "thrust_swing_pct": t_swing,
            "plnorm_swing_pct": pl_swing,
            "best_azimuth_deg": best_row["azimuth_deg"],
            "best_plnorm": best_row["plnorm"],
        })

    if not rows:
        raise SystemExit(
            "No group had more than one azimuth_deg value -- can't assess azimuth "
            "sensitivity at all with this CSV. Check that the sweep actually varied "
            "azimuth_deg within fixed spacing/RPM combinations."
        )

    summary = pd.DataFrame(rows)
    pd.set_option("display.width", 120)
    pd.set_option("display.max_rows", None)
    print(summary.to_string(index=False))

    print("\n=== Verdict vs. literature-derived thresholds ===\n")
    median_t_swing = summary["thrust_swing_pct"].median()
    median_pl_swing = summary["plnorm_swing_pct"].median()
    print(f"Median thrust swing across azimuth: {median_t_swing:.2f}%  "
          f"(Jacobellis observed 17.1% over just 22.5 deg of sweep)")
    print(f"Median PLnorm (efficiency) swing across azimuth: {median_pl_swing:.2f}%  "
          f"(both papers: 2-12% efficiency gain achievable via azimuth/spacing)")

    if median_t_swing < LIT_THRUST_SWING_PCT_LOW:
        print(
            "\n  FLAG: thrust swing across azimuth is well below what the published "
            "stacked-rotor literature reports for a comparable design-variable sweep. "
            "Given azimuth is described as one of the two dominant physical effects "
            "(the other being axial/stacking spacing), this small a swing is more "
            "consistent with the CFD sweep not resolving the blade-blade interaction "
            "(near-body mesh density in the gap, azimuthal sampling too coarse, MRF "
            "zone sizing) than with azimuth genuinely being unimportant for this "
            "geometry. Worth checking before trusting a 'azimuth is negligible' "
            "conclusion and dropping it from the policy MLP's outputs."
        )
    else:
        print(
            "\n  Consistent with the literature: azimuth has a real, non-trivial "
            "effect on thrust/efficiency in this sweep. Keep it as a controlled "
            "output of the policy MLP (see the open question in ml_scripts/README.md)."
        )

    if "spacing_m" in summary.columns and summary["spacing_m"].nunique() > 1:
        print("\n=== Does the best azimuth shift with spacing? (literature says it should) ===\n")
        by_spacing = summary.groupby("spacing_m")["best_azimuth_deg"].agg(["mean", "std"])
        print(by_spacing.to_string())
        if by_spacing["mean"].nunique() == 1:
            print(
                "\n  FLAG: best azimuth is identical across all spacing values. Hong et "
                "al. found the optimal index angle migrates substantially as stacking "
                "distance changes (near-field airfoil interaction dominant at small "
                "spacing, blade-vortex interaction dominant at larger spacing). An "
                "unchanging optimum across spacing is another signal worth checking "
                "against mesh/domain setup rather than accepting at face value."
            )


if __name__ == "__main__":
    main()
