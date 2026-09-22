"""
PickupPlanner: commits to an actual shortest-path route toward the best
reachable X pickup, instead of only nudging Evaluator's distance-decayed
heuristic term (which only ever votes on the single next step, so a far
pickup's pull gets diluted by everything else in the evaluation).

Recomputed fresh every turn (as GameState is immutable per turn), so it
naturally re-routes around anything that changes -- there's no stale
"committed plan" to go stale.

Safety: `SnakeStrategy` only takes the suggested direction if its own
2-ply score isn't more than PICKUP_RUSH_SAFETY_MARGIN worse than the
best move it found on its own, so a pickup that's only reachable by
running into a dead end never gets chosen over playing it safe.
"""

from .bfs import bfs_distances, walls_for

MIN_REMAINING_TO_RUSH = 50
SAFETY_MARGIN = 40.0


def _wrong_digit_cells(state):
    target_digit = state.target_digit()
    return {pos for pos, digit in state.food.items()
            if digit is not None and digit != target_digit}


def _race_distance(dist_me, dist_opp, pos):
    d_me = dist_me.get(pos)
    if d_me is None:
        return None
    d_opp = dist_opp.get(pos)
    if d_opp is not None and d_opp <= d_me:
        return None  # opponent ties or wins the race
    return d_me


def _best_target(pickups, dist_me, dist_opp, horizon):
    best_pos, best_score = None, float('-inf')
    for p in pickups:
        d_me = _race_distance(dist_me, dist_opp, p)
        if d_me is None:
            continue
        opportunity = horizon - d_me
        if opportunity <= 0:
            continue
        score = opportunity / (1.0 + d_me)
        if score > best_score:
            best_score, best_pos = score, p
    return best_pos


class PickupPlanner:
    def __init__(self, me, opp):
        self.me = me
        self.opp = opp

    def _eligible_for_rush(self, state):
        if state.remaining_moves is not None and state.remaining_moves < MIN_REMAINING_TO_RUSH:
            return False
        return bool(state.pickups)

    def _pickup_target(self, state):
        if not self._eligible_for_rush(state):
            return None
        my_head = state.heads.get(self.me)
        if my_head is None:
            return None
        opp_head = state.heads.get(self.opp)
        walls = walls_for(state.bodies.get(self.me.lower(), []),
                           state.bodies.get(self.opp.lower(), []), state.walls)
        dist_me = bfs_distances(my_head, walls, state.rows, state.cols)
        dist_opp = bfs_distances(opp_head, walls, state.rows, state.cols) if opp_head else {}
        horizon = state.remaining_moves if state.remaining_moves is not None else 200
        return _best_target(state.pickups, dist_me, dist_opp, horizon)

    def _step_toward(self, state, target, legal_moves):
        obstacles = walls_for(state.bodies.get(self.me.lower(), []),
                               state.bodies.get(self.opp.lower(), []), state.walls)
        obstacles = obstacles | _wrong_digit_cells(state)
        dist_from_target = bfs_distances(target, obstacles, state.rows, state.cols)

        best_dir, best_dist = None, None
        for d, new_state, _reward in legal_moves:
            d_to_target = dist_from_target.get(new_state.heads[self.me])
            if d_to_target is not None and (best_dist is None or d_to_target < best_dist):
                best_dist, best_dir = d_to_target, d
        return best_dir

    def suggest(self, state, legal_moves, scored_moves, best_score):
        """Returns a direction if a reachable pickup is worth committing
        to and its own 2-ply score isn't much worse than the best
        alternative, else None (meaning: don't override)."""
        target = self._pickup_target(state)
        if target is None:
            return None
        step_dir = self._step_toward(state, target, legal_moves)
        if step_dir is None:
            return None
        step_score = dict(scored_moves).get(step_dir)
        if step_score is None or step_score < best_score - SAFETY_MARGIN:
            return None
        return step_dir
