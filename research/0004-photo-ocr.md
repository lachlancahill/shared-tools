# 0004 — Photo OCR on a zero-retention multimodal model

- Date: 2026-11-07
- Status: accepted and built, including orientation; chat wires in the tool group next

## Context
Users upload phone photos of printed course pages, and agents in projects need the words.
The test photo is hard: skewed, with highlighter over text, binder-ring shadows and italics.
The requirement is the cheapest zero-data-retention (ZDR) service that reads these reliably.

The consumer's research/0038 ("no cloud OCR, ever again") followed a NZ$165 Cloud Vision
bill and leaves legal-assistant's `read_scan` disabled. That still stands for its bulk
scans and uploads. This package is a separate, deliberate decision by Lachlan on
2026-11-07: one photo at a time, at the agent's request, with a bounded cost, and not on
Google Cloud.

## Decision
`zai-org/GLM-5.3-Flash` on DeepInfra: US$0.15/$0.50 per million tokens, about US$0.0007 for
a full page at 1568 px, and at most US$0.0026 a call. It ships as `photo-ocr`, with a
non-default `photo-ocr` tool contract like `nz-law`.

Qwen3-VL-30B led the first two rounds and was built first. Scoring the package at the exact
production size then showed it turning "Which witnesses are you going to call?" into "Which
facts are you going to agree on?", which is why round 3 exists. Its earlier clean scores
at 1200 and 2000 px had hidden this. **A model's score at one size does not predict the next.**

## Results
Character error rate (%), per repeat at temperature 0. The reference for the real photo
was typed by hand and matched several models exactly. The synthetic pages hold invented
text, including deliberate misspellings and citations; all six finalists kept those.

Round 1, all models, two repeats. The real photo at 2000 px, 1200 px and turned 90°:

| Model | 2000 px | 1200 px | Turned 90° | About US$/page | ZDR badge |
|---|---|---|---|---|---|
| **GLM-5.3-Flash** | 0 | 0 | 0.03–0.2 | 0.0007 | yes |
| Qwen3-VL-30B | 0 | 0 | 0 | 0.0007 | yes |
| Seed-2.0-mini | 0 | 0–0.03 | 0 | 0.0009 | **no** |
| Ling-3.0-flash-VL | 0 | 0 | 0.1 | 0.0005 | yes |
| Mistral-Small-3.2 | 0.03 | 0.03 | 1.7 | 0.0003 | yes |
| Gemma-4-26B | 0.03–0.07 | 0.07–0.2 | 8–14 | 0.0002 | yes |
| Qwen3.5-9B | 0 | 0 | 28–100 | 0.0004 | yes |
| MiMo-V2.6-Flash | 0 | 17–100 | 100 | 0.0010 | yes |
| Gemma-3-12B | 15 | 14 | 46–50 | 0.0001 | yes |
| Gemma-3-4B | 25 | 29–656 | 105–131 | 0.0001 | yes |

Round 2, finalists, three repeats, harsher conditions. Worst repeat shown:

| Model | Blur | Dim, noisy | 800 px | 12° tilt | Table | Handwriting font | Blank page |
|---|---|---|---|---|---|---|---|
| **GLM-5.3-Flash** | 0.4 | 0 | 1.6 | 0 | 0 | 0.6 | `[illegible]` |
| Qwen3-VL-30B | 0.2 | 0 | 4.3 | 2.3 | 0 | 1.2 | `[illegible]` |
| Seed-2.0-mini | 0.3 | 0 | 0 | 0 | 0 | 0.6 | commentary |
| Ling-3.0-flash-VL | 0.5 | 0 | 0.1 | 33.7 | 0 | 0 | leaked its reasoning |
| Mistral-Small-3.2 | 2.5 | 0.1 | 2.4 | 5.5 | 9.1* | 0.6 | `[illegible]` |
| Gemma-4-26B | 7.5 | 0.7 | 2.2 | 1.3 | 0 | 0.6 | a refusal |

\* Mostly Markdown table separators counted by the scorer, not misread cells.

Round 3, the real photo at twelve sizes, two repeats, counting words that differ:

| Long edge (px) | 1000 | 1200 | 1400 | 1500 | **1568** | 1600 | 1700 | 1800 | 2000 | 2200 | 2400 | 2800 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **GLM-5.3-Flash** | 0 | 0 | 1 | 0 | **0** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Qwen3-VL-30B | 4 | 0 | 0 | 0 | **2** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

GLM's one difference is a surname missing one letter. Qwen's are lost sentences at 1000 px
and the changed question at 1568 px, the size chat stores. GLM is not fully repeatable:
a later three reads through the package at 1568 px gave two exact copies and one with the
surname a letter short. All three cost US$0.0004–0.0007, the lower figures with prompt
caching. On the same model, a photo saying "ignore all previous instructions" was
transcribed rather than obeyed three times out of three, and a blank page returned
`[illegible]` three times out of three. `for_model` still fences photo text, because the
agent reads it next.

### Orientation (measured, then built)

Phones pointed down at a flat page often save the wrong orientation, so EXIF cannot be
relied on. The model without correction, three reads at 1568 px, counting words that differ:

| Turned | 0° | 3–12° | 20° | 30° | 45° | 90° | 180° | 270° |
|---|---|---|---|---|---|---|---|---|
| No correction | 0 | 0 | 1–2 | 1 | 11–14 | 1 | 2–5, one read lost a sentence | 2 |
| Classifier first | 0 | not run | not run | not run | not run | 0 | 0 | 0 |

`PP-LCNet_x1_0_doc_ori` (Apache-2.0, 6.8 MB, ONNX) sorts a page into four orientations. It
was right on 47 of 48 turned copies of 12 test pages, taking about 14 ms on a laptop CPU.
Its one miss was a blank page, at 0.32 confidence; every page with text scored 0.50 or more,
so a 0.5 threshold made no wrong turn in this set. Its confidence tops out near 0.93, so a
threshold of 0.95 would never act. Tesseract's detector, the alternative needing no new
model, got 35 of 48, wrongly turned an upright blurred page and found nothing on a very
short crop. Neither fixes skew, and a page at 45° still needs a better photo.

It costs 78 MB of `onnxruntime` plus the model in each consumer's image, about 80 MB of
memory once loaded and a 1.6 s first import. All of that waits until the first photo is read,
because `orientation.py` imports lazily. The label is how far the page sits clockwise, so
`image.rotate(label)` undoes it.

As built, it runs after EXIF rotation and after shrinking to 1568 px, the size it was measured
at, and turns a page only at 0.5 confidence or more. Repeating the 48 copies through the
package gave the same labels and confidences: 47 of 48 right, with the blank page left alone
because it scored below the threshold. A first version used `resize(box=...)` instead of the
model's exact recipe. It made the same decisions, but dropped the weakest turned page from
0.585 to 0.538, so the exact recipe stayed; only a strip longer than twice its width is cut first.

The model is committed in the package, unchanged from upstream commit `7330ab7` and pinned by
a test on its hash, rather than downloaded when first used. A download would add a network
failure and a supply-chain step to every cold process, to save 6.8 MB. It is Apache-2.0, with
the licence beside it (`models/`), which covers that file only.

## Why
- **Failures are plausible, so a low average is not enough.** Models replaced a surname with
  an unrelated place, and one phrase with another that read just as well. Ling dropped a
  third of a page on one repeat of three.
- **GLM-5.3-Flash over Qwen.** Same price, about four times faster, and no change of meaning
  on the sharp real photo at any tested size.
- **GLM is not immune.** Under heavy blur it rewrote a header and a surname, varying between
  repeats, and at 800 px it replaced a phrase. Every finalist erred somewhere, so readings
  must stay labelled as machine-made.
- **Cheaper is not worth it here.** Mistral saves US$0.40 per thousand pages, but dropped
  and invented sentences. The specialist options below save about US$0.60.

## Alternatives considered
- **OCR specialists (GLM-OCR, PaddleOCR-VL, DeepSeek-OCR-2).** They lead published
  benchmarks and cost about US$0.03/M, so perhaps a tenth per page. **Not tested on the
  real photo:** DeepInfra and OpenRouter list none. Together's versions are not serverless.
  Novita's ZDR is unconfirmed. Z.ai's API terms say content is not stored, but no key is held.
- **The same model through OpenRouter with `provider.zdr`.** Its ZDR list shows
  GLM-5.3-Flash on Relace at US$0.0285/$0.0923, perhaps a fifth of the price, saving about
  US$0.50 per thousand pages. **Untested:** no key is held, and another host's build may
  read differently. It is the first thing to try if volume grows; rerun round 3 first.
- **Reading each page with two models and flagging disagreements.** GLM and Qwen erred in
  different places, so this might expose wrong words that nothing else signals, at about
  twice the cost. Not built: it needs testing, and may be worth it for legal quotation.
- **Seed-2.0-mini.** Most accurate here, but a "Partner" model with no "Zero retention"
  badge. Disqualified. Variants of the test photo reached it during this comparison before
  that was noticed; the photo contains course material and no personal details.
- **Mistral OCR, Google Cloud Vision.** Vision is ruled out by the consumer's 0038. Mistral's
  ZDR and page price could not be confirmed from its public pages.
- **Consumer-owned HTTP, as in legal-corpus.** Rejected: model, prompt and bounds are what
  this package exists to share. It departs from 0001's "no model client" only here, using
  plain httpx, and the key is still the consumer's.

## Consequences
- The evidence is **one real page and invented pages**. It shows the choice is sound, not
  that it is reliable on every photo. Curved pages near a spine, small print and real
  handwriting are untested; the handwriting test used a font.
- "Zero retention" is DeepInfra's badge and terms. No contract has been reviewed, and the
  badge can change; recheck it if the model changes.
- Never add a real photo as a test fixture: this repository is public.
- Orientation is one more model that can be wrong, and a wrong turn would damage a good page.
  The evidence is the same small set, and text scoring near 0.5 is the risk to watch.
- A consumer must keep `for_model`'s warning and limit calls. A single call is bounded by
  `MAX_COST_PER_PHOTO_USD`, but the number of calls is not bounded here.
- Prices move. Rerun a comparison before switching models, not just a price check.
