"""Scheduler: coloca pods nos nós sem tocar nos pods que já rodam.

Um nó está aberto quando tem pelo menos um pod (used > 0). Pods evictados
são pods novos para o Scheduler: ele não sabe onde estavam antes, então
omega não entra na pontuação.
"""

from abc import ABC, abstractmethod
from typing import Optional

from .cluster_state import ClusterState
from .cost import EMPTY_NODE_TOLERANCE, CostModel


class Scheduler(ABC):
    def __init__(self, instance):
        self.instance = instance

    @abstractmethod
    def choose_node(self, pod: int, state: ClusterState) -> Optional[int]:
        """Nó escolhido para um pod isolado, ou None se nenhum nó o comporta."""

    def schedule(self, pods: list, state: ClusterState):
        """Fila do Scheduler: coloca cada pod, na ordem dada. Pod sem nó
        viável fica sem alocação (equivalente a Pending)."""
        for pod in pods:
            self._bind(pod, state)

    def _bind(self, pod: int, state: ClusterState):
        node = self.choose_node(pod, state)
        if node is None:
            return
        state.place(pod, node)


class GreedyCostScheduler(Scheduler):
    """Nó viável de menor custo marginal (lógica do Score plugin)."""

    def __init__(self, instance):
        super().__init__(instance)
        self.cost_model = CostModel(instance)

    def choose_node(self, pod, state):
        feasible = state.feasible_nodes(pod)
        if not feasible:
            return None
        return min(feasible, key=lambda node: self._cost(pod, node, state))

    def _cost(self, pod, node, state):
        is_open = state.used[node] > EMPTY_NODE_TOLERANCE
        return self.cost_model.marginal_cost(pod, node, is_open)


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
