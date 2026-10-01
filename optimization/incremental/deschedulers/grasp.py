import math

from ..evictions import EvictionPlan, execute_evictions
from .base import Descheduler

MIN_COST_GAIN = 1e-9


class GraspDescheduler(Descheduler):
    """GRASP adaptado ao Descheduler: cada iteração constrói um conjunto de
    evicções escolhendo, a cada passo, uma evicção aleatória da RCL (as
    rcl_alpha melhores pela redução prevista), ponderada por delta como a
    RCL ponderada de heuristics.py. A construção só termina quando nenhuma
    evicção melhora (ou o limite é atingido), então a busca local fica
    embutida nela. Cada conjunto é avaliado executando as evicções de fato
    (evicta tudo, Scheduler recoloca) e fica o de menor custo real (ω por
    evicção e M por pod Pending); não evictar nada também é candidato. A
    primeira iteração é gulosa (igual a LocalSearchBest)."""

    def __init__(self, max_iter: int = 10, rcl_alpha: float = 0.15,
                 temperature: float = 1.0):
        self.max_iter = max_iter
        self.rcl_alpha = rcl_alpha
        self.temperature = temperature

    def select(self, context):
        best_plan = EvictionPlan()
        best_cost = context.cost_model.period(context.state.allocation, 0, 0).total
        for iteration in range(self.max_iter):
            plan = self._construct(context, iteration)
            cost = self._real_cost(context, plan)
            if cost < best_cost - MIN_COST_GAIN:
                best_cost, best_plan = cost, plan
        return best_plan

    def _construct(self, context, iteration: int) -> EvictionPlan:
        state = context.state.copy()
        plan = EvictionPlan()
        while context.policy.allows(len(plan)):
            candidates = context.predictor.improving(context.pods, plan, state)
            if not candidates:
                break
            chosen = self._choose(candidates, iteration, context.rng)
            state.relocate(chosen.pod, chosen.destination)
            plan.add(chosen.pod)
        return plan

    def _choose(self, candidates: list, iteration: int, rng):
        candidates.sort()
        if iteration == 0:
            return candidates[0]
        rcl = candidates[:max(1, int(len(candidates) * self.rcl_alpha))]
        best_delta = rcl[0].delta
        weights = [math.exp(-(c.delta - best_delta) / max(self.temperature, 1e-6))
                   for c in rcl]
        return rng.choices(rcl, weights=weights, k=1)[0]

    def _real_cost(self, context, plan: EvictionPlan) -> float:
        result = execute_evictions(context.scheduler, plan, context.state)
        pending = len(context.state) - len(result)
        return context.cost_model.period(result.allocation, len(plan), pending).total
