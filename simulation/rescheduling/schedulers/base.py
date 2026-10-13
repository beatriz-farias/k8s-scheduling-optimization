"""Scheduler: coloca pods nos nós sem tocar nos pods que já rodam.

Um nó está aberto quando tem pelo menos um pod (used > 0). Pods evictados
são pods novos para o Scheduler: ele não sabe onde estavam antes, então
omega não entra na pontuação.
"""

from abc import ABC, abstractmethod
from typing import Optional

from ..cluster_state import ClusterState


class Scheduler(ABC):
    def __init__(self, instance, objective):
        self.instance = instance
        self.objective = objective

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
