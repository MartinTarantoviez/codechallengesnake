# Snake CodeChallenge Bot

A bot for the two-player, turn-based Snake CodeChallenge
(`wss://server.codechallenge.net.ar/ws`). Connects over a websocket,
auto-accepts challenges, and picks a move every turn using a short
lookahead search over BFS territory control and food/pickup value.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m snake.main <YOUR_BOT_TOKEN>
```

Flags:

- `--board` (alias `--gui`): prints a colored ASCII view of the board each
  turn in the terminal (no display server needed).
- `--local`: connect to `ws://localhost:5000` instead of production.
- `--challenge USERNAME`: send an outgoing challenge on connect. **The
  exact protocol for this isn't documented** (the rules only show the
  server-initiated `challenge` event and the `accept_challenge` reply);
  this sends `{"action": "challenge", "data": {"opponent": USERNAME}}`
  as the best guess and relies on the bot's own error logging (see
  below) to tell you if the server rejects it.

## Project layout

```
snake/
  board.py       Board: parses the raw board string into heads/bodies/
                 food/pickups/walls/tail_food/bombs/stars/shot_food.
                 Knows the v3 cyclic "next correct digit" rule (via
                 digits.py) and v10's per-side inverted head/body
                 drawing while invincible.
  digits.py      The v3 cyclic "next correct digit" rule in one place,
                 shared by Board and GameState so it's never duplicated.
  ordering.py    BodyOrderer: turns each snake's unordered body cells
                 into a neck->tail ordered list. The neck is always the
                 opponent/our own head's position one turn ago (tracked
                 by SnakeBot), never guessed from a single frame -- see
                 the module docstring for why that guess is provably
                 ambiguous in some coiled shapes.
  bfs.py         Generic BFS distance / territory utilities shared by
                 the evaluator and the pickup-rush planner.
  game_state.py  GameState: one turn's ordered snapshot, plus
                 simulate()/legal_moves()/simulate_shoot()/
                 shoot_moves() -- the only place that knows the actual
                 scoring rules (correct digit / wrong digit / pickup /
                 multiplier / crash+tail-food (v7) / bomb explosions
                 (v8) / shooting (v9) / the star and invincibility
                 (v10)).
  evaluator.py   Evaluator: heuristic score for a GameState (territory,
                 target-digit/tail-food/shot-food/star pull, pickup
                 pull, length, exit safety, bomb-proximity safety --
                 the last two skipped while invincible, since neither
                 costs anything then).
  pickup_rush.py PickupPlanner: computes an actual BFS shortest-path
                 route to the single best reachable X pickup or star
                 and steers along it -- see "Pickup strategy" below.
  shooting.py    ShootPlanner: decides whether a v9 shot is worth its
                 flat 5000-point cost right now (a clean, meaningfully
                 damaging hit whose estimated value beats the best
                 ordinary move).
  strategy.py    SnakeStrategy: the 2-ply search (my move -> opponent's
                 best reply) that assembles Evaluator + PickupPlanner +
                 ShootPlanner into a final action (`choose_action`).
  bot.py         SnakeBot: the facade. Owns per-game history (previous
                 heads, multipliers, invincibility) and turns
                 turn_data -> (action, direction).
  client.py      MatchClient + GameLogger: websocket loop and per-game
                 log files, independent of game logic (testable with
                 plain dicts, no network).
  main.py        CLI entry point.
tests/
  test_board.py     board parsing: digits + cyclic target, v4 pickups,
                     v5 walls, v7 tail food, v8 bombs, v9 shot food, v10
                     star + inverted invincible parsing.
  test_ordering.py  neck/tail ordering, including the exact ambiguous
                     coiled-body shape that used to make the bot walk
                     into itself.
  test_strategy.py  scoring rules (grow/penalty/pickup/multiplier/
                     shooting/invincibility) and that the bot actually
                     prefers the correct digit, avoids wrong ones, and
                     shoots/moves sensibly when a safer option exists.
  test_shooting.py  ShootPlanner's shoot-or-not decision in isolation.
  test_coverage.py  full edge-case coverage ported from the pre-refactor
                     test suite: board parsing edge cases, ordering
                     fallbacks, BFS/territory, move legality,
                     evaluation, and choose_direction's search.
  test_bot.py       end-to-end: replays two real recorded matches
                     (logs/) through SnakeBot.choose_move() and asserts
                     it never raises and always returns a legal action.
logs/            Match logs, one per game, written automatically at
                 game_over (git-ignored).
```

Run all tests: `for f in tests/test_*.py; do python3 "$f" || break; done`
(each file is a standalone script with `assert`s and prints `... OK` per
case; no test framework dependency).

Code quality: every function/method/module is cyclomatic-complexity
rank A (`xenon --max-absolute A --max-modules A --max-average A snake/`
passes clean -- 161 blocks, average complexity 2.7). Modules are kept
small and single-purpose specifically so this holds as the rules keep
changing; when adding a new rule, prefer a new small function/module
over growing an existing branch-heavy one.

## Protocol

Each turn arrives as a `your_turn` event; reply with either a `move`
action:

```json
{"action": "move", "data": {"game_id": "...", "turn_token": "...", "direction": "up"}}
```

or, since **v9 (21 Oct 2026)**, a `shoot` action instead (same shape,
same `game_id`/`turn_token`) that costs the current turn's move:

```json
{"action": "shoot", "data": {"game_id": "...", "turn_token": "...", "direction": "right"}}
```

`direction` is one of `up` / `down` / `left` / `right` either way. The
board is a string of `rows` lines wrapped in `|...|`: `A`/`B` are snake
heads, `a`/`b` their bodies, empty is a space -- **except while a side
is invincible (v10)**, when that side's own case is inverted
(lowercase head, UPPERCASE body); see "Star / invincibility" below.
Board size varies per match (each of `rows`/`cols` is 12-20, **20-30
since v8**) -- always read them from `turn_data`, never hardcode 15.

### Food and scoring (current rules, see `docs` link below for the source)

- Surviving a move: **+1**.
- Food is five digits `1`-`9` on the board at once, eaten in ascending
  **cyclic** order (`...,8,9,1,2,...`, no `0`). Eating the correct next
  digit grows you and scores `digit * 100 * your_multiplier`. Eating
  any other digit is a **-500 penalty** (does not end the game) and
  that digit reappears elsewhere. Since **v6 (30 Sep 2026)** each of
  the five digits appears in **several copies** (3-5, random) instead
  of one cell; eating the target consumes *every* copy of that digit
  at once (scores/grows once, for the copy actually landed on) and the
  next digit appears in its own fresh set of copies. A wrong-digit
  copy still only consumes that one cell.
- `X` pickups score a flat **+50** and permanently bump your score
  multiplier (`x2`, then `x3`, ...). The multiplier only applies to
  food points -- not the `+50` itself, not the per-move `+1`, not
  penalties. `X` does **not** grow your snake.
- A single `#` **wall** (v5, since 23 Sep 2026) can be on the board at
  a time: a straight line, odd length up to 11, placed on empty cells.
  After both players have moved, the wall shrinks one cell off each end
  (`11 -> 9 -> 7 -> ... -> 1 -> gone`), then a new one appears elsewhere
  at random. There's no separate field for it -- read the `#` cells
  straight off the board, same as everything else.
- **Crashes (v7, since 7 Oct 2026):** running into the board edge, your
  own body, a `#` wall, or the opponent **no longer ends the game**.
  Matches also got longer: **400 moves** (200 per player) instead of
  300. Instead of dying, a crash:
  - Leaves your snake **in place** that turn (doesn't move, like a
    wall bump always did).
  - **Sheds your tail**: you keep only your first 3 cells (head + 2);
    the rest becomes **tail food** for the opponent. A snake of 3 cells
    or fewer loses nothing.
  - **Wipes your score to 0** on your *first* crash of the match; every
    crash after that is the usual **-500**. If your score is already
    `<= 0` at your first crash, the usual -500 still applies (a crash
    is never a way to launder a negative score, but it still counts as
    your first one).
  - Gives the opponent **nothing** (no more `+1000` for your crash).
  - Falling below **-2500** total still ends the game (you lose).
  - Tail food is drawn as a circled letter -- `Ⓐ` (`U+24B6`) only `A`
    may eat, `Ⓑ` (`U+24B7`) only `B` -- so a crash always feeds the
    *rival*, never the snake that shed it. Eating your own tail food
    scores **+100 x multiplier** and grows you by one cell; it's not
    part of the digit sequence (no penalty for "wrong" tail food) and
    isn't replaced once eaten. The shedding snake can still step on its
    own leftover tail food -- that just **clears it** (no points, no
    growth, a plain survive-the-move), a way to deny it to the rival.
    These are single Unicode characters, not ASCII -- see the "turn_data"
    section below.
- **Bombs (v8, since 14 Oct 2026):** two big bombs (💣, `U+1F4A3`) and
  five small ones (🧨, `U+1F9E8`) sit on the board. You don't have to
  step on one -- it goes off whenever your head *ends a move* within
  **Chebyshev distance 2** of a 💣 or **1** of a 🧨 (diagonals count:
  `distance = max(|Δrow|, |Δcol|)`), i.e. a **5x5** blast square around
  a big bomb and **3x3** around a small one.
  - An explosion **wipes your score to 0** (or the usual **-500** if
    you're already at 0 or negative). Two bombs catching you at once
    only count as **one** explosion.
  - It is **not a crash**: your move happens exactly as normal -- you
    still eat whatever's on the landed cell and keep your tail.
  - The bomb that went off disappears and an identical-size one appears
    elsewhere, **never within range of any head**.
  - Food and `X` never spawn inside a blast square -- everything
    edible can always be eaten without setting anything off.
  - After round 150 (150 moves per player) every bomb vanishes for
    good; the endgame is bomb-free.
  - Board sizes grew to **20-30** per side (was 12-20).
  - 💣/🧨 sit **outside the Unicode BMP** (unlike every other board
    character) -- split board rows by *code point*, not UTF-16 unit:
    `Array.from(row)` in JS, `row.codePoints()` in Java, `[]rune(row)`
    in Go. Python's `str` already iterates by code point, so nothing
    special is needed there.
- **Shooting (v9, since 21 Oct 2026):** instead of moving, send a
  `shoot` action with a direction (see Protocol above). It always costs
  a flat **5000 points**, hit or miss -- shooting below 5000 is an
  invalid action (-500, doesn't fire).
  - The shot is **instant** and travels in a straight line from your
    head. It passes straight over your own body, food, `X`, bombs, the
    star and shot food without touching any of it, and stops at the
    board edge, a `#` wall (walls are cover), or the **first** cell
    belonging to the opponent (body or head) -- it can never hit your
    own snake.
  - A hit **cuts the opponent from the impacted cell to the tip of
    their tail**; hitting the head itself cuts their *whole* body,
    leaving them with just the head. Every cut cell becomes **shot
    food** (`*`) that *either* snake may eat for **+100 x their own
    multiplier** (grows one cell, not part of the digit sequence,
    doesn't respawn) -- except any cut cell that lands inside a bomb's
    blast square, which just vanishes instead.
  - Being shot is **not a crash**: no score wipe, doesn't count as a
    first crash, the victim doesn't even move -- they just lose length
    (and may want to race back for their own cut-off tail).
  - An **invincible** target can't be cut at all (v10) -- the shooter
    still pays the 5000.
- **Star / invincibility (v10, since 28 Oct 2026):** a single star
  (⭐, `U+2B50`) can be on the board (never more than one until the
  final frenzy, see below). Eating it works exactly like eating shot
  food (**+100 x multiplier**, grows one cell) and additionally sets
  that side's invincibility counter to **50** of their own turns
  (`invincible_1`/`invincible_2` in `turn_data`; moving, shooting, and
  an invalid action/timeout all count as one of your own turns --
  eating a second star while still invincible just **resets** the
  counter to 50, it doesn't stack). While invincible:
  - A side's head/body **case is inverted** on the board: lowercase
    head (`a`/`b`), UPPERCASE body (`A`/`B`). `Board.from_turn` needs
    to be told which sides are currently inverted (see `bot.py`) or
    it'll misread a body cell as a second head.
  - Running into the board edge, a `#` wall, or your own body costs
    **nothing at all**: no -500, no score wipe, no tail shed, you just
    stay exactly where you were. A bomb's blast and a wrong digit are
    likewise entirely free (still consumes the cell/digit copy as
    usual, just no penalty). An invalid action costs nothing either
    (though 10 timeouts in a row still loses the match).
  - Running **into the opponent's body** cuts them for free, exactly
    like a successful shot, while you simply stay put (no cost to you
    at all, not even a lost turn's movement). The reverse -- a
    non-invincible side running into an invincible one -- is just an
    ordinary crash for whoever moved, *unless they're invincible too*,
    in which case they do the cutting instead.
  - Shots can't cut an invincible snake either (the shooter still pays
    5000).
  - The first star appears after round 20, equidistant from both
    heads (a fair race); while anyone is invincible no new star
    appears; the next one shows up 20 rounds after that invincibility
    ends. In the **final 100 moves** (right as the bombs disappear) a
    "frenzy" fills the board with **10 stars at once**, each replaced
    the instant it's eaten.
- `turn_data` includes `board_size` (`"15x18"`), and from the
  multiplier rule on, `multiplier_1`/`multiplier_2`; from v10,
  `invincible_1`/`invincible_2` (remaining turns, 0 = not invincible).

Full source: the challenge's own `/how-to-play` page (ask whoever set
up your bot token for the current URL -- it's the canonical source and
gets updated when rules change; this README mirrors it as of the rules
version in effect on 2026-10-29 -- **note**: the PDF copy of the rules
in this repo (`Snake — How to play.pdf`) is still only 3 pages (through
v8); v9 and v10 were transcribed from the professor's Slack
announcements (including worked examples -- shooting, wall cover, a
head hit, star invincibility, crashes/ramming while invincible) since
no updated PDF has been saved yet. Worth re-saving a fresh, complete
copy next time the rules page is open.

### Open questions / assumptions worth re-checking

- **Growth on a wrong digit**: the rules doc says eating the wrong
  digit is "a penalty of -500" but doesn't explicitly say whether it
  still grows the snake the way a classic snake-game apple would. This
  bot assumes **no growth** on a wrong digit (only the correct digit
  grows you) since growth is only mentioned for the correct case.
  Worth confirming against a real v3+ match log once one is available,
  and updating `GameState.simulate` if that assumption is wrong.
- **`multiplier_1`/`multiplier_2` -> side mapping**: `turn_data` gives
  the multiplier per player *label* (`player_1`/`player_2`), not per
  side (`A`/`B`). `SnakeBot` assumes `player_1` corresponds to side `A`
  (matches the one example log in the rules doc), cached per game the
  first time both fields are seen. Re-check this mapping once a few
  real v4 matches are logged.
- **Crash/explosion score accounting (v7/v8)**: `GameState` doesn't
  track real cumulative score at all (only relative reward, for the
  lookahead search), so it can't tell a first crash/explosion (wipes to
  0) from a later one (-500) -- both are simplified to the same flat
  penalty (`CRASH_PENALTY` / `EXPLOSION_PENALTY`, both -500) in
  `game_state.py`. This under-counts the true cost of a first one when
  you're sitting on a big lead, but keeps the 2-ply search's relative
  move ranking sound without threading real score through every
  `GameState`. Worth revisiting if the bot starts taking first-hit
  risks it shouldn't.
- **Outgoing challenge protocol** (`--challenge`): unconfirmed, see
  `client.py`'s `challenge_user` docstring.
- **Shoot-value heuristic (v9)**: `ShootPlanner`'s estimate of a cut's
  worth (`shooting.py`'s `CUT_CELL_VALUE`) is an optimistic guess, not
  a real reward -- it assumes we'd actually win the race to every cut
  cell, which won't always hold. Worth retuning once real match logs
  show the bot actually taking shots (or, more likely at first, show
  it correctly declining to).
- **Both sides invincible at once, ramming each other (v10)**: the
  rules text and examples only cover one side being invincible at a
  time; `GameState._advance` resolves a double-invincible head-on
  collision by letting whichever side's `simulate` call runs first cut
  the other (order depends on which snake the 2-ply search is
  evaluating), which is a guess, not a confirmed rule. Rare enough in
  practice that it hasn't seemed worth a real match log yet.

## Strategy

1. **Parse & order.** `Board` classifies every cell; `BodyOrderer` turns
   each snake's body into an exact neck->tail list using last turn's head
   position (unambiguous), falling back to a single-frame heuristic only
   on turn 1.
2. **Simulate.** `GameState.simulate` advances one snake one step and
   returns the real point reward (correct-digit growth+score,
   wrong-digit penalty, pickup score+multiplier bump, tail-food/shot-
   food/star score+growth). Since v7 a crash (wall/body/edge/opponent,
   except a snake's own vacating tail) is no longer fatal: it returns
   `None` only if the snake itself doesn't exist in the state; a crash
   instead leaves the snake in place, sheds its tail, and charges the
   flat crash penalty (see the "Crashes" rule above) -- unless this
   side is invincible (v10), in which case it's entirely free and
   nothing sheds (`GameState._free_stay`). Since v8, landing within a
   bomb's blast square *also* charges that same flat penalty (skipped
   if invincible), but as a normal move (eats the cell, keeps the
   tail). `GameState.simulate_shoot` is the v9 alternative: it never
   moves the head, always costs the flat shooting fee, and cuts the
   opponent's body into shot food on a hit (see "Shooting" above).
3. **Evaluate.** For a resulting position, `Evaluator` scores:
   - **Territory**: simultaneous BFS from both heads (a la Voronoi) --
     more reachable-first cells is safer and keeps options open.
   - **Target digit** value: only the *correct* next digit is chased,
     toward whichever reachable copy (v6) is closest; value decays with
     BFS distance and is zeroed out if the opponent would reach it
     first.
   - **Tail food / shot food / star** value (v7/v9/v10): same shape as
     the target digit -- shot food and the star are open to either
     side, so there's no "mine only" filter the way tail food has.
   - **Pickup (`X`)** value: same decay-with-distance shape, weighted
     lower than food since its main value (permanent multiplier) is
     long-run rather than a one-off score.
   - **Length advantage** and a small **exit penalty** (avoid dead-end
     corridors) -- a crash's tail-shedding naturally shows up here too,
     since it shrinks `len(my_body)`.
   - **Bomb proximity** (v8): a smaller penalty than the real explosion
     reward, so the evaluated position (after both plies) also prefers
     to sit outside every blast square, not just the one step actually
     being chosen right now. Skipped entirely (v10) when this side is
     invincible in the evaluated state, since a blast costs nothing
     then -- same for the exit penalty.
4. **Choose.** `SnakeStrategy.choose_direction` does a 2-ply search:
   for each of our legal moves, assume the opponent then plays *their*
   best reply (by their own evaluation), and score our move as `our
   immediate reward + evaluation of the position after their reply`.
   Picks the best. Since v7 a crash is survivable, `legal_moves` is
   essentially never empty (only if the snake itself is missing from
   the state), so the old "every move is immediately fatal" fallback is
   now effectively dead code kept as a defensive no-op.
5. **Override for a worthwhile pickup or star.** `PickupPlanner`
   separately computes the single most valuable *reachable and
   winnable* `X` pickup or star together (skips a target the opponent
   would get to first, or if there's not enough of the match left to
   cash in a bigger multiplier), then finds the actual BFS-shortest
   safe route to it (treating wrong digits as soft obstacles to route
   around). If that route's own 2-ply score isn't more than a safety
   margin worse than the best move found in step 4, the bot commits to
   that route's next step instead -- this is what lets it actually
   detour for a pickup several cells away, rather than only grabbing
   one that happens to be on the way to something else.
6. **Override for a worthwhile shot (v9).** `SnakeStrategy.choose_action`
   (the real top-level entry point SnakeBot calls, not `choose_direction`)
   asks `ShootPlanner` first: if we can afford the flat 5000-point fee
   (from the real current score in `turn_data`, which `GameState` itself
   never tracks) and some direction cuts at least a few cells off the
   opponent, it estimates that cut's value (every cell is worth up to
   100 x our multiplier as shot food) on top of the usual 2-ply score and
   only shoots if that genuinely beats the best move from step 4 --
   otherwise it falls through to the ordinary move decision.

### Why a separate pickup planner instead of just weighting pickups higher

An earlier version of this bot only gave pickups more weight inside
`Evaluator`. That helps a little, but `Evaluator`'s pull is a
distance-decayed heuristic voted on at a single step of a 2-ply search
-- it nudges the choice when a pickup happens to be nearby, but it
doesn't make the bot *commit* to crossing the board for a distant one,
because the decay washes out the signal well before the bot gets close.
`PickupPlanner` instead computes the actual shortest safe path with BFS
and steers along it every turn (recomputed fresh each turn, so it
re-routes automatically if the board changes), which is what makes a
multi-turn pickup detour actually happen. Measured against two real
recorded matches (see game logs), this raised the number of turns the
bot actively headed toward the best reachable pickup from 54/83 to
66/83 in one match; in the other, the opponent was closer to nearly
every pickup on the board almost the entire game (71/80 turns), so
there wasn't much to gain there regardless of strategy -- the planner
correctly declines to chase a pickup it can't win.

## Requirements

- Python 3.9+
- `websockets` (see `requirements.txt`)
