"""Resultados de uma simulação: por período e agregados no horizonte."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PeriodResult:
    period: int
    n_active_pods: int
    n_new_pods: int
    n_nodes_open: int
    cost: float
    node_cost: float
    frag_cost: float
    disruption_cost: float
    admission: float
    time_ms: float
    scheduler_time_ms: float
    descheduler_time_ms: float
    migrations: int
    evictions: int
    pending_pods: int
    # Diagnósticos de empacotamento do estado final
    fragmented_pct: float = 0.0
    utilization: tuple = ()


class HorizonResult:
    """Coleção de PeriodResult com os totais do horizonte. total_cost é a
    soma de C_t e se divide em nós + fragmentação + disrupção. migrations (pods
    do período anterior que terminam em outro nó) é só informativo: a
    disrupção cobrada é por evicção."""

    def __init__(self, periods: list):
        self.periods = periods

    def _sum(self, field_name: str):
        return sum(getattr(period, field_name) for period in self.periods)

    def to_dict(self) -> dict:
        return {
            "results_per_period": [asdict(period) for period in self.periods],
            "total_cost": self._sum("cost"),
            "total_node_cost": self._sum("node_cost"),
            "total_frag_cost": self._sum("frag_cost"),
            "total_disruption_cost": self._sum("disruption_cost"),
            "total_admission": self._sum("admission"),
            "total_time_ms": self._sum("time_ms"),
            "total_scheduler_time_ms": self._sum("scheduler_time_ms"),
            "total_descheduler_time_ms": self._sum("descheduler_time_ms"),
            "total_migrations": self._sum("migrations"),
            "total_evictions": self._sum("evictions"),
            "total_pending_pods": self._sum("pending_pods"),
            "mean_fragmented_pct": self._mean("fragmented_pct"),
            "mean_utilization": self._mean_utilization(),
        }

    def _mean(self, field_name: str) -> float:
        return self._sum(field_name) / len(self.periods) if self.periods else 0.0

    def _mean_utilization(self) -> tuple:
        """Utilização média por recurso, entre os períodos."""
        if not self.periods:
            return ()
        columns = zip(*(period.utilization for period in self.periods))
        return tuple(sum(column) / len(self.periods) for column in columns)
