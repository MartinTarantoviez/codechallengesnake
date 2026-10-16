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

This module stays legacy-compatible: a board with only '*' still parses
and plays fine (target_digit is simply None, meaning "any food cell is
correct" -- see Board.target_digit).
"""

from .digits import next_target_digit

EMPTY = ' '
LEGACY_FOOD = '*'
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
    """Handles '*' / a food digit / empty space. Returns True if the
    character was one of those."""
    if ch == EMPTY:
        return True
    if ch == LEGACY_FOOD:
        food[pos] = None  # None = "no ordering, any food is correct"
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


def _classify_special_char(ch, pos, food, pickups, walls, big_bombs, small_bombs):
    """Handles '*' / a food digit / 'X' / '#' / a bomb / empty space.
    Returns True if the character was one of those (nothing left for
    the caller to do)."""
    if _classify_food_char(ch, pos, food):
        return True
    if _classify_marker_char(ch, pos, pickups, walls):
        return True
    return _classify_bomb_char(ch, pos, big_bombs, small_bombs)


def _classify_tail_food_char(ch, pos, tail_food):
    """Handles the circled-letter tail food dropped by a crash. Must run
    before _classify_snake_char: these are NOT ASCII letters, but Python's
    str.isupper() is True for them too."""
    owner = TAIL_FOOD_OWNERS.get(ch)
    if owner is None:
        return False
    tail_food[pos] = owner
    return True


def _classify_snake_char(ch, pos, heads, bodies):
    if ch.isupper():
        heads[ch] = pos
    elif ch.islower():
        bodies.setdefault(ch, set()).add(pos)


def _classify_cell(ch, pos, food, pickups, walls, bombs, tail_food, heads, bodies):
    big_bombs, small_bombs = bombs
    if _classify_special_char(ch, pos, food, pickups, walls, big_bombs, small_bombs):
        return
    if _classify_tail_food_char(ch, pos, tail_food):
        return
    _classify_snake_char(ch, pos, heads, bodies)


class Board:
    """Immutable snapshot of one turn's grid, already classified into
    heads / bodies (unordered at this stage) / food / pickups / walls /
    bombs / tail_food."""

    __slots__ = ('rows', 'cols', 'heads', 'bodies', 'food', 'pickups',
                 'walls', 'big_bombs', 'small_bombs', 'tail_food')

    def __init__(self, rows, cols, heads, bodies, food, pickups, walls=(),
                 tail_food=None, big_bombs=(), small_bombs=()):
        self.rows = rows
        self.cols = cols
        self.heads = heads          # {'A': (r,c), 'B': (r,c)}
        self.bodies = bodies        # {'a': {(r,c), ...}, 'b': {...}} -- UNORDERED
        self.food = food            # {(r,c): digit_or_None}
        self.pickups = pickups      # [(r,c), ...]
        self.walls = walls          # [(r,c), ...] -- the current '#' hazard, if any
        self.tail_food = tail_food or {}  # {(r,c): 'A'|'B'} -- who may eat it
        self.big_bombs = big_bombs      # [(r,c), ...] -- 5x5 blast each
        self.small_bombs = small_bombs  # [(r,c), ...] -- 3x3 blast each

    @classmethod
    def from_turn(cls, board_str, rows, cols):
        grid = parse_grid(board_str, rows, cols)
        food, pickups, walls, tail_food, heads, bodies = {}, [], [], {}, {}, {}
        big_bombs, small_bombs = [], []
        for r in range(rows):
            for c in range(cols):
                _classify_cell(grid[r][c], (r, c), food, pickups, walls,
                                (big_bombs, small_bombs), tail_food, heads, bodies)
        return cls(rows, cols, heads, bodies, food, pickups, walls,
                    tail_food, big_bombs, small_bombs)

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
