"""Registro dos Schedulers disponíveis.

    least_requested  kube-scheduler padrão (maior capacidade livre relativa)
    greedy           menor custo marginal (lógica do plugin.go Score)
    milp             MILP (Gurobi) coloca a fila de pods de uma vez, de forma ótima
"""

from .milp_scheduler import MilpScheduler
from .schedulers import GreedyCostScheduler, LeastRequestedScheduler, Scheduler

SCHEDULERS = {
    "least_requested": LeastRequestedScheduler,
    "greedy": GreedyCostScheduler,
    "milp": MilpScheduler,
}


def build_scheduler(name: str, instance, params: dict = None) -> Scheduler:
    return SCHEDULERS[name](instance, **(params or {}))
