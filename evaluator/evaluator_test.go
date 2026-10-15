package evaluator

import (
	"math"
	"math/rand"
	"testing"
)

// Recursos dos testes: 0 = CPU (milicores), 1 = memória (MiB).
func testConfig(lambda float64) Config {
	return Config{
		ResourceNames:     []string{"cpu", "memory"},
		Lambda:            lambda,
		ReferenceCapacity: Resources{8000, 32768},
		PodTypes: []PodType{
			{Requests: Resources{500, 1024}, Weight: 3},  // p = 0,75
			{Requests: Resources{4000, 8192}, Weight: 1}, // p = 0,25
		},
	}
}

func mustNew(t testing.TB, cfg Config) *Evaluator {
	t.Helper()
	ev, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	return ev
}

// approx compara dois float64 com tolerância relativa.
func approx(a, b float64) bool {
	return math.Abs(a-b) <= 1e-9*math.Max(1, math.Max(math.Abs(a), math.Abs(b)))
}

func checkFloat(t *testing.T, name string, got, want float64) {
	t.Helper()
	if !approx(got, want) {
		t.Errorf("%s: obtido %v, esperado %v", name, got, want)
	}
}

func TestAdmissionWeight(t *testing.T) {
	ev := mustNew(t, testConfig(1))
	cases := []struct {
		name string
		req  Resources
		want int64 // milionésimos de cap_ref
	}{
		{"CPU domina", Resources{2000, 4096}, 250000},
		{"memória domina", Resources{500, 16384}, 500000},
		{"BestEffort", Resources{0, 0}, 0},
	}
	for _, c := range cases {
		if got := ev.AdmissionWeight(c.req); got != c.want {
			t.Errorf("%s: obtido %d, esperado %d", c.name, got, c.want)
		}
	}
}

func TestFragmentation(t *testing.T) {
	ev := mustNew(t, testConfig(1))
	alloc := Resources{4000, 16384}
	cases := []struct {
		name string
		used Resources
		want float64
	}{
		{"cheio", Resources{4000, 16384}, 0},
		{"vazio, todos os tipos cabem", Resources{0, 0}, 0},
		{"só o tipo grande não cabe", Resources{1000, 0}, 0.21875},
		{"nenhum tipo cabe", Resources{3800, 0}, 0.525},
		{"sobra CPU, falta memória", Resources{0, 16000}, (1 + 384.0/16384) / 2},
	}
	for _, c := range cases {
		checkFloat(t, c.name, ev.Fragmentation(alloc, c.used), c.want)
	}
}

func TestNodeCost(t *testing.T) {
	ev := mustNew(t, testConfig(2))
	nodes := []Node{
		{Name: "comum", Cost: 2, Allocatable: Resources{4000, 16384}},
		{Name: "só daemonset", Cost: 5, Allocatable: Resources{4000, 16384}},
		{Name: "ancorado", Cost: 3, Allocatable: Resources{4000, 16384}, Anchored: true},
	}
	pods := []Pod{
		{Name: "p", Requests: Resources{1000, 0}},
		{Name: "daemon", Requests: Resources{100, 128}, DaemonSet: true},
	}
	s, err := ev.NewState(nodes, pods)
	if err != nil {
		t.Fatal(err)
	}

	// Estado inicial: só o nó ancorado está ligado (custo 3).
	checkFloat(t, "C inicial", s.Score().C, 3)

	s.Assign(0, 0)
	// Nó comum com o pod p: 2 + 2·2·F.
	checkFloat(t, "custo do nó comum", s.NodeCost(0), 2.875)

	s.Assign(1, 1)
	// Só DaemonSet não liga o nó: custo 0.
	checkFloat(t, "custo do nó só daemonset", s.NodeCost(1), 0)
}

func TestDeltaAssignIgualFormulaDoScheduler(t *testing.T) {
	// λ = 2. Os dois nós são iguais e custam 2; o nó "ligado" já tem um pod.
	const lambda = 2.0
	ev := mustNew(t, testConfig(lambda))
	alloc := Resources{4000, 16384}
	nodes := []Node{
		{Name: "desligado", Cost: 2, Allocatable: alloc},
		{Name: "ligado", Cost: 2, Allocatable: alloc},
	}
	pods := []Pod{
		{Name: "ja-no-ligado", Requests: Resources{1000, 0}},
		{Name: "novo", Requests: Resources{2800, 0}},
	}
	s, err := ev.NewState(nodes, pods)
	if err != nil {
		t.Fatal(err)
	}
	s.Assign(0, 1) // o nó 1 fica ligado, com uso {1000, 0}

	novo := pods[1].Requests
	c := nodes[0].Cost

	// Nó desligado: estava desligado (termo c_i) e F_antes = 0.
	fDepois := ev.Fragmentation(alloc, novo)
	formula := c*1 + lambda*c*(fDepois-0)
	checkFloat(t, "ΔC no nó desligado", s.DeltaAssign(1, 0), formula)

	// Nó ligado: não paga c_i de novo; só muda a fragmentação.
	fAntes := ev.Fragmentation(alloc, Resources{1000, 0})
	fDepois = ev.Fragmentation(alloc, Resources{1000 + 2800, 0})
	formula = c*0 + lambda*c*(fDepois-fAntes)
	checkFloat(t, "ΔC no nó ligado", s.DeltaAssign(1, 1), formula)

	// DeltaAssign não pode alterar o estado.
	if s.NodeOf(1) != Unassigned || s.On(0) {
		t.Error("DeltaAssign alterou o estado")
	}
}

func TestFits(t *testing.T) {
	ev := mustNew(t, testConfig(1))
	nodes := []Node{{Name: "a", Cost: 1, Allocatable: Resources{1000, 1024}}}
	pods := []Pod{
		{Name: "base", Requests: Resources{600, 512}},
		{Name: "exato", Requests: Resources{400, 512}},       // completa o nó nos dois recursos
		{Name: "falta-cpu", Requests: Resources{401, 0}},     // só a CPU não cabe, por 1 milicore
		{Name: "falta-memoria", Requests: Resources{0, 513}}, // só a memória não cabe, por 1 MiB
	}
	s, err := ev.NewState(nodes, pods)
	if err != nil {
		t.Fatal(err)
	}
	s.Assign(0, 0) // uso {600, 512}; livre {400, 512}

	cases := []struct {
		name string
		pod  int
		want bool
	}{
		{"cabe exatamente (igualdade permitida)", 1, true},
		{"não cabe por falta de CPU", 2, false},
		{"não cabe por falta de memória", 3, false},
		{"pod já no próprio nó", 0, true},
	}
	for _, c := range cases {
		if got := s.Fits(c.pod, 0); got != c.want {
			t.Errorf("%s: obtido %v, esperado %v", c.name, got, c.want)
		}
	}

	// Um nó cheio: o pod "base" continua cabendo no próprio nó.
	s.Assign(1, 0) // uso {1000, 1024}
	if !s.Fits(0, 0) {
		t.Error("pod já no nó cheio deveria caber no próprio nó")
	}
}

func TestBetter(t *testing.T) {
	cases := []struct {
		name string
		s, o Score
		want bool
	}{
		{"admissão domina o custo", Score{A: 10, C: 100}, Score{A: 9, C: 1}, true},
		{"menos admissão perde", Score{A: 9, C: 1}, Score{A: 10, C: 100}, false},
		{"mesma admissão, custo menor", Score{A: 10, C: 5}, Score{A: 10, C: 6}, true},
		{"empate exato não é melhor", Score{A: 10, C: 6}, Score{A: 10, C: 6}, false},
		// Diferença abaixo da tolerância relativa conta como empate.
		{"diferença de ruído", Score{A: 10, C: 6 - 1e-13}, Score{A: 10, C: 6}, false},
	}
	for _, c := range cases {
		if got := c.s.Better(c.o); got != c.want {
			t.Errorf("%s: obtido %v, esperado %v", c.name, got, c.want)
		}
	}
}

// TestDeltaUnassignEMove confere DeltaUnassign e DeltaMove com valores
// calculados à mão. Com λ = 2, custo 2 e capacidade {4000, 16384}:
//
//	uso {1000, 0}: F = 0,25·0,875 = 0,21875 → custo 2,875
//	uso {2800, 0}: F = 0,25·0,65 = 0,1625   → custo 2,65
//	uso {3800, 0}: F = 0,525                → custo 4,1
func TestDeltaUnassignEMove(t *testing.T) {
	ev := mustNew(t, testConfig(2))
	alloc := Resources{4000, 16384}
	nodes := []Node{
		{Name: "n0", Cost: 2, Allocatable: alloc},
		{Name: "n1", Cost: 2, Allocatable: alloc},
		{Name: "ancorado", Cost: 3, Allocatable: alloc, Anchored: true},
	}
	pods := []Pod{
		{Name: "p0", Requests: Resources{1000, 0}},
		{Name: "p1", Requests: Resources{2800, 0}},
	}
	s, err := ev.NewState(nodes, pods)
	if err != nil {
		t.Fatal(err)
	}

	// Pod em Unassigned
	checkFloat(t, "DeltaUnassign de pod Unassigned", s.DeltaUnassign(0), 0)
	checkFloat(t, "DeltaAssign em nó desligado", s.DeltaAssign(0, 0), 2.875)
	checkFloat(t, "DeltaMove de pod Unassigned", s.DeltaMove(0, 0), 2.875)

	// Último pod ativo sai: o nó desliga
	s.Assign(0, 0)
	checkFloat(t, "DeltaUnassign do último pod", s.DeltaUnassign(0), -2.875)

	// Ancorado: com o pod custa 3 + 2·3·0,21875 = 4,3125; vazio, 3
	s.Assign(1, 2)
	s.Unassign(1)
	s.Assign(0, 2)
	checkFloat(t, "custo do ancorado com o pod", s.NodeCost(2), 4.3125)
	checkFloat(t, "DeltaUnassign no ancorado", s.DeltaUnassign(0), 3-4.3125)
	s.Unassign(0)

	// p0 sai de n0 (desliga) e entra em n1, onde está p1
	s.Assign(0, 0)
	s.Assign(1, 1)
	checkFloat(t, "DeltaMove entre nós", s.DeltaMove(0, 1), -2.875+(4.1-2.65))

	checkFloat(t, "DeltaMove para o próprio nó", s.DeltaMove(0, 0), 0)

	// Os Delta* não podem alterar o estado.
	if s.NodeOf(0) != 0 || s.NodeOf(1) != 1 || !s.On(0) {
		t.Error("um Delta* alterou o estado")
	}

	before := s.Score().C
	predicted := s.DeltaMove(0, 1)
	s.Assign(0, 1)
	checkFloat(t, "C depois do movimento", s.Score().C, before+predicted)
	if s.On(0) {
		t.Error("n0 deveria ter desligado")
	}
}

// TestDaemonSetNaoMantemNoLigado confere que pods de DaemonSet ocupam espaço,
// mas não ligam nem mantêm o nó ligado.
func TestDaemonSetNaoMantemNoLigado(t *testing.T) {
	ev := mustNew(t, testConfig(2))
	alloc := Resources{4000, 16384}
	nodes := []Node{
		{Name: "n0", Cost: 2, Allocatable: alloc},
		{Name: "n1", Cost: 5, Allocatable: alloc},
	}
	pods := []Pod{
		{Name: "p", Requests: Resources{1000, 0}},
		{Name: "daemon", Requests: Resources{100, 128}, DaemonSet: true},
	}
	s, err := ev.NewState(nodes, pods)
	if err != nil {
		t.Fatal(err)
	}

	checkFloat(t, "DeltaAssign do DaemonSet em nó desligado", s.DeltaAssign(1, 1), 0)
	s.Assign(1, 1)
	if s.On(1) {
		t.Error("DaemonSet não deveria ligar o nó")
	}
	checkFloat(t, "custo do nó só com DaemonSet", s.NodeCost(1), 0)
	s.Unassign(1)

	// Uso {1100, 128}: livre {2900, 16256}; só o tipo grande não cabe
	s.Assign(0, 0)
	s.Assign(1, 0)
	fracLivre := (0.725 + 16256.0/16384) / 2
	custoComAmbos := 2 + 2*2*(0.25*fracLivre)
	checkFloat(t, "custo com p e DaemonSet", s.NodeCost(0), custoComAmbos)

	// O DaemonSet sai, p fica: o nó continua ligado (custo 2,875)
	checkFloat(t, "DeltaUnassign do DaemonSet", s.DeltaUnassign(1), 2.875-custoComAmbos)

	// p sai, o DaemonSet fica: o nó desliga
	checkFloat(t, "DeltaUnassign do pod ativo", s.DeltaUnassign(0), -custoComAmbos)
	s.Unassign(0)
	if s.On(0) {
		t.Error("nó só com DaemonSet deveria estar desligado")
	}
	checkFloat(t, "C depois de p sair", s.Score().C, 0)
	checkFloat(t, "C recalculado", s.Recompute().C, 0)
}

// TestFragmentationBordas cobre os casos de borda de F.
func TestFragmentationBordas(t *testing.T) {
	ev := mustNew(t, testConfig(1))

	t.Run("uso acima da capacidade vira livre 0", func(t *testing.T) {
		// livre {0, 16384}: frac_livre = 0,5 e nenhum tipo cabe
		got := ev.Fragmentation(Resources{4000, 16384}, Resources{5000, 0})
		checkFloat(t, "F", got, 0.5)
	})

	t.Run("recurso com capacidade zero é ignorado na média", func(t *testing.T) {
		// Só a CPU entra em frac_livre (0,75); os tipos pedem memória e não cabem
		got := ev.Fragmentation(Resources{4000, 0}, Resources{1000, 0})
		checkFloat(t, "F", got, 0.75)
	})

	t.Run("nenhum recurso com capacidade", func(t *testing.T) {
		got := ev.Fragmentation(Resources{0, 0}, Resources{0, 0})
		checkFloat(t, "F", got, 0)
	})

	t.Run("M_pods vazia", func(t *testing.T) {
		cfg := testConfig(1)
		cfg.PodTypes = nil
		vazio := mustNew(t, cfg)
		got := vazio.Fragmentation(Resources{4000, 16384}, Resources{1000, 0})
		checkFloat(t, "F", got, 0)
	})

	t.Run("encaixe exato conta como caber", func(t *testing.T) {
		// livre {500, 1024} é exatamente o tipo pequeno; só o grande não cabe
		got := ev.Fragmentation(Resources{4000, 16384}, Resources{3500, 15360})
		checkFloat(t, "F", got, 0.25*0.09375)
	})

	t.Run("um milicore a menos, o tipo pequeno não cabe", func(t *testing.T) {
		// livre {499, 1024}: nenhum tipo cabe
		got := ev.Fragmentation(Resources{4000, 16384}, Resources{3501, 15360})
		checkFloat(t, "F", got, (499.0/4000+0.0625)/2)
	})
}

func TestConfigInvalida(t *testing.T) {
	cases := map[string]func(*Config){
		"sem recursos":       func(c *Config) { c.ReferenceCapacity = nil },
		"cap_ref zero":       func(c *Config) { c.ReferenceCapacity = Resources{0, 1} },
		"lambda negativo":    func(c *Config) { c.Lambda = -1 },
		"tipo com 3 recurso": func(c *Config) { c.PodTypes[0].Requests = Resources{1, 2, 3} },
		"peso negativo":      func(c *Config) { c.PodTypes[0].Weight = -1 },
		"pesos somam zero":   func(c *Config) { c.PodTypes[0].Weight, c.PodTypes[1].Weight = 0, 0 },
		"nomes a menos":      func(c *Config) { c.ResourceNames = []string{"cpu"} },
	}
	for name, mutate := range cases {
		cfg := testConfig(1)
		mutate(&cfg)
		if _, err := New(cfg); err == nil {
			t.Errorf("%s: esperado erro", name)
		}
	}
}

// randomState monta um cluster aleatório com pods já alocados onde cabem.
func randomState(t testing.TB, rng *rand.Rand) *State {
	t.Helper()
	cfg := Config{
		Lambda:            rng.Float64() * 5,
		ReferenceCapacity: Resources{16000, 65536},
	}
	for m := 0; m < 1+rng.Intn(5); m++ {
		cfg.PodTypes = append(cfg.PodTypes, PodType{
			Requests: Resources{int64(100 + rng.Intn(4000)), int64(128 + rng.Intn(16384))},
			Weight:   rng.Float64() + 0.01,
		})
	}
	ev := mustNew(t, cfg)

	sizes := []Resources{{4000, 16384}, {8000, 32768}, {16000, 65536}}
	var nodes []Node
	for i := 0; i < 3+rng.Intn(10); i++ {
		k := rng.Intn(len(sizes))
		nodes = append(nodes, Node{
			Cost:        float64(k+1) * (0.5 + rng.Float64()),
			Allocatable: sizes[k],
			Anchored:    rng.Intn(10) == 0,
		})
	}
	var pods []Pod
	for j := 0; j < 10+rng.Intn(80); j++ {
		pods = append(pods, Pod{
			Requests:  Resources{int64(rng.Intn(3000)), int64(rng.Intn(8192))},
			DaemonSet: rng.Intn(10) == 0,
		})
	}
	s, err := ev.NewState(nodes, pods)
	if err != nil {
		t.Fatal(err)
	}
	for j := range pods {
		i := rng.Intn(len(nodes))
		if rng.Intn(5) > 0 && s.Fits(j, i) {
			s.Assign(j, i)
		}
	}
	return s
}

// TestDeltaIgualRecalculo confere, em movimentos aleatórios, que o ΔC previsto
// é igual à diferença dos custos recalculados e que Score() acompanha
// Recompute().
func TestDeltaIgualRecalculo(t *testing.T) {
	rng := rand.New(rand.NewSource(42))
	for inst := 0; inst < 50; inst++ {
		s := randomState(t, rng)
		for op := 0; op < 2000; op++ {
			j := rng.Intn(s.NumPods())
			before := s.Recompute()

			var predicted float64
			if rng.Intn(5) == 0 {
				predicted = s.DeltaUnassign(j)
				s.Unassign(j)
			} else {
				i := rng.Intn(s.NumNodes())
				if !s.Fits(j, i) {
					continue
				}
				predicted = s.DeltaMove(j, i)
				s.Assign(j, i)
			}

			after := s.Recompute()
			if !approx(predicted, after.C-before.C) {
				t.Fatalf("instância %d, op %d: ΔC previsto %v, real %v", inst, op, predicted, after.C-before.C)
			}
			if got := s.Score(); got.A != after.A || !approx(got.C, after.C) {
				t.Fatalf("instância %d, op %d: incremental %+v, recalculado %+v", inst, op, got, after)
			}
		}
	}
}

func TestCloneIndependente(t *testing.T) {
	s := randomState(t, rand.New(rand.NewSource(7)))
	orig := s.Score()
	c := s.Clone()
	for j := 0; j < c.NumPods(); j++ {
		c.Unassign(j)
	}
	if got := s.Score(); got != orig {
		t.Errorf("alterar o clone mudou o original: %+v -> %+v", orig, got)
	}
	if got := c.Score(); got.A != 0 {
		t.Errorf("clone deveria ter A = 0, tem %d", got.A)
	}
}

// BenchmarkDeltaMove mede o custo de avaliar um movimento. Rode com:
//
//	go test -run xxx -bench .
func BenchmarkDeltaMove(b *testing.B) {
	s := randomState(b, rand.New(rand.NewSource(1)))
	b.ResetTimer()
	for n := 0; n < b.N; n++ {
		_ = s.DeltaMove(n%s.NumPods(), n%s.NumNodes())
	}
}
