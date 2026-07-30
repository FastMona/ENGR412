# Literature check + meshing pivot (2026-07-15)

## Question that started this: do the reference papers use O-grid?

Five papers now reviewed. Short answer: only one of them clearly does, and it's
not the CT benchmark paper.

| Paper | Meshing approach | O-grid? |
|---|---|---|
| Qin & Yang (ART3) | Structured **C-H** blade grid + overset background | No (C-H, a related but different topology) |
| NORMA slides (ART5) | Structured near-body block (unlabeled) + unstructured tet background | Ambiguous, not named in text |
| **Jeon & Lee 2025 (ART8)** -- our actual CT benchmark | ANSYS Fluent automated meshing: 25-layer viscous/prism stack + generic unstructured tet/poly background, ~13.6M cells | **No** |
| Jacobellis et al. 2021 (ART1) -- stacked rotor experiment + CFD | Helios: mStrand unstructured near-body grid + SAMCart structured *Cartesian* off-body solver (dual-mesh, adaptive Q-criterion refinement in the wake) | No |
| Hong et al. 2023 (ART2) -- stacked rotor design exploration + NN optimization | KFLOW: Chimera grid = **O-H blade grid** (197x61x149, chord x normal x spanwise) + Cartesian background, y+<=1, 20-25 boundary-layer points | **Yes** |

So across five papers spanning the exact CFD tooling landscape relevant here, exactly
one (Hong et al., the paper closest in design-variable structure to our own co_rot
sweep) uses a true O-grid variant, and it's paired with a Cartesian background grid
via Chimera overset, not a pure structured domain. The paper we're actually being
validated against for CT (Jeon & Lee) doesn't use one at all -- it succeeds with
prism layers + unstructured background, which is architecturally closer to what
snappyHexMesh already does than to a hand-rolled O-grid.

## Pivot decision

Per direction from the project owner (2026-07-15): this is an undergraduate
independent-study assignment built on open-source tooling, not a research paper --
validation error is acceptable as long as the end-to-end pipeline (CFD sweep -> MLP
policy -> embedded controller) actually works. That changes the cost/benefit here
substantially.

**Dropping the full O-grid/C-H generator rewrite scoped in
`structured_mesh_followup_2026-07-14.md`.** Building and debugging a hand-rolled
multi-station lofted O-grid blockMeshDict (or wiring up classy_blocks) is a
multi-week undertaking for a topology that isn't even what the primary benchmark
paper uses. That effort is better spent elsewhere given the actual deliverable.

**Keeping snappyHexMesh, not chasing further GCI refinement on it either.** The
GCI study's own result (level (6,7) diverging, p=-2.898, oscillatory/non-monotonic)
already told us more mesh levels on this approach have diminishing, possibly
negative, returns. The existing CT comparison (Appendix A results, <1% deviation
at 5-8 deg per the project's own validation_summary.csv) is a defensible baseline
for an undergraduate submission as-is. Further tuning (absolute vs. relative first
layer thickness, more layers) is a nice-to-have, not a blocker.

**Redirecting remaining CFD-validation effort toward the co_rot sweep, not CT.**
This is the more important realization from reading ART1 and ART2 closely: CT
(Caradonna-Tung) is a *single, untwisted, non-interacting rotor* case. It validates
that the solver gets basic rotor aerodynamics right, but it tests none of the
physics that actually matters for this project -- upper/lower rotor interaction,
azimuthal-spacing sensitivity, blade-vortex interaction (BVI). ART1 and ART2 are
*direct* validation targets for the 700-case co_rot sweep already sitting in
`2_co_rot_sweep/co_rot_results.csv`, in a way CT never was.

## Concrete, checkable targets for the co_rot sweep (from ART1 + ART2)

Both papers sweep almost exactly our design space (index angle / azimuthal
spacing, axial/stacking spacing, and in Hong's case a pitch differential). Their
reported trends give quantitative sanity checks our own sweep should reproduce
qualitatively, even if magnitudes don't match exactly:

1. **Total thrust has real, large sensitivity to azimuthal spacing at fixed
   collective/RPM.** Jacobellis: 17.1% total-thrust swing over just a 22.5 deg
   change in index angle (a 0.76%/deg sensitivity), with a minimum near phi=0 deg
   and rising toward phi=+17 deg at their tested spacing (z/c=0.73). Hong: total
   power loading similarly has a clear azimuth-dependent optimum, and *where* that
   optimum sits shifts with stacking distance (small Z -> optimum near +90 deg;
   larger Z -> optimum migrates toward moderate positive index angles, driven by
   the blade-vortex-interaction effect becoming dominant over the near-field
   airfoil-interaction effect).
2. **Efficiency (CT/CP or PLnorm) gains of order 2-12% are achievable over an
   equally-spaced baseline**, by picking azimuth/spacing well -- not free, and not
   huge, but real and worth an MLP finding it. (Jacobellis: 3.5% at z/c=0.73, up to
   11.6% at z/c=1.75; Hong: 1.35-8.65% across the DOE, 9.33% after NN-based
   optimization.)
3. **Pitch/collective differential between rotors has comparatively small effect**
   on power loading (Hong's violin plot, Fig. 7: near-identical PLnorm
   distributions across pitch-difference 0-4 deg) -- azimuth and spacing are what
   dominate, not differential collective.

## Why point 3 above (and its mirror image) matters right now

`ml_scripts/README.md` on the mlp-lower-rotor-control branch carries this open question,
verbatim: *"The prior (525-case, superseded) EDA found azimuth angle
aerodynamically negligible... Don't assume it still holds -- check the re-run EDA
first."*

That prior finding is the opposite of what both of these papers report. Azimuthal
spacing is described in both as one of the two dominant physical effects on
stacked-rotor performance (the other being axial/stacking spacing), capable of
swinging total thrust by 15-17% on its own. If the real 700-case co_rot sweep's
own EDA still shows azimuth as negligible, that's not a "huh, interesting" result
-- given the published physics, it's a signal something in the sweep itself (near
body mesh resolution around the blade-blade gap, insufficient azimuthal sampling
density, or an MRF/domain sizing issue) is failing to capture the interaction
physics these papers say should be there. This needs to be checked against the
real data before the MLP is trained on it, not after.

See `ml_scripts/eda_azimuth_sensitivity.py` (mlp-lower-rotor-control branch) for the
check itself.

## Root cause, acknowledged and design space revised (2026-07-15)

Confirmed with the project owner: there's no real physical question that azimuth
matters at close spacing (Biot-Savart/bound-vortex interference is first-order
physics here, not a subtle effect) -- the "negligible" result is very likely an
artifact of how the co_rot design space and mesh/MRF setup were built, not a
finding about the actual aerodynamics.

Mechanism: `cfd_scripts/run_sweep.py`'s dynamic MRF sizing
(`mrf_dz = min(0.25, spacing * 0.45)` in `write_case_configs_dual`) existed to
stop the two rotors' MRF zones from overlapping, and `spacing_m = 0.10` was
already dropped from the design space for exactly this reason ("MRF-zone-overlap
issue that made those cases unphysical" -- see `ml_scripts/dataset.py` docstring). This
was likely introduced/tuned while getting the co_rot sweep (feeding the
placeholder "dummy" rule-based controller in `ml_scripts/rule_policy.py`) to actually run
and converge, not as a deliberate choice about which spacing regime to study. Net
effect: the tested range (0.20-0.60 m = 0.20-0.60D) was biased away from the
close-spacing regime (Hong: strongest effects at 0.1-0.3D; Jacobellis: even
tighter) where azimuth sensitivity is largest, plus the azimuth grid itself only
covered 0-90 deg in 15 deg steps with nothing sampled near 0 deg or in the
negative range where the papers show the sharpest features.

**Physical minimum spacing.** The whole CFD pipeline assumes rigid, non-deflecting
blades and incompressible flow. Under that assumption, the real hard constraint on
how close the rotor planes can get is the hub -- the thickest rigid part -- not
blade-tip clearance. Given hub depth = 0.03 * D (project owner's spec), the
physical minimum spacing is one full hub depth, 0.03 m: each hub occupies its own
full thickness at its own rotor plane, so the two would collide below a full hub
depth of separation, not half of one (an earlier draft of this note incorrectly
used hub/2 -- corrected the same day).

**Fixed (this commit, on the mlp-lower-rotor-control branch's
`cfd_scripts/run_sweep.py`, since that's the version that actually produced
`co_rot_results.csv` -- the copy on this branch is an older pre-rpm_upper
variant and was left untouched):**
- `spacing_m` design space now starts at `MRF_FEASIBLE_MIN_SPACING` = 0.05 m
  (derived from a documented MRF-zone half-height floor, itself tied to the hub
  depth) instead of 0.20 m, with denser sampling toward the close end.
  `spacing_m = 0.10` is back in.
- `azimuth_deg` is now symmetric (-90..+90) and denser near 0 deg, matching both
  papers' sampling convention.
- MRF zone sizing now has an explicit floor and fails fast with a clear error if
  a requested spacing is below what the current dual-cylinder method can mesh
  validly, instead of silently shrinking to a degenerate zone.
- **Note the remaining gap:** `MRF_FEASIBLE_MIN_SPACING` (0.05 m) is still larger
  than the true physical minimum (0.03 m). Reaching 0.03-0.05 m needs replacing
  the two independent MRF cylinders with an overset/AMI-based approach -- not
  attempted yet, left as a clearly-flagged open item.

The existing 700-case `co_rot_results.csv` predates this fix and was generated
under the design space that most likely caused the negligible-azimuth result --
it needs a re-run under the revised design space before that question is
actually resolved (see `ml_scripts/eda_azimuth_sensitivity.py` and `ml_scripts/README.md`).
