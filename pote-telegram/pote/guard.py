"""Validateur d'ancrage — le mur qui arrête les inventions.

Le modèle ne fait QUE mettre en mots des faits déjà calculés par brain.py.
Rien ne l'empêche techniquement de sortir « AMC 2 » ou d'annoncer « 23 retards »
alors qu'il y en a 27 — sauf CECI :

  1. on extrait de sa réponse les nombres de compte et les sigles de matière ;
  2. on les confronte aux faits autorisés (Faits.lignes()) ;
  3. au moindre fait inconnu, on JETTE sa réponse et on part sur la réponse
     déterministe, qui est exacte par construction.

C'est le seul mécanisme qui tient : une consigne écrite dans un prompt
(« n'invente pas ») est déjà demonstrablement insuffisante sur cette machine.
"""
from __future__ import annotations

import re

from . import brain

# Nombres qui ne sont pas des « comptes » : volumes de phrases, années.
BENIGNES = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "20", "30",
            "60", "100", "2026", "2027"}
# Une heure « 08h00 », une durée « 20 minutes », « 1h30 » : pas un compte.
MOTIF_HEURE = re.compile(r"\b\d{1,2}[h:]\d{2}\b|\b\d{1,2}\s?(?:h|min|heures?|minutes?)\b", re.I)
# Numérotation de liste (« 1. », « 2) ») : des ordinals, pas des totaux.
MOTIF_LISTE = re.compile(r"^\s*\d+[.)]\s", re.M)
# Un sigle de matière, tel que Pronote les écrit : AMC 2, SENC, LLC ANGL…
MOTIF_SIGLE = re.compile(r"\b[A-ZÉÈÀÙÂÊÎÔÛÇ][A-ZÉÈÀÙÂÊÎÔÛÇ0-9&.'\-]{2,}\b")
# Mots en capitales qui ne sont pas des matières : la phrase reste du français.
# Les TITRES DE SECTION du bot comptent — « AUJOURD'HUI », « EN RETARD » sont
# des en-têtes, pas des matières inventées.
STOP_SIGLES = {
    "BONJOUR", "SALUT", "YO", "OK", "PDF", "SMS", "TV", "BAC", "BREVET",
    "MATH", "MATHS", "PHYS", "PHILO", "HIST", "GEO", "SVT", "ANG", "ESP",
    "HIPP", "EMC", "EPS", "SI", "NSI", "SNT", "TATTO",
    "PROF", "PROFS", "PROFESSEUR", "CLASSE", "INFO", "AIDE",
    "COURS", "DEVOIR", "DEVOIRS", "NOTES", "NOTE", "MOYENNE", "MOYENNES",
    "BULLETIN", "QUIZ", "SOIR", "DEMAIN", "RETARD", "PLUS", "TARD", "FAIT",
    "FAITS", "AUJOURDHUI", "AUJOURD'HUI", "ANNULES", "ANNULÉS", "ANNULE",
    "CONTROLE", "CONTRÔLE", "CONTRÔLES", "MATIERE", "MATIÈRE",
}


def nombres_de_compte(texte: str) -> set:
    """Les nombres qui pourraient être un total faux (« 23 retards »)."""
    sans = MOTIF_LISTE.sub("", texte)
    sans = MOTIF_HEURE.sub(" ", sans)
    return set(re.findall(r"\d+", sans)) - BENIGNES


def sigles_cites(texte: str) -> set:
    """Sigles en capitales : c'est sous cette forme qu'apparaissent les
    inventions (« AMC 2 », « SENC »), que Pronote n'a jamais vus."""
    trouves = set()
    for m in MOTIF_SIGLE.finditer(texte):
        sigle = m.group(0).strip(" .-")
        if len(sigle) < 3 or sigle in STOP_SIGLES:
            continue
        trouves.add(sigle)
    return trouves


def verifier(texte: str, faits: brain.Faits) -> list:
    """Renvoie les faits NON ANCRÉS de la réponse (vide = recevable)."""
    if not texte or not texte.strip():
        return ["réponse vide"]

    lisibles = " ".join(faits.lignes())
    lisibles_b = brain.sans_accents(lisibles)
    autorises = {brain.sans_accents(str(v)) for v in faits.chiffres.values()}
    autorises |= {brain.sans_accents(str(m["moy"])) for m in faits.moyennes.values()}
    for d in faits.todo:
        if d.due:
            autorises |= {brain.sans_accents(d.due),
                          brain.sans_accents(d.due.replace("-", "/"))}
    for c in faits.controls:
        autorises |= {brain.sans_accents(str(c["j"])), brain.sans_accents(c["due"])}

    fautifs = []
    for n in sorted(nombres_de_compte(texte)):
        nn = brain.sans_accents(n)
        if nn in autorises or nn in lisibles_b:
            continue
        fautifs.append(f"chiffre non ancré : {n}")

    for sigle in sorted(sigles_cites(texte)):
        if brain.sans_accents(sigle) in lisibles_b:
            continue
        fautifs.append(f"matière hors faits : {sigle}")
    return fautifs


def nettoyer(balises: str) -> str:
    """Telegram HTML -> texte nu, pour que le validateur ne lise pas du balisage."""
    s = re.sub(r"<[^>]+>", " ", balises or "")
    return (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&#39;", "'"))