"""CLI — le bot en mode « je teste sans passer par Telegram ».

    pote ask « combien de retards »
    pote matin           # le point du matin
    pote relance         # la relance retard (silencieuse si rien a dire)
    pote quiz            # question 1 du quiz du soir
    pote lessons         # rejoue les corrections, affiche le rapport
    pote doctor          # etat : sync, donnees, file d'attente, LLM

Toute action qui parle a l’élève passe par ``dire()`` — le meme chemin que le
bot, donc le meme code de livraison.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import brain, compose, guard, lessons, llm, tgbot


def _fait(sortie: str, texte: str) -> None:
    if sortie == "json":
        print(json.dumps({"texte": texte}, ensure_ascii=False, indent=2))
    else:
        print(texte)


def cmd_ask(args) -> int:
    faits = brain.construire()
    det = compose.repondre(faits, args.message, {})
    if args.deterministe:
        _fait(args.sortie, det.texte)
        return 0
    if det.intention in tgbot.JAMAIS_LLM:
        _fait(args.sortie, det.texte)
        return 0
    texte, rejet = llm.mettre_en_mots(det.intention, det.faits, det.texte, faits)
    if rejet and args.verbose:
        print(f"[rejeté] {rejet}", file=sys.stderr)
    _fait(args.sortie, texte)
    return 0


def cmd_matin(args) -> int:
    texte = tgbot.point_du_matin()
    if args.envoyer:
        return 0 if tgbot.dire(texte) else 1
    _fait(args.sortie, texte)
    return 0


def cmd_relance(args) -> int:
    texte = tgbot.relancer_retard(force=args.force)
    if not texte:
        print("(rien à relancer)", file=sys.stderr)
        return 0
    if args.envoyer:
        return 0 if tgbot.dire(texte) else 1
    _fait(args.sortie, texte)
    return 0


def cmd_quiz(args) -> int:
    texte = tgbot.quiz_du_soir()
    if not texte:
        print("(pas de quiz aujourd'hui)", file=sys.stderr)
        return 0
    if args.envoyer:
        return 0 if tgbot.dire(texte) else 1
    _fait(args.sortie, texte)
    return 0


def cmd_lessons(args) -> int:
    texte = tgbot.rapport_apprentissage()
    if args.envoyer:
        return 0 if tgbot.dire(texte) else 1
    _fait(args.sortie, texte)
    return 0


def cmd_push(args) -> int:
    n = tgbot.pousser_evenements()
    print(f"{n} événement(s) poussé(s)")
    return 0


def cmd_doctor(args) -> int:
    faits = brain.construire()
    sante = brain.lire("health.json", {})
    attente = brain.lire_avec_defaut(brain.INBOX, [])
    lignes = [
        f"état :     {len(faits.todo)} à faire · {faits.chiffres['retard']} en retard",
        f"dernier sync : {sante.get('last_ok', '—')} (échecs : {sante.get('failures', 0)})",
        f"file d'attente : {len(attente)} op(s) en attente de Pronote",
        f"quiz :     {len(faits.quiz.get('questions') or [])} question(s) aujourd'hui",
        f"leçons :   {len(lessons.actives())} active(s)",
    ]
    try:
        llm._post([{"role": "user", "content": "ping"}], max_tokens=5)
        lignes.append(f"modèle :   OK ({llm.MODELE} sur {llm.BASE})")
    except Exception as e:
        lignes.append(f"modèle :   INDISPONIBLE ({type(e).__name__}) — réponses déterministes")
    try:
        tgbot.charger_token()
        lignes.append(f"telegram : jeton présent, chat {tgbot.CHAT}")
    except SystemExit:
        lignes.append("telegram : PAS DE JETON — remplis tg.env")
    print("\n".join(lignes))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pote", description="Bot Pote — les devoirs de l’élève")
    p.add_argument("--sortie", choices=["texte", "json"], default="texte")
    s = p.add_subparsers(dest="cmd", required=True)

    a = s.add_parser("ask"); a.add_argument("message")
    a.add_argument("--deterministe", action="store_true")
    a.add_argument("--verbose", action="store_true")
    a.set_defaults(fn=cmd_ask)

    for nom, fn, besoin in (("matin", cmd_matin, False), ("relance", cmd_relance, True),
                            ("quiz", cmd_quiz, False), ("lessons", cmd_lessons, False)):
        q = s.add_parser(nom); q.add_argument("--envoyer", action="store_true")
        if besoin:
            q.add_argument("--force", action="store_true")
        q.set_defaults(fn=fn)

    s.add_parser("push").set_defaults(fn=cmd_push)
    s.add_parser("doctor").set_defaults(fn=cmd_doctor)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())