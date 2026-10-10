"""Tabelas de resultados (texto) a partir de um ResultsSummary."""

from . import settings
from .summary import ResultsSummary

SHORT_NAMES = {"least_requested": "LR", "greedy": "GR", "milp": "MS"}
LEGEND = ("Legenda: LR = Scheduler least-requested (kube padrão), GR = Scheduler guloso "
          "por custo, MS = Scheduler MILP")
MIN_COLUMN_WIDTH = 9


def short_label(label: str) -> str:
    """Abrevia só o Scheduler (prefixo antes do '+'); o Descheduler 'milp' fica por extenso."""
    scheduler, separator, rest = label.partition("+")
    return SHORT_NAMES.get(scheduler, scheduler) + separator + rest


def print_pivot(sizes: list, columns: list, cell, title: str, column_names: list = None):
    """Linhas = tamanho da instância, colunas = configurações."""
    column_names = column_names or [short_label(c) for c in columns]
    width = max(MIN_COLUMN_WIDTH, *(len(name) for name in column_names))
    print(f"\n{title}")
    header = f"{'Pods':>5} {'Nós':>4} | " + " ".join(f"{n:>{width}}" for n in column_names)
    print(header)
    print("-" * len(header))
    for n_nodes, n_pods in sizes:
        cells = [f"{cell(n_nodes, n_pods, column):>{width}}" for column in columns]
        print(f"{n_pods:>5} {n_nodes:>4} | " + " ".join(cells))


def _gap_cell(summary: ResultsSummary, metric: str, base: str):
    def cell(n_nodes, n_pods, config):
        group = summary.get(n_nodes, n_pods, config)
        reference = summary.get(n_nodes, n_pods, base)
        if not group or not reference or group[metric] is None or not reference[metric]:
            return "-"
        return f"{(group[metric] - reference[metric]) / reference[metric] * 100:+.1f}%"
    return cell


def _metric_cell(summary: ResultsSummary, metric: str, fmt: str):
    def cell(n_nodes, n_pods, config):
        group = summary.get(n_nodes, n_pods, config)
        return format(group[metric], fmt) if group and group[metric] is not None else "-"
    return cell


GROUPS = (
    ("IMPLANTÁVEIS (Scheduler heurístico, decide no caminho crítico)",
     lambda scheduler: scheduler in settings.DEPLOYABLE_SCHEDULERS),
    ("REFERÊNCIA (Scheduler MILP: limite superior, não implantável no caminho crítico)",
     lambda scheduler: scheduler in settings.REFERENCE_SCHEDULERS),
)


def scheduler_of(config: str) -> str:
    return config.partition("+")[0]


def configs_in_group(configs: list, group: tuple) -> list:
    return [c for c in configs if group[1](scheduler_of(c))]


def print_factorial_tables(rows: list):
    """Uma seção para as configurações implantáveis e outra para a referência
    (Scheduler MILP). Em ambas, os gaps são medidos contra o baseline
    kube-scheduler padrão. A admissão (prioridade 1) vem antes do custo C."""
    summary = ResultsSummary(rows)
    sizes, all_configs = summary.sizes(), summary.configs()

    print(f"\n{LEGEND}")
    for group in GROUPS:
        configs = configs_in_group(all_configs, group)
        if configs:
            print(f"\n################ {group[0]} ################")
            _print_group_tables(summary, sizes, configs)
    _warn_about_pending(rows)


def _print_group_tables(summary, sizes, configs):
    base = settings.BASELINE_LABEL
    print_pivot(sizes, configs, _metric_cell(summary, "admission", ".2f"),
                "=== ADMISSÃO A = soma de w_j*a_j nos períodos (prioridade 1; maior é melhor) ===")
    print_pivot(sizes, configs, _metric_cell(summary, "pending_pods", ".1f"),
                "=== PODS PENDING somados nos períodos (média das seeds) ===")
    print_pivot(sizes, configs, _gap_cell(summary, "cost", base),
                f"=== CUSTO C = nós + lambda*fragmentação + evicções (prioridade 2): "
                f"gap % vs {short_label(base)} ===")
    print_pivot(sizes, configs, _gap_cell(summary, "node_cost", base),
                f"=== CUSTO DE NÓS soma de c_i*x_i: gap % vs {short_label(base)} ===")
    print_pivot(sizes, configs, _metric_cell(summary, "frag_cost", ".1f"),
                "=== CUSTO DE FRAGMENTAÇÃO lambda*soma de c_i*F_i (média das seeds) ===")
    print_pivot(sizes, configs, _metric_cell(summary, "fragmented_pct", ".1f"),
                "=== % DE CAPACIDADE FRAGMENTADA (média) ===")
    print_pivot(sizes, configs, _metric_cell(summary, "utilization_demanda", ".3f"),
                "=== UTILIZAÇÃO: requests alocados / capacidade ligada (média) ===")
    print_pivot(sizes, configs, _metric_cell(summary, "evictions", ".1f"),
                "=== EVICÇÕES totais (média das seeds) ===")
    print_pivot(sizes, configs, _metric_cell(summary, "migrations", ".1f"),
                "=== MIGRAÇÕES: pods do período anterior que mudaram de nó (média) ===")
    print_pivot(sizes, configs, _metric_cell(summary, "time_ms", ".0f"),
                "=== TEMPO total em ms (média das seeds) ===")


def _warn_about_pending(rows: list):
    pending = [row for row in rows if float(row["pending_pods"] or 0) > 0]
    if pending:
        print(f"\nAVISO: {len(pending)} execuções com pods Pending "
              f"(reduzem a admissão; o pod é tentado de novo no período seguinte).")


SWEEP_METRICS = (
    ("admission", ".2f", "ADMISSÃO"), ("node_cost", ".0f", "CUSTO DE NÓS"),
    ("fragmented_pct", ".2f", "% DE CAPACIDADE FRAGMENTADA"),
    ("utilization_demanda", ".3f", "UTILIZAÇÃO"), ("evictions", ".1f", "EVICÇÕES"),
)


def print_sweep_comparison(rows_by_setting: dict):
    """Varredura de parâmetros: linhas = combinação (lambda, omega), colunas =
    configurações; média sobre todas as instâncias. O custo C inclui lambda e
    omega, então a comparação usa métricas que não dependem da escala deles:
    custo de nós e evicções formam a fronteira custo x disrupção sem fixar o
    omega."""
    rows_by_setting = {name: rows for name, rows in rows_by_setting.items() if rows}
    if len(rows_by_setting) < 2:
        return
    all_configs = list(dict.fromkeys(
        r["config"] for rows in rows_by_setting.values() for r in rows))
    label_width = max(len(name) for name in rows_by_setting)
    for group in GROUPS:
        configs = configs_in_group(all_configs, group)
        if not configs:
            continue
        names = [short_label(c) for c in configs]
        width = max(MIN_COLUMN_WIDTH, *(len(n) for n in names))
        for metric, fmt, title in SWEEP_METRICS:
            print(f"\n=== VARREDURA: {title} (média de todas as instâncias) | {group[0].split(' (')[0]} ===")
            header = f"{'':>{label_width}} | " + " ".join(f"{n:>{width}}" for n in names)
            print(header)
            print("-" * len(header))
            for name, rows in rows_by_setting.items():
                cells = [_mean_cell(rows, config, metric, fmt) for config in configs]
                print(f"{name:>{label_width}} | " + " ".join(f"{c:>{width}}" for c in cells))


def _mean_cell(rows: list, config: str, metric: str, fmt: str) -> str:
    values = [float(r[metric]) for r in rows if r["config"] == config and r[metric] != ""]
    return format(sum(values) / len(values), fmt) if values else "-"
