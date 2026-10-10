"""Schedulers disponíveis.

    least_requested  kube-scheduler padrão (maior capacidade livre relativa)
    greedy           menor ΔC da f.o. (lógica do plugin Score)
    milp             MILP (Gurobi) coloca a fila de pods de uma vez, de forma ótima
"""

from ..milp.scheduler import MilpScheduler
from .base import Scheduler
from .heuristics import GreedyCostScheduler, LeastRequestedScheduler

SCHEDULERS = {
    "least_requested": LeastRequestedScheduler,
    "greedy": GreedyCostScheduler,
    "milp": MilpScheduler,
}


def build_scheduler(name: str, instance, objective, params: dict = None) -> Scheduler:
    return SCHEDULERS[name](instance, objective, **(params or {}))
