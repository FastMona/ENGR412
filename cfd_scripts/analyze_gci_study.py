"""
cfd_scripts/analyze_gci_study.py -- Richardson extrapolation / Grid Convergence Index
(GCI) for the three-resolution mesh study produced by cfd_scripts/run_gci_study.sh.

Implements the standard procedure from Celik, Ghia, Roache et al. (2008), "Procedure
for Estimation and Reporting of Uncertainty Due to Discretization in CFD
Applications" (ASME J. Fluids Eng. 130(7)) -- not an ad hoc "percent difference
between two meshes" comparison. Requires 3 resolution levels with a consistent
geometric refinement ratio (r=2 here, from run_gci_study.sh's blade_level choices).

Usage:
    python3 cfd_scripts/analyze_gci_study.py --root /home/david/OpenFOAM/ENGR412/gci_study --angle 8
"""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

R = 2.0  # geometric refinement ratio between successive blade_level steps (see
         # run_gci_study.sh: background cell ~0.4m/2^level -> exact factor-of-2 steps)


def read_case_row(csv_path: Path, angle: float) -> dict:
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            if abs(float(row["collective_deg"]) - angle) < 1e-6:
                return row
    raise ValueError(f"angle {angle} not found in {csv_path}")


def gci_report(label: str, f_coarse: float, f_medium: float, f_fine: float) -> dict:
    """
    f_coarse/medium/fine = quantity at level (4,5)/(5,6)/(6,7) i.e. h3 > h2 > h1,
    r constant = R between each pair. Returns apparent order p, Richardson-
    extrapolated "exact" value, and the fine-mesh GCI (%).
    """
    eps32 = f_coarse - f_medium   # f3 - f2
    eps21 = f_medium - f_fine     # f2 - f1

    if eps21 == 0:
        return {"label": label, "status": "identical f1/f2 -- can't compute order (division by zero)"}

    ratio = eps32 / eps21
    if ratio <= 0:
        # Oscillatory (non-monotonic) convergence -- Celik et al. explicitly flag this
        # as a case the standard GCI formula does not apply to; report raw values
        # instead of manufacturing a misleading "order of convergence".
        return {
            "label": label, "status": "oscillatory convergence (eps32/eps21 <= 0) -- "
            "GCI formula not valid, see Celik et al. 2008 sec. on non-monotonic convergence",
            "f_coarse": f_coarse, "f_medium": f_medium, "f_fine": f_fine,
        }

    p = math.log(ratio) / math.log(R)

    if p <= 0:
        # p<=0 means |eps32| <= |eps21| in a way that makes (R**p - 1) <= 0 -- i.e.
        # the fine-vs-medium difference is LARGER than the medium-vs-coarse
        # difference (solution moving further away under refinement, not settling).
        # Plugging this into the GCI formula produces a negative "uncertainty
        # percentage", which is meaningless -- Celik et al. require monotonic
        # convergence *and* a physically sane positive order for the formula to
        # apply at all. Report the raw order and refuse to compute a GCI number
        # rather than print something that looks like a real percentage but isn't.
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


def main():
    ap = argparse.ArgumentParser(description="GCI analysis for the 3-level mesh study")
    ap.add_argument("--root", required=True, help="Directory containing lvl_4_5/, lvl_5_6/, lvl_6_7/")
    ap.add_argument("--angle", type=float, default=8.0, help="Collective angle analyzed (default 8)")
    args = ap.parse_args()

    root = Path(args.root)
    rows = {}
    for tag in ["4_5", "5_6", "6_7"]:
        csv_path = root / f"lvl_{tag}" / "ct_results.csv"
        if not csv_path.exists():
            raise FileNotFoundError(
                f"{csv_path} not found -- run cfd_scripts/run_gci_study.sh first "
                f"(all three levels must complete before this can run)"
            )
        rows[tag] = read_case_row(csv_path, args.angle)

    coarse, medium, fine = rows["4_5"], rows["5_6"], rows["6_7"]

    print(f"GCI study at theta={args.angle} deg (r={R} between each level)\n")
    for quantity, key in [("thrust", "thrust_N"), ("torque", "torque_Nm"), ("power", "power_W")]:
        fc, fm, ff = float(coarse[key]), float(medium[key]), float(fine[key])
        result = gci_report(quantity, fc, fm, ff)
        print(f"--- {quantity} ---")
        print(f"  lvl(4,5) coarse = {fc:.4f}")
        print(f"  lvl(5,6) medium = {fm:.4f}")
        print(f"  lvl(6,7) fine   = {ff:.4f}")
        if result["status"] != "ok":
            print(f"  {result['status']}")
        else:
            print(f"  apparent order p        = {result['apparent_order_p']:.3f}")
            print(f"  Richardson extrapolated = {result['richardson_extrapolated']:.4f}")
            print(f"  GCI (fine mesh)         = {result['gci_fine_pct']:.2f}%")
            if result["gci_fine_pct"] > 5.0:
                print(f"  -> GCI > 5%: even the finest mesh here is not yet in the "
                      f"asymptotic range -- treat lvl(6,7) results with caution, "
                      f"consider a 4th, finer level before trusting this quantity.")
        print()


if __name__ == "__main__":
    main()
