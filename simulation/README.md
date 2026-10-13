# Simulação (protótipo local)

Código e resultados do TCC sobre **escalonamento dinâmico de contêineres no Kubernetes com penalidade de migração**.

O trabalho parte do modelo de programação inteira de Martins et al. (*Abordagens Heurísticas para o Problema de Escalonamento de Contêineres em Orquestradores Kubernetes*, SBPO 2025) e da formulação multiperíodo com penalidade de realocação de Carneiro et al. (*Uma nova Formulação de Programação Inteira para o Problema de Escalonamento de Containers*, SBPO 2025). O cenário é **multi-período**: a cada período, alguns pods saem do cluster e outros chegam. Cada evicção (reinício de um pod para movê-lo de nó) custa uma penalidade **ω (omega)**. O objetivo é minimizar o custo de operar o cluster sem provocar disrupção desnecessária.

O projeto simula a arquitetura real do Kubernetes, com **Scheduler** e **Descheduler** separados, e compara várias combinações de componentes. As configurações com Scheduler heurístico são **implantáveis** no Kubernetes; as com Scheduler MILP entram como **referência** (limite superior), porque resolver um MILP de até 60 s por fila de pods não cabe no caminho crítico de um scheduler real.

## Modelo

### Função objetivo (avaliação de todos os métodos)

A otimização é **lexicográfica**, com duas prioridades (`rescheduling/objective.py`, um único avaliador compartilhado por Scheduler, Descheduler e MILP):

1. **Admissão** (maximizar): `A_t = Σ_j w_j·a_jt`, com `a_jt = 1` se o pod *j* está alocado e `w_j = max_r(req_jr / cap_médio_r)` (peso pelo recurso dominante).
2. **Eficiência** (minimizar): `C_t = Σ_i c_i·x_it + λ·Σ_i c_i·F_it + Σ_j ω_j·ev_jt`.

| Termo | Significado |
|---|---|
| `c_i·x_it` | custo de manter o nó *i* ligado (`c_i = α_i`; ver `--cost-model` em [Instâncias](#instâncias)) |
| `F_it` | fração da capacidade do nó *i* que está livre mas inutilizável |
| `λ` | peso da fragmentação (padrão 1.0; `--lam 0 1 2 5` varre vários valores e compara ao final) |
| `ev_jt`, `ω_j` | evicção do pod *j* e seu custo (uniforme por padrão, `0,5 × c_i` médio, `--omega-fraction`; aceita valores por pod) |

**Fragmentação.** Seja `M_pods` a distribuição de pods típicos (tipos *m* com frequência `p_m`). Então

```
F_it = Σ_m p_m · 1[ pod do tipo m NÃO cabe no espaço livre de i ] · frac_livre_it
```

em que `frac_livre_it` é a média, sobre os recursos, de `livre_ir / cap_ir`. Um nó desligado, vazio ou totalmente cheio tem `F = 0`. A métrica é inspirada na fragmentação do FGD (Weng et al., USENIX ATC 2023).

**Comparação.** Uma solução *s* é melhor que *s'* se `A(s) > A(s')`, ou `A(s) = A(s')` e `C(s) < C(s')`. A implementação compara a tupla `(-A, C)`, sem big-M: a admissão sempre domina o custo.

**Uso nos componentes.**

- **Scheduler guloso**: para cada nó viável, `ΔC(i) = c_i·[i estava desligado] + λ·c_i·(F_depois − F_antes)`; escolhe o menor. Aloca sempre que houver nó viável.
- **Descheduler** (LS e GRASP): prevê o efeito de cada evicção com o mesmo `ΔC` mais `ω_j`. O GRASP só aplica o estado proposto se a tupla `(-A, C)` completa melhora.
- **MILP**: dois passos. Primeiro maximiza `A`; depois minimiza `C` com `Σ w_j·a_j ≥ A*`. A fragmentação é linearizada em `milp/model.py`. No Descheduler MILP os pods em execução continuam admitidos, então `A` é constante e só o segundo passo é resolvido.

**Decisões de implementação**

- `M_pods` é a distribuição empírica de um **histórico** de pods (`Instance.history_demand`, 200 pods de execuções passadas, sorteados à parte da carga da instância), em `POD_TYPES = 5` faixas de mesma contagem (`settings.py`). Assim a fragmentação não usa informação dos pods que ainda vão chegar. Também aceita uma `PodDistribution` explícita, por exemplo montada de um trace real.
- `ω_j` é uniforme e na escala do custo dos nós: `OMEGA_FRACTION` (0,5) × `c_i` médio. `OMEGA_BY_SIZE` o torna proporcional ao peso `w_j` do pod (mantendo a média), e `EVICTION_COST` aceita um número ou `{pod: ω_j}`. Toda evicção paga `ω_j`, inclusive se o pod voltar ao mesmo nó, porque o pod é reiniciado.
- A instância tem um único recurso (a demanda `u_j`). O avaliador é escrito por recurso (`requests`, `capacities`, `usage`); para CPU + memória basta estender esses ganchos e o `ClusterState`.

**Premissa: nó vazio não custa.** O termo `c_i` só faz sentido se um nó sem pods deixa de ser cobrado. No Kubernetes isso exige o **Cluster Autoscaler**, que remove nós vazios. Todo o ganho do Descheduler vem de esvaziar ou compactar nós, então essa premissa vale também para os testes em cluster real.

**Métricas registradas por período**: `admission`, `node_cost`, `frag_cost`, `disruption_cost`, pods Pending, evicções, utilização (requests alocados / capacidade ligada) e % de capacidade fragmentada.

## Arquitetura Scheduler + Descheduler

Cada período segue o fluxo real do Kubernetes:

1. **Scheduler**: coloca apenas os pods **novos**. Pods que já estão rodando não são tocados.
2. **Descheduler**: escolhe **quais pods evictar**. Ele **não escolhe o destino**. Há um **limite de evicções por ciclo (K)**, como no Descheduler real (`maxNoOfPodsToEvictTotal`), e cada pod é evictado no máximo uma vez por ciclo.
3. **Scheduler**: os pods evictados voltam para a fila e são recolocados na ordem de evicção, com a mesma regra usada para pods novos. Um pod evictado pode até voltar ao mesmo nó.

Para decidir quem evictar, os Deschedulers heurísticos prevêem onde o Scheduler recolocaria cada pod simulando a regra dele. Só vale evictar se a redução prevista de `C` (nós + fragmentação) superar `ω_j` (o custo da própria evicção) mais um limiar mínimo. A previsão avalia uma evicção por vez. Na execução, todos os pods do ciclo são evictados antes de serem recolocados, então o resultado final pode diferir do previsto. Isso também acontece no Kubernetes, onde o Descheduler não controla as decisões do Scheduler.

Os dois componentes são plugáveis e o experimento testa todas as combinações (3 × 5 = 15):

| Componente | Opção | Descrição |
|---|---|---|
| Scheduler | `least_requested` | kube-scheduler padrão: escolhe o nó com mais capacidade livre relativa e não conhece custos |
| Scheduler | `greedy` | decide pod a pod pelo menor `ΔC` (lógica do plugin de *Score*) |
| Scheduler | `milp` | coloca a **fila inteira de uma vez** com MILP exato, com os pods que já rodam fixos. Resolve a otimização lexicográfica (admissão, depois `C`). Pods que não cabem ficam Pending. Se o solver não devolver solução no limite de tempo, usa o guloso |
| Descheduler | `none` | nenhuma evicção |
| Descheduler | `ls_first` | percorre os pods e evicta o **primeiro** cuja recolocação prevista reduz o custo |
| Descheduler | `ls_best` | a cada passo evicta o pod de **maior** redução prevista |
| Descheduler | `grasp` | GRASP sobre conjuntos de evicção. A RCL guarda as evicções com delta até `rcl_alpha` da faixa entre a melhor e a pior e sorteia com peso por delta. Cada conjunto construído é avaliado executando as evicções de fato, e só vale se a tupla `(-A, C)` real melhora. A primeira iteração é gulosa (igual a `ls_best`) |
| Descheduler | `milp` | MILP exato planeja a alocação com no máximo K pods movidos e evicta os pods que o plano move. No plano, cada pod movido paga ω, igual a uma evicção. Os destinos do plano **não** são impostos: quem recoloca os pods é o Scheduler |

Como o Descheduler só evicta, **o resultado depende da regra do Scheduler**. Com o `least_requested`, os pods evictados vão para os nós mais vazios e não para os mais baratos, então o Descheduler tem pouco efeito sobre o custo. O Descheduler MILP sofre o mesmo problema: se o Scheduler não segue o plano, as evicções podem piorar o custo. A combinação **`milp+milp`** fecha esse ciclo: o plano mantém os pods não movidos onde estão, e o Scheduler MILP recoloca os evictados resolvendo o mesmo subproblema, o que evita a perda causada por um Scheduler que não segue o plano. Por usar o Scheduler MILP, essa combinação é de referência, não implantável.

O Scheduler decide no momento em que o pod chega, então o realista é ser rápido (`least_requested`, `greedy`); por isso o `milp` é tratado como referência. O Descheduler roda periodicamente e tem mais tempo, então métodos mais caros (GRASP, MILP) podem compensar ali.

### Ponto de comparação

**Baseline `least_requested+none`**: kube-scheduler padrão sem Descheduler. É o comportamento de um cluster Kubernetes sem customização, e o gap de cada configuração é medido contra ele.

## Experimentos

Parâmetros em `experiments/settings.py`.

Fatorial: 3 Schedulers × 5 Deschedulers com limite de K = 10 evicções por período (`DESCHEDULER_MAX_MOVES`). Tabelas e testes estatísticos separam dois grupos:

- **Implantáveis**: `least_requested` e `greedy` × todos os Deschedulers.
- **Referência**: todas as combinações com Scheduler `milp`. Esse Scheduler resolve a fila inteira de pods de cada período com o solver, o que não cabe no tempo de decisão de um scheduler real. Ele serve como limite superior: mostra o que um Scheduler quase ótimo conseguiria e, comparado ao `greedy`, quanto a heurística deixa de ganhar. O `milp+milp` (Scheduler e Descheduler ótimos em cada período) é a melhor configuração possível nesse sentido, mas não é uma proposta para produção.

Varreduras opcionais, cada combinação em um CSV próprio (`results/dados/factorial_lam<λ>_omega<f>_margin<m>_cost-<modelo>.csv`) com uma tabela comparativa no final:

- `--lam`: peso da fragmentação.
- `--omega-fraction`: ω = F × `c_i` médio. A fronteira **custo de nós × evicções** (colunas `node_cost` e `evictions`) não depende da escala de ω, então a varredura mostra se a conclusão vale só para um ω. Use `--sizes 10x100 20x200` para limitar os tamanhos.
- `--margin`: folga de capacidade.
- `--cost-model`: ver [Instâncias](#instâncias).

Evicções são a medida de disrupção cobrada no custo. O runner também registra **migrações** (pods do período anterior que terminam em outro nó) como informação complementar: uma evicção não vira migração quando o pod volta ao mesmo nó.

### Escolha da melhor configuração

- O critério principal é lexicográfico, como a f.o.: maior **admissão** `Σ_t A_t` e, em empate, menor **custo total** `Σ_t C_t`. Fragmentação, evicções e tempo são critérios secundários.
- As seeds são as mesmas para todas as configurações, então as amostras são pareadas. Cada bloco é uma instância (N, P, seed).
- **Friedman**: dentro de cada instância, as configurações são ordenadas por (maior `ΣA`, menor `ΣC`) e a posição vira o rank (empates pela média). O Friedman testa os ranks.
- **Wilcoxon pareado com correção de Holm**: compara a configuração de melhor rank médio com cada outra pela diferença de custo `ΣC`, só nas instâncias em que a admissão das duas empata. Onde a admissão difere, a prioridade 1 já decide e o custo não é comparável. A tabela mostra quantos pares entraram.
- Rodam dois conjuntos: as implantáveis e todas (com a referência).

### Número de execuções (`N_RUNS = 10`)

Com 11 tamanhos × 10 seeds são 110 blocos pareados no teste de Friedman. O custo dominante é o MILP (até 60 s por período ou por fila de pods), não as heurísticas.

### Premissas da simulação

- A evicção e a recolocação acontecem no mesmo período. O Scheduler processa a fila de pods evictados logo após o ciclo do Descheduler.
- Um pod que o Scheduler não consegue colocar fica Pending, não entra na admissão e é **tentado de novo no período seguinte** (enquanto estiver ativo), como no Kubernetes.
- Nó vazio não custa (Cluster Autoscaler ativo; ver [Função objetivo](#função-objetivo-avaliação-de-todos-os-métodos)).

### Limitações

- **Um único recurso.** A fragmentação funciona, mas é no caso multirecurso (CPU sobrando num nó sem memória) que ela mais importa. O avaliador já é escrito por recurso (`requests`, `capacities`, `usage`); falta estender o `ClusterState` e o gerador de instâncias. Fica como trabalho futuro.
- **Nó vazio sai de graça de imediato.** No Kubernetes, o Cluster Autoscaler remove nós vazios só depois de um tempo (por padrão, alguns minutos). Se a duração do período *t* for menor que esse atraso, o ganho medido é otimista.
- **O Descheduler não recupera pods Pending.** A previsão dele olha só o `ΔC` (nós + fragmentação + evicção), não o ganho de admissão que compactar o cluster traria para um pod Pending. Quem admite o pod no período seguinte é o Scheduler.
- **Descheduler sem garantia de admissão entre períodos.** Dentro de um ciclo, nenhum Descheduler reduz a admissão (verificado em `tests/test_simulation_invariants.py`), mas as evicções mudam o estado dos períodos seguintes, então a admissão total de uma configuração pode ficar abaixo da de outra.

## Estrutura

```
simulation/
rescheduling/                    # pacote: simulação Scheduler + Descheduler
├── instance.py                  #   gera instâncias multi-período (churn, capacidades, custos)
├── objective.py                 #   f.o. lexicográfica (-A, C): admissão, fragmentação, ΔC incremental
├── cluster_state.py             #   estado do cluster (alocação, ocupação dos nós)
├── evictions.py                 #   política (limite K), previsão e execução de evicções
├── simulation.py                #   laço por período: Scheduler → Descheduler → Scheduler
├── results.py                   #   resultado por período e do horizonte
├── schedulers/                  #   registro, base e heurísticas (least_requested, greedy)
├── deschedulers/                #   none, local_search (ls_first/ls_best), grasp
└── milp/                        #   componentes MILP (Gurobi)
    ├── model.py                 #     modelos de dois passos (fila do Scheduler, plano do Descheduler)
    ├── scheduler.py             #     Scheduler MILP (coloca a fila em lote)
    └── descheduler.py           #     Descheduler MILP
experiments/                     # bateria de experimentos (python -m experiments)
├── settings.py                  #   tamanhos, seeds, K, parâmetros e caminhos dos CSVs
├── configurations.py            #   configurações do fatorial
├── runner.py                    #   execução das instâncias
├── results_store.py             #   CSV com retomada
├── summary.py, tables.py        #   agregação e tabelas
└── statistical_tests.py         #   Friedman + Wilcoxon com Holm
examples/demo.py                 # todas as combinações em uma instância
tests/test_objective.py          # testes unitários da f.o. e dos MILPs
tests/test_simulation_invariants.py  # capacidade, limite K, evicção única e admissão por ciclo
results/
├── README.md                    # qual arquivo corresponde a qual execução
├── dados/                       # factorial_lam<λ>_omega<f>_margin<m>_cost-<modelo>.csv: um por combinação; uma linha por instância × configuração
├── analises/                    # saídas de --analyze guardadas em texto
└── logs/                        # baseline/, omega/, lambda/, folga_e_custo/ e cadeias/
```

Os CSVs são gerados pela execução dos experimentos; `results/README.md` lista as execuções e os arquivos de cada uma.

## Instâncias

`generate_instance(n_nodes, n_pods_total, n_periods=20, seed=...)`:

- Custos e demandas seguem as faixas de Martins et al. (SBPO 2025): `α_i ~ U(1, 4n)` e `u_j ~ U(1, 10)`. Nesse modelo (`--cost-model martins`, padrão) o custo é sorteado independente da capacidade, então há nós grandes e baratos e nós pequenos e caros. A variante `--cost-model proportional` refaz `α_i` proporcional à capacidade do nó × U(0,8; 1,2), com a mesma média, como o preço de instâncias na nuvem.
- Metade dos pods está presente desde o início (`ramp_fraction=0.5`). A cada período, 15% dos pods ativos saem (`churn_rate=0.15`) e voltam ao pool de espera, enquanto novos pods chegam.
- A capacidade total é a demanda média do pico de pods ativos × `CAPACITY_MARGIN` (padrão 1,1, `--margin`). Com folga de 1,6× todos os pods cabem e a admissão não diferencia as configurações; perto de 1,0 sobram pods Pending e a prioridade de admissão passa a decidir.

Os experimentos usam 20 períodos, os tamanhos (nós, pods) ∈ {(10,50), (10,100), (10,200), (20,100), (20,200), (20,500), (50,200), (50,500), (50,1000), (100,500), (100,1000)} e as seeds a partir de 100.

## Como executar

Requisitos: Python 3.9+, [Gurobi](https://www.gurobi.com/) com licença válida (para as opções MILP) e scipy (para os testes estatísticos). As heurísticas usam só a biblioteca padrão.

```bash
pip install gurobipy scipy
cd simulation

# Exemplo rápido: todas as combinações numa instância com 10 nós e 50 pods
python -m examples.demo

# Bateria completa: fatorial + análise → results/dados/*.csv (a partir de `simulation/`)
python -m experiments

# Varreduras (tabela comparativa no final) e variantes da instância
python -m experiments --lam 0 1 2 5
python -m experiments --omega-fraction 0 0.25 0.5 1 2 --sizes 10x100 20x200
python -m experiments --margin 1.6
python -m experiments --cost-model proportional

# Só relê os CSVs e imprime tabelas/testes
python -m experiments --analyze

# Teste rápido (2 tamanhos, grava em *_quick.csv)
python -m experiments --quick --runs 2

# Sem Gurobi: pula as configurações com Scheduler ou Descheduler MILP
python -m experiments --no-milp
```

Os CSVs são salvos após cada instância. Se a execução for interrompida, basta rodar o mesmo comando de novo: as linhas já calculadas são puladas.

Testes (a partir de `simulation/`): `python -m unittest discover -s tests`.

### Execução longa (Windows)

A bateria completa pode levar horas. Para rodar sem prender o terminal, em segundo plano, com log:

```powershell
$env:PYTHONIOENCODING = "utf-8"
Start-Process python -ArgumentList "-u","-m","experiments" `
  -WorkingDirectory (Get-Location) -WindowStyle Hidden `
  -RedirectStandardOutput results\logs\baseline\run.log -RedirectStandardError results\logs\baseline\run.err

Get-Content results\logs\baseline\run.log -Wait -Tail 20   # acompanhar
Stop-Process -Name python                     # parar (o mesmo comando retoma)
```

Suspender o computador pausa a execução (`powercfg /change standby-timeout-ac 0` evita). Execuções simultâneas disputam CPU e distorcem a coluna de tempo, então rode uma de cada vez.

## Resultados

Bateria de 7 a 11 de outubro de 2026. Todos os números abaixo vêm dos CSVs em `results/dados/` (os logs estão em `results/logs/` e a análise da varredura de ω em `results/analises/`) e podem ser reproduzidos com `python -m experiments --analyze` (acrescente os mesmos parâmetros e `--sizes` da execução). A análise só é impressa no terminal; para guardá-la, redirecione a saída (`... | Out-File -Encoding utf8 results\analises\arquivo.txt`). O arquivo `results/README.md` diz qual log e qual CSV pertence a cada execução.

| Execução | Parâmetros | Tamanhos | Instâncias |
|---|---|---|---|
| Baseline | λ = 1, ω = 0,5 × c médio, folga 1,1, custo de Martins | os 11 | 110 × 15 configurações |
| Varredura de ω | ω = F × c médio, F ∈ {0, 0,25, 0,5, 1, 2} | os 11 | 110 × 15 por valor |
| Varredura de λ | λ ∈ {0, 1, 2, 5} | 10×100, 20×200, 20×500 | 30 × 15 por valor |
| Folga 1,6 | sem pods Pending | 10×100, 20×200, 20×500 | 30 × 15 |
| Custo proporcional | `c_i` proporcional à capacidade | 10×100, 20×200, 20×500 | 30 × 15 |

### Baseline (λ = 1, ω = 0,5, folga 1,1)

Gap do custo `C` contra `least_requested+none`, faixa entre os 11 tamanhos:

| Configuração | Gap do custo C |
|---|---|
| `GR+none` | −16% a −41% |
| `GR+ls_best` / `GR+grasp` | −22% a −54% |
| `GR+milp` (implantável) | −28% a −63% |
| `MS+milp` (referência) | −21% a −63% |
| `LR+ls_*` / `LR+grasp` | 0% a −2% |
| `LR+milp` | +2% a +29% (pior que o baseline) |

- **Implantáveis**: `GR+milp` tem o melhor rank (1,14), com diferença significativa (Wilcoxon-Holm) para todas as outras. Depois vêm `GR+ls_best` e `GR+grasp` (2,89), `GR+ls_first` (3,26) e `GR+none` (5,00). Com `least_requested`, nenhum Descheduler muda a classificação de forma relevante. `LR+milp` fica em último (9,45).
- **Referência**: `MS+milp` tem o melhor rank (2,00), mas `GR+milp` **empata** com ele (p = 0,16). O Scheduler MILP quase não ganha sobre o guloso quando o Descheduler é o MILP.
- **Admissão**: o `least_requested` deixa de 0 a 18 pods Pending somados por instância; o guloso, de 0 a 3. Espalhar pods fragmenta o cluster e custa admissão. Nenhum Descheduler recupera pods Pending.
- **Utilização**: 0,51 a 0,55 com `least_requested`, 0,58 a 0,93 com guloso (com ou sem Descheduler).
- **`LR+milp`**: o Descheduler MILP planeja evicções que o `least_requested` não segue, e o resultado são 15 a 200 evicções por instância (média por tamanho) e custo pior. Com `greedy+milp`, que segue o plano, o mesmo Descheduler é o melhor entre as implantáveis.

### GRASP

O GRASP **não acrescenta nada à busca local** nesta configuração. Duas causas, medidas numa sonda de 180 ciclos (guloso, 3 tamanhos × 3 seeds):

1. Em 110 dos 180 ciclos não existe nenhuma evicção que melhore o custo, e nos demais há em média 2,3 candidatos. A busca local já esgota essa vizinhança.
2. A RCL original escolhia `int(n × 0,15)` candidatos, que com 2,3 candidatos vira sempre 1, então as 10 iterações repetiam o plano guloso (110 de 110 instâncias idênticas ao `ls_best`). Corrigi para a regra padrão do GRASP (candidatos até `rcl_alpha` da faixa entre o melhor e o pior).

Depois da correção, mesmo com RCL totalmente aleatória (`rcl_alpha = 1`) e 30 iterações, uma iteração posterior achou um plano melhor em só 5 dos 180 ciclos. Com o padrão (`rcl_alpha = 0,15`, 10 iterações), o GRASP fica igual ao `ls_best` em 63 a 109 das 110 instâncias, conforme o Scheduler (105 com o guloso), e o rank empata (2,89 nos dois). Com o Scheduler MILP, as diferenças que aparecem (18 instâncias melhores, 29 piores) não mostram vantagem sistemática: o GRASP decide pelo custo do ciclo atual, e os ciclos seguintes divergem. Conclusão: com K = 10 e vizinhança de uma evicção por vez, o GRASP não justifica o custo extra de tempo.

### Varredura de ω (o resultado depende dele)

Custo de nós e evicções médios sobre as 110 instâncias dos 11 tamanhos (a média de nós é dominada pelos clusters grandes), com `GR+none` = 76.050 nós e 0 evicções para qualquer ω:

| ω (× c médio) | `GR+ls_best` | `GR+milp` | `MS+milp` (ref.) |
|---|---|---|---|
| 0 | 61.754 nós / 64 evic. | 41.686 / 189 | 40.519 / 176 |
| 0,25 | 63.159 / 19 | 43.761 / 67 | 43.578 / 62 |
| 0,5 | 63.505 / 15 | 51.524 / 34 | 52.472 / 30 |
| 1 | 65.267 / 11 | 64.502 / 11 | 65.446 / 9,7 |
| 2 | 75.273 / 0,6 | 75.309 / 0,6 | 75.695 / 0,5 |

Redução do custo de nós contra `GR+none`:

| ω (× c médio) | `GR+ls_best` | `GR+milp` |
|---|---|---|
| 0 | −18,8% | −45,2% |
| 0,25 | −16,9% | −42,5% |
| 0,5 | −16,5% | −32,3% |
| 1 | −14,2% | −15,2% |
| 2 | −1,0% | −1,0% |

Com ω = 0 o Descheduler MILP corta 45% do custo de nós à custa de 189 evicções por instância (com os 3 tamanhos pequenos eram −51% e 178). Com ω = 2 o ganho de qualquer Descheduler cai a 1%, porque quase nada vale a evicção. Ou seja, **a conclusão "o Descheduler ajuda" vale conforme o custo da evicção**; a fronteira acima é o resultado que não depende de um ω arbitrário.

**A classificação também depende de ω** (Friedman e Wilcoxon-Holm, 110 instâncias; rank médio entre parênteses):

| ω | Implantáveis: melhor | Quem empata com ele | Referência (com `MS+milp`): melhor |
|---|---|---|---|
| 0 | `GR+milp` (1,45) | ninguém; `GR+grasp` (2,58) e `GR+ls_best` (2,67) são significativamente piores | `MS+milp` (1,28); `GR+milp` (3,35) é significativamente pior |
| 0,25 | `GR+milp` (1,00) | ninguém; `GR+grasp` (2,79) e `GR+ls_best` (2,81) são significativamente piores | `MS+milp` (1,46); `GR+milp` (2,56) é significativamente pior (p = 0,029) |
| 0,5 | `GR+milp` (1,14) | ninguém | `MS+milp` (2,00); `GR+milp` (2,70) empata (p = 0,16) |
| 1 | `GR+ls_best` (2,50) | `GR+grasp`, `GR+milp` (2,54), `GR+ls_first` | `MS+milp` (4,07); empata com `MS+ls_*`, `MS+grasp` e todos os `GR+` exceto `GR+none` |
| 2 | `GR+ls_first` (2,88) | `GR+ls_best`, `GR+grasp`, `GR+milp` (2,95) | `MS+ls_best` (4,59); empata com `MS+milp` e os `GR+` |

- Com evicção barata (ω ≤ 0,5) o Descheduler MILP é claramente o melhor entre os implantáveis; com ω = 0,25 ele fica em primeiro lugar em todas as instâncias (rank 1,00). A partir de ω = 1 ele deixa de se distinguir da busca local, e com ω = 2 os três Descheduler heurísticos e o MILP empatam.
- Contra a referência `MS+milp`, `GR+milp` é significativamente pior em ω = 0 e 0,25, empata em ω = 0,5 (p = 0,16) e fica estatisticamente igual a partir de ω = 1. Como a diferença em ω = 0,25 é pequena (p = 0,029 após Holm), não leia o empate em ω = 0,5 como tendência monótona.
- `GR+none` é sempre significativamente pior que os `GR+` com Descheduler (rank 4,93 / 5,02 / 5,00 / 5,03 / 3,60 para ω = 0 / 0,25 / 0,5 / 1 / 2), mas a diferença encolhe com ω = 2 (p = 4,7e-6).
- Com `least_requested`, os Descheduler heurísticos só mudam a classificação com ω = 0 (rank 6,85 a 7,75 contra 9,15 de `LR+none`); com ω ≥ 0,25 a diferença é pequena (7,40 a 7,98 em ω = 0,25 e 7,39 a 7,93 em ω = 0,5). `LR+milp` é o último dos implantáveis em ω = 0,25, 0,5, 1 e 2 (9,57 / 9,45 / 9,17 / 8,74); em ω = 0 o último é `LR+none` (9,15 contra 9,03). Suas evicções caem com ω (199 / 176 / 133 / 73 / 21 por instância), mas ficam muito acima das de `GR+milp` em ω ≥ 0,25 (67 / 34 / 11 / 0,6).
- O `GR+milp` com ω = 0 aumenta a fragmentação (3,18% contra 2,72% de `GR+none`) e leva a utilização a 0,91, porque as evicções gratuitas compactam os nós além do que a penalidade λ desconta. Com ω = 0,25 a utilização é 0,86 e a fragmentação 3,05%.

### Varredura de λ

Média de 30 instâncias, `GR+none` / `GR+ls_best` / `GR+milp`:

| λ | % fragmentada (`GR+none`) | custo de nós (`GR+none`) | evicções (`GR+ls_best`) |
|---|---|---|---|
| 0 | 2,40 | 9.553 | 6,1 |
| 1 | 0,74 | 9.912 | 5,5 |
| 2 | 0,74 | 9.912 | 5,7 |
| 5 | 0,73 | 9.912 | 8,0 |

Com λ = 0 o guloso fragmenta 3,2× mais (2,40% contra 0,74%); com λ = 1 ele já satura, e valores maiores quase não mudam a fragmentação. Reduzir a fragmentação custa +3,8% de custo de nós no `GR+none`. Só com λ = 5 o `least_requested` começa a evictar (3 evicções por instância). A fragmentação média é baixa em todos os casos (≤ 3,1%) nos três tamanhos pequenos.

### Folga 1,6 (sem Pending) e custo proporcional

- **Folga 1,6**: não há pods Pending em nenhuma configuração, e a admissão não diferencia mais nada. O gap do guloso contra o baseline fica entre −51% e −64%, maior que com folga 1,1: com mais folga o `least_requested` mantém utilização de 0,35 a 0,37, enquanto o guloso compacta os nós. Rank: `GR+milp` 1,25, `GR+ls_*` 2,90, `GR+none` 5,00, `LR+*` 7,55 a 9,80.
- **Custo proporcional à capacidade**: o gap do guloso contra o baseline cai para −12% a −18% (`GR+none`), −19% a −27% (`GR+ls_best`) e −21% a −33% (`GR+milp`). O ganho é menor que com o custo de Martins (hipótese, não testada: com `c_i` proporcional à capacidade, espalhar pods custa menos em nós caros do que quando o custo é independente da capacidade). A ordem das configurações é a mesma (`GR+milp` 1,03, `GR+ls_first` 2,90, `GR+ls_best` e `GR+grasp` 3,03, `GR+none` 5,00).

### Ressalvas

- A varredura de ω usa os 11 tamanhos (110 instâncias por valor). As varreduras de λ, a folga 1,6 e o custo proporcional usam só 30 instâncias nos três tamanhos menores (10×100, 20×200, 20×500); o baseline usa os 11 tamanhos. Esses resultados podem não valer para clusters de 50 a 100 nós.
- Os tempos nos CSVs incluem períodos em que o computador pode ter ficado sem rede ou suspenso (a cadeia foi interrompida e retomada), então use `time_ms` com cautela.
- Os MILPs têm limite de 60 s e gap de 1%; execuções com o mesmo plano podem diferir um pouco.
