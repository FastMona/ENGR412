"""
ml_scripts/train.py -- end-to-end CLI: load CFD sweep -> train forward surrogate -> extract
optimal policy table -> distill embeddable policy MLP -> export C header.

    python3 -m ml_scripts.train \
        --csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results.csv \
        --outdir ml_scripts/artifacts

Will refuse to run past the surrogate-training step if the CSV doesn't span multiple
rpm_upper values (see ml_scripts/dataset.py::load_co_rot) -- pass --allow_single_upper to
smoke-test the code path on the current single-RPM dataset anyway; the resulting
policy will be degenerate (same output regardless of commanded rpm_upper) and is not
meant to be flown or trusted, only to confirm the pipeline runs without errors.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from ml_scripts.dataset import load_co_rot, train_val_split, FEATURE_COLS_FULL
from ml_scripts.surrogate import train_surrogate, evaluate
from ml_scripts.policy_extract import build_policy_table
from ml_scripts.policy_mlp import train_policy_mlp, export_c_header


def main():
    ap = argparse.ArgumentParser(description="Train the lower-rotor control MLP pipeline")
    ap.add_argument("--csv", required=True, help="Path to co_rot_results.csv")
    ap.add_argument("--outdir", default="ml_scripts/artifacts", help="Where to write the C header")
    ap.add_argument("--objective", default="thrust_total_N",
                    help="Surrogate target to maximize when building the policy table. "
                         "Changed default from fom_total to thrust_total_N per "
                         "PROJECT_STATE Sec 2.10/2.22 -- power is enforced as a "
                         "constraint (--no_power_constraint to disable), not folded "
                         "into the objective itself.")
    ap.add_argument("--no_power_constraint", action="store_true",
                    help="Disable the power_total<=P_ref constraint (Sec 2.21) and "
                         "fall back to a bare unconstrained argmax over --objective. "
                         "Off by default -- this is the constraint that was entirely "
                         "missing before Sec 2.22's fix.")
    ap.add_argument("--rpm_lower_search_points", type=int, default=101,
                    help="Densify the rpm_lower search to this many points across "
                         "the tested range, instead of only the 5 literal CFD-tested "
                         "values -- closes the coarse-grid artifact in Sec 2.25. Pass "
                         "0 to search only the literal grid (old behaviour).")
    ap.add_argument("--rpm_upper_search_points", type=int, default=51,
                    help="Densify the rpm_upper sweep used for stage-B policy "
                         "extraction (task #16) to this many points across the "
                         "tested range, instead of only the literal CFD-tested "
                         "values (5 on FINAL.csv). PROJECT_STATE Sec 5.2 calls for "
                         "sweeping rpm_upper 'densely across its continuous range' "
                         "-- rpm_upper is the controller's actual runtime input "
                         "(Sec 1.1), so stage C needs many more than 5 label pairs "
                         "to learn a smooth mapping, not just one row per literal "
                         "CFD point. This is safe because the surrogate is trained "
                         "on rpm_upper as a continuous feature and its interior-RPM "
                         "interpolation was validated in Sec 4.8's held-out-RPM "
                         "check (R2=0.92-0.96, task #15) -- it is not extrapolation. "
                         "Pass 0 to search only the literal grid (old behaviour, "
                         "which is what every run before task #16 actually did).")
    ap.add_argument("--allow_single_upper", action="store_true",
                    help="Smoke-test on a single-rpm_upper dataset (degenerate policy, "
                         "not for real use -- see module docstring)")
    ap.add_argument("--continuity_bonus_frac", type=float, default=0.0,
                    help="`[2026-07-30]` Opt-in, default 0.0 (no behaviour change). "
                         "Boosts candidates matching the previous rpm_upper grid "
                         "point's (spacing,azimuth) tier by this fraction of the "
                         "best feasible value, so stage-B only switches tiers on a "
                         "clear win -- suppresses spurious flip-flopping between "
                         "near-tied candidates (observed on CLEAN_v3: 3 switches "
                         "between spacing=0.20/0.60m) without masking a genuine "
                         "structural crossing (confirmed present on the current "
                         "dataset's low-rpm_upper edge via a densified sweep -- "
                         "stable ~20 RPM on both sides, not noise). 0.02 tested "
                         "and removed 2 of the noisiest azimuth flips on the "
                         "current dataset with no observed downside; not yet the "
                         "default pending review.")
    ap.add_argument("--rpm_upper_dense_zone", default=None,
                    help="'lo,hi,n' -- add n extra rpm_upper points evenly spaced "
                         "in [lo,hi] on top of the standard --rpm_upper_search_points "
                         "grid, to give stage-C more label resolution around a known "
                         "sharp transition instead of relying on the uniform grid to "
                         "happen to sample it densely enough. `[2026-07-30]`: the "
                         "current dataset has a confirmed genuine (not noisy) "
                         "spacing/azimuth crossing between rpm_upper 524.1-545 "
                         "(diagnosed via a standalone densified sweep) that the "
                         "default 51-point uniform grid only samples with 2-3 "
                         "points on the narrow side -- try e.g. '524.1,545,30'. "
                         "Opt-in, no effect if omitted.")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = load_co_rot(args.csv, require_multi_upper=not args.allow_single_upper)
    n_converged = int(df["is_converged"].sum()) if "is_converged" in df.columns else len(df)
    print(f"Loaded {len(df)} rows ({n_converged} converged, "
          f"{len(df) - n_converged} time-averaged, kept as a feature not dropped -- "
          f"PROJECT_STATE Sec 2.22), rpm_upper values: {sorted(df['rpm_upper'].unique())}")

    df_train, df_val = train_val_split(df)
    surrogate = train_surrogate(df_train)
    metrics = evaluate(surrogate, df_val)
    print("Surrogate held-out metrics:")
    for col, m in metrics.items():
        print(f"  {col:16s} R2={m['r2']:.3f}  MAPE={m['mape_pct']:.1f}%")

    literal_rpm_upper = sorted(df["rpm_upper"].unique())
    if args.rpm_upper_search_points:
        rpm_upper_grid = list(np.linspace(
            min(literal_rpm_upper), max(literal_rpm_upper), args.rpm_upper_search_points
        ))
        print(f"Stage-B rpm_upper sweep: {args.rpm_upper_search_points} dense points "
              f"across [{min(literal_rpm_upper)}, {max(literal_rpm_upper)}] "
              f"(literal CFD-tested values were only {literal_rpm_upper} -- Sec 5.2/#16)")
    else:
        rpm_upper_grid = literal_rpm_upper
        print(f"Stage-B rpm_upper sweep: literal CFD-tested values only {literal_rpm_upper} "
              f"(--rpm_upper_search_points=0 -- degenerate, few-label stage-C training set)")

    if args.rpm_upper_dense_zone:
        lo, hi, n = args.rpm_upper_dense_zone.split(",")
        lo, hi, n = float(lo), float(hi), int(n)
        extra = list(np.linspace(lo, hi, n))
        rpm_upper_grid = sorted(set(rpm_upper_grid) | set(extra))
        print(f"Added {n} dense points in [{lo}, {hi}] to the rpm_upper sweep "
              f"(now {len(rpm_upper_grid)} total points) -- targeted densification "
              f"around a known sharp transition, not a general density increase.")

    policy_table = build_policy_table(
        surrogate,
        rpm_upper_grid=rpm_upper_grid,
        spacing_grid=sorted(df["spacing_m"].unique()),
        azimuth_grid=sorted(df["azimuth_deg"].unique()),
        rpm_lower_grid=sorted(df["rpm_lower"].unique()),
        objective=args.objective,
        constrain_power=not args.no_power_constraint,
        rpm_lower_search_points=(args.rpm_lower_search_points or None),
        continuity_bonus_frac=args.continuity_bonus_frac,
    )
    policy_table.to_csv(outdir / "policy_table.csv", index=False)
    print(f"Wrote {outdir / 'policy_table.csv'} ({len(policy_table)} rpm_upper points)")

    policy = train_policy_mlp(policy_table)
    header_path = outdir / "policy_mlp.h"
    export_c_header(policy, str(header_path))
    print(f"Wrote {header_path}")


if __name__ == "__main__":
    main()
