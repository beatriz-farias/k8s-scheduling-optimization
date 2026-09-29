"""
Simulação da arquitetura REAL de Scheduler + Descheduler separados,
para validar o desenho antes de portar para Go (Fase 4).

Diferença em relação a heuristics.py (modelo "monolítico" usado até agora):
naquele, cada período resolve a alocação de TODOS os pods ativos do zero,
como se fosse uma decisão nova para todos. Isso não corresponde a nenhum
componente real do Kubernetes — é uma simplificação de simulação.

Aqui, cada período segue o fluxo real:
  1. SCHEDULER: decide onde colocar apenas os pods NOVOS deste período
     (que não têm alocação anterior). Pods já rodando NÃO são tocados.
     Usa marginal_cost() pod a pod — mesma lógica do plugin.go Score.
  2. DESCHEDULER: avalia, entre TODOS os pods atualmente alocados (novos
     e antigos), se vale a pena mover algum para reduzir custo. Usa
     compute_move_delta() — mesma lógica que o controller de rebalanceamento
     do Go vai implementar. Só move se a melhoria ultrapassar um limiar
     mínimo (min_improvement), e pode limitar quantos pods move por ciclo
     (max_moves_per_period) — refletindo que um Descheduler real evita
     disrupção excessiva de uma vez.
"""

import time

from instance_generator import Instance
from heuristics import marginal_cost, compute_move_delta, solution_total_cost


def schedule_new_pods(inst: Instance, new_pods: list, alloc: dict, used: list):
    """Scheduler: decide o nó de cada pod NOVO, um de cada vez, sem tocar
    em pods já alocados. Equivalente à lógica do Score plugin (gulosa)."""
    n = inst.n_nodes
    open_nodes = {alloc[j] for j in alloc}

    for j in new_pods:
        demand = inst.pod_demand[j]
        best_node, best_cost = None, float("inf")

        for i in range(n):
            if used[i] + demand > inst.capacity[i]:
                continue
            # omega nunca se aplica aqui: pod novo não tem alocação anterior
            cost = marginal_cost(inst, i, j, i in open_nodes, previous_alloc={})
            if cost < best_cost:
                best_cost, best_node = cost, i

        if best_node is not None:
            alloc[j] = best_node
            used[best_node] += demand
            open_nodes.add(best_node)
        # se nenhum no viavel, pod fica sem alocacao (equivalente a Pending)

    return alloc, used


def rebalance_existing_pods(inst: Instance, active_pods: list, alloc: dict, used: list,
                             previous_alloc: dict, min_improvement: float = 1e-6,
                             max_moves_per_period: int = None):
    """Descheduler: avalia mover pods já alocados para reduzir custo, usando
    compute_move_delta pod a pod (mesma lógica reutilizável do controller
    real). Só aplica um movimento se a melhoria for maior que
    min_improvement (evita oscilação/disrupção por ganhos triviais).
    max_moves_per_period limita quantos pods são movidos neste ciclo
    (um Descheduler real não quer evictar tudo de uma vez)."""
    alloc = dict(alloc)
    used = list(used)
    n = inst.n_nodes
    moves_made = 0

    if max_moves_per_period is None:
        max_moves_per_period = 5 * max(1, len(active_pods))  # mesmo teto de local_search

    while moves_made < max_moves_per_period:
        best_delta, best_pod, best_dest = -min_improvement, None, None

        for j in active_pods:
            current_node = alloc[j]
            demand = inst.pod_demand[j]

            for i in range(n):
                if i == current_node:
                    continue
                if used[i] + demand > inst.capacity[i]:
                    continue

                delta = compute_move_delta(inst, j, current_node, i, used, previous_alloc)

                if delta < best_delta - 1e-9:
                    best_delta, best_pod, best_dest = delta, j, i

        if best_pod is None:
            break

        old_node = alloc[best_pod]
        demand = inst.pod_demand[best_pod]
        used[old_node] -= demand
        used[best_dest] += demand
        alloc[best_pod] = best_dest
        moves_made += 1

    return alloc, used, moves_made


def solve_full_horizon_incremental(inst: Instance, min_improvement: float = 1e-6,
                                    max_moves_per_period: int = None,
                                    verbose: bool = False):
    """Roda a arquitetura Scheduler + Descheduler separados por todos os
    períodos, mesma interface de retorno de heuristics.py para comparação
    direta."""
    previous_alloc = {}
    results_per_period = []
    total_cost = 0.0
    total_time_ms = 0.0
    total_migrations = 0

    for t, active_pods in enumerate(inst.periods_active_pods):
        t0 = time.time()

        active_set = set(active_pods)
        # Pods que continuam ativos mantêm a alocação anterior (Scheduler
        # nunca os toca); pods que saíram do cluster são descartados.
        alloc = {j: node for j, node in previous_alloc.items() if j in active_set}
        used = [0.0] * inst.n_nodes
        for j, node in alloc.items():
            used[node] += inst.pod_demand[j]

        new_pods = [j for j in active_pods if j not in alloc]

        # 1) Scheduler: só os pods novos
        alloc, used = schedule_new_pods(inst, new_pods, alloc, used)

        # 2) Descheduler: reavalia todos os pods atualmente alocados
        alloc, used, moves_made = rebalance_existing_pods(
            inst, list(alloc.keys()), alloc, used, previous_alloc,
            min_improvement=min_improvement, max_moves_per_period=max_moves_per_period,
        )

        elapsed_ms = (time.time() - t0) * 1000
        cost = solution_total_cost(inst, alloc, previous_alloc)
        migrations = sum(
            1 for j, node in alloc.items()
            if j in previous_alloc and previous_alloc[j] != node
        )
        total_migrations += migrations

        results_per_period.append({
            "period": t, "n_active_pods": len(active_pods),
            "n_new_pods": len(new_pods),
            "n_nodes_open": len(set(alloc.values())),
            "cost": cost, "time_ms": elapsed_ms, "migrations": migrations,
            "descheduler_moves": moves_made,
        })
        total_cost += cost
        total_time_ms += elapsed_ms
        previous_alloc = alloc

        if verbose:
            print(f"  período {t:2d}: {len(active_pods):3d} pods ({len(new_pods):2d} novos) | "
                  f"custo {cost:8.1f} | migrações {migrations:2d} "
                  f"(descheduler moveu {moves_made}) | {elapsed_ms:6.2f}ms")

    return {
        "results_per_period": results_per_period,
        "total_cost": total_cost,
        "total_time_ms": total_time_ms,
        "total_migrations": total_migrations,
    }


if __name__ == "__main__":
    from instance_generator_v1 import generate_instance
    from heuristics_v1 import solve_full_horizon_local_search

    print(f"{'N':>4} {'P':>5} | {'Monolitico':>12} {'Incremental':>12} {'delta%':>8} | "
          f"{'mono mig':>9} {'incr mig':>9}")
    print("-" * 75)

    for n_nodes, n_pods in [(10, 50), (20, 100), (20, 200), (50, 200), (50, 500)]:
        inst = generate_instance(n_nodes=n_nodes, n_pods_total=n_pods, n_periods=20, seed=100)

        r_mono = solve_full_horizon_local_search(inst)
        r_incr = solve_full_horizon_incremental(inst, min_improvement=1e-6)

        delta_pct = (r_incr["total_cost"] - r_mono["total_cost"]) / r_mono["total_cost"] * 100

        print(f"{n_nodes:>4} {n_pods:>5} | {r_mono['total_cost']:>12.0f} "
              f"{r_incr['total_cost']:>12.0f} {delta_pct:>+7.2f}% | "
              f"{r_mono['total_migrations']:>9} {r_incr['total_migrations']:>9}")
