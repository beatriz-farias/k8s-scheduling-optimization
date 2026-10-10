"""
Experimentos de Scheduler + Descheduler.

Roda todas as combinações Scheduler x Descheduler com o mesmo limite de
evicções por ciclo (DESCHEDULER_MAX_MOVES) e grava um CSV por combinação de
λ, ω, folga de capacidade e modelo de custo em results/ (formato longo: uma
linha por instância x configuração).

As configurações com Scheduler heurístico (least_requested, greedy) são as
implantáveis. As com Scheduler MILP (até 60 s por fila de pods) são a
referência: um limite superior, não algo que rode no caminho crítico. O
"milp+milp" mostra quanto se perde quando o Scheduler não segue o plano do
Descheduler. A base de comparação é o kube-scheduler padrão sem Descheduler
("least_requested+none").

Vários valores em --lam e/ou --omega-fraction fazem uma varredura, com
comparação no final.

Os CSVs são salvos após cada instância e, ao rodar de novo, as linhas já
existentes são puladas (retomada após interrupção).

Uso:
    python -m experiments                              # roda e analisa
    python -m experiments --lam 0 1 2 5                # varredura de λ
    python -m experiments --omega-fraction 0 0.25 0.5 1 2 --sizes 10x100 20x200
    python -m experiments --margin 1.6                 # capacidade folgada (sem Pending)
    python -m experiments --cost-model proportional    # c_i proporcional à capacidade
    python -m experiments --analyze                    # só relê os CSVs
    python -m experiments --quick --runs 2             # teste rápido (*_quick.csv)
"""

import argparse
import itertools

from experiments import settings
from experiments.configurations import factorial_configs
from experiments.results_store import ResultsStore
from experiments.runner import ExperimentRunner
from experiments.statistical_tests import run_statistical_tests
from experiments.tables import print_factorial_tables, print_sweep_comparison


def analyze(store: ResultsStore, sizes: list):
    """Tabelas e testes só dos tamanhos pedidos (o CSV pode ter mais)."""
    rows = [r for r in store.load() if (int(r["n_nodes"]), int(r["n_pods"])) in sizes]
    if not rows:
        print("Nenhum resultado encontrado em results/.")
        return []
    print_factorial_tables(rows)
    run_statistical_tests(rows)
    return rows


def parse_size(text: str) -> tuple:
    """'10x100' -> (10, 100): nós x pods."""
    nodes, pods = text.lower().split("x")
    return int(nodes), int(pods)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Scheduler + Descheduler")
    parser.add_argument("--analyze", action="store_true",
                        help="só relê os CSVs e imprime tabelas e testes, sem rodar")
    parser.add_argument("--runs", type=int, default=settings.N_RUNS, help="seeds por tamanho")
    parser.add_argument("--quick", action="store_true",
                        help=f"só os tamanhos {settings.QUICK_INSTANCE_SIZES}")
    parser.add_argument("--sizes", type=parse_size, nargs="+", metavar="NxP",
                        help="só estes tamanhos (nós x pods), por exemplo 10x100 20x200")
    parser.add_argument("--lam", type=float, nargs="+", default=[settings.LAMBDA],
                        help="peso(s) λ da fragmentação; vários valores fazem uma varredura")
    parser.add_argument("--omega-fraction", type=float, nargs="+",
                        default=[settings.OMEGA_FRACTION], metavar="F",
                        help="ω = F × c_i médio; vários valores fazem uma varredura")
    parser.add_argument("--margin", type=float, default=settings.CAPACITY_MARGIN,
                        help="folga de capacidade das instâncias (perto de 1,0 sobram pods Pending)")
    parser.add_argument("--cost-model", choices=["martins", "proportional"],
                        default=settings.COST_MODEL,
                        help="martins: c_i ~ U(1, 4n) independente da capacidade; "
                             "proportional: c_i proporcional à capacidade, com ruído")
    parser.add_argument("--no-milp", action="store_true",
                        help="pula as configurações com Scheduler ou Descheduler MILP (sem Gurobi)")
    return parser.parse_args()


def build_store(quick: bool) -> ResultsStore:
    store = ResultsStore(settings.factorial_csv(
        settings.LAMBDA, settings.CAPACITY_MARGIN, settings.OMEGA_FRACTION,
        settings.COST_MODEL))
    # --quick grava em arquivo separado para não misturar com a bateria oficial
    return store.with_suffix("_quick") if quick else store


def run_factorial(store, sizes, args):
    print(f"Fatorial Scheduler x Descheduler (N_RUNS={args.runs}, "
          f"K={settings.DESCHEDULER_MAX_MOVES} evicções/período, lambda={settings.LAMBDA:g}, "
          f"omega={settings.OMEGA_FRACTION:g}*c, folga={settings.CAPACITY_MARGIN:g}, "
          f"custo={settings.COST_MODEL})")
    ExperimentRunner(store, sizes, args.runs).run(factorial_configs(include_milp=not args.no_milp))


def main():
    args = parse_arguments()
    settings.CAPACITY_MARGIN = args.margin
    settings.COST_MODEL = args.cost_model
    sizes = args.sizes or (settings.QUICK_INSTANCE_SIZES if args.quick
                           else settings.DEFAULT_INSTANCE_SIZES)
    rows_by_setting = {}
    for lam, omega_fraction in itertools.product(args.lam, args.omega_fraction):
        settings.LAMBDA, settings.OMEGA_FRACTION = lam, omega_fraction
        store = build_store(args.quick)
        if not args.analyze:
            run_factorial(store, sizes, args)
        name = f"lambda={lam:g} omega={omega_fraction:g}"
        print(f"\n########## {name} ##########")
        rows_by_setting[name] = analyze(store, sizes)
    print_sweep_comparison(rows_by_setting)


if __name__ == "__main__":
    main()
