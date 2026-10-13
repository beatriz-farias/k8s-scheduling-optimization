"""Execução das configurações sobre as instâncias, com retomada via CSV."""

import time

from rescheduling import simulate
from rescheduling.instance import generate_instance

from . import settings
from .configurations import ExperimentConfig
from .results_store import ResultsStore


def objective_params() -> dict:
    return {"lam": settings.LAMBDA, "omega": settings.EVICTION_COST,
            "omega_fraction": settings.OMEGA_FRACTION,
            "omega_by_size": settings.OMEGA_BY_SIZE, "n_types": settings.POD_TYPES}


def run_config(instance, config: ExperimentConfig, seed: int) -> dict:
    result = simulate(
        instance, scheduler=config.scheduler, descheduler=config.descheduler,
        max_moves_per_period=config.max_moves, min_improvement=settings.MIN_IMPROVEMENT,
        seed=seed, scheduler_params=config.scheduler_params,
        descheduler_params=config.descheduler_params,
        objective_params=objective_params(),
    )
    utilization = result["mean_utilization"]
    return {
        "config": config.label, "scheduler": config.scheduler,
        "descheduler": config.descheduler,
        "max_moves": "" if config.max_moves is None else config.max_moves,
        "cost": result["total_cost"], "node_cost": result["total_node_cost"],
        "frag_cost": result["total_frag_cost"],
        "disruption_cost": result["total_disruption_cost"],
        "admission": result["total_admission"],
        "fragmented_pct": result["mean_fragmented_pct"],
        "utilization_demanda": utilization[0] if utilization else "",
        "evictions": result["total_evictions"], "migrations": result["total_migrations"],
        "pending_pods": result["total_pending_pods"], "time_ms": result["total_time_ms"],
        "scheduler_time_ms": result["total_scheduler_time_ms"],
        "descheduler_time_ms": result["total_descheduler_time_ms"],
    }


class ExperimentRunner:
    """Roda todas as configs em todas as instâncias, salvando o CSV após
    cada instância. Linhas já presentes no CSV são reaproveitadas."""

    def __init__(self, store: ResultsStore, instance_sizes: list = None,
                 n_runs: int = settings.N_RUNS, verbose: bool = True):
        self.store = store
        self.instance_sizes = instance_sizes or settings.DEFAULT_INSTANCE_SIZES
        self.n_runs = n_runs
        self.verbose = verbose
        self.rows = store.load()
        self.done = {self._row_key(row) for row in self.rows}

    @staticmethod
    def _row_key(row: dict) -> tuple:
        return (int(row["n_nodes"]), int(row["n_pods"]), int(row["seed"]), row["config"])

    def run(self, configs: list) -> list:
        self._announce_resume()
        for n_nodes, n_pods in self.instance_sizes:
            self._run_size(n_nodes, n_pods, configs)
        return self.rows

    def _run_size(self, n_nodes: int, n_pods: int, configs: list):
        self._log(f"\n=== N={n_nodes} nós, P={n_pods} pods ===")
        for run in range(self.n_runs):
            self._run_seed(n_nodes, n_pods, run, configs)

    def _run_seed(self, n_nodes: int, n_pods: int, run: int, configs: list):
        seed = settings.BASE_SEED + run
        pending = [c for c in configs if (n_nodes, n_pods, seed, c.label) not in self.done]
        if not pending:
            return
        instance = generate_instance(n_nodes=n_nodes, n_pods_total=n_pods,
                                     n_periods=settings.N_PERIODS, seed=seed,
                                     capacity_margin=settings.CAPACITY_MARGIN,
                                     cost_model=settings.COST_MODEL)
        started = time.time()
        summary = [self._run_one(instance, config, n_nodes, n_pods, seed)
                   for config in pending]
        self.store.save(self.rows)
        self._log(f"  run {run + 1}/{self.n_runs} (seed={seed}) "
                  f"[{time.time() - started:.1f}s] custo/migrações: " + ", ".join(summary))

    def _run_one(self, instance, config, n_nodes, n_pods, seed) -> str:
        row = {"n_nodes": n_nodes, "n_pods": n_pods, "seed": seed}
        row.update(run_config(instance, config, seed))
        self.rows.append(row)
        return f"{config.label}={row['cost']:.0f}/{row['migrations']}"

    def _announce_resume(self):
        if self.rows:
            self._log(f"[retomando: {len(self.rows)} linhas já existentes em {self.store.path}]")

    def _log(self, message: str):
        if self.verbose:
            print(message)
