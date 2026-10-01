"""Registro dos Deschedulers disponíveis.

    none      nenhuma evicção (comportamento padrão do Kubernetes)
    ls_first  evicta o primeiro pod cuja recolocação prevista reduz o custo
    ls_best   evicta o pod de maior redução prevista, um de cada vez
    grasp     GRASP sobre conjuntos de evicção (RCL ponderada por delta)
    milp      MILP (Gurobi) planeja a alocação com no máximo K pods movidos
              e evicta os pods que mudariam de nó
"""

from .base import Descheduler, DeschedulingContext
from .grasp import GraspDescheduler
from .local_search import LocalSearchBest, LocalSearchFirst
from .milp import MilpDescheduler
from .none import NoDescheduler

DESCHEDULERS = {
    "none": NoDescheduler,
    "ls_first": LocalSearchFirst,
    "ls_best": LocalSearchBest,
    "grasp": GraspDescheduler,
    "milp": MilpDescheduler,
}


def build_descheduler(name: str, params: dict = None) -> Descheduler:
    return DESCHEDULERS[name](**(params or {}))
