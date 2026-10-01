"""Evicções: plano, previsão de efeito e execução."""

from dataclasses import dataclass
from typing import Optional

from .cluster_state import ClusterState
from .cost import CostModel
from .schedulers import Scheduler


@dataclass(frozen=True)
class EvictionPolicy:
    """Limite de evicções por ciclo (None = sem limite) e melhoria mínima
    prevista para valer a pena evictar."""
    max_moves: Optional[int]
    min_improvement: float

    def allows(self, evictions_so_far: int) -> bool:
        return self.max_moves is None or evictions_so_far < self.max_moves


class EvictionPlan:
    """Pods a evictar no ciclo, em ordem; cada pod aparece no máximo uma vez."""

    def __init__(self):
        self._ordered = []
        self._members = set()

    def add(self, pod: int):
        self._ordered.append(pod)
        self._members.add(pod)

    def __contains__(self, pod: int) -> bool:
        return pod in self._members

    def __len__(self) -> int:
        return len(self._ordered)

    def pods(self) -> list:
        return list(self._ordered)


@dataclass(frozen=True, order=True)
class EvictionCandidate:
    delta: float
    pod: int
    destination: int


class EvictionPredictor:
    """Prevê, simulando o Scheduler, o efeito de evictar um pod. A previsão
    avalia uma evicção por vez; na execução real todos os pods do ciclo são
    evictados antes de serem recolocados, então o resultado pode diferir."""

    def __init__(self, scheduler: Scheduler, cost_model: CostModel, min_improvement: float):
        self.scheduler = scheduler
        self.cost_model = cost_model
        self.min_improvement = min_improvement

    def predict(self, pod: int, state: ClusterState) -> Optional[EvictionCandidate]:
        """None se o pod voltaria ao mesmo nó (evicção que só paga ω) ou não
        caberia em lugar nenhum."""
        current = state.node_of(pod)
        with state.freed(pod):
            destination = self.scheduler.choose_node(pod, state)
        if destination is None or destination == current:
            return None
        infra_delta = self.cost_model.move_delta(pod, current, destination, state.used)
        return EvictionCandidate(infra_delta + state.instance.omega, pod, destination)

    def improving(self, pods: list, plan: EvictionPlan, state: ClusterState) -> list:
        """Evicções que reduzem o custo previsto em mais que min_improvement,
        entre os pods ainda fora do plano."""
        predictions = (self.predict(pod, state) for pod in pods if pod not in plan)
        return [candidate for candidate in predictions
                if candidate is not None and candidate.delta < -self.min_improvement]


def execute_evictions(scheduler: Scheduler, plan: EvictionPlan,
                      state: ClusterState) -> ClusterState:
    """Evicta todos os pods do plano e o Scheduler os recoloca, na ordem de
    evicção. Retorna um novo estado; não altera o recebido."""
    result = state.copy()
    for pod in plan.pods():
        result.evict(pod)
    scheduler.schedule(plan.pods(), result)
    return result
