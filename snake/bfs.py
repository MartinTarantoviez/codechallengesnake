"""
Generic BFS distance / territory utilities shared by the evaluator, the
pickup-rush planner and anything else that needs "shortest safe path
avoiding these cells" on the board.
"""

from collections import deque

from .board import neighbors4
from .ordering import tail_of


def in_bounds(pos, rows, cols):
    r, c = pos
    return 0 <= r < rows and 0 <= c < cols


def _bfs_step(nxt, dist, obstacles, rows, cols, d):
    if not in_bounds(nxt, rows, cols) or nxt in dist or nxt in obstacles:
        return None
    return d + 1


def bfs_distances(start, obstacles, rows, cols):
    """Multi-target BFS distance map from `start`, avoiding `obstacles`."""
    dist = {start: 0}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        d = dist[cur]
        for nxt in neighbors4(cur):
            new_d = _bfs_step(nxt, dist, obstacles, rows, cols, d)
            if new_d is not None:
                dist[nxt] = new_d
                queue.append(nxt)
    return dist


def _closer(d, other):
    return other is None or d < other


def _count_closer(dist_a, dist_b):
    return sum(1 for cell, d in dist_a.items() if _closer(d, dist_b.get(cell)))


def voronoi_territory(my_head, opp_head, walls, rows, cols):
    """Simultaneous BFS from both heads: a cell belongs to whoever
    reaches it first; ties belong to neither."""
    dist_me = bfs_distances(my_head, walls, rows, cols)
    dist_opp = bfs_distances(opp_head, walls, rows, cols) if opp_head else {}
    my_territory = _count_closer(dist_me, dist_opp)
    opp_territory = _count_closer(dist_opp, dist_me)
    return my_territory, opp_territory, dist_me, dist_opp


def walls_for(my_body, opp_body):
    """Solid cells for BFS purposes: both bodies, minus each snake's own
    tail (which vacates on a non-growing move)."""
    walls = set(my_body) | set(opp_body)
    walls.discard(tail_of(my_body))
    walls.discard(tail_of(opp_body))
    walls.discard(None)
    return walls
