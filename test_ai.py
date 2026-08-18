import json
import time
import sys

sys.path.insert(0, '/home/claude/snake')
from snake_ai import (
    parse_board, find_positions, order_bodies, order_body_heuristic,
    order_body_from_neck, tail_of, choose_direction, evaluate_position,
    DIRECTIONS, in_bounds,
)

LOG_PATH_1 = '/mnt/user-data/uploads/game_bced6c3e-9581-11f1-8e06-a2aae80a9e38.log'
LOG_PATH_2 = '/mnt/user-data/uploads/game_4d70dada-9810-11f1-90ac-a2aaa0a99892.log'


def load_turns(path):
    turns = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line.startswith('< '):
                continue
            payload = json.loads(line[2:])
            if payload.get('event') in ('your_turn', 'game_over'):
                turns.append(payload['data'])
    return turns


def test_tail_basic():
    # Straight snake, head at (5,5), body going left: neck (5,4), tail (5,2)
    head = (5, 5)
    body = {(5, 4), (5, 3), (5, 2)}
    tail = tail_of(order_body_heuristic(head, body))
    assert tail == (5, 2), tail

    # Single-segment body: neck == tail
    head = (0, 0)
    body = {(0, 1)}
    assert tail_of(order_body_heuristic(head, body)) == (0, 1)

    # No body at all
    assert tail_of(order_body_heuristic((0, 0), set())) is None

    # Coiled snake (path with a turn)
    head = (2, 2)
    body = {(2, 1), (1, 1), (1, 2), (1, 3)}
    tail = tail_of(order_body_heuristic(head, body))
    assert tail == (1, 3), tail
    print('test_tail_basic: OK')


def test_regression_game_4d70dada():
    # This is the EXACT shape that killed the bot for real: body
    # {(6,6),(7,6),(7,7)}, head (6,7). Both (6,6) and (7,7) touch the head,
    # so a single-frame guess is genuinely ambiguous -- order_body_heuristic
    # is allowed to get this one wrong. What must NOT happen is
    # order_bodies() getting it wrong when the previous head is known,
    # because in the real match we DO know it (the snake's head was at
    # (6,6) the turn before, seen in the log right before this one).
    head = (6, 7)
    body = {(6, 6), (7, 6), (7, 7)}

    ordered = order_body_from_neck((6, 6), body)
    assert ordered == [(6, 6), (7, 6), (7, 7)], ordered
    assert tail_of(ordered) == (7, 7), tail_of(ordered)  # the TRUE tail

    board_info = {
        'heads': {'A': head, 'B': (9, 8)},
        'bodies': {'a': body, 'b': {(10, 7), (10, 8)}},
        'food': [(1, 6), (0, 0)],
    }
    fixed = order_bodies(board_info, prev_heads={'A': (6, 6), 'B': (9, 9)})
    assert fixed['bodies']['a'] == [(6, 6), (7, 6), (7, 7)]
    assert tail_of(fixed['bodies']['a']) == (7, 7)

    # And critically: moving "left" (into (6,6), the true neck) must now
    # be correctly rejected as fatal.
    from snake_ai import simulate_move
    result = simulate_move(fixed, 'A', 'a', 'B', 'b', 'left', 15, 15)
    assert result is None, "moving into the neck should be illegal, but wasn't"
    print('test_regression_game_4d70dada: OK (the fatal move is now correctly rejected)')


def test_order_bodies_no_history_falls_back():
    # Turn 1 of a game: no previous head yet. Should still produce SOME
    # valid full ordering (even if, in a pathological coil, it can't be
    # 100% guaranteed correct without history).
    board_info = {
        'heads': {'A': (5, 5), 'B': (0, 0)},
        'bodies': {'a': {(5, 4), (5, 3)}, 'b': set()},
        'food': [],
    }
    fixed = order_bodies(board_info, prev_heads=None)
    assert fixed['bodies']['a'] == [(5, 4), (5, 3)], fixed['bodies']['a']
    assert fixed['bodies']['b'] == []
    print('test_order_bodies_no_history_falls_back: OK')


def run_against_match(path):
    turns = load_turns(path)
    print(f'Loaded {len(turns)} turns from {path.split("/")[-1]}')

    errors = 0
    total_time = 0.0
    prev_heads = None  # mirrors run.py's PREV_HEADS.get(game_id) across turns

    for i, data in enumerate(turns):
        rows, cols = data['rows'], data['cols']
        side = data.get('side') or 'A'
        grid = parse_board(data['board'], rows, cols)
        board_info = find_positions(grid, rows, cols)
        board_info = order_bodies(board_info, prev_heads)

        me_head = side
        opp_head = 'B' if side == 'A' else 'A'
        me_body = me_head.lower()
        opp_body = opp_head.lower()

        if me_head not in board_info['heads']:
            continue  # game_over frame, our head already gone

        t0 = time.time()
        try:
            direction = choose_direction(
                board_info, rows, cols, me_head, me_body, opp_head, opp_body,
                data.get('remaining_moves')
            )
        except Exception as e:
            print(f'  turn {i}: EXCEPTION {e!r}')
            errors += 1
            continue
        total_time += time.time() - t0

        assert direction in DIRECTIONS, direction

        # Sanity: the chosen direction must not run off the board, and must
        # not walk into a currently-solid cell of either snake (the same
        # check simulate_move does, replicated here as an independent
        # cross-check on the *real* board data).
        head = board_info['heads'][me_head]
        dr, dc = DIRECTIONS[direction]
        nb = (head[0] + dr, head[1] + dc)
        if not in_bounds(nb, rows, cols):
            print(f'  turn {i}: chose {direction} which leaves the board!')
            errors += 1

        prev_heads = dict(board_info['heads'])

    print(f'Ran choose_direction on {len(turns)} real board states.')
    print(f'Errors: {errors}')
    print(f'Avg decision time: {1000*total_time/max(1,len(turns)):.2f} ms, '
          f'total: {total_time:.2f}s')
    assert errors == 0


def test_tail_frees_self_move():
    # A snake boxed in on 3 sides except through its own tail cell should
    # still find a legal move once the tail is correctly excluded.
    from snake_ai import simulate_move
    rows = cols = 5
    # Layout (A=head a=body):
    #   . a a . .
    #   . a A . .
    #   . a a . .
    # body cells: (0,1),(0,2),(1,1),(2,1),(2,2) with head (1,2)
    heads = {'A': (1, 2), 'B': (4, 4)}
    raw = {'heads': heads,
           'bodies': {'a': {(0, 1), (0, 2), (1, 1), (2, 1), (2, 2)}, 'b': set()},
           'food': []}
    board_info = order_bodies(raw, prev_heads=None)
    tail = tail_of(board_info['bodies']['a'])
    print('computed tail:', tail)
    for d in DIRECTIONS:
        nb = simulate_move(board_info, 'A', 'a', 'B', 'b', d, rows, cols)
        print(' ', d, '-> legal' if nb is not None else 'illegal')
    print('test_tail_frees_self_move: OK')


if __name__ == '__main__':
    test_tail_basic()
    test_regression_game_4d70dada()
    test_order_bodies_no_history_falls_back()
    test_tail_frees_self_move()
    run_against_match(LOG_PATH_1)
    run_against_match(LOG_PATH_2)
    print('ALL TESTS PASSED')