#!/bin/bash
set -e
cd ~/PythonProjects/ENGR412
python3 - <<'PYEOF'
import re

path = "scripts/run_sweep.py"
with open(path) as f:
    src = f.read()

def do_replace(src, old, new, label):
    n = src.count(old)
    assert n == 1, f"{label}: expected 1 match, found {n}"
    return src.replace(old, new, 1)

# --- 1. Add _tail_ratio() helper right before force_converged() ---
old1 = 'def force_converged(dat_path, col=3, tail_frac=0.2, tol=0.02, min_points=5):'
new1 = '''def _tail_ratio(dat_path, col=3, tail_frac=0.2, min_points=5):
    """
    Raw tail-window std/mean|value| ratio for a force.dat time-history column -- the same
    quantity force_converged() thresholds against, exposed directly so callers can grade
    convergence quality (CONVERGED_TIGHT/CONVERGED/BORDERLINE/NOT_CONVERGED) instead of just
    getting a pass/fail bool. Returns None if the file is missing or too short to judge.
    """
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


def force_converged(dat_path, col=3, tail_frac=0.2, tol=0.02, min_points=5):'''
src = do_replace(src, old1, new1, "force_converged_detail helper")

# --- 2. extract_results_dual(): add convergence_ratio + data_quality ---
old2 = '''    def conv(name):
        p = pp / name / "0" / "force.dat"
        return force_converged(str(p))

    return {
        "thrust_upper_N":  fz("forcesUpper"),
        "thrust_lower_N":  fz("forcesLower"),
        "thrust_total_N":  fz("forcesTotal"),
        "torque_upper_Nm": mz("forcesUpper"),
        "torque_lower_Nm": mz("forcesLower"),
        "iterations":      last_iter(case_dir),
        "converged":       conv("forcesUpper") and conv("forcesLower") and conv("forcesTotal"),
    }'''
new2 = '''    def conv(name):
        p = pp / name / "0" / "force.dat"
        return force_converged(str(p))

    def ratio(name):
        p = pp / name / "0" / "force.dat"
        return _tail_ratio(str(p))

    ratios = [r for r in (ratio("forcesUpper"), ratio("forcesLower"), ratio("forcesTotal")) if r is not None]
    worst_ratio = max(ratios) if ratios else None
    if worst_ratio is None:
        data_quality = "MISSING"
    elif worst_ratio <= 0.005:
        data_quality = "CONVERGED_TIGHT"
    elif worst_ratio <= 0.02:
        data_quality = "CONVERGED"
    elif worst_ratio <= 0.05:
        data_quality = "BORDERLINE"
    else:
        data_quality = "NOT_CONVERGED"

    return {
        "thrust_upper_N":  fz("forcesUpper"),
        "thrust_lower_N":  fz("forcesLower"),
        "thrust_total_N":  fz("forcesTotal"),
        "torque_upper_Nm": mz("forcesUpper"),
        "torque_lower_Nm": mz("forcesLower"),
        "iterations":      last_iter(case_dir),
        "converged":       conv("forcesUpper") and conv("forcesLower") and conv("forcesTotal"),
        "convergence_ratio": worst_ratio,
        "data_quality":    data_quality,
    }'''
src = do_replace(src, old2, new2, "extract_results_dual graded quality")

# --- 3. CSV_HEADER_DUAL: add 4 new columns (VR12 header untouched) ---
old3 = '''CSV_HEADER_DUAL = [
    "case_id",
    "spacing_m", "azimuth_deg", "rpm_upper", "rpm_lower",
    "pitch",
    "thrust_upper_N", "thrust_lower_N", "thrust_total_N",
    "torque_upper_Nm", "torque_lower_Nm", "torque_net_Nm",
    "power_upper_W", "power_lower_W", "power_total_W",
    "fom_upper", "fom_lower", "fom_total",
    "iterations", "converged",
]'''
new3 = '''CSV_HEADER_DUAL = [
    "case_id",
    "spacing_m", "azimuth_deg", "rpm_upper", "rpm_lower",
    "pitch",
    "thrust_upper_N", "thrust_lower_N", "thrust_total_N",
    "torque_upper_Nm", "torque_lower_Nm", "torque_net_Nm",
    "power_upper_W", "power_lower_W", "power_total_W",
    "fom_upper", "fom_lower", "fom_total",
    "spacing_inv_m", "azimuth_folded_deg",
    "convergence_ratio", "data_quality",
    "iterations", "converged",
]'''
src = do_replace(src, old3, new3, "CSV_HEADER_DUAL new columns")

# --- 4. row-building in run_case(): populate the new columns (non-VR12 only) ---
old4 = '''            "fom_upper":  figure_of_merit(tu, pu, R=params.get("diameter", DIAMETER) / 2.0),
            "fom_lower":  figure_of_merit(tl, pl, R=params.get("diameter", DIAMETER) / 2.0),
            "fom_total":  figure_of_merit(tt, pu + pl, R=params.get("diameter", DIAMETER) / 2.0),
            "iterations": iters,
            "converged":  res.get("converged", False),
        })'''
new4 = '''            "fom_upper":  figure_of_merit(tu, pu, R=params.get("diameter", DIAMETER) / 2.0),
            "fom_lower":  figure_of_merit(tl, pl, R=params.get("diameter", DIAMETER) / 2.0),
            "fom_total":  figure_of_merit(tt, pu + pl, R=params.get("diameter", DIAMETER) / 2.0),
            "iterations": iters,
            "converged":  res.get("converged", False),
        })

        if dataset not in VR12_DATASETS:
            # Extra columns for the co_rot dataset only -- CSV_HEADER_DUAL_VR12 is untouched,
            # so adding these unconditionally would break DictWriter on vr12 rows.
            spacing_val = params["spacing_m"]
            azimuth_val = params["azimuth_deg"]
            row["spacing_inv_m"] = round(1.0 / spacing_val, 4) if spacing_val else None
            # theta ~ theta+180 confirmed empirically (PS 2.25); does NOT assume mirror
            # symmetry theta ~ -theta, which is unconfirmed for a co-rotating system.
            row["azimuth_folded_deg"] = round(azimuth_val % 180, 3)
            row["convergence_ratio"] = (
                round(res["convergence_ratio"], 5)
                if res.get("convergence_ratio") is not None else None
            )
            row["data_quality"] = res.get("data_quality")'''
src = do_replace(src, old4, new4, "row-building new columns")

with open(path, "w") as f:
    f.write(src)

print("All 4 patches applied successfully.")
PYEOF

echo "--- syntax check ---"
python3 -c "import ast; ast.parse(open('scripts/run_sweep.py').read())" && echo "OK: syntax valid"

echo "--- sanity grep ---"
grep -n "_tail_ratio\|data_quality\|spacing_inv_m\|azimuth_folded_deg\|convergence_ratio" scripts/run_sweep.py
