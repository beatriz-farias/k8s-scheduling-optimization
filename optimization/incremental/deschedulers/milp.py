from ..evictions import EvictionPlan
from .base import Descheduler


class MilpDescheduler(Descheduler):
    """Descheduler com planejamento exato: resolve o MILP do período
    (milp_model.solve_period) partindo da alocação atual como warm start e
    com no máximo max_moves pods mudando de nó, e evicta os pods que o plano
    move. O ω do MILP é medido em relação à alocação atual (previous_alloc =
    alocação atual), então cada pod movido no plano paga ω, igual a uma
    evicção. Os destinos do plano NÃO são impostos: quem recoloca os pods é
    o Scheduler, que pode escolher nós diferentes dos planejados."""

    def __init__(self, mip_gap: float = 0.01, time_limit: float = 60):
        self.mip_gap = mip_gap
        self.time_limit = time_limit

    def select(self, context):
        from milp_model import solve_period  # Gurobi só é exigido por este Descheduler

        current = context.state.allocation
        result = solve_period(context.instance, context.pods, current,
                              mip_gap=self.mip_gap, time_limit=self.time_limit,
                              start_alloc=current, max_moves=context.policy.max_moves)
        return self._plan_from(result, context)

    def _plan_from(self, result: dict, context) -> EvictionPlan:
        plan = EvictionPlan()
        if result["cost"] is None:
            return plan
        for pod in context.pods:
            if result["alloc"][pod] != context.state.node_of(pod):
                plan.add(pod)
        return plan
