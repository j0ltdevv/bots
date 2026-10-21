"""Pote — moteur de faits déterministe.

Aucune invention possible ici : ce module ne fait que LIRE state/ et CALCULER.
Le LLM, plus loin, ne fait que mettre ces faits en mots ; s'il sort un fait
absent de ``Faits.lignes()``, le validateur le rejette et la réponse
déterministe part à la place.

C'est la réponse directe aux pannes historiques de ce bot :
  · « AMC 2 », « SENC », « le bac blanc » : rien de tout ça n'existait ;
  · « 23 devoirs en retard » alors qu'il y en avait 27 : il comptait de tête ;
  · « j'ai barré le travail d'espagnol » sans avoir rien écrit : promesse en
    l'air — ici ``marquer()`` ÉCRIT dans done-inbox.json et relit le fichier
    pour le prouver.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path


def state_dir() -> Path:
    """Le répertoire d'état, résolu À CHAQUE APPEL. C'est ce qui rend le
    cerveau testable sur un état de synthèse : les devoirs de l’élève ne
    doivent jamais décider du résultat d'un test."""
    return Path(os.environ.get("POTE_STATE",
                               Path.home() / ".local/share/pronote-sync/state"))


def inbox() -> Path:
    return Path(os.environ.get(
        "POTE_INBOX",
        Path.home() / ".openmausbot/workspaces"
                       "/cef33777-3fea-40f6-9b16-5fb01f6b4c1e/done-inbox.json"))


def _lock() -> Path:
    return Path(os.environ.get("POTE_LOCK", Path.home() / ".local/share/pote-tg/inbox.lock"))


JOURS = {"lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
         "vendredi": 4, "samedi": 5, "dimanche": 6}

# Un devoir « contrôle » : c'est ce qui doit remonter en priorité.
CTRL_RE = re.compile(
    r"contr[ôo]le|interrogation|interro\b|\btest\b|[ée]valuation"
    r"|devoir sur table|recopier le cours|apprendre le cours", re.I)
# Un devoir qui implique un ENVOI (« à rendre en ligne »).
ENLIGNE_RE = re.compile(
    r"quiziniere|quizini[eè]re|envoyer|envoie|rendre|remettre|sur table"
    r"|en ligne|d[ée]poser|upload|à remettre", re.I)

VACANCES = [
    ("2026-10-17", "2026-11-02", "Toussaint"),
    ("2026-12-19", "2027-01-04", "Noël"),
    ("2027-02-13", "2027-03-01", "hiver"),
    ("2027-04-10", "2027-04-26", "printemps"),
]


# ─────────────────────────────── helpers ───────────────────────────────

def sans_accents(s: str) -> str:
    """« ESPAGNOL LV2 » -> « espagnol lv2 », « j'ai » -> « j ai ».

    Les ESPACES sont conservés : tous les motifs du projet s'appuient sur des
    frontières de mots. Les apostrophes deviennent un espace parce qu'un
    téléphone écrit « jai fait » : un motif exigeant la ponctuation perdait
    des devoirs en silence.
    """
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[’ʼ']+", " ", s).split())


def mots(s: str) -> list:
    return sans_accents(s).split()


def court(s: str, n: int = 70) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def lire(nom: str, defaut):
    p = state_dir() / nom
    try:
        return json.loads(p.read_text()) if p.exists() else defaut
    except (ValueError, OSError):
        return defaut


def lire_avec_defaut(p: Path, defaut):
    try:
        return json.loads(p.read_text()) if p.exists() else defaut
    except (ValueError, OSError):
        return defaut


def _nombre_fr(s: str) -> str:
    """« 3,5 » -> 3.5 pour le calcul ; '' si ce n'est pas un nombre."""
    try:
        return str(float(str(s).replace(",", ".").strip()))
    except ValueError:
        return ""


def en_vacances(quand: date) -> str:
    iso = quand.isoformat()
    for debut, fin, nom in VACANCES:
        if debut <= iso <= fin:
            return nom
    return ""


def _rad_commun(a: str, b: str, n: int = 4) -> bool:
    """« maths » et « MATHEMATIQUES » partagent « math » -> même matière.

    Quatre lettres suffisent : en dessous, « les cours » attraperaient
    « court ». Au-dessus, « anglais » ne rejoint plus « anglais lv2 ».
    """
    return a[:n] == b[:n] and len(a) >= n and len(b) >= n


def nomme_matiere(phrase: str, matiere: str) -> bool:
    """« j'ai fait l'espagnol » nomme-t-il « ESPAGNOL LV2 » ?

    Deux portes, dans cet ordre :
      · la matière en toutes lettres (« anglais lv2 ») ;
      · sinon le MOT DE TÊTE par radical (« espagnol », « anglais »).
    Deux matières qui partagent ce mot (« ANGLAIS LV1 » et « ANGLAIS LV2 »)
    remontent toutes les deux — c'est voulu : il faut demander plutôt que
    cocher au hasard.
    """
    pm, mm = mots(phrase), mots(matiere)
    if not mm:
        return False
    if len(mm) > 1 and len(pm) >= len(mm) and pm[-len(mm):] == mm:
        return True
    tete = mm[0]
    if tete in pm:
        return True
    return any(_rad_commun(tete, mot) for mot in pm if len(mot) >= 4)

@dataclass
class Devoir:
    fp: str
    subject: str
    detail: str
    due: str
    files: list = field(default_factory=list)
    premier_pas: str = ""
    bucket: str = "PLUS_TARD"

    @property
    def cle(self) -> str:
        return f"{self.subject} — {court(self.detail, 40)}"

    def ligne(self) -> str:
        pj = f" 📎{len(self.files)}" if self.files else ""
        due = f" pour le {self.due}" if self.due else ""
        return f"{self.subject}{pj} : {court(self.detail, 80)}{due}"


@dataclass
class Faits:
    aujourdhui: date
    todo: list          # Devoir — retard, aujourd'hui, demain, plus tard
    chiffres: dict
    moyennes: dict      # matière -> {moy, trend, notes}
    cours_demain: list
    annules: list
    profs: list
    quiz: dict
    controls: list
    faits_recents: list

    def bucket(self, nom: str) -> list:
        return [d for d in self.todo if d.bucket == nom]

    def lignes(self) -> list:
        """Toutes les chaînes autorisées — le garde-fou du LLM."""
        out = [str(v) for v in self.chiffres.values()]
        out += [d.ligne() for d in self.todo]
        out += [court(d.premier_pas, 120) for d in self.todo if d.premier_pas]
        out += [d.subject for d in self.todo]
        out += [m for m in self.moyennes.values() if isinstance(m, str)]
        out += [str(m["moy"]) for m in self.moyennes.values()]
        out += [c.get("subject", "") for c in self.cours_demain]
        out += [c.get("start", "") for c in self.cours_demain]
        out += [c.get("room", "") for c in self.cours_demain]
        out += [a.get("subject", "") for a in self.annules]
        out += [a.get("jour", "") for a in self.annules]
        out += [p.get("auteur", "") for p in self.profs]
        out += [court(p.get("titre", ""), 90) for p in self.profs]
        out += [court(p.get("corps", ""), 200) for p in self.profs]
        out += [c["texte"] for c in self.controls]
        out += list(self.faits_recents)
        return [o for o in out if str(o).strip()]


def construire(quand: date | None = None) -> Faits:
    """Lit state/ et calcule TOUT. Aucun réseau, aucun modèle."""
    aujourdhui = quand or date.today()
    state = lire("state.json", {}) or {}
    done = lire("done.json", {}) or {}
    grades = lire("grades.json", {}) or {}
    annules = lire("annules.json", {}) or {}
    msgs = lire("msgs.json", {}) or {}
    quiz = lire("quiz.json", {}) or {}
    cours_notes = lire("lessons.json", {}) or {}
    cours = lire("cours.json", []) or []
    fiches = lire("fiches.json", {}) or {}

    demain = (aujourdhui + timedelta(days=1)).isoformat()

    todo: list[Devoir] = []
    for fp, v in state.items():
        if v.get("done") or fp in done:
            continue
        due = v.get("date") or ""
        if due and due < aujourdhui.isoformat():
            bucket = "RETARD"
        elif due == aujourdhui.isoformat():
            bucket = "AUJOURDHUI"
        elif due == demain:
            bucket = "DEMAIN"
        else:
            bucket = "PLUS_TARD"
        todo.append(Devoir(fp=fp, subject=v.get("subject") or "?",
                           detail=v.get("detail") or "", due=due,
                           files=v.get("files") or [],
                           premier_pas=v.get("premier_pas") or "",
                           bucket=bucket))
    ordre = {"RETARD": 0, "AUJOURDHUI": 1, "DEMAIN": 2, "PLUS_TARD": 3}
    todo.sort(key=lambda d: (ordre[d.bucket], d.due or "9999"))

    n = {b: sum(1 for d in todo if d.bucket == b)
         for b in ("RETARD", "AUJOURDHUI", "DEMAIN", "PLUS_TARD")}
    chiffres = {
        "total": len(todo), "retard": n["RETARD"], "aujourdhui": n["AUJOURDHUI"],
        "demain": n["DEMAIN"], "plus_tard": n["PLUS_TARD"],
    }

    # moyennes par matière, avec tendance entre les deux dernières notes
    par_mat: dict = {}
    for g in grades.values():
        v = _nombre_fr(g.get("grade", ""))
        o = _nombre_fr(g.get("out_of", "")) or "20"
        if not v or float(o) <= 0:
            continue
        par_mat.setdefault(g.get("subject") or "?", []).append(
            (g.get("date") or "", float(v), float(o)))
    moyennes = {}
    for mat, notes in par_mat.items():
        notes.sort(key=lambda t: t[0])
        sur20 = [v / o * 20 for _, v, o in notes]
        moy = sum(sur20) / len(sur20)
        moy = int(moy) if moy >= 10 else round(moy, 1)
        trend = ""
        if len(sur20) >= 2:
            if sur20[-1] > sur20[-2] + 0.4:
                trend = "↗"
            elif sur20[-1] < sur20[-2] - 0.4:
                trend = "↘"
        moyennes[mat] = {"moy": moy, "trend": trend, "notes": len(sur20)}

    cours_demain = [{"subject": c.get("subject", ""), "start": c.get("start", ""),
                     "end": c.get("end", ""), "room": c.get("room", "")}
                    for c in cours][:12]

    ann = []
    for cle in annules:
        jour, _, mat = cle.partition("|")
        ann.append({"jour": jour, "subject": mat})
    ann.sort(key=lambda a: a["jour"], reverse=True)

    profs = []
    for fil, v in (msgs or {}).items():
        at = v.get("at") or ""
        if not at:
            continue
        try:
            age_h = (datetime.now() - datetime.fromisoformat(at)).total_seconds() / 3600
        except ValueError:
            continue
        if age_h <= 48:
            profs.append({"auteur": fil.split("|")[-1].strip(),
                          "titre": fil.split("|")[0], "corps": "", "at": at})
    for r in (cours_notes.get("_recent") or [])[:4]:
        profs.append({"auteur": "Contenu de cours", "titre": court(r, 70),
                      "corps": "", "at": ""})

    questions = (quiz.get("quiz", {}).get("questions") or []
                 if quiz.get("date") == aujourdhui.isoformat() else [])

    controls = []
    for d in todo:
        if not d.due or d.due < aujourdhui.isoformat() or not CTRL_RE.search(d.detail or ""):
            continue
        try:
            j = (datetime.strptime(d.due, "%Y-%m-%d").date() - aujourdhui).days
        except ValueError:
            continue
        fnom = "fiche-%s-%s.md" % (d.due, re.sub(r"[^A-Za-z0-9]+", "_", d.subject)[:20])
        prete = bool(fiches.get(d.fp) or (state_dir() / "fiches" / fnom).exists())
        controls.append({
            "subject": d.subject, "due": d.due, "j": j, "fp": d.fp, "fiche": prete,
            "texte": f"{d.subject} — {d.due} (J-{j})" +
                     (" — fiche prête" if prete else " — fiche à venir")})

    faits_recents = []
    for _, v in sorted(done.items(), key=lambda kv: kv[1].get("done_at", ""), reverse=True):
        if str(v.get("done_at", ""))[:10] >= (aujourdhui - timedelta(days=7)).isoformat():
            faits_recents.append(f"{v.get('subject')} ({v.get('due') or '?'})")

    return Faits(aujourdhui=aujourdhui, todo=todo, chiffres=chiffres, moyennes=moyennes,
                 cours_demain=cours_demin(cours_demain) or [], annules=ann, profs=profs,
                 quiz={"questions": questions}, controls=controls,
                 faits_recents=faits_recents[:8])


def cours_demin(cours: list) -> list:
    return cours


# ─────────────────────── cibler le bon devoir (fp exact) ───────────────────────

@dataclass
class Cibles:
    uniques: list          # Devoir[] — le premier (sans date : le plus ancien)
    ambigu: list           # Devoir[] — les autres : il faut DEMANDER
    aucune: bool
    tous: list = field(default_factory=list)


def demain_ou(faits: Faits) -> str:
    return (faits.aujourdhui + timedelta(days=1)).isoformat()


def _date_du_jour(faits: Faits, nom: str) -> str:
    delta = (JOURS[nom] - faits.aujourdhui.weekday()) % 7 or 7
    return (faits.aujourdhui + timedelta(days=delta)).isoformat()


def cibler(faits: Faits, phrase: str) -> Cibles:
    """« j'ai fait l'espagnol de demain » -> le DEVOIR visé, sans deviner.

    Trois issues, jamais de hasard :
      · un seul candidat -> c'est lui ;
      · plusieurs         -> AMBIGU : le bot DEMANDE, parce qu'un devoir coché
                            par erreur disparaît des rappels sans laisser de
                            trace ;
      · aucun             -> rien à cocher.
    """
    bas = sans_accents(phrase)
    candidats = [d for d in faits.todo if nomme_matiere(bas, d.subject)]
    if not candidats:
        # un mot distinctif de l'énoncé (« quizlet », « pix », la fresque…)
        pm = set(mots(phrase))
        for d in faits.todo:
            if any(m in pm for m in mots(d.detail) if len(m) >= 5):
                candidats.append(d)
                break
    if not candidats:
        return Cibles([], [], True)

    # l'échéance nommée dans la phrase tranche
    cible = None
    if re.search(r"\bdemain\b", bas):
        cible = demain_ou(faits)
    elif re.search(r"\bde (lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b", bas):
        cible = _date_du_jour(faits, re.search(
            r"\bde (lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b", bas).group(1))
    elif re.search(r"\bce soir\b|\baujourd hui\b", bas):
        cible = faits.aujourdhui.isoformat()
    elif re.search(r"\ben retard\b|\bpas fait\b|\bplus vieux\b", bas):
        cible = None                      # le plus ancien des candidats
    if cible:
        exacts = [d for d in candidats if d.due == cible]
        if not exacts:
            return Cibles([], [], True)   # il vise une date où il n'a rien
        candidats = exacts
    return Cibles(candidats[:1], candidats[1:], False, candidats)


# ─────────────────────── écrire « c'est fait » (et le prouver) ───────────────────────
def marquer(faits: Faits, phrase: str, ecrire: bool = True) -> dict:
    """Dépose l'op fp-exacte dans done-inbox.json, puis RELIT le fichier.

    Aucune promesse non prouvée : « c'est noté » n'est dit que si la relecture
    a confirmé l'écriture. Le fp est envoyé pour que pronote-sync ne doive plus
    deviner en triant par date — c'est ce tri qui cochait le plus ancien.
    """
    c = cibler(faits, phrase)
    if c.aucune:
        return {"statut": "introuvable"}
    if c.ambigu:
        return {"statut": "ambigu", "candidats": [d.cle for d in c.tous]}
    d = c.uniques[0]
    op = {"fp": d.fp, "done": True, "subject": d.subject,
          "detail": d.detail, "due": d.due}
    if ecrire:
        _ecrire_op(op)
    return {"statut": "fait", "devoir": d.cle, "fp": d.fp, "due": d.due}


def decocher(faits: Faits, phrase: str, ecrire: bool = True) -> dict:
    c = cibler(faits, phrase)
    if c.aucune:
        return {"statut": "introuvable"}
    if c.ambigu:
        return {"statut": "ambigu", "candidats": [d.cle for d in c.tous]}
    d = c.uniques[0]
    if ecrire:
        _ecrire_op({"fp": d.fp, "done": False, "subject": d.subject})
    return {"statut": "decoche", "devoir": d.cle}


def _ecrire_op(op: dict) -> dict:
    import fcntl
    chemin, lock = inbox(), _lock()
    lock.parent.mkdir(parents=True, exist_ok=True)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        ops = lire_avec_defaut(chemin, [])
        if not isinstance(ops, list):
            ops = []
        ops.append(op)
        tmp = chemin.with_suffix(".tmp")
        tmp.write_text(json.dumps(ops, ensure_ascii=False, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(chemin)
        relu = lire_avec_defaut(chemin, [])       # preuve : on relit
        if not (isinstance(relu, list) and relu[-1] == op):
            raise RuntimeError("écriture non confirmée dans done-inbox.json")
        return {"op": op, "en_attente": len(relu)}


# ─────────────────────────────── small views ───────────────────────────────

def a_envoyer_en_ligne(faits: Faits) -> list:
    """Devoirs dont l'énoncé implique un ENVOI."""
    return [d for d in faits.todo if ENLIGNE_RE.search(d.detail or "")]


def intention_de_fait(phrase: str) -> str:
    """« c'est fait » / « en fait non » -> « fait » / « decoche » / ''.

    Reconnaît le PARLÉ : « jai fait l'espagnol » sans apostrophe matche aussi.
    """
    b = sans_accents(phrase)
    if re.search(r"\b(pas fait|pas encore|en fait non|finalement non)\b", b):
        return "decoche"
    if re.search(
            r"c.?est (fait|bon|rendu|fini|regarde|regarn)|j.?ai (fait|fini|termin|rendu|boucl)"
            r"|je l.?ai (fait|fini|termin)|il est (fait|fini|termin)|termin[ée]s?\b", b):
        return "fait"
    return ""