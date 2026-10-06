# Pair-specific CZ runtime experiment

This isolated local experiment compares the existing `cloud_runs` MPS model (A) with the same model after replacing only its global CZ depolarizing channel with calibrated pair-specific CZ channels (B). See [REPORT.md](REPORT.md) for measurements and limitations.

## Run

From the repository root, using the existing simulation environment:

```bash
uv pip install --python .venv/bin/python \
  --target experiments/pair_specific_2q_runtime/vendor \
  --cache-dir experiments/pair_specific_2q_runtime/.cache/uv \
  -r experiments/pair_specific_2q_runtime/requirements-extra.txt
.venv/bin/python -B experiments/pair_specific_2q_runtime/run_experiment.py
```

NetworkX is installed only in this experiment's `vendor/`; the project environment and dependency files remain unchanged. The measured stack is Python 3.13.2, Qiskit 2.2.3, Aer 0.17.2, IBM Runtime 0.44.0, NumPy 2.4.0, SciPy 1.16.3, and NetworkX 3.7. `results/configuration.json` records the complete environment and snapshot hashes. Simulation uses only the locally installed FakeFez snapshot; it makes no IBM service or AWS calls.

The default command executes exactly eight jobs for each case at P=1,2,4,8 (64 simulation attempts). Each job is a fresh Python process; a thread pool only supervises processes and refills slots like `xargs -P`. Cases do not overlap. Case order is A/B at P=1, B/A at P=2, A/B at P=4, and B/A at P=8. There is one measured batch per case and P, without additional pilots or timing repetitions.

Completed batches are retained and skipped on restart. An existing individual attempt without a completed batch causes a refusal to overwrite it. To intentionally repeat the full experiment, first archive the existing `results/` directory **inside this experiment directory** and then run again. Keep the recorded snapshot/package versions to reproduce the assignment. Do not mix measurements from different environments.

Optional commands:

```bash
.venv/bin/python -B experiments/pair_specific_2q_runtime/run_experiment.py --prepare-only
.venv/bin/python -B experiments/pair_specific_2q_runtime/run_experiment.py --summarize-only
.venv/bin/python -B experiments/pair_specific_2q_runtime/run_experiment.py --verify-only
```

Preparation compiles and fingerprints circuits but does not simulate. The integrity command compares the entire `cloud_runs/` file list and file hashes with `baseline.json`. It also checks changes outside this directory, while explicitly allowing independently observed user changes to `download_calibrations.py` and `noise_history/`; these are never read or modified by the experiment. Bytecode is disabled, and temporary files/caches stay here.

## Fixed workload and models

For each code 513, 713, 823, and 913, select the first manifest job with two hops and the first with three hops. Zero-based indices are 0, 60, 240, 300, 480, 540, 720, and 780. Paths are `[0,1,2]` and `[0,1,2,3]`. The graph is the existing fully connected six-node graph. Use the original code classes and `build_swap_circuit`, logical input `0`, 2000 shots, basis `cz,id,rz,sx,x`, and optimization level 1. No coupling map, backend target, physical layout, or routing is supplied.

A calls the original `build_simulator` unchanged: backend-derived one-qubit errors and global `depolarizing_error(0.01, 2)`. B calls the same function, removes precisely that global CZ error, and registers a local error for every ordered CZ pair in the compiled circuit. Aer 0.17.2 has no public removal method, so the adapter uses its private `_default_quantum_errors` dictionary; this is tied to the recorded version. All original one-qubit error objects are retained and checked using a serialization fingerprint with random error IDs removed. Their existing parameter convention is deliberately preserved.

Both cases use `matrix_product_state`, `max_parallel_threads=1`, `max_parallel_shots=1`, and `max_parallel_experiments=1`. OpenMP, MKL, OpenBLAS, Accelerate, NumExpr, Rayon, and Qiskit process parallelism are also constrained. Other MPS settings keep their defaults. Transpiler seed is `1729 + manifest_index`; simulator seed is `20261006 + 10000*manifest_index`, identical between cases and P levels. No distribution equivalence claim is made.

## Calibration assignment

The installed FakeFez snapshot is dated 2025-02-26. For a reported average gate infidelity `r`, use `lambda = 4*r/3` in the two-qubit depolarizing channel. A's existing lambda `0.01` therefore corresponds to average infidelity `0.0075`.

Of 352 ordered physical CZ entries, 14 report `r=1.0`. Although their operational flags are true, these values cannot define the requested pure depolarizing channel: complete positivity permits `lambda <= 16/15`, hence `r <= 0.8`. They are explicitly excluded, never clipped. The remaining 338 positive entries have `r` from 0.0021389143724314663 to 0.0500489382618447. The experiment preserves this **valid subset's** distribution; it cannot preserve the invalid entries under the requested channel family. All exclusions and original snapshot JSON are saved.

Sort the valid ordered physical entries by `(r, physical_pair)`. Sort the union of abstract **unordered** CZ pairs across all eight compiled circuits lexicographically. For abstract rank `i`, take pool index `floor((i+0.5)*M/K)`, where M=338 and K=363. Thus every valid physical entry is used once or twice (313 once, 25 twice), with its exact reported value. Both orientations of an abstract pair receive the same rate. Each worker installs channels for every ordered pair that actually occurs in its circuit. The saved assignment table fixes this policy across cases, P levels, and repeated runs with this stack.

This deterministic distribution assignment measures computational cost. It does not identify abstract qubits with physical Fez qubits or support network-fidelity claims. A particular circuit uses a subset of the assignment; the complete eight-job union covers the valid pool.

## Measurements and artifacts

Each `results/{A,B}_p{P}_job{index}.json` records:

- simulator/noise-model construction, circuit construction, transpilation, `run(...).result()`, and parent-observed process wall times;
- peak process RSS, compiled depth/size/operation counts, circuit fingerprint, channel count and number/range of distinct strengths;
- seeds, thread options, Aer execution metadata, counts and syndrome histogram, and CZ coverage checks.

Process wall time includes interpreter/import startup, validation, serialization, and shutdown in addition to the requested timing components. Simulation time isolates `run(...).result()`. A 20-minute watchdog starts at simulation entry and kills the process group on timeout; a 22-minute total-process guard catches stalled setup. Logs, failures, and timeouts are retained.

`batch_*.json` and `batch_timings.csv` contain wall time, median/max individual process time, and jobs/minute. `paired_timings.csv` and `summary.json` contain matched A/B ratios. Circuit JSON/QPY files preserve the actual prepared circuits. Workers independently rebuild and compile them and require matching fingerprints and native operation counts. Every successful run must have exactly 2000 counts and histogram entries, MPS execution, one Aer thread, unchanged one-qubit noise, no readout/thermal noise, multiple B strengths, and complete B CZ coverage.

No decoding, error inference, statistical equivalence tests, other simulator methods, thermal experiments, or full-manifest execution are included.
