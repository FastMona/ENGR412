"""
ml/train.py -- end-to-end CLI: load CFD sweep -> train forward surrogate -> extract
optimal policy table -> distill embeddable policy MLP -> export C header.

    python3 -m ml.train \
        --csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results.csv \
        --outdir ml/artifacts

Will refuse to run past the surrogate-training step if the CSV doesn't span multiple
rpm_upper values (see ml/dataset.py::load_co_rot) -- pass --allow_single_upper to
smoke-test the code path on a single-rpm_upper CSV anyway (e.g. an older archived
sweep); the resulting policy will be degenerate (same output regardless of commanded
rpm_upper) and is not meant to be flown or trusted, only to confirm the pipeline runs
without errors.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ml.dataset import load_co_rot, train_val_split, FEATURE_COLS_FULL
from ml.surrogate import train_surrogate, evaluate
from ml.policy_extract import build_policy_table
from ml.policy_mlp import train_policy_mlp, export_c_header


def main():
    ap = argparse.ArgumentParser(description="Train the lower-rotor control MLP pipeline")
    ap.add_argument("--csv", required=True, help="Path to co_rot_results.csv")
    ap.add_argument("--outdir", default="ml/artifacts", help="Where to write the C header")
    ap.add_argument("--objective", default="fom_total",
                    help="Surrogate target to maximize when building the policy table")
    ap.add_argument("--allow_single_upper", action="store_true",
                    help="Smoke-test on a single-rpm_upper dataset (degenerate policy, "
                         "not for real use -- see module docstring)")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = load_co_rot(args.csv, require_multi_upper=not args.allow_single_upper)
    print(f"Loaded {len(df)} converged rows, "
          f"rpm_upper values: {sorted(df['rpm_upper'].unique())}")

    df_train, df_val = train_val_split(df)
    surrogate = train_surrogate(df_train)
    metrics = evaluate(surrogate, df_val)
    print("Surrogate held-out metrics:")
    for col, m in metrics.items():
        print(f"  {col:16s} R2={m['r2']:.3f}  MAPE={m['mape_pct']:.1f}%")

    rpm_upper_grid = sorted(df["rpm_upper"].unique())
    policy_table = build_policy_table(
        surrogate,
        rpm_upper_grid=rpm_upper_grid,
        spacing_grid=sorted(df["spacing_m"].unique()),
        azimuth_grid=sorted(df["azimuth_deg"].unique()),
        rpm_lower_grid=sorted(df["rpm_lower"].unique()),
        objective=args.objective,
    )
    policy_table.to_csv(outdir / "policy_table.csv", index=False)
    print(f"Wrote {outdir / 'policy_table.csv'} ({len(policy_table)} rpm_upper points)")

    policy = train_policy_mlp(policy_table)
    header_path = outdir / "policy_mlp.h"
    export_c_header(policy, str(header_path))
    print(f"Wrote {header_path}")


if __name__ == "__main__":
    main()
