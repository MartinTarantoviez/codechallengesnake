"""
GameState: one turn's board with bodies already ordered (neck->tail),
plus move simulation used by the lookahead search.

Scoring assumptions encoded here (from the rules PDF):
  - Correct next digit: grows the snake, scores digit*100*multiplier.
  - Wrong digit: does NOT end the game (-500 penalty only). ASSUMPTION,
    not spelled out in the rules doc: we treat it as NOT growing the
    snake (only "penalty" is mentioned, unlike the correct case which
    explicitly says "grow"). Flagged in README as worth confirming
    against a real v3 match log once one is available.
  - X pickup: scores flat +50, bumps the multiplier by one step, does
    NOT grow the snake (explicitly stated in the rules).
  - Multiplier applies only to food points, never to the +50, the +1
    per move, or the -500 penalty.
  - '#' wall: running into one is a -500 penalty and the snake does not
    move at all that turn (not fatal, unlike every other collision --
    see board.py's module docstring for the full v5 rule).

DIRECTIONS / in_bounds / neighbors4 live in board.py; this module only
adds the *dynamic* (turn-to-turn) pieces: ordering, simulation, reward.
"""

from .digits import next_target_digit
from .ordering import BodyOrderer, tail_of

DIRECTIONS = {
    'up': (-1, 0),
    'down': (1, 0),
    'left': (0, -1),
    'right': (0, 1),
}

WRONG_DIGIT_PENALTY = -500.0
WALL_PENALTY = -500.0
PICKUP_SCORE = 50.0
CORRECT_DIGIT_UNIT = 100.0


def _step(head, direction):
    dr, dc = DIRECTIONS[direction]
    return head[0] + dr, head[1] + dc


def _is_fatal(new_head, solid, grows, tail):
    if new_head not in solid:
        return False
    return not (grows and new_head == tail)


def _advance_body(head, my_body, grows):
    if grows:
        return [head] + list(my_body)  # old head becomes the new neck
    if my_body:
        return [head] + list(my_body[:-1])  # shift, dropping the old tail
    return []  # zero-length snake with no growth stays that way


def _food_landing(digit, target_digit):
    """digit is the food digit at the landed-on cell (or None for
    legacy '*'). Returns (is_correct, is_wrong, reward)."""
    if digit is None or digit == target_digit:
        reward_digit = digit if digit is not None else 1
        return True, False, reward_digit * CORRECT_DIGIT_UNIT
    return False, True, WRONG_DIGIT_PENALTY


class GameState:
    """
    heads: {'A': pos, 'B': pos}
    bodies: {'a': [ordered neck..tail], 'b': [...]}
    food: {(r,c): digit_or_None}
    pickups: [(r,c), ...]
    walls: {(r,c), ...}  -- the current '#' hazard, if any
    multipliers: {'A': int, 'B': int}  -- starts at 1 each
    """

    def __init__(self, rows, cols, heads, bodies, food, pickups,
                 multipliers=None, remaining_moves=None, walls=None):
        self.rows = rows
        self.cols = cols
        self.heads = heads
        self.bodies = bodies
        self.food = food
        self.pickups = pickups
        self.multipliers = multipliers or {'A': 1, 'B': 1}
        self.remaining_moves = remaining_moves
        self.walls = walls if walls is not None else frozenset()

    @classmethod
    def from_board(cls, board, prev_heads=None, multipliers=None,
                    remaining_moves=None):
        ordered_bodies = BodyOrderer.order_all(board.heads, board.bodies, prev_heads)
        return cls(board.rows, board.cols, dict(board.heads), ordered_bodies,
                    dict(board.food), list(board.pickups),
                    multipliers, remaining_moves, set(board.walls))

    def in_bounds(self, pos):
        r, c = pos
        return 0 <= r < self.rows and 0 <= c < self.cols

    def target_digit(self):
        digits_present = {d for d in self.food.values() if d is not None}
        return next_target_digit(digits_present)

    # -- move simulation ----------------------------------------------

    def _solid_cells(self, my_body, other_body, other_head, tail):
        solid = set(my_body) | set(other_body)
        if other_head is not None:
            solid.add(other_head)
        if tail is not None:
            solid.discard(tail)  # our own tail vacates unless we grow into it
        return solid

    def _classify_landing(self, new_head, target_digit):
        """Returns (is_food_correct, is_food_wrong, is_pickup, reward)."""
        if new_head in self.pickups:
            return False, False, True, PICKUP_SCORE
        if new_head not in self.food:
            return False, False, False, 0.0
        is_correct, is_wrong, reward = _food_landing(self.food[new_head], target_digit)
        return is_correct, is_wrong, False, reward

    def _apply_landing(self, new_head, is_correct, is_wrong, is_pickup):
        new_food = dict(self.food)
        if is_correct or is_wrong:
            new_food.pop(new_head, None)
        new_pickups = list(self.pickups)
        if is_pickup:
            new_pickups.remove(new_head)
        return new_food, new_pickups

    def _apply_multiplier(self, head_letter, is_pickup):
        new_multipliers = dict(self.multipliers)
        if is_pickup:
            new_multipliers[head_letter] = new_multipliers.get(head_letter, 1) + 1
        return new_multipliers

    def _reward_for(self, is_correct, raw_reward, mult):
        return raw_reward * mult if is_correct else raw_reward

    def simulate(self, head_letter, other_letter, direction, my_multiplier=None):
        """Advance `head_letter`'s snake one `direction`. Returns
        (new_state, reward) where reward is the real-scoring points
        this single move earns (already multiplier-adjusted for food),
        or (None, 0.0) if the move is immediately fatal.

        Running into a '#' wall is neither: it's a flat penalty and the
        whole snake stays exactly where it was, so the unchanged state
        (self) is returned rather than a new one.
        """
        head = self.heads.get(head_letter)
        if head is None:
            return None, 0.0
        new_head = _step(head, direction)
        if not self.in_bounds(new_head):
            return None, 0.0
        if new_head in self.walls:
            return self, WALL_PENALTY
        return self._advance(head_letter, other_letter, head, new_head, my_multiplier)

    def _advance(self, head_letter, other_letter, head, new_head, my_multiplier):
        body_letter = head_letter.lower()
        my_body = self.bodies.get(body_letter, [])
        other_body = self.bodies.get(other_letter.lower(), [])
        other_head = self.heads.get(other_letter)
        tail = tail_of(my_body)
        solid = self._solid_cells(my_body, other_body, other_head, tail)

        is_correct, is_wrong, is_pickup, raw_reward = self._classify_landing(
            new_head, self.target_digit()
        )
        if _is_fatal(new_head, solid, is_correct, tail):
            return None, 0.0

        mult = my_multiplier if my_multiplier is not None else self.multipliers.get(head_letter, 1)
        reward = self._reward_for(is_correct, raw_reward, mult)

        new_bodies = dict(self.bodies)
        new_bodies[body_letter] = _advance_body(head, my_body, is_correct)
        new_food, new_pickups = self._apply_landing(new_head, is_correct, is_wrong, is_pickup)
        new_multipliers = self._apply_multiplier(head_letter, is_pickup)
        new_heads = dict(self.heads)
        new_heads[head_letter] = new_head

        new_state = GameState(
            self.rows, self.cols, new_heads, new_bodies, new_food,
            new_pickups, new_multipliers, self.remaining_moves, self.walls,
        )
        return new_state, reward

    def legal_moves(self, head_letter, other_letter):
        """[(direction, new_state, reward), ...] for every survivable move."""
        out = []
        for d in DIRECTIONS:
            new_state, reward = self.simulate(head_letter, other_letter, d)
            if new_state is not None:
                out.append((d, new_state, reward))
        return out
