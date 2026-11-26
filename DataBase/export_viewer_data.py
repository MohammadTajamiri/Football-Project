"""Export football.db for the viewer page: core.json + one file per season (lineups, events, shots, momentum)."""
import json, re, sqlite3, sys
from pathlib import Path

DB, OUTDIR = sys.argv[1], Path(sys.argv[2])
OUTDIR.mkdir(parents=True, exist_ok=True)
HERE = Path(__file__).parent
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row
q = lambda sql, *a: db.execute(sql, a).fetchall()


def r2(v, d=2):
    return round(v, d) if isinstance(v, float) else v


COLORS = {
    "Arsenal": ("#E8202A", "#2B5BA8"), "Aston Villa": ("#8A1F4C", "#7FB2DE"),
    "Bournemouth": ("#D5222C", "#7C7C7C"), "Brentford": ("#E30613", "#E0A800"),
    "Brighton & Hove Albion": ("#0057B8", "#E0B400"), "Burnley": ("#7A1F4F", "#7EC0EA"),
    "Chelsea": ("#1453B5", "#D4A017"), "Crystal Palace": ("#1B4FA8", "#C4122E"),
    "Everton": ("#1D46B0", "#8E8E8E"), "Fulham": ("#5A5A5A", "#CC0000"),
    "Ipswich Town": ("#0B55C4", "#DE2C37"), "Leeds United": ("#1D4FA8", "#E8B800"),
    "Leicester City": ("#0B3FA8", "#F0B000"), "Liverpool": ("#C8102E", "#00A398"),
    "Luton Town": ("#F07A10", "#1F4E9A"), "Manchester City": ("#5FA4D9", "#2A3F7A"),
    "Manchester United": ("#DA291C", "#E8C800"), "Newcastle United": ("#4A4A4A", "#41B6E6"),
    "Nottingham Forest": ("#D10A11", "#7C878E"), "Sheffield United": ("#E52535", "#666666"),
    "Southampton": ("#D71920", "#E8B000"), "Sunderland": ("#E2142A", "#A59466"),
    "Tottenham Hotspur": ("#2C3E8C", "#9AA5B1"), "West Ham United": ("#8A2B42", "#1BA6D8"),
    "Wolverhampton Wanderers": ("#E8A800", "#5A5A5A"),
}

COLORS.update({  # La Liga / Serie A clubs
    "Alavés": ("#1E4FA8", "#7C7C7C"), "Almería": ("#D1202F", "#2B5BA8"), "Athletic Club": ("#E2231A", "#2A2A2A"),
    "Atlético Madrid": ("#CB3524", "#272E61"), "Barcelona": ("#A50044", "#004D98"), "Real Betis": ("#0BB363", "#7C7C7C"),
    "Cádiz": ("#E0B400", "#1F4FA8"), "Celta Vigo": ("#6AAEDC", "#C8102E"), "Elche": ("#0B7A4B", "#7C7C7C"),
    "Espanyol": ("#1E5BC6", "#7C7C7C"), "Getafe": ("#1C4FA0", "#D1202F"), "Girona": ("#D1202F", "#7C7C7C"),
    "Granada": ("#C8102E", "#1F4FA8"), "Las Palmas": ("#E0B400", "#1F4FA8"), "Leganés": ("#1F4FA8", "#7C7C7C"),
    "Levante": ("#8A1F4C", "#1F4FA8"), "Mallorca": ("#C8102E", "#E0B400"), "Osasuna": ("#C8102E", "#1F2F6B"),
    "Real Oviedo": ("#1F4FA8", "#7C7C7C"), "Rayo Vallecano": ("#D1202F", "#6E6E6E"), "Real Madrid": ("#8C7AE6", "#E0B400"),
    "Real Sociedad": ("#1F5FB4", "#7C7C7C"), "Sevilla": ("#D1202F", "#7C7C7C"), "Valencia": ("#E87A00", "#4A4A4A"),
    "Real Valladolid": ("#6B2C91", "#7C7C7C"), "Villarreal": ("#E0B400", "#1F4FA8"), "AC Milan": ("#C8102E", "#2A2A2A"),
    "Atalanta": ("#1E5BC6", "#2A2A2A"), "Bologna": ("#A21C26", "#1A2D5A"), "Cagliari": ("#A21C26", "#1A2D5A"),
    "Como": ("#1E5BC6", "#7C7C7C"), "Cremonese": ("#B3122E", "#7C7C7C"), "Empoli": ("#1E5BC6", "#7C7C7C"),
    "Fiorentina": ("#6B2C91", "#7C7C7C"), "Frosinone": ("#E0B400", "#1F4FA8"), "Genoa": ("#A21C26", "#1A2D5A"),
    "Hellas Verona": ("#1F3F8F", "#E0B400"), "Inter": ("#0B4EA2", "#2A2A2A"), "Juventus": ("#4A4A4A", "#C9A227"),
    "Lazio": ("#6AAEDC", "#1A2D5A"), "Lecce": ("#E0B400", "#C8102E"), "Monza": ("#C8102E", "#7C7C7C"),
    "Napoli": ("#12A0D7", "#1A2D5A"), "Parma": ("#E0B400", "#1F4FA8"), "Pisa": ("#1A2D5A", "#7C7C7C"),
    "Roma": ("#8E1F2F", "#E0A000"), "Salernitana": ("#7A1F2B", "#7C7C7C"), "Sassuolo": ("#00A651", "#2A2A2A"),
    "Torino": ("#7A1F2B", "#7C7C7C"), "Udinese": ("#4A4A4A", "#7C7C7C"), "Venezia": ("#E87A00", "#0B6B3A"),
    "Bayern München": ("#DC052D", "#0066B2"), "Paris Saint-Germain": ("#1A2F6B", "#D1202F"), "Borussia Dortmund": ("#E0B400", "#2A2A2A"),
    "Bayer Leverkusen": ("#E32221", "#2A2A2A"), "Benfica": ("#E8202A", "#7C7C7C"), "Porto": ("#1E5BC6", "#7C7C7C"),
    "Sporting CP": ("#008057", "#7C7C7C"), "RB Leipzig": ("#DD0741", "#1A2D5A"), "Celtic": ("#018749", "#7C7C7C"),
    "Galatasaray": ("#A90432", "#FDB912"), "Club Brugge": ("#0B5CA8", "#2A2A2A"), "PSV": ("#E2231A", "#7C7C7C"),
    "Feyenoord": ("#E2231A", "#2A2A2A"), "Ajax": ("#D2122E", "#7C7C7C"), "Marseille": ("#2FAEE0", "#7C7C7C"),
    "Monaco": ("#E2231A", "#7C7C7C"), "Lille": ("#C8102E", "#1A2D5A"), "Eintracht Frankfurt": ("#E1000F", "#2A2A2A"),
})
core = {}
core["competitions"] = [dict(id=r["competition_id"], n=r["name"], s={"Premier League": "Premier League", "La Liga": "La Liga", "Serie A": "Serie A", "Champions League": "Champions League"}[r["name"]], cup=r["type"] == "cup") for r in q("SELECT * FROM competitions ORDER BY competition_id")]
core["teams"] = {r["team_id"]: dict(n=r["name"], s=r["short_name"], c=r["code"], k=r["country"], col=COLORS.get(r["name"])) for r in q("SELECT * FROM teams")}
core["seasons"] = [dict(id=r["season_id"], n=r["name"], c=r["competition_id"]) for r in q("SELECT * FROM seasons ORDER BY competition_id, name")]
core["coverage"] = {r["season_id"]: dict(m=r["m"], p=r["p"], sh=r["sh"], ts=r["ts"], poss=r["poss"], ev=r["ev"], mo=r["mo"]) for r in q('''
  SELECT s.season_id, COUNT(*) m,
    SUM(EXISTS(SELECT 1 FROM player_match_stats p WHERE p.match_id=m.match_id AND p.minutes_played>0)) p,
    SUM(EXISTS(SELECT 1 FROM shots x WHERE x.match_id=m.match_id)) sh,
    SUM(EXISTS(SELECT 1 FROM team_match_stats t WHERE t.match_id=m.match_id AND t.total_shots IS NOT NULL)) ts,
    SUM(EXISTS(SELECT 1 FROM team_match_stats t WHERE t.match_id=m.match_id AND t.possession_pct IS NOT NULL)) poss,
    SUM((SELECT COUNT(*) FROM match_events e WHERE e.match_id=m.match_id AND e.event_type IN ('goal','penalty_goal','own_goal')) = m.home_score + m.away_score
        AND (m.home_score + m.away_score > 0 OR EXISTS(SELECT 1 FROM shots x WHERE x.match_id=m.match_id))) ev,
    SUM(EXISTS(SELECT 1 FROM match_momentum x WHERE x.match_id=m.match_id)) mo
  FROM seasons s JOIN matches m USING(season_id) GROUP BY s.season_id''')}
core["players"] = {r["player_id"]: [r["name"], r["primary_position"]] for r in q("SELECT * FROM players")}
core["venues"] = {r["venue_id"]: r["name"] for r in q("SELECT * FROM venues")}
core["refs"] = {r["referee_id"]: r["name"] for r in q("SELECT * FROM referees")}
core["matches"] = [[r["match_id"], r["season_id"], r["round_no"], r["kickoff_utc"], r["home_team_id"], r["away_team_id"],
                    r["home_score"], r["away_score"], r["ht_home_score"], r["ht_away_score"], r["venue_id"], r["referee_id"],
                    r["attendance"], r["fotmob_match_id"], r["stage"], r["leg"], r["went_to"], r["home_pens"], r["away_pens"]]
                   for r in q("SELECT * FROM matches ORDER BY kickoff_utc")]
ts_cols = [c[1] for c in db.execute("PRAGMA table_info(team_match_stats)")][3:-1]
core["teamstats"] = {}
for r in q("SELECT * FROM team_match_stats WHERE period='ALL'"):
    core["teamstats"].setdefault(r["match_id"], {})[r["team_id"]] = dict(v={c: r2(r[c]) for c in ts_cols if r[c] is not None}, src=r["source"])
core["sheets"] = {}
for r in q("SELECT * FROM match_team_sheets"):
    core["sheets"].setdefault(r["match_id"], {})[r["team_id"]] = [r["formation"], r["coach_name"], r["team_rating"]]
core["standings"] = {}
for r in q("SELECT * FROM standings ORDER BY season_id, after_round, position"):
    core["standings"].setdefault(r["season_id"], {}).setdefault(r["after_round"], []).append(
        [r["team_id"], r["position"], r["played"], r["won"], r["drawn"], r["lost"], r["goals_for"], r["goals_against"],
         r["goal_diff"], r["points"], r["form"], r2(r["xg_for"], 1), r2(r["xg_against"], 1), r["group_name"]])
core["summary"] = [dict(r) for r in q("SELECT * FROM v_league_season_summary ORDER BY season_id")]
core["counts"] = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
                  ["matches", "player_match_stats", "match_events", "players", "shots", "match_momentum", "standings", "team_match_stats"]}

# ---- schema + samples (Tables tab)
schema_sql = (HERE / "schema.sql").read_text()
LAYER = {"competitions": "Reference", "seasons": "Reference", "venues": "Reference", "teams": "Reference", "referees": "Reference",
         "players": "Reference", "squad_memberships": "Reference", "matches": "Match", "match_team_sheets": "Match",
         "team_match_stats": "Match", "player_match_stats": "Match", "match_events": "Match", "shots": "Match",
         "match_momentum": "Match", "standings": "League"}
FEAT = "(SELECT match_id FROM matches WHERE fotmob_match_id=4813399)"
SAMPLE = {
    "matches": "SELECT * FROM matches WHERE stage IS NOT NULL ORDER BY kickoff_utc DESC LIMIT 8",
    "match_team_sheets": f"SELECT * FROM match_team_sheets ORDER BY match_id={FEAT} DESC, match_id DESC LIMIT 8",
    "team_match_stats": f"SELECT * FROM team_match_stats WHERE match_id={FEAT}",
    "player_match_stats": f"SELECT * FROM player_match_stats WHERE match_id={FEAT} AND minutes_played>0 ORDER BY rating DESC LIMIT 10",
    "match_events": f"SELECT * FROM match_events WHERE match_id={FEAT}",
    "shots": f"SELECT * FROM shots WHERE match_id={FEAT} ORDER BY minute",
    "match_momentum": f"SELECT * FROM match_momentum WHERE match_id={FEAT} LIMIT 10",
    "standings": "SELECT * FROM standings WHERE after_round=38 AND season_id=3 ORDER BY position LIMIT 8",
    "squad_memberships": "SELECT * FROM squad_memberships WHERE season_id=3 ORDER BY team_id, shirt_number LIMIT 8",
    "players": "SELECT * FROM players ORDER BY player_id LIMIT 8",
}
tables = []
for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY rowid"):
    body = re.search(rf"CREATE TABLE {name} \((.*?)\n\);", schema_sql, re.S).group(1)
    group, comments, groups = None, {}, {}
    for line in body.splitlines():
        s = line.strip()
        m = re.match(r"^-- (.+)$", s)
        if m:
            group = m.group(1); continue
        m = re.match(r"^([a-z_0-9]+)\s+(\w+)", s)
        if m and m.group(1) not in ("PRIMARY", "UNIQUE", "CHECK"):
            c = re.search(r"--\s*(.+)$", s); comments[m.group(1)] = c.group(1) if c else ""; groups[m.group(1)] = group
    n = db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    cols = []
    for cid, cname, ctype, notnull, dflt, pk in db.execute(f"PRAGMA table_info({name})"):
        filled = db.execute(f"SELECT COUNT({cname}) FROM {name}").fetchone()[0]
        cols.append(dict(n=cname, t=ctype, pk=pk > 0, g=groups.get(cname), d=comments.get(cname, ""), f=round(100 * filled / n, 1) if n else 0))
    fks = [dict(col=r[3], ref=r[2]) for r in db.execute(f"PRAGMA foreign_key_list({name})")]
    cur = db.execute(SAMPLE.get(name, f"SELECT * FROM {name} LIMIT 8"))
    tables.append(dict(name=name, layer=LAYER[name], rows=n, cols=cols, fks=fks, sample=[[r2(v, 3) for v in r] for r in cur.fetchall()]))
VDESC = {
    "v_team_matches": "Every match from both sides: one row per team per match with result W/D/L.",
    "v_head_to_head": "Record of any team against any opponent: played, W/D/L, goals, average xG and possession.",
    "v_h2h_matches": "Every meeting with side-by-side score, xG, possession, shots, venue and referee.",
    "v_player_season_stats": "Player totals per season and club: apps, minutes, goals, assists, xG, xA, cards, avg rating, goals per 90.",
    "v_team_season_stats": "Team season profile: W/D/L, goals, clean sheets, home and away wins, points, possession, xG.",
    "v_league_season_summary": "Competition-wide numbers per season: goals per match, home/draw/away %, BTTS, over 2.5.",
    "v_final_table": "Final league table for each season, taken from the last standings snapshot.",
}
VSAMPLE = {
    "v_head_to_head": "SELECT * FROM v_head_to_head WHERE team IN ('Arsenal','Liverpool') AND opponent IN ('Arsenal','Liverpool')",
    "v_h2h_matches": "SELECT * FROM v_h2h_matches WHERE home_team IN ('Arsenal','Real Madrid') AND away_team IN ('Arsenal','Real Madrid') OR home_team IN ('Arsenal','Liverpool') AND away_team IN ('Arsenal','Liverpool') ORDER BY match_date",
    "v_player_season_stats": "SELECT * FROM v_player_season_stats WHERE season='2023/24' ORDER BY goals DESC LIMIT 8",
    "v_team_season_stats": "SELECT * FROM v_team_season_stats WHERE competition='La Liga' AND season='2025/26' ORDER BY points DESC LIMIT 8",
    "v_final_table": "SELECT * FROM v_final_table WHERE competition='Serie A' AND season='2025/26' LIMIT 8",
}
views = []
for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY rowid"):
    sql = VSAMPLE.get(name, f"SELECT * FROM {name} LIMIT 8")
    cur = db.execute(sql)
    views.append(dict(name=name, desc=VDESC[name], query=sql, cols=[d[0] for d in cur.description],
                      sample=[[r2(v, 3) for v in r] for r in cur.fetchall()]))
core["tables"], core["views"] = tables, views
(OUTDIR / "core.json").write_text(json.dumps(core, separators=(",", ":"), ensure_ascii=False))

# ---- per season
LU = ["team_id", "player_id", "is_starter", "is_captain", "minutes_played", "sub_on_minute", "sub_off_minute", "goals",
      "penalty_goals", "own_goals", "yellow_cards", "red_cards", "rating", "shirt_number", "position", "is_player_of_match",
      "fotmob_rating", "assists", "xg", "xa", "shots_total", "shots_on_target", "chances_created", "touches", "passes_accurate",
      "passes_total", "tackles_won", "interceptions", "recoveries", "duels_won", "duels_lost", "dribbles_succeeded", "saves",
      "xgot", "clearances", "big_chances_missed", "aerial_duels_won", "goals_prevented"]
OUTC = {"goal": "g", "saved": "s", "missed": "m", "blocked": "b", "woodwork": "w"}
for (sid,) in db.execute("SELECT season_id FROM seasons"):
    sd = dict(lineups={}, events={}, shots={}, momentum={})
    for r in q(f"""SELECT p.* FROM player_match_stats p JOIN matches m USING(match_id) WHERE m.season_id=?
                  ORDER BY p.match_id, p.team_id, p.is_starter DESC,
                  CASE p.position WHEN 'GK' THEN 0 WHEN 'RB' THEN 1 WHEN 'CB' THEN 2 WHEN 'LB' THEN 3 WHEN 'DM' THEN 4
                  WHEN 'CM' THEN 5 WHEN 'RW' THEN 6 WHEN 'AM' THEN 7 WHEN 'LW' THEN 8 WHEN 'ST' THEN 9 ELSE 10 END,
                  COALESCE(p.sub_on_minute, 0), p.minutes_played DESC""", sid):
        sd["lineups"].setdefault(r["match_id"], []).append([r2(r[c]) for c in LU])
    for r in q("""SELECT e.* FROM match_events e JOIN matches m USING(match_id) WHERE m.season_id=?
                  ORDER BY e.match_id, e.minute, COALESCE(e.added_time,0), e.event_id""", sid):
        sd["events"].setdefault(r["match_id"], []).append([r["minute"], r["added_time"], r["event_type"], r["team_id"], r["player_id"],
                                                          r["related_player_id"], r["detail"], r["home_score_after"], r["away_score_after"]])
    for r in q("SELECT s.* FROM shots s JOIN matches m USING(match_id) WHERE m.season_id=? ORDER BY s.match_id, s.minute", sid):
        sd["shots"].setdefault(r["match_id"], []).append([r["team_id"], r["player_id"], r["minute"], r["added_time"], r2(r["x"], 1),
                                                         r2(r["y"], 1), r2(r["xg"], 3), r2(r["xgot"], 3), OUTC.get(r["outcome"]),
                                                         r["situation"], r["body_part"], r["source"]])
    for r in q("SELECT mm.* FROM match_momentum mm JOIN matches m USING(match_id) WHERE m.season_id=? ORDER BY mm.match_id, mm.minute", sid):
        sd["momentum"].setdefault(r["match_id"], []).append([r["minute"], r["value"]])
    (OUTDIR / f"s{sid}.json").write_text(json.dumps(sd, separators=(",", ":"), ensure_ascii=False))
for f in sorted(OUTDIR.glob("*.json")):
    print(f.name, round(f.stat().st_size / 1024), "KB")
