# Coached agents duel

Two AI agents negotiate a split of tea, silk and saffron under fixed rules. Each agent has a personality, private values and a memory of at most five lessons. A coach's note becomes a lesson; the agent decides what to keep. Rules, not the model, decide every score.

Replay page: https://theaipipe.com/demos/coached-duel/

## What works today

- **The duel, end to end.** Structured actions (offer, accept, reject) validated by schema and then by the engine; 8 alternating actions; scores computed by code. 48 real duels were played by a model and recorded in `corpus/duels.jsonl`, with every action, message, memory version and token count.
- **The coaching loop.** Coach note, lesson written by the agent, memory update (add, replace a slot, or discard), versioned memory, next match loaded with that exact version. Two rounds were run; in the second, every learning agent's memory was full and each one chose a slot to replace (`corpus/memory_events.jsonl`).
- **The branches the analysis needs.** Four agents: two coached, one self-reflective (same inputs minus the coach's note, same limits), one that never learns.
- **Replays from identical states** to measure luck alone: 3 configurations x 4 replays, flagged `eval=true`, which forbids any memory write.
- **A power simulation** that applies exactly the planned analysis (`sim/power.py`), fed with the noise measured on those replays.
- **Cost accounting** from the raw usage the CLI returns, per call, per duel, per lesson update.

## Limits, said plainly

- The demo season is small: 4 agents, 36 season duels, 12 replays, 2 rounds of coaching. It shows the machine. It concludes nothing about coaching.
- The coach's notes were written by The AI Pipe for the demo. There is one human source, not independent coaches.
- The replay noise comes from 3 configurations only, so the simulation also shows half and 1.5 times that noise.
- All 36 season duels reached an agreement, with no invalid action. Impasses are simulated at that observed rate (zero); harder scenarios would change it.
- One lesson in the corpus misreads a rule (Hollis, round 2: it assumes a refused counter leaves the other offer open). The engine still enforced the rule. It is left as recorded.
- Building this demo took a few hours. The real experiment is a separate two-week run with real coaches.

## Check every score without any model account

```
python3 scripts/rescore.py      # replays the 48 logged duels through the engine, recomputes every score
python3 -m pytest -q tests      # 22 model-free tests, including log/page score concordance
```

Expected: `48 duels replayed, 48 agreements, 0 mismatches`, then `22 passed`.

## The duel, specified

- **Goods.** Public integer stocks: 4 tea, 3 silk, 2 saffron. Each side has private integer values per good; the whole pool is worth 30 to each side. Value configurations come from a seeded generator (`make_scenarios`, seed 20261010). Each pairing is played twice on the same configuration with positions and value profiles swapped.
- **Turns.** 8 actions in total, alternating. The first mover acts on 1, 3, 5, 7.
- **Offer.** A complete allocation in whole units; stocks are conserved. A new offer replaces the open offer (a counter-offer).
- **Accept.** Names the id of the opponent's current open offer. Accepting your own offer, a superseded offer, an unknown id, or nothing is invalid.
- **Reject.** Closes the opponent's open offer; nothing is on the table until the next offer. Rejecting when no opponent offer is open is invalid.
- **Talk.** The message attached to an action binds nothing.
- **End.** An acceptance is terminal; any later action raises `MatchOver`. Without agreement after 8 actions, each side gets its impasse value, fixed before the match (6 of 30).
- **Score.** Value received divided by the value of the whole pool to that side. Both scores and the agreement rate are reported.
- **Errors.** An invalid or unparseable action costs the turn and is counted. A network failure, timeout or exhausted quota is an execution incident: never scored, retried at most twice, every attempt logged and its usage counted. An exhausted quota stops the run cleanly; finished duels are already saved and the run resumes where it stopped.
- **Same objective for all.** Every agent maximises its own score. No personality is asked to care about the other side.

### What each model call sees

A play call receives only: personality, at most 5 lessons of at most 50 words, its own values, the rules, the public state and the transcript of the match in progress. No earlier transcript, raw feedback or summary. A lesson call receives the agent's batch of duels with end-of-match information (the other side's values revealed), plus the coach's note for the coached branch only. Tests check on the serialized prompt that the opponent's values never appear.

## Analysis plan

Two questions, kept apart:

1. **Are the performances of frozen versions reproducible?** Freeze each agent's memory, replay the same evaluation schedule twice, compare the rankings.
2. **Does human feedback add more than self-reflection, at equal conditions?** That is the coaching question.

Protocol for the two-week run:

- **Paired branches.** For each coached personality, three branches start from the same saved state: human-coached, self-reflective, and a copy that never learns. The coached and self-reflective branches get the same model, personality, number of matches, number of updates, memory limit, eviction rule and end-of-match information. Proposed cadence: one update per coach per day, after a batch of matches.
- **Reference phase.** A balanced schedule of matches before any feedback (not a fixed "week").
- **Frozen evaluations** at the start, day 7 and day 14: memories frozen, the same panel of frozen opponents, scenarios reserved for measurement, both roles. These matches write nothing (`eval=true`).
- **Primary analysis.** For each coach, the coached branch's mean evaluation score minus the self-reflective branch's, on the same evaluation matches (the shared starting state cancels). Report every coach's difference, their mean and a 95% interval; two-sided t-test across coaches. A mixed model (small-sample correction, the two scores of one match treated as dependent) is secondary.
- **Counting.** Witness branches are not coaches. The question about coaches themselves is framed as differences between coach-agent pairs.
- **Outcomes.** If the test is not significant, report the range of benefits still compatible with the data. "Undetermined at this size" is a planned outcome.
- **Ranking.** No Elo. Rank frozen versions by mean score under balanced conditions, with intervals.
- **Rule-based profiles** to see whether agents stay distinct: anchoring of the first offer, concession per offer, actions to agreement, impasse rate.

Profiles measured on the 36 demo season duels (share of the pool's value):

| Agent | Learning | First offer claims | Concession per offer | Actions to agreement | Impasses | Mean score |
|---|---|---|---|---|---|---|
| Hollis | coached | 0.84 | 0.10 | 4.9 | 0 | 0.68 |
| Marlow | coached | 0.78 | 0.10 | 4.5 | 0 | 0.65 |
| Juno | self-reflective | 0.74 | 0.07 | 4.6 | 0 | 0.60 |
| Tamsin | never learns | 0.78 | 0.06 | 5.1 | 0 | 0.65 |

## What a two-week pilot could detect

`python3 sim/power.py 3000` (about 20 seconds). The simulation estimates what a two-week pilot could detect under explicit assumptions. It applies exactly the primary analysis above and never uses a true value. Score points are percent of the pool's value.

Measured inputs (from `corpus/pilot_params.json`): replay noise 6.8 points (12 replays from 3 identical states; it measures variability within one situation, not between coaches), first-mover edge 7.2 points, spread between scenarios 7.1 points, spread between agents 2.8 points, impasses 0 of 36. Hypotheses: average benefit of coaching 0, +5 or +10 points; variation of that benefit between coach-personality pairs none, 5 or 10 points; self-reflection gain +3 points (cancels in the comparison). Schedule: 4 training matches per learning branch per day for 14 days, evaluations at the start, day 7 and day 14.

With the measured noise and 16 evaluation matches per frozen version:

| Coaches | Variation between coaches | +10 detected | +5 detected | False alarms at 0 | 95% interval, +/- points | Matches in two weeks |
|---|---|---|---|---|---|---|
| 8 | none | 100% | 100% | 5.6% | 1.9 | 1,792 |
| 8 | +/-5 points | 99% | 59% | 5.2% | 4.5 | 1,792 |
| 8 | +/-10 points | 67% | 22% | 5.3% | 8.2 | 1,792 |
| 10 | none | 100% | 100% | 4.7% | 1.7 | 2,240 |
| 10 | +/-5 points | 100% | 72% | 4.9% | 3.8 | 2,240 |
| 10 | +/-10 points | 79% | 29% | 4.3% | 7.1 | 2,240 |
| 16 | none | 100% | 100% | 4.8% | 1.3 | 3,584 |
| 16 | +/-5 points | 100% | 91% | 4.6% | 2.9 | 3,584 |
| 16 | +/-10 points | 95% | 44% | 4.6% | 5.4 | 3,584 |

Reading it: more matches make each agent's score more precise; more coaches show whether the benefit generalises. When the benefit varies a lot between coaches, going from 4 to 64 evaluation matches barely moves detection (10 coaches, +5 points, variation 10: 25% to 30%), while going from 8 to 16 coaches does. Ranking stability of frozen versions (rank correlation between two independent runs of the same evaluation, median): 0.39 at 4 matches, 0.71 at 16, 0.90 at 64. Every cell, including half and 1.5 times the noise, is in `sim/results.json`; `tests/test_sim.py` checks that false alarms at zero benefit stay near 5%.

## Cost of running the duel

Three separate lines:

1. **Additional API spend for this demo: 0 USD.** Every call ran on a Claude subscription through the Claude Code CLI.
2. **Observed usage** (raw usage returned by the CLI, all 238 calls, no failed attempt): per duel on average 4.8 calls, 1,808 output tokens, 5,716 input tokens written to cache, 6,324 read from cache and about 10 uncached, about 19 seconds. The 6 lesson updates used 1,424 output tokens in all. Total: 274,378 cache-write, 303,560 cache-read, 464 uncached input and 86,770 output tokens for the duels.
3. **Equivalent API cost, estimated** at the public list price of the only model run, `claude-sonnet-5-5`, read on 2026-10-10 at https://platform.claude.com/docs/en/about-claude/pricing (input 2 USD, 1-hour cache write 4 USD, cache read 0.10 USD, output 10 USD per million tokens): **0.042 USD per duel, 0.044 USD counting lesson updates** ("duel only" vs "duel + learning"). The CLI's own cost field gives the same total (1.996 USD for the 48 duels). A pilot of 10 coaches with 16 evaluation matches per version, about 2,240 matches and 280 lesson updates, would come to about 98 USD at that rate. Effort was set to low; another model or effort level changes these numbers.

A character count of the prompts and outputs (about 890,000 characters for 665,000 reported tokens) is kept only as a rough control: the CLI adds its own schema and framing.

## Model calls, isolated

Recorded on the machine that ran the season: `claude --version` = `2.1.296 (Claude Code)`. `claude --help` lists both `--json-schema <schema>` ("JSON Schema for structured output validation") and `--safe-mode` ("Start with all customizations ... disabled"). `claude auth status` reports `"authMethod": "claude.ai"` (subscription); `--bare` is not used.

Each call (`duel/llm.py`) runs from an empty temporary folder with `--system-prompt` (replaces the default), `--tools ""`, `--strict-mcp-config`, `--setting-sources ""`, `--safe-mode`, `--no-session-persistence`, `--output-format json`, `--json-schema`, `--model sonnet`, `--effort low`. Every `ANTHROPIC_*` variable is removed from the child environment; `env | grep -i anthropic` printed nothing during the run. A quota message stops the run cleanly. The schema check never replaces the engine's own validation.

There is no seed or temperature control in the CLI, and fixing the draw would erase the luck being measured. Seeds exist for the scenario generator and the simulation only.

## Group round (written, not built)

Duel first; the group format reuses the same agents and memory. Proposed rules, to be built as a paid prototype with its cost measured:

- **Who speaks next.** Round-robin, five seats; the first speaker rotates every sitting so no seat is always first. Each agent gets the same speaking budget (same number of turns, same word cap per turn). An agent may pass; a pass uses its turn.
- **Agreement.** At any turn an agent may table a complete split; it is adopted when a majority accepts it before the last round. No adopted split by the end: everyone gets the impasse value.
- **Exclusion vote.** After the split, sealed simultaneous votes, one per agent, no self-votes. Invalid ballot: counted as abstention. The agent with the most votes is excluded from the payout and its share is redistributed in proportion to the others' shares; a tie excludes nobody.
- **Scoring** stays rule-based: each agent's payout over the value of the whole pool to it.

## Repository map

- `duel/engine.py` rules, validation, scoring
- `duel/agents.py` personalities, memory limits, prompts, schemas
- `duel/llm.py` isolated CLI calls, incident handling, a scripted stand-in for tests
- `duel/runner.py` one duel end to end, memory updates
- `duel/cost.py` usage and equivalent cost
- `scripts/season.py` the demo season, stage by stage
- `scripts/rescore.py` model-free replay and rescoring
- `scripts/build_data.py` simulation inputs and page data from the corpus
- `sim/power.py` the simulation; `sim/results.json` its output
- `corpus/` everything recorded: duels, memory events, coach notes, agents, scenarios
- `site/` the static replay page
- `tests/` model-free tests
