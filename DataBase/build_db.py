"""
Build football.db (FotMob-style schema) for the Premier League, 2023/24 - 2025/26.

  python3 -I build_db.py <openfootball football.json repo> <download dir> <out.db>

Sources (download dir layout)
  openfootball/football.json  results, HT scores, kick-off; 2025/26 referee, venue, attendance
  fpl/                         vaastav/Fantasy-Premier-League: per player per match minutes, starts,
                               goals, assists, Opta xG/xA, cards, saves, own goals (+ id tables)
  elo/data/                    olbauday/FPL-Elo-Insights: FotMob match + player stats (2024/25, 2025/26);
                               2025/26 lineups, incidents, shots, momentum, ratings (Sofascore-style feed)
  fbref/, fbref2/              JaseZiv/worldfootballR_data: FBref (Opta) player match stats + shots (2023/24)
  understat/                   JaseZiv/worldfootballR_data: Understat shots with pitch coordinates
"""
import json, re, sqlite3, sys, glob, unicodedata, collections
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import pandas as pd
import pyreadr

OF, DL, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
HERE = Path(__file__).parent
ELO = DL / "elo" / "data"
LOG = []
def log(*a):
    msg = " ".join(str(x) for x in a); LOG.append(msg); print(msg)

SEASONS = [("2023/24", "2023-24", "2023-24/en.1.json"),
           ("2024/25", "2024-25", "2024-25/en.1.json"),
           ("2025/26", "2025-26", "2025-26/en.1-full.json")]

TEAMS = {
    "Arsenal": ("Arsenal", "ARS"), "Aston Villa": ("Aston Villa", "AVL"), "Bournemouth": ("Bournemouth", "BOU"),
    "Brentford": ("Brentford", "BRE"), "Brighton & Hove Albion": ("Brighton", "BHA"), "Burnley": ("Burnley", "BUR"),
    "Chelsea": ("Chelsea", "CHE"), "Crystal Palace": ("Crystal Palace", "CRY"), "Everton": ("Everton", "EVE"),
    "Fulham": ("Fulham", "FUL"), "Ipswich Town": ("Ipswich", "IPS"), "Leeds United": ("Leeds", "LEE"),
    "Leicester City": ("Leicester", "LEI"), "Liverpool": ("Liverpool", "LIV"), "Luton Town": ("Luton", "LUT"),
    "Manchester City": ("Man City", "MCI"), "Manchester United": ("Man United", "MUN"),
    "Newcastle United": ("Newcastle", "NEW"), "Nottingham Forest": ("Nottm Forest", "NFO"),
    "Sheffield United": ("Sheffield Utd", "SHU"), "Southampton": ("Southampton", "SOU"), "Sunderland": ("Sunderland", "SUN"),
    "Tottenham Hotspur": ("Tottenham", "TOT"), "West Ham United": ("West Ham", "WHU"),
    "Wolverhampton Wanderers": ("Wolves", "WOL"),
}
ALIAS = {"Man City": "Manchester City", "Man Utd": "Manchester United", "Manchester Utd": "Manchester United",
         "Newcastle": "Newcastle United", "Newcastle Utd": "Newcastle United", "Nott'm Forest": "Nottingham Forest",
         "Nott'ham Forest": "Nottingham Forest", "Sheffield Utd": "Sheffield United", "Spurs": "Tottenham Hotspur",
         "Tottenham": "Tottenham Hotspur", "West Ham": "West Ham United", "Wolves": "Wolverhampton Wanderers",
         "Brighton": "Brighton & Hove Albion", "Luton": "Luton Town", "Ipswich": "Ipswich Town",
         "Leicester": "Leicester City", "Leeds": "Leeds United"}
DEDUCTIONS = {"2023/24": [("Everton", 10, "2023-11-17"), ("Everton", -4, "2024-02-26"),
                          ("Nottingham Forest", 4, "2024-03-18"), ("Everton", 2, "2024-04-08")]}


def canon_team(n):
    n = re.sub(r"^AFC ", "", str(n)); n = re.sub(r" (FC|AFC)$", "", n); n = ALIAS.get(n, n)
    assert n in TEAMS, n
    return n


def fold(s):
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))
    s = s.replace("ø", "o").replace("Ø", "O").replace("ł", "l").replace("ß", "ss")
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()


def name_sim(a, b):
    ta, tb = fold(a), fold(b)
    if not ta or not tb:
        return 0
    sa, sb = set(ta), set(tb)
    if ta == tb:
        return 1.0
    jac = len(sa & sb) / len(sa | sb)
    sub = 1.0 if (sa <= sb or sb <= sa) else 0
    last = 1.0 if ta[-1] == tb[-1] else 0
    ratio = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    return 0.35 * jac + 0.25 * sub + 0.2 * last + 0.2 * ratio


def num(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, str):
        v = v.strip()
        if v == "":
            return None
        v = float(v)
    f = float(v)
    return int(f) if f.is_integer() else round(f, 4)


def parse_minute(m):
    m = str(m)
    if "+" in m:
        a, b = m.split("+"); return int(float(a)), int(float(b))
    return int(float(m)), None


def kickoff_utc(date, time):
    if " UTC" in time:
        hhmm, off = time.split(" UTC")
        return (datetime.fromisoformat(f"{date}T{hhmm}") - timedelta(hours=int(off or 0))).strftime("%Y-%m-%d %H:%M")
    dt = datetime.fromisoformat(f"{date}T{time}").replace(tzinfo=ZoneInfo("Europe/London"))
    return dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M")


def fbid(href):
    m = re.search(r"/players/([0-9a-f]{8})", str(href))
    return m.group(1) if m else str(href)


def rd(path):
    return list(pyreadr.read_r(str(path)).values())[0]


# =============================================================================
# 1. Base: competition, teams, matches (openfootball)
# =============================================================================
if OUT.exists():
    OUT.unlink()
db = sqlite3.connect(OUT)
db.executescript((HERE / "schema.sql").read_text())
cur = db.cursor()
cur.execute("INSERT INTO competitions VALUES (1, 47, 'Premier League', 'England', 'league', 1)")
team_id = {}
for i, (name, (short, code)) in enumerate(sorted(TEAMS.items()), 1):
    cur.execute("INSERT INTO teams (team_id, name, short_name, code, country) VALUES (?,?,?,?, 'England')", (i, name, short, code))
    team_id[name] = i
TNAME = {v: k for k, v in team_id.items()}
venue_id, referee_id = {}, {}


def get_venue(ground):
    name, _, city = ground.partition(", ")
    if name not in venue_id:
        cur.execute("INSERT INTO venues (name, city) VALUES (?,?)", (name, city or None)); venue_id[name] = cur.lastrowid
    return venue_id[name]


def get_referee(name):
    if name not in referee_id:
        cur.execute("INSERT INTO referees (name, country) VALUES (?, 'England')", (name,)); referee_id[name] = cur.lastrowid
    return referee_id[name]


season_id, MKEY, MINFO, OF_RAW = {}, {}, {}, {}
home_grounds = collections.defaultdict(collections.Counter)
for sid, (sname, _, fname) in enumerate(SEASONS, 1):
    data = json.load(open(OF / fname))["matches"]
    dates = sorted(m["date"] for m in data)
    cur.execute("INSERT INTO seasons VALUES (?,?,?,?,?,0)", (sid, 1, sname, dates[0], dates[-1]))
    season_id[sname] = sid
    for m in data:
        home, away = canon_team(m["team1"]), canon_team(m["team2"])
        sc = m.get("score"); ft = sc.get("ft") if isinstance(sc, dict) else sc; ht = sc.get("ht") if isinstance(sc, dict) else None
        v = get_venue(m["ground"]) if m.get("ground") else None
        if v: home_grounds[home][v] += 1
        ref = get_referee(m["referees"][0]["name"]) if m.get("referees") else None
        ko = kickoff_utc(m["date"], m["time"])
        cur.execute("""INSERT INTO matches (season_id, round_no, kickoff_utc, home_team_id, away_team_id, status, home_score,
                       away_score, ht_home_score, ht_away_score, venue_id, referee_id, attendance, source)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (sid, int(re.search(r"(\d+)\s*$", m["round"]).group(1)), ko, team_id[home], team_id[away], "finished",
                     ft[0], ft[1], ht[0] if ht else None, ht[1] if ht else None, v, ref, m.get("attendance"), "openfootball"))
        mid = cur.lastrowid
        MKEY[(sname, home, away)] = mid
        MINFO[mid] = dict(season=sname, home=team_id[home], away=team_id[away], hs=ft[0], as_=ft[1], ko=ko)
        OF_RAW[mid] = m
for team, cnt in home_grounds.items():
    cur.execute("UPDATE teams SET home_venue_id=? WHERE team_id=?", (cnt.most_common(1)[0][0], team_id[team]))


def mkey(sname, h, a):
    return MKEY[(sname, canon_team(h), canon_team(a))]


# =============================================================================
# 2. Player registry (FPL code = stable identity)
# =============================================================================
P = {}            # player_id -> dict
PID_BY_CODE, PID_BY_ALT = {}, {}
FPL_EL = {}       # (season, element) -> dict(code, first, second, web, pos, dob)
POSMAP = {1: "GK", 2: "DF", 3: "MF", 4: "FW"}


def new_player(code=None, names=None):
    pid = len(P) + 1
    P[pid] = dict(code=code, names={}, pos=None, dob=None, nat=None)
    for prio, n in (names or {}).items():
        P[pid]["names"][prio] = n
    return pid


def set_name(pid, prio, name):
    if name and (prio not in P[pid]["names"]):
        P[pid]["names"][prio] = name


for sname, fpl, _ in SEASONS:
    raw = pd.read_csv(DL / "fpl" / f"{fpl}_players_raw.csv")
    for r in raw.itertuples():
        e = dict(code=int(r.code), first=r.first_name, second=r.second_name, web=r.web_name,
                 pos=POSMAP.get(int(r.element_type)), dob=getattr(r, "birth_date", None))
        FPL_EL[(sname, int(r.id))] = e
        pid = PID_BY_CODE.get(e["code"])
        if pid is None:
            pid = new_player(e["code"]); PID_BY_CODE[e["code"]] = pid
        full = f"{e['first']} {e['second']}".strip()
        smart = e["web"] if (" " in str(e["web"]) and "." not in str(e["web"])) else full
        P[pid]["names"][1] = smart          # FPL (latest season wins)
        P[pid]["fpl_names"] = [full, str(e["web"]), str(e["second"])]
        if e["pos"]: P[pid]["pos"] = e["pos"]
        if isinstance(e["dob"], str) and e["dob"]: P[pid]["dob"] = e["dob"]


def pid_el(sname, element):
    return PID_BY_CODE[FPL_EL[(sname, int(element))]["code"]]


def cand_names(pid):
    p = P[pid]
    return list(p["names"].values()) + p.get("fpl_names", [])


def match_names(rows, cands, name_of, min_of=None, cand_min=None, threshold=0.5):
    """Assign source rows to candidate player ids (within one match + team). Returns {row_index: pid}."""
    pairs = []
    for i, r in enumerate(rows):
        for pid in cands:
            s = max(name_sim(name_of(r), n) for n in cand_names(pid))
            if min_of and cand_min:
                a, b = min_of(r), cand_min.get(pid)
                if a is not None and b is not None:
                    s += 0.3 if abs(a - b) <= 1 else (0.1 if abs(a - b) <= 5 else -0.1)
            pairs.append((s, i, pid))
    pairs.sort(key=lambda x: -x[0])
    out, used = {}, set()
    for s, i, pid in pairs:
        if s < threshold or i in out or pid in used:
            continue
        out[i] = pid; used.add(pid)
    return out


# =============================================================================
# 3. Containers
# =============================================================================
PMS = {}                       # (mid, pid) -> dict(columns)
SRC = collections.defaultdict(set)
TMS = {}                       # (mid, tid) -> dict
TSRC = collections.defaultdict(set)
SHEETS = {}                    # (mid, tid) -> dict(formation, coach, team_rating, source)
EVENTS, SHOTS, MOM = [], [], []
FOTMOB_ID = {}


BYM = collections.defaultdict(set)


def pm(mid, pid, tid, src):
    k = (mid, pid)
    if k not in PMS:
        PMS[k] = dict(team_id=tid, is_starter=0, is_captain=0); BYM[mid].add(pid)
    SRC[k].add(src)
    return PMS[k]


def put(d, col, val, overwrite=True):
    if isinstance(val, str):
        try:
            v = num(val)
        except ValueError:
            v = val.strip() or None
    else:
        v = num(val)
    if v is None:
        return
    if overwrite or d.get(col) is None:
        d[col] = v


def team_players(mid, tid, played=True):
    return [p for p in BYM[mid] if PMS[(mid, p)]["team_id"] == tid and (not played or (PMS[(mid, p)].get("minutes_played") or 0) > 0)]


def tm(mid, tid, src):
    k = (mid, tid)
    TMS.setdefault(k, {}); TSRC[k].add(src)
    return TMS[k]


def total_from_pct(won, pct):
    won, pct = num(won), num(pct)
    if won is None or pct is None:
        return None
    if pct == 0:
        return None if won else None
    return int(round(won * 100.0 / pct))


# ---------------------------------------------------------------------------- FPL (all seasons)
FPL_ROW = {}       # (mid, pid) -> FPL row
FPLBYM = collections.defaultdict(list)
FIX2MID = {}
for sname, fpl, _ in SEASONS:
    teams = pd.read_csv(DL / "fpl" / f"{fpl}_teams.csv"); tname = dict(zip(teams.id, teams.name))
    fx = pd.read_csv(DL / "fpl" / f"{fpl}_fixtures.csv")
    for r in fx.itertuples():
        FIX2MID[(sname, int(r.id))] = mkey(sname, tname[r.team_h], tname[r.team_a])
    gw = pd.read_csv(DL / "fpl" / f"{fpl}.csv")
    for r in gw.itertuples():
        mid = FIX2MID[(sname, int(r.fixture))]
        pid = pid_el(sname, r.element)
        tid = MINFO[mid]["home"] if r.was_home else MINFO[mid]["away"]
        FPL_ROW[(mid, pid)] = r._asdict() | {"tid": tid, "season": sname}; FPLBYM[mid].append(pid)
log("FPL rows:", len(FPL_ROW))


def apply_fpl(mid, pid, tid, create=False):
    """Fill minutes / starts / goals / cards / Opta xG etc. from FPL."""
    r = FPL_ROW.get((mid, pid))
    if r is None:
        return False
    if (mid, pid) not in PMS and not (create and r["minutes"] > 0):
        return False
    d = pm(mid, pid, tid or r["tid"], "fpl")
    put(d, "minutes_played", r["minutes"])
    put(d, "is_starter", int(r.get("starts", 0) or 0))
    put(d, "goals", r["goals_scored"])  # official Premier League record wins
    put(d, "assists", r["assists"], overwrite=False)
    put(d, "own_goals", r["own_goals"])
    put(d, "penalties_missed", r["penalties_missed"], overwrite=False)
    put(d, "yellow_cards", r["yellow_cards"])
    put(d, "red_cards", r["red_cards"])
    put(d, "xg", r.get("expected_goals"), overwrite=False)
    put(d, "xa", r.get("expected_assists"), overwrite=False)
    if P[pid]["pos"] == "GK":
        put(d, "saves", r["saves"], overwrite=False)
        put(d, "goals_conceded", r["goals_conceded"], overwrite=False)
    if r.get("defensive_contribution") is not None and not pd.isna(r.get("defensive_contribution")):
        put(d, "defensive_contributions", r["defensive_contribution"])
    return True


# =============================================================================
# 4. 2023/24 - FBref (Opta) + FPL
# =============================================================================
S = "2023/24"
FB = {t: rd(DL / "fbref" / f"{t}.rds") for t in ["passing", "passing_types", "defense", "possession", "misc", "keeper"]}
FB25 = FB["passing"][FB["passing"].Season_End_Year == 2025].copy()
for t in FB:
    FB[t] = FB[t][FB[t].Season_End_Year == 2024].copy()
    FB[t]["mcode"] = FB[t].MatchURL.str.extract(r"matches/(\w+)/")[0]
base = FB["passing"]
FB_HREF = {}          # (mid, href) -> pid
fb_by_match = collections.defaultdict(list)
for r in base.itertuples():
    fb_by_match[(r.mcode, r.Team)].append(r)
FBMATCH = {}
for (mcode, team), rows in fb_by_match.items():
    r0 = rows[0]
    mid = mkey(S, r0.Home_Team, r0.Away_Team); FBMATCH[mcode] = mid
    tid = team_id[canon_team(team)]
    cands = [pid for pid in FPLBYM[mid] if FPL_ROW[(mid, pid)]["tid"] == tid and FPL_ROW[(mid, pid)]["minutes"] > 0]
    cmin = {pid: FPL_ROW[(mid, pid)]["minutes"] for pid in cands}
    got = match_names(rows, cands, lambda r: r.Player, lambda r: num(r.Min), cmin)
    for i, r in enumerate(rows):
        pid = got.get(i)
        if pid is None:
            key = ("fbref", r.Player_Href)
            pid = PID_BY_ALT.get(key) or new_player(None, {3: r.Player}); PID_BY_ALT[key] = pid
            log("  2023/24 FBref player without FPL match:", r.Player, team, r.Match_Date)
        FB_HREF[(mid, fbid(r.Player_Href))] = pid; P[pid].setdefault("fb", fbid(r.Player_Href))
        set_name(pid, 3, r.Player)
        if isinstance(r.Nation, str) and r.Nation: P[pid]["nat"] = r.Nation.split()[-1]
        d = pm(mid, pid, tid, "fbref")
        put(d, "minutes_played", r.Min, overwrite=False)
        put(d, "shirt_number", r.Player_Num)
        put(d, "position", str(r.Pos).split(",")[0] if isinstance(r.Pos, str) else None)
        put(d, "passes_accurate", r.Cmp_Total); put(d, "passes_total", r.Att_Total)
        put(d, "assists", r.Ast); put(d, "chances_created", r.KP); put(d, "passes_final_third", r.Final_Third)
        put(d, "long_balls_accurate", r.Cmp_Long); put(d, "long_balls_total", r.Att_Long)
        put(d, "xa", r.xA, overwrite=False)
    # FBref formations
    if mid not in [k[0] for k in SHEETS]:
        for side, form in ((MINFO[mid]["home"], r0.Home_Formation), (MINFO[mid]["away"], r0.Away_Formation)):
            if isinstance(form, str) and form:
                SHEETS[(mid, side)] = dict(formation=form.replace("◆", "").strip(), source="fbref")

COLMAP = {
    "passing_types": [("CK_Pass_Types", "_corners"), ("TI_Pass_Types", "_throw_ins"), ("Crs_Pass_Types", "crosses_total")],
    "defense": [("Tkl_Tackles", "tackles_total"), ("TklW_Tackles", "tackles_won"), ("Int", "interceptions"),
                ("Clr", "clearances"), ("Sh_Blocks", "blocks"), ("Lost_Challenges", "dribbled_past")],
    "possession": [("Touches_Touches", "touches"), ("Att Pen_Touches", "touches_opp_box"), ("Att_Take_Ons", "dribbles_attempted"),
                   ("Succ_Take_Ons", "dribbles_succeeded"), ("Dis_Carries", "dispossessed")],
    "misc": [("Fls", "fouls_committed"), ("Fld", "was_fouled"), ("Off", "offsides"), ("Recov", "recoveries"),
             ("Won_Aerial_Duels", "aerial_duels_won"), ("_aerial_total", "aerial_duels_total")],
    "keeper": [("Saves_Shot_Stopping", "saves"), ("GA_Shot_Stopping", "goals_conceded"), ("PSxG_Shot_Stopping", "xgot_faced"),
               ("Stp_Crosses", "high_claims"), ("Player_NumOPA_Sweeper", "sweeper_actions")],
}
for t, cols in COLMAP.items():
    df = FB[t]
    if t == "misc":
        df["_aerial_total"] = pd.to_numeric(df.Won_Aerial_Duels, errors="coerce") + pd.to_numeric(df.Lost_Aerial_Duels, errors="coerce")
    for rec in df.to_dict("records"):
        mid = FBMATCH.get(rec["mcode"])
        pid = FB_HREF.get((mid, fbid(rec["Player_Href"])))
        if pid is None:
            continue
        d = PMS[(mid, pid)]
        for src, col in cols:
            put(d, col, rec.get(src))
        if t == "keeper":
            if num(rec.get("PSxG_Shot_Stopping")) is not None and num(rec.get("GA_Shot_Stopping")) is not None:
                d["goals_prevented"] = round(num(rec["PSxG_Shot_Stopping"]) - num(rec["GA_Shot_Stopping"]), 2)

# FBref shots -> per-player shots, xG, xGOT, npxG, penalty goals; team shot split
fsh = rd(DL / "fbref2" / "match_shooting.rds"); fsh = fsh[fsh.Season_End_Year == 2024].copy()
fsh["mcode"] = fsh.MatchURL.str.extract(r"matches/(\w+)/")[0]
for c_ in ("xG", "PSxG", "Distance"): fsh[c_ + "_n"] = pd.to_numeric(fsh[c_], errors="coerce")
fsh["Minute_s"] = fsh.Minute.astype(str).str.strip()
n0 = len(fsh); fsh = fsh.drop_duplicates(subset=["mcode", "Squad", "Minute_s", "Player", "xG_n", "Outcome", "Distance_n"])
log("FBref 2023/24 shot rows:", n0, "after removing duplicates:", len(fsh))
TEAM_SHOTS = collections.defaultdict(collections.Counter)
for rec in fsh.to_dict("records"):
    mid = FBMATCH.get(rec["mcode"])
    if mid is None:
        continue
    tid = team_id[canon_team(rec["Squad"])]
    pen = "(pen)" in rec["Player"]
    out = rec["Outcome"]; on = out in ("Goal", "Saved")
    ts = TEAM_SHOTS[(mid, tid)]
    ts["shots"] += 1; ts["on"] += on; ts["off"] += out in ("Off Target", "Saved off Target", "Woodwork")
    ts["blocked"] += out == "Blocked"; ts["wood"] += out == "Woodwork"
    ts["inside"] += (num(rec["Distance"]) or 99) <= 16
    ts["xgot"] += (num(rec["PSxG"]) or 0) if on else 0
    ts["npxg"] += 0 if pen else (num(rec["xG"]) or 0)
    ts["xg"] += num(rec["xG"]) or 0
    pid = FB_HREF.get((mid, fbid(rec["Player_Href"])))
    if pid is None:
        continue
    d = PMS[(mid, pid)]
    for c in ("shots_total", "shots_on_target", "_xg_fb", "npxg", "xgot", "penalty_goals"):
        d.setdefault(c, 0)
    d["shots_total"] += 1; d["shots_on_target"] += on
    d["_xg_fb"] = round(d["_xg_fb"] + (num(rec["xG"]) or 0), 3)
    d["npxg"] = round(d["npxg"] + (0 if pen else (num(rec["xG"]) or 0)), 3)
    d["xgot"] = round(d["xgot"] + ((num(rec["PSxG"]) or 0) if on else 0), 3)
    d["penalty_goals"] += int(pen and out == "Goal")
# FBref players who played but never shot: zero shot counts
for (mid, pid), d in PMS.items():
    if MINFO[mid]["season"] == S and "fbref" in SRC[(mid, pid)]:
        for c in ("shots_total", "shots_on_target", "penalty_goals"):
            d.setdefault(c, 0)
        d.setdefault("npxg", 0); d.setdefault("xgot", 0)

# FPL on top for 2023/24 (minutes, starts, goals, cards, Opta xG/xA) + FPL-only appearances
for (mid, pid), r in FPL_ROW.items():
    if r["season"] == S and r["minutes"] > 0:
        apply_fpl(mid, pid, r["tid"], create=True)

# 2023/24 team stats aggregated from player rows
AGG = ["passes_total", "passes_accurate", "long_balls_accurate", "long_balls_total", "crosses_total", "touches_opp_box",
       "offsides", "fouls_committed", "tackles_won", "interceptions", "blocks", "clearances", "saves", "aerial_duels_won",
       "aerial_duels_total", "dribbles_succeeded", "dribbles_attempted", "yellow_cards", "red_cards", "_corners", "_throw_ins"]
TEAM_RENAME = {"fouls_committed": "fouls", "saves": "keeper_saves", "_corners": "corners", "_throw_ins": "throw_ins"}
fb_xg = {}
for rec in base.drop_duplicates("mcode").to_dict("records"):
    mid = FBMATCH[rec["mcode"]]
    fb_xg[(mid, MINFO[mid]["home"])] = num(rec["Home_xG"]); fb_xg[(mid, MINFO[mid]["away"])] = num(rec["Away_xG"])
for mid in set(FBMATCH.values()):
    sums = {}
    for side in (MINFO[mid]["home"], MINFO[mid]["away"]):
        rows = [PMS[(mid, p)] for p in BYM[mid] if PMS[(mid, p)]["team_id"] == side]
        t = tm(mid, side, "fbref (sum of players)")
        for c in AGG:
            vals = [d.get(c) for d in rows if d.get(c) is not None]
            if vals:
                t[TEAM_RENAME.get(c, c)] = int(sum(vals))
        ts = TEAM_SHOTS[(mid, side)]
        t.update(total_shots=ts["shots"], shots_on_target=ts["on"], shots_off_target=ts["off"] - ts["wood"],
                 shots_blocked=ts["blocked"], hit_woodwork=ts["wood"], xgot=round(ts["xgot"], 2))
        # team xG = FBref's published match xG; npxG = that minus the penalty xG of the shots
        t["xg"] = fb_xg.get((mid, side)) if fb_xg.get((mid, side)) is not None else round(ts["xg"], 2)
        t["npxg"] = round(max((t["xg"] or 0) - (ts["xg"] - ts["npxg"]), 0), 2)
        sums[side] = t.get("passes_total") or 0
    tot = sum(sums.values())
    if tot:
        for side, v in sums.items():
            TMS[(mid, side)]["possession_pct"] = round(100.0 * v / tot)
# 2023/24 xG per player: FPL Opta xG where present, else FBref shot xG
for (mid, pid), d in PMS.items():
    if MINFO[mid]["season"] == S:
        if d.get("xg") is None and d.get("_xg_fb") is not None:
            d["xg"] = d["_xg_fb"]
        d.pop("_xg_fb", None); d.pop("_corners", None); d.pop("_throw_ins", None)
for (mid, pid), d in PMS.items():
    d.pop("_corners", None); d.pop("_throw_ins", None); d.pop("_xg_fb", None)
log("2023/24 player rows:", sum(1 for (m, p) in PMS if MINFO[m]["season"] == S))

# =============================================================================
# 5. FotMob player + team stats (FPL-Elo-Insights), 2024/25 and 2025/26
# =============================================================================
PMS_COLS = {  # FotMob column -> schema column
    "minutes_played": "minutes_played", "goals": "goals", "assists": "assists", "total_shots": "shots_total", "xg": "xg",
    "xa": "xa", "xgot": "xgot", "shots_on_target": "shots_on_target", "successful_dribbles": "dribbles_succeeded",
    "big_chances_missed": "big_chances_missed", "touches_opposition_box": "touches_opp_box", "touches": "touches",
    "accurate_passes": "passes_accurate", "chances_created": "chances_created", "final_third_passes": "passes_final_third",
    "accurate_crosses": "crosses_accurate", "accurate_long_balls": "long_balls_accurate", "tackles_won": "tackles_won",
    "interceptions": "interceptions", "recoveries": "recoveries", "blocks": "blocks", "clearances": "clearances",
    "headed_clearances": "headed_clearances", "dribbled_past": "dribbled_past", "duels_won": "duels_won",
    "duels_lost": "duels_lost", "ground_duels_won": "ground_duels_won", "aerial_duels_won": "aerial_duels_won",
    "was_fouled": "was_fouled", "fouls_committed": "fouls_committed", "saves": "saves", "goals_conceded": "goals_conceded",
    "xgot_faced": "xgot_faced", "goals_prevented": "goals_prevented", "sweeper_actions": "sweeper_actions",
    "offsides": "offsides", "high_claim": "high_claims", "tackles": "tackles_total", "penalties_scored": "penalty_goals",
    "penalties_missed": "penalties_missed", "dispossessed": "dispossessed", "saves_inside_box": "saves_inside_box",
    "defensive_contributions": "defensive_contributions",
}
PCT_TOTALS = [("accurate_passes", "accurate_passes_percent", "passes_total"),
              ("accurate_long_balls", "accurate_long_balls_percent", "long_balls_total"),
              ("accurate_crosses", "accurate_crosses_percent", "crosses_total"),
              ("ground_duels_won", "ground_duels_won_percent", "ground_duels_total"),
              ("aerial_duels_won", "aerial_duels_won_percent", "aerial_duels_total"),
              ("successful_dribbles", "successful_dribbles_percent", "dribbles_attempted")]
TEAM_COLS = {
    "possession": "possession_pct", "expected_goals_xg": "xg", "total_shots": "total_shots", "shots_on_target": "shots_on_target",
    "big_chances": "big_chances", "big_chances_missed": "big_chances_missed", "accurate_passes": "passes_accurate",
    "passes": "passes_total", "fouls_committed": "fouls", "corners": "corners", "xg_open_play": "xg_open_play",
    "xg_set_play": "xg_set_play", "non_penalty_xg": "npxg", "xg_on_target_xgot": "xgot", "shots_off_target": "shots_off_target",
    "blocked_shots": "shots_blocked", "hit_woodwork": "hit_woodwork", "shots_inside_box": "shots_inside_box",
    "shots_outside_box": "shots_outside_box", "own_half": "passes_own_half", "opposition_half": "passes_opp_half",
    "accurate_long_balls": "long_balls_accurate", "accurate_crosses": "crosses_accurate", "throws": "throw_ins",
    "touches_in_opposition_box": "touches_opp_box", "offsides": "offsides", "yellow_cards": "yellow_cards",
    "red_cards": "red_cards", "tackles_won": "tackles_won", "interceptions": "interceptions", "blocks": "blocks",
    "clearances": "clearances", "keeper_saves": "keeper_saves", "duels_won": "duels_won", "ground_duels_won": "ground_duels_won",
    "aerial_duels_won": "aerial_duels_won", "successful_dribbles": "dribbles_succeeded",
}
TEAM_PCT = [("accurate_long_balls", "accurate_long_balls_pct", "long_balls_total"),
            ("accurate_crosses", "accurate_crosses_pct", "crosses_total"),
            ("ground_duels_won", "ground_duels_won_pct", "ground_duels_total"),
            ("aerial_duels_won", "aerial_duels_won_pct", "aerial_duels_total"),
            ("successful_dribbles", "successful_dribbles_pct", "dribbles_attempted")]


def load_fotmob(S, matches, pms, teams_df, lineup_side=None):
    code2name = dict(zip(teams_df.code, teams_df.name))
    slug2mid = {}
    for r in matches.to_dict("records"):
        mid = mkey(S, code2name[r["home_team"]], code2name[r["away_team"]])
        slug2mid[r["match_id"]] = mid
        if num(r.get("fotmob_id")):
            FOTMOB_ID[mid] = int(num(r["fotmob_id"]))
        for side, pre in ((MINFO[mid]["home"], "home_"), (MINFO[mid]["away"], "away_")):
            t = tm(mid, side, "fotmob")
            for c, col in TEAM_COLS.items():
                put(t, col, r.get(pre + c))
            for won, pct, col in TEAM_PCT:
                v = total_from_pct(r.get(pre + won), r.get(pre + pct))
                if v is not None: t[col] = v
    n_side_missing = 0
    match_end = pms[pms.minutes_played > 0].groupby("match_id").finish_min.max().to_dict()
    for r in pms.to_dict("records"):
        mid = slug2mid[r["match_id"]]
        pid = pid_el(S, r["player_id"])
        side = None
        if lineup_side:
            side = lineup_side.get((mid, pid))
        if side is None and (mid, pid) in FPL_ROW:
            side = FPL_ROW[(mid, pid)]["tid"]
        if side is None:
            n_side_missing += 1; continue
        d = pm(mid, pid, side, "fotmob")
        for c, col in PMS_COLS.items():
            if c in r: put(d, col, r[c])
        for won, pct, col in PCT_TOTALS:
            v = total_from_pct(r.get(won), r.get(pct))
            if v is not None: d[col] = v
        st, fi, mins = num(r.get("start_min")), num(r.get("finish_min")), num(r.get("minutes_played")) or 0
        apply_fpl(mid, pid, side)
        if mins > 0:
            if st and st > 0: d["sub_on_minute"] = st
            end = match_end.get(r["match_id"])
            if fi is not None and end is not None and fi < end and fi > (st or 0) and not (d.get("red_cards") or 0):
                d["sub_off_minute"] = fi
        if FPL_ROW.get((mid, pid)) is None:
            d["is_starter"] = int(mins > 0 and not (st and st > 0))
    log(S, "FotMob player rows:", len(pms), "side unknown:", n_side_missing)
    return slug2mid


# ---- 2024/25
S = "2024/25"
m24 = pd.read_csv(ELO / "2024-2025" / "matches" / "matches.csv")
p24 = pd.read_csv(ELO / "2024-2025" / "playermatchstats" / "playermatchstats.csv")
t24 = pd.read_csv(ELO / "2024-2025" / "teams" / "teams.csv")
load_fotmob(S, m24, p24, t24)
for (mid, pid), r in FPL_ROW.items():   # FPL appearances FotMob missed
    if r["season"] == S and r["minutes"] > 0 and (mid, pid) not in PMS:
        apply_fpl(mid, pid, r["tid"], create=True)

# FBref 2024/25 (first 239 matches): formations, shirt numbers, positions, nationality
FB25["mcode"] = FB25.MatchURL.str.extract(r"matches/(\w+)/")[0]
for (mcode, team), g in FB25.groupby(["mcode", "Team"]):
    rows = g.to_dict("records"); r0 = rows[0]
    mid = mkey(S, r0["Home_Team"], r0["Away_Team"]); tid = team_id[canon_team(team)]
    form = r0["Home_Formation"] if tid == MINFO[mid]["home"] else r0["Away_Formation"]
    if isinstance(form, str) and form:
        SHEETS[(mid, tid)] = dict(formation=form.replace("◆", "").strip(), source="fbref")
    cands = team_players(mid, tid)
    cmin = {p: PMS[(mid, p)].get("minutes_played") for p in cands}
    got = match_names(rows, cands, lambda r: r["Player"], lambda r: num(r["Min"]), cmin)
    for i, r in enumerate(rows):
        if i in got:
            d = PMS[(mid, got[i])]
            put(d, "shirt_number", r["Player_Num"]); put(d, "position", str(r["Pos"]).split(",")[0] if isinstance(r["Pos"], str) else None)
            set_name(got[i], 3, r["Player"]); P[got[i]].setdefault("fb", fbid(r["Player_Href"]))
            if isinstance(r["Nation"], str) and r["Nation"]: P[got[i]]["nat"] = r["Nation"].split()[-1]

# ---- 2025/26 (FotMob + detailed feed)
S = "2025-26"
E = ELO / "2025-2026" / "By Tournament" / "Premier League"
cat = lambda f: pd.concat([pd.read_csv(x) for x in sorted(glob.glob(str(E / "*" / f)))], ignore_index=True)
m25, p25, t25 = cat("matches.csv"), cat("playermatchstats.csv"), pd.read_csv(ELO / "2025-2026" / "teams.csv")
lu25, inc25, sh25, mo25, en25 = cat("lineups.csv"), cat("incidents.csv"), cat("shots.csv"), cat("momentum.csv"), cat("player_match_enrichment.csv")
S = "2025/26"
code2name = dict(zip(t25.code, t25.name))
slug_pre = {}
for r in m25.to_dict("records"):
    slug_pre[r["match_id"]] = mkey(S, code2name[r["home_team"]], code2name[r["away_team"]])
lineup_side = {}
for r in lu25.to_dict("records"):
    mid = slug_pre[r["match_id"]]
    lineup_side[(mid, pid_el(S, r["player_id"]))] = MINFO[mid]["home"] if r["team_side"] == "home" else MINFO[mid]["away"]
slug25 = load_fotmob(S, m25, p25, t25, lineup_side)
POS_LETTER = {"G": "GK", "D": "DF", "M": "MF", "F": "FW"}
for r in lu25.to_dict("records"):
    mid = slug25[r["match_id"]]; pid = pid_el(S, r["player_id"]); tid = lineup_side[(mid, pid)]
    d = pm(mid, pid, tid, "lineups")
    d["is_starter"] = int(str(r["is_starting"]) == "True")
    put(d, "shirt_number", r["jersey_number"]); put(d, "position", POS_LETTER.get(r["position"]))
    d.setdefault("minutes_played", 0)
    if isinstance(r.get("formation"), str):
        SHEETS[(mid, tid)] = dict(formation=r["formation"], source="lineups feed")
for mid in set(slug25.values()):
    for tid in (MINFO[mid]["home"], MINFO[mid]["away"]):
        ps = [p for p in BYM[mid] if PMS[(mid, p)]["team_id"] == tid]
        if sum(PMS[(mid, p)]["is_starter"] for p in ps) != 11:
            fpl_st = {p: int(FPL_ROW[(mid, p)].get("starts") or 0) for p in ps if (mid, p) in FPL_ROW}
            if sum(fpl_st.values()) == 11:
                for p in ps: PMS[(mid, p)]["is_starter"] = fpl_st.get(p, 0)
                log("  2025/26 lineup feed had wrong starter count; used FPL starts:", TNAME[tid], MINFO[mid]["ko"])
for r in en25.to_dict("records"):
    mid = slug25[r["match_id"]]; pid = pid_el(S, r["player_id"])
    d = PMS.get((mid, pid))
    if d is None:
        continue
    SRC[(mid, pid)].add("detailed feed")
    put(d, "rating", r["rating"]); put(d, "possession_lost", r["possession_lost"]); put(d, "punches", r["goalkeeper_punches"])
    put(d, "passes_total", r["total_passes"]); put(d, "long_balls_total", r["total_long_balls"])
    put(d, "crosses_total", r["total_crosses"]); put(d, "dribbles_attempted", r["total_dribbles"])
    if num(r.get("ground_duels_lost")) is not None and d.get("ground_duels_won") is not None:
        d["ground_duels_total"] = d["ground_duels_won"] + num(r["ground_duels_lost"])
    if num(r.get("aerial_duels_lost")) is not None and d.get("aerial_duels_won") is not None:
        d["aerial_duels_total"] = d["aerial_duels_won"] + num(r["aerial_duels_lost"])

# 2025/26 common names from the openfootball lineups (better than short or legal names)
PARTICLES_ = {"van", "de", "da", "der", "den", "dos", "di", "le", "la", "du", "von"}
def norm_of(sname):
    out = []
    for i, t in enumerate(sname.split()):
        if t.isupper():
            t = t.lower() if i > 0 and t.lower() in PARTICLES_ else "-".join(x.capitalize() for x in t.split("-"))
        out.append(t)
    return " ".join(out)
for mid, m in OF_RAW.items():
    if MINFO[mid]["season"] != "2025/26":
        continue
    for lu, tid in ((m["lineup"][0], MINFO[mid]["home"]), (m["lineup"][1], MINFO[mid]["away"])):
        names = [x["name"] for x in lu.get("starter", []) + lu.get("bench", [])]
        got = match_names(names, team_players(mid, tid, played=False), lambda x: norm_of(x), threshold=0.55)
        for i, n in enumerate(names):
            if i in got and len(n.split()) <= 3:
                set_name(got[i], 2.5, norm_of(n))

# =============================================================================
# 6. Events
# =============================================================================
def ev(mid, tid, minute, added, etype, p=None, rp=None, detail=None, src=None):
    EVENTS.append(dict(match_id=mid, team_id=tid, minute=minute, added_time=added, event_type=etype, player_id=p,
                       related_player_id=rp, detail=detail, source=src))




# ---- 2025/26 incidents
GOAL_OK, GOAL_BAD = 0, []
SUB_FLIP = [0, 0]
inc25["mid"] = inc25.match_id.map(slug25)
for mid, g in inc25.groupby("mid"):
    g = g.sort_values(["minute", "added_time", "incident_index"], na_position="first", ascending=[True, True, False])
    h, a, goals = 0, 0, []
    for r in g.to_dict("records"):
        t = r["incident_type"]; mi = num(r["minute"]); add = num(r["added_time"])
        if mi is None or mi < 0:
            continue
        side = MINFO[mid]["home"] if r["team_side"] == "home" else MINFO[mid]["away"] if r["team_side"] == "away" else None
        p = pid_el(S, r["player_id"]) if num(r["player_id"]) else None
        if t == "goal":
            hs, as_ = num(r["home_score"]), num(r["away_score"])
            scoring = MINFO[mid]["home"] if hs is not None and hs > h else MINFO[mid]["away"]
            h, a = (hs, as_) if hs is not None else (h, a)
            etype = {"penalty": "penalty_goal", "ownGoal": "own_goal"}.get(r["goal_type"], "goal")
            assist = pid_el(S, r["assist_player_id"]) if num(r["assist_player_id"]) else None
            goals.append(dict(match_id=mid, team_id=scoring, minute=mi, added_time=add, event_type=etype, player_id=p,
                              related_player_id=assist, detail=None, source="detailed feed", home_score_after=h, away_score_after=a))
        elif t == "card":
            ev(mid, side, mi, add, {"yellow": "yellow_card", "red": "red_card", "yellowRed": "second_yellow"}[r["card_type"]], p, src="detailed feed")
        elif t == "substitution":
            q = pid_el(S, r["secondary_player_id"]) if num(r["secondary_player_id"]) else None
            sp, sq = PMS.get((mid, p), {}).get("is_starter"), PMS.get((mid, q), {}).get("is_starter")
            on, off = (q, p) if (sp == 1 and sq != 1) or (sp is None and sq == 0) else (p, q)
            if sp == 0 and sq == 0 and PMS.get((mid, p), {}).get("sub_on_minute") is not None and (mid, q) in PMS \
               and (PMS[(mid, q)].get("sub_on_minute") or 0) < (PMS[(mid, p)].get("sub_on_minute") or 0):
                on, off = p, q
            SUB_FLIP[0] += (on == q); SUB_FLIP[1] += 1
            ev(mid, side, mi, add, "substitution", on, off, src="detailed feed")
            if on and (mid, on) in PMS:
                PMS[(mid, on)]["sub_on_minute"] = mi
            if off and (mid, off) in PMS:
                PMS[(mid, off)]["sub_off_minute"] = mi
        elif t == "varDecision":
            ev(mid, side, mi, add, "var", p, detail=r.get("text") if isinstance(r.get("text"), str) else None, src="detailed feed")
    if (h, a) == (MINFO[mid]["hs"], MINFO[mid]["as_"]) and len(goals) == h + a:
        GOAL_OK += 1; EVENTS.extend(goals)
    else:
        GOAL_BAD.append(mid)
log("2025/26 subs where the feed's second player is the one coming on:", SUB_FLIP)
log("2025/26 goal timelines matching the score:", GOAL_OK, "/ 380; falling back to openfootball for", len(GOAL_BAD))
# openfootball fallback for goals
PARTICLES = {"van", "de", "da", "der", "den", "dos", "di", "le", "la", "du", "von"}
for mid in GOAL_BAD:
    m = OF_RAW[mid]; hs = as_ = 0
    seq = []
    for side_key, side in (("goals1", MINFO[mid]["home"]), ("goals2", MINFO[mid]["away"])):
        for gl in m.get(side_key, []):
            mi, add = parse_minute(gl["minute"]); seq.append((mi, add or 0, side, gl))
    for mi, add, side, gl in sorted(seq, key=lambda x: (x[0], x[1])):
        other = MINFO[mid]["away"] if side == MINFO[mid]["home"] else MINFO[mid]["home"]
        cands = team_players(mid, other if gl.get("owngoal") else side)
        got = match_names([gl], cands, lambda x: x["name"], threshold=0.35)
        if side == MINFO[mid]["home"]: hs += 1
        else: as_ += 1
        EVENTS.append(dict(match_id=mid, team_id=side, minute=mi, added_time=add or None,
                           event_type="own_goal" if gl.get("owngoal") else "penalty_goal" if gl.get("penalty") else "goal",
                           player_id=got.get(0), related_player_id=None, detail=None, source="openfootball",
                           home_score_after=hs, away_score_after=as_))

# ---- 2023/24 + 2024/25 goals from Understat; shots for the shot map
US = rd(DL / "understat" / "EPL_shot_data.rds")
US = US[US.season.isin([2023, 2024])].copy()
US["h_a"] = [h if isinstance(h, str) and h in ("h", "a") else ("h" if str(x).lower().startswith("h") else "a")
             for h, x in zip(US.h_a, US.home_away)]
US_SEASON = {2023: "2023/24", 2024: "2024/25"}
OUTC = {"Goal": "goal", "SavedShot": "saved", "MissedShots": "missed", "BlockedShot": "blocked", "ShotOnPost": "woodwork"}
SIT = {"OpenPlay": "open_play", "FromCorner": "corner", "SetPiece": "set_piece", "DirectFreekick": "free_kick", "Penalty": "penalty"}
BODY = {"RightFoot": "right_foot", "LeftFoot": "left_foot", "Head": "header", "OtherBodyPart": "other"}
us_ok, us_bad = 0, []
for (season, home, away), g in US.groupby(["season", "home_team", "away_team"]):
    S = US_SEASON[season]; mid = mkey(S, home, away)
    sides = {"h": MINFO[mid]["home"], "a": MINFO[mid]["away"]}
    goals = []
    pmap = {}
    for side_code, tid in sides.items():
        rows = g[g.h_a == side_code].to_dict("records")
        usid = {r["player"]: r["player_id"] for r in rows}
        names = sorted({r["player"] for r in rows} | {r["player_assisted"] for r in rows if isinstance(r["player_assisted"], str)})
        cands = team_players(mid, tid)
        got = match_names(names, cands, lambda x: x, threshold=0.4)
        for i, n in enumerate(names):
            if i in got:
                pmap[(tid, n)] = got[i]; set_name(got[i], 2, n)
                if num(usid.get(n)) is not None: P[got[i]].setdefault("us", int(num(usid[n])))
    for r in g.sort_values(["minute", "id"]).to_dict("records"):
        tid = sides[r["h_a"]]; other = sides["a" if r["h_a"] == "h" else "h"]
        mi = int(r["minute"]); add = None
        if mi > 90: mi, add = 90, mi - 90
        if r["result"] == "OwnGoal":
            # Understat lists own goals under the team that benefited; the player belongs to the other side
            best = {}
            for t_ in (tid, other):
                for c_ in team_players(mid, t_):
                    sc_ = max(name_sim(r["player"], n) for n in cand_names(c_))
                    if sc_ > best.get("s", 0.39): best = dict(s=sc_, team=t_, pid=c_)
            ogp = best.get("pid")
            scorer_team = (other if best.get("team") == tid else tid) if ogp else tid
            goals.append((mi, add, "own_goal", scorer_team, ogp, None))
            continue
        pid = pmap.get((tid, r["player"]))
        if r["result"] == "Goal":
            goals.append((mi, add, "penalty_goal" if r["situation"] == "Penalty" else "goal", tid, pid,
                          pmap.get((tid, r["player_assisted"])) if isinstance(r["player_assisted"], str) else None))
        SHOTS.append(dict(match_id=mid, team_id=tid, player_id=pid, minute=mi, added_time=add, period=None,
                          x=round(num(r["X"]) * 105, 1), y=round(num(r["Y"]) * 68, 1), xg=round(num(r["xG"]), 4), xgot=None,
                          outcome=OUTC[r["result"]], body_part=BODY.get(r["shotType"]), situation=SIT.get(r["situation"]),
                          is_own_goal=0, goal_mouth_y=None, goal_mouth_z=None, source="understat"))
    hs = as_ = 0; out = []
    for mi, add, et, tid, p, a in goals:
        if tid == MINFO[mid]["home"]: hs += 1
        else: as_ += 1
        out.append(dict(match_id=mid, team_id=tid, minute=mi, added_time=add, event_type=et, player_id=p, related_player_id=a,
                        detail=None, source="understat", home_score_after=hs, away_score_after=as_))
    if (hs, as_) == (MINFO[mid]["hs"], MINFO[mid]["as_"]):
        us_ok += 1
    else:
        us_bad.append((S, TNAME[MINFO[mid]['home']], TNAME[MINFO[mid]['away']], (hs, as_), (MINFO[mid]['hs'], MINFO[mid]['as_'])))
    EVENTS.extend(out)
log("Understat goal timelines matching the score:", us_ok, "/ 760", us_bad[:5])

# ---- 2024/25 substitutions from FotMob start/finish minutes
for mid in {m for (m, p) in PMS if MINFO[m]["season"] == "2024/25"}:
    for tid in (MINFO[mid]["home"], MINFO[mid]["away"]):
        rows = [(p, PMS[(mid, p)]) for p in BYM[mid] if PMS[(mid, p)]["team_id"] == tid]
        ons = collections.defaultdict(list); offs = collections.defaultdict(list)
        for p, d in rows:
            if d.get("sub_on_minute") and (d.get("minutes_played") or 0) > 0: ons[d["sub_on_minute"]].append(p)
            if d.get("sub_off_minute"): offs[d["sub_off_minute"]].append(p)
        for minute, on_list in ons.items():
            off_list, todo, pair = list(offs.get(minute, [])), list(on_list), {}
            changed = True
            while changed and todo:
                changed = False
                for p in list(todo):
                    fine = PMS[(mid, p)].get("position")
                    same = [q for q in off_list if fine and PMS[(mid, q)].get("position") == fine]
                    if len(same) != 1:
                        same = [q for q in off_list if P[q]["pos"] == P[p]["pos"]]
                    if len(same) == 1:
                        pair[p] = same[0]; off_list.remove(same[0]); todo.remove(p); changed = True
                if len(todo) == 1 and len(off_list) == 1:
                    pair[todo[0]] = off_list.pop(); todo.clear()
            for p in on_list:
                mi_, add_ = (90, minute - 90) if minute > 90 else (minute, None)
                ev(mid, tid, mi_, add_, "substitution", p, pair.get(p), src="fotmob (start/finish minutes)")

# =============================================================================
# 7. Shots + momentum 2025/26
# =============================================================================
S = "2025/26"
OUT2 = {"goal": "goal", "save": "saved", "miss": "missed", "block": "blocked", "post": "woodwork"}
SIT2 = {"regular": "open_play", "assisted": "open_play", "fast-break": "fast_break", "corner": "corner", "set-piece": "set_piece",
        "free-kick": "free_kick", "penalty": "penalty", "throw-in-set-piece": "throw_in"}
BODY2 = {"right-foot": "right_foot", "left-foot": "left_foot", "head": "header", "other": "other"}
pen_xg = sh25[sh25.situation == "penalty"].xg
log("2025/26 penalty xG in feed: median", round(pen_xg.median(), 4), "std", round(pen_xg.std(), 4))
NPXG = collections.Counter()
for r in sh25.to_dict("records"):
    if r["outcome"] == "ownGoal":
        continue
    mid = slug25[r["match_id"]]; tid = MINFO[mid]["home"] if str(r["is_home"]) == "True" else MINFO[mid]["away"]
    pid = pid_el(S, r["player_id"]) if num(r["player_id"]) else None
    SHOTS.append(dict(match_id=mid, team_id=tid, player_id=pid, minute=num(r["minute"]), added_time=num(r["added_time"]), period=None,
                      x=round(105 - num(r["start_x"]) * 1.05, 1), y=round(num(r["start_y"]) * 0.68, 1), xg=num(r["xg"]),
                      xgot=num(r["xgot"]), outcome=OUT2[r["outcome"]], body_part=BODY2.get(r["body_part"]),
                      situation=SIT2.get(r["situation"]), is_own_goal=0, goal_mouth_y=num(r["goal_mouth_y"]),
                      goal_mouth_z=num(r["goal_mouth_z"]), source="detailed feed"))
    if r["situation"] != "penalty" and pid:
        NPXG[(mid, pid)] += num(r["xg"]) or 0
for (mid, pid), d in PMS.items():
    if MINFO[mid]["season"] == S and (d.get("minutes_played") or 0) > 0:
        d["npxg"] = round(NPXG.get((mid, pid), 0), 3)
    elif MINFO[mid]["season"] == "2024/25" and d.get("xg") is not None:
        pens = (d.get("penalty_goals") or 0) + (d.get("penalties_missed") or 0)
        d["npxg"] = round(max(d["xg"] - pens * float(pen_xg.median()), 0), 3)
for r in mo25.to_dict("records"):
    MOM.append((slug25[r["match_id"]], num(r["minute"]), num(r["value"])))
for s in SHOTS:
    s["period"] = "1H" if s["minute"] is not None and s["minute"] <= 45 else "2H"
for e in EVENTS:
    e["period"] = "1H" if e["minute"] <= 45 else "2H"

# =============================================================================
# 8. FotMob overlay for the two featured matches (ratings, positions, coach, team rating)
# =============================================================================
for fm in json.load(open(HERE / "fotmob_featured.json")):
    mid = MKEY[("2025/26", fm["home"], fm["away"])]
    FOTMOB_ID[mid] = fm["fotmob_match_id"]
    for side in ("home", "away"):
        tid = team_id[fm[side]]; sh = fm["sheets"][side]
        SHEETS[(mid, tid)] = dict(formation=sh["formation"], coach=sh["coach"], team_rating=sh["team_rating"], source="fotmob")
        plist = fm["players"][side]
        got = match_names(plist, team_players(mid, tid, played=False), lambda x: x["fotmob_name"], threshold=0.4)
        for i, p in enumerate(plist):
            pid = got.get(i)
            assert pid, ("featured player not found", p["fotmob_name"])
            d = PMS[(mid, pid)]
            d["fotmob_rating"] = p.get("rating"); d["is_player_of_match"] = int(p.get("potm", False))
            if p.get("pos") and p["pos"] != "SUB": d["position"] = p["pos"]
            d["shirt_number"] = p["shirt"]; SRC[(mid, pid)].add("fotmob page")
            set_name(pid, 4, p["fotmob_name"])

# =============================================================================
# 9. Write everything
# =============================================================================
USED = {k[1] for k in PMS}
SEEN_FB, SEEN_US = set(), set()
for pid, p in P.items():
    if pid not in USED:
        continue
    name = p["names"][max(p["names"])] if p["names"] else "Unknown"
    if len(name.split()) == 1:   # 'Thiago' -> 'Igor Thiago' when another source has the fuller common name
        alt = [n for k, n in p["names"].items() if k >= 2 and 2 <= len(n.split()) <= 3 and fold(n)[-1:] == fold(name)]
        if alt: name = alt[0]
    fb = p.get("fb") if p.get("fb") not in SEEN_FB else None; us = p.get("us") if p.get("us") not in SEEN_US else None
    SEEN_FB.add(fb); SEEN_US.add(us)
    cur.execute("INSERT INTO players (player_id, fpl_code, fbref_id, understat_id, name, nationality, date_of_birth, primary_position) VALUES (?,?,?,?,?,?,?,?)",
                (pid, p["code"], fb, us, name, p["nat"], p["dob"], p["pos"]))
for mid, fid in FOTMOB_ID.items():
    cur.execute("UPDATE matches SET fotmob_match_id=? WHERE match_id=?", (fid, mid))

cols = [c[1] for c in db.execute("PRAGMA table_info(player_match_stats)")]
for (mid, pid), d in PMS.items():
    d = dict(d); d["match_id"] = mid; d["player_id"] = pid
    d.setdefault("minutes_played", 0)
    if (d.get("minutes_played") or 0) == 0:
        d["is_starter"] = 0
    d["source"] = "+".join(sorted(SRC[(mid, pid)]))
    keys = [c for c in cols if c in d]
    cur.execute(f"INSERT INTO player_match_stats ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})", [d[k] for k in keys])

tcols = [c[1] for c in db.execute("PRAGMA table_info(team_match_stats)")]
for (mid, tid), d in TMS.items():
    d = {k: v for k, v in d.items() if k in tcols and v is not None}
    d.update(match_id=mid, team_id=tid, period="ALL", source="+".join(sorted(TSRC[(mid, tid)])))
    cur.execute(f"INSERT INTO team_match_stats ({','.join(d)}) VALUES ({','.join('?' * len(d))})", list(d.values()))
for (mid, tid), s in SHEETS.items():
    cur.execute("INSERT INTO match_team_sheets VALUES (?,?,?,?,?,?,?)",
                (mid, tid, int(tid == MINFO[mid]["home"]), s.get("formation"), s.get("coach"), s.get("team_rating"), s["source"]))
ecols = ["match_id", "team_id", "minute", "added_time", "period", "event_type", "player_id", "related_player_id", "detail",
         "home_score_after", "away_score_after", "source"]
for e in sorted(EVENTS, key=lambda e: (e["match_id"], e["minute"], e["added_time"] or 0)):
    cur.execute(f"INSERT INTO match_events ({','.join(ecols)}) VALUES ({','.join('?' * len(ecols))})", [e.get(c) for c in ecols])
scols = list(SHOTS[0].keys())
cur.executemany(f"INSERT INTO shots ({','.join(scols)}) VALUES ({','.join('?' * len(scols))})", [[s[c] for c in scols] for s in SHOTS])
cur.executemany("INSERT OR IGNORE INTO match_momentum VALUES (?,?,?)", MOM)

cur.execute("""INSERT INTO squad_memberships (season_id, team_id, player_id, shirt_number, first_match_date, last_match_date)
               SELECT m.season_id, p.team_id, p.player_id,
                      (SELECT shirt_number FROM player_match_stats x JOIN matches mm USING(match_id)
                       WHERE x.player_id=p.player_id AND x.team_id=p.team_id AND mm.season_id=m.season_id AND shirt_number IS NOT NULL
                       GROUP BY shirt_number ORDER BY COUNT(*) DESC LIMIT 1),
                      MIN(DATE(m.kickoff_utc)), MAX(DATE(m.kickoff_utc))
               FROM player_match_stats p JOIN matches m USING (match_id)
               GROUP BY m.season_id, p.team_id, p.player_id""")

# Standings snapshots (+ cumulative xG for/against)
for sname, sid in season_id.items():
    ms = cur.execute("""SELECT m.round_no, DATE(m.kickoff_utc), m.home_team_id, m.away_team_id, m.home_score, m.away_score,
                               hs.xg, as_.xg
                        FROM matches m
                        LEFT JOIN team_match_stats hs ON hs.match_id=m.match_id AND hs.team_id=m.home_team_id AND hs.period='ALL'
                        LEFT JOIN team_match_stats as_ ON as_.match_id=m.match_id AND as_.team_id=m.away_team_id AND as_.period='ALL'
                        WHERE m.season_id=? AND m.status='finished' ORDER BY m.kickoff_utc""", (sid,)).fetchall()
    teams_in = sorted({m[2] for m in ms} | {m[3] for m in ms})
    for r in range(1, max(m[0] for m in ms) + 1):
        played = [m for m in ms if m[0] <= r]
        asof = max(m[1] for m in played)
        tab = {t: dict(p=0, w=0, d=0, l=0, gf=0, ga=0, xf=0.0, xa=0.0, res=[]) for t in teams_in}
        for _, d, h, a, hs, as_, hx, ax in played:
            for t, gf, ga, xf, xa in ((h, hs, as_, hx, ax), (a, as_, hs, ax, hx)):
                row = tab[t]; row["p"] += 1; row["gf"] += gf; row["ga"] += ga
                row["xf"] += xf or 0; row["xa"] += xa or 0
                res = "W" if gf > ga else "D" if gf == ga else "L"; row[res.lower()] += 1; row["res"].append(res)
        for tname, pts, when in DEDUCTIONS.get(sname, []):
            if asof >= when: tab[team_id[tname]]["ded"] = tab[team_id[tname]].get("ded", 0) + pts
        order = sorted(teams_in, key=lambda t: (-(3 * tab[t]["w"] + tab[t]["d"] - tab[t].get("ded", 0)),
                                                -(tab[t]["gf"] - tab[t]["ga"]), -tab[t]["gf"]))
        for pos, t in enumerate(order, 1):
            x = tab[t]
            cur.execute("""INSERT INTO standings (season_id, after_round, team_id, position, played, won, drawn, lost, goals_for,
                           goals_against, goal_diff, points, form, xg_for, xg_against) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (sid, r, t, pos, x["p"], x["w"], x["d"], x["l"], x["gf"], x["ga"], x["gf"] - x["ga"],
                         3 * x["w"] + x["d"] - x.get("ded", 0), "".join(x["res"][-5:]), round(x["xf"], 2), round(x["xa"], 2)))

db.commit()
print("built", OUT)
for t in ["players", "squad_memberships", "matches", "match_team_sheets", "team_match_stats", "player_match_stats",
          "match_events", "shots", "match_momentum", "standings"]:
    print(f"  {t:22s} {cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:>7}")
(HERE / "build_log.txt").write_text("\n".join(LOG))
