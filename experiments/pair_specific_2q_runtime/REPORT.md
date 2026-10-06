# Pair-specific CZ runtime results

1. **Per job:** at P=1, median process slowdown was **1.087× (8.7%)**, ranging from 1.069× to 1.097×. Median Aer simulation slowdown was **1.110× (11.0%)**, ranging from 1.086× to 1.126×.
2. **Full eight-job workload:** **1.085× at P=1**, **1.063× at P=2**, **1.064× at P=4**, **1.048× at P=8**.
3. **Five-minute AWS jobs appear plausibly manageable:** using the serial median process ratio gives `5 × 1.087 ≈ 5.43 minutes`; using the serial median simulation ratio gives `5 × 1.110 ≈ 5.55 minutes`. These are rough projections from this Mac, not AWS measurements or guarantees.
4. **No evidence of a sixfold increase to approximately 30 minutes.** The largest observed paired process ratio across all P levels was 1.116×; the largest simulation ratio was 1.145×. This experiment does not establish the cause of the earlier runtime.

## Measured times

Serial per-job Aer simulation times (seconds). Process ratios include model construction, imports, circuit preparation, validation, and process startup/shutdown.

| Manifest index | Code / hops | A simulation | B simulation | Simulation B/A | Process B/A |
|---:|---|---:|---:|---:|---:|
| 0 | 513 / 2 | 4.04 | 4.54 | 1.124× | 1.074× |
| 60 | 513 / 3 | 5.81 | 6.51 | 1.120× | 1.094× |
| 240 | 713 / 2 | 8.95 | 9.75 | 1.089× | 1.069× |
| 300 | 713 / 3 | 12.64 | 13.98 | 1.106× | 1.095× |
| 480 | 823 / 2 | 15.24 | 16.55 | 1.086× | 1.075× |
| 540 | 823 / 3 | 21.71 | 23.78 | 1.096× | 1.087× |
| 720 | 913 / 2 | 7.86 | 8.74 | 1.113× | 1.087× |
| 780 | 913 / 3 | 11.28 | 12.70 | 1.126× | 1.097× |

Eight-job batches, with all times in seconds. Median/max are individual **process** wall times; A/B values are displayed in that order.

| P | A batch | B batch | Batch B/A | Jobs/min A / B | Median job A / B | Max job A / B |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 115.17 | 124.98 | 1.085× | 4.17 / 3.84 | 13.62 / 14.76 | 25.16 / 27.35 |
| 2 | 68.10 | 72.39 | 1.063× | 7.05 / 6.63 | 14.20 / 15.18 | 26.29 / 27.88 |
| 4 | 38.74 | 41.21 | 1.064× | 12.39 / 11.65 | 15.40 / 16.53 | 26.59 / 28.58 |
| 8 | 34.02 | 35.66 | 1.048× | 14.11 / 13.46 | 22.29 / 22.85 | 34.02 / 35.65 |

At P=1, mean simulator/noise construction was 2.754 s for A and 2.828 s for B (difference +0.074 s). This construction includes the original backend and one-qubit noise setup; the difference is an observed A/B difference, not an isolated microbenchmark. Full timing components, peak RSS, depth, size, native operation counts, and channel counts are in [job_timings.csv](results/job_timings.csv) and the 64 per-job JSON files. Maximum measured per-process peak RSS was 177.0 MiB.

## What was held fixed

Local Apple M4 Pro, 48 GiB RAM, macOS 26.6.2; Python 3.13.2, Qiskit 2.2.3, Aer 0.17.2, IBM Runtime 0.44.0. Eight real Heron R2 manifest jobs: first two-hop and three-hop path for each code 513/713/823/913, always `[0,1,2]` and `[0,1,2,3]`. Each uses 2000 shots, logical `0`, optimization level 1, original circuit-generation functions, and MPS. One process per job and one CPU thread per process; up to P simultaneous processes, matching the existing `xargs -P` architecture. No AWS or IBM service calls were made.

A retains the production global CZ parameter `lambda=0.01`. B replaces only this entry with local CZ errors on every compiled ordered pair, retaining all one-qubit errors exactly. Compiled circuit fingerprints and operation counts match across A/B and every P. No physical routing, coupling map/target, extra gates, readout, thermal/Kraus noise, or simulator-method changes were introduced.

## Calibration and assignment boundary

The local FakeFez snapshot is dated **2025-02-26**. IBM average infidelity `r` is converted using **`lambda=4*r/3`**, verified against channel average gate fidelity. Of 352 ordered CZ entries, **14 have `r=1.0` and are explicitly excluded**: the requested pure depolarizing channel permits only `r<=0.8`. Their operational flags are true; they were not classified as disabled or clipped. The valid 338 entries span `r=0.002139` to `0.050049`.

Sort these entries by `(r, physical_pair)` and sort the 363 abstract unordered pairs lexicographically. Abstract rank `i` gets pool index `floor((i+0.5)*338/363)`; both orientations receive that exact rate. Every valid entry is represented once or twice. Each job installs 44–101 ordered channel entries containing 28–69 distinct strengths. This preserves heterogeneity of the **valid subset**, with no missing abstract CZ errors. See [calibration_assignment.json](results/calibration_assignment.json) for the complete mapping/exclusions and [README.md](README.md) for the reproduction policy. It is a timing assignment, not a physical-device mapping or network-fidelity estimate.

The valid pool's mean `r` is 0.005560, compared with A's implied `r=0.0075`. Thus measured B/A includes both additional per-pair channel handling and changed numerical error probabilities. These two effects are not separately identifiable from the requested two-case experiment. Costs of physical routing, larger gate counts, and thermal/Kraus channels are outside this comparison and cannot be assigned numerical shares from it.

## Validation and limits

**64/64 attempts succeeded; no failures or timeouts.** Every counts dictionary and histogram sums to exactly 2000. All B circuits have multiple strengths and complete CZ coverage; one-qubit noise fingerprints match A. Aer metadata confirms MPS and one thread. [validation.json](results/validation.json) records these checks. No syndrome-distribution equivalence tests, decoding, or error inference were performed.

There was one measured batch per case/P, with alternating A/B order, fixed seeds, and no repetitions or confidence intervals. Local contention, startup costs, hardware, and calibration choice limit extrapolation to AWS and other historical snapshots. These measurements support a modest increase for this workload; they do not predict the full 960-job workload.

**`cloud_runs/` is unchanged:** its complete 46-entry tree (42 files, four directories) and every file hash match the pre-experiment baseline. No bytecode/cache files were created there. [integrity_check.json](integrity_check.json) records the comparison. Independently occurring changes to root `download_calibrations.py` and `noise_history/` were preserved and explicitly excluded from other workspace checks. All experiment-created files are under this directory; no production files, project dependencies, AWS configuration, commits, pushes, or deployments were changed by this experiment.
