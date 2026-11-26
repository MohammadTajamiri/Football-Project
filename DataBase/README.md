# Football Stats Database (FotMob-style)

`football.db` is a SQLite database (15 tables, 7 views) covering the **Premier League, La Liga, Serie A and the
UEFA Champions League, 2023/24 to 2025/26**, all in the same tables.
Open it with DB Browser for SQLite, DBeaver, Python (`sqlite3`) or any SQLite client.

## What's in it
| Table | Rows | Contents |
|---|---:|---|
| matches | 3,923 | every match; cup stage, leg, extra time and penalties for the Champions League |
| player_match_stats | 80,410 | one row per player per match (~65 FotMob-style stats) |
| team_match_stats | 6,962 | one row per team per match (FotMob stats tab, or what the sources have) |
| shots | 69,785 | shot map: x/y in metres, xG, xGOT, outcome, situation, body part |
| match_events | 15,969 | goals (scorer, assist), own goals, penalties, substitutions, cards, VAR |
| match_momentum | 39,093 | per-minute momentum |
| standings | 7,608 | table after every matchday (league, Champions League groups and league phase) |
| players | 3,552 | linked across seasons and leagues (FPL code, FBref id, Understat id) |

Every row has a `source` column. Coverage by competition and season is on the Overview page of the viewer.

## Coverage
| | Results, tables | Team stats | Player stats | Goal timeline | Shot map |
|---|---|---|---|---|---|
| Premier League, all 3 seasons | all | full (FotMob / Opta) | all | all | all |
| La Liga / Serie A 2023/24 | all | full (Opta via FBref) | all | all | all |
| La Liga / Serie A 2024/25 | all | full for matches to 3 Feb 2025, basic after | matches to 3 Feb 2025 (~58%) | all | all |
| La Liga / Serie A 2025/26 | all | basic (+ full for ~35 matches) | ~35 matches | ~35 matches | ~35 matches |
| Champions League 2023/24, 2024/25 | all (incl. stages, ET, pens) | none | none | none | none |
| Champions League 2025/26 | all | FotMob, 61 matches with English clubs | English players in those 61 | 45 | 45 |

Basic team stats = shots, shots on target, corners, fouls, cards (football-data.co.uk).

## Sources
- openfootball/football.json and openfootball/champions-league: results, HT, kick-off, stages, ET, penalties
- datasets/football-datasets (football-data.co.uk): La Liga and Serie A basic team stats
- olbauday/FPL-Elo-Insights: FotMob match and player stats (PL 2024/25, 2025/26; UCL 2025/26 English clubs),
  plus a second detailed feed (lineups, incidents, shots, momentum, ratings) for 2025/26
- vaastav/Fantasy-Premier-League: official FPL minutes, starts, goals, cards, player ids (Premier League)
- JaseZiv/worldfootballR_data: FBref (Opta) player match stats and shots; Understat shots
- FotMob pages for the two 2025/26 Arsenal v Liverpool matches (FotMob ratings, coaches)

## Checks
- Final tables match the official ones for all 12 competition-seasons checked (incl. 2023/24 PL points deductions,
  La Liga/Serie A head-to-head tiebreaks, Champions League league phase).
- Goal timelines reproduce the final score in every match where they exist (1 La Liga match left out because its
  two own goals could not be attributed).
- Player goals + opponents' own goals = final score in all Premier League matches and >99% of La Liga / Serie A
  matches with player rows.
- Team npxG never exceeds xG; team xG matches FBref's published season totals.
- The FPL-Elo-Insights Champions League file has home and away reversed in many matches; each match was re-oriented
  against the real fixture and kept only if the score agreed (3 of 64 dropped).

## Known gaps (left empty, never estimated)
- La Liga / Serie A player stats after 3 Feb 2025 and most of 2025/26; Champions League detail outside English clubs'
  2025/26 matches. No open source reachable from the build environment has them.
- Starting XIs (is_starter) for La Liga and Serie A; ratings before 2025/26; card minutes outside 2025/26 PL/UCL.
- 2023/24 player duels, big chances and headed clearances (FBref doesn't have them).

## Rebuild
```
python3 -I build_db.py   <openfootball football.json> <download dir> football.db   # Premier League
python3 -I build_more.py <openfootball football.json> <download dir> football.db   # La Liga, Serie A, Champions League
```
The download directory layout is described at the top of each script.
`build_log.txt`, `build_more_log.txt` and `fill_rates.txt` hold the build checks and per-season fill rates.
