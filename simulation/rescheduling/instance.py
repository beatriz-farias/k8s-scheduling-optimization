"""
Gerador de instâncias multi-período para o problema de escalonamento
dinâmico de containers.

Cada instância é uma sequência de T períodos; em cada período, um
subconjunto de pods está ativo. A cada período, alguns pods saem e outros
entram (churn), simulando a dinâmica de um cluster real.

Uso:
    from rescheduling.instance import generate_instance
    inst = generate_instance(n_nodes=20, n_pods_total=100, n_periods=20, seed=100)
"""

import random
from dataclasses import dataclass, field


@dataclass
class Instance:
    n_nodes: int
    n_periods: int
    alpha: list          # custo de abertura do nó i
    capacity: list       # capacidade do nó i
    periods_active_pods: list = field(default_factory=list)
    pod_demand: dict = field(default_factory=dict)
    # Demandas de pods de execuções passadas (trace histórico), independentes dos
    # pods da instância; origem do M_pods da f.o. sem olhar a carga futura.
    history_demand: list = field(default_factory=list)


def generate_instance(n_nodes: int, n_pods_total: int, n_periods: int = 20,
                       seed: int = 100, churn_rate: float = 0.15,
                       ramp_fraction: float = 0.5, capacity_margin: float = 1.6,
                       history_size: int = 200, cost_model: str = "martins",
                       cost_noise: float = 0.2):
    """
    Parâmetros de custo/recurso seguem as faixas de Martins et al. (SBPO 2025):
    u_j ~ U(1,10), alpha_i ~ U(1, 4n). A capacidade não usa a faixa do artigo
    (U(m/(n+1), 2m)): é dimensionada pelo pico de demanda, ver capacity_margin.

    ramp_fraction: fração dos pods presente desde o início.
    churn_rate: fração dos pods ativos substituída a cada período.
    history_size: quantos pods tem o histórico (mesma distribuição de demanda,
    sorteio independente dos pods da instância).
    cost_model: "martins" mantém α_i ~ U(1, 4n) independente da capacidade; "proportional"
    refaz α_i proporcional à capacidade do nó × U(1 ± cost_noise), com a mesma média,
    como o preço de instâncias na nuvem.
    capacity_margin: capacidade total / demanda média no pico de pods ativos.
    Com folga (1,6) todos os pods cabem; perto de 1,0 sobram pods Pending e a
    prioridade de admissão da f.o. passa a decidir.
    """
    rng = random.Random(seed)
    m, n = n_pods_total, n_nodes

    alpha = [rng.uniform(1, 4 * n) for _ in range(n)]

    pod_demand = {j: rng.uniform(1, 10) for j in range(m)}

    # Histórico com gerador próprio: não altera o sorteio da instância.
    history_rng = random.Random(f"historico-{seed}")
    history_demand = [history_rng.uniform(1, 10) for _ in range(history_size)]

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

    # Capacidade dimensionada pelo pico de demanda agregada, com margem (a
    # fórmula estática de Martins et al. pode ser infactível no cenário
    # multi-período).
    peak_active = max(len(p) for p in periods_active_pods)
    avg_pod_demand = 5.5
    target_total_capacity = peak_active * avg_pod_demand * capacity_margin
    target_per_node = target_total_capacity / n
    capacity = [rng.uniform(0.6, 1.4) * target_per_node for _ in range(n)]

    if cost_model == "proportional":
        alpha = _proportional_costs(alpha, capacity, cost_noise, seed)
    elif cost_model != "martins":
        raise ValueError(f"cost_model desconhecido: {cost_model!r}")

    return Instance(
        n_nodes=n_nodes,
        n_periods=n_periods,
        alpha=alpha, capacity=capacity,
        periods_active_pods=periods_active_pods,
        pod_demand=pod_demand,
        history_demand=history_demand,
    )


def _proportional_costs(alpha: list, capacity: list, noise: float, seed: int) -> list:
    """Custos proporcionais à capacidade, mantendo a média de `alpha` (e, com ela, a
    escala do ω). Gerador próprio, para não alterar o sorteio da instância."""
    rng = random.Random(f"custo-{seed}")
    scale = (sum(alpha) / len(alpha)) / (sum(capacity) / len(capacity))
    return [scale * cap * rng.uniform(1 - noise, 1 + noise) for cap in capacity]


if __name__ == "__main__":
    inst = generate_instance(n_nodes=10, n_pods_total=50, n_periods=20, seed=100)
    print(f"Nós: {inst.n_nodes} | Períodos: {inst.n_periods}")
    for t, pods in enumerate(inst.periods_active_pods):
        print(f"  período {t}: {len(pods)} pods ativos")
