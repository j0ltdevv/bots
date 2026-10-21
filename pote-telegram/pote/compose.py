"""Réponses déterministes — la vérité de référence.

Chaque intention produit DEUX choses :
  · ``texte``  : la réponse exacte, sans LLM. C'est ce qui part si le modèle
                 dérape, et c'est ce que les tests vérifient ;
  · ``faits``  : le contexte compact remis au modèle, qui n'a plus qu'à le
                 mettre en mots.

Aucun nombre n'est écrit ici autrement que par ``Faits.chiffres`` : c'est la
réponse au « 23 retards » annoncé alors qu'il y en avait 27.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import brain
from .brain import Faits, court, sans_accents


@dataclass
class Reponse:
    intention: str
    texte: str                    # déterministe, toujours exact
    faits: list = field(default_factory=list)   # lignes autorisées pour le LLM
    suivi: dict = field(default_factory=dict)    # état de session (quiz, attente…)
    action: str = ""              # 'marque' si on a écrit dans done-inbox


def _titres(faits: Faits) -> dict:
    return {"RETARD": "EN RETARD", "AUJOURDHUI": "AUJOURD'HUI",
            "DEMAIN": "DEMAIN", "PLUS_TARD": "PLUS TARD"}


def _section(faits: Faits, bucket: str, vide="(rien)") -> str:
    ds = faits.bucket(bucket)
    if not ds:
        return vide
    return "\n".join("· " + d.ligne() for d in ds)


# ─────────────────────────── les intentions ───────────────────────────

def chiffres(faits: Faits) -> Reponse:
    c = faits.chiffres
    txt = (f"{c['total']} trucs à faire au total — {c['retard']} en retard, "
           f"{c['aujourdhui']} aujourd'hui, {c['demain']} demain.")
    return Reponse("chiffres", txt, list(faits.lignes()))


def demain(faits: Faits) -> Reponse:
    ds = faits.bucket("DEMAIN")
    if not ds:
        base = "Rien pour demain. T'as le temps."
    else:
        base = "Demain :\n" + "\n".join("· " + d.ligne() for d in ds)
    if faits.cours_demain:
        cours = ", ".join(f"{c['subject']} {c['start']}" for c in faits.cours_demain[:6])
        base += f"\n\nCours : {cours}."
    return Reponse("demain", base, list(faits.lignes()))


def ce_soir(faits: Faits) -> Reponse:
    """Priorité : ce soir d'abord, puis le retard le plus ancien."""
    ordre = (faits.bucket("AUJOURDHUI") + faits.bucket("RETARD")[:3]
             + faits.bucket("DEMAIN"))
    if not ordre:
        return Reponse("ce_soir", "Rien à faire ce soir. Profite 👌", list(faits.lignes()))
    txt = "Ce soir, dans l'ordre :\n" + "\n".join(
        f"{i}. {d.ligne()}" for i, d in enumerate(ordre, 1))
    if ordre[0].premier_pas:
        txt += f"\n\nCommence par : {ordre[0].premier_pas}"
    return Reponse("ce_soir", txt, list(faits.lignes()))


def recap(faits: Faits) -> Reponse:
    t = _titres(faits)
    blocs = []
    for b in ("RETARD", "AUJOURDHUI", "DEMAIN", "PLUS_TARD"):
        blocs.append(f"{t[b]} ({len(faits.bucket(b))})\n{_section(faits, b)}")
    return Reponse("recap", "\n\n".join(blocs), list(faits.lignes()))


def retards(faits: Faits) -> Reponse:
    c = faits.chiffres
    if not c["retard"]:
        return Reponse("retards", "Zero retard. Comme quoi ça arrive.", list(faits.lignes()))
    t = _titres(faits)
    return Reponse("retards",
                   f"{c['retard']} en retard :\n" + _section(faits, "RETARD"),
                   list(faits.lignes()))


def notes(faits: Faits) -> Reponse:
    if not faits.moyennes:
        return Reponse("notes", "Aucune note relevée pour l'instant.", list(faits.lignes()))
    lignes = []
    for mat, m in sorted(faits.moyennes.items(), key=lambda kv: -kv[1]["moy"]):
        t = f" {m['trend']}" if m["trend"] else ""
        lignes.append(f"{mat} : {m['moy']}/20{t}")
    return Reponse("notes", "Tes moyennes :\n" + "\n".join(lignes), list(faits.lignes()))


def cours(faits: Faits) -> Reponse:
    if not faits.cours_demain:
        return Reponse("cours", "Pas de cours demain.", list(faits.lignes()))
    return Reponse("cours", "Demain en cours :\n" + "\n".join(
        f"· {c['subject']} {c['start']}–{c['end']} en {c['room']}"
        for c in faits.cours_demain), list(faits.lignes()))


def annules(faits: Faits) -> Reponse:
    if not faits.annules:
        return Reponse("annules", "Aucun cours annulé.", list(faits.lignes()))
    return Reponse("annules", "Cours annulés :\n" + "\n".join(
        f"· {a['jour']} : {a['subject']}" for a in faits.annules[:8]),
        list(faits.lignes()))


def profs(faits: Faits) -> Reponse:
    if not faits.profs:
        return Reponse("profs", "Rien de neuf des profs ces 48 h.", list(faits.lignes()))
    return Reponse("profs", "Ce qu'ils ont dit :\n" + "\n".join(
        f"· {p['auteur']} — {court(p['titre'], 110)}" for p in faits.profs[:8]),
        list(faits.lignes()))


def en_ligne(faits: Faits) -> Reponse:
    ds = brain.a_envoyer_en_ligne(faits)
    if not ds:
        return Reponse("en_ligne", "Rien à rendre en ligne d'après ta liste.",
                       list(faits.lignes()))
    return Reponse("en_ligne", "À envoyer :\n" + "\n".join(
        "· " + d.ligne() for d in ds[:15]), list(faits.lignes()))


def controles(faits: Faits) -> Reponse:
    if not faits.controls:
        return Reponse("controles", "Aucun contrôle à venir.", list(faits.lignes()))
    return Reponse("controles", "Contrôles à venir :\n" + "\n".join(
        "· " + c["texte"] for c in faits.controls[:8]), list(faits.lignes()))


def quiz(faits: Faits, index: int = 0, reponse: str = "") -> Reponse:
    """Une question à la fois. On attend entre chaque, on corrige avec la
    réponse officielle — jamais une correction inventée."""
    qs = faits.quiz.get("questions") or []
    if not qs:
        return Reponse("quiz", "Pas de quiz aujourd'hui.", list(faits.lignes()),
                       suivi={"quiz_i": 0})
    if reponse and index > 0:
        off = qs[index - 1]
        corr = f"{off.get('a', '')}" if not reponse.strip() else reponse.strip()
        if off.get("a"):
            corr = f"{off.get('a')}"
        return Reponse("quiz", f"Réponse : {corr}", list(faits.lignes()),
                       suivi={"quiz_i": index})
    q = qs[min(index, len(qs) - 1)]
    return Reponse("quiz", f"Question {index + 1}/{len(qs)} — {q.get('q', '')}",
                   list(faits.lignes()), suivi={"quiz_i": index + 1})


def aide(faits: Faits) -> Reponse:
    return Reponse("aide",
                   "Tu peux me demander :\n"
                   "· quoi faire ce soir\n· j'ai quoi demain\n· combien de retards\n"
                   "· où j'en suis\n· mes notes\n· cours de demain / annulés\n"
                   "· ce qu'ont dit les profs\n· quoi rendre en ligne\n"
                   "· quiz · et « j'ai fait <matière> » pour barrer",
                   list(faits.lignes()))

def c_est_fait(faits: Faits, phrase: str, ecrire: bool = True) -> Reponse:
    r = brain.marquer(faits, phrase, ecrire=ecrire)

    if r["statut"] == "fait":
        return Reponse("fait",
                       f"C'est noté : {court(r['devoir'], 70)}. "
                       "Ça se verra à la prochaine sync Pronote (< 10 min).",
                       list(faits.lignes()), suivi={"marque": r["fp"]}, action="marque")
    if r["statut"] == "ambigu":
        return Reponse("ambigu",
                       "J'en vois plusieurs, c'est lequel ?\n" +
                       "\n".join("· " + c for c in r["candidats"][:8]),
                       list(faits.lignes()), suivi={"attente": "fait"})
    return Reponse("introuvable",
                   "J'ai trouvé aucun devoir qui colle à ça — dis-moi la matière, "
                   "ou « la suite des retards ».", list(faits.lignes()))


def en_fait_non(faits: Faits, phrase: str) -> Reponse:
    r = brain.decocher(faits, phrase)
    if r["statut"] == "decoche":
        return Reponse("decoche", f"Ok, je remets {court(r['devoir'], 70)}.",
                       list(faits.lignes()), action="decoche")
    if r["statut"] == "ambigu":
        return Reponse("ambigu", "Lequel ?\n" + "\n".join("· " + c for c in r["candidats"][:8]),
                       list(faits.lignes()), suivi={"attente": "decoche"})
    return Reponse("introuvable", "Je vois pas lequel decocher.", list(faits.lignes()))


# ─────────────────────────── le routeur ───────────────────────────

# Ordre IMPORTANT : la première regex qui matche gagne. Les intentions
# « c'est fait » passent AVANT « demain », sinon « j'ai fait l'espagnol de
# demain » cocherait au lieu de répondre.
REGLES: list[tuple[str, re.Pattern]] = [
    ("fait", re.compile(r"\b(j.?ai (fait|fini|termin|rendu|boucl)|c.?est (fait|bon|rendu|fini)|"
                        r"je l.?ai (fait|fini)|termin[ée]s?\b)")),
    ("decoche", re.compile(r"\b(pas fait|pas encore|en fait non|finalement non)\b")),
    ("chiffres", re.compile(r"combien|chiffre|total|nb de|nombre de")),
    ("ce_soir", re.compile(r"ce soir|ce soir la|par quoi|commenc|quoi faire|priorit")),
    ("quiz", re.compile(r"\bquiz\b|revis|revision|interroge moi")),
    ("notes", re.compile(r"\bnotes?\b|bulletin|moyenne|note d")),
    ("en_ligne", re.compile(r"rendre|en ligne|envoyer|depoter|remettre")),
    ("annules", re.compile(r"annul")),
    ("controles", re.compile(r"controle|evaluation|interro")),
    ("cours", re.compile(r"cours de|emploi du temps|edt|quand est")),
    ("profs", re.compile(r"prof|messag|info|Ils ont dit")),
    ("demain", re.compile(r"\bdemain\b|\bde demain\b")),
    ("aujourdhui", re.compile(r"aujourd.?hui|\bce jour\b|maintenant")),
    ("retards", re.compile(r"retard|en retard|pas fait depuis")),
    ("recap", re.compile(r"ou j.?en suis|recap|todo|ma liste|ou en est")),
    ("aide", re.compile(r"aide|help|tu sais faire|commandes")),
]


def router(message: str) -> str | None:
    b = sans_accents(message)
    for nom, rx in REGLES:
        if rx.search(b):
            return nom
    return None


def repondre(faits: Faits, message: str, session: dict | None = None) -> Reponse:
    """Route le message et renvoie la réponse déterministe + son contexte."""
    session = session or {}
    intention = router(message)

    # le bot était en train de demander WHICH devoir, et l’élève a répondu
    # par la matière / la date : on ne lâche pas la conversation
    if session.get("attente") in ("fait", "decoche") and intention in (None, "demain",
                                                                    "aujourdhui", "retards"):
        cible = re.sub(r"\b(le|la|les|un|une|c est|cest|celui de|celle de)\b", " ", message)
        return (c_est_fait(faits, cible) if session["attente"] == "fait"
                else en_fait_non(faits, cible))

    if session.get("quiz_i") and (intention == "quiz" or intention is None):
        r = quiz(faits, max(0, session["quiz_i"] - 1), reponse=message)
        r.suivi["quiz_i"] = session["quiz_i"] + 1
        return r

    table = {
        "chiffres": chiffres, "demain": demain, "ce_soir": ce_soir, "recap": recap,
        "retards": retards, "notes": notes, "cours": cours, "annules": annules,
        "profs": profs, "en_ligne": en_ligne, "controles": controles, "aide": aide,
    }
    if intention == "fait":
        return c_est_fait(faits, message)
    if intention == "decoche":
        return en_fait_non(faits, message)
    if intention == "aujourdhui":
        ds = faits.bucket("AUJOURDHUI")
        txt = ("Aujourd'hui :\n" + "\n".join("· " + d.ligne() for d in ds)) if ds \
            else "Rien pour aujourd'hui."
        return Reponse("aujourdhui", txt, list(faits.lignes()))
    fn = table.get(intention or "")
    if fn:
        return fn(faits)
    return Reponse("inconnu",
                   "J'ai pas capté, là. Tape « aide » et je te liste ce que je sais faire.",
                   list(faits.lignes()))