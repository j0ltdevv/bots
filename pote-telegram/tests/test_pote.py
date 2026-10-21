"""Les tests qui rejouent LES ERREURS RÉELLES de ce bot.

Chaque test porte sur une panne constatée sur cette machine, pas sur une
fonction imaginée :

  · « j'ai fait l'espagnol de demain » cochait le plus ancien ;
  · « 23 devoirs en retard » annoncé alors qu'il n'y en a qu'un ;
  · « AMC 2 » / « SENC » : des matières qui n'ont jamais existé ;
  · « je le barre » sans avoir rien écrit ;
  · « jai fait l'espagnol » (sans apostrophe) : rien n'était détecté.

Ils tournent sur un état de SYNTHÈSE (POTE_STATE), jamais sur les données
réelles : un test qui dépend des devoirs de l’élève casse le jour où il en rend
un, et ne prouve plus rien.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def etat(tmp_path, monkeypatch):
    """Un Pronote de synthèse : 8 devoirs, dont 1 déjà fait, 1 pour aujourd'hui."""
    from pote import brain
    d = tmp_path / "state"
    d.mkdir()
    auj = date.today()
    demain = (auj + timedelta(days=1)).isoformat()
    hier = (auj - timedelta(days=3)).isoformat()

    state = {
        "aaaaaaaaaaaaaaaa": {"subject": "ESPAGNOL LV2", "detail": "traduction du texte",
                           "date": hier, "done": False, "files": []},
        "bbbbbbbbbbbbbbbb": {"subject": "ESPAGNOL LV2", "detail": "fresque à l'oral",
                             "date": demain, "done": False, "files": []},
        "cccccccccccccccc": {"subject": "ESPAGNOL LV2", "detail": "exercice 12",
                             "date": demain, "done": False, "files": []},
        "dddddddddddddddd": {"subject": "ANGLAIS LV1", "detail": "interro Lesson 1",
                             "date": demain, "done": False, "files": []},
        "eeeeeeeeeeeeeeee": {"subject": "MATHEMATIQUES", "detail": "exo 42 a rendre en ligne",
                             "date": demain, "done": False, "files": []},
        "ffffffffffffffff": {"subject": "HISTOIRE", "detail": "contrôle chapitre 3",
                             "date": demain, "done": False, "files": []},
        "9999999999999999": {"subject": "SPORT", "detail": "ramener les basket",
                             "date": auj.isoformat(), "done": False, "files": []},
        "0000000000000000": {"subject": "ESPAGNOL LV2", "detail": "devoir déjà fait",
                             "date": hier, "done": False, "files": []},
    }
    (d / "state.json").write_text(json.dumps(state))
    (d / "done.json").write_text(json.dumps(
        {"0000000000000000": {"subject": "ESPAGNOL LV2", "due": hier,
                              "done_at": auj.isoformat(), "source": "chat"}}))
    (d / "grades.json").write_text(json.dumps(
        {"g1": {"subject": "ESPAGNOL LV2", "grade": "16", "out_of": "20",
                "date": "2026-10-01"},
         "g2": {"subject": "ESPAGNOL LV2", "grade": "12", "out_of": "20",
                "date": "2026-10-05"},
         "g3": {"subject": "MATHEMATIQUES", "grade": "9", "out_of": "20",
                "date": "2026-10-05"}}))
    (d / "annules.json").write_text(json.dumps({f"{demain}|ANGLAIS LV1": 1}))
    (d / "msgs.json").write_text(json.dumps({}))
    (d / "lessons.json").write_text(json.dumps({}))
    (d / "cours.json").write_text(json.dumps(
        [{"start": "08h00", "end": "08h55", "subject": "ANGLAIS LV1", "room": "A203"}]))
    (d / "quiz.json").write_text(json.dumps({"date": auj.isoformat(), "quiz": {"questions": [
        {"q": "Question 1 ?", "a": "Réponse 1"}]}}))
    (d / "health.json").write_text(json.dumps({"last_ok": auj.isoformat(), "failures": 0}))

    monkeypatch.setenv("POTE_STATE", str(d))
    monkeypatch.setenv("POTE_INBOX", str(tmp_path / "done-inbox.json"))
    monkeypatch.setenv("POTE_LOCK", str(tmp_path / "inbox.lock"))
    monkeypatch.setenv("POTE_DATA", str(tmp_path / "data"))
    return d


# ─────────────────────────── les comptes ───────────────────────────

def test_chiffres_sont_calcules_pas_comptees(etat):
    from pote import brain, compose
    f = brain.construire()
    assert f.chiffres["total"] == 7          # 8 en état, 1 déjà fait
    assert f.chiffres["retard"] == 1
    assert f.chiffres["aujourdhui"] == 1
    assert f.chiffres["demain"] == 5
    r = compose.chiffres(f)
    assert str(f.chiffres["retard"]) in r.texte
    assert "en retard" in r.texte


def test_recap_annonce_le_bon_nombre_de_lignes(etat):
    from pote import brain, compose
    f = brain.construire()
    r = compose.recap(f)
    assert f"EN RETARD ({len(f.bucket('RETARD'))})" in r.texte
    for d in f.bucket("RETARD"):
        assert d.ligne() in r.texte


def test_moyennes_sur_20_et_tendance(etat):
    from pote import brain, compose
    f = brain.construire()
    assert f.moyennes["ESPAGNOL LV2"]["moy"] == 14      # (16+12)/2
    assert f.moyennes["ESPAGNOL LV2"]["trend"] == "↘"    # 16 puis 12
    assert "ESPAGNOL LV2 : 14/20 ↘" in compose.notes(f).texte


# ─────────────────────────── le ciblage ───────────────────────────

def test_de_demain_cible_le_bon_devoir(etat):
    """LA panne historique : « l'espagnol de demain » cochait le plus ancien."""
    from pote import brain
    f = brain.construire()
    c = brain.cibler(f, "j'ai fait l'espagnol de demain")
    assert not c.aucune
    assert c.uniques[0].fp == "bbbbbbbbbbbbbbbb"      # la fresque, datée demain


def test_matieres_partageant_un_mot_de_tete_restent_ambigu(etat):
    """« l'ANGLAIS » vise LV1 et LV2 : il faut demander, pas choisir."""
    from pote import brain
    f = brain.construire()
    demain = (date.today() + timedelta(days=1)).isoformat()
    f.todo.append(brain.Devoir(fp="zz", subject="ANGLAIS LV2", detail="oral",
                               due=demain, bucket="DEMAIN"))
    c = brain.cibler(f, "j'ai fait l'anglais de demain")
    assert not c.aucune and len(c.ambigu) == 1


def test_ambiguite_demande_au_lieu_de_deviner(etat):
    """Deux devoirs d'espagnol pour demain, sans précision -> il DEMANDE."""
    from pote import brain, compose
    f = brain.construire()
    r = compose.c_est_fait(f, "j'ai fait l'espagnol de demain")
    assert r.intention == "ambigu"
    assert "J'en vois plusieurs" in r.texte
    assert not (etat.parent / "done-inbox.json").exists()   # rien n'a été coché


def test_matiere_unique_est_cochee_sans_demander(etat):
    """« les maths » -> MATHEMATIQUES : le radical suffit, pas de question."""
    from pote import brain, compose
    f = brain.construire()
    r = compose.c_est_fait(f, "j'ai fait les maths")
    assert r.intention == "fait"
    assert r.suivi["marque"] == "eeeeeeeeeeeeeeee"


def test_phrase_sans_apostrophe_est_reconnue(etat):
    """« jai fait l'espagnol » : l'ancien motif ne matchait pas, en silence."""
    from pote import brain
    assert brain.intention_de_fait("jai fait l'espagnol") == "fait"
    assert brain.intention_de_fait("c'est bon, c'est fini") == "fait"
    assert brain.intention_de_fait("en fait non") == "decoche"
    assert brain.intention_de_fait("j'ai quoi demain") == ""


def test_promesse_de_cochage_est_prouvee(etat):
    """« c'est noté » n'est dit QUE si l'op est relue dans le fichier."""
    from pote import brain, compose
    f = brain.construire()
    compose.c_est_fait(f, "j'ai fait les maths")
    ops = json.loads((etat.parent / "done-inbox.json").read_text())
    assert len(ops) == 1
    assert ops[0]["fp"] == "eeeeeeeeeeeeeeee"      # fp EXACT, pas « la plus urgente »
    assert ops[0]["done"] is True


# ─────────────────────────── l'ancrage ───────────────────────────

def test_invention_de_matiere_rejetee(etat):
    """« AMC 2 », « SENC » : rien de tout ça n'existait."""
    from pote import brain, guard
    f = brain.construire()
    assert guard.verifier("T'as AMC 2 en maths demain", f)
    assert guard.verifier("Fais le SENC stp", f)
    assert guard.verifier("Tu as ANGLAIS LV1 en retard", f) == []


def test_compte_faux_rejete(etat):
    """Le « 23 retards » alors qu'il n'y en a qu'un."""
    from pote import brain, guard
    f = brain.construire()
    assert guard.verifier("T'as 23 retards", f)
    assert guard.verifier("T'as 1 retard", f) == []


def test_heures_ne_sont_pas_des_comptes(etat):
    from pote import brain, guard
    f = brain.construire()
    assert guard.verifier("Cours à 08h00 en A203, 20 minutes", f) == []


def test_llm_renvoie_deterministe_si_invention(etat, monkeypatch):
    """Le filet : un modèle qui invente voit sa réponse JETÉE."""
    from pote import brain, compose, llm
    f = brain.construire()
    monkeypatch.setattr(llm, "_post", lambda *a, **k: "Yo t'as AMC 2 et 12 retards !")
    det = compose.ce_soir(f)
    texte, rejet = llm.mettre_en_mots(det.intention, det.faits, det.texte, f)
    assert rejet
    assert texte == det.texte
    assert "AMC 2" not in texte


def test_llm_accepte_une_reponse_ancree(etat, monkeypatch):
    from pote import brain, compose, llm
    f = brain.construire()
    monkeypatch.setattr(llm, "_post",
                        lambda *a, **k: "Ce soir tu fais le contrôle d'HISTOIRE, ça va vite.")
    det = compose.ce_soir(f)
    texte, rejet = llm.mettre_en_mots(det.intention, det.faits, det.texte, f)
    assert rejet == []
    assert texte.startswith("Ce soir")


def test_llm_indisponible_retombe_sur_le_fait(etat, monkeypatch):
    from pote import brain, compose, llm
    f = brain.construire()

    def boom(*a, **k):
        raise TimeoutError("réseau")

    monkeypatch.setattr(llm, "_post", boom)
    det = compose.ce_soir(f)
    texte, rejet = llm.mettre_en_mots(det.intention, det.faits, det.texte, f)
    assert texte == det.texte
    assert rejet


# ─────────────────────────── le routage ───────────────────────────

def test_fait_prime_sur_demain(etat):
    """« j'ai fait l'espagnol de demain » ne doit pas être lu comme
    « j'ai quoi demain » : l'ordre des règles a déjà coûté un devoir mal barré."""
    from pote import compose
    assert compose.router("j'ai fait l'espagnol de demain") == "fait"
    assert compose.router("j'ai quoi demain") == "demain"
    assert compose.router("quoi faire ce soir") == "ce_soir"
    assert compose.router("combien de retards exactement") == "chiffres"


def test_message_de_prof_passe_dans_profs_pas_dans_devoirs(etat):
    from pote import brain, compose
    f = brain.construire()
    assert compose.router("il a écrit quoi les profs") == "profs"
    assert compose.repondre(f, "il a écrit quoi les profs").intention == "profs"
    r = compose.repondre(f, "quoi rendre en ligne")
    assert r.intention == "en_ligne"
    assert "exo 42" in r.texte


def test_cours_annules_present(etat):
    from pote import brain, compose
    f = brain.construire()
    assert "ANGLAIS LV1" in compose.repondre(f, "y a des cours annulés ?").texte


def test_reponse_du_bot_est_toujours_ancree(etat):
    """Propriété générale : aucune intention ne sort un fait absent."""
    from pote import brain, compose, guard
    f = brain.construire()
    questions = ["quoi faire ce soir", "j'ai quoi demain", "où j'en suis",
                 "mes notes", "les profs ont dit quoi", "quoi rendre en ligne",
                 "cours de demain", "y a des cours annulés", "aide"]
    for q in questions:
        r = compose.repondre(f, q)
        assert guard.verifier(r.texte, f) == [], f"{q} -> {guard.verifier(r.texte, f)}"


# ─────────────────────────── l'apprentissage ───────────────────────────

def test_correction_non_rejouee_ne_devient_pas_active(etat):
    """Une correction ne devient une leçon qu'après 3 rejeux réussis."""
    from pote import brain, lessons
    f = brain.construire()
    lessons.noter("non c'est pas l'espagnol de demain", "oups", "fait")
    r = lessons.consolider(f)
    assert r["rejouees"] >= 1
    assert lessons.actives() == []


def test_lecon_applicable_devient_active_apres_trois_rejeux(etat):
    """Le chemin heureux : « l'espagnol de demain », deux devoirs pour demain —
    le cerveau DEMANDE, la correction est donc respectée."""
    from pote import brain, lessons
    f = brain.construire()
    for _ in range(3):
        lessons.noter("non c'est pas l'espagnol de demain", "oups", "fait")
    lessons.consolider(f)
    assert lessons.actives(), "une leçon rejouée 3 fois doit devenir active"


def test_lecon_inapplicable_est_signalee_pas_cachee(etat, monkeypatch):
    """Si le cerveau régresse, la leçon est rétrogradée — jamais « apprise »
    en silence. On force la régression pour vérifier la machine d'états."""
    from pote import brain, lessons
    f = brain.construire()
    for _ in range(4):
        lessons.noter("non c'est pas l'espagnol de demain", "oups", "fait")
    monkeypatch.setattr(lessons, "rejouer", lambda lecon, faits: "je_ne_sais_pas")
    lessons.consolider(f)
    etats = [l["etat"] for l in lessons._lire_jsonl(lessons.lecons())]
    assert "inappliquee" in etats
    assert lessons.actives() == []


def test_rejouer_signale_un_echec_honnetement(etat):
    """Le rejeu compare l'attendu et l'obtenu : une leçon qu'on ne sait pas
    appliquer doit être RAPPORTÉE comme échouée, pas comptée comme réussie."""
    from pote import brain, lessons
    f = brain.construire()
    lecon = {"type": "ciblage_unique", "attendu": "un_seul_cible",
             "phrase": "l'espagnol de demain"}
    assert lessons.rejouer(lecon, f) != "un_seul_cible"
    lecon_ok = {"type": "ciblage_unique", "attendu": "demander",
                "phrase": "l'espagnol de demain"}
    assert lessons.rejouer(lecon_ok, f) == "demander"


def test_le_rejeu_n_ecrit_jamais_dans_la_file(etat):
    """Le rejeu est un essai À SEC : sinon la consolidation nocturne
    re-cocherait chaque soir les devoirs que le bot vient de barrer."""
    from pote import brain, lessons
    f = brain.construire()
    lessons.consolider(f)
    assert not (etat.parent / "done-inbox.json").exists()


def test_detecte_une_correction(etat):
    from pote import lessons
    assert lessons.est_correction("non c'est pas l'autre")
    assert lessons.est_correction("t'as inventé")
    assert not lessons.est_correction("j'ai quoi demain")


# ─────────────────────────── l'autonomie ───────────────────────────

def test_relance_une_seule_fois_par_jour(etat):
    from pote import tgbot
    a = tgbot.relancer_retard(force=True)
    assert a and "retard" in a
    assert tgbot.relancer_retard(force=True) is None      # déjà relancé aujourd'hui


def test_pas_de_relance_le_week_end(etat):
    from pote import tgbot
    samedi = date.today()
    while samedi.weekday() != 5:
        samedi += timedelta(days=1)
    assert tgbot.relancer_retard(quand=samedi) is None

def test_pas_de_relance_en_vacances(etat):
    from pote import tgbot
    assert tgbot.relancer_retard(quand=date(2026, 10, 20)) is None


def test_en_vacances(etat):
    from pote.brain import en_vacances
    assert en_vacances(date(2026, 10, 20)) == "Toussaint"
    assert en_vacances(date(2026, 11, 5)) == ""


def test_drain_evenements_ne_rejoue_pas(etat, monkeypatch):
    from pote import tgbot
    (etat / "events.log").write_text("\n".join(json.dumps(e) for e in [
        {"ts": "2026-10-01T10:00:00", "type": "new_hw",
         "hw": {"subject": "MATHEMATIQUES", "detail": "exo 42", "due": "2026-10-02"}},
        {"ts": "2026-10-02T10:00:00", "type": "new_hw",
         "hw": {"subject": "SPORT", "detail": "basket", "due": "2026-10-03"}},
    ]) + "\n")
    envoyes = []
    monkeypatch.setattr(tgbot, "envoyer", lambda t, r=None: (envoyes.append(t), True)[1])
    tgbot.racine().mkdir(parents=True, exist_ok=True)
    tgbot.chemin("dernier_push").write_text("2026-10-01T10:00:00")
    assert tgbot.pousser_evenements() == 1
    assert "SPORT" in envoyes[0] and "MATHEMATIQUES" not in envoyes[0]
    assert tgbot.pousser_evenements() == 0        # déjà poussé, jamais rejoué


def test_drain_ignore_une_archive_vide(etat):
    from pote import tgbot
    (etat / "events.log").write_text("")
    assert tgbot.pousser_evenements() == 0


def test_une_ligne_illisible_ne_tue_pas_le_drain(etat, monkeypatch):
    from pote import tgbot
    (etat / "events.log").write_text(
        "{pas du json\n" + json.dumps(
            {"ts": "2026-10-02T10:00:00", "type": "new_hw",
             "hw": {"subject": "SPORT", "detail": "basket", "due": "2026-10-03"}}) + "\n")
    envoyes = []
    monkeypatch.setattr(tgbot, "envoyer", lambda t, r=None: (envoyes.append(t), True)[1])
    assert tgbot.pousser_evenements() == 1
    assert "SPORT" in envoyes[0]


def test_amorcage_ignore_le_backlog(etat, monkeypatch):
    """Premier démarrage : on s'aligne sur le dernier update_id SANS répondre,
    sinon Pote traiterait des messages vieux de plusieurs jours."""
    from pote import tgbot
    appels = []

    def faux_get_updates(method, **kw):
        appels.append(kw)
        return {"ok": True, "result": [{"update_id": 4242}]}

    monkeypatch.setattr(tgbot, "api", faux_get_updates)
    assert tgbot.amorcer() == 4243
    assert tgbot.chemin("tg_offset").read_text() == "4243"
    assert len(appels) == 1