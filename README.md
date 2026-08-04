# paraphrase-spread

One task. **414 wordings that a judge confirmed ask for the same thing.** The same 24 problems
through every one of them, at temperature 0.

**[The distribution](https://jesserweigel.github.io/paraphrase-spread/)**

On `qwen3:8b`, accuracy on those 414 wordings has a mean of **70.9%** and a standard deviation of
**12.8%**. The middle 90% of wordings run from **50.0%** to **91.7%**. The full range is 0% to
100%.

A benchmark that reports one number for this task and this model is reporting one draw from that
spread, and nothing in the number tells you which draw you got.

**It was 414 wordings, not 1,000.** The catalog task asked for 1,000 paraphrases each of five
tasks across three models. This is two tasks, three models, and 414 wordings on the primary task.
The number is stated everywhere it is used and the shortfall is not dressed up.

## The distribution, on three models

24 items per wording, 36,240 raw model responses saved to `results/raw/`.

| model | wordings | mean | sd | 5th pct | 95th pct | min | max | IQR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `qwen3:8b` | 414 | 70.9% | **12.8%** | 50.0% | 91.7% | 0.0% | 100.0% | 16.7% |
| `gemma4:e4b` | 414 | 92.3% | 8.5% | 87.5% | 95.8% | 0.0% | 100.0% | 4.2% |
| `qwen3.5:9b` | 414 | 98.8% | 5.9% | 95.8% | 100.0% | 4.2% | 100.0% | 0.0% |

The spread shrinks as the model gets better at the task, which is what you would expect and is
worth saying out loud: on a task a model has comfortably solved, wording matters less. The
interesting regime is the one where a model is near its limit, and that is where benchmarks
usually sit.

The second task keeps the same model and changes the work. Conditional reasoning, three-way
answer, two valid argument forms and two formal fallacies:

| task | model | wordings | mean | sd | 5th pct | 95th pct |
|---|---|---:|---:|---:|---:|---:|
| `entail` | `qwen3:8b` | 105 | 65.2% | **21.8%** | 16.7% | 91.7% |

The middle 90% of wordings spans 75 points there. Same model, same 24 items, same question.

## The range is not the evidence, and reporting it alone would be dishonest

With 414 wordings scored on 24 items, some wordings land at the extremes by luck. To see how
much, the correct/incorrect matrix is permuted 1,000 times **within each item**, so every item
keeps its exact difficulty and only which wordings got it right changes. That null still produces
a wide range:

| model | observed sd | sd under the null | observed range | range under the null | Cochran Q | p |
|---|---:|---:|---:|---:|---:|---:|
| `qwen3:8b` | 12.8% | 6.8% | 100.0% | 39.8% | 1447 | 0.001 |
| `gemma4:e4b` | 8.5% | 3.6% | 100.0% | 20.3% | 2279 | 0.001 |
| `qwen3.5:9b` | 5.9% | 2.2% | 95.8% | 11.3% | 2884 | 0.001 |
| `entail` on `qwen3:8b` | 21.8% | 8.6% | 95.8% | 42.8% | 666 | 0.001 |

A **39.8%** range appears on `qwen3:8b` even when every wording is equally good. That is why this
README leads with the standard deviation and the middle 90% rather than with min-to-max. The
observed standard deviation is roughly double the null on every run, and 0.001 is the smallest
p-value 1,000 permutations can produce.

The second test asks a different question: does a wording that did well here do well on items it
was not measured on? Score each wording on a random half of the items, score it again on the
other half, correlate the two across wordings, and correct for the halving. Over 200 random
splits:

| run | split-half correlation | Spearman-Brown |
|---|---:|---:|
| `mult` on `qwen3:8b` | 0.61 | **0.76** |
| `mult` on `gemma4:e4b` | 0.76 | 0.86 |
| `mult` on `qwen3.5:9b` | 0.82 | 0.90 |
| `entail` on `qwen3:8b` | 0.80 | 0.88 |

A spread that was pure item-set luck would give a reliability near zero. The pipeline can produce
that number: `tests/test_stats.py` builds a world where every wording is equally good, checks
that the accuracy range is still visibly wide, and requires the reliability to come out under
0.25 and the spread test to find nothing. That test is the negative control for this entire
project.

## 49 of the 463 wordings were not paraphrases, and that had to be caught

The lowest-scoring wording in the raw pool was this:

> You are an efficient processor. Give the result of the calculation as a raw integer with no
> commas or non-numeric text: {a} and {b}

It never says which calculation. `qwen3:8b` scored 4% on it, mostly by concatenating the two
numbers: given 79 and 92 it answered `7992`. Counting that as a wording effect would have
inflated the spread with a prompt that changes the question.

So every wording, not a sample of them, goes to a judge that compares it against the reference and
is told to answer DIFFERENT if the candidate omits the operation, adds or drops information, or is
truncated. **413 of 462 passed** on `mult` and 104 of 120 on `entail`. The judge caught the
wording above for exactly the right reason: *"The candidate does not specify which operation to
perform, whereas the reference explicitly asks for the product."* Nineteen of the 49 exclusions
were wordings the generator had truncated mid-sentence.

Only the wordings that passed are in the distribution. `results/analysis.json` carries the
unfiltered figures too, so the size of the correction is visible: without the filter the standard
deviation on `qwen3:8b` reads 15.7% rather than 12.8%.

Two more equivalence checks back that one up. A deterministic structural filter runs at generation
time and rejected 46 candidates before the judge saw them. And a random 40 wordings were
translated to Spanish and back, then judged against their own originals: **40 of 40** survived as
equivalent, with all placeholders intact.

**The reviewer was a language model, and the spot-check of its verdicts was done by an AI agent.
No human read these wordings.** Everything is in `results/equivalence_mult.json` if you want to.

## Unparseable is counted, not scored as wrong without saying so

On `entail`, **316 of 2,520 responses carried no readable answer**, 12.5% of them. Those are
counted in their own column. The headline accuracy counts them against the wording, because a
benchmark harness scoring this run would, and the parsed-only accuracy is reported next to it so
the difference is visible rather than buried.

| run | responses | correct | wrong | unparseable | call failed | headline | parsed-only |
|---|---:|---:|---:|---:|---:|---:|---:|
| `mult` / `qwen3:8b` | 9,936 | 7,041 | 2,895 | 0 | 0 | 70.9% | 70.9% |
| `mult` / `gemma4:e4b` | 9,936 | 9,172 | 764 | 0 | 0 | 92.3% | 92.3% |
| `mult` / `qwen3.5:9b` | 9,936 | 9,812 | 124 | 0 | 0 | 98.8% | 98.8% |
| `entail` / `qwen3:8b` | 2,520 | 1,642 | 562 | **316** | 0 | 65.2% | **73.6%** |

A failed model call is a fifth outcome and never becomes a wrong answer. There were none in this
run, and the distinction is still in the code and still tested, because an unreachable server
looking like a model that got everything wrong is exactly the sort of thing that gets noticed
after publication.

## Which features of a wording track accuracy, and why you should not take prompting advice from it

Fourteen surface features of each template, Spearman correlation against its accuracy, Holm
corrected across all fourteen. What survives correction:

| run | feature | ρ | p (Holm) |
|---|---|---:|---:|
| `mult` / `qwen3:8b` | `words`, template length in words | **−0.160** | 0.014 |
| `mult` / `gemma4:e4b` | `slot_position`, how late the numbers appear | **+0.284** | 0.007 |
| `mult` / `gemma4:e4b` | `format_before_slot`, format stated before the problem | **+0.209** | 0.019 |
| `mult` / `qwen3.5:9b` | `is_question`, phrased as a question | **−0.195** | 0.007 |
| `entail` / `qwen3:8b` | nothing survives correction | | |

**No feature is significant on more than one model.** Shorter helps `qwen3:8b`; putting the
numbers last helps `gemma4:e4b`; asking a question hurts `qwen3.5:9b`. If there were a
transferable rule about how to word a prompt, three models on one identical task is where it
would show up, and it does not. Correlations are within one generator's output, the features are
not independent of each other, and the honest reading is a description of this pool rather than
advice.

## Temperature 0 is not determinism, measured

Re-asking 200 already-answered prompts on `qwen3:8b` reproduced **188 of them byte for byte,
94.0%**. The other 12 differed, sometimes only in a greeting and sometimes in the answer: one
asking for 68 × 74 returned `4972` on the first pass and `5012` on the second. Both are wrong,
and they are wrong differently.

So the spread reported here is not purely a wording effect. Some small part of it is server-side
nondeterminism under batching, and the measured 6% disagreement rate is the honest bound on that.
It is in `results/repeat_mult__qwen3-8b.json` with the disagreeing pairs.

## What this is a sample of

- The wordings were written by `gemini-3-flash-preview` under 14 style directives crossed with 10
  structural directives, all chosen by the author, with each call shown 20 wordings already in the
  pool and told to differ from them. **This is a sample from one generator conditioned on one list
  of styles. It is not a random sample of how people write prompts,** and no model-generated pool
  could be. The directives and the generation prompt are in `pspread/paraphrase.py`.
- 508 raw candidates produced 463 usable wordings: 46 were rejected by the structural filter,
  mostly for losing a placeholder, and 0 were exact duplicates after normalisation.
  Near-duplicates were deliberately kept, because thinning them would make the pool look more
  varied than the thing that produced it.
- 24 items per wording. That is a small item set, which is the reason for the permutation null and
  the split-half reliability rather than a bare range.
- Two tasks and three models, not the five tasks and three models the catalog task described.

## Running it

```bash
python3 -m pspread.cli paraphrase --task mult --calls 90 --per-call 20   # needs GEMINI_API_KEY
python3 -m pspread.cli equiv      --task mult                           # needs GEMINI_API_KEY
python3 -m pspread.cli run        --task mult --model qwen3:8b          # needs Ollama
python3 -m pspread.cli repeat     --task mult --model qwen3:8b          # needs Ollama
python3 -m pspread.cli analyze                                          # needs neither
python3 scripts/build_docs.py                                           # needs neither
```

`bash scripts/run_experiment.sh` runs the whole measurement in order. Every phase is resumable:
the runner reads what is on disk and asks the model only for what is missing, which matters
because the GPU here is shared and a run that has to restart from zero never finishes.

Python 3, no dependencies. `analyze` and `build_docs.py` read only committed files, so every
published number can be re-derived with no GPU and no API key.

## Verification

```bash
bash scripts/verify.sh
```

Ten layers. The ones that do work:

- **56** unit tests, and a structural check that parses the test files with `ast` and fails if any
  test lacks its `_negative_control` partner. A suite whose assertions are all satisfied by
  construction proves nothing.
- The whole analysis **rebuilt from the raw responses** and compared field by field against the
  committed `results/analysis.json`. Every seed is fixed, so any difference is a real one.
- Every headline number **re-derived by `scripts/check_independent.py`**, which imports nothing
  from `pspread/`. It rebuilds the answer key from the item identifiers rather than importing it,
  scans characters instead of matching regular expressions, and does its own arithmetic. It
  demands exact agreement, not agreement within a tolerance. The independence is proved by walking
  its import graph with `ast`, including a refusal of dynamic imports.
- A **control on that checker**: a copy of the tool with its grader reading the first number
  instead of the last must make the re-derivation disagree. Without it, agreement would prove only
  that both sides ran.
- **Eight sabotages**, each proved to have applied and to have moved a probe named for what it was
  supposed to change, before any failing check counts. The `cochran-q-wrong-constant` attack is
  invisible to the unit suite, because the permutation null uses the same formula and the p-value
  does not move. Only the independent re-derivation catches it, which is why that layer exists.
- The page **rebuilt byte for byte** from the committed results, with its numbers matched back to
  the JSON, no JavaScript anywhere in it, and every table inside a scrolling container.
- The README checked against `results/analysis.json`, including a rule that fails the build if
  this file ever claims 1,000 paraphrases while fewer than 1,000 were run.

## Status

```
$ bash scripts/verify.sh
STATUS_BLOCK_PLACEHOLDER
```

## What is not done

- **Two tasks, not five**, and 414 wordings on the primary task rather than 1,000. Both were
  bounded by a shared GPU, not by anything in the design. `scripts/run_experiment.sh` scales
  without changes.
- **The paraphrase pool is one generator's output.** A pool collected from real users would be the
  right comparison and would probably be wider, since real prompts carry typos, missing context,
  and formatting the structural filter here rejects.
- **The equivalence judge is a model**, and it is stricter than a person on some wordings, for
  example rejecting "plain number" as unequal to "plain integer". That makes the reported spread
  conservative rather than inflated.
- **`qwen3.5:9b` is near ceiling on `mult`** at 98.8%, so its distribution is squeezed against
  100% and its spread is a floor rather than an estimate.
- No CPU-only fallback. Both `run` and `repeat` need a reachable Ollama, and they fail rather than
  skip when it is not there.

Task RSCH-046 from [722 things to build](https://github.com/JesseRWeigel/722-things-to-build).

MIT.
