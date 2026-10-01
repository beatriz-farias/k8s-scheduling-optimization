"""
Modelo MILP do escalonamento de containers com penalidade de migração
(extensão de Martins et al. 2023) para um período, usado pelo Descheduler
MILP (incremental/deschedulers/milp.py):

    min  sum_i [ alpha_i*x_i + (beta_i+gamma_i)*sum_j y_ij ]
         + sum_i sum_{j: y_bar_ij=1} (1-y_ij)*omega

Sujeito a: capacidade por nó, cada pod alocado a exatamente 1 nó, binárias.
"""

import time
import gurobipy as gp
from gurobipy import GRB

from instance_generator import Instance


def solve_period(inst: Instance, active_pods: list, previous_alloc: dict,
                  mip_gap: float = 0.01, time_limit: float = None,
                  verbose: bool = False, start_alloc: dict = None,
                  max_moves: int = None):
    """
    Resolve o MILP para um único período.

    active_pods: pods ativos neste período.
    previous_alloc: alocação do período anterior {pod_id: node_id}, usada
    no cálculo da penalidade omega.
    start_alloc: alocação atual, usada como warm start (uso pelo
    Descheduler MILP).
    max_moves: se informado (exige start_alloc), limita quantos pods podem
    mudar de nó em relação a start_alloc.
    """
    n = inst.n_nodes
    t0 = time.time()

    model = gp.Model("container_scheduling_period")
    if not verbose:
        model.Params.OutputFlag = 0
    model.Params.MIPGap = mip_gap
    if time_limit:
        model.Params.TimeLimit = time_limit

    x = model.addVars(n, vtype=GRB.BINARY, name="x")
    y = model.addVars(active_pods, n, vtype=GRB.BINARY, name="y")

    # Restrição: cada pod alocado a exatamente um nó
    for j in active_pods:
        model.addConstr(gp.quicksum(y[j, i] for i in range(n)) == 1)

    # Restrição: capacidade dos nós (só ativa se o nó estiver aberto)
    for i in range(n):
        model.addConstr(
            gp.quicksum(inst.pod_demand[j] * y[j, i] for j in active_pods)
            <= inst.capacity[i] * x[i]
        )

    # Função objetivo
    custo_abertura = gp.quicksum(inst.alpha[i] * x[i] for i in range(n))
    custo_alocacao = gp.quicksum(
        (inst.beta[i] + inst.gamma[i] * inst.pod_errors.get(j, 0)) * y[j, i]
        for j in active_pods for i in range(n)
    )
    # Penalidade de migração: aplica-se a pods que já tinham alocação anterior
    custo_migracao = gp.quicksum(
        inst.omega * (1 - y[j, previous_alloc[j]])
        for j in active_pods if j in previous_alloc
    )

    model.setObjective(custo_abertura + custo_alocacao + custo_migracao, GRB.MINIMIZE)

    if start_alloc is not None:
        start_nodes = set(start_alloc.values())
        for i in range(n):
            x[i].Start = 1.0 if i in start_nodes else 0.0
        for j in active_pods:
            for i in range(n):
                y[j, i].Start = 1.0 if start_alloc.get(j) == i else 0.0

        # Limite de evicções por ciclo do Descheduler
        if max_moves is not None:
            model.addConstr(
                gp.quicksum(1 - y[j, start_alloc[j]] for j in active_pods if j in start_alloc)
                <= max_moves
            )

    model.optimize()

    elapsed_ms = (time.time() - t0) * 1000

    if model.Status not in (GRB.OPTIMAL, GRB.TIME_LIMIT) or model.SolCount == 0:
        return {
            "alloc": {}, "nodes_open": set(), "cost": None,
            "time_ms": elapsed_ms, "status": f"FAILED({model.Status})",
        }

    alloc = {}
    for j in active_pods:
        for i in range(n):
            if y[j, i].X > 0.5:
                alloc[j] = i
                break

    nodes_open = {i for i in range(n) if x[i].X > 0.5}
    status = "OPTIMAL" if model.Status == GRB.OPTIMAL else "TIME_LIMIT"

    return {
        "alloc": alloc, "nodes_open": nodes_open, "cost": model.ObjVal,
        "time_ms": elapsed_ms, "status": status,
        "mip_gap": model.MIPGap if model.SolCount > 0 else None,
    }
