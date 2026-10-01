"""
Ponto de entrada compatível da arquitetura Scheduler + Descheduler.

A implementação vive no pacote `incremental/` (um módulo por responsabilidade:
estado, custo, schedulers, evicções, deschedulers, simulação, resultados).
Este arquivo só reexporta a API pública e traz um demo comparando todas as
combinações.
"""

from incremental import DESCHEDULERS, SCHEDULERS, solve_full_horizon_incremental

__all__ = ["DESCHEDULERS", "SCHEDULERS", "solve_full_horizon_incremental"]


def _available(registry):
    """Nomes do registro; sem Gurobi, omite a opção MILP."""
    try:
        import gurobipy  # noqa: F401
    except ImportError:
        return [name for name in registry if name != "milp"]
    return list(registry)


if __name__ == "__main__":
    from instance_generator import generate_instance

    inst = generate_instance(n_nodes=10, n_pods_total=50, n_periods=20, seed=100)
    print(f"Instância: {inst.n_nodes} nós, omega={inst.omega:.2f} | limite: 10 evicções/período\n")
    print(f"{'Scheduler':>16} {'Descheduler':>12} | {'total':>8} {'infra':>8} {'disrup':>7} "
          f"{'evic':>5} {'migr':>5} {'tempo(ms)':>10}")
    print("-" * 82)

    for sched in _available(SCHEDULERS):
        for desched in _available(DESCHEDULERS):
            r = solve_full_horizon_incremental(inst, scheduler=sched, descheduler=desched,
                                               max_moves_per_period=10, seed=100)
            print(f"{sched:>16} {desched:>12} | {r['total_cost']:>8.0f} "
                  f"{r['total_infra_cost']:>8.0f} {r['total_disruption_cost']:>7.0f} "
                  f"{r['total_evictions']:>5} {r['total_migrations']:>5} "
                  f"{r['total_time_ms']:>10.1f}")
