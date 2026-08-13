"""
ml_scripts/spot_check_policy.py -- end-to-end CFD spot check for Stage B's corrected
(pinned-P_ref) policy table.

PROJECT_STATE (through v35, 2026-08-11) records this as outstanding: "End-to-end CFD
spot check -- candidates selected, not yet executed." Whatever candidates were
selected before are stale regardless -- the P_ref baseline-spacing fix
(ml_scripts/policy_extract.py, 2026-08-12) changed which configurations the policy
table recommends (dominant pick moved from (0.6m, -10deg) to (0.35m, 90deg)/(0.2m,
90deg)), so this module picks fresh candidates directly from the corrected
ml_scripts/artifacts/policy_table.csv.

What this actually checks: the surrogate is trained on a 5(spacing) x 13(azimuth) x
5(rpm_lower) x 5(rpm_upper) literal CFD grid, but build_policy_table() densifies
rpm_lower to 101 points and rpm_upper to 51 -- so almost every row in the policy
table is the surrogate *interpolating* between real CFD data, not reading it off
directly. This script takes real (non-literal-grid) policy-table rows, actually
meshes and solves them in OpenFOAM via cfd_scripts/run_sweep.py's existing
case-generation/run infrastructure (imported directly, not reimplemented), and
compares the real thrust_total_N/power_total_W against what the surrogate predicted
at that exact point -- the one thing that's never been checked.

Spot-check cases are written to their own directory/CSV (8_policy_spot_check/),
never touching the real production 2_co_rot_sweep/co_rot_results.csv or its case
directories.

ROUND_1 (run 2026-08-12, sequential): one point each in the policy's two dominant
tiers. (0.2m, 90deg) matched well (-3.9% thrust); (0.35m, 90deg) missed badly
(-26.6% thrust) -- surprising enough, and in the tier the policy leans on hardest
(25/51 rows), to warrant follow-up rather than either accepting or dismissing it
from n=1.

ROUND_2 (this batch): four more points designed to distinguish *why* ROUND_1's
(0.35m, 90deg) point missed -- isolated bad luck, a tier-wide problem, or a sharp
local feature right at the azimuth=90deg symmetry point (a 2-blade rotor is
180deg-periodic, so +90/-90 are geometrically special -- see
ml_scripts/eda_azimuth_sensitivity.py -- and Hong et al.'s cited near-field-vs-BVI
competing-mechanism crossover could plausibly sit right there):
  - two more (0.35m, 90deg) points at different rpm_upper (low/high end of that
    tier's range) -- tier-wide vs. isolated.
  - one point at the *same* (rpm_lower, rpm_upper) as ROUND_1's miss but azimuth
    shifted to the adjacent literal grid value (67.5deg instead of 90deg) --
    isolates whether the error is specific to exactly 90deg.
  - one more (0.2m, 90deg) point at a different rpm_upper than ROUND_1's match --
    confirms that tier's good result wasn't itself a fluke (also n=1 so far).

Usage (WSL, real OpenFOAM environment required):
  python3 -m ml_scripts.spot_check_policy --round 2 --parallel 4
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# cfd_scripts/ has no __init__.py, so add it to sys.path directly rather than loading
# run_sweep.py via importlib.util.spec_from_file_location -- a dynamically-loaded module
# isn't registered under an importable name, so ProcessPoolExecutor can't pickle
# references to its functions (`import run_sweep` failing in the worker) when
# --parallel > 1 submits run_case across the process boundary.
_CFD_SCRIPTS = REPO_ROOT / "cfd_scripts"
if str(_CFD_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CFD_SCRIPTS))
import run_sweep  # noqa: E402

from ml_scripts.dataset import load_co_rot, train_val_split, add_engineered_features
from ml_scripts.surrogate import train_surrogate

CSV = "/home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results.csv"
SPOT_CHECK_DIR = Path("/home/david/OpenFOAM/ENGR412/8_policy_spot_check")
RESULTS_CSV = SPOT_CHECK_DIR / "spot_check_results.csv"

# Picked from the corrected policy_table.csv's two dominant tiers -- (0.2m, 90deg) for
# the lower rpm_upper band, (0.35m, 90deg) for the upper band -- at mid-tier rows so
# neither rpm_lower nor rpm_upper coincides with a literal 5-point CFD-tested grid
# value (524.1/655.1/786.1/917.1/1048.1) and neither is the table's edge row.
CANDIDATES_ROUND_1 = [
    {"spacing_m": 0.20, "azimuth_deg": 90.0, "rpm_lower": 717.98, "rpm_upper": 597.46},
    {"spacing_m": 0.35, "azimuth_deg": 90.0, "rpm_lower": 848.98, "rpm_upper": 848.98},
]

CANDIDATES_ROUND_2 = [
    # low/high end of the (0.35m, 90deg) tier, bracketing round 1's miss at ru=849
    {"spacing_m": 0.35, "azimuth_deg": 90.0, "rpm_lower": 817.54, "rpm_upper": 817.54},
    {"spacing_m": 0.35, "azimuth_deg": 90.0, "rpm_lower": 985.22, "rpm_upper": 1006.18},
    # same (rpm_lower, rpm_upper) as round 1's (0.35m, 90deg) point, adjacent literal
    # azimuth instead of 90deg -- isolates whether the miss is specific to 90deg
    {"spacing_m": 0.35, "azimuth_deg": 67.5, "rpm_lower": 848.98, "rpm_upper": 848.98},
    # a second point in (0.2m, 90deg), different rpm_upper than round 1's match
    {"spacing_m": 0.20, "azimuth_deg": 90.0, "rpm_lower": 676.06, "rpm_upper": 555.54},
]

CANDIDATES_ROUND_3 = [
    # Retraining the surrogate against the extended 2275-row/7-tier dataset (spacing
    # extension, 2026-08-13) produced a policy table where the brand-new (0.27m,
    # -32.5deg) tier -- one of the two new spacing values just added, only 650 rows
    # of data -- suddenly wins 49/51 rpm_upper points, completely displacing every
    # tier that was competitive before ((0.2m,90deg)/(0.35m,90deg)/(0.6m,*) all
    # vanished from the table entirely). Given the confirmed azimuth=90deg
    # overprediction bug from round 1/2, a brand-new, sparsely-anchored tier suddenly
    # dominating this hard is exactly the kind of result that needs checking before
    # being trusted, not reported as-is. Low/mid/high points across the tier's
    # rpm_upper range, all non-literal-grid.
    {"spacing_m": 0.27, "azimuth_deg": -32.5, "rpm_lower": 571.26, "rpm_upper": 555.54},
    {"spacing_m": 0.27, "azimuth_deg": -32.5, "rpm_lower": 896.14, "rpm_upper": 890.90},
    {"spacing_m": 0.27, "azimuth_deg": -32.5, "rpm_lower": 1016.66, "rpm_upper": 1037.62},
]

ROUNDS = {1: CANDIDATES_ROUND_1, 2: CANDIDATES_ROUND_2, 3: CANDIDATES_ROUND_3}

# 1500 = the current default (ml_scripts/train.py / run_sweep.py --end_time), not the
# 500 some of the older production-sweep rows were run at -- so this spot check's own
# CFD cases are at least as well-converged as anything currently trusted, and any
# discrepancy against the surrogate isn't confounded by under-iterating this run.
END_TIME = 1500.0


def _case_id(i: int, cand: dict) -> str:
    return (
        f"spotcheck_{i}_s{cand['spacing_m']:.2f}"
        f"_a{cand['azimuth_deg']:+.1f}_ru{cand['rpm_upper']:.1f}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="End-to-end CFD spot check for the policy table")
    ap.add_argument("--round", type=int, default=2, choices=sorted(ROUNDS),
                     help="Which candidate batch to run (default 2)")
    ap.add_argument("--parallel", type=int, default=1,
                     help="Parallel CFD cases at once (each case is single-threaded "
                          "simpleFoam, no decomposePar -- safe to set this as high as "
                          "the candidate count on a machine with enough cores)")
    args = ap.parse_args()

    candidates = ROUNDS[args.round]
    SPOT_CHECK_DIR.mkdir(parents=True, exist_ok=True)

    print("Training surrogate (same deterministic seed=0 as ml_scripts.train) ...")
    df = load_co_rot(CSV)
    df_train, df_val = train_val_split(df)
    surrogate = train_surrogate(df_train)
    obj_cols = surrogate.target_cols
    has_is_converged = "is_converged" in surrogate.feature_cols

    def predict(cand: dict) -> tuple[float, float]:
        pred_df = pd.DataFrame({
            "spacing_m":   [cand["spacing_m"]],
            "azimuth_deg": [cand["azimuth_deg"]],
            "rpm_lower":   [cand["rpm_lower"]],
            "rpm_upper":   [cand["rpm_upper"]],
        })
        if has_is_converged:
            pred_df["is_converged"] = 1.0
        pred_df = add_engineered_features(pred_df)
        preds = surrogate.predict(pred_df)[0]
        return (float(preds[obj_cols.index("thrust_total_N")]),
                float(preds[obj_cols.index("power_total_W")]))

    jobs = []
    for i, cand in enumerate(candidates, 1):
        case_id = _case_id(i, cand)
        case_dir = str(SPOT_CHECK_DIR / case_id)
        params = dict(cand)
        params["end_time"] = END_TIME
        jobs.append((i, len(candidates), case_id, case_dir, params, "co_rot", run_sweep.TEMPLATE_DUAL))

    rows_out = []
    print(f"\nRunning {len(jobs)} candidates, --parallel {args.parallel} ...")
    if args.parallel <= 1:
        results = [(job[2], run_sweep.run_case(job)) for job in jobs]
    else:
        results = []
        with ProcessPoolExecutor(max_workers=args.parallel) as pool:
            futures = {pool.submit(run_sweep.run_case, job): job[2] for job in jobs}
            for fut in as_completed(futures):
                results.append((futures[fut], fut.result()))

    by_case_id = {job[2]: cand for job, cand in zip(jobs, candidates)}
    for case_id, result_row in results:
        cand = by_case_id[case_id]
        if result_row is None:
            print(f"  CFD run FAILED for {case_id}")
            continue

        pred_thrust, pred_power = predict(cand)
        real_thrust = result_row["thrust_total_N"]
        real_power = result_row["power_total_W"]
        thrust_err_pct = (real_thrust - pred_thrust) / pred_thrust * 100 if pred_thrust else float("nan")
        power_err_pct = (real_power - pred_power) / pred_power * 100 if pred_power else float("nan")

        print(f"\n{case_id}")
        print(f"  Real CFD : thrust={real_thrust:.3f} N   power={real_power:.1f} W   "
              f"converged={result_row.get('converged')}  quality={result_row.get('data_quality')}")
        print(f"  Surrogate: thrust={pred_thrust:.3f} N   power={pred_power:.1f} W")
        print(f"  Error    : thrust={thrust_err_pct:+.1f}%   power={power_err_pct:+.1f}%")

        rows_out.append({
            **cand,
            "real_thrust_total_N": real_thrust, "pred_thrust_total_N": pred_thrust,
            "thrust_err_pct": thrust_err_pct,
            "real_power_total_W": real_power, "pred_power_total_W": pred_power,
            "power_err_pct": power_err_pct,
            "converged": result_row.get("converged"), "data_quality": result_row.get("data_quality"),
            "case_id": case_id, "round": args.round,
        })

    new_df = pd.DataFrame(rows_out)
    if RESULTS_CSV.exists():
        old_df = pd.read_csv(RESULTS_CSV)
        combined = pd.concat([old_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset="case_id", keep="last")
    else:
        combined = new_df
    combined.to_csv(RESULTS_CSV, index=False)
    print(f"\nWrote {RESULTS_CSV} ({len(combined)} rows total)")
    if len(new_df):
        print(f"This run  -- mean |thrust error| = {new_df['thrust_err_pct'].abs().mean():.1f}%   "
              f"mean |power error| = {new_df['power_err_pct'].abs().mean():.1f}%")
    if len(combined):
        print(f"All rounds -- mean |thrust error| = {combined['thrust_err_pct'].abs().mean():.1f}%   "
              f"mean |power error| = {combined['power_err_pct'].abs().mean():.1f}%")


if __name__ == "__main__":
    main()
