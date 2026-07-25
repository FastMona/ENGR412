"""
scripts/analyze_gci_study_vr12.py -- Richardson extrapolation / Grid Convergence Index
(GCI) for the three-resolution co_rot_vr12 mesh study, adapted from the existing
scripts/analyze_gci_study.py (main branch, written for the single-rotor CT validation
mesh). The Celik et al. (2008) GCI math (gci_report()) is copied verbatim, unchanged --
only the CSV-reading logic differs, because the dual-rotor VR12 dataset has a different
schema (CSV_HEADER_DUAL_VR12 in run_sweep.py: spacing_m/azimuth_deg instead of a single
collective_deg sweep) and reports per-rotor thrust/torque/power in addition to totals.

Three levels, same fixed physical case (spacing=0.12 m, azimuth=+11.25 deg, rpm=1200/1200,
collective=12 deg -- the case that showed a 24.6% total-thrust shift between the base
mesh and the informal _meshcheck mesh, i.e. the most mesh-sensitive point found so far):

  lvl(3,4)  coarse  -- already in co_rot_vr12_results.csv, no separate run needed
  lvl(4,5)  medium  -- co_rot_vr12_gci_lvl45_results.csv
  lvl(5,6)  fine    -- co_rot_vr12_gci_lvl56_results.csv

Usage:
    python3 scripts/analyze_gci_study_vr12.py \\
        --base_csv    /home/david/OpenFOAM/ENGR412/3_co_rot_vr12_sweep/co_rot_vr12_results.csv \\
        --lvl45_csv   /home/david/OpenFOAM/ENGR412/5_co_rot_vr12_gci_sweep/lvl45/co_rot_vr12_gci_lvl45_results.csv \\
        --lvl56_csv   /home/david/OpenFOAM/ENGR412/5_co_rot_vr12_gci_sweep/lvl56/co_rot_vr12_gci_lvl56_results.csv \\
        --spacing 0.12 --azimuth 11.25
"""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

R = 2.0  # geometric refinement ratio between successive levels: (3,4)->(4,5)->(5,6)


def read_case_row(csv_path: Path, spacing: float, azimuth: float) -> dict:
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            if (abs(float(row["spacing_m"]) - spacing) < 1e-6
                    and abs(float(row["azimuth_deg"]) - azimuth) < 1e-6):
                return row
    raise ValueError(f"spacing={spacing}, azimuth={azimuth} not found in {csv_path}")


# ── Unchanged from scripts/analyze_gci_study.py (main branch) ─────────────────────────
def gci_report(label: str, f_coarse: float, f_medium: float, f_fine: float) -> dict:
    """
    f_coarse/medium/fine = quantity at level (3,4)/(4,5)/(5,6) i.e. h3 > h2 > h1,
    r constant = R between each pair. Returns apparent order p, Richardson-
    extrapolated "exact" value, and the fine-mesh GCI (%).
    """
    eps32 = f_coarse - f_medium   # f3 - f2
    eps21 = f_medium - f_fine     # f2 - f1

    if eps21 == 0:
        return {"label": label, "status": "identical f1/f2 -- can't compute order (division by zero)"}

    ratio = eps32 / eps21
    if ratio <= 0:
        return {
            "label": label, "status": "oscillatory convergence (eps32/eps21 <= 0) -- "
            "GCI formula not valid, see Celik et al. 2008 sec. on non-monotonic convergence",
            "f_coarse": f_coarse, "f_medium": f_medium, "f_fine": f_fine,
        }

    p = math.log(ratio) / math.log(R)

    if p <= 0:
        return {
            "label": label, "status":
                f"apparent order p={p:.3f} <= 0 -- NOT in the asymptotic convergence "
                "range (successive refinement made the answer move further, not "
                "less). GCI formula invalid here; this usually means something is "
                "wrong with the finer mesh itself (layer coverage, quality, or "
                "under-converged solve), not just 'needs a finer mesh yet'.",
            "f_coarse": f_coarse, "f_medium": f_medium, "f_fine": f_fine,
            "apparent_order_p": p,
        }

    f_exact = (R**p * f_fine - f_medium) / (R**p - 1.0)
    e_a21 = abs((f_fine - f_medium) / f_fine) if f_fine != 0 else float("nan")
    gci_fine21 = 1.25 * e_a21 / (R**p - 1.0) * 100.0  # percent

    return {
        "label": label, "status": "ok",
        "f_coarse": f_coarse, "f_medium": f_medium, "f_fine": f_fine,
        "apparent_order_p": p, "richardson_extrapolated": f_exact,
        "gci_fine_pct": gci_fine21,
    }
# ── end unchanged block ────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base_csv",  required=True, help="co_rot_vr12_results.csv (lvl 3,4)")
    ap.add_argument("--lvl45_csv", required=True, help="co_rot_vr12_gci_lvl45_results.csv")
    ap.add_argument("--lvl56_csv", required=True, help="co_rot_vr12_gci_lvl56_results.csv")
    ap.add_argument("--spacing", type=float, default=0.12)
    ap.add_argument("--azimuth", type=float, default=11.25)
    args = ap.parse_args()

    coarse = read_case_row(Path(args.base_csv),  args.spacing, args.azimuth)
    medium = read_case_row(Path(args.lvl45_csv), args.spacing, args.azimuth)
    fine   = read_case_row(Path(args.lvl56_csv), args.spacing, args.azimuth)

    print(f"GCI study at spacing={args.spacing} m, azimuth={args.azimuth} deg (r={R} between each level)\n")

    quantities = [
        ("thrust_upper", "thrust_upper_N"),
        ("thrust_lower", "thrust_lower_N"),
        ("thrust_total", "thrust_total_N"),
        ("torque_net",   "torque_net_Nm"),
        ("power_total",  "power_total_W"),
    ]
    for label, key in quantities:
        fc, fm, ff = float(coarse[key]), float(medium[key]), float(fine[key])
        result = gci_report(label, fc, fm, ff)
        print(f"--- {label} ---")
        print(f"  lvl(3,4) coarse = {fc:.4f}")
        print(f"  lvl(4,5) medium = {fm:.4f}")
        print(f"  lvl(5,6) fine   = {ff:.4f}")
        if result["status"] != "ok":
            print(f"  {result['status']}")
        else:
            print(f"  apparent order p        = {result['apparent_order_p']:.3f}")
            print(f"  Richardson extrapolated = {result['richardson_extrapolated']:.4f}")
            print(f"  GCI (fine mesh)         = {result['gci_fine_pct']:.2f}%")
            if result["gci_fine_pct"] > 5.0:
                print(f"  -> GCI > 5%: even the finest mesh here is not yet in the "
                      f"asymptotic range -- treat lvl(5,6) results with caution, "
                      f"consider a 4th, finer level before trusting this quantity.")
        print()


if __name__ == "__main__":
    main()
