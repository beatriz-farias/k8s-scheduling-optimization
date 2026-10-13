from ..evictions import EvictionPlan
from .base import Descheduler


class NoDescheduler(Descheduler):
    """Sem Descheduler: comportamento padrão de um cluster Kubernetes."""

    def select(self, context):
        return EvictionPlan()
