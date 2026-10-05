"""
Evaluator: heuristic score for one GameState from one side's
perspective. Combines territory control, the reachable/winnable target
digit, reachable pickups, length, and an exit-count safety penalty.

Weight history: pickup weight used to sit far below the target-digit
weight (40/30 vs 90/80), which meant the bot only grabbed an X when it
was basically on the way to food anyway. Real matches showed 0-2
pickups collected per game vs 2-3 for an opponent who ended up with a
permanently higher multiplier and blew past us on a single high-value
digit. Since the multiplier is PERMANENT and multiplies every future
food score, it's worth actively detouring for -- but only when there
are enough turns left to cash it in, hence the endgame/midgame split
below. Actively *committing* to a distant pickup is PickupPlanner's
job (pickup_rush.py); this evaluator only supplies the passive pull
used by the 2-ply search's own scoring.
"""

from .bfs import in_bounds, voronoi_territory, walls_for
from .board import neighbors4

_ENDGAME_REMAINING_MOVES = 50
_LENGTH_WEIGHT = 6.0
_MULTIPLIER_EDGE_BASE = 8.0
_MULTIPLIER_EDGE_HORIZON = 150.0
_EXIT_PENALTY_ONE = -25.0
_EXIT_PENALTY_TWO = -8.0

# (target_digit_weight, pickup_weight, territory_weight, distance_decay)
_MIDGAME_WEIGHTS = (70.0, 65.0, 0.25, 0.25)
_ENDGAME_WEIGHTS = (90.0, 12.0, 0.25, 0.25)


def _is_endgame(remaining_moves):
    return remaining_moves is not None and remaining_moves < _ENDGAME_REMAINING_MOVES


def _target_positions(state, target_digit):
    # v6: several copies of the target digit can be on the board at
    # once, so chase whichever copy is actually closest/winnable, not
    # just the first one a dict scan happens to find.
    return [pos for pos, dig in state.food.items() if dig == target_digit]


def _wins_the_race(dist_me, dist_opp, pos):
    d_me = dist_me.get(pos)
    if d_me is None:
        return None
    d_opp = dist_opp.get(pos)
    if d_opp is not None and d_opp < d_me:
        return None
    return d_me


def _closest_winnable(positions, dist_me, dist_opp):
    best_d = None
    for pos in positions:
        d_me = _wins_the_race(dist_me, dist_opp, pos)
        if d_me is not None and (best_d is None or d_me < best_d):
            best_d = d_me
    return best_d


def _target_term(state, target_digit, dist_me, dist_opp, my_mult, decay):
    d_me = _closest_winnable(_target_positions(state, target_digit), dist_me, dist_opp)
    if d_me is None:
        return 0.0
    value = (target_digit or 1) * 100.0 * my_mult
    return value / (1.0 + decay * d_me) / 100.0  # normalized like the old food term


def _my_tail_food(state, me):
    return [pos for pos, owner in state.tail_food.items() if owner == me]


def _tail_food_term(state, me, dist_me, dist_opp, my_mult, decay):
    # Eating your own tail food is worth +100*multiplier and grows you,
    # same economics as a correct digit=1 -- reuse the target-digit
    # weight rather than tuning a whole separate one for it.
    d_me = _closest_winnable(_my_tail_food(state, me), dist_me, dist_opp)
    if d_me is None:
        return 0.0
    value = 100.0 * my_mult
    return value / (1.0 + decay * d_me) / 100.0


def _pickup_term(pickups, dist_me, dist_opp, decay):
    total = 0.0
    for p in pickups:
        d_me = _wins_the_race(dist_me, dist_opp, p)
        if d_me is not None:
            total += 1.0 / (1.0 + decay * d_me)
    return total


def _multiplier_edge_weight(remaining_moves):
    if remaining_moves is None:
        return _MULTIPLIER_EDGE_BASE
    return _MULTIPLIER_EDGE_BASE * min(1.0, remaining_moves / _MULTIPLIER_EDGE_HORIZON)


def _count_open_exits(head, walls, rows, cols):
    return sum(1 for n in neighbors4(head) if in_bounds(n, rows, cols) and n not in walls)


_EXIT_PENALTIES = {0: _EXIT_PENALTY_ONE, 1: _EXIT_PENALTY_ONE, 2: _EXIT_PENALTY_TWO}


def _exit_penalty(head, walls, rows, cols):
    exits = _count_open_exits(head, walls, rows, cols)
    return _EXIT_PENALTIES.get(exits, 0.0)


class Evaluator:
    """Heuristic evaluation of a GameState from one side's perspective."""

    def __init__(self, me, opp):
        self.me = me    # 'A' or 'B'
        self.opp = opp

    def _weights(self, remaining_moves):
        return _ENDGAME_WEIGHTS if _is_endgame(remaining_moves) else _MIDGAME_WEIGHTS

    def _multiplier_edge_term(self, state):
        my_mult = state.multipliers.get(self.me, 1)
        opp_mult = state.multipliers.get(self.opp, 1)
        weight = _multiplier_edge_weight(state.remaining_moves)
        return (my_mult - opp_mult) * weight

    def _territory_and_distances(self, state, my_head, opp_head):
        my_body = state.bodies.get(self.me.lower(), [])
        opp_body = state.bodies.get(self.opp.lower(), [])
        walls = walls_for(my_body, opp_body, state.walls)
        my_t, opp_t, dist_me, dist_opp = voronoi_territory(
            my_head, opp_head, walls, state.rows, state.cols
        )
        return my_body, opp_body, walls, my_t, opp_t, dist_me, dist_opp

    def evaluate(self, state):
        my_head = state.heads.get(self.me)
        opp_head = state.heads.get(self.opp)
        if my_head is None:
            return float('-inf')
        if opp_head is None:
            return float('inf')

        my_body, opp_body, walls, my_t, opp_t, dist_me, dist_opp = (
            self._territory_and_distances(state, my_head, opp_head)
        )
        target_w, pickup_w, territory_w, decay = self._weights(state.remaining_moves)
        target_digit = state.target_digit()
        my_mult = state.multipliers.get(self.me, 1)

        score = (my_t - opp_t) * territory_w
        score += _target_term(state, target_digit, dist_me, dist_opp,
                               my_mult, decay) * target_w
        score += _tail_food_term(state, self.me, dist_me, dist_opp,
                                  my_mult, decay) * target_w
        score += _pickup_term(state.pickups, dist_me, dist_opp, decay) * pickup_w
        score += self._multiplier_edge_term(state)
        score += (len(my_body) - len(opp_body)) * _LENGTH_WEIGHT
        score += _exit_penalty(my_head, walls, state.rows, state.cols)
        return score
