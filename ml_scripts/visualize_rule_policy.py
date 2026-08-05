"""
ml_scripts/visualize_rule_policy.py -- top-down two-rotor diagram for visually verifying
ml_scripts/rule_policy.py (or, with --model mlp, the real trained ml_scripts/policy_mlp.py) without
needing OpenFOAM or any hardware. Renders one panel per sample RPM showing the upper
rotor's blades (fixed reference, 0 deg) and the lower rotor's blades rotated by the
commanded azimuth, plus a small step-function chart with the current operating point
marked -- so you can eyeball both "did the blade actually rotate to the angle I
expect" and "which regime is this RPM in" at once.

Usage:
    python3 ml_scripts/visualize_rule_policy.py                          # 5 sample RPMs, rule policy
    python3 ml_scripts/visualize_rule_policy.py --rpms 100 500 899 900 1300
    python3 ml_scripts/visualize_rule_policy.py --animate --out rule_policy.gif
"""
from __future__ import annotations

import argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrow

from ml_scripts.rule_policy import RulePolicy


def draw_rotor(ax, azimuth_deg: float, n_blades: int = 2, radius: float = 1.0,
               color: str = "tab:blue", label: str = "", label_row: int = 0):
    ax.add_patch(plt.Circle((0, 0), radius, fill=False, linestyle="--",
                             linewidth=0.8, edgecolor="0.7"))
    for k in range(n_blades):
        theta = np.radians(azimuth_deg + k * (360.0 / n_blades))
        dx, dy = radius * np.cos(theta), radius * np.sin(theta)
        ax.add_patch(FancyArrow(0, 0, dx, dy, width=0.035, length_includes_head=True,
                                 head_width=0.12, head_length=0.15, color=color))
    if label:
        y = -radius - 0.22 - 0.22 * label_row
        ax.text(0, y, label, ha="center", va="top", fontsize=8.5, color=color)


def render_panel(ax, rpm_upper: float, spacing_m: float, azimuth_deg: float, rpm_lower: float):
    draw_rotor(ax, azimuth_deg=0.0, color="tab:blue", label_row=0,
               label=f"upper {rpm_upper:.0f} RPM (ref. 0\u00b0)")
    draw_rotor(ax, azimuth_deg=azimuth_deg, color="tab:orange", label_row=1,
               label=f"lower {rpm_lower:.0f} RPM ({azimuth_deg:.0f}\u00b0)")
    ax.set_xlim(-1.6, 1.9)
    ax.set_ylim(-1.9, 1.6)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(f"rpm_upper = {rpm_upper:.0f}", fontsize=10)


def render_step_function(ax, current_rpm: float | None = None):
    rpm = np.linspace(0, 1500, 2000)
    az = np.where(rpm < 500, 45, np.where(rpm <= 900, 90, 135))
    ax.plot(rpm, az, color="black", linewidth=1.5)
    ax.axvline(500, color="0.7", linestyle=":", linewidth=1)
    ax.axvline(900, color="0.7", linestyle=":", linewidth=1)
    if current_rpm is not None:
        cur_az = 45 if current_rpm < 500 else (90 if current_rpm <= 900 else 135)
        ax.plot([current_rpm], [cur_az], "o", color="tab:red", markersize=8, zorder=5)
    ax.set_xlabel("rpm_upper")
    ax.set_ylabel("azimuth_deg")
    ax.set_yticks([45, 90, 135])
    ax.set_title("commanded rule (this run's operating point in red)", fontsize=9)


def main():
    ap = argparse.ArgumentParser(description="Visualize the placeholder (or trained) lower-rotor policy")
    ap.add_argument("--rpms", type=float, nargs="+",
                     default=[100, 400, 500, 700, 900, 1000, 1400],
                     help="Sample upper-rotor RPM values to render")
    ap.add_argument("--model", choices=["rule", "mlp"], default="rule",
                     help="'rule' = ml_scripts.rule_policy placeholder (default); "
                          "'mlp' = load a trained ml_scripts.policy_mlp model (requires --mlp_path)")
    ap.add_argument("--out", default="ml_scripts/artifacts/rule_policy_check.png",
                     help="Output image path")
    args = ap.parse_args()

    if args.model == "rule":
        policy = RulePolicy()
    else:
        raise NotImplementedError(
            "--model mlp requires loading a saved trained PolicyMLP; not wired up yet "
            "since no trained model exists -- use --model rule (the default) until then."
        )

    n = len(args.rpms)
    fig = plt.figure(figsize=(3.0 * n, 4.0))
    gs = fig.add_gridspec(2, n, height_ratios=[3, 1.3])

    for i, rpm_upper in enumerate(args.rpms):
        spacing_m, azimuth_deg, rpm_lower = policy.predict([rpm_upper])[0]
        ax = fig.add_subplot(gs[0, i])
        render_panel(ax, rpm_upper, spacing_m, azimuth_deg, rpm_lower)

    ax_step = fig.add_subplot(gs[1, :])
    render_step_function(ax_step, current_rpm=None)
    for rpm_upper in args.rpms:
        az = 45 if rpm_upper < 500 else (90 if rpm_upper <= 900 else 135)
        ax_step.plot([rpm_upper], [az], "o", color="tab:red", markersize=6, zorder=5)

    fig.suptitle("Placeholder controller check -- rule_policy.py "
                  "(rpm_lower = rpm_upper; azimuth = 45/90/135 deg step at 500/900 RPM)",
                  fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.93])

    import os
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=140)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
