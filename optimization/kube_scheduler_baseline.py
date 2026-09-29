"""
Simulação do kube-scheduler padrão com scoring real "least-requested"
(prioriza nós com mais capacidade livre relativa). Diferente do MILP e das
heurísticas propostas, não conhece o custo de abertura de nós, não otimiza
quantidade de nós ativos, e não tem noção de migração (recalcula tudo do
zero a cada período). Usado como baseline realista, substituindo a
simulação por distribuição aleatória do artigo original.
"""

import time

from instance_generator import Instance


def score_least_requested(node_id: int, capacity: list, used: list) -> float:
    """Maior capacidade livre relativa = maior score."""
    return (capacity[node_id] - used[node_id]) / capacity[node_id]


def solve_period_kube_scheduler(inst: Instance, active_pods: list,
                                 score_fn=score_least_requested):
    """Filtra nós viáveis e escolhe o de maior score, pod a pod.
    Retorna dict no mesmo formato de milp_model.solve_period."""
    t0 = time.time()
    n = inst.n_nodes

    used = [0.0] * n
    alloc = {}
    failed_pods = []

    for j in active_pods:
        demand = inst.pod_demand[j]

        feasible = [i for i in range(n) if used[i] + demand <= inst.capacity[i]]

        if not feasible:
            failed_pods.append(j)
            continue

        best_node = max(feasible, key=lambda i: score_fn(i, inst.capacity, used))

        alloc[j] = best_node
        used[best_node] += demand

    nodes_open = {i for i in range(n) if used[i] > 0}

    # Custo calculado com a mesma função objetivo do MILP (comparação justa)
    cost = sum(inst.alpha[i] for i in nodes_open)
    cost += sum(inst.beta[alloc[j]] for j in alloc)
    cost += sum(inst.gamma[alloc[j]] * inst.pod_errors.get(j, 0) for j in alloc)

    elapsed_ms = (time.time() - t0) * 1000
    status = "OPTIMAL" if not failed_pods else f"INFEASIBLE({len(failed_pods)} pods sem no)"

    return {
        "alloc": alloc, "nodes_open": nodes_open, "cost": cost,
        "time_ms": elapsed_ms, "status": status, "failed_pods": failed_pods,
    }


def solve_full_horizon_kube_scheduler(inst: Instance, score_fn=score_least_requested,
                                       verbose: bool = False):
    """Roda o kube-scheduler simulado por todos os períodos. Como ele
    recalcula do zero a cada período, toda mudança de nó entre períodos
    conta como migração (mesmo sem o scheduler ter noção disso)."""
    previous_alloc = {}
    results_per_period = []
    total_cost = 0.0
    total_time_ms = 0.0
    total_migrations = 0
    total_failed = 0

    for t, active_pods in enumerate(inst.periods_active_pods):
        res = solve_period_kube_scheduler(inst, active_pods, score_fn=score_fn)

        migrations = sum(
            1 for j, node in res["alloc"].items()
            if j in previous_alloc and previous_alloc[j] != node
        )
        total_migrations += migrations
        total_failed += len(res["failed_pods"])

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
            print(f"  período {t:2d}: {len(active_pods):3d} pods | "
                  f"custo {res['cost']:8.1f} | migrações {migrations:2d} | "
                  f"{res['time_ms']:6.2f}ms | {res['status']}")

    return {
        "results_per_period": results_per_period,
        "total_cost": total_cost,
        "total_time_ms": total_time_ms,
        "total_migrations": total_migrations,
        "total_failed_pods": total_failed,
    }


if __name__ == "__main__":
    from instance_generator import generate_instance

    inst = generate_instance(n_nodes=10, n_pods_total=50, n_periods=20, seed=100)
    print(f"Instância: {inst.n_nodes} nós, omega={inst.omega:.2f}")
    print("Simulando Kube-scheduler (least-requested)...\n")

    result = solve_full_horizon_kube_scheduler(inst, verbose=True)

    print(f"\nCusto total (20 períodos): {result['total_cost']:.2f}")
    print(f"Tempo total: {result['total_time_ms']:.2f} ms")
    print(f"Migrações totais: {result['total_migrations']}")
    print(f"Pods não alocados: {result['total_failed_pods']}")
