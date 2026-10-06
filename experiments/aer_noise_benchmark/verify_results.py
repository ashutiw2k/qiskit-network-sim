#!/usr/bin/env python3
"""Verify saved experiment evidence without submitting any simulations."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
prepared = json.loads((OUT / "prepared.json").read_text())
summary = json.loads((OUT / "summary.json").read_text())
checks = {}
all_runs = []
for case, info in prepared["cases"].items():
    payload = OUT / f"{case}.pickle"
    assert hashlib.sha256(payload.read_bytes()).hexdigest() == info["payload_sha256"]
    runs = [json.loads(p.read_text()) for p in sorted(OUT.glob(f"{case}.*.*.json"))]
    assert len(runs) == 6
    for run in runs:
        assert run["success"] and run["shots"] == 128
        assert sum(run["raw_counts"].values()) == 128
        assert run["histogram_0000_through_1111"] == [run["raw_counts"].get(f"{i:04b}", 0) for i in range(16)]
        for key in ["payload_sha256", "qpy_sha256", "noise_sha256"]:
            assert run[key] == info[key]
        assert run["aer_metadata"]["method"] == run["method"]
        assert run["aer_metadata"]["parallel_state_update"] == 1
        assert run["aer_metadata"]["parallel_shots"] == 1
        assert run["aer_metadata"]["active_input_qubits"] == info["circuit"]["active_qubits"]
        all_runs.append(run)
    assert info["compatibility"]["eligible"] and not info["compatibility"]["angles_modified"]
    assert info["compatibility"]["max_rz_multiple_residual"] < 1e-10
    checks[case + "_same_artifacts_threads_counts_and_runtime_method"] = True
    # Archived repeats used adjacent seeds: the summary must not pool them.
    comp = summary["comparisons"][case]
    assert set(comp["independent_shots_per_engine"].values()) == {128}
    assert all(v == [1, 2] for v in comp["repetitions_excluded_from_distribution_test"].values())

alternative = prepared["cases"]["B_calibration_depolarizing_readout"]["coverage"]
assert alternative["strict"] and not alternative["failures"]
assert alternative["two_qubit_occurrences_without_channel"] == 0
assert alternative["two_qubit_occurrences_outside_hardware_target"] == 0
for row in alternative["rows"]:
    if row["operation"] in {"sx", "cz"}:
        assert abs(row["model_average_infidelity"] - row["backend_gate_or_measure_error"]) < 1e-10
        assert row["factory_channel_max_abs_difference"] < 1e-10
checks["calibration_infidelities_and_depolarizing_conversion"] = True
checks["all_routed_two_qubit_gates_have_calibrated_channels"] = True
for row in json.loads((OUT / "readout_factory_audit.json").read_text()):
    matrix = row["properties_factory_matrix"]
    assert matrix[0][1] == row["prob_meas1_prep0"]
    assert matrix[1][0] == row["prob_meas0_prep1"]
checks["asymmetric_readout_calibrations_preserved"] = True
controls = json.loads((OUT / "ideal_controls.json").read_text())
assert controls["all_zero_syndrome_check_passed"] and controls["classical_routing_map_check_passed"]
checks["ideal_syndrome_and_routed_classical_bit_mapping"] = True
thermal = json.loads((OUT / "thermal_audit.json").read_text())
assert not thermal["compatibility"]["eligible"]
assert "kraus" in thermal["compatibility"]["noise_instruction_names"]
assert all(prepared["negative_controls"].values())
checks["thermal_and_nonclifford_negative_controls_rejected"] = True
ledger = json.loads((HERE / "budget.json").read_text())
charged = sum(p["charged_seconds"] for p in ledger["processes"])
assert charged < 600 and all(p["timeout_seconds"] <= 120 for p in ledger["processes"])
assert all(p["status"] == "success" for p in ledger["processes"])
checks["runtime_limits_and_successful_processes"] = True
checks["overlapping_seed_repeats_excluded_from_statistics"] = True
result = {"checks": checks, "all_passed": all(checks.values()), "noisy_runs": len(all_runs),
          "total_noisy_shots": sum(r["shots"] for r in all_runs),
          "simulation_wall_seconds": sum(r["simulation_wall_seconds"] for r in all_runs),
          "charged_process_wall_seconds_including_preparation": charged}
(HERE / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
