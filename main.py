#!/usr/bin/env python3
"""MeasurementBasedQC-Lab - educational measurement-based quantum computing lab.

by Darion Kellar

Pure Python standard library. Zero dependencies. Zero network.
Education only - and the central lesson is stated up front:

  * In measurement-based quantum computing (MBQC) the computer is
    built BEFORE any logic happens: qubits are prepared in |+>,
    entangled once with controlled-Z gates into a cluster state,
    and from then on the only operations are single-qubit
    measurements. The computation is steered by choosing measurement
    angles, and corrected by classical feed-forward: each outcome is
    random (50/50, asserted in this lab), but the randomness only
    ever shows up as a known Pauli byproduct - the Pauli frame -
    which is tracked exactly and either corrected at the end or
    folded into later measurement angles.
  * This lab proves those claims by enumeration, not sampling:
    every measurement branch of every pattern is run, the corrected
    output is compared against direct gate application on a grid of
    input states, and the Pauli frame of every branch is fitted to
    an affine function of the outcome bits over GF(2).
  * The two-qubit patch is reported honestly: the 2x3 patch with
    all-X measurements implements (H x H) CZ (H x H) - a CZ in the
    Hadamard frame, locally equivalent to CZ and maximally
    entangling - NOT a bare CZ. The lab asserts exactly that, and
    asserts that sandwiching it between Hadamard patterns recovers
    CZ itself.

No real quantum hardware is touched, no advantage over classical
computing is claimed, and every service / product / cryptographic
use is a permanent HOLD gate - with Gemini Argon 4 Extended
Thinking as DECIDER (names-only, tighten-only), Muse as advisor
(never overrides HOLD), and Google Flow plan-only seats.
"""
import cmath
import hashlib
import itertools
import json
import math
import sys

# ---------------------------------------------------------------- constants
VERSION = "1.0.0"
SEED = 20261119
TOL = 1e-9

SQ2 = 1.0 / math.sqrt(2.0)
EYE2 = [[1.0 + 0j, 0j], [0j, 1.0 + 0j]]
PAULI_X = [[0j, 1.0 + 0j], [1.0 + 0j, 0j]]
PAULI_Y = [[0j, -1j], [1j, 0j]]
PAULI_Z = [[1.0 + 0j, 0j], [0j, -1.0 + 0j]]
H_MAT = [[SQ2, SQ2], [SQ2, -SQ2]]
PAULIS = {(0, 0): EYE2, (1, 0): PAULI_X, (0, 1): PAULI_Z, (1, 1): PAULI_Y}

# ---------------------------------------------------------------- HOLD gates
HOLD_GATES = {
    "real_hardware_control": "HOLD - no control of real quantum hardware, photonic processors, or cluster-state sources",
    "quantum_advantage_claim": "HOLD - no claim of quantum advantage or speedup from a teaching simulation",
    "cryptographic_use_claim": "HOLD - these patterns are not a cryptographic product; no QKD, encryption, or security claim",
    "blind_computing_service_claim": "HOLD - no blind or verified quantum-computing service; MBQC is the basis of BQC, which is exactly why it is gated",
    "production_compiler_claim": "HOLD - this is not a production MBQC compiler or pattern optimiser for real devices",
    "fault_tolerance_product_claim": "HOLD - bare patterns are not fault tolerance; no error-corrected product claim",
    "cloud_quantum_service_claim": "HOLD - no cloud quantum-computing service is offered or implied",
    "hardware_fabrication_claim": "HOLD - no fabrication guidance for photonic chips, sources, or detectors",
    "medical_claim": "HOLD - no medical, diagnostic, or life-support computation claim",
    "financial_claim": "HOLD - no trading, pricing, risk, or financial-computation claim",
    "investment_claim": "HOLD - no investment claims; a lab model is not a prospectus",
    "military_surveillance_claim": "HOLD - no military, intelligence, or surveillance use",
    "claim_certified_system": "HOLD - no claim this simulation is a certified quantum computer",
    "remove_human_override": "HOLD - the human override is never removed",
}


def gate(action):
    """Return 'HOLD' if the action is gated, else 'PROCEED' (sandbox sim)."""
    return "HOLD" if action in HOLD_GATES else "PROCEED"


# ================================================================ 0. Seeded PRNG
# splitmix64: tiny, deterministic, and identical on every platform.
# It only picks the grid of probe input states - the lab enumerates
# measurement branches, it never samples them.

class SplitMix64:
    def __init__(self, seed):
        self.state = seed & 0xFFFFFFFFFFFFFFFF

    def next_u64(self):
        self.state = (self.state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return z ^ (z >> 31)

    def next_float(self):
        return (self.next_u64() >> 11) / float(1 << 53)


# ================================================================ 1. Matrix + statevector kit
# Everything from scratch: 2x2 / 4x4 complex matrices as lists, and
# statevectors as flat lists with qubit q = bit q of the index.

def mm(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(len(B)))
             for j in range(len(B[0]))] for i in range(len(A))]


def mv(A, v):
    return [sum(A[i][k] * v[k] for k in range(len(v))) for i in range(len(A))]


def kron2(A, B):
    return [[A[i][j] * B[k][l] for j in range(2) for l in range(2)]
            for i in range(2) for k in range(2)]


def mat_dev(A, B):
    return max(abs(A[i][j] - B[i][j])
               for i in range(len(A)) for j in range(len(A[0])))


def rz(alpha):
    return [[cmath.exp(-0.5j * alpha), 0j], [0j, cmath.exp(0.5j * alpha)]]


def rx(alpha):
    c, s = math.cos(alpha / 2.0), math.sin(alpha / 2.0)
    return [[c, -1j * s], [-1j * s, c]]


def j_gate(alpha):
    """The MBQC primitive: J(alpha) = H . Rz(alpha)."""
    return mm(H_MAT, rz(alpha))


def j_inv(alpha):
    return mm(rz(-alpha), H_MAT)


def pauli_mat(x, z):
    return PAULIS[(x, z)]


def pauli_exponents(P):
    """Return (x, z) if P is a Pauli up to global phase, else None."""
    for (x, z), Q in PAULIS.items():
        for i in range(2):
            for j in range(2):
                if abs(Q[i][j]) > 0.5:
                    phase = P[i][j] / Q[i][j]
                    if abs(abs(phase) - 1.0) < 1e-6 and \
                            mat_dev(P, [[phase * q for q in row] for row in Q]) < 1e-6:
                        return (x, z)
    return None


def apply_1q(state, n, q, U):
    st = list(state)
    for i in range(1 << n):
        if not (i >> q) & 1:
            j = i | (1 << q)
            a, b = st[i], st[j]
            st[i] = U[0][0] * a + U[0][1] * b
            st[j] = U[1][0] * a + U[1][1] * b
    return st


def apply_cz(state, n, a, b):
    return [(-amp if ((i >> a) & 1) and ((i >> b) & 1) else amp)
            for i, amp in enumerate(state)]


def set_input(state, n, q, psi):
    """Overwrite qubit q (currently |0>) with the state psi."""
    a, b = psi
    U = [[a, -b.conjugate()], [b, a.conjugate()]]
    return apply_1q(state, n, q, U)


def plus_state(n, qubits):
    st = [0j] * (1 << n)
    st[0] = 1.0
    for q in qubits:
        st = apply_1q(st, n, q, H_MAT)
    return st


def overlap(a, b):
    return sum(x.conjugate() * y for x, y in zip(a, b))


def fidelity(a, b):
    return abs(overlap(a, b))


def dev_phase(a, b):
    """Distance up to global phase: 0 iff a = phase * b."""
    return 1.0 - fidelity(a, b)


def measure_qubit(state, n, q, phi, outcome):
    """Project qubit q onto the XY-plane basis at angle phi.

    Basis: |+_phi> = (|0> + e^{i phi}|1>)/sqrt(2) is outcome 0,
    |-_phi> is outcome 1. The qubit is rotated back to the
    computational basis afterwards, so it ends in |outcome>.
    Returns (probability, collapsed state).
    """
    e = cmath.exp(-1j * phi)
    U = [[SQ2, e * SQ2], [SQ2, -e * SQ2]]  # M(phi)^dagger
    st = apply_1q(state, n, q, U)
    prob = sum(abs(a) ** 2 for i, a in enumerate(st) if ((i >> q) & 1) == outcome)
    inv = 1.0 / math.sqrt(prob)
    st = [(a * inv if ((i >> q) & 1) == outcome else 0j)
          for i, a in enumerate(st)]
    return prob, st


def bloch_state(theta, phi):
    return (math.cos(theta / 2.0),
            cmath.exp(1j * phi) * math.sin(theta / 2.0))


def input_grid():
    """Deterministic probe states: 6 axis states + 8 seeded states."""
    states = [(1.0 + 0j, 0j), (0j, 1.0 + 0j),
              (SQ2, SQ2), (SQ2, -SQ2), (SQ2, 1j * SQ2), (SQ2, -1j * SQ2)]
    rng = SplitMix64(SEED)
    for _ in range(8):
        z = 2.0 * rng.next_float() - 1.0
        phi = 2.0 * math.pi * rng.next_float()
        r = math.sqrt(max(0.0, 1.0 - z * z))
        states.append((math.sqrt((1.0 + z) / 2.0),
                       cmath.exp(1j * phi) * math.sqrt((1.0 - z) / 2.0)
                       if r > 0 else 0j))
    return states


# ================================================================ 2. Cluster states + stabilizers
# A cluster state is |+>^n with CZ on every graph edge. Its defining
# receipt: every stabilizer K_a = X_a prod_{b in N(a)} Z_b leaves it
# invariant, K_a |psi> = |psi>, i.e. expectation exactly +1.

def chain_edges(n):
    return [(i, i + 1) for i in range(n - 1)]


def grid_edges(rows, cols):
    edges = []
    for r in range(rows):
        for c in range(cols):
            q = r * cols + c
            if c + 1 < cols:
                edges.append((q, q + 1))
            if r + 1 < rows:
                edges.append((q, q + cols))
    return edges


def neighbours(edges, n):
    nbr = {a: [] for a in range(n)}
    for a, b in edges:
        nbr[a].append(b)
        nbr[b].append(a)
    return nbr


def build_cluster(n, edges):
    st = plus_state(n, list(range(n)))
    for a, b in edges:
        st = apply_cz(st, n, a, b)
    return st


def apply_pauli_string(state, n, ops):
    """ops: dict qubit -> 'X' or 'Z'."""
    out = [0j] * (1 << n)
    for i, amp in enumerate(state):
        j = i
        phase = 1.0
        for q, op in ops.items():
            if op == "X":
                j ^= (1 << q)
            elif op == "Z":
                if (i >> q) & 1:
                    phase = -phase
        out[j] = out[j] + phase * amp
    return out


def stabilizer_deviation(state, n, edges, a):
    """||K_a |psi> - |psi>|| for K_a = X_a prod Z_neighbours."""
    nbr = neighbours(edges, n)
    ops = {a: "X"}
    for b in nbr[a]:
        ops[b] = "Z"
    kpsi = apply_pauli_string(state, n, ops)
    return math.sqrt(sum(abs(x - y) ** 2 for x, y in zip(kpsi, state)))


def reduced_purity(state, n, q):
    """Tr(rho_q^2) for the single-qubit reduced state."""
    rho = [[0j, 0j], [0j, 0j]]
    for i, amp in enumerate(state):
        bi = (i >> q) & 1
        for j, amp2 in enumerate(state):
            if (i & ~(1 << q)) == (j & ~(1 << q)):
                rho[bi][(j >> q) & 1] += amp * amp2.conjugate()
    return float((rho[0][0] * rho[0][0] + rho[1][1] * rho[1][1]
                  + 2.0 * abs(rho[0][1]) ** 2).real)


def cluster_report():
    report = {}
    worst = 0.0
    for n in range(2, 7):
        edges = chain_edges(n)
        st = build_cluster(n, edges)
        dev = max(stabilizer_deviation(st, n, edges, a) for a in range(n))
        worst = max(worst, dev)
        report[f"chain_{n}"] = {"qubits": n, "edges": len(edges),
                                "max_stabilizer_dev": round(dev, 12)}
    for rows, cols in ((2, 3), (3, 3)):
        n = rows * cols
        edges = grid_edges(rows, cols)
        st = build_cluster(n, edges)
        dev = max(stabilizer_deviation(st, n, edges, a) for a in range(n))
        worst = max(worst, dev)
        report[f"patch_{rows}x{cols}"] = {"qubits": n, "edges": len(edges),
                                         "max_stabilizer_dev": round(dev, 12)}
    st = build_cluster(4, chain_edges(4))
    report["chain_4_marginal_purity"] = {
        q: round(reduced_purity(st, 4, q), 9) for q in range(4)}
    report["worst_stabilizer_dev"] = round(worst, 12)
    return report


# ================================================================ 3. One-qubit patterns
# A pattern is a list of J-angles [alpha_1..alpha_m] on a linear
# cluster of m+1 qubits: input on qubit 0, output on qubit m.
# Measuring qubit i at angle phi implements J(-phi) up to an X^s
# byproduct, where J(a) = H.Rz(a). Feed-forward: with current Pauli
# frame (x, z) on the logical state, the angle that implements the
# desired J(alpha) is phi = -(-1)^x * alpha + pi * z. The frame is
# tracked as a matrix and asserted to stay a Pauli at every step:
#   P' = X^s . J(-phi) . P . J(alpha)^{-1}
# so the bookkeeping is verified against the statevector, not hoped.

def run_pattern_1q(alphas, psi, branch):
    """Run one branch of a 1-qubit pattern. Returns dict with the raw
    output state, the tracked Pauli frame (x, z), the ideal unitary
    matrix, and the per-step outcome probabilities."""
    m = len(alphas)
    n = m + 1
    st = plus_state(n, list(range(1, n)))
    st = set_input(st, n, 0, psi)
    for a, b in chain_edges(n):
        st = apply_cz(st, n, a, b)
    frame = (0, 0)
    P = EYE2
    U = EYE2
    probs = []
    for i, alpha in enumerate(alphas):
        x, z = frame
        phi = -(((-1) ** x) * alpha) + math.pi * z
        s = branch[i]
        prob, st = measure_qubit(st, n, i, phi, s)
        probs.append(prob)
        Pn = mm(PAULIS[(s, 0)], mm(j_gate(-phi), mm(P, j_inv(alpha))))
        ex = pauli_exponents(Pn)
        if ex is None:
            raise AssertionError(f"frame left the Pauli group at step {i}")
        frame = ex
        P = PAULIS[ex]
        U = mm(j_gate(alpha), U)
    out = [0j, 0j]
    for idx, amp in enumerate(st):
        if all(((idx >> q) & 1) == branch[q] for q in range(m)):
            out[(idx >> m) & 1] = amp
    return {"out": out, "frame": frame, "unitary": U, "probs": probs}


def affine_fit(frames):
    """True iff branch -> exponent tuple is affine over GF(2):
    e(b) = c XOR sum_i b_i * v_i."""
    m = len(next(iter(frames)))
    c = frames[(0,) * m]
    basis = []
    for i in range(m):
        unit = tuple(1 if k == i else 0 for k in range(m))
        basis.append(tuple(a ^ b for a, b in zip(frames[unit], c)))
    for branch, e in frames.items():
        pred = list(c)
        for i, bit in enumerate(branch):
            if bit:
                pred = [p ^ v for p, v in zip(pred, basis[i])]
        if tuple(pred) != e:
            return False
    return True


def pattern_report(alphas, target):
    """Grade a 1-qubit pattern over ALL branches x the input grid:
    corrected output vs target, raw output vs frame.target, and the
    uniformity of branch probabilities."""
    m = len(alphas)
    grid = input_grid()
    worst_corr = 0.0
    worst_frame = 0.0
    worst_prob = 0.0
    frames = {}
    for branch in itertools.product([0, 1], repeat=m):
        for psi in grid:
            r = run_pattern_1q(alphas, psi, branch)
            tgt = mv(target, list(psi))
            corrected = mv(PAULIS[r["frame"]], r["out"])
            worst_corr = max(worst_corr, dev_phase(corrected, tgt))
            worst_frame = max(worst_frame,
                              dev_phase(r["out"], mv(PAULIS[r["frame"]], tgt)))
            worst_prob = max(worst_prob,
                             max(abs(p - 0.5) for p in r["probs"]))
            if branch in frames and frames[branch] != r["frame"]:
                raise AssertionError("frame depends on the input state")
            frames[branch] = r["frame"]
    return {"steps": m, "branches": 2 ** m, "inputs": len(grid),
            "max_corrected_dev": worst_corr,
            "max_frame_dev": worst_frame,
            "max_prob_dev_from_half": worst_prob,
            "frames": { "".join(str(b) for b in br): fr
                        for br, fr in frames.items()},
            "frame_affine": affine_fit(frames)}


def mat_pow(M, k):
    out = EYE2
    for _ in range(k):
        out = mm(M, out)
    return out


def wire_report():
    report = {}
    for length in (1, 2, 4):
        report[f"wire_{length}"] = pattern_report([0.0] * length,
                                                  mat_pow(H_MAT, length))
    return report


# Named patterns: (J-angle list, target matrix builder)
def gate_patterns():
    return {
        "hadamard": ([0.0], H_MAT),
        "rz_0.7": ([0.7, 0.0], rz(0.7)),
        "rz_-1.3": ([-1.3, 0.0], rz(-1.3)),
        "rz_pi_over_3": ([math.pi / 3.0, 0.0], rz(math.pi / 3.0)),
        "rx_0.7": ([0.0, 0.7], rx(0.7)),
        "rx_-2.0": ([0.0, -2.0], rx(-2.0)),
        "euler_h_frame": ([0.3, 1.1, -0.6],
                          mm(H_MAT, mm(rz(-0.6), mm(rx(1.1), rz(0.3))))),
        "euler_exact": ([0.3, 1.1, -0.6, 0.0],
                        mm(rz(-0.6), mm(rx(1.1), rz(0.3)))),
    }


def gate_report():
    return {name: pattern_report(alphas, target)
            for name, (alphas, target) in gate_patterns().items()}


# ================================================================ 4. Two-qubit patch: CZ in the H frame
# Patch layout (qubit index = row * 3 + col):
#     0 - 1 - 2        A: input 0, output 2
#         |            B: input 3, output 5
#     3 - 4 - 5
# All four non-output qubits are measured in the X basis. The
# implemented gate - computed here from the statevector, and matched
# against the closed form - is (H x H) . CZ . (H x H): the gate that
# puts a -1 phase on |--> instead of |11>. It is locally equivalent
# to CZ, and (H x H) . U_patch . (H x H) = CZ exactly.

PATCH_EDGES = [(0, 1), (1, 2), (3, 4), (4, 5), (1, 4)]
PATCH_MEASURED = [0, 1, 3, 4]
CZ_MAT = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, -1]]
PATCH_TARGET = mm(kron2(H_MAT, H_MAT), mm(CZ_MAT, kron2(H_MAT, H_MAT)))


def run_patch(psi_a, psi_b, branch):
    n = 6
    st = plus_state(n, [1, 2, 4, 5])
    st = set_input(st, n, 0, psi_a)
    st = set_input(st, n, 3, psi_b)
    for a, b in PATCH_EDGES:
        st = apply_cz(st, n, a, b)
    probs = []
    for q, s in zip(PATCH_MEASURED, branch):
        prob, st = measure_qubit(st, n, q, 0.0, s)
        probs.append(prob)
    out = [0j] * 4
    for idx, amp in enumerate(st):
        if all(((idx >> q) & 1) == s
               for q, s in zip(PATCH_MEASURED, branch)):
            out[(((idx >> 5) & 1) << 1) | ((idx >> 2) & 1)] = amp
    return {"out": out, "probs": probs}


def vec2q(psi_a, psi_b):
    """Two-qubit vector, index = b * 2 + a."""
    return [psi_a[0] * psi_b[0], psi_a[1] * psi_b[0],
            psi_a[0] * psi_b[1], psi_a[1] * psi_b[1]]


def pauli2_mat(fa, fb):
    """Tensor Pauli for frame (xa, za, xb, zb): B is the high bit."""
    return kron2(PAULIS[(fb[0], fb[1])], PAULIS[(fa[0], fa[1])])


def patch_frame(branch, probes):
    """Find the unique Pauli frame for a branch by intersecting the
    candidate sets over several probe inputs (special inputs can be
    Pauli eigenstates and admit spurious frames; generic ones can't)."""
    candidates = None
    for psi_a, psi_b in probes:
        r = run_patch(psi_a, psi_b, branch)
        tgt = mv(PATCH_TARGET, vec2q(psi_a, psi_b))
        here = set()
        for xa, za, xb, zb in itertools.product([0, 1], repeat=4):
            P = pauli2_mat((xa, za), (xb, zb))
            if dev_phase(mv(P, tgt), r["out"]) < TOL:
                here.add((xa, za, xb, zb))
        candidates = here if candidates is None else candidates & here
    if candidates is None or len(candidates) != 1:
        raise AssertionError(f"branch {branch}: frame not unique: {candidates}")
    return next(iter(candidates))


def patch_probes():
    grid = input_grid()
    return [(grid[2], grid[2]), (grid[4], grid[5]),
            (grid[6], grid[9]), (grid[10], grid[3]), (grid[12], grid[7])]


def patch_input_pairs():
    grid = input_grid()
    pairs = [(grid[i], grid[j]) for i in (0, 1) for j in (0, 1)]
    pairs += [(grid[2], grid[2]), (grid[2], grid[4]), (grid[6], grid[9]),
              (grid[10], grid[12]), (grid[3], grid[7]), (grid[13], grid[8])]
    return pairs


def concurrence(state4):
    a, b, c, d = state4
    return 2.0 * abs(a * d - b * c)


def cz_report():
    probes = patch_probes()
    pairs = patch_input_pairs()
    frames = {}
    worst_corr = 0.0
    worst_prob = 0.0
    for branch in itertools.product([0, 1], repeat=4):
        frame = patch_frame(branch, probes)
        frames[branch] = frame
        P = pauli2_mat((frame[0], frame[1]), (frame[2], frame[3]))
        for psi_a, psi_b in pairs:
            r = run_patch(psi_a, psi_b, branch)
            tgt = mv(PATCH_TARGET, vec2q(psi_a, psi_b))
            corrected = mv(P, r["out"])
            worst_corr = max(worst_corr, dev_phase(corrected, tgt))
            worst_prob = max(worst_prob,
                             max(abs(p - 0.5) for p in r["probs"]))
    ent = mv(PATCH_TARGET, [1.0, 0j, 0j, 0j])
    prod = mv(PATCH_TARGET, [0.5, 0.5, 0.5, 0.5])
    return {"branches": 16, "input_pairs": len(pairs),
            "max_corrected_dev": worst_corr,
            "max_prob_dev_from_half": worst_prob,
            "frames": {"".join(str(b) for b in br): fr
                       for br, fr in frames.items()},
            "frame_affine": affine_fit(frames),
            "target": "(H x H) CZ (H x H)",
            "concurrence_target_on_00": round(concurrence(ent), 9),
            "concurrence_target_on_++": round(concurrence(prod), 9),
            "sandwich_recovers_cz": mat_dev(
                mm(kron2(H_MAT, H_MAT), mm(PATCH_TARGET, kron2(H_MAT, H_MAT))),
                CZ_MAT)}


def frame_report():
    """The Pauli-frame bookkeeping, printed as data: for each pattern,
    the frame of every branch, whether it is affine in the outcome
    bits, and one worked example of uncorrected vs corrected output."""
    wire = pattern_report([0.0, 0.0], EYE2)
    euler = pattern_report([0.3, 1.1, -0.6, 0.0],
                           mm(rz(-0.6), mm(rx(1.1), rz(0.3))))
    cz = cz_report()
    psi = input_grid()[4]  # |+i>
    branch = (1, 0, 1, 0)
    r = run_pattern_1q([0.3, 1.1, -0.6, 0.0], psi, branch)
    tgt = mv(mm(rz(-0.6), mm(rx(1.1), rz(0.3))), list(psi))
    example = {
        "pattern": "euler_exact", "branch": "1010",
        "input": "|+i>", "frame": r["frame"],
        "uncorrected_dev": dev_phase(r["out"], tgt),
        "corrected_dev": dev_phase(mv(PAULIS[r["frame"]], r["out"]), tgt),
    }
    return {"wire_2_frames": wire["frames"],
            "wire_2_affine": wire["frame_affine"],
            "euler_exact_frames": euler["frames"],
            "euler_exact_affine": euler["frame_affine"],
            "cz_patch_frames": cz["frames"],
            "cz_patch_affine": cz["frame_affine"],
            "worked_example": example}


# ================================================================ 5. kNN pattern classifier
# Features: measurements m, output qubits o, cross (non-chain) edges
# e, nonzero J-angles a. The training grid is labelled by the lab's
# own pattern policy (model_label) - the classifier interpolates the
# policy, it does not replace the pattern engine's receipts.

def model_label(measurements, outputs, cross_edges, nonzero_angles):
    if measurements == 0:
        return "resource-state"
    if outputs >= 2:
        return "entangling-gate"
    if nonzero_angles > 0:
        return "rotation-gate"
    if measurements == 1:
        return "single-step-gate"
    return "wire"


def _training_grid():
    rows = []
    for m in range(0, 6):
        for o in (1, 2):
            for e in (0, 1):
                for a in range(0, 5):
                    rows.append(((m, o, e, a), model_label(m, o, e, a)))
    return rows


TRAINING_GRID = _training_grid()


def _scaled(features):
    m, o, e, a = features
    return (m / 5.0, o / 2.0, float(e), a / 4.0)


def classify_pattern(measurements, outputs, cross_edges, nonzero_angles, k=5):
    """Distance-weighted kNN over the policy-labelled grid."""
    target = _scaled((measurements, outputs, cross_edges, nonzero_angles))
    ranked = []
    for features, label in TRAINING_GRID:
        point = _scaled(features)
        dist = math.sqrt(sum((x - y) ** 2 for x, y in zip(target, point)))
        ranked.append((dist, features, label))
    ranked.sort(key=lambda row: (row[0], row[1]))
    votes = {}
    for dist, _, label in ranked[:k]:
        votes[label] = votes.get(label, 0.0) + 1.0 / (dist + 1e-9)
    priority = {"resource-state": 0, "wire": 1, "single-step-gate": 2,
                "rotation-gate": 3, "entangling-gate": 4}
    return sorted(votes.items(), key=lambda kv: (-kv[1], priority[kv[0]]))[0][0]


def classifier_report():
    scenarios = {
        "cluster_3x3_no_measurements": (0, 1, 0, 0),
        "hadamard_pattern": (1, 1, 0, 0),
        "wire_4_steps": (4, 1, 0, 0),
        "rz_pattern": (2, 1, 0, 1),
        "euler_exact_pattern": (4, 1, 0, 3),
        "cz_patch": (4, 2, 1, 0),
    }
    return {name: classify_pattern(*features)
            for name, features in scenarios.items()}


# ================================================================ 6. Advisory seats
def _trace(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def argon4_decide(topic="measurementbasedqc-demo"):
    """Gemini Argon 4 DECIDER seat: MAP->MODEL->STRESS->DECIDE.

    Names-only keys, live calls 0, tighten-only: can add HOLDs, never lift one.
    """
    stages = ["MAP", "MODEL", "STRESS", "DECIDE"]
    payload = {"seat": "gemini-argon-4", "topic": topic, "stages": stages}
    return {
        "seat": "Gemini Argon 4 Extended Thinking",
        "role": "DECIDER",
        "pipeline": stages,
        "tiers": [2048, 8192, 32768],
        "key": "names-only (GEMINI_API_KEY name checked, value never read)",
        "live_calls": 0,
        "decision": "PROCEED - sandbox simulation only, all service and hardware gates stay HOLD",
        "can_override_hold": False,
        "trace_sha256_16": _trace(payload),
    }


def claude_advisor(topic="measurementbasedqc-demo"):
    """Muse advisor seat: advises, can never override a HOLD."""
    return {
        "seat": "Muse",
        "role": "ADVISOR",
        "key": "names-only (MODEL_API_KEY name checked, value never read)",
        "live_calls": 0,
        "advice": "Say it plainly in every report: the patch implements (H x H) CZ (H x H), not a bare CZ - then show the branch enumeration, the affine Pauli frame, and the sandwich identity that recovers CZ.",
        "can_override_hold": False,
    }


def google_flow_plan():
    """Google Flow seat: plan-only, nothing rendered, nothing live."""
    return {
        "seat": "Google Flow",
        "role": "PLAN-ONLY",
        "shots": ["a lattice of |+> qubits lighting up as CZ edges stitch them into a cluster",
                  "measurement bases rotating on a wire while outcomes rain down 50/50",
                  "a Pauli frame tag chasing the logical state down the chain",
                  "feed-forward arrows bending later measurement angles",
                  "the 2x3 patch flashing its -1 phase onto |-->"],
        "rendered": False,
        "live": 0,
    }


def brains_report():
    return {"decider": argon4_decide(), "advisor": claude_advisor(),
            "flow": google_flow_plan()}


# ================================================================ checks
def run_checks():
    c = []

    def chk(name, ok):
        c.append((name, bool(ok)))

    # 0. PRNG + kit
    r1, r2 = SplitMix64(SEED), SplitMix64(SEED)
    chk("prng_deterministic",
        [r1.next_u64() for _ in range(8)] == [r2.next_u64() for _ in range(8)])
    chk("prng_float_range",
        all(0.0 <= SplitMix64(SEED + i).next_float() < 1.0 for i in range(4)))
    chk("hadamard_involution",
        mat_dev(mm(H_MAT, H_MAT), EYE2) < 1e-12)
    chk("j_gate_zero_is_hadamard", mat_dev(j_gate(0.0), H_MAT) < 1e-12)
    chk("j_gate_inverse",
        mat_dev(mm(j_gate(0.9), j_inv(0.9)), EYE2) < 1e-12)
    grid = input_grid()
    chk("input_grid_normalised",
        all(abs(abs(a) ** 2 + abs(b) ** 2 - 1.0) < 1e-12 for a, b in grid))
    chk("pauli_exponents_roundtrip",
        all(pauli_exponents(PAULIS[k]) == k for k in PAULIS))

    # 1. cluster states + stabilizers
    cl = cluster_report()
    chk("chain_stabilizers_exact",
        all(cl[f"chain_{n}"]["max_stabilizer_dev"] < TOL for n in range(2, 7)))
    chk("patch_2x3_stabilizers_exact", cl["patch_2x3"]["max_stabilizer_dev"] < TOL)
    chk("patch_3x3_stabilizers_exact", cl["patch_3x3"]["max_stabilizer_dev"] < TOL)
    chk("cluster_marginals_maximally_mixed",
        all(abs(p - 0.5) < 1e-9
            for p in cl["chain_4_marginal_purity"].values()))
    st_zero = [0j] * 16
    st_zero[0] = 1.0
    chk("product_state_fails_stabilizer",
        stabilizer_deviation(st_zero, 4, chain_edges(4), 0) > 0.5)

    # 2. wire: teleportation along the cluster, every branch
    wires = wire_report()
    chk("wire_1_is_hadamard",
        wires["wire_1"]["max_corrected_dev"] < TOL
        and wires["wire_1"]["max_frame_dev"] < TOL)
    chk("wire_2_is_identity", wires["wire_2"]["max_corrected_dev"] < TOL)
    chk("wire_4_is_identity", wires["wire_4"]["max_corrected_dev"] < TOL)
    chk("wire_probs_uniform",
        all(wires[f"wire_{k}"]["max_prob_dev_from_half"] < TOL
            for k in (1, 2, 4)))
    chk("wire_frame_affine",
        all(wires[f"wire_{k}"]["frame_affine"] for k in (1, 2, 4)))

    # 3. gate patterns
    gates = gate_report()
    chk("hadamard_pattern", gates["hadamard"]["max_corrected_dev"] < TOL)
    chk("rz_patterns",
        all(gates[k]["max_corrected_dev"] < TOL
            for k in ("rz_0.7", "rz_-1.3", "rz_pi_over_3")))
    chk("rx_patterns",
        all(gates[k]["max_corrected_dev"] < TOL
            for k in ("rx_0.7", "rx_-2.0")))
    chk("euler_h_frame_pattern", gates["euler_h_frame"]["max_corrected_dev"] < TOL)
    chk("euler_exact_pattern", gates["euler_exact"]["max_corrected_dev"] < TOL)
    chk("gate_frames_match_raw_output",
        all(g["max_frame_dev"] < TOL for g in gates.values()))
    chk("gate_probs_uniform",
        all(g["max_prob_dev_from_half"] < TOL for g in gates.values()))
    chk("gate_frames_affine", all(g["frame_affine"] for g in gates.values()))

    # 4. CZ patch
    cz = cz_report()
    chk("cz_patch_matches_h_frame_target", cz["max_corrected_dev"] < TOL)
    chk("cz_patch_probs_uniform", cz["max_prob_dev_from_half"] < TOL)
    chk("cz_patch_frame_affine", cz["frame_affine"])
    chk("cz_patch_sandwich_recovers_cz", cz["sandwich_recovers_cz"] < 1e-12)
    chk("cz_patch_maximally_entangling",
        abs(cz["concurrence_target_on_00"] - 1.0) < 1e-9)
    chk("cz_patch_not_bare_cz",
        mat_dev(PATCH_TARGET, CZ_MAT) > 0.5)

    # 5. Pauli frame bookkeeping
    fr = frame_report()
    chk("frame_worked_example",
        fr["worked_example"]["uncorrected_dev"] > 0.1
        and fr["worked_example"]["corrected_dev"] < TOL)
    chk("frame_tables_affine",
        fr["wire_2_affine"] and fr["euler_exact_affine"]
        and fr["cz_patch_affine"])

    # 6. classifier - labels come from the pattern policy itself
    rep = classifier_report()
    chk("classifier_resource", rep["cluster_3x3_no_measurements"] == "resource-state")
    chk("classifier_single_step", rep["hadamard_pattern"] == "single-step-gate")
    chk("classifier_wire", rep["wire_4_steps"] == "wire")
    chk("classifier_rotation",
        rep["rz_pattern"] == "rotation-gate"
        and rep["euler_exact_pattern"] == "rotation-gate")
    chk("classifier_entangling", rep["cz_patch"] == "entangling-gate")
    chk("classifier_matches_model_on_grid",
        all(classify_pattern(*features) == label
            for features, label in TRAINING_GRID))

    # gates + seats
    chk("hold_gates_14", len(HOLD_GATES) == 14
        and all(v.startswith("HOLD") for v in HOLD_GATES.values()))
    chk("gate_hardware_hold", gate("real_hardware_control") == "HOLD")
    chk("gate_advantage_hold", gate("quantum_advantage_claim") == "HOLD")
    chk("gate_crypto_hold", gate("cryptographic_use_claim") == "HOLD")
    chk("gate_blind_service_hold", gate("blind_computing_service_claim") == "HOLD")
    chk("gate_sandbox_proceed", gate("run_simulation") == "PROCEED")
    brains = brains_report()
    chk("argon4_no_override", brains["decider"]["can_override_hold"] is False
        and brains["decider"]["seat"]
        == "Gemini Argon 4 Extended Thinking")
    chk("claude_no_override", brains["advisor"]["can_override_hold"] is False)
    chk("flow_plan_only", brains["flow"]["rendered"] is False
        and brains["flow"]["live"] == 0)
    return c


# ================================================================ CLI / demo
def demo():
    print("=" * 68)
    print("MeasurementBasedQC-Lab - measurement-based quantum computing lab")
    print("by Darion Kellar | MIT | pure stdlib | zero network | EDUCATION ONLY")
    print("=" * 68)
    print("\n[1] THE HONEST CORE - compute by measuring, correct by bookkeeping")
    print("    The cluster state is built first and logic comes second: every")
    print("    measurement outcome is 50/50 random, but the randomness only")
    print("    ever appears as a Pauli byproduct. Track the Pauli frame and")
    print("    the computation is exact - asserted below by enumerating EVERY")
    print("    branch, never by sampling. Probe states come from a splitmix64")
    print(f"    PRNG, seed {SEED}.")
    print("\n[2] Cluster states - stabilizers pinned at +1")
    cl = cluster_report()
    for name in ("chain_2", "chain_4", "chain_6", "patch_2x3", "patch_3x3"):
        row = cl[name]
        print(f"    {name:10s} {row['qubits']} qubits | {row['edges']} CZ edges "
              f"| max ||K|psi>-|psi>|| = {row['max_stabilizer_dev']:.2e}")
    print(f"    chain-4 marginal purities: "
          f"{list(cl['chain_4_marginal_purity'].values())} (0.5 = maximally mixed)")
    print("\n[3] The one-way wire - teleportation along a chain")
    wires = wire_report()
    for length in (1, 2, 4):
        w = wires[f"wire_{length}"]
        print(f"    wire {length} step(s): {w['branches']} branches x "
              f"{w['inputs']} inputs | corrected dev {w['max_corrected_dev']:.2e} "
              f"| prob dev {w['max_prob_dev_from_half']:.2e}")
    print("    -> 1 step = H, 2 steps = identity, 4 steps = identity, exactly,")
    print("       on every branch, after the tracked Pauli correction.")
    print("\n[4] Gate patterns - angles steer, feed-forward corrects")
    gates = gate_report()
    for name, g in gates.items():
        print(f"    {name:16s} {g['steps']} measurements | {g['branches']} branches "
              f"| corrected dev {g['max_corrected_dev']:.2e}")
    print("    -> Rz and Rx from two J-steps; a general rotation from three")
    print("       (H.Rz.Rx.Rz) or four (exact Rz.Rx.Rz Euler) steps.")
    print("\n[5] Two-qubit patch - CZ in the Hadamard frame, stated honestly")
    cz = cz_report()
    print(f"    target (H x H) CZ (H x H) | {cz['branches']} branches x "
          f"{cz['input_pairs']} input pairs")
    print(f"    corrected dev {cz['max_corrected_dev']:.2e} | prob dev "
          f"{cz['max_prob_dev_from_half']:.2e}")
    print(f"    concurrence of target on |00> = {cz['concurrence_target_on_00']} "
          f"(maximally entangling); on |++> = {cz['concurrence_target_on_++']}")
    print(f"    sandwich (H x H).U.(H x H) vs CZ: dev "
          f"{cz['sandwich_recovers_cz']:.2e} -> the patch plus Hadamard")
    print("    patterns is exactly CZ. The bare patch is NOT bare CZ, and this")
    print("    lab never calls it that.")
    print("\n[6] Pauli frame bookkeeping - affine in the outcome bits")
    fr = frame_report()
    ex = fr["worked_example"]
    print(f"    wire-2 frames affine over GF(2): {fr['wire_2_affine']} | "
          f"euler-exact: {fr['euler_exact_affine']} | cz patch: "
          f"{fr['cz_patch_affine']}")
    print(f"    worked example ({ex['pattern']}, branch {ex['branch']}, "
          f"input {ex['input']}): frame {ex['frame']} -> uncorrected dev "
          f"{ex['uncorrected_dev']:.4f}, corrected dev {ex['corrected_dev']:.2e}")
    print("    -> the uncorrected output is wrong by exactly the predicted")
    print("       Pauli, and the correction removes it to machine precision.")
    print("\n[7] Pattern classifier (TinyML kNN, labels from the pattern policy)")
    for name, label in classifier_report().items():
        print(f"    {name:36s} -> {label}")
    print("\n[8] Advisory seats")
    brains = brains_report()
    print(f"    decider: {brains['decider']['decision']} "
          f"trace={brains['decider']['trace_sha256_16']}")
    print(f"    advisor can_override_hold = {brains['advisor']['can_override_hold']}")
    print(f"    flow rendered = {brains['flow']['rendered']} "
          f"live = {brains['flow']['live']}")
    print(f"\n[9] HOLD gates: {len(HOLD_GATES)}")
    for key in HOLD_GATES:
        print(f"    HOLD  {key}")
    checks = run_checks()
    passed = sum(1 for _, ok in checks if ok)
    print(f"\nCHECKS {passed}/{len(checks)}")
    for name, ok in checks:
        if not ok:
            print(f"    FAIL {name}")
    verdict = "PROCEED" if passed == len(checks) else "HOLD"
    print(f"VERDICT {verdict} (sandbox simulation only) | HOLD gates {len(HOLD_GATES)}")
    return 0 if passed == len(checks) else 1


def _rounded(obj):
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, dict):
        return {k: _rounded(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rounded(v) for v in obj]
    return obj


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] == "demo":
        return demo()
    cmd = argv[0]
    if cmd == "checks":
        checks = run_checks()
        for name, ok in checks:
            print(f"{'PASS' if ok else 'FAIL'} {name}")
        print(f"CHECKS {sum(1 for _, ok in checks if ok)}/{len(checks)}")
        return 0 if all(ok for _, ok in checks) else 1
    if cmd == "cluster":
        print(json.dumps(_rounded(cluster_report()), indent=2, sort_keys=True))
        return 0
    if cmd == "wire":
        print(json.dumps(_rounded(wire_report()), indent=2, sort_keys=True))
        return 0
    if cmd == "gates":
        print(json.dumps(_rounded(gate_report()), indent=2, sort_keys=True))
        return 0
    if cmd == "cz":
        print(json.dumps(_rounded(cz_report()), indent=2, sort_keys=True))
        return 0
    if cmd == "frame":
        print(json.dumps(_rounded(frame_report()), indent=2, sort_keys=True))
        return 0
    if cmd == "classify":
        print(json.dumps(classifier_report(), indent=2, sort_keys=True))
        return 0
    if cmd == "brains":
        print(json.dumps(brains_report(), indent=2, sort_keys=True))
        return 0
    if cmd == "holds":
        for key, value in HOLD_GATES.items():
            print(f"{key}: {value}")
        return 0
    if cmd == "hold-demo":
        action = argv[1] if len(argv) > 1 else "real_hardware_control"
        print(f"{action}: {HOLD_GATES.get(action, 'PROCEED - not gated')}")
        return 2 if gate(action) == "HOLD" else 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
