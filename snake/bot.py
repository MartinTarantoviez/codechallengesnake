"""
SnakeBot: the facade run.py (or tests) actually talks to. Owns the
per-game "previous head" history that BodyOrderer needs (see
ordering.py's module docstring for why that history is required for a
correct, non-guessed neck/tail order), the per-game multiplier and
invincibility state (turn_data only gives us multiplier_1/multiplier_2
and invincible_1/invincible_2 by player *label*, not by side, so the
bot tracks them keyed by game_id + side -- see _read_multipliers/
_read_invincible), and the per-game `SnakeStrategy` instance itself --
reused turn to turn (not rebuilt) so its `PickupPlanner` can remember
which pickup it was last headed for (see pickup_rush.py's
`last_target`).
"""

from .board import Board
from .game_state import GameState
from .strategy import SnakeStrategy


class SnakeBot:
    def __init__(self):
        self._prev_heads = {}       # game_id -> {'A': pos, 'B': pos}
        self._multipliers = {}      # game_id -> {'A': int, 'B': int}
        self._invincible = {}       # game_id -> {'A': int, 'B': int}
        self._strategies = {}       # game_id -> SnakeStrategy

    def forget_game(self, game_id):
        self._prev_heads.pop(game_id, None)
        self._multipliers.pop(game_id, None)
        self._invincible.pop(game_id, None)
        self._strategies.pop(game_id, None)

    def _strategy_for(self, game_id, side, opp_side):
        strategy = self._strategies.get(game_id)
        if strategy is None:
            strategy = SnakeStrategy(side, opp_side)
            self._strategies[game_id] = strategy
        return strategy

    def choose_move(self, turn_data):
        """turn_data: the 'data' payload of a 'your_turn' event. Returns
        (action, direction) -- action is 'move' or 'shoot' (v9), both
        carrying a direction string ('up'/'down'/'left'/'right')."""
        game_id = turn_data['game_id']
        side = turn_data['side']  # 'A' or 'B'
        opp_side = 'B' if side == 'A' else 'A'
        rows, cols = turn_data['rows'], turn_data['cols']

        invincible = self._read_invincible(turn_data, game_id)
        inverted_sides = {s for s, left in invincible.items() if left > 0}
        board = Board.from_turn(turn_data['board'], rows, cols, inverted_sides)

        if side not in board.heads:
            # Shouldn't happen mid-game, but never crash on a bad frame.
            return 'move', 'up'

        multipliers = self._read_multipliers(turn_data, game_id)
        state = GameState.from_board(
            board,
            prev_heads=self._prev_heads.get(game_id),
            multipliers=multipliers,
            remaining_moves=turn_data.get('remaining_moves'),
            invincible=invincible,
        )

        strategy = self._strategy_for(game_id, side, opp_side)
        my_score = self._read_my_score(turn_data, side)
        action, direction = strategy.choose_action(state, my_score)

        self._prev_heads[game_id] = dict(board.heads)
        return action, direction

    def _read_my_score(self, turn_data, side):
        # Same player_1==side 'A' convention as multipliers/invincible
        # below -- turn_data always carries the real, current score, so
        # there's no need to track our own running total separately.
        score_1 = turn_data.get('score_1')
        score_2 = turn_data.get('score_2')
        score = score_1 if side == 'A' else score_2
        return score if score is not None else 0

    def _read_multipliers(self, turn_data, game_id):
        # turn_data (from v4 on) gives multiplier_1/multiplier_2 keyed to
        # player_1/player_2 labels, not to 'A'/'B' sides directly. We map
        # them once per game using player_1 == side 'A' by convention
        # (matches the example log in the rules doc) and cache the result
        # so a mid-match KeyError never breaks an older-format game.
        m1 = turn_data.get('multiplier_1')
        m2 = turn_data.get('multiplier_2')
        if m1 is None and m2 is None:
            return self._multipliers.get(game_id, {'A': 1, 'B': 1})
        current = {'A': m1 if m1 is not None else 1,
                   'B': m2 if m2 is not None else 1}
        self._multipliers[game_id] = current
        return current

    def _read_invincible(self, turn_data, game_id):
        # Same player_1==side 'A' convention as multipliers (v10's
        # invincible_1/invincible_2).
        i1 = turn_data.get('invincible_1')
        i2 = turn_data.get('invincible_2')
        if i1 is None and i2 is None:
            return self._invincible.get(game_id, {'A': 0, 'B': 0})
        current = {'A': i1 if i1 is not None else 0,
                   'B': i2 if i2 is not None else 0}
        self._invincible[game_id] = current
        return current
