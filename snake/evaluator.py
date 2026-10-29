"""
Evaluator: heuristic score for one GameState from one side's
perspective. Combines territory control, the reachable/winnable target
digit (plus shot food and the star, same economics, v9/v10), reachable
pickups, length, and an exit-count safety penalty.

v10: all of the defensive terms (exit safety, bomb proximity) are
skipped while `self.me` is invincible in the evaluated state -- none
of what they're steering away from costs anything in that state (see
GameState's invincible-branch rewards), so penalizing it would just be
wrong, not merely redundant.

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
from .game_state import BIG_BOMB_RADIUS, SMALL_BOMB_RADIUS

_ENDGAME_REMAINING_MOVES = 50
_LENGTH_WEIGHT = 6.0
_MULTIPLIER_EDGE_BASE = 8.0
_MULTIPLIER_EDGE_HORIZON = 150.0
_EXIT_PENALTY_ONE = -25.0
_EXIT_PENALTY_TWO = -8.0
# v8: a bomb going off is a flat -500 (see EXPLOSION_PENALTY in
# game_state.py) which the search's own reward already strongly avoids
# for the immediate move; this is a smaller nudge so the *evaluated*
# position (after both plies) also prefers to end up clear of a blast
# square, not just the single step we're choosing right now.
_BOMB_PROXIMITY_PENALTY = -40.0

# The target-digit/tail-food pull terms scale with the multiplier (a
# high multiplier really does make that food worth more), but
# uncapped that scaling can run away: a real match had multiplier x8
# make a single distant digit's pull (~610 after weighting) dwarf even
# CRASH_PENALTY (-500, see game_state.py), so the search happily
# crashed into the opponent's head -- wiping a 44,000+ point lead to 0
# under the v7 first-crash rule -- just because the post-crash
# body-shedding incidentally shortened the BFS path to that digit.
# Capping the multiplier used *only* in these pull terms (never in the
# real reward computed in game_state.py, which must keep scaling with
# the true multiplier) keeps the heuristic nudge from ever being able
# to outweigh a guaranteed, severe penalty like a crash.
_PULL_MULTIPLIER_CAP = 2.0

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
    value = (target_digit or 1) * 100.0 * min(my_mult, _PULL_MULTIPLIER_CAP)
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
    value = 100.0 * min(my_mult, _PULL_MULTIPLIER_CAP)
    return value / (1.0 + decay * d_me) / 100.0


def _shot_food_term(state, dist_me, dist_opp, my_mult, decay):
    # v9: shot food (and v10's star, same economics) scores like a
    # correct digit=1 and is up for grabs by either side -- without
    # this pull, a shot's real upside (the free food it creates) is
    # invisible to the search that decides whether to take it.
    d_me = _closest_winnable(state.shot_food, dist_me, dist_opp)
    if d_me is None:
        return 0.0
    value = 100.0 * min(my_mult, _PULL_MULTIPLIER_CAP)
    return value / (1.0 + decay * d_me) / 100.0


def _star_term(state, dist_me, dist_opp, my_mult, decay):
    d_me = _closest_winnable(state.stars, dist_me, dist_opp)
    if d_me is None:
        return 0.0
    value = 100.0 * min(my_mult, _PULL_MULTIPLIER_CAP)
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


def _chebyshev(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _bomb_penalty(head, big_bombs, small_bombs):
    if any(_chebyshev(head, b) <= BIG_BOMB_RADIUS for b in big_bombs):
        return _BOMB_PROXIMITY_PENALTY
    if any(_chebyshev(head, b) <= SMALL_BOMB_RADIUS for b in small_bombs):
        return _BOMB_PROXIMITY_PENALTY
    return 0.0


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
        invincible_me = state.invincible.get(self.me, 0) > 0

        score = (my_t - opp_t) * territory_w
        score += _target_term(state, target_digit, dist_me, dist_opp,
                               my_mult, decay) * target_w
        score += _tail_food_term(state, self.me, dist_me, dist_opp,
                                  my_mult, decay) * target_w
        score += _shot_food_term(state, dist_me, dist_opp, my_mult, decay) * target_w
        score += _star_term(state, dist_me, dist_opp, my_mult, decay) * target_w
        score += _pickup_term(state.pickups, dist_me, dist_opp, decay) * pickup_w
        score += self._multiplier_edge_term(state)
        score += (len(my_body) - len(opp_body)) * _LENGTH_WEIGHT
        if not invincible_me:
            # v10: a wrong-digit-style trap or a bomb's blast square
            # costs nothing while invincible, so there's nothing here
            # to steer away from.
            score += _exit_penalty(my_head, walls, state.rows, state.cols)
            score += _bomb_penalty(my_head, state.big_bombs, state.small_bombs)
        return score
