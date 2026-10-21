"""Le bot Telegram : un seul consommateur getUpdates, un seul mot.

Il parle a l’élève en prive. Il ne touche JAMAIS a Pronote (pronote-sync est le
seul), et n ecrit dans ses donnees que par la boite a ops ``brain.marquer()``.

Il est autonome : il pousse les nouveaux evenements au fil de l eau (drain de
l archive ``events.log``), il fait le point du matin, relance le retard au bon
moment, et rejoue ses propres erreurs chaque nuit.
"""
from __future__ import annotations

import json
import os
import signal
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from . import brain, compose, lessons, llm
from .brain import court

EVENTS_NOM = "events.log"
TOKEN = ""
CHAT = ""
_stop = False


# ─────────────────────────── les fichiers ───────────────────────────
# Résolus à chaque appel : c'est ce qui rend le daemon testable sur un état de
# synthèse, et ce qui évite un module figé au premier import.

def racine() -> Path:
    return Path(os.environ.get("POTE_DATA", Path.home() / ".local/share/pote-tg"))


def chemin(nom: str) -> Path:
    return racine() / nom


def env_file() -> Path:
    return Path(os.environ.get("POTE_ENV", Path.home() / ".local/share/pote-tg/tg.env"))


# ─────────────────────────── transport ───────────────────────────

def charger_token() -> None:
    """Le jeton ne vit ni dans le code ni dans l unit systemd (lisible par
    tout le monde) : il est lu au demarrage depuis un fichier 0600."""
    global TOKEN, CHAT
    f = env_file()
    if f.exists():
        for ligne in f.read_text().splitlines():
            if "=" not in ligne or ligne.lstrip().startswith("#"):
                continue
            k, v = ligne.split("=", 1)
            if k.strip() == "POTE_TG_TOKEN":
                TOKEN = v.strip()
            elif k.strip() == "POTE_TG_CHAT":
                CHAT = v.strip()
    if not TOKEN or not CHAT:
        raise SystemExit(f"jeton/chat manquant — remplis {f}")


def api(method: str, **params) -> dict:
    """Une seule porte vers Telegram : tout le reste passe par là."""
    data = urllib.parse.urlencode({k: v for k, v in params.items()
                                   if v is not None}).encode()
    req = urllib.request.Request("https://api.telegram.org/bot" + TOKEN + "/" + method,
                                 data=data)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"ok": False, "error_code": e.code,
                "description": e.read().decode(errors="replace")[:300]}
    except Exception as e:
        return {"ok": False, "description": f"{type(e).__name__}: {e}"}


def html(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def decouper(texte: str, lim: int = 3800) -> list:
    out, cur = [], ""
    for ligne in texte.split("\n"):
        if cur and len(cur) + len(ligne) + 1 > lim:
            out.append(cur)
            cur = ""
        cur += ligne + "\n"
    if cur.strip():
        out.append(cur.strip())
    return out or [texte[:lim]]


def envoyer(texte: str, repondre_a: int | None = None) -> bool:
    """Renvoie la VRAIE reponse de Telegram, jamais un « c est parti ».

    Si le HTML est refuse (balisage casse par le modele), on renvoie le texte
    nu : mieux vaut un message sans gras qu un message perdu.
    """
    for ligne in decouper(texte):
        r = api("sendMessage", chat_id=CHAT, text=html(ligne), parse_mode="HTML",
                disable_web_page_preview=True, reply_to_message_id=repondre_a)
        if r.get("ok"):
            continue
        r2 = api("sendMessage", chat_id=CHAT, text=ligne[:3800],
                 disable_web_page_preview=True, reply_to_message_id=repondre_a)
        if r2.get("ok"):
            continue
        print(f"[tg] envoi refusé : {r.get('description')}", flush=True)
        return False
    return True


# ─────────────────────────── session ───────────────────────────

def _sessions() -> dict:
    return brain.lire_avec_defaut(chemin("session.json"), {})


def _sauver_session(sessions: dict) -> None:
    racine().mkdir(parents=True, exist_ok=True)
    p = chemin("session.json")
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(sessions, ensure_ascii=False))
    tmp.replace(p)


# ─────────────────────────── repondre ───────────────────────────

# Intentions que le modele n a pas le droit de toucher : comptes, listes de
# matieres, ciblage de devoir. C est precisement la qu il a invente « AMC 2 »
# et annonce « 23 retards » au lieu de 27.
JAMAIS_LLM = {"chiffres", "recap", "retards", "fait", "decoche", "ambigu",
              "introuvable", "aide", "inconnu"}


def repondre(message: str, cle: str) -> tuple:
    """Route deterministe -> mise en mots -> garde-fou -> journal."""
    faits = brain.construire()
    sessions = _sessions()
    session = sessions.get(cle, {})

    det = compose.repondre(faits, message, session)
    suivi = dict(session)
    suivi.update({k: v for k, v in det.suivi.items() if v is not None})
    suivi.pop("marque", None)
    sessions[cle] = suivi
    _sauver_session(sessions)

    rejet = []
    if det.intention in JAMAIS_LLM:
        texte = det.texte
    else:
        texte, rejet = llm.mettre_en_mots(det.intention, det.faits, det.texte, faits)
        if rejet:
            print(f"[guard] « {message[:40]} » rejete : {rejet}", flush=True)
            texte = det.texte          # pas de 2e essai : on part sur l exact

    lessons.noter(message, texte, det.intention)
    return texte, {"intention": det.intention, "rejet": rejet}


# ─────────────────────────── drain d evenements ───────────────────────────

def _evenements() -> list:
    journal = brain.state_dir() / EVENTS_NOM
    if not journal.exists():
        return []
    depuis = ""
    try:
        depuis = chemin("dernier_push").read_text().strip()
    except OSError:
        pass
    lignes = []
    for brute in journal.read_text(errors="replace").splitlines():
        brute = brute.strip()
        if not brute.startswith("{"):
            continue
        try:
            ev = json.loads(brute)
        except ValueError:
            continue
        if depuis and str(ev.get("ts", "")) <= depuis:
            continue
        lignes.append(ev)
    return lignes


def pousser_evenements() -> int:
    """Reprend events.log et annonce ce qui est tombe depuis le dernier envoi.

    events.log est l ARCHIVE (append-only) ecrite par pronote_sync : c est la
    seule source qui survit a un bot en panne. On compare sur le timestamp,
    jamais sur la taille du fichier : un fichier tronque se rattrape au
    prochain cycle, un offset faux perd des messages a jamais.
    """
    lignes = _evenements()
    if not lignes:
        return 0

    texte = ["Yo, ça vient de tomber sur Pronote :"]
    for ev in lignes[:6]:
        t = ev.get("type")
        if t == "new_hw":
            h = ev["hw"]
            tag = ("en retard" if (h.get("due") and h["due"] < date.today().isoformat())
                   else "pour le " + str(h.get("due") or "quand"))
            texte.append(f"· {h['subject']} : {court(h.get('detail') or '', 70)} ({tag})")
        elif t == "new_msg":
            m = ev["msg"]
            texte.append(f"· {m['creator']} a écrit : {court(m.get('preview') or '', 90)}")
        elif t == "new_info":
            texte.append("· info : " + court(ev["info"]["titre"], 80))
        elif t == "new_annul":
            a = ev["annul"]
            texte.append(f"· cours annulé : {a['subject']} le {a['jour']}")
        elif t == "new_ressource":
            texte.append("· contenu en ligne : " + court(ev["lesson"]["titre"], 70))
        elif t == "new_grade":
            g = ev["grade"]
            texte.append(f"· note : {g['subject']} {g['grade']}/{g['out_of']}")
    if len(texte) == 1:
        return 0
    if not envoyer("\n".join(texte)):
        return 0
    racine().mkdir(parents=True, exist_ok=True)
    chemin("dernier_push").write_text(max(str(ev.get("ts", "")) for ev in lignes))
    return len(lignes)


# ─────────────────────────── actions autonomes ───────────────────────────

def point_du_matin() -> str:
    faits = brain.construire()
    n, d = faits.chiffres["retard"], faits.chiffres["demain"]
    if not faits.bucket("RETARD") and not d:
        tete = "Debout ! Rien pour demain, et zéro retard. Nice."
    else:
        tete = f"Debout ! {n} en retard, {d} pour demain."
    return tete + "\n\n" + compose.ce_soir(faits).texte


def relancer_retard(force: bool = False, quand: date | None = None) -> str | None:
    """UNE relance par devoir et par jour, jamais le week-end ni en vacances.

    La regle vit dans relances.json, pas dans la tete du modele : c est
    precisement ce qui a deja produit douze relances le meme jour.
    """
    jour = quand or date.today()
    if not force and (jour.weekday() >= 5 or brain.en_vacances(jour)):
        return None
    faits = brain.construire(quand=jour)
    cibles = faits.bucket("RETARD")[:3]
    if not cibles:
        return None
    etat = brain.lire_avec_defaut(chemin("relances.json"), {})
    a_faire = [d for d in cibles if etat.get(d.fp, {}).get("jour") != jour.isoformat()]
    if not a_faire:
        return None
    for d in a_faire:
        etat[d.fp] = {"jour": jour.isoformat()}
    racine().mkdir(parents=True, exist_ok=True)
    chemin("relances.json").write_text(json.dumps(etat, ensure_ascii=False))
    return ("T'as du retard qui traîne :\n" +
            "\n".join("· " + d.ligne() for d in a_faire) +
            "\n\nOn en fait un ou pas ?")


def quiz_du_soir() -> str | None:
    faits = brain.construire()
    return compose.quiz(faits, 0).texte if faits.quiz.get("questions") else None


def rapport_apprentissage() -> str:
    """Ce que le bot a compris de ses erreurs — et ce qu il n a PAS su faire."""
    r = lessons.consolider()
    txt = f"{r['rejouees']} correction(s) rejouée(s), {r['reussies']} réussie(s)."
    if lessons.actives():
        txt += "\n\nCe que j'ai retenu :\n" + "\n".join(
            "· " + court(l["phrase"], 70) for l in lessons.actives()[:5])
    inap = [l for l in lessons._lire_jsonl(lessons.lecons())
            if l.get("etat") == "inappliquee"]
    if inap:
        txt += "\n\nEncore raté :\n" + "\n".join(
            "· " + court(l["phrase"], 70) for l in inap[:5])
    return txt


def dire(texte: str) -> bool:
    racine().mkdir(parents=True, exist_ok=True)
    return envoyer(texte)


# ─────────────────────────── la boucle ───────────────────────────

def _arret(*_a):
    global _stop
    _stop = True


def _commande(texte: str) -> str:
    mots = texte.split(None, 1)
    cmd = mots[0][1:].split("@")[0].lower()
    reste = mots[1] if len(mots) > 1 else ""
    if cmd in ("fait", "done") and reste:
        return reste          # /fait espagnol LV2 -> le ciblage fait son travail
    return {
        "aide": "aide", "help": "aide", "sync": "où j'en suis",
        "moins": "combien de retards", "retard": "combien de retards",
        "demain": "j'ai quoi demain", "soir": "quoi faire ce soir",
        "notes": "mes notes", "quiz": "quiz", "profs": "les profs ont dit quoi",
        "cours": "cours de demain", "annules": "cours annulés",
    }.get(cmd, "aide")


def traiter(u: dict) -> None:
    msg = u.get("message") or u.get("edited_message") or {}
    chat = msg.get("chat") or {}
    if str(chat.get("id")) != str(CHAT):
        return
    texte = (msg.get("text") or "").strip()
    if not texte:
        return
    if texte.startswith("/start"):
        envoyer(compose.aide(brain.construire()).texte, msg.get("message_id"))
        return
    if texte.startswith("/"):
        texte = _commande(texte)
    texte_sorti, info = repondre(texte, str(chat["id"]))
    envoyer(texte_sorti, repondre_a=msg.get("message_id"))
    print(f"[tg] « {texte[:40]} » -> {info}", flush=True)


def amorcer() -> int:
    """Aligne l'offset sur le dernier update_id SANS rien traiter.

    Le jeton peut porter un arrière de message que Pote n'a jamais vu.
    Répondre à un backlog d'il y a trois jours serait pire que de le perdre.
    """
    try:
        offset = int(chemin("tg_offset").read_text().strip() or 0)
    except (OSError, ValueError):
        offset = 0
    if offset:
        return offset
    r = api("getUpdates", offset=-1, limit=1, timeout=0,
            allowed_updates=json.dumps(["message", "edited_message"]))
    if r.get("ok") and r.get("result"):
        offset = int(r["result"][-1]["update_id"]) + 1
        print(f"[tg] amorçage : offset {offset} (backlog ignoré)", flush=True)
    racine().mkdir(parents=True, exist_ok=True)
    chemin("tg_offset").write_text(str(offset))
    return offset


def boucle() -> None:
    signal.signal(signal.SIGTERM, _arret)
    signal.signal(signal.SIGINT, _arret)
    offset = amorcer()
    print(f"[tg] démarrage — chat {CHAT}, offset {offset}", flush=True)
    dernier_drain = time.time()
    dernier_409 = 0.0
    while not _stop:
        try:
            r = api("getUpdates", offset=str(offset), timeout=30,
                    allowed_updates=json.dumps(["message", "edited_message"]))
            if not r.get("ok"):
                if r.get("error_code") == 409:
                    # Un AUTRE consommateur tient le jeton : les messages se
                    # partageraient au hasard. On le dit fort, une fois par
                    # minute, au lieu de boucler en silence à 1 Hz.
                    if time.time() - dernier_409 > 60:
                        dernier_409 = time.time()
                        print("[tg] ERREUR 409 — un autre bot poll déjà ce jeton ; "
                              "Pote ne répond qu'une fois l'autre arrêté.", flush=True)
                else:
                    print(f"[tg] getUpdates refusé : {r.get('description')}", flush=True)
                time.sleep(10)
                continue
            if r.get("result"):
                for u in r["result"]:
                    offset = int(u.get("update_id", 0)) + 1
                    traiter(u)
                chemin("tg_offset").write_text(str(offset))
        except Exception as e:
            print(f"[tg] getUpdates: {type(e).__name__}: {e}", flush=True)
            time.sleep(5)
        if time.time() - dernier_drain > 300:
            dernier_drain = time.time()
            try:
                n = pousser_evenements()
                if n:
                    print(f"[tg] {n} événement(s) poussé(s)", flush=True)
            except Exception as e:
                print(f"[tg] drain: {type(e).__name__}: {e}", flush=True)
        time.sleep(1)
    print("[tg] arrêt", flush=True)


if __name__ == "__main__":
    charger_token()
    boucle()