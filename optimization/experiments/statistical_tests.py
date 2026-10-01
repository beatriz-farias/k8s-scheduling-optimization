"""Friedman + Wilcoxon pareado (correção de Holm) sobre o custo total."""

import statistics

from .tables import short_label

SIGNIFICANCE = 0.05
MIN_BLOCKS = 2
MIN_CONFIGS = 3


def holm_adjust(pvalues: list) -> list:
    """Correção de Holm-Bonferroni; retorna p-valores ajustados na ordem original."""
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    adjusted = [0.0] * len(pvalues)
    running_max = 0.0
    for rank, index in enumerate(order):
        running_max = max(running_max, min(1.0, (len(pvalues) - rank) * pvalues[index]))
        adjusted[index] = running_max
    return adjusted


def _complete_blocks(rows: list, configs: list) -> list:
    """Uma linha de custos por instância (N, P, seed) que tenha todas as configs."""
    blocks = {}
    for row in rows:
        if row["config"] in configs:
            key = (row["n_nodes"], row["n_pods"], row["seed"])
            blocks.setdefault(key, {})[row["config"]] = float(row["cost"])
    complete = [block for block in blocks.values() if len(block) == len(configs)]
    return [[block[config] for config in configs] for block in complete]


def _wilcoxon_pvalue(matrix: list, column: int, best: int) -> float:
    from scipy.stats import wilcoxon

    differences = [row[column] - row[best] for row in matrix]
    if all(abs(d) < 1e-9 for d in differences):
        return 1.0
    return wilcoxon(differences).pvalue


def run_statistical_tests(rows: list):
    try:
        from scipy.stats import friedmanchisquare, rankdata
    except ImportError:
        print("\n(scipy não instalado: testes estatísticos pulados — pip install scipy)")
        return

    configs = list(dict.fromkeys(row["config"] for row in rows))
    matrix = _complete_blocks(rows, configs)
    if len(matrix) < MIN_BLOCKS or len(configs) < MIN_CONFIGS:
        print("\n(dados insuficientes para os testes estatísticos)")
        return

    ranks = [rankdata(row) for row in matrix]
    average_rank = {c: statistics.mean(r[k] for r in ranks) for k, c in enumerate(configs)}
    statistic, p = friedmanchisquare(*[[row[k] for row in matrix] for k in range(len(configs))])

    print(f"\n=== TESTES ESTATÍSTICOS (custo; {len(matrix)} instâncias pareadas) ===")
    print(f"Friedman: chi2 = {statistic:.1f}, p = {p:.2e}")
    _print_pairwise(configs, matrix, average_rank)


def _print_pairwise(configs: list, matrix: list, average_rank: dict):
    best = min(configs, key=lambda c: average_rank[c])
    others = [c for c in configs if c != best]
    raw = [_wilcoxon_pvalue(matrix, configs.index(c), configs.index(best)) for c in others]

    print(f"\n{'Configuração':>12} | {'rank médio':>10} | Wilcoxon vs melhor (Holm)")
    print("-" * 66)
    print(f"{short_label(best):>12} | {average_rank[best]:>10.2f} | (melhor)")
    for config, p in sorted(zip(others, holm_adjust(raw)), key=lambda x: average_rank[x[0]]):
        verdict = "diferença significativa" if p < SIGNIFICANCE else "empate estatístico"
        print(f"{short_label(config):>12} | {average_rank[config]:>10.2f} | "
              f"p={p:.2e} ({verdict})")
