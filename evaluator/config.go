// Package evaluator implementa a função objetivo compartilhada pelos plugins de
// scheduler e de descheduler (ver funcao_objetivo.md).
//
// O pacote não depende do Kubernetes: trabalha com vetores de recursos
// (int64) e índices de nós e pods. Cada plugin converte os seus objetos
// para os tipos daqui.
package evaluator

import (
	"errors"
	"fmt"
	"math"
)

// Resources é um vetor de quantidades de recursos. A posição r de todos os
// vetores se refere ao mesmo recurso (por exemplo, 0 = CPU em milicores,
// 1 = memória em bytes).
type Resources []int64

// PodType é um tipo de pod típico da distribuição M_pods.
type PodType struct {
	Requests Resources // requests do tipo, um valor por recurso
	Weight   float64   // frequência relativa; não precisa somar 1
}

// Config são os parâmetros da função objetivo, iguais nos dois plugins.
type Config struct {
	ResourceNames     []string  // opcional, só para mensagens de erro
	Lambda            float64   // λ, peso da fragmentação
	ReferenceCapacity Resources // cap_ref, usada nos pesos de admissão
	PodTypes          []PodType // M_pods
}

// Evaluator guarda a configuração já validada.
type Evaluator struct {
	numRes    int
	lambda    float64
	refCap    Resources
	typeReqs  []Resources // requests de cada tipo m
	typeProbs []float64   // p_m de cada tipo, somando 1
}

// New valida a configuração e devolve um avaliador pronto para uso.
func New(cfg Config) (*Evaluator, error) {
	n := len(cfg.ReferenceCapacity)
	if n == 0 {
		return nil, errors.New("referenceCapacity deve ter pelo menos um recurso")
	}
	if cfg.ResourceNames != nil && len(cfg.ResourceNames) != n {
		return nil, fmt.Errorf("resourceNames tem %d nomes, mas referenceCapacity tem %d recursos",
			len(cfg.ResourceNames), n)
	}
	for r, v := range cfg.ReferenceCapacity {
		if v <= 0 {
			return nil, fmt.Errorf("referenceCapacity[%s] deve ser > 0, é %d", resName(cfg, r), v)
		}
	}
	if cfg.Lambda < 0 || math.IsNaN(cfg.Lambda) || math.IsInf(cfg.Lambda, 0) {
		return nil, fmt.Errorf("lambda deve ser um número >= 0, é %v", cfg.Lambda)
	}

	ev := &Evaluator{
		numRes: n,
		lambda: cfg.Lambda,
		refCap: append(Resources(nil), cfg.ReferenceCapacity...),
	}

	// Normaliza os pesos de M_pods para que os p_m somem 1.
	var total float64
	for m, t := range cfg.PodTypes {
		if len(t.Requests) != n {
			return nil, fmt.Errorf("podTypes[%d] tem %d recursos, esperado %d", m, len(t.Requests), n)
		}
		if t.Weight < 0 || math.IsNaN(t.Weight) || math.IsInf(t.Weight, 0) {
			return nil, fmt.Errorf("podTypes[%d].weight deve ser >= 0, é %v", m, t.Weight)
		}
		for r, v := range t.Requests {
			if v < 0 {
				return nil, fmt.Errorf("podTypes[%d].requests[%s] deve ser >= 0, é %d", m, resName(cfg, r), v)
			}
		}
		total += t.Weight
	}
	if len(cfg.PodTypes) > 0 && total == 0 {
		return nil, errors.New("a soma dos pesos de podTypes deve ser > 0")
	}
	for _, t := range cfg.PodTypes {
		if t.Weight == 0 {
			continue
		}
		ev.typeReqs = append(ev.typeReqs, append(Resources(nil), t.Requests...))
		ev.typeProbs = append(ev.typeProbs, t.Weight/total)
	}
	return ev, nil
}

// NumResources devolve o número de recursos que o avaliador espera.
func (e *Evaluator) NumResources() int { return e.numRes }

// AdmissionWeight devolve o peso de admissão w_j de um pod com os requests req.
//
//	w_j = max_r (req_r / cap_ref_r)
//
// O resultado é int64, em milionésimos de cap_ref, para que a comparação de A
// seja exata. Pod sem requests tem peso 0.
func (e *Evaluator) AdmissionWeight(req Resources) int64 {
	w := 0.0
	for r := 0; r < e.numRes; r++ {
		frac := float64(req[r]) / float64(e.refCap[r])
		if frac > w {
			w = frac
		}
	}
	return int64(math.Round(w * 1e6)) // escala para milionésimos
}

// Fragmentation devolve F para um nó LIGADO com capacidade alloc e uso used:
//
//		F = Σ_m p_m · 1[tipo m não cabe no espaço livre] · frac_livre
//
//	  - livre_r = alloc[r] − used[r], com mínimo 0.
//	  - frac_livre é a média de livre_r / alloc[r] nos recursos com
//	    capacidade > 0.
//	  - Um tipo cabe se couber em todos os recursos.
func (e *Evaluator) Fragmentation(alloc, used Resources) float64 {
	n := len(alloc)

	// Espaço livre de cada recurso (nunca negativo)
	free := make([]int64, n)
	for r := 0; r < n; r++ {
		free[r] = alloc[r] - used[r]
		if free[r] < 0 {
			free[r] = 0
		}
	}

	// frac_livre: média de free[r]/alloc[r], só nos recursos com capacidade > 0
	sum := 0.0
	counted := 0
	for r := 0; r < n; r++ {
		if alloc[r] == 0 {
			continue
		}
		sum += float64(free[r]) / float64(alloc[r])
		counted++
	}
	if counted == 0 {
		return 0
	}
	fracFree := sum / float64(counted)

	// Soma dos p_m dos tipos que não cabem
	notFit := 0.0
	for m := 0; m < len(e.typeReqs); m++ {
		fits := true
		for r := 0; r < n; r++ {
			if e.typeReqs[m][r] > free[r] {
				fits = false
				break
			}
		}
		if !fits {
			notFit += e.typeProbs[m]
		}
	}

	return notFit * fracFree
}

// nodeCost devolve a parcela de um nó em C: c_i·x_i + λ·c_i·F_i.
//
// on indica x_i (ver isOn). Nó desligado custa 0.
func (e *Evaluator) nodeCost(n Node, used Resources, on bool) float64 {
	if !on {
		return 0.0
	}
	cost := float64(n.Cost)
	frag := e.Fragmentation(n.Allocatable, used)
	return cost + e.lambda*cost*frag
}

func resName(cfg Config, r int) string {
	if r < len(cfg.ResourceNames) {
		return cfg.ResourceNames[r]
	}
	return fmt.Sprintf("%d", r)
}
