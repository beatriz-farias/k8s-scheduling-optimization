"""Configurações (Scheduler x Descheduler) do fatorial."""

from dataclasses import dataclass
from typing import Optional

from . import settings


@dataclass(frozen=True)
class ExperimentConfig:
    scheduler: str
    descheduler: str
    max_moves: Optional[int]

    @property
    def label(self) -> str:
        return f"{self.scheduler}+{self.descheduler}"

    @property
    def scheduler_params(self) -> dict:
        return settings.SCHEDULER_PARAMS.get(self.scheduler, {})

    @property
    def descheduler_params(self) -> dict:
        return settings.DESCHEDULER_PARAMS.get(self.descheduler, {})

    @property
    def needs_milp(self) -> bool:
        return settings.MILP_COMPONENT in (self.scheduler, self.descheduler)


def factorial_configs(include_milp: bool = True) -> list:
    """Todas as combinações Scheduler x Descheduler com o mesmo limite de
    evicções por ciclo; "least_requested+none" é o Kubernetes padrão."""
    configs = [ExperimentConfig(scheduler, descheduler, _factorial_max_moves(descheduler))
               for scheduler in settings.SCHEDULERS_TESTED
               for descheduler in settings.DESCHEDULERS_TESTED]
    return _only_runnable(configs, include_milp)


def _only_runnable(configs: list, include_milp: bool) -> list:
    return [config for config in configs if include_milp or not config.needs_milp]


def _factorial_max_moves(descheduler: str) -> int:
    return 0 if descheduler == "none" else settings.DESCHEDULER_MAX_MOVES
