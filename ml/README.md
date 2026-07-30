# ml/ -- lower-rotor control MLP (co-rotating only)

## Status as of 2026-07-16 (start here if picking this up fresh)

**Trained end-to-end on real data for the first time.** `python3 -m ml.train --csv
.../co_rot_results.csv --outdir ml/artifacts` ran successfully against the full
1675-row post-revision CSV: surrogate held-out R2 = 0.968 (thrust), 0.977 (power),
0.901 (FOM); wrote `policy_table.csv` and `policy_mlp.h`. Azimuth-sensitivity
question from the prior note is closed -- see
`analysis/stacked_rotor_literature_pivot_2026-07-15.md` on the main ENGR412 repo for
the full writeup (median thrust swing 34.4% across azimuth, matching/exceeding the
literature).

**`ml/policy_extract.py::build_policy_table()` only grid-searches the exact CFD-
tested rpm_lower values (5 points), not a continuous range.** This produced an
apparently discontinuous jump in the policy table (optimal rpm_lower jumping from
1050 to 1200 between adjacent rpm_upper values) that looked like a real physical
cliff but isn't -- the underlying surrogate is a smooth continuous function
(verified by evaluating it densely), the true optimum drifts gradually, and the
"jump" was purely the argmax flipping between two coarse grid candidates. Worth
searching a denser `rpm_lower` grid (not just the literal CFD-tested points) before
trusting the policy table's exact values.

**Design-space RPM grids are now derived from tip Mach number, not literal RPM
lists (`scripts/run_sweep.py`, 2026-07-16).** Raw RPM only means anything relative
to the rotor diameter it's paired with; `DIAMETER` is a pure CFD variable here
(project is computational-only, no physical build -- D=1.0 was chosen for
Caradonna-Tung-comparable CT validation, not because a 1m rotor is the actual
target hardware size). `rpm_from_mtip()`/`mtip_from_rpm()` plus the
`M_TIP_GRID_UPPER`/`M_TIP_GRID_LOWER` constants mean the RPM design space (and the
MRF zone radius/half-height, which were also silently hardcoded assuming D=1.0)
now rescale automatically if DIAMETER ever changes, instead of every constant
needing hand-recalculation. Numerically identical to the prior design space at the
current D=1.0 for spacing/MRF constants; the RPM grids themselves are a similar but
not bit-identical range, chosen for M_tip=0.08-0.26 rather than reproducing the old
literal values -- existing CSV rows are unaffected either way (self-describing by
their own stored columns).

## Status as of 2026-07-15

**The rpm_upper sweep is done.** `/home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results.csv`
has all 700 cases (4 spacing x 7 azimuth x 5 rpm_lower x 5 rpm_upper, rpm_upper in
[500, 600, 700, 800, 900]) completed and converged. This is real data, not the
synthetic smoke-test set referenced further down -- `ml/train.py` can be pointed at
it for real now. This hasn't been done yet as of this note; that's the next concrete
step on this branch.

**Hardware deployment target is now known: Arduino + SimpleFOC.** The embedded policy
(`ml/policy_mlp.py::export_c_header()` / `ml/rule_policy.py::export_c_header()`) was
built as a generic dependency-free C header assuming *some* microcontroller target,
without a specific one in mind. Now that it's Arduino running SimpleFOC specifically,
this needs review before assuming the existing export is a drop-in fit:

- SimpleFOC's own control loop expects target commands (e.g. `motor.target = ...` for
  velocity/angle/torque mode) fed to it each loop iteration -- the policy MLP's job is
  to compute that target (lower rotor RPM, and whatever azimuth/spacing actuation
  exists mechanically), not to implement FOC commutation itself. The two shouldn't
  conflict, but the actual integration point (where in the Arduino sketch's loop the
  policy's `policy_forward()` gets called, and how its outputs map onto SimpleFOC's
  motor objects) hasn't been designed yet.
- Azimuth and spacing need actual servo/actuator hardware and control, separate from
  the SimpleFOC-driven rotor motor(s) -- confirm what's actually mechanically able to
  be commanded before assuming the policy's 3-output shape is what the firmware needs.
- Arduino's available RAM/flash and float vs. double precision are worth checking
  against the exported header's size before assuming it fits -- the policy MLP is
  tiny by construction so this is likely fine, but hasn't been verified on-device.

**`ml/rule_policy.py` exists** as a deterministic placeholder with the identical
`.predict()` / `export_c_header()` interface as the trained `PolicyMLP` (rpm_lower =
rpm_upper, azimuth steps 45/90/135 deg at 500/900 RPM) -- useful for wiring up and
testing the Arduino/SimpleFOC integration itself before the real trained model exists,
since it's swappable for the real one with zero call-site changes once ready.

## Literature pivot (2026-07-15): run the azimuth-sensitivity EDA before training

Two stacked/co-rotating rotor papers (Jacobellis et al. 2021; Hong et al. 2023) were
reviewed for the CFD-meshing side of this project and turned out to be directly
relevant here too -- both sweep essentially the same design variables as this
dataset (azimuthal/index angle, axial/stacking spacing) and both report azimuth as
one of the two dominant physical effects on stacked-rotor thrust/efficiency (17.1%
total-thrust swing over just 22.5 deg of azimuth in Jacobellis; an azimuth-optimum
whose location shifts with stacking distance in Hong). That directly contradicts
the prior (superseded) EDA's finding that azimuth is "aerodynamically negligible" --
see the section below for that finding's original context.

**Root cause found and fixed (2026-07-15): the design space itself was the problem.**
`scripts/run_sweep.py`'s dual-rotor MRF zone sizing shrank proportionally with
spacing to avoid the two rotors' rotating zones overlapping, which is also why
spacing=0.10m was dropped entirely from the old design space. Net effect: the
700-case sweep never actually reached the close-spacing regime (Hong et al.:
strongest effects at 0.1-0.3D; our old range started at 0.20D) where azimuth
interference is physically dominant, and the azimuth grid itself (0-90 deg only,
15 deg steps) undersampled the region right around 0 deg where both papers show
the sharpest features. Given rigid, non-deflecting blades and a hub depth of
0.03*D (project owner's spec), the true physical minimum spacing is one full hub
depth (0.03 m) -- hubs would collide below that, not half of it.

Revised (this commit): `spacing_m` now starts at 0.05 m (`MRF_FEASIBLE_MIN_SPACING`,
the closest the current dual-MRF-cylinder method can mesh without the zones
overlapping or going degenerately thin -- still short of the 0.03 m physical floor,
which needs an overset/AMI rewrite to actually reach), with denser sampling toward
the close end; `azimuth_deg` is now symmetric (-90..+90) and denser near 0 deg.
MRF zone sizing itself now has an explicit floor + fails fast instead of silently
shrinking to something numerically meaningless. Full writeup:
`analysis/stacked_rotor_literature_pivot_2026-07-15.md` on the main ENGR412 repo.

**Still need to re-run the sweep** with the revised design space before
`ml/eda_azimuth_sensitivity.py` can give a real answer -- the existing 700-case
CSV predates this fix and was generated by the design space that most likely
caused the negligible-azimuth result in the first place.

This also closes out the CFD-meshing question that was blocking work on the other
branch: the O-grid rewrite scoped in `structured_mesh_followup_2026-07-14.md` has
been dropped (the actual CT benchmark paper, Jeon & Lee 2025, doesn't use one
either -- see the pivot doc). Given this is an undergraduate assignment on
open-source tooling where validation error is acceptable as long as the MLP
control pipeline works end-to-end, further CFD refinement effort is being redirected
toward sanity-checking the co_rot sweep (this section) rather than chasing tighter
CT agreement.

## The one thing that needed fixing before training on real data (done -- kept for context)

**Originally, the `co_rot_results.csv` design space couldn't train this controller.**
`scripts/run_sweep.py`'s `co_rot` dataset fixed `rpm_upper = 900` for all 140 cases
(see `RPM_UPPER` in that file). The objective here is "lower rotor command as a
function of upper rotor RPM" -- with only one upper-RPM operating point in the data,
there was nothing to learn that relationship from; a model trained on it would have
just memorized a single-point offset and extrapolated blindly (silently, since nothing
in the code would flag it) to any other commanded RPM. This is resolved now (see
Status above) -- the section below is kept as the rationale for why the fix exists.

This branch adds a `--rpm_upper` override to `run_sweep.py` (see that file's diff)
so a real dataset can be built, e.g.:

```bash
python3 scripts/run_sweep.py --dataset co_rot --parallel 12 \
    --rpm_upper 700 900 1100
```

This triples the case count (140 -> 420) and is not free -- pick the smallest set of
upper-RPM points that meaningfully spans the flight envelope before committing to a
full run. The case_id/CSV format only changes when more than one `rpm_upper` value is
requested, so the existing 140-case dataset and its case_ids are untouched by this
change (see the comment above `DESIGN_SPACE_DUAL` and `case_id_fn` in `run_sweep.py`).

`ml/dataset.py::load_co_rot()` raises by default if it's handed a single-rpm_upper
CSV, specifically so this gap can't be silently ignored later. Pass
`require_multi_upper=False` (or `--allow_single_upper` to `ml/train.py`) only to
smoke-test the code path on existing data -- the resulting policy is degenerate
(same output regardless of commanded RPM) and isn't meant to be trusted or flown.

## Pipeline

```
co_rot_results.csv
      │  ml/dataset.py::load_co_rot()  (drop non-converged, compute CT/CP/PLnorm)
      ▼
forward surrogate  (ml/surrogate.py)
  MLPRegressor: [rpm_upper, spacing_m, azimuth_deg, rpm_lower] -> [thrust_total_N, power_total_W, fom_total]
      │  ml/policy_extract.py::build_policy_table()  (grid-search the surrogate per rpm_upper, keep the argmax)
      ▼
policy table  (one row per rpm_upper grid point: the best spacing/azimuth/rpm_lower found)
      │  ml/policy_mlp.py::train_policy_mlp()
      ▼
embeddable policy MLP  (tiny: rpm_upper -> [spacing_m, azimuth_deg, rpm_lower])
      │  ml/policy_mlp.py::export_c_header()
      ▼
ml/artifacts/policy_mlp.h  -- dependency-free C forward pass for the flight controller
```

Run the whole thing with:

```bash
python3 -m ml.train --csv /home/david/OpenFOAM/ENGR412/2_co_rot_sweep/co_rot_results.csv \
    --outdir ml/artifacts
```

Two-stage design (surrogate -> distilled policy) rather than training the policy
directly on CFD rows: the CFD sweep only tells you performance *for* a given design
point, never the optimal point for an arbitrary commanded RPM -- that has to be
constructed by optimizing over the (interpolated) performance surface, which is what
the surrogate is for. This also matches the project's planned three-tier fallback
hierarchy (adaptive hybrid -> static MLP surrogate -> identical-RPM baseline): this
pipeline builds the middle tier.

## What's verified vs. not

- All four modules (`dataset`, `surrogate`, `policy_extract`, `policy_mlp`) run
  end-to-end against a synthetic 420-row dataset (3 rpm_upper x 4 spacing x 7 azimuth
  x 5 rpm_lower) with a fabricated-but-structured performance surface. The exported
  C header's arithmetic was checked by re-implementing its exact forward pass in
  Python and confirming it matches `sklearn`'s `.predict()` bit-for-bit.
- **Not verified against real CFD data** -- none exists yet with more than one
  `rpm_upper` value. Surrogate accuracy, policy-table sanity, and the azimuth
  question below all need to be re-checked once the real multi-RPM sweep exists.

## Open question carried over from project memory: does azimuth matter?

The prior (525-case, superseded per README) EDA found azimuth angle aerodynamically
negligible. The current 140-case space's own EDA is still pending. If that finding
holds on the real re-run, `POLICY_OUTPUT_COLS` in `ml/policy_mlp.py` should drop from
3 outputs to 2 (spacing, rpm_lower; azimuth fixed at 0), which also removes the need
for an azimuth actuator in the mechanical design. Don't assume it still holds --
check the re-run EDA first.
