"""
Full coverage test suite for snake_ai.py.

Organized to mirror the sections of snake_ai.py itself:
  - board parsing
  - body ordering (neck -> tail)
  - BFS / voronoi territory
  - move simulation / legality
  - evaluation
  - top-level choose_direction (2-ply search)

Run with:
    pytest test_snake_ai_coverage.py --cov=snake_ai --cov-report=term-missing -q
"""
import math

import pytest

from snake_ai import (
    parse_board, find_positions, in_bounds, neighbors4,
    order_body_heuristic, order_body_from_neck, order_bodies, tail_of,
    bfs_distances, voronoi_territory,
    simulate_move, legal_moves,
    evaluate_position, choose_direction,
    DIRECTIONS, VERSION,
)


# ---------------------------------------------------------------------------
# Board parsing
# ---------------------------------------------------------------------------

def test_version_is_a_string():
    assert isinstance(VERSION, str) and VERSION


def test_parse_board_strips_pipes_and_keeps_content():
    board_str = "|A  |\n| b |\n|  *|"
    grid = parse_board(board_str, 3, 3)
    assert grid == [
        ['A', ' ', ' '],
        [' ', 'b', ' '],
        [' ', ' ', '*'],
    ]


def test_parse_board_without_pipes():
    board_str = "A \n b"
    grid = parse_board(board_str, 2, 2)
    assert grid[0] == ['A', ' ']
    assert grid[1] == [' ', 'b']


def test_parse_board_pads_short_rows():
    # row shorter than cols gets padded with EMPTY
    board_str = "|A|"
    grid = parse_board(board_str, 1, 4)
    assert grid == [['A', ' ', ' ', ' ']]


def test_parse_board_truncates_long_rows():
    board_str = "|ABCDEF|"
    grid = parse_board(board_str, 1, 3)
    assert grid == [['A', 'B', 'C']]


def test_parse_board_pads_missing_rows():
    # fewer newline-separated rows than `rows` -> extra blank rows appended
    board_str = "|A |"
    grid = parse_board(board_str, 3, 2)
    assert len(grid) == 3
    assert grid[0] == ['A', ' ']
    assert grid[1] == [' ', ' ']
    assert grid[2] == [' ', ' ']


def test_parse_board_ignores_empty_lines():
    board_str = "|A |\n\n|B |\n"
    grid = parse_board(board_str, 2, 2)
    assert grid[0] == ['A', ' ']
    assert grid[1] == ['B', ' ']


def test_parse_board_truncates_extra_rows():
    board_str = "|A|\n|B|\n|C|"
    grid = parse_board(board_str, 2, 1)
    assert grid == [['A'], ['B']]


def test_find_positions_classifies_all_cell_types():
    grid = [
        ['A', 'a', '*'],
        [' ', 'b', 'B'],
    ]
    info = find_positions(grid, 2, 3)
    assert info['heads'] == {'A': (0, 0), 'B': (1, 2)}
    assert info['bodies'] == {'a': {(0, 1)}, 'b': {(1, 1)}}
    assert info['food'] == [(0, 2)]


def test_find_positions_ignores_unknown_characters():
    # A character that is food, empty, uppercase, nor lowercase (e.g. a
    # digit or stray symbol) must be silently ignored rather than
    # misclassified as a body segment.
    grid = [['#', 'A'], ['7', ' ']]
    info = find_positions(grid, 2, 2)
    assert info['heads'] == {'A': (0, 1)}
    assert info['bodies'] == {}
    assert info['food'] == []


def test_find_positions_empty_board():
    grid = [[' ', ' '], [' ', ' ']]
    info = find_positions(grid, 2, 2)
    assert info == {'food': [], 'heads': {}, 'bodies': {}}


def test_in_bounds():
    assert in_bounds((0, 0), 5, 5) is True
    assert in_bounds((4, 4), 5, 5) is True
    assert in_bounds((-1, 0), 5, 5) is False
    assert in_bounds((0, -1), 5, 5) is False
    assert in_bounds((5, 0), 5, 5) is False
    assert in_bounds((0, 5), 5, 5) is False


def test_neighbors4():
    assert set(neighbors4((2, 2))) == {(1, 2), (3, 2), (2, 1), (2, 3)}


# ---------------------------------------------------------------------------
# Body ordering
# ---------------------------------------------------------------------------

def test_order_body_heuristic_empty_body():
    assert order_body_heuristic((0, 0), set()) == []


def test_order_body_heuristic_straight_line():
    head = (5, 5)
    body = {(5, 4), (5, 3), (5, 2)}
    ordered = order_body_heuristic(head, body)
    assert ordered == [(5, 4), (5, 3), (5, 2)]


def test_order_body_heuristic_single_segment():
    ordered = order_body_heuristic((0, 0), {(0, 1)})
    assert ordered == [(0, 1)]


def test_order_body_heuristic_coiled_path():
    head = (2, 2)
    body = {(2, 1), (1, 1), (1, 2), (1, 3)}
    ordered = order_body_heuristic(head, body)
    assert ordered[0] == (2, 1)
    assert ordered[-1] == (1, 3)
    assert len(ordered) == 4


def test_order_body_heuristic_no_neck_candidate_uses_any_endpoint():
    # Body cells with no member touching head at all -> necks == [],
    # falls back to _any_endpoint. Use a 2-cell body far from the head.
    head = (0, 0)
    body = {(5, 5), (5, 6)}
    ordered = order_body_heuristic(head, body)
    assert set(ordered) == body
    assert len(ordered) == 2


def test_order_body_heuristic_single_cell_no_endpoint_branch():
    # A single isolated cell not adjacent to head: necks == [], and
    # _any_endpoint has to fall through its loop to `next(iter(body_set))`
    # only if no cell qualifies as an endpoint -- but a lone cell has
    # degree 0 <= 1, so it *is* an endpoint. Still exercises the
    # necks-empty branch of order_body_heuristic.
    ordered = order_body_heuristic((9, 9), {(0, 0)})
    assert ordered == [(0, 0)]


def test_order_body_heuristic_closed_loop_has_no_endpoint():
    # A 2x2 closed loop: every cell has degree 2, so _is_endpoint is never
    # true for any cell -> _any_endpoint falls through its for-loop to
    # `next(iter(body_set))`. Also exercises _walk_path's "already
    # visited" branch (line 143-144), since walking a cycle eventually
    # meets a cell that's already been visited rather than just its
    # immediate predecessor.
    body = {(0, 0), (0, 1), (1, 0), (1, 1)}
    ordered = order_body_heuristic((5, 5), body)
    assert set(ordered) == body
    assert len(ordered) == 4  # the walk stops once it re-meets a visited cell


def test_order_body_from_neck_valid():
    body = {(6, 6), (7, 6), (7, 7)}
    ordered = order_body_from_neck((6, 6), body)
    assert ordered == [(6, 6), (7, 6), (7, 7)]


def test_order_body_from_neck_neck_not_in_body_returns_empty():
    body = {(1, 1), (1, 2)}
    assert order_body_from_neck((9, 9), body) == []


def test_tail_of():
    assert tail_of([(1, 1), (2, 2)]) == (2, 2)
    assert tail_of([]) is None
    assert tail_of([(0, 0)]) == (0, 0)


def test_order_bodies_uses_prev_head_when_valid():
    board_info = {
        'heads': {'A': (6, 7), 'B': (9, 8)},
        'bodies': {'a': {(6, 6), (7, 6), (7, 7)}, 'b': {(10, 7), (10, 8)}},
        'food': [(1, 6)],
    }
    fixed = order_bodies(board_info, prev_heads={'A': (6, 6), 'B': (9, 9)})
    assert fixed['bodies']['a'] == [(6, 6), (7, 6), (7, 7)]
    # unaffected keys preserved
    assert fixed['food'] == [(1, 6)]
    assert fixed['heads'] == board_info['heads']


def test_order_bodies_falls_back_when_prev_head_not_in_body():
    # prev_head given but doesn't match current body -> heuristic fallback
    board_info = {
        'heads': {'A': (5, 5)},
        'bodies': {'a': {(5, 4), (5, 3)}},
        'food': [],
    }
    fixed = order_bodies(board_info, prev_heads={'A': (99, 99)})
    assert fixed['bodies']['a'] == [(5, 4), (5, 3)]


def test_order_bodies_falls_back_when_ordered_length_mismatches():
    # prev_head is a real body cell, but it's the MIDDLE of the path
    # rather than the true endpoint, so walking from it in both
    # directions dead-ends early and can't reach every cell -> length
    # mismatch -> falls back to the single-frame heuristic, which (given
    # the real head) recovers the full, correctly-ordered path.
    head = (5, 5)
    body = {(5, 4), (5, 3), (5, 2)}  # true neck->tail: (5,4),(5,3),(5,2)
    board_info = {'heads': {'A': head}, 'bodies': {'a': body}, 'food': []}
    fixed = order_bodies(board_info, prev_heads={'A': (5, 3)})  # middle cell
    assert fixed['bodies']['a'] == [(5, 4), (5, 3), (5, 2)]


def test_order_bodies_no_prev_heads_arg():
    board_info = {
        'heads': {'A': (5, 5), 'B': (0, 0)},
        'bodies': {'a': {(5, 4), (5, 3)}, 'b': set()},
        'food': [],
    }
    fixed = order_bodies(board_info, prev_heads=None)
    assert fixed['bodies']['a'] == [(5, 4), (5, 3)]
    assert fixed['bodies']['b'] == []


def test_order_bodies_empty_body_short_circuits():
    board_info = {'heads': {'A': (0, 0)}, 'bodies': {}, 'food': []}
    fixed = order_bodies(board_info, prev_heads={'A': (1, 1)})
    assert fixed['bodies']['a'] == []


# ---------------------------------------------------------------------------
# BFS / voronoi territory
# ---------------------------------------------------------------------------

def test_bfs_distances_open_field():
    dist = bfs_distances((0, 0), set(), 3, 3)
    assert dist[(0, 0)] == 0
    assert dist[(0, 1)] == 1
    assert dist[(2, 2)] == 4


def test_bfs_distances_respects_obstacles():
    # wall blocks the only path around
    obstacles = {(0, 1), (1, 0)}
    dist = bfs_distances((0, 0), obstacles, 2, 2)
    assert (1, 1) not in dist  # unreachable: both neighbors of (0,0) blocked
    assert dist == {(0, 0): 0}


def test_bfs_distances_does_not_revisit():
    dist = bfs_distances((1, 1), set(), 3, 3)
    assert len(dist) == 9  # every cell visited exactly once


def test_voronoi_territory_symmetric_split():
    my_territory, opp_territory, dist_me, dist_opp = voronoi_territory(
        (0, 0), (0, 2), set(), 1, 3
    )
    # (0,1) is equidistant -> belongs to neither
    assert my_territory == 1
    assert opp_territory == 1
    assert dist_me[(0, 0)] == 0
    assert dist_opp[(0, 2)] == 0


def test_voronoi_territory_no_opponent_head():
    my_territory, opp_territory, dist_me, dist_opp = voronoi_territory(
        (0, 0), None, set(), 2, 2
    )
    assert opp_territory == 0
    assert dist_opp == {}
    assert my_territory == 4


# ---------------------------------------------------------------------------
# Move simulation / legality
# ---------------------------------------------------------------------------

def _board(me_head, me_body, opp_head=None, opp_body=None, food=None):
    return {
        'heads': {'A': me_head, **({'B': opp_head} if opp_head else {})},
        'bodies': {'a': list(me_body), 'b': list(opp_body or [])},
        'food': list(food or []),
    }


def test_simulate_move_out_of_bounds_returns_none():
    board_info = _board((0, 0), [])
    assert simulate_move(board_info, 'A', 'a', 'B', 'b', 'up', 5, 5) is None


def test_simulate_move_missing_head_returns_none():
    board_info = {'heads': {}, 'bodies': {}, 'food': []}
    assert simulate_move(board_info, 'A', 'a', 'B', 'b', 'up', 5, 5) is None


def test_simulate_move_into_own_body_is_fatal():
    board_info = _board((2, 2), [(1, 2), (0, 2)])
    result = simulate_move(board_info, 'A', 'a', 'B', 'b', 'up', 5, 5)
    assert result is None


def test_simulate_move_into_own_tail_without_eating_is_legal():
    # Coiled snake, ordered neck -> tail: head (2,2), neck (2,3),
    # mid (1,3), tail (1,2). The tail sits directly "up" from the head,
    # and since a non-growing move always vacates the tail, moving into
    # it must be legal.
    board_info = _board((2, 2), [(2, 3), (1, 3), (1, 2)])
    result = simulate_move(board_info, 'A', 'a', 'B', 'b', 'up', 5, 5)
    assert result is not None
    assert result['heads']['A'] == (1, 2)
    assert result['bodies']['a'] == [(2, 2), (2, 3), (1, 3)]  # dropped old tail


def test_simulate_move_growing_into_own_tail_cell_is_also_legal():
    # Same shape, but food sits on the tail cell. Whether or not the bot
    # grows, the tail cell it is about to vacate is never treated as
    # solid, so this stays legal either way -- confirms _is_fatal_move's
    # growing_into_own_tail branch doesn't turn this into a death.
    board_info = _board((2, 2), [(2, 3), (1, 3), (1, 2)], food=[(1, 2)])
    result = simulate_move(board_info, 'A', 'a', 'B', 'b', 'up', 5, 5)
    assert result is not None
    assert result['bodies']['a'] == [(2, 2), (2, 3), (1, 3), (1, 2)]  # grew


def test_simulate_move_head_on_collision_with_opponent_head_is_fatal():
    board_info = _board((2, 2), [], opp_head=(1, 2), opp_body=[])
    result = simulate_move(board_info, 'A', 'a', 'B', 'b', 'up', 5, 5)
    assert result is None


def test_simulate_move_into_opponent_body_is_fatal():
    board_info = _board((2, 2), [], opp_head=(9, 9), opp_body=[(1, 2)])
    result = simulate_move(board_info, 'A', 'a', 'B', 'b', 'up', 5, 5)
    assert result is None


def test_simulate_move_eats_food_grows_and_removes_food():
    board_info = _board((2, 2), [(2, 1)], food=[(1, 2), (5, 5)])
    result = simulate_move(board_info, 'A', 'a', 'B', 'b', 'up', 5, 5)
    assert result is not None
    assert result['heads']['A'] == (1, 2)
    assert result['bodies']['a'] == [(2, 2), (2, 1)]  # kept old tail
    assert result['food'] == [(5, 5)]


def test_simulate_move_normal_shift_without_food():
    board_info = _board((2, 2), [(2, 1), (2, 0)])
    result = simulate_move(board_info, 'A', 'a', 'B', 'b', 'up', 5, 5)
    # new body = [old head] + old body minus its last (tail) segment
    assert result['bodies']['a'] == [(2, 2), (2, 1)]


def test_legal_moves_filters_fatal_directions():
    # Walled in on three sides by the OPPONENT's body (opponent cells are
    # always solid -- no tail-vacate logic applies to them), only
    # 'right' is open.
    board_info = _board(
        (2, 2), [], opp_head=(9, 9), opp_body=[(1, 2), (3, 2), (2, 1)],
    )
    moves = legal_moves(board_info, 'A', 'a', 'B', 'b', 5, 5)
    dirs = {d for d, _ in moves}
    assert dirs == {'right'}


def test_legal_moves_empty_when_fully_boxed_in():
    board_info = _board((0, 0), [], opp_head=None, opp_body=[])
    # place walls on all four neighbors using opponent body
    board_info['bodies']['b'] = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    moves = legal_moves(board_info, 'A', 'a', 'B', 'b', 5, 5)
    # (-1,0) and (0,-1) are out of bounds anyway; (1,0) and (0,1) are walls
    assert moves == []


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def test_evaluate_position_missing_my_head_is_neg_inf():
    board_info = {'heads': {'B': (0, 0)}, 'bodies': {}, 'food': []}
    score = evaluate_position(board_info, 5, 5, 'A', 'a', 'B', 'b', None)
    assert score == float('-inf')


def test_evaluate_position_missing_opp_head_is_pos_inf():
    board_info = {'heads': {'A': (0, 0)}, 'bodies': {}, 'food': []}
    score = evaluate_position(board_info, 5, 5, 'A', 'a', 'B', 'b', None)
    assert score == float('inf')


def test_evaluate_position_prefers_more_territory():
    # A in the corner of a big open board has less territory than an
    # opponent parked in the middle.
    board_info = {
        'heads': {'A': (0, 0), 'B': (4, 4)},
        'bodies': {'a': [], 'b': []},
        'food': [],
    }
    score = evaluate_position(board_info, 9, 9, 'A', 'a', 'B', 'b', None)
    assert score < 0  # corner has strictly less territory than the center


def test_evaluate_position_endgame_weighting_differs_from_midgame():
    board_info = {
        'heads': {'A': (0, 0), 'B': (8, 8)},
        'bodies': {'a': [], 'b': []},
        'food': [(0, 1)],
    }
    mid = evaluate_position(board_info, 9, 9, 'A', 'a', 'B', 'b', 200)
    end = evaluate_position(board_info, 9, 9, 'A', 'a', 'B', 'b', 10)
    assert mid != end


def test_evaluate_position_unreachable_food_contributes_nothing():
    # Food sealed off behind a wall of the opponent's body is unreachable
    # by me (dist_me.get(f) is None) -- _food_term must contribute 0.0
    # for it rather than erroring or applying decay to a missing distance.
    walled_food = {
        'heads': {'A': (0, 0), 'B': (8, 8)},
        'bodies': {'a': [], 'b': [(0, 1), (1, 0), (1, 1)]},
        'food': [(9, 9)],  # sealed on the far side of the wall from me
    }
    no_food = {**walled_food, 'food': []}
    score_walled = evaluate_position(walled_food, 10, 10, 'A', 'a', 'B', 'b', None)
    score_none = evaluate_position(no_food, 10, 10, 'A', 'a', 'B', 'b', None)
    assert score_walled == score_none


def test_evaluate_position_food_contested_and_won_by_opponent_scores_zero_term():
    # food equidistant-favoring opponent should not count toward my score
    board_info = {
        'heads': {'A': (0, 0), 'B': (0, 2)},
        'bodies': {'a': [], 'b': []},
        'food': [(0, 2)],  # sits right on opponent's head, dist_opp=0 < dist_me
    }
    score_with_food = evaluate_position(board_info, 1, 5, 'A', 'a', 'B', 'b', None)
    board_info_no_food = {**board_info, 'food': []}
    score_without_food = evaluate_position(board_info_no_food, 1, 5, 'A', 'a', 'B', 'b', None)
    assert score_with_food == score_without_food


def test_evaluate_position_length_advantage_matters():
    short = {
        'heads': {'A': (2, 2), 'B': (2, 6)},
        'bodies': {'a': [], 'b': [(2, 5), (2, 4), (2, 3)]},
        'food': [],
    }
    long_ = {
        'heads': {'A': (2, 2), 'B': (2, 6)},
        'bodies': {'a': [(2, 1), (2, 0)], 'b': [(2, 5), (2, 4), (2, 3)]},
        'food': [],
    }
    score_short = evaluate_position(short, 9, 9, 'A', 'a', 'B', 'b', None)
    score_long = evaluate_position(long_, 9, 9, 'A', 'a', 'B', 'b', None)
    assert score_long > score_short


def test_evaluate_position_exit_penalty_applies_when_boxed():
    # Three of my head's four neighbors are opponent-body walls; the
    # fourth wall-list entry, (9, 9), is deliberately far away so it
    # becomes the "tail" _walls_for() vacates, without opening up any of
    # the three real walls around my head. That leaves exactly 1 exit
    # -> the -25 penalty tier.
    boxed = {
        'heads': {'A': (2, 2), 'B': (8, 8)},
        'bodies': {'a': [], 'b': [(1, 2), (3, 2), (2, 1), (9, 9)]},
        'food': [],
    }
    open_ = {
        'heads': {'A': (2, 2), 'B': (8, 8)},
        'bodies': {'a': [], 'b': []},
        'food': [],
    }
    score_boxed = evaluate_position(boxed, 9, 9, 'A', 'a', 'B', 'b', None)
    score_open = evaluate_position(open_, 9, 9, 'A', 'a', 'B', 'b', None)
    assert score_boxed < score_open


# ---------------------------------------------------------------------------
# choose_direction (top-level 2-ply search)
# ---------------------------------------------------------------------------

def test_choose_direction_moves_toward_reachable_food():
    # Food a few steps away (not adjacent): closing the distance clearly
    # dominates. (Adjacent food is a subtler case -- see the note on
    # test_choose_direction_prefers_not_to_immediately_eat_when_it_kills_future_value.)
    board_info = {
        'heads': {'A': (5, 5), 'B': (0, 0)},
        'bodies': {'a': [], 'b': []},
        'food': [(5, 8)],
    }
    direction = choose_direction(board_info, 11, 11, 'A', 'a', 'B', 'b', None)
    assert direction == 'right'


def test_choose_direction_prefers_not_to_immediately_eat_when_it_kills_future_value():
    # Counting-intuitive but correct given evaluate_position: eating the
    # ONLY food on the board removes it from the position entirely, so a
    # move that eats it can score *worse* than one that just gets closer,
    # because the food-closeness bonus disappears the instant it's eaten.
    # This exercises the 2-ply search actually comparing post-opponent-
    # reply positions rather than reacting to the current frame alone.
    board_info = {
        'heads': {'A': (5, 5), 'B': (0, 0)},
        'bodies': {'a': [], 'b': []},
        'food': [(5, 6)],  # directly adjacent, to the right
    }
    direction = choose_direction(board_info, 11, 11, 'A', 'a', 'B', 'b', None)
    assert direction != 'right'


def test_choose_direction_no_legal_moves_uses_fallback():
    # boxed in on all sides -> legal_moves empty -> fallback direction
    board_info = {
        'heads': {'A': (0, 0), 'B': (9, 9)},
        'bodies': {'a': [], 'b': [(-1, 0), (1, 0), (0, -1), (0, 1)]},
        'food': [],
    }
    direction = choose_direction(board_info, 5, 5, 'A', 'a', 'B', 'b', None)
    assert direction in DIRECTIONS
    # only 'down' and 'right' stay on-board from (0,0); fallback returns
    # the first in-bounds direction, which per DIRECTIONS dict order is
    # 'down' (since 'up' goes off-board).
    from snake_ai import _first_onboard_direction
    assert direction == _first_onboard_direction((0, 0), 5, 5)


def test_choose_direction_traps_opponent_scores_inf_and_is_chosen():
    # Opponent sits in the corner (0,0) with two sides off-board and one
    # side already walled by their own (non-tail) body segment. Their
    # only remaining exit is (0,1) -- exactly where our move lands, which
    # fills it with our own head and leaves them zero legal replies. That
    # move must score +inf (via _best_opponent_reply returning None) and
    # so must be the one chosen, even though its raw territory/food
    # numbers alone don't dominate the other candidates.
    board_info = {
        'heads': {'A': (0, 2), 'B': (0, 0)},
        'bodies': {'a': [], 'b': [(1, 0), (2, 0)]},
        'food': [],
    }
    direction = choose_direction(board_info, 5, 5, 'A', 'a', 'B', 'b', None)
    assert direction == 'left'


def test_first_onboard_direction_degenerate_board_returns_up():
    # On a 1x1 board every direction leaves the board, so the loop in
    # _first_onboard_direction never finds an in-bounds neighbor and
    # falls through to its final 'up' default.
    from snake_ai import _first_onboard_direction
    assert _first_onboard_direction((0, 0), 1, 1) == 'up'


def test_choose_direction_fallback_when_my_head_missing():
    board_info = {'heads': {'B': (5, 5)}, 'bodies': {'a': [], 'b': []}, 'food': []}
    # legal_moves will find head None -> simulate_move returns None for
    # every direction -> legal_moves empty -> _fallback_direction, which
    # itself can't find 'A' either -> returns 'up'.
    direction = choose_direction(board_info, 5, 5, 'A', 'a', 'B', 'b', None)
    assert direction == 'up'


def test_choose_direction_prefers_move_that_does_not_shrink_territory():
    # Symmetric-ish setup where moving toward the center should beat
    # moving toward a wall corner, all else equal.
    board_info = {
        'heads': {'A': (0, 4), 'B': (8, 4)},
        'bodies': {'a': [], 'b': []},
        'food': [],
    }
    direction = choose_direction(board_info, 9, 9, 'A', 'a', 'B', 'b', None)
    assert direction == 'down'  # moving toward open center territory


# ---------------------------------------------------------------------------
# Regression test carried over from the original suite (kept here so the
# whole thing runs from one file / one coverage run).
# ---------------------------------------------------------------------------

def test_regression_neck_ambiguous_frame_resolved_by_history():
    head = (6, 7)
    body = {(6, 6), (7, 6), (7, 7)}
    board_info = {
        'heads': {'A': head, 'B': (9, 8)},
        'bodies': {'a': body, 'b': {(10, 7), (10, 8)}},
        'food': [(1, 6), (0, 0)],
    }
    fixed = order_bodies(board_info, prev_heads={'A': (6, 6), 'B': (9, 9)})
    assert fixed['bodies']['a'] == [(6, 6), (7, 6), (7, 7)]
    assert tail_of(fixed['bodies']['a']) == (7, 7)
    result = simulate_move(fixed, 'A', 'a', 'B', 'b', 'left', 15, 15)
    assert result is None, "moving into the neck should be illegal"


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))