# Extended experiment analysis

All values below are computed from recorded results.

## Certified tactics

| Variant | Budget | Engine | Objective | Successes / trials | Rate |
|---|---:|---|---|---:|---:|
| enhanced | 0.1s | alphabeta | force_mate | 4 / 6 | 66.7% |
| enhanced | 0.1s | alphabeta | avoid_mate | 4 / 6 | 66.7% |
| enhanced | 0.1s | mcts | force_mate | 11 / 30 | 36.7% |
| enhanced | 0.1s | mcts | avoid_mate | 13 / 30 | 43.3% |
| enhanced | 1s | alphabeta | force_mate | 6 / 6 | 100.0% |
| enhanced | 1s | alphabeta | avoid_mate | 6 / 6 | 100.0% |
| enhanced | 1s | mcts | force_mate | 0 / 30 | 0.0% |
| enhanced | 1s | mcts | avoid_mate | 3 / 30 | 10.0% |
| enhanced | 5s | alphabeta | force_mate | 6 / 6 | 100.0% |
| enhanced | 5s | alphabeta | avoid_mate | 6 / 6 | 100.0% |
| enhanced | 5s | mcts | force_mate | 1 / 30 | 3.3% |
| enhanced | 5s | mcts | avoid_mate | 4 / 30 | 13.3% |
| baseline | 0.1s | alphabeta | force_mate | 0 / 6 | 0.0% |
| baseline | 0.1s | alphabeta | avoid_mate | 3 / 6 | 50.0% |
| baseline | 0.1s | mcts | force_mate | 2 / 30 | 6.7% |
| baseline | 0.1s | mcts | avoid_mate | 14 / 30 | 46.7% |
| baseline | 1s | alphabeta | force_mate | 6 / 6 | 100.0% |
| baseline | 1s | alphabeta | avoid_mate | 5 / 6 | 83.3% |
| baseline | 1s | mcts | force_mate | 2 / 30 | 6.7% |
| baseline | 1s | mcts | avoid_mate | 10 / 30 | 33.3% |

## Paired games

| Budget | Starts | Games | Alpha wins / draws / losses | Score | Capped draws |
|---:|---:|---:|---|---:|---:|
| 0.5s | 8 | 16 | 10 / 6 / 0 | 81.2% | 3 |
| 5s | 2 | 4 | 4 / 0 / 0 | 100.0% | 0 |

## Interpretation

The certified objective measures fast forced mate or survival within a short bound. Failure is not proof that a move loses the full game.

Alpha-beta prefers shorter proven mates. MCTS rewards terminal wins equally and uses a material-sensitive cutoff, so a slower material gain may score well in simulations.

Baseline/enhanced changes several features together. The budget series, seeds and mirrors are repeated diagnostics, not independent population samples.

The 0.5s and 5s game subsets use different starts; their aggregate scores do not isolate the effect of thinking time.

## Auditable 5s examples (MCTS seed 7)

| Position | Accepted UCI moves | Alpha-beta | MCTS |
|---|---|---|---|
| Corner net / force_mate / original | a4a1, a4c6, a4e4 | a4a1 (passes) | a4a1 (passes) |
| Corner net / avoid_mate / original | h1h2, h8f8, h8h2 | h8f8 (passes) | h8f8 (passes) |
| Unique queen maneuver / force_mate / original | e3e7 | e3e7 (passes) | e3g1 (fails bounded objective) |
| Unique queen maneuver / avoid_mate / original | d8c8, g1c1, g1d1, g1e1, g1g6, g1g7 | g1d1 (passes) | g1g7 (passes) |
| Narrow rook defense / force_mate / original | c4c1 | c4c1 (passes) | c4a2 (fails bounded objective) |
| Narrow rook defense / avoid_mate / original | d7d1, d7g7 | d7g7 (passes) | d7d8 (fails bounded objective) |
