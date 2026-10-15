package evaluator

import (
	"fmt"
	"math"
)

// Unassigned indica um pod que não está em nenhum nó (Pending).
const Unassigned = -1

// Node é um nó do cluster, já convertido pelo plugin.
type Node struct {
	Name        string
	Cost        float64   // c_i, custo por ciclo
	Allocatable Resources // capacidade alocável
	// Anchored indica que o Cluster Autoscaler nunca removeria o nó
	// (por exemplo, por ter pods com armazenamento local).
	Anchored bool
}

// Pod é um pod do cluster, já convertido pelo plugin.
type Pod struct {
	Name      string
	Requests  Resources
	DaemonSet bool // pod de DaemonSet
}

// Score é o valor de uma solução: A (admissão) e C (custo).
type Score struct {
	A int64   // maior é melhor
	C float64 // menor é melhor
}

// State é uma alocação de pods a nós. O uso de cada nó e a parcela de cada
// nó em C ficam em cache e são atualizados a cada Assign/Unassign.
// Não é seguro para uso concorrente.
type State struct {
	ev     *Evaluator
	nodes  []Node
	pods   []Pod
	weight []int64 // w_j de cada pod

	assign   []int       // nó de cada pod, ou Unassigned
	used     []Resources // soma dos requests por nó
	active   []int       // pods que mantêm o nó ligado, por nó
	nodeCost []float64   // parcela de cada nó em C
	admitted int64       // A
}

// costTolerance é a tolerância relativa para empates em C
// (seção "Comparação entre soluções").
const costTolerance = 1e-9

// Better diz se s é estritamente melhor que o: mais admissão, ou a mesma
// admissão e custo menor. Diferenças de C abaixo da tolerância contam como
// empate.
func (s Score) Better(o Score) bool {
	if s.A != o.A {
		return s.A > o.A
	}
	return s.C < o.C-costTolerance*math.Max(1, math.Abs(o.C))
}

// countsAsActive diz se o pod p mantém o nó ligado. Pods de DaemonSet não
// contam: o Cluster Autoscaler os ignora ao remover nós.
func countsAsActive(p Pod) bool {
	return !p.DaemonSet
}

// isOn diz se um nó está ligado (x_i = 1): tem pod ativo ou é ancorado.
func isOn(n Node, activePods int) bool {
	return activePods > 0 || n.Anchored
}

// Fits diz se o pod j cabe no nó i. A igualdade é permitida. Um pod que já
// está no nó i sempre cabe nele, pois seus requests já estão em s.used[i].
func (s *State) Fits(j, i int) bool {
	if s.assign[j] == i {
		return true
	}
	alloc := s.nodes[i].Allocatable
	used := s.used[i]
	req := s.pods[j].Requests
	for r := range req {
		if used[r]+req[r] > alloc[r] {
			return false
		}
	}
	return true
}

// DeltaAssign devolve a variação de C se o pod j (em Unassigned) for colocado
// no nó i, sem alterar o estado:
//
//	ΔC(i) = c_i·[i estava desligado] + λ·c_i·(F_depois − F_antes)
//
// Calculada como custo do nó depois menos custo do nó antes. Não verifica
// capacidade: use Fits antes.
func (s *State) DeltaAssign(j, i int) float64 {
	p := s.pods[j]
	activeAfter := s.active[i]
	if countsAsActive(p) {
		activeAfter++
	}
	usedAfter := withDelta(s.used[i], p.Requests, +1)
	costAfter := s.ev.nodeCost(s.nodes[i], usedAfter, isOn(s.nodes[i], activeAfter))
	return costAfter - s.nodeCost[i]
}

// DeltaUnassign devolve a variação de C se o pod j sair do nó em que está,
// sem alterar o estado. Se o último pod ativo sai, o nó desliga (a menos que
// seja ancorado). Para um pod em Unassigned, devolve 0.
func (s *State) DeltaUnassign(j int) float64 {
	i := s.assign[j]
	if i == Unassigned {
		return 0
	}
	p := s.pods[j]
	activeAfter := s.active[i]
	if countsAsActive(p) {
		activeAfter--
	}
	usedAfter := withDelta(s.used[i], p.Requests, -1)
	costAfter := s.ev.nodeCost(s.nodes[i], usedAfter, isOn(s.nodes[i], activeAfter))
	return costAfter - s.nodeCost[i]
}

// DeltaMove devolve a variação de C se o pod j for movido para o nó dst,
// sem alterar o estado. É a soma de DeltaUnassign e DeltaAssign, pois o custo
// de cada nó só depende dos próprios pods. Se dst é o nó atual, devolve 0.
// Não verifica capacidade: use Fits antes.
func (s *State) DeltaMove(j, dst int) float64 {
	if s.assign[j] == dst {
		return 0
	}
	return s.DeltaUnassign(j) + s.DeltaAssign(j, dst)
}

// NewState cria um estado com todos os pods em Unassigned.
func (e *Evaluator) NewState(nodes []Node, pods []Pod) (*State, error) {
	for _, n := range nodes {
		if len(n.Allocatable) != e.numRes {
			return nil, fmt.Errorf("nó %q tem %d recursos, esperado %d", n.Name, len(n.Allocatable), e.numRes)
		}
		if n.Cost < 0 || math.IsNaN(n.Cost) || math.IsInf(n.Cost, 0) {
			return nil, fmt.Errorf("nó %q tem custo inválido %v", n.Name, n.Cost)
		}
	}
	s := &State{
		ev:       e,
		nodes:    append([]Node(nil), nodes...),
		pods:     append([]Pod(nil), pods...),
		weight:   make([]int64, len(pods)),
		assign:   make([]int, len(pods)),
		used:     make([]Resources, len(nodes)),
		active:   make([]int, len(nodes)),
		nodeCost: make([]float64, len(nodes)),
	}
	for j, p := range pods {
		if len(p.Requests) != e.numRes {
			return nil, fmt.Errorf("pod %q tem %d recursos, esperado %d", p.Name, len(p.Requests), e.numRes)
		}
		s.weight[j] = e.AdmissionWeight(p.Requests)
		s.assign[j] = Unassigned
	}
	for i := range nodes {
		s.used[i] = make(Resources, e.numRes)
		s.refreshNodeCost(i)
	}
	return s, nil
}

// NumNodes e NumPods devolvem os tamanhos do estado.
func (s *State) NumNodes() int { return len(s.nodes) }
func (s *State) NumPods() int  { return len(s.pods) }

// Node e Pod devolvem os dados de entrada.
func (s *State) Node(i int) Node { return s.nodes[i] }
func (s *State) Pod(j int) Pod   { return s.pods[j] }

// NodeOf devolve o nó do pod j, ou Unassigned.
func (s *State) NodeOf(j int) int { return s.assign[j] }

// Used devolve o uso atual do nó i. Não altere o vetor devolvido.
func (s *State) Used(i int) Resources { return s.used[i] }

// On diz se o nó i está ligado.
func (s *State) On(i int) bool { return isOn(s.nodes[i], s.active[i]) }

// NodeCost devolve a parcela do nó i em C.
func (s *State) NodeCost(i int) float64 { return s.nodeCost[i] }

// Score devolve (A, C) do estado atual.
func (s *State) Score() Score {
	var c float64
	for _, v := range s.nodeCost {
		c += v
	}
	return Score{A: s.admitted, C: c}
}

// Assign coloca o pod j no nó i, movendo-o se estava em outro. Não verifica
// capacidade: use Fits antes.
func (s *State) Assign(j, i int) {
	if s.assign[j] == i {
		return
	}
	if s.assign[j] != Unassigned {
		s.Unassign(j)
	}
	addInto(s.used[i], s.pods[j].Requests, +1)
	if countsAsActive(s.pods[j]) {
		s.active[i]++
	}
	s.assign[j] = i
	s.admitted += s.weight[j]
	s.refreshNodeCost(i)
}

// Unassign tira o pod j do nó em que está (ele volta a Unassigned).
func (s *State) Unassign(j int) {
	i := s.assign[j]
	if i == Unassigned {
		return
	}
	addInto(s.used[i], s.pods[j].Requests, -1)
	if countsAsActive(s.pods[j]) {
		s.active[i]--
	}
	s.assign[j] = Unassigned
	s.admitted -= s.weight[j]
	s.refreshNodeCost(i)
}

// Clone devolve uma cópia independente do estado (útil no GRASP).
func (s *State) Clone() *State {
	c := &State{
		ev:       s.ev,
		nodes:    s.nodes,  // somente leitura, pode ser compartilhado
		pods:     s.pods,   // somente leitura
		weight:   s.weight, // somente leitura
		assign:   append([]int(nil), s.assign...),
		used:     make([]Resources, len(s.used)),
		active:   append([]int(nil), s.active...),
		nodeCost: append([]float64(nil), s.nodeCost...),
		admitted: s.admitted,
	}
	for i, u := range s.used {
		c.used[i] = append(Resources(nil), u...)
	}
	return c
}

// Recompute recalcula (A, C) do zero, sem cache. Usado nos testes.
func (s *State) Recompute() Score {
	used := make([]Resources, len(s.nodes))
	active := make([]int, len(s.nodes))
	for i := range s.nodes {
		used[i] = make(Resources, s.ev.numRes)
	}
	var a int64
	for j, i := range s.assign {
		if i == Unassigned {
			continue
		}
		addInto(used[i], s.pods[j].Requests, +1)
		if countsAsActive(s.pods[j]) {
			active[i]++
		}
		a += s.ev.AdmissionWeight(s.pods[j].Requests)
	}
	var c float64
	for i, n := range s.nodes {
		c += s.ev.nodeCost(n, used[i], isOn(n, active[i]))
	}
	return Score{A: a, C: c}
}

// refreshNodeCost recalcula o cache da parcela do nó i em C.
func (s *State) refreshNodeCost(i int) {
	s.nodeCost[i] = s.ev.nodeCost(s.nodes[i], s.used[i], s.On(i))
}

// withDelta devolve um novo vetor com used + sign·delta. Não altera used.
func withDelta(used, delta Resources, sign int64) Resources {
	out := append(Resources(nil), used...)
	addInto(out, delta, sign)
	return out
}

// addInto faz dst += sign·delta, posição a posição.
func addInto(dst, delta Resources, sign int64) {
	for r := range dst {
		dst[r] += sign * delta[r]
	}
}
