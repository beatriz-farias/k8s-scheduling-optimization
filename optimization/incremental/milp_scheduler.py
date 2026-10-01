"""Scheduler MILP: coloca a fila de pods de uma vez, de forma ótima, com os
pods que já rodam fixos.

Fecha o ciclo do Descheduler MILP: o plano dele mantém os pods não movidos
onde estão, então recolocar os evictados com este Scheduler resolve o mesmo
subproblema do plano e chega a um custo de infraestrutura igual ou menor.
Com Schedulers que decidem pod a pod, o plano pode não ser seguido.
"""

from .cluster_state import ClusterState
from .cost import EMPTY_NODE_TOLERANCE, CostModel
from .schedulers import GreedyCostScheduler


class MilpScheduler(GreedyCostScheduler):
    """Para um pod isolado, o ótimo do MILP é o nó de menor custo marginal,
    então choose_node é o do guloso (usado pelas previsões do Descheduler).
    Só a colocação em lote (schedule) resolve o MILP.

    Pods que não cabem em lugar nenhum ficam Pending (penalidade M, a mesma
    do custo do período). Se o solver não devolver solução dentro do limite
    de tempo, a fila é colocada pelo guloso."""

    def __init__(self, instance, mip_gap: float = 0.01, time_limit: float = 60):
        super().__init__(instance)
        self.mip_gap = mip_gap
        self.time_limit = time_limit

    def schedule(self, pods: list, state: ClusterState):
        if not pods:
            return
        placement = self._solve(pods, state)
        if placement is None:
            super().schedule(pods, state)
            return
        for pod in pods:
            self._place_if_planned(pod, placement, state)

    @staticmethod
    def _place_if_planned(pod: int, placement: dict, state: ClusterState):
        if pod in placement:
            state.place(pod, placement[pod])

    def _solve(self, pods: list, state: ClusterState):
        """{pod: nó} dos pods colocados, ou None se o solver falhou."""
        import gurobipy as gp  # Gurobi só é exigido por este Scheduler
        from gurobipy import GRB

        instance = self.instance
        nodes = range(instance.n_nodes)
        closed = [i for i in nodes if state.used[i] <= EMPTY_NODE_TOLERANCE]

        model = gp.Model("milp_scheduler")
        model.Params.OutputFlag = 0
        model.Params.MIPGap = self.mip_gap
        model.Params.TimeLimit = self.time_limit

        y = model.addVars(pods, nodes, vtype=GRB.BINARY)
        pending = model.addVars(pods, vtype=GRB.BINARY)
        opened = model.addVars(closed, vtype=GRB.BINARY)

        for j in pods:
            model.addConstr(gp.quicksum(y[j, i] for i in nodes) + pending[j] == 1)
        for i in nodes:
            load = gp.quicksum(instance.pod_demand[j] * y[j, i] for j in pods)
            if i in opened:
                model.addConstr(load <= instance.capacity[i] * opened[i])
            else:
                model.addConstr(load <= instance.capacity[i] - state.used[i])

        costs = CostModel(instance)
        model.setObjective(
            gp.quicksum(instance.alpha[i] * opened[i] for i in closed)
            + gp.quicksum(costs.marginal_cost(j, i, True) * y[j, i] for j in pods for i in nodes)
            + costs.pending_penalty * pending.sum(),
            GRB.MINIMIZE,
        )
        model.optimize()

        if model.SolCount == 0:
            return None
        return {j: i for j in pods for i in nodes if y[j, i].X > 0.5}
