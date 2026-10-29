"""
Board parsing.

Rule history (see docs/RULES.md for the full source):
  v1 (fixed 15x15): food is '*', eat any of it to grow, +100.
  v2 (2 Sep 2026): board size varies per match (12-20 each dim). We never
      hardcode 15 anywhere -- rows/cols always come from turn_data.
  v3 (9 Sep 2026): food becomes single digits 1-9. Five are on the board
      at once and must be eaten in ascending CYCLIC order (...,8,9,1,2,...).
      Eating the correct next digit scores digit*100 and grows the snake.
      Eating any other digit is a -500 penalty (does not end the game).
  v4 (16 Sep 2026): 'X' pickups also appear. Eating one scores a flat +50
      and permanently bumps a per-player score multiplier (x2, then x3,
      ...) that applies ONLY to food points (not the +50 itself, not the
      per-move +1, not penalties). Does not grow the snake.
  v5 (23 Sep 2026): a single '#' wall (a straight line, odd length up to
      11) appears on the board at a time, placed on empty cells. Running
      your head into it is a -500 penalty and your snake does not move
      that turn -- it is not fatal, the game continues. The wall shrinks
      one cell off each end after both players have moved (11->9->...->1
      ->gone), then a new one appears elsewhere. There's no separate
      field for it -- it's read straight off the board like everything
      else here.
  v6 (30 Sep 2026): each of the five "window" digits now appears in
      several copies (3-5) instead of a single cell. Eating the target
      removes every copy of that digit at once (see GameState); wrong
      copies still cost -500 each individually.
  v7 (7 Oct 2026): crashing (own body, board edge, a '#' wall, or the
      opponent) no longer ends the game -- see GameState.simulate for
      the full consequence. The board can now also hold tail food, the
      circled letters U+24B6 ('Ⓐ') / U+24B7 ('Ⓑ'), dropped by a
      crashing snake and edible only by the side named on it (never by
      the snake that shed it -- stepping on your own counts as a normal
      move that just clears the cell). These are NOT ASCII uppercase
      letters even though str.isupper() is True for them, so they must
      be classified before the generic snake-head check or they'd be
      mistaken for a third snake's head.
  v8 (14 Oct 2026): two big bombs (U+1F4A3 'BOMB') and five small ones
      (U+1F9E8 'FIRECRACKER') sit on the board. You don't have to step
      on one: it goes off whenever your head *ends a move* within
      Chebyshev distance 2 of a big bomb or 1 of a small one (a 5x5 /
      3x3 blast square). It is NOT a crash -- your move still happens
      normally, you still eat whatever's on the landed cell, and you
      keep your tail. See GameState.simulate for the score consequence.
      A bomb that goes off is replaced elsewhere (same size, never in
      range of any head); food/pickups never spawn inside a blast
      square; and every bomb vanishes for good after round 150. Boards
      are now 20-30 per side (was 12-20) -- still never hardcoded.
      These emoji are outside the Unicode BMP, unlike every other board
      character so far -- Python's str already iterates by code point
      so parse_grid needs no change, but anything reading this board in
      JS/Java/Go must split by code point too (see README).
  v9 (21 Oct 2026): '*' is back, this time as *shot food* -- you can
      send {"action": "shoot", "data": {"direction": ...}} instead of
      moving (see GameState.simulate_shoot); a hit cuts the opponent
      from the hit cell to the tip of their tail and each cut cell
      becomes a '*' either side may eat. It has nothing to do with the
      digit sequence any more, so it's parsed into its own
      `Board.shot_food` list, not into `food`.
  v10 (28 Oct 2026): a single star, U+2B50 ('STAR'), can appear; eating
      it works like shot food (+100*multiplier, grows one cell) and
      also grants 50 turns of invincibility. While invincible a side's
      head/body case is INVERTED on the board (lowercase head, UPPERCASE
      body) -- that's a parsing decision, not a game-state one, so
      `Board.from_turn` takes `inverted_sides` (which letters are
      currently drawn flipped) from the caller, who reads it off
      `invincible_1`/`invincible_2` in turn_data the same way it already
      reads multipliers (see bot.py).

This module stays legacy-compatible: a board with only '*' still parses
and plays fine as shot food with no snake-specific owner (see
Board.shot_food and GameState's shot-food landing).
"""

from .digits import next_target_digit

EMPTY = ' '
SHOT_FOOD = '*'
STAR = '⭐'
PICKUP = 'X'
WALL = '#'
BIG_BOMB = '\U0001F4A3'    # 💣
SMALL_BOMB = '\U0001F9E8'  # 🧨
DIGITS = set('123456789')
TAIL_FOOD_OWNERS = {'Ⓐ': 'A', 'Ⓑ': 'B'}


def _strip_pipes(line):
    if line.startswith('|'):
        line = line[1:]
    if line.endswith('|'):
        line = line[:-1]
    return line


def _pad_row(content, cols):
    if len(content) < cols:
        return content + EMPTY * (cols - len(content))
    return content


def _pad_rows(grid, rows, cols):
    while len(grid) < rows:
        grid.append([EMPTY] * cols)
    return grid


def parse_grid(board_str, rows, cols):
    """Turn the raw '|...|\\n|...|' board string into a rows x cols
    list-of-lists of single characters."""
    lines = [line for line in board_str.split('\n') if line != '']
    grid = []
    for line in lines:
        content = _pad_row(_strip_pipes(line), cols)
        grid.append(list(content[:cols]))
    grid = _pad_rows(grid, rows, cols)
    return grid[:rows]


def _classify_food_char(ch, pos, food):
    """Handles a food digit / empty space. Returns True if the
    character was one of those."""
    if ch == EMPTY:
        return True
    if ch in DIGITS:
        food[pos] = int(ch)
        return True
    return False


def _classify_marker_char(ch, pos, pickups, walls):
    """Handles 'X' / '#'. Returns True if the character was one of those."""
    if ch == PICKUP:
        pickups.append(pos)
        return True
    if ch == WALL:
        walls.append(pos)
        return True
    return False


def _classify_bomb_char(ch, pos, big_bombs, small_bombs):
    """Handles the two bomb emoji. Returns True if the character was
    one of those."""
    if ch == BIG_BOMB:
        big_bombs.append(pos)
        return True
    if ch == SMALL_BOMB:
        small_bombs.append(pos)
        return True
    return False


def _classify_star_or_shot_char(ch, pos, stars, shot_food):
    """Handles the v10 star and the v9 shot-food '*'. Returns True if
    the character was one of those."""
    if ch == STAR:
        stars.append(pos)
        return True
    if ch == SHOT_FOOD:
        shot_food.append(pos)
        return True
    return False


def _classify_special_char(ch, pos, food, pickups, walls, bombs, resources):
    """Handles a food digit / 'X' / '#' / a bomb / the star / shot food
    / empty space. Returns True if the character was one of those
    (nothing left for the caller to do)."""
    big_bombs, small_bombs = bombs
    stars, shot_food = resources
    if _classify_food_char(ch, pos, food):
        return True
    if _classify_marker_char(ch, pos, pickups, walls):
        return True
    if _classify_bomb_char(ch, pos, big_bombs, small_bombs):
        return True
    return _classify_star_or_shot_char(ch, pos, stars, shot_food)


def _classify_tail_food_char(ch, pos, tail_food):
    """Handles the circled-letter tail food dropped by a crash. Must run
    before _classify_snake_char: these are NOT ASCII letters, but Python's
    str.isupper() is True for them too."""
    owner = TAIL_FOOD_OWNERS.get(ch)
    if owner is None:
        return False
    tail_food[pos] = owner
    return True


def _classify_snake_char(ch, pos, heads, bodies, inverted_sides):
    """Normally uppercase is a head, lowercase is body. v10: while a
    side is invincible it's drawn inverted (lowercase head, UPPERCASE
    body), so `inverted_sides` (a set of 'A'/'B') flips that reading
    for just that side -- the output (heads['A']/bodies['a']) always
    means the same thing regardless of how it was drawn."""
    side = ch.upper()
    if side not in ('A', 'B'):
        return
    is_head_char = ch.isupper()
    if side in inverted_sides:
        is_head_char = not is_head_char
    if is_head_char:
        heads[side] = pos
    else:
        bodies.setdefault(side.lower(), set()).add(pos)


def _classify_cell(ch, pos, food, pickups, walls, bombs, resources,
                    tail_food, heads, bodies, inverted_sides):
    if _classify_special_char(ch, pos, food, pickups, walls, bombs, resources):
        return
    if _classify_tail_food_char(ch, pos, tail_food):
        return
    _classify_snake_char(ch, pos, heads, bodies, inverted_sides)


class Board:
    """Immutable snapshot of one turn's grid, already classified into
    heads / bodies (unordered at this stage) / food / pickups / walls /
    bombs / tail_food / stars / shot_food."""

    __slots__ = ('rows', 'cols', 'heads', 'bodies', 'food', 'pickups',
                 'walls', 'big_bombs', 'small_bombs', 'tail_food',
                 'stars', 'shot_food')

    def __init__(self, rows, cols, heads, bodies, food, pickups, walls=(),
                 tail_food=None, big_bombs=(), small_bombs=(),
                 stars=(), shot_food=()):
        self.rows = rows
        self.cols = cols
        self.heads = heads          # {'A': (r,c), 'B': (r,c)}
        self.bodies = bodies        # {'a': {(r,c), ...}, 'b': {...}} -- UNORDERED
        self.food = food            # {(r,c): digit}
        self.pickups = pickups      # [(r,c), ...]
        self.walls = walls          # [(r,c), ...] -- the current '#' hazard, if any
        self.tail_food = tail_food or {}  # {(r,c): 'A'|'B'} -- who may eat it
        self.big_bombs = big_bombs      # [(r,c), ...] -- 5x5 blast each
        self.small_bombs = small_bombs  # [(r,c), ...] -- 3x3 blast each
        self.stars = stars              # [(r,c), ...] -- v10, usually 0 or 1
        self.shot_food = shot_food      # [(r,c), ...] -- v9, either side may eat

    @classmethod
    def from_turn(cls, board_str, rows, cols, inverted_sides=()):
        grid = parse_grid(board_str, rows, cols)
        food, pickups, walls, tail_food, heads, bodies = {}, [], [], {}, {}, {}
        big_bombs, small_bombs, stars, shot_food = [], [], [], []
        inverted_sides = set(inverted_sides)
        for r in range(rows):
            for c in range(cols):
                _classify_cell(grid[r][c], (r, c), food, pickups, walls,
                                (big_bombs, small_bombs), (stars, shot_food),
                                tail_food, heads, bodies, inverted_sides)
        return cls(rows, cols, heads, bodies, food, pickups, walls,
                    tail_food, big_bombs, small_bombs, stars, shot_food)

    def in_bounds(self, pos):
        r, c = pos
        return 0 <= r < self.rows and 0 <= c < self.cols

    def target_digit(self):
        """The next digit that must be eaten, per the cyclic rule (the
        predecessor of the returned digit is NOT on the board). Returns
        None if the board has no digits at all (legacy '*'-only board,
        or an empty board), meaning any food cell scores/grows normally.
        """
        digits_present = {d for d in self.food.values() if d is not None}
        return next_target_digit(digits_present)


def neighbors4(pos):
    r, c = pos
    return [(r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]
