"""Função objetivo compartilhada por Scheduler e Descheduler.

Prioridade 1 (maximizar): admissão    A_t = Σ_j w_j·a_jt
Prioridade 2 (minimizar): eficiência  C_t = Σ_i c_i·x_it + λ·Σ_i c_i·F_it + Σ_j ω_j·ev_jt

A comparação é por tupla (-A, C), sem big-M. A fragmentação F_it de um nó é a
fração livre dele ponderada pela frequência dos tipos de pod típicos que NÃO
cabem no espaço livre (ver `fragmentation`).

A instância atual tem um único recurso (a demanda u_j e a capacidade U_i). Os
ganchos `requests`, `capacities` e `usage` devolvem tuplas por recurso; para
CPU + memória basta estendê-los (e o ClusterState), o restante já é genérico.

"""

from dataclasses import dataclass
from typing import Optional, Sequence

from .instance import Instance

EMPTY_NODE_TOLERANCE = 1e-9
COMPARISON_TOLERANCE = 1e-9
DEFAULT_POD_TYPES = 5
DEFAULT_LAMBDA = 1.0
DEFAULT_OMEGA_FRACTION = 0.5
RESOURCE_NAMES = ("demanda",)


@dataclass(frozen=True)
class PodType:
    """Tipo de pod típico: requests por recurso e frequência p_m."""
    request: tuple
    frequency: float


class PodDistribution:
    """M_pods: distribuição dos pods típicos (tipos m com frequência p_m)."""

    def __init__(self, types: Sequence[PodType]):
        total = sum(t.frequency for t in types)
        self.types = [PodType(t.request, t.frequency / total) for t in types]

    @classmethod
    def from_requests(cls, requests: Sequence[tuple], n_types: int = DEFAULT_POD_TYPES):
        """Distribuição empírica: ordena os pods pelo tamanho e divide em
        `n_types` faixas de mesma contagem; cada faixa vira um tipo com o
        request médio e frequência proporcional ao tamanho da faixa."""
        ordered = sorted(requests, key=sum)
        n_types = max(1, min(n_types, len(ordered)))
        types = []
        for k in range(n_types):
            band = ordered[k * len(ordered) // n_types:(k + 1) * len(ordered) // n_types]
            mean = tuple(sum(r[i] for r in band) / len(band) for i in range(len(band[0])))
            types.append(PodType(mean, len(band)))
        return cls(types)

    @classmethod
    def from_instance(cls, instance: Instance, n_types: int = DEFAULT_POD_TYPES):
        """Origem padrão: o histórico de pods da instância (`history_demand`),
        sem usar os pods que ainda vão chegar."""
        if not instance.history_demand:
            raise ValueError("a instância não tem history_demand; informe `distribution`")
        return cls.from_requests([(d,) for d in instance.history_demand], n_types)


@dataclass(frozen=True)
class Evaluation:
    """Valor da f.o. de um estado: admissão e os três termos de C."""
    admission: float
    node_cost: float
    frag_cost: float
    disruption_cost: float

    @property
    def total(self) -> float:
        return self.node_cost + self.frag_cost + self.disruption_cost

    @property
    def key(self) -> tuple:
        """Menor é melhor: (-A, C)."""
        return (-self.admission, self.total)


def is_better(first, second) -> bool:
    """True se a avaliação `first` é estritamente melhor que `second`:
    compara as chaves lexicograficamente, com tolerância numérica."""
    for a, b in zip(first.key, second.key):
        if a < b - COMPARISON_TOLERANCE:
            return True
        if a > b + COMPARISON_TOLERANCE:
            return False
    return False


class Objective:
    resource_names = RESOURCE_NAMES

    def __init__(self, instance: Instance, lam: float = DEFAULT_LAMBDA,
                 omega=None, omega_fraction: float = DEFAULT_OMEGA_FRACTION,
                 omega_by_size: bool = False,
                 distribution: Optional[PodDistribution] = None,
                 node_costs: Optional[list] = None, n_types: int = DEFAULT_POD_TYPES):
        """lam: peso λ da fragmentação. omega: número (uniforme) ou
        dict {pod: ω_j}. Sem ele, ω = omega_fraction × c_i médio (mesma escala
        do custo dos nós); omega_by_size=True torna ω_j proporcional ao peso
        w_j do pod, mantendo a média. distribution: M_pods; se None,
        é a distribuição empírica do histórico da instância. node_costs: c_i; se
        None, reaproveita α_i."""
        self.instance = instance
        self.lam = lam
        self.distribution = distribution or PodDistribution.from_instance(instance, n_types)
        self.node_costs = list(node_costs) if node_costs is not None else list(instance.alpha)
        self._default_omega = float(omega) if isinstance(omega, (int, float)) \
            else omega_fraction * sum(self.node_costs) / len(self.node_costs)
        self._pod_omega = omega if isinstance(omega, dict) else {}
        n = instance.n_nodes
        self.mean_capacity = tuple(
            sum(self.capacities(i)[r] for i in range(n)) / n for r in range(len(RESOURCE_NAMES)))
        self.weights = {pod: self._weight(pod) for pod in instance.pod_demand}
        if omega_by_size and not self._pod_omega:
            mean_weight = sum(self.weights.values()) / len(self.weights)
            self._pod_omega = {pod: self._default_omega * weight / mean_weight
                               for pod, weight in self.weights.items()}

    # ----- ganchos de recurso (um recurso hoje) -----

    def requests(self, pod: int) -> tuple:
        return (self.instance.pod_demand[pod],)

    def capacities(self, node: int) -> tuple:
        return (self.instance.capacity[node],)

    def usage(self, state, node: int) -> tuple:
        return (state.used[node],)

    # ----- parâmetros por pod -----

    def _weight(self, pod: int) -> float:
        """w_j = max_r req_jr / cap_médio_r (recurso dominante)."""
        return max(req / cap for req, cap in zip(self.requests(pod), self.mean_capacity))

    def eviction_cost(self, pod: int) -> float:
        """ω_j: uniforme por padrão, mas aceita valores por pod."""
        return self._pod_omega.get(pod, self._default_omega)

    # ----- admissão -----

    def admission(self, state) -> float:
        """A_t = Σ_j w_j·a_jt sobre os pods alocados do estado."""
        return sum(self.weights[pod] for pod in state.allocation)

    # ----- fragmentação -----

    @staticmethod
    def _is_on(used: tuple) -> bool:
        return any(u > EMPTY_NODE_TOLERANCE for u in used)

    def _fragmentation_for(self, node: int, used: tuple, distribution: PodDistribution) -> float:
        """F para uma ocupação `used` do nó. Desligado/vazio dá 0; cheio dá 0."""
        if not self._is_on(used):
            return 0.0
        capacity = self.capacities(node)
        free = [c - u for c, u in zip(capacity, used)]
        free_fraction = sum(f / c for f, c in zip(free, capacity)) / len(capacity)
        if free_fraction <= COMPARISON_TOLERANCE:
            return 0.0
        misfit = sum(t.frequency for t in distribution.types
                     if any(req > f + COMPARISON_TOLERANCE for req, f in zip(t.request, free)))
        return misfit * free_fraction

    def fragmentation(self, node: int, state, pod_distribution: Optional[PodDistribution] = None):
        """F_it = Σ_m p_m·1[tipo m não cabe no livre de i]·frac_livre_it."""
        return self._fragmentation_for(node, self.usage(state, node),
                                       pod_distribution or self.distribution)

    # ----- custo -----

    def cost(self, prev_state, state, evicted=None, active_pods=None) -> tuple:
        """(node_cost, frag_cost, disruption_cost) do estado `state`.

        evicted: pods reiniciados no período (cada um paga ω_j, mesmo que
        volte ao mesmo nó, como no Descheduler real). Se None, deriva de
        prev_state: pods que continuam existindo (active_pods; se None, os
        que estão em `state`) e mudaram de nó ou saíram do nó."""
        node_cost = frag_cost = 0.0
        for node in range(self.instance.n_nodes):
            used = self.usage(state, node)
            if self._is_on(used):
                node_cost += self.node_costs[node]
                frag_cost += self.node_costs[node] * self._fragmentation_for(
                    node, used, self.distribution)
        if evicted is None:
            evicted = self._derive_evictions(prev_state, state, active_pods)
        disruption = sum(self.eviction_cost(pod) for pod in evicted)
        return node_cost, self.lam * frag_cost, disruption

    @staticmethod
    def _derive_evictions(prev_state, state, active_pods) -> list:
        surviving = set(active_pods) if active_pods is not None else set(state.allocation)
        return [pod for pod, node in prev_state.allocation.items()
                if pod in surviving and state.allocation.get(pod) != node]

    def evaluate(self, state, evicted: list, pending: int = 0) -> Evaluation:
        """Avaliação completa do estado final de um período (pending é só
        informativo: a admissão já o penaliza, ponderada por w_j)."""
        node_cost, frag_cost, disruption = self.cost(None, state, evicted=evicted)
        return Evaluation(self.admission(state), node_cost, frag_cost, disruption)

    def better(self, first, second) -> bool:
        """True se a solução `first` é melhor que `second` na ordem (-A, C)."""
        return is_better(first, second)

    # ----- avaliação incremental -----

    def _node_term(self, node: int, used: tuple) -> float:
        """c_i·x_i + λ·c_i·F_i do nó para a ocupação `used`."""
        if not self._is_on(used):
            return 0.0
        return self.node_costs[node] * (
            1.0 + self.lam * self._fragmentation_for(node, used, self.distribution))

    def delta_place(self, pod: int, node: int, state) -> float:
        """ΔC de colocar o pod no nó: c_i·[nó desligado] + λ·c_i·(F_depois − F_antes).
        Só olha o nó afetado; não verifica capacidade."""
        before = self.usage(state, node)
        after = tuple(u + r for u, r in zip(before, self.requests(pod)))
        return self._node_term(node, after) - self._node_term(node, before)

    def place_cost(self, pod: int, node: int, state) -> float:
        return self.delta_place(pod, node, state)

    def move_delta(self, pod: int, current: int, destination: int, state) -> float:
        """ΔC (nós + fragmentação) de mover o pod; a evicção (ω_j) fica por
        conta de quem chama. O pod ainda está em `current` no estado."""
        request = self.requests(pod)
        used_current = self.usage(state, current)
        remaining = tuple(u - r for u, r in zip(used_current, request))
        released = self._node_term(current, remaining) - self._node_term(current, used_current)
        return released + self.delta_place(pod, destination, state)

    # ----- diagnóstico -----

    def diagnostics(self, state) -> dict:
        """Utilização por recurso (requests alocados / capacidade ligada) e % de
        capacidade fragmentada (F ponderada pela capacidade dos nós ligados)."""
        n_resources = len(RESOURCE_NAMES)
        used_total = [0.0] * n_resources
        capacity_total = [0.0] * n_resources
        frag_weighted = weight_total = 0.0
        for node in range(self.instance.n_nodes):
            used = self.usage(state, node)
            if not self._is_on(used):
                continue
            capacity = self.capacities(node)
            for r in range(n_resources):
                used_total[r] += used[r]
                capacity_total[r] += capacity[r]
            weight = sum(c / m for c, m in zip(capacity, self.mean_capacity)) / n_resources
            frag_weighted += weight * self._fragmentation_for(node, used, self.distribution)
            weight_total += weight
        return {
            "utilization": tuple(u / c if c else 0.0 for u, c in zip(used_total, capacity_total)),
            "fragmented_pct": 100.0 * frag_weighted / weight_total if weight_total else 0.0,
        }

