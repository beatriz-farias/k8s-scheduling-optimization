"""
Roda APENAS a arquitetura incremental (Scheduler + Descheduler) nas mesmas
combinacoes/seeds da bateria monolitica ja executada anteriormente
(experiment_results_raw.csv). Nao recalcula MILP, Gulosa, Busca Local nem
GRASP monoliticos -- essa parte ja foi feita e nao precisa ser repetida.

Depois de rodar, use merge_with_monolithic() para juntar este resultado
com o CSV antigo e comparar lado a lado.

Uso:
    python3 run_incremental_only.py
"""

import csv
import statistics
import time

from instance_generator_v1 import generate_instance
from incremental_scheduler import solve_full_horizon_incremental


DEFAULT_INSTANCE_SIZES = [
    (10, 50), (10, 100), (10, 200),
    (20, 100), (20, 200), (20, 500),
    (50, 200), (50, 500), (50, 1000),
    (100, 500), (100, 1000),
]

N_RUNS = 10
N_PERIODS = 20
BASE_SEED = 100
MIN_IMPROVEMENT = 1e-6


def run_experiments(instance_sizes=None, n_runs: int = N_RUNS,
                     verbose: bool = True, checkpoint_path: str = None):
    instance_sizes = instance_sizes or DEFAULT_INSTANCE_SIZES
    all_rows = []

    for n_nodes, n_pods in instance_sizes:
        if verbose:
            print(f"\n=== N={n_nodes} nos, P={n_pods} pods ===")

        for run in range(n_runs):
            seed = BASE_SEED + run
            inst = generate_instance(n_nodes=n_nodes, n_pods_total=n_pods,
                                      n_periods=N_PERIODS, seed=seed)

            t0 = time.time()
            r = solve_full_horizon_incremental(inst, min_improvement=MIN_IMPROVEMENT)
            elapsed = time.time() - t0

            row = {
                "n_nodes": n_nodes, "n_pods": n_pods, "seed": seed,
                "incremental_cost": r["total_cost"],
                "incremental_time_ms": r["total_time_ms"],
                "incremental_migrations": r["total_migrations"],
            }
            all_rows.append(row)

            if verbose:
                print(f"  run {run+1}/{n_runs} (seed={seed}): "
                      f"custo={r['total_cost']:.0f} migracoes={r['total_migrations']} "
                      f"tempo={r['total_time_ms']:.0f}ms [{elapsed:.1f}s]")

        if checkpoint_path:
            save_csv(all_rows, checkpoint_path)
            if verbose:
                print(f"  [checkpoint salvo: {len(all_rows)} linhas em {checkpoint_path}]")

    return all_rows


def save_csv(rows: list, path: str):
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def merge_with_monolithic(incremental_csv: str, monolithic_csv: str, output_csv: str):
    """Junta o CSV do incremental com o CSV monolitico ja existente
    (mesmo n_nodes/n_pods/seed), produzindo uma tabela unica para
    comparacao. rcl_alpha do monolitico e ignorado (usa a primeira
    ocorrencia de cada seed, ja que o incremental nao depende de alpha)."""
    incr_rows = list(csv.DictReader(open(incremental_csv)))
    mono_rows = list(csv.DictReader(open(monolithic_csv)))

    # indexa o monolitico por (n_nodes, n_pods, seed), pegando so a
    # primeira linha de cada (evita duplicar por causa da varredura de alpha)
    mono_by_key = {}
    for r in mono_rows:
        key = (r["n_nodes"], r["n_pods"], r["seed"])
        if key not in mono_by_key:
            mono_by_key[key] = r

    merged = []
    for r in incr_rows:
        key = (r["n_nodes"], r["n_pods"], r["seed"])
        mono = mono_by_key.get(key)
        if mono is None:
            continue  # sem par monolitico para essa combinacao/seed

        merged.append({
            "n_nodes": r["n_nodes"], "n_pods": r["n_pods"], "seed": r["seed"],
            "ls_cost": mono.get("ls_cost"), "ls_migrations": mono.get("ls_migrations"),
            "grasp_cost": mono.get("grasp_cost"), "grasp_migrations": mono.get("grasp_migrations"),
            "milp_cost": mono.get("milp_cost"),
            "incremental_cost": r["incremental_cost"],
            "incremental_migrations": r["incremental_migrations"],
            "incremental_time_ms": r["incremental_time_ms"],
        })

    save_csv(merged, output_csv)
    print(f"Comparacao salva em {output_csv} ({len(merged)} linhas combinadas)")
    return merged


def print_comparison_summary(merged_rows: list):
    groups = {}
    for r in merged_rows:
        key = (r["n_nodes"], r["n_pods"])
        groups.setdefault(key, []).append(r)

    print(f"{'Pods':>6} {'Nos':>5} | {'BuscaLoc':>10} {'Incremental':>12} {'delta%':>8} | "
          f"{'mig LS':>7} {'mig Incr':>9}")
    print("-" * 70)
    for (n_nodes, n_pods), rows in sorted(groups.items(), key=lambda kv: (int(kv[0][1]), int(kv[0][0]))):
        ls_costs = [float(r["ls_cost"]) for r in rows if r["ls_cost"]]
        incr_costs = [float(r["incremental_cost"]) for r in rows if r["incremental_cost"]]
        ls_migs = [float(r["ls_migrations"]) for r in rows if r["ls_migrations"]]
        incr_migs = [float(r["incremental_migrations"]) for r in rows if r["incremental_migrations"]]

        ls_avg = statistics.mean(ls_costs)
        incr_avg = statistics.mean(incr_costs)
        delta_pct = (incr_avg - ls_avg) / ls_avg * 100

        print(f"{n_pods:>6} {n_nodes:>5} | {ls_avg:>10.0f} {incr_avg:>12.0f} {delta_pct:>+7.2f}% | "
              f"{statistics.mean(ls_migs):>7.0f} {statistics.mean(incr_migs):>9.0f}")


if __name__ == "__main__":
    INCREMENTAL_CHECKPOINT = "incremental_results_raw.csv"

    print(f"Rodando SOMENTE a arquitetura incremental (N_RUNS={N_RUNS})...")
    print("O modelo monolitico (MILP/Gulosa/BuscaLocal/GRASP) NAO sera recalculado --")
    print("use o CSV que voce ja tem de experiment_runner.py para a comparacao.\n")

    rows = run_experiments(instance_sizes=DEFAULT_INSTANCE_SIZES, n_runs=N_RUNS,
                            verbose=True, checkpoint_path=INCREMENTAL_CHECKPOINT)

    save_csv(rows, INCREMENTAL_CHECKPOINT)
    print(f"\nResultados do incremental salvos em {INCREMENTAL_CHECKPOINT}")

    print("\nPara comparar com o modelo monolitico ja rodado, chame:")
    print("  from run_incremental_only import merge_with_monolithic, print_comparison_summary")
    print("  merged = merge_with_monolithic('incremental_results_raw.csv', "
          "'experiment_results_raw.csv', 'comparison_final.csv')")
    print("  print_comparison_summary(merged)")
