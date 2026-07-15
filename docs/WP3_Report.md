![askEarth](header_logo.png)

*askEarth AG · WP3 report*

---

# WP3: LLM Provisioning

**Feasibility of state-of-the-art and alternative model options for SWISSGEO conversational access**

---

## Legends in this report

*Table 1. Verdict wording used in tables*

| Verdict wording used in tables | What it means |
|---|---|
| **Ready** | Production-ready, or the recommended choice |
| **Caveat** | Usable, but with a stated limitation, or worth watching |
| **Not viable** | Ruled out for this project specifically |
| **Reference** | Useful for comparison; not a deployment candidate |

*Table 2. Jurisdiction tag*

| Jurisdiction tag | Meaning |
|---|---|
| **[CH]** | Swiss jurisdiction (headquartered, trained, or hostable in Switzerland) |
| **[EU]** | European Union jurisdiction |
| **[US]** | United States jurisdiction |
| **[CN]** | Chinese jurisdiction |

This tag is a simplification of something more layered. Who legally owns the vendor, where processing physically happens, and where the model was trained aren't always the same country. §6 unpacks all three properly, with the legal entity behind every model in this report and what it implies.

Every model and platform table also carries an **openness tier**:

*Table 3. Openness tier*

| Openness tier | What it means | Example |
|---|---|---|
| **Open-source** | Weights, training data *and* code are all released | Apertus, OLMo, EuroLLM |
| **Open-weight** | Only the trained weights are released; training data and code are not | Mistral, gpt-oss, DeepSeek, Qwen, GLM, Kimi |
| **Closed** | Available only as a paid API; nothing is released | Claude, GPT, Gemini, Grok, Nova |
| **Restricted** | Weights released, but under a license that limits who may use them | Llama 4 |

Cost figures follow rule: **Low / Central / High**, where Low and High are floor-and-ceiling estimates - the cheapest and most expensive realistic setups we could find, not a narrow band around the middle. A single-point figure is called out as such rather than dressed up as a range.

---

## Contents

1. [Summary](#1-summary)
2. [Scope](#2-scope)
3. [Requirements and constraints](#3-requirements-and-constraints)
4. [Cost](#4-cost)
5. [Model options](#5-model-options)
6. [Platform and residency options](#6-platform-and-residency-options)
7. [Recommendation and plan](#7-recommendation-and-plan)
8. [Risks](#8-risks)
9. [References](#9-references)

---

## 1. Summary

This report answers one question for swisstopo: which LLM (the AI system that understands and answers a user's question) should power SWISSGEO's conversational access to the geo.admin.ch catalogue, and what are the credible alternatives.

> **Recommendation:** deploy Anthropic's Claude models via Amazon Bedrock, Amazon's managed service for running AI models and already part of swisstopo's infrastructure, using its EU-resident routing option. Bedrock calls these "`eu.` profiles": the request is guaranteed to process inside EU data centres rather than route globally. Start with the mid-tier model, Sonnet 4.6, as the default. Keep a watch on European, Chinese-origin and Swiss (Apertus) alternatives, and potentially switch if the situation changes.

**Cost.** At a realistic production volume, Sonnet 4.6 runs roughly CHF 690–1,030/month non-optimized, potentially falling to CHF 180–270/month when the optimization stack is built; see §4.3 for the full derivation, §4.5 for the optimization stack, and §4.7 for the higher-volume case.

**Answer quality on multi-step tasks.** Where models actually differ is in chaining several tool calls together, recovering from an error mid-conversation, and knowing when to say "no data exists" instead of guessing; agentic readiness is best reviewed in §5.7 (Table 25).

**Sovereignty.** It has many steps from a cloud API to fully on-premises hardware, and each step trades cost against control differently. Our recommendation is the first step (§6.1, Table 26).

*Table 4. Summary questions and answers*

| Question | Answer | Confidence |
|---|---|---|
| What should we deploy? | Claude Sonnet 4.6 via Amazon Bedrock, EU-resident routing, on swisstopo's existing AWS account | High, closest to contract requirement; matches a live government precedent (GOV.UK Chat) |
| What will it cost? | Central estimate is CHF 690–1,030/month non-optimized, potentially CHF 180–270/month optimized, at a realistic production volume (full breakdown in §4.3, optimization stages in §4.5, higher-volume case in §4.7, pilot cost in §4.3's table) | High for the unit-cost arithmetic; Medium for adoption volume and query complexity, both our best estimate until pilot data exists; the optimized figures depend on which get built and their effectiveness |
| How sovereign? | It's the first step of five. Every step uses the same API, so moving between them is a configuration change after setup (§6.1, Table 26) | High |
| What's the fallback? | Mistral Large 3 (European, open-weight) is the strongest alternative on current evidence, but it's a clear step down from Claude on demonstrated agentic capability, not a peer contender; Apertus (Swiss, open-source) not yet viable (§5.3 Table 20; §5.7 Table 25) | High on the ranking; Medium on timing, since it depends on Apertus v1.5, which has no release date and unknown performance |

---

## 2. Scope

WP3 of the Phase-2 contract asks for two things: a state-of-the-art LLM provisioned on swisstopo's own AWS infrastructure, and a consideration of the feasibility of alternatives, naming open-source and open-weight models such as OLMo, and the Swiss model Apertus, explicitly.

It also answers three other pieces of client input directly:

- **SGS-5-25-2** (24.11.2025), swisstopo's own decision-basis report for integrating LLMs into the national geodata infrastructure, which sets the governance constraints this report works within (§3, Table 6).
- **Five questions**: Bedrock cost, open-model cost, whether a large model is even needed, whether a small self-hosted model would suffice, and how to control cost; answered across §4 and §5.

### 2.1 Document map

*Table 5. Document map*

| Source document | What it asked for | Where this report answers it |
|---|---|---|
| Phase-2 contract, WP3 clause | SotA LLM deployment plus an alternatives report (incl. OLMo, Apertus) | Whole document; §5.3–§5.7 for the alternatives |
| SGS-5-25-2 | Governance constraints, risk classification, sovereignty preference | §3 (Table 6), §6.1–§6.2 |
| Five coordination questions (06.07.2026) | Bedrock cost / open-model cost / model size / self-hosting / cost control | §4.3, §4.5, §4.8, §5.2–§5.7 |

---

## 3. Requirements and constraints

*Table 6. Requirements and constraints*

| Constraint | Source | Binding or preferred? | Addressed in |
|---|---|---|---|
| Deployed on swisstopo's AWS infrastructure; open-source repository on swisstopo's GitHub | Contract | Binding | §6.1 (Table 26, step 1 — Bedrock `eu.` profiles); §7.1 (Table 30, Level 1) |
| Only swisstopo data: no OpenStreetMap, no fusion with outside sources; the assistant adds value to the existing geoadmin API rather than replacing it | PoC kickoff | Binding | §2 (scope boundary) — a tool/API-design constraint, outside this report's model-comparison tables |
| Every answer cites its source; the assistant says plainly when no matching data exists rather than guessing | PoC kickoff, SGS report | Binding | §5.1 (refusal/error-recovery benchmark evidence [23][24]) |
| Coordinate system EPSG:2056 (the Swiss national grid); catalogue of roughly 16,000 datasets / 800+ layers | PoC kickoff | Binding | §5.1 (geospatial tool-use and long-context benchmark evidence [20][25]) — context for scale, not a dedicated table |
| Working languages: German, French, Italian, English. Romansh and Swiss German are Swiss-specific ambitions, keep updated | PoC kickoff; WP5 test plan | Binding (DE/FR/IT/EN); keep updated (RM/gsw) | §5.6 (Table 24, Romansh/Swiss German rows); §7.1 (Table 30, Level 2 gate — WP5 evaluation) |
| Risk classification: limited risk, since the data handled is open, non-personal, and the assistant is read-only and informational | SGS-5-25-2 | Shapes governance weight | §6.2 (public, non-personal data framing) |
| Sovereignty: data handling, model training and operational use should occur as far as possible on national or European infrastructure | SGS-5-25-2 | Preferred | §6.1 (Table 26, the sovereignty scale) |
| eCH-0272, the Swiss standard for transparency in AI systems, applies to pre-trained, locally-operated systems - cloud-only GenAI is outside its scope | eCH-0272 standard | Contextual | §6.2 (provenance and standards discussion) |
| Test-case-driven decisions: the SGS report's own mechanism for choosing a model is a dedicated evaluation, not a specification on paper | SGS-5-25-2 | Binding on method | §7.1 (Table 30, WP5 evaluation gate) |

---

## 4. Cost

### 4.1 Three ways to pay for an LLM

*Table 7. Three ways to pay for an LLM*

| Mode | What it is | Who owns the infrastructure | What you're billed for | Minimum realistic commitment | When it's the right choice |
|---|---|---|---|---|---|
| **Serverless API** (Amazon Bedrock, or a vendor's own API) | You send a request to a model someone else runs; you never touch a server | The cloud vendor | Per token | None - pay for what you use | Any volume, especially traffic that's uncertain or bursty - **this project's situation** |
| **Self-hosted server** (Amazon SageMaker, or a rented cloud GPU) | You rent a GPU-equipped machine and run the model's software on it yourself | You, on the vendor's hardware | Per hour the machine is switched on, regardless of how much it's used | The machine typically needs to run near-continuously to be worth deploying | An open-weight model isn't available serverless or inference has to be in a specific country |
| **On-premises hardware** | You buy physical GPU servers and run them in your own building or a data centre you control | You, entirely | Hardware capex, power, and salaries | A multi-year hardware purchase and a standing operations team | Only when physical, air-gapped control is mandated (§4.8) |

### 4.2 How many conversations will there be?

The public `sgs-llm` cost model scales "40–80,000 portal hits/day" into scenarios of up to 20,000 assistant conversations per day. Published data from comparable, already-live government assistants suggests that's about two orders of magnitude too high:

*Table 8. Comparable government-assistant deployments*

| Deployment | Scale | Published volume | Rate |
|---|---|---|---|
| GOV.UK Chat (Claude on Bedrock) [5] | National (68 million population) | 15,000+ questions, 7-week soft launch | ~306 questions/day |
| ZüriCityGPT (Liip, City of Zurich) [7] | City-level | 39,000 conversations in 8 months | ~160 conversations/day |
| RNP assistant, City of Riga [69] | Municipal (housing authority), not national | ~47,000 conversations in 5 months | ~310 conversations/day |
| GOV.UK, 18-month pilot phase [6] | National | 26,000 questions, 10,000+ users | Accuracy bar rose 76% → 90% over the pilot |

This report grounds Low and Central directly in what the comparable deployments above actually recorded, then uses swisstopo's own real traffic, not a generic industry benchmark, to set a High that reflects swisstopo's genuinely larger reach, rather than either ignoring that traffic entirely or projecting it through an unrelated benchmark:

*Table 9. Low / Central / High volume assumptions*

| | Low | Central | High |
|---|---|---|---|
| Basis | ZüriCityGPT [7], the smallest and only other Swiss deployment in this set | Simple average across the three live deployments with a daily rate (ZüriCityGPT, GOV.UK Chat, RNP Riga) [5][7][69] | Swisstopo's own traffic [4], at the same conservative, task-driven open rate that independently reproduces Central (see below) |
| Conversations/day | ~160 | ~260 | ~452 (90,400 visits/day × 0.5% open rate) |
| **Turns/day** | **~440** (2.75 turns/conversation) | **~715** (2.75 turns/conversation) | **~1,350** (Larger, more habitual audience plausibly runs longer sessions) |

Low and Central are narrow (roughly 2× apart) because that's what the evidence actually shows: GOV.UK Chat (national, 68 million population) and RNP Riga (a single municipal housing authority) land within a few percent of each other despite a huge difference in the population each one serves, and ZüriCityGPT isn't far below either. Reach doesn't appear to scale with population for this category of assistant

High: map.geo.admin.ch recorded 33 million visits in 2025, ~90,400/day [4]. A generic live-chat benchmark (2–8%, up to 15% with pop-ups [58]) would imply several thousand turns/day (far above any comparable government assistant on record), so this report instead uses a conservative, portal-adjusted open rate of 0.5%, reflecting that geodata-portal visitors mostly arrive already knowing what they want. That rate cross-checks against precedent: a similarly conservative ~0.3% rate, applied with the midpoint turns/conversation to swisstopo's own traffic, independently reproduces ~680 turns/day, within 5% of Central, two unrelated methods converging on the same place. High simply carries that logic to the top of the plausible range (0.5% open rate, 3 turns/conversation) on swisstopo's real traffic.

### 4.3 What does one conversation cost, before optimization?

Pricing basis: a typical agent turn (one question, including its internal tool calls) uses about 5,000 input tokens and 300 output tokens; a complex, multi-step turn uses 2–3× that. Vendor list prices are quoted in USD (Anthropic's own currency for Bedrock), then converted to CHF for every cost estimate in this report at the current USD/CHF rate (≈0.81, pulled 14.07.2026 [73]) to avoid mixing currencies. (§4.6's price-history table below is the one exception, left in USD since it quotes vendors' own published list prices as a directly checkable historical record.) Figures are per Claude model, on Bedrock, EU-resident routing (+10% over the global rate), pulled 14.07.2026 [9]. For example, Sonnet 4.6 at $3/$15 per million tokens (≈CHF 2.43/CHF 12.15) costs 5,000 × CHF 2.43/1,000,000 + 300 × CHF 12.15/1,000,000 ≈ CHF 0.0158 per lean turn; at Central (715 turns/day × 30.4 days/month, the 365/12 average used consistently throughout this report) that's 21,748 turns/month × CHF 0.0158 ≈ CHF 344/month. Monthly figures throughout this report use that same 30.4 days/month, so monthly × 12 always reconciles with the annual figures quoted elsewhere:

*Table 10. Per-model pricing, naive (no caching, no routing)*

| Model | CHF per 1M input / output tokens | CHF/turn | Pilot (~60 turns/day) | Low (440 turns/day) | Central (715 turns/day) | High (1,350 turns/day) |
|---|---|---|---|---|---|---|
| Haiku 4.5 (the potential "routing tier") | 0.81 / 4.05 | 0.0053 | ~CHF 10/mo | ~CHF 70/mo | ~CHF 114/mo | ~CHF 216/mo |
| Sonnet 4.6 (simple query average) | 2.43 / 12.15 | 0.0158 | ~CHF 29/mo | ~CHF 211/mo | ~CHF 344/mo | ~CHF 649/mo |
| **Sonnet 4.6**, **complex, multi-step queries** (2–3× tokens/turn) | 2.43 / 12.15 | 0.0316–0.0474 | ~CHF 58–86/mo | **~CHF 423–634/mo** | **~CHF 687–1,030/mo** | **~CHF 1,297–1,946/mo** |
| Sonnet 5 (intro price to 31.08.2026, then CHF 2.43/12.15) | 1.62 / 8.10 | 0.0105 | ~CHF 19/mo | ~CHF 141/mo | ~CHF 229/mo | ~CHF 432/mo |
| Opus 4.8 (quality ceiling probe) | 4.05 / 20.25 | 0.0263 | ~CHF 48/mo | ~CHF 352/mo | ~CHF 573/mo | ~CHF 1,081/mo |
| Mistral Large 3 (La Plateforme, EU vendor, simple query average) [74] | 1.62 / 4.86 | 0.0096 | ~CHF 17/mo | ~CHF 128/mo | ~CHF 208/mo | ~CHF 392/mo |
| **Mistral Large 3**, **complex, multi-step queries** (2–3× tokens/turn) [74] | 1.62 / 4.86 | 0.0191–0.0287 | ~CHF 35–52/mo | ~CHF 256–384/mo | ~CHF 416–623/mo | ~CHF 785–1,177/mo |

Every figure above is naive: no caching, no routing, nothing.

### 4.4 The same workload, three ways to run it

*Table 11. Deployment mode comparison, annual*

| Deployment mode | Low (CHF/year) | Central (CHF/year) | High (CHF/year) | Notes |
|---|---|---|---|---|
| **Serverless (Bedrock, Sonnet 4.6, complex queries, naive)**| ~5,076–7,608 | ~8,244–12,360 | ~15,564–23,352 | The simpler lean-question floor is lower, at ~2,532/4,128/7,788/year |
| Serverless (Bedrock, Sonnet 4.6, complex queries, optimized, previewing §4.5) | ~1,320–1,980 | ~2,148–3,216 | ~4,044–6,072 | Lean floor optimized: ~55–169/month |
| Serverless (Mistral Large 3, La Plateforme, complex queries, naive) [74] | ~3,072–4,608 | ~4,992–7,476 | ~9,420–14,124 | EU vendor, not swisstopo's existing AWS contract; not reachable via Bedrock in an EU region (§5.3 Table 19, §6.1 Table 26). Lean floor: ~1,536/2,496/4,704/year |
| Self-hosted server (SageMaker, open-weight model, 24/7 in Zurich) | ~150,000 | ~205,000 | ~260,000 | Fixed regardless of how many conversations actually happen |
| On-premises (small rig, business-hours operation) | ~137,000 | ~208,000 | ~280,000 | Fixed, three-year hardware amortization, 0.5–1 FTE of staff time |
| On-premises (production-scale, 8×H100-class rig) | ~470,000 | ~625,000 | ~780,000 | Only when requirement for physical control (§4.8) |

The pattern holds at every volume this project is likely to see: serverless cost scales with actual use, while self-hosted and on-premises costs are fixed regardless of use, and at this precedent-grounded volume serverless remains two to three orders of magnitude cheaper even before optimization.

### 4.5 What brings the naive number down

Everything that follows is what can bring the naive estimate down with extra work. The numbers below reflect probable estimates, rather than a best case.

This project's recommended path is serverless (§4.4 above). The levers above the line apply to that path; the levers below it only matter for a fixed-cost self-hosted or on-prem deployment, which isn't being recommended here:

*Table 12. Optimization levers*

| Lever | Mechanism | Realistic saving | Applies to |
|---|---|---|---|
| Prompt caching | Repeated system instructions and tool definitions are billed at a tenth of the price on re-use within a session | 30–45% off the cost of calls that still reach a model | Serverless, self-hosted |
| Model routing (what some vendors market separately as "cascading" is the same mechanism: send easy questions to a cheap model, escalate the hard ones.) [13] | Simple questions answered by Haiku; hard ones escalate to Sonnet or Opus | Depends entirely on how much real traffic turns out to be simple, which is unproven for swisstopo's query mix until the evaluation and pilot logs exist. Published extremes (10–20× cheaper) assume most traffic is simple; this report uses a more modest working assumption until it's measured | All modes |
| Semantic answer caching [15] | A repeated question is answered from a stored prior answer, without calling a model at all | 20–35% of turns removed, toward the conservative end of the 30–70% published range, since swisstopo-specific repeat-question rates aren't known yet | All modes |
| ***— not applicable to this project's recommended serverless path —*** | | | |
| Scale-to-zero scheduling | Infrastructure not mostly needed overnight or on weekends isn't paid for then | Relevant only where the bill is otherwise fixed | Self-hosted, on-prem |
| Reserved/committed pricing | Committing to a usage volume or instance-hours in advance | ~60% off list, on infrastructure that's already rented long-term anyway | Self-hosted, on-prem |

*Table 13. Running total after each optimization stage*

| Stage | What optimizations applied | Running total (central est, Sonnet 4.6) |
|---|---|---|
| Naive | Nothing yet | CHF 687–1,030/month |
| + Semantic caching | ~25% of turns answered from cache, no model call | CHF 515–773/month |
| + Prompt caching | ~35% off whatever still reaches a model | CHF 335–502/month |
| + Model routing | Of the remaining calls, roughly two-thirds go to Haiku at ~30% of Sonnet's cost | CHF 179–268/month |

That's a reduction to roughly a quarter of the naive figure (factor 0.26, ÷3.8). Overlap between semantic and prompt caching is accounted for and routing is calibrated on real, not assumed, traffic. Semantic and prompt caching ship first since both are available directly from the cloud provider; model routing ships last since it requires building and tuning the routing logic itself. If only caching ships near-term, a more conservative interim figure is **CHF 335–502/month**, with routing added later once real traffic data justifies it.

**Self-hosted server (SageMaker or similar).** These levers barely move this bill: it's a rental, not a metered charge, so caching and routing only affect efficiency, not cost. The lever that matters here is scale-to-zero scheduling: running only during real usage hours instead of 24/7. Bedrock's own Custom Model Import pricing for a comparable model, active ~12h/day, gives ~CHF 95,000–110,000/year, against ~CHF 205,000/year continuous.

**On-premises.** No meaningful reduction applies: hardware and staff are paid for regardless of volume. Software efficiency only buys headroom (delaying the next hardware purchase or hire), not a lower standing bill.

This is why serverless is the default recommendation here: it's the only mode where efficiency gains lower the bill rather than just freeing up already-paid-for capacity.

### 4.6 What changes over time: capability, not the price tag

The industry habit is to project a single "AI inference gets X% cheaper per year" curve forward and apply it to today's bill. That curve is real at the level of compute economics, but it doesn't describe what happens to a specific, persisting deployment, for two reasons worth separating: the model itself doesn't sit still and get a discount (it gets retired), and the number of tokens a task actually consumes is moving too, mostly upward. 

**Models don't get cheaper: they get retired.** Anthropic does not keep a fixed model on sale at a falling price; it publishes a retirement date, typically 12–18 months after release, and requires migration to whatever replaces it [70]:

*Table 14. Claude model deprecation schedule*

| Model | Deprecated (notice given) | Retired (requests fail) |
|---|---|---|
| Claude Sonnet 3.5 (both releases) | 13 Aug 2025 | 28 Oct 2025 |
| Claude Sonnet 3.7 | 28 Oct 2025 | 19 Feb 2026 |
| Claude Haiku 3.5 | 19 Dec 2025 | 19 Feb 2026 |
| Claude Haiku 3 | 19 Feb 2026 | 20 Apr 2026 |
| Claude Sonnet 4 / Claude Opus 4 | 14 Apr 2026 | 15 Jun 2026 |
| Claude Opus 4.1 | 5 Jun 2026 | 5 Aug 2026 (scheduled) |

On any planning horizon past roughly 18 months, Sonnet 4.6 (the model recommended in this report) will not be an option any more. swisstopo will be migrating to whatever the then-current Sonnet-tier model is and re-validating it against the WP5 test cases before switching over, regardless of whether the replacement turns out cheaper, the same price, or more expensive. Anthropic frames the retirements as a byproduct of keeping the frontier moving, not as a service guarantee, and has committed only to preserving retired models' weights for research, not to keeping them purchasable [71].

What a given tier has actually billed at, tracked release by release: [9]

*Table 15. Claude tier price history*

| Model | Released | Price ($/M in, $/M out) | Change from the prior release in that tier |
|---|---|---|---|
| Claude Sonnet 3.7 | Feb 2025 | $3 / $15 | n/a, first in series |
| Claude Sonnet 4.6 | Feb 2026 | $3 / $15 | No change in a year |
| Claude Sonnet 5 | Jun 2026 | $2 / $10 introductory, then $3 / $15 from 1 Sep 2026 | Temporary launch discount only; standard rate unchanged |
| Claude Opus 4 / 4.1 | 2025 | $15 / $75 | n/a, first in series |
| Claude Opus 4.5 → 4.8 | Nov 2025 – May 2026 | $5 / $25 | One real cut (−67%), delivered by retiring Opus 4 and shipping a new model. Flat across four releases since |
| Claude Fable 5 | Jun 2026 | $10 / $50 | The newest, most capable tier on the price list, priced *above* Opus 4.8 |

Over ~16 months and three Sonnet-tier releases, the mid-tier list price hasn't moved: what's changed is capability at a held price, not price at held capability. Opus shows the one genuine price cut, achieved by discontinuing the old model and launching a cheaper one, not by repricing the same product. Fable 5 shows the mechanism can run the other way too: Anthropic's newest frontier tier launched more expensive than the model it sits above.

**What this means for the Gartner / Goldman Sachs / Epoch bands used elsewhere as background context [16][17][18]:** those studies describe industry-wide compute cost per unit of intelligence falling, which is real, and it does eventually show up as capability moving down the price list (today's Sonnet-level performance reaching Haiku, say). But that's not the same as this deployment's bill falling automatically. Capturing the saving needs an active decision: re-testing a cheaper model against the WP5 evaluation set once it looks good enough, then switching, exactly the Level 2/3 progression already recommended (§7). Waiting passively captures nothing; forced migration on the deprecation schedule above delivers a mix of cheaper, same, or occasionally pricier, depending on what's current when the old tier retires.

**Does token volume undercut the price side of the story? Mostly, yes**:

- Agentic tasks draw 5–30× the tokens of a standard chat turn [16]. This is directly relevant, since SWISSGEO's own queries are tool-calling/agentic by design (§3, Table 6), not plain chat.
- Live agent deployments typically grow from ~200 to 10,000+ tokens/request within weeks, as history, tool output and system-prompt size accumulate [72].
- This project's own estimate (§4.2–4.3): a complex, multi-step query already runs 2–3× a lean lookup's tokens, before any of the above growth is factored in.

Combined: if tokens/turn rise 3× (a conservative read of the complex-query estimate) while price falls at Goldman Sachs's central ~65%/year, the net effect is 3 × 0.35 ≈ 1.05×: the bill stays roughly flat, not three times lower. At Gartner's more conservative −37%/year, the same 3× token growth pushes the bill up ~90%. Token growth can cancel or reverse a headline price cut; tracking $/token without tracking tokens/turn is optimistic by construction [72].

**Practical takeaway.** Don't budget against a smooth "prices fall 40–90%/year" curve on today's figure. A migration event roughly every 12–18 months when the recommended model retires and its replacement needs re-validation against WP5 (an operational cost, not just a pricing one); a real chance the per-token price stays flat for a year or more, as Sonnet's has since Feb 2025; and a tokens-per-turn trend more likely to rise than fall as query complexity grows, which can absorb some or all of any headline price cut. The figure worth re-checking quarterly isn't $/million tokens: it's CHF per resolved SWISSGEO query, end to end, since that's the only version of "the bill" that reflects both trends at once.

**A note on where the open-weight floor is moving.** Gemma 4, this report's "Reference"-tier small open-weight model (§5.4, Table 22), is currently offered by third-party hosts at roughly $0.06–0.99/M input tokens depending on provider and variant, an order of magnitude below even Haiku 4.5 [75]. Current capability is insufficient but the gap is changing.

### 4.7 The full cost spectrum, in one view

Every scenario and every deployment mode, cheapest to most expensive, with this project's likely position marked. Serverless figures use the realistic, not best-case, optimized numbers from §4.5:

*Table 16. Full cost spectrum*

| Configuration | Monthly cost (CHF, approx.) |
|---|---|
| Pilot, Haiku 4.5, optimized, serverless | ~6 |
| Low (440 turns/day), Sonnet 4.6, lean, optimized (floor case) | ~55 |
| Central (715 turns/day), Sonnet 4.6, lean, optimized (floor case) | ~90 |
| **Central, Sonnet 4.6, complex queries, optimized** | **~179–268** |
| High (1,350 turns/day, swisstopo's own traffic), Sonnet 4.6, lean, optimized (floor case) | ~169 |
| Central, Sonnet 4.6, lean, naive | ~344 |
| **High, Sonnet 4.6, complex queries, optimized** | **~337–506** |
| **Central, Mistral Large 3 (La Plateforme, EU vendor), complex queries, naive** [74] | **~416–623** |
| High, Sonnet 4.6, lean, naive | ~649 |
| **Central, Sonnet 4.6, complex queries, naive** | **~687–1,030** |
| **High, Sonnet 4.6, complex queries, naive** | **~1,297–1,946** |
| Self-hosted server, SageMaker, in-country (Zurich), scale-to-zero | ~7,900–9,200 |
| Self-hosted server, SageMaker, in-country (Zurich), 24/7, unoptimized | ~12,500–21,700 |
| On-premises, small rig, business hours | ~11,400–23,300 |
| On-premises, 8×H100-class production rig, full operations team | ~39,000–65,000 |

"Lean" rows are a floor, kept for reference; SWISSGEO's catalogue-search-heavy query pattern (§3, Table 6) makes the complex-query rows the realistic planning basis. On that basis, the planning range spans roughly CHF 179 to CHF 506 per month once optimized, or CHF 687 to CHF 1,946 per month naive, depending on volume. The Mistral Large 3 row is the one cross-vendor comparison in this table.

### 4.8 Self-hosting

If sovereignty ever requires it, here's the full three-year cost:

*Table 17. Self-hosting, three-year cost*

| Option | Annual, all-in | 3-year total |
|---|---|---|
| Small rig (2 GPUs, business-hours, 0.5–1 FTE) | CHF 137,000–280,000 | CHF 0.4–0.85M |
| Production rig (8×H100-class, 1.5–2.5 FTE) | CHF 470,000–780,000 | CHF 1.4–2.3M |
| SageMaker, in-country, 24/7, 0.2–0.5 FTE | CHF 150,000–260,000 | CHF 0.45–0.8M |
| Bedrock scale-to-zero (Custom Model Import) | ~CHF 95,000 | ~CHF 0.3M |

---

## 5. Model options

### 5.1 Reading the tables below

Two things worth stating before the comparison starts. "On Bedrock" means the model can be called through swisstopo's existing AWS account with no new vendor contract. "Production evidence" means the model has been shown to work for real users in a live deployment, not just scored well on a benchmark.

Where a formal benchmark sits behind a verdict rather than production evidence: geospatial tool-use specifically is scored in GeoBenchX [20]; multi-step MCP tool orchestration in MCPMark [21] and τ²-bench [22]; the failure mode this project cares about most — recovering from an error mid-conversation, or saying "no data exists" instead of guessing (§3) — in 'When Agents Fail to Act' [23] and SciAgentGym [24]; and handling a large catalogue (§3's ~16,000 datasets) in context is the domain of the long-context benchmarks RULER and NoLiMa [25]. None of these are geodata-specific end-to-end proof; they're the closest published evidence for the sub-skills SWISSGEO's assistant actually needs.

### 5.2 Models in one list

*Table 18. Model overview*

| Model | Vendor | Jurisdiction | Openness | On Bedrock? | EU/CH path | Production evidence | Verdict |
|---|---|---|---|---|---|---|---|
| Claude Opus 4.8 | Anthropic | [US] | Closed | Yes | `eu.` profile available | Quality-ceiling role in Claude deployments incl. the GOV.UK Chat family [5][6] | **Ready** |
| **Claude Sonnet 4.6** | Anthropic | [US] | **Closed** | Yes | `eu.` profile available | **GOV.UK Chat runs on this stack, live, national scale; proved for complex use-cases** [5][6] | **Ready, recommended default** |
| Claude Sonnet 5 | Anthropic | [US] | Closed | Yes | Global routing only, no `eu.` profile yet | Newest, ~2 weeks of field data | **Ready** on capability; **Caveat** on EU routing |
| Claude Haiku 4.5 | Anthropic | [US] | Closed | Yes | `eu.` profile available | Matches the prior mid-tier's agent performance at a third of the price | **Ready** (routing tier) |
| Claude Fable 5 | Anthropic | [US] | Closed | Yes | `eu.` profile available, but requires a provider-data-sharing opt-in and forces temperature=1.0 | Newest, most powerful tier; overkill for this use case | **Caveat** |
| GPT-5.5 / 5.4 + Codex | OpenAI | [US] | Closed | Yes, US regions only | Direct API offers EU residency incl. Switzerland | Strong agentic claims; some vendor benchmark comparisons used unequal settings | **Caveat** |
| GPT-5.6 (Sol/Terra/Luna) | OpenAI | [US] | Closed | No | Direct API + EU residency | Newest tier | **Reference** (watch item) |
| Gemini 3.1 Pro / 3.5 Flash | Google | [US] | Closed | No, not on AWS at all | Vertex EU multi-region; no Zurich pinning | Strongest published multilingual scores [33] | **Reference** (wrong cloud for this stack) |
| Grok 4.3 | xAI | [US] | Closed | Yes, US regions only | None documented | Signed only the safety chapter of the EU AI-Act code of practice [44] | **Not viable** here |
| Amazon Nova 2 Lite | Amazon | [US] | Closed | Yes, native | EU regions yes, not invocable from Zurich | Evidence is largely vendor-reported [56] | **Caveat** (executor tier only) |
| Cohere Command A+ | Cohere / Aleph Alpha | [US/EU, merged] | Open-weight | No, not on Bedrock in any form | Self-host only | Citation-native RAG design | **Reference** |
| **Mistral Large 3** | Mistral AI | [EU] (France) | Open-weight (Apache 2.0) | Yes, US/APAC regions only | Self-host, or Mistral's own EU platform, for EU residency | 1M+ French civil servants; French armed-forces framework tests [80] | **Caveat** (the strongest European option, but markedly behind Claude on demonstrated agentic capability, not a peer: no live tool-heavy agent deployment exists, and its function calling has a documented tool-description over-weighting failure mode) |
| Ministral 3 / Devstral 2 / Magistral / Voxtral | Mistral AI | [EU] | Open-weight | Yes, EU regions | `eu.`-region native | Smaller-task / router role | **Ready** (router tier) |
| gpt-oss-120b / 20b | OpenAI | [US] | Open-weight (Apache 2.0) | Yes | EU regions | AI Sweden (on-prem), Orange, Snowflake Cortex | **Caveat** (known failure mode on long tool chains) |
| Gemma 4 | Google | [US] | Open-weight (Apache 2.0) | No | Self-host | Strong small model | **Reference** |
| IBM Granite 4.x | IBM | [US] | Open-weight (Apache 2.0) | No, watsonx not Bedrock | Self-host | "Western Qwen" positioning | **Reference** |
| GLM-5.x | Zhipu AI | [CN] | Open-weight | Yes, some regions | Self-host for full control | Coinbase adopted; scores at frontier level on agentic benchmarks | **Not viable** as core (eval reference only) |
| DeepSeek V3.2 / V4 | DeepSeek | [CN] | Open-weight | Yes, some EU regions | Self-host for full control | Documented tool-call parser instability | **Not viable** as core (eval reference only) |
| Qwen3.x | Alibaba | [CN] | Open-weight (Apache 2.0) | Yes, some EU regions | Self-host for full control | Very large adoption globally; parser friction documented | **Caveat** (self-hosted) |
| Kimi K2.x | Moonshot AI | [CN] | Open-weight (MIT) | Yes | Self-host for full control | Ties GPT-5.5 on a coding benchmark | **Not viable** as core (eval reference only) |
| **Apertus 8B/70B** | Swiss AI Initiative (ETH Zürich, EPFL, CSCS) | [CH] | **Open-source** (weights + data + code, Apache 2.0) | No | SageMaker (Zurich), Swisscom, Infomaniak | CHUV, Canton Ticino translation; zero agentic production deployments found | **Caveat** as core; **Ready** as sovereign sidecar, watched rather than tested |
| OLMo 3 / 3.1 | Allen Institute for AI | [US] | Open-source | No | Self-host | Zero named production deployments | **Not viable** yet (methodological reference only) |
| EuroLLM | EU-funded consortium | [EU] | Open-source | No | Self-host | No native tool calling | **Reference** (multilingual auxiliary only) |
| Llama 4 | Meta | [US] | Restricted licence | Yes | None | Benchmark controversy; licence prohibits EU-domiciled entities from its multimodal models | **Not viable** |

### 5.3 The same models, grouped by family

**Proprietary frontier models**

*Table 19. Proprietary frontier models*

| Model | Jurisdiction | Bedrock + EU from Switzerland? | Verdict |
|---|---|---|---|
| **Claude** (Opus 4.8 / Sonnet 4.6 / Haiku 4.5) | [US] | Yes | **Ready, recommended** |
| GPT-5.5/5.4 | [US] | Bedrock yes, EU routing no (US regions only) | **Caveat** |
| Gemini 3.x | [US] | Not on Bedrock at all | **Reference** (wrong cloud) |
| Grok 4.3 | [US] | Bedrock yes, EU routing no | **Not viable** here |
| Nova 2 Lite | [US] | Bedrock yes, not invocable from Switzerland | **Caveat** (executor tier only) |
| Command A+ | [US/EU] | Not on Bedrock | **Reference** |

**Open-weight models**

*Table 20. Open-weight models*

| Model | Jurisdiction | Verdict |
|---|---|---|
| **Mistral Large 3** | [EU] | **Caveat** (European anchor, a real capability step down from Claude; EU residency comes from Mistral's own La Plateforme platform, not Bedrock, where Mistral is US/APAC-only; self-hosting is an option) |
| gpt-oss-120b | [US] | **Caveat** (long-tool-chain formatting issue) |
| Gemma 4 / Granite 4 | [US] | **Reference** |
| GLM / DeepSeek / Qwen / Kimi | [CN] | See the jurisdiction split below |

**Swiss-specific:** Apertus, the one model here actually built, trained and hostable entirely in Switzerland, and fully open-source rather than merely open-weight.

*Table 21. Swiss-specific: Apertus*

| Model | Jurisdiction | Openness | Verdict |
|---|---|---|---|
| **Apertus 8B/70B** | [CH] | Open-source (the strongest transparency) | **Caveat** as agent core; **Ready** as the sovereign sidecar |

### 5.4 Open-source and open-weight models, in depth

*Table 22. Open-source and open-weight models, in depth*

| Model | Licence | What's released | Trained by | Runs with zero vendor contact? | Verdict |
|---|---|---|---|---|---|
| **Mistral Large 3** / Ministral family | Apache 2.0 [32] | **Weights only** | Mistral AI SAS, Paris, France [EU] [62] | Yes | **Caveat** (the European anchor) |
| gpt-oss-120b / 20b | Apache 2.0 [68] | Weights only | OpenAI Group PBC, USA [US] | Yes | **Caveat** |
| Gemma 4 | Apache 2.0 (the first Apache-licensed Gemma release) [47] | Weights only | Google (Alphabet Inc.), USA [US] | Yes | **Reference** |
| IBM Granite 4.x | Apache 2.0 [67] | Weights only | IBM Corporation, USA [US] | Yes | **Reference** |
| GLM-5.x | MIT [66] | Weights only | Zhipu AI, Beijing, China [CN] | Yes, technically (see the jurisdiction table below) | **Not viable** as core |
| DeepSeek V3.2 / V4 | MIT [66] | Weights only | DeepSeek, Hangzhou, China [CN] | Yes, technically (see the jurisdiction table below) | **Not viable** as core |
| Qwen3.x | Apache 2.0 [66] | Weights only | Alibaba Group, Hangzhou, China [CN] | Yes, technically (see the jurisdiction table below) | **Caveat** (self-hosted) |
| Kimi K2.x | Modified MIT: standard MIT below 100M monthly active users or $20M in monthly revenue; above that threshold, the product must display "Kimi K2" in its interface [64] | Weights only | Moonshot AI, Beijing, China [CN] | Yes, technically (see the jurisdiction table below) | **Not viable** as core |
| **Apertus 8B/70B** | Apache 2.0 [26] | **Weights, training data and code** (the most complete release in this table) | Swiss AI Initiative (ETH Zürich, EPFL, CSCS), Switzerland [CH] | Yes | **Caveat** as core; **Ready** as sidecar |
| OLMo 3 / 3.1 | Apache 2.0 [46] | Weights, training data and code | Allen Institute for AI, Seattle, USA [US] (non-profit research institute, not a commercial vendor) | Yes | **Not viable** yet |
| EuroLLM | Apache 2.0 [54] | Weights, training data and code (near-complete) | EU-funded research consortium, institutions across several member states [EU] | Yes | **Reference** |
| Llama 4 | Meta's own Llama 4 Community Licence, not Apache, not MIT, and not an OSI-approved open-source licence [65] | Weights only, with usage restrictions attached | Meta Platforms, Inc., USA [US] | Technically self-hostable, but the licence itself bars EU-domiciled individuals and companies from its multimodal models, regardless of hosting arrangement [65] | **Not viable** |

Three precisions, since "open" gets used loosely elsewhere. Apache 2.0 and MIT are genuinely permissive, OSI-approved: run indefinitely, no vendor contact, no retroactive licence changes. "Open-weight" (most rows above) is narrower than "open-source": the trained model is released, but not the data or code used to train it, which matters for provenance and eCH-0272's transparency expectations, not for self-hosting. And Llama 4 is the one model here marketed as "open" that isn't: its bespoke Meta licence with a geographic carve-out is a licensing choice, not a technical or jurisdictional one, hence its own category in this table.

### 5.5 Chinese open-weight models

*Table 23. Chinese open-weight models: API vs. self-hosted*

| Model | Via the vendor's own API | Self-hosted (weights downloaded, run on AWS or own infrastructure) |
|---|---|---|
| GLM-5.x, DeepSeek V3.2/V4, Qwen3.x, Kimi K2.x | **Not viable** (data flows to PRC-jurisdiction servers, and Switzerland has no data-adequacy finding for China) | **Caveat** — the vendor has no access to the data or the running system |

Note: bias and weaker safety-robustness remain baked into the weights themselves, potentially mitigated by guardrails and evaluation.

### 5.6 Apertus, in more detail

*Table 24. Apertus, in more detail*

| Dimension | Today | At the promised v1.5 (undated) |
|---|---|---|
| Tool calling (the core capability an agent needs) | Not supported in the standard way; only manual workarounds exist | Promised, no release date announced |
| Instruction following | Measurably behind a same-size US budget model in 8 months of live production data (Liip/ZüriCityGPT) | Expected to improve; unverified |
| Romansh | The best-scoring published model in independent evaluations | Same strength should carry forward |
| Swiss German | Comprehension is reasonable; generated text was judged "practically unusable" in independent testing | Unknown |
| Where it can run | SageMaker (including Zurich), Swisscom, Infomaniak, PublicAI | Unchanged |
| Real-world adoption so far | Canton Ticino (translation), CHUV (clinical trials); zero agentic deployments found anywhere | Worth keeping an eye on once tool calling ships |

**Role in this project today:** the Romansh/Swiss-German layer alongside the main assistant, where it already performs well. Worth keeping an eye on it, if and when v1.5's tool calling matures.

### 5.7 Production-readiness verdict, condensed

*Table 25. Production-readiness verdict, condensed*

| Candidate | Verdict | The evidence in one line |
|---|---|---|
| **Claude** Sonnet 4.6/5 + Haiku 4.5 (Bedrock) | **Ready** (production agent core) | GOV.UK Chat live at national scale on this exact stack [5][6] |
| **Mistral Large 3** + Ministral | **Caveat, clearly behind Claude** | Large public-sector footprint, but assistant/RAG-style, not tool-heavy agentic [80] |
| Amazon Nova 2 Lite | **Caveat** (executor tier only) | Real deployments exist, but evidence is largely vendor-reported; not reachable from Zurich |
| gpt-oss-120b | **Caveat** | Known formatting failure after long chains of tool calls, exactly this project's search-then-identify pattern |
| Qwen3.x (self-hosted) | **Caveat** | Very large adoption elsewhere; documented serving-software friction we'd own |
| **Apertus 70B** | **Caveat** as core; **Ready** as sidecar | No tool calling until v1.5; strong as a Romansh/dialect layer today |
| GLM-5.x / DeepSeek | **Not viable** (eval reference only) | Genuinely frontier-capable, but blocked by procurement and reputational concerns for a federal deployment |
| Llama 4 | **Not viable** | Frozen product line; licence actively hostile to EU-domiciled use |
| OLMo 3 | **Not viable** yet | Zero production deployments found anywhere; a transparency reference, not a deployment candidate |

---

## 6. Platform and residency options

"Sovereignty" is here as a scale with five steps. The same software runs on every step, and moving between them is a deployment change.

### 6.1 The sovereignty scale

*Table 26. The sovereignty scale*

| Step | What it is | Jurisdiction | Who controls it | When it's the right step |
|---|---|---|---|---|
| 1. Bedrock `eu.` profiles | Requests guaranteed to process inside EU data centres | [EU] (AWS/Anthropic-controlled) | Vendor | **Today's default** (sufficient for the stated "möglichst EU/national" preference) |
| 2. Open-weight models on Bedrock (EU regions) | Same serverless model, swapped to an open-weight one | [EU/US/CN depending on model] | Vendor hosts, licence governs use | Cost-sensitive tiering, or evaluation of alternatives |
| 3. SageMaker in Zurich | Self-hosted, in-country, any open model including Apertus | [CH] | swisstopo/askEarth operates the instance; AWS controls the region | A firm mandate for in-country processing |
| 4. Swiss providers (Swisscom, Infomaniak, PublicAI) | Vendor-hosted, physically in Switzerland | [CH] | Swiss vendor | A vendor-independent Swiss fallback |
| 5. On-premises | Fully in-house hardware | [CH], complete control | swisstopo/askEarth, entirely | Only if physical, air-gapped control is mandated by policy; priced honestly in §4 |

### 6.2 Jurisdiction, properly explained: who owns what, where, and what that actually means

The [CH]/[EU]/[US]/[CN] tag used throughout this report is a simplification, and it's worth unpacking once, properly, rather than leaving it as a one-letter label. "Jurisdiction" actually bundles three separate questions that can each point to a different country:

1. **Who legally owns and operates the vendor**: its country of incorporation, which determines whose courts and laws can compel it to act.
2. **Where the data is technically processed**: which physical region's servers handle a given request, relevant mainly to local seizure or access rules.
3. **Where the model was trained**: relevant to provenance and to standards like eCH-0272, but not to who can compel access to a live conversation.

The tag tracks the first of these, since it matters most for compelled-disclosure risk. Clearest example: the US CLOUD Act (2018) lets US law enforcement compel a US-incorporated company to hand over data it controls, wherever it physically sits [63]. Bedrock's EU-resident routing keeps processing inside EU data centres, satisfying the SGS report's residency preference, but Anthropic remains a US public benefit corporation, so the vendor-level dependency the SGS report's Microsoft quote warns about is real regardless of region. This is why §6.1's sovereignty scale treats weight-portability, not the region flag, as the durable guarantee.

*Table 27. Vendor jurisdiction*

| Vendor / model family | Legal entity | Headquarters | Whose law can compel disclosure | What this means here |
|---|---|---|---|---|
| **Anthropic (Claude)** | Anthropic PBC, a Delaware public benefit corporation [59] | San Francisco, USA | US law, incl. the CLOUD Act | The recommended stack. EU-resident routing controls *where processing happens*, not Anthropic's status as a US company |
| Amazon (Bedrock platform; Nova models) | Amazon.com, Inc., Delaware | Seattle, USA | US law | Bedrock is US-owned infrastructure wherever its servers physically sit; the same reasoning applies to the hosting platform itself, not just the models on it |
| OpenAI (GPT family) | OpenAI Group PBC, a Delaware public benefit corporation, controlled by the non-profit OpenAI Foundation since the October 2025 restructuring [60] | San Francisco, USA | US law | Same category as Anthropic; currently without Bedrock-EU availability (§5.3, Table 19) |
| Google (Gemini) | Google LLC, a subsidiary of Alphabet Inc., Delaware | Mountain View, USA | US law | Not reachable via Bedrock at all (§5.3, Table 19); the jurisdiction question is moot here for this project |
| xAI (Grok) | X.AI Corp., incorporated in Nevada, March 2023 [61] | San Francisco, USA | US law | US-regions-only on Bedrock; not viable here on evidence grounds regardless (§5.3, Table 19) |
| Cohere (Command A+) | Cohere Inc., incorporated in Canada | Toronto, Canada | Canadian law (a genuinely different jurisdiction from the US majority above) | Not on Bedrock in any form; a reference point only |
| **Mistral AI (Large 3, Ministral)** | Mistral AI SAS [62] | Paris, France | French and EU law | The one frontier-adjacent vendor in this comparison actually incorporated inside the EU |
| Meta (Llama 4) | Meta Platforms, Inc., Delaware | Menlo Park, USA | US law | Also carries its own licence-level exclusion of EU-domiciled users for the multimodal models, a contractual restriction on top of, not instead of, the jurisdiction question |
| Allen Institute for AI (OLMo) | Non-profit research institute | Seattle, USA | US law, but there's no commercial API to compel access through; the weights are simply published | Lowers the practical relevance of jurisdiction for this specific model |
| Zhipu AI (GLM) | Zhipu AI, incorporated in China | Beijing, China | Chinese law, including national intelligence and cybersecurity legislation that can compel a China-incorporated company to cooperate with state requests | Applies to Zhipu's own hosted API. Does not apply in the same way to a copy of the published weights running with no connection back to Zhipu (§5.5's Chinese-model table) |
| DeepSeek | DeepSeek, incorporated in China | Hangzhou, China | Chinese law | Same reasoning as Zhipu |
| Alibaba (Qwen) | Alibaba Group | Hangzhou, China | Chinese law | Same reasoning as Zhipu |
| Moonshot AI (Kimi) | Moonshot AI, incorporated in China | Beijing, China | Chinese law | Same reasoning as Zhipu |
| IBM (Granite) | International Business Machines Corporation | Armonk, USA | US law | Offered mainly through IBM's own watsonx platform, not Bedrock |
| **Swiss AI Initiative (Apertus)** | A public academic consortium (ETH Zürich, EPFL, and the Swiss National Supercomputing Centre), not a commercial company at all | Zürich / Lausanne / Lugano, Switzerland | Swiss law; as public institutions, not exposed to a foreign compelled-disclosure regime the way a commercial vendor is | The only entry in this report where the owner is Swiss public institutions rather than any company, the clearest sovereignty story available, alongside the capability gaps documented in §5.6 (Table 24) |
| EuroLLM | An EU-funded, multi-institution research consortium | Institutions across several EU member states | EU law, distributed across the member states involved | A public research project, like Apertus, not a commercial vendor |

This also answers the SGS report's sharpest concern: a US hyperscaler's regional promises don't remove the underlying jurisdiction, and that applies to AWS as much as Microsoft. For public, non-personal geodata, the honest framing is that the residual risk is vendor dependency, not data confidentiality. The scale's guarantee against that dependency is weights that can be taken anywhere under Apache/MIT licensing, not the region flag on a server.

### 6.3 Bedrock vs. other clouds and direct vendor APIs

If a frontier model that AWS can't serve from an EU region ever becomes the deciding factor, here's the menu. All figures are naive (no prompt caching, no routing) on a single, shared complex-query definition (2–3× the base token count) for cross-vendor comparability, not the full naive/complex spectrum from §4:

*Table 28. Bedrock vs. other clouds and direct vendor APIs*

| Provider | Model & platform | Deployed on | Jurisdiction | CHF/turn (naive, complex query) | CHF/month (Central, 715 turns/day, naive) | Residency reality |
|---|---|---|---|---|---|---|
| Google | Gemini 3.5 Flash, Vertex AI (EU multi-region) [76] | Google Cloud | [EU boundary / US vendor] | 0.0104–0.0156 | ~CHF 227–340 | EU boundary, no Swiss region |
| Mistral AI | Mistral Large 3, La Plateforme [74] | Mistral's own infrastructure | [EU] | 0.0112–0.0168 | ~CHF 243–364 | EU datacentres, EU vendor |
| OpenAI | GPT-5.6 "Terra" tier, direct API + EU residency [77] | OpenAI's own infrastructure | [EEA incl. CH / US vendor] | 0.0174–0.0261 | ~CHF 378–567 | Zero data retention |
| Anthropic | Claude Sonnet 4.6, Amazon Bedrock `eu.` (status quo) [9] | AWS (Amazon Bedrock) | [EU / US vendor] | 0.0182–0.0273 | ~CHF 396–594 | EU regions, existing AWS setup (**recommended**) |
| OpenAI (via Microsoft) | GPT-5.5, Azure OpenAI, Switzerland North, Global Standard [78] | Microsoft Azure | [CH data-at-rest / US vendor, global inference] | 0.0316–0.0474 | ~CHF 687–1,030 | Data stored in Switzerland, but processed anywhere in Microsoft's global fleet, a materially weaker guarantee than it sounds |

Note: all prices in USD, converted at the same ≈0.81 CHF/USD rate throughout [73]. This table's query basis is shorter than §4's own (see §4.3 for this project's real naive/lean and naive/complex figures); the point here is relative ordering between vendors, not absolute cost.

### 6.4 What's actually available from Switzerland

as of 14.07.2026

*Table 29. What's actually available from Switzerland*

| Resource | Available in Zurich (`eu-central-2`)? | Where it actually runs otherwise |
|---|---|---|
| Claude 3 Haiku, Titan Text Embeddings V2 | Yes, true in-region | Zurich |
| Current Claude generation (Haiku 4.5, Sonnet 4.5/4.6, Opus 4.5–4.8, Fable 5) | Via `eu.` cross-region routing | EU destination regions, including Zurich for several of them |
| Claude Sonnet 5 | No `eu.` profile yet | Global routing |
| High-end GPU instances (H100/L40S-class) | Not available | Nearest: Frankfurt |
| Entry-level GPU instances (L4, 24GB) | Available | Zurich |
| Bedrock Custom Model Import (scale-to-zero self-hosting) | Not available | Frankfurt and a handful of US regions |
| Open-weight serverless models (DeepSeek, Qwen, Kimi, gpt-oss, GLM Flash, Ministral) | None invocable from Zurich | Ireland, Milan, London, Frankfurt, Stockholm |
| Mistral Large 3 (serverless) | Not in any EU region | US/APAC only |

No committed date exists for Zurich reaching this parity [79].

---

## 7. Recommendation and plan

### 7.1 Rollout levels

*Table 30. Rollout levels*

| Level | Action | Gate to move forward | Expected effect |
|---|---|---|---|
| **1: Deploy** | Claude Sonnet 4.6 via Bedrock `eu.`, built on Bedrock AgentCore (the current agent framework) | None | Live pilot |
| **2: Optimize** | Potential caching, routing | The WP5 evaluation shows quality, cost | Cost reduction |
| **3: Watch** | No active testing of alternatives; Mistral Large 3, Apertus and other models stay monitored | If a concrete trigger arises | - |

---

## 8. Risks

### 8.1 Risk register

*Table 31. Risk register*

| Risk | Likelihood / impact | Mitigation |
|---|---|---|
| Real adoption exceeds the grounded scenarios in §4.2 (Table 9) | Low / Low | Cost scales linearly and stays small even at High (~1,350 turns/day, already scaled to swisstopo's own traffic) |
| A vendor changes a model or its price | High / Low | Model identifier kept as a simple configuration value; observe |
| No EU-resident routing yet for the newest models (e.g. Sonnet 5) | Medium / Low | Sonnet 4.6 is the EU-resident default; this pattern (a delay, then an `eu.` profile follows) has repeated with every recent Claude release |
| Dependency on a single vendor (AWS/Anthropic) | Medium / Medium | Develop exit option |

---

## 9. References

**[1]** swisstopo–askEarth IT-Dienstleistungsvertrag, Bestellnr. 9950006773, signed 05.05.2026 (incl. askEarth offer of 23.03.2026, WP definitions WP1–WP6)

**[2]** swisstopo, SGS-5-25-2 Report V1.0, 'KI im Bereich Geodaten: LLMs für die semantische Suche und Abfragen entwickeln', 24.11.2025

**[3]** swisstopo sgs-llm repository, docs/model-cost-options/cost-model.md: https://github.com/swisstopo/sgs-llm/blob/main/docs/model-cost-options/cost-model.md

**[4]** swisstopo press release, '1000 Layer auf map.geo.admin.ch', 18.05.2026 (33M visits 2025; >3,800 TB data traffic): https://www.swisstopo.admin.ch/de/1000-layer-map-geo-admin-ch

**[5]** UK Government Digital Service, 'GOV.UK Chat launches', 14.05.2026: https://gds.blog.gov.uk/2026/05/14/gov-uk-chat-launches/

**[6]** Inside GOV.UK, '5 things we learned testing GOV.UK Chat', 16.03.2026: https://insidegovuk.blog.gov.uk/2026/03/16/5-things-we-learned-testing-gov-uk-chat-an-ai-assistant-for-government/

**[7]** Liip, 'ZüriCityGPT — 10 months later' / 'Apertus after 8 months', 07.2026: https://www.liip.ch/en/blog/apertus-after-8-months-what-we-learned-and-look-forward-using-switzerlands-ai-model

**[8]** WebFX, analysis of 13,252 real ChatGPT conversations: https://www.webfx.com/blog/ai/chatgpt-usage-statistics/

**[9]** Anthropic model pricing and prompt caching documentation, pulled 14.07.2026: https://platform.claude.com/docs/en/about-claude/pricing

**[10]** Amazon Bedrock pricing page, pulled 14.07.2026: https://aws.amazon.com/bedrock/pricing/

**[11]** AWS Alps blog, 'Unlocking AI flexibility in Switzerland': https://aws.amazon.com/blogs/alps/unlocking-ai-flexibility-in-switzerland-a-guide-to-cross-region-inference-for-eu-data-processing-and-model-access/

**[12]** AWS Bedrock model cards, pulled 14.07.2026: https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html

**[13]** Ong et al., RouteLLM (ICLR 2025): https://lmsys.org/blog/2024-07-01-routellm/

**[14]** Chen, Zaharia, Zou, FrugalGPT (2023): https://arxiv.org/abs/2305.05176

**[15]** GPT Semantic Cache (arXiv 2411.05276): https://arxiv.org/abs/2411.05276

**[16]** Gartner press release, 25.03.2026: https://www.gartner.com/en/newsroom/press-releases/2026-03-25-gartner-predicts-that-by-2030-performing-inference-on-an-llm-with-1-trillion-parameters-will-cost-genai-providers-over-90-percent-less-than-in-2025

**[17]** Goldman Sachs, 05.2026: https://www.goldmansachs.com/insights/articles/ai-agents-forecast-to-boost-tech-cash-flow-as-usage-soars

**[18]** Epoch AI, 'LLM inference price trends': https://epoch.ai/data-insights/llm-inference-price-trends

**[19]** OpenAI o3 price reduction, ARC Prize re-test: https://www.bleepingcomputer.com/news/artificial-intelligence/chatgpt-o3-api-80-percent-price-drop-has-no-impact-on-performance/

**[20]** Krechetova & Kochedykov, GeoBenchX (arXiv 2503.18129): https://arxiv.org/abs/2503.18129

**[21]** MCPMark (arXiv 2509.24002): https://arxiv.org/abs/2509.24002

**[22]** τ²-bench results, Artificial Analysis, 07.2026; Amazon tau2-bench-verified fork: https://artificialanalysis.ai/evaluations/tau2-bench

**[23]** 'When Agents Fail to Act' (arXiv 2601.16280): https://arxiv.org/abs/2601.16280

**[24]** SciAgentGym (arXiv 2602.12984): https://arxiv.org/abs/2602.12984

**[25]** RULER (COLM 2024) and NoLiMa (ICML 2025): https://arxiv.org/abs/2404.06654

**[26]** Swiss AI Initiative, Apertus technical report (arXiv 2509.14233): https://arxiv.org/abs/2509.14233

**[27]** effektiv.ch, 'Apertus is here', 05.09.2025: https://www.effektiv.ch/en/blog/apertus-release

**[28]** litellm issue #21124 (Apertus tool-calling gap): https://github.com/BerriAI/litellm/issues/21124

**[29]** NIST CAISI, 'Evaluation of DeepSeek AI Models', 30.09.2025; follow-up on DeepSeek V4 Pro, 05.2026: https://www.nist.gov/news-events/news/2025/09/caisi-evaluation-deepseek-ai-models-finds-shortcomings-and-risks

**[30]** Czech NÚKIB warning on DeepSeek products, 10.07.2025: https://nukib.gov.cz/en/infoservis-en/news/2280-nukib-issues-a-warning-regarding-certain-products-of-the-company-deepseek/

**[31]** CrowdStrike research, 11.2025: https://www.crowdstrike.com/en-us/blog/crowdstrike-researchers-identify-hidden-vulnerabilities-ai-coded-software/

**[32]** Mistral AI, Mistral 3 announcement and pricing: https://mistral.ai/news/mistral-3/

**[33]** Artificial Analysis model index, 07.2026: https://artificialanalysis.ai/

**[34]** Microsoft Learn, Azure AI Foundry deployment types and region availability: https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/deployment-types

**[35]** OpenAI API data residency, pulled 14.07.2026: https://help.openai.com/en/articles/10503543-data-residency-for-the-openai-api

**[36]** Google Cloud Vertex AI locations & data residency: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/locations

**[37]** Anthropic API data residency, pulled 14.07.2026: https://platform.claude.com/docs/en/manage-claude/data-residency

**[38]** GPU market data 2026 (residual values, rental rates): https://www.amcompute.com/blog/gpu-depreciation-residual-value-report-2026

**[39]** Google SRE Book, 'Being On-Call': https://sre.google/sre-book/being-on-call/

**[40]** SwissDevJobs / Robert Half Switzerland, ML/MLOps salary data 2026: https://swissdevjobs.ch/salaries/Machine-Learning/all/all

**[41]** AWS EC2/SageMaker GPU pricing and Bedrock Custom Model Import pricing, pulled 04–14.07.2026: https://aws.amazon.com/sagemaker/ai/pricing/

**[42]** askEarth–BAFU API specification meeting notes, 09.07.2025

**[43]** eCH-0272 standard, v1.0: https://www.ech.ch/de/ech/ech-0272/1.0.0

**[44]** EU GPAI Code of Practice signatories: https://digital-strategy.ec.europa.eu/en/policies/contents-code-gpai

**[45]** MCP in production maturity (InfoQ 07.2026; MCP roadmap 2026): https://www.infoq.com/news/2026/07/mcp-ema-enterprise-auth/

**[46]** Allen AI, OLMo 3 / 3.1: https://allenai.org/blog/olmo3

**[47]** Google Gemma 4 (Apache 2.0): https://huggingface.co/google/gemma-4-31B-it

**[48]** AWS, Bedrock Agents (Classic) maintenance / Bedrock AgentCore: https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-agentcore-and-claude-transforming-business-with-agentic-ai/

**[49]** DINUM, Albert / Assistant IA (French state self-hosted open-model fleet): https://www.numerique.gouv.fr/offre-accompagnement/expertise-albert-ia-etat/

**[50]** Infomaniak, AI Services pricing (Apertus-70B): https://www.infomaniak.com/en/hosting/ai-services/prices

**[51]** gpt-oss harmony-format failures: https://forum.langchain.com/t/harmony-response-format-sometimes-outputted-when-using-gpt-oss-120b-as-an-agent/2554

**[52]** DeepSeek/Qwen tool-parser instability: https://github.com/sgl-project/sglang/issues/14695 · https://github.com/vllm-project/vllm/issues/36654

**[53]** OpenRouter, China-origin open-weight token share, 07.2026: https://openrouter.ai/blog/insights/the-open-weight-models-that-matter-june-2026/

**[54]** EuroLLM-22B: https://huggingface.co/blog/eurollm-team/eurollm-22b

**[55]** Cohere–Aleph Alpha merger; Command A+: https://www.cnbc.com/2026/04/24/cohere-aleph-alpha-germany-ai-europe-expansion.html

**[56]** Artificial Analysis, Nova 2 Lite model card: https://artificialanalysis.ai/models/nova-2-0-lite

**[57]** Anthropic, Claude Fable 5 announcement (provider-data-sharing and temperature caveats): https://www.anthropic.com/news/claude-fable-5-mythos-5

**[58]** Live-chat engagement benchmarks: unprompted open rate 2–8%, vs. up to 15% including proactively-triggered pop-ups, per Which-50, 'Live Chat Engagement Rate Benchmarks', and Cometly, 'What Is Chatbot Engagement Rate?', pulled 14.07.2026: https://which-50.com/live-chat-engagement-rate-benchmarks/ · https://www.cometly.com/post/what-is-chatbot-engagement-rate

**[59]** Anthropic PBC, Delaware public benefit corporation, per Harvard Law School Forum on Corporate Governance, 'Anthropic Long-Term Benefit Trust', 28.10.2023; Bloomberg LEI record: https://corpgov.law.harvard.edu/2023/10/28/anthropic-long-term-benefit-trust/ · https://lei.bloomberg.com/leis/view/984500B6DEB8CEBC4Z70

**[60]** OpenAI restructuring, 28.10.2025: OpenAI Foundation (non-profit) controlling OpenAI Group PBC (for-profit): https://openai.com/index/evolving-our-structure/

**[61]** xAI Corp., incorporated in Nevada, 09.03.2023: https://www.crunchbase.com/organization/xai

**[62]** Mistral AI SAS, Paris, France, company profile: https://www.bloomberg.com/profile/company/2278919D:FP

**[63]** US CLOUD Act (2018) mechanism: compels a US-controlled provider to produce data in its possession or control regardless of where it's physically stored, per Congressional Research Service, 'Cross-Border Data Sharing Under the CLOUD Act'; AWS CLOUD Act compliance page: https://www.congress.gov/crs-product/R45173 · https://aws.amazon.com/compliance/cloud-act/

**[64]** Kimi K2 LICENSE file (Modified MIT: standard MIT below 100M MAU / $20M monthly revenue, "Kimi K2" attribution required above that threshold), verified on GitHub: https://github.com/moonshotai/Kimi-K2/blob/main/LICENSE

**[65]** Llama 4 Community License Agreement, rights not granted to EU-domiciled individuals/companies for the multimodal models: https://www.llama.com/llama4/use-policy/ · https://ioplus.nl/en/posts/european-union-excluded-from-llama-4-multimodal-models

**[66]** GLM-5.2 licence (MIT); DeepSeek V3 licence (MIT); Qwen3 licence (Apache 2.0), per ComputingForGeeks, 'Open Source LLM Comparison Table (2026)': https://computingforgeeks.com/open-source-llm-comparison/

**[67]** IBM Granite 4.0 (Apache 2.0): https://www.ibm.com/new/announcements/ibm-granite-4-0-hyper-efficient-high-performance-hybrid-models

**[68]** OpenAI gpt-oss (Apache 2.0): https://openai.com/index/introducing-gpt-oss/

**[69]** Tilde.ai, 'The first AI-chatbot of public administration in Latvia', RNP (Rīgas Namu Pārvaldnieks, City of Riga housing authority), ~47,000 conversations in 5 months: https://tilde.ai/case-study/the-first-ai-chatbot-of-public-administration-in-latvia/

**[70]** Anthropic, 'Model deprecations', pulled 14.07.2026: https://platform.claude.com/docs/en/about-claude/model-deprecations

**[71]** Anthropic, 'Commitments on model deprecation and preservation', 04.11.2025: https://www.anthropic.com/research/deprecation-commitments

**[72]** Janakiram MSV, 'Cheaper AI Tokens Do Not Guarantee Cheaper Enterprise Agents', Forbes, 14.07.2026: https://www.forbes.com/sites/janakirammsv/2026/07/13/cheaper-ai-tokens-do-not-guarantee-cheaper-enterprise-agents/

**[73]** USD/CHF spot exchange rate, ≈0.81, pulled 14.07.2026, Federal Reserve H.10 release: https://www.federalreserve.gov/releases/h10/hist/dat00_sz.htm

**[74]** Mistral AI, official API pricing page, Mistral Large ($2/M input, $6/M output tokens; includes 90% cached-input discount), pulled 14.07.2026: https://mistral.ai/pricing/api

**[75]** Gemma 4 third-party API pricing across providers (blended range ~$0.06–0.99/M input tokens depending on variant and host), pulled 14.07.2026: https://pricepertoken.com/pricing-page/model/google-gemma-4-31b-it · https://openrouter.ai/google/gemma-4-31b-it · https://deepinfra.com/blog/gemma-4-pricing-benchmarks-cost-scenarios

**[76]** Google, Gemini API pricing (Gemini 3.5 Flash: $1.50/M input, $9.00/M output tokens global; $1.65/$9.90 non-global regions incl. Vertex EU multi-region), pulled 14.07.2026: https://ai.google.dev/gemini-api/docs/pricing

**[77]** OpenAI, API pricing (GPT-5.6 three-tier family: Luna $1/$6, Terra $2.50/$15, Sol $5/$30 per M tokens; this table uses Terra, the mid-tier, with OpenAI's stated surcharge for EU-residency-eligible models), pulled 14.07.2026: https://developers.openai.com/api/docs/pricing

**[78]** Microsoft, Azure OpenAI Service pricing (GPT-5.5, Global Standard deployment: $5/M input, $30/M output tokens; Switzerland North stores data at rest but does not guarantee in-region inference), pulled 14.07.2026: https://azure.microsoft.com/en-us/pricing/details/azure-openai/

**[79]** AWS, '3-Year Anniversary – News About AWS Europe (Zurich) Region', 09.01.2026, incl. public regional roadmap: only Amazon Bedrock AgentCore is dated for Zurich (2026 Q4); no GPU-class instances or open-weight serverless models are on the published roadmap, and AWS labels all dates directional, not committed, pulled 14.07.2026: https://aws.amazon.com/blogs/alps/3-year-anniversary-news-about-aws-europe-zurich-region/

**[80]** Startup Fortune / TNW, France's €655m sovereign-AI announcement (Jan 2026): a chatbot for ~1 million civil servants, widely reported as Mistral-powered though officials did not name a vendor explicitly; French armed-forces framework per Mistral's own public-sector materials, pulled 14.07.2026: https://startupfortune.com/france-drops-palantir-for-a-local-rival-and-hands-every-civil-servant-a-mistral-ai-assistant/ · https://thenextweb.com/news/france-to-spend-e655m-on-ai
