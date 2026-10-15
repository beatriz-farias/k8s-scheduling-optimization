### Função objetivo

Especificação da função objetivo usada pelos plugins de **scheduler** (kube-scheduler) e de **descheduler** (sigs.k8s.io/descheduler). Os dois plugins usam o mesmo avaliador, para que um estado considerado bom pelo descheduler também seja mantido pelo scheduler.

O objetivo do sistema é **minimizar o custo dos nós ao longo do tempo sem deixar de admitir pods**. A fragmentação entra como um substituto do custo futuro e a disrupção como uma restrição.

#### Formulação

Em cada ciclo *t*:

```
maximizar   A_t = Σ_j w_j · a_jt                          (1) admissão
minimizar   C_t = Σ_i c_i · x_it  +  λ · Σ_i c_i · F_it    (2) custo
sujeito a   Σ_j ev_jt ≤ K                                  (3) orçamento de evicções
```

A otimização é **lexicográfica**: primeiro (1), depois (2), sempre respeitando (3).

| Termo | Significado |
|---|---|
| `a_jt` | 1 se o pod *j* está alocado a um nó (não está `Pending`) |
| `w_j` | peso de admissão do pod *j* (recurso dominante, ver abaixo) |
| `c_i` | custo do nó *i* por ciclo, lido da configuração (ver [Custo dos nós](#custo-dos-nós)) |
| `x_it` | 1 se o nó *i* está ligado (ver [Nó ligado](#nó-ligado)) |
| `F_it` | fração da capacidade do nó *i* que está livre mas inutilizável |
| `λ` | peso da fragmentação, o único peso da FO |
| `ev_jt` | 1 se o pod *j* é evictado no ciclo *t* |
| `K` | número máximo de evicções por ciclo do descheduler |

**Interpretação de `λ`.** O custo dos nós é um gasto presente. A fragmentação é uma previsão de gasto futuro: capacidade inutilizável hoje tende a obrigar a ligar um nó amanhã. `λ` diz quanto peso se dá a essa previsão. Com `λ = 0` o sistema só olha o custo presente; valores maiores protegem o cluster contra fragmentação a custo de decisões menos econômicas no curto prazo.

#### Recursos

O avaliador trabalha com um vetor de recursos *r*. O conjunto padrão é CPU e memória; outros recursos (por exemplo, GPU) podem ser adicionados pela configuração.

- Demanda do pod: os **requests** do pod, incluindo o overhead, como o kube-scheduler calcula.
- Capacidade do nó: o **allocatable** do nó.
- Uso do nó: a soma dos requests dos pods alocados nele, exceto pods em `Succeeded` ou `Failed`.

#### Admissão

`w_j = max_r (req_jr / cap_ref_r)`: a fração da capacidade de referência que o pod ocupa no seu recurso dominante.

- `cap_ref_r` é uma **capacidade de referência fixa**, definida na configuração (por exemplo, o allocatable de um nó de referência ou do maior tipo de instância). Assim `w_j` depende só do pod: não muda quando nós são ligados ou desligados, e `A` é comparável entre ciclos.
- `A` é representado como **inteiro** (`int64`, com `w_j` em milionésimos de `cap_ref`, arredondado). A comparação lexicográfica usa igualdade exata, e somas de `float64` em ordens diferentes poderiam criar diferenças espúrias em `A` que se sobreporiam a qualquer diferença em `C`.
- O arredondamento é para o inteiro mais próximo.
- Um pod sem requests (BestEffort) tem `w_j = 0`: ele não ocupa capacidade reservada, então admiti-lo ou não deixa `A` inalterado.
- A escala de `w` não afeta a ordem entre soluções, porque `A` nunca é somado a `C`. Só a proporção entre os pods importa.

#### Custo dos nós

`c_i` vem da configuração, por uma de duas formas:

- uma chave de label do nó (por exemplo, `node.kubernetes.io/instance-type`) e um mapa de valor do label para custo;
- ou uma annotation numérica no próprio nó.

Nós sem custo conhecido usam um custo padrão definido na configuração.

#### Nó ligado

`x_it = 1` se o nó tem pelo menos um pod que não seja de DaemonSet. A definição segue a regra do Cluster Autoscaler, que ignora DaemonSets ao decidir se um nó pode ser removido.

Um nó que tem algum pod que impede a remoção pelo Cluster Autoscaler é **ancorado**: fica com `x_it = 1` em qualquer plano, porque nunca será removido. Impedem a remoção, entre outros:

- pods com armazenamento local;
- pods com a annotation `cluster-autoscaler.kubernetes.io/safe-to-evict: "false"`;
- pods sem controlador (sem ReplicaSet, StatefulSet, Job etc.);
- pods do `kube-system` sem PodDisruptionBudget.

#### Fragmentação

Seja `M_pods` a distribuição de pods típicos: tipos *m*, cada um com um vetor de requests e uma frequência `p_m`. Então

```
F_it = Σ_m p_m · 1[ pod do tipo m NÃO cabe no espaço livre de i ] · frac_livre_it
```

em que `frac_livre_it` é a média, sobre os recursos, de `livre_ir / cap_ir`. Um pod do tipo *m* cabe no nó se `req_mr ≤ livre_ir` para **todos** os recursos *r*. Um nó desligado, vazio ou totalmente cheio tem `F = 0`.

Casos de borda:

- **Espaço livre negativo** (uso acima da capacidade, por exemplo depois de o allocatable do nó ser reduzido com os pods já rodando) é tratado como `livre_ir = 0`. Assim `frac_livre` e `F` nunca ficam negativos.
- **Recursos com capacidade zero** no nó (por exemplo, GPU num nó sem GPU) ficam fora da média de `frac_livre`. Contá-los como 0% livre faria um nó parecer mais ocupado só por não ter o recurso. Se nenhum recurso do nó tem capacidade, `F = 0`.
- **`M_pods` vazia**: `F = 0` para todos os nós, e a FO se reduz ao custo dos nós.

`M_pods` é fornecida na configuração, como lista de tipos com requests e frequência. Ela deve vir de um **histórico** de pods (por exemplo, um trace real ou execuções passadas), não dos pods que ainda vão chegar.

A métrica é inspirada na fragmentação do FGD (Weng et al., USENIX ATC 2023), com duas diferenças: é ponderada pelo custo `c_i` do nó (capacidade perdida num nó caro pesa mais) e é usada também no reagendamento.

#### Disrupção

A disrupção é limitada por **restrição**, e não por um termo na soma:

- **Orçamento `K`**: no máximo *K* evicções por ciclo do descheduler. É um limite que o operador escolhe diretamente ("tolero até *K* reinícios por ciclo"). Ele deve ser compatível com os limites do DefaultEvictor (`maxNoOfPodsToEvictPerNode`, `maxNoOfPodsToEvictPerNamespace`, `maxNoOfPodsToEvictTotal`).
- **Ganho mínimo `θ`**: o plano só é executado se reduzir `C` em pelo menos `θ` (relativo). Sem isso, o descheduler gastaria o orçamento a cada ciclo em troca de melhoras ínfimas.

Toda evicção conta no orçamento.

#### Comparação entre soluções

Uma solução *s* é melhor que *s'* se `A(s) > A(s')`, ou `A(s) = A(s')` e `C(s) < C(s')`. Planos que violam o orçamento `K` são inviáveis.

`A` é inteiro e comparado com igualdade exata. `C` é `float64`, e dois estados com o mesmo custo real podem diferir por ruído de arredondamento (da ordem de 1e-13). Por isso, `C(s) < C(s')` só vale se a diferença for maior que uma **tolerância relativa de 1e-9**:

```
C(s) < C(s') − 1e-9 · max(1, |C(s')|)
```

Diferenças menores contam como empate, e um empate não é melhora. Sem essa tolerância, a busca local poderia aceitar "melhoras" que são só ruído e ficar movendo pods sem ganho real. O valor é bem maior que o ruído numérico e bem menor que qualquer diferença real de custo.

#### Capacidade

Um pod *j* cabe no nó *i* se `uso_ir + req_jr ≤ cap_ir` para **todos** os recursos *r* (a igualdade é permitida, como no kube-scheduler). Um pod que já está no nó *i* sempre cabe nele: os seus requests já estão somados no uso do nó, e verificar de novo contaria o pod duas vezes.

#### Uso nos plugins

**Scheduler** (plugin de `Score` do kube-scheduler):

- Para cada nó que passou pelo `Filter`, calcula `ΔC(i) = c_i·[i estava desligado] + λ·c_i·(F_depois − F_antes)`.
- O `Score` retorna `−ΔC(i)`, e o `NormalizeScore` mapeia os valores para a faixa `[0, 100]` exigida pelo framework. O scheduler escolhe o nó de maior pontuação, que é o de menor `ΔC`.
- Os dados que dependem só do pod (requests, tipos de `M_pods` relevantes) são calculados no `PreScore` e guardados no `CycleState`.
- A admissão é garantida por construção: o `Score` só ordena nós viáveis, então o pod é alocado sempre que existe um nó viável. Não há evicções.
- Os outros plugins de pontuação do perfil devem ser desabilitados ou ter peso zero, para que a decisão siga apenas `ΔC`.

**Descheduler** (plugin `Balance`):

- Monta um snapshot do cluster: nós, pods, uso por recurso, pods movíveis (os aceitos por `Evictor().Filter` e `PreEvictionFilter`) e nós ancorados.
- A heurística (busca local ou GRASP) procura um plano de evicções que reduza `C`, com no máximo `K` evicções, usando o mesmo `ΔC` do scheduler para prever o efeito de cada movimento.
- Os pods em execução continuam admitidos: `A` é constante e só é preciso garantir que todo pod evictado tenha um nó viável no plano.
- O plano só é executado se o ganho em `C` for de pelo menos `θ`. As evicções são feitas nó a nó, e um nó só é drenado se puder ser esvaziado por completo dentro dos limites do evictor e dos PodDisruptionBudgets.

#### Parâmetros de configuração

Os dois plugins recebem os mesmos parâmetros da função objetivo:

| Parâmetro | Significado | Plugins |
|---|---|---|
| `lambda` | peso da fragmentação `λ` | scheduler, descheduler |
| `referenceCapacity` | capacidade de referência `cap_ref` por recurso | scheduler, descheduler |
| `podTypes` | distribuição `M_pods`: lista de `{requests, weight}` | scheduler, descheduler |
| `nodeCost` | label ou annotation de custo, mapa de valores e custo padrão | scheduler, descheduler |
| `resources` | recursos considerados (padrão: `cpu`, `memory`) | scheduler, descheduler |
| `maxEvictions` | orçamento `K` | descheduler |
| `minGain` | ganho mínimo relativo `θ` | descheduler |

O descheduler recebe ainda os parâmetros da heurística (escolha entre busca local e GRASP, número de iterações, tempo máximo por ciclo, semente, `α` do GRASP).

#### Implementação compartilhada

O avaliador (estado, `ΔC`, fragmentação, comparação lexicográfica) fica num módulo Go próprio, **sem dependências do Kubernetes**, usando apenas tipos simples (vetores de recursos, índices de nós e pods). Cada plugin converte os seus objetos para esses tipos: `NodeInfo` no scheduler, `*v1.Node` e `*v1.Pod` no descheduler. Isso evita conflitos entre as versões de `k8s.io/*` exigidas pelos dois projetos e garante que os dois plugins otimizam exatamente a mesma função.

#### Premissa: nó vazio não custa

O termo `c_i·x_it` só faz sentido se um nó sem pods deixa de ser cobrado. No Kubernetes isso exige o **Cluster Autoscaler** (ou outro provisionador que remova nós vazios). Todo o ganho do descheduler vem de esvaziar ou compactar nós.

### Métricas de avaliação

A função objetivo **não** é usada como placar entre métodos. Ela contém o termo de fragmentação, que os baselines (scheduler padrão, `MostAllocated`, `HighNodeUtilization`) nem tentam reduzir; avaliá-los por `C` favoreceria o método proposto por construção. Os métodos são comparados por grandezas observáveis.

**Métricas principais (o placar):**

| Métrica | O que mede |
|---|---|
| custo dos nós | `Σ c_i·x_it`, acumulado ao longo do tempo |
| pods `Pending` e tempo de espera | admissão |
| evicções | disrupção |

**Métricas explicativas (ajudam a entender o resultado, não entram no placar):**

| Métrica | O que mede |
|---|---|
| fragmentação e % de capacidade fragmentada | quanto da capacidade ligada está inutilizável |
| utilização | requests alocados / capacidade ligada |
| admissão ponderada (`A_t`) | admissão pelo recurso dominante |

**Hipótese testada.** Se reduzir a fragmentação hoje evita ligar nós amanhã, as configurações com `λ > 0` devem ter custo dos nós acumulado menor que as com `λ = 0`, sem aumento de pods `Pending`. A varredura de `λ` testa exatamente isso.
