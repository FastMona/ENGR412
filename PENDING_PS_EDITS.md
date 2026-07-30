# Pending PS edits (not yet merged into any PROJECT_STATE.md)

Baseline this is meant to layer onto: PROJECT_STATE_11.md (most current version seen in
this thread as of 2026-07-29). Do not merge until confirmed that no newer PS version has
superseded PROJECT_STATE_11.md in the meantime -- same lesson as the v6/v7 baseline
mixup earlier this thread: verify baseline before merging.

## New section content (candidate: next open §2.x number after PS11's highest, currently §2.35)

**§2.36 (candidate) -- CLEAN_v3.csv wired into the training pipeline: 225 flagged rows
dropped, physics-informed features added to the surrogate**

Per explicit user instruction ("discard those 225 results"), `ml/dataset.py::load_co_rot()`
now drops all rows where `mesh_diagnostic_flag == "UNDER_RESOLVED_TIGHT_SPACING"` by
default (new `drop_unreliable_mesh: bool = True` param; no-op on CSVs without that
column, e.g. FINAL.csv/CLEAN.csv). Also now computes `spacing_inv_m = 1/spacing_m` and
`azimuth_folded_deg = azimuth_deg % 180` unconditionally inside `load_co_rot()` (not
trusted from the CSV even when present -- one source of truth), both added to
`FEATURE_COLS_FULL`.

`ml/policy_extract.py::build_policy_table()`'s hypothetical candidate grids (`grid_df`,
`baseline_df`) are constructed directly as DataFrames, never routed through
`load_co_rot()` -- these now also get `add_engineered_features()` applied before
`surrogate.predict()`, otherwise the new `FEATURE_COLS_FULL` columns would KeyError.

Re-ran the full stage A/B/C pipeline against `co_rot_results_CLEAN_v3.csv`
(`python3 -m ml.train --csv co_rot_results_CLEAN_v3.csv --outdir ml/artifacts_clean_v3`):

- Confirmed "dropping 225 rows... out of 1125 total" -- 900 rows remain, all 5
  rpm_upper levels intact (no accidental loss of an RPM tier).
- Surrogate held-out metrics (900 rows, spatial (spacing,azimuth)-combo holdout):
  thrust R2=0.747, power R2=0.902, fom R2=0.465.
- Same code/features re-run on the full 1125-row CLEAN.csv for a controlled
  comparison (isolates the effect of the 225-row drop from the feature-engineering
  change): thrust R2=0.798, power R2=0.919, fom R2=0.493. So dropping the 225 rows
  costs a modest, expected ~0.05 R2 across targets -- losing 20% of training data
  (the entire innermost spacing tier) has a real interpolation-accuracy cost, traded
  for training only on mesh-reliable data.
- The old worst-combo finding (spacing=0.10m/azimuth=-20 deg, from the CLEAN.csv-only
  run, task #23) is now moot -- that whole tier is excluded from training entirely.
  A new, more diffuse error pattern appears instead, worst at spacing=0.20m,
  azimuth=20-45 deg (thrust error ~29%, fom error up to ~39% on that held-out combo).
  Not concentrated in one place the way the old finding was -- looks like a genuine,
  broader accuracy cost of the smaller training set, not a new localized data problem.
- Stage-C header (`ml/artifacts_clean_v3/policy_mlp.h`) compiles clean under
  `gcc -Wall -Wextra -std=c11` (one harmless unused-variable warning, same pattern
  seen in every prior export). Round-trip validated correctly this time: reproduced
  the full pipeline in-memory (not a CSV-reread -- see the CLEAN.csv round-trip
  methodology lesson from earlier this thread) and confirmed the in-memory
  `PolicyMLP.predict()` output matches the compiled C header's output exactly at
  4 test rpm_upper values.

**New observation, not yet resolved:** the stage-B policy table for CLEAN_v3
(225-dropped) only ever selects spacing=0.20m or 0.60m across the entire rpm_upper
sweep (never 0.35m), and flips between the two three separate times rather than
trending smoothly/monotonically as rpm_upper increases. Likely a symptom of the
power-constrained argmax being noisy at R2~0.75, not a real physical effect -- flagged
as plausibly connected to the still-open thrust_total-as-objective question
(§4.9 / task #10) rather than a bug in this change. Needs a decision/investigation,
not yet made.

## Files produced this sub-task
- `ml/artifacts_clean_v3/policy_table.csv`, `ml/artifacts_clean_v3/policy_mlp.h`
  (ENGR412-mlp repo)
- Code changes: `ml/dataset.py`, `ml/policy_extract.py` (already committed to the
  working tree -- this pending-edits file is only about the PS *documentation* of
  those changes, the code itself is not pending)

## Open items this section should cross-reference once merged
- §4.9 / task #10 (thrust_total vs other stage-B objective) -- still open, and the
  flip-flopping spacing choice above is a new, concrete data point for that
  discussion, not a resolution of it.
- Whether to also densify azimuth further (PS11 §2.35, scoped/dry-run-verified,
  not executed) before treating this as the final training set.

---

## §2.37 (candidate) -- Task #19 status check + task #20 executed (thrust_total objective, subject to rerun)

`[2026-07-29]`, same session as §2.36 above. User context: CFD data improvement (500
additional cases) is running on a separate thread; that thread's output will feed
task #10's resolution once reviewed there. This section does not depend on or
anticipate that outcome.

**Task #19 (end-to-end spot check against real CFD) -- still blocked, unchanged.**
Re-confirmed this sandbox has no OpenFOAM toolchain (`which simpleFoam/blockMesh/
snappyHexMesh` empty, no `docker`, no `/opt`-level install) -- same blocker as the
original attempt. Not executable here; needs the machine that actually runs
`scripts/run_sweep.py`.

Follow-up (`[2026-07-29]`, same session): dug into *why*, not just confirmed *that*.
Root cause is a hard environment boundary, not a "haven't gotten to it" gap --
Ubuntu's own package index actually has `openfoam`/`libopenfoam` available (found via
`apt-cache search`), but this sandbox user has no sudo (`no new privileges` flag set
at the container level -- sudo explicitly refuses to run), so `apt-get install` fails
on a permission-denied dpkg lock regardless. Separately, outbound network is
allowlisted and OpenFOAM's own installer domain (`dl.openfoam.com`) returns
403/blocked-by-allowlist. And even past both of those, this is an ephemeral,
resource-light container (~4GB free disk, shared CPU, resets between sessions) not
sized for the mesh generation / parallel solves this project's sweeps need. Task #19
must run on whatever machine already runs `scripts/run_sweep.py` -- e.g. the machine
currently running the other thread's 500-case sweep -- not in this sandbox, ever.

While blocked, regenerated `ml/artifacts/spot_check_candidates.csv` -> now written to
`ml/artifacts_clean_v3/spot_check_candidates.csv`, because the old file was stale: it
was built from the FINAL.csv-era policy (rpm_upper grid 650-1200) which no longer
matches the current CLEAN_v3-minus-225 stage-C policy (rpm_upper grid 524.1-1048.1,
M_tip-derived). New file has 5 candidate `run_sweep.py` commands spanning the current
grid, generated from the in-memory-reproduced artifacts_clean_v3 pipeline (same
methodology as the §2.36 round-trip check). Ready to hand to whichever thread has CFD
access, once useful -- not urgent, since #19 doesn't block #20.

**Task #20 (headline baseline comparison) -- executed, using `thrust_total` as the
stage-B objective per explicit user go-ahead** ("can 20 be executed using thrust_total
and later rerun if that changes"). Per §2.10's definition ("baseline is the
identical-RPM configuration ... report thrust gain over that baseline across the RPM
range"), computed for 11 rpm_upper report points across [524.1, 1048.1]:

- Mean thrust gain over the identical-RPM baseline: **+13.0%** (range: +2.1% to +20.7%
  across the sweep, biggest gains at the low-RPM end).
- Output written to `ml/artifacts_clean_v3/headline_baseline_comparison.csv` (per-point
  spacing/azimuth/rpm_lower, policy vs. baseline thrust/power/fom, thrust_gain_pct,
  power_delta_pct).

**Caveat found, not smoothed over:** the power constraint (`power_total <= P_ref`) is
satisfied *exactly* at stage B's own 51 grid points by construction (that's what the
constrained argmax guarantees), but at 4 of the 11 headline report points, the
**distilled stage-C policy** (the actual embeddable 1-in/3-out MLP, evaluated through
the surrogate at its output) predicts *slightly higher* power than the identical-RPM
baseline -- up to **+8.7%** at rpm_upper=890.9. This means stage-C's regression-fit
smoothing over the 51-point stage-B table does not perfectly preserve the power
constraint the labels were built to satisfy. Not a stage-B bug; a real, currently
unaddressed distillation-fidelity gap between stage B and the deployed stage-C
controller. Options not yet decided: bigger stage-C hidden layers, a post-hoc power
clamp in the C header, or accepting the drift as within tolerance -- flagged here, not
resolved.

**Explicitly subject to rerun**: both the +13.0% headline number and the power-drift
finding depend on `thrust_total` remaining the stage-B objective. If §4.9/task #10
changes the objective, task #20 must be recomputed from scratch, not patched.
