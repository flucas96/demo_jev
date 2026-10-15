"""Publish the measured snapshot as readable GitHub tables and standalone charts."""

from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.text import Annotation, Text
from matplotlib.ticker import FuncFormatter, MaxNLocator
from PIL import Image

from jev_demo.waldo_benchmarks import BenchmarkReport, read_report
from jev_demo.waldo_history import Run

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "benchmarks"
COLORS = ["#ff753e", "#a56ce0", "#268fac", "#c39a28", "#d25c8b", "#478b51", "#5b7fd5"]


def chart(runs: list[Run], measure: Literal["time", "cost"], date: str) -> None:
    """Preserve measured coordinates and separate every model name with connector lines."""
    figure = Figure(figsize=(14, 8.5), dpi=160, facecolor="#111316")
    canvas = FigureCanvasAgg(figure)
    axis = figure.subplots()
    axis.set_position((0.075, 0.18, 0.60, 0.64))
    axis.set_facecolor("#1b1e23")
    _ = figure.add_artist(
        Text(
            0.075,
            0.93,
            "WALDO · 60-SECOND MODEL BENCHMARK",
            transform=figure.transFigure,
            color="#a4a7b0",
            size=11,
        )
    )
    _ = figure.add_artist(
        Text(
            0.075,
            0.875,
            "Score vs. response time" if measure == "time" else "Score vs. cost",
            color="#f7f5f2",
            size=25,
            weight="bold",
            transform=figure.transFigure,
        )
    )
    _ = figure.add_artist(
        Text(
            0.075,
            0.035,
            f"{date} · One parallel run per model · Higher and left is better",
            color="#a4a7b0",
            size=10,
            transform=figure.transFigure,
        )
    )
    axis.yaxis.label.set_text("Points")
    axis.xaxis.label.set_text(
        "Average response (ms)" if measure == "time" else "Total model cost (USD)"
    )
    for label in (axis.xaxis.label, axis.yaxis.label):
        label.set_color("#cbd0da")
        label.set_fontsize(12)
    axis.xaxis.labelpad = axis.yaxis.labelpad = 14
    for spine in axis.spines.values():
        spine.set_visible(False)
    axis.set_axisbelow(True)
    _ = axis.set_ylim(
        min(-5, min(run.score for run in runs) - 5), max(run.score for run in runs) + 10
    )
    values = [run.average_ms if measure == "time" else run.cost_usd for run in runs]
    maximum = max(value for value in values if value is not None)
    _ = axis.set_xlim(-maximum * 0.04, maximum * 1.08)
    axis.xaxis.set_major_locator(MaxNLocator(5))
    axis.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))

    def format_value(value: float, _position: int | None) -> str:
        """Format time and money without losing small measured costs."""
        return f"{value:,.0f}" if measure == "time" else f"${value:.2f}"

    axis.xaxis.set_major_formatter(FuncFormatter(format_value))
    for tick in [*axis.xaxis.get_major_ticks(), *axis.yaxis.get_major_ticks()]:
        tick.label1.set_color("#a4a7b0")
        tick.label1.set_fontsize(10)
        tick.tick1line.set_visible(False)
        tick.set_pad(10)
    for score in axis.get_yticks():
        _ = axis.add_line(
            Line2D(
                [0, 1],
                [float(score), float(score)],
                transform=axis.get_yaxis_transform(),
                color="#353a44",
                linewidth=0.8,
            )
        )
    for index, (run, value) in enumerate(zip(runs, values, strict=True)):
        if value is None:
            continue
        color = COLORS[index % len(COLORS)]
        label_y = 0.95 - index * 0.071
        _ = axis.add_line(
            Line2D(
                [value],
                [run.score],
                marker="o",
                markersize=16,
                color=color,
                markeredgecolor="#111316",
                linestyle="none",
                zorder=4,
            )
        )
        _ = axis.add_artist(
            Text(
                value,
                run.score,
                str(index + 1),
                color="white",
                ha="center",
                va="center",
                size=9,
                weight="bold",
                zorder=5,
            )
        )
        annotation = Annotation(
            f"{index + 1:02d}   {run.label}",
            xy=(value, run.score),
            xycoords="data",
            xytext=(1.07, label_y),
            textcoords="axes fraction",
            color="#f7f5f2",
            size=11,
            va="center",
            annotation_clip=False,
            arrowprops={
                "arrowstyle": "-",
                "color": color,
                "linewidth": 1,
                "alpha": 0.65,
                "relpos": (0, 0.5),
            },
        )
        annotation.set_clip_on(False)
        _ = axis.add_artist(annotation)
    canvas.draw()
    image = Image.frombytes("RGBA", canvas.get_width_height(), bytes(canvas.buffer_rgba()))
    image.save(OUTPUT / f"score-{measure}.png")


def table(report: BenchmarkReport) -> str:
    """Keep failed models in the report while only ranking completed measurements."""
    lines = [
        "| Model | Points | Accuracy | Avg. response | Cost | Calls |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    results = sorted(
        report.results,
        key=lambda result: (
            result.status != "completed",
            -(result.run.score if result.run else 0),
        ),
    )
    for result in results:
        run = result.run
        if result.status != "completed" or run is None:
            lines.append(
                f"| {result.label} | — | Unavailable | — | Unknown | {run.calls if run else 0} |"
            )
            continue
        attempts = run.hits + run.misses
        accuracy = f"{run.hits / attempts:.0%}" if attempts else "—"
        cost = f"${run.cost_usd:.6f}" if run.cost_usd is not None else "—"
        response = f"{run.average_ms:,.0f} ms" if run.average_ms is not None else "—"
        lines.append(
            f"| **{run.label}** | **{run.score}** | {accuracy} | {response} | "
            f"{cost} | {run.calls} |"
        )
    return "\n".join(lines)


def main() -> None:
    """Regenerate shareable artifacts from saved results without calling any models."""
    report = read_report()
    if report is None or report.finished_at is None:
        raise SystemExit("Finish a benchmark before exporting its report.")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    runs = sorted(
        [item.run for item in report.results if item.status == "completed" and item.run],
        key=lambda run: -run.score,
    )
    date = (
        datetime.fromisoformat(report.created_at)
        .astimezone(ZoneInfo("Europe/Berlin"))
        .strftime("%d %B %Y, %H:%M %Z")
    )
    for measure in ("time", "cost"):
        chart(runs, measure, date)
    failed = [result.label for result in report.results if result.status != "completed"]
    summary = (
        f"Measured **{date}**: **{len(runs)} of {len(report.results)} models** returned results. "
        f"One **{report.duration}-second** run per model, "
        "launched in parallel on the same shuffled course. "
        + (
            f"No completed measurement for {', '.join(failed)}; "
            "their recorded errors remain in the raw data, without invented scores or chart points."
            if failed
            else "All available models completed their runs."
        )
    )
    methodology = f"""## Method

- Score: +1 for a correct box, −1 for a miss or malformed box. Late answers earn no points.
- All models start together, with one in-flight request per model. No hidden retries.
- The same 60 generated images, course seed `{report.seed}`, and scoring fingerprint
  `{report.deck}` apply to every model.
- Fast models reach more images. A correct answer has the same 450 ms feedback pause as the
  game; a miss advances immediately.
- Models see the same unmarked JPEG bytes without reference coordinates or position hints. Jev
  uses its native box question; gateway models use the game's JSON box prompt and 256-token
  output limit.
- Average response time includes all returned requests, including the last answer after the
  cutoff. Cost includes its returned billing too, unlike a live game that may cancel an
  outstanding call.
- Gateway-reported cost is preferred; token-based list pricing is the fallback. Jev uses $0.042
  per million input tokens. Failed calls with no billing information have unknown cost.
- One run per model is a demonstration snapshot, not a general capability ranking. Parallel
  load, gateway routing, caching, network latency, and model output-format compliance affect
  these numbers.
- These results are separate from player history; no synthetic human scores are added to the
  leaderboard.

## Reproduce

```sh
uv run python -m jev_demo.waldo_benchmarks
uv run python scripts/export_waldo_benchmarks.py
```

The first command makes paid requests using the ignored `.env` and replaces the snapshot.
The second only regenerates these tables and charts. Opening **Show full model benchmarks**
in the app is read-only and never starts model calls.

[Raw measured data](../../backend/jev_demo/assets/waldo/full-benchmarks.json)
"""
    _ = (OUTPUT / "README.md").write_text(
        f"# Waldo model benchmarks\n\n{summary}\n\n{table(report)}\n\n"
        "![Points vs. response time](score-time.png)\n\n![Points vs. cost](score-cost.png)\n\n"
        + methodology
    )
    section = (
        "<!-- WALDO-BENCHMARKS:START -->\n## Measured model benchmarks\n\n"
        + summary
        + "\n\n"
        + table(report)
        + "\n\n![Points vs. response time](docs/benchmarks/score-time.png)"
        + "\n\n![Points vs. cost](docs/benchmarks/score-cost.png)"
        + "\n\n[Method, limitations, and raw results](docs/benchmarks/README.md). "
        + "Open **Show full model benchmarks** in the app for interactive charts."
        + "\n<!-- WALDO-BENCHMARKS:END -->"
    )
    readme = ROOT / "README.md"
    text = readme.read_text()
    if "<!-- WALDO-BENCHMARKS:START -->" in text:
        before, rest = text.split("<!-- WALDO-BENCHMARKS:START -->", 1)
        _, after = rest.split("<!-- WALDO-BENCHMARKS:END -->", 1)
        text = before + section + after
    else:
        text = text.replace("## Quick start", section + "\n\n## Quick start", 1)
    _ = readme.write_text(text)


if __name__ == "__main__":
    main()
