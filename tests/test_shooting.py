import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snake.game_state import GameState, SHOT_COST
from snake.shooting import ShootPlanner, MIN_CUT_CELLS


def _state(heads, bodies=None):
    return GameState(9, 12, heads, bodies or {'a': [], 'b': []}, {}, [])


def _always_zero(_new_state, _reward):
    return 0.0


def test_suggest_none_when_cannot_afford_it():
    state = _state({'A': (4, 0), 'B': (4, 8)}, {'a': [], 'b': [(4, 7), (4, 6), (4, 5)]})
    planner = ShootPlanner('A', 'B')
    assert planner.suggest(state, SHOT_COST - 1, _always_zero, -999.0) is None
    print('test_suggest_none_when_cannot_afford_it: OK')


def test_suggest_none_when_every_shot_misses():
    # B at (1, 1) is off both of A's firing lines (row 4, column 0).
    state = _state({'A': (4, 0), 'B': (1, 1)})
    planner = ShootPlanner('A', 'B')
    assert planner.suggest(state, SHOT_COST, _always_zero, -999.0) is None
    print('test_suggest_none_when_every_shot_misses: OK')


def test_suggest_none_when_cut_is_too_small():
    # Only one cell gets cut -- below MIN_CUT_CELLS, not worth 5000.
    state = _state({'A': (4, 0), 'B': (4, 4)}, {'a': [], 'b': [(4, 3)]})
    planner = ShootPlanner('A', 'B')
    assert planner.suggest(state, SHOT_COST, _always_zero, -999.0) is None
    print('test_suggest_none_when_cut_is_too_small: OK')


def _big_cut_state():
    # B's head sits off row 4 (at (3, 3)); its neck is the closest body
    # cell to A along the line of fire, so the shot hits index 0 and
    # cuts the whole 4-cell body (kept=[]) -- a clean, big hit.
    return _state({'A': (4, 0), 'B': (3, 3)},
                   {'a': [], 'b': [(4, 3), (4, 4), (4, 5), (4, 6)]})


def test_suggest_direction_when_a_big_cut_beats_the_best_move():
    # score_fn always returns 0.0, which beats best_move_score -999.0.
    planner = ShootPlanner('A', 'B')
    assert planner.suggest(_big_cut_state(), SHOT_COST, _always_zero, -999.0) == 'right'
    print('test_suggest_direction_when_a_big_cut_beats_the_best_move: OK')


def test_suggest_none_when_not_better_than_the_best_move():
    # Same big cut, but the best ordinary move already scores higher.
    planner = ShootPlanner('A', 'B')
    assert planner.suggest(_big_cut_state(), SHOT_COST, _always_zero, 999.0) is None
    print('test_suggest_none_when_not_better_than_the_best_move: OK')


def test_min_cut_cells_is_at_least_a_couple_of_segments():
    # Sanity check on the tuning constant itself, not just behavior.
    assert MIN_CUT_CELLS >= 2
    print('test_min_cut_cells_is_at_least_a_couple_of_segments: OK')


if __name__ == '__main__':
    test_suggest_none_when_cannot_afford_it()
    test_suggest_none_when_every_shot_misses()
    test_suggest_none_when_cut_is_too_small()
    test_suggest_direction_when_a_big_cut_beats_the_best_move()
    test_suggest_none_when_not_better_than_the_best_move()
    test_min_cut_cells_is_at_least_a_couple_of_segments()
    print('ALL SHOOTING TESTS PASSED')
