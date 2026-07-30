#!/usr/bin/env python3
"""
Backfill items 4 (graded data_quality) and 5 (spacing_inv_m / azimuth_folded_deg) onto the
existing co_rot_results_CLEAN.csv WITHOUT rerunning any CFD -- items 4 and 5 are both
derivable from data already on disk:
  - item 5 is pure arithmetic on columns CLEAN.csv already has (spacing_m, azimuth_deg).
  - item 4 needs the raw force.dat time histories, which still exist in each case's
    postProcessing/ directory from the completed sweep.

Run from anywhere; edit SWEEP_DIR/IN_CSV below if your paths differ.
"""
import csv
import os

SWEEP_DIR = "/home/david/OpenFOAM/ENGR412/2_co_rot_sweep"
IN_CSV = os.path.join(SWEEP_DIR, "co_rot_results_CLEAN.csv")
OUT_CSV = os.path.join(SWEEP_DIR, "co_rot_results_CLEAN_v2.csv")

NEW_COLS = ["spacing_inv_m", "azimuth_folded_deg", "convergence_ratio", "data_quality"]


def tail_ratio(dat_path, col=3, tail_frac=0.2, min_points=5):
    if not os.path.exists(dat_path):
        return None
    vals = []
    with open(dat_path) as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith('#') and not s.startswith('/'):
                try:
                    vals.append(float(s.split()[col]))
                except (ValueError, IndexError):
                    pass
    if len(vals) < min_points:
        return None
    n = max(min_points, int(len(vals) * tail_frac))
    tail = vals[-n:]
    mean_abs = sum(abs(v) for v in tail) / len(tail)
    if mean_abs < 1e-6:
        return 0.0
    mean_val = sum(tail) / len(tail)
    std = (sum((v - mean_val) ** 2 for v in tail) / len(tail)) ** 0.5
    return std / mean_abs


def data_quality_from_ratio(worst_ratio):
    if worst_ratio is None:
        return "MISSING"
    if worst_ratio <= 0.005:
        return "CONVERGED_TIGHT"
    if worst_ratio <= 0.02:
        return "CONVERGED"
    if worst_ratio <= 0.05:
        return "BORDERLINE"
    return "NOT_CONVERGED"


def main():
    with open(IN_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"Read {len(rows)} rows from {IN_CSV}")

    missing_dirs = []
    quality_counts = {}

    for row in rows:
        case_id = row["case_id"]
        case_dir = os.path.join(SWEEP_DIR, case_id)

        spacing_val = float(row["spacing_m"])
        azimuth_val = float(row["azimuth_deg"])
        row["spacing_inv_m"] = round(1.0 / spacing_val, 4) if spacing_val else ""
        row["azimuth_folded_deg"] = round(azimuth_val % 180, 3)

        if not os.path.isdir(case_dir):
            missing_dirs.append(case_id)
            row["convergence_ratio"] = ""
            row["data_quality"] = "MISSING"
        else:
            pp = os.path.join(case_dir, "postProcessing")
            ratios = []
            for name in ("forcesUpper", "forcesLower", "forcesTotal"):
                p = os.path.join(pp, name, "0", "force.dat")
                r = tail_ratio(p)
                if r is not None:
                    ratios.append(r)
            worst = max(ratios) if ratios else None
            row["convergence_ratio"] = round(worst, 5) if worst is not None else ""
            row["data_quality"] = data_quality_from_ratio(worst)

        quality_counts[row["data_quality"]] = quality_counts.get(row["data_quality"], 0) + 1

    fieldnames = list(rows[0].keys())
    for c in NEW_COLS:
        if c not in fieldnames:
            fieldnames.append(c)

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUT_CSV}")
    print("data_quality breakdown:", quality_counts)
    if missing_dirs:
        print(f"WARNING: {len(missing_dirs)} case directories not found on disk "
              f"(convergence_ratio left blank, data_quality=MISSING):")
        for c in missing_dirs[:20]:
            print(f"  {c}")
        if len(missing_dirs) > 20:
            print(f"  ... and {len(missing_dirs) - 20} more")


if __name__ == "__main__":
    main()
