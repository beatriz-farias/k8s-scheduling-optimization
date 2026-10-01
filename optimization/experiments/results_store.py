"""Persistência dos resultados brutos em CSV (formato longo)."""

import csv
import os
import time

from . import settings

SAVE_ATTEMPTS = 10


class ResultsStore:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> list:
        if not os.path.exists(self.path):
            return []
        with open(self.path, newline="") as file:
            return list(csv.DictReader(file))

    def save(self, rows: list):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        for attempt in range(SAVE_ATTEMPTS):
            if self._try_write(rows, last_attempt=attempt == SAVE_ATTEMPTS - 1):
                return

    def _try_write(self, rows: list, last_attempt: bool) -> bool:
        """O OneDrive pode bloquear o arquivo por instantes durante a sincronização."""
        try:
            self._write(rows)
        except PermissionError:
            if last_attempt:
                raise
            time.sleep(1)
            return False
        return True

    def _write(self, rows: list):
        with open(self.path, "w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=settings.FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)

    def with_suffix(self, suffix: str) -> "ResultsStore":
        return ResultsStore(self.path.replace(".csv", f"{suffix}.csv"))
