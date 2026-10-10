# Coached agents duel

Two AI agents negotiate a split of tea, silk and saffron under fixed rules. Each agent has a personality, private values and a memory of at most five lessons. A coach's note becomes a lesson; the agent decides what to keep. Rules, not the model, decide every score.

Replay page: https://theaipipe.com/demos/coached-duel/

## What works today

- **The duel, end to end.** Structured actions (offer, accept, reject) validated by schema and then by the engine; 8 alternating actions; scores computed by code. 48 real duels were played by a model and recorded in `corpus/duels.jsonl`, with every action, message, memory version and token count.
- **The coaching loop.** Coach note, lesson written by the agent, memory update (add, replace a slot, or discard), versioned memory, next match loaded with that exact version. Two rounds were run; in the second, every learning agent's memory was full and each one chose a slot to replace (`corpus/memory_events.jsonl`). Each duel's record holds the exact lessons it was played with.
- **The branches the analysis needs.** Four agents: two coached, one self-reflective (same inputs minus the coach's note, same limits), one that never learns.
- **Replays from identical states** to measure luck alone: 3 configurations x 4 replays, flagged `eval=true`, which forbids any memory write.
- **A power simulation** that applies exactly the planned analysis (`sim/power.py`), fed with the noise measured on those replays.
- **Cost accounting** from the raw usage the CLI returns, per call, per duel, per lesson update.

## Limits, said plainly

- The demo season is small: 4 agents, 36 season duels, 12 replays, 2 rounds of coaching. It shows the machine. It concludes nothing about coaching.
- The coach's notes were written by The AI Pipe for the demo. There is one human source, not independent coaches.
- The replay noise comes from 3 configurations only, so the simulation also shows half and 1.5 times that noise.
- All 36 season duels reached an agreement, with no invalid action. Impasses are simulated at that observed rate (zero); harder scenarios would change it.
- A first run used two demo coach notes that misdescribed the logs; one of them also misstated a rule and the agent's lesson repeated the mistake. Both notes were rewritten to match the logs, and every lesson update and duel that depended on them was replayed: 30 duels and 4 lesson updates (159 extra model calls). The first run is kept, unused, in `corpus/superseded/`.
- Building this demo took a few hours. The real experiment is a separate two-week run with real coaches.

## Check every score without any model account

```
python3 -m pip install -r requirements.txt   # numpy, scipy, pytest
python3 scripts/rescore.py      # replays the 48 logged duels through the engine, recomputes every score
python3 -m pytest -q tests      # 27 model-free tests, including log/page score concordance
```

Expected: `48 duels replayed, 48 agreements, 0 mismatches`, then `27 passed`.

## The duel, specified

- **Goods.** Public integer stocks: 4 tea, 3 silk, 2 saffron. Each side has private integer values per good; the whole pool is worth 30 to each side. Value configurations come from a seeded generator (`make_scenarios`, seed 20261010). Each pairing is played twice on the same configuration with positions and value profiles swapped.
- **Turns.** 8 actions in total, alternating. The first mover acts on 1, 3, 5, 7.
- **Offer.** A complete allocation in whole units; stocks are conserved. A new offer replaces the open offer (a counter-offer).
- **Accept.** Names the id of the opponent's current open offer. Accepting your own offer, a superseded offer, an unknown id, or nothing is invalid.
- **Reject.** Names the id of the opponent's open offer and closes it; nothing is on the table until the next offer. A wrong id, or no opponent offer open, is invalid.
- **Talk.** The message attached to an action binds nothing.
- **End.** An acceptance is terminal; any later action raises `MatchOver`. Without agreement after 8 actions, each side gets its impasse value, fixed before the match (6 of 30).
- **Score.** Value received divided by the value of the whole pool to that side. Both scores and the agreement rate are reported.
- **Errors.** An invalid or unparseable action costs the turn and is counted. A network failure, timeout, overload or exhausted quota is an execution incident: never scored, and logged in `corpus/incidents.jsonl` with the usage of the calls the interrupted duel had already made. Transient errors (network, timeout, overload, rate limiting) are retried at most twice. An exhausted subscription quota cancels the duels still queued; each finished duel is written as soon as it ends, a duel already running is allowed to finish, and the run resumes where it stopped (tested with a stand-in CLI).
- **Same objective for all.** Every agent maximises its own score. No personality is asked to care about the other side.

#### Memory limits

At most 5 lessons, each at most 50 words and 400 characters; a lesson identical to one already kept is refused; `replace_slot` must be a real slot number (a boolean is refused). Any record flagged `eval=true` in a batch makes the memory update refuse to run, whatever the caller passes.

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
| Hollis | coached | 0.84 | 0.11 | 5.2 | 0 | 0.66 |
| Marlow | coached | 0.77 | 0.10 | 4.6 | 0 | 0.65 |
| Juno | self-reflective | 0.73 | 0.06 | 4.7 | 0 | 0.60 |
| Tamsin | never learns | 0.79 | 0.05 | 5.2 | 0 | 0.65 |

## What a two-week pilot could detect

`python3 sim/power.py 3000` (about 20 seconds). The simulation estimates what a two-week pilot could detect under explicit assumptions. It applies exactly the primary analysis above and never uses a true value. Score points are percent of the pool's value.

Measured inputs (from `corpus/pilot_params.json`): replay noise 7.3 points (12 replays from 3 identical states; it measures variability within one situation, not between coaches), first-mover edge 4.4 points, spread between scenarios 7.2 points, impasses 0 of 36. Hypotheses: average benefit of coaching 0, +5 or +10 points; variation of that benefit between coach-personality pairs none, 5 or 10 points; self-reflection gain +3 points (cancels in the comparison); spread between agents 2.6 points (the spread of the four demo agents' means, used only as a hypothesis: shuffling the agent labels over the season's scores gives a spread at least that large with p = 0.33, so it may be noise alone). Schedule: 4 training matches per learning branch per day for 14 days, evaluations at the start, day 7 and day 14.

With the measured noise and 16 evaluation matches per frozen version:

| Coaches | Variation between coaches | +10 detected | +5 detected | False alarms at 0 | 95% interval, +/- points | Matches in two weeks |
|---|---|---|---|---|---|---|
| 8 | none | 100% | 99% | 5.6% | 2.1 | 1,792 |
| 8 | +/-5 points | 99% | 58% | 5.2% | 4.5 | 1,792 |
| 8 | +/-10 points | 66% | 22% | 5.2% | 8.2 | 1,792 |
| 10 | none | 100% | >99% | 4.7% | 1.8 | 2,240 |
| 10 | +/-5 points | >99% | 71% | 5.0% | 3.9 | 2,240 |
| 10 | +/-10 points | 78% | 28% | 4.2% | 7.2 | 2,240 |
| 16 | none | 100% | 100% | 4.8% | 1.4 | 3,584 |
| 16 | +/-5 points | 100% | 90% | 4.7% | 3.0 | 3,584 |
| 16 | +/-10 points | 95% | 44% | 4.5% | 5.4 | 3,584 |

Reading it: more matches make each agent's score more precise; more coaches show whether the benefit generalises. When the benefit varies a lot between coaches, going from 4 to 64 evaluation matches barely moves detection (10 coaches, +5 points, variation 10: 25% to 30%), while going from 8 to 16 coaches does. Ranking stability of frozen versions is a hypothesis-driven figure: if agents truly differ by the spread above, two independent runs of the same evaluation agree with a median rank correlation of 0.34 at 4 matches, 0.66 at 16 and 0.87 at 64 (10 coaches). Every cell, including half and 1.5 times the noise, is in `sim/results.json`; across all 135 zero-benefit cells false alarms run from 4.0% to 6.0%, and `tests/test_sim.py` checks that they stay near 5%.

## Cost of running the duel

Three separate lines:

1. **Additional API spend for this demo: 0 USD.** Every call ran on a Claude subscription through the Claude Code CLI.
2. **Observed usage** (raw usage returned by the CLI, all 248 calls behind the current corpus, no failed attempt): per duel on average 5.0 calls, 1,913 output tokens, 6,115 input tokens written to cache, 6,584 read from cache and about 10 uncached, about 20 seconds. The 6 lesson updates used 1,587 output tokens in all. Total for the duels: 293,524 cache-write, 316,018 cache-read, 484 uncached input and 91,804 output tokens. The replaced part of the first run (30 duels, 4 lesson updates) used 149 more calls on the same subscription, kept in `corpus/superseded/`.
3. **Equivalent API cost, estimated** at the public list price of the only model run, `claude-sonnet-5-5`, read on 2026-10-10 at https://platform.claude.com/docs/en/about-claude/pricing (input 2 USD, 1-hour cache write 4 USD, cache read 0.10 USD, output 10 USD per million tokens): **0.044 USD per duel, 0.047 USD counting lesson updates** ("duel only" vs "duel + learning"). The CLI's own cost field gives the same total (2.12 USD for the 48 duels). A pilot of 10 coaches with 16 evaluation matches per version, about 2,240 matches and 280 lesson updates, would come to about 104 USD at that rate. Effort was set to low; another model or effort level changes these numbers.

A character count of the prompts and outputs (about 945,000 characters for 702,000 reported tokens) is kept only as a rough control: the CLI adds its own schema and framing.

## Model calls, isolated

Recorded on the machine that ran the season: `claude --version` = `2.1.296 (Claude Code)`. `claude --help` lists both `--json-schema <schema>` ("JSON Schema for structured output validation") and `--safe-mode` ("Start with all customizations ... disabled"). `claude auth status` reports `"authMethod": "claude.ai"` (subscription); `--bare` is not used.

Each call (`duel/llm.py`) runs from an empty temporary folder with `--system-prompt` (replaces the default), `--tools ""`, `--strict-mcp-config`, `--setting-sources ""`, `--safe-mode`, `--no-session-persistence`, `--output-format json`, `--json-schema`, `--model sonnet`, `--effort low`. Every `ANTHROPIC_*` variable is removed from the child environment; `env | grep -i anthropic` printed nothing during the run. An exhausted-quota message stops the run cleanly; overload and rate-limit messages are retried. The schema check never replaces the engine's own validation.

There is no seed or temperature control in the CLI, and fixing the draw would erase the luck being measured. Seeds exist for the scenario generator and the simulation only.

## Group round (written, not built)

The duel comes first; the group round would be built on top of the duel's agents and memory store. Proposed rules, to be built as a paid prototype with its cost measured:

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
- `corpus/` everything recorded: duels, memory events, coach notes, agents, scenarios; `corpus/superseded/` the first run, kept for the record
- `site/` the static replay page
- `tests/` model-free tests
