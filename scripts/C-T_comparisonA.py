"""
C-T_comparisonA.py — Caradonna-Tung Appendix A validation (Jeon & Lee 2025)

Reproduces Appendix A of Aerospace 2025, 12, 940:
  - NACA 0012 rotor, R=1.143 m, c=0.1905 m, 2 blades, 1250 RPM
  - Collective pitch: 5°, 8°, 12°
  - Incompressible RANS (simpleFoam + MRF + SST k-ω)

Produces:
  1. Terminal table : CT vs. collective pitch (experimental + CFD)
  2. Figure 1       : CT vs. collective pitch (4–14°)
                      → figures/CT_vs_collective_appendixA.png
  3. Figure 2       : 5-panel −Cp vs. x/c  (θ=5°, r/R = 0.50/0.68/0.80/0.89/0.96)
                      → figures/Cp_sections_appendixA.png

Reference:
  Caradonna, F.X. & Tung, C. (1981). Experimental and Analytical Studies of a
  Model Helicopter Rotor in Hover. NASA TM-81232.

Usage:
  python3 scripts/C-T_comparisonA.py
  python3 scripts/C-T_comparisonA.py \\
      --cfd      /home/david/OpenFOAM/ENGR412/caradonnaTung_1250rpm/ct_results.csv \\
      --case_dir /home/david/OpenFOAM/ENGR412/caradonnaTung_1250rpm/theta5 \\
      --outdir   results_CT_appendixA
"""

import argparse, csv, glob, os
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Rotor geometry ─────────────────────────────────────────────────────────────
R       = 1.143     # blade radius [m]
C       = 0.1905    # chord [m]
NB      = 2
A       = np.pi * R**2
SIG     = NB * C / (np.pi * R)
ROTOR_Z = 12.0      # z-coordinate of rotor disk plane in OpenFOAM world frame [m]

# ── Atmospheric / operating conditions ────────────────────────────────────────
RHO   = 1.225
RPM   = 1250.0
OMEGA = RPM * 2.0 * np.pi / 60.0   # [rad/s] ≈ 130.9
VTIP  = OMEGA * R                   # ~149.6 m/s
MTIP  = VTIP / 343.0                # ~0.436
PG    = 1.0 / np.sqrt(1.0 - MTIP**2)   # Prandtl-Glauert correction ≈ 1.111

THETA_CP = 5.0   # collective pitch used for the Cp figure [deg]

# ── Radial stations for Cp figure ─────────────────────────────────────────────
STATIONS = [0.50, 0.68, 0.80, 0.89, 0.96]   # r/R
DR_BAND  = 0.03    # ±band in r/R when binning surface-point data per station

# ── Experimental CT — C-T (1981) NASA TM-81232, Mtip=0.439 ───────────────────
EXP_CT_MAP = {5: 0.0021, 8: 0.0046, 12: 0.0080}
EXP_THETA  = np.array(sorted(EXP_CT_MAP), dtype=float)
EXP_CT     = np.array([EXP_CT_MAP[k] for k in sorted(EXP_CT_MAP)], dtype=float)

# ── Experimental Cp — C-T (1981) NASA TM-81232, Table 10, θ=5°, Mtip≈0.433 ──
# Stored as actual Cp (suction surface: Cp < 0, pressure surface: Cp > 0).
# The figure plots −Cp so suction peaks appear as positive values upward.
# Sentinel (0, 0) entries mark unfilled slots and are skipped when plotting.
_Z = (0.0, 0.0)
EXP_CP = {
    0.50: {
        "upper": [(0.03, -0.504), (0.12, -0.483), (0.26, -0.389),
                  (0.47, -0.264), (0.69, -0.139), (0.83, -0.045),
                  _Z, _Z, _Z, _Z],
        "lower": [(0.04, -0.066), (0.20,  -0.295), (0.45,  -0.201),
                  (0.69, -0.097), (0.85,  -0.034), _Z, _Z, _Z, _Z, _Z],
    },
    0.68: {
        "upper": [(0.02, -0.485), (0.06, -0.557), (0.10, -0.563),
                  (0.15, -0.515), (0.19, -0.491), (0.23, -0.455),
                  (0.29, -0.419), (0.33, -0.389), (0.39, -0.311),
                  (0.44, -0.293)],
        "lower": [(0.07, -0.081), (0.18, -0.312), (0.28, -0.301),
                  (0.38, -0.259), (0.51, -0.200), (0.57, -0.164),
                  (0.79, -0.032), _Z, _Z, _Z],
    },
    0.80: {
        "upper": [(0.01, -0.319), (0.04, -0.686), (0.09, -0.598),
                  (0.13, -0.561), (0.17, -0.540), (0.24, -0.465),
                  (0.30, -0.398), (0.35, -0.361), (0.42, -0.315),
                  (0.56, -0.219)],
        "lower": [(0.02, -0.097), (0.11, -0.265), (0.14, -0.307),
                  (0.24, -0.298), (0.34, -0.269), (0.57, -0.165),
                  (0.74, -0.814), (0.90,  0.023), _Z, _Z],
    },
    0.89: {
        "upper": [(0.01, -0.457), (0.04, -0.627), (0.06, -0.623),
                  (0.10, -0.595), (0.13, -0.567), (0.17, -0.583),
                  (0.21, -0.492), (0.26, -0.425), (0.35, -0.319),
                  (0.52, -0.206)],
        "lower": [(0.01,  0.381), (0.04,  0.009), (0.14, -0.231),
                  (0.28, -0.234), (0.45, -0.178), (0.57, -0.118),
                  (0.69, -0.068), (0.79, -0.015), (0.90,  0.052), _Z],
    },
    0.96: {
        "upper": [(0.02, -0.718), (0.07, -0.680), (0.15, -0.527),
                  (0.19, -0.469), (0.23, -0.402), (0.29, -0.332),
                  (0.39, -0.256), (0.50, -0.208), (0.61, -0.150),
                  (0.76, -0.070)],
        "lower": [(0.07, -0.071), (0.16, -0.211), (0.24, -0.230),
                  (0.39, -0.182), (0.51, -0.144), (0.63, -0.099),
                  (0.74, -0.061), (0.85, -0.026), _Z, _Z],
    },
}


# ── Coefficient helpers ────────────────────────────────────────────────────────
def thrust_to_CT(thrust_N):
    return thrust_N / (RHO * A * VTIP**2)

def power_to_CP(power_W):
    return power_W / (RHO * A * VTIP**3)


# ── Load CFD CT/CP results from sweep CSV ─────────────────────────────────────
def load_cfd(csv_path):
    rows = []
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            try:
                theta = float(row["collective_deg"])
                T     = float(row["thrust_N"])
                P     = float(row["power_W"])
                rows.append((theta, T, P))
            except (KeyError, ValueError):
                continue
    if not rows:
        raise ValueError(f"No valid rows in {csv_path}")
    rows.sort()
    theta = np.array([r[0] for r in rows])
    CT    = thrust_to_CT(np.array([r[1] for r in rows]))
    CP    = power_to_CP(np.array([r[2] for r in rows]))
    return theta, CT, CP


# ── Load blade surface from OpenFOAM postProcessing ──────────────────────────
def load_surface_raw(case_dir: str) -> np.ndarray:
    """Read p from postProcessing/bladeSurface/{latest_time}/*.raw.
    Returns (N, 4) array: x  y  z  p_kinematic."""
    pp = os.path.join(case_dir, "postProcessing", "bladeSurface")
    if not os.path.isdir(pp):
        raise FileNotFoundError(
            f"postProcessing/bladeSurface/ not found in:\n  {case_dir}")

    time_dirs = sorted(
        (d for d in os.listdir(pp) if os.path.isdir(os.path.join(pp, d))),
        key=lambda s: float(s) if s.replace(".", "", 1).isdigit() else 0.0,
    )
    if not time_dirs:
        raise FileNotFoundError(f"No time directories under {pp}")

    latest = os.path.join(pp, time_dirs[-1])
    candidates = (glob.glob(os.path.join(latest, "blade.raw")) or
                  glob.glob(os.path.join(latest, "*blade*.raw")) or
                  glob.glob(os.path.join(latest, "*.raw")))
    if not candidates:
        raise FileNotFoundError(f"No .raw files in {latest}")

    raw_file = candidates[0]
    print(f"  Surface file : {raw_file}")

    rows = []
    with open(raw_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 4:
                try:
                    rows.append([float(v) for v in parts[:4]])
                except ValueError:
                    continue
    if not rows:
        raise ValueError(f"No numeric data in {raw_file}")
    return np.array(rows, dtype=float)


# ── Extract Cp(x/c) at one radial station ────────────────────────────────────
def extract_cp(data: np.ndarray, r_R_target: float, theta_deg: float):
    """Return (xc_upper, Cp_upper, xc_lower, Cp_lower) sorted by x/c."""
    tw = np.radians(theta_deg)

    d = data[data[:, 0] > 0.05]   # blade 1 only (world x > 0)
    if len(d) < 4:
        return np.array([]), np.array([]), np.array([]), np.array([])

    r_R     = d[:, 0] / R
    in_band = np.abs(r_R - r_R_target) <= DR_BAND
    db = d[in_band]
    if len(db) < 4:
        return np.array([]), np.array([]), np.array([]), np.array([])

    yw, zw, p = db[:, 1], db[:, 2], db[:, 3]
    z_loc = zw - ROTOR_Z

    # Inverse pitch rotation to recover chord-line position and surface side
    y_chord = yw * np.cos(tw) + z_loc * np.sin(tw)
    z_thick = -yw * np.sin(tw) + z_loc * np.cos(tw)   # +ve = suction side

    xc    = y_chord / C + 0.25
    valid = (xc >= -0.02) & (xc <= 1.02)
    xc, z_thick, p_v = xc[valid], z_thick[valid], p[valid]
    x_w_v = db[valid][:, 0]

    q_loc = 0.5 * (OMEGA * np.mean(x_w_v)) ** 2
    Cp    = p_v / q_loc

    is_upper = z_thick >= 0
    xc_u, Cp_u = xc[is_upper],  Cp[is_upper]
    xc_l, Cp_l = xc[~is_upper], Cp[~is_upper]

    xc_u, Cp_u = xc_u[np.argsort(xc_u)], Cp_u[np.argsort(xc_u)]
    xc_l, Cp_l = xc_l[np.argsort(xc_l)], Cp_l[np.argsort(xc_l)]
    return xc_u, Cp_u, xc_l, Cp_l


# ── Figure 1: CT vs collective pitch ──────────────────────────────────────────
def plot_CT(fig_dir, cfd=None):
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.plot(EXP_THETA, EXP_CT,
            color="black", marker="o", markersize=8, linewidth=0,
            label="Measurement (Caradonna et al., 1981)")

    if cfd is not None:
        theta_c, CT_c, _ = cfd
        mask = np.isin(theta_c, EXP_THETA)
        plot_theta = theta_c[mask] if mask.any() else theta_c
        plot_ct    = CT_c[mask]    if mask.any() else CT_c
        ax.plot(plot_theta, plot_ct,
                color="#1f77b4", marker="s", markersize=7, linewidth=1.5,
                label="Present CFD")

    ax.set_xlabel("Collective Pitch [deg]")
    ax.set_ylabel("Thrust Coefficient  $C_T$")
    ax.set_title(f"Caradonna-Tung Rotor  —  {RPM:.0f} RPM  (Mtip = {MTIP:.3f})\n"
                 f"NACA 0012, R = {R} m, 2 blades, incompressible RANS")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    ax.set_xlim(4, 14)
    ax.set_ylim(0, 0.009)
    ax.yaxis.set_major_formatter(plt.FormatStrFormatter("%.3f"))

    path = os.path.join(fig_dir, "CT_vs_collective_appendixA.png")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Saved : {path}")


# ── Figure 2: 5-panel −Cp vs x/c ──────────────────────────────────────────────
def plot_cp_figure(case_dir: str | None, fig_dir: str, theta_deg: float):
    data = None
    if case_dir is not None:
        try:
            data = load_surface_raw(case_dir)
            print(f"  Surface points: {len(data)}")
        except FileNotFoundError as e:
            print(f"  Warning: {e}")
            print(f"  No CFD surface data — plotting experimental data only.")

    fig, axes = plt.subplots(2, 3, figsize=(13, 8))
    panel_labels = ["(a)", "(b)", "(c)", "(d)", "(e)"]

    for i, r_R in enumerate(STATIONS):
        ax = axes.flat[i]

        if data is not None:
            xc_u, Cp_u, xc_l, Cp_l = extract_cp(data, r_R, theta_deg)
            if len(xc_u) > 0:
                ax.plot(xc_u, -Cp_u, color="#1f77b4", lw=1.5, label="CFD upper (suction)")
            if len(xc_l) > 0:
                ax.plot(xc_l, -Cp_l, color="#d62728", lw=1.5, label="CFD lower (pressure)")

        exp   = EXP_CP.get(r_R, {})
        pts_u = [(xc, cp) for xc, cp in exp.get("upper", []) if (xc, cp) != _Z]
        pts_l = [(xc, cp) for xc, cp in exp.get("lower", []) if (xc, cp) != _Z]
        if pts_u:
            xu, cu = zip(*pts_u)
            ax.scatter(xu, [-c for c in cu], c="black", s=24, zorder=5, label="Exp. upper")
        if pts_l:
            xl, cl = zip(*pts_l)
            ax.scatter(xl, [-c for c in cl], c="black", marker="^", s=24, zorder=5, label="Exp. lower")

        ax.axhline(0, color="grey", lw=0.5, ls="--")
        ax.set_xlim(0.0, 1.0)
        ax.set_xlabel("x/c")
        ax.set_ylabel("$-C_p$")
        ax.set_title(f"{panel_labels[i]}  r/R = {r_R:.2f}", fontsize=10)
        ax.grid(True, alpha=0.25)
        if i == 0:
            ax.legend(fontsize=7, loc="lower right")

    axes.flat[5].set_visible(False)
    fig.suptitle(
        f"Sectional Pressure Coefficient  —  C-T Validation (Appendix A)\n"
        f"NACA 0012, {RPM:.0f} RPM,  θ = {theta_deg:.0f}°,  "
        f"Vtip = {VTIP:.1f} m/s,  Mtip ≈ {MTIP:.3f}",
        fontsize=10,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.92])

    path = os.path.join(fig_dir, "Cp_sections_appendixA.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Saved : {path}")


# ── Terminal table ─────────────────────────────────────────────────────────────
def print_summary(cfd=None):
    print(f"\n{'='*65}")
    print(f"C-T Appendix A Validation  ({RPM:.0f} RPM, Mtip={MTIP:.3f})")
    print(f"  NACA 0012  R={R} m  c={C} m  sigma={SIG:.4f}  Vtip={VTIP:.1f} m/s")
    print(f"  PG factor: {PG:.3f}  (incompressible CFD ~{(PG-1)*100:.0f}% below experiment)")
    print(f"{'='*65}")

    if cfd is None:
        print("\n  No CFD results loaded.  Experimental data:\n")
        print(f"  {'theta':>6}  {'CT_exp':>10}  {'CT/sigma':>10}")
        print(f"  {'-'*30}")
        for i, th in enumerate(EXP_THETA):
            print(f"  {th:>6.0f}  {EXP_CT[i]:>10.5f}  {EXP_CT[i]/SIG:>10.4f}")
        print(f"{'='*65}\n")
        return None

    theta_c, CT_c, CP_c = cfd
    print(f"\n  {'theta':>6}  {'CT_exp':>9}  {'CT_cfd':>9}  {'err %':>7}")
    print(f"  {'-'*40}")

    rows = []
    for i, th in enumerate(EXP_THETA):
        idx = np.where(theta_c == th)[0]
        if len(idx) == 0:
            print(f"  {th:>6.0f}  {EXP_CT[i]:>9.5f}  {'(no CFD)':>9}  {'?':>7}")
            rows.append((th, EXP_CT[i], float("nan"), float("nan")))
            continue
        ct_c = CT_c[idx[0]]
        err  = (ct_c - EXP_CT[i]) / EXP_CT[i] * 100
        print(f"  {th:>6.0f}  {EXP_CT[i]:>9.5f}  {ct_c:>9.5f}  {err:>+7.1f}%")
        rows.append((th, EXP_CT[i], ct_c, err))

    errs = [r[3] for r in rows if not np.isnan(r[3])]
    if errs:
        print(f"\n  Mean |error| in CT: {np.mean(np.abs(errs)):.1f}%  "
              f"(expected ~{(PG-1)*100:.0f}% from compressibility alone)")
    print(f"{'='*65}\n")
    return rows


def write_summary_csv(out_dir, rows):
    path = os.path.join(out_dir, "appendixA_summary.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["collective_deg", "CT_exp", "CT_cfd", "CT_error_pct"])
        for r in rows:
            w.writerow([f"{v:.5f}" if isinstance(v, float) and not np.isnan(v)
                        else ("" if isinstance(v, float) else v) for v in r])
    print(f"  Saved : {path}")


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    _DEFAULT_CSV      = Path("/home/david/OpenFOAM/ENGR412/caradonnaTung_1250rpm/ct_results.csv")
    _DEFAULT_CASE_DIR = Path("/home/david/OpenFOAM/ENGR412/caradonnaTung_1250rpm/theta5")

    ap = argparse.ArgumentParser(
        description="Caradonna-Tung Appendix A — CT table + CT figure + Cp figure")
    ap.add_argument("--cfd", default=None,
                    help="CFD results CSV (auto-detected from default sweep path if omitted)")
    ap.add_argument("--case_dir", default=None,
                    help="OpenFOAM theta5 case dir for Cp figure (auto-detected if omitted)")
    ap.add_argument("--theta", type=float, default=THETA_CP,
                    help=f"Collective pitch for Cp figure [deg] (default {THETA_CP})")
    ap.add_argument("--outdir", default="results_CT_appendixA",
                    help="Output directory (default: results_CT_appendixA)")
    args = ap.parse_args()

    fig_dir = os.path.join(args.outdir, "figures")
    os.makedirs(fig_dir, exist_ok=True)

    print(f"\nC-T Appendix A  —  {RPM:.0f} RPM  Vtip={VTIP:.1f} m/s  Mtip={MTIP:.3f}")
    print(f"Output: {args.outdir}/\n")

    # ── CT results CSV ─────────────────────────────────────────────────────────
    cfd_path = args.cfd
    if cfd_path is None and _DEFAULT_CSV.exists():
        cfd_path = str(_DEFAULT_CSV)
        print(f"Auto-detected CFD results: {cfd_path}")

    cfd = None
    if cfd_path:
        try:
            cfd = load_cfd(cfd_path)
            print(f"  Loaded {len(cfd[0])} CFD points at theta={list(cfd[0])} deg")
        except Exception as e:
            print(f"  Warning: could not load CFD CSV — {e}")
    else:
        print(f"  No CFD CSV found at {_DEFAULT_CSV}  (run sweep 2g to generate it)")

    # ── Case dir for Cp figure ─────────────────────────────────────────────────
    case_dir = args.case_dir
    if case_dir is None and _DEFAULT_CASE_DIR.exists():
        case_dir = str(_DEFAULT_CASE_DIR)
        print(f"Auto-detected case dir: {case_dir}")
    elif case_dir is None:
        print(f"  No theta5 case at {_DEFAULT_CASE_DIR} — Cp figure will be experimental only.")

    # ── Table ──────────────────────────────────────────────────────────────────
    rows = print_summary(cfd)
    if rows:
        write_summary_csv(args.outdir, rows)

    # ── Figure 1: CT vs collective ─────────────────────────────────────────────
    print("Generating Figure 1: CT vs collective pitch...")
    plot_CT(fig_dir, cfd)

    # ── Figure 2: −Cp vs x/c ──────────────────────────────────────────────────
    print(f"Generating Figure 2: −Cp sections (θ = {args.theta}°)...")
    plot_cp_figure(case_dir, fig_dir, args.theta)

    print("\nDone.")


if __name__ == "__main__":
    main()
