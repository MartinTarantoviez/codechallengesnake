"""
GameState: one turn's board with bodies already ordered (neck->tail),
plus move simulation used by the lookahead search.

Scoring assumptions encoded here (from the rules PDF):
  - Correct next digit: grows the snake, scores digit*100*multiplier.
    Since v6 (30 Sep 2026) each digit has several copies on the board at
    once; eating the target consumes every copy of that digit at once
    (only the landed-on copy scores/grows), not just the one cell.
  - Wrong digit: does NOT end the game (-500 penalty only, only that one
    copy is consumed). ASSUMPTION, not spelled out in the rules doc: we
    treat it as NOT growing the snake (only "penalty" is mentioned,
    unlike the correct case which explicitly says "grow"). Flagged in
    README as worth confirming against a real v3 match log once one is
    available.
  - X pickup: scores flat +50, bumps the multiplier by one step, does
    NOT grow the snake (explicitly stated in the rules).
  - Tail food (v7, 7 Oct 2026): dropped by a crash (see below), marked
    with the letter of the side allowed to eat it. Eating your own (the
    side named on it) scores +100*multiplier and grows you, same as a
    correct digit. Landing on the *other* side's tail food (i.e. your
    own shed tail, since a crash always marks tail food for the
    opponent) just clears the cell -- no points, no growth, a plain
    survive-the-move +1.
  - Multiplier applies only to food points and tail food, never to the
    +50, the +1 per move, or the -500 penalty.
  - Crashes (v7, 7 Oct 2026): running into a '#' wall, your own body,
    the board edge, or the opponent no longer ends the game. The snake
    stays exactly where it was that turn, sheds its body down to the
    head + 2 cells (a snake of <=3 cells loses nothing), and the shed
    cells become tail food for the *opponent*. We don't track real
    cumulative score here, so -- unlike the live rules, which wipe your
    score to 0 on your first crash of the match and only charge -500 on
    later ones -- every crash is simplified to a flat -500 reward; see
    CRASH_PENALTY below and the README for the full rule.
  - Bombs (v8, 14 Oct 2026): not a crash at all -- the move happens
    completely normally (you eat whatever's on the landed cell, keep
    your tail), it's just that landing within Chebyshev distance 2 of
    a big bomb or 1 of a small one also sets it off. Same simplified
    flat penalty as a crash (see EXPLOSION_PENALTY), applied *in place
    of* that move's normal reward, not in addition to it.

DIRECTIONS / in_bounds / neighbors4 live in board.py; this module only
adds the *dynamic* (turn-to-turn) pieces: ordering, simulation, reward.
"""

from collections import namedtuple

from .digits import next_target_digit
from .ordering import BodyOrderer, tail_of

DIRECTIONS = {
    'up': (-1, 0),
    'down': (1, 0),
    'left': (0, -1),
    'right': (0, 1),
}

WRONG_DIGIT_PENALTY = -500.0
CRASH_PENALTY = -500.0
EXPLOSION_PENALTY = -500.0
PICKUP_SCORE = 50.0
CORRECT_DIGIT_UNIT = 100.0
TAIL_FOOD_UNIT = 100.0
CRASH_KEPT_BODY = 2  # body segments kept beyond the head after a crash
BIG_BOMB_RADIUS = 2    # Chebyshev distance -- a 5x5 blast square
SMALL_BOMB_RADIUS = 1  # Chebyshev distance -- a 3x3 blast square


def _chebyshev(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

# is_correct / is_wrong: landed on the right/wrong digit.
# is_pickup: landed on an 'X'. is_tail_food_mine: landed on tail food you
# may eat (grows + scores). is_tail_food_deny: landed on tail food only
# the opponent may eat (your own shed tail) -- clears it, no effect.
Landing = namedtuple('Landing', 'is_correct is_wrong is_pickup '
                                 'is_tail_food_mine is_tail_food_deny reward')
_NOTHING = Landing(False, False, False, False, False, 0.0)


def _step(head, direction):
    dr, dc = DIRECTIONS[direction]
    return head[0] + dr, head[1] + dc


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
    tail_food: {(r,c): 'A'|'B'}  -- who may eat it, dropped by a crash
    big_bombs / small_bombs: [(r,c), ...]  -- 5x5 / 3x3 blast squares (v8)
    multipliers: {'A': int, 'B': int}  -- starts at 1 each
    """

    def __init__(self, rows, cols, heads, bodies, food, pickups,
                 multipliers=None, remaining_moves=None, walls=None,
                 tail_food=None, big_bombs=(), small_bombs=()):
        self.rows = rows
        self.cols = cols
        self.heads = heads
        self.bodies = bodies
        self.food = food
        self.pickups = pickups
        self.multipliers = multipliers or {'A': 1, 'B': 1}
        self.remaining_moves = remaining_moves
        self.walls = walls if walls is not None else frozenset()
        self.tail_food = tail_food if tail_food is not None else {}
        self.big_bombs = big_bombs
        self.small_bombs = small_bombs

    @classmethod
    def from_board(cls, board, prev_heads=None, multipliers=None,
                    remaining_moves=None):
        ordered_bodies = BodyOrderer.order_all(board.heads, board.bodies, prev_heads)
        return cls(board.rows, board.cols, dict(board.heads), ordered_bodies,
                    dict(board.food), list(board.pickups),
                    multipliers, remaining_moves, set(board.walls),
                    dict(board.tail_food), list(board.big_bombs),
                    list(board.small_bombs))

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

    def _in_blast_range(self, pos):
        """v8: True if `pos` sets off a bomb -- not a crash, just a flat
        penalty on top of whatever that move would otherwise do."""
        if any(_chebyshev(pos, b) <= BIG_BOMB_RADIUS for b in self.big_bombs):
            return True
        return any(_chebyshev(pos, b) <= SMALL_BOMB_RADIUS for b in self.small_bombs)

    def _is_crash(self, new_head, my_body, other_body, other_head, tail, grows):
        if not self.in_bounds(new_head):
            return True
        solid = self._solid_cells(my_body, other_body, other_head, tail)
        if new_head not in solid:
            return False
        return not (grows and new_head == tail)

    def _tail_food_landing(self, new_head, head_letter):
        owner = self.tail_food[new_head]
        if owner == head_letter:
            return Landing(False, False, False, True, False, TAIL_FOOD_UNIT)
        return Landing(False, False, False, False, True, 0.0)

    def _classify_landing(self, new_head, head_letter, target_digit):
        if new_head in self.tail_food:
            return self._tail_food_landing(new_head, head_letter)
        if new_head in self.pickups:
            return Landing(False, False, True, False, False, PICKUP_SCORE)
        if new_head not in self.food:
            return _NOTHING
        is_correct, is_wrong, reward = _food_landing(self.food[new_head], target_digit)
        return Landing(is_correct, is_wrong, False, False, False, reward)

    def _clear_one_food_cell(self, new_head):
        new_food = dict(self.food)
        new_food.pop(new_head, None)
        return new_food

    def _clear_every_copy_of_the_eaten_digit(self, new_head):
        digit = self.food.get(new_head)
        if digit is None:
            return self._clear_one_food_cell(new_head)
        return {pos: d for pos, d in self.food.items() if d != digit}

    def _cleared_food(self, new_head, landing):
        """All remaining food after a landing: eating the target clears
        every copy of that digit (v6), not just the landed-on cell."""
        if landing.is_correct:
            return self._clear_every_copy_of_the_eaten_digit(new_head)
        if landing.is_wrong:
            return self._clear_one_food_cell(new_head)
        return dict(self.food)

    def _apply_landing(self, new_head, landing):
        new_food = self._cleared_food(new_head, landing)
        new_pickups = list(self.pickups)
        if landing.is_pickup:
            new_pickups.remove(new_head)
        new_tail_food = dict(self.tail_food)
        if landing.is_tail_food_mine or landing.is_tail_food_deny:
            new_tail_food.pop(new_head, None)
        return new_food, new_pickups, new_tail_food

    def _reward_for(self, landing, head_letter, new_head, my_multiplier, grows):
        if self._in_blast_range(new_head):
            return EXPLOSION_PENALTY  # v8: replaces, never stacks with the landing reward
        mult = my_multiplier if my_multiplier is not None else self.multipliers.get(head_letter, 1)
        return landing.reward * mult if grows else landing.reward

    def _apply_multiplier(self, head_letter, is_pickup):
        new_multipliers = dict(self.multipliers)
        if is_pickup:
            new_multipliers[head_letter] = new_multipliers.get(head_letter, 1) + 1
        return new_multipliers

    def _crash(self, head_letter, other_letter, head):
        """Common consequence of running into a wall, the board edge,
        your own body, or the opponent (v7): the snake stays exactly
        where it was, sheds its body down to head+2, and the shed cells
        become tail food only the opponent may eat."""
        body_letter = head_letter.lower()
        my_body = self.bodies.get(body_letter, [])
        new_bodies = dict(self.bodies)
        new_bodies[body_letter] = my_body[:CRASH_KEPT_BODY]
        new_tail_food = dict(self.tail_food)
        for pos in my_body[CRASH_KEPT_BODY:]:
            new_tail_food[pos] = other_letter
        return GameState(
            self.rows, self.cols, dict(self.heads), new_bodies, dict(self.food),
            list(self.pickups), dict(self.multipliers), self.remaining_moves,
            self.walls, new_tail_food, self.big_bombs, self.small_bombs,
        )

    def simulate(self, head_letter, other_letter, direction, my_multiplier=None):
        """Advance `head_letter`'s snake one `direction`. Returns
        (new_state, reward), or (None, 0.0) if this snake doesn't exist
        in the current state at all.

        A crash (wall / board edge / own body / opponent, v7) is no
        longer fatal: the snake stays put and sheds its tail (see
        _crash), and reward is the flat CRASH_PENALTY.
        """
        head = self.heads.get(head_letter)
        if head is None:
            return None, 0.0
        new_head = _step(head, direction)
        if new_head in self.walls:
            return self._crash(head_letter, other_letter, head), CRASH_PENALTY
        return self._advance(head_letter, other_letter, head, new_head, my_multiplier)

    def _advance(self, head_letter, other_letter, head, new_head, my_multiplier):
        body_letter = head_letter.lower()
        my_body = self.bodies.get(body_letter, [])
        other_body = self.bodies.get(other_letter.lower(), [])
        other_head = self.heads.get(other_letter)
        tail = tail_of(my_body)

        landing = self._classify_landing(new_head, head_letter, self.target_digit())
        grows = landing.is_correct or landing.is_tail_food_mine

        if self._is_crash(new_head, my_body, other_body, other_head, tail, grows):
            return self._crash(head_letter, other_letter, head), CRASH_PENALTY

        reward = self._reward_for(landing, head_letter, new_head, my_multiplier, grows)

        new_bodies = dict(self.bodies)
        new_bodies[body_letter] = _advance_body(head, my_body, grows)
        new_food, new_pickups, new_tail_food = self._apply_landing(new_head, landing)
        new_multipliers = self._apply_multiplier(head_letter, landing.is_pickup)
        new_heads = dict(self.heads)
        new_heads[head_letter] = new_head

        new_state = GameState(
            self.rows, self.cols, new_heads, new_bodies, new_food,
            new_pickups, new_multipliers, self.remaining_moves, self.walls,
            new_tail_food, self.big_bombs, self.small_bombs,
        )
        return new_state, reward

    def legal_moves(self, head_letter, other_letter):
        """[(direction, new_state, reward), ...] for every direction this
        snake can attempt. Since v7 a crash is survivable (see simulate),
        so this only ever comes up empty if the snake itself is missing."""
        out = []
        for d in DIRECTIONS:
            new_state, reward = self.simulate(head_letter, other_letter, d)
            if new_state is not None:
                out.append((d, new_state, reward))
        return out
