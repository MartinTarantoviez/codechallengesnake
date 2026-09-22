import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snake.board import Board


def _mk(rows_str, rows, cols):
    return Board.from_turn(rows_str, rows, cols)


def test_legacy_star_food_has_no_target_digit():
    board_str = "|A * |\n|    |\n|    |\n|    |"
    b = _mk(board_str, 4, 4)
    assert (0, 2) in b.food and b.food[(0, 2)] is None
    assert b.target_digit() is None
    print('test_legacy_star_food_has_no_target_digit: OK')


def test_digits_parsed_and_target_is_cyclic_gap():
    # digits 8,9,1,2,3 present -> predecessor of 8 (=7) absent -> target 8
    board_str = "|8  9|\n|1   |\n|2   |\n|3   |"
    b = _mk(board_str, 4, 4)
    assert b.food == {(0, 0): 8, (0, 3): 9, (1, 0): 1, (2, 0): 2, (3, 0): 3}
    assert b.target_digit() == 8
    print('test_digits_parsed_and_target_is_cyclic_gap: OK')


def test_digits_simple_ascending_window():
    # 1,2,3,4,5 present -> predecessor of 1 is 9 (absent) -> target 1
    board_str = "|1234|\n|5   |\n|    |\n|    |"
    b = _mk(board_str, 4, 4)
    assert b.target_digit() == 1
    print('test_digits_simple_ascending_window: OK')


def test_pickup_parsed_separately_from_food():
    board_str = "|A X |\n|    |\n|    |\n|    |"
    b = _mk(board_str, 4, 4)
    assert (0, 2) in b.pickups
    assert (0, 2) not in b.food
    print('test_pickup_parsed_separately_from_food: OK')


def test_heads_and_bodies_parsed():
    board_str = "|Aab |\n|    |\n|    |\n|   B|"
    b = _mk(board_str, 4, 4)
    assert b.heads == {'A': (0, 0), 'B': (3, 3)}
    assert b.bodies['a'] == {(0, 1)}
    assert b.bodies['b'] == {(0, 2)}
    print('test_heads_and_bodies_parsed: OK')


if __name__ == '__main__':
    test_legacy_star_food_has_no_target_digit()
    test_digits_parsed_and_target_is_cyclic_gap()
    test_digits_simple_ascending_window()
    test_pickup_parsed_separately_from_food()
    test_heads_and_bodies_parsed()
    print('ALL BOARD TESTS PASSED')
