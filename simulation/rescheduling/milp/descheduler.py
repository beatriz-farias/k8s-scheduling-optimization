from ..deschedulers.base import Descheduler
from ..evictions import EvictionPlan


class MilpDescheduler(Descheduler):
    """Descheduler com planejamento exato (milp.model.plan_moves): parte
    da alocação atual como warm start e move no máximo max_moves pods; cada
    pod movido paga ω_j, igual a uma evicção. Evicta os pods que o plano
    move. Os destinos do plano NÃO são impostos: quem recoloca os pods é o
    Scheduler, que pode escolher nós diferentes dos planejados."""

    def __init__(self, mip_gap: float = 0.01, time_limit: float = 60):
        self.mip_gap = mip_gap
        self.time_limit = time_limit

    def select(self, context):
        from .model import plan_moves  # Gurobi só é exigido por este Descheduler

        planned = plan_moves(context.objective, context.state, context.policy.max_moves,
                             self.mip_gap, self.time_limit)
        plan = EvictionPlan()
        if planned is None:
            return plan
        for pod in context.pods:
            if planned[pod] != context.state.node_of(pod):
                plan.add(pod)
        return plan
