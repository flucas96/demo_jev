# Lantern Run

Open `http://127.0.0.1:8000/#runner`, or select **Lantern Run** in the workbench navigation. The existing Jira queue is still available.

Choose **Jev plays** for live inference or **You play** for manual control. **Endless** is selected by default and has no time limit: it ends when all three hearts are lost. Choose **60 seconds** for the original timed round. Crates, hanging bamboo screens, clear stretches, sizes, and spacing are randomly generated as the course advances. The first obstacle starts beyond the right edge, and one following encounter is generated ahead of time so obstacles scroll into view without popping in. Every course has a seed; **Replay seed** repeats its geometry, including after switching controllers.

The denser course uses 2.5–2.8 game seconds between encounters, with 45% crates, 45% overhead screens, and 10% clear stretches. Across 200 seeds, physical obstacles in the first 60 game seconds increased from 9.315 to 19.305 on average (2.07×); see `artifacts/runner-density.json`. The spacing leaves room for a full jump and keeps newly generated obstacles off-screen. Seeds remain reproducible within this generator version; density changes alter courses from earlier versions.

Manual controls apply immediately during the decision window: ↑ or Space to jump, ↓ to duck, → to remain upright. The three on-screen buttons also work. Actions begin as soon as the control or Jev response arrives. Upright earns **1 point per metre travelled**, ducking earns **0.2 points per metre**, and jumping earns **zero**. Selecting a move awards nothing. Collisions subtract 25 points and one life. Duck stays active until another move is selected; jumps last 1.8 game seconds before landing upright.

The **Speed** slider runs from **0.5× to 2×**. In timed mode it can change before or during a round. In Endless mode it sets the starting speed; the server then increases speed continuously by **0.1× every 10 real seconds**, without a 2× ceiling. The slider is disabled during an Endless run so the challenge cannot be reset. Speed scales movement, jump animation, and game time continuously. It does not scale the displayed API response time. Faster play leaves less wall time for Jev to respond. Distance and points do not jump when changing speed. One metre corresponds to ten scene pixels.


## Architecture

- `backend/jev_demo/runner/world.py`: deterministic seeded generation, 60 Hz fixed-step physics, collisions, deadlines, scoring, and private reference decisions.
- `backend/jev_demo/runner/inference.py`: one typed Choice question per request, validated action distribution, shared HTTP transport.
- `backend/jev_demo/runner/session.py`: WebSocket frames at 20 Hz and concurrent inference with cancellation.
- `frontend/src/runner/`: React controls and a Canvas renderer. Interpolation affects pixels only; Python decides outcomes.
- `frontend/public/runner/kyoto-dusk.png`: generated background. Courier, obstacles, and ground are original code-drawn pixel shapes. Prompt provenance is in `docs/concepts/runner-background-prompt.txt`.

Jev receives **text only**: obstacle kind, dimensions, passage clearance, distant/approaching/crossing phase, body dimensions, jump height and duration, current posture, game time until contact and until fully passed, and reward rules. Clear road has no phantom obstacle countdown. It does not receive screenshots or the private evaluator's answer. The Choice criteria explain each move's physical purpose. The model's actual choice drives the runner, including incorrect choices.

Jev is queried continuously, including on empty road and while obstacles are far away. Each answer starts the next request immediately with a fresh snapshot; exactly one provider request is in flight. The snapshot includes time to contact, current posture, and remaining jump time. There is no wait for an obstacle decision window. Failed calls retry after a short 0.5-second backoff; successful calls have no deliberate delay.

Responses apply immediately. Repeated jump commands continue the existing arc, and responses describing a jump or obstacle that has already finished are discarded. A stale response still contributes its real usage and latency. Python does not substitute a better action. The inspector keeps the latest completed request paired with its corresponding response, plus total request/response counts.

A jump response targeting a different, approaching crate can start a new jump if the previous arc lands while the request is in flight. The server tracks which encounter started each arc, so it can distinguish the next crate's jump from an expired continuation of the previous jump.

The prompt gives nearby overhead clearance priority over continuing a jump. Stand and duck cancel an airborne jump immediately in the existing physics; the instructions now describe this explicitly. A screen's top height is distinguished from its open passage underneath. Distant obstacles do not require an immediate avoidance move. These are input and instruction changes, with no model-weight training or rules-based replacement of Jev's output.

Obstacle urgency also anticipates response arrival. The server smooths measured API round-trip time (70% previous estimate, 30% latest response), starting with a 300 ms estimate. It converts that delay to game time using the current pace and marks an obstacle approaching when contact is expected within 0.9 game seconds of response arrival. Observations retain both the raw and estimated arrival-time countdowns. This gives the jump time to rise while keeping actions immediate, requests sequential, and collision physics unchanged. Unusually delayed answers or very high speeds can still cause collisions; crate timing failures are labelled **Jump too late** or **Landed too soon** in the history.

The manual controls retain their near-obstacle decision window. Both modes run physics independently from inference. Late moves can collide; speed changes do not rescale measured API latency.


A failed request is recorded separately from a valid but incorrect choice. Hidden tabs, disconnected clients, and severe server stalls end the run. Only one local runner session may be active at a time. Endless has no timer-based ending; Stop, closing the tab, and connection failures still end the active session.


## Inspecting results

**Under the hood** shows the seed, reported token usage, resolved model, last response latency, complete request/validated response, and the latest 50 per-encounter outcomes. Storage is bounded for long Endless runs; score, collisions, usage, and decision totals cover the entire run. Reference actions appear only after an encounter resolves. End-of-run metrics count optimal choices against all presented encounters; answered encounters count resolved encounters with an applied action. Interrupted rounds can include an unresolved presented encounter.

Cost is an estimate using existing model pricing and reported usage, not a billing receipt. Aborted requests may have unreported provider charges; unknown model pricing shows a dash. Rewards score the demonstration; they do not train Jev. Confidence describes the returned distribution, not measured reliability.

## Validation

Run `uv run ruff check backend tests`, `uv run basedpyright`, `uv run pytest -q`, `npm --prefix frontend run typecheck`, and `npm --prefix frontend run build`. Tests use fake credentials and mocked provider responses. Live smoke-test results for clear road, a ground block, a low screen, and a high screen are in `artifacts/runner-smoke.json`; these examples are not a benchmark.

Before the immediate-action revision, on 2026-09-23 all 87 automated tests and strict Python/TypeScript checks passed. A final live smoke run selected the expected action for six cases (clear road, two crate sizes, two low screens, and a high screen), with observed round-trip times of 278–462 ms. These checks validate the integration, not general model accuracy. Desktop and 390-pixel mobile layouts, manual buttons, keyboard duck, stop, and seeded replay were checked in the browser.

The revised suite also checks immediate pose changes, response latency causing collisions, distance-only scoring, persistent ducking, speed changes without position jumps, and live speed commands.

The immediate-action revision passes 99 tests plus lint, strict Python types, TypeScript checks, and a production frontend build. A live browser round changed from 1× to 2× without restarting: 15 on-time decisions, 14 collision-free optimal decisions, one collision, and 441 distance points over 720 m. See `artifacts/runner-realtime-check.json`. The desktop and mobile speed controls were visually reviewed.

Endless validation: 103 automated tests pass, including survival past the old time limit, termination at the third collision, continuous acceleration independent of frame rate, bounded long-run history, and rejection of manual speed overrides during Endless runs.

Continuous-control and edge-entry validation: 110 tests pass, along with Ruff, strict Python types, TypeScript checks, and the production build. Tests cover sequential requests before the first obstacle, fresh posture snapshots, repeated jumps retaining their original arc, expired jump responses, and continuous obstacle positions at 0.5× through 4×. A live browser run showed 16 completed responses with request 17 in flight after about five seconds; desktop and 390-pixel mobile layouts were visually reviewed. This verifies the request loop and presentation, not model accuracy.

Prompt clarification validation: 116 automated tests, Ruff, and strict Python checks pass. The opt-in `uv run python scripts/runner_eval.py --output artifacts/runner-eval.json` sends 17 fixed snapshots twice using the configured API. It covers clear/distant road, nearby crates, low/high screens, active crossings, and different current postures. The original prompt matched 26/34 expected choices; an intermediate revision matched 30/34; the final revision matched 34/34. Requests, real model responses, and timings are recorded in `artifacts/runner-prompt-before.json`, `artifacts/runner-prompt-after.json`, and `artifacts/runner-prompt-final.json`. These cases were used during tuning and are not an independent accuracy benchmark or guarantee of collision-free play.

A live Endless browser check on seed 1286777811 completed six encounters: both low screens were ducked successfully, both clear stretches used upright, and both crates received jump choices. Five encounters were collision-free; one crate still collided despite a jump choice. The run was stopped manually after 305 m with two hearts remaining. Correct action classification alone does not guarantee that its arrival and animation timing will avoid every collision.

After response-time compensation, 123 automated tests pass, including deterministic replays with 300–500 ms response delays and a 2× speed case, plus a test preserving genuine late-jump collisions and their timing explanation. Ruff, strict Python/TypeScript checks, and the frontend build pass. All 17 live prompt regression cases returned the expected choice (`artifacts/runner-latency-prompt.json`). A live WebSocket replay of seed 1286777811 cleared its first six encounters, including the previously colliding fifth crate, with three hearts remaining after 291.4 m and 67 Jev responses (`artifacts/runner-latency-replay.json`).
