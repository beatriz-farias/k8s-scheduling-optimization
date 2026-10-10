"""MILP da f.o. (Gurobi): otimização lexicográfica em dois passos.

Passo 1: maximiza a admissão A = Σ_j w_j·a_j.
Passo 2: minimiza C = Σ c_i·x_i + λ·Σ c_i·F_i + Σ ω_j·ev_j com a restrição
         Σ_j w_j·a_j ≥ A* (o ótimo do passo 1).

Fragmentação linearizada. Para cada nó i e tipo de pod m (frequência p_m):
    z_im ∈ {0,1}, com free_ir ≥ req_mr·z_im para todo recurso r (z = 1 só se o tipo cabe)
    w_im ≥ frac_livre_i − z_im, w_im ≥ 0
    F_i = Σ_m p_m·w_im
Como z = 1 só custa zero, o solver o liga sempre que o tipo cabe; assim w_im é
exatamente frac_livre_i quando o tipo não cabe e 0 quando cabe. Nó desligado
tem livre 0 e portanto F = 0.
"""

import gurobipy as gp
from gurobipy import GRB

from ..objective import EMPTY_NODE_TOLERANCE

ADMISSION_TOLERANCE = 1e-6


def _fragmentation_expr(model, objective, free):
    """λ·Σ_i c_i·F_i. free[i][r] é a expressão linear do livre do nó i no recurso r."""
    n_resources = len(objective.resource_names)
    terms = []
    for node, free_node in enumerate(free):
        capacity = objective.capacities(node)
        free_fraction = gp.quicksum(free_node[r] / capacity[r]
                                    for r in range(n_resources)) / n_resources
        for pod_type in objective.distribution.types:
            fits = model.addVar(vtype=GRB.BINARY)
            for r in range(n_resources):
                model.addConstr(free_node[r] >= pod_type.request[r] * fits)
            misfit = model.addVar(lb=0.0)
            model.addConstr(misfit >= free_fraction - fits)
            terms.append(objective.node_costs[node] * pod_type.frequency * misfit)
    return objective.lam * gp.quicksum(terms)


def _new_model(name, mip_gap, time_limit):
    model = gp.Model(name)
    model.Params.OutputFlag = 0
    model.Params.MIPGap = mip_gap
    model.Params.TimeLimit = time_limit
    return model


def _has_solution(model) -> bool:
    return model.SolCount > 0


def _lexicographic(model, admission, efficiency, variables):
    """Passo 1 (max admissão) e passo 2 (min eficiência com admissão ≥ A*).
    False se o passo 1 não achou solução; se o passo 2 falhar, vale a
    solução do passo 1 (valores já lidos antes pelo chamador via `snapshot`)."""
    model.setObjective(admission, GRB.MAXIMIZE)
    model.optimize()
    if not _has_solution(model):
        return None
    best_admission = model.ObjVal
    snapshot = {var: var.X for var in variables}
    for var, value in snapshot.items():
        var.Start = value
    model.addConstr(admission >= best_admission - ADMISSION_TOLERANCE)
    model.setObjective(efficiency, GRB.MINIMIZE)
    model.optimize()
    if _has_solution(model):
        return {var: var.X for var in variables}
    return snapshot


def solve_queue(objective, pods, state, mip_gap: float, time_limit: float):
    """Scheduler: coloca a fila `pods` com os pods que já rodam fixos.
    Retorna {pod: nó} dos pods admitidos, ou None se o solver falhou."""
    instance = objective.instance
    nodes = range(instance.n_nodes)
    resources = range(len(objective.resource_names))
    closed = [i for i in nodes if not any(u > EMPTY_NODE_TOLERANCE
                                          for u in objective.usage(state, i))]

    model = _new_model("milp_scheduler_new_fo", mip_gap, time_limit)
    y = model.addVars(pods, nodes, vtype=GRB.BINARY)
    pending = model.addVars(pods, vtype=GRB.BINARY)
    opened = model.addVars(closed, vtype=GRB.BINARY)

    free = []
    for i in nodes:
        capacity, used = objective.capacities(i), objective.usage(state, i)
        switch = opened[i] if i in opened else 1
        free_node = []
        for r in resources:
            load = gp.quicksum(objective.requests(j)[r] * y[j, i] for j in pods)
            model.addConstr(load <= capacity[r] * switch - used[r])
            free_node.append(capacity[r] * switch - used[r] - load)
        free.append(free_node)
    for j in pods:
        model.addConstr(gp.quicksum(y[j, i] for i in nodes) + pending[j] == 1)

    admission = gp.quicksum(objective.weights[j] * (1 - pending[j]) for j in pods)
    efficiency = (gp.quicksum(objective.node_costs[i] * opened[i] for i in closed)
                  + _fragmentation_expr(model, objective, free))

    values = _lexicographic(model, admission, efficiency, list(y.values()))
    if values is None:
        return None
    return {j: i for j in pods for i in nodes if values[y[j, i]] > 0.5}


def plan_moves(objective, state, max_moves, mip_gap: float, time_limit: float):
    """Descheduler: realocação ótima dos pods em execução com no máximo
    `max_moves` pods movidos (cada um paga ω_j). Os pods em execução continuam
    todos admitidos, então A é constante e o passo 1 é trivial: resolve só o
    passo 2. Retorna {pod: nó} ou None se o solver falhou."""
    instance = objective.instance
    nodes = range(instance.n_nodes)
    resources = range(len(objective.resource_names))
    pods = state.pods()

    model = _new_model("milp_descheduler_new_fo", mip_gap, time_limit)
    x = model.addVars(nodes, vtype=GRB.BINARY)
    y = model.addVars(pods, nodes, vtype=GRB.BINARY)
    moved = model.addVars(pods, lb=0.0, ub=1.0)

    free = []
    for i in nodes:
        capacity = objective.capacities(i)
        free_node = []
        for r in resources:
            load = gp.quicksum(objective.requests(j)[r] * y[j, i] for j in pods)
            model.addConstr(load <= capacity[r] * x[i])
            free_node.append(capacity[r] * x[i] - load)
        free.append(free_node)
    for j in pods:
        model.addConstr(gp.quicksum(y[j, i] for i in nodes) == 1)
        model.addConstr(moved[j] >= 1 - y[j, state.node_of(j)])
    if max_moves is not None:
        model.addConstr(moved.sum() <= max_moves)

    current_nodes = set(state.allocation.values())
    for i in nodes:
        x[i].Start = 1.0 if i in current_nodes else 0.0
    for j in pods:
        for i in nodes:
            y[j, i].Start = 1.0 if state.node_of(j) == i else 0.0

    model.setObjective(
        gp.quicksum(objective.node_costs[i] * x[i] for i in nodes)
        + _fragmentation_expr(model, objective, free)
        + gp.quicksum(objective.eviction_cost(j) * moved[j] for j in pods),
        GRB.MINIMIZE)
    model.optimize()
    if not _has_solution(model):
        return None
    return {j: i for j in pods for i in nodes if y[j, i].X > 0.5}
