"""Parâmetros da bateria de experimentos."""

import os

DEFAULT_INSTANCE_SIZES = [
    (10, 50), (10, 100), (10, 200),
    (20, 100), (20, 200), (20, 500),
    (50, 200), (50, 500), (50, 1000),
    (100, 500), (100, 1000),
]
QUICK_INSTANCE_SIZES = [(10, 50), (20, 100)]

N_RUNS = 10
N_PERIODS = 20
BASE_SEED = 100
MIN_IMPROVEMENT = 1e-6

# Função objetivo
LAMBDA = 1.0          # peso λ da fragmentação (--lam aceita vários valores para varrer)
POD_TYPES = 5         # tipos em M_pods (distribuição empírica dos pods da instância)
# Custo de evicção ω_j. Por padrão é uniforme: OMEGA_FRACTION × c_i médio, na escala
# do custo dos nós. OMEGA_BY_SIZE torna ω_j proporcional ao tamanho (peso w_j) do pod.
# EVICTION_COST sobrescreve: número (uniforme) ou {pod: ω_j}.
OMEGA_FRACTION = 0.5
OMEGA_BY_SIZE = False
EVICTION_COST = None

# Modelo de custo dos nós: "martins" (c_i ~ U(1, 4n), independente da capacidade, como em
# Martins et al.) ou "proportional" (c_i proporcional à capacidade, com ruído, como o preço
# de instâncias na nuvem).
COST_MODEL = "martins"

# Folga de capacidade das instâncias (capacidade total / demanda média no pico).
# Perto de 1,0 sobram pods Pending e a prioridade de admissão decide.
CAPACITY_MARGIN = 1.1

SCHEDULERS_TESTED = ["least_requested", "greedy", "milp"]
DESCHEDULERS_TESTED = ["none", "ls_first", "ls_best", "grasp", "milp"]

# Limite de evicções por ciclo (K) (None = sem limite)
DESCHEDULER_MAX_MOVES = 10

SCHEDULER_PARAMS = {
    "milp": {"mip_gap": 0.01, "time_limit": 60},  # time_limit por fila de pods (s)
}
DESCHEDULER_PARAMS = {
    "grasp": {"max_iter": 10, "rcl_alpha": 0.15, "temperature": 1.0},
    "milp": {"mip_gap": 0.01, "time_limit": 60},  # time_limit por período (s)
}

# Schedulers implantáveis (decidem pod a pod, no caminho crítico) e de referência
# (MILP em lote, limite superior); as tabelas e os testes os separam.
DEPLOYABLE_SCHEDULERS = ["least_requested", "greedy"]
REFERENCE_SCHEDULERS = ["milp"]

# kube-scheduler padrão sem Descheduler: base de comparação dos gaps
BASELINE_LABEL = "least_requested+none"
# Os Schedulers que precisam de Gurobi, para o modo --no-milp
MILP_COMPONENT = "milp"

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")


def factorial_csv(lam: float, margin: float, omega_fraction: float, cost_model: str) -> str:
    """Um CSV por combinação de parâmetros, para não misturar resultados."""
    return os.path.join(RESULTS_DIR, f"factorial_lam{lam:g}_omega{omega_fraction:g}"
                                     f"_margin{margin:g}_cost-{cost_model}.csv")


# Totais no horizonte, exceto fragmented_pct e utilization_* (médias entre períodos).
# cost = node_cost + frag_cost + disruption_cost.
FIELDNAMES = ["n_nodes", "n_pods", "seed", "config", "scheduler", "descheduler",
              "max_moves", "cost", "node_cost", "frag_cost", "disruption_cost", "admission",
              "fragmented_pct", "utilization_demanda", "evictions", "migrations",
              "pending_pods", "time_ms", "scheduler_time_ms", "descheduler_time_ms"]

METRICS = [name for name in FIELDNAMES
           if name not in ("n_nodes", "n_pods", "seed", "config", "scheduler",
                           "descheduler", "max_moves")]
