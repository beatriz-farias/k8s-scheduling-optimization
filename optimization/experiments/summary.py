"""Agregação dos resultados brutos: médias por (nós, pods, configuração)."""

import statistics

from . import settings


def without_legacy(rows: list) -> list:
    return [row for row in rows if row["config"] not in settings.LEGACY_LABELS]


class ResultsSummary:
    def __init__(self, rows: list):
        self.rows = rows
        self._means = self._mean_per_group()

    def _mean_per_group(self) -> dict:
        groups = {}
        for row in self.rows:
            key = (int(row["n_nodes"]), int(row["n_pods"]), row["config"])
            groups.setdefault(key, []).append(row)
        return {key: self._mean_metrics(group) for key, group in groups.items()}

    @staticmethod
    def _mean_metrics(group: list) -> dict:
        means = {}
        for metric in settings.METRICS:
            values = [float(r[metric]) for r in group if r.get(metric) not in (None, "")]
            means[metric] = statistics.mean(values) if values else None
        means["n_runs"] = len(group)
        return means

    def get(self, n_nodes: int, n_pods: int, config: str):
        """Médias do grupo, ou None se a combinação não foi executada."""
        return self._means.get((n_nodes, n_pods, config))

    def sizes(self) -> list:
        sizes = {(int(r["n_nodes"]), int(r["n_pods"])) for r in self.rows}
        return sorted(sizes, key=lambda size: (size[1], size[0]))

    def configs(self) -> list:
        return list(dict.fromkeys(row["config"] for row in self.rows))
