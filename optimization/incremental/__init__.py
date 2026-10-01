"""Arquitetura incremental: Scheduler + Descheduler separados (Fase 2)."""

import random

from instance_generator import Instance

from .deschedulers import DESCHEDULERS, build_descheduler
from .evictions import EvictionPolicy
from .scheduler_registry import SCHEDULERS, build_scheduler
from .simulation import IncrementalSimulation


def solve_full_horizon_incremental(instance: Instance, scheduler: str = "greedy",
                                   descheduler: str = "ls_best",
                                   max_moves_per_period: int = None,
                                   min_improvement: float = 1e-6, seed: int = None,
                                   scheduler_params: dict = None,
                                   descheduler_params: dict = None,
                                   verbose: bool = False) -> dict:
    """Roda Scheduler + Descheduler por todos os períodos. Retorna o
    HorizonResult como dict. max_moves_per_period=None: sem limite."""
    simulation = IncrementalSimulation(
        instance,
        scheduler=build_scheduler(scheduler, instance, scheduler_params),
        descheduler=build_descheduler(descheduler, descheduler_params),
        policy=EvictionPolicy(max_moves_per_period, min_improvement),
        rng=random.Random(seed),
    )
    on_period = _print_period if verbose else None
    return simulation.run(on_period).to_dict()


def _print_period(result):
    print(f"  período {result.period:2d}: {result.n_active_pods:3d} pods "
          f"({result.n_new_pods:2d} novos) | custo {result.cost:8.1f} | "
          f"migrações {result.migrations:2d} (evicções {result.evictions}) | "
          f"{result.time_ms:6.2f}ms")
