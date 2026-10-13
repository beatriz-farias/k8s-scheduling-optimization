"""Demo: roda todas as combinações Scheduler × Descheduler em uma instância.

    python -m examples.demo      # a partir da raiz do projeto
"""

from rescheduling import DESCHEDULERS, SCHEDULERS, simulate
from rescheduling.instance import generate_instance


def _available(registry):
    """Nomes do registro; sem Gurobi, omite a opção MILP."""
    try:
        import gurobipy  # noqa: F401
    except ImportError:
        return [name for name in registry if name != "milp"]
    return list(registry)


if __name__ == "__main__":
    inst = generate_instance(n_nodes=10, n_pods_total=50, n_periods=20, seed=100)
    print(f"Instância: {inst.n_nodes} nós | limite: 10 evicções/período\n")
    print(f"{'Scheduler':>16} {'Descheduler':>12} | {'custo':>8} {'nós':>8} {'frag':>7} {'disrup':>7} "
          f"{'evic':>5} {'migr':>5} {'tempo(ms)':>10}")
    print("-" * 90)

    for sched in _available(SCHEDULERS):
        for desched in _available(DESCHEDULERS):
            r = simulate(inst, scheduler=sched, descheduler=desched,
                         max_moves_per_period=10, seed=100)
            print(f"{sched:>16} {desched:>12} | {r['total_cost']:>8.0f} "
                  f"{r['total_node_cost']:>8.0f} {r['total_frag_cost']:>7.0f} "
                  f"{r['total_disruption_cost']:>7.0f} "
                  f"{r['total_evictions']:>5} {r['total_migrations']:>5} "
                  f"{r['total_time_ms']:>10.1f}")
