# k8s-scheduling-optimization

TCC sobre **escalonamento dinâmico de contêineres no Kubernetes com penalidade de migração**.

**Objetivo do trabalho:** implementar **plugins em Go** para o Kubernetes (Scheduler Framework do kube-scheduler e plugins do Descheduler) que aplicam a função objetivo do TCC (admissão, custo de nós, fragmentação e custo de evicção) e **avaliá-los em clusters simulados com o [KWOK](https://kwok.sigs.k8s.io/)**.

O modelo (base: Martins et al. e Carneiro et al., SBPO 2025) e os resultados com a simulação em Python estão em [`simulation/`](simulation/README.md). Essa simulação é um **protótipo local**: serviu para formular a função objetivo e comparar heurísticas e MILP, e agora é a referência para validar os plugins.

## Estrutura

```
simulation/     # protótipo em Python (modelo, heurísticas, MILP, experimentos e resultados)
plugins/
├── scheduler/      # plugins Go do Scheduler Framework (Filter/Score) para o kube-scheduler
└── descheduler/    # plugins Go para o kubernetes-sigs/descheduler (estratégias de evicção)
deploy/         # KubeSchedulerConfiguration, Dockerfiles e manifests para instalar os plugins
kwok/
└── scenarios/      # clusters e cargas no KWOK (nós falsos, pods, churn por período)
analysis/       # coleta e comparação das métricas do KWOK com os resultados da simulação
```

## Plano

1. **Plugin de Score** (equivalente ao Scheduler `greedy`): ΔC com custo do nó e fragmentação.
2. **Plugin do Descheduler** (equivalente a `ls_first`/`ls_best`), com limite K de evicções por ciclo.
3. **Cenários no KWOK**: reproduzir as instâncias da simulação (nós, pods, churn) e comparar com o kube-scheduler padrão.
4. **Análise**: mesmas métricas da simulação (admissão, custo de nós, fragmentação, evicções).

Nada disso está implementado ainda; as pastas `plugins/`, `deploy/`, `kwok/` e `analysis/` são o esqueleto.
