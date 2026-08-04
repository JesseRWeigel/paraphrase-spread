#!/usr/bin/env python3
"""Build docs/index.html from results/analysis.json.

Every number and every bar on the page comes from the committed analysis file. There is no
JavaScript: the histogram is server-rendered SVG, so there is no inline script that can fail to
parse and leave a page that looks fine and contains nothing. `scripts/verify.sh` rebuilds this
file and fails if the committed copy differs by a byte, which is what stops the page drifting
away from the results it claims to show.
"""

import argparse
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CSS = """
:root {
  --bg: #fbfaf7; --fg: #1a1a1a; --muted: #5c5c5c; --rule: #e0ddd6;
  --bar: #2f5d50; --bar2: #b5651d; --accent: #8a2b2b; --card: #ffffff;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #16171a; --fg: #e9e6e0; --muted: #9a978f; --rule: #2f3136;
          --bar: #6fae9b; --bar2: #e0975a; --accent: #e07a7a; --card: #1d1f23; }
}
:root[data-theme="dark"] {
  --bg: #16171a; --fg: #e9e6e0; --muted: #9a978f; --rule: #2f3136;
  --bar: #6fae9b; --bar2: #e0975a; --accent: #e07a7a; --card: #1d1f23;
}
:root[data-theme="light"] {
  --bg: #fbfaf7; --fg: #1a1a1a; --muted: #5c5c5c; --rule: #e0ddd6;
  --bar: #2f5d50; --bar2: #b5651d; --accent: #8a2b2b; --card: #ffffff;
}
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--fg); margin: 0;
  font: 16px/1.6 ui-serif, Georgia, "Times New Roman", serif; }
main { max-width: 60rem; margin: 0 auto; padding: 2.5rem 1.25rem 5rem; }
h1 { font-size: clamp(1.7rem, 5vw, 2.6rem); line-height: 1.15; margin: 0 0 .4rem; }
h2 { font-size: 1.3rem; margin: 2.6rem 0 .8rem; padding-top: 1.2rem;
     border-top: 1px solid var(--rule); }
h3 { font-size: 1.05rem; margin: 1.6rem 0 .5rem; }
p, li { max-width: 42rem; }
.sub { color: var(--muted); margin: 0 0 2rem; }
.big { font-size: clamp(2.4rem, 9vw, 4.2rem); line-height: 1; font-weight: 700;
       color: var(--accent); letter-spacing: -0.02em; }
.big small { display: block; font-size: 1rem; font-weight: 400; color: var(--muted);
             letter-spacing: 0; margin-top: .5rem; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
         gap: .75rem; margin: 1.5rem 0; }
.card { background: var(--card); border: 1px solid var(--rule); border-radius: 6px;
        padding: .9rem 1rem; min-width: 0; }
.card .k { font-size: .78rem; text-transform: uppercase; letter-spacing: .06em;
           color: var(--muted); }
.card .v { font-size: 1.5rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 1rem 0; }
table { border-collapse: collapse; font-size: .9rem; min-width: 34rem; }
th, td { text-align: right; padding: .4rem .6rem; border-bottom: 1px solid var(--rule);
         white-space: nowrap; font-variant-numeric: tabular-nums; }
th:first-child, td:first-child { text-align: left; }
thead th { border-bottom: 2px solid var(--rule); font-size: .8rem; text-transform: uppercase;
           letter-spacing: .05em; color: var(--muted); }
figure { margin: 1.5rem 0; }
.chart { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.chart svg { min-width: 40rem; max-width: 100%; }
figcaption { color: var(--muted); font-size: .88rem; margin-top: .5rem; max-width: 42rem; }
svg { display: block; max-width: 100%; height: auto; }
blockquote { margin: .6rem 0 1rem; padding: .7rem 1rem; background: var(--card);
             border-left: 3px solid var(--rule); font-size: .93rem; }
blockquote.good { border-left-color: var(--bar); }
blockquote.bad { border-left-color: var(--accent); }
code { font: .88em ui-monospace, SFMono-Regular, Menlo, monospace;
       background: var(--card); padding: .1em .3em; border-radius: 3px; }
.note { color: var(--muted); font-size: .9rem; }
footer { margin-top: 3rem; padding-top: 1.2rem; border-top: 1px solid var(--rule);
         color: var(--muted); font-size: .88rem; }
a { color: inherit; }
"""


def esc(s):
    return html.escape(str(s))


def pct(x, places=1):
    return "n/a" if x is None else f"{100 * x:.{places}f}%"


def histogram_svg(runs, width=880, height=340):
    """Overlaid outline histograms, one per model, drawn as SVG paths."""
    pad_l, pad_r, pad_t, pad_b = 52, 16, 20, 52
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    colors = ["var(--bar)", "var(--bar2)", "var(--accent)"]
    peak = max(max(r["histogram"]["counts"]) for r in runs)
    peak = max(peak, 1)

    parts = [f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
             f'role="img" aria-label="Accuracy distribution over paraphrases">']
    # y gridlines
    steps = 4
    for i in range(steps + 1):
        y = pad_t + plot_h - plot_h * i / steps
        val = peak * i / steps
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" '
                     f'stroke="var(--rule)" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="12" '
                     f'fill="var(--muted)">{val:.0f}</text>')
    # x axis
    for i in range(11):
        x = pad_l + plot_w * i / 10
        parts.append(f'<text x="{x:.1f}" y="{pad_t + plot_h + 20}" text-anchor="middle" '
                     f'font-size="12" fill="var(--muted)">{i * 10}%</text>')
    parts.append(f'<text x="{pad_l + plot_w / 2:.1f}" y="{height - 8}" text-anchor="middle" '
                 f'font-size="13" fill="var(--muted)">accuracy of one wording, over the same '
                 f'24 items</text>')

    for idx, run in enumerate(runs):
        counts = run["histogram"]["counts"]
        edges = run["histogram"]["edges"]
        colour = colors[idx % len(colors)]
        pts = [f"{pad_l:.1f},{pad_t + plot_h:.1f}"]
        for i, c in enumerate(counts):
            # Bin edges sit half a bin outside 0..1 so each attainable score gets
            # its own bin, so they are clamped back to the axis before drawing.
            x0 = pad_l + plot_w * min(max(edges[i], 0.0), 1.0)
            x1 = pad_l + plot_w * min(max(edges[i + 1], 0.0), 1.0)
            y = pad_t + plot_h - plot_h * c / peak
            pts.append(f"{x0:.1f},{y:.1f}")
            pts.append(f"{x1:.1f},{y:.1f}")
        pts.append(f"{pad_l + plot_w:.1f},{pad_t + plot_h:.1f}")
        parts.append(f'<polyline points="{" ".join(pts)}" fill="{colour}" fill-opacity="0.16" '
                     f'stroke="{colour}" stroke-width="2" stroke-linejoin="round"/>')
        # the canonical wording, marked
        if run.get("canonical_accuracy") is not None:
            x = pad_l + plot_w * run["canonical_accuracy"]
            parts.append(f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" '
                         f'y2="{pad_t + plot_h}" stroke="{colour}" stroke-width="1.5" '
                         f'stroke-dasharray="5 4"/>')
    # legend
    ly = pad_t + 4
    for idx, run in enumerate(runs):
        colour = colors[idx % len(colors)]
        parts.append(f'<rect x="{pad_l + 12}" y="{ly - 9}" width="12" height="12" '
                     f'fill="{colour}" fill-opacity="0.35" stroke="{colour}"/>')
        parts.append(f'<text x="{pad_l + 30}" y="{ly + 1}" font-size="13" fill="var(--fg)">'
                     f'{esc(run["model"])}</text>')
        ly += 20
    parts.append("</svg>")
    return "\n".join(parts)


def strip_svg(runs, width=880):
    """One row per model: the full range as a bar, with quartiles and the canonical wording."""
    row_h = 54
    pad_l, pad_r, pad_t = 130, 16, 18
    height = pad_t + row_h * len(runs) + 34
    plot_w = width - pad_l - pad_r
    colors = ["var(--bar)", "var(--bar2)", "var(--accent)"]
    parts = [f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
             f'role="img" aria-label="Range of accuracy per model">']
    for i in range(11):
        x = pad_l + plot_w * i / 10
        parts.append(f'<line x1="{x:.1f}" y1="{pad_t - 6}" x2="{x:.1f}" '
                     f'y2="{pad_t + row_h * len(runs)}" stroke="var(--rule)"/>')
        parts.append(f'<text x="{x:.1f}" y="{height - 12}" text-anchor="middle" font-size="12" '
                     f'fill="var(--muted)">{i * 10}%</text>')
    for idx, run in enumerate(runs):
        s = run["strict"]
        y = pad_t + row_h * idx + row_h / 2
        colour = colors[idx % len(colors)]
        x0 = pad_l + plot_w * s["min"]
        x1 = pad_l + plot_w * s["max"]
        q1 = pad_l + plot_w * s["p25"]
        q3 = pad_l + plot_w * s["p75"]
        med = pad_l + plot_w * s["median"]
        parts.append(f'<text x="{pad_l - 10}" y="{y + 4:.1f}" text-anchor="end" font-size="13" '
                     f'fill="var(--fg)">{esc(run["model"])}</text>')
        parts.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x1:.1f}" y2="{y:.1f}" '
                     f'stroke="{colour}" stroke-width="2"/>')
        parts.append(f'<rect x="{q1:.1f}" y="{y - 11:.1f}" width="{max(q3 - q1, 1):.1f}" '
                     f'height="22" fill="{colour}" fill-opacity="0.25" stroke="{colour}"/>')
        parts.append(f'<line x1="{med:.1f}" y1="{y - 13:.1f}" x2="{med:.1f}" '
                     f'y2="{y + 13:.1f}" stroke="{colour}" stroke-width="3"/>')
        for x in (x0, x1):
            parts.append(f'<line x1="{x:.1f}" y1="{y - 8:.1f}" x2="{x:.1f}" '
                         f'y2="{y + 8:.1f}" stroke="{colour}" stroke-width="2"/>')
        if run.get("canonical_accuracy") is not None:
            cx = pad_l + plot_w * run["canonical_accuracy"]
            parts.append(f'<circle cx="{cx:.1f}" cy="{y:.1f}" r="4.5" fill="var(--bg)" '
                         f'stroke="{colour}" stroke-width="2"/>')
        parts.append(f'<text x="{x0 - 6:.1f}" y="{y - 16:.1f}" text-anchor="end" font-size="11" '
                     f'fill="var(--muted)">{pct(s["min"], 0)}</text>')
        parts.append(f'<text x="{x1 + 6:.1f}" y="{y - 16:.1f}" font-size="11" '
                     f'fill="var(--muted)">{pct(s["max"], 0)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def summary_table(runs):
    head = ("<thead><tr><th>model</th><th>wordings</th><th>responses</th><th>mean</th>"
            "<th>median</th><th>sd</th><th>min</th><th>max</th><th>range</th><th>IQR</th>"
            "<th>Cochran Q p</th><th>reliability</th></tr></thead>")
    rows = []
    for r in runs:
        s = r["strict"]
        st = r["spread_test"]
        rows.append(
            f"<tr><td>{esc(r['model'])}</td><td>{s['n']}</td><td>{r['responses']:,}</td>"
            f"<td>{pct(s['mean'])}</td><td>{pct(s['median'])}</td><td>{pct(s['sd'])}</td>"
            f"<td>{pct(s['min'])}</td><td>{pct(s['max'])}</td>"
            f"<td><strong>{pct(s['range'])}</strong></td><td>{pct(s['iqr'])}</td>"
            f"<td>{st['q_p_value']:.4f}</td>"
            f"<td>{r['reliability']['spearman_brown']:.2f}</td></tr>")
    return f"<div class='scroll'><table>{head}<tbody>{''.join(rows)}</tbody></table></div>"


def accounting_table(runs):
    head = ("<thead><tr><th>model</th><th>responses</th><th>correct</th><th>wrong</th>"
            "<th>unparseable</th><th>call failed</th><th>strict mean</th>"
            "<th>parsed-only mean</th></tr></thead>")
    rows = []
    for r in runs:
        a = r["accounting"]
        rows.append(
            f"<tr><td>{esc(r['model'])}</td><td>{r['responses']:,}</td><td>{a['correct']:,}</td>"
            f"<td>{a['wrong']:,}</td><td>{a['unparseable']:,}</td><td>{a['error']:,}</td>"
            f"<td>{pct(r['strict']['mean'])}</td>"
            f"<td>{pct(r['parsed_only']['mean'])}</td></tr>")
    return f"<div class='scroll'><table>{head}<tbody>{''.join(rows)}</tbody></table></div>"


def feature_table(run):
    head = ("<thead><tr><th>feature</th><th>what it detects</th><th>share of wordings</th>"
            "<th>Spearman &rho;</th><th>p (Holm)</th></tr></thead>")
    rows = []
    for f in sorted(run["features"], key=lambda f: -(abs(f["spearman"] or 0))):
        share = "varies" if f["share_with_feature"] is None else pct(f["share_with_feature"], 0)
        rho = "n/a" if f["spearman"] is None else f"{f['spearman']:+.3f}"
        mark = " <strong>*</strong>" if f["p_holm"] < 0.05 else ""
        rows.append(f"<tr><td><code>{esc(f['name'])}</code></td><td>{esc(f['description'])}</td>"
                    f"<td>{share}</td><td>{rho}</td><td>{f['p_holm']:.3f}{mark}</td></tr>")
    return f"<div class='scroll'><table>{head}<tbody>{''.join(rows)}</tbody></table></div>"


def build(analysis, repeat_checks, equivalence, pool_meta):
    mult = [r for r in analysis["runs"] if r["task"] == "mult"]
    entail = [r for r in analysis["runs"] if r["task"] == "entail"]
    mult.sort(key=lambda r: r["model"])
    primary = max(mult, key=lambda r: r["strict"]["range"]) if mult else None
    widest = primary["strict"]["range"] if primary else 0

    n_par = mult[0]["strict"]["n"] if mult else 0
    total_responses = sum(r["responses"] for r in analysis["runs"])

    out = [f"<title>The accuracy distribution over {n_par} paraphrases of one task</title>",
           f"<style>{CSS}</style>", "<main>"]
    out.append(f"<h1>One task, {n_par} wordings, and an accuracy range of "
               f"{pct(widest, 0)}</h1>")
    out.append(f"<p class='sub'>Every wording asks for the same thing. The same 24 "
               f"multiplication problems go through all of them, at temperature 0. "
               f"{total_responses:,} model responses, all saved to disk.</p>")

    out.append("<div class='cards'>")
    for k, v in [
        ("wordings tested", f"{n_par}"),
        ("worst wording", pct(primary["strict"]["min"], 0)),
        ("best wording", pct(primary["strict"]["max"], 0)),
        ("spread", pct(widest, 0)),
    ]:
        out.append(f"<div class='card'><div class='k'>{esc(k)}</div>"
                   f"<div class='v'>{esc(v)}</div></div>")
    out.append("</div>")
    out.append(f"<p>The widest range is on <code>{esc(primary['model'])}</code>. A benchmark "
               f"that reports one number for this task and this model is reporting one draw "
               f"from that range, and nothing in the number says which draw it was.</p>")

    out.append("<h2>The distribution</h2>")
    out.append("<figure><div class='chart'>" + histogram_svg(mult) + "</div>"
               "<figcaption>Count of wordings at each accuracy, in 5-point bins. The dashed "
               "line marks the plain reference wording the paraphrases were generated from. "
               "It is one wording among many and it sits inside the spread, not above it."
               "</figcaption></figure>")
    out.append("<figure><div class='chart'>" + strip_svg(mult) + "</div>"
               "<figcaption>Full range, interquartile box, median, and the reference wording "
               "as a hollow circle. The bar is what a single-prompt benchmark number is drawn "
               "from.</figcaption></figure>")
    out.append(summary_table(mult))

    out.append("<h2>Is the spread real, or is it luck on 24 items?</h2>")
    out.append("<p>Every call runs at temperature 0, so a wording's score on these 24 items is "
               "exact rather than estimated. The question worth asking is whether the same "
               "wording would still look good on different items. Two tests answer it.</p>")
    rows = []
    for r in mult:
        st = r["spread_test"]
        rows.append(
            f"<tr><td>{esc(r['model'])}</td><td>{st['cochran_q']:.0f}</td>"
            f"<td>{st['q_p_value']:.4f}</td><td>{pct(st['observed_sd'])}</td>"
            f"<td>{pct(st['null_sd_mean'])}</td><td>{pct(st['observed_range'])}</td>"
            f"<td>{pct(st['null_range_mean'])}</td>"
            f"<td>{r['reliability']['spearman_brown']:.2f}</td></tr>")
    out.append("<div class='scroll'><table><thead><tr><th>model</th><th>Cochran Q</th>"
               "<th>p</th><th>observed sd</th><th>sd if wordings were equal</th>"
               "<th>observed range</th><th>range if wordings were equal</th>"
               "<th>split-half reliability</th></tr></thead><tbody>"
               + "".join(rows) + "</tbody></table></div>")
    out.append(f"<p class='note'>The two null columns come from {mult[0]['spread_test']['permutations']:,} "
               "permutations that keep each item's difficulty fixed and shuffle only which "
               "wordings got it right. That null still produces a visible range, which is why "
               "the range on its own is not evidence. Reliability is the mean Spearman-Brown "
               "corrected correlation between a wording's score on one random half of the "
               "items and its score on the other half, over 200 splits.</p>")

    out.append("<h2>The best and the worst wording</h2>")
    for r in mult:
        out.append(f"<h3>{esc(r['model'])}</h3>")
        out.append(f"<blockquote class='good'><strong>{pct(r['best']['accuracy'], 0)}</strong> "
                   f"&mdash; {esc(r['best']['text'])}</blockquote>")
        out.append(f"<blockquote class='bad'><strong>{pct(r['worst']['accuracy'], 0)}</strong> "
                   f"&mdash; {esc(r['worst']['text'])}</blockquote>")

    out.append("<h2>Where the responses went</h2>")
    out.append("<p>A response the grader cannot read an answer out of is counted as unparseable "
               "and reported separately. It is not scored as a wrong answer without saying so, "
               "and a failed call is not scored at all.</p>")
    out.append(accounting_table(analysis["runs"]))

    out.append("<h2>Which features of a wording track accuracy</h2>")
    out.append(f"<p>On <code>{esc(primary['model'])}</code>, across {primary['strict']['n']} "
               f"wordings. Spearman correlation between the feature and the wording's accuracy, "
               f"with Holm correction across all {len(primary['features'])} features. A star "
               f"marks a corrected p below 0.05.</p>")
    out.append(feature_table(primary))
    out.append("<p class='note'>These features are not independent of each other, and they are "
               "measured inside one generator's output. Read them as descriptions of this pool, "
               "not as prompt-writing advice.</p>")

    if entail:
        out.append("<h2>A second task, to check it is not an arithmetic quirk</h2>")
        out.append(f"<p>Conditional reasoning with two valid forms and two formal fallacies, "
                   f"{entail[0]['strict']['n']} wordings, same procedure.</p>")
        out.append(summary_table(entail))

    out.append("<h2>What this is a sample of</h2>")
    out.append("<ul>")
    out.append(f"<li><strong>{primary['paraphrases_before_equivalence_filter']} wordings "
               f"survived generation, and {primary['strict']['n']} of them are in the "
               f"distribution above.</strong> {esc(primary['equivalence_note'])}. Without that "
               f"filter the range on <code>{esc(primary['model'])}</code> would read "
               f"{pct(primary['unfiltered']['range'], 0)} rather than "
               f"{pct(primary['strict']['range'], 0)}, and the extra width would come from "
               f"prompts that changed the question rather than the wording.</li>")
    out.append(f"<li>The wordings were written by <code>{esc(pool_meta['generator']['model'])}</code> "
               f"under {len(pool_meta['generator']['styles'])} style directives crossed with "
               f"{len(pool_meta['generator'].get('axes', []))} structural directives, all chosen "
               f"by the author. They are a sample from that generator, not a random sample of "
               f"how people write prompts.</li>")
    out.append(f"<li>{pool_meta['raw_candidates']:,} candidates were generated, "
               f"{len(pool_meta['rejected'])} were rejected by a structural filter, and "
               f"{pool_meta['duplicates_dropped']} were exact duplicates. Near-duplicates were "
               f"kept, because thinning them would make the pool look more varied than the thing "
               f"that produced it.</li>")
    if equivalence:
        for task_name, eq in sorted(equivalence.items()):
            out.append(f"<li>On <code>{task_name}</code>, a model judge called "
                       f"{eq['judged']['equivalent']} of {eq['judged']['n']} sampled wordings "
                       f"equivalent to the reference "
                       f"({pct(eq['judged']['rate'], 0)}), and "
                       f"{eq['backtranslation']['equivalent']} of "
                       f"{eq['backtranslation']['n']} survived a round trip through Spanish "
                       f"still judged equivalent to their own original.</li>")
    for key, rep in sorted(repeat_checks.items()):
        out.append(f"<li>Re-asking {rep['n']} already-answered prompts on "
                   f"<code>{esc(rep['model'])}</code> reproduced "
                   f"{rep['identical']} of them byte for byte "
                   f"({pct(rep['rate'], 0)}), which is how much determinism "
                   f"temperature 0 actually buys on this server.</li>")
    out.append("<li>24 items per wording. That is a small item set, which is why the spread "
               "is tested against a permutation null and a split-half reliability rather than "
               "presented on its own.</li>")
    out.append("</ul>")

    out.append(f"<footer>Built from <code>results/analysis.json</code> on "
               f"{esc(analysis['generated_at'])}. Every raw model response is in "
               f"<code>results/raw/</code>, so these numbers can be re-derived without running "
               f"a model. Catalog task RSCH-046. "
               f"<a href='https://github.com/JesseRWeigel/paraphrase-spread'>Source</a>."
               f"</footer>")
    out.append("</main>")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(ROOT, "results"))
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "index.html"))
    args = ap.parse_args()

    analysis_path = os.path.join(args.results, "analysis.json")
    if not os.path.exists(analysis_path):
        print("results/analysis.json is missing, so there is nothing to build the page from. "
              "Run: python3 -m pspread.cli analyze", file=sys.stderr)
        return 2
    analysis = json.load(open(analysis_path, encoding="utf-8"))
    if not analysis.get("runs"):
        print("results/analysis.json has no runs in it", file=sys.stderr)
        return 2

    repeat_checks, equivalence = {}, {}
    for name in sorted(os.listdir(args.results)):
        path = os.path.join(args.results, name)
        if name.startswith("repeat_") and name.endswith(".json"):
            repeat_checks[name] = json.load(open(path, encoding="utf-8"))
        elif name.startswith("equivalence_") and name.endswith(".json"):
            equivalence[name[len("equivalence_"):-len(".json")]] = json.load(
                open(path, encoding="utf-8"))
    pool_meta = json.load(open(os.path.join(args.results, "paraphrases_mult.json"),
                               encoding="utf-8"))

    page = build(analysis, repeat_checks, equivalence, pool_meta)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"wrote {os.path.relpath(args.out, ROOT)} ({len(page):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
