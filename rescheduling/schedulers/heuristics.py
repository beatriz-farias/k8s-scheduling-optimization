"""Schedulers heurísticos: decidem pod a pod, no momento em que o pod chega."""

from .base import Scheduler


class GreedyCostScheduler(Scheduler):
    """Nó viável de menor ΔC (lógica do Score plugin): score = -ΔC(i) com ΔC = c_i·[nó desligado] +
    λ·c_i·(F_depois − F_antes). A admissão é garantida: sempre aloca se
    existir nó viável."""

    def choose_node(self, pod, state):
        feasible = state.feasible_nodes(pod)
        if not feasible:
            return None
        return min(feasible, key=lambda node: self.objective.place_cost(pod, node, state))


class LeastRequestedScheduler(Scheduler):
    """kube-scheduler padrão: nó viável com maior capacidade livre relativa,
    sem conhecer custos."""

    def choose_node(self, pod, state):
        feasible = state.feasible_nodes(pod)
        if not feasible:
            return None
        return max(feasible, key=lambda node: self._free_fraction(node, state))

    def _free_fraction(self, node, state):
        capacity = self.instance.capacity[node]
        return (capacity - state.used[node]) / capacity
