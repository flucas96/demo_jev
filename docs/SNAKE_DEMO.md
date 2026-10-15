# Snake demo

Open `http://127.0.0.1:8000/#snake` or select Snake in the demo navigation.

Python owns the 10 × 10 board, collisions, growth, and seeded food placement. Each validated
Jev answer moves the snake exactly one cell. The board stays still during inference. There
is no movement timer, automatic forward movement, pathfinder, or safety override.

The model state uses the tested structured observation format: a spaced character board with
row/column labels, `H` for the head, a separate current heading, and the literal contents of
the four neighboring cells. Fixed rules explain `#` (wall), `.` (empty), `*` (food), `o`
(body), and `T` (tail). All four directions remain available. No safety ratings, recommended
moves, or paths are computed for the model. The interface displays the entire state verbatim.

`ObservationFormat` and `format_request` are shared with `scripts/snake_eval.py`. The live
format matches the `combined_with_neighbors` experiment recorded in
`docs/SNAKE_FORMAT_EVALUATION.md`. The result on frozen boards does not guarantee long-term
planning in a full game.

The WebSocket endpoint `/api/snake/play?seed=...` allows one active Snake game. Each answer
is applied before submitting the updated board, with one provider call in flight at a time.
Stop, disconnect, tab hiding, or navigation ends play and cancels outstanding work. Provider
errors stop the run; the application never fabricates a replacement direction.

The interface displays the last sent board, response probabilities and confidence, call
count, actual response time, and cost based on reported usage. The inspector pairs the last
completed request with its response. A pending or cancelled call may incur unreported cost.
Replay repeats the initial board and seeded food sequence; model decisions may differ.

Tests cover food growth, tail movement, boundaries, reversals, full-board completion,
probability validation, request contents, pricing, origin checks, provider failures, and
cancellation. A delayed-inference regression test verifies that waiting never moves the
snake. The response-loop test verifies exactly one attempted move per answer.
