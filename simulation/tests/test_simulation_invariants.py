"""Invariantes da simulação, em todo período de cada configuração.

    python -m unittest discover -s tests -v   (a partir da raiz)
"""

import itertools
import random
import unittest

from rescheduling.deschedulers import build_descheduler
from rescheduling.deschedulers.base import Descheduler
from rescheduling.evictions import EvictionPolicy
from rescheduling.instance import generate_instance
from rescheduling.objective import Objective
from rescheduling.schedulers import build_scheduler
from rescheduling.simulation import Simulation

try:
    import gurobipy  # noqa: F401
    HAS_GUROBI = True
except ImportError:
    HAS_GUROBI = False

MAX_MOVES = 3
TOLERANCE = 1e-9
SCHEDULERS = ["least_requested", "greedy"]
DESCHEDULERS = ["none", "ls_first", "ls_best", "grasp"]
MARGINS = [1.6, 0.95]       # folgada (sem Pending) e apertada (com Pending)
SEEDS = [1, 2]


class RecordingDescheduler(Descheduler):
    """Delega a um Descheduler real e guarda o estado e o plano de cada ciclo."""

    def __init__(self, inner, objective):
        self.inner = inner
        self.objective = objective
        self.cycles = []

    def select(self, context):
        plan = self.inner.select(context)
        self.cycles.append({
            "plan": plan.pods(),
            "pods_before": set(context.state.pods()),
            "admission_before": self.objective.admission(context.state),
        })
        return plan


class RecordingSimulation(Simulation):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.final_states = []

    def _run_period(self, period, active_pods, previous):
        state, result = super()._run_period(period, active_pods, previous)
        self.final_states.append(state)
        return state, result


def simulate_recording(instance, scheduler, descheduler, seed, **params):
    objective = Objective(instance)
    recorder = RecordingDescheduler(build_descheduler(descheduler, params), objective)
    simulation = RecordingSimulation(
        instance, scheduler=build_scheduler(scheduler, instance, objective),
        descheduler=recorder, policy=EvictionPolicy(MAX_MOVES, 1e-6),
        rng=random.Random(seed), objective=objective)
    simulation.run()
    return simulation, recorder, objective


class InvariantsTest(unittest.TestCase):
    def runs(self, schedulers, deschedulers, **params):
        for margin, seed, scheduler, descheduler in itertools.product(
                MARGINS, SEEDS, schedulers, deschedulers):
            instance = generate_instance(n_nodes=8, n_pods_total=60, n_periods=8,
                                         seed=seed, capacity_margin=margin)
            name = f"{scheduler}+{descheduler} margem={margin} seed={seed}"
            yield name, instance, simulate_recording(instance, scheduler, descheduler,
                                                     seed, **params)

    def test_no_node_exceeds_capacity(self):
        for name, instance, (simulation, _, _) in self.runs(SCHEDULERS, DESCHEDULERS):
            for t, state in enumerate(simulation.final_states):
                for node in range(instance.n_nodes):
                    load = sum(instance.pod_demand[p] for p, n in state.allocation.items()
                               if n == node)
                    self.assertLessEqual(load, instance.capacity[node] + TOLERANCE,
                                         f"{name} período {t} nó {node}")
                    self.assertAlmostEqual(load, state.used[node], msg=f"{name} período {t}")

    def test_each_pod_has_at_most_one_node_and_only_active_pods_run(self):
        for name, instance, (simulation, _, _) in self.runs(SCHEDULERS, DESCHEDULERS):
            for t, state in enumerate(simulation.final_states):
                self.assertTrue(set(state.allocation) <= set(instance.periods_active_pods[t]),
                                f"{name} período {t}")

    def test_no_pod_is_evicted_twice_in_a_cycle(self):
        for name, _, (_, recorder, _) in self.runs(SCHEDULERS, DESCHEDULERS):
            for cycle in recorder.cycles:
                self.assertEqual(len(cycle["plan"]), len(set(cycle["plan"])), name)
                self.assertTrue(set(cycle["plan"]) <= cycle["pods_before"], name)

    def test_evictions_per_cycle_respect_the_limit(self):
        for name, _, (simulation, recorder, _) in self.runs(SCHEDULERS, DESCHEDULERS):
            for cycle in recorder.cycles:
                self.assertLessEqual(len(cycle["plan"]), MAX_MOVES, name)

    def test_none_descheduler_never_evicts(self):
        for name, _, (_, recorder, _) in self.runs(SCHEDULERS, ["none"]):
            self.assertTrue(all(not cycle["plan"] for cycle in recorder.cycles), name)

    def test_grasp_never_lowers_admission(self):
        """O GRASP só aplica o plano se a tupla (-A, C) real melhora, então não pode
        perder admissão."""
        self.assert_admission_not_lowered(SCHEDULERS, ["grasp"])

    def test_heuristic_deschedulers_never_lower_admission(self):
        """LS escolhe pela previsão de uma evicção por vez; ao executar todas e
        recolocar, um pod evictado pode não caber e virar Pending. Este teste
        vigia esse caso."""
        self.assert_admission_not_lowered(SCHEDULERS, ["ls_first", "ls_best"])

    def assert_admission_not_lowered(self, schedulers, deschedulers):
        for name, _, (simulation, recorder, objective) in self.runs(schedulers, deschedulers):
            for cycle, state in zip(recorder.cycles, simulation.final_states):
                self.assertGreaterEqual(objective.admission(state),
                                        cycle["admission_before"] - TOLERANCE, name)


@unittest.skipUnless(HAS_GUROBI, "requer Gurobi")
class MilpInvariantsTest(unittest.TestCase):
    def test_milp_components_respect_capacity_and_limit(self):
        instance = generate_instance(n_nodes=6, n_pods_total=30, n_periods=4, seed=3,
                                     capacity_margin=1.1)
        for scheduler, descheduler in (("greedy", "milp"), ("milp", "none"), ("milp", "milp")):
            simulation, recorder, _ = simulate_recording(
                instance, scheduler, descheduler, 3, **(
                    {"time_limit": 10} if descheduler == "milp" else {}))
            for t, state in enumerate(simulation.final_states):
                for node in range(instance.n_nodes):
                    load = sum(instance.pod_demand[p] for p, n in state.allocation.items()
                               if n == node)
                    self.assertLessEqual(load, instance.capacity[node] + 1e-6)
            for cycle in recorder.cycles:
                self.assertLessEqual(len(cycle["plan"]), MAX_MOVES)
                self.assertEqual(len(cycle["plan"]), len(set(cycle["plan"])))


if __name__ == "__main__":
    unittest.main()
