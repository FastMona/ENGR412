"""
analyze_sweep.py — ENGR412 coaxial rotor EDA
Reads sweep_results.csv, computes dimensionless performance metrics,
and generates violin plots, heatmaps, and summary statistics.

Outputs
  results/figures/violin_PLnorm.png      — 2x2 violin grid: PLnorm vs each design variable
  results/figures/thrust_decomp.png      — stacked bar: mean upper/lower thrust by spacing
  results/figures/interaction_heatmap.png — mean FOM on spacing x azimuth grid
  results/figures/correlation_matrix.png — Pearson r between inputs and outputs
  results/figures/convergence_hist.png   — solver iteration count distribution
  results/eda_summary.csv                — per-group median/IQR/p5/p95/min/max

Usage:
  python3 analyze_sweep.py [--csv PATH] [--outdir PATH]
"""

import argparse
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

# ── Physical constants ────────────────────────────────────────────────────────
RHO     = 1.225          # kg/m³, air density at sea level
D       = 1.0            # m, rotor diameter
A       = np.pi * (D / 2) ** 2   # m², rotor disk area
N_UPPER = 900.0          # RPM, upper rotor (fixed across all cases)


# ── Load and enrich ───────────────────────────────────────────────────────────
CSV_HEADER = [
    "case_id", "spacing_m", "azimuth_deg", "rpm_upper", "rpm_lower",
    "pitch_upper", "pitch_lower", "counter_rotating",
    "thrust_upper_N", "thrust_lower_N", "thrust_total_N",
    "torque_upper_Nm", "torque_lower_Nm", "torque_net_Nm",
    "power_upper_W", "power_lower_W", "power_total_W",
    "fom_upper", "fom_lower", "fom_total",
    "iterations", "converged",
]

def load_and_enrich(csv_path):
    # If the header row on disk was written with an older field count, skip it
    # and impose the current known column names.
    with open(csv_path) as fh:
        n_header_cols = len(fh.readline().strip().split(","))
    if n_header_cols != len(CSV_HEADER):
        df = pd.read_csv(csv_path, names=CSV_HEADER, skiprows=1,
                         on_bad_lines="skip")
    else:
        df = pd.read_csv(csv_path)
    # Keep only co-rotating cases (counter-rotating sweep not yet complete)
    df = df[df["counter_rotating"] == False].copy()

    # Rotational speed in rev/s
    df["n_upper"] = N_UPPER / 60.0
    df["n_lower"] = df["rpm_lower"] / 60.0

    # Per-rotor dimensionless coefficients (each rotor referenced to its own n)
    df["CT_upper"] = df["thrust_upper_N"] / (RHO * df["n_upper"] ** 2 * D ** 4)
    df["CT_lower"] = df["thrust_lower_N"] / (RHO * df["n_lower"] ** 2 * D ** 4)
    df["CP_upper"] = df["power_upper_W"]  / (RHO * df["n_upper"] ** 3 * D ** 5)
    df["CP_lower"] = df["power_lower_W"]  / (RHO * df["n_lower"] ** 3 * D ** 5)

    # System-level coefficients: total thrust/power referenced to lower-rotor n
    # (lower rotor is the swept/controlled variable)
    df["CT_total"] = df["thrust_total_N"] / (RHO * df["n_lower"] ** 2 * D ** 4)
    df["CP_total"] = df["power_total_W"]  / (RHO * df["n_lower"] ** 3 * D ** 5)

    # Normalised power loading: PLnorm = CT / CP (Jacobellis 2021 primary metric)
    df["PLnorm"]       = df["CT_total"] / df["CP_total"]
    df["PLnorm_upper"] = df["CT_upper"] / df["CP_upper"]
    df["PLnorm_lower"] = df["CT_lower"] / df["CP_lower"]

    # Interference ratio: how much lower rotor is penalised by upper-rotor downwash
    df["interference_ratio"] = df["thrust_lower_N"] / df["thrust_upper_N"]

    return df


# ── Plots ─────────────────────────────────────────────────────────────────────
def plot_violin_grid(df, fig_dir):
    """2x2 violin grid: PLnorm vs each swept design variable."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    fig.suptitle(
        "Normalised Power Loading (PLnorm = CT/CP) vs Design Variables\n"
        "Co-rotating, 525 cases",
        fontsize=13,
    )

    pairs = [
        ("spacing_m",    "Axial Spacing [m]",    axes[0, 0]),
        ("azimuth_deg",  "Azimuth Angle [deg]",   axes[0, 1]),
        ("rpm_lower",    "Lower Rotor RPM",       axes[1, 0]),
        ("pitch_lower",  "Lower Rotor Pitch [m]", axes[1, 1]),
    ]

    for col, label, ax in pairs:
        order = sorted(df[col].unique())
        sns.violinplot(
            data=df, x=col, y="PLnorm", order=order, ax=ax,
            hue=col, legend=False, inner="box", palette="muted", cut=0,
        )
        ax.set_xlabel(label)
        ax.set_ylabel("PLnorm")
        ax.set_title(f"PLnorm vs {label}")
        ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    path = os.path.join(fig_dir, "violin_PLnorm.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"Saved: {path}")


def plot_thrust_decomp(df, fig_dir):
    """Stacked bar: mean upper + lower thrust by axial spacing."""
    grp = df.groupby("spacing_m")[["thrust_upper_N", "thrust_lower_N"]].mean()

    fig, ax = plt.subplots(figsize=(7, 5))
    x = np.arange(len(grp))
    w = 0.5
    ax.bar(x, grp["thrust_upper_N"], w, label="Upper rotor", color="#4C72B0")
    ax.bar(x, grp["thrust_lower_N"], w, bottom=grp["thrust_upper_N"],
           label="Lower rotor", color="#DD8452")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{s:.2f}" for s in grp.index])
    ax.set_xlabel("Axial Spacing [m]")
    ax.set_ylabel("Mean Thrust [N]")
    ax.set_title(
        "Mean Thrust Decomposition by Axial Spacing\n"
        "(averaged over azimuth, RPM, pitch)"
    )
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    path = os.path.join(fig_dir, "thrust_decomp.png")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"Saved: {path}")


def plot_interaction_heatmap(df, fig_dir):
    """Mean figure of merit on spacing × azimuth grid."""
    pivot = (
        df.groupby(["spacing_m", "azimuth_deg"])["fom_total"]
        .mean()
        .unstack("azimuth_deg")
    )

    fig, ax = plt.subplots(figsize=(10, 5))
    sns.heatmap(
        pivot, annot=True, fmt=".3f", cmap="YlOrRd", ax=ax,
        linewidths=0.5, cbar_kws={"label": "Mean Figure of Merit"},
    )
    ax.set_xlabel("Azimuth Angle [deg]")
    ax.set_ylabel("Axial Spacing [m]")
    ax.set_title(
        "Mean Figure of Merit — Spacing × Azimuth\n"
        "(averaged over RPM and pitch)"
    )

    path = os.path.join(fig_dir, "interaction_heatmap.png")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"Saved: {path}")


def plot_correlation_matrix(df, fig_dir):
    """Pearson correlation between design inputs and performance outputs."""
    cols = [
        "spacing_m", "azimuth_deg", "rpm_lower", "pitch_lower",
        "thrust_upper_N", "thrust_lower_N", "thrust_total_N",
        "power_total_W", "PLnorm", "fom_total", "interference_ratio",
    ]
    corr = df[cols].corr()

    fig, ax = plt.subplots(figsize=(10, 8))
    sns.heatmap(
        corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0,
        ax=ax, linewidths=0.5, vmin=-1, vmax=1,
        cbar_kws={"label": "Pearson r"},
    )
    ax.set_title("Pearson Correlation Matrix — Design Inputs and Performance Metrics")
    plt.xticks(rotation=45, ha="right")
    plt.yticks(rotation=0)

    path = os.path.join(fig_dir, "correlation_matrix.png")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"Saved: {path}")


def plot_convergence_hist(df, fig_dir):
    """Histogram of simpleFoam iteration counts."""
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(df["iterations"], bins=20, color="#4C72B0", edgecolor="white")
    ax.axvline(
        df["iterations"].median(), color="red", linestyle="--",
        label=f"Median: {df['iterations'].median():.0f}",
    )
    ax.set_xlabel("Solver Iterations at Convergence")
    ax.set_ylabel("Case Count")
    ax.set_title("Convergence: Distribution of Solver Iteration Counts")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    path = os.path.join(fig_dir, "convergence_hist.png")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"Saved: {path}")


# ── Summary statistics ────────────────────────────────────────────────────────
def write_summary(df, out_dir):
    metrics = [
        "PLnorm", "fom_total",
        "thrust_total_N", "thrust_upper_N", "thrust_lower_N",
        "power_total_W", "CT_total", "CP_total", "interference_ratio",
    ]
    design_vars = ["spacing_m", "azimuth_deg", "rpm_lower", "pitch_lower"]

    rows = []
    for var in design_vars:
        for level, grp in df.groupby(var):
            for m in metrics:
                s = grp[m]
                rows.append({
                    "variable": var,
                    "level":    level,
                    "metric":   m,
                    "n":        len(s),
                    "median":   s.median(),
                    "iqr":      s.quantile(0.75) - s.quantile(0.25),
                    "p5":       s.quantile(0.05),
                    "p95":      s.quantile(0.95),
                    "min":      s.min(),
                    "max":      s.max(),
                })

    summary = pd.DataFrame(rows)
    path = os.path.join(out_dir, "eda_summary.csv")
    summary.to_csv(path, index=False)
    print(f"Saved: {path}")
    return summary


def print_headline_stats(df):
    best_fom  = df.loc[df["fom_total"].idxmax()]
    best_plnm = df.loc[df["PLnorm"].idxmax()]

    print(f"\n{'='*65}")
    print(f"Co-rotating cases: {len(df)}   converged: {df['converged'].sum()}")
    print()
    print(f"{'Metric':<24} {'Min':>8} {'Median':>8} {'Max':>8}")
    print(f"{'-'*50}")
    for col, label in [
        ("thrust_total_N",   "Thrust total [N]"),
        ("fom_total",        "FOM total"),
        ("PLnorm",           "PLnorm (CT/CP)"),
        ("interference_ratio", "Interference ratio"),
    ]:
        print(f"{label:<24} {df[col].min():>8.3f} {df[col].median():>8.3f} {df[col].max():>8.3f}")

    print(f"\nBest FOM  : {best_fom['case_id']}")
    print(f"  spacing={best_fom['spacing_m']}m  az={best_fom['azimuth_deg']}°  "
          f"rpm_l={best_fom['rpm_lower']}  pitch_l={best_fom['pitch_lower']}  "
          f"FOM={best_fom['fom_total']:.4f}")

    print(f"\nBest PLnorm: {best_plnm['case_id']}")
    print(f"  spacing={best_plnm['spacing_m']}m  az={best_plnm['azimuth_deg']}°  "
          f"rpm_l={best_plnm['rpm_lower']}  pitch_l={best_plnm['pitch_lower']}  "
          f"PLnorm={best_plnm['PLnorm']:.4f}")
    print('='*65)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="EDA for ENGR412 coaxial rotor sweep")
    ap.add_argument(
        "--csv",
        default="/home/david/OpenFOAM/ENGR412/sweep/sweep_results.csv",
        help="Path to sweep_results.csv",
    )
    ap.add_argument(
        "--outdir",
        default="/mnt/c/Users/David/Documents_local/Repository_local/PythonProjects/ENGR412/results",
        help="Root output directory (figures/ and eda_summary.csv written here)",
    )
    args = ap.parse_args()

    fig_dir = os.path.join(args.outdir, "figures")
    os.makedirs(fig_dir, exist_ok=True)

    df = load_and_enrich(args.csv)
    print_headline_stats(df)

    plot_violin_grid(df, fig_dir)
    plot_thrust_decomp(df, fig_dir)
    plot_interaction_heatmap(df, fig_dir)
    plot_correlation_matrix(df, fig_dir)
    plot_convergence_hist(df, fig_dir)
    write_summary(df, args.outdir)

    print("\nEDA complete.")


if __name__ == "__main__":
    main()
