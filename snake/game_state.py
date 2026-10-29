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
  - Shooting (v9, 21 Oct 2026): instead of moving, a side can shoot a
    direction (`simulate_shoot`). It always costs SHOT_COST (5000),
    hit or miss. The shot travels in a straight line from the head,
    passing over everything of your own (body/food/pickups/bombs) and
    stopping at the board edge, a '#' wall, or the first cell belonging
    to the OPPONENT. A hit cuts the opponent from that cell to the tip
    of their tail: every one of those cells becomes shot food ('*',
    SHOT_FOOD_UNIT*multiplier, grows either side that eats it) except
    any that land inside a bomb's blast square, which just vanish. An
    invincible opponent can't be cut (the shooter still pays the cost).
  - Star / invincibility (v10, 28 Oct 2026): eating a star scores like
    shot food (SHOT_FOOD_UNIT*multiplier, grows) and sets that side's
    `invincible` counter to STAR_INVINCIBLE_TURNS, ticking down by one
    on each of that side's own turns (move or shoot -- see
    `_decremented_invincible`). While invincible: running into the
    board edge, a '#' wall, or your own body costs nothing at all (no
    penalty, no body shed, no score change -- `_free_stay`/`_advance`'s
    invincible branch); a bomb's blast and a wrong digit are likewise
    free (`_reward_for`); and running INTO the opponent's body cuts
    them for free, exactly like a successful shot, while the invincible
    mover itself just stays put (see `_ram_opponent`). The reverse --
    a non-invincible side running into an invincible one -- is a normal
    crash for the one who moved, unless *they're* invincible too, in
    which case they do the cutting instead.

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
SHOT_FOOD_UNIT = 100.0   # v9/v10: shot food and the star share this economics
SHOT_COST = 5000.0
STAR_INVINCIBLE_TURNS = 50
CRASH_KEPT_BODY = 2  # body segments kept beyond the head after a crash
BIG_BOMB_RADIUS = 2    # Chebyshev distance -- a 5x5 blast square
SMALL_BOMB_RADIUS = 1  # Chebyshev distance -- a 3x3 blast square


def _chebyshev(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

# is_correct / is_wrong: landed on the right/wrong digit.
# is_pickup: landed on an 'X'. is_tail_food_mine: landed on tail food you
# may eat (grows + scores). is_tail_food_deny: landed on tail food only
# the opponent may eat (your own shed tail) -- clears it, no effect.
# is_shot_food: landed on v9 shot food ('*'). is_star: landed on the
# v10 star (same economics as shot food, plus invincibility).
Landing = namedtuple('Landing', 'is_correct is_wrong is_pickup '
                                 'is_tail_food_mine is_tail_food_deny '
                                 'is_shot_food is_star reward')
_NOTHING = Landing(False, False, False, False, False, False, False, 0.0)


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
    stars: [(r,c), ...]  -- v10, grants invincibility (usually 0 or 1)
    shot_food: [(r,c), ...]  -- v9, dropped by a shot, either side may eat
    multipliers: {'A': int, 'B': int}  -- starts at 1 each
    invincible: {'A': int, 'B': int}  -- remaining turns, 0 = not invincible
    """

    def __init__(self, rows, cols, heads, bodies, food, pickups,
                 multipliers=None, remaining_moves=None, walls=None,
                 tail_food=None, big_bombs=(), small_bombs=(),
                 stars=(), shot_food=(), invincible=None):
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
        self.stars = stars
        self.shot_food = shot_food
        self.invincible = invincible or {'A': 0, 'B': 0}

    @classmethod
    def from_board(cls, board, prev_heads=None, multipliers=None,
                    remaining_moves=None, invincible=None):
        ordered_bodies = BodyOrderer.order_all(board.heads, board.bodies, prev_heads)
        return cls(board.rows, board.cols, dict(board.heads), ordered_bodies,
                    dict(board.food), list(board.pickups),
                    multipliers, remaining_moves, set(board.walls),
                    dict(board.tail_food), list(board.big_bombs),
                    list(board.small_bombs), list(board.stars),
                    list(board.shot_food), invincible)

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

    def _is_invincible(self, head_letter):
        return self.invincible.get(head_letter, 0) > 0

    def _tail_food_landing(self, new_head, head_letter):
        owner = self.tail_food[new_head]
        if owner == head_letter:
            return Landing(False, False, False, True, False, False, False, TAIL_FOOD_UNIT)
        return Landing(False, False, False, False, True, False, False, 0.0)

    def _resource_landing(self, new_head):
        """Landed on 'X' / shot food / a star -- or None for any of
        those. Split out of _classify_landing to keep it xenon-A."""
        if new_head in self.pickups:
            return Landing(False, False, True, False, False, False, False, PICKUP_SCORE)
        if new_head in self.shot_food:
            return Landing(False, False, False, False, False, True, False, SHOT_FOOD_UNIT)
        if new_head in self.stars:
            return Landing(False, False, False, False, False, False, True, SHOT_FOOD_UNIT)
        return None

    def _classify_landing(self, new_head, head_letter, target_digit):
        if new_head in self.tail_food:
            return self._tail_food_landing(new_head, head_letter)
        resource = self._resource_landing(new_head)
        if resource is not None:
            return resource
        if new_head not in self.food:
            return _NOTHING
        is_correct, is_wrong, reward = _food_landing(self.food[new_head], target_digit)
        return Landing(is_correct, is_wrong, False, False, False, False, False, reward)

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

    def _apply_resource_removal(self, new_head, landing):
        """Drop the eaten 'X' / shot food / star from its list. Split
        out of _apply_landing to keep it xenon-A."""
        new_pickups = list(self.pickups)
        if landing.is_pickup:
            new_pickups.remove(new_head)
        new_shot_food = list(self.shot_food)
        if landing.is_shot_food:
            new_shot_food.remove(new_head)
        new_stars = list(self.stars)
        if landing.is_star:
            new_stars.remove(new_head)
        return new_pickups, new_shot_food, new_stars

    def _apply_landing(self, new_head, landing):
        new_food = self._cleared_food(new_head, landing)
        new_pickups, new_shot_food, new_stars = self._apply_resource_removal(new_head, landing)
        new_tail_food = dict(self.tail_food)
        if landing.is_tail_food_mine or landing.is_tail_food_deny:
            new_tail_food.pop(new_head, None)
        return new_food, new_pickups, new_shot_food, new_stars, new_tail_food

    def _invincible_reward(self, landing, head_letter, my_multiplier, grows):
        if landing.is_wrong:
            return 0.0  # v10: a wrong digit costs nothing while invincible
        return self._scaled_reward(landing, head_letter, my_multiplier, grows)

    def _scaled_reward(self, landing, head_letter, my_multiplier, grows):
        mult = my_multiplier if my_multiplier is not None else self.multipliers.get(head_letter, 1)
        return landing.reward * mult if grows else landing.reward

    def _reward_for(self, landing, head_letter, new_head, my_multiplier, grows, invincible):
        if invincible:
            return self._invincible_reward(landing, head_letter, my_multiplier, grows)
        if self._in_blast_range(new_head):
            return EXPLOSION_PENALTY  # v8: replaces, never stacks with the landing reward
        return self._scaled_reward(landing, head_letter, my_multiplier, grows)

    def _apply_multiplier(self, head_letter, is_pickup):
        new_multipliers = dict(self.multipliers)
        if is_pickup:
            new_multipliers[head_letter] = new_multipliers.get(head_letter, 1) + 1
        return new_multipliers

    def _ticked_invincible(self, head_letter):
        """One of `head_letter`'s own turns just passed (move, shoot, a
        free stay/ram, ...) -- count it down, floored at 0."""
        new_invincible = dict(self.invincible)
        new_invincible[head_letter] = max(0, new_invincible.get(head_letter, 0) - 1)
        return new_invincible

    def _next_invincible(self, head_letter, landing):
        """v10: eating a star resets the counter to the full 50 turns
        regardless of what it was; anything else just ticks it down."""
        if landing.is_star:
            new_invincible = dict(self.invincible)
            new_invincible[head_letter] = STAR_INVINCIBLE_TURNS
            return new_invincible
        return self._ticked_invincible(head_letter)

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
            list(self.stars), list(self.shot_food), self._ticked_invincible(head_letter),
        )

    def _free_stay(self, head_letter):
        """v10: an invincible snake that would've crashed (edge / wall /
        own body) just stays exactly where it was -- no penalty, no
        shedding, no score change at all."""
        return GameState(
            self.rows, self.cols, dict(self.heads), dict(self.bodies),
            dict(self.food), list(self.pickups), dict(self.multipliers),
            self.remaining_moves, self.walls, dict(self.tail_food),
            self.big_bombs, self.small_bombs, list(self.stars),
            list(self.shot_food), self._ticked_invincible(head_letter),
        )

    def _cells_to_cut(self, victim_body, hit_cell):
        """Split an (ordered neck->tail) body at `hit_cell`: everything
        from there to the tail is cut; the rest, closer to the head, is
        kept. Hitting the head itself (not in the body list) cuts the
        whole body."""
        if hit_cell not in victim_body:
            return [], list(victim_body)
        idx = victim_body.index(hit_cell)
        return victim_body[:idx], victim_body[idx:]

    def _shot_food_from_cut(self, cut_cells):
        """v9: a cut cell becomes shot food, unless it falls inside a
        bomb's blast square, in which case it just vanishes."""
        return [pos for pos in cut_cells if not self._in_blast_range(pos)]

    def _cut_victim(self, victim_letter, hit_cell):
        """Shared by a successful shot and an invincible ram: truncate
        the victim's body at `hit_cell` and turn the removed cells into
        shot food (see _cells_to_cut / _shot_food_from_cut)."""
        victim_body_letter = victim_letter.lower()
        victim_body = self.bodies.get(victim_body_letter, [])
        kept, cut_cells = self._cells_to_cut(victim_body, hit_cell)
        new_bodies = dict(self.bodies)
        new_bodies[victim_body_letter] = kept
        new_shot_food = list(self.shot_food) + self._shot_food_from_cut(cut_cells)
        return new_bodies, new_shot_food

    def _ram_opponent(self, head_letter, other_letter, hit_cell):
        """v10: an invincible snake moving into the opponent's body cuts
        them for free (like a shot) and simply stays put itself."""
        new_bodies, new_shot_food = self._cut_victim(other_letter, hit_cell)
        return GameState(
            self.rows, self.cols, dict(self.heads), new_bodies, dict(self.food),
            list(self.pickups), dict(self.multipliers), self.remaining_moves,
            self.walls, dict(self.tail_food), self.big_bombs, self.small_bombs,
            list(self.stars), new_shot_food, self._ticked_invincible(head_letter),
        )

    def simulate(self, head_letter, other_letter, direction, my_multiplier=None):
        """Advance `head_letter`'s snake one `direction`. Returns
        (new_state, reward), or (None, 0.0) if this snake doesn't exist
        in the current state at all.

        A crash (wall / board edge / own body / opponent, v7) is no
        longer fatal: the snake stays put and sheds its tail (see
        _crash), and reward is the flat CRASH_PENALTY -- unless this
        side is invincible (v10), in which case it's entirely free (see
        _free_stay / _ram_opponent).
        """
        head = self.heads.get(head_letter)
        if head is None:
            return None, 0.0
        new_head = _step(head, direction)
        invincible = self._is_invincible(head_letter)
        if new_head in self.walls:
            if invincible:
                return self._free_stay(head_letter), 0.0
            return self._crash(head_letter, other_letter, head), CRASH_PENALTY
        return self._advance(head_letter, other_letter, head, new_head, my_multiplier, invincible)

    def _grows(self, landing):
        return (landing.is_correct or landing.is_tail_food_mine
                or landing.is_shot_food or landing.is_star)

    def _hits_opponent(self, new_head, other_head, other_body):
        return new_head == other_head or new_head in other_body

    def _advance(self, head_letter, other_letter, head, new_head, my_multiplier, invincible):
        body_letter = head_letter.lower()
        my_body = self.bodies.get(body_letter, [])
        other_body = self.bodies.get(other_letter.lower(), [])
        other_head = self.heads.get(other_letter)
        tail = tail_of(my_body)

        if invincible and self._hits_opponent(new_head, other_head, other_body):
            return self._ram_opponent(head_letter, other_letter, new_head), 0.0

        landing = self._classify_landing(new_head, head_letter, self.target_digit())
        grows = self._grows(landing)

        if self._is_crash(new_head, my_body, other_body, other_head, tail, grows):
            if invincible:
                return self._free_stay(head_letter), 0.0
            return self._crash(head_letter, other_letter, head), CRASH_PENALTY

        return self._advance_result(head_letter, head, new_head, my_multiplier,
                                     invincible, my_body, landing, grows)

    def _advance_result(self, head_letter, head, new_head, my_multiplier,
                         invincible, my_body, landing, grows):
        body_letter = head_letter.lower()
        reward = self._reward_for(landing, head_letter, new_head, my_multiplier, grows, invincible)

        new_bodies = dict(self.bodies)
        new_bodies[body_letter] = _advance_body(head, my_body, grows)
        new_food, new_pickups, new_shot_food, new_stars, new_tail_food = \
            self._apply_landing(new_head, landing)
        new_multipliers = self._apply_multiplier(head_letter, landing.is_pickup)
        new_heads = dict(self.heads)
        new_heads[head_letter] = new_head

        new_state = GameState(
            self.rows, self.cols, new_heads, new_bodies, new_food,
            new_pickups, new_multipliers, self.remaining_moves, self.walls,
            new_tail_food, self.big_bombs, self.small_bombs, new_stars,
            new_shot_food, self._next_invincible(head_letter, landing),
        )
        return new_state, reward

    def _shot_hit_cell(self, head, direction, other_letter):
        """Walk the line of fire from `head` in `direction`: stop (miss,
        None) at the board edge or a '#' wall, stop (hit) at the first
        cell belonging to the opponent. Everything of our own -- body,
        food, pickups, bombs, stars, shot food -- is passed straight
        over."""
        other_head = self.heads.get(other_letter)
        other_body = set(self.bodies.get(other_letter.lower(), []))
        dr, dc = DIRECTIONS[direction]
        pos = (head[0] + dr, head[1] + dc)
        while self.in_bounds(pos) and pos not in self.walls:
            if pos == other_head or pos in other_body:
                return pos
            pos = (pos[0] + dr, pos[1] + dc)
        return None

    def simulate_shoot(self, head_letter, other_letter, direction):
        """v9: shoot `direction` instead of moving. Always costs
        SHOT_COST, hit or miss (affordability is the caller's job --
        GameState doesn't track real cumulative score, see bot.py/
        strategy.py). An invincible opponent can't be cut either way."""
        head = self.heads.get(head_letter)
        if head is None:
            return None, 0.0
        hit_cell = self._shot_hit_cell(head, direction, other_letter)
        if hit_cell is None or self._is_invincible(other_letter):
            return self._free_stay(head_letter), -SHOT_COST
        new_bodies, new_shot_food = self._cut_victim(other_letter, hit_cell)
        new_state = GameState(
            self.rows, self.cols, dict(self.heads), new_bodies, dict(self.food),
            list(self.pickups), dict(self.multipliers), self.remaining_moves,
            self.walls, dict(self.tail_food), self.big_bombs, self.small_bombs,
            list(self.stars), new_shot_food, self._ticked_invincible(head_letter),
        )
        return new_state, -SHOT_COST

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

    def shoot_moves(self, head_letter, other_letter):
        """[(direction, new_state, reward), ...] for every direction this
        snake could shoot -- always 4 options; whether we can actually
        afford SHOT_COST is checked by the caller, not here."""
        out = []
        for d in DIRECTIONS:
            new_state, reward = self.simulate_shoot(head_letter, other_letter, d)
            if new_state is not None:
                out.append((d, new_state, reward))
        return out
