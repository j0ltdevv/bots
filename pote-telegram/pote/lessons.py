"""Le bot apprend de ses propres erreurs - sans se raconter d'histoires.

Quand l’élève corrige le bot ("non c est l autre", "t as invente", "27 pas 23"),
la correction est enregistree telle quelle. Une passe de consolidation en tire
des LECONS, et chaque lecon est REJOUEE contre le cerveau : si le cerveau ne
sait pas l appliquer, la lecon est marquee "inappliquee" et remonte a l oeil de
l’élève. Rien n est "appris" qu on n ait rejoue.

Le rejeu est un ESSAI A SEC : il passe par les mêmes fonctions que la vraie
réponse, mais avec ``ecrire=False`` — sinon la consolidation nocturne
re-cocherait chaque soir les devoirs que le bot venait de barrer.

Trois etats de lecon, un seul fichier :
  - "nouvelle"    : extraite d une correction, pas encore rejouee assez ;
  - "active"      : rejouee avec succes, injectee dans le prompt ;
  - "inappliquee" : rejouee, le cerveau echoue - c est un BUG, pas une lecon.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from . import brain, compose
from .brain import court, sans_accents

SEUIL = 3   # fois qu une lecon doit passer le rejeu


def racine() -> Path:
    return Path(os.environ.get("POTE_DATA", Path.home() / ".local/share/pote-tg"))


def corrections() -> Path:
    return racine() / "corrections.jsonl"


def lecons() -> Path:
    return racine() / "lecons.jsonl"


def _lire_jsonl(p: Path) -> list:
    if not p.exists():
        return []
    out = []
    for ligne in p.read_text(errors="replace").splitlines():
        if not ligne.strip():
            continue
        try:
            out.append(json.loads(ligne))
        except ValueError:
            continue
    return out


def noter(message: str, reponse_bot: str, intention: str) -> dict:
    """Journalise l echange et qualifie la negation (l’élève corrige le bot)."""
    racine().mkdir(parents=True, exist_ok=True)
    entree = {
        "at": datetime.now().isoformat(),
        "message": message,
        "reponse_bot": reponse_bot,
        "intention": intention,
        "negation": est_correction(message),
    }
    with corrections().open("a") as f:
        f.write(json.dumps(entree, ensure_ascii=False) + "\n")
    os.chmod(corrections(), 0o600)
    return entree


def est_correction(message: str) -> bool:
    """l’élève contredit le bot : c est le signal que le bot a eu tort.

    On teste sur la forme normalisee ("c est", sans apostrophe) parce que sur
    un telephone on ecrit sans apostrophe : un motif trop etroit perdait des
    corrections en silence.
    """
    b = sans_accents(message)
    return bool(re.search(
        r"non !|mais non|pas ca|c est pas|arrete|t as invente|t as hallucine"
        r"|n invente|je t ai dit|mauvais|faux|si c est pas"
        r"|le numero est|c est pas le bon|tu te trompes|autre chose|pas le bon", b))


def _nettoyer_phrase(phrase: str) -> str:
    return re.sub(r"^(non|mais|si c est pas|je t ai dit|celui|l autre)\s*[!,. ]*",
                  "", phrase or "", flags=re.I)


def _lecon_de(c: dict, faits) -> dict | None:
    """Transforme une correction en lecon rejouable, ou None.

    On ne devine pas une intention depuis le langage naturel : on regarde ce
    que le cerveau a repondu et on exige qu il reponde autrement. Une
    correction qui ne change rien au calcul est une observation, pas une lecon.
    """
    msg = c.get("message", "")
    intention = c.get("intention") or ""
    if intention in ("fait", "decoche"):
        cibles = brain.cibler(faits, _nettoyer_phrase(msg))
        if cibles.ambigu:
            return {"type": "ciblage_unique", "attendu": "demander", "phrase": msg}
        if not cibles.aucune:
            return {"type": "ciblage_unique", "attendu": "un_seul_cible", "phrase": msg}
        return None      # aucune matière nommée : rien à cibler, donc rien à apprendre
    if intention in ("chiffres", "retards", "recap", "demain", "ce_soir"):
        return {"type": "chiffres", "attendu": "citer_les_faits", "phrase": msg}
    if intention in ("profs", "en_ligne", "cours", "notes", "controles"):
        return {"type": "source", "attendu": "ne_pas_melanger_les_sources", "phrase": msg}
    return None


def rejouer(lecon: dict, faits) -> str:
    """Rejoue une lecon contre le cerveau et renvoie CE QUE L UTILISATEUR
    verrait. Essai a sec : ``ecrire=False``, sinon la consolidation nocturne
    re-cocherait les devoirs pour de bon."""
    if lecon["type"] == "ciblage_unique":
        r = compose.c_est_fait(faits, _nettoyer_phrase(lecon.get("phrase", "")),
                               ecrire=False)
        obtenu = "demander" if r.intention in ("ambigu", "introuvable") else "un_seul_cible"
        return lecon["attendu"] if obtenu == lecon["attendu"] else obtenu
    if lecon["type"] == "chiffres":
        r = compose.chiffres(faits)
        return "citer_les_faits" if str(faits.chiffres["retard"]) in r.texte else "autre"
    if lecon["type"] == "source":
        r = compose.repondre(faits, "qu ils ont dit les profs")
        return "ne_pas_melanger_les_sources" if r.intention == "profs" else "autre"
    return "autre"


def consolider(faits=None) -> dict:
    """Rejoue chaque correction contre le cerveau et met a jour les etats.

    L ordre compte : on downgrade avant de trier et d ecrire, sinon le seuil ne
    s applique qu a la copie en memoire et rien n est persiste.
    """
    faits = faits or brain.construire()
    connues = {l["cle"]: l for l in _lire_jsonl(lecons()) if l.get("cle")}

    nb_rejouees = nb_ok = 0
    for c in _lire_jsonl(corrections()):
        if not c.get("negation"):
            continue
        lecon = _lecon_de(c, faits)
        if not lecon:
            continue
        cle = lecon["type"] + "|" + court(lecon["phrase"], 60)
        ancienne = connues.get(cle, {})
        nb_rejouees += 1
        if rejouer(lecon, faits) == lecon["attendu"]:
            nb_ok += 1
            lecon.update({"cle": cle, "etat": "active",
                          "reussites": ancienne.get("reussites", 0) + 1,
                          "dernier_rejeu": datetime.now().isoformat(),
                          "exemple": c.get("reponse_bot", "")[:300]})
        else:
            lecon.update({"cle": cle, "etat": "inappliquee",
                          "echecs": ancienne.get("echecs", 0) + 1,
                          "dernier_rejeu": datetime.now().isoformat(),
                          "exemple": c.get("reponse_bot", "")[:300]})
        connues[cle] = lecon

    for lecon in connues.values():
        if lecon.get("etat") == "active" and lecon.get("reussites", 0) < SEUIL:
            lecon["etat"] = "nouvelle"

    finales = sorted(les_connues(connues), key=lambda l: -l.get("reussites", 0))
    _ecrire(lecons(), finales)
    return {"rejouees": nb_rejouees, "reussies": nb_ok,
            "actives": sum(1 for l in finales if l["etat"] == "active"),
            "inappliquees": sum(1 for l in finales if l["etat"] == "inappliquee")}


def les_connues(connues: dict) -> list:
    """Les lecons connues, les plus rejouees d abord."""
    return list(connues.values())


def actives() -> list:
    """Lecons a injecter dans le prompt : courtes, actionnables, rejouees."""
    return [l for l in _lire_jsonl(lecons()) if l.get("etat") == "active"]


def prompt_lessons() -> str:
    return "\n".join(f"- {l['type']}: « {court(l['phrase'], 80)} »" for l in actives())


def _ecrire(p: Path, donnees: list) -> None:
    racine().mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in donnees))
    os.chmod(tmp, 0o600)
    tmp.replace(p)