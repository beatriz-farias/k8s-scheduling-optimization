"""
Modelo MILP para o escalonamento de containers com penalidade de
migração (extensão de Martins et al. 2023). Resolve período a período:

    min  sum_i [ alpha_i*x_i + (beta_i+gamma_i)*sum_j y_ij ]
         + sum_i sum_{j: y_bar_ij=1} (1-y_ij)*omega

Sujeito a: capacidade por nó, cada pod alocado a exatamente 1 nó, binárias.

Uso:
    from milp_model import solve_period, solve_full_horizon
"""

import time
import gurobipy as gp
from gurobipy import GRB

from instance_generator import Instance


def solve_period(inst: Instance, active_pods: list, previous_alloc: dict,
                  mip_gap: float = 0.01, time_limit: float = None,
                  verbose: bool = False):
    """
    Resolve o MILP para um único período.

    active_pods: pods ativos neste período.
    previous_alloc: alocação do período anterior {pod_id: node_id}, usada
    no cálculo da penalidade omega.
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


def solve_full_horizon(inst: Instance, mip_gap: float = 0.01,
                        time_limit: float = None, verbose: bool = False):
    """Resolve a sequência completa de períodos, propagando a alocação
    entre períodos para o cálculo de omega."""
    previous_alloc = {}
    results_per_period = []
    total_cost = 0.0
    total_time_ms = 0.0
    total_migrations = 0

    for t, active_pods in enumerate(inst.periods_active_pods):
        res = solve_period(inst, active_pods, previous_alloc,
                            mip_gap=mip_gap, time_limit=time_limit, verbose=verbose)

        if res["cost"] is None:
            raise RuntimeError(f"Período {t} falhou ao resolver: {res['status']}")

        # Conta migrações: pods que estavam ativos antes E mudaram de nó
        migrations = sum(
            1 for j, node in res["alloc"].items()
            if j in previous_alloc and previous_alloc[j] != node
        )
        total_migrations += migrations

        results_per_period.append({
            "period": t,
            "n_active_pods": len(active_pods),
            "n_nodes_open": len(res["nodes_open"]),
            "cost": res["cost"],
            "time_ms": res["time_ms"],
            "migrations": migrations,
            "status": res["status"],
        })

        total_cost += res["cost"]
        total_time_ms += res["time_ms"]
        previous_alloc = res["alloc"]

        if verbose:
            print(f"  período {t}: {len(active_pods)} pods, "
                  f"custo={res['cost']:.1f}, migrações={migrations}, "
                  f"tempo={res['time_ms']:.0f}ms, status={res['status']}")

    return {
        "results_per_period": results_per_period,
        "total_cost": total_cost,
        "total_time_ms": total_time_ms,
        "total_migrations": total_migrations,
    }


if __name__ == "__main__":
    from instance_generator import generate_instance

    inst = generate_instance(n_nodes=10, n_pods_total=50, n_periods=20, seed=100)
    print(f"Instância: {inst.n_nodes} nós, omega={inst.omega:.2f}")
    print("Resolvendo horizonte completo (MILP exato, período a período)...\n")

    result = solve_full_horizon(inst, mip_gap=0.01, verbose=True)

    print(f"\nCusto total (20 períodos): {result['total_cost']:.2f}")
    print(f"Tempo total: {result['total_time_ms']:.0f} ms")
    print(f"Migrações totais: {result['total_migrations']}")
