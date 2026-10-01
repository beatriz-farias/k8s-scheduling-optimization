# k8s-rescheduling-optimization

Código e resultados do TCC sobre **escalonamento dinâmico de contêineres no Kubernetes com penalidade de migração**.

O trabalho estende o modelo de Martins et al. (*Abordagens Heurísticas para o Problema de Escalonamento de Contêineres em Orquestradores Kubernetes*, SBPO 2025) para um cenário **multi-período**: a cada período, alguns pods saem do cluster e outros chegam. Cada evicção (reinício de um pod para movê-lo de nó) custa uma penalidade **ω (omega)**. O objetivo é minimizar o custo de operar o cluster sem provocar disrupção desnecessária.

O projeto simula a arquitetura real do Kubernetes, com **Scheduler** e **Descheduler** separados, e compara várias combinações de componentes. Só são comparadas configurações que **podem ser executadas no Kubernetes**.

## Modelo

### Função de custo (avaliação de todos os métodos)

O custo de cada período *t* é o que o operador do cluster paga:

```
C_t  =  Σ_i α_i·x_it + Σ_i Σ_j (β_i + γ_i·e_j)·y_ijt   +   ω·E_t   +   M·P_t
        \______________ infraestrutura ______________/     disrupção    Pending
```

| Termo | Significado |
|---|---|
| infraestrutura | nós ligados (α) e pods alocados (β, γ) |
| `E_t` | pods **evictados** no período. Toda evicção reinicia o pod, então paga ω mesmo que o pod volte ao mesmo nó |
| `P_t` | pods sem nó (**Pending**) ao fim do período |
| `M` | penalidade por pod Pending: 10 × (maior α + maior β + maior penalidade de erro). É maior que o custo de alocar qualquer pod em qualquer nó, então deixar um pod Pending nunca compensa |

O custo total do experimento é `Σ_t C_t`. Os três componentes são registrados separadamente (`infra_cost`, `disruption_cost`, `pending_cost`). Assim dá para analisar a **fronteira custo de infraestrutura × número de evicções** sem depender do valor de ω, que é arbitrário (metade do β médio).

**Premissa: nó vazio não custa.** O termo α só faz sentido se um nó sem pods deixa de ser cobrado. No Kubernetes isso exige o **Cluster Autoscaler**, que remove nós vazios. Todo o ganho do Descheduler vem de esvaziar nós, então essa premissa vale também para os testes em cluster real.

### MILP por período

O MILP (`milp_model.py`, Gurobi) resolve, em cada período *t*, dado o conjunto de pods ativos e a alocação atual (`ȳ`):

```
min  Σ_i α_i·x_i  +  Σ_i Σ_j (β_i + γ_i·e_j)·y_ij  +  Σ_j∈ativos-antes ω·(1 − y_{j,ȳ(j)})

s.a. Σ_i y_ij = 1                   ∀ pod j          (cada pod em exatamente um nó)
     Σ_j u_j·y_ij ≤ U_i·x_i         ∀ nó i           (capacidade, só se o nó estiver aberto)
     Σ_j (1 − y_{j,ȳ(j)}) ≤ K                        (opcional: no máximo K pods mudam de nó)
     x_i, y_ij ∈ {0,1}
```

| Símbolo | Significado |
|---|---|
| `α_i` | custo de abrir/ativar o nó *i* |
| `β_i` | custo de alocar um pod no nó *i* |
| `γ_i`, `e_j` | penalidade de falhas do nó *i* × número de erros do pod *j* (desativado por padrão) |
| `U_i`, `u_j` | capacidade do nó *i* e demanda do pod *j* |
| `ω` | penalidade por migração/evicção (padrão: metade do `β` médio) |
| `K` | limite de evicções por ciclo (opcional; exige alocação inicial, usada também como warm start) |

Cada pod que muda de nó corresponde a uma evicção, então o objetivo é o mesmo `C_t` acima (com `P_t = 0`, imposto pela primeira restrição). O MILP é **míope**: otimiza cada período sem enxergar os seguintes.

## Arquitetura Scheduler + Descheduler

Cada período segue o fluxo real do Kubernetes:

1. **Scheduler**: coloca apenas os pods **novos**. Pods que já estão rodando não são tocados.
2. **Descheduler**: escolhe **quais pods evictar**. Ele **não escolhe o destino**. Há um **limite de evicções por ciclo (K)**, como no Descheduler real (`maxNoOfPodsToEvictTotal`), e cada pod é evictado no máximo uma vez por ciclo.
3. **Scheduler**: os pods evictados voltam para a fila e são recolocados na ordem de evicção, com a mesma regra usada para pods novos. Um pod evictado pode até voltar ao mesmo nó.

Para decidir quem evictar, os Deschedulers heurísticos prevêem onde o Scheduler recolocaria cada pod simulando a regra dele. Só vale evictar se a redução prevista da infraestrutura superar ω (o custo da própria evicção) mais um limiar mínimo. A previsão avalia uma evicção por vez. Na execução, todos os pods do ciclo são evictados antes de serem recolocados, então o resultado final pode diferir do previsto. Isso também acontece no Kubernetes, onde o Descheduler não controla as decisões do Scheduler.

Os dois componentes são plugáveis e o experimento testa todas as combinações (3 × 5 = 15):

| Componente | Opção | Descrição |
|---|---|---|
| Scheduler | `least_requested` | kube-scheduler padrão: escolhe o nó com mais capacidade livre relativa e não conhece custos |
| Scheduler | `greedy` | decide pod a pod pelo menor custo marginal (lógica do plugin de *Score*) |
| Scheduler | `milp` | coloca a **fila inteira de uma vez** com MILP exato, com os pods que já rodam fixos. Pods que não cabem ficam Pending (pagam M). Se o solver não devolver solução no limite de tempo, usa o guloso |
| Descheduler | `none` | nenhuma evicção |
| Descheduler | `ls_first` | percorre os pods e evicta o **primeiro** cuja recolocação prevista reduz o custo |
| Descheduler | `ls_best` | a cada passo evicta o pod de **maior** redução prevista |
| Descheduler | `grasp` | GRASP sobre conjuntos de evicção. A RCL guarda as melhores evicções e sorteia com peso por delta. Cada conjunto construído é avaliado executando as evicções de fato, e fica o de menor custo real. A primeira iteração é gulosa (igual a `ls_best`) |
| Descheduler | `milp` | MILP exato planeja a alocação com no máximo K pods movidos e evicta os pods que o plano move. No plano, cada pod movido paga ω, igual a uma evicção. Os destinos do plano **não** são impostos: quem recoloca os pods é o Scheduler |

Como o Descheduler só evicta, **o resultado depende da regra do Scheduler**. Com o `least_requested`, os pods evictados vão para os nós mais vazios e não para os mais baratos, então o Descheduler tem pouco efeito sobre o custo. O Descheduler MILP sofre o mesmo problema: se o Scheduler não segue o plano, as evicções podem piorar o custo. A combinação **`milp+milp`** fecha esse ciclo: o plano mantém os pods não movidos onde estão, e o Scheduler MILP recoloca os evictados resolvendo o mesmo subproblema, chegando a um custo de infraestrutura igual ou menor que o planejado.

O Scheduler decide no momento em que o pod chega, então o realista é ser rápido (`least_requested`, `greedy`). O Descheduler roda periodicamente e tem mais tempo, então métodos mais caros (GRASP, MILP) podem compensar ali.

### Ponto de comparação

**Baseline `least_requested+none`**: kube-scheduler padrão sem Descheduler. É o comportamento de um cluster Kubernetes sem customização, e o gap de cada configuração é medido contra ele.

## Experimentos

Parâmetros em `optimization/experiments/settings.py`.

1. **Fatorial**: 3 Schedulers × 5 Deschedulers com K = 10 evicções por período.
2. **Sensibilidade de K**: K ∈ {1, 2, 5, 10, 20, 50, sem limite} para `least_requested+ls_best`, `greedy+ls_best` e `milp+milp`. O resultado é a curva **custo de infraestrutura × evicções**, o trade-off central de um Descheduler.

Evicções são a medida de disrupção cobrada no custo. O runner também registra **migrações** (pods do período anterior que terminam em outro nó) como informação complementar: uma evicção não vira migração quando o pod volta ao mesmo nó.

### Escolha da melhor configuração

- O critério principal é o **custo total** `Σ_t C_t`. O custo de infraestrutura, as evicções e o tempo são critérios secundários.
- As seeds são as mesmas para todas as configurações, então as amostras são pareadas. O runner aplica o **teste de Friedman** sobre todas as configurações, em que cada bloco é uma instância (N, P, seed). Depois compara a de melhor rank médio com cada uma das outras usando **Wilcoxon pareado com correção de Holm**.

### Número de execuções (`N_RUNS = 10`)

Com 11 tamanhos × 10 seeds são 110 blocos pareados no teste de Friedman. O custo dominante é o MILP (até 60 s por período ou por fila de pods), não as heurísticas.

### Premissas da simulação

- A evicção e a recolocação acontecem no mesmo período. O Scheduler processa a fila de pods evictados logo após o ciclo do Descheduler.
- Um pod que o Scheduler não consegue colocar fica Pending e paga M.
- Nó vazio não custa (Cluster Autoscaler ativo; ver [Função de custo](#função-de-custo-avaliação-de-todos-os-métodos)).

## Estrutura

```
optimization/
├── instance_generator.py        # gera instâncias multi-período (churn, capacidades, custos)
├── milp_model.py                # MILP exato por período (Gurobi); aceita warm start e limite de movimentos
├── incremental_scheduler.py     # ponto de entrada da arquitetura + demo de todas as combinações
├── run_experiments.py      # linha de comando: fatorial, sensibilidade e análise
├── incremental/                 # simulação Scheduler + Descheduler
│   ├── cluster_state.py         #   estado do cluster (alocação, ocupação dos nós)
│   ├── cost.py                  #   modelo de custo C_t (infra + ω·evicções + M·Pending)
│   ├── schedulers.py            #   least_requested e greedy
│   ├── milp_scheduler.py        #   Scheduler MILP (coloca a fila em lote)
│   ├── scheduler_registry.py    #   registro dos Schedulers
│   ├── evictions.py             #   política (limite K), previsão e execução de evicções
│   ├── simulation.py            #   laço por período: Scheduler → Descheduler → Scheduler
│   ├── results.py               #   resultado por período e do horizonte
│   └── deschedulers/            #   none, local_search (ls_first/ls_best), grasp, milp
└── experiments/                 # bateria de experimentos
    ├── settings.py              #   tamanhos, seeds, K, parâmetros e caminhos dos CSVs
    ├── configurations.py        #   configurações do fatorial e da sensibilidade
    ├── runner.py                #   execução das instâncias
    ├── results_store.py         #   CSV com retomada
    ├── summary.py, tables.py    #   agregação e tabelas
    └── statistical_tests.py     #   Friedman + Wilcoxon com Holm
results/
├── incremental_factorial_raw.csv    # fatorial (uma linha por instância × configuração)
└── incremental_sensitivity_raw.csv  # sensibilidade de K
```

Os CSVs são gerados pela execução dos experimentos.

## Instâncias

`generate_instance(n_nodes, n_pods_total, n_periods=20, seed=...)`:

- Custos e demandas seguem as faixas de Martins et al. (2023): `α_i, β_i ~ U(1, 4n)` e `u_j ~ U(1, 10)`.
- Metade dos pods está presente desde o início (`ramp_fraction=0.5`). A cada período, 15% dos pods ativos saem (`churn_rate=0.15`) e voltam ao pool de espera, enquanto novos pods chegam.
- A capacidade dos nós é dimensionada pelo pico de demanda agregada, com margem de 1,6×, para que todos os períodos sejam factíveis.

Os experimentos usam 20 períodos, os tamanhos (nós, pods) ∈ {(10,50), (10,100), (10,200), (20,100), (20,200), (20,500), (50,200), (50,500), (50,1000), (100,500), (100,1000)} e as seeds a partir de 100.

## Como executar

Requisitos: Python 3.9+, [Gurobi](https://www.gurobi.com/) com licença válida (para as opções MILP) e scipy (para os testes estatísticos). As heurísticas usam só a biblioteca padrão.

```bash
pip install gurobipy scipy
cd optimization

# Exemplo rápido: todas as combinações numa instância com 10 nós e 50 pods
python incremental_scheduler.py

# Bateria completa: fatorial + sensibilidade + análise → results/*.csv
python run_experiments.py

# Etapas separadas
python run_experiments.py --stage factorial
python run_experiments.py --stage sensitivity
python run_experiments.py --stage analyze        # só relê os CSVs e imprime tabelas/testes

# Teste rápido (2 tamanhos, grava em *_quick.csv)
python run_experiments.py --quick --runs 2

# Sem Gurobi: pula as configurações com Scheduler ou Descheduler MILP
python run_experiments.py --no-milp
```

Os CSVs são salvos após cada instância. Se a execução for interrompida, basta rodar o mesmo comando de novo: as linhas já calculadas são puladas.

## Resultados

*A preencher após rodar `run_experiments.py`.* O runner imprime:

- o gap do custo total e do custo de infraestrutura em relação ao baseline `least_requested+none`, as evicções, as migrações e o tempo de cada combinação Scheduler × Descheduler, por tamanho;
- o rank médio de cada configuração, o teste de Friedman e o Wilcoxon da melhor contra as demais;
- para cada limite K, o custo total e o par infraestrutura/evicções.
