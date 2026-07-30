# ml_scripts/ -- lower-rotor control MLP (co-rotating only)

## Status as of 2026-07-29 (start here if picking this up fresh)

This section is sourced from `PROJECT_STATE_13.md` (the live status log on the WSL
machine, `/home/david/OpenFOAM/ENGR412/PROJECT_STATE_13.md`), not from re-running any
code in this folder. See "Known gaps vs. the live project state" immediately below for
what that means in practice.

**Scope correction: one project, one paper.** There is no Phase 2 and no capstone
follow-on. Any earlier framing of hardware bring-up as a later, separate phase is void
-- it is (and has been) active, concurrent work on its own branch/worktree.

**Controller signature (settled 2026-07-26):** the MLP is a *controller*, not a thrust
predictor -- 1 input (upper rotor RPM, the flight controller's demand signal), 3
outputs (azimuthal index angle, rotor disk separation, lower rotor RPM). The forward
surrogate (`ml_scripts/surrogate.py`) still exists in the pipeline, but only as an
intermediate tool for generating this controller's training labels, not as the
deliverable itself.

**The production CFD dataset is real, multi-`rpm_upper`, and current as of
2026-07-29.** `co_rot_results.csv` (at
`/home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results.csv`) now has **1625 rows**
-- the original 1125-case grid (5 spacing x 9 azimuth x 5 rpm_lower x 5 rpm_upper) plus
500 cases added to densify the azimuth grid's sparsely-sampled +-45/+-90 flanks (4 new
azimuth values x the full 5x5x5 spacing/rpm_lower/rpm_upper grid). 1593/1625 rows
(98.0%) are `converged=True`, computed per-row by a real tail-window residual check
(not the historical hardcoded-`True` bug). The file also now carries a graded
`data_quality` column (`CONVERGED_TIGHT`/`CONVERGED`/`BORDERLINE`/`NOT_CONVERGED`/
`MISSING`), a `convergence_ratio`, physics-informed features (`spacing_inv_m`,
`azimuth_folded_deg`), and a `mesh_diagnostic_flag` (`UNDER_RESOLVED_TIGHT_SPACING` for
every `spacing=0.10 m` row -- confirmed via a dedicated mesh-refinement study that the
tight-spacing tier's absolute `fom_total` values move 20-99% under a finer mesh, so
treat that tier's absolute values with caution even though it converges cleanly on
residuals). None of these newer columns are consumed by `ml_scripts/dataset.py` yet --
see "Known gaps" below.

**Azimuth is a real, strong, non-monotonic effect -- SETTLED, do not re-open.**
This supersedes the "open question" that used to sit at the bottom of this file. The
prior "azimuth is aerodynamically negligible" finding was invalid: it came from a
Pearson correlation computed on azimuth pooled across all spacing levels, and Pearson
`r` cannot detect a non-monotonic, sign-changing effect that also gets averaged flat by
pooling a strong small-spacing response against a near-flat large-spacing one. Direct
evidence from `co_rot_results.csv` (spacing=0.05 m, rpm_upper=600, rpm_lower=1050,
azimuth as the only free variable): total thrust spans 10.73 N to 19.78 N (84% swing)
as azimuth sweeps -90 deg to +45 deg, non-monotonic, peaking at -45 deg, with the upper
rotor's own thrust crossing negative at some azimuth values. **Consequence: azimuth
stays a required controller output. Do not drop `POLICY_OUTPUT_COLS` from 3 to 2.**
`ml_scripts/eda_azimuth_sensitivity.py`'s original purpose (settle this question) is
therefore done; it remains useful as a re-runnable regression check -- if a future
sweep or mesh change makes azimuth look negligible again, that is a signal to suspect
the sweep/mesh, not a reason to revisit this conclusion.

**Objective function: `thrust_total_N` at matched power -- decided but PARTIALLY
REOPENED, do not treat as fully closed.** The controller does not optimize efficiency
or FOM for its own sake; it answers "given the power the flight controller is already
putting into the upper rotor, what configuration extracts the most total thrust from
the pair?" FOM remains a *reporting* metric for the paper, not the training objective.
A specific failure mode is under active investigation elsewhere and is **not resolved**
as of this note: maximizing `thrust_total` even under a power constraint might admit a
degenerate solution that just pins `rpm_lower` to the top of its swept range instead of
a genuine interior trade-off. Empirical checks so far (a coarse 5-point sweep, then a
dense 51-point sweep once the constraint was actually implemented) have *not*
reproduced that failure mode -- the constrained optimum tracks `rpm_lower` close to
`rpm_upper` rather than saturating -- but the question is explicitly still open, not
closed by that reassurance.

**Hardware target: STM32 Nucleo-64 L452RE-P + SimpleFOC, not Arduino.** Superseded from
an earlier Arduino Uno R3 plan -- the Uno's single I2C bus couldn't run two on-axis
encoders without a workaround; the L452RE-P has four. Encoder plan has also changed
since this file was last written: on-axis magnetic encoders (AS5600, then MLX90374)
were both evaluated and rejected for the hardware demo (the upper rotor's shaft passes
through the lower rotor's hollow output tube, so both ends of that bore need to stay
open, and neither part is characterized for reading a spinning on-axis magnet from the
side). The adopted approach senses the motor's own 14-pole drive-magnet ring directly,
off-axis, with three Honeywell SS461A latching Hall switches spaced 120 deg apart --
matches SimpleFOC's native `HallSensor` class. `export_c_header()`'s dependency-free C
forward pass is still the right shape for this target (no ONNX/TF-Lite-Micro runtime
available or needed on an MCU this small).

## Known gaps vs. the live project state (as of 2026-07-29)

The fixes described above as "decided" or "implemented" mostly happened in a
**separate, uncommitted worktree** -- `ENGR412-mlp` (branch `mlp-lower-rotor-control`)
-- not in this repo's `ml_scripts/`. This folder is a distinct, still-unfixed snapshot
of the same pipeline. Concretely, as of this pass, `ml_scripts/` still has every one of
the gaps the project log identifies against the *other* copy:

1. `ml_scripts/train.py --objective` (and `policy_extract.py`'s default) is still
   `fom_total`, not the decided `thrust_total_N`.
2. `ml_scripts/policy_extract.py::build_policy_table()` has **no power constraint** --
   it is a bare, unconstrained argmax over the grid. `power_total <= P_ref` does not
   exist anywhere in this file.
3. `ml_scripts/dataset.py::load_co_rot()` hard-drops non-converged rows rather than
   treating convergence as a feature (`is_converged`) or sample weight, per the
   project's stated plan (`sklearn`'s `MLPRegressor.fit()` doesn't support
   `sample_weight`, so the feature route is what the other copy uses).
4. `ml_scripts/dataset.py::train_val_split()` is a plain random row shuffle, not a
   held-out-(spacing, azimuth)-combination split -- it measures memorization more than
   real interpolation.
5. `ml_scripts/policy_extract.py::build_policy_table()` only searches the literal
   CFD-tested `rpm_upper`/`rpm_lower` grid points (5 each), not a dense continuous
   sweep -- `rpm_upper` is the controller's actual runtime input, so this under-samples
   exactly the axis that matters most for a deployed controller.
6. No `SPACING_FLOOR_TRAINED_M` (50 mm, the surrogate's trained range) enforcement in
   `build_policy_table()` -- nothing stops it from searching below where the surrogate
   is trustworthy. (30 mm is the true physical hub-thickness floor, but the decision
   was to keep the optimizer's search range inside the trained 50 mm floor and disclose
   30 mm only as a design-intent bound in the paper.)
7. `export_c_header()`'s `f"{v:.8g}f"` float formatting can emit invalid C
   floating-point literals for whole numbers (e.g. `700.0` -> `"700f"`, which is
   neither a valid float nor int literal in C -- needs a decimal point or exponent
   before the `f` suffix). Confirmed reproducible with this file's own `arr()`
   function; not fixed here since it's a behavior change, not a comment fix -- flagging
   per the project's own standing pattern (surface real bugs found during a scoped
   pass, don't silently fix or silently ignore them).

None of the above are fixed as part of this documentation pass -- they're genuine
behavior gaps, not just stale comments, so fixing them belongs to a deliberate
follow-up (likely: pulling the corresponding changes over from `ENGR412-mlp`), not to
a comment/README audit. Point `--csv` at the current `co_rot_results.csv` and this
pipeline will run end-to-end without erroring, but the result will not match the
project's actual current design decisions on objective, constraint, or search density.

## Literature pivot (2026-07-15): why the design space itself needed fixing

Two stacked/co-rotating rotor papers (Jacobellis et al. 2021; Hong et al. 2023) were
reviewed for the CFD-meshing side of this project and turned out to be directly
relevant here too -- both sweep essentially the same design variables as this dataset
(azimuthal/index angle, axial/stacking spacing) and both report azimuth as one of the
two dominant physical effects on stacked-rotor thrust/efficiency (17.1% total-thrust
swing over just 22.5 deg of azimuth in Jacobellis; an azimuth-optimum whose location
shifts with stacking distance in Hong). This directly contradicted the original
(now-purged) "azimuth is aerodynamically negligible" finding -- see "Azimuth is a real,
strong, non-monotonic effect" above for how that got resolved.

**Root cause: the design space itself was the problem, not the physics.**
`cfd_scripts/run_sweep.py`'s dual-rotor MRF zone sizing used to shrink proportionally
with spacing to avoid the two rotors' rotating zones overlapping, which is also why
spacing=0.10 m was dropped entirely from the original design space. Net effect: the
original 700-case sweep never actually reached the close-spacing regime (Hong et al.:
strongest effects at 0.1-0.3D; the old range started at 0.20D) where azimuth
interference is physically dominant, and the azimuth grid itself (0-90 deg only, 15 deg
steps) undersampled the region right around 0 deg where both papers show the sharpest
features. Given rigid, non-deflecting blades and a hub depth of 0.03*D (project owner's
spec), the true physical minimum spacing is one full hub depth (0.03 m) -- hubs would
collide below that, not half of it. (The 50 mm-vs-30 mm distinction re-appears in
"Known gaps" above: 30 mm is the true physical floor, but the surrogate's trained range
only reaches 50 mm.)

Revised: `spacing_m` now starts at 0.05 m (`MRF_FEASIBLE_MIN_SPACING`, the closest the
current dual-MRF-cylinder method can mesh without the zones overlapping or going
degenerately thin -- still short of the 0.03 m physical floor, which needs an
overset/AMI rewrite to actually reach), with denser sampling toward the close end;
`azimuth_deg` is symmetric (-90..+90, later densified further at the flanks -- see
Status above) and denser near 0 deg. MRF zone sizing itself now has an explicit floor
and fails fast instead of silently shrinking to something numerically meaningless. Full
writeup: `analysis/stacked_rotor_literature_pivot_2026-07-15.md` on the main ENGR412
repo.

This also closed out the CFD-meshing question that was blocking work on the other
branch: the O-grid rewrite scoped in `structured_mesh_followup_2026-07-14.md` was
dropped (the actual CT benchmark paper, Jeon & Lee 2025, doesn't use one either -- see
the pivot doc). Given this is an undergraduate assignment on open-source tooling where
some validation error is acceptable as long as the MLP control pipeline works
end-to-end, further CFD refinement effort was redirected toward sanity-checking the
co_rot sweep rather than chasing tighter CT agreement.

## The one thing that needed fixing before training on real data (done -- kept for context)

**Originally, the dataset couldn't train this controller at all.**
`cfd_scripts/run_sweep.py`'s `co_rot` dataset used to fix `rpm_upper = 900` for every
case (see the historical `RPM_UPPER` constant). The objective here is "lower rotor
command as a function of upper rotor RPM" -- with only one upper-RPM operating point in
the data, there was nothing to learn that relationship from; a model trained on it
would have just memorized a single-point offset and extrapolated blindly (silently,
since nothing in the code would flag it) to any other commanded RPM. This is resolved
now (see Status above) -- the section below is kept as the rationale for why the
`--rpm_upper` override exists.

`cfd_scripts/run_sweep.py` accepts a `--rpm_upper` override so a real multi-RPM dataset
can be built, e.g.:

```bash
python3 cfd_scripts/run_sweep.py --dataset co_rot --parallel 12 \
    --rpm_upper 700 900 1100
```

Sweeping more `rpm_upper` values is not free -- pick the smallest set of upper-RPM
points that meaningfully spans the flight envelope before committing to a full run. The
case_id/CSV format only changes when more than one `rpm_upper` value is requested, so a
single-`rpm_upper` dataset and its case_ids stay compatible with this format (see the
comments above `DESIGN_SPACE_DUAL` and `case_id_fn` in `run_sweep.py`).

`ml_scripts/dataset.py::load_co_rot()` raises by default if it's handed a
single-`rpm_upper` CSV, specifically so this gap can't be silently ignored later. Pass
`require_multi_upper=False` (or `--allow_single_upper` to `ml_scripts/train.py`) only to
smoke-test the code path on a single-RPM CSV -- the resulting policy is degenerate
(same output regardless of commanded RPM) and isn't meant to be trusted or flown.

## Pipeline

```
co_rot_results.csv
      │  ml_scripts/dataset.py::load_co_rot()  (drop non-converged, compute CT/CP/PLnorm)
      ▼
forward surrogate  (ml_scripts/surrogate.py)
  MLPRegressor: [rpm_upper, spacing_m, azimuth_deg, rpm_lower] -> [thrust_total_N, power_total_W, fom_total]
      │  ml_scripts/policy_extract.py::build_policy_table()  (grid-search the surrogate per rpm_upper, keep the argmax)
      ▼
policy table  (one row per rpm_upper grid point: the best spacing/azimuth/rpm_lower found)
      │  ml_scripts/policy_mlp.py::train_policy_mlp()
      ▼
embeddable policy MLP  (tiny: rpm_upper -> [spacing_m, azimuth_deg, rpm_lower])
      │  ml_scripts/policy_mlp.py::export_c_header()
      ▼
ml_scripts/artifacts/policy_mlp.h  -- dependency-free C forward pass for the flight controller
```

Run the whole thing with:

```bash
python3 -m ml_scripts.train --csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results.csv \
    --outdir ml_scripts/artifacts
```

(See "Known gaps" above before treating that run's output as the real controller --
this repo's version of the pipeline still optimizes `fom_total` with no power
constraint and no dense continuous search.)

Two-stage design (surrogate -> distilled policy) rather than training the policy
directly on CFD rows: the CFD sweep only tells you performance *for* a given design
point, never the optimal point for an arbitrary commanded RPM -- that has to be
constructed by optimizing over the (interpolated) performance surface, which is what
the surrogate is for. The sweep is also dense in the wrong direction for direct
supervision: 225+ configurations per spacing level, but only 5 distinct `rpm_upper`
values -- the one axis the controller actually takes as input. Training the controller
directly on the CFD rows would yield a 5-entry lookup table, not a controller; sweeping
the *surrogate* densely (stage B) works around this without needing more CFD data.

## What's verified vs. not

- All four modules (`dataset`, `surrogate`, `policy_extract`, `policy_mlp`) run
  end-to-end against a synthetic 420-row dataset (3 rpm_upper x 4 spacing x 7 azimuth x
  5 rpm_lower) with a fabricated-but-structured performance surface. The exported C
  header's arithmetic was checked by re-implementing its exact forward pass in Python
  and confirming it matches `sklearn`'s `.predict()` bit-for-bit (modulo the known
  `%.8g` whole-number literal bug noted in "Known gaps" above, which affects the
  *generated C text*, not this Python-side numerical check).
- **Real multi-`rpm_upper` CFD data now exists** (`co_rot_results.csv`, 1625 rows,
  98.0% converged -- see Status above) and this pipeline has not yet been re-run
  against it in this repo. A demonstration run against an earlier version of the
  dataset (1125-row `co_rot_results_FINAL.csv`) exists in the other worktree with the
  fixes from "Known gaps" applied, and produced sane-looking results (surrogate
  R² 0.77-0.93 held out by spacing/azimuth combination, 0.92-0.96 held out by an entire
  interior `rpm_upper` level) -- but that run used different code than what's in this
  folder, on a dataset that has since been superseded twice over (1125 -> CLEAN.csv
  regeneration -> current 1625-row version), so treat it as evidence the pipeline
  *shape* works, not as validation of this repo's actual numbers.
