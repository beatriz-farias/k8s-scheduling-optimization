"""Estado de ocupação do cluster: onde cada pod roda e quanto cada nó consome."""

from contextlib import contextmanager

from instance_generator import Instance


class ClusterState:
    def __init__(self, instance: Instance, allocation: dict, used: list):
        self.instance = instance
        self.allocation = allocation
        self.used = used

    @classmethod
    def empty(cls, instance: Instance):
        return cls(instance, {}, [0.0] * instance.n_nodes)

    @classmethod
    def carry_over(cls, previous: "ClusterState", active_pods: list):
        """Pods que continuam ativos mantêm o nó; os que saíram são descartados."""
        active = set(active_pods)
        kept = {pod: node for pod, node in previous.allocation.items() if pod in active}
        state = cls.empty(previous.instance)
        for pod, node in kept.items():
            state.place(pod, node)
        return state

    def copy(self) -> "ClusterState":
        return ClusterState(self.instance, dict(self.allocation), list(self.used))

    def __contains__(self, pod: int) -> bool:
        return pod in self.allocation

    def __len__(self) -> int:
        return len(self.allocation)

    def pods(self) -> list:
        return list(self.allocation)

    def node_of(self, pod: int) -> int:
        return self.allocation[pod]

    def open_nodes_count(self) -> int:
        return len(set(self.allocation.values()))

    def fits(self, pod: int, node: int) -> bool:
        return self.used[node] + self.instance.pod_demand[pod] <= self.instance.capacity[node]

    def feasible_nodes(self, pod: int) -> list:
        return [node for node in range(self.instance.n_nodes) if self.fits(pod, node)]

    def place(self, pod: int, node: int):
        self.allocation[pod] = node
        self.used[node] += self.instance.pod_demand[pod]

    def evict(self, pod: int):
        node = self.allocation.pop(pod)
        self.used[node] -= self.instance.pod_demand[pod]

    def relocate(self, pod: int, destination: int):
        demand = self.instance.pod_demand[pod]
        self.used[self.allocation[pod]] -= demand
        self.used[destination] += demand
        self.allocation[pod] = destination

    @contextmanager
    def freed(self, pod: int):
        """Libera temporariamente a capacidade do pod (para prever onde o
        Scheduler o recolocaria) sem tirá-lo da alocação."""
        node = self.allocation[pod]
        demand = self.instance.pod_demand[pod]
        self.used[node] -= demand
        try:
            yield
        finally:
            self.used[node] += demand

    def migrations_from(self, previous: "ClusterState") -> int:
        return sum(1 for pod, node in self.allocation.items()
                   if pod in previous and previous.node_of(pod) != node)
