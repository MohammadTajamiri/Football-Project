-- =====================================================================
--  FOOTBALL STATS DATABASE  (FotMob-style)
--  Engine: SQLite 3 (also runs on PostgreSQL with the small changes
--  noted at the bottom of this file).
--
--  Three layers:
--    1. Reference   competitions, seasons, teams, venues, referees, players, squads
--    2. Match       matches, team sheets, team stats, player stats, events, shots, momentum
--    3. League      standings snapshots + analysis views (H2H, season totals, league summary)
--
--  Every fact table has a `source` column so you always know where a
--  number came from (e.g. 'fotmob', 'openfootball', 'api-football').
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- 1. REFERENCE TABLES
-- ---------------------------------------------------------------------

CREATE TABLE competitions (
    competition_id     INTEGER PRIMARY KEY,
    fotmob_league_id   INTEGER UNIQUE,          -- FotMob id, e.g. 47 = Premier League
    name               TEXT    NOT NULL,
    country            TEXT,
    type               TEXT    NOT NULL DEFAULT 'league' CHECK (type IN ('league','cup','international')),
    tier               INTEGER                  -- 1 = top division
);

CREATE TABLE seasons (
    season_id          INTEGER PRIMARY KEY,
    competition_id     INTEGER NOT NULL REFERENCES competitions(competition_id),
    name               TEXT    NOT NULL,        -- '2025/26' (FotMob format)
    start_date         DATE,
    end_date           DATE,
    is_current         INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0,1)),
    UNIQUE (competition_id, name)
);

CREATE TABLE venues (
    venue_id           INTEGER PRIMARY KEY,
    name               TEXT    NOT NULL,
    city               TEXT,
    capacity           INTEGER,
    surface            TEXT,
    UNIQUE (name)
);

CREATE TABLE teams (
    team_id            INTEGER PRIMARY KEY,
    fotmob_team_id     INTEGER UNIQUE,          -- FotMob id (filled by the FotMob loader)
    name               TEXT    NOT NULL UNIQUE, -- 'Manchester City'
    short_name         TEXT,                    -- 'Man City'
    code               TEXT,                    -- 'MCI'
    country            TEXT,
    home_venue_id      INTEGER REFERENCES venues(venue_id)
);

CREATE TABLE referees (
    referee_id         INTEGER PRIMARY KEY,
    name               TEXT    NOT NULL UNIQUE,
    country            TEXT
);

CREATE TABLE players (
    player_id          INTEGER PRIMARY KEY,
    fotmob_player_id   INTEGER UNIQUE,
    fpl_code           INTEGER UNIQUE,          -- Fantasy Premier League player code (stable across seasons)
    fbref_id           TEXT    UNIQUE,          -- FBref player id, e.g. 'e342ad68'
    understat_id       INTEGER UNIQUE,
    name               TEXT    NOT NULL,        -- display name, 'Dominik Szoboszlai'
    nationality        TEXT,                    -- 3-letter code, e.g. 'HUN'
    date_of_birth      DATE,
    height_cm          INTEGER,
    preferred_foot     TEXT    CHECK (preferred_foot IN ('left','right','both')),
    primary_position   TEXT    CHECK (primary_position IN ('GK','DF','MF','FW'))
);

-- Which players were in which squad in which season (handles mid-season transfers)
CREATE TABLE squad_memberships (
    season_id          INTEGER NOT NULL REFERENCES seasons(season_id),
    team_id            INTEGER NOT NULL REFERENCES teams(team_id),
    player_id          INTEGER NOT NULL REFERENCES players(player_id),
    shirt_number       INTEGER,
    first_match_date   DATE,
    last_match_date    DATE,
    PRIMARY KEY (season_id, team_id, player_id)
);

-- ---------------------------------------------------------------------
-- 2. MATCH TABLES
-- ---------------------------------------------------------------------

CREATE TABLE matches (
    match_id           INTEGER PRIMARY KEY,
    fotmob_match_id    INTEGER UNIQUE,          -- e.g. 4813399 = Liverpool v Arsenal, 31 Aug 2025
    season_id          INTEGER NOT NULL REFERENCES seasons(season_id),
    round_no           INTEGER,                 -- matchday (league / group / league phase); NULL in knockouts
    stage              TEXT,                    -- NULL for leagues; 'Group stage', 'League phase', 'Knockout play-offs', 'Round of 16', 'Quarter-finals', 'Semi-finals', 'Final'
    leg                INTEGER,                 -- 1 / 2 for two-legged ties
    kickoff_utc        TIMESTAMP,
    home_team_id       INTEGER NOT NULL REFERENCES teams(team_id),
    away_team_id       INTEGER NOT NULL REFERENCES teams(team_id),
    status             TEXT    NOT NULL DEFAULT 'finished'
                       CHECK (status IN ('scheduled','live','finished','postponed','cancelled')),
    home_score         INTEGER,
    away_score         INTEGER,
    ht_home_score      INTEGER,
    ht_away_score      INTEGER,
    went_to            TEXT    CHECK (went_to IN ('ET','PEN')),   -- scores above include extra time
    home_pens          INTEGER,
    away_pens          INTEGER,
    venue_id           INTEGER REFERENCES venues(venue_id),
    referee_id         INTEGER REFERENCES referees(referee_id),
    attendance         INTEGER,
    source             TEXT,
    CHECK (home_team_id <> away_team_id)
);
CREATE INDEX ix_matches_season  ON matches(season_id, round_no);
CREATE INDEX ix_matches_home    ON matches(home_team_id);
CREATE INDEX ix_matches_away    ON matches(away_team_id);

-- One row per team per match: the "team sheet" header FotMob shows above the lineup
CREATE TABLE match_team_sheets (
    match_id           INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    team_id            INTEGER NOT NULL REFERENCES teams(team_id),
    is_home            INTEGER NOT NULL CHECK (is_home IN (0,1)),
    formation          TEXT,                    -- '4-2-3-1'
    coach_name         TEXT,
    team_rating        REAL,                    -- FotMob average team rating
    source             TEXT,
    PRIMARY KEY (match_id, team_id)
);

-- Team stats per match, per period. Mirrors FotMob "Stats" tab groups.
-- period: 'ALL' (full match), '1H', '2H'
CREATE TABLE team_match_stats (
    match_id               INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    team_id                INTEGER NOT NULL REFERENCES teams(team_id),
    period                 TEXT    NOT NULL DEFAULT 'ALL' CHECK (period IN ('ALL','1H','2H')),
    -- Top stats
    possession_pct         REAL,
    xg                     REAL,
    total_shots            INTEGER,
    big_chances            INTEGER,
    big_chances_missed     INTEGER,
    passes_total           INTEGER,             -- some totals are derived from FotMob's success % (accurate / pct)
    passes_accurate        INTEGER,
    fouls                  INTEGER,
    corners                INTEGER,
    -- Shots
    shots_on_target        INTEGER,
    shots_off_target       INTEGER,
    shots_blocked          INTEGER,
    hit_woodwork           INTEGER,
    shots_inside_box       INTEGER,
    shots_outside_box      INTEGER,
    -- Expected goals
    xg_open_play           REAL,
    xg_set_play            REAL,
    npxg                   REAL,                -- non-penalty xG
    xgot                   REAL,                -- xG on target
    -- Passes
    passes_own_half        INTEGER,
    passes_opp_half        INTEGER,
    long_balls_accurate    INTEGER,
    long_balls_total       INTEGER,
    crosses_accurate       INTEGER,
    crosses_total          INTEGER,
    throw_ins              INTEGER,
    touches_opp_box        INTEGER,
    offsides               INTEGER,
    -- Defence
    tackles_won            INTEGER,
    interceptions          INTEGER,
    blocks                 INTEGER,
    clearances             INTEGER,
    keeper_saves           INTEGER,
    -- Duels
    duels_won              INTEGER,
    ground_duels_won       INTEGER,
    ground_duels_total     INTEGER,
    aerial_duels_won       INTEGER,
    aerial_duels_total     INTEGER,
    dribbles_succeeded     INTEGER,
    dribbles_attempted     INTEGER,
    -- Discipline
    yellow_cards           INTEGER,
    red_cards              INTEGER,
    source                 TEXT,
    PRIMARY KEY (match_id, team_id, period)
);

-- One row per player per match (starters, used subs AND unused subs).
-- This is the heart of "player stats in each game". Mirrors the FotMob
-- player pop-up: rating, top stats, attack, passing, defence, duels, GK.
CREATE TABLE player_match_stats (
    match_id               INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    player_id              INTEGER NOT NULL REFERENCES players(player_id),
    team_id                INTEGER NOT NULL REFERENCES teams(team_id),
    -- Lineup info
    is_starter             INTEGER CHECK (is_starter IN (0,1)),   -- NULL where the source has no lineup
    is_captain             INTEGER NOT NULL DEFAULT 0,
    shirt_number           INTEGER,
    position               TEXT,                -- 'GK','RB','CB','LB','DM','CM','AM','RW','LW','ST'
    minutes_played         INTEGER,
    sub_on_minute          INTEGER,
    sub_off_minute         INTEGER,
    -- Top stats
    rating                 REAL,                -- match rating 0-10 (2025/26: detailed feed, Sofascore-style scale)
    fotmob_rating          REAL,                -- FotMob's own rating, where captured
    is_player_of_match     INTEGER DEFAULT 0,
    goals                  INTEGER,
    penalty_goals          INTEGER,
    penalties_missed       INTEGER,
    own_goals              INTEGER,
    assists                INTEGER,
    -- Attack
    shots_total            INTEGER,
    shots_on_target        INTEGER,
    xg                     REAL,
    xgot                   REAL,
    npxg                   REAL,
    xa                     REAL,                -- expected assists
    big_chances_missed     INTEGER,
    chances_created        INTEGER,             -- key passes
    touches                INTEGER,
    touches_opp_box        INTEGER,
    dribbles_succeeded     INTEGER,
    dribbles_attempted     INTEGER,
    dispossessed           INTEGER,
    possession_lost        INTEGER,
    offsides               INTEGER,
    -- Passing
    passes_accurate        INTEGER,
    passes_total           INTEGER,
    passes_final_third     INTEGER,
    long_balls_accurate    INTEGER,
    long_balls_total       INTEGER,
    crosses_accurate       INTEGER,
    crosses_total          INTEGER,
    -- Defence
    tackles_won            INTEGER,
    tackles_total          INTEGER,
    interceptions          INTEGER,
    clearances             INTEGER,
    headed_clearances      INTEGER,
    blocks                 INTEGER,
    recoveries             INTEGER,
    dribbled_past          INTEGER,
    defensive_contributions INTEGER,            -- FPL 2025/26 defensive contribution count
    -- Duels
    duels_won              INTEGER,
    duels_lost             INTEGER,
    ground_duels_won       INTEGER,
    ground_duels_total     INTEGER,
    aerial_duels_won       INTEGER,
    aerial_duels_total     INTEGER,
    fouls_committed        INTEGER,
    was_fouled             INTEGER,
    -- Discipline
    yellow_cards           INTEGER,
    red_cards              INTEGER,
    -- Goalkeeping
    saves                  INTEGER,
    saves_inside_box       INTEGER,
    goals_conceded         INTEGER,
    xgot_faced             REAL,
    goals_prevented        REAL,                -- xgot_faced - goals_conceded
    punches                INTEGER,
    high_claims            INTEGER,
    sweeper_actions        INTEGER,
    source                 TEXT,
    PRIMARY KEY (match_id, player_id)
);
CREATE INDEX ix_pms_player ON player_match_stats(player_id);
CREATE INDEX ix_pms_team   ON player_match_stats(team_id, match_id);

-- Timeline: goals, cards, substitutions, VAR, missed penalties
CREATE TABLE match_events (
    event_id               INTEGER PRIMARY KEY,
    match_id               INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    team_id                INTEGER REFERENCES teams(team_id),
    minute                 INTEGER NOT NULL,    -- 90 for '90+4'
    added_time             INTEGER,             -- 4 for '90+4'
    period                 TEXT CHECK (period IN ('1H','2H','ET','PEN')),
    event_type             TEXT NOT NULL CHECK (event_type IN
                           ('goal','penalty_goal','own_goal','missed_penalty',
                            'yellow_card','second_yellow','red_card',
                            'substitution','var')),
    player_id              INTEGER REFERENCES players(player_id),   -- scorer / booked / player ON
    related_player_id      INTEGER REFERENCES players(player_id),   -- assist / player OFF
    detail                 TEXT,                -- 'Direct free kick', 'Header', VAR decision...
    home_score_after       INTEGER,
    away_score_after       INTEGER,
    source                 TEXT
);
CREATE INDEX ix_events_match  ON match_events(match_id, minute);
CREATE INDEX ix_events_player ON match_events(player_id);

-- Shot map (FotMob "Shot map"): coordinates in metres on a 105 x 68 pitch, attacking left -> right (x = 105 is the goal line)
CREATE TABLE shots (
    shot_id                INTEGER PRIMARY KEY,
    match_id               INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    team_id                INTEGER NOT NULL REFERENCES teams(team_id),
    player_id              INTEGER REFERENCES players(player_id),
    minute                 INTEGER,
    added_time             INTEGER,
    period                 TEXT,
    x                      REAL,
    y                      REAL,
    xg                     REAL,
    xgot                   REAL,
    outcome                TEXT CHECK (outcome IN ('goal','saved','missed','blocked','woodwork')),
    body_part              TEXT CHECK (body_part IN ('right_foot','left_foot','header','other')),
    situation              TEXT CHECK (situation IN ('open_play','fast_break','set_piece','corner',
                                                     'free_kick','penalty','throw_in')),
    is_own_goal            INTEGER DEFAULT 0,
    goal_mouth_y           REAL,                -- where it crossed the goal line
    goal_mouth_z           REAL,
    source                 TEXT
);
CREATE INDEX ix_shots_match  ON shots(match_id);
CREATE INDEX ix_shots_player ON shots(player_id);

-- FotMob "Momentum" graph: one value per minute, positive = home pressure
CREATE TABLE match_momentum (
    match_id               INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    minute                 REAL    NOT NULL,
    value                  INTEGER NOT NULL,    -- -100 .. +100
    PRIMARY KEY (match_id, minute)
);

-- ---------------------------------------------------------------------
-- 3. LEAGUE TABLES
-- ---------------------------------------------------------------------

-- League table snapshot after each matchday (round 38 = final table)
CREATE TABLE standings (
    season_id              INTEGER NOT NULL REFERENCES seasons(season_id),
    after_round            INTEGER NOT NULL,
    group_name             TEXT,                -- cup group, e.g. 'Group B'; NULL for leagues and league phase
    team_id                INTEGER NOT NULL REFERENCES teams(team_id),
    position               INTEGER NOT NULL,
    played                 INTEGER NOT NULL,
    won                    INTEGER NOT NULL,
    drawn                  INTEGER NOT NULL,
    lost                   INTEGER NOT NULL,
    goals_for              INTEGER NOT NULL,
    goals_against          INTEGER NOT NULL,
    goal_diff              INTEGER NOT NULL,
    points                 INTEGER NOT NULL,
    form                   TEXT,                -- last 5, newest last: 'WWDLW'
    xg_for                 REAL,                -- FotMob xG table
    xg_against             REAL,
    xpoints                REAL,
    PRIMARY KEY (season_id, after_round, team_id)
);

-- =====================================================================
--  VIEWS  (ready-made answers)
-- =====================================================================

-- Every match seen from BOTH sides (one row per team per match). Base for most views.
CREATE VIEW v_team_matches AS
SELECT m.match_id, m.season_id, m.round_no, m.kickoff_utc,
       m.home_team_id AS team_id, m.away_team_id AS opponent_id, 1 AS is_home,
       m.home_score AS goals_for, m.away_score AS goals_against,
       CASE WHEN m.home_score > m.away_score THEN 'W'
            WHEN m.home_score = m.away_score THEN 'D' ELSE 'L' END AS result
FROM matches m WHERE m.status = 'finished'
UNION ALL
SELECT m.match_id, m.season_id, m.round_no, m.kickoff_utc,
       m.away_team_id, m.home_team_id, 0,
       m.away_score, m.home_score,
       CASE WHEN m.away_score > m.home_score THEN 'W'
            WHEN m.away_score = m.home_score THEN 'D' ELSE 'L' END
FROM matches m WHERE m.status = 'finished';

-- Head-to-head summary for any pair of teams (e.g. Arsenal vs Liverpool)
CREATE VIEW v_head_to_head AS
SELECT t.name  AS team,
       o.name  AS opponent,
       COUNT(*)                                   AS played,
       SUM(tm.result = 'W')                       AS wins,
       SUM(tm.result = 'D')                       AS draws,
       SUM(tm.result = 'L')                       AS losses,
       SUM(tm.goals_for)                          AS goals_for,
       SUM(tm.goals_against)                      AS goals_against,
       ROUND(AVG(ts.xg), 2)                       AS avg_xg,
       ROUND(AVG(ts.possession_pct), 1)           AS avg_possession,
       MAX(tm.kickoff_utc)                        AS last_meeting,
       tm.team_id, tm.opponent_id
FROM v_team_matches tm
JOIN teams t ON t.team_id = tm.team_id
JOIN teams o ON o.team_id = tm.opponent_id
LEFT JOIN team_match_stats ts
       ON ts.match_id = tm.match_id AND ts.team_id = tm.team_id AND ts.period = 'ALL'
GROUP BY tm.team_id, tm.opponent_id;

-- Every meeting between two teams with side-by-side stats
CREATE VIEW v_h2h_matches AS
SELECT m.match_id, c.name AS competition, s.name AS season, m.stage, m.round_no, DATE(m.kickoff_utc) AS match_date,
       h.name AS home_team, a.name AS away_team,
       m.home_score, m.away_score, m.ht_home_score, m.ht_away_score,
       hs.possession_pct AS home_possession, as_.possession_pct AS away_possession,
       hs.xg AS home_xg, as_.xg AS away_xg,
       hs.total_shots AS home_shots, as_.total_shots AS away_shots,
       hs.shots_on_target AS home_sot, as_.shots_on_target AS away_sot,
       hs.corners AS home_corners, as_.corners AS away_corners,
       v.name AS venue, r.name AS referee, m.attendance,
       m.home_team_id, m.away_team_id
FROM matches m
JOIN seasons s ON s.season_id = m.season_id
JOIN competitions c ON c.competition_id = s.competition_id
JOIN teams h ON h.team_id = m.home_team_id
JOIN teams a ON a.team_id = m.away_team_id
LEFT JOIN team_match_stats hs  ON hs.match_id  = m.match_id AND hs.team_id  = m.home_team_id AND hs.period  = 'ALL'
LEFT JOIN team_match_stats as_ ON as_.match_id = m.match_id AND as_.team_id = m.away_team_id AND as_.period = 'ALL'
LEFT JOIN venues v   ON v.venue_id   = m.venue_id
LEFT JOIN referees r ON r.referee_id = m.referee_id;

-- Player totals per season & team (FotMob player page "Season stats")
CREATE VIEW v_player_season_stats AS
SELECT c.name AS competition, s.name AS season, p.name AS player, t.name AS team,
       COUNT(CASE WHEN pms.minutes_played > 0 THEN 1 END)      AS appearances,
       SUM(pms.is_starter)                                      AS starts,
       SUM(pms.minutes_played)                                  AS minutes,
       SUM(pms.goals)                                           AS goals,
       SUM(pms.penalty_goals)                                   AS penalty_goals,
       SUM(pms.assists)                                         AS assists,
       ROUND(SUM(pms.xg), 2)                                    AS xg,
       ROUND(SUM(pms.xa), 2)                                    AS xa,
       ROUND(AVG(pms.rating), 2)                                AS avg_rating,
       SUM(pms.yellow_cards)                                    AS yellow_cards,
       SUM(pms.red_cards)                                       AS red_cards,
       ROUND(SUM(pms.goals) * 90.0 / NULLIF(SUM(pms.minutes_played), 0), 2) AS goals_per_90,
       pms.player_id, pms.team_id, m.season_id
FROM player_match_stats pms
JOIN matches m ON m.match_id = pms.match_id
JOIN seasons s ON s.season_id = m.season_id
JOIN competitions c ON c.competition_id = s.competition_id
JOIN players p ON p.player_id = pms.player_id
JOIN teams t   ON t.team_id   = pms.team_id
GROUP BY m.season_id, pms.player_id, pms.team_id;

-- Team season profile incl. home/away splits
CREATE VIEW v_team_season_stats AS
SELECT c.name AS competition, s.name AS season, t.name AS team,
       COUNT(*)                                   AS played,
       SUM(tm.result='W') AS won, SUM(tm.result='D') AS drawn, SUM(tm.result='L') AS lost,
       SUM(tm.goals_for) AS goals_for, SUM(tm.goals_against) AS goals_against,
       SUM(tm.goals_against = 0)                  AS clean_sheets,
       SUM(tm.goals_for = 0)                      AS failed_to_score,
       SUM(CASE WHEN tm.is_home=1 AND tm.result='W' THEN 1 ELSE 0 END) AS home_wins,
       SUM(CASE WHEN tm.is_home=0 AND tm.result='W' THEN 1 ELSE 0 END) AS away_wins,
       SUM(CASE tm.result WHEN 'W' THEN 3 WHEN 'D' THEN 1 ELSE 0 END)   AS points,
       ROUND(AVG(ts.possession_pct),1)            AS avg_possession,
       ROUND(SUM(ts.xg),2)                        AS xg_for,
       tm.team_id, tm.season_id
FROM v_team_matches tm
JOIN seasons s ON s.season_id = tm.season_id
JOIN competitions c ON c.competition_id = s.competition_id
JOIN teams t   ON t.team_id   = tm.team_id
LEFT JOIN team_match_stats ts ON ts.match_id = tm.match_id AND ts.team_id = tm.team_id AND ts.period='ALL'
GROUP BY tm.season_id, tm.team_id;

-- League-wide numbers per season ("League stats in general")
CREATE VIEW v_league_season_summary AS
SELECT s.name AS season, c.name AS competition,
       COUNT(*)                                                      AS matches,
       SUM(m.home_score + m.away_score)                              AS total_goals,
       ROUND(AVG(m.home_score + m.away_score), 2)                    AS goals_per_match,
       ROUND(100.0 * SUM(m.home_score > m.away_score) / COUNT(*), 1) AS home_win_pct,
       ROUND(100.0 * SUM(m.home_score = m.away_score) / COUNT(*), 1) AS draw_pct,
       ROUND(100.0 * SUM(m.home_score < m.away_score) / COUNT(*), 1) AS away_win_pct,
       SUM(m.home_score = 0 AND m.away_score = 0)                    AS goalless_draws,
       ROUND(100.0 * SUM(m.home_score > 0 AND m.away_score > 0) / COUNT(*), 1) AS btts_pct,
       ROUND(100.0 * SUM(m.home_score + m.away_score > 2) / COUNT(*), 1)      AS over_2_5_pct,
       MAX(m.home_score + m.away_score)                              AS most_goals_in_match,
       ROUND(AVG(m.attendance))                                      AS avg_attendance,
       m.season_id
FROM matches m
JOIN seasons s      ON s.season_id = m.season_id
JOIN competitions c ON c.competition_id = s.competition_id
WHERE m.status = 'finished'
GROUP BY m.season_id;

-- Final league table per season
CREATE VIEW v_final_table AS
SELECT c.name AS competition, s.name AS season, st.group_name, st.position, t.name AS team, st.played, st.won, st.drawn, st.lost,
       st.goals_for, st.goals_against, st.goal_diff, st.points, st.form,
       st.season_id, st.team_id
FROM standings st
JOIN seasons s ON s.season_id = st.season_id
JOIN competitions c ON c.competition_id = s.competition_id
JOIN teams t   ON t.team_id   = st.team_id
WHERE st.after_round = (SELECT MAX(after_round) FROM standings x WHERE x.season_id = st.season_id);

-- =====================================================================
--  PostgreSQL notes
--   * INTEGER PRIMARY KEY  ->  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY
--   * flags (0/1)          ->  BOOLEAN
--   * SUM(condition)       ->  COUNT(*) FILTER (WHERE condition)
--   * drop the PRAGMA line
-- =====================================================================
