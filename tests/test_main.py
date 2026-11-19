"""Tests for MeasurementBasedQC-Lab. Every test grades a computed
number against a closed form or an independent implementation in
main.py - branch enumeration against direct gate application."""
import itertools
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main as mb

TOL = 1e-9


def test_prng_deterministic():
    a, b = mb.SplitMix64(mb.SEED), mb.SplitMix64(mb.SEED)
    assert [a.next_u64() for _ in range(16)] == [b.next_u64() for _ in range(16)]


def test_j_gate_zero_is_hadamard():
    assert mb.mat_dev(mb.j_gate(0.0), mb.H_MAT) < 1e-12


def test_cluster_stabilizers_chain():
    for n in range(2, 7):
        edges = mb.chain_edges(n)
        st = mb.build_cluster(n, edges)
        for a in range(n):
            assert mb.stabilizer_deviation(st, n, edges, a) < TOL


def test_cluster_stabilizers_patches():
    for rows, cols in ((2, 3), (3, 3)):
        n = rows * cols
        edges = mb.grid_edges(rows, cols)
        st = mb.build_cluster(n, edges)
        for a in range(n):
            assert mb.stabilizer_deviation(st, n, edges, a) < TOL


def test_cluster_marginals_maximally_mixed():
    st = mb.build_cluster(4, mb.chain_edges(4))
    for q in range(4):
        assert abs(mb.reduced_purity(st, 4, q) - 0.5) < TOL


def test_wire_two_steps_is_identity_all_branches():
    grid = mb.input_grid()
    for branch in itertools.product([0, 1], repeat=2):
        for psi in grid:
            r = mb.run_pattern_1q([0.0, 0.0], psi, branch)
            corrected = mb.mv(mb.PAULIS[r["frame"]], r["out"])
            assert mb.dev_phase(corrected, list(psi)) < TOL


def test_wire_one_step_is_hadamard():
    for branch in itertools.product([0, 1], repeat=1):
        for psi in mb.input_grid():
            r = mb.run_pattern_1q([0.0], psi, branch)
            corrected = mb.mv(mb.PAULIS[r["frame"]], r["out"])
            assert mb.dev_phase(corrected, mb.mv(mb.H_MAT, list(psi))) < TOL


def test_branch_probabilities_uniform():
    r = mb.run_pattern_1q([0.3, 1.1, -0.6, 0.0], mb.input_grid()[6], (1, 0, 1, 1))
    assert all(abs(p - 0.5) < TOL for p in r["probs"])


def test_rz_pattern_matches_direct():
    for theta in (0.7, -1.3, math.pi / 3.0):
        rep = mb.pattern_report([theta, 0.0], mb.rz(theta))
        assert rep["max_corrected_dev"] < TOL
        assert rep["frame_affine"]


def test_rx_pattern_matches_direct():
    rep = mb.pattern_report([0.0, -2.0], mb.rx(-2.0))
    assert rep["max_corrected_dev"] < TOL


def test_euler_exact_pattern():
    target = mb.mm(mb.rz(-0.6), mb.mm(mb.rx(1.1), mb.rz(0.3)))
    rep = mb.pattern_report([0.3, 1.1, -0.6, 0.0], target)
    assert rep["max_corrected_dev"] < TOL
    assert rep["max_frame_dev"] < TOL
    assert rep["frame_affine"]


def test_cz_patch_target_and_frames():
    rep = mb.cz_report()
    assert rep["max_corrected_dev"] < TOL
    assert rep["max_prob_dev_from_half"] < TOL
    assert rep["frame_affine"]


def test_cz_patch_sandwich_recovers_cz():
    hh = mb.kron2(mb.H_MAT, mb.H_MAT)
    assert mb.mat_dev(mb.mm(hh, mb.mm(mb.PATCH_TARGET, hh)), mb.CZ_MAT) < 1e-12


def test_cz_patch_is_not_bare_cz():
    assert mb.mat_dev(mb.PATCH_TARGET, mb.CZ_MAT) > 0.5


def test_cz_patch_maximally_entangling():
    out = mb.mv(mb.PATCH_TARGET, [1.0, 0j, 0j, 0j])
    assert abs(mb.concurrence(out) - 1.0) < TOL


def test_frame_worked_example():
    ex = mb.frame_report()["worked_example"]
    assert ex["uncorrected_dev"] > 0.1
    assert ex["corrected_dev"] < TOL


def test_classifier_scenarios():
    rep = mb.classifier_report()
    assert rep["cluster_3x3_no_measurements"] == "resource-state"
    assert rep["hadamard_pattern"] == "single-step-gate"
    assert rep["wire_4_steps"] == "wire"
    assert rep["rz_pattern"] == "rotation-gate"
    assert rep["cz_patch"] == "entangling-gate"


def test_classifier_matches_model_on_grid():
    for features, label in mb.TRAINING_GRID:
        assert mb.classify_pattern(*features) == label


def test_checks_all_pass():
    checks = mb.run_checks()
    assert all(ok for _, ok in checks), [n for n, ok in checks if not ok]


def test_hold_gates():
    assert len(mb.HOLD_GATES) == 14
    assert mb.gate("real_hardware_control") == "HOLD"
    assert mb.gate("blind_computing_service_claim") == "HOLD"
    assert mb.gate("run_simulation") == "PROCEED"


def test_seats_cannot_override():
    brains = mb.brains_report()
    assert brains["decider"]["can_override_hold"] is False
    assert brains["advisor"]["can_override_hold"] is False
    assert brains["flow"]["rendered"] is False
    assert brains["flow"]["live"] == 0


def test_hold_demo_exit_code():
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "main.py"),
         "hold-demo"],
        capture_output=True, text=True)
    assert proc.returncode == 2
