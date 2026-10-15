# Evaluator

Pacote Go que implementa a função objetivo compartilhada pelos plugins de scheduler e de descheduler. Não depende do Kubernetes: cada plugin converte os seus objetos para os tipos do pacote (vetores `int64` de recursos, nós e pods).

## Função objetivo

Uma solução é avaliada pelo par `Score{A, C}`, comparado em ordem lexicográfica:

- **A** (admissão, `int64`, maior é melhor): soma dos pesos `w_j` dos pods alocados.
- **C** (custo, `float64`, menor é melhor): soma, sobre os nós, de `c_i·x_i + λ·c_i·F_i`.

| Símbolo | Significado | Onde está |
|---|---|---|
| `w_j = max_r (req_r / cap_ref_r)` | peso de admissão do pod, em milionésimos de `cap_ref`, arredondado. Pod sem requests (BestEffort) pesa 0 | `AdmissionWeight` |
| `x_i` | nó ligado: tem pelo menos um pod ativo (que não seja de DaemonSet) ou é ancorado (`Anchored`) | `isOn`, `countsAsActive` |
| `F_i = Σ_m p_m · 1[tipo m não cabe no livre] · frac_livre` | fragmentação de um nó ligado | `Fragmentation` |
| `c_i·x_i + λ·c_i·F_i` | parcela do nó em C; nó desligado custa 0 | `nodeCost` |

Regras de `Fragmentation`:

- `livre_r = alloc[r] − used[r]`, limitado a 0.
- `frac_livre` é a média de `livre_r / alloc[r]` nos recursos com capacidade > 0 (capacidade zero é ignorada).
- Um tipo de `M_pods` "cabe" se couber em todos os recursos ao mesmo tempo.
- Nó cheio ou `M_pods` vazia dão `F = 0`.

## Comparação

`Score.Better(o)` é verdadeiro se `A` é maior, ou se `A` é igual e `C` é menor além da tolerância relativa `costTolerance` (1e-9). Diferenças menores contam como empate, para a busca local não aceitar ruído de arredondamento como melhora.

## API

```go
ev, err := evaluator.New(evaluator.Config{
    ResourceNames:     []string{"cpu", "memory"}, // opcional, para mensagens de erro
    Lambda:            1.0,                       // λ >= 0
    ReferenceCapacity: evaluator.Resources{8000, 32768},
    PodTypes: []evaluator.PodType{ // M_pods; os pesos são normalizados
        {Requests: evaluator.Resources{500, 1024}, Weight: 3},
        {Requests: evaluator.Resources{4000, 8192}, Weight: 1},
    },
})

s, err := ev.NewState(nodes, pods) // todos os pods começam em Unassigned
```

`New` e `NewState` validam as entradas (número de recursos, valores negativos, `NaN`, pesos) e devolvem erro. A posição `r` de todo vetor `Resources` se refere ao mesmo recurso.

### `State`

Alocação de pods a nós, com uso por nó e custo por nó em cache. **Não é seguro para uso concorrente.**

| Método | O que faz |
|---|---|
| `Assign(j, i)` / `Unassign(j)` | coloca (ou move) / retira o pod `j`. Não verificam capacidade |
| `Fits(j, i)` | o pod cabe no nó? Igualdade é permitida; um pod sempre cabe no próprio nó |
| `DeltaAssign(j, i)` | ΔC ao colocar o pod `j` (em `Unassigned`) no nó `i` |
| `DeltaUnassign(j)` | ΔC ao retirar o pod `j` do nó atual |
| `DeltaMove(j, dst)` | ΔC ao mover o pod; 0 se `dst` já é o nó dele |
| `Score()` | `(A, C)` do estado, a partir do cache |
| `Recompute()` | `(A, C)` recalculado do zero (para testes) |
| `Clone()` | cópia independente (útil no GRASP) |
| `NodeOf`, `Used`, `On`, `NodeCost`, `Node`, `Pod`, `NumNodes`, `NumPods` | consultas |

Os métodos `Delta*` não alteram o estado nem verificam capacidade: chame `Fits` antes.

## Testes

```bash
go test ./...
go test -run xxx -bench .   # custo de avaliar um movimento (BenchmarkDeltaMove)
```

- Testes com valores calculados à mão: `TestAdmissionWeight`, `TestFragmentation`, `TestNodeCost`, `TestFits`, `TestBetter`, `TestDeltaAssignIgualFormulaDoScheduler`.
- `TestDeltaIgualRecalculo`: em milhares de movimentos aleatórios, confere que o ΔC previsto é igual à diferença dos custos recalculados e que `Score()` nunca se afasta de `Recompute()`. É o teste mais importante do pacote.
- `TestConfigInvalida` e `TestCloneIndependente` cobrem a validação e o `Clone`.
