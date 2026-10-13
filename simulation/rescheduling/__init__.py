"""Simulação de Scheduler + Descheduler separados, com a f.o. lexicográfica (-A, C)."""

import random

from .deschedulers import DESCHEDULERS, build_descheduler
from .evictions import EvictionPolicy
from .instance import Instance
from .objective import Objective
from .schedulers import SCHEDULERS, build_scheduler
from .simulation import Simulation


def simulate(instance: Instance, scheduler: str = "greedy",
                                   descheduler: str = "ls_best",
                                   max_moves_per_period: int = None,
                                   min_improvement: float = 1e-6, seed: int = None,
                                   scheduler_params: dict = None,
                                   descheduler_params: dict = None,
                                   objective_params: dict = None,
                                   verbose: bool = False) -> dict:
    """Roda Scheduler + Descheduler por todos os períodos. Retorna o
    HorizonResult como dict. max_moves_per_period=None: sem limite.

    objective_params: parâmetros de Objective (lam, omega, distribution,
    node_costs, n_types)."""
    objective_model = Objective(instance, **(objective_params or {}))
    simulation = Simulation(
        instance,
        scheduler=build_scheduler(scheduler, instance, objective_model, scheduler_params),
        descheduler=build_descheduler(descheduler, descheduler_params),
        policy=EvictionPolicy(max_moves_per_period, min_improvement),
        rng=random.Random(seed),
        objective=objective_model,
    )
    on_period = _print_period if verbose else None
    return simulation.run(on_period).to_dict()


def _print_period(result):
    print(f"  período {result.period:2d}: {result.n_active_pods:3d} pods "
          f"({result.n_new_pods:2d} novos) | custo {result.cost:8.1f} | "
          f"migrações {result.migrations:2d} (evicções {result.evictions}) | "
          f"{result.time_ms:6.2f}ms")
