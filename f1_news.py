"""
f1_news.py — lightweight signal extraction from the live F1 news feed.

The dashboard already pulls the latest headlines (motorsport.com RSS) into
data/news.json. This module scans those headlines for transparent,
keyword-based signals that feed the prediction model:

  • upgrades — how often a team's car development is in the news (a proxy for
               in-season car upgrades / development momentum)
  • buzz     — net positive / negative sentiment around each driver & team
  • penalty  — an explicit grid / engine penalty flagged for a driver

These are deliberately SMALL nudges and clearly labelled as news-derived
(headline-only, noisy) — they are not hard data. Everything is keyword based
so it is fully explainable.
"""
import re
import unicodedata

UPGRADE_KW = ("upgrade", "update", "new floor", "new wing", "front wing", "rear wing",
              "new package", "upgrade package", "development", "b-spec", "evolution",
              "sidepod", "diffuser", "revised", "new spec", "bodywork", "new parts")
POS_KW = ("win", "wins", "won", "victory", "pole", "fastest", "dominant", "dominate",
          "podium", "impressive", "record", "quickest", "topped", "strong", "charge",
          "stunning", "breakthrough", "resurgent", "flying")
NEG_KW = ("crash", "crashes", "penalty", "disqualified", "dsq", "retire", "retirement",
          "dnf", "struggle", "struggles", "slump", "injury", "injured", "sidelined",
          "failure", "fails", "spin", "damage", "fined", "investigation", "stewards",
          "axed", "sacked", "withdraw", "blow", "woes")
PENALTY_KW = ("grid penalty", "engine penalty", "gearbox penalty", "power unit penalty",
              "place grid", "back of the grid", "grid drop", "places on the grid")

# Team-name aliases (driver names are matched separately and mapped to their team)
CONS_ALIASES = {
    "red_bull":     ("red bull", "redbull"),
    "ferrari":      ("ferrari", "scuderia"),
    "mclaren":      ("mclaren",),
    "mercedes":     ("mercedes", "merc "),
    "aston_martin": ("aston martin", "aston"),
    "alpine":       ("alpine",),
    "williams":     ("williams",),
    "rb":           ("racing bulls", "visa cash app", "rb f1", "vcarb"),
    "haas":         ("haas",),
    "audi":         ("audi", "sauber"),
    "cadillac":     ("cadillac",),
}


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _count(text, kws):
    return sum(text.count(k) for k in kws)


def news_signals(news, drivers):
    """drivers: list of dicts with driverId, family, constructorId.
    Returns dev (per constructor), buzz (per driver), cons_buzz, penalty
    (per driver), and the number of headlines scanned."""
    fam = {d["driverId"]: _norm(d.get("family") or "") for d in drivers}
    cons_of = {d["driverId"]: d["constructorId"] for d in drivers}
    cons_ids = sorted(set(cons_of.values()))
    dev = {c: 0 for c in cons_ids}
    buzz = {d["driverId"]: 0.0 for d in drivers}
    cons_buzz = {c: 0.0 for c in cons_ids}
    penalty = {d["driverId"]: False for d in drivers}
    mentions = {d["driverId"]: 0 for d in drivers}
    n_head = 0

    for item in (news or []):
        t = _norm(item.get("title"))
        if not t:
            continue
        n_head += 1
        up = _count(t, UPGRADE_KW)
        sent = max(-2, min(2, _count(t, POS_KW) - _count(t, NEG_KW)))
        is_pen = any(k in t for k in PENALTY_KW)
        # team mentions
        for c, al in CONS_ALIASES.items():
            if c in dev and any(a in t for a in al):
                dev[c] += up
                cons_buzz[c] += sent
        # driver mentions (word-boundary on family name; needs ≥4 chars)
        for did, f in fam.items():
            if len(f) >= 4 and re.search(r"\b" + re.escape(f) + r"\b", t):
                mentions[did] += 1
                buzz[did] += sent
                if up:
                    dev[cons_of[did]] += 1
                if is_pen:
                    penalty[did] = True

    return {"dev": dev, "buzz": buzz, "cons_buzz": cons_buzz,
            "penalty": penalty, "mentions": mentions, "headlines": n_head}
