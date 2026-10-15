# Snake observation comparison

Run: 2026-09-24T08:52:37.405400+00:00 · model: `jev-1.13.0`

## Finding

Adding factual adjacent-cell contents was the only tested variant to improve immediate collision avoidance overall. Formatting and more explicit fixed rules alone did not improve the baseline in this experiment. All variants retained the full board and four possible actions. No action filtering, pathfinding, suggested direction, or computed safety label was sent to Jev.

## Method

280 real API calls: seven variants × 20 identical board snapshots × two repeats. Snapshots cover five situations, each rotated through four orientations. Call order was shuffled with a fixed seed; up to four calls were in flight. No transport or validation errors occurred. All snapshots were checked for contiguous, non-overlapping bodies, valid headings, food outside the snake, and at least one legal move.

Legal means the selected move avoids an immediate wall/body collision, allowing entry into the departing tail. Food progress means a legal move reduces Manhattan distance to food; it is scored only on the 12 boards (24 repeated evaluations) where such a move exists. This deliberately does not claim that greedily approaching food is always optimal. The game engine scored outputs after inference.

| Input variant | Legal moves | Food progress on eligible boards | Median round trip |
| --- | ---: | ---: | ---: |
| Current compact ASCII | 24/40 | 22/24 | 337 ms |
| Spaces between cells | 22/40 | 21/24 | 339 ms |
| H head + separate heading | 22/40 | 14/24 | 367 ms |
| Spaced row/column labels | 24/40 | 20/24 | 341 ms |
| Explicit rules per direction | 24/40 | 22/24 | 336 ms |
| All board/rule changes combined | 22/40 | 14/24 | 370 ms |
| Combined + adjacent-cell contents | 40/40 | 20/24 | 325 ms |

## Collision breakdown

| Variant | Food ahead | Food behind | Wall turn | Body detour | Tail exit |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current compact ASCII | 8/8 | 2/8 | 6/8 | 0/8 | 8/8 |
| Spaces between cells | 8/8 | 1/8 | 5/8 | 0/8 | 8/8 |
| H head + separate heading | 8/8 | 8/8 | 2/8 | 0/8 | 4/8 |
| Spaced row/column labels | 8/8 | 4/8 | 6/8 | 0/8 | 6/8 |
| Explicit rules per direction | 8/8 | 2/8 | 6/8 | 0/8 | 8/8 |
| All board/rule changes combined | 8/8 | 8/8 | 2/8 | 0/8 | 4/8 |
| Combined + adjacent-cell contents | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 |

## Recommendation and limits

Use the board plus a clearly disclosed adjacent-cell description mode if the purpose is to showcase decisions rather than grid parsing. This is preprocessing: it gives the model spatial relationships directly, although it does not select or rank an action. The combined board plus neighbors was tested; neighbors alone were not isolated. Pure board-format changes showed no overall gain.

40/40 is a result on 20 constructed boards, not a guarantee or an independent 40-board test. Rotations and repeats are correlated. This evaluation does not establish full-game performance, avoidance of future traps, or calibrated confidence. A rollout comparison on new seeds would be needed before claiming a better Snake player. The live game input was not modified by this experiment.

Total estimated standard input-token cost: **$0.0090069**, approximately 0.9 US cents. Output tokens are free under the current pricing function.

## Reproduction

```sh
UV_CACHE_DIR=.cache/uv uv run --no-sync python scripts/snake_eval.py --output artifacts/snake-format-eval.json --repeats 2
```

Full exact requests, real responses, token usage, and evaluator-only labels: `artifacts/snake-format-eval.json`. Credentials and HTTP headers are never recorded.
