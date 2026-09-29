"""
Gerador de instâncias multi-período para o problema de escalonamento
dinâmico de containers com penalidade de migração (omega).

Cada instância é uma sequência de T períodos; em cada período, um
subconjunto de pods está ativo. A cada período, alguns pods saem e outros
entram (churn), simulando a dinâmica de um cluster real.

Uso:
    from instance_generator import generate_instance
    inst = generate_instance(n_nodes=20, n_pods_total=100, n_periods=20, seed=100)
"""

import random
from dataclasses import dataclass, field


@dataclass
class Instance:
    n_nodes: int
    n_periods: int
    alpha: list          # custo de abertura do nó i
    beta: list           # custo de alocação no nó i
    gamma: list          # penalidade por falhas no nó i
    capacity: list       # capacidade do nó i
    omega: float         # penalidade de migração
    periods_active_pods: list = field(default_factory=list)
    pod_demand: dict = field(default_factory=dict)
    pod_errors: dict = field(default_factory=dict)


def generate_instance(n_nodes: int, n_pods_total: int, n_periods: int = 20,
                       omega: float = None, seed: int = 100,
                       churn_rate: float = 0.15, ramp_fraction: float = 0.5,
                       enable_errors: bool = False):
    """
    Parâmetros de custo/recurso seguem as faixas de Martins et al. (2023):
    U_i ~ U(m/(n+1), 2n), u_j ~ U(1,10), alpha_i/beta_i ~ U(1, 4n).

    ramp_fraction: fração dos pods presente desde o início.
    churn_rate: fração dos pods ativos substituída a cada período.
    omega: penalidade de migração; se None, usa metade do beta médio.
    """
    rng = random.Random(seed)
    m, n = n_pods_total, n_nodes

    alpha = [rng.uniform(1, 4 * n) for _ in range(n)]
    beta = [rng.uniform(1, 4 * n) for _ in range(n)]
    gamma = [rng.uniform(0.5, 2) if enable_errors else 0.0 for _ in range(n)]

    if omega is None:
        omega = 0.5 * (sum(beta) / len(beta))

    pod_demand = {j: rng.uniform(1, 10) for j in range(m)}
    pod_errors = {j: (rng.randint(0, 3) if enable_errors else 0) for j in range(m)}

    n_initial = max(1, int(m * ramp_fraction))
    all_pod_ids = list(range(m))
    rng.shuffle(all_pod_ids)

    active = set(all_pod_ids[:n_initial])
    not_yet_arrived = all_pod_ids[n_initial:]
    periods_active_pods = [sorted(active)]

    n_new_per_period = max(1, len(not_yet_arrived) // max(1, (n_periods - 1))) \
        if not_yet_arrived else 0

    for t in range(1, n_periods):
        # Pods que saem voltam ao pool de espera (podem retornar depois),
        # evitando esvaziamento progressivo do cluster.
        n_leave = int(len(active) * churn_rate)
        if n_leave > 0 and len(active) > n_leave:
            leaving = set(rng.sample(sorted(active), n_leave))
            active -= leaving
            not_yet_arrived.extend(leaving)
            rng.shuffle(not_yet_arrived)

        n_new = min(n_new_per_period, len(not_yet_arrived))
        if n_new > 0:
            arriving = not_yet_arrived[:n_new]
            not_yet_arrived = not_yet_arrived[n_new:]
            active |= set(arriving)

        periods_active_pods.append(sorted(active))

    # Capacidade dimensionada pelo pico de demanda agregada, com margem de
    # segurança (a fórmula estática original pode ser infactível no cenário
    # multi-período — ver static_instance_generator.py para o caso puro).
    peak_active = max(len(p) for p in periods_active_pods)
    avg_pod_demand = 5.5
    safety_margin = 1.6
    target_total_capacity = peak_active * avg_pod_demand * safety_margin
    target_per_node = target_total_capacity / n
    capacity = [rng.uniform(0.6, 1.4) * target_per_node for _ in range(n)]

    return Instance(
        n_nodes=n_nodes,
        n_periods=n_periods,
        alpha=alpha, beta=beta, gamma=gamma, capacity=capacity,
        omega=omega,
        periods_active_pods=periods_active_pods,
        pod_demand=pod_demand,
        pod_errors=pod_errors,
    )


if __name__ == "__main__":
    inst = generate_instance(n_nodes=10, n_pods_total=50, n_periods=20, seed=100)
    print(f"Nós: {inst.n_nodes} | Períodos: {inst.n_periods} | Omega: {inst.omega:.2f}")
    for t, pods in enumerate(inst.periods_active_pods):
        print(f"  período {t}: {len(pods)} pods ativos")
