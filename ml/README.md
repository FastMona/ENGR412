# ml/ -- lower-rotor control MLP (co-rotating only)

## The one thing to fix before training on real data

**The current `co_rot_results.csv` design space cannot train this controller.**
`scripts/run_sweep.py`'s `co_rot` dataset fixes `rpm_upper = 900` for all 140 cases
(see `RPM_UPPER` in that file). The objective here is "lower rotor command as a
function of upper rotor RPM" -- with only one upper-RPM operating point in the data,
there is nothing to learn that relationship from; a model trained on it would just
memorize a single-point offset and extrapolate blindly (silently, since nothing in
the code would flag it) to any other commanded RPM.

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
