"""Custo de um período: C_t = infraestrutura + ω·evicções + M·Pending."""

from dataclasses import dataclass

from instance_generator import Instance

EMPTY_NODE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class PeriodCost:
    infrastructure: float
    disruption: float
    pending: float

    @property
    def total(self) -> float:
        return self.infrastructure + self.disruption + self.pending


class CostModel:
    def __init__(self, instance: Instance):
        self.instance = instance
        self.pending_penalty = self._pending_penalty()

    def _pending_penalty(self) -> float:
        """M: 10x o maior custo possível de alocar um pod (abrir o nó mais caro
        + alocar no nó mais caro + maior penalidade de erro)."""
        instance = self.instance
        max_errors = max(instance.pod_errors.values(), default=0)
        return 10 * (max(instance.alpha) + max(instance.beta) + max(instance.gamma) * max_errors)

    def marginal_cost(self, pod: int, node: int, node_is_open: bool) -> float:
        """Custo de infraestrutura de colocar o pod no nó: α se o nó ainda
        não está aberto, mais β + γ·erros do pod. A disrupção (ω) não entra:
        é cobrada por evicção, não por posição."""
        instance = self.instance
        cost = 0.0 if node_is_open else instance.alpha[node]
        cost += instance.beta[node] + instance.gamma[node] * instance.pod_errors.get(pod, 0)
        return cost

    def move_delta(self, pod: int, current: int, destination: int, used: list) -> float:
        """Variação do custo de infraestrutura ao mover o pod de `current` para
        `destination`, dada a ocupação `used`. Negativo = mover reduz o custo.
        Não verifica capacidade do destino."""
        instance = self.instance
        demand = instance.pod_demand[pod]
        cost_current = self.marginal_cost(pod, current, True)
        cost_destination = self.marginal_cost(pod, destination, used[destination] != 0)
        delta = cost_destination - cost_current
        if used[current] - demand <= EMPTY_NODE_TOLERANCE:
            delta -= instance.alpha[current]
        return delta

    def infrastructure(self, allocation: dict) -> float:
        """Σ α_i dos nós abertos + Σ (β_i + γ_i·e_j) dos pods alocados."""
        instance = self.instance
        cost = sum(instance.alpha[node] for node in set(allocation.values()))
        cost += sum(instance.beta[allocation[pod]]
                    + instance.gamma[allocation[pod]] * instance.pod_errors.get(pod, 0)
                    for pod in allocation)
        return cost

    def period(self, allocation: dict, evictions: int, pending: int) -> PeriodCost:
        return PeriodCost(
            infrastructure=self.infrastructure(allocation),
            disruption=self.instance.omega * evictions,
            pending=self.pending_penalty * pending,
        )
