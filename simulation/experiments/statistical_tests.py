"""Friedman + Wilcoxon pareado (correção de Holm).

Como a escolha da melhor configuração é lexicográfica (admissão, depois custo),
os testes seguem a mesma ordem:

- **Friedman**: em cada instância (N, P, seed), as configurações são ordenadas
  por (maior admissão ΣA, menor custo ΣC) e a posição vira o rank (empates pela
  média). O Friedman testa os ranks entre as configurações.
- **Wilcoxon**: compara a melhor (menor rank médio) com cada outra usando a
  diferença de custo ΣC, só nas instâncias em que a admissão empata entre as
  duas. Onde a admissão difere, a prioridade 1 já decide e o custo não é
  comparável. A tabela mostra quantos pares entraram.

Rodam dois conjuntos: as configurações implantáveis e todas, com a referência
(Scheduler MILP) incluída."""

import statistics

from .tables import GROUPS, configs_in_group, short_label

SIGNIFICANCE = 0.05
MIN_BLOCKS = 2
MIN_CONFIGS = 3
ADMISSION_TOLERANCE = 1e-6
COST_TOLERANCE = 1e-9


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
    """Uma linha por instância (N, P, seed) que tenha todas as configs:
    [(admissão, custo), ...] na ordem de `configs`."""
    blocks = {}
    for row in rows:
        if row["config"] in configs:
            key = (row["n_nodes"], row["n_pods"], row["seed"])
            blocks.setdefault(key, {})[row["config"]] = (float(row["admission"]),
                                                          float(row["cost"]))
    complete = [block for block in blocks.values() if len(block) == len(configs)]
    return [[block[config] for config in configs] for block in complete]


def _lexicographic_ranks(values: list) -> list:
    """Posto (1 = melhor, empates pela média) de [(admissão, custo), ...]."""
    def tied(a, b):
        return abs(a[0] - b[0]) <= ADMISSION_TOLERANCE and abs(a[1] - b[1]) <= COST_TOLERANCE

    def better(a, b):
        if abs(a[0] - b[0]) > ADMISSION_TOLERANCE:
            return a[0] > b[0]
        return a[1] < b[1] - COST_TOLERANCE

    ranks = []
    for value in values:
        smaller = sum(1 for other in values if better(other, value))
        equal = sum(1 for other in values if tied(other, value))
        ranks.append(smaller + (equal + 1) / 2)
    return ranks


def _wilcoxon(matrix: list, column: int, best: int):
    """(p-valor, nº de pares) da diferença de custo nas instâncias com admissão empatada."""
    from scipy.stats import wilcoxon

    differences = [row[column][1] - row[best][1] for row in matrix
                   if abs(row[column][0] - row[best][0]) <= ADMISSION_TOLERANCE]
    if not differences or all(abs(d) < COST_TOLERANCE for d in differences):
        return 1.0, len(differences)
    return wilcoxon(differences).pvalue, len(differences)


def run_statistical_tests(rows: list):
    try:
        from scipy.stats import friedmanchisquare  # noqa: F401
    except ImportError:
        print("\n(scipy não instalado: testes estatísticos pulados — pip install scipy)")
        return

    all_configs = list(dict.fromkeys(row["config"] for row in rows))
    deployable = configs_in_group(all_configs, GROUPS[0])
    _run_for(rows, deployable, "IMPLANTÁVEIS")
    if len(deployable) < len(all_configs):
        _run_for(rows, all_configs, "TODAS, com a referência (Scheduler MILP)")


def _run_for(rows: list, configs: list, title: str):
    from scipy.stats import friedmanchisquare

    matrix = _complete_blocks(rows, configs)
    if len(matrix) < MIN_BLOCKS or len(configs) < MIN_CONFIGS:
        print(f"\n({title}: dados insuficientes para os testes estatísticos)")
        return

    ranks = [_lexicographic_ranks(row) for row in matrix]
    average_rank = {c: statistics.mean(r[k] for r in ranks) for k, c in enumerate(configs)}
    statistic, p = friedmanchisquare(*[[rank[k] for rank in ranks] for k in range(len(configs))])

    print(f"\n=== TESTES ESTATÍSTICOS: {title} ({len(matrix)} instâncias pareadas) ===")
    print("Rank por instância: (maior admissão, menor custo). Wilcoxon: custo nas instâncias "
          "com admissão empatada.")
    print(f"Friedman: chi2 = {statistic:.1f}, p = {p:.2e}")
    _print_pairwise(configs, matrix, average_rank)


def _print_pairwise(configs: list, matrix: list, average_rank: dict):
    best = min(configs, key=lambda c: average_rank[c])
    others = [c for c in configs if c != best]
    results = [_wilcoxon(matrix, configs.index(c), configs.index(best)) for c in others]
    adjusted = holm_adjust([p for p, _ in results])

    print(f"\n{'Configuração':>12} | {'rank médio':>10} | {'pares':>5} | "
          f"Wilcoxon vs melhor (Holm)")
    print("-" * 74)
    print(f"{short_label(best):>12} | {average_rank[best]:>10.2f} | {'':>5} | (melhor)")
    for config, (_, pairs), p in sorted(zip(others, results, adjusted),
                                        key=lambda x: average_rank[x[0]]):
        verdict = "diferença significativa" if p < SIGNIFICANCE else "empate estatístico"
        print(f"{short_label(config):>12} | {average_rank[config]:>10.2f} | {pairs:>5} | "
              f"p={p:.2e} ({verdict})")
