# Copyright 2021 qclib project.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Union, List, Tuple

from cmath import isclose
import numpy as np

from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit import Qubit
from qiskit.circuit.library import C3XGate
from qiskit.circuit.library import RZGate, RYGate
from qiskit.extensions import UnitaryGate
from qiskit.quantum_info import OneQubitEulerDecomposer


# pylint: disable=maybe-no-member


def mcg(
    self,
    unitary,
    controls: Union[QuantumRegister, List[Qubit]],
    target: Qubit,
    ctrl_state: str=None
):
    """
    Selects the most cost-effective multicontrolled gate decomposition.
    """
    _check_u2(unitary)

    num_ctrl = len(controls)
    if num_ctrl == 0:
        self.unitary(unitary, [target])
    else:
        if num_ctrl > 1 and _check_su2(unitary):
            self.linear_mcg_su2(unitary, controls, target, ctrl_state)
        else:
            u_gate = QuantumCircuit(1)
            u_gate.unitary(unitary, 0)
            self.append(u_gate.control(num_ctrl, ctrl_state=ctrl_state), [*controls, target])


QuantumCircuit.mcg = mcg


def _check_u2(matrix):
    if matrix.shape != (2, 2):
        raise ValueError(
            "The shape of a U(2) matrix must be (2, 2)."
        )
    if not np.allclose(matrix @ np.conj(matrix.T), [[1.0, 0.0],[0.0, 1.0]]):
        raise ValueError(
            "The columns of a U(2) matrix must be orthonormal."
        )

def _check_su2(matrix):
    return isclose(np.linalg.det(matrix), 1.0)


def linear_mcg_su2(
    self,
    unitary,
    controls: Union[QuantumRegister, List[Qubit]],
    target: Qubit,
    ctrl_state: str=None
):
    """
    Multicontrolled gate decomposition with linear cost.
    `unitary` must be a SU(2) matrix with at least one real diagonal.
    """
    is_main_diag_real = unitary[0, 0].imag == 0.0 and unitary[1, 1].imag == 0.0
    is_secondary_diag_real = unitary[0,1].imag == 0.0 and unitary[1,0].imag == 0.0

    if  not is_main_diag_real and not is_secondary_diag_real:
        self.linear_depth_any_mcsu2(
            unitary=unitary,
            controls=controls,
            target=target,
            ctrl_state=ctrl_state
        )
    else:
        if is_secondary_diag_real:
            x = unitary[0,1]
            z = unitary[1,1]
        else:
            x = -unitary[0,1].real
            z = unitary[1,1] - unitary[0,1].imag * 1.0j
            self.h(target)

        self.linear_depth_mcv(
            x,
            z,
            controls,
            target,
            ctrl_state
        )

        if not is_secondary_diag_real:
            self.h(target)


QuantumCircuit.linear_mcg_su2 = linear_mcg_su2


def mcx_v_chain_dirty(
    self,
    controls,
    target,
    ancillae,
    ctrl_state=None,
    relative_phase=False,
    action_only=False
):
    """
        In-place application of k-controlled X gate with k - 2 dirty ancilla qubits.
        This decomposition uses the optimization shown in Lemma 9 of
        https://arxiv.org/abs/1501.06911), which contains at most 8k - 6 `cx`.

        Parameters
        ----------
        circuit : quantum circuit where the k-controlled X will be applied
        controls : k control qubits
        ancillae : at least k - 2 dirty ancilla qubits
        target : target qubit of the operation
    """

    num_ctrl = len(controls)
    num_ancilla = num_ctrl - 2
    targets = [target] + ancillae[:num_ancilla][::-1]

    if ctrl_state is not None:
        for i, ctrl in enumerate(ctrl_state[::-1]):
            if ctrl == '0':
                self.x(controls[i])

    if num_ctrl < 3:
        self.mcx(
            control_qubits=controls,
            target_qubit=target,
            mode="noancilla"
        )
    elif num_ctrl == 3:
        self.append(C3XGate(), [*controls[:], target], [])
    else:
        for m in range(2):
            for i, _ in enumerate(controls):      # action part
                if i < num_ctrl - 2:
                    if targets[i] != target or relative_phase:  # gate cancelling
                        theta = np.pi / 4.

                        # cancel rightmost gates of action part with leftmost gates of reset part
                        if (relative_phase and targets[i] == target and m == 1):
                            self.cx(ancillae[num_ancilla - i - 1], targets[i])
                            self.u(theta=theta, phi=0., lam=0., qubit=targets[i])
                            self.cx(controls[num_ctrl - i - 1], targets[i])
                            self.u(theta=theta, phi=0., lam=0., qubit=targets[i])
                        else:
                            self.u(theta=-theta, phi=0., lam=0., qubit=targets[i])
                            self.cx(controls[num_ctrl - i - 1], targets[i])
                            self.u(theta=-theta, phi=0., lam=0., qubit=targets[i])
                            self.cx(ancillae[num_ancilla - i - 1], targets[i])

                    else:
                        self.ccx(
                            control_qubit1=controls[num_ctrl - i - 1],
                            control_qubit2=ancillae[num_ancilla - i - 1],
                            target_qubit=targets[i]
                        )
                else:
                    theta = np.pi / 4.

                    self.u(theta=-theta, phi=0., lam=0., qubit=targets[i])
                    self.cx(controls[num_ctrl - i - 2], targets[i])
                    self.u(theta=-theta, phi=0., lam=0., qubit=targets[i])
                    self.cx(controls[num_ctrl - i - 1], targets[i])
                    self.u(theta=theta, phi=0., lam=0., qubit=targets[i])
                    self.cx(controls[num_ctrl - i - 2], targets[i])
                    self.u(theta=theta, phi=0., lam=0., qubit=targets[i])

                    break

            for i, _ in enumerate(ancillae[1:]):      # reset part
                theta = np.pi / 4.
                self.cx(ancillae[i], ancillae[i + 1])
                self.u(theta=theta, phi=0., lam=0., qubit=ancillae[i + 1])
                self.cx(controls[2 + i], ancillae[i + 1])
                self.u(theta=theta, phi=0., lam=0., qubit=ancillae[i + 1])


            if action_only:
                break

    if ctrl_state is not None:
        for i, ctrl in enumerate(ctrl_state[::-1]):
            if ctrl == '0':
                self.x(controls[i])


QuantumCircuit.mcx_v_chain_dirty = mcx_v_chain_dirty


def linear_depth_mcv(
    self,
    x,
    z,
    controls: Union[QuantumRegister, List[Qubit]],
    target: Qubit,
    ctrl_state: str=None
):

    alpha_r = np.sqrt(
    (np.sqrt((z.real + 1.) / 2.) + 1.) / 2.
    )
    alpha_i = z.imag / (2. * np.sqrt(
        (z.real + 1.) * (np.sqrt((z.real + 1.) / 2.) + 1.)
    ))
    alpha = alpha_r + 1.j * alpha_i
    beta = x / (2. * np.sqrt(
            (z.real + 1.) * (np.sqrt((z.real + 1.) / 2.) + 1.)
        )
    )
    s_op = np.array(
        [[alpha, -np.conj(beta)],
        [beta, np.conj(alpha)]]
    )

    # S gate definition
    s_gate = QuantumCircuit(1)
    s_gate.unitary(s_op, 0)

    num_ctrl = len(controls)
    k_1 = int(np.ceil(num_ctrl / 2.))
    k_2 = int(np.floor(num_ctrl / 2.)) - 1

    ctrl_state_k_1 = None
    ctrl_state_k_2 = None

    if ctrl_state is not None:
        ctrl_state_k_1 = ctrl_state[::-1][:k_1][::-1]
        ctrl_state_k_2 = ctrl_state[::-1][k_1:][::-1]

    self.mcx_v_chain_dirty(
        controls=controls[:k_1],
        target=target,
        ancillae=controls[k_1:2 * k_1 - 2],
        ctrl_state=ctrl_state_k_1
    )
    self.append(s_gate, [target])
    self.mcx_v_chain_dirty(
        controls=controls[k_1:],
        target=target,
        ancillae=controls[k_1 - k_2 + 1:k_1],
        ctrl_state=ctrl_state_k_2
    )
    self.append(s_gate.inverse(), [target])
    self.mcx_v_chain_dirty(
        controls=controls[:k_1],
        target=target,
        ancillae=controls[k_1:2 * k_1 - 2],
        ctrl_state=ctrl_state_k_1
    )
    self.append(s_gate, [target])
    self.mcx_v_chain_dirty(
        controls=controls[k_1:],
        target=target,
        ancillae=controls[k_1 - k_2 + 1:k_1],
        ctrl_state=ctrl_state_k_2
    )
    self.append(s_gate.inverse(), [target])


QuantumCircuit.linear_depth_mcv = linear_depth_mcv

def linear_depth_any_mcsu2(
    self,
    unitary,
    controls: Union[QuantumRegister, List[Qubit]],
    target: Qubit,
    ctrl_state: str=None
):
    """
        Implements the gate decompostion of any gate in SU(2)
        presented in Lemma 7.9 of https://arxiv.org/abs/quant-ph/9503016
    """
    theta, phi, lamb, _ = OneQubitEulerDecomposer._params_zyz(unitary)

    a_gate, b_gate, c_gate = get_abc_operators(phi, theta, lamb)

    self._apply_abc(
        controls=controls,
        target=target,
        su2_gates=(a_gate, b_gate, c_gate),
        ctrl_state=ctrl_state
    )

QuantumCircuit.linear_depth_any_mcsu2 = linear_depth_any_mcsu2

def get_abc_operators(beta, gamma, delta):
    """
    Creates A,B and C matrices such that
    ABC = I
    """
    # A
    a_rz = RZGate(beta).to_matrix()
    a_ry = RYGate(gamma / 2).to_matrix()
    a_matrix = a_rz.dot(a_ry)

    # B
    b_ry = RYGate(-gamma / 2).to_matrix()
    b_rz = RZGate(-(delta + beta) / 2).to_matrix()
    b_matrix = b_ry.dot(b_rz)

    # C
    c_matrix = RZGate((delta - beta) / 2).to_matrix()

    a_gate = UnitaryGate(a_matrix, label='A')
    b_gate = UnitaryGate(b_matrix, label='B')
    c_gate = UnitaryGate(c_matrix, label='C')
    return a_gate, b_gate, c_gate


def _apply_abc(
    self,
    controls: Union[QuantumRegister, List[Qubit]],
    target: Qubit,
    su2_gates: Tuple[UnitaryGate],
    ctrl_state: str = None
):
    """
        Applies ABC matrices to the quantum circuit according to theorem 5
        of Iten et al. 2016 (arXiv:1501.06911).
        Where su2_gates is a tuple of UnitaryGates in SU(2) eg.: (A,  B, C).
    """
    a_gate, b_gate, c_gate = su2_gates
    if len(controls) < 8:
        self.append(c_gate, target)
        self.mcx(controls, target)
        self.append(b_gate, target)
        self.mcx(controls, target)
        self.append(a_gate, target)

    else:
        ancilla = controls[-1]
        # setting gate controls
        controlled_a = a_gate.control(1)
        controlled_b = b_gate.control(1)
        controlled_c = c_gate.control(1)

        # applying controlled_gates to circuit
        self.append(controlled_c, [ancilla, target], [])
        self.mcx_v_chain_dirty(
            controls=controls[:-1],
            target=target,
            ancillae=ancilla,
            ctrl_state=ctrl_state
        )
        self.append(controlled_b, [ancilla, target], [])
        self.mcx_v_chain_dirty(
            controls=controls[:-1],
            target=target,
            ancillae=ancilla,
            ctrl_state=ctrl_state
        )
        self.append(controlled_a, [ancilla, target], [])

    return self

QuantumCircuit._apply_abc = _apply_abc