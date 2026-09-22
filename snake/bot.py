"""
SnakeBot: the facade run.py (or tests) actually talks to. Owns the
per-game "previous head" history that BodyOrderer needs (see
ordering.py's module docstring for why that history is required for a
correct, non-guessed neck/tail order), and the per-game multiplier
state (turn_data only gives us multiplier_1/multiplier_2 by player
*label*, not by side, so the bot tracks it keyed by game_id + side).
"""

from .board import Board
from .game_state import GameState
from .strategy import SnakeStrategy


class SnakeBot:
    def __init__(self):
        self._prev_heads = {}       # game_id -> {'A': pos, 'B': pos}
        self._multipliers = {}      # game_id -> {'A': int, 'B': int}

    def forget_game(self, game_id):
        self._prev_heads.pop(game_id, None)
        self._multipliers.pop(game_id, None)

    def choose_move(self, turn_data):
        """turn_data: the 'data' payload of a 'your_turn' event. Returns
        a direction string ('up'/'down'/'left'/'right')."""
        game_id = turn_data['game_id']
        side = turn_data['side']  # 'A' or 'B'
        opp_side = 'B' if side == 'A' else 'A'
        rows, cols = turn_data['rows'], turn_data['cols']

        board = Board.from_turn(turn_data['board'], rows, cols)

        if side not in board.heads:
            # Shouldn't happen mid-game, but never crash on a bad frame.
            return 'up'

        multipliers = self._read_multipliers(turn_data, game_id)
        state = GameState.from_board(
            board,
            prev_heads=self._prev_heads.get(game_id),
            multipliers=multipliers,
            remaining_moves=turn_data.get('remaining_moves'),
        )

        strategy = SnakeStrategy(side, opp_side)
        direction = strategy.choose_direction(state)

        self._prev_heads[game_id] = dict(board.heads)
        return direction

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
