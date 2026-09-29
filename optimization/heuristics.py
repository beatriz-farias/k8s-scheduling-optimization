"""
Heurísticas para o escalonamento dinâmico com penalidade de migração
(omega), adaptadas de "Abordagens Heurísticas para o Problema de
Escalonamento de Contêineres em Orquestradores Kubernetes"
(Martins, Moura, Alvim, Lucena — SBPO 2025).

O custo marginal do artigo original tem 3 componentes (abertura, alocação,
erro); aqui adicionamos um quarto (migração), que entra tanto na decisão
gulosa quanto no delta de custo da busca local.

Implementados: constructive_greedy (Alg. 1), local_search (Alg. 2),
grasp (Alg. 3) — todos com omega.
"""

import random
import time
import math

from instance_generator import Instance


def marginal_cost(inst: Instance, node: int, pod: int, node_is_open: bool,
                   previous_alloc: dict) -> float:
    """
    custo = alpha_i (se o nó ainda não está aberto)
          + beta_i + gamma_i * erros_pod
          + omega, se o pod estava em outro nó no período anterior
    """
    cost = 0.0 if node_is_open else inst.alpha[node]
    cost += inst.beta[node] + inst.gamma[node] * inst.pod_errors.get(pod, 0)

    if pod in previous_alloc and previous_alloc[pod] != node:
        cost += inst.omega

    return cost


def solution_total_cost(inst: Instance, alloc: dict, previous_alloc: dict) -> float:
    """Custo total da solução (Eq. 2 do artigo, estendida com omega)."""
    nodes_open = set(alloc.values())
    cost = sum(inst.alpha[i] for i in nodes_open)
    cost += sum(inst.beta[alloc[j]] + inst.gamma[alloc[j]] * inst.pod_errors.get(j, 0)
                for j in alloc)
    cost += sum(inst.omega for j in alloc
                if j in previous_alloc and previous_alloc[j] != alloc[j])
    return cost


# --- 1) Heurística Construtiva Gulosa (Alg. 1) ---

def constructive_greedy(inst: Instance, active_pods: list, previous_alloc: dict,
                         node_order: list = None):
    """Aloca cada pod ao nó de menor custo marginal viável.
    node_order: ordem de varredura dos nós (usada pelo GRASP); padrão = natural."""
    n = inst.n_nodes
    used = [0.0] * n
    open_nodes = set()
    alloc = {}

    nodes = node_order if node_order is not None else list(range(n))

    for j in active_pods:
        demand = inst.pod_demand[j]
        best_node, best_cost = None, float("inf")

        for i in nodes:
            if used[i] + demand > inst.capacity[i]:
                continue
            cost = marginal_cost(inst, i, j, i in open_nodes, previous_alloc)
            if cost < best_cost:
                best_cost, best_node = cost, i

        if best_node is not None:
            alloc[j] = best_node
            used[best_node] += demand
            open_nodes.add(best_node)

    return alloc, used


def constructive_greedy_randomized_uniform(inst: Instance, active_pods: list,
                                            previous_alloc: dict, rcl_alpha: float,
                                            rng: random.Random):
    """RCL classica (Secao 4.4 do artigo): escolha uniforme entre os
    rcl_alpha% melhores nos. No cenario dinamico, ignora o tamanho da
    vantagem de custo entre candidatos -- quando "ficar onde esta" domina
    fortemente as alternativas (por causa de omega), a escolha uniforme
    ainda tem chance real de mover o pod sem necessidade. Ver
    constructive_greedy_randomized_weighted para a correcao."""
    n = inst.n_nodes
    used = [0.0] * n
    open_nodes = set()
    alloc = {}

    for j in active_pods:
        demand = inst.pod_demand[j]
        candidates = []

        for i in range(n):
            if used[i] + demand > inst.capacity[i]:
                continue
            cost = marginal_cost(inst, i, j, i in open_nodes, previous_alloc)
            candidates.append((cost, i))

        if not candidates:
            continue

        candidates.sort(key=lambda c: c[0])
        rcl_size = max(1, int(len(candidates) * rcl_alpha))
        rcl = candidates[:rcl_size]
        _, chosen_node = rng.choice(rcl)

        alloc[j] = chosen_node
        used[chosen_node] += demand
        open_nodes.add(chosen_node)

    return alloc, used


def constructive_greedy_randomized_weighted(inst: Instance, active_pods: list,
                                             previous_alloc: dict, rcl_alpha: float,
                                             rng: random.Random, temperature: float = 1.0):
    """RCL ponderada por custo (softmax invertido): favorece fortemente o
    candidato mais barato quando ha uma vantagem grande sobre os demais
    (tipico quando omega faz "ficar onde esta" dominar), mas ainda permite
    exploracao quando os custos dos candidatos sao parecidos. temperature
    menor = mais deterministico; temperature maior = aproxima-se da
    escolha uniforme."""
    n = inst.n_nodes
    used = [0.0] * n
    open_nodes = set()
    alloc = {}

    for j in active_pods:
        demand = inst.pod_demand[j]
        candidates = []

        for i in range(n):
            if used[i] + demand > inst.capacity[i]:
                continue
            cost = marginal_cost(inst, i, j, i in open_nodes, previous_alloc)
            candidates.append((cost, i))

        if not candidates:
            continue

        candidates.sort(key=lambda c: c[0])
        rcl_size = max(1, int(len(candidates) * rcl_alpha))
        rcl = candidates[:rcl_size]

        min_cost = rcl[0][0]
        weights = [math.exp(-(c - min_cost) / max(temperature, 1e-6)) for c, _ in rcl]
        chosen_idx = rng.choices(range(len(rcl)), weights=weights, k=1)[0]
        _, chosen_node = rcl[chosen_idx]

        alloc[j] = chosen_node
        used[chosen_node] += demand
        open_nodes.add(chosen_node)

    return alloc, used


# --- 2) Busca Local com Melhor Melhoria (Alg. 2) ---

def compute_move_delta(inst: Instance, pod: int, current_node: int, dest_node: int,
                        used: list, previous_alloc: dict) -> float:
    """
    Calcula o delta de custo de mover `pod` de `current_node` para
    `dest_node`, dado o estado atual de ocupação (`used`) e o histórico de
    alocação anterior (para o termo omega). Delta negativo = movimento
    reduz o custo total (vale a pena mover).

    Esta função avalia UM movimento isolado, sem varrer outros pods ou
    nós — é a peça reutilizável tanto pela busca local (que a chama em
    loop, escaneando todos os pods/nós candidatos) quanto por um futuro
    Descheduler real, que perguntaria "vale a pena mover ESTE pod agora?"
    pod a pod, em background, sem ter uma lista fechada de "todos os pods
    do período" como a simulação offline tem.

    Não verifica capacidade do nó de destino — isso é responsabilidade de
    quem chama.
    """
    demand = inst.pod_demand[pod]
    cost_current = marginal_cost(inst, current_node, pod, True, previous_alloc)

    node_will_open = used[dest_node] == 0
    cost_dest = marginal_cost(inst, dest_node, pod, not node_will_open, previous_alloc)

    will_close_current = (used[current_node] - demand) <= 1e-9
    delta = cost_dest - cost_current
    if will_close_current:
        delta -= inst.alpha[current_node]

    return delta


def local_search(inst: Instance, alloc: dict, used: list, active_pods: list,
                  previous_alloc: dict, max_iterations: int = None):
    """
    Vizinhança "mover um pod para outro nó"; aplica a maior redução de
    custo a cada iteração até convergir (usa compute_move_delta para
    avaliar cada movimento candidato).

    max_iterations padrão = 5*m (m = pods ativos): o artigo demonstra teto
    teórico O(m) no pior caso; com omega, deltas próximos de zero podem
    gerar oscilação por ponto flutuante, então mantemos essa margem como
    limite de segurança.
    """
    alloc = dict(alloc)
    used = list(used)
    n = inst.n_nodes
    iteration = 0

    if max_iterations is None:
        max_iterations = 5 * max(1, len(active_pods))

    EPS = 1e-6

    while iteration < max_iterations:
        iteration += 1
        best_delta, best_pod, best_dest = -EPS, None, None

        for j in active_pods:
            current_node = alloc[j]
            demand = inst.pod_demand[j]

            for i in range(n):
                if i == current_node:
                    continue
                if used[i] + demand > inst.capacity[i]:
                    continue

                delta = compute_move_delta(inst, j, current_node, i, used, previous_alloc)

                if delta < best_delta - EPS:
                    best_delta, best_pod, best_dest = delta, j, i

        if best_pod is None:
            break

        old_node = alloc[best_pod]
        demand = inst.pod_demand[best_pod]
        used[old_node] -= demand
        used[best_dest] += demand
        alloc[best_pod] = best_dest

    return alloc, used


# --- 3) Meta-heurística GRASP (Alg. 3) ---

def grasp(inst: Instance, active_pods: list, previous_alloc: dict,
          max_iter: int = 10, rcl_alpha: float = 0.3,
          local_search_max_iter: int = None, seed: int = None,
          weighted: bool = True, temperature: float = 1.0):
    """GRASP: multi-inicio (construcao aleatorizada + busca local).
    weighted=True (padrao): usa a RCL ponderada por custo, que corrige a
    falha da RCL uniforme classica no cenario dinamico (ver
    constructive_greedy_randomized_weighted). weighted=False reproduz o
    comportamento original do artigo (Secao 4.4), util para comparacao."""
    rng = random.Random(seed)
    best_alloc, best_cost = None, float("inf")

    for _ in range(max_iter):
        if weighted:
            alloc, used = constructive_greedy_randomized_weighted(
                inst, active_pods, previous_alloc, rcl_alpha, rng, temperature
            )
        else:
            alloc, used = constructive_greedy_randomized_uniform(
                inst, active_pods, previous_alloc, rcl_alpha, rng
            )
        alloc, used = local_search(
            inst, alloc, used, active_pods, previous_alloc,
            max_iterations=local_search_max_iter,
        )
        cost = solution_total_cost(inst, alloc, previous_alloc)

        if cost < best_cost:
            best_cost, best_alloc = cost, alloc

    return best_alloc, best_cost


# --- Runners de horizonte completo (mesma interface de milp_model.py) ---

def _run_full_horizon(inst: Instance, period_solver, verbose: bool = False,
                       label: str = ""):
    previous_alloc = {}
    results_per_period = []
    total_cost = 0.0
    total_time_ms = 0.0
    total_migrations = 0

    for t, active_pods in enumerate(inst.periods_active_pods):
        t0 = time.time()
        alloc = period_solver(active_pods, previous_alloc)
        elapsed_ms = (time.time() - t0) * 1000

        cost = solution_total_cost(inst, alloc, previous_alloc)
        migrations = sum(
            1 for j, node in alloc.items()
            if j in previous_alloc and previous_alloc[j] != node
        )
        total_migrations += migrations

        results_per_period.append({
            "period": t, "n_active_pods": len(active_pods),
            "n_nodes_open": len(set(alloc.values())),
            "cost": cost, "time_ms": elapsed_ms, "migrations": migrations,
            "status": "OK",
        })
        total_cost += cost
        total_time_ms += elapsed_ms
        previous_alloc = alloc

        if verbose:
            print(f"  [{label}] período {t:2d}: {len(active_pods):3d} pods | "
                  f"custo {cost:8.1f} | migrações {migrations:2d} | "
                  f"{elapsed_ms:7.2f}ms")

    return {
        "results_per_period": results_per_period,
        "total_cost": total_cost,
        "total_time_ms": total_time_ms,
        "total_migrations": total_migrations,
    }


def solve_full_horizon_greedy(inst: Instance, verbose: bool = False):
    def solver(active_pods, previous_alloc):
        alloc, _ = constructive_greedy(inst, active_pods, previous_alloc)
        return alloc
    return _run_full_horizon(inst, solver, verbose, label="Gulosa")


def solve_full_horizon_local_search(inst: Instance, verbose: bool = False):
    def solver(active_pods, previous_alloc):
        alloc, used = constructive_greedy(inst, active_pods, previous_alloc)
        alloc, _ = local_search(inst, alloc, used, active_pods, previous_alloc)
        return alloc
    return _run_full_horizon(inst, solver, verbose, label="BuscaLocal")


def solve_full_horizon_grasp(inst: Instance, max_iter: int = 10,
                              rcl_alpha: float = 0.3, seed: int = 100,
                              weighted: bool = True, temperature: float = 1.0,
                              verbose: bool = False):
    def solver(active_pods, previous_alloc):
        alloc, _ = grasp(inst, active_pods, previous_alloc,
                          max_iter=max_iter, rcl_alpha=rcl_alpha, seed=seed,
                          weighted=weighted, temperature=temperature)
        return alloc
    return _run_full_horizon(inst, solver, verbose, label="GRASP")


if __name__ == "__main__":
    from instance_generator import generate_instance

    inst = generate_instance(n_nodes=10, n_pods_total=50, n_periods=20, seed=100)
    print(f"Instância: {inst.n_nodes} nós, omega={inst.omega:.2f}\n")

    print("== Heurística Construtiva Gulosa ==")
    r1 = solve_full_horizon_greedy(inst, verbose=False)
    print(f"Custo total: {r1['total_cost']:.2f} | Tempo: {r1['total_time_ms']:.2f}ms | "
          f"Migrações: {r1['total_migrations']}\n")

    print("== Busca Local (a partir da construtiva) ==")
    r2 = solve_full_horizon_local_search(inst, verbose=False)
    print(f"Custo total: {r2['total_cost']:.2f} | Tempo: {r2['total_time_ms']:.2f}ms | "
          f"Migrações: {r2['total_migrations']}\n")

    print("== GRASP (10 iterações) ==")
    r3 = solve_full_horizon_grasp(inst, max_iter=10, seed=100, verbose=False)
    print(f"Custo total: {r3['total_cost']:.2f} | Tempo: {r3['total_time_ms']:.2f}ms | "
          f"Migrações: {r3['total_migrations']}")
