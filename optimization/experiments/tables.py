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


def print_factorial_tables(rows: list):
    summary = ResultsSummary(rows)
    sizes, configs = summary.sizes(), summary.configs()
    base = settings.BASELINE_LABEL

    print(f"\n{LEGEND}")
    print_pivot(sizes, configs, _gap_cell(summary, "cost", base),
                f"=== CUSTO TOTAL (infra + omega*evicções + M*Pending): "
                f"gap % vs {short_label(base)} ===")
    print_pivot(sizes, configs, _gap_cell(summary, "infra_cost", base),
                f"=== CUSTO DE INFRAESTRUTURA (alpha + beta): gap % vs {short_label(base)} ===")
    print_pivot(sizes, configs, _metric_cell(summary, "evictions", ".1f"),
                "=== EVICÇÕES totais (média das seeds) ===")
    print_pivot(sizes, configs, _metric_cell(summary, "migrations", ".1f"),
                "=== MIGRAÇÕES: pods do período anterior que mudaram de nó (média) ===")
    print_pivot(sizes, configs, _metric_cell(summary, "time_ms", ".0f"),
                "=== TEMPO total em ms (média das seeds) ===")
    _warn_about_pending(rows)


def _warn_about_pending(rows: list):
    pending = [row for row in rows if float(row["pending_pods"] or 0) > 0]
    if pending:
        print(f"\nAVISO: {len(pending)} execuções com pods Pending "
              f"(penalizados com M no custo total).")


def print_sensitivity_tables(rows: list):
    """Duas tabelas por configuração (linhas = tamanho, colunas = limite K):
    custo total médio, e infraestrutura/evicções médias, que formam a
    fronteira custo x disrupção sem depender do valor de ω."""
    summary = ResultsSummary(rows)
    sizes, configs = summary.sizes(), summary.configs()
    for base in dict.fromkeys(config.split("@")[0] for config in configs):
        columns = [c for c in configs if c.split("@")[0] == base]
        _print_sensitivity_for(summary, sizes, base, columns)


def _print_sensitivity_for(summary, sizes, base, columns):
    limits = [column.split("@")[1] for column in columns]

    def total_cell(n_nodes, n_pods, config):
        group = summary.get(n_nodes, n_pods, config)
        return f"{group['cost']:.0f}" if group else "-"

    def frontier_cell(n_nodes, n_pods, config):
        group = summary.get(n_nodes, n_pods, config)
        return f"{group['infra_cost']:.0f}/{group['evictions']:.0f}" if group else "-"

    print_pivot(sizes, columns, total_cell,
                f"=== SENSIBILIDADE {short_label(base)}: custo total por limite K ===", limits)
    print_pivot(sizes, columns, frontier_cell,
                f"=== SENSIBILIDADE {short_label(base)}: infraestrutura/evicções por K ===",
                limits)
