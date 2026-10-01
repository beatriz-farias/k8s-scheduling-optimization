"""Parâmetros da bateria de experimentos da Fase 2."""

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

SCHEDULERS_TESTED = ["least_requested", "greedy", "milp"]
DESCHEDULERS_TESTED = ["none", "ls_first", "ls_best", "grasp", "milp"]

# Limite de evicções por ciclo no fatorial (None = sem limite)
DESCHEDULER_MAX_MOVES = 10
SENSITIVITY_MAX_MOVES = [1, 2, 5, 10, 20, 50, None]
SENSITIVITY_CONFIGS = [("least_requested", "ls_best"), ("greedy", "ls_best"),
                       ("milp", "milp")]

SCHEDULER_PARAMS = {
    "milp": {"mip_gap": 0.01, "time_limit": 60},  # time_limit por fila de pods (s)
}
DESCHEDULER_PARAMS = {
    "grasp": {"max_iter": 10, "rcl_alpha": 0.15, "temperature": 1.0},
    "milp": {"mip_gap": 0.01, "time_limit": 60},  # time_limit por período (s)
}

# kube-scheduler padrão sem Descheduler: base de comparação dos gaps
BASELINE_LABEL = "least_requested+none"
# Configuração removida (MILP monolítico, não executável no Kubernetes);
# linhas antigas nos CSVs são ignoradas na análise.
LEGACY_LABELS = frozenset({"milp_ref"})
# Os Schedulers que precisam de Gurobi, para o modo --no-milp
MILP_COMPONENT = "milp"

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "results")
FACTORIAL_CSV = os.path.join(RESULTS_DIR, "incremental_factorial_raw.csv")
SENSITIVITY_CSV = os.path.join(RESULTS_DIR, "incremental_sensitivity_raw.csv")

FIELDNAMES = ["n_nodes", "n_pods", "seed", "config", "scheduler", "descheduler",
              "max_moves", "cost", "infra_cost", "disruption_cost", "pending_cost",
              "evictions", "migrations", "pending_pods", "time_ms", "scheduler_time_ms",
              "descheduler_time_ms"]

METRICS = ["cost", "infra_cost", "disruption_cost", "pending_cost", "evictions",
           "migrations", "pending_pods", "time_ms", "scheduler_time_ms",
           "descheduler_time_ms"]
