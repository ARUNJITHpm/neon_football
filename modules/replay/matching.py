"""Maximum-cardinality, minimum-total-time one-to-one matching with stable ties."""
import math


def match(labels, predictions, tolerance, eligible=lambda prediction: True, compatible=None):
    labels = sorted(labels, key=lambda l: l.label_id)
    predictions = sorted(predictions, key=lambda p: p.event_id)
    source, sink = len(labels) + len(predictions), len(labels) + len(predictions) + 1
    graph = [[] for _ in range(sink + 1)]
    edges = []

    def add(a, b, cost):
        forward = [b, len(graph[b]), 1, cost]
        backward = [a, len(graph[a]), 0, -cost]
        graph[a].append(forward)
        graph[b].append(backward)
        return forward

    for i, label in enumerate(labels):
        add(source, i, 0)
        for j, prediction in enumerate(predictions):
            error = abs(label.crossing_seconds - prediction.occurred_seconds)
            same_incident = (compatible(label, prediction) if compatible else
                label.match_id == prediction.match_id and label.goal_end == prediction.goal_end and label.team == prediction.team)
            if eligible(prediction) and same_incident and error <= tolerance:
                edge = add(i, len(labels) + j, round(error * 1_000_000))
                edges.append((i, j, edge))
    for j in range(len(predictions)):
        add(len(labels) + j, sink, 0)
    while True:
        distance, parent = [math.inf] * len(graph), [None] * len(graph)
        distance[source] = 0
        # Residual reverse edges can have negative costs; Bellman-Ford supports reassignment.
        for _ in range(len(graph) - 1):
            changed = False
            for a, adjacent in enumerate(graph):
                if not math.isfinite(distance[a]):
                    continue
                for index, (b, reverse, capacity, cost) in enumerate(adjacent):
                    if capacity and distance[a] + cost < distance[b]:
                        distance[b] = distance[a] + cost
                        parent[b] = (a, index)
                        changed = True
            if not changed:
                break
        if parent[sink] is None:
            break
        node = sink
        while node != source:
            a, index = parent[node]
            edge = graph[a][index]
            edge[2] -= 1
            graph[node][edge[1]][2] += 1
            node = a
    return [(labels[i], predictions[j]) for i, j, edge in edges if edge[2] == 0]
