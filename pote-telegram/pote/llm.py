"""Le modèle, en cage.

Il ne fait QUE deux choses : mettre les faits en mots, et fixer le ton de pote.
Trois garde-fous, dans cet ordre :

  1. le prompt ne contient QUE ``faits`` (les lignes autorisées) — pas de
     contexte, pas de conversation précédente, rien qui puisse l'inciter ;
  2. la réponse est relue par ``guard.verifier`` : un chiffre ou une matière
     hors faits -> réponse jetée ;
  3. au second rejet, on ne réessaie pas : on part sur le texte déterministe,
     qui est exact par construction.

Modèle : opencode2api local (127.0.0.1:8000), alias space-bunny. Pas de clé,
pas de réseau sortant, pas de quota.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from . import guard
from .brain import Faits

BASE = os.environ.get("POTE_LLM_URL", "http://127.0.0.1:8000/v1")
MODELE = os.environ.get("POTE_LLM_MODEL", "space-bunny")
TIMEOUT = int(os.environ.get("POTE_LLM_TIMEOUT", "25"))

SYSTEME = """Tu es Pote, le pote de l’élève pour les devoirs du collège.
Tutoiement, français, phrases courtes comme des textos, une emoji de temps en
temps. Jamais scolaire, jamais de morale, jamais de « n'oublie pas ».

Règles absolues :
· Tu n'inventes RIEN. Tout ce que tu dis est écrit dans le bloc FAITS.
· Tu ne comptes pas de tête : si un nombre n'est pas écrit dans FAITS, tu ne
  l'écris pas. Les nombres de FAITS sont exacts, cite-les tels quels.
· Un message de prof n'est pas un devoir. Une info n'est pas un devoir.
· Tu ne promets aucune action que tu n'as pas déjà faite. Si FAITS dit qu'une
  action est notée, tu peux dire « c'est noté ». Sinon, tu dis ce que tu sais.
· Maximum 12 lignes. Pas de tableau, pas de tirets multiples par ligne.

Réponds UNIQUEMENT avec le texte à envoyer, sans préface et sans commentaire."""


def _post(messages: list, max_tokens: int = 400) -> str:
    req = urllib.request.Request(
        BASE.rstrip("/") + "/chat/completions",
        data=json.dumps({"model": MODELE, "messages": messages,
                         "max_tokens": max_tokens, "temperature": 0.4}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "curl/8.5.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)["choices"][0]["message"]["content"] or ""


def mettre_en_mots(intention: str, faits: list, texte_fait: str,
                   faits_obj: Faits) -> tuple[str, list[str]]:
    """Renvoie (texte_à_envoyer, fautifs).

    ``texte_fait`` est la réponse déterministe : elle sert de repli et de
    gabarit. Le modèle ne la voit PAS dans le prompt (il verrait la réponse
    toute faite) — il reçoit seulement les faits, puis sa réponse est confrontée
    à la vérité.
    """
    bloc = "\n".join(f"- {l}" for l in faits[:120])
    try:
        brut = _post([
            {"role": "system", "content": SYSTEME},
            {"role": "user", "content":
                f"Intention de la question : {intention}\n\n"
                f"FAITS (seule source autorisée) :\n{bloc}\n\n"
                "Mets ça en mots, ton de pote, pour l’élève."},
        ])
    except Exception as e:                                    # réseau, timeout, 5xx
        return texte_fait, [f"llm indisponible : {type(e).__name__}"]

    propre = _nettoyer(brut)
    fautifs = guard.verifier(propre, faits_obj)
    if fautifs:
        return texte_fait, fautifs
    return propre, []


def _nettoyer(s: str) -> str:
    s = re.sub(r"<think>.*?</think>", "", s or "", flags=re.S)
    s = re.sub(r"<(im_end|endoftext)>", "", s)
    s = s.strip().strip("`")
    return s