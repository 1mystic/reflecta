# When 0.51 AUC was the most useful number I got

*A short technical write-up on cold-start in latent-variable models, group-aware
evaluation, and why the model that "scored well" is not always the model you serve.
Grounded in [Reflecta](https://reflecta-j1wz.onrender.com/) — the reasoning behind the
numbers lives in [`STORY.md`](STORY.md) and [`GUIDEBOOK.md`](GUIDEBOOK.md).*

---

## The one-line takeaway

The number that looks like your goal is usually measuring something adjacent to it, and
the interesting work is figuring out *what*. I ran into this twice on the same project,
which is what turned it from an anecdote into a pattern worth writing down:

> A metric can be capped by something that isn't your model at all — the labels, or the
> evaluation regime — and until you find out which, "improve the model" is the wrong move.

---

## Act 1 — a 0.752 ceiling that wasn't the model's fault

The project started as a Kaggle MCQ competition: predict the top-3 answers for 5-option
questions, scored by MAP@3. A retrieval lookup got to **0.752** almost immediately (the
training set had ~7.9 near-duplicate copies per unique question, so matching a test item to
its training twin was most of the signal). Then it stalled. Four different rank-2/3
strategies all landed within **0.004** of each other — that's noise, not signal.

The instinct is to reach for a better model. The right move was to interrogate the
ceiling. A leave-one-question-out check inside the training set gave label-majority
retrieval a **perfect 1.000 MAP@3** — so the data was internally consistent — while the
highest-leverage test items matched their training twins at **similarity 1.0**, ruling out
text drift. The only hypothesis left standing: **~25% of the answer keys were wrong or
genuinely ambiguous.** A leave-one-out model disagreed with the recorded key on 58% of
questions, 58 of them at high confidence — almost exactly the error count the ceiling
implied.

The 0.752 wasn't a modeling ceiling. It was a **label-quality ceiling.** No amount of
feature engineering can predict a wrong answer key. (This is not exotic: *Are We Done with
MMLU?* found ~6.5% of MMLU is mislabeled, rising to ~57% in some subjects.)

**Lesson 1:** before optimizing, prove the ceiling is yours to move.

## The pivot

The capability underneath — *telling genuine understanding apart from surface
pattern-matching* — was real and reusable; it was just aimed at the wrong target. Point it
at a **learner** instead of an answer key and you get something useful: a system that reads
*how* you answer (choices, timing, confidence, accuracy on reworded twins of the same
concept) and tells you whether you understand a thing or just recognize its phrasing. That
became Reflecta.

## Act 2 — a model that scored at chance, and why that was the useful result

"Mastery" needs a principled definition — raw percent-correct conflates *how hard the
items were* with *how able the learner is*. So I trained three knowledge-tracing models on
**525,534 real interactions** from ASSISTments 2009, and here is the honest table:

| Model | Val AUC (held-out learners) |
|---|---:|
| IRT (1PL / Rasch) | **0.506** |
| BKT (per-skill HMM) | 0.763 |
| SAKT (self-attention, from scratch) | 0.803 |

The IRT result looks broken. AUC 0.506 is a coin flip. My first reaction was "the training
is bugged."

It wasn't. It's the textbook **cold-start** limitation, and seeing it clearly required one
piece of evaluation discipline that is easy to skip.

### The thing that made the failure legible: group-aware splits

Joint 1PL IRT factorizes each response as

```
P(correct) = sigmoid(θ_learner − b_item)
```

It learns a per-learner ability `θ_i` **and** a per-item difficulty `b_j`. Now consider how
you split train/test:

- **Split by row** (the naive default): the same learner appears in both train and test.
  The model already has that learner's `θ_i`, so it predicts their held-out rows well. AUC
  looks great — and it's a **lie**, the same duplicate-leakage that inflated my Kaggle
  validation to 0.92 against a 0.73 leaderboard.
- **Split by learner** (group-aware): whole learners are held out. A held-out learner has
  **no `θ_i`** — the model never saw them. With the ability term missing, every prediction
  collapses toward the prior, and AUC falls to chance.

BKT and SAKT survive the group-aware split because they infer knowledge state *from the
sequence of answers as it arrives* — they don't depend on a learner-specific parameter
baked in at training time. 1PL IRT structurally cannot. **The 0.506 is not a bad model;
it's an honest model measured under the only split that matches how it would actually be
used — on people it has never seen.**

**Lesson 2:** your split defines what your metric means. Split by the unit you'll be cold
on in production, or your AUC is answering a question you'll never ask.

## Act 3 — the fix isn't a better model, it's a different serving regime

A live quiz-taker is, by definition, a learner the system has never seen. So a pretrained
per-learner ability is exactly the wrong tool. The fix is to **keep the part of IRT that
generalizes and re-fit the part that doesn't, per session:**

- **Freeze the item difficulties.** Difficulty `b_j` is a property of the *question*, not
  the person; the quiz bank authors it directly (mapped from an authored 0–1 difficulty
  onto the logit scale). No training needed.
- **Fit only this learner's `θ`** from their handful of live answers, by MAP:

```
θ* = argmax_θ  Σ_i [ y_i(θ − b_i) − log(1 + e^{θ−b_i}) ]  −  θ² / (2σ²)
```

solved with a few Newton steps. The Gaussian prior `N(0, σ²)` is load-bearing: with only
2–4 answers per concept, an all-correct or all-wrong run would send the MLE to ±∞. The
prior keeps `θ` finite and shrinks sparse evidence toward the population average. This is
the same IRT method, validated offline — now applied to *one* learner at request time.
It needs no pretrained model file at all.

This is the counterintuitive payoff: the offline model that scored **0.803** (SAKT) is
**not** the one serving live traffic, because it was trained on ASSISTments' exercise
vocabulary — a disjoint item space from the live quiz bank. Serving live sessions through
it would mean looking up embeddings for exercise IDs it never saw: silently meaningless
output, the *same* cold-start/domain-mismatch failure as the 0.506, wearing a better AUC.
The model with the worse benchmark number (per-session online IRT) is the one that is
actually correct to serve, because it only needs the bank's own authored difficulties.

**Lesson 3:** "best val AUC" and "correct to serve" are different questions. Benchmark the
model; serve the one whose assumptions match the request.

## A small free lunch at the end

Fitting `θ` by Newton's method means forming the Hessian of the log-posterior on every
iteration:

```
H = −Σ p_i(1 − p_i) − 1/σ²
```

The Laplace posterior **variance** of `θ` is exactly `−1/H` — the Fisher information plus
the prior precision, already computed and sitting in the loop. The first version of this
code returned `θ` and threw `H` away. But that variance *is* the model's uncertainty about
the learner: it starts at the prior variance (the model knows nothing) and shrinks as
consistent evidence arrives (the model becomes sure). Surfacing it cost zero extra
compute — one line, `var = -1/H` — and it became the single most "alive" signal in the
product: a live readout of *the model getting surer about you* as you answer. The
uncertainty was free the whole time; I just wasn't returning it.

**Lesson 4:** the quantity you need is sometimes already inside a computation you're
running — check what you're discarding before you build something new.

## What generalizes beyond this project

1. **Interrogate the ceiling before optimizing.** A flat metric across very different
   strategies is a tell that the cap is outside your model — labels, leakage, or eval
   regime. (Kaggle 0.752.)
2. **Split by the unit you'll be cold on.** Row-splits leak; group-aware splits tell the
   truth. The split *is* the definition of the metric. (IRT 0.506.)
3. **Benchmarking and serving are different objectives.** The highest-AUC model can be the
   wrong one to deploy when its assumptions don't survive contact with a real request.
   (SAKT 0.803 offline, online IRT live.)
4. **Audit what you throw away.** The uncertainty estimate was a byproduct of a computation
   already running. (`−1/H`.)

None of these are advanced. They're the difference between a project that reports a number
and one that understands what the number measures — which is most of what "ML maturity"
actually is.

---

*Code: the live estimator is [`src/reflecta/models/online_irt.py`](../src/reflecta/models/online_irt.py)
(`estimate_ability_var`, `session_vitals`); the serving seam is
[`src/reflecta/serving.py`](../src/reflecta/serving.py) (`get_mastery_estimator`); the
offline models and their real logged metrics are in `models_store/` + `mlflow.db`, surfaced
live on the app's Model Lab page. Every reported number comes from a group-aware split by
learner.*
