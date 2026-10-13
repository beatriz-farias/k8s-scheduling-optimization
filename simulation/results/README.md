# Resultados dos experimentos

```
results/
├── dados/      CSVs (uma linha por instância × configuração; o código retoma a partir deles)
├── analises/   saídas de `python -m experiments --analyze` guardadas em texto
└── logs/       saída (.log) e erros (.err) de cada execução
```

Os caminhos dos CSVs são definidos em `experiments/settings.py` (`DATA_DIR`). Os parâmetros de cada execução e os números estão na seção **Resultados** do `README.md` da raiz.

## Dados (`dados/`)

Nome: `factorial_lam<λ>_omega<F>_margin<folga>_cost-<modelo>.csv`, com ω = F × custo médio de nó.

| Arquivo | Execução | Tamanhos |
|---|---|---|
| `factorial_lam1_omega0.5_margin1.1_cost-martins.csv` | Baseline | os 11 |
| `factorial_lam1_omega{0,0.25,1,2}_margin1.1_cost-martins.csv` | Varredura de ω | os 11 |
| `factorial_lam{0,2,5}_omega0.5_margin1.1_cost-martins.csv` | Varredura de λ (λ = 1 é o baseline) | 10×100, 20×200, 20×500 |
| `factorial_lam1_omega0.5_margin1.6_cost-martins.csv` | Folga 1,6 | 10×100, 20×200, 20×500 |
| `factorial_lam1_omega0.5_margin1.1_cost-proportional.csv` | Custo proporcional | 10×100, 20×200, 20×500 |

## Análises (`analises/`)

| Arquivo | Conteúdo |
|---|---|
| `omega_0_0.5_1_2.txt` | `--analyze --omega-fraction 0 0.5 1 2` (sem o ω = 0,25) |
| `omega_0_0.25_0.5_1_2.txt` | `--analyze --omega-fraction 0 0.25 0.5 1 2`, a análise completa da varredura de ω |

## Logs (`logs/`)

Os arquivos `.err` não vazios são falhas do Gurobi por falta de rede (`Could not resolve host: token.gurobi.com`). Esses processos terminaram com código 1 e foram relançados; a execução retoma do CSV. Por isso os tempos (`time_ms`) incluem períodos de pausa ou interrupção e devem ser usados com cautela.

| Pasta | Arquivos | O que são |
|---|---|---|
| `baseline/` | `baseline_grasp_corrigido.*` | tentativa do baseline com o GRASP corrigido; terminou com código 1 (rede) |
| | `baseline_grasp_2.*` | nova tentativa, concluída com código 0 |
| | `baseline_lam1_omega0.5_margin1.1.log`, `run.log`, `run.err` | log da execução do baseline; `run.log` é cópia idêntica do primeiro |
| `omega/` | `omega_3tam_1.*`, `omega_3tam_2.*` | varredura de ω nos 3 tamanhos pequenos; a 1ª caiu por rede, a 2ª concluiu |
| | `omega_11tam_{0,0.25,1,2}.*` | varredura de ω completada nos 11 tamanhos, um por valor de ω; no ω = 1 a 1ª tentativa caiu por rede e a 2ª concluiu |
| `lambda/` | `lambda.*` | tentativa que caiu por rede logo no início |
| | `lambda_2.*` | varredura de λ concluída |
| `folga_e_custo/` | `folga1.6.*` | folga 1,6 |
| | `custo_proporcional.*`, `custo_proporcional_2.*` | custo proporcional; a 1ª caiu por rede, a 2ª concluiu |
| `cadeias/` | `chain.log`, `chain2.log`, `chain3.log` | início, fim e código de saída de cada etapa encadeada (cadeias 1 e 2 em 8 e 9/10; cadeia 3 em 10 e 11/10, que contém as etapas `omega1`, `omega0`, `omega2`; o ω = 0,25 foi lançado à parte, sem cadeia) |

Os nomes dentro de `cadeias/` (`omega`, `lambda`, `folga1.6`, `custo_proporcional`, `baseline_grasp`) são os dos logs antes da reorganização: `omega` → `omega_3tam_*`, `omega0_full`/`omega1_full`/`omega2_full` → `omega_11tam_0/1/2`.
