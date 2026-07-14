# Tier-2 follow-up: mesh-convergence harness + structured-mesh scoping

**Date:** 2026-07-14
**Branch:** `tier2-structured-mesh`
**Builds on:** `ed6a6fb` (domain/Cp fixes), `2dfd80b` (force-based convergence check)

## What this session adds

`scripts/run_ct_sweep.py` gained three new CLI overrides so a mesh-convergence (GCI)
study — flagged as unpursued in the 2026-07-12 investigation — can actually be run:

- `--blade_level MIN MAX` — override the snappyHexMesh blade refinement/feature level
  (default `(5, 6)`, background cell ~0.4 m → ~6.25 mm near-wall vs. the ~1.3 mm STL
  facets at `n_pts=150` — a known under-resolution noted in-line in the source).
- `--layers N` — override `nSurfaceLayers` on the blade patch (default 5).
- `--medial_ratio RATIO` — override `maxThicknessToMedialRatio` (default 0.3), which is
  the parameter that actually clamps first-layer thickness (confirmed in the prior
  session: retuning `firstLayerThickness` alone did nothing while this was fixed at 0.3).

`maxGlobalCells`/`maxLocalCells` were also raised (12M→20M, 4M→6M) so a finer
`--blade_level` run isn't silently truncated by the existing ceiling.

None of these change default behavior — a plain `run_ct_sweep.py` call with no new
flags produces byte-identical dictionaries to before this branch.

**Not done this session:** no CFD was actually run (no OpenFOAM/WSL access in this
environment). These are unexecuted, syntax-checked and dry-run-smoke-tested only up to
the point where the script needs David's real WSL template case directories. The next
concrete step is to run the GCI study itself on the WSL box, e.g.:

```bash
for lvl in "4 5" "5 6" "6 7"; do
  python3 scripts/run_ct_sweep.py --angles 8 --blade_level $lvl \
    --sweep_dir /home/david/OpenFOAM/ENGR412/gci_study_lvl_${lvl// /_} \
    --csv /home/david/OpenFOAM/ENGR412/gci_study_lvl_${lvl// /_}/ct_results.csv
done
```
then compare CT/CP/thrust across the three levels (Richardson extrapolation) to get an
actual discretization-error estimate instead of ad hoc single-resolution changes.

## Correction to the y+ target framing

The 2026-07-12 doc frames the goal as "target y+<1, matching Jeon & Lee's 25 graded
layers." That target doesn't transfer as-is: this setup's wall BCs are
`kqRWallFunction`/`omegaWallFunction` — standard log-law wall functions, valid for
roughly 30 < y+ < 300, not a low-Re treatment. The observed average y+ ≈ 228–262 is
inside that range already. Chasing y+<1 here would require also switching to
`nutLowReWallFunction`-style BCs and a first-layer height orders of magnitude smaller
than current, which is a materially different (and larger) change than just adding
layers or loosening `maxThicknessToMedialRatio`.

The actual near-wall failure documented in the 07-12 session is narrower and worse:
4–16% of blade faces (concentrated at LE/root/tip) get **zero** prism layers at all,
so those faces sit at whatever y+ the raw background cell gives — the max y+ >1000
reported is coming from exactly those unlayered faces, not from the layered 84–96%
of the surface. That's a coverage problem, not an average-y+ problem, and it will not
be fixed by tuning `nSurfaceLayers`/`medial_ratio` globally.

## Why this points to structured meshing (this branch's namesake)

The 07-12 session's own two independent investigation threads (non-monotonic CT dip
at θ=8–9°, and the Cp sawtooth ripple whose wavelength tracks mesh size but whose
amplitude doesn't shrink with refinement) both converged on the same root cause:
snappyHexMesh's Cartesian cut-cell approach to snapping onto a curved, twisted NACA
0012 surface. Refinement and scheme changes were tested and ruled out. This is
consistent with the LE/root/tip layer-coverage gap above — all three symptoms trace
to the same limitation: an unstructured octree mesh snapped onto curved blade geometry,
rather than a mesh built to conform to it from the start.

**Concrete next-step proposal (not started — this is a scoping note, not code):**

Replace the snappyHexMesh blade region with a structured O-grid (or C-grid) block
topology around each spanwise blade section, extruded/lofted along the span, in place
of background-cell snapping:

1. Generate blade section coordinates directly from `generate_propeller.py`'s existing
   NACA camber/thickness math (already spanwise-stationed — reuse, don't rewrite).
2. Build an O-grid `blockMeshDict` per spanwise station (four blocks around the
   profile + one center block, the standard airfoil O-grid topology), with layer
   count and first-cell height as explicit, guaranteed parameters — no snapping,
   no coverage gaps by construction.
3. Loft/stack stations along span using `createPatch`/`mergeMeshes` or a Python
   generator emitting the full multi-block `blockMeshDict` directly (likely easiest
   given the existing scripted-dictionary pattern in this repo).
4. Validate against the existing `full`-preset snappyHexMesh result at a single angle
   (θ=8°) before committing to a full re-sweep.

This is a multi-session mesh-generation effort, not a drop-in fix — flagging it here as
the scoped follow-on this branch is named for, rather than attempting a partial version
of it blind.

## Open items carried forward unchanged from 07-12

- Non-monotonic CT dip at θ=8–9° (650 rpm) — likely resolved as a side effect of
  structured meshing (root cause identified as mesh/grid alignment sensitivity), not
  independently pursued.
- CP/torque overprediction (~+55% at θ=8° after both 07-12 fixes) — same root cause.
- 1250 rpm (Mtip=0.436) case is still evaluated with an incompressible solver plus a
  post-hoc Prandtl-Glauert correction; a compressible solver remains unexplored.
