# k8s-scheduling-optimization

TCC sobre **escalonamento dinâmico de contêineres no Kubernetes com penalidade de migração**.

**Objetivo do trabalho:** implementar **plugins em Go** para o Kubernetes (Scheduler Framework do kube-scheduler e plugins do Descheduler) que aplicam a função objetivo do TCC (admissão, custo de nós, fragmentação e custo de evicção) e **avaliá-los em clusters simulados com o [KWOK](https://kwok.sigs.k8s.io/)**.

O modelo (base: Martins et al. e Carneiro et al., SBPO 2025) e os resultados com a simulação em Python estão em [`simulation/`](simulation/README.md). Essa simulação é um **protótipo local**: serviu para formular a função objetivo e comparar heurísticas e MILP, e agora é a referência para validar os plugins.

## Estrutura

```
simulation/     # protótipo em Python (modelo, heurísticas, MILP, experimentos e resultados)
evaluator/      # pacote Go com a função objetivo, compartilhado pelos plugins
plugins/
├── scheduler/      # plugins Go do Scheduler Framework (Filter/Score) para o kube-scheduler
└── descheduler/    # plugins Go para o kubernetes-sigs/descheduler (estratégias de evicção)
deploy/         # KubeSchedulerConfiguration, Dockerfiles e manifests para instalar os plugins
kwok/
└── scenarios/      # clusters e cargas no KWOK (nós falsos, pods, churn por período)
analysis/       # coleta e comparação das métricas do KWOK com os resultados da simulação
```

## Evaluator

[`evaluator/`](evaluator/) é o pacote Go que implementa a função objetivo e é usado pelos dois plugins. Ele não depende do Kubernetes: cada plugin converte seus objetos para vetores `int64` de recursos, `Node` e `Pod`.

O evaluator avalia uma alocação de pods em nós com duas métricas, que formam o `Score{A, C}`:

- **`A` (admissão), maior é melhor.** Mede quanto da demanda foi atendida: soma dos pesos `w_j` dos pods que estão alocados em algum nó. Pods Pending não contribuem. O peso de um pod é `w_j = max_r (req_r / cap_ref_r)`, a fração do recurso dominante em relação a uma capacidade de referência (`cap_ref`), de modo que pods maiores valem mais e o valor não depende do nó. É guardado em milionésimos (`int64`) para a comparação ser exata.
- **`C` (custo), menor é melhor.** Mede quanto custa manter a alocação: soma, sobre os nós ligados, de `c_i + λ·c_i·F_i`.
  - `c_i` é o custo do nó. Só é pago se o nó está ligado, ou seja, tem pelo menos um pod ativo (pods de DaemonSet não contam) ou é ancorado (o Cluster Autoscaler nunca o removeria). Nó desligado custa 0.
  - `F_i` é a fragmentação do nó: a probabilidade de um pod típico de `M_pods` não caber no espaço livre, multiplicada pela fração livre do nó. Mede espaço sobrando que ninguém consegue usar.
  - `λ` define o peso da fragmentação em relação ao custo bruto.
- **Comparação (`Better`):** `A` vem primeiro. Uma solução com mais admissão sempre vence, mesmo que custe mais. Só com `A` igual se compara `C`, e diferenças menores que uma tolerância relativa contam como empate.

`State` é a alocação com uso e custo por nó em cache. `Assign`/`Unassign` atualizam o cache, e `Fits`, `DeltaAssign`, `DeltaUnassign` e `DeltaMove` avaliam movimentos sem alterar o estado. `Clone` e `Recompute` apoiam a busca e os testes.

```bash
cd evaluator && go test ./...
```

`TestDeltaIgualRecalculo` confere em movimentos aleatórios que o cálculo incremental coincide com o recálculo completo.

## Plano

0. **Evaluator** (feito): função objetivo em Go, com testes.
1. **Plugin de Score** (equivalente ao Scheduler `greedy`): ΔC com custo do nó e fragmentação.
2. **Plugin do Descheduler** (equivalente a `ls_first`/`ls_best`), com limite K de evicções por ciclo.
3. **Cenários no KWOK**: reproduzir as instâncias da simulação (nós, pods, churn) e comparar com o kube-scheduler padrão.
4. **Análise**: mesmas métricas da simulação (admissão, custo de nós, fragmentação, evicções).

Do plano, só o `evaluator/` está implementado; as pastas `plugins/`, `deploy/`, `kwok/` e `analysis/` são o esqueleto.
