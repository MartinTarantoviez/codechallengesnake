"""
Body ordering (neck -> tail).

This is the piece that has to be exact: get it wrong and the bot thinks
an occupied cell is safe to enter.

A snake's neck is always exactly where its head was one turn ago --
that's unambiguous. BodyOrderer.order_all() uses each snake's previous
head (tracked turn to turn by the caller) to establish the true
neck->tail order without guessing. Only on turn 1 of a game (no
previous head yet) does it fall back to a single-frame heuristic, which
is ambiguous whenever a coiled snake has both its neck and its tail
adjacent to the head at once (see the regression test for the exact
shape that used to kill the bot: body {(6,6),(7,6),(7,7)}, head (6,7)).

_walk_path backtracks rather than greedily committing to the first
unvisited neighbor it finds: a tightly coiled body can bring two
*non-consecutive* segments next to each other, so the first neighbor
isn't always the real next segment. Picking it anyway used to dead-end
early and silently drop the rest of the body from every collision
check -- a real match (body of 22 cells coiled through a narrow
corridor) saw this resolve only 6 of 22 cells, after which the engine
no longer recognized several of the opponent's own body cells as solid
at all, and the bot walked straight into one of them turn after turn.
"""

from .board import neighbors4


def _unvisited_body_neighbors(cur, body_set, prev, visited):
    result = []
    for p in neighbors4(cur):
        if p not in body_set or p == prev or p in visited:
            continue
        result.append(p)
    return result


def _extend_path(path, visited, body_set, target_len, exclude):
    if len(path) == target_len:
        return True
    cur = path[-1]
    prev = path[-2] if len(path) > 1 else exclude
    for nxt in _unvisited_body_neighbors(cur, body_set, prev, visited):
        path.append(nxt)
        visited.add(nxt)
        if _extend_path(path, visited, body_set, target_len, exclude):
            return True
        path.pop()
        visited.discard(nxt)
    return False


def _walk_path(start, body_set, exclude):
    """The neck(or heuristic-start)->tail order, backtracking whenever a
    branch can't be extended to cover every cell in body_set. Returns
    the longest path found; a short result (compare against
    len(body_set)) means no full path exists from `start` at all."""
    path = [start]
    _extend_path(path, {start}, body_set, len(body_set), exclude)
    return path


def _degree_in_set(p, body_set):
    return sum(1 for n in neighbors4(p) if n in body_set)


def _is_endpoint(p, body_set):
    return _degree_in_set(p, body_set) <= 1


def _neck_candidates(head, body_set):
    return [p for p in neighbors4(head) if p in body_set and _is_endpoint(p, body_set)]


def _any_endpoint(body_set):
    for p in body_set:
        if _is_endpoint(p, body_set):
            return p
    return next(iter(body_set))


def order_body_heuristic(head, body_set):
    """Best-effort neck->tail ordering from a single frame, no history."""
    if not body_set:
        return []
    necks = _neck_candidates(head, body_set)
    neck = necks[0] if necks else _any_endpoint(body_set)
    return _walk_path(neck, body_set, exclude=head)


def order_body_from_neck(neck, body_set):
    """Exact ordering when the true neck is already known (unambiguous)."""
    if neck not in body_set:
        return []
    return _walk_path(neck, body_set, exclude=None)


def tail_of(ordered_body):
    return ordered_body[-1] if ordered_body else None


class BodyOrderer:
    @staticmethod
    def _has_usable_history(prev_head, body_set):
        return prev_head is not None and prev_head in body_set

    @classmethod
    def _order_one(cls, head, body_set, prev_head):
        if not body_set:
            return []
        if cls._has_usable_history(prev_head, body_set):
            ordered = order_body_from_neck(prev_head, body_set)
            if len(ordered) == len(body_set):
                return ordered
        return order_body_heuristic(head, body_set)

    @classmethod
    def order_all(cls, heads, bodies, prev_heads):
        """heads: {'A': pos, 'B': pos}; bodies: {'a': set, 'b': set};
        prev_heads: {'A': pos or None, 'B': pos or None}.
        Returns {'a': [ordered...], 'b': [ordered...]}."""
        prev_heads = prev_heads or {}
        new_bodies = {}
        for head_letter, head in heads.items():
            body_letter = head_letter.lower()
            body_set = bodies.get(body_letter, set())
            prev_head = prev_heads.get(head_letter)
            new_bodies[body_letter] = cls._order_one(head, body_set, prev_head)
        return new_bodies
