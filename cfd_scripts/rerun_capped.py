"""
cfd_scripts/rerun_capped.py -- clean full rebuild (mesh + solve) for co_rot cases that
hit the 500-iteration endTime cap, at a raised endTime.

Supersedes continue_run.py's restart-from-latestTime approach: that hit a hard
OpenFOAM restart-incompatibility wall (FOAM FATAL IO ERROR on a boundary field size
mismatch between the case's saved '500' time directory and the mesh as re-read for
restart -- see chat notes, 2026-07-2x). Rather than patch around field-level
mismatches on a per-case basis (fragile, risks silently-wrong data across 294 cases
each with their own quirks), this deletes the case directory entirely and reruns it
through the exact same pipeline (run_sweep.py's own run_case()) that produced the
other 831 good rows in the first place -- just with a higher endTime. A fresh mesh +
fresh '0/' fields are always internally consistent by construction, so this can't
hit the same restart mismatch.

This IS a real rebuild, not a cheap continuation -- expect it to cost close to what
the original run of these specific cases cost (they're disproportionately the
slowest 26% of the whole sweep). No shortcut available here; the point of this
script is reliability, not speed.

Safety:
  - Deletes ONLY the specific case directories selected (via --min_iterations or
    explicit --case_ids), never anything else.
  - Output goes to a SEPARATE csv (co_rot_results_rebuilt.csv by default), same
    column schema as the original co_rot_results.csv (produced by the same
    run_case() code path), so it can be directly concatenated/merged later --
    but the original co_rot_results.csv is never opened for writing here.
  - Test on --limit 2-3 first.

Usage:
    # sanity check on 2 cases first
    python3 cfd_scripts/rerun_capped.py --csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results.csv \\
        --sweep_dir /home/david/OpenFOAM/ENGR412/2_co_rot_sweep \\
        --out_csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results_rebuilt.csv \\
        --new_endtime 1000 --limit 2 --parallel 2

    # full run once the sample looks right
    python3 cfd_scripts/rerun_capped.py --csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results.csv \\
        --sweep_dir /home/david/OpenFOAM/ENGR412/2_co_rot_sweep \\
        --out_csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results_rebuilt.csv \\
        --new_endtime 1000 --parallel 40
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_sweep import run_case, append_row, CSV_HEADER_DUAL, TEMPLATE_DUAL  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True, help="Original co_rot_results.csv (read-only)")
    ap.add_argument("--sweep_dir", required=True, help="2_co_rot_sweep directory (case folders live here)")
    ap.add_argument("--out_csv", required=True, help="Separate output csv -- never the same as --csv")
    ap.add_argument("--min_iterations", type=int, default=500,
                     help="Select cases with iterations >= this from --csv (default 500, the cap)")
    ap.add_argument("--new_endtime", type=int, default=1000, help="New endTime for the rebuild (default 1000)")
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
        params = {
            "spacing_m": float(r["spacing_m"]), "azimuth_deg": float(r["azimuth_deg"]),
            "rpm_lower": float(r["rpm_lower"]), "rpm_upper": float(r["rpm_upper"]),
            "end_time": args.new_endtime,
        }
        case_dir = os.path.join(args.sweep_dir, r["case_id"])
        queue.append((i, len(targets), r["case_id"], case_dir, params, "co_rot", TEMPLATE_DUAL))

    print(f"Cases to run: {len(queue)}")
    if args.dry_run:
        for item in queue[:20]:
            print(f"  {item[2]}  spacing={item[4]['spacing_m']} azimuth={item[4]['azimuth_deg']} "
                  f"rpm_upper={item[4]['rpm_upper']} rpm_lower={item[4]['rpm_lower']} "
                  f"new_endtime={item[4]['end_time']}")
        if len(queue) > 20:
            print(f"  ... ({len(queue) - 20} more)")
        return

    # Delete each target case directory BEFORE running the rebuild -- run_case()'s
    # own copytree-if-not-exists logic depends on the directory being fully gone,
    # otherwise it'll (correctly, by its own design) assume the case is already set
    # up and skip re-copying the template, leaving stale files mixed with new ones.
    for item in queue:
        case_dir = item[3]
        if os.path.isdir(case_dir):
            print(f"Deleting stale directory: {case_dir}")
            shutil.rmtree(case_dir)

    os.makedirs(os.path.dirname(os.path.abspath(args.out_csv)), exist_ok=True)
    if not os.path.exists(args.out_csv):
        with open(args.out_csv, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADER_DUAL).writeheader()

    if args.parallel == 1:
        for item in queue:
            try:
                row = run_case(item)
            except Exception as e:
                print(f"ERROR: {item[2]} raised {type(e).__name__}: {e} -- skipping, "
                      f"continuing with remaining cases.", flush=True)
                continue
            if row:
                append_row(row, args.out_csv, CSV_HEADER_DUAL)
    else:
        with ProcessPoolExecutor(max_workers=args.parallel) as ex:
            futures = {ex.submit(run_case, item): item for item in queue}
            for fut in as_completed(futures):
                item = futures[fut]
                try:
                    row = fut.result()
                except Exception as e:
                    print(f"ERROR: {item[2]} raised {type(e).__name__}: {e} -- skipping, "
                          f"remaining cases keep running.", flush=True)
                    continue
                if row:
                    append_row(row, args.out_csv, CSV_HEADER_DUAL)

    print(f"All done. Results: {args.out_csv}")


if __name__ == "__main__":
    main()
