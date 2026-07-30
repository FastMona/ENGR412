# C-T Validation: Domain-Orientation Bug Investigation & Fix

**Date:** 2026-07-12
**Scope:** `cfd_scripts/run_ct_sweep.py`, `cfd_scripts/generate_propeller.py` (`full` geometry preset)

## Starting problem

A full-geometry resweep (after combining wake refinement, an LE-geometry fix, and a
retuned `firstLayerThickness`) showed mean |CT error| roughly *double* the previous
best result (650rpm: 30.0% vs. 16.6%; 1250rpm: 75.1% vs. 44.6%), plus a nonphysical
~33-37N thrust at θ=0° (should be ≈0, since a symmetric NACA 0012 blade at zero
collective and zero twist produces no net lift).

## Changes tried, in order

| # | Change | Outcome |
|---|---|---|
| 1 | Raised `refinementSurfaces`/feature-edge levels (3,4)→(5,6) | Fixed a real bug: boundary-layer prism-layer coverage went from 0% (silently reverted every iteration due to illegal faces) to 81-96% coverage. Necessary, kept. |
| 2 | Fixed degenerate zero-area STL facets at the blade leading edge (`generate_propeller.py::build_section`, dropped duplicate LE vertex) | Removed ~100 zero-area triangles per blade STL across all propeller geometries (single, coaxial, C-T). Legitimate geometry fix, kept. Did not rescue the specific LE/root/tip faces that still lack layers (accepted residual, low priority). |
| 3 | Added a `yPlus` function object to `controlDict` | Diagnostic only — revealed average y+≈228-262 (target ~100), max y+>1000 concentrated at unlayered faces. Kept for ongoing visibility. |
| 4 | Retuned `firstLayerThickness` (0.015 → 0.00657) | **Dead end.** Produced a bit-identical mesh/y+ result — `maxThicknessToMedialRatio 0.3` clamps the achievable thickness regardless of the nominal request. Reverted to 0.015. |
| 5 | Added a wake/tip-vortex volumetric refinement cylinder (`WAKE_R`/`WAKE_ZSTART`/`WAKE_ZEND`, `refinementRegions`) | Adds ~5% cells, doesn't disrupt layer coverage. Isolation-tested (disabled/re-enabled) against the θ=0° anomaly — **did not cause it** (anomaly got slightly worse without it, disproving the original wake-refinement hypothesis). Direction bug found later (#8). |
| 6 | Fixed `MRF_R` from a hardcoded 1.40 m to the derived `0.55×D_CT` (≈1.257 m), matching ART8 (Jeon & Lee 2025) Appendix A's "1.1D radial and axial" MRF-sizing convention | Thrust unaffected (<1%); torque/power shifted ~15-16% at θ=8°. Consistency fix, kept. |
| 7 | **Root-caused the θ=0° anomaly: domain z-extent was backwards.** `full` preset used 2.5D on the −z (wake/downstream) side and 10D on the +z (entrainment/upstream) side. Thrust is measured +z, so by Newton's third law the wake is pushed toward −z — the *short* boundary was sitting in the developing wake's path (causing a boundary-interaction pressure artifact), while the *long* boundary was wasted on the calm entrainment side. | **Confirmed via a symmetric-domain diagnostic**: symmetrizing the z-extent (±2.5D, same fine mesh) collapsed the θ=0° spurious thrust from a stable +37.4N plateau to <1N. Swapping `BOX_ZMIN`/`BOX_ZMAX` so the short (2.5D) leg is on +z and the long (10D) leg is on −z fixed it directly: θ=0° went from a converged wrong plateau (+37.4N) to a value still decaying toward zero (−4.4N at t=1000, trending down). This is the key fix from this session. |
| 8 | Fixed the wake/tip-vortex refinement cylinder's z-direction (`WAKE_ZEND`), which had the same backwards assumption — it extended 3D into the +z entrainment side instead of the −z wake side where tip vortices actually travel. | θ=8° (650rpm): T 180.2N→185.1N, but Q/P dropped ~11% (37.18→32.99 N·m, 2531→2246 W) and both CT and CP errors improved vs. the domain-fix-only result. No regression seen. |

## Diagnostic technique used

Three isolating background-mesh CFD runs were used to separate variables before touching
the main pipeline:
- **`full_symtest`** (temporary preset, later removed): full mesh resolution + symmetric
  ±2.5D z-domain → isolated *domain asymmetry* from *mesh resolution* as the θ=0° driver.
- **Extended `reduced`-preset θ=0° run** (t=1000→5000, resuming from a copied case):
  proved the `reduced` preset's θ=0° result was NOT the "correct ~0" it appeared to be at
  t=1000 — it was still climbing and only truly plateaus (~3.48N) around t≈1800. This
  disproved an early theory that `reduced` was simply slower to reach the same wrong
  equilibrium as `full`; it actually converges to a smaller, independent nonzero value.
- Force-time-history inspection (`postProcessing/forcesRotor/*/force.dat`) was essential
  throughout — reading only the final iteration's force is unreliable, since these MRF
  hover cases converge slowly and can plateau at a wrong equilibrium that looks
  indistinguishable from a mid-transient value without the full history.

## Post-fix validation status (both fixes applied: domain orientation + wake-zone direction)

**650rpm (Mtip=0.228), full preset, mean |CT error| = 22.4%** — better than the
regressed 30.0%, not yet back to the original best of 16.6%. θ=0° is now −0.00070
(from the equivalent of +37N pre-fix). Error is systematic, not noise: CFD overpredicts
CT at low collective (2°-7°, up to +48%) and underpredicts at high collective (8°-12°,
down to −27%), with the sign flipping around 7°-8°. A non-monotonic dip at θ=8°-9°
persists — this was flagged earlier in the investigation and is independent of the
domain-orientation bug (not resolved by this session's fixes).

**1250rpm (Mtip=0.436), full preset, mean |CT error| = 61.5%** — dominated by θ=5°
(+147%), where the experimental CT is small enough that a modest absolute overprediction
(ΔCT≈0.0031, similar in magnitude to θ=8°'s ΔCT≈0.0015) reads as a huge percentage. θ=12°
(highest-thrust, least noise-sensitive point) is only +3.9% off.

## Known open issues (not addressed this session)

1. **Non-monotonic CT dip at θ=8°-9°** (650rpm) — real, not noise; root cause unknown.
2. **CP/torque overprediction** is large and was not meaningfully improved by either fix
   (still ~+55% at θ=8° after both fixes, vs. +74% before) — a separate problem from the
   thrust/CT prediction.
3. **LE/root/tip prism-layer coverage gap** (~4-16% of blade faces still lack layers) —
   traced to a genuine curvature-vs-cell-size mismatch at a geometric singularity, not
   pursued further (diminishing returns).
4. Broader unexplored strategies: formal grid-convergence (GCI) study, compressible
   solver for the 1250rpm/Mtip=0.436 case instead of a post-hoc Prandtl-Glauert
   correction, steady MRF → transient rotating-mesh (pimpleFoam + AMI/sliding interface).

## Files changed

- `cfd_scripts/run_ct_sweep.py`: `BOX_ZMIN`/`BOX_ZMAX` (module defaults and `full` preset),
  `WAKE_ZEND`, `MRF_R`, `refinementSurfaces`/feature levels (refactored into a
  `BLADE_LEVEL` constant), `firstLayerThickness` (reverted to original), added `yPlus`
  function object, added wake refinement region.
- `cfd_scripts/generate_propeller.py`: `build_section()` LE duplicate-vertex fix.
- `cfd_scripts/C-T_comparisonA.py`: `extract_cp()` per-point dynamic-pressure fix (see below).

Committed as `1deecab` ("Fix C-T domain z-orientation bug causing spurious theta=0
thrust") and pushed to `origin/main`.

---

## Follow-up same day: `reduced`-preset regeneration + root-cause exploration of the two open issues

After the domain-orientation and wake-zone fixes above, the `full`-preset data was
regenerated (`caradonnaTung_full_650rpm_v2`, `caradonnaTung_full_1250rpm_v2` — the
22.4%/61.5% figures above) and the `reduced` preset — which predated *all* of today's
fixes — was regenerated too (`caradonnaTung_reduced_650rpm_v2`,
`caradonnaTung_reduced_1250rpm_v2`). All stale pre-fix directories and this session's
one-off diagnostic directories were then deleted.

**Reduced preset, post-fix:**

- 650rpm: mean |CT error| = 30.6% (worse than `full`'s 22.4%, as expected — coarser
  mesh, n_pts=50 vs. 150, smaller domain).
- 1250rpm (θ=5/8/12): mean |CT error| = 69.3% (worse than `full`'s 61.5%, same reason).

Both results are consistent with `reduced` simply being the cheaper/coarser preset;
nothing alarming. `full` remains the better-founded preset (aligned with ART8 Appendix
A) going forward.

### Thread 1: the non-monotonic CT dip

Checked whether the θ=8°-9° dip (650rpm, `full`) tracked mesh quality:

- Direct polyMesh parsing (`analyze_layer_coverage.py`) across θ=6°-11° showed layer
  coverage 90.2%-96.8% with **no clean correlation** to the dip — θ10° had the *worst*
  coverage (90.2%) of the six angles checked yet the *highest* thrust (no dip), while
  θ9° had middling coverage (93.6%) but the *lowest* thrust. Cell counts (1365k-1375k)
  and y+ averages (209-242) were similarly flat across the range.
- The stronger evidence came from the `reduced`-preset 650rpm regeneration: it dips
  hard at **θ4°→5°** (156.1N→127.8N, -18%) instead of θ8°-9°, with only a faint
  plateau at 9°-11°. A real aerodynamic non-monotonicity should occur at the same
  physical AoA regardless of mesh/domain preset — instead the dip's location moves
  with the mesh.

**Conclusion:** very likely a per-angle mesh-realization artifact, not real flow
physics — each collective angle gets an independently-rotated blade STL snapped onto
the *same* fixed background Cartesian grid, and snappyHexMesh's snap/layer quality is
known to be sensitive to that alignment. Not resolved; would need either per-angle
mesh-convergence verification across the whole sweep, or a meshing approach not
sensitive to STL/grid alignment (see Thread 2 conclusion — same underlying cause).

### Thread 2: CP/torque overprediction

Confirmed the overprediction is ~93% pressure-driven, not viscous (θ=8°, 650rpm:
Pressure=-30.62 N·m vs. Viscous=-2.37 N·m) — rules out the fully-turbulent kOmegaSST
assumption inflating skin friction as the main driver.

Inspected sectional Cp (`C-T_comparisonA.py`'s Cp-section plot, θ=5°/1250rpm) and found
a persistent sawtooth ripple across the entire chord, upper and lower surface, at every
span station. Three hypotheses tested, in order:

1. **Cp-normalization bug**: `extract_cp()` binned points within a ±3% r/R band and
   normalized all of them by one band-averaged dynamic pressure instead of each point's
   own radius (q ∝ r²) — fixed (kept, real correctness bug), but the ripple was
   **visually unchanged** after the fix. Ruled out: the loft-ring spacing (~68mm)
   already exceeds the band width, so each band only ever contained one ring in
   practice.
2. **Mesh under-resolution**: refined `BLADE_LEVEL` from (5,6) to (6,7) (near-wall
   cells ~6.25mm→~3.1mm) at θ=5°/1250rpm. Result: T 584.8N→555.4N (-5.0%), Q
   -106.7→-95.2 N·m (-10.8%) — torque fell disproportionately more than thrust (right
   direction, CT error improved +147.4%→+135.0%), but the Cp ripple's **wavelength**
   shrank (more surface points: 18370→43364) while its **amplitude did not** — the
   signature of a scheme/representation artifact, not a pure resolution deficit.
3. **Discretization scheme**: re-solved the same (unrefined) mesh with
   `snGradSchemes`/`laplacianSchemes` changed from `corrected` to
   `limited corrected 0.5` (more robust on non-orthogonal meshes). Result: **zero
   effect** — CT/CP changed by <1%, and the Cp figure was visually identical to
   baseline. Ruled out.

**Conclusion:** neither mesh refinement nor scheme robustness fixes the sawtooth or
fully resolves the torque overprediction, though refinement gives a real, modest gain.
The ripple's wavelength consistently tracks mesh cell size while its amplitude doesn't
shrink — most likely an artifact of snappyHexMesh's Cartesian-cut-cell representation
of the curved NACA 0012 surface, the same underlying limitation implicated in Thread 1.
Fully resolving both would likely require a body-fitted/structured mesh around the
blade (e.g. an O-grid or C-grid) instead of a Cartesian-background snap mesh — a
substantially larger undertaking than anything tested this session, not attempted.

### Updated open issues

Both threads above now point to the **same root cause**: snappyHexMesh's Cartesian
background/cut-cell approach, not a specific parameter that can be tuned away. This
supersedes item 1/2 in the "Known open issues" list further up — they're linked, not
independent problems.
