"""
The v3 cyclic "next correct digit" rule, in one place so Board and
GameState don't each carry their own copy of the same logic.
"""


def _predecessor(d):
    return 9 if d == 1 else d - 1


def next_target_digit(digits_present):
    """Given the set of digits currently on the board, return the one
    that must be eaten next (the one whose cyclic predecessor -- 9
    before 1 -- is absent), or None if no digits are present at all."""
    if not digits_present:
        return None
    return next(
        (d for d in range(1, 10)
         if d in digits_present and _predecessor(d) not in digits_present),
        min(digits_present),
    )
