# Spot on: human vs Jev

Open `/waldo`, or `/waldo/referenzen` to review and correct scoring regions.
The game and demo hub use Eraneos' public visual identity: Mona Sans, Eraneos Display,
warm paper, dark ink, and orange accents.

## Play

Click Waldo on the human board. A hit earns +1 and a miss −1; three misses or an
explicit skip advance the image. Arrow keys position a keyboard cursor; Enter submits it.
Jev locates Waldo with the `box` primitive. Both players see the same unmarked image
bytes in the same shuffled order, advancing independently. The default duel lasts
60 seconds, configurable from 15 to 180 seconds. The server rejects late answers.

The display shows scores, accuracy, calls, API response time, and estimated cost.
Accuracy is hits / (hits + misses); skips count as misses, transport errors do not.
The 450 ms feedback pause is excluded from API response time.

## Sixty images

The deck mixes twelve generated illustrations with 48 composited variants. The latter
place one transparent Waldo sprite into reviewed ground positions on eleven generated
backgrounds. Scale and placement match each scene's perspective; seeded jitter and
mirroring vary the figure. Easier and crowded scenes are mixed, with no difficulty selector.
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
Jev's raw answer is expanded by 30% of its width/height on each side, clipped to the image.
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
