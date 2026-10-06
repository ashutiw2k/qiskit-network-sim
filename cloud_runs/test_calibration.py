"""Focused checks: python -m unittest cloud_runs.test_calibration."""
import json
from pathlib import Path
import tempfile
import unittest

from qiskit import QuantumCircuit
from qiskit.quantum_info import average_gate_fidelity

from cloud_runs.common import build_calibrated_simulator


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "calibration.json"
        self.basis = ["cz", "id", "rz", "sx", "x"]
        gates = []
        for q in range(3):
            for name in self.basis[1:]:
                r = 0 if name == "rz" else (1 if q == 1 else 0.001 * (q + 1))
                gates.append({"gate": name, "qubits": [q],
                              "parameters": [{"name": "gate_error", "value": r}]})
        for pair, r in [([0, 1], 0.02), ([1, 0], 0.02), ([0, 2], 0.03),
                        ([2, 0], 0.03), ([1, 2], 1)]:
            gates.append({"gate": "cz", "qubits": pair,
                          "parameters": [{"name": "gate_error", "value": r}]})
        self.payload = {"requested_date_utc": "2026-10-06", "properties": {
            "backend_name": "ibm_fez", "last_update_date": "2026-10-06T12:00:00Z",
            "qubits": [[], [], []], "gates": gates}}
        self.path.write_text(json.dumps(self.payload))

    def circuit(self, width=5):
        circuit = QuantumCircuit(width, 1)
        circuit.sx(1)
        circuit.x(4)
        circuit.rz(0.3, 1)
        circuit.cz(0, 1)
        circuit.cz(1, 0)
        circuit.cz(1, 4)  # Not a physical calibration edge.
        circuit.measure(1, 0)
        return circuit

    def test_channel_infidelity_coverage_and_execution(self):
        circuit = self.circuit()
        original = circuit.copy()
        simulator, meta = build_calibrated_simulator(self.path, circuit, self.basis)
        self.assertEqual(circuit, original)
        self.assertEqual(meta["valid_source_qubits"], [0, 2])
        self.assertEqual(len(meta["excluded_entries"]), 4)
        model = simulator.options.noise_model
        self.assertFalse(model._default_quantum_errors)
        self.assertFalse(model._local_readout_errors)
        self.assertIsNone(model._default_readout_error)
        self.assertFalse(model._custom_noise_passes)
        for assignment in meta["assignments"]:
            gate, pair = assignment["gate"], tuple(assignment["qubits"])
            if assignment["reported_error"] == 0:
                self.assertNotIn(pair, model._local_quantum_errors.get(gate, {}))
            else:
                channel = model._local_quantum_errors[gate][pair]
                self.assertAlmostEqual(1 - average_gate_fidelity(channel), assignment["reported_error"])
        cz = {tuple(a["qubits"]): a for a in meta["assignments"] if a["gate"] == "cz"}
        self.assertEqual(set(cz), {(0, 1), (1, 0), (1, 4)})
        self.assertEqual(cz[0, 1]["lambda"], cz[1, 0]["lambda"])
        self.assertGreater(len({a["lambda"] for a in cz.values()}), 1)
        result = simulator.run(circuit, shots=32, seed_simulator=37).result()
        self.assertTrue(result.success)
        self.assertEqual(sum(result.get_counts().values()), 32)
        self.assertEqual(result.results[0].metadata["method"], "matrix_product_state")
        self.assertEqual(result.results[0].metadata["parallel_state_update"], 1)

    def test_assignment_stays_fixed_when_rates_or_width_change(self):
        _, before = build_calibrated_simulator(self.path, self.circuit(), self.basis)
        for gate in self.payload["properties"]["gates"]:
            r = gate["parameters"][0]["value"]
            if 0 < r < 1:
                gate["parameters"][0]["value"] = r * 2
        self.path.write_text(json.dumps(self.payload))
        _, after = build_calibrated_simulator(self.path, self.circuit(9), self.basis)
        for a, b in zip(before["assignments"], after["assignments"]):
            self.assertEqual(a["source_qubits"], b["source_qubits"])
            self.assertEqual(b["reported_error"], a["reported_error"] * 2)

    def test_missing_two_qubit_calibration_fails(self):
        self.payload["properties"]["gates"] = [g for g in self.payload["properties"]["gates"]
                                                if g["gate"] != "cz"]
        self.path.write_text(json.dumps(self.payload))
        with self.assertRaisesRegex(ValueError, "2Q pool"):
            build_calibrated_simulator(self.path, self.circuit(), self.basis)

    def test_uncompiled_gate_fails(self):
        circuit = self.circuit()
        circuit.h(0)
        with self.assertRaisesRegex(ValueError, "outside calibrated basis"):
            build_calibrated_simulator(self.path, circuit, self.basis)


if __name__ == "__main__":
    unittest.main()
