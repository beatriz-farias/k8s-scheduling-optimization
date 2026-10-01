"""Simulação da arquitetura REAL de Scheduler + Descheduler separados.

Diferente de heuristics.py (modelo "monolítico" da Fase 1), onde cada período
resolve a alocação de TODOS os pods do zero, cada período segue o fluxo do
Kubernetes:

  1. SCHEDULER: coloca os pods NOVOS deste período, um de cada vez, com a
     sua regra de pontuação. Pods já rodando NÃO são tocados.
  2. DESCHEDULER: escolhe quais pods EVICTAR (no máximo max_moves por ciclo,
     como o maxNoOfPodsToEvictTotal do Descheduler real). Ele não escolhe o
     destino.
  3. SCHEDULER: os pods evictados voltam para a fila e são recolocados pelo
     Scheduler, na ordem de evicção, com a mesma regra usada para pods novos.
     Um pod evictado pode voltar ao mesmo nó.
"""

import random
import time
from typing import Callable, Optional

from instance_generator import Instance

from .cluster_state import ClusterState
from .cost import CostModel
from .deschedulers import Descheduler, DeschedulingContext
from .evictions import EvictionPolicy, execute_evictions
from .results import HorizonResult, PeriodResult
from .schedulers import Scheduler


def _elapsed_ms(start: float, end: float) -> float:
    return (end - start) * 1000


class IncrementalSimulation:
    def __init__(self, instance: Instance, scheduler: Scheduler,
                 descheduler: Descheduler, policy: EvictionPolicy,
                 rng: random.Random):
        self.instance = instance
        self.scheduler = scheduler
        self.descheduler = descheduler
        self.policy = policy
        self.rng = rng
        self.cost_model = CostModel(instance)

    def run(self, on_period: Optional[Callable[[PeriodResult], None]] = None) -> HorizonResult:
        previous = ClusterState.empty(self.instance)
        results = []
        for period, active_pods in enumerate(self.instance.periods_active_pods):
            state, result = self._run_period(period, active_pods, previous)
            results.append(result)
            previous = state
            if on_period:
                on_period(result)
        return HorizonResult(results)

    def _run_period(self, period: int, active_pods: list, previous: ClusterState):
        started = time.time()
        state = ClusterState.carry_over(previous, active_pods)
        new_pods = [pod for pod in active_pods if pod not in state]
        self.scheduler.schedule(new_pods, state)
        scheduled = time.time()

        plan = self.descheduler.select(self._context(state))
        planned = time.time()

        state = execute_evictions(self.scheduler, plan, state)
        finished = time.time()

        scheduler_ms = _elapsed_ms(started, scheduled) + _elapsed_ms(planned, finished)
        descheduler_ms = _elapsed_ms(scheduled, planned)
        pending = len(active_pods) - len(state)
        cost = self.cost_model.period(state.allocation, len(plan), pending)
        result = PeriodResult(
            period=period, n_active_pods=len(active_pods), n_new_pods=len(new_pods),
            n_nodes_open=state.open_nodes_count(),
            cost=cost.total, infra_cost=cost.infrastructure,
            disruption_cost=cost.disruption, pending_cost=cost.pending,
            time_ms=scheduler_ms + descheduler_ms,
            scheduler_time_ms=scheduler_ms, descheduler_time_ms=descheduler_ms,
            migrations=state.migrations_from(previous), evictions=len(plan),
            pending_pods=pending,
        )
        return state, result

    def _context(self, state: ClusterState) -> DeschedulingContext:
        return DeschedulingContext(state=state, scheduler=self.scheduler,
                                   policy=self.policy, cost_model=self.cost_model,
                                   rng=self.rng)
