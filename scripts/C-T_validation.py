"""
C-T_validation.py — Caradonna-Tung CFD Validation
Compares OpenFOAM MRF simpleFoam results against the published hover experiment.

Reference:
  Caradonna, F.X. & Tung, C. (1981). Experimental and Analytical Studies of a
  Model Helicopter Rotor in Hover. NASA Technical Memorandum 81232.

Rotor geometry (C-T paper):
  Airfoil  : NACA 0012, untwisted, untapered
  Radius   : R  = 1.143 m
  Chord    : c  = 0.1905 m
  Blades   : Nb = 2
  Solidity : σ  = Nb·c / (π·R) = 0.1063

Test condition reproduced here:
  Tip Mach : 0.439  →  Vtip = 150.6 m/s  →  ~1258 RPM
  Collective: 0° – 12° at constant RPM

Coefficient convention (matches C-T paper):
  CT = T  / (ρ A Vtip²)
  CP = P  / (ρ A Vtip³)
  where A = π R²

Compressibility note:
  simpleFoam is incompressible.  At Mtip = 0.439 the Prandtl-Glauert factor
  is 1/√(1−M²) ≈ 1.11, so CFD will overpredict CT by ~11% at the tip.
  An incompressibility-corrected band is shown on the CT plot.

Outputs (written to --outdir):
  figures/CT_vs_collective.png   — CT comparison: experiment vs CFD
  figures/CP_vs_collective.png   — CP comparison
  figures/CT_CP_polar.png        — CT/σ vs CP/σ efficiency polar
  figures/FOM_vs_collective.png  — figure of merit vs collective
  validation_summary.csv         — per-collective % error table

Usage:
  # Plot experimental data only (before CFD cases are run):
  python3 scripts/C-T_validation.py

  # Overlay CFD results once cases are complete:
  python3 scripts/C-T_validation.py \\
      --cfd /home/david/OpenFOAM/ENGR412/caradonnaTung/ct_results.csv \\
      --outdir results_CT_validation

CFD CSV format (one row per collective angle run):
  collective_deg, thrust_N, power_W, iterations, converged
"""

import argparse, csv, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

# ── Rotor geometry ─────────────────────────────────────────────────────────────
R   = 1.143                  # m, blade radius
C   = 0.1905                 # m, blade chord
NB  = 2                      # number of blades
A   = np.pi * R**2           # m², rotor disk area
SIG = NB * C / (np.pi * R)  # blade solidity  ≈ 0.1063

# ── Atmospheric conditions ─────────────────────────────────────────────────────
RHO     = 1.225   # kg/m³
SPD_SND = 343.0   # m/s  (20°C, sea level)

# ── Test condition: Mtip = 0.439 ──────────────────────────────────────────────
MTIP = 0.439
VTIP = MTIP * SPD_SND         # ≈ 150.6 m/s
RPM  = 60.0 * VTIP / (2.0 * np.pi * R)   # ≈ 1258 RPM

# Prandtl-Glauert compressibility factor (for incompressible CFD correction band)
PG = 1.0 / np.sqrt(1.0 - MTIP**2)   # ≈ 1.107

# ── Experimental data — digitised from C-T (1981) NASA TM-81232 ───────────────
# CT and CP use the Vtip-based convention above.
# Values read from Figs 8 & 9 (Mtip = 0.439 curve).
# Accuracy: ±3% of full-scale reading; update with table data if available.
EXP_THETA = np.array([0, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12], dtype=float)

EXP_CT = np.array([
    0.0000,   # 0°
    0.0016,   # 2°
    0.0034,   # 4°
    0.0044,   # 5°
    0.0054,   # 6°
    0.0064,   # 7°
    0.0074,   # 8°
    0.0083,   # 9°
    0.0092,   # 10°
    0.0101,   # 11°
    0.0110,   # 12°
])

# Power data sparser in the paper — only at selected collectives
EXP_CP_THETA = np.array([5.0, 8.0, 12.0])
EXP_CP       = np.array([0.000450, 0.000720, 0.001060])


# ── Coefficient helpers ────────────────────────────────────────────────────────
def thrust_to_CT(thrust_N):
    return thrust_N / (RHO * A * VTIP**2)

def power_to_CP(power_W):
    return power_W / (RHO * A * VTIP**3)

def fom(CT, CP):
    """Figure of merit = ideal induced power / actual power."""
    num = CT**1.5 / np.sqrt(2.0)
    return np.where(CP > 0, num / CP, np.nan)


# ── Load CFD results ──────────────────────────────────────────────────────────
def load_cfd(csv_path):
    """
    Read ct_results.csv.  Expected columns:
      collective_deg, thrust_N, power_W, iterations, converged
    Returns (theta, CT, CP) arrays sorted by collective.
    """
    rows = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                theta = float(row["collective_deg"])
                T     = float(row["thrust_N"])
                P     = float(row["power_W"])
                rows.append((theta, T, P))
            except (KeyError, ValueError):
                continue
    if not rows:
        raise ValueError(f"No valid rows found in {csv_path}")
    rows.sort()
    theta = np.array([r[0] for r in rows])
    CT    = thrust_to_CT(np.array([r[1] for r in rows]))
    CP    = power_to_CP (np.array([r[2] for r in rows]))
    return theta, CT, CP


# ── Plots ─────────────────────────────────────────────────────────────────────
STYLE = dict(marker="o", linewidth=1.5)

def plot_CT(fig_dir, cfd=None):
    fig, ax = plt.subplots(figsize=(7, 5))

    ax.plot(EXP_THETA, EXP_CT, color="#1f77b4", label="Experiment (C-T 1981)",
            **STYLE)

    # Incompressibility correction band: CFD should land ~PG× above experiment
    ax.fill_between(EXP_THETA, EXP_CT, EXP_CT * PG,
                    alpha=0.15, color="#1f77b4",
                    label=f"Expected CFD band (×{PG:.3f} PG factor)")

    if cfd is not None:
        theta_c, CT_c, _ = cfd
        ax.plot(theta_c, CT_c, color="#d62728", linestyle="--",
                label="CFD (simpleFoam, incompressible)", **STYLE)

    ax.set_xlabel("Collective pitch, θ₀ [deg]")
    ax.set_ylabel(r"$C_T = T\,/\,(\rho\,A\,V_{tip}^2)$")
    ax.set_title(f"CT vs Collective — Caradonna-Tung Rotor\n"
                 f"NACA 0012, R={R} m, Mtip={MTIP}, ~{RPM:.0f} RPM")
    ax.legend()
    ax.grid(alpha=0.3)
    ax.set_xlim(-0.5, 12.5)
    ax.set_ylim(bottom=-0.0005)

    path = os.path.join(fig_dir, "CT_vs_collective.png")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"Saved: {path}")


def plot_CP(fig_dir, cfd=None):
    fig, ax = plt.subplots(figsize=(7, 5))

    ax.plot(EXP_CP_THETA, EXP_CP, color="#1f77b4",
            label="Experiment (C-T 1981)", **STYLE)

    ax.fill_between(EXP_CP_THETA, EXP_CP, EXP_CP * PG**3,
                    alpha=0.15, color="#1f77b4",
                    label=f"Expected CFD band (×{PG**3:.3f} PG factor)")

    if cfd is not None:
        theta_c, _, CP_c = cfd
        # Interpolate to CP data points for a clean line
        ax.plot(theta_c, CP_c, color="#d62728", linestyle="--",
                label="CFD (simpleFoam, incompressible)", **STYLE)

    ax.set_xlabel("Collective pitch, θ₀ [deg]")
    ax.set_ylabel(r"$C_P = P\,/\,(\rho\,A\,V_{tip}^3)$")
    ax.set_title(f"CP vs Collective — Caradonna-Tung Rotor\n"
                 f"NACA 0012, R={R} m, Mtip={MTIP}, ~{RPM:.0f} RPM")
    ax.legend()
    ax.grid(alpha=0.3)
    ax.set_xlim(4, 12.5)

    path = os.path.join(fig_dir, "CP_vs_collective.png")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"Saved: {path}")


def plot_polar(fig_dir, cfd=None):
    """CT/σ vs CP/σ efficiency polar."""
    fig, ax = plt.subplots(figsize=(7, 5))

    ax.plot(EXP_CT / SIG, EXP_CT / SIG,
            color="white", alpha=0)   # dummy for limits

    # Ideal (actuator disk) line: CT^(3/2) = CP * sqrt(2)
    ct_range = np.linspace(0, EXP_CT.max() * 1.1 / SIG, 100)
    cp_ideal = ct_range**1.5 / np.sqrt(2)
    ax.plot(cp_ideal, ct_range, "k--", linewidth=1, alpha=0.5, label="Ideal (FOM=1)")

    ax.plot(EXP_CP / SIG, EXP_CT[np.searchsorted(EXP_THETA, EXP_CP_THETA)] / SIG,
            color="#1f77b4", label="Experiment (C-T 1981)", **STYLE)

    if cfd is not None:
        theta_c, CT_c, CP_c = cfd
        ax.plot(CP_c / SIG, CT_c / SIG, color="#d62728", linestyle="--",
                label="CFD (simpleFoam, incompressible)", **STYLE)

    ax.set_xlabel(r"$C_P\,/\,\sigma$")
    ax.set_ylabel(r"$C_T\,/\,\sigma$")
    ax.set_title("CT/σ vs CP/σ Efficiency Polar\nCaradonna-Tung Rotor")
    ax.legend()
    ax.grid(alpha=0.3)

    path = os.path.join(fig_dir, "CT_CP_polar.png")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"Saved: {path}")


def plot_fom(fig_dir, cfd=None):
    """Figure of merit vs collective pitch."""
    # Compute FOM at CP data points only (need both CT and CP)
    ct_at_cp = EXP_CT[np.searchsorted(EXP_THETA, EXP_CP_THETA)]
    exp_fom  = fom(ct_at_cp, EXP_CP)

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(EXP_CP_THETA, exp_fom, color="#1f77b4",
            label="Experiment (C-T 1981)", **STYLE)

    if cfd is not None:
        theta_c, CT_c, CP_c = cfd
        cfd_fom = fom(CT_c, CP_c)
        ax.plot(theta_c, cfd_fom, color="#d62728", linestyle="--",
                label="CFD (simpleFoam, incompressible)", **STYLE)

    ax.axhline(1.0, color="k", linestyle=":", linewidth=1, alpha=0.4,
               label="FOM = 1 (ideal)")
    ax.set_xlabel("Collective pitch, θ₀ [deg]")
    ax.set_ylabel("Figure of Merit")
    ax.set_title("Hover Figure of Merit — Caradonna-Tung Rotor")
    ax.set_ylim(0, 1.1)
    ax.legend()
    ax.grid(alpha=0.3)

    path = os.path.join(fig_dir, "FOM_vs_collective.png")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"Saved: {path}")


# ── Summary table ─────────────────────────────────────────────────────────────
def print_summary(cfd=None):
    print(f"\n{'='*70}")
    print(f"Caradonna-Tung Validation Summary")
    print(f"  NACA 0012  R={R} m  c={C} m  σ={SIG:.4f}  Mtip={MTIP}  "
          f"Vtip={VTIP:.1f} m/s  ~{RPM:.0f} RPM")
    print(f"  Prandtl-Glauert factor: {PG:.3f}  "
          f"(incompressible CFD expected to overpredict CT by ~{(PG-1)*100:.0f}%)")
    print(f"{'='*70}")

    if cfd is None:
        print("\n  No CFD results loaded.  Experimental data:\n")
        print(f"  {'θ [deg]':>8}  {'CT_exp':>10}  {'CT/σ_exp':>10}  {'FOM_exp':>9}")
        print(f"  {'-'*45}")
        cp_idx = {t: i for i, t in enumerate(EXP_CP_THETA)}
        for i, th in enumerate(EXP_THETA):
            ct  = EXP_CT[i]
            j   = cp_idx.get(th)
            fom_str = f"{fom(ct, EXP_CP[j]):.3f}" if j is not None else "  —  "
            print(f"  {th:>8.0f}  {ct:>10.5f}  {ct/SIG:>10.4f}  {fom_str:>9}")
    else:
        theta_c, CT_c, CP_c = cfd
        print(f"\n  {'θ [deg]':>8}  {'CT_exp':>9}  {'CT_cfd':>9}  "
              f"{'err %':>7}  {'FOM_exp':>9}  {'FOM_cfd':>9}")
        print(f"  {'-'*60}")

        exp_interp = np.interp(theta_c, EXP_THETA, EXP_CT)
        cp_interp_exp = np.interp(theta_c, EXP_CP_THETA, EXP_CP,
                                   left=np.nan, right=np.nan)

        rows = []
        for i, th in enumerate(theta_c):
            ct_e = exp_interp[i]
            ct_c = CT_c[i]
            err  = (ct_c - ct_e) / ct_e * 100 if ct_e > 0 else float("nan")
            fom_e = fom(ct_e, cp_interp_exp[i]) if not np.isnan(cp_interp_exp[i]) else float("nan")
            fom_c = fom(ct_c, CP_c[i])
            rows.append((th, ct_e, ct_c, err, fom_e, fom_c))
            fom_e_str = f"{fom_e:.3f}" if not np.isnan(fom_e) else "  —  "
            fom_c_str = f"{fom_c:.3f}" if not np.isnan(fom_c) else "  —  "
            print(f"  {th:>8.1f}  {ct_e:>9.5f}  {ct_c:>9.5f}  "
                  f"{err:>+7.1f}%  {fom_e_str:>9}  {fom_c_str:>9}")

        errs = [r[3] for r in rows if not np.isnan(r[3])]
        if errs:
            print(f"\n  Mean |error| in CT: {np.mean(np.abs(errs)):.1f}%   "
                  f"(expected ~{(PG-1)*100:.0f}% from compressibility alone)")

        return rows

    print(f"{'='*70}\n")
    return None


def write_summary_csv(out_dir, rows):
    path = os.path.join(out_dir, "validation_summary.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["collective_deg", "CT_exp", "CT_cfd",
                    "CT_error_pct", "FOM_exp", "FOM_cfd"])
        for r in rows:
            w.writerow([f"{v:.4f}" if not isinstance(v, float) or not np.isnan(v)
                        else "" for v in r])
    print(f"Saved: {path}")


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description="Compare OpenFOAM C-T validation cases against C-T (1981) experiment")
    ap.add_argument(
        "--cfd",
        default=None,
        help="Path to CFD results CSV "
             "(columns: collective_deg, thrust_N, power_W, iterations, converged)")
    ap.add_argument(
        "--outdir",
        default="results_CT_validation",
        help="Output directory for figures and summary CSV (default: results_CT_validation)")
    args = ap.parse_args()

    fig_dir = os.path.join(args.outdir, "figures")
    os.makedirs(fig_dir, exist_ok=True)

    cfd = None
    if args.cfd:
        print(f"Loading CFD results: {args.cfd}")
        try:
            cfd = load_cfd(args.cfd)
            print(f"  Loaded {len(cfd[0])} CFD data points at "
                  f"θ = {list(cfd[0])} deg")
        except Exception as e:
            print(f"  Warning: could not load CFD CSV — {e}")
            print("  Plotting experimental data only.")

    print(f"\nRotor:  NACA 0012  R={R} m  c={C} m  σ={SIG:.4f}")
    print(f"Cond.:  Mtip={MTIP}  Vtip={VTIP:.1f} m/s  ~{RPM:.0f} RPM")
    print(f"Output: {args.outdir}/\n")

    plot_CT(fig_dir, cfd)
    plot_CP(fig_dir, cfd)
    plot_polar(fig_dir, cfd)
    plot_fom(fig_dir, cfd)

    rows = print_summary(cfd)
    if rows:
        write_summary_csv(args.outdir, rows)

    print("\nDone.")


if __name__ == "__main__":
    main()
