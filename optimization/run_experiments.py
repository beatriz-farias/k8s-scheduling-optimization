"""
Fase 2: experimentos da arquitetura incremental (Scheduler + Descheduler).

Só configurações executáveis no Kubernetes são comparadas entre si. O MILP
participa como Scheduler (coloca a fila de pods de uma vez, com os pods que
já rodam fixos) e como Descheduler (planeja quais pods mover). A combinação
"milp+milp" é o pipeline incremental todo exato: o Scheduler MILP recoloca
os evictados seguindo o plano do Descheduler MILP. A base de comparação é o
kube-scheduler padrão sem Descheduler ("least_requested+none").

Duas etapas, cada uma com seu CSV em results/ (formato longo: uma linha
por instância x configuração):

  factorial    Todas as combinações Scheduler x Descheduler com o mesmo
               limite de evicções por ciclo (DESCHEDULER_MAX_MOVES).
  sensitivity  Varredura do limite de evicções por ciclo
               (SENSITIVITY_MAX_MOVES) para SENSITIVITY_CONFIGS, que mostra
               o trade-off custo x disrupção.

A análise imprime as tabelas e escolhe a melhor configuração por custo
total, com teste de Friedman e Wilcoxon pareado (correção de Holm) contra
as demais. Os testes exigem scipy.

Os CSVs são salvos após cada instância e, ao rodar de novo, as linhas já
existentes são puladas (retomada após interrupção).

Uso:
    python run_experiments.py                      # tudo
    python run_experiments.py --stage factorial
    python run_experiments.py --stage analyze      # só relê os CSVs
    python run_experiments.py --quick --runs 2     # teste rápido (*_quick.csv)
"""

import argparse

from experiments import settings
from experiments.configurations import factorial_configs, sensitivity_configs
from experiments.results_store import ResultsStore
from experiments.runner import ExperimentRunner
from experiments.statistical_tests import run_statistical_tests
from experiments.summary import without_legacy
from experiments.tables import print_factorial_tables, print_sensitivity_tables


def analyze(factorial_store: ResultsStore, sensitivity_store: ResultsStore):
    factorial = without_legacy(factorial_store.load())
    sensitivity = without_legacy(sensitivity_store.load())
    if factorial:
        print_factorial_tables(factorial)
        run_statistical_tests(factorial)
    if sensitivity:
        print_sensitivity_tables(sensitivity)
    if not factorial and not sensitivity:
        print("Nenhum resultado encontrado em results/.")


def parse_arguments():
    parser = argparse.ArgumentParser(description="Fase 2: Scheduler + Descheduler")
    parser.add_argument("--stage", choices=["factorial", "sensitivity", "analyze", "all"],
                        default="all")
    parser.add_argument("--runs", type=int, default=settings.N_RUNS, help="seeds por tamanho")
    parser.add_argument("--quick", action="store_true",
                        help=f"só os tamanhos {settings.QUICK_INSTANCE_SIZES}")
    parser.add_argument("--no-milp", action="store_true",
                        help="pula as configurações com Scheduler ou Descheduler MILP (sem Gurobi)")
    return parser.parse_args()


def build_stores(quick: bool):
    factorial = ResultsStore(settings.FACTORIAL_CSV)
    sensitivity = ResultsStore(settings.SENSITIVITY_CSV)
    if not quick:
        return factorial, sensitivity
    # --quick grava em arquivos separados para não misturar com a bateria oficial
    return factorial.with_suffix("_quick"), sensitivity.with_suffix("_quick")


def run_factorial(store, sizes, args):
    print(f"Fatorial Scheduler x Descheduler (N_RUNS={args.runs}, "
          f"K={settings.DESCHEDULER_MAX_MOVES} evicções/período)")
    ExperimentRunner(store, sizes, args.runs).run(factorial_configs(include_milp=not args.no_milp))


def run_sensitivity(store, sizes, args):
    print(f"\nSensibilidade do limite de evicções K em {settings.SENSITIVITY_MAX_MOVES}")
    ExperimentRunner(store, sizes, args.runs).run(sensitivity_configs(include_milp=not args.no_milp))


def main():
    args = parse_arguments()
    sizes = settings.QUICK_INSTANCE_SIZES if args.quick else settings.DEFAULT_INSTANCE_SIZES
    factorial_store, sensitivity_store = build_stores(args.quick)

    if args.stage in ("factorial", "all"):
        run_factorial(factorial_store, sizes, args)
    if args.stage in ("sensitivity", "all"):
        run_sensitivity(sensitivity_store, sizes, args)
    analyze(factorial_store, sensitivity_store)


if __name__ == "__main__":
    main()
