"""
Runner de experimentos: Kube-scheduler, MILP exato, Heurística Gulosa,
Busca Local e GRASP em instâncias multi-período (modelo dinâmico com omega).
Inclui varredura de rcl_alpha por combinação (N,P).
"""

import csv
import statistics
import time

import gurobipy as gp

from instance_generator import generate_instance
from milp_model import solve_full_horizon as milp_solve
from kube_scheduler_baseline import solve_full_horizon_kube_scheduler as kube_solve
from heuristics import (solve_full_horizon_greedy, solve_full_horizon_local_search,
                         solve_full_horizon_grasp)


DEFAULT_INSTANCE_SIZES = [
    (10, 50), (10, 100), (10, 200),
    (20, 100), (20, 200), (20, 500),
    (50, 200), (50, 500), (50, 1000),
    (100, 500), (100, 1000),
]

N_RUNS = 5
N_PERIODS = 20
BASE_SEED = 100
GRASP_MAX_ITER = 10

# Valores de rcl_alpha testados na análise de sensibilidade (Fase 1).
# O alpha usado na tabela principal é escolhido a partir desta varredura,
# não fixado a priori — ver print_alpha_sensitivity_table().
GRASP_RCL_ALPHA_VALUES = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]

MILP_MIP_GAP = 0.01
MILP_TIME_LIMIT = 60  # segundos por período

# Se True, roda também o GRASP com RCL uniforme (versão classica do artigo,
# com a falha diagnosticada para o cenario dinamico) ao lado da versao
# ponderada (padrao, corrigida) para comparacao direta no mesmo CSV.
# Desligue para reduzir o tempo total do experimento pela metade (aprox.)
# se o prazo estiver apertado — o GRASP ponderado sozinho ja e o resultado
# principal do TCC.
RUN_UNIFORM_COMPARISON = True


def run_baseline_methods(inst, n_nodes: int, n_pods: int, seed: int):
    """Kube-scheduler, MILP, Gulosa e Busca Local (independentes de rcl_alpha)."""
    row = {"n_nodes": n_nodes, "n_pods": n_pods, "seed": seed}

    r = kube_solve(inst)
    row["kube_cost"] = r["total_cost"]
    row["kube_time_ms"] = r["total_time_ms"]
    row["kube_migrations"] = r["total_migrations"]

    try:
        r = milp_solve(inst, mip_gap=MILP_MIP_GAP, time_limit=MILP_TIME_LIMIT)
        row["milp_cost"] = r["total_cost"]
        row["milp_time_ms"] = r["total_time_ms"]
        row["milp_migrations"] = r["total_migrations"]
    except (gp.GurobiError, RuntimeError) as e:
        row["milp_cost"] = None
        row["milp_time_ms"] = None
        row["milp_migrations"] = None
        row["milp_error"] = str(e)

    r = solve_full_horizon_greedy(inst)
    row["greedy_cost"] = r["total_cost"]
    row["greedy_time_ms"] = r["total_time_ms"]
    row["greedy_migrations"] = r["total_migrations"]

    r = solve_full_horizon_local_search(inst)
    row["ls_cost"] = r["total_cost"]
    row["ls_time_ms"] = r["total_time_ms"]
    row["ls_migrations"] = r["total_migrations"]

    return row


def run_one_instance(n_nodes: int, n_pods: int, seed: int, rcl_alpha_values=None,
                      run_uniform_comparison: bool = None):
    """Roda todos os métodos numa instância. GRASP roda uma vez por valor
    de rcl_alpha_values; retorna uma linha por valor testado.

    Cada linha contém dois conjuntos de resultados de GRASP:
      - grasp_cost/time/migrations: RCL ponderada por custo (padrão,
        corrigido para o cenário dinâmico).
      - grasp_uniform_cost/time/migrations: RCL uniforme (versão clássica
        do artigo, mantida para comparação — ver RUN_UNIFORM_COMPARISON).
    """
    rcl_alpha_values = rcl_alpha_values or GRASP_RCL_ALPHA_VALUES
    if run_uniform_comparison is None:
        run_uniform_comparison = RUN_UNIFORM_COMPARISON

    inst = generate_instance(n_nodes=n_nodes, n_pods_total=n_pods,
                              n_periods=N_PERIODS, seed=seed)

    baseline_row = run_baseline_methods(inst, n_nodes, n_pods, seed)

    rows = []
    for rcl_alpha in rcl_alpha_values:
        row = dict(baseline_row)
        row["rcl_alpha"] = rcl_alpha

        r = solve_full_horizon_grasp(inst, max_iter=GRASP_MAX_ITER,
                                      rcl_alpha=rcl_alpha, seed=seed, weighted=True)
        row["grasp_cost"] = r["total_cost"]
        row["grasp_time_ms"] = r["total_time_ms"]
        row["grasp_migrations"] = r["total_migrations"]

        if run_uniform_comparison:
            r_u = solve_full_horizon_grasp(inst, max_iter=GRASP_MAX_ITER,
                                            rcl_alpha=rcl_alpha, seed=seed, weighted=False)
            row["grasp_uniform_cost"] = r_u["total_cost"]
            row["grasp_uniform_time_ms"] = r_u["total_time_ms"]
            row["grasp_uniform_migrations"] = r_u["total_migrations"]

        rows.append(row)

    return rows


def run_experiments(instance_sizes=None, n_runs: int = N_RUNS,
                     rcl_alpha_values=None, verbose: bool = True,
                     checkpoint_path: str = None):
    """checkpoint_path: se informado, salva o CSV parcial apos cada
    combinacao (N,P) concluida, para nao perder progresso em caso de
    interrupcao (queda de energia, fechamento acidental, etc.)."""
    instance_sizes = instance_sizes or DEFAULT_INSTANCE_SIZES
    rcl_alpha_values = rcl_alpha_values or GRASP_RCL_ALPHA_VALUES
    all_rows = []

    for n_nodes, n_pods in instance_sizes:
        if verbose:
            print(f"\n=== N={n_nodes} nós, P={n_pods} pods ===")

        for run in range(n_runs):
            seed = BASE_SEED + run
            t0 = time.time()
            rows = run_one_instance(n_nodes, n_pods, seed, rcl_alpha_values)
            elapsed = time.time() - t0
            all_rows.extend(rows)

            if verbose:
                base = rows[0]
                milp_str = (f"{base['milp_cost']:.0f}" if base['milp_cost'] is not None
                            else "SKIP")
                grasp_by_alpha = ", ".join(
                    f"alpha={r['rcl_alpha']:.2f}->{r['grasp_cost']:.0f}"
                    + (f" (unif={r['grasp_uniform_cost']:.0f})" if "grasp_uniform_cost" in r else "")
                    for r in rows
                )
                print(f"  run {run+1}/{n_runs} (seed={seed}): "
                      f"kube={base['kube_cost']:.0f} milp={milp_str} "
                      f"| grasp: {grasp_by_alpha} [{elapsed:.1f}s]")

        if checkpoint_path:
            save_csv(all_rows, checkpoint_path)
            if verbose:
                print(f"  [checkpoint salvo: {len(all_rows)} linhas em {checkpoint_path}]")

    return all_rows


def summarize(rows: list):
    """Agrupa por (n_nodes, n_pods, rcl_alpha) e calcula médias."""
    groups = {}
    for row in rows:
        key = (row["n_nodes"], row["n_pods"], row["rcl_alpha"])
        groups.setdefault(key, []).append(row)

    summary = []
    methods = ["kube", "milp", "greedy", "ls", "grasp", "grasp_uniform"]

    for key, group_rows in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2])):
        n_nodes, n_pods, rcl_alpha = key
        entry = {"n_nodes": n_nodes, "n_pods": n_pods, "rcl_alpha": rcl_alpha}

        for m in methods:
            costs = [r[f"{m}_cost"] for r in group_rows
                     if isinstance(r.get(f"{m}_cost"), (int, float))]
            times = [r[f"{m}_time_ms"] for r in group_rows
                     if isinstance(r.get(f"{m}_time_ms"), (int, float))]
            migs = [r[f"{m}_migrations"] for r in group_rows
                    if isinstance(r.get(f"{m}_migrations"), (int, float))]

            entry[f"{m}_cost_avg"] = statistics.mean(costs) if costs else None
            entry[f"{m}_time_avg"] = statistics.mean(times) if times else None
            entry[f"{m}_migrations_avg"] = statistics.mean(migs) if migs else None
            entry[f"{m}_n_runs"] = len(costs)

        summary.append(entry)

    return summary


def print_alpha_sensitivity_table(summary: list):
    """Custo médio do GRASP por rcl_alpha, por combinação (N,P), com o
    melhor alpha de cada escala destacado."""
    alpha_values = sorted({e["rcl_alpha"] for e in summary})

    groups = {}
    for e in summary:
        key = (e["n_nodes"], e["n_pods"])
        groups.setdefault(key, []).append(e)

    print(f"{'Pods':>5} {'Nós':>4} | " + " | ".join(f"alpha={a:.2f}" for a in alpha_values)
          + " | melhor alpha")
    print("-" * 100)

    best_alphas = []
    for (n_nodes, n_pods), entries in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        entries = sorted(entries, key=lambda e: e["rcl_alpha"])
        costs = [e["grasp_cost_avg"] for e in entries]
        best_idx = costs.index(min(costs))
        best_alpha = entries[best_idx]["rcl_alpha"]
        best_alphas.append(best_alpha)

        row_str = " | ".join(f"{c:>7.0f}" for c in costs)
        print(f"{n_pods:>5} {n_nodes:>4} | {row_str} | alpha={best_alpha:.2f}")

    print(f"\nMediana dos melhores alpha observados: {statistics.median(best_alphas):.2f}")


def print_summary_table(summary: list, rcl_alpha: float):
    """Tabela principal para um valor fixo de rcl_alpha."""
    filtered = [e for e in summary if abs(e["rcl_alpha"] - rcl_alpha) < 1e-9]

    header = (f"{'Pods':>6} {'Nós':>5} | "
              f"{'Kube (custo)':>13} {'MILP (custo)':>13} {'Gulosa':>10} "
              f"{'BuscaLoc':>10} {'GRASP':>10} | "
              f"{'MILP(ms)':>10} {'GRASP(ms)':>10}")
    print(f"(rcl_alpha = {rcl_alpha:.2f})")
    print(header)
    print("-" * len(header))
    for e in filtered:
        milp_c = f"{e['milp_cost_avg']:.0f}" if e['milp_cost_avg'] is not None else "N/A"
        milp_t = f"{e['milp_time_avg']:.0f}" if e['milp_time_avg'] is not None else "N/A"
        print(f"{e['n_pods']:>6} {e['n_nodes']:>5} | "
              f"{e['kube_cost_avg']:>13.0f} {milp_c:>13} {e['greedy_cost_avg']:>10.0f} "
              f"{e['ls_cost_avg']:>10.0f} {e['grasp_cost_avg']:>10.0f} | "
              f"{milp_t:>10} {e['grasp_time_avg']:>10.1f}")


def print_weighted_vs_uniform_table(summary: list, rcl_alpha: float):
    """Compara a RCL ponderada (padrão, corrigida) com a RCL uniforme
    (clássica do artigo) no mesmo rcl_alpha — evidencia o efeito da
    correção diagnosticada para o cenário dinâmico."""
    filtered = [e for e in summary
                if abs(e["rcl_alpha"] - rcl_alpha) < 1e-9
                and e.get("grasp_uniform_cost_avg") is not None]

    if not filtered:
        print("(sem dados de grasp_uniform — RUN_UNIFORM_COMPARISON estava desligado)")
        return

    header = (f"{'Pods':>6} {'Nós':>5} | {'BuscaLoc':>10} {'GRASP ponderado':>16} "
              f"{'GRASP uniforme':>15} | {'ponderado vs LS':>16} {'vs uniforme':>12}")
    print(f"(rcl_alpha = {rcl_alpha:.2f})")
    print(header)
    print("-" * len(header))
    for e in filtered:
        ls = e["ls_cost_avg"]
        w = e["grasp_cost_avg"]
        u = e["grasp_uniform_cost_avg"]
        vs_ls = (w - ls) / ls * 100
        vs_uniform = (w - u) / u * 100
        print(f"{e['n_pods']:>6} {e['n_nodes']:>5} | {ls:>10.0f} {w:>16.0f} {u:>15.0f} | "
              f"{vs_ls:>+15.1f}% {vs_uniform:>+11.1f}%")


def save_csv(rows: list, path: str):
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    for row in rows:
        for k in row:
            if k not in fieldnames:
                fieldnames.append(k)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    CHECKPOINT_PATH = "experiment_results_raw.csv"

    print(f"Rodando experimento (N_RUNS={N_RUNS}, varredura de rcl_alpha em "
          f"{GRASP_RCL_ALPHA_VALUES})...")
    print(f"Progresso sera salvo incrementalmente em {CHECKPOINT_PATH} "
          f"apos cada combinacao (N,P).")
    rows = run_experiments(instance_sizes=DEFAULT_INSTANCE_SIZES, n_runs=N_RUNS,
                            verbose=True, checkpoint_path=CHECKPOINT_PATH)

    summary = summarize(rows)

    print("\n\n=== ANÁLISE DE SENSIBILIDADE: custo do GRASP por rcl_alpha ===")
    print_alpha_sensitivity_table(summary)

    # Alpha escolhido para a tabela principal: mediana dos ótimos por escala.
    chosen_alpha = statistics.median(
        min(({e["rcl_alpha"]: e["grasp_cost_avg"]
              for e in summary if (e["n_nodes"], e["n_pods"]) == key}).items(),
            key=lambda kv: kv[1])[0]
        for key in {(e["n_nodes"], e["n_pods"]) for e in summary}
    )

    print(f"\n\n=== TABELA PRINCIPAL (rcl_alpha = {chosen_alpha:.2f}) ===")
    print_summary_table(summary, rcl_alpha=chosen_alpha)

    if RUN_UNIFORM_COMPARISON:
        print(f"\n\n=== GRASP PONDERADO vs. UNIFORME (rcl_alpha = {chosen_alpha:.2f}) ===")
        print_weighted_vs_uniform_table(summary, rcl_alpha=chosen_alpha)

    save_csv(rows, CHECKPOINT_PATH)
    print(f"\nResultados finais salvos em {CHECKPOINT_PATH}")
