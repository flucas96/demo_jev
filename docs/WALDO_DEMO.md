# Spot on: human vs LLM, then Jev

Open `/waldo` for the playground, `/waldo/presentation` for the guided game, or
`/waldo/referenzen` to review and correct scoring regions. All game UI is in English.
The game and demo hub use Eraneos' public visual identity: Mona Sans, Eraneos Display,
warm paper, dark ink, and orange accents.

## Play

Click Waldo on the human board. A hit earns +1 and a miss −1; three misses or an
explicit skip advance the image. Arrow keys position a keyboard cursor; Enter submits it.
In the playground, select any gateway vision model (default Claude Opus 5.5) or Jev for
a standalone round. Changing the model ends the current round and keeps its partial record.
The result screen offers **Choose another model**.

Presentation mode uses a dark arcade layout: LLM first, then an automatic scroll transition
to Jev’s ready screen. **Start the game** opens the arena without starting a round.
Each round waits for its **Start round 1** or **Start round 2** button before the three-second
countdown. Waiting never starts the game or makes model calls. Live metrics stay visible;
standings and charts are revealed only after both rounds. Reduced-motion preferences
disable animated scrolling. Jev locates Waldo with the `box` primitive; gateway models
return JSON coordinates.
Both AIs get one attempt per image, immediately moving on after a miss or malformed box.
Both players see the same unmarked image
bytes in the same shuffled order, advancing independently. The default duel lasts
60 seconds, configurable from 15 to 180 seconds. The server rejects late answers.

Both rounds share a server-generated seed, duration, and reference fingerprint. Editing
references between rounds requires a new comparison. Jev can also be played alone.
The display shows scores, accuracy, calls, API response time, and cost.
Accuracy is hits / (hits + misses); skips count as misses, transport errors do not.
Correct AI answers and human attempts have a 450 ms feedback pause, excluded from API
response time. Wrong AI answers advance without that pause.

## Gateway and leaderboard

Configure `AI_GATEWAY_API_KEY` and optionally `AI_GATEWAY_BASE_URL` in the ignored `.env`.
The default endpoint is `https://ai-gateway.eraneos.com/v1`. The server checks `/models`
and shows accessible models with known vision capabilities. Each request uses
`/chat/completions`, the exact JPEG as a data URI, and a short instruction to return
left/top/right/bottom normalized to 0–1. The output limit is 256 tokens. No position hints,
reference boxes, previous attempts, or generated confidence claims are supplied.

Gateway cost comes from `x-litellm-response-cost`, which includes cache charges. Without
that header, input/output list prices from the supplied 2026-10-15 catalogue give an
estimate. The Cost column shows the amount without grey billing-source captions; hover
text explains the calculation. Unknown usage is not shown as zero cost. Errors and pending calls are marked as
potentially unbilled in the displayed subtotal; cancelling a request does not guarantee
the provider stops billing. Jev still uses the input-token estimate described below.

SQLite stores server-scored runs in `.local/waldo.sqlite3`, ignored by Git. Set
`WALDO_HISTORY_PATH` to move it. Each run is saved once; only completed rounds advance
the comparison. Stopped, disconnected, and failed runs remain visible without rank.
The leaderboard shows the latest 500 records, filtered by equal duration and ranked by
points and accuracy, with separate human and model rows. Ties retain chronological order.
It stores no API keys or image payloads. Two scatter charts show points on the y-axis and
average response time or cost on the x-axis. Higher and further left is better.
Each provider logo represents one completed model run; inspect it by hover or keyboard
focus. Unknown metrics are omitted, and partial
costs are marked. Charts use the most recent 30 completed runs at the selected duration.
Humans are absent from these model charts because their response time is not recorded.

This interactive comparison has limitations: the human can recognize images in round two,
different comparisons use different shuffled orders, and gateway caching affects costs
and latency. The history is local demo data, not an authenticated competitive service.

## Sixty images

The deck mixes twelve generated illustrations with 48 composited variants. The latter
place one transparent Waldo sprite into reviewed ground positions on eleven generated
backgrounds. Scale and placement match each scene's perspective; seeded jitter and
mirroring vary the figure. Easier and crowded scenes are mixed, with no difficulty selector.
A seeded scheduler alternates backgrounds, so consecutive scenes never share the same
background, even across a deck wrap. Both competitors receive the identical schedule.
All packaged images are 1568×882 baseline JPEGs. Each has exactly one target.

Sources, sprite, prompts, and placement configuration are in
[`generated-sources`](../backend/jev_demo/assets/waldo/generated-sources/).
The built-in Imagegen tool created the illustrations and transparent sprite, and removed
the original target from each background plate. Pillow places the sprite and transforms
its body/head boxes together, so the reference coordinates follow the actual pixels.

The generation prompts are saved in `prompts.json`, `prompts-crowds.json`, and
`prompts-composition.json`. `catalog.json` contains the twelve manually reviewed source
annotations; `composition.json` controls the other 48 placements and the seed.

```sh
uv run python scripts/prepare_generated_waldo.py
```

This prepares the sixty images before the server starts. A match shuffles that prepared
deck; it does not generate new images or placements during play. Changing the seed or
placements and rerunning the script produces new variants and image identities. Existing
user corrections are preserved for unchanged images; regenerated images receive new IDs.
No scans from the original puzzle books are included in the public repository.

## Model contract

- Model: `jev-1.14.0`, with `TypeSafe-Danger-Zone-Images: true`.
- Question: ``{"type":"box","instructions":"Where is Waldo in `scene`?"}``.
- `scene` references a UUID-keyed inline JPEG asset. No location hints, reference boxes,
  filenames, scores, or annotations go to Jev.
- The returned normalized box and confidence are displayed without moving the answer.
- Network errors pause Jev rather than inventing an answer or deducting a point.
- Cost uses reported input tokens at $0.042 per million, including image tokens;
  output is free. Failed, cancelled, or unpriced calls can make the estimate partial.

## Tolerant scoring and corrections

A human click anywhere inside the visible-body box expanded by 20% on each side counts.
Each model's raw answer is expanded by 30% of its width/height on each side, clipped to the image.
That expanded box must cover at least 50% of the head, while at least 55% of the raw box
must lie inside the body with its 20% tolerance. This accepts head-only and loose body
answers while rejecting whole-scene guesses. Confidence does not change the score.

The reference editor shows the head in green, body in blue, and body tolerance in dashed
orange. Select an image, choose head or body, draw a replacement box, and save. The head
must lie inside the body. Saving is blocked during a match. Corrections are atomically
saved in `backend/jev_demo/assets/waldo/reviewed-annotations.json` and survive restarts.
The editor deliberately reveals solutions for this local demo; the normal catalog and
all model requests omit them.

## Validation and sources

Tests cover click scoring, double submission, late answers, box tolerance, image transport,
coordinate transforms, transparent sprite composition, reproducibility, and saved corrections.
The twelve original generated scenes each passed a single live Jev smoke test; the clear
six returned in 360–840 ms, and the crowded six in 515–1,244 ms. These small local checks
are not a general accuracy or speed benchmark.

- Generated art: built-in Imagegen; Waldo/Wally character created by Martin Handford.
- [Eraneos](https://www.eraneos.com/): public logo, fonts, and design colors.
- [TypeSafe Box](https://docs.typesafe.ai/primitives/box),
  [image contract](https://docs.typesafe.ai/images), and
  [model pricing](https://docs.typesafe.ai/models), checked 2026-10-15.

## Model identity assets

TypeSafe’s icon is from its [public website](https://typesafe.ai/). Claude, Gemini, and
OpenAI icons are from [Lobe Icons](https://github.com/lobehub/lobe-icons), bundled locally
with its MIT license. They identify providers, not endorsements. Files live in
`frontend/public/brand/models/`. The hero uses the existing transparent generated sprite.
