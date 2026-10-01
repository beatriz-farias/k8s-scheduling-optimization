from ..evictions import EvictionPlan
from .base import Descheduler


class LocalSearchBest(Descheduler):
    """Melhor melhoria: a cada passo escolhe a evicção de maior redução de
    custo prevista e atualiza o estado previsto, até não haver melhoria ou
    atingir o limite de evicções."""

    def select(self, context):
        state = context.state.copy()
        plan = EvictionPlan()
        while context.policy.allows(len(plan)):
            candidates = context.predictor.improving(context.pods, plan, state)
            if not candidates:
                break
            best = min(candidates)
            state.relocate(best.pod, best.destination)
            plan.add(best.pod)
        return plan


class LocalSearchFirst(Descheduler):
    """Primeira melhoria: percorre os pods em ordem e marca para evicção o
    primeiro cuja recolocação prevista reduz o custo; repete as passadas até
    uma passada inteira não marcar nada. Mais barata que LocalSearchBest."""

    def select(self, context):
        state = context.state.copy()
        plan = EvictionPlan()
        while self._improving_pass(context, state, plan):
            pass
        return plan

    def _improving_pass(self, context, state, plan) -> bool:
        """Uma passada sobre os pods; False quando nada melhorou ou o limite
        de evicções foi atingido."""
        improved = False
        for pod in context.pods:
            if not context.policy.allows(len(plan)):
                return False
            improved |= self._evict_if_improving(pod, context, state, plan)
        return improved

    def _evict_if_improving(self, pod, context, state, plan) -> bool:
        if pod in plan:
            return False
        candidate = context.predictor.predict(pod, state)
        if candidate is None or candidate.delta >= -context.policy.min_improvement:
            return False
        state.relocate(candidate.pod, candidate.destination)
        plan.add(pod)
        return True
