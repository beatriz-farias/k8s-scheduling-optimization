"""Testes da f.o. (rescheduling/objective.py).

    python -m unittest discover -s tests -v   (a partir da raiz)
"""

import unittest

from rescheduling import simulate  # noqa: E402
from rescheduling.cluster_state import ClusterState  # noqa: E402
from rescheduling.objective import Objective, PodDistribution, PodType, is_better  # noqa: E402
from rescheduling.instance import Instance, generate_instance  # noqa: E402

try:
    import gurobipy  # noqa: F401
    HAS_GUROBI = True
except ImportError:
    HAS_GUROBI = False


def make_instance(capacities, demands, alpha=None, history=None):
    """Instância de um período; os pods listados
    em `demands` ({pod: demanda}) ficam ativos."""
    n = len(capacities)
    return Instance(
        n_nodes=n, n_periods=1, alpha=alpha or [10.0] * n,
        capacity=list(capacities),
        periods_active_pods=[sorted(demands)], pod_demand=dict(demands),
        history_demand=list(history if history is not None else demands.values()),
    )


def build_state(instance, placement):
    state = ClusterState.empty(instance)
    for pod, node in placement.items():
        state.place(pod, node)
    return state


def big_pod_distribution(request=4.0):
    return PodDistribution([PodType((request,), 1.0)])


class ReferenceCaseTest(unittest.TestCase):
    """2 nós ligados com 4 CPUs livres cada (capacidade 8, um pod residente de
    4), 2 pods de 2 CPUs e M_pods só com pods de 4 CPUs."""

    def setUp(self):
        demands = {0: 4.0, 1: 4.0, 2: 2.0, 3: 2.0}
        self.instance = make_instance([8.0, 8.0], demands)
        self.spread = build_state(self.instance, {0: 0, 1: 1, 2: 0, 3: 1})    # sobra 2+2
        self.packed = build_state(self.instance, {0: 0, 1: 1, 2: 0, 3: 0})   # sobra 0+4
        self.new = Objective(self.instance, distribution=big_pod_distribution())

    def test_prefers_packed(self):
        spread = self.new.evaluate(self.spread, [])
        packed = self.new.evaluate(self.packed, [])
        self.assertAlmostEqual(spread.node_cost, packed.node_cost)
        self.assertGreater(spread.frag_cost, packed.frag_cost)
        self.assertTrue(is_better(packed, spread))
        self.assertTrue(self.new.better(packed, spread))
        self.assertFalse(self.new.better(spread, packed))

    def test_fragmentation_values(self):
        # Livre 2 de 8: tipo de 4 não cabe → F = 1.0 · 0.25
        self.assertAlmostEqual(self.new.fragmentation(0, self.spread), 0.25)
        # Nó cheio: F = 0
        self.assertAlmostEqual(self.new.fragmentation(0, self.packed), 0.0)
        self.assertAlmostEqual(self.new.fragmentation(1, self.packed), 0.0)  # livre 4 cabe o tipo


class FragmentationEdgeCasesTest(unittest.TestCase):
    def setUp(self):
        self.instance = make_instance([8.0, 8.0], {0: 8.0, 1: 3.0})
        self.objective = Objective(
            self.instance, distribution=big_pod_distribution())

    def test_empty_node_has_no_fragmentation(self):
        state = ClusterState.empty(self.instance)
        self.assertEqual(self.objective.fragmentation(0, state), 0.0)
        self.assertEqual(self.objective.evaluate(state, []).total, 0.0)

    def test_full_node_has_no_fragmentation(self):
        state = build_state(self.instance, {0: 0})
        self.assertEqual(self.objective.fragmentation(0, state), 0.0)

    def test_partially_used_node_is_fragmented(self):
        state = build_state(self.instance, {1: 0})  # livre 5 ≥ 4 → cabe
        self.assertEqual(self.objective.fragmentation(0, state), 0.0)
        tight = Objective(self.instance, distribution=big_pod_distribution(6.0))
        self.assertAlmostEqual(tight.fragmentation(0, state), 5.0 / 8.0)

    def test_pod_weight_is_dominant_resource_share(self):
        self.assertAlmostEqual(self.objective.weights[0], 8.0 / 8.0)
        self.assertAlmostEqual(self.objective.weights[1], 3.0 / 8.0)

    def test_lambda_scales_fragmentation(self):
        state = build_state(self.instance, {1: 0})
        tight = dict(distribution=big_pod_distribution(6.0))
        base = Objective(self.instance, lam=1.0, **tight).evaluate(state, [])
        double = Objective(self.instance, lam=2.0, **tight).evaluate(state, [])
        self.assertAlmostEqual(double.frag_cost, 2 * base.frag_cost)
        self.assertAlmostEqual(double.node_cost, base.node_cost)

    def test_per_pod_eviction_cost(self):
        objective = Objective(self.instance, omega={0: 5.0})
        state = build_state(self.instance, {0: 0, 1: 1})
        self.assertAlmostEqual(objective.evaluate(state, [0, 1]).disruption_cost,
                               5.0 + objective.eviction_cost(1))

    def test_default_eviction_cost_follows_node_cost_scale(self):
        objective = Objective(self.instance, omega_fraction=0.5)
        self.assertAlmostEqual(objective.eviction_cost(0), 0.5 * 10.0)

    def test_eviction_cost_by_size_keeps_mean(self):
        uniform = Objective(self.instance)
        by_size = Objective(self.instance, omega_by_size=True)
        pods = list(self.instance.pod_demand)
        mean = sum(by_size.eviction_cost(p) for p in pods) / len(pods)
        self.assertAlmostEqual(mean, uniform.eviction_cost(0))
        self.assertGreater(by_size.eviction_cost(0), by_size.eviction_cost(1))


class LexicographicTest(unittest.TestCase):
    def test_admission_always_dominates_cost(self):
        instance = make_instance([8.0, 8.0], {0: 4.0, 1: 4.0, 2: 1.0}, alpha=[1.0, 1000.0])
        objective = Objective(instance)
        # Admite 2 pods usando só o nó barato vs. admite 3 abrindo o nó caro.
        cheap = build_state(instance, {0: 0, 1: 0})
        costly = build_state(instance, {0: 0, 1: 0, 2: 1})
        a, b = objective.evaluate(cheap, []), objective.evaluate(costly, [])
        self.assertLess(a.total, b.total)
        self.assertTrue(objective.better(b, a))
        self.assertFalse(objective.better(a, b))

    def test_equal_admission_falls_back_to_cost(self):
        instance = make_instance([8.0, 8.0], {0: 2.0}, alpha=[1.0, 5.0])
        objective = Objective(instance)
        on_cheap = objective.evaluate(build_state(instance, {0: 0}), [])
        on_costly = objective.evaluate(build_state(instance, {0: 1}), [])
        self.assertTrue(objective.better(on_cheap, on_costly))

    def test_ties_are_not_better(self):
        instance = make_instance([8.0], {0: 2.0})
        objective = Objective(instance)
        value = objective.evaluate(build_state(instance, {0: 0}), [])
        self.assertFalse(objective.better(value, value))


class IncrementalDeltaTest(unittest.TestCase):
    """delta_place e move_delta devem coincidir com a diferença da f.o. completa."""

    def setUp(self):
        demands = {j: float(1 + j % 4) for j in range(8)}
        self.instance = make_instance([10.0, 9.0, 12.0], demands, alpha=[3.0, 4.0, 5.0])
        self.objective = Objective(self.instance, lam=1.5)

    def total(self, state):
        return self.objective.evaluate(state, []).total

    def test_delta_place(self):
        state = build_state(self.instance, {0: 0, 1: 1, 2: 0})
        for node in range(3):
            delta = self.objective.delta_place(5, node, state)
            after = state.copy()
            after.place(5, node)
            self.assertAlmostEqual(delta, self.total(after) - self.total(state))

    def test_move_delta(self):
        state = build_state(self.instance, {0: 0, 1: 1, 2: 0, 3: 2, 4: 2})
        for pod in (0, 1, 3):
            for destination in range(3):
                current = state.node_of(pod)
                if destination == current:
                    continue
                delta = self.objective.move_delta(pod, current, destination, state)
                after = state.copy()
                after.relocate(pod, destination)
                self.assertAlmostEqual(delta, self.total(after) - self.total(state))

    def test_cost_derives_evictions_from_states(self):
        previous = build_state(self.instance, {0: 0, 1: 1, 2: 0})
        current = build_state(self.instance, {0: 1, 1: 1})  # 0 mudou de nó, 2 saiu
        _, _, disruption = self.objective.cost(previous, current, active_pods=[0, 1, 2])
        self.assertAlmostEqual(disruption, self.objective.eviction_cost(0) + self.objective.eviction_cost(2))   # 0 mudou, 2 removido
        _, _, disruption = self.objective.cost(previous, current, active_pods=[0, 1])
        self.assertAlmostEqual(disruption, self.objective.eviction_cost(0))        # 2 deixou de existir


class SimulationTest(unittest.TestCase):
    def setUp(self):
        self.instance = generate_instance(n_nodes=6, n_pods_total=30, n_periods=6, seed=7)

    def run_config(self, scheduler, descheduler):
        return simulate(
            self.instance, scheduler=scheduler, descheduler=descheduler,
            max_moves_per_period=5, seed=1)

    def test_records_metrics(self):
        result = self.run_config("greedy", "ls_best")
        period = result["results_per_period"][-1]
        for key in ("admission", "node_cost", "frag_cost", "fragmented_pct", "utilization"):
            self.assertIn(key, period)
        self.assertAlmostEqual(result["total_cost"],
                               result["total_node_cost"] + result["total_frag_cost"]
                               + result["total_disruption_cost"])
        self.assertTrue(0 <= result["mean_fragmented_pct"] <= 100)
        self.assertTrue(0 < result["mean_utilization"][0] <= 1)

    def test_pod_distribution_ignores_the_instance_pods(self):
        a = generate_instance(n_nodes=6, n_pods_total=60, n_periods=6, seed=7)
        b = generate_instance(n_nodes=6, n_pods_total=120, n_periods=6, seed=7)
        self.assertEqual(a.history_demand, b.history_demand)
        self.assertNotEqual(list(a.pod_demand.values())[:5], a.history_demand[:5])
        objective = Objective(a)
        self.assertAlmostEqual(sum(t.frequency for t in objective.distribution.types), 1.0)

    def test_proportional_cost_model_follows_capacity(self):
        base = generate_instance(n_nodes=30, n_pods_total=60, n_periods=6, seed=7)
        prop = generate_instance(n_nodes=30, n_pods_total=60, n_periods=6, seed=7,
                                 cost_model="proportional")
        self.assertEqual(base.capacity, prop.capacity)
        self.assertAlmostEqual(sum(base.alpha), sum(prop.alpha) , delta=0.3 * sum(base.alpha))
        ratios = [a / c for a, c in zip(prop.alpha, prop.capacity)]
        self.assertLess(max(ratios) / min(ratios), 1.5)
        with self.assertRaises(ValueError):
            generate_instance(n_nodes=3, n_pods_total=6, cost_model="outro")

    def test_distribution_needs_history(self):
        instance = make_instance([8.0], {0: 2.0}, history=[])
        with self.assertRaises(ValueError):
            Objective(instance)

    def test_tight_capacity_leaves_pods_pending(self):
        roomy = generate_instance(n_nodes=6, n_pods_total=60, n_periods=6, seed=7,
                                  capacity_margin=1.6)
        tight = generate_instance(n_nodes=6, n_pods_total=60, n_periods=6, seed=7,
                                  capacity_margin=0.9)
        self.assertEqual(simulate(roomy, "greedy", "none", seed=1)["total_pending_pods"], 0)
        self.assertGreater(simulate(tight, "greedy", "none", seed=1)["total_pending_pods"], 0)

    def test_greedy_costs_no_more_than_least_requested(self):
        greedy = self.run_config("greedy", "none")
        spread = self.run_config("least_requested", "none")
        self.assertLessEqual(greedy["total_cost"], spread["total_cost"])

    def test_descheduler_never_worsens_lexicographic_value(self):
        base = self.run_config("greedy", "none")
        grasp = self.run_config("greedy", "grasp")
        self.assertGreaterEqual(grasp["total_admission"], base["total_admission"] - 1e-9)


@unittest.skipUnless(HAS_GUROBI, "requer Gurobi")
class MilpTest(unittest.TestCase):
    def test_queue_prefers_packing_over_spreading(self):
        from rescheduling.milp.model import solve_queue

        demands = {0: 4.0, 1: 4.0, 2: 2.0, 3: 2.0}
        instance = make_instance([8.0, 8.0], demands)
        state = build_state(instance, {0: 0, 1: 1})
        objective = Objective(instance, distribution=big_pod_distribution())
        placement = solve_queue(objective, [2, 3], state, mip_gap=0.0, time_limit=30)
        self.assertEqual(set(placement), {2, 3})
        self.assertEqual(len(set(placement.values())), 1)   # os dois no mesmo nó

    def test_queue_maximizes_admission_first(self):
        from rescheduling.milp.model import solve_queue

        demands = {0: 6.0, 1: 3.0, 2: 3.0}
        instance = make_instance([6.0], demands, alpha=[1.0])
        state = ClusterState.empty(instance)
        objective = Objective(instance)
        placement = solve_queue(objective, [0, 1, 2], state, mip_gap=0.0, time_limit=30)
        # 3+3 = 6 (A = 1.0) ou 6 sozinho (A = 1.0): ambos cabem 6; nunca deixa o nó vazio.
        self.assertAlmostEqual(sum(objective.weights[j] for j in placement), 1.0)

    def test_descheduler_plan_respects_move_limit_and_matches_evaluator(self):
        from rescheduling.milp.model import plan_moves

        demands = {0: 4.0, 1: 4.0, 2: 2.0, 3: 2.0}
        instance = make_instance([8.0, 8.0], demands)
        state = build_state(instance, {0: 0, 1: 1, 2: 0, 3: 1})
        objective = Objective(instance, omega=0.1, distribution=big_pod_distribution())
        none = plan_moves(objective, state, 0, mip_gap=0.0, time_limit=30)
        self.assertEqual(none, state.allocation)
        planned = plan_moves(objective, state, 1, mip_gap=0.0, time_limit=30)
        moved = [p for p in planned if planned[p] != state.node_of(p)]
        self.assertEqual(len(moved), 1)
        after = build_state(instance, planned)
        self.assertTrue(objective.better(objective.evaluate(after, moved),
                                         objective.evaluate(state, [])))


if __name__ == "__main__":
    unittest.main()
