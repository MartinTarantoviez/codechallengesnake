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

  v3: reweighted food vs. territory (the bot was wandering for space
  control instead of eating reachable food -- see _weights below), and
  every function in this module is kept deliberately small and
  single-purpose so cyclomatic complexity stays in rank A throughout
  (verify with `xenon --max-absolute A --max-modules A --max-average A
  snake_ai.py`).
"""

from collections import deque

# Bump whenever this file changes. Not printed automatically (this module
# has no entry point), but check it with:
#   python -c "import snake_ai; print(snake_ai.VERSION)"
# against the version stated in the chat message that gave you the file.
VERSION = "2026-08-18.v4-rank-a"

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


def parse_board(board_str, rows, cols):
    lines = [line for line in board_str.split('\n') if line != '']
    grid = []
    for line in lines:
        content = _pad_row(_strip_pipes(line), cols)
        grid.append(list(content[:cols]))
    grid = _pad_rows(grid, rows, cols)
    return grid[:rows]


def _classify_cell(ch, pos, food, heads, bodies):
    if ch == FOOD:
        food.append(pos)
        return
    if ch == EMPTY:
        return
    if ch.isupper():
        heads[ch] = pos
        return
    if ch.islower():
        bodies.setdefault(ch, set()).add(pos)


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
            _classify_cell(grid[r][c], (r, c), food, heads, bodies)
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

def _unvisited_body_neighbors(cur, body_set, prev, visited):
    result = []
    for p in neighbors4(cur):
        if p not in body_set:
            continue
        if p == prev:
            continue
        if p in visited:
            continue
        result.append(p)
    return result


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
        nxts = _unvisited_body_neighbors(cur, body_set, prev, visited)
        if not nxts:
            return order
        prev, cur = cur, nxts[0]
        visited.add(cur)
        order.append(cur)


def _degree_in_set(p, body_set):
    return sum(1 for n in neighbors4(p) if n in body_set)


def _is_endpoint(p, body_set):
    return _degree_in_set(p, body_set) <= 1


def _neck_candidates(head, body_set):
    return [p for p in neighbors4(head) if p in body_set and _is_endpoint(p, body_set)]


def _any_endpoint(body_set):
    for p in body_set:
        if _is_endpoint(p, body_set):
            return p
    return next(iter(body_set))


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
    necks = _neck_candidates(head, body_set)
    neck = necks[0] if necks else _any_endpoint(body_set)
    return _walk_path(neck, body_set, exclude=head)


def order_body_from_neck(neck, body_set):
    """Exact ordering when the true neck is already known (unambiguous)."""
    if neck not in body_set:
        return []
    return _walk_path(neck, body_set, exclude=None)


def _has_usable_history(prev_head, body_set):
    if prev_head is None:
        return False
    return prev_head in body_set


def _order_one_body(head, body_set, prev_head):
    if not body_set:
        return []
    if _has_usable_history(prev_head, body_set):
        ordered = order_body_from_neck(prev_head, body_set)
        if len(ordered) == len(body_set):
            return ordered
    return order_body_heuristic(head, body_set)


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
    prev_heads = prev_heads or {}
    new_bodies = {}
    for head_letter, head in board_info['heads'].items():
        body_letter = head_letter.lower()
        body_set = board_info['bodies'].get(body_letter, set())
        prev_head = prev_heads.get(head_letter)
        new_bodies[body_letter] = _order_one_body(head, body_set, prev_head)

    out = dict(board_info)
    out['bodies'] = new_bodies
    return out


def tail_of(ordered_body):
    return ordered_body[-1] if ordered_body else None


# ---------------------------------------------------------------------------
# BFS helpers
# ---------------------------------------------------------------------------

def _step_cost(nxt, dist, obstacles, rows, cols, d):
    if not in_bounds(nxt, rows, cols):
        return None
    if nxt in dist:
        return None
    if nxt in obstacles:
        return None
    return d + 1


def bfs_distances(start, obstacles, rows, cols):
    """Multi-target BFS distance map from `start`, avoiding `obstacles`."""
    dist = {start: 0}
    q = deque([start])
    while q:
        cur = q.popleft()
        d = dist[cur]
        for nxt in neighbors4(cur):
            new_d = _step_cost(nxt, dist, obstacles, rows, cols, d)
            if new_d is not None:
                dist[nxt] = new_d
                q.append(nxt)
    return dist


def _closer(d, other):
    return other is None or d < other


def _count_closer(dist_a, dist_b):
    count = 0
    for cell, d in dist_a.items():
        if _closer(d, dist_b.get(cell)):
            count += 1
    return count


def voronoi_territory(my_head, opp_head, walls, rows, cols):
    """
    Simultaneous BFS from both heads (each moves 1 cell/round). A cell
    belongs to whoever reaches it in fewer steps; ties belong to neither.
    """
    dist_me = bfs_distances(my_head, walls, rows, cols)
    dist_opp = bfs_distances(opp_head, walls, rows, cols) if opp_head else {}
    my_territory = _count_closer(dist_me, dist_opp)
    opp_territory = _count_closer(dist_opp, dist_me)
    return my_territory, opp_territory, dist_me, dist_opp


# ---------------------------------------------------------------------------
# Move simulation (for lookahead)
#
# Bodies here are always ordered lists (neck first, tail last), either
# produced by order_bodies() at the root or by this function itself one
# ply deeper -- so the tail is always read off directly, never guessed.
# ---------------------------------------------------------------------------

def _solid_cells(my_body, other_body, other_head, tail):
    solid = set(my_body) | set(other_body)
    if other_head is not None:
        solid.add(other_head)
    if tail is not None:
        solid.discard(tail)  # our own tail vacates unless we grow into it
    return solid


def _is_fatal_move(new_head, solid, ate_food, tail):
    if new_head not in solid:
        return False
    growing_into_own_tail = ate_food and new_head == tail
    return not growing_into_own_tail


def _advance_body(head, my_body, tail, ate_food):
    if ate_food:
        return [head] + my_body  # grow: keep the old tail too
    return [head] + my_body[:-1]  # shift: drop the old tail


def _consume_food(food, new_head, ate_food):
    if not ate_food:
        return list(food)
    new_food = list(food)
    new_food.remove(new_head)
    return new_food


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

    solid = _solid_cells(my_body, other_body, other_head, tail)
    ate_food = new_head in food
    if _is_fatal_move(new_head, solid, ate_food, tail):
        return None

    new_heads = dict(heads)
    new_heads[head_letter] = new_head
    new_bodies = dict(bodies)
    new_bodies[body_letter] = _advance_body(head, my_body, tail, ate_food)
    new_food = _consume_food(food, new_head, ate_food)

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

def _weights(remaining_moves):
    """(food_weight, territory_weight, food_decay) for this position.

    Tuned against 5 real matches: with the original weights the bot moved
    *away* from food that was <=8 steps away about 40% of the time,
    because territory swings (worth a lot per cell) drowned out food
    value (which decayed to near-zero past a few steps). These weights
    keep territory as a real tiebreaker/safety signal without letting it
    override a clearly winnable, nearby apple.
    """
    if _is_endgame(remaining_moves):
        return 90.0, 0.25, 0.25
    return 80.0, 0.25, 0.25


def _is_endgame(remaining_moves):
    return remaining_moves is not None and remaining_moves < 50


def _food_term(f, dist_me, dist_opp, decay):
    d_me = dist_me.get(f)
    if d_me is None:
        return 0.0
    d_opp = dist_opp.get(f)
    if d_opp is not None and d_opp < d_me:
        return 0.0  # opponent wins this race, don't chase it
    return 1.0 / (1.0 + decay * d_me)


def _food_score(food, dist_me, dist_opp, decay):
    """Sum of reachable-and-winnable food, weighted by closeness."""
    return sum(_food_term(f, dist_me, dist_opp, decay) for f in food)


def _exit_penalty(my_head, walls, rows, cols):
    """Mild penalty for standing next to few open exits (avoid corridors)."""
    my_exits = sum(
        1 for n in neighbors4(my_head)
        if in_bounds(n, rows, cols) and n not in walls
    )
    return _exit_penalty_for_count(my_exits)


def _exit_penalty_for_count(my_exits):
    if my_exits <= 1:
        return -25.0
    if my_exits == 2:
        return -8.0
    return 0.0


def _walls_for(my_body, opp_body):
    walls = set(my_body) | set(opp_body)
    walls.discard(tail_of(my_body))
    walls.discard(tail_of(opp_body))
    walls.discard(None)
    return walls


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
    walls = _walls_for(my_body, opp_body)

    my_territory, opp_territory, dist_me, dist_opp = voronoi_territory(
        my_head, opp_head, walls, rows, cols
    )
    food_weight, territory_weight, decay = _weights(remaining_moves)

    return (
        (my_territory - opp_territory) * territory_weight
        + _food_score(board_info['food'], dist_me, dist_opp, decay) * food_weight
        + (len(my_body) - len(opp_body)) * 6.0
        + _exit_penalty(my_head, walls, rows, cols)
    )


# ---------------------------------------------------------------------------
# Top-level move choice: 2-ply search (my move -> opponent's best reply)
#
# `board_info` passed in here MUST already have ordered bodies (i.e. have
# gone through order_bodies()). choose_direction itself never re-derives
# order from geometry, so once the root is right, everything downstream is
# right by construction.
# ---------------------------------------------------------------------------

def _best_opponent_reply(board_after_me, opp_head_l, opp_body_l, me_head,
                          me_body, rows, cols, remaining_moves):
    """
    Opponent model: among their legal replies to our move, assume they
    play the one that maximizes *their own* evaluation. Returns the
    resulting board, or None if the opponent has no legal move at all
    (we just trapped them).
    """
    opp_moves = legal_moves(board_after_me, opp_head_l, opp_body_l,
                             me_head, me_body, rows, cols)
    if not opp_moves:
        return None
    return _argmax_board(opp_moves, opp_head_l, opp_body_l, me_head, me_body,
                          rows, cols, remaining_moves)


def _argmax_board(candidate_moves, head_a, body_a, head_b, body_b, rows, cols,
                   remaining_moves):
    best_board = None
    best_eval = float('-inf')
    for _direction, board_after in candidate_moves:
        score = evaluate_position(board_after, rows, cols, head_a, body_a,
                                   head_b, body_b, remaining_moves)
        if score > best_eval:
            best_eval = score
            best_board = board_after
    return best_board


def _score_my_move(board_after_me, me_head, me_body, opp_head_l, opp_body_l,
                    rows, cols, remaining_moves):
    """Score one of our candidate moves by our position after the
    opponent's best reply to it (or +inf if that move traps them)."""
    best_opp_board = _best_opponent_reply(
        board_after_me, opp_head_l, opp_body_l, me_head, me_body, rows,
        cols, remaining_moves
    )
    if best_opp_board is None:
        return float('inf')
    return evaluate_position(
        best_opp_board, rows, cols, me_head, me_body, opp_head_l,
        opp_body_l, remaining_moves
    )


def _first_onboard_direction(head, rows, cols):
    for d, (dr, dc) in DIRECTIONS.items():
        nb = (head[0] + dr, head[1] + dc)
        if in_bounds(nb, rows, cols):
            return d
    return 'up'


def _fallback_direction(board_info, me_head, rows, cols):
    """Nothing we tried was safe; send whatever stays on the board."""
    head = board_info['heads'].get(me_head)
    if head is None:
        return 'up'
    return _first_onboard_direction(head, rows, cols)


def choose_direction(board_info, rows, cols, me_head, me_body, opp_head_l,
                      opp_body_l, remaining_moves):
    my_moves = legal_moves(board_info, me_head, me_body, opp_head_l,
                            opp_body_l, rows, cols)
    if not my_moves:
        return _fallback_direction(board_info, me_head, rows, cols)

    best_dir, best_score = None, float('-inf')
    for d, board_after_me in my_moves:
        score = _score_my_move(board_after_me, me_head, me_body, opp_head_l,
                                opp_body_l, rows, cols, remaining_moves)
        if score > best_score:
            best_score, best_dir = score, d

    return best_dir or my_moves[0][0]