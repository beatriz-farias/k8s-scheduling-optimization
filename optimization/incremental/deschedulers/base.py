"""Contrato dos Deschedulers: decidem quais pods evictar, não o destino."""

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..cluster_state import ClusterState
from ..cost import CostModel
from ..evictions import EvictionPlan, EvictionPolicy, EvictionPredictor
from ..schedulers import Scheduler


@dataclass
class DeschedulingContext:
    """Tudo que um Descheduler enxerga em um ciclo. O estado nunca é
    alterado por ele: quem planeja trabalha sobre cópias."""
    state: ClusterState
    scheduler: Scheduler
    policy: EvictionPolicy
    cost_model: CostModel
    rng: random.Random
    predictor: EvictionPredictor = field(init=False)

    def __post_init__(self):
        self.predictor = EvictionPredictor(self.scheduler, self.cost_model,
                                           self.policy.min_improvement)

    @property
    def instance(self):
        return self.state.instance

    @property
    def pods(self) -> list:
        return self.state.pods()


class Descheduler(ABC):
    @abstractmethod
    def select(self, context: DeschedulingContext) -> EvictionPlan:
        """Plano ordenado de pods a evictar neste ciclo."""
