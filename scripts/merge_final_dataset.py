"""
scripts/merge_final_dataset.py -- consolidate the co_rot production sweep into one final
training CSV, after the multi-round non-convergence triage done in chat on 2026-07-22.

Full decision tree this script encodes (each of the 1125 case_ids in the original
co_rot_results.csv lands in exactly one branch):

  case_id NOT in convergence_check.csv (831 cases)
      -> never flagged; use co_rot_results.csv row as-is.        quality=CONVERGED, detail=original

  case_id IS in convergence_check.csv (294 cases) -- classified from the ORIGINAL
  500-iteration logs:
    class == CONVERGED (2 cases, converged during ad-hoc manual pretesting)
      -> use co_rot_results_rebuilt.csv row.                     quality=CONVERGED, detail=rebuilt_1000
    class in {PLATEAU, DIVERGING} (213 cases)
      -> use co_rot_results_timeaveraged.csv row.       quality=TIME_AVERAGED, detail=<class>_original
    class == SLOW (79 cases) -- rebuilt at --new_endtime 1000, reclassified via rebuild_verify.csv:
      reclass == CONVERGED (40 cases)
        -> use co_rot_results_rebuilt.csv row.                   quality=CONVERGED, detail=rebuilt_1000
      reclass in {PLATEAU, DIVERGING} (26 cases)
        -> use co_rot_results_timeaveraged_round2.csv row. quality=TIME_AVERAGED, detail=<reclass>_after_1000
      reclass == SLOW (13 cases) -- rebuilt again at --new_endtime 2000, via rebuild2_verify.csv:
        reclass2 == CONVERGED (4 cases)
          -> use co_rot_results_rebuilt2.csv row.                quality=CONVERGED, detail=rebuilt_2000
        reclass2 in {PLATEAU, SLOW} (9 cases, stopped here -- diminishing returns:
                     round 1 recovered 51% of its SLOW cases, round 2 only 31%)
          -> use co_rot_results_timeaveraged_round3.csv row. quality=TIME_AVERAGED, detail=<reclass2>_after_2000

Expected final counts: 831 + 2 + 40 + 4 = 877 CONVERGED, 213 + 26 + 9 = 248 TIME_AVERAGED,
877 + 248 = 1125 total, matching co_rot_results.csv's row count exactly. The script asserts
this and refuses to write output if the accounting doesn't match -- silently dropping or
double-counting a case here would corrupt the MLP training set without any obvious symptom.

Usage (paths as used throughout this chat):
    python3 scripts/merge_final_dataset.py --sweep_dir /home/david/OpenFOAM/ENGR412/2_co_rot_sweep \
        --out_csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results_FINAL.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_sweep import CSV_HEADER_DUAL  # noqa: E402

# FIXME (schema drift, found 2026-07-30): CSV_HEADER_DUAL gained its own "data_quality"
# column (2026-07-29, tail-window-ratio grading in run_sweep.py) after this script was
# written -- OUT_HEADER now lists "data_quality" twice, and build_row()'s explicit
# row["data_quality"] = quality (CONVERGED/TIME_AVERAGED) silently overwrites whatever
# per-row value CSV_HEADER_DUAL's own "data_quality" column carried in (e.g.
# CONVERGED_TIGHT/BORDERLINE), rather than the two coexisting as distinct columns.
# Needs a rename (e.g. "merge_quality"/"merge_quality_detail") before the next run of
# this script against post-2026-07-29 data.
OUT_HEADER = CSV_HEADER_DUAL + ["data_quality", "data_quality_detail"]


def load_rows(path):
    if not path.exists():
        return {}
    with open(path, newline="") as f:
        return {r["case_id"]: r for r in csv.DictReader(f)}


def load_class(path):
    if not path.exists():
        return {}
    with open(path, newline="") as f:
        return {r["case_id"]: r["class"] for r in csv.DictReader(f)}


def build_row(src_row, quality, detail):
    row = {k: src_row.get(k, "") for k in CSV_HEADER_DUAL}
    row["data_quality"] = quality
    row["data_quality_detail"] = detail
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep_dir", required=True, help="Directory containing all the intermediate CSVs from this chat")
    ap.add_argument("--out_csv", required=True)
    args = ap.parse_args()
    sd = Path(args.sweep_dir)

    orig            = load_rows(sd / "co_rot_results.csv")
    conv0           = load_class(sd / "convergence_check.csv")
    rebuilt1        = load_rows(sd / "co_rot_results_rebuilt.csv")
    rebuilt1_class  = load_class(sd / "rebuild_verify.csv")
    ta_original     = load_rows(sd / "co_rot_results_timeaveraged.csv")
    rebuilt2        = load_rows(sd / "co_rot_results_rebuilt2.csv")
    rebuilt2_class  = load_class(sd / "rebuild2_verify.csv")
    ta_round2       = load_rows(sd / "co_rot_results_timeaveraged_round2.csv")
    ta_round3       = load_rows(sd / "co_rot_results_timeaveraged_round3.csv")

    if not orig:
        raise SystemExit(f"ERROR: no rows loaded from {sd / 'co_rot_results.csv'} -- check --sweep_dir")

    out_rows = []
    counts = {}
    errors = []

    def bump(key):
        counts[key] = counts.get(key, 0) + 1

    for cid, src in orig.items():
        cls0 = conv0.get(cid)

        if cls0 is None:
            out_rows.append(build_row(src, "CONVERGED", "original"))
            bump("CONVERGED:original")
            continue

        if cls0 == "CONVERGED":
            if cid not in rebuilt1:
                errors.append(f"{cid}: class0=CONVERGED but missing from co_rot_results_rebuilt.csv")
                continue
            out_rows.append(build_row(rebuilt1[cid], "CONVERGED", "rebuilt_1000"))
            bump("CONVERGED:rebuilt_1000")
            continue

        if cls0 in ("PLATEAU", "DIVERGING"):
            if cid not in ta_original:
                errors.append(f"{cid}: class0={cls0} but missing from co_rot_results_timeaveraged.csv")
                continue
            out_rows.append(build_row(ta_original[cid], "TIME_AVERAGED", f"{cls0.lower()}_original"))
            bump(f"TIME_AVERAGED:{cls0.lower()}_original")
            continue

        if cls0 == "SLOW":
            cls1 = rebuilt1_class.get(cid)
            if cls1 == "CONVERGED":
                if cid not in rebuilt1:
                    errors.append(f"{cid}: class1=CONVERGED but missing from co_rot_results_rebuilt.csv")
                    continue
                out_rows.append(build_row(rebuilt1[cid], "CONVERGED", "rebuilt_1000"))
                bump("CONVERGED:rebuilt_1000")
                continue

            if cls1 in ("PLATEAU", "DIVERGING"):
                if cid not in ta_round2:
                    errors.append(f"{cid}: class1={cls1} but missing from co_rot_results_timeaveraged_round2.csv")
                    continue
                out_rows.append(build_row(ta_round2[cid], "TIME_AVERAGED", f"{cls1.lower()}_after_1000"))
                bump(f"TIME_AVERAGED:{cls1.lower()}_after_1000")
                continue

            if cls1 == "SLOW":
                cls2 = rebuilt2_class.get(cid)
                if cls2 == "CONVERGED":
                    if cid not in rebuilt2:
                        errors.append(f"{cid}: class2=CONVERGED but missing from co_rot_results_rebuilt2.csv")
                        continue
                    out_rows.append(build_row(rebuilt2[cid], "CONVERGED", "rebuilt_2000"))
                    bump("CONVERGED:rebuilt_2000")
                    continue

                if cls2 in ("PLATEAU", "SLOW", "DIVERGING"):
                    if cid not in ta_round3:
                        errors.append(f"{cid}: class2={cls2} but missing from co_rot_results_timeaveraged_round3.csv")
                        continue
                    out_rows.append(build_row(ta_round3[cid], "TIME_AVERAGED", f"{cls2.lower()}_after_2000"))
                    bump(f"TIME_AVERAGED:{cls2.lower()}_after_2000")
                    continue

                errors.append(f"{cid}: unrecognized class2={cls2!r} in rebuild2_verify.csv")
                continue

            errors.append(f"{cid}: unrecognized class1={cls1!r} in rebuild_verify.csv")
            continue

        errors.append(f"{cid}: unrecognized class0={cls0!r} in convergence_check.csv")

    print("Counts by (quality, detail):")
    for k in sorted(counts):
        print(f"  {k:<45} {counts[k]}")
    total = sum(counts.values())
    print(f"\nTotal rows built: {total}  (orig co_rot_results.csv has {len(orig)} rows)")

    if errors:
        print(f"\n{len(errors)} ERRORS -- refusing to write output:")
        for e in errors[:30]:
            print(f"  {e}")
        if len(errors) > 30:
            print(f"  ... ({len(errors) - 30} more)")
        raise SystemExit(1)

    if total != len(orig):
        raise SystemExit(f"\nERROR: built {total} rows but co_rot_results.csv has {len(orig)} -- "
                          f"accounting mismatch, refusing to write output.")

    case_ids_seen = set(r["case_id"] for r in out_rows)
    if len(case_ids_seen) != len(out_rows):
        raise SystemExit(f"\nERROR: {len(out_rows)} rows but only {len(case_ids_seen)} unique case_ids -- "
                          f"duplicate rows, refusing to write output.")

    with open(args.out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_HEADER)
        w.writeheader()
        w.writerows(out_rows)

    print(f"\nWrote {len(out_rows)} rows to {args.out_csv}")


if __name__ == "__main__":
    main()
