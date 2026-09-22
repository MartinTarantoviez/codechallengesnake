"""
Coverage test suite ported from the pre-refactor test_snake_ai_coverage.py
(which tested the old function-based snake_ai.py) onto the new OOP
classes: Board, BodyOrderer, GameState, Evaluator, SnakeStrategy.

Mirrors the same sections/order as the original for easy comparison:
  - board parsing
  - body ordering (neck -> tail)
  - BFS / voronoi territory
  - move simulation / legality
  - evaluation
  - top-level choose_direction (2-ply search)

A few tests changed shape because the API changed on purpose:
  - food is now a dict {pos: digit_or_None} instead of a list of
    positions (needed for the v3 "correct digit" rule) -- tests that
    only cared about *legality*, not scoring, use `None` values
    (legacy '*' semantics: any food cell is "correct").
  - simulate_move/legal_moves/order_bodies are now GameState/BodyOrderer
    methods that take/return GameState objects or plain dicts of
    ordered bodies, not one big board_info dict.
  - one old test (`ignores unknown characters`, using digit '7' as the
    "unknown/ignored" example) no longer applies: digits are now
    meaningful food (see the v3 rule), so it's replaced with a version
    that checks a genuinely unknown character ('#') is still ignored
    while confirming a digit *is* now picked up as food.

Run: python tests/test_coverage.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snake.board import Board, parse_grid, neighbors4
from snake.ordering import (
    order_body_heuristic, order_body_from_neck, tail_of, BodyOrderer,
)
from snake.game_state import GameState, DIRECTIONS
from snake.strategy import in_bounds, bfs_distances, voronoi_territory, Evaluator, SnakeStrategy

_FAILURES = []


def check(name, condition):
    print(f'{name}: {"OK" if condition else "FAILED"}')
    if not condition:
        _FAILURES.append(name)
    assert condition, name  # so pytest (and CI) actually detects a failure here


# ---------------------------------------------------------------------------
# Board parsing
# ---------------------------------------------------------------------------

def test_parse_grid_strips_pipes_and_keeps_content():
    grid = parse_grid("|A  |\n| b |\n|  *|", 3, 3)
    check('test_parse_grid_strips_pipes_and_keeps_content',
          grid == [['A', ' ', ' '], [' ', 'b', ' '], [' ', ' ', '*']])


def test_parse_grid_without_pipes():
    grid = parse_grid("A \n b", 2, 2)
    check('test_parse_grid_without_pipes',
          grid[0] == ['A', ' '] and grid[1] == [' ', 'b'])


def test_parse_grid_pads_short_rows():
    grid = parse_grid("|A|", 1, 4)
    check('test_parse_grid_pads_short_rows', grid == [['A', ' ', ' ', ' ']])


def test_parse_grid_truncates_long_rows():
    grid = parse_grid("|ABCDEF|", 1, 3)
    check('test_parse_grid_truncates_long_rows', grid == [['A', 'B', 'C']])


def test_parse_grid_pads_missing_rows():
    grid = parse_grid("|A |", 3, 2)
    check('test_parse_grid_pads_missing_rows',
          len(grid) == 3 and grid[0] == ['A', ' ']
          and grid[1] == [' ', ' '] and grid[2] == [' ', ' '])


def test_parse_grid_ignores_empty_lines():
    grid = parse_grid("|A |\n\n|B |\n", 2, 2)
    check('test_parse_grid_ignores_empty_lines',
          grid[0] == ['A', ' '] and grid[1] == ['B', ' '])


def test_parse_grid_truncates_extra_rows():
    grid = parse_grid("|A|\n|B|\n|C|", 2, 1)
    check('test_parse_grid_truncates_extra_rows', grid == [['A'], ['B']])


def test_board_classifies_all_cell_types_legacy_star():
    b = Board.from_turn("|Aa*|\n| bB|", 2, 3)
    check('test_board_classifies_all_cell_types_legacy_star',
          b.heads == {'A': (0, 0), 'B': (1, 2)}
          and b.bodies == {'a': {(0, 1)}, 'b': {(1, 1)}}
          and b.food == {(0, 2): None})


def test_board_ignores_unknown_chars_but_now_picks_up_digits_as_food():
    # '#' is genuinely unknown -> ignored. '7' used to be "ignored" in
    # the pre-v3 test, but digits are now real food (v3 rule) -> must be
    # picked up as food[pos] == 7, not silently dropped.
    b = Board.from_turn("|#A|\n|7 |", 2, 2)
    check('test_board_ignores_unknown_chars_but_now_picks_up_digits_as_food',
          b.heads == {'A': (0, 1)} and b.bodies == {}
          and b.food == {(1, 0): 7})


def test_board_empty_board():
    b = Board.from_turn("|  |\n|  |", 2, 2)
    check('test_board_empty_board',
          b.heads == {} and b.bodies == {} and b.food == {} and b.pickups == [])


def test_in_bounds():
    check('test_in_bounds',
          in_bounds((0, 0), 5, 5) is True
          and in_bounds((4, 4), 5, 5) is True
          and in_bounds((-1, 0), 5, 5) is False
          and in_bounds((0, -1), 5, 5) is False
          and in_bounds((5, 0), 5, 5) is False
          and in_bounds((0, 5), 5, 5) is False)


def test_neighbors4():
    check('test_neighbors4',
          set(neighbors4((2, 2))) == {(1, 2), (3, 2), (2, 1), (2, 3)})


# ---------------------------------------------------------------------------
# Body ordering
# ---------------------------------------------------------------------------

def test_order_body_heuristic_empty_body():
    check('test_order_body_heuristic_empty_body',
          order_body_heuristic((0, 0), set()) == [])


def test_order_body_heuristic_straight_line():
    ordered = order_body_heuristic((5, 5), {(5, 4), (5, 3), (5, 2)})
    check('test_order_body_heuristic_straight_line',
          ordered == [(5, 4), (5, 3), (5, 2)])


def test_order_body_heuristic_single_segment():
    check('test_order_body_heuristic_single_segment',
          order_body_heuristic((0, 0), {(0, 1)}) == [(0, 1)])


def test_order_body_heuristic_coiled_path():
    ordered = order_body_heuristic((2, 2), {(2, 1), (1, 1), (1, 2), (1, 3)})
    check('test_order_body_heuristic_coiled_path',
          ordered[0] == (2, 1) and ordered[-1] == (1, 3) and len(ordered) == 4)


def test_order_body_heuristic_no_neck_candidate_uses_any_endpoint():
    ordered = order_body_heuristic((0, 0), {(5, 5), (5, 6)})
    check('test_order_body_heuristic_no_neck_candidate_uses_any_endpoint',
          set(ordered) == {(5, 5), (5, 6)} and len(ordered) == 2)


def test_order_body_heuristic_single_cell_no_endpoint_branch():
    check('test_order_body_heuristic_single_cell_no_endpoint_branch',
          order_body_heuristic((9, 9), {(0, 0)}) == [(0, 0)])


def test_order_body_heuristic_closed_loop_has_no_endpoint():
    body = {(0, 0), (0, 1), (1, 0), (1, 1)}
    ordered = order_body_heuristic((5, 5), body)
    check('test_order_body_heuristic_closed_loop_has_no_endpoint',
          set(ordered) == body and len(ordered) == 4)


def test_order_body_from_neck_valid():
    ordered = order_body_from_neck((6, 6), {(6, 6), (7, 6), (7, 7)})
    check('test_order_body_from_neck_valid',
          ordered == [(6, 6), (7, 6), (7, 7)])


def test_order_body_from_neck_neck_not_in_body_returns_empty():
    check('test_order_body_from_neck_neck_not_in_body_returns_empty',
          order_body_from_neck((9, 9), {(1, 1), (1, 2)}) == [])


def test_tail_of():
    check('test_tail_of',
          tail_of([(1, 1), (2, 2)]) == (2, 2)
          and tail_of([]) is None
          and tail_of([(0, 0)]) == (0, 0))


def test_order_bodies_uses_prev_head_when_valid():
    bodies = BodyOrderer.order_all(
        heads={'A': (6, 7), 'B': (9, 8)},
        bodies={'a': {(6, 6), (7, 6), (7, 7)}, 'b': {(10, 7), (10, 8)}},
        prev_heads={'A': (6, 6), 'B': (9, 9)},
    )
    check('test_order_bodies_uses_prev_head_when_valid',
          bodies['a'] == [(6, 6), (7, 6), (7, 7)])


def test_order_bodies_falls_back_when_prev_head_not_in_body():
    bodies = BodyOrderer.order_all(
        heads={'A': (5, 5)}, bodies={'a': {(5, 4), (5, 3)}},
        prev_heads={'A': (99, 99)},
    )
    check('test_order_bodies_falls_back_when_prev_head_not_in_body',
          bodies['a'] == [(5, 4), (5, 3)])


def test_order_bodies_falls_back_when_ordered_length_mismatches():
    # prev_head is a real body cell but the MIDDLE of the path, not a
    # true endpoint -> walking from it dead-ends early both ways ->
    # length mismatch -> falls back to the heuristic (which, given the
    # real head, recovers the full correct order).
    bodies = BodyOrderer.order_all(
        heads={'A': (5, 5)}, bodies={'a': {(5, 4), (5, 3), (5, 2)}},
        prev_heads={'A': (5, 3)},
    )
    check('test_order_bodies_falls_back_when_ordered_length_mismatches',
          bodies['a'] == [(5, 4), (5, 3), (5, 2)])


def test_order_bodies_no_prev_heads_arg():
    bodies = BodyOrderer.order_all(
        heads={'A': (5, 5), 'B': (0, 0)},
        bodies={'a': {(5, 4), (5, 3)}, 'b': set()},
        prev_heads=None,
    )
    check('test_order_bodies_no_prev_heads_arg',
          bodies['a'] == [(5, 4), (5, 3)] and bodies['b'] == [])


def test_order_bodies_empty_body_short_circuits():
    bodies = BodyOrderer.order_all(
        heads={'A': (0, 0)}, bodies={}, prev_heads={'A': (1, 1)},
    )
    check('test_order_bodies_empty_body_short_circuits', bodies['a'] == [])


# ---------------------------------------------------------------------------
# BFS / voronoi territory
# ---------------------------------------------------------------------------

def test_bfs_distances_open_field():
    dist = bfs_distances((0, 0), set(), 3, 3)
    check('test_bfs_distances_open_field',
          dist[(0, 0)] == 0 and dist[(0, 1)] == 1 and dist[(2, 2)] == 4)


def test_bfs_distances_respects_obstacles():
    dist = bfs_distances((0, 0), {(0, 1), (1, 0)}, 2, 2)
    check('test_bfs_distances_respects_obstacles',
          (1, 1) not in dist and dist == {(0, 0): 0})


def test_bfs_distances_does_not_revisit():
    dist = bfs_distances((1, 1), set(), 3, 3)
    check('test_bfs_distances_does_not_revisit', len(dist) == 9)


def test_voronoi_territory_symmetric_split():
    my_t, opp_t, dist_me, dist_opp = voronoi_territory((0, 0), (0, 2), set(), 1, 3)
    check('test_voronoi_territory_symmetric_split',
          my_t == 1 and opp_t == 1 and dist_me[(0, 0)] == 0 and dist_opp[(0, 2)] == 0)


def test_voronoi_territory_no_opponent_head():
    my_t, opp_t, _dm, dist_opp = voronoi_territory((0, 0), None, set(), 2, 2)
    check('test_voronoi_territory_no_opponent_head',
          opp_t == 0 and dist_opp == {} and my_t == 4)


# ---------------------------------------------------------------------------
# Move simulation / legality (GameState.simulate / legal_moves)
# ---------------------------------------------------------------------------

def _state(me_head, me_body, opp_head=None, opp_body=None, food=None,
           rows=5, cols=5):
    heads = {'A': me_head}
    if opp_head is not None:
        heads['B'] = opp_head
    bodies = {'a': list(me_body), 'b': list(opp_body or [])}
    food_dict = {pos: None for pos in (food or [])}  # legacy '*'-style food
    return GameState(rows, cols, heads, bodies, food_dict, [])


def test_simulate_out_of_bounds_returns_none():
    new_state, _r = _state((0, 0), []).simulate('A', 'B', 'up')
    check('test_simulate_out_of_bounds_returns_none', new_state is None)


def test_simulate_missing_head_returns_none():
    state = GameState(5, 5, {}, {}, {}, [])
    new_state, _r = state.simulate('A', 'B', 'up')
    check('test_simulate_missing_head_returns_none', new_state is None)


def test_simulate_into_own_body_is_fatal():
    new_state, _r = _state((2, 2), [(1, 2), (0, 2)]).simulate('A', 'B', 'up')
    check('test_simulate_into_own_body_is_fatal', new_state is None)


def test_simulate_into_own_tail_without_eating_is_legal():
    # ordered neck->tail: head (2,2), neck (2,3), mid (1,3), tail (1,2).
    # Tail sits directly "up" from head; a non-growing move always
    # vacates the tail, so moving into it must be legal.
    new_state, _r = _state((2, 2), [(2, 3), (1, 3), (1, 2)]).simulate('A', 'B', 'up')
    check('test_simulate_into_own_tail_without_eating_is_legal',
          new_state is not None and new_state.heads['A'] == (1, 2)
          and new_state.bodies['a'] == [(2, 2), (2, 3), (1, 3)])


def test_simulate_growing_into_own_tail_cell_is_also_legal():
    state = _state((2, 2), [(2, 3), (1, 3), (1, 2)], food=[(1, 2)])
    new_state, _r = state.simulate('A', 'B', 'up')
    check('test_simulate_growing_into_own_tail_cell_is_also_legal',
          new_state is not None
          and new_state.bodies['a'] == [(2, 2), (2, 3), (1, 3), (1, 2)])


def test_simulate_head_on_collision_with_opponent_head_is_fatal():
    new_state, _r = _state((2, 2), [], opp_head=(1, 2), opp_body=[]).simulate('A', 'B', 'up')
    check('test_simulate_head_on_collision_with_opponent_head_is_fatal', new_state is None)


def test_simulate_into_opponent_body_is_fatal():
    new_state, _r = _state((2, 2), [], opp_head=(9, 9), opp_body=[(1, 2)]).simulate('A', 'B', 'up')
    check('test_simulate_into_opponent_body_is_fatal', new_state is None)


def test_simulate_eats_food_grows_and_removes_food():
    state = _state((2, 2), [(2, 1)], food=[(1, 2), (5, 5)])
    new_state, reward = state.simulate('A', 'B', 'up')
    check('test_simulate_eats_food_grows_and_removes_food',
          new_state is not None and new_state.heads['A'] == (1, 2)
          and new_state.bodies['a'] == [(2, 2), (2, 1)]
          and new_state.food == {(5, 5): None} and reward == 100.0)


def test_simulate_normal_shift_without_food():
    state = _state((2, 2), [(2, 1), (2, 0)])
    new_state, _r = state.simulate('A', 'B', 'up')
    check('test_simulate_normal_shift_without_food',
          new_state.bodies['a'] == [(2, 2), (2, 1)])


def test_legal_moves_filters_fatal_directions():
    state = _state((2, 2), [], opp_head=(9, 9), opp_body=[(1, 2), (3, 2), (2, 1)])
    dirs = {d for d, _s, _r in state.legal_moves('A', 'B')}
    check('test_legal_moves_filters_fatal_directions', dirs == {'right'})


def test_legal_moves_empty_when_fully_boxed_in():
    state = _state((0, 0), [], opp_body=[(-1, 0), (1, 0), (0, -1), (0, 1)])
    moves = state.legal_moves('A', 'B')
    check('test_legal_moves_empty_when_fully_boxed_in', moves == [])


# ---------------------------------------------------------------------------
# Evaluation (Evaluator)
# ---------------------------------------------------------------------------

def test_evaluate_missing_my_head_is_neg_inf():
    state = GameState(5, 5, {'B': (0, 0)}, {}, {}, [])
    check('test_evaluate_missing_my_head_is_neg_inf',
          Evaluator('A', 'B').evaluate(state) == float('-inf'))


def test_evaluate_missing_opp_head_is_pos_inf():
    state = GameState(5, 5, {'A': (0, 0)}, {}, {}, [])
    check('test_evaluate_missing_opp_head_is_pos_inf',
          Evaluator('A', 'B').evaluate(state) == float('inf'))


def test_evaluate_prefers_more_territory():
    state = GameState(9, 9, {'A': (0, 0), 'B': (4, 4)}, {'a': [], 'b': []}, {}, [])
    check('test_evaluate_prefers_more_territory',
          Evaluator('A', 'B').evaluate(state) < 0)


def test_evaluate_endgame_weighting_differs_from_midgame():
    heads, bodies, food = {'A': (0, 0), 'B': (8, 8)}, {'a': [], 'b': []}, {(0, 1): None}
    ev = Evaluator('A', 'B')
    mid = ev.evaluate(GameState(9, 9, heads, bodies, food, [], remaining_moves=200))
    end = ev.evaluate(GameState(9, 9, heads, bodies, food, [], remaining_moves=10))
    check('test_evaluate_endgame_weighting_differs_from_midgame', mid != end)


def test_evaluate_unreachable_food_contributes_nothing():
    heads = {'A': (0, 0), 'B': (8, 8)}
    bodies = {'a': [], 'b': [(0, 1), (1, 0), (1, 1)]}
    ev = Evaluator('A', 'B')
    walled = ev.evaluate(GameState(10, 10, heads, bodies, {(9, 9): None}, []))
    none_ = ev.evaluate(GameState(10, 10, heads, bodies, {}, []))
    check('test_evaluate_unreachable_food_contributes_nothing', walled == none_)


def test_evaluate_food_contested_and_won_by_opponent_scores_zero_term():
    heads = {'A': (0, 0), 'B': (0, 2)}
    bodies = {'a': [], 'b': []}
    ev = Evaluator('A', 'B')
    with_food = ev.evaluate(GameState(1, 5, heads, bodies, {(0, 2): None}, []))
    without_food = ev.evaluate(GameState(1, 5, heads, bodies, {}, []))
    check('test_evaluate_food_contested_and_won_by_opponent_scores_zero_term',
          with_food == without_food)


def test_evaluate_length_advantage_matters():
    heads = {'A': (2, 2), 'B': (2, 6)}
    ev = Evaluator('A', 'B')
    short = ev.evaluate(GameState(9, 9, heads,
                                   {'a': [], 'b': [(2, 5), (2, 4), (2, 3)]}, {}, []))
    long_ = ev.evaluate(GameState(9, 9, heads,
                                   {'a': [(2, 1), (2, 0)], 'b': [(2, 5), (2, 4), (2, 3)]}, {}, []))
    check('test_evaluate_length_advantage_matters', long_ > short)


def test_evaluate_exit_penalty_applies_when_boxed():
    heads = {'A': (2, 2), 'B': (8, 8)}
    ev = Evaluator('A', 'B')
    boxed = ev.evaluate(GameState(9, 9, heads,
                                   {'a': [], 'b': [(1, 2), (3, 2), (2, 1), (9, 9)]}, {}, []))
    open_ = ev.evaluate(GameState(9, 9, heads, {'a': [], 'b': []}, {}, []))
    check('test_evaluate_exit_penalty_applies_when_boxed', boxed < open_)


# ---------------------------------------------------------------------------
# choose_direction (SnakeStrategy's 2-ply search)
# ---------------------------------------------------------------------------

def test_choose_direction_moves_toward_reachable_food():
    state = GameState(11, 11, {'A': (5, 5), 'B': (0, 0)}, {'a': [], 'b': []},
                       {(5, 8): None}, [])
    direction = SnakeStrategy('A', 'B').choose_direction(state)
    check('test_choose_direction_moves_toward_reachable_food', direction == 'right')


def test_choose_direction_eats_adjacent_food_now_that_real_reward_counts():
    # Old behavior (pre-refactor) avoided eating the ONLY adjacent food,
    # because the old search had no notion of real score reward -- it
    # only compared a proximity heuristic, which zeroed out the instant
    # the food was eaten (nothing left to be "close to"), making eating
    # look paradoxically worse than approaching. The new SnakeStrategy
    # adds the real immediate reward (+100 here) into the search score,
    # so a genuinely scoring move now correctly wins over a purely
    # heuristic territory/proximity edge. This is an intentional
    # improvement, not a regression -- see game_state.py's reward
    # tracking and strategy.py's _score_my_move.
    state = GameState(11, 11, {'A': (5, 5), 'B': (0, 0)}, {'a': [], 'b': []},
                       {(5, 6): None}, [])
    direction = SnakeStrategy('A', 'B').choose_direction(state)
    check('test_choose_direction_eats_adjacent_food_now_that_real_reward_counts',
          direction == 'right')


def test_choose_direction_no_legal_moves_uses_fallback():
    state = GameState(5, 5, {'A': (0, 0), 'B': (9, 9)},
                       {'a': [], 'b': [(-1, 0), (1, 0), (0, -1), (0, 1)]}, {}, [])
    direction = SnakeStrategy('A', 'B').choose_direction(state)
    # only 'down'/'right' stay on-board from (0,0); DIRECTIONS dict order
    # is up, down, left, right, and 'up' is off-board -> 'down' first.
    check('test_choose_direction_no_legal_moves_uses_fallback',
          direction in DIRECTIONS and direction == 'down')


def test_choose_direction_traps_opponent_scores_inf_and_is_chosen():
    # Opponent in the corner (0,0), already walled on one side by their
    # own body, with (0,1) as their only remaining exit -- exactly where
    # our move lands, leaving them zero legal replies (+inf for us).
    state = GameState(5, 5, {'A': (0, 2), 'B': (0, 0)},
                       {'a': [], 'b': [(1, 0), (2, 0)]}, {}, [])
    direction = SnakeStrategy('A', 'B').choose_direction(state)
    check('test_choose_direction_traps_opponent_scores_inf_and_is_chosen',
          direction == 'left')


def test_choose_direction_fallback_when_my_head_missing():
    state = GameState(5, 5, {'B': (5, 5)}, {'a': [], 'b': []}, {}, [])
    direction = SnakeStrategy('A', 'B').choose_direction(state)
    check('test_choose_direction_fallback_when_my_head_missing', direction == 'up')


def test_choose_direction_prefers_move_that_does_not_shrink_territory():
    state = GameState(9, 9, {'A': (0, 4), 'B': (8, 4)}, {'a': [], 'b': []}, {}, [])
    direction = SnakeStrategy('A', 'B').choose_direction(state)
    check('test_choose_direction_prefers_move_that_does_not_shrink_territory',
          direction == 'down')


def test_fallback_direction_degenerate_board_returns_up():
    # On a 1x1 board every direction leaves the board.
    state = GameState(1, 1, {'A': (0, 0)}, {'a': [], 'b': []}, {}, [])
    direction = SnakeStrategy('A', 'B')._fallback_direction(state)
    check('test_fallback_direction_degenerate_board_returns_up', direction == 'up')


def test_evaluate_pickup_reachable_and_winnable_adds_positive_pull():
    heads = {'A': (0, 0), 'B': (8, 8)}
    ev = Evaluator('A', 'B')
    with_pickup = ev.evaluate(GameState(9, 9, heads, {'a': [], 'b': []}, {}, [(0, 3)]))
    without_pickup = ev.evaluate(GameState(9, 9, heads, {'a': [], 'b': []}, {}, []))
    check('test_evaluate_pickup_reachable_and_winnable_adds_positive_pull',
          with_pickup > without_pickup)


def test_board_in_bounds():
    b = Board.from_turn("|A |\n|  |", 2, 2)
    check('test_board_in_bounds',
          b.in_bounds((0, 0)) is True and b.in_bounds((-1, 0)) is False
          and b.in_bounds((2, 0)) is False)



ALL_TESTS = [
    test_parse_grid_strips_pipes_and_keeps_content,
    test_parse_grid_without_pipes,
    test_parse_grid_pads_short_rows,
    test_parse_grid_truncates_long_rows,
    test_parse_grid_pads_missing_rows,
    test_parse_grid_ignores_empty_lines,
    test_parse_grid_truncates_extra_rows,
    test_board_classifies_all_cell_types_legacy_star,
    test_board_ignores_unknown_chars_but_now_picks_up_digits_as_food,
    test_board_empty_board,
    test_in_bounds,
    test_neighbors4,
    test_order_body_heuristic_empty_body,
    test_order_body_heuristic_straight_line,
    test_order_body_heuristic_single_segment,
    test_order_body_heuristic_coiled_path,
    test_order_body_heuristic_no_neck_candidate_uses_any_endpoint,
    test_order_body_heuristic_single_cell_no_endpoint_branch,
    test_order_body_heuristic_closed_loop_has_no_endpoint,
    test_order_body_from_neck_valid,
    test_order_body_from_neck_neck_not_in_body_returns_empty,
    test_tail_of,
    test_order_bodies_uses_prev_head_when_valid,
    test_order_bodies_falls_back_when_prev_head_not_in_body,
    test_order_bodies_falls_back_when_ordered_length_mismatches,
    test_order_bodies_no_prev_heads_arg,
    test_order_bodies_empty_body_short_circuits,
    test_bfs_distances_open_field,
    test_bfs_distances_respects_obstacles,
    test_bfs_distances_does_not_revisit,
    test_voronoi_territory_symmetric_split,
    test_voronoi_territory_no_opponent_head,
    test_simulate_out_of_bounds_returns_none,
    test_simulate_missing_head_returns_none,
    test_simulate_into_own_body_is_fatal,
    test_simulate_into_own_tail_without_eating_is_legal,
    test_simulate_growing_into_own_tail_cell_is_also_legal,
    test_simulate_head_on_collision_with_opponent_head_is_fatal,
    test_simulate_into_opponent_body_is_fatal,
    test_simulate_eats_food_grows_and_removes_food,
    test_simulate_normal_shift_without_food,
    test_legal_moves_filters_fatal_directions,
    test_legal_moves_empty_when_fully_boxed_in,
    test_evaluate_missing_my_head_is_neg_inf,
    test_evaluate_missing_opp_head_is_pos_inf,
    test_evaluate_prefers_more_territory,
    test_evaluate_endgame_weighting_differs_from_midgame,
    test_evaluate_unreachable_food_contributes_nothing,
    test_evaluate_food_contested_and_won_by_opponent_scores_zero_term,
    test_evaluate_length_advantage_matters,
    test_evaluate_exit_penalty_applies_when_boxed,
    test_choose_direction_moves_toward_reachable_food,
    test_choose_direction_eats_adjacent_food_now_that_real_reward_counts,
    test_choose_direction_no_legal_moves_uses_fallback,
    test_choose_direction_traps_opponent_scores_inf_and_is_chosen,
    test_choose_direction_fallback_when_my_head_missing,
    test_choose_direction_prefers_move_that_does_not_shrink_territory,
    test_fallback_direction_degenerate_board_returns_up,
    test_evaluate_pickup_reachable_and_winnable_adds_positive_pull,
    test_board_in_bounds,
]


if __name__ == '__main__':
    for t in ALL_TESTS:
        try:
            t()
        except AssertionError:
            pass  # already recorded in _FAILURES by check(); keep going
    if _FAILURES:
        print(f'\n{len(_FAILURES)} FAILED: {_FAILURES}')
        sys.exit(1)
    print(f'\nALL {len(ALL_TESTS)} COVERAGE TESTS PASSED')
