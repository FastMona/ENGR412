"""
cfd_scripts/continue_run.py -- targeted continuation run for co_rot cases that hit the
500-iteration endTime cap without meeting fvSolution's residual tolerance (294 of
1125 cases, 26%, found in the post-mortem of the full production sweep on
2026-07-2x -- see chat/analysis notes).

Why this exists instead of just re-running those 294 from scratch: they're
disproportionately the SLOW cases (some took 45-50 min each on the first pass), and
blockMesh/snappyHexMesh/promoteMesh/topoSet don't need redoing -- the mesh and MRF
cellZones are already correct and untouched from the original run. This restarts
ONLY simpleFoam, from each case's existing latest time directory (startFrom
latestTime instead of startTime 0), with endTime raised to give it more room, and
skips the meshing steps entirely.

Safety design (read before running on the full 294):
  - NEVER deletes or overwrites anything from the original run. system/controlDict
    is backed up to system/controlDict.pre_continue (once) before being modified.
  - simpleFoam's new output is APPENDED (>>) to the existing simpleFoam.log, not a
    fresh file -- this matters because run_sweep.py's last_iter() (reused here
    unmodified) just scans for the LAST "Time = " line in that file, so appending
    keeps that working correctly with zero changes to the shared helper.
  - Does NOT assume OpenFOAM continues writing forces into postProcessing/<func>/0/
    on restart -- some OpenFOAM versions/configs start a new subdirectory named
    after the restart time instead. find_latest_dat() scans ALL subdirectories
    under each function object's postProcessing folder and picks whichever's
    force.dat/moment.dat has the highest recorded Time column value, rather than
    hardcoding "0" the way the original run_sweep.py extract_results_dual() does
    (safe there because those cases never restart; not safe to assume here).
  - Output goes to a SEPARATE csv (co_rot_results_continued.csv), never touching
    the original co_rot_results.csv. Merge logic (prefer the continuation row for
    any case_id present in both) is left to you at analysis time -- keeping this
    separate means a bug here can't corrupt the already-good 831 rows.
  - Test on a small sample first: --limit 3 or explicit --case_ids before
    committing to the full 294. This is UNTESTED against real OpenFOAM (no
    OpenFOAM in the environment this was written in) -- verify one result by hand
    (check postProcessing output directly, compare thrust before/after) before
    trusting a bulk run.

Usage:
    # sanity check on 3 cases first
    python3 cfd_scripts/continue_run.py --csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results.csv \\
        --sweep_dir /home/david/OpenFOAM/ENGR412/2_co_rot_sweep \\
        --out_csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results_continued.csv \\
        --new_endtime 1000 --limit 3 --parallel 3

    # full run once the sample looks right
    python3 cfd_scripts/continue_run.py --csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results.csv \\
        --sweep_dir /home/david/OpenFOAM/ENGR412/2_co_rot_sweep \\
        --out_csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results_continued.csv \\
        --new_endtime 1000 --parallel 20
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_sweep import (  # noqa: E402  -- reuse, don't reimplement
    OPENFOAM_BASHRC, of_run, rpm_to_rads, figure_of_merit,
    read_last_force, last_iter, append_row, _lock, _unlock,
)

CONTINUED_CSV_HEADER = [
    "case_id", "iterations_before", "iterations_after", "still_at_cap",
    "thrust_upper_N", "thrust_lower_N", "thrust_total_N",
    "torque_upper_Nm", "torque_lower_Nm", "torque_net_Nm",
    "power_upper_W", "power_lower_W", "power_total_W",
    "fom_upper", "fom_lower", "fom_total",
]


def find_latest_dat(pp_dir: Path, func_name: str, filename: str):
    """
    postProcessing/<func_name>/ normally has one subdirectory, '0'. A restart
    (startFrom latestTime) may or may not continue appending there -- don't assume;
    scan every subdirectory's <filename> and return whichever has the highest
    recorded Time-column value (i.e. whichever one is actually the most current).
    Returns (path, last_time) or (None, None) if nothing found.
    """
    func_dir = pp_dir / func_name
    if not func_dir.exists():
        return None, None
    best_path, best_t = None, -1.0
    for sub in func_dir.iterdir():
        f = sub / filename
        if not f.exists():
            continue
        last_line = None
        with open(f) as fh:
            for line in fh:
                s = line.strip()
                if s and not s.startswith(("#", "/")):
                    last_line = s
        if last_line is None:
            continue
        try:
            t = float(last_line.split()[0])
        except (ValueError, IndexError):
            continue
        if t > best_t:
            best_t = t
            best_path = f
    return best_path, best_t


def extract_results_continued(case_dir: str):
    pp = Path(case_dir) / "postProcessing"

    def fz(name):
        path, _ = find_latest_dat(pp, name, "force.dat")
        return read_last_force(str(path), 3) if path else None

    def mz(name):
        path, _ = find_latest_dat(pp, name, "moment.dat")
        return read_last_force(str(path), 3) if path else None

    return {
        "thrust_upper_N":  fz("forcesUpper"),
        "thrust_lower_N":  fz("forcesLower"),
        "thrust_total_N":  fz("forcesTotal"),
        "torque_upper_Nm": mz("forcesUpper"),
        "torque_lower_Nm": mz("forcesLower"),
        "iterations":      last_iter(case_dir),  # unmodified helper -- see module docstring
    }


def patch_control_dict(case_dir: Path, new_endtime: int) -> bool:
    """
    Returns True if the file was modified, False if it was already in the
    'continued' state (startFrom latestTime) and only endTime needed bumping
    further -- either way, the ORIGINAL is preserved in controlDict.pre_continue
    the first time this runs on a given case.
    """
    cd_path = case_dir / "system" / "controlDict"
    backup_path = case_dir / "system" / "controlDict.pre_continue"
    text = cd_path.read_text()

    if not backup_path.exists():
        backup_path.write_text(text)  # one-time, never overwritten again

    original_snippet = "startFrom startTime; startTime 0;"
    if original_snippet in text:
        new_text = text.replace(original_snippet, "startFrom latestTime;")
    elif "startFrom latestTime;" in text:
        new_text = text  # already continued once before, just bump endTime below
    else:
        raise RuntimeError(
            f"{cd_path}: controlDict doesn't match either the expected original "
            f"format or an already-continued format -- refusing to guess. Check "
            f"this case's controlDict by hand before running continue_run.py on it."
        )

    new_text, n = re.subn(r"endTime \d+;", f"endTime {new_endtime};", new_text)
    if n != 1:
        raise RuntimeError(
            f"{cd_path}: expected exactly one 'endTime N;' to replace, found {n}. "
            f"Refusing to write a possibly-corrupted controlDict -- check by hand."
        )

    cd_path.write_text(new_text)
    return True


def continue_case(args_tuple):
    (i, total, case_id, case_dir_str, new_endtime, iterations_before,
     rpm_upper, rpm_lower) = args_tuple
    case_dir = Path(case_dir_str)
    print(f"[{i}/{total}] CONTINUE {case_id} (was {iterations_before} iterations)", flush=True)

    if not (case_dir / "constant" / "polyMesh").exists():
        print(f"[{i}/{total}] SKIP {case_id}: no constant/polyMesh found -- this case "
              f"was never successfully meshed, can't continue it. Investigate separately, "
              f"don't just rerun the whole pipeline blind.", flush=True)
        return None

    try:
        patch_control_dict(case_dir, new_endtime)
    except RuntimeError as e:
        print(f"[{i}/{total}] ABORT {case_id}: {e}", flush=True)
        return None

    t0 = time.time()
    # >> not > -- append to the existing log so last_iter() (unmodified, imported
    # from run_sweep.py) still finds the true latest "Time = " line across both the
    # original run and this continuation. See module docstring.
    rc, _ = of_run("simpleFoam >> simpleFoam.log 2>&1", str(case_dir))
    elapsed = time.time() - t0

    res = extract_results_continued(str(case_dir))
    tu = res.get("thrust_upper_N") or 0.0
    tl = res.get("thrust_lower_N") or 0.0
    tt = res.get("thrust_total_N") or 0.0
    qu = res.get("torque_upper_Nm") or 0.0
    ql = res.get("torque_lower_Nm") or 0.0
    iters_after = res.get("iterations", 0)
    still_at_cap = iters_after >= new_endtime

    # Same formulas run_sweep.py's own run_case() dual branch uses, applied here so
    # the continued rows are directly comparable to the original CSV's columns.
    # figure_of_merit's default R=0.5 matches this dataset's geometry (D=1.0 m).
    omega_u = rpm_to_rads(rpm_upper)
    omega_l = rpm_to_rads(rpm_lower)
    pu = abs(qu) * omega_u
    pl = abs(ql) * omega_l

    row = {
        "case_id": case_id,
        "iterations_before": iterations_before,
        "iterations_after": iters_after,
        "still_at_cap": still_at_cap,
        "thrust_upper_N": round(tu, 4), "thrust_lower_N": round(tl, 4), "thrust_total_N": round(tt, 4),
        "torque_upper_Nm": round(qu, 4), "torque_lower_Nm": round(ql, 4), "torque_net_Nm": round(qu + ql, 4),
        "power_upper_W": round(pu, 2), "power_lower_W": round(pl, 2), "power_total_W": round(pu + pl, 2),
        "fom_upper": figure_of_merit(tu, pu), "fom_lower": figure_of_merit(tl, pl),
        "fom_total": figure_of_merit(tt, pu + pl),
    }

    status = "STILL NOT CONVERGED (hit new cap again)" if still_at_cap else f"CONVERGED at {iters_after}"
    print(f"[{i}/{total}] DONE {case_id}: {status}  T={tt:.1f}N (was in original CSV)  "
          f"t={elapsed:.0f}s", flush=True)
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True, help="Original co_rot_results.csv")
    ap.add_argument("--sweep_dir", required=True, help="2_co_rot_sweep directory (case folders live here)")
    ap.add_argument("--out_csv", required=True, help="Separate output csv -- never the same as --csv")
    ap.add_argument("--min_iterations", type=int, default=500,
                     help="Select cases with iterations >= this from --csv (default 500, the cap)")
    ap.add_argument("--new_endtime", type=int, default=1000, help="New endTime for continuation (default 1000)")
    ap.add_argument("--parallel", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None, help="Only process the first N selected cases (for testing)")
    ap.add_argument("--case_ids", nargs="+", default=None,
                     help="Explicit case_id list, overrides --min_iterations selection entirely")
    ap.add_argument("--dry_run", action="store_true")
    args = ap.parse_args()

    if os.path.abspath(args.out_csv) == os.path.abspath(args.csv):
        raise SystemExit("--out_csv must not be the same file as --csv -- refusing to risk the original dataset.")

    with open(args.csv, newline="") as f:
        rows = list(csv.DictReader(f))

    if args.case_ids:
        wanted = set(args.case_ids)
        targets = [r for r in rows if r["case_id"] in wanted]
    else:
        targets = [r for r in rows if int(r["iterations"]) >= args.min_iterations]

    if args.limit:
        targets = targets[: args.limit]

    print(f"Selected {len(targets)} cases (min_iterations>={args.min_iterations}"
          f"{', case_ids override' if args.case_ids else ''}"
          f"{f', limited to {args.limit}' if args.limit else ''})")

    completed = set()
    if os.path.exists(args.out_csv):
        with open(args.out_csv, newline="") as f:
            for row in csv.DictReader(f):
                completed.add(row["case_id"])
        print(f"Skipping {len(completed)} already in {args.out_csv}")

    queue = []
    for i, r in enumerate(targets, 1):
        if r["case_id"] in completed:
            continue
        case_dir = os.path.join(args.sweep_dir, r["case_id"])
        if not os.path.isdir(case_dir):
            print(f"WARNING: {r['case_id']} has no directory at {case_dir} -- skipping, can't continue "
                  f"a case whose folder doesn't exist.")
            continue
        queue.append((i, len(targets), r["case_id"], case_dir, args.new_endtime, int(r["iterations"]),
                      float(r["rpm_upper"]), float(r["rpm_lower"])))

    print(f"Cases to run: {len(queue)}")
    if args.dry_run:
        for item in queue[:20]:
            print(f"  {item[2]}  (was {item[5]} iterations)")
        if len(queue) > 20:
            print(f"  ... ({len(queue) - 20} more)")
        return

    os.makedirs(os.path.dirname(os.path.abspath(args.out_csv)), exist_ok=True)
    if not os.path.exists(args.out_csv):
        with open(args.out_csv, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=CONTINUED_CSV_HEADER).writeheader()

    if args.parallel == 1:
        for item in queue:
            row = continue_case(item)
            if row:
                append_row(row, args.out_csv, CONTINUED_CSV_HEADER)
    else:
        with ProcessPoolExecutor(max_workers=args.parallel) as ex:
            futures = {ex.submit(continue_case, item): item for item in queue}
            for fut in as_completed(futures):
                row = fut.result()
                if row:
                    append_row(row, args.out_csv, CONTINUED_CSV_HEADER)

    print(f"All done. Results: {args.out_csv}")


if __name__ == "__main__":
    main()
