"""Scheduler MILP: coloca a fila de pods de uma vez, de forma ótima, com os
pods que já rodam fixos.

Fecha o ciclo do Descheduler MILP: o plano dele mantém os pods não movidos
onde estão, então recolocar os evictados com este Scheduler resolve o mesmo
subproblema do plano. Com Schedulers que decidem pod a pod, o plano pode não
ser seguido.
"""

from ..cluster_state import ClusterState
from ..schedulers.heuristics import GreedyCostScheduler


class MilpScheduler(GreedyCostScheduler):
    """Para um pod isolado, o ótimo do MILP é o nó de menor ΔC, então
    choose_node é o do guloso (usado pelas previsões do Descheduler). Só a
    colocação em lote (schedule) resolve o MILP, em dois passos: primeiro
    maximiza a admissão, depois minimiza nós + fragmentação. Pods que não
    cabem em lugar nenhum ficam Pending. Se o solver não devolver solução
    dentro do limite de tempo, a fila é colocada pelo guloso."""

    def __init__(self, instance, objective, mip_gap: float = 0.01, time_limit: float = 60):
        super().__init__(instance, objective)
        self.mip_gap = mip_gap
        self.time_limit = time_limit

    def schedule(self, pods: list, state: ClusterState):
        if not pods:
            return
        from .model import solve_queue  # Gurobi só é exigido por este Scheduler

        placement = solve_queue(self.objective, pods, state, self.mip_gap, self.time_limit)
        if placement is None:
            super().schedule(pods, state)
            return
        for pod in pods:
            if pod in placement:
                state.place(pod, placement[pod])
