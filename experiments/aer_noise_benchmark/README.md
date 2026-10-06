This isolated experiment reviews `cloud_runs/` and compares Aer engines without changing production files. Read [REPORT.md](REPORT.md) for the findings, [results/summary.json](results/summary.json) for timings and statistics, and [validation.json](validation.json) for evidence checks.

The benchmark has no AWS calls. It imports the existing circuit and noise builders with bytecode writes disabled. Dependencies, temporary files, caches, frozen circuits, calibration snapshots, and results stay in this directory. The default case is code `513`, two nodes, path `[0, 1]`, initial logical state `0`, FakeFez, and 128 shots. This deliberately small case is not the production job list.

Run from the repository root. Python used here was **3.13.2**, on an Apple M4 Pro (`Mac16,7`, 48 GiB RAM), macOS arm64. The main packages match the root `uv.lock`: **Qiskit 2.2.3, Aer 0.17.2, IBM Runtime 0.44.0, NumPy 2.4.0, SciPy 1.16.3**. [requirements.txt](requirements.txt) pins all installed packages. Installation reported NumPy 2.4.0 as yanked for a backward compatibility bug; it was retained to match the existing lock for this isolated experiment. The checks in [validation.json](validation.json) passed on these versions. The production Dockerfile uses Python 3.11 and unpinned packages; deployed package versions were not verified.

```sh
BENCH_DIR="$PWD/experiments/aer_noise_benchmark"
mkdir -p "$BENCH_DIR/.cache/uv" "$BENCH_DIR/.tmp"
PYTHONDONTWRITEBYTECODE=1 python3 -m venv "$BENCH_DIR/.venv"
UV_CACHE_DIR="$BENCH_DIR/.cache/uv" TMPDIR="$BENCH_DIR/.tmp" \
  PYTHONDONTWRITEBYTECODE=1 uv pip sync \
  --python "$BENCH_DIR/.venv/bin/python" "$BENCH_DIR/requirements.txt"

# Choose a NEW output directory; prior results are never overwritten.
PYTHONDONTWRITEBYTECODE=1 "$BENCH_DIR/.venv/bin/python" -B \
  "$BENCH_DIR/benchmark.py" --output reproduction --shots 128 --repeats 3
```

The controller allows one worker at a time, 120 seconds per child process, and a persistent **600-second aggregate process wall-time budget**, conservatively including imports, preparation, controls, and failed attempts. `budget.json` is shared across output directories; do not reset it to evade the investigation limit. `--shots` is restricted to 64–256 and `--repeats` to 1–3. Thread environment variables are set before Qiskit/NumPy imports; Aer explicitly receives one thread, one parallel shot, and one parallel experiment. Aer has a 4096 MiB memory setting, not a separate OS memory limit. Peak process RSS is recorded. Do not invoke the internal `--worker`, `--prepare`, or `--controls` modes directly: their process timeout is enforced by the controller.

Each comparison uses one frozen `(compiled circuit, noise model)` pickle for both engines. QPY and readable noise JSON are saved alongside it. Only load the pickles produced locally by this harness. Simulator submission and blocking result retrieval are timed together; Python process startup, noise construction, backend initialization, and transpilation are separately recorded. No circuit is rewritten for stabilizer compatibility. Incompatible cases are skipped; failed runs and timeouts are recorded.

The exact commands used to collect the saved results were:

```sh
PYTHONDONTWRITEBYTECODE=1 experiments/aer_noise_benchmark/.venv/bin/python -B \
  experiments/aer_noise_benchmark/benchmark.py --output results --shots 128 --repeats 1
PYTHONDONTWRITEBYTECODE=1 experiments/aer_noise_benchmark/.venv/bin/python -B \
  experiments/aer_noise_benchmark/benchmark.py --output results --shots 128 \
  --repeats 3 --reuse-prepared
```

Those initial timing repeats used MPS seeds `271828,271829,271830` and stabilizer seeds `314159,314160,314161`. Aer's `seed + shot_index` behavior means the repeated shot streams overlap. The saved summary explicitly excludes repetitions 1 and 2 from statistics, retaining them for timing. It therefore uses **128 independent shots per engine per case**, not 384. The current harness fixes future runs to use `base + 10000*repetition`, with bases `271828` and `314159`, and rejects overlapping intervals from statistical pooling. Seed spacing changes future repeat counts; the recorded first-run counts remain exactly reproducible. Transpiler seed is `1729`; ideal controls use `12345`; the conditional permutation test uses `8675309`. This correction and its effect on the analysis are preserved in the report.

After fixing the analysis, the second command above was run again; it reused all completed attempts and only regenerated the summary. `--reuse-prepared` never retries an attempted simulation or rebuilds its circuit/noise. To reproduce a different fresh comparison use a new output directory.

Verify the archived results and protected files without simulation:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B experiments/aer_noise_benchmark/verify_results.py
PYTHONDONTWRITEBYTECODE=1 experiments/aer_noise_benchmark/.venv/bin/python -B \
  experiments/aer_noise_benchmark/benchmark.py --verify-only
git diff --check
```

`verify_results.py` checks the delivered `results/` dataset, including its documented seed exclusions; it is not a generic verifier for differently sized future datasets. `baseline.json` records the original Git status/diffs and the full protected directory manifest. `integrity_check.json` compares file names, contents, existing untracked files, and Git diffs. No commit, push, deployment, production job, or QPU submission is part of this workflow.

The six narrowly scoped AWS metadata calls and their results are preserved in [aws_readonly_inspection.py.txt](aws_readonly_inspection.py.txt), [aws_inspection.json](aws_inspection.json), and [aws_capacity.json](aws_capacity.json). They used the existing AWS MCP connection for account `241766333838`, matching local profile `default`, and workload region `us-east-2`. The text file is an audit record, not an executable deployment script.
