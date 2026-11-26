"""
Add La Liga, Serie A and the UEFA Champions League (2023/24 - 2025/26) to football.db,
in the same tables as the Premier League. Run after build_db.py.

  python3 -I build_more.py <openfootball football.json> <download dir> <football.db>

Download dir:
  fdco/        github.com/datasets/football-datasets       (football-data.co.uk results + team stats)
  fbref_esp/, fbref_ita/                                    (worldfootballR_data FBref player match stats)
  understat2/  La_liga.rds, Serie_A.rds                     (worldfootballR_data Understat shots)
  ucl/         github.com/openfootball/champions-league     (UCL results, stages, ET, penalties)
  elo/, fpl/   FPL-Elo-Insights + FPL ids                   (UCL 2025/26 matches of English clubs)
"""
import json, re, sqlite3, sys, glob, unicodedata, collections
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import pandas as pd
import pyreadr

OF, DL, DBP = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
HERE = Path(__file__).parent
db = sqlite3.connect(DBP)
cur = db.cursor()
LOG = []
def log(*a):
    m = " ".join(str(x) for x in a); LOG.append(m); print(m)

# ----------------------------------------------------------------------------- helpers
def fold(s):
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))
    s = s.replace("ø", "o").replace("Ø", "O").replace("ł", "l").replace("ß", "ss").replace("ı", "i")
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()


def name_sim(a, b):
    ta, tb = fold(a), fold(b)
    if not ta or not tb: return 0
    for x, y in ((ta, tb), (tb, ta)):   # 'E. Eze' vs 'Eberechi Eze', 'R. K. Muani' vs 'Randal Kolo Muani'
        if len(x) >= 2 and all(len(t) == 1 for t in x[:-1]) and len(y) >= 2 and x[-1] == y[-1] and y[0].startswith(x[0]):
            return 0.9
    if len(ta) >= 2 and len(tb) >= 2 and ta[0][:3] == tb[0][:3] and (ta[-1] in tb[1:] or tb[-1] in ta[1:]) and len(ta[-1]) >= 4:
        return 0.75                     # 'Isi Palazón' vs 'Isaac Palazón Camacho'
    sa, sb = set(ta), set(tb)
    if ta == tb: return 1.0
    jac = len(sa & sb) / len(sa | sb); sub = 1.0 if (sa <= sb or sb <= sa) else 0
    last = 1.0 if ta[-1] == tb[-1] else 0
    return 0.35 * jac + 0.25 * sub + 0.2 * last + 0.2 * SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()


def num(v):
    if v is None: return None
    if isinstance(v, str):
        v = v.strip()
        if v == "": return None
        try: v = float(v)
        except ValueError: return None
    try:
        if pd.isna(v): return None
    except (TypeError, ValueError): pass
    f = float(v)
    return int(f) if f.is_integer() else round(f, 4)


def rd(path):
    return list(pyreadr.read_r(str(path)).values())[0]


def fbid(href):
    m = re.search(r"/players/([0-9a-f]{8})", str(href)); return m.group(1) if m else None


def put(d, col, val, overwrite=True):
    v = num(val) if not (isinstance(val, str) and not re.match(r"^-?[\d.]+$", val.strip() or "x")) else None
    if isinstance(val, str) and v is None and val.strip() and not re.match(r"^-?[\d.]+$", val.strip()):
        v = val.strip()
    if v is None: return
    if overwrite or d.get(col) is None: d[col] = v


def total_from_pct(won, pct):
    won, pct = num(won), num(pct)
    if won is None or pct is None or pct == 0: return None
    return int(round(won * 100.0 / pct))


def to_utc(date, time, tz):
    dt = datetime.fromisoformat(f"{date}T{time or '00:00'}").replace(tzinfo=ZoneInfo(tz))
    return dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M")


# ----------------------------------------------------------------------------- teams
STOP = {"fc", "cf", "ac", "acf", "ssc", "ss", "us", "ud", "cd", "rcd", "rc", "ca", "sd", "sc", "bc", "cfc", "calcio", "club",
        "de", "del", "futbol", "balompie", "afc", "as", "1907", "1909", "1913", "1919", "1906"}
def tkey(n): return " ".join(t for t in fold(n) if t not in STOP)

SPAIN = [("Alavés", "Alavés", "ALA", ["alaves", "deportivo alaves"], ("#1E4FA8", "#7C7C7C")),
         ("Almería", "Almería", "ALM", ["almeria"], ("#D1202F", "#2B5BA8")),
         ("Athletic Club", "Athletic", "ATH", ["athletic club", "ath bilbao", "athletic bilbao"], ("#E2231A", "#2A2A2A")),
         ("Atlético Madrid", "Atlético", "ATM", ["atletico madrid", "ath madrid", "atletico de madrid", "club atletico de madrid"], ("#CB3524", "#272E61")),
         ("Barcelona", "Barcelona", "BAR", ["barcelona"], ("#A50044", "#004D98")),
         ("Real Betis", "Betis", "BET", ["betis", "real betis", "real betis balompie"], ("#0BB363", "#7C7C7C")),
         ("Cádiz", "Cádiz", "CAD", ["cadiz"], ("#E0B400", "#1F4FA8")),
         ("Celta Vigo", "Celta", "CEL", ["celta", "celta vigo", "rc celta de vigo"], ("#6AAEDC", "#C8102E")),
         ("Elche", "Elche", "ELC", ["elche"], ("#0B7A4B", "#7C7C7C")),
         ("Espanyol", "Espanyol", "ESP", ["espanyol", "espanol", "espanyol barcelona", "rcd espanyol de barcelona"], ("#1E5BC6", "#7C7C7C")),
         ("Getafe", "Getafe", "GET", ["getafe"], ("#1C4FA0", "#D1202F")),
         ("Girona", "Girona", "GIR", ["girona"], ("#D1202F", "#7C7C7C")),
         ("Granada", "Granada", "GRA", ["granada"], ("#C8102E", "#1F4FA8")),
         ("Las Palmas", "Las Palmas", "LPA", ["las palmas"], ("#E0B400", "#1F4FA8")),
         ("Leganés", "Leganés", "LEG", ["leganes"], ("#1F4FA8", "#7C7C7C")),
         ("Levante", "Levante", "LEV", ["levante"], ("#8A1F4C", "#1F4FA8")),
         ("Mallorca", "Mallorca", "MLL", ["mallorca"], ("#C8102E", "#E0B400")),
         ("Osasuna", "Osasuna", "OSA", ["osasuna"], ("#C8102E", "#1F2F6B")),
         ("Real Oviedo", "Oviedo", "OVI", ["oviedo", "real oviedo"], ("#1F4FA8", "#7C7C7C")),
         ("Rayo Vallecano", "Rayo", "RAY", ["vallecano", "rayo vallecano", "rayo vallecano madrid"], ("#D1202F", "#6E6E6E")),
         ("Real Madrid", "Real Madrid", "RMA", ["real madrid"], ("#8C7AE6", "#E0B400")),
         ("Real Sociedad", "Real Sociedad", "RSO", ["sociedad", "real sociedad"], ("#1F5FB4", "#7C7C7C")),
         ("Sevilla", "Sevilla", "SEV", ["sevilla"], ("#D1202F", "#7C7C7C")),
         ("Valencia", "Valencia", "VAL", ["valencia"], ("#E87A00", "#4A4A4A")),
         ("Real Valladolid", "Valladolid", "VLL", ["valladolid", "real valladolid"], ("#6B2C91", "#7C7C7C")),
         ("Villarreal", "Villarreal", "VIL", ["villarreal"], ("#E0B400", "#1F4FA8"))]
ITALY = [("AC Milan", "Milan", "MIL", ["milan", "ac milan"], ("#C8102E", "#2A2A2A")),
         ("Atalanta", "Atalanta", "ATA", ["atalanta"], ("#1E5BC6", "#2A2A2A")),
         ("Bologna", "Bologna", "BOL", ["bologna"], ("#A21C26", "#1A2D5A")),
         ("Cagliari", "Cagliari", "CAG", ["cagliari"], ("#A21C26", "#1A2D5A")),
         ("Como", "Como", "COM", ["como"], ("#1E5BC6", "#7C7C7C")),
         ("Cremonese", "Cremonese", "CRE", ["cremonese"], ("#B3122E", "#7C7C7C")),
         ("Empoli", "Empoli", "EMP", ["empoli"], ("#1E5BC6", "#7C7C7C")),
         ("Fiorentina", "Fiorentina", "FIO", ["fiorentina"], ("#6B2C91", "#7C7C7C")),
         ("Frosinone", "Frosinone", "FRO", ["frosinone"], ("#E0B400", "#1F4FA8")),
         ("Genoa", "Genoa", "GEN", ["genoa"], ("#A21C26", "#1A2D5A")),
         ("Hellas Verona", "Verona", "VER", ["verona", "hellas verona"], ("#1F3F8F", "#E0B400")),
         ("Inter", "Inter", "INT", ["inter", "internazionale", "internazionale milano", "inter milan"], ("#0B4EA2", "#2A2A2A")),
         ("Juventus", "Juventus", "JUV", ["juventus"], ("#4A4A4A", "#C9A227")),
         ("Lazio", "Lazio", "LAZ", ["lazio"], ("#6AAEDC", "#1A2D5A")),
         ("Lecce", "Lecce", "LEC", ["lecce"], ("#E0B400", "#C8102E")),
         ("Monza", "Monza", "MON", ["monza"], ("#C8102E", "#7C7C7C")),
         ("Napoli", "Napoli", "NAP", ["napoli"], ("#12A0D7", "#1A2D5A")),
         ("Parma", "Parma", "PAR", ["parma"], ("#E0B400", "#1F4FA8")),
         ("Pisa", "Pisa", "PIS", ["pisa"], ("#1A2D5A", "#7C7C7C")),
         ("Roma", "Roma", "ROM", ["roma"], ("#8E1F2F", "#E0A000")),
         ("Salernitana", "Salernitana", "SAL", ["salernitana"], ("#7A1F2B", "#7C7C7C")),
         ("Sassuolo", "Sassuolo", "SAS", ["sassuolo"], ("#00A651", "#2A2A2A")),
         ("Torino", "Torino", "TOR", ["torino"], ("#7A1F2B", "#7C7C7C")),
         ("Udinese", "Udinese", "UDI", ["udinese"], ("#4A4A4A", "#7C7C7C")),
         ("Venezia", "Venezia", "VEN", ["venezia"], ("#E87A00", "#0B6B3A"))]
TEAM_COLORS = {}
LEAGUES = {
    "La Liga": dict(cid=2, fotmob=87, country="Spain", teams=SPAIN, of="es.1", fb="fbref_esp", us="La_liga", fd="la-liga", tz="Europe/Madrid"),
    "Serie A": dict(cid=3, fotmob=55, country="Italy", teams=ITALY, of="it.1", fb="fbref_ita", us="Serie_A", fd="serie-a", tz="Europe/Rome"),
}
ALIAS = {lg: {} for lg in LEAGUES}
for lg, cfg in LEAGUES.items():
    for canon, short, code, als, col in cfg["teams"]:
        TEAM_COLORS[canon] = col
        for a in als + [canon]:
            ALIAS[lg][tkey(a)] = canon
META = {t[0]: t for lg in LEAGUES.values() for t in lg["teams"]}


def resolve(lg, name):
    k = tkey(name)
    if k in ALIAS[lg]: return ALIAS[lg][k]
    ks = set(k.split())
    c = {v for ak, v in ALIAS[lg].items() if ks and (ks <= set(ak.split()) or set(ak.split()) <= ks)}
    if len(c) == 1: return c.pop()
    raise KeyError(f"{lg}: cannot resolve team {name!r} (key {k!r}, candidates {c})")


TEAM = {name: tid for tid, name in cur.execute("SELECT team_id, name FROM teams")}


def team_id(canon, country, short=None, code=None):
    if canon not in TEAM:
        m = META.get(canon)
        cur.execute("INSERT INTO teams (name, short_name, code, country) VALUES (?,?,?,?)",
                    (canon, short or (m[1] if m else canon), code or (m[2] if m else canon[:3].upper()), country))
        TEAM[canon] = cur.lastrowid
    return TEAM[canon]


# ----------------------------------------------------------------------------- players
PL_FB = {fb: pid for pid, fb in cur.execute("SELECT player_id, fbref_id FROM players WHERE fbref_id IS NOT NULL")}
PL_US = {us: pid for pid, us in cur.execute("SELECT player_id, understat_id FROM players WHERE understat_id IS NOT NULL")}
PL_FPL = {c: pid for pid, c in cur.execute("SELECT player_id, fpl_code FROM players WHERE fpl_code IS NOT NULL")}
PNAME = {pid: [n] for pid, n in cur.execute("SELECT player_id, name FROM players")}
NEWP = {}              # pid -> dict(name, fb, us, nat, pos)
NEXT = [max(PNAME) + 1]
BYNAME_TEAM = {}       # (team_id, folded name) -> pid  (players known only by name)


def new_player(name, fb=None, us=None, nat=None):
    pid = NEXT[0]; NEXT[0] += 1
    NEWP[pid] = dict(name=name, fb=fb, us=us, nat=nat, pos=None); PNAME[pid] = [name]
    if fb: PL_FB[fb] = pid
    if us: PL_US[us] = pid
    return pid


def note_ids(pid, fb=None, us=None, name=None):
    if fb and fb not in PL_FB: PL_FB[fb] = pid
    if us and us not in PL_US: PL_US[us] = pid
    if pid in NEWP:
        if fb and not NEWP[pid]["fb"]: NEWP[pid]["fb"] = fb
        if us and not NEWP[pid]["us"]: NEWP[pid]["us"] = us
    if name and name not in PNAME[pid]: PNAME[pid].append(name)


def match_names(rows, cands, name_of, min_of=None, cand_min=None, threshold=0.5):
    pairs = []
    for i, r in enumerate(rows):
        for pid in cands:
            s = max(name_sim(name_of(r), n) for n in PNAME[pid])
            if min_of and cand_min:
                a, b = min_of(r), cand_min.get(pid)
                if a is not None and b is not None: s += 0.3 if abs(a - b) <= 1 else (0.1 if abs(a - b) <= 5 else -0.1)
            pairs.append((s, i, pid))
    pairs.sort(key=lambda x: -x[0])
    out, used = {}, set()
    for s, i, pid in pairs:
        if s < threshold or i in out or pid in used: continue
        out[i] = pid; used.add(pid)
    return out


# ----------------------------------------------------------------------------- containers
PMS, SRC, BYM = {}, collections.defaultdict(set), collections.defaultdict(set)
TMS, TSRC, SHEETS = {}, collections.defaultdict(set), {}
EVENTS, SHOTS, MOM, MINFO = [], [], [], {}


def pm(mid, pid, tid, src):
    k = (mid, pid)
    if k not in PMS:
        PMS[k] = dict(team_id=tid, is_starter=None, is_captain=0); BYM[mid].add(pid)
    SRC[k].add(src); return PMS[k]


def tm(mid, tid, src):
    TMS.setdefault((mid, tid), {}); TSRC[(mid, tid)].add(src); return TMS[(mid, tid)]


def team_players(mid, tid, played=True):
    return [p for p in BYM[mid] if PMS[(mid, p)]["team_id"] == tid and (not played or (PMS[(mid, p)].get("minutes_played") or 0) > 0)]


EVBYM = collections.defaultdict(list)


def ev(mid, tid, minute, added, etype, p=None, rp=None, detail=None, src=None, hs=None, as_=None):
    EVBYM[mid].append((etype, p))
    EVENTS.append(dict(match_id=mid, team_id=tid, minute=minute, added_time=added, event_type=etype, player_id=p,
                       related_player_id=rp, detail=detail, source=src, home_score_after=hs, away_score_after=as_))


def insert_match(sid, rnd, ko, h, a, hs, as_, hth, hta, src, stage=None, leg=None, went=None, hp=None, ap=None):
    cur.execute("""INSERT INTO matches (season_id, round_no, stage, leg, kickoff_utc, home_team_id, away_team_id, status, home_score,
                   away_score, ht_home_score, ht_away_score, went_to, home_pens, away_pens, source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, rnd, stage, leg, ko, h, a, "finished" if hs is not None else "scheduled", hs, as_, hth, hta, went, hp, ap, src))
    mid = cur.lastrowid
    MINFO[mid] = dict(sid=sid, home=h, away=a, hs=hs, as_=as_, ko=ko)
    return mid


SEASONS = [("2023/24", "2023-24", 2024, 2023, "2324"), ("2024/25", "2024-25", 2025, 2024, "2425"), ("2025/26", "2025-26", 2026, 2025, "2526")]
for lg, cfg in LEAGUES.items():
    cur.execute("INSERT INTO competitions VALUES (?,?,?,?, 'league', 1)", (cfg["cid"], cfg["fotmob"], lg, cfg["country"]))
cur.execute("INSERT INTO competitions VALUES (4, 42, 'Champions League', 'Europe', 'cup', NULL)")

FBCOLS = {
    "summary": [("Gls", "goals"), ("Ast", "assists"), ("PK", "penalty_goals"), ("Sh", "shots_total"), ("SoT", "shots_on_target"),
                ("Touches", "touches"), ("xG_Expected", "xg"), ("npxG_Expected", "npxg"), ("Cmp_Passes", "passes_accurate"),
                ("Att_Passes", "passes_total"), ("Att_Take_Ons", "dribbles_attempted"), ("Succ_Take_Ons", "dribbles_succeeded")],
    "passing": [("Cmp_Total", "passes_accurate"), ("Att_Total", "passes_total"), ("Ast", "assists"), ("KP", "chances_created"),
                ("Final_Third", "passes_final_third"), ("Cmp_Long", "long_balls_accurate"), ("Att_Long", "long_balls_total"), ("xA", "xa")],
    "passing_types": [("CK_Pass_Types", "_corners"), ("TI_Pass_Types", "_throw_ins"), ("Crs_Pass_Types", "crosses_total")],
    "defense": [("Tkl_Tackles", "tackles_total"), ("TklW_Tackles", "tackles_won"), ("Int", "interceptions"), ("Clr", "clearances"),
                ("Sh_Blocks", "blocks"), ("Lost_Challenges", "dribbled_past")],
    "possession": [("Touches_Touches", "touches"), ("Att Pen_Touches", "touches_opp_box"), ("Att_Take_Ons", "dribbles_attempted"),
                   ("Succ_Take_Ons", "dribbles_succeeded"), ("Dis_Carries", "dispossessed")],
    "misc": [("CrdY", "yellow_cards"), ("CrdR", "red_cards"), ("OG", "own_goals"), ("Fls", "fouls_committed"), ("Fld", "was_fouled"),
             ("Off", "offsides"), ("Recov", "recoveries"), ("Won_Aerial_Duels", "aerial_duels_won"), ("_aerial_total", "aerial_duels_total")],
    "keeper": [("Saves_Shot_Stopping", "saves"), ("GA_Shot_Stopping", "goals_conceded"), ("PSxG_Shot_Stopping", "xgot_faced"),
               ("Stp_Crosses", "high_claims"), ("Player_NumOPA_Sweeper", "sweeper_actions")],
}
OUTC = {"Goal": "goal", "SavedShot": "saved", "MissedShots": "missed", "BlockedShot": "blocked", "ShotOnPost": "woodwork"}
SIT = {"OpenPlay": "open_play", "FromCorner": "corner", "SetPiece": "set_piece", "DirectFreekick": "free_kick", "Penalty": "penalty"}
BODY = {"RightFoot": "right_foot", "LeftFoot": "left_foot", "Head": "header", "OtherBodyPart": "other"}
SEASON_IDS = {}

# =============================================================================
# La Liga + Serie A
# =============================================================================
for lg, cfg in LEAGUES.items():
    FBT = {}
    for t in list(FBCOLS) + ["match_shooting"]:
        f = DL / cfg["fb"] / f"{t}.rds"
        if f.exists() and f.stat().st_size > 1000:
            df = rd(f); df = df[df.Season_End_Year >= 2024].copy()
            df["mcode"] = df.MatchURL.str.extract(r"matches/(\w+)/")[0]
            FBT[t] = df
    US = rd(DL / "understat2" / f"{cfg['us']}.rds"); US = US[US.season >= 2023].copy()
    US["h_a"] = [h if isinstance(h, str) and h in ("h", "a") else ("h" if str(x).lower().startswith("h") else "a") for h, x in zip(US.h_a, US.home_away)]

    for sname, folder, fbyear, usyear, fdcode in SEASONS:
        ofm = json.load(open(OF / folder / f"{cfg['of']}.json"))["matches"]
        fd = pd.read_csv(DL / "fdco" / "datasets" / cfg["fd"] / f"season-{fdcode}.csv")
        dates = sorted(m["date"] for m in ofm)
        cur.execute("INSERT INTO seasons (competition_id, name, start_date, end_date, is_current) VALUES (?,?,?,?,0)", (cfg["cid"], sname, dates[0], dates[-1]))
        sid = cur.lastrowid; SEASON_IDS[(lg, sname)] = sid
        fdx = {}
        for r in fd.to_dict("records"):
            fdx[(resolve(lg, r["HomeTeam"]), resolve(lg, r["AwayTeam"]))] = r
        MK = {}
        mism = 0
        for m in ofm:
            h, a = resolve(lg, m["team1"]), resolve(lg, m["team2"])
            sc = m.get("score"); ft = sc.get("ft") if isinstance(sc, dict) else sc; ht = sc.get("ht") if isinstance(sc, dict) else None
            f = fdx.get((h, a)); src = "openfootball"
            if f is not None:
                if ft and (ft[0], ft[1]) != (int(f["FTHG"]), int(f["FTAG"])): mism += 1
                if not ft: ft = [int(f["FTHG"]), int(f["FTAG"])]; src += "+football-data.co.uk"
                if not ht and num(f.get("HTHG")) is not None: ht = [int(f["HTHG"]), int(f["HTAG"])]
            hid, aid = team_id(h, cfg["country"]), team_id(a, cfg["country"])
            mid = insert_match(sid, int(re.search(r"(\d+)\s*$", m["round"]).group(1)), to_utc(m["date"], m.get("time"), cfg["tz"]),
                               hid, aid, ft[0] if ft else None, ft[1] if ft else None, ht[0] if ht else None, ht[1] if ht else None, src)
            MK[(h, a)] = mid
            if f is not None:
                for tid, pre in ((hid, "H"), (aid, "A")):
                    t = tm(mid, tid, "football-data.co.uk")
                    for c, col in (("S", "total_shots"), ("ST", "shots_on_target"), ("F", "fouls"), ("C", "corners"), ("Y", "yellow_cards"), ("R", "red_cards")):
                        put(t, col, f.get(pre + c))
        log(lg, sname, "matches", len(ofm), "score mismatches openfootball vs football-data:", mism)

        # ---------------- FBref player stats
        fbmatch = {}
        fb_rows = 0
        if "passing" in FBT:
            base = FBT["passing"][FBT["passing"].Season_End_Year == fbyear]
            for (mcode, team), g in base.groupby(["mcode", "Team"]):
                rows = g.to_dict("records"); r0 = rows[0]
                mid = MK[(resolve(lg, r0["Home_Team"]), resolve(lg, r0["Away_Team"]))]; fbmatch[mcode] = mid
                tid = TEAM[resolve(lg, team)]
                form = r0["Home_Formation"] if tid == MINFO[mid]["home"] else r0["Away_Formation"]
                if isinstance(form, str) and form: SHEETS[(mid, tid)] = dict(formation=form.replace("◆", "").strip(), source="fbref")
                for r in rows:
                    f_id = fbid(r["Player_Href"])
                    pid = PL_FB.get(f_id) or new_player(r["Player"], fb=f_id, nat=(r["Nation"].split()[-1] if isinstance(r["Nation"], str) and r["Nation"] else None))
                    note_ids(pid, fb=f_id, name=r["Player"])
                    if pid in NEWP and isinstance(r["Nation"], str) and r["Nation"]: NEWP[pid]["nat"] = r["Nation"].split()[-1]
                    d = pm(mid, pid, tid, "fbref"); fb_rows += 1
                    put(d, "minutes_played", r["Min"]); put(d, "shirt_number", r["Player_Num"])
                    if isinstance(r["Pos"], str): d["position"] = r["Pos"].split(",")[0]
            for t, cols in FBCOLS.items():
                if t not in FBT: continue
                df = FBT[t][FBT[t].Season_End_Year == fbyear].copy()
                if t == "misc":
                    df["_aerial_total"] = pd.to_numeric(df.Won_Aerial_Duels, errors="coerce") + pd.to_numeric(df.Lost_Aerial_Duels, errors="coerce")
                for rec in df.to_dict("records"):
                    mid = fbmatch.get(rec["mcode"]); pid = PL_FB.get(fbid(rec["Player_Href"]))
                    if mid is None or pid is None or (mid, pid) not in PMS: continue
                    d = PMS[(mid, pid)]
                    for s_, col in cols: put(d, col, rec.get(s_), overwrite=(t != "summary"))
                    if t == "summary" and num(rec.get("PKatt")) is not None and num(rec.get("PK")) is not None:
                        d["penalties_missed"] = num(rec["PKatt"]) - num(rec["PK"])
                    if t == "keeper" and num(rec.get("PSxG_Shot_Stopping")) is not None and num(rec.get("GA_Shot_Stopping")) is not None:
                        d["goals_prevented"] = round(num(rec["PSxG_Shot_Stopping"]) - num(rec["GA_Shot_Stopping"]), 2)
            if "match_shooting" in FBT:
                sh = FBT["match_shooting"]; sh = sh[sh.Season_End_Year == fbyear].copy()
                for c_ in ("xG", "Distance"): sh[c_ + "_n"] = pd.to_numeric(sh[c_], errors="coerce")
                sh["Minute_s"] = sh.Minute.astype(str).str.strip()
                n0 = len(sh); sh = sh.drop_duplicates(subset=["mcode", "Squad", "Minute_s", "Player", "xG_n", "Outcome", "Distance_n"])
                log(lg, sname, "FBref shot rows:", n0, "after removing duplicates:", len(sh))
                agg = collections.defaultdict(lambda: collections.Counter())
                for rec in sh.to_dict("records"):
                    mid = fbmatch.get(rec["mcode"]); pid = PL_FB.get(fbid(rec["Player_Href"]))
                    if mid is None or pid is None or (mid, pid) not in PMS: continue
                    pen = "(pen)" in rec["Player"]; on = rec["Outcome"] in ("Goal", "Saved"); a_ = agg[(mid, pid)]
                    a_["shots_total"] += 1; a_["shots_on_target"] += on; a_["xg"] += num(rec["xG"]) or 0
                    a_["npxg"] += 0 if pen else (num(rec["xG"]) or 0); a_["xgot"] += (num(rec["PSxG"]) or 0) if on else 0
                    a_["goals"] += rec["Outcome"] == "Goal"; a_["penalty_goals"] += pen and rec["Outcome"] == "Goal"
                for (mid, pid), a_ in agg.items():
                    d = PMS[(mid, pid)]
                    for c, v in a_.items(): put(d, c, round(v, 3) if isinstance(v, float) else v, overwrite=False)
                for mid in set(fbmatch.values()):
                    for p in BYM[mid]:
                        d = PMS[(mid, p)]
                        for c in ("shots_total", "shots_on_target", "goals", "penalty_goals"): d.setdefault(c, 0)
            # team sums for FBref-covered matches
            meta = base.drop_duplicates("mcode").to_dict("records")
            for rec in meta:
                mid = fbmatch[rec["mcode"]]; sums = {}
                for side, xg in ((MINFO[mid]["home"], rec["Home_xG"]), (MINFO[mid]["away"], rec["Away_xG"])):
                    rows_ = [PMS[(mid, p)] for p in BYM[mid] if PMS[(mid, p)]["team_id"] == side]
                    t = tm(mid, side, "fbref (sum of players)")
                    for c, col in (("passes_total", "passes_total"), ("passes_accurate", "passes_accurate"), ("long_balls_accurate", "long_balls_accurate"),
                                   ("long_balls_total", "long_balls_total"), ("crosses_total", "crosses_total"), ("touches_opp_box", "touches_opp_box"),
                                   ("offsides", "offsides"), ("tackles_won", "tackles_won"), ("interceptions", "interceptions"), ("blocks", "blocks"),
                                   ("clearances", "clearances"), ("saves", "keeper_saves"), ("aerial_duels_won", "aerial_duels_won"),
                                   ("aerial_duels_total", "aerial_duels_total"), ("dribbles_succeeded", "dribbles_succeeded"),
                                   ("dribbles_attempted", "dribbles_attempted"), ("_throw_ins", "throw_ins")):
                        vals = [d.get(c) for d in rows_ if isinstance(d.get(c), (int, float))]
                        if vals: t[col] = int(sum(vals))
                    # one xG basis per team row: FBref player xG (summary or shot table) when present, else FBref's match xG
                    fb_xg = (("summary" in FBT and (FBT["summary"].Season_End_Year == fbyear).any())
                             or ("match_shooting" in FBT and (FBT["match_shooting"].Season_End_Year == fbyear).any()))
                    # team xG = FBref's published match xG; npxG = that minus the players' penalty xG
                    put(t, "xg", xg)
                    if t.get("xg") is None and fb_xg: t["xg"] = round(sum(d.get("xg") or 0 for d in rows_), 2)
                    if fb_xg and t.get("xg") is not None and any("npxg" in d for d in rows_):
                        pen = sum(d.get("xg") or 0 for d in rows_) - sum(d.get("npxg") or 0 for d in rows_)
                        t["npxg"] = round(max(t["xg"] - pen, 0), 2)
                    if "match_shooting" in FBT and (FBT["match_shooting"].Season_End_Year == fbyear).any():
                        t["xgot"] = round(sum(d.get("xgot") or 0 for d in rows_), 2)
                    sums[side] = t.get("passes_total") or 0
                tot = sum(sums.values())
                if tot:
                    for side, v in sums.items(): TMS[(mid, side)]["possession_pct"] = round(100.0 * v / tot)
        for d in PMS.values():
            d.pop("_corners", None); d.pop("_throw_ins", None)
        log(lg, sname, "FBref matches", len(fbmatch), "player rows", fb_rows)

        # ---------------- Understat: shots, goals timeline, shots/xG for rows FBref left empty
        u = US[US.season == usyear]
        ok = bad = 0
        # pass 1: name matches, and co-occurrence of unmatched Understat ids with unmatched FBref players
        PASS1, CO, TOT = {}, collections.defaultdict(collections.Counter), collections.Counter()
        name2uid = {}
        for (home, away), g in u.groupby(["home_team", "away_team"]):
            mid = MK[(resolve(lg, home), resolve(lg, away))]
            for sc, tid in (("h", MINFO[mid]["home"]), ("a", MINFO[mid]["away"])):
                rows = g[g.h_a == sc].to_dict("records")
                for r in rows: name2uid[(tid, r["player"])] = num(r["player_id"])
                names = sorted({r["player"] for r in rows} | {r["player_assisted"] for r in rows if isinstance(r["player_assisted"], str)})
                cands = team_players(mid, tid)
                got = match_names(names, cands, lambda x: x, threshold=0.4) if cands else {}
                PASS1[(mid, tid)] = (names, got)
                free = set(cands) - set(got.values())
                for i, n in enumerate(names):
                    uid = name2uid.get((tid, n))
                    if i not in got and uid and uid not in PL_US and free:
                        TOT[uid] += 1
                        for f_ in free: CO[uid][f_] += 1
        CO_MAP = {}
        for uid, cnt in CO.items():
            (best, c1), *rest = cnt.most_common(2) + [(None, 0)]
            c2 = rest[0][1] if rest else 0
            if c1 >= 2 and c1 >= 0.6 * TOT[uid] and c1 > c2: CO_MAP[uid] = best
        log(lg, sname, "Understat players linked to FBref players by co-occurrence:", len(CO_MAP))
        for (home, away), g in u.groupby(["home_team", "away_team"]):
            mid = MK[(resolve(lg, home), resolve(lg, away))]
            sides = {"h": MINFO[mid]["home"], "a": MINFO[mid]["away"]}
            pmap = {}
            for sc, tid in sides.items():
                rows = g[g.h_a == sc].to_dict("records")
                usid = {r["player"]: num(r["player_id"]) for r in rows}
                names, got = PASS1[(mid, tid)]
                for i, n in enumerate(names):
                    pid = got.get(i)
                    if pid is None and name2uid.get((tid, n)) in CO_MAP: pid = CO_MAP[name2uid[(tid, n)]]
                    if pid is None:
                        uid = usid.get(n)
                        pid = (PL_US.get(uid) if uid else None) or BYNAME_TEAM.get((tid, " ".join(fold(n))))
                        if pid is None:
                            pid = new_player(n, us=uid); BYNAME_TEAM[(tid, " ".join(fold(n)))] = pid
                    note_ids(pid, us=usid.get(n), name=n)
                    pmap[(tid, n)] = pid
            goals = []
            agg = collections.defaultdict(collections.Counter)
            for r in g.sort_values(["minute", "id"]).to_dict("records"):
                tid = sides[r["h_a"]]; other = sides["a" if r["h_a"] == "h" else "h"]
                mi = int(r["minute"]); add = None
                if mi > 90: mi, add = 90, mi - 90
                if r["result"] == "OwnGoal":
                    best = {}
                    for t_ in (tid, other):
                        for c_ in team_players(mid, t_):
                            s_ = max(name_sim(r["player"], n) for n in PNAME[c_])
                            if s_ > best.get("s", 0.39): best = dict(s=s_, team=t_, pid=c_)
                    ogp = best.get("pid")
                    goals.append((mi, add, "own_goal", (other if best.get("team") == tid else tid) if ogp else tid, ogp, None))
                    continue
                pid = pmap.get((tid, r["player"]))
                if r["result"] == "Goal":
                    goals.append((mi, add, "penalty_goal" if r["situation"] == "Penalty" else "goal", tid, pid,
                                  pmap.get((tid, r["player_assisted"])) if isinstance(r["player_assisted"], str) else None))
                a_ = agg[pid]; a_["shots_total"] += 1; a_["shots_on_target"] += r["result"] in ("Goal", "SavedShot"); a_["xg"] += num(r["xG"]) or 0
                a_["goals"] += r["result"] == "Goal"; a_["penalty_goals"] += r["result"] == "Goal" and r["situation"] == "Penalty"
                a_["npxg"] += 0 if r["situation"] == "Penalty" else (num(r["xG"]) or 0)
                SHOTS.append(dict(match_id=mid, team_id=tid, player_id=pid, minute=mi, added_time=add, period="1H" if mi <= 45 else "2H",
                                  x=round(num(r["X"]) * 105, 1), y=round(num(r["Y"]) * 68, 1), xg=round(num(r["xG"]), 4), xgot=None,
                                  outcome=OUTC[r["result"]], body_part=BODY.get(r["shotType"]), situation=SIT.get(r["situation"]),
                                  is_own_goal=0, goal_mouth_y=None, goal_mouth_z=None, source="understat"))
            # player rows FBref already has: fill shots/xG/goals only where FBref had none (ESP 2023/24)
            for pid, a_ in agg.items():
                if (mid, pid) in PMS:
                    d = PMS[(mid, pid)]; SRC[(mid, pid)].add("understat")
                    for c, v in a_.items(): put(d, c, round(v, 3) if isinstance(v, float) else v, overwrite=False)
            if (mid, None) in PMS: pass
            if mid in {v for v in fbmatch.values()}:
                for p in BYM[mid]:
                    d = PMS[(mid, p)]
                    for c in ("shots_total", "shots_on_target", "goals", "penalty_goals"): d.setdefault(c, 0)
                    d.setdefault("xg", 0); d.setdefault("npxg", 0)
            # own goals: benefiting side decided by the result (Understat's side flag is not consistent)
            ogs = [i for i, x in enumerate(goals) if x[2] == "own_goal"]
            if ogs:
                reg_h = sum(1 for x in goals if x[2] != "own_goal" and x[3] == sides["h"]); reg_a = sum(1 for x in goals if x[2] != "own_goal" and x[3] == sides["a"])
                need_h, need_a = MINFO[mid]["hs"] - reg_h, MINFO[mid]["as_"] - reg_a
                if need_h + need_a == len(ogs) and min(need_h, need_a) >= 0 and (need_h == 0 or need_a == 0):
                    ben = sides["h"] if need_h else sides["a"]; conc = sides["a"] if ben == sides["h"] else sides["h"]
                    for i in ogs:
                        mi, add, et, _, ogp, _ = goals[i]
                        if ogp is None or PMS.get((mid, ogp), {}).get("team_id") not in (None, conc):
                            name = g.sort_values(["minute", "id"]).to_dict("records")
                            ogp = None
                        goals[i] = (mi, add, et, ben, ogp, None)
            hs = as_ = 0; tl = []
            for mi, add, et, tid, p, a in goals:
                if tid == MINFO[mid]["home"]: hs += 1
                else: as_ += 1
                tl.append((mid, tid, mi, add, et, p, a, hs, as_))
            if (hs, as_) == (MINFO[mid]["hs"], MINFO[mid]["as_"]):
                for x in tl: ev(x[0], x[1], x[2], x[3], x[4], x[5], x[6], src="understat", hs=x[7], as_=x[8])
            if (hs, as_) == (MINFO[mid]["hs"], MINFO[mid]["as_"]): ok += 1
            else:
                bad += 1
                log("   goal timeline mismatch:", home, "v", away, "understat", (hs, as_), "result", (MINFO[mid]["hs"], MINFO[mid]["as_"]),
                    "fbref rows:", bool(team_players(mid, sides["h"])), "own goals:", sum(1 for x in goals if x[2] == "own_goal"))
            # team xG from Understat where FBref has none
            for tid in sides.values():
                t = tm(mid, tid, "understat xG") if TMS.get((mid, tid), {}).get("xg") is None else TMS[(mid, tid)]
                if t.get("xg") is None:
                    t["xg"] = round(sum(num(r["xG"]) or 0 for r in g.to_dict("records") if sides[r["h_a"]] == tid and r["result"] != "OwnGoal"), 2)
        log(lg, sname, "Understat matches", u.groupby(["home_team", "away_team"]).ngroups, "goal timelines matching score:", ok, "mismatch:", bad)
        # player goals / penalties / own goals from the reconciled timeline (FBref own-goal data is incomplete)
        fixed = 0
        for mid in set(fbmatch.values()):
            gl = [(t_, p_) for t_, p_ in EVBYM.get(mid, []) if t_ in ("goal", "penalty_goal", "own_goal")]
            if len(gl) != MINFO[mid]["hs"] + MINFO[mid]["as_"] or any(p_ is None or (mid, p_) not in PMS for _, p_ in gl): continue
            for p_ in BYM[mid]:
                d = PMS[(mid, p_)]
                if (d.get("minutes_played") or 0) > 0:
                    d["goals"] = sum(1 for t_, q in gl if q == p_ and t_ != "own_goal")
                    d["penalty_goals"] = sum(1 for t_, q in gl if q == p_ and t_ == "penalty_goal")
                    d["own_goals"] = sum(1 for t_, q in gl if q == p_ and t_ == "own_goal")
            fixed += 1
        log(lg, sname, "player goals taken from the reconciled timeline:", fixed, "of", len(set(fbmatch.values())))

# =============================================================================
# Champions League (openfootball/champions-league)
# =============================================================================
CC = {"ENG": "England", "ESP": "Spain", "ITA": "Italy", "GER": "Germany", "FRA": "France", "POR": "Portugal", "NED": "Netherlands",
      "BEL": "Belgium", "SCO": "Scotland", "AUT": "Austria", "SUI": "Switzerland", "SRB": "Serbia", "UKR": "Ukraine", "TUR": "Türkiye",
      "DEN": "Denmark", "CZE": "Czechia", "CRO": "Croatia", "SVK": "Slovakia", "NOR": "Norway", "AZE": "Azerbaijan", "KAZ": "Kazakhstan",
      "CYP": "Cyprus", "GRE": "Greece", "MCO": "Monaco", "ISR": "Israel", "HUN": "Hungary", "POL": "Poland", "SWE": "Sweden"}
UCL_NAMES = {"FC Bayern München": "Bayern München", "Paris Saint-Germain FC": "Paris Saint-Germain", "Sport Lisboa e Benfica": "Benfica",
             "Sporting Clube de Portugal": "Sporting CP", "PAE Olympiakos SFP": "Olympiacos", "Royale Union Saint-Gilloise": "Union Saint-Gilloise",
             "Sporting Clube de Braga": "Braga", "FK Crvena Zvezda": "Crvena Zvezda", "FC Red Bull Salzburg": "RB Salzburg",
             "Bayer 04 Leverkusen": "Bayer Leverkusen", "BSC Young Boys": "Young Boys", "Feyenoord Rotterdam": "Feyenoord",
             "Racing Club de Lens": "Lens", "Olympique de Marseille": "Marseille", "Stade Brestois 29": "Brest", "LOSC Lille": "Lille",
             "AS Monaco FC": "Monaco", "GNK Dinamo Zagreb": "Dinamo Zagreb", "ŠK Slovan Bratislava": "Slovan Bratislava",
             "AC Sparta Praha": "Sparta Praha", "SK Slavia Praha": "Slavia Praha", "Qarabağ Ağdam FK": "Qarabağ", "FK Bodø/Glimt": "Bodø/Glimt",
             "SK Sturm Graz": "Sturm Graz", "1. FC Union Berlin": "Union Berlin", "VfB Stuttgart": "VfB Stuttgart", "AFC Ajax": "Ajax",
             "Royal Antwerp FC": "Antwerp", "FK Shakhtar Donetsk": "Shakhtar Donetsk", "Club Brugge KV": "Club Brugge", "Celtic FC": "Celtic",
             "Galatasaray SK": "Galatasaray", "FC København": "Copenhagen", "FC Porto": "Porto", "Borussia Dortmund": "Borussia Dortmund",
             "RB Leipzig": "RB Leipzig", "Eintracht Frankfurt": "Eintracht Frankfurt", "PSV": "PSV", "FK Kairat": "Kairat", "Paphos FC": "Pafos",
             "PSV Eindhoven": "PSV"}
ENG_ALIAS = {"Manchester City": "Manchester City", "Manchester United": "Manchester United", "Newcastle United": "Newcastle United",
             "Tottenham Hotspur": "Tottenham Hotspur", "Aston Villa": "Aston Villa", "Arsenal": "Arsenal", "Liverpool": "Liverpool", "Chelsea": "Chelsea"}


def ucl_team(raw):
    m = re.match(r"(.+?)\s*\(([A-Z]{3})\)$", raw.strip())
    name, cc = m.group(1).strip(), m.group(2)
    if cc == "ENG":
        n = re.sub(r" (FC|AFC)$", "", name); return TEAM[ENG_ALIAS.get(n, n)]
    if cc == "ESP": return team_id(resolve("La Liga", name), "Spain")
    if cc == "ITA": return team_id(resolve("Serie A", name), "Italy")
    nice = UCL_NAMES.get(name) or re.sub(r"^(FC|FK|SK|AC|AS) | (FC|CF|SK|KV)$", "", name).strip()
    return team_id(nice, CC.get(cc, cc), short=nice if len(nice) <= 14 else nice.split()[0], code=re.sub(r"[^A-Z]", "", nice.upper())[:3])


MON = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
STAGE = {"Group": "Group stage", "League": "League phase", "Playoffs": "Knockout play-offs", "Round of 16": "Round of 16",
         "Quarterfinals": "Quarter-finals", "Semifinals": "Semi-finals", "Final": "Final"}
GROUP_KEYS = {"Bayern München": "A", "Arsenal": "B", "Real Madrid": "C", "Real Sociedad": "D", "Atlético Madrid": "E",
              "Borussia Dortmund": "F", "Manchester City": "G", "Barcelona": "H"}
UCL_MATCH = {}
TNAME = lambda tid: next(k for k, v in TEAM.items() if v == tid)
for sname, folder, *_ in SEASONS:
    txt = (DL / "ucl" / folder / "cl.txt").read_text()
    expected = int(re.search(r"# Matches\s+(\d+)", txt).group(1))
    rows, stage, rnd, year, month, date, time = [], None, None, None, None, None, None
    for line in txt.splitlines():
        if line.startswith("▪"):
            head = line[1:].strip(); a, _, b = head.partition(", ")
            if a in ("Group", "League", "Playoffs"):
                stage, rnd = STAGE[a], int(re.search(r"(\d+)", b).group(1))
            else:
                stage, rnd = STAGE[b], None
            continue
        md = re.match(r"^\s{2}(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\w{3}) (\d{1,2})(?: (\d{4}))?\s*$", line)
        if md:
            mo, dd = MON[md.group(1)], int(md.group(2))
            if md.group(3): year = int(md.group(3))
            elif month and mo < month: year += 1
            month = mo; date = f"{year:04d}-{mo:02d}-{dd:02d}"; continue
        mm = re.match(r"^\s{4}(?:(\d{1,2}:\d{2})\s+|\s{7})(.+?\([A-Z]{3}\))\s+v\s+(.+?\([A-Z]{3}\))\s+(.+?)\s*$", line)
        if not mm: continue
        if mm.group(1): time = mm.group(1)
        sc = mm.group(4)
        p = re.match(r"(\d+)-(\d+) pen\. (\d+)-(\d+) a\.e\.t\. \((\d+)-(\d+), (\d+)-(\d+)\)", sc)
        e = re.match(r"(\d+)-(\d+) a\.e\.t\. \((\d+)-(\d+), (\d+)-(\d+)\)", sc)
        n = re.match(r"(\d+)-(\d+)(?: \((\d+)-(\d+)\))?$", sc)
        if p: hs, as_, ht, went, pens = int(p.group(3)), int(p.group(4)), (int(p.group(7)), int(p.group(8))), "PEN", (int(p.group(1)), int(p.group(2)))
        elif e: hs, as_, ht, went, pens = int(e.group(1)), int(e.group(2)), (int(e.group(5)), int(e.group(6))), "ET", (None, None)
        elif n: hs, as_, ht, went, pens = int(n.group(1)), int(n.group(2)), ((int(n.group(3)), int(n.group(4))) if n.group(3) else ((0, 0) if (n.group(1), n.group(2)) == ("0", "0") else None)), None, (None, None)
        else: raise ValueError(f"UCL score not parsed: {line!r}")
        rows.append(dict(stage=stage, rnd=rnd, date=date, time=time, h=mm.group(2), a=mm.group(3), hs=hs, as_=as_, ht=ht, went=went, pens=pens))
    assert len(rows) == expected, (sname, len(rows), expected)
    cur.execute("INSERT INTO seasons (competition_id, name, start_date, end_date, is_current) VALUES (4,?,?,?,0)", (sname, rows[0]["date"], rows[-1]["date"]))
    sid = cur.lastrowid; SEASON_IDS[("Champions League", sname)] = sid
    seen_pairs = collections.Counter()
    for r in rows:
        h, a = ucl_team(r["h"]), ucl_team(r["a"])
        leg = None
        if r["stage"] not in ("Group stage", "League phase", "Final"):
            seen_pairs[(r["stage"], frozenset((h, a)))] += 1; leg = seen_pairs[(r["stage"], frozenset((h, a)))]
        mid = insert_match(sid, r["rnd"], to_utc(r["date"], r["time"], "Europe/Paris"), h, a, r["hs"], r["as_"],
                           r["ht"][0] if r["ht"] else None, r["ht"][1] if r["ht"] else None, "openfootball",
                           stage=r["stage"], leg=leg, went=r["went"], hp=r["pens"][0], ap=r["pens"][1])
        UCL_MATCH[(sid, r["date"], h)] = mid; UCL_MATCH[(sid, r["date"], a)] = mid
    log("Champions League", sname, "matches", len(rows))

# =============================================================================
# Champions League 2025/26: FotMob team stats + English clubs' player data (FPL-Elo-Insights)
# =============================================================================
U = ELO = DL / "elo" / "data" / "2025-2026" / "By Tournament" / "Champions League"
cat = lambda f: pd.concat([pd.read_csv(x) for x in sorted(glob.glob(str(U / "*" / f)))], ignore_index=True)
um, up, ul, ui, us_, umo, uen = (cat(f) for f in ["matches.csv", "playermatchstats.csv", "lineups.csv", "incidents.csv", "shots.csv", "momentum.csv", "player_match_enrichment.csv"])
eteams = pd.read_csv(DL / "elo" / "data" / "2025-2026" / "teams.csv"); code2eng = {c: n for c, n in zip(eteams.code, eteams.name)}
ENGN = {"Man City": "Manchester City", "Man Utd": "Manchester United", "Newcastle": "Newcastle United", "Spurs": "Tottenham Hotspur"}
raw = pd.read_csv(DL / "fpl" / "2025-26_players_raw.csv"); el2code = dict(zip(raw.id, raw.code))
sid = SEASON_IDS[("Champions League", "2025/26")]
TEAM_COLS = {"possession": "possession_pct", "expected_goals_xg": "xg", "total_shots": "total_shots", "shots_on_target": "shots_on_target",
             "big_chances": "big_chances", "big_chances_missed": "big_chances_missed", "accurate_passes": "passes_accurate", "passes": "passes_total",
             "fouls_committed": "fouls", "corners": "corners", "xg_open_play": "xg_open_play", "xg_set_play": "xg_set_play", "non_penalty_xg": "npxg",
             "xg_on_target_xgot": "xgot", "shots_off_target": "shots_off_target", "blocked_shots": "shots_blocked", "hit_woodwork": "hit_woodwork",
             "shots_inside_box": "shots_inside_box", "shots_outside_box": "shots_outside_box", "own_half": "passes_own_half",
             "opposition_half": "passes_opp_half", "accurate_long_balls": "long_balls_accurate", "accurate_crosses": "crosses_accurate",
             "throws": "throw_ins", "touches_in_opposition_box": "touches_opp_box", "offsides": "offsides", "yellow_cards": "yellow_cards",
             "red_cards": "red_cards", "tackles_won": "tackles_won", "interceptions": "interceptions", "blocks": "blocks", "clearances": "clearances",
             "keeper_saves": "keeper_saves", "duels_won": "duels_won", "ground_duels_won": "ground_duels_won", "aerial_duels_won": "aerial_duels_won",
             "successful_dribbles": "dribbles_succeeded"}
PMS_COLS = {"minutes_played": "minutes_played", "goals": "goals", "assists": "assists", "total_shots": "shots_total", "xg": "xg", "xa": "xa",
            "xgot": "xgot", "shots_on_target": "shots_on_target", "successful_dribbles": "dribbles_succeeded", "big_chances_missed": "big_chances_missed",
            "touches_opposition_box": "touches_opp_box", "touches": "touches", "accurate_passes": "passes_accurate", "chances_created": "chances_created",
            "final_third_passes": "passes_final_third", "accurate_crosses": "crosses_accurate", "accurate_long_balls": "long_balls_accurate",
            "tackles_won": "tackles_won", "interceptions": "interceptions", "recoveries": "recoveries", "blocks": "blocks", "clearances": "clearances",
            "headed_clearances": "headed_clearances", "dribbled_past": "dribbled_past", "duels_won": "duels_won", "duels_lost": "duels_lost",
            "ground_duels_won": "ground_duels_won", "aerial_duels_won": "aerial_duels_won", "was_fouled": "was_fouled",
            "fouls_committed": "fouls_committed", "saves": "saves", "goals_conceded": "goals_conceded", "xgot_faced": "xgot_faced",
            "goals_prevented": "goals_prevented", "sweeper_actions": "sweeper_actions", "offsides": "offsides", "high_claim": "high_claims",
            "tackles": "tackles_total", "penalties_scored": "penalty_goals", "penalties_missed": "penalties_missed", "dispossessed": "dispossessed",
            "saves_inside_box": "saves_inside_box", "defensive_contributions": "defensive_contributions"}
slug2 = {}
SIDE = {}            # slug -> {"home": team_id, "away": team_id}  (the dataset's own orientation)
eng_matches = collections.defaultdict(list)
for (s_, dd, t_), mid in UCL_MATCH.items():
    if s_ == sid: eng_matches[t_].append(mid)
skipped = []
for r in um.to_dict("records"):
    code = r["home_team"] if num(r["home_team"]) else r["away_team"]
    eng = TEAM[ENGN.get(code2eng[int(code)], code2eng[int(code)])]
    elo_home_is_eng = num(r["home_team"]) is not None
    slug_teams = r["match_id"].replace("25-26-champions-league-", "").split("-vs-")
    opp_slug = slug_teams[1] if elo_home_is_eng else slug_teams[0]
    cands = sorted(set(eng_matches[eng]))
    best, bs = None, -1
    for mid in cands:
        if mid in [v[0] for v in slug2.values()]: continue
        opp = MINFO[mid]["away"] if MINFO[mid]["home"] == eng else MINFO[mid]["home"]
        sc = name_sim(opp_slug.replace("-", " "), TNAME(opp))
        if isinstance(r["kickoff_time"], str) and abs((datetime.fromisoformat(r["kickoff_time"][:10]) - datetime.fromisoformat(MINFO[mid]["ko"][:10])).days) <= 1:
            sc += 1
        eh_, ea_ = (eng, opp) if elo_home_is_eng else (opp, eng)
        ours_ = (MINFO[mid]["hs"], MINFO[mid]["as_"]) if MINFO[mid]["home"] == eh_ else (MINFO[mid]["as_"], MINFO[mid]["hs"])
        if (num(r["home_score"]), num(r["away_score"])) == ours_: sc += 0.6
        if sc > bs: best, bs = mid, sc
    if best is None:
        skipped.append((r["match_id"], "no fixture left")); continue
    mid = best
    opp = MINFO[mid]["away"] if MINFO[mid]["home"] == eng else MINFO[mid]["home"]
    eh, ea = (eng, opp) if elo_home_is_eng else (opp, eng)
    ours = (MINFO[mid]["hs"], MINFO[mid]["as_"]) if MINFO[mid]["home"] == eh else (MINFO[mid]["as_"], MINFO[mid]["hs"])
    if (num(r["home_score"]), num(r["away_score"])) != ours:
        skipped.append((r["match_id"], (num(r["home_score"]), num(r["away_score"])), ours)); continue
    if eh != MINFO[mid]["home"]:
        log("  dataset has home/away reversed for", r["match_id"], "-> using the real fixture", TNAME(MINFO[mid]["home"]), "v", TNAME(MINFO[mid]["away"]))
    slug2[r["match_id"]] = (mid, eng); SIDE[r["match_id"]] = {"home": eh, "away": ea}
    for side, pre in ((eh, "home_"), (ea, "away_")):
        t = tm(mid, side, "fotmob")
        for c, col in TEAM_COLS.items(): put(t, col, r.get(pre + c))
        for won, pct, col in (("accurate_long_balls", "accurate_long_balls_pct", "long_balls_total"), ("accurate_crosses", "accurate_crosses_pct", "crosses_total"),
                              ("ground_duels_won", "ground_duels_won_pct", "ground_duels_total"), ("aerial_duels_won", "aerial_duels_won_pct", "aerial_duels_total"),
                              ("successful_dribbles", "successful_dribbles_pct", "dribbles_attempted")):
            v = total_from_pct(r.get(pre + won), r.get(pre + pct))
            if v is not None: t[col] = v
log("UCL 2025/26 dataset matches skipped because their score disagrees with the result:", skipped)
log("UCL 2025/26 matches with FotMob team stats:", len(slug2))


NAME_MAP = {}   # (mid, folded name) -> pid for English clubs' players
CLUB_PLAYERS = collections.defaultdict(set)      # every player seen for a club in any league season
for (m_, p_), d_ in PMS.items(): CLUB_PLAYERS[d_["team_id"]].add(p_)
for t_, p_ in cur.execute("SELECT DISTINCT team_id, player_id FROM player_match_stats"): CLUB_PLAYERS[t_].add(p_)
PL26 = cur.execute("SELECT season_id FROM seasons WHERE competition_id=1 AND name='2025/26'").fetchone()[0]
SQUAD = collections.defaultdict(set)
for t_, p_ in cur.execute("SELECT team_id, player_id FROM squad_memberships WHERE season_id=?", (PL26,)): SQUAD[t_].add(p_)


def ucl_pid(mid, tid, el, name):
    if num(el) is not None:
        code = el2code.get(int(num(el)))
        if code in PL_FPL: return PL_FPL[code]
    if (mid, " ".join(fold(name))) in NAME_MAP: return NAME_MAP[(mid, " ".join(fold(name)))]
    key = (tid, " ".join(fold(name)))
    if key not in BYNAME_TEAM and CLUB_PLAYERS.get(tid):
        got = match_names([name], sorted(CLUB_PLAYERS[tid]), lambda x: x, threshold=0.6)
        if got: BYNAME_TEAM[key] = got[0]
    if key not in BYNAME_TEAM:
        cands = [p for p in BYNAME_TEAM.values() if False]
        BYNAME_TEAM[key] = new_player(name)
    return BYNAME_TEAM[key]


# FotMob player rows first (FPL ids), then map the lineup feed's short names for English sides onto them
for r in up.to_dict("records"):
    if r["match_id"] not in slug2: continue
    mid, eng = slug2[r["match_id"]]
    code = el2code.get(int(num(r["player_id"]))) if num(r["player_id"]) is not None else None
    if code in PL_FPL: BYM_ENG = pm(mid, PL_FPL[code], eng, "fotmob")
for slug, g in ul[ul.match_id.isin(slug2)].groupby("match_id"):
    mid, eng = slug2[slug]
    rows = [r for r in g.to_dict("records") if SIDE[slug][r["team_side"]] == eng and num(r["player_id"]) is None]
    cands = sorted(set(team_players(mid, eng, played=False)) | SQUAD[eng])
    got = match_names(rows, cands, lambda r: r["player_name"], threshold=0.45)
    for i, r in enumerate(rows):
        if i in got: NAME_MAP[(mid, " ".join(fold(r["player_name"])))] = got[i]
    log("  ", slug, "English lineup names matched:", len(got), "/", len(rows))
for r in ul.to_dict("records"):
    if r["match_id"] not in slug2: continue
    mid, eng = slug2[r["match_id"]]
    tid = SIDE[r["match_id"]][r["team_side"]]
    pid = ucl_pid(mid, tid, r["player_id"], r["player_name"])
    d = pm(mid, pid, tid, "lineups feed")
    d["is_starter"] = int(str(r["is_starting"]) == "True"); put(d, "shirt_number", r["jersey_number"])
    d["position"] = {"G": "GK", "D": "DF", "M": "MF", "F": "FW"}.get(r["position"])
    if isinstance(r.get("formation"), str): SHEETS[(mid, tid)] = dict(formation=r["formation"], source="lineups feed")
for r in up.to_dict("records"):
    if r["match_id"] not in slug2: continue
    mid, eng = slug2[r["match_id"]]
    pid = ucl_pid(mid, eng, r["player_id"], str(r["player_id"]))
    d = pm(mid, pid, eng, "fotmob")
    for c, col in PMS_COLS.items():
        if c in r: put(d, col, r[c])
    for won, pct, col in (("accurate_passes", "accurate_passes_percent", "passes_total"), ("accurate_long_balls", "accurate_long_balls_percent", "long_balls_total"),
                          ("accurate_crosses", "accurate_crosses_percent", "crosses_total"), ("ground_duels_won", "ground_duels_won_percent", "ground_duels_total"),
                          ("aerial_duels_won", "aerial_duels_won_percent", "aerial_duels_total"), ("successful_dribbles", "successful_dribbles_percent", "dribbles_attempted")):
        v = total_from_pct(r.get(won), r.get(pct))
        if v is not None: d[col] = v
for r in uen.to_dict("records"):
    if r["match_id"] not in slug2: continue
    mid, eng = slug2[r["match_id"]]
    if num(r["player_id"]) is None: continue
    code = el2code.get(int(num(r["player_id"]))); pid = PL_FPL.get(code)
    if (mid, pid) in PMS:
        d = PMS[(mid, pid)]; SRC[(mid, pid)].add("detailed feed")
        put(d, "rating", r["rating"]); put(d, "possession_lost", r["possession_lost"]); put(d, "punches", r["goalkeeper_punches"])
        put(d, "passes_total", r["total_passes"]); put(d, "long_balls_total", r["total_long_balls"]); put(d, "crosses_total", r["total_crosses"])
        put(d, "dribbles_attempted", r["total_dribbles"]); put(d, "yellow_cards", r["yellow_cards"]); put(d, "red_cards", r["red_cards"])
# incidents -> events, minutes for opposition players, cards
ui = ui[ui.match_id.isin(slug2)]
gok = gbad = 0
for slug, g in ui.groupby("match_id"):
    mid, eng = slug2[slug]
    g = g.sort_values(["minute", "added_time", "incident_index"], na_position="first", ascending=[True, True, False])
    h = a = 0; goals = []
    for r in g.to_dict("records"):
        t = r["incident_type"]; mi = num(r["minute"]); add = num(r["added_time"])
        if mi is None or mi < 0: continue
        side = SIDE[slug].get(r["team_side"]) if r["team_side"] in ("home", "away") else None
        pid = ucl_pid(mid, side, r["player_id"], r["player_name"]) if side and isinstance(r["player_name"], str) else None
        if t == "goal":
            if mi > 120: continue
            hs, as_ = num(r["home_score"]), num(r["away_score"])
            scoring = SIDE[slug]["home"] if hs is not None and hs > h else SIDE[slug]["away"]
            if hs is not None: h, a = hs, as_
            ast = ucl_pid(mid, side, r["assist_player_id"], r["assist_player_name"]) if isinstance(r.get("assist_player_name"), str) else None
            goals.append((mi, add, {"penalty": "penalty_goal", "ownGoal": "own_goal"}.get(r["goal_type"], "goal"), scoring, pid, ast, h, a))
        elif t == "card" and pid:
            ev(mid, side, mi, add, {"yellow": "yellow_card", "red": "red_card", "yellowRed": "second_yellow"}[r["card_type"]], pid, src="detailed feed")
            if (mid, pid) in PMS:
                d = PMS[(mid, pid)]
                if r["card_type"] == "yellow": d["yellow_cards"] = (d.get("yellow_cards") or 0) + (0 if "fotmob" in SRC[(mid, pid)] and d.get("yellow_cards") else 1)
                else: d["red_cards"] = 1; d["_red"] = mi
        elif t == "substitution" and side:
            q = ucl_pid(mid, side, r["secondary_player_id"], r["secondary_player_name"]) if isinstance(r.get("secondary_player_name"), str) else None
            sp, sq = PMS.get((mid, pid), {}).get("is_starter"), PMS.get((mid, q), {}).get("is_starter")
            on, off = (q, pid) if (sp == 1 and sq != 1) or (sp is None and sq == 0) else (pid, q)
            ev(mid, side, mi, add, "substitution", on, off, src="detailed feed")
            if on and (mid, on) in PMS: PMS[(mid, on)]["sub_on_minute"] = mi
            if off and (mid, off) in PMS: PMS[(mid, off)]["sub_off_minute"] = mi
        elif t == "varDecision":
            ev(mid, side, mi, add, "var", pid, detail=r.get("text") if isinstance(r.get("text"), str) else None, src="detailed feed")
    flip = SIDE[slug]["home"] != MINFO[mid]["home"]
    if ((a, h) if flip else (h, a)) == (MINFO[mid]["hs"], MINFO[mid]["as_"]) and len(goals) == h + a:
        gok += 1
        for mi, add, et, tid, p, ast, hh, aa in goals: ev(mid, tid, mi, add, et, p, ast, src="detailed feed", hs=aa if flip else hh, as_=hh if flip else aa)
    else:
        gbad += 1
log("UCL 2025/26 goal timelines matching the score:", gok, "mismatch:", gbad)
# minutes for players without FotMob rows (opposition): from lineup + substitutions
for (mid, pid), d in PMS.items():
    if MINFO[mid]["sid"] == sid and d.get("minutes_played") is None and d.get("is_starter") is not None:
        end = 120 if any(e["match_id"] == mid and e["minute"] > 90 for e in EVENTS) and False else 90
        if d["is_starter"]:
            mins = (d.get("sub_off_minute") or d.get("_red") or end)
        else:
            mins = (min(d.get("sub_off_minute") or end, d.get("_red") or end) - d["sub_on_minute"]) if d.get("sub_on_minute") is not None else 0
        d["minutes_played"] = max(int(mins), 1 if (d["is_starter"] or d.get("sub_on_minute") is not None) else 0)
        SRC[(mid, pid)].add("minutes from substitutions")
for d in PMS.values(): d.pop("_red", None)
for r in us_.to_dict("records"):
    if r["match_id"] not in slug2 or r["outcome"] == "ownGoal": continue
    mid, eng = slug2[r["match_id"]]; tid = SIDE[r["match_id"]]["home" if str(r["is_home"]) == "True" else "away"]
    pid = ucl_pid(mid, tid, r["player_id"], r["player_name"]) if isinstance(r["player_name"], str) else None
    SHOTS.append(dict(match_id=mid, team_id=tid, player_id=pid, minute=num(r["minute"]), added_time=num(r["added_time"]),
                      period="1H" if (num(r["minute"]) or 0) <= 45 else "2H", x=round(105 - num(r["start_x"]) * 1.05, 1), y=round(num(r["start_y"]) * 0.68, 1),
                      xg=num(r["xg"]), xgot=num(r["xgot"]), outcome={"goal": "goal", "save": "saved", "miss": "missed", "block": "blocked", "post": "woodwork"}[r["outcome"]],
                      body_part={"right-foot": "right_foot", "left-foot": "left_foot", "head": "header", "other": "other"}.get(r["body_part"]),
                      situation={"regular": "open_play", "assisted": "open_play", "fast-break": "fast_break", "corner": "corner", "set-piece": "set_piece",
                                 "free-kick": "free_kick", "penalty": "penalty", "throw-in-set-piece": "throw_in"}.get(r["situation"]),
                      is_own_goal=0, goal_mouth_y=num(r["goal_mouth_y"]), goal_mouth_z=num(r["goal_mouth_z"]), source="detailed feed"))
for r in umo.to_dict("records"):
    if r["match_id"] in slug2:
        sgn = -1 if SIDE[r["match_id"]]["home"] != MINFO[slug2[r["match_id"]][0]]["home"] else 1
        MOM.append((slug2[r["match_id"]][0], num(r["minute"]), sgn * num(r["value"])))

# =============================================================================
# Write
# =============================================================================
for pid, p in NEWP.items():
    if not any(pid in BYM[m] for m in BYM) and not any(s["player_id"] == pid for s in SHOTS) and not any(e["player_id"] == pid or e["related_player_id"] == pid for e in EVENTS):
        continue
    fb = p["fb"] if p["fb"] and cur.execute("SELECT 1 FROM players WHERE fbref_id=?", (p["fb"],)).fetchone() is None else None
    us = p["us"] if p["us"] and cur.execute("SELECT 1 FROM players WHERE understat_id=?", (p["us"],)).fetchone() is None else None
    cur.execute("INSERT INTO players (player_id, fbref_id, understat_id, name, nationality) VALUES (?,?,?,?,?)", (pid, fb, us, p["name"], p["nat"]))
for pid in {pid for (m, pid) in PMS} - set(NEWP):
    pass
for fbk, pid in PL_FB.items():   # FBref ids discovered for existing Premier League players
    if pid not in NEWP:
        cur.execute("UPDATE players SET fbref_id=COALESCE(fbref_id, ?) WHERE player_id=? AND NOT EXISTS (SELECT 1 FROM players WHERE fbref_id=?)", (fbk, pid, fbk))
cols = [c[1] for c in db.execute("PRAGMA table_info(player_match_stats)")]
for (mid, pid), d in PMS.items():
    d = dict(d); d.update(match_id=mid, player_id=pid, source="+".join(sorted(SRC[(mid, pid)])))
    d.setdefault("minutes_played", 0)
    keys = [c for c in cols if c in d]
    cur.execute(f"INSERT INTO player_match_stats ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})", [d[k] for k in keys])
tcols = [c[1] for c in db.execute("PRAGMA table_info(team_match_stats)")]
for (mid, tid), d in TMS.items():
    d = {k: v for k, v in d.items() if k in tcols and v is not None}
    d.update(match_id=mid, team_id=tid, period="ALL", source="+".join(sorted(TSRC[(mid, tid)])))
    cur.execute(f"INSERT INTO team_match_stats ({','.join(d)}) VALUES ({','.join('?' * len(d))})", list(d.values()))
for (mid, tid), s in SHEETS.items():
    cur.execute("INSERT OR REPLACE INTO match_team_sheets VALUES (?,?,?,?,?,?,?)", (mid, tid, int(tid == MINFO[mid]["home"]), s.get("formation"), None, None, s["source"]))
ecols = ["match_id", "team_id", "minute", "added_time", "period", "event_type", "player_id", "related_player_id", "detail", "home_score_after", "away_score_after", "source"]
for e in sorted(EVENTS, key=lambda e: (e["match_id"], e["minute"], e["added_time"] or 0)):
    e["period"] = "1H" if e["minute"] <= 45 else ("2H" if e["minute"] <= 90 else "ET")
    cur.execute(f"INSERT INTO match_events ({','.join(ecols)}) VALUES ({','.join('?' * len(ecols))})", [e.get(c) for c in ecols])
scols = list(SHOTS[0].keys())
cur.executemany(f"INSERT INTO shots ({','.join(scols)}) VALUES ({','.join('?' * len(scols))})", [[s[c] for c in scols] for s in SHOTS])
cur.executemany("INSERT OR IGNORE INTO match_momentum VALUES (?,?,?)", MOM)
new_sids = tuple(SEASON_IDS.values())
cur.execute(f"""INSERT INTO squad_memberships (season_id, team_id, player_id, shirt_number, first_match_date, last_match_date)
               SELECT m.season_id, p.team_id, p.player_id,
                      (SELECT shirt_number FROM player_match_stats x JOIN matches mm USING(match_id)
                       WHERE x.player_id=p.player_id AND x.team_id=p.team_id AND mm.season_id=m.season_id AND shirt_number IS NOT NULL
                       GROUP BY shirt_number ORDER BY COUNT(*) DESC LIMIT 1),
                      MIN(DATE(m.kickoff_utc)), MAX(DATE(m.kickoff_utc))
               FROM player_match_stats p JOIN matches m USING (match_id)
               WHERE m.season_id IN ({','.join('?' * len(new_sids))})
               GROUP BY m.season_id, p.team_id, p.player_id""", new_sids)


# ---------------- standings
def rank(teams, played, rule):
    tab = {t: dict(p=0, w=0, d=0, l=0, gf=0, ga=0, agf=0, xf=0.0, xa=0.0, res=[]) for t in teams}
    for h, a, hs, as_, hx, ax in played:
        for t, gf, ga, xf, xa, away in ((h, hs, as_, hx, ax, 0), (a, as_, hs, ax, hx, 1)):
            r = tab[t]; r["p"] += 1; r["gf"] += gf; r["ga"] += ga; r["agf"] += gf * away; r["xf"] += xf or 0; r["xa"] += xa or 0
            res = "W" if gf > ga else "D" if gf == ga else "L"; r[res.lower()] += 1; r["res"].append(res)
    pts = lambda t: 3 * tab[t]["w"] + tab[t]["d"]
    def h2h(group):
        mini = {t: [0, 0, 0] for t in group}
        for h, a, hs, as_, *_ in played:
            if h in mini and a in mini:
                for t, gf, ga in ((h, hs, as_), (a, as_, hs)):
                    mini[t][0] += 3 if gf > ga else 1 if gf == ga else 0; mini[t][1] += gf - ga; mini[t][2] += gf
        return mini
    order = sorted(teams, key=lambda t: -pts(t))
    out, i = [], 0
    while i < len(order):
        j = i
        while j < len(order) and pts(order[j]) == pts(order[i]): j += 1
        grp = order[i:j]
        if len(grp) > 1 and rule == "h2h":
            mini = h2h(grp)
            grp.sort(key=lambda t: (-mini[t][0], -mini[t][1], -(tab[t]["gf"] - tab[t]["ga"]), -tab[t]["gf"]))
        else:
            grp.sort(key=lambda t: (-(tab[t]["gf"] - tab[t]["ga"]), -tab[t]["gf"], -tab[t]["agf"], -tab[t]["w"]))
        out += grp; i = j
    return out, tab, pts


def write_table(sid, r, order, tab, pts, group=None):
    for pos, t in enumerate(order, 1):
        x = tab[t]
        cur.execute("""INSERT INTO standings (season_id, after_round, group_name, team_id, position, played, won, drawn, lost, goals_for,
                       goals_against, goal_diff, points, form, xg_for, xg_against) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (sid, r, group, t, pos, x["p"], x["w"], x["d"], x["l"], x["gf"], x["ga"], x["gf"] - x["ga"], pts(t), "".join(x["res"][-5:]),
                     round(x["xf"], 2) if x["xf"] else None, round(x["xa"], 2) if x["xa"] else None))


for (comp, sname), sid in SEASON_IDS.items():
    ms = cur.execute("""SELECT m.round_no, m.home_team_id, m.away_team_id, m.home_score, m.away_score, hs.xg, as_.xg, m.stage
                        FROM matches m
                        LEFT JOIN team_match_stats hs ON hs.match_id=m.match_id AND hs.team_id=m.home_team_id
                        LEFT JOIN team_match_stats as_ ON as_.match_id=m.match_id AND as_.team_id=m.away_team_id
                        WHERE m.season_id=? AND m.home_score IS NOT NULL AND (m.stage IS NULL OR m.stage IN ('Group stage','League phase'))
                        ORDER BY m.kickoff_utc""", (sid,)).fetchall()
    if comp == "Champions League" and sname == "2023/24":
        adj = collections.defaultdict(set)
        for m in ms: adj[m[1]].add(m[2]); adj[m[2]].add(m[1])
        groups, seen = [], set()
        for t in adj:
            if t in seen: continue
            comp_, stack = set(), [t]
            while stack:
                x = stack.pop()
                if x in comp_: continue
                comp_.add(x); stack.extend(adj[x])
            seen |= comp_; groups.append(comp_)
        assert len(groups) == 8 and all(len(g) == 4 for g in groups), [len(g) for g in groups]
        for g in groups:
            letter = next(GROUP_KEYS[TNAME(t)] for t in g if TNAME(t) in GROUP_KEYS)
            for r in range(1, 7):
                played = [m[1:7] for m in ms if m[0] <= r and m[1] in g]
                order, tab, pts = rank(sorted(g), played, "h2h"); write_table(sid, r, order, tab, pts, f"Group {letter}")
        continue
    teams = sorted({m[1] for m in ms} | {m[2] for m in ms})
    for r in range(1, max(m[0] for m in ms) + 1):
        played = [m[1:7] for m in ms if m[0] <= r]
        order, tab, pts = rank(teams, played, "h2h" if comp in LEAGUES else "uefa")
        write_table(sid, r, order, tab, pts)

SHORTS = {"Paris Saint-Germain": ("PSG", "PSG"), "Bayer Leverkusen": ("Leverkusen", "B04"), "Borussia Dortmund": ("Dortmund", "BVB"),
          "Eintracht Frankfurt": ("Frankfurt", "SGE"), "Bayern München": ("Bayern", "FCB"), "Union Saint-Gilloise": ("Union SG", "USG"),
          "Shakhtar Donetsk": ("Shakhtar", "SHA"), "Slovan Bratislava": ("Slovan", "SLO"), "Crvena Zvezda": ("Crvena Zvezda", "CZV")}
for n_, (sh_, co_) in SHORTS.items():
    cur.execute("UPDATE teams SET short_name=?, code=? WHERE name=?", (sh_, co_, n_))
db.commit()
for t in ["competitions", "seasons", "teams", "players", "matches", "player_match_stats", "team_match_stats", "match_events", "shots", "match_momentum", "standings"]:
    print(f"  {t:20s} {cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:>7}")
(HERE / "build_more_log.txt").write_text("\n".join(LOG))
