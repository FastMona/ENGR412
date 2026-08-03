"""
X2TD_validation.py — Qin & Yang (2025) coaxial-rotor CFD validation

Compares run_x2td_validation.py's collective-angle sweep (NACA 2412
approximation of the X2TD mid-span SC1012R8 section) against the published
figure of merit for the real X2TD blade.

Reference:
  Qin, S.-H., & Yang, A.-M. (2025). Aerodynamic optimization of a coaxial
  rotor system using a deep learning-based multi-fidelity surrogate model.
  Engineering Applications of Computational Fluid Mechanics.
  Baseline-2 (X2TD blade, pre-optimization): FM = 0.4102 at CT = 0.005,
  tip Mach = 0.563, H/D = 0.0568.

Read run_x2td_validation.py's module docstring before trusting this
comparison. Documented deviations from Qin & Yang's exact operating point:
  - Geometry: NACA 2412 single section vs. the real 3-airfoil blend
  - Tip Mach: 0.137 here vs. 0.563 in the paper
  - Chord: 0.08m, chosen for meshability, not for any dimensional match to
    the real X2TD blade
  - Spacing: H/D=0.10 here vs. Qin & Yang's H/D=0.0568 -- ABANDONED the
    exact H/D match 2026-07-30 after the literal H/D=0.0568 case produced
    negative upper-rotor thrust (blade geometry likely exceeding its own
    MRF zone at that tight a spacing/chord combination -- see
    run_x2td_validation.py docstring deviation 2 for the full diagnosis).
    H/D=0.10 instead matches this project's own co_rot_meshcheck case, so
    the fom_total sensitivity documented there (20-99% swing under mesh
    refinement) applies here too -- a real caveat, but at least a
    characterized one instead of an unexplained failure mode.
This script reports how close the CFD lands to the literature FM, it does
not certify a wind-tunnel-grade match -- treat it as a trend/plausibility
check on the airfoil approximation, run at a spacing chosen for pipeline
reliability rather than literature fidelity.

Coefficient convention (matches C-T_validation.py and run_sweep.py's
figure_of_merit()):
  CT = T / (rho * A * Vtip^2)
  CP = P / (rho * A * Vtip^3)
  FM = CT^1.5 / (sqrt(2) * CP)
  where A = pi * R^2

Outputs (written to --outdir):
  figures/FM_vs_CT.png          — CFD points vs. Qin & Yang's target point
  figures/CT_vs_collective.png  — CT bracket, showing where CT=0.005 falls
  x2td_validation_summary.csv   — per-collective CT/CP/FM + literature comparison

Usage:
  python3 cfd_scripts/X2TD_validation.py \
      --csv /home/david/OpenFOAM/ENGR412/8_x2td_validation_sweep/x2td_validation_results.csv \
      --outdir results_X2TD_validation
"""

import argparse
import csv
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

# ── Case geometry (must match run_x2td_validation.py) ──────────────────────────
DIAMETER = 1.0
R        = DIAMETER / 2.0
A        = np.pi * R**2
RHO      = 1.225
RPM      = 900.0
OMEGA    = RPM * 2.0 * np.pi / 60.0
VTIP     = OMEGA * R                    # ~= 47.1 m/s -> Mtip ~= 0.137 (SPD_SND=343 m/s)
SPD_SND  = 343.0
MTIP     = VTIP / SPD_SND

# ── Literature target: Qin & Yang (2025), Baseline-2 (real X2TD blade) ─────────
LIT_CT   = 0.005
LIT_FM   = 0.4102
LIT_MTIP = 0.563
LIT_HD   = 0.0568   # Qin & Yang's H/D -- NOT what this run uses (see docstring); kept only for the printed comparison line


def thrust_to_CT(thrust_N):
    return thrust_N / (RHO * A * VTIP**2)


def power_to_CT_power(power_W):
    return power_W / (RHO * A * VTIP**3)


def load_cfd(csv_path):
    rows = []
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            try:
                theta = float(row["collective_deg"])
                T     = float(row["thrust_total_N"])
                P     = float(row["power_total_W"])
                fom   = float(row["fom_total"]) if row.get("fom_total") not in (None, "", "None") else np.nan
                dq    = row.get("data_quality", "")
                rows.append((theta, T, P, fom, dq))
            except (KeyError, ValueError):
                continue
    if not rows:
        raise ValueError(f"No valid rows found in {csv_path}")
    rows.sort()
    theta = np.array([r[0] for r in rows])
    T     = np.array([r[1] for r in rows])
    P     = np.array([r[2] for r in rows])
    fom   = np.array([r[3] for r in rows])
    dq    = [r[4] for r in rows]
    CT    = thrust_to_CT(T)
    CP    = power_to_CT_power(P)
    return theta, CT, CP, fom, dq


def plot_FM_vs_CT(fig_dir, CT, fom, dq):
    plt.figure(figsize=(6, 5))
    colors = ["tab:red" if d == "NOT_CONVERGED" else
              "tab:orange" if d == "BORDERLINE" else "tab:blue" for d in dq]
    plt.scatter(CT, fom, c=colors, zorder=3, label="CFD (NACA 2412 approx., this project)")
    plt.plot(CT, fom, "--", color="tab:blue", alpha=0.4, zorder=2)
    plt.scatter([LIT_CT], [LIT_FM], marker="*", s=220, color="black", zorder=4,
                label=f"Qin & Yang (2025) X2TD baseline\n(CT={LIT_CT}, FM={LIT_FM})")
    plt.xlabel("CT (total)")
    plt.ylabel("Figure of Merit")
    plt.title(f"FM vs CT — Mtip={MTIP:.3f} (this run) vs {LIT_MTIP} (Qin & Yang)")
    plt.legend(fontsize=8)
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(fig_dir / "FM_vs_CT.png", dpi=150)
    plt.close()


def plot_CT_vs_collective(fig_dir, theta, CT):
    plt.figure(figsize=(6, 5))
    plt.plot(theta, CT, "o-", color="tab:blue", label="CFD (this run)")
    plt.axhline(LIT_CT, color="black", linestyle="--", label=f"Target CT={LIT_CT}")
    plt.xlabel("Collective [deg]")
    plt.ylabel("CT (total)")
    plt.title("CT bracket vs. collective — locating CT=0.005")
    plt.legend(fontsize=8)
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(fig_dir / "CT_vs_collective.png", dpi=150)
    plt.close()


def interpolate_at_target(CT, fom):
    """Linear interpolation of FM at CT=LIT_CT if the sweep brackets it, else None."""
    order = np.argsort(CT)
    CT_s, fom_s = CT[order], fom[order]
    if LIT_CT < CT_s.min() or LIT_CT > CT_s.max():
        return None
    return float(np.interp(LIT_CT, CT_s, fom_s))


def write_summary_csv(out_dir, theta, CT, CP, fom, dq):
    path = out_dir / "x2td_validation_summary.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["collective_deg", "CT", "CP", "FM", "data_quality",
                    "lit_CT", "lit_FM", "FM_pct_of_lit"])
        for t, ct, cp, fm, d in zip(theta, CT, CP, fom, dq):
            pct = (fm / LIT_FM * 100.0) if not np.isnan(fm) else None
            w.writerow([t, round(ct, 6), round(cp, 6),
                        round(fm, 4) if not np.isnan(fm) else None, d,
                        LIT_CT, LIT_FM, round(pct, 1) if pct is not None else None])
    return path


def print_summary(theta, CT, CP, fom, dq):
    print(f"\n{'Collective':>10} {'CT':>9} {'CP':>10} {'FM':>7}  {'quality':>16}")
    for t, ct, cp, fm, d in zip(theta, CT, CP, fom, dq):
        fm_s = f"{fm:.4f}" if not np.isnan(fm) else "  n/a "
        print(f"{t:>10.1f} {ct:>9.5f} {cp:>10.6f} {fm_s:>7}  {d:>16}")

    interp_fm = interpolate_at_target(CT, fom)
    print(f"\nQin & Yang (2025) X2TD baseline-2: CT={LIT_CT}, FM={LIT_FM}  "
          f"(Mtip={LIT_MTIP}, H/D={LIT_HD})")
    print(f"This run:                          Mtip={MTIP:.3f}, H/D=0.10")
    if interp_fm is not None:
        pct = interp_fm / LIT_FM * 100.0
        print(f"Interpolated FM at CT={LIT_CT}: {interp_fm:.4f}  ({pct:.1f}% of literature FM)")
    else:
        print(f"Sweep does not bracket CT={LIT_CT} -- widen --collectives in "
              f"run_x2td_validation.py and re-run before drawing a conclusion.")
    print("\nReminder: this compares a NACA 2412 single-section approximation, at "
          "Mtip=0.137 (not 0.563), at H/D=0.10 (not Qin & Yang's 0.0568 -- abandoned "
          "after the exact-H/D case produced negative upper-rotor thrust; see "
          "run_x2td_validation.py docstring). This spacing matches co_rot_meshcheck, "
          "where fom_total is already known to move 20-99% under mesh refinement. "
          "Treat any match/mismatch as a trend signal, not a validated absolute "
          "result, until a mesh-refinement check is run on this specific case.")


def main():
    ap = argparse.ArgumentParser(description="X2TD (Qin & Yang 2025) CFD validation")
    ap.add_argument("--csv", type=str, required=True, help="run_x2td_validation.py results CSV")
    ap.add_argument("--outdir", type=str, default="results_X2TD_validation")
    args = ap.parse_args()

    out_dir = Path(args.outdir)
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    theta, CT, CP, fom, dq = load_cfd(args.csv)
    plot_FM_vs_CT(fig_dir, CT, fom, dq)
    plot_CT_vs_collective(fig_dir, theta, CT)
    summary_path = write_summary_csv(out_dir, theta, CT, CP, fom, dq)
    print_summary(theta, CT, CP, fom, dq)
    print(f"\nFigures written to {fig_dir}/")
    print(f"Summary CSV written to {summary_path}")


if __name__ == "__main__":
    main()
