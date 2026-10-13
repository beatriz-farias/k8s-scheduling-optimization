import math

from ..evictions import EvictionPlan, execute_evictions
from ..objective import is_better
from .base import Descheduler


class GraspDescheduler(Descheduler):
    """GRASP adaptado ao Descheduler: cada iteração constrói um conjunto de
    evicções escolhendo, a cada passo, uma evicção aleatória da RCL (as
    evicções com delta até rcl_alpha da faixa entre a melhor e a pior,
    regra padrão do GRASP), ponderada por delta. A construção só termina quando nenhuma
    evicção melhora (ou o limite é atingido), então a busca local fica
    embutida nela. Cada conjunto é avaliado executando as evicções de fato
    (evicta tudo, Scheduler recoloca) com a f.o. completa, a tupla (-A, C)
    com o termo de evicção; só substitui o estado atual quem for estritamente melhor.
    Não evictar nada é o ponto de partida. A primeira iteração é gulosa
    (igual a LocalSearchBest)."""

    def __init__(self, max_iter: int = 10, rcl_alpha: float = 0.15,
                 temperature: float = 1.0):
        self.max_iter = max_iter
        self.rcl_alpha = rcl_alpha
        self.temperature = temperature

    def select(self, context):
        best_plan = EvictionPlan()
        best_value = context.objective.evaluate(context.state, [], 0)
        for iteration in range(self.max_iter):
            plan = self._construct(context, iteration)
            value = self._real_value(context, plan)
            if is_better(value, best_value):
                best_value, best_plan = value, plan
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
        limit = candidates[0].delta + self.rcl_alpha * (candidates[-1].delta - candidates[0].delta)
        rcl = [c for c in candidates if c.delta <= limit]
        best_delta = rcl[0].delta
        weights = [math.exp(-(c.delta - best_delta) / max(self.temperature, 1e-6))
                   for c in rcl]
        return rng.choices(rcl, weights=weights, k=1)[0]

    def _real_value(self, context, plan: EvictionPlan):
        result = execute_evictions(context.scheduler, plan, context.state)
        pending = len(context.state) - len(result)
        return context.objective.evaluate(result, plan.pods(), pending)
