# Jev Decision Lab

A Jira-first developer demo for turning text into typed decisions with [Jev](https://typesafe.ai/).
Python owns inference, validation, and application policy. React and Mantine provide the
workbench. All model results are live; nothing silently substitutes canned answers.

## Quick start

You need Git, [uv](https://docs.astral.sh/uv/), [Node.js](https://nodejs.org/) 22.12+
(or a newer supported LTS, including npm), and a TypeSafe API key with access to Jev.
Python 3.14 is installed automatically by uv if needed. No database, Docker, or Jira
account is required. The 60 Waldo images are included; you do not need to generate them.

### Download and install

```sh
git clone https://github.com/flucas96/demo_jev.git
cd demo_jev
uv sync --locked --python 3.14
npm --prefix frontend ci
cp .env.example .env
```

The copy command is for a fresh checkout. Keep an existing `.env` when updating.
Open `.env` in your editor and replace the placeholder with your own key:

```dotenv
TYPESAFE_API_KEY=your-typesafe-api-key
TYPESAFE_MODEL=jev-latest
```

The key stays on the Python server. `.env` is ignored by Git and is never included in
the browser bundle. Waldo pins `jev-1.14.0` for image and box support; the text demos
use `TYPESAFE_MODEL`. Starting an AI game or evaluating tickets makes paid API calls.

### Start the demo

Run these commands from the repository root:

```sh
npm --prefix frontend run build
uv run jev-demo
```

Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)**. Keep the terminal running;
press **Ctrl+C** to stop the server.

| Demo | Address |
| --- | --- |
| Demo hub | [localhost:8000](http://127.0.0.1:8000/) |
| Waldo: human vs Jev | [localhost:8000/waldo](http://127.0.0.1:8000/waldo) |
| Jira triage | [localhost:8000/#queue](http://127.0.0.1:8000/#queue) |
| Lantern Run | [localhost:8000/#runner](http://127.0.0.1:8000/#runner) |
| Snake | [localhost:8000/#snake](http://127.0.0.1:8000/#snake) |
| Python API docs | [localhost:8000/docs](http://127.0.0.1:8000/docs) |

### Development mode

For automatic reloads while editing, stop the single-process server and run:

```sh
uv run python scripts/dev.py
```

Open [localhost:5173](http://127.0.0.1:5173). This starts the React development server
on port 5173 and the Python API on port 8000. Ctrl+C stops both.

### Troubleshooting

- **Missing API key:** check `.env` in the repository root and restart the server after
  editing it. `/api/health` reports whether a key is configured, not whether it is valid.
- **TypeSafe rejects the key or model:** check your key, account access, and available
  credit. Waldo requires image and box access for `jev-1.14.0`.
- **The homepage returns 404:** run `npm --prefix frontend run build`, then restart
  `uv run jev-demo`. The backend discovers the built frontend at startup.
- **Port already in use:** stop the previous demo process before starting another one.
- **Changes do not appear:** rebuild and restart, or use development mode.

## Spot on: human vs Jev

The Eraneos demo hub links to [the Waldo game](http://127.0.0.1:8000/waldo).
Humans click Waldo in generated search scenes; Jev uses image input and the `box`
primitive on `jev-1.14.0`. Live metrics show response time, calls, accuracy, and estimated cost.
The default match lasts 60 seconds, configurable from 15 to 180 seconds.
Sixty generated 1568×882 images mix twelve original compositions with 48 seeded placement
variants across eleven backgrounds. Clear and crowded scenes are shuffled together for each match.
The target is inserted into reviewed ground positions, and its reference boxes follow the same transform.

[Reference review](http://127.0.0.1:8000/waldo/referenzen) shows and edits the exact
scoring regions. Saved corrections persist across restarts and update both views of
the scene. See [the game guide](docs/WALDO_DEMO.md) for scoring, resources, and validation.

## What it demonstrates

The Jira demo has a queue of **20 distinct fictional Jira tickets**. Run 5, 10, or
20 tickets and watch each decision arrive. Enable **Parallel requests** to process
all selected tickets concurrently, with up to 20 Python workers. Uncheck it to process
the same queue sequentially with one worker.
Each ticket makes one real TypeSafe request containing Choice, Score, and Noul.
Parallel tickets are separate HTTP requests; the three questions within a ticket are
evaluated together by Jev. Nothing is precomputed or replayed as a live result.

The queue highlights **throughput** in successful tickets per second and **estimated cost**.
The API also reports batch duration, median and p95 request latency, observed maximum
in-flight tickets, and token usage.
Click a ticket to inspect its input, model outputs, routing policy, and exact payload.
The single-ticket workbench and other examples remain available separately.

| Scenario | Choice | Score | Noul |
| --- | --- | --- | --- |
| Jira ticket triage | Owning team | Customer impact, 0–4 | P(active production outage) |
| Reply verification | Supported / contradicted / insufficient | Factual support, 0–4 | P(unsupported factual claim) |
| Runbook relevance | Mitigation / diagnostic / background / irrelevant | Relevance, 0–4 | P(component match) |

In the single-ticket workbench, choose one of 11 examples or paste your own text. Run all three independent
questions in one call, inspect the complete distributions, and move the confidence
threshold to replay **Python policy without another Jev call**. Inspect the actual
request, raw model response, and executable Python integration.

Runbook relevance judges one supplied incident/runbook pair at a time. It does not
retrieve documents or execute a runbook. Replies are evaluated, never generated or
sent. Jira assignment and incident escalation are simulated destinations.

## Lantern Run

The **Lantern Run** tab is a continuous 2D runner set in pixel-art Kyoto at dusk.
Jev chooses upright, jump, or duck from text geometry as random obstacles approach.
Jev is queried continuously, one request at a time, and actions execute as responses arrive. Earn distance points upright, fewer while ducking,
and none while jumping. **Endless** gradually accelerates by 0.1× every 10 real seconds
until all three hearts are lost. **60 seconds** keeps the timed run and live 0.5×–2× speed control. Switch to manual controls, replay the same seed,
and inspect real decisions, deadlines, cost, and collisions.
Open [the game](http://127.0.0.1:8000/#runner) and see [the runner guide](docs/LANTERN_RUN.md).

## The important semantics

- **Choice** selects one named option and returns its full distribution and confidence.
- **Score** returns the probability-weighted mean of ordered rubric positions, not an
  invented numerical rating. A 0–4 scale has five descriptive levels.
- **Noul** returns P(yes) between 0 and 1, with no separate confidence field.
- Confidence summarizes the model's distribution; it is not the chance a particular
  answer is correct. Production thresholds require evaluation against representative data.
- Jev does not generate the prose in the policy panel. These explanations come directly
  from deterministic Python rules.
- The displayed round-trip time measures the Python-to-TypeSafe request, including
  network time. Token counts come from the API. It is not a benchmark or inference-only latency.

The local API uses `jev-latest` by default and displays the resolved model from each
response. Pin `TYPESAFE_MODEL` to a version when comparing runs or tuning thresholds.
Text is sent to TypeSafe when you evaluate a ticket or start a batch. Errors remain visible and
do not trigger hidden retries, substitute results, or external actions. Starting a batch
submits the selected tickets to TypeSafe. Stopping the stream cancels local workers;
requests already received by TypeSafe may still be processed and billed.

### Reading the speed display

- Batch duration runs from server-side batch start until all requested tickets have
  succeeded or failed. It includes queueing, network calls, and local validation,
  but excludes browser rendering and final response delivery.
- Throughput is **successful tickets ÷ batch duration**. Failures are counted separately.
- Per-ticket latency is the Python-to-TypeSafe round trip, including network time;
  it is not inference-only latency. p50 is the median and p95 uses the nearest-rank method.
- Latency and token totals include successful responses only. Missing latency and cost
  estimates remain empty when no tickets succeed.
- Concurrency is a local worker limit, not a guarantee of backend model execution timing.
  Account limits, network conditions, and contention can change observed performance.
- A sequential/parallel comparison is meaningful only for the same tickets and model.
  Run both modes to measure a speedup; do not multiply one ticket's latency into a claimed baseline.

### Reading estimated cost

The API does not return a billed cost. Python estimates USD from successful responses'
reported input tokens and the resolved model ID. For `jev-1.13.0` and `jev-1.14.0`, the published price
is **$0.042 per million input tokens**, with free output tokens; verified on
**2026-10-15** against [TypeSafe's model pricing](https://docs.typesafe.ai/models).
The three questions share one request, so the estimate does not multiply token usage by three.

Unknown model versions, unresolved aliases, and batches containing different resolved
models have no aggregate estimate. Failed or cancelled requests may still incur charges,
but their missing usage cannot be included. A partial batch estimate therefore covers
only its successful responses and is not a final bill. Update the pinned pricing rule
when published rates change.

## Project structure

```text
backend/jev_demo/
  app.py       FastAPI routes and connection lifecycle
  batch.py     Bounded async workers, NDJSON streaming, and cancellation
  batch_models.py Batch progress events and measured summaries
  catalog.py   Text examples, questions, and rubrics
  tickets.py   Twenty distinct fictional Jira issues
  models.py    Validated request/response models
  policy.py    Deterministic routing and review rules
  pricing.py   Published input-token cost estimate for known model versions
  service.py   Async TypeSafe HTTP adapter
frontend/      React + TypeScript + Mantine workbench
tests/         Policy and transport boundary tests
scripts/dev.py Both development servers in one command
docs/DEMO.md   Presentation narrative and extensions
```

`POST /api/evaluate` makes one outbound TypeSafe request. `POST /api/policy` only applies
local rules to an existing response. `GET /api/health` indicates whether a key is
configured, not whether TypeSafe has accepted it. `GET /api/scenarios` exposes all
presets and their exact questions.

`GET /api/triage/tickets` returns the Jira queue. `POST /api/triage/batch` accepts
`ticket_ids`, `concurrency` (1–20, default 20), and `threshold`, then streams newline-delimited JSON.
The interface sends the selected ticket count when **Parallel requests** is checked
and one when it is unchecked; the API also accepts intermediate worker limits.
Events announce batch start, ticket start, ticket success/failure, and a final summary.
The endpoint validates the full selection before making any upstream request and
never repeats a ticket within one batch.

This is a local demo with no database or authentication. It binds to loopback and uses
same-origin requests. Add access controls and request budgets before hosting a shared
instance. No real Jira connector is configured.

## Checks

```sh
uv run ruff check .
uv run basedpyright
uv run pytest
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

## Reference

[TypeSafe API](https://docs.typesafe.ai/api) ·
[Choice](https://docs.typesafe.ai/primitives/choice) ·
[Score](https://docs.typesafe.ai/primitives/score) ·
[Noul](https://docs.typesafe.ai/primitives/noul) ·
[Confidence](https://docs.typesafe.ai/confidence)
