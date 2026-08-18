"""
Snake AI core.

Design notes (why this exists):
  v1 (single-frame greedy): the bot picked a move by scoring each of the 4
  directions in isolation. Reviewing game bced6c3e-...-a2aae80a9e38 showed
  it losing contested apples to the opponent -> fixed with territory
  control + a 2-ply search (see below).

  v2 introduced a real bug: to know which body cell is safe to walk into
  (a snake's own tail vacates on a non-growing move), it *guessed* the
  body's neck-to-tail order from a single board frame using adjacency.
  That guess is fundamentally ambiguous whenever a coiled snake has BOTH
  its neck and its tail sitting next to the head at once -- which is
  exactly what happens right after eating food in a tight space. Game
  4d70dada-...-90ac-a2aaa0a99892 shows the exact failure: body
  {(6,6),(7,6),(7,7)} with head (6,7) -- both (6,6) and (7,7) touch the
  head, and the guesser picked the wrong one as "tail", so the bot walked
  into its own neck and died (score -377 vs opponent's 1024).

  Fix: don't guess. A snake's neck is always exactly where its head was
  one turn ago -- that's unambiguous. The entry point now tracks each
  snake's previous head position across turns (order_bodies) and uses it
  to establish the true neck->tail order once, up front. From there, every
  simulated move in the lookahead builds the new order explicitly
  (new head prepended, old tail dropped unless growing) -- no further
  guessing is possible anywhere in the search tree.
"""

from collections import deque

EMPTY = ' '
FOOD = '*'

DIRECTIONS = {
    'up': (-1, 0),
    'down': (1, 0),
    'left': (0, -1),
    'right': (0, 1),
}


# ---------------------------------------------------------------------------
# Board parsing
# ---------------------------------------------------------------------------

def parse_board(board_str, rows, cols):
    lines = [line for line in board_str.split('\n') if line != '']
    grid = []
    for line in lines:
        content = line
        if content.startswith('|'):
            content = content[1:]
        if content.endswith('|'):
            content = content[:-1]
        if len(content) < cols:
            content = content + EMPTY * (cols - len(content))
        grid.append(list(content[:cols]))
    while len(grid) < rows:
        grid.append([EMPTY] * cols)
    return grid[:rows]


def find_positions(grid, rows, cols):
    """
    {'food': [(r,c), ...], 'heads': {'A': (r,c), 'B': (r,c)},
     'bodies': {'a': {(r,c), ...}, 'b': {...}}}   -- bodies are UNORDERED
    sets at this stage; call order_bodies() before using them for
    simulation/tail logic.
    """
    food = []
    heads = {}
    bodies = {}
    for r in range(rows):
        for c in range(cols):
            ch = grid[r][c]
            if ch == FOOD:
                food.append((r, c))
            elif ch == EMPTY:
                continue
            elif ch.isupper():
                heads[ch] = (r, c)
            elif ch.islower():
                bodies.setdefault(ch, set()).add((r, c))
    return {'food': food, 'heads': heads, 'bodies': bodies}


def in_bounds(pos, rows, cols):
    r, c = pos
    return 0 <= r < rows and 0 <= c < cols


def neighbors4(pos):
    r, c = pos
    return [(r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]


# ---------------------------------------------------------------------------
# Body ordering (neck -> tail)
#
# This is the piece that has to be exact: get it wrong and the bot thinks
# an occupied cell is safe to enter.
# ---------------------------------------------------------------------------

def _walk_path(start, body_set, exclude):
    """
    Walk the simple path formed by body_set starting at `start` (which must
    itself be in body_set), never stepping back into `exclude`. Returns the
    ordered list of cells from `start` to the far end (the tail).
    """
    order = [start]
    visited = {start}
    prev = exclude
    cur = start
    while True:
        nxts = [
            p for p in neighbors4(cur)
            if p in body_set and p != prev and p not in visited
        ]
        if not nxts:
            return order
        prev, cur = cur, nxts[0]
        visited.add(cur)
        order.append(cur)


def order_body_heuristic(head, body_set):
    """
    Best-effort neck->tail ordering from a SINGLE frame, with no history.
    Ambiguous (and occasionally wrong) when both path endpoints happen to
    be adjacent to the head at once -- only used as a fallback for the
    very first turn of a game, before we have a previous head to anchor
    on. Returns an ordered list (neck first, tail last), or [].
    """
    if not body_set:
        return []

    def degree(p):
        return sum(1 for n in neighbors4(p) if n in body_set)

    # True endpoints of the body-only path have degree <= 1. A middle
    # segment can still be spatially adjacent to the head (a coil), so
    # "adjacent to head" alone isn't a safe filter -- it must also be an
    # endpoint.
    necks = [p for p in neighbors4(head) if p in body_set and degree(p) <= 1]
    if not necks:
        necks = [p for p in body_set if degree(p) <= 1] or [next(iter(body_set))]

    return _walk_path(necks[0], body_set, exclude=head)


def order_body_from_neck(neck, body_set):
    """Exact ordering when the true neck is already known (unambiguous)."""
    if neck not in body_set:
        return []
    return _walk_path(neck, body_set, exclude=None)


def order_bodies(board_info, prev_heads):
    """
    Returns a new board_info whose 'bodies' values are ordered lists
    (neck first, tail last) instead of unordered sets.

    prev_heads: {'A': (r,c) or None, 'B': (r,c) or None} -- each snake's
    head position one turn ago, as seen by the caller. Since this is a
    strictly alternating-turn game, "one turn ago" is exactly one move
    old for both snakes, so the previous head is always the current
    neck -- no guessing required. Falls back to the single-frame
    heuristic when we don't have a previous position yet (turn 1 of a
    game) or it doesn't check out (e.g. mismatched game).
    """
    new_bodies = {}
    for head_letter, head in board_info['heads'].items():
        body_letter = head_letter.lower()
        body_set = board_info['bodies'].get(body_letter, set())
        if not body_set:
            new_bodies[body_letter] = []
            continue

        prev_head = (prev_heads or {}).get(head_letter)
        ordered = []
        if prev_head is not None and prev_head in body_set:
            ordered = order_body_from_neck(prev_head, body_set)
        if len(ordered) != len(body_set):
            # Fallback: either no usable history, or the history didn't
            # explain every body cell (shouldn't normally happen) --
            # recompute from scratch rather than trust a partial order.
            ordered = order_body_heuristic(head, body_set)

        new_bodies[body_letter] = ordered

    out = dict(board_info)
    out['bodies'] = new_bodies
    return out


def tail_of(ordered_body):
    return ordered_body[-1] if ordered_body else None


# ---------------------------------------------------------------------------
# BFS helpers
# ---------------------------------------------------------------------------

def bfs_distances(start, obstacles, rows, cols):
    """Multi-target BFS distance map from `start`, avoiding `obstacles`."""
    dist = {start: 0}
    q = deque([start])
    while q:
        cur = q.popleft()
        d = dist[cur]
        for nxt in neighbors4(cur):
            if not in_bounds(nxt, rows, cols):
                continue
            if nxt in dist or nxt in obstacles:
                continue
            dist[nxt] = d + 1
            q.append(nxt)
    return dist


def voronoi_territory(my_head, opp_head, walls, rows, cols):
    """
    Simultaneous BFS from both heads (each moves 1 cell/round). A cell
    belongs to whoever reaches it in fewer steps; ties belong to neither.
    """
    dist_me = bfs_distances(my_head, walls, rows, cols)
    dist_opp = bfs_distances(opp_head, walls, rows, cols) if opp_head else {}

    my_territory = 0
    opp_territory = 0
    for cell, d in dist_me.items():
        do = dist_opp.get(cell)
        if do is None or d < do:
            my_territory += 1
    for cell, d in dist_opp.items():
        dm = dist_me.get(cell)
        if dm is None or d < dm:
            opp_territory += 1

    return my_territory, opp_territory, dist_me, dist_opp


# ---------------------------------------------------------------------------
# Move simulation (for lookahead)
#
# Bodies here are always ordered lists (neck first, tail last), either
# produced by order_bodies() at the root or by this function itself one
# ply deeper -- so the tail is always read off directly, never guessed.
# ---------------------------------------------------------------------------

def simulate_move(board_info, head_letter, body_letter, other_head_letter,
                   other_body_letter, direction, rows, cols):
    """
    Returns a new board_info after `head_letter`'s snake takes `direction`,
    or None if that move is immediately fatal (wall / body / head-on-body
    collision). Does not know about future food spawns, so eaten food is
    simply removed with nothing replacing it.
    """
    heads = board_info['heads']
    bodies = board_info['bodies']
    food = board_info['food']

    head = heads.get(head_letter)
    if head is None:
        return None

    dr, dc = DIRECTIONS[direction]
    new_head = (head[0] + dr, head[1] + dc)
    if not in_bounds(new_head, rows, cols):
        return None

    my_body = list(bodies.get(body_letter, []))
    other_body = list(bodies.get(other_body_letter, []))
    other_head = heads.get(other_head_letter)

    tail = tail_of(my_body)

    solid = set(my_body) | set(other_body)
    if other_head is not None:
        solid.add(other_head)
    if tail is not None:
        solid.discard(tail)  # our own tail vacates unless we grow into it

    ate_food = new_head in food
    if new_head in solid and not (ate_food and new_head == tail):
        return None

    if ate_food:
        new_body = [head] + my_body  # grow: keep the old tail too
    else:
        new_body = [head] + my_body[:-1]  # shift: drop the old tail

    new_heads = dict(heads)
    new_heads[head_letter] = new_head
    new_bodies = dict(bodies)
    new_bodies[body_letter] = new_body
    new_food = list(food)
    if ate_food:
        new_food.remove(new_head)

    return {'heads': new_heads, 'bodies': new_bodies, 'food': new_food}


def legal_moves(board_info, head_letter, body_letter, other_head_letter,
                 other_body_letter, rows, cols):
    out = []
    for d in DIRECTIONS:
        nb = simulate_move(board_info, head_letter, body_letter,
                            other_head_letter, other_body_letter, d, rows, cols)
        if nb is not None:
            out.append((d, nb))
    return out


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_position(board_info, rows, cols, me_head, me_body, opp_head_l,
                       opp_body_l, remaining_moves):
    """
    Positive = good for "me". Combines territory control, contested-food
    value, and length advantage. Weighted so that in the endgame (few
    moves left) grabbing reachable food matters much more than long-run
    territory, since there is no long run left.
    """
    heads = board_info['heads']
    my_head = heads.get(me_head)
    opp_head = heads.get(opp_head_l)

    if my_head is None:
        return float('-inf')
    if opp_head is None:
        return float('inf')

    my_body = board_info['bodies'].get(me_body, [])
    opp_body = board_info['bodies'].get(opp_body_l, [])
    my_tail = tail_of(my_body)
    opp_tail = tail_of(opp_body)

    walls = set(my_body) | set(opp_body)
    walls.discard(my_tail)
    walls.discard(opp_tail)
    walls.discard(None)

    my_territory, opp_territory, dist_me, dist_opp = voronoi_territory(
        my_head, opp_head, walls, rows, cols
    )
    territory_diff = my_territory - opp_territory

    # Food value: reward food we can reach at least as fast as the
    # opponent, weighted by how close it is. Ignore food the opponent
    # will clearly win the race for.
    food_score = 0.0
    for f in board_info['food']:
        d_me = dist_me.get(f)
        d_opp = dist_opp.get(f)
        if d_me is None:
            continue
        if d_opp is not None and d_opp < d_me:
            continue  # opponent wins this race, don't chase it
        food_score += 1.0 / (1.0 + d_me)

    endgame = remaining_moves is not None and remaining_moves < 50
    food_weight = 40.0 if endgame else 18.0
    territory_weight = 0.6 if endgame else 1.2

    length_diff = len(my_body) - len(opp_body)

    # Mild bonus for keeping some breathing room right next to our head,
    # so we don't walk into single-exit corridors.
    my_exits = sum(
        1 for n in neighbors4(my_head)
        if in_bounds(n, rows, cols) and n not in walls
    )
    exit_penalty = -25.0 if my_exits <= 1 else (0.0 if my_exits >= 2 else -8.0)

    score = (
        territory_diff * territory_weight
        + food_score * food_weight
        + length_diff * 6.0
        + exit_penalty
    )
    return score


# ---------------------------------------------------------------------------
# Top-level move choice: 2-ply search (my move -> opponent's best reply)
#
# `board_info` passed in here MUST already have ordered bodies (i.e. have
# gone through order_bodies()). choose_direction itself never re-derives
# order from geometry, so once the root is right, everything downstream is
# right by construction.
# ---------------------------------------------------------------------------

def choose_direction(board_info, rows, cols, me_head, me_body, opp_head_l,
                      opp_body_l, remaining_moves):
    my_moves = legal_moves(board_info, me_head, me_body, opp_head_l,
                            opp_body_l, rows, cols)

    if not my_moves:
        # Nothing is safe; still have to send something. Prefer the move
        # that survives longest / stays in bounds.
        head = board_info['heads'].get(me_head)
        if head is not None:
            for d, (dr, dc) in DIRECTIONS.items():
                nb = (head[0] + dr, head[1] + dc)
                if in_bounds(nb, rows, cols):
                    return d
        return 'up'

    best_dir = None
    best_score = float('-inf')

    for d, board_after_me in my_moves:
        opp_moves = legal_moves(board_after_me, opp_head_l, opp_body_l,
                                 me_head, me_body, rows, cols)
        if not opp_moves:
            # Opponent has no legal move left -> effectively a win for us.
            score = float('inf')
        else:
            # Assume the opponent plays their own best reply (rational,
            # self-interested opponent model): pick the move that
            # maximizes *their* evaluation, then score the resulting
            # board from our own perspective.
            best_opp_eval = float('-inf')
            best_opp_board = None
            for _od, board_after_opp in opp_moves:
                opp_eval = evaluate_position(
                    board_after_opp, rows, cols, opp_head_l, opp_body_l,
                    me_head, me_body, remaining_moves
                )
                if opp_eval > best_opp_eval:
                    best_opp_eval = opp_eval
                    best_opp_board = board_after_opp
            score = evaluate_position(
                best_opp_board, rows, cols, me_head, me_body, opp_head_l,
                opp_body_l, remaining_moves
            )

        if score > best_score:
            best_score = score
            best_dir = d

    return best_dir or my_moves[0][0]