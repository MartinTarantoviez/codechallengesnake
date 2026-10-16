"""
SnakeStrategy: 2-ply search (my move -> opponent's best reply), scored
by the real reward each ply earns plus Evaluator's heuristic score of
the resulting position, with PickupPlanner able to override the choice
when a reachable pickup is worth committing to (see pickup_rush.py).

bfs.py / evaluator.py / pickup_rush.py hold the pieces this module
assembles; kept split up so each stays small and single-purpose.

A real match log showed the bot stuck circling the same 4 cells for
~50 turns despite the rest of the board being wide open: with no
winnable target digit and no close pickup, every evaluated score comes
out near-tied, and the search settles into a stable short cycle from
pure tie-breaking. Since `SnakeBot` now reuses one `SnakeStrategy` per
game (see bot.py), it can remember our own last few head positions and
nudge the score away from one that was just visited -- just enough to
break that kind of tie without affecting any move that's genuinely the
only reasonable one.
"""

from collections import deque

from .bfs import in_bounds
from .evaluator import Evaluator
from .game_state import DIRECTIONS
from .pickup_rush import PickupPlanner

# Re-exported for backwards compatibility (older tests/tools import
# these straight from strategy).
from .bfs import bfs_distances, voronoi_territory, walls_for as _walls_for  # noqa: F401

_RECENT_HEADS_REMEMBERED = 6
_REVISIT_PENALTY = -15.0


class SnakeStrategy:
    def __init__(self, me, opp):
        self.me = me
        self.opp = opp
        self.evaluator = Evaluator(me, opp)
        self.opp_evaluator = Evaluator(opp, me)
        self.pickup_planner = PickupPlanner(me, opp)
        self._recent_heads = deque(maxlen=_RECENT_HEADS_REMEMBERED)

    def _best_opponent_reply(self, state):
        opp_moves = state.legal_moves(self.opp, self.me)
        if not opp_moves:
            return None, 0.0  # we just trapped them
        return self._best_reply_among(opp_moves)

    def _best_reply_among(self, opp_moves):
        best_state, best_reward, best_score = None, 0.0, float('-inf')
        for _d, opp_state, opp_reward in opp_moves:
            score = opp_reward + self.opp_evaluator.evaluate(opp_state)
            if score > best_score:
                best_score, best_state, best_reward = score, opp_state, opp_reward
        return best_state, best_reward

    def _revisit_penalty(self, state_after_me):
        new_head = state_after_me.heads.get(self.me)
        return _REVISIT_PENALTY if new_head in self._recent_heads else 0.0

    def _score_my_move(self, state_after_me, my_reward):
        opp_state, _opp_reward = self._best_opponent_reply(state_after_me)
        if opp_state is None:
            return float('inf')
        return (my_reward + self.evaluator.evaluate(opp_state)
                + self._revisit_penalty(state_after_me))

    def _score_all(self, my_moves):
        return [(d, self._score_my_move(s, r)) for d, s, r in my_moves]

    def _best_of(self, scored_moves):
        best_dir, best_score = None, float('-inf')
        for d, score in scored_moves:
            if score > best_score:
                best_score, best_dir = score, d
        return best_dir, best_score

    def _fallback_direction(self, state):
        head = state.heads.get(self.me)
        if head is None:
            return 'up'
        return self._first_onboard_direction(head, state)

    def _first_onboard_direction(self, head, state):
        for d, (dr, dc) in DIRECTIONS.items():
            nb = (head[0] + dr, head[1] + dc)
            if state.in_bounds(nb):
                return d
        return 'up'

    def _record_head(self, direction, my_moves):
        for d, s, _r in my_moves:
            if d == direction:
                self._recent_heads.append(s.heads.get(self.me))
                return

    def choose_direction(self, state):
        my_moves = state.legal_moves(self.me, self.opp)
        if not my_moves:
            return self._fallback_direction(state)

        scored = self._score_all(my_moves)
        best_dir, best_score = self._best_of(scored)

        pickup_dir = self.pickup_planner.suggest(state, my_moves, scored, best_score)
        direction = pickup_dir or best_dir or my_moves[0][0]
        self._record_head(direction, my_moves)
        return direction
