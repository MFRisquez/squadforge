## Friend-facing rules (WhatsApp)

Paste-ready version:

- `docs/RULES_WHATSAPP.txt` (scoring + captain + chips + Technical Director)
- `docs/CHIPS.md` (chip design)
- `docs/TECHNICAL_DIRECTOR.md` (TD design)



- `backend/app/scoring/goalkeeper.py`
- `backend/app/scoring/defender.py`
- `backend/app/scoring/midfielder.py`
- `backend/app/scoring/attacker.py`
- `backend/app/scoring/scouting.py`

## Balance goal

Extras should reward real work **without** letting one position farm points.

Rough “good GW” targets (appearance included):

| Outcome | Typical points |
|---------|----------------|
| DEF clean sheet | ~6 |
| DEF CS + solid defensive extras (capped) | ~8–10 |
| MID goal | ~7 |
| MID goal + creation threshold | ~9–10 |
| ATT goal | ~6 |
| ATT goal + shot thresholds | ~8–9 |

So a noisy CB with lots of clearances should not quietly beat a MID who scored.

## Appearance (all positions)

- **2** if 60'+ minutes
- **2** if any minutes **and** a goal or assist (impactful cameo / sub who delivers)
- **1** if they played but didn’t hit either of the above
- **0** if they didn’t play

This is on top of the normal goal/assist points — it only upgrades the cheap 1-pt appearance to a full 2 when the player actually produced.

## Goalkeeper

- Appearance: as above
- Clean sheet: 4 · Goals conceded: −1 per 2 · Saves: +1 per 3
- Goal 6 · Assist 3 · Pen saved 5 · Pen missed −2
- YC −1 · RC −3 · OG −2

## Defender — base + thresholds

**Base (kept):** appearance (incl. cameo rule), goal 6, assist 3, CS 4, −1 / 2 conceded, cards/OG.

**Extras (threshold → flat points, then cap 4):**

| KPI | Threshold | Points | Why |
|-----|-----------|--------|-----|
| Successful tackles | ≥ 5 | **2** | Your example; meaningful volume |
| Interceptions | ≥ 4 | **1** | Useful but easier to rack → fewer pts than tackles |
| Blocks | ≥ 3 | **1** | Strong CB signal, less frequent |
| Clearances | ≥ 10 | **1** | High volume stat → high bar, low reward |
| Goal-line clearance / “save on the line” | ≥ 1 | **1** | Big play bonus |

If several extras hit at once, keep lines in this **priority order** until the extras total reaches **4** (later lines become 0 that GW): goal-line → tackles → interceptions → blocks → clearances.

## Midfielder — same idea, lower cap

**Base:** appearance, goal 5, assist 3, CS 1, cards.

**Extras (cap 3):**

| KPI | Threshold | Points | Why |
|-----|-----------|--------|-----|
| Key passes | ≥ 4 | **2** | MID identity = chance creation |
| Tackles | ≥ 5 | **1** | Same bar as DEF, half the reward (avoid box-to-box farming both) |
| Interceptions | ≥ 4 | **1** | Defensive MID spice |

## Attacker — thresholds on shots

**Base:** appearance, goal 4, assist 3, cards.

**Extras (cap 3):**

| KPI | Threshold | Points | Why |
|-----|-----------|--------|-----|
| Shots on target | ≥ 3 | **2** | Quality chance creation/finishing pressure |
| Shots | ≥ 6 | **1** | Volume only if they really pepper the goal |

Sot is harder than raw shots, so it pays more. Cap stops a blank 10-shot game from outscoring a goal.

## Scouting bonus (+2) — league rule

**Ownership rule (best for 5–10 friends):** the player is owned by **exactly 1** manager in the private league.

Why not “5%”? With 10 managers, 5% ≈ half a person — it collapses to unique ownership anyway. Unique is clear and drama-friendly (“only you had him”).

If the league grows past 10 managers: owned by **≤ 10%** of managers (at least 1).

**Performance trigger:** that differential player records **any of**:
- a goal, or
- an assist, or
- a clean sheet **and** position is GK or DEF

Then the owning manager gets **+2 scouting** on that player for the GW.

Applied in `score_player(..., owners_count=1, league_size=8)` via `scouting.py`.

## Technical Director

See `docs/TECHNICAL_DIRECTOR.md`.

- Pick one PL club for **3 consecutive GWs**
- Win **+3** · Draw **+1** · Loss **−1**
- Not a chip; added to manager GW total as `technical_director`
- Cannot pick the same club two blocks in a row

## Captain (locked)

- Default captain multiplier: **×2**
- Triple Captain chip: **×3** for that GW only (replaces ×2, does not stack)

## Chips

See `docs/CHIPS.md`. Friend summary is in `docs/RULES_WHATSAPP.txt`.

## KPI sources

| KPI | Source notes |
|-----|----------------|
| minutes, goals, assists, cards, CS, GC, saves | FPL / API-Football — reliable |
| tackles, interceptions, blocks, clearances, key_passes, shots | API-Football — good |
| goal_line_clearances | Often missing or inconsistently tagged — may need **manual admin flag** for v1 |

## Still open

- ~~Super Sub if sub doesn’t play?~~ → chip still consumed (**locked**)
- ~~2nd Wildcard~~ → from **GW20** (**locked**)
- Skip classic BPS/bonus for v1? (**Yes — locked**)
