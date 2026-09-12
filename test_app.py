import os
import re
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

import extract
import leads
from extract import (
    EMAIL_REGEX,
    REVERSE_TYPO,
    TYPO_MAP,
    BUSINESS_SOURCES,
    categorize,
    correct_typo,
    domain_of,
    domain_type,
    email_audience,
    extract as extract_emails,
    last_activity_date,
    quality_score,
    score_label,
    sentence_context,
    validate_domains,
)
from generators import (
    generate_demo_text,
    generate_emails_from_names,
    slugify,
)
from pitch import build_pitch, _pitch_company


class TestRegex(unittest.TestCase):
    def test_extracts_simple_emails(self):
        text = "Contactez john.doe@example.com ou jane@foo.fr."
        matches = sorted(set(m.group(0) for m in EMAIL_REGEX.finditer(text)))
        self.assertEqual(matches, ["jane@foo.fr", "john.doe@example.com"])

    def test_handles_special_chars(self):
        m = EMAIL_REGEX.search("adresse : a+b_c@sub.domain-x.co.uk merci")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(0), "a+b_c@sub.domain-x.co.uk")

    def test_ignores_invalid_top_level(self):
        text = "pas-un-email@ et c'est(à la fin) sans adresse."
        matches = list(EMAIL_REGEX.finditer(text))
        self.assertEqual(matches, [])

    def test_does_not_match_partial_username(self):
        text = "voici toto.pierre@mesa-bz.com : abc.toto@x.com contient un suffixe."
        matches = sorted({m.group(0) for m in EMAIL_REGEX.finditer(text)})
        self.assertEqual(matches, ["abc.toto@x.com", "toto.pierre@mesa-bz.com"])

    def test_does_not_match_double_at(self):
        self.assertEqual(list(EMAIL_REGEX.finditer("foo@toto@x.com")), [])

    def test_does_not_match_leading_dot(self):
        self.assertEqual(list(EMAIL_REGEX.finditer(".toto@x.com")), [])


class TestTypoCorrection(unittest.TestCase):
    def test_reverse_map_consistency(self):
        self.assertEqual(REVERSE_TYPO["gamil.com"], "gmail.com")
        self.assertEqual(REVERSE_TYPO["hotmial.fr"], "hotmail.com")
        self.assertEqual(correct_typo("outlok.com"), "outlook.com")
        for wrong in REVERSE_TYPO:
            self.assertEqual(correct_typo(wrong), REVERSE_TYPO[wrong])

    def test_unknown_domain_unchanged(self):
        self.assertEqual(correct_typo("monentreprise.fr"), "monentreprise.fr")
        self.assertEqual(correct_typo("gmail.com"), "gmail.com")

    def test_all_typos_are_distinct(self):
        seen = set()
        for wrongs in TYPO_MAP.values():
            for wrong in wrongs:
                self.assertNotIn(wrong, seen)
                seen.add(wrong)


class TestCategorize(unittest.TestCase):
    def test_active(self):
        self.assertEqual(categorize("Suite à notre échange, votre contact est confirmé depuis septembre 2026"), "active")
        self.assertEqual(categorize("envoi de la facture de décembre 2025"), "active")

    def test_recente(self):
        self.assertEqual(categorize("Rendez-vous en novembre 2026."), "recente")

    def test_ancienne(self):
        self.assertEqual(categorize("Texte sans date ni indicateur."), "ancienne")


class TestDomainClassification(unittest.TestCase):
    def test_domain_type(self):
        self.assertEqual(domain_type("gmail.com"), "perso")
        self.assertEqual(domain_type("monentreprise.fr"), "pro")

    def test_email_audience(self):
        self.assertEqual(email_audience("j.dupont@gmail.com"), "nominal")
        self.assertEqual(email_audience("info@monentreprise.fr"), "generique")
        self.assertEqual(email_audience("no-reply@msn.com"), "generique")
        self.assertEqual(email_audience("toto@mailinator.com"), "jetable")

    def test_domain_of(self):
        self.assertEqual(domain_of("Jean.Pierre@ExAmpLe.COM"), "example.com")
        self.assertEqual(domain_of("sans-arobase"), "")


class TestQualityScore(unittest.TestCase):
    def test_best_case(self):
        self.assertEqual(
            quality_score("active", "pro", ["LinkedIn"], False, "nominal"), 100
        )

    def test_jetable_penalized(self):
        base = quality_score("active", "pro", ["LinkedIn"], False, "nominal")
        jetable = quality_score("active", "pro", ["LinkedIn"], False, "jetable")
        self.assertEqual(jetable, base - 35)

    def test_generique_penalized(self):
        base = quality_score("active", "pro", ["LinkedIn"], False, "nominal")
        generique = quality_score("active", "pro", ["LinkedIn"], False, "generique")
        self.assertEqual(generique, base - 10)

    def test_typography_penalty(self):
        with_typo = quality_score("active", "pro", ["LinkedIn"], True, "nominal")
        without = quality_score("active", "pro", ["LinkedIn"], False, "nominal")
        self.assertEqual(with_typo, without - 10)

    def test_clamped(self):
        self.assertEqual(quality_score("ancienne", "perso", ["Non identifié"], True, "jetable"), 0)
        self.assertEqual(quality_score("active", "pro", ["LinkedIn"], False, "nominal"), 100)

    def test_score_label(self):
        self.assertEqual(score_label(100), "chaud")
        self.assertEqual(score_label(75), "chaud")
        self.assertEqual(score_label(74), "tiede")
        self.assertEqual(score_label(50), "tiede")
        self.assertEqual(score_label(20), "froid")


class TestSentenceContext(unittest.TestCase):
    def test_returns_sentence_without_echo(self):
        text = "Bonjour Alain.\nSuite à notre échange du 12 novembre 2026, voici julie.martin@capgemini.com qui vous suivra."
        display, analyse = sentence_context(text, "julie.martin@capgemini.com")
        self.assertNotIn("julie.martin@capgemini.com", display)
        self.assertNotIn("julie.martin@capgemini.com", analyse)
        self.assertIn("Suite à notre échange", display)
        self.assertIn("Suite à notre échange", analyse)

    def test_context_surrounding_sentence(self):
        text = "Premier paragraphe sans email.\nMerci de contacter louis.girard@oracle.com pour la suite.\nFin du message."
        display, analyse = sentence_context(text, "louis.girard@oracle.com")
        self.assertIn("Merci de contacter", display)
        self.assertIn("pour la suite", display)
        self.assertNotIn("louis.girard@oracle.com", display)
        self.assertNotIn("Premier paragraphe", display)

    def test_empty_if_email_not_found(self):
        self.assertEqual(sentence_context("aucun email ici", "x@y.z"), ("", ""))


class TestLastActivityDate(unittest.TestCase):
    def test_full_date_french(self):
        self.assertEqual(last_activity_date("du 15/09/2026"), date(2026, 9, 15))
        self.assertEqual(last_activity_date("du 15-09-2026"), date(2026, 9, 15))

    def test_iso_date(self):
        self.assertEqual(last_activity_date("le 2026-09-15"), date(2026, 9, 15))

    def test_month_year(self):
        self.assertEqual(last_activity_date("rendez-vous de mars 2027"), date(2027, 3, 15))

    def test_year_alone(self):
        self.assertEqual(last_activity_date("depuis 2024"), date(2024, 7, 1))

    def test_month_alone_current_year(self):
        self.assertEqual(last_activity_date("visite en septembre"),
                         date(date.today().year, 9, 1))

    def test_specific_date_beats_year_of_same_year(self):
        self.assertEqual(last_activity_date("du 15/09/2026"), date(2026, 9, 15))

    def test_picks_most_recent(self):
        ld = last_activity_date("ancien échange 2022, puis mars 2026")
        self.assertEqual(ld, date(2026, 3, 15))

    def test_empty(self):
        self.assertIsNone(last_activity_date("aucune date"))
        self.assertIsNone(last_activity_date(""))


class TestValidateDomains(unittest.TestCase):
    def test_filters_invalid(self):
        with mock.patch.object(extract, "domain_valid",
                               side_effect=lambda d: d != "b.fr"):
            valid = validate_domains(["a.fr", "b.fr", "c.fr"])
        self.assertEqual(valid, {"a.fr", "c.fr"})

    def test_dedupes_input(self):
        with mock.patch.object(extract, "domain_valid", side_effect=[True]):
            valid = validate_domains(["a.fr", "a.fr", "a.fr"])
        self.assertEqual(valid, {"a.fr"})


class TestDNSCacheTtl(unittest.TestCase):
    def setUp(self):
        extract._dns_cache.clear()

    def tearDown(self):
        extract._dns_cache.clear()

    def test_cache_used_second_time(self):
        with mock.patch.object(extract, "_check_domain", return_value=True) as check:
            self.assertTrue(extract.domain_valid("cache.test"))
            self.assertTrue(extract.domain_valid("cache.test"))
            self.assertEqual(check.call_count, 1)

    def test_negative_cached(self):
        with mock.patch.object(extract, "_check_domain", return_value=False) as check:
            self.assertFalse(extract.domain_valid("nope.test"))
            self.assertFalse(extract.domain_valid("nope.test"))
            self.assertEqual(check.call_count, 1)


class TestExtract(unittest.TestCase):
    def setUp(self):
        # pas de lookup DNS réseau pendant les tests
        self.patcher = mock.patch.object(extract, "domain_valid", return_value=True)
        self.patcher.start()
        extract._dns_cache.clear()

    def tearDown(self):
        self.patcher.stop()
        extract._dns_cache.clear()

    def test_basic_extraction_and_dedup(self):
        text = "hello@monentreprise.fr et HELLO@monentreprise.fr et au-revoir@exemple.fr"
        data = extract_emails(text)
        self.assertEqual(data["total"], 2)
        addresses = [r["email"] for r in data["emails"]]
        self.assertEqual(addresses.count("hello@monentreprise.fr"), 1)

    def test_ignored_domains(self):
        text = "toto@example.com tata@test.fr real@entreprise.fr"
        data = extract_emails(text)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["emails"][0]["email"], "real@entreprise.fr")

    def test_typo_correction_in_results(self):
        text = "Cliquez ici kangourou@hotmial.fr"
        data = extract_emails(text)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["emails"][0]["email"], "kangourou@hotmail.com")
        self.assertEqual(data["emails"][0]["typo_corrected"], True)
        self.assertEqual(data["typos_corriges"], 1)

    def test_stats_counts(self):
        text = "\n".join([
            "Contrat signé en septembre 2026, contactez a@proaa.fr.",
            "Vieux passage sans indication : b@probb.fr.",
            "Réponse à une facture : c@procc.fr.",
        ])
        data = extract_emails(text)
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["pros"], 3)
        self.assertEqual(data["actives"] + data["recentes"] + data["anciennes"], 3)

    def test_invalid_domains_filtered(self):
        with mock.patch.object(extract, "domain_valid", return_value=False):
            data = extract_emails("bad@domaine-inconnu.xyz")
            self.assertEqual(data["total"], 0)
            self.assertEqual(data["invalides"], 1)

    def test_provider_detection(self):
        data = extract_emails("coucou@outlook.fr")
        self.assertEqual(data["emails"][0]["provider"], "outlook")

    def test_context_field_present(self):
        data = extract_emails("Signature : batman@gothamcorp.com.")
        self.assertIsNotNone(data["emails"][0]["context"])

    def test_sort_by_score_desc(self):
        text = "\n".join([
            "Signature batman@gothamcorp.com.",
            "Suite échange septembre 2026 : superman@dailyplanet.us.",
        ])
        data = extract_emails(text)
        scores = [r["score"] for r in data["emails"]]
        self.assertEqual(scores, sorted(scores, reverse=True))


class TestGenerators(unittest.TestCase):
    def test_slugify_accents(self):
        self.assertEqual(slugify("Léa"), "lea")
        self.assertEqual(slugify("O'Brien"), "obrien")
        self.assertEqual(slugify("Jean-Paul"), "jeanpaul")

    def test_generate_demo_contains_emails(self):
        mails = re.findall(EMAIL_REGEX.pattern, generate_demo_text(5), re.IGNORECASE)
        self.assertGreater(len(mails), 0)

    def test_generate_estimate_formats(self):
        candidates = generate_emails_from_names("acme.com", "Marie", "Martin")
        addresses = {c["email"] for c in candidates}
        expected = {"marie.martin@acme.com", "m.martin@acme.com",
                    "mariem@acme.com", "mmartin@acme.com",
                    "martin.marie@acme.com", "martin@acme.com",
                    "marie@acme.com"}
        self.assertEqual(len(addresses), len(candidates))
        self.assertLessEqual(addresses, expected)

    def test_generate_estimate_requires_name(self):
        candidates = generate_emails_from_names("acme.com", "", "")
        self.assertEqual(candidates, [])

    def test_generate_estimate_one_seed(self):
        by_last = generate_emails_from_names("acme.com", "", "Martin")
        self.assertEqual({c["email"] for c in by_last}, {"martin@acme.com"})
        by_first = generate_emails_from_names("acme.com", "Marie", "")
        self.assertEqual({c["email"] for c in by_first}, {"marie@acme.com"})

    def test_generate_demo_count_bounds(self):
        self.assertLessEqual(generate_demo_text(9999).count("\n"), 100_000)


class TestPitch(unittest.TestCase):
    def test_pitch_company_from_domain(self):
        self.assertEqual(_pitch_company("entreprise-dupont.fr"), "Entreprise dupont")
        self.assertEqual(_pitch_company("capgemini.com"), "Capgemini")

    def test_build_pitch_structure(self):
        pitch = build_pitch("j.martin@acme.com", "Suite à un échange", ["LinkedIn"], "chaud")
        self.assertIn("subject", pitch)
        self.assertIn("text", pitch)
        self.assertIn("opener", pitch)
        self.assertIn("Bonjour", pitch["text"])
        self.assertIn("acme", pitch["subject"].lower() + pitch["text"].lower())
        self.assertEqual(pitch["opener"], "LinkedIn")

    def test_build_pitch_fallback_opener(self):
        pitch = build_pitch("j.martin@acme.com", "", ["Source bizarre"], "tiede")
        self.assertEqual(pitch["opener"], "Contact direct")
        self.assertIn("contact", pitch["text"].lower())

    def test_pitch_urgency_variation(self):
        chaud = build_pitch("j@acme.com", "", [], "chaud")["text"]
        froid = build_pitch("j@acme.com", "", [], "froid")["text"]
        self.assertNotIn("reviens vers vous au plus vite", froid)
        self.assertIn("reviens vers vous au plus vite", chaud)


def _make_result(email, domain=None, audience="nominal", sources=None, score=50,
                 heat="tiede", last_seen="2026-09-01"):
    domain = domain or email.split("@")[1]
    return {
        "email": email,
        "domain": domain,
        "domain_type": "pro" if not email.split("@")[1].startswith(("gmail", "outlook")) else "perso",
        "provider": "autre",
        "audience": audience,
        "scores": [score],
        "score": score,
        "heat": heat,
        "last_seen": last_seen,
        "sources": sources or [],
    }


class TestLeadsIdentity(unittest.TestCase):
    def test_prenom_nom_matches_initial(self):
        lexicon = {"doe"}
        a = leads.person_key("john.doe@acme.com", "acme.com", lexicon)
        b = leads.person_key("j.doe@acme.com", "acme.com", lexicon)
        self.assertEqual(leads._merge_key(a), leads._merge_key(b))

    def test_order_insensitive(self):
        a = leads.person_key("john.doe@acme.com", "acme.com", {"doe"})
        b = leads.person_key("doe.john@acme.com", "acme.com", {"doe", "john"})
        self.assertEqual(a, b)

    def test_different_initials_do_not_match(self):
        lexicon = {"doe"}
        a = leads.person_key("john.doe@acme.com", "acme.com", lexicon)
        b = leads.person_key("jane.doe@acme.com", "acme.com", lexicon)
        self.assertNotEqual(a, b)

    def test_different_surnames_do_not_match(self):
        lexicon = {"doe", "martin"}
        a = leads.person_key("john.doe@acme.com", "acme.com", lexicon)
        b = leads.person_key("john.martin@acme.com", "acme.com", lexicon)
        self.assertNotEqual(a, b)

    def test_concatenated_initial_matches_via_lexicon(self):
        lexicon = {"doe"}
        a = leads.person_key("john.doe@acme.com", "acme.com", lexicon)
        b = leads.person_key("jdoe@acme.com", "acme.com", lexicon)
        self.assertEqual(leads._merge_key(a), leads._merge_key(b))

    def test_generic_is_unique(self):
        a = leads.person_key("info@acme.com", "acme.com", {"acme"}, "generique")
        b = leads.person_key("contact@acme.com", "acme.com", {"acme"}, "generique")
        self.assertNotEqual(a, b)
        self.assertEqual(a, ("generic", "info@acme.com", None, None))

    def test_other_domain_does_not_match(self):
        a = leads.person_key("john.doe@acme.com", "acme.com", {"doe"})
        b = leads.person_key("john.doe@other.com", "other.com", {"doe"})
        self.assertNotEqual(a, b)


class TestLeadsDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        leads.init_db(self.tmp.name)

    def tearDown(self):
        leads.close()
        os.unlink(self.tmp.name)

    def test_merge_creates_and_dedups(self):
        report = leads.merge_analysis([
            _make_result("john.doe@acme.com"),
            _make_result("j.doe@acme.com"),
        ])
        self.assertEqual(report["created"], 1)
        self.assertEqual(leads.stats()["total"], 1)
        lead = leads.list_leads()[0]
        self.assertEqual(set(lead["emails"]),
                         {"john.doe@acme.com", "j.doe@acme.com"})
        self.assertEqual(lead["first_name"], "john")
        self.assertEqual(lead["last_name"], "doe")

    def test_reimport_updates_and_preserves_status(self):
        leads.merge_analysis([_make_result("john.doe@acme.com")])
        lead = leads.list_leads()[0]
        leads.update_lead(lead["id"], status="Client", notes="à relancer")
        report = leads.merge_analysis([_make_result("j.doe@acme.com")])
        self.assertEqual(report["updated"], 1)
        self.assertEqual(report["created"], 0)
        lead = leads.list_leads()[0]
        self.assertEqual(lead["status"], "Client")
        self.assertEqual(lead["notes"], "à relancer")
        self.assertEqual(lead["scans"], 2)
        self.assertEqual(set(lead["emails"]),
                         {"john.doe@acme.com", "j.doe@acme.com"})

    def test_patch_status_and_notes(self):
        leads.merge_analysis([_make_result("john.doe@acme.com")])
        lead = leads.list_leads()[0]
        updated = leads.update_lead(lead["id"], status="Lead", notes="note")
        self.assertEqual(updated["status"], "Lead")
        self.assertEqual(updated["notes"], "note")
        self.assertIsNone(leads.update_lead(99999, status="x"))

    def test_delete(self):
        leads.merge_analysis([_make_result("john.doe@acme.com")])
        lead = leads.list_leads()[0]
        self.assertTrue(leads.delete_lead(lead["id"]))
        self.assertEqual(leads.stats()["total"], 0)
        self.assertFalse(leads.delete_lead(lead["id"]))

    def test_filters(self):
        leads.merge_analysis([_make_result("john.doe@acme.com")])
        lead = leads.list_leads()[0]
        leads.update_lead(lead["id"], status="Client")
        self.assertEqual(len(leads.list_leads(status="Client")), 1)
        self.assertEqual(len(leads.list_leads(status="Prospect")), 0)
        self.assertEqual(len(leads.list_leads(q="doe")), 1)
        self.assertEqual(len(leads.list_leads(q="inconnu")), 0)

    def test_sources_merged(self):
        leads.merge_analysis([_make_result("john.doe@acme.com", sources=["LinkedIn"])])
        leads.merge_analysis([_make_result("j.doe@acme.com", sources=["Signature"])])
        lead = leads.list_leads()[0]
        self.assertEqual(set(lead["sources"]), {"LinkedIn", "Signature"})


class TestLeadsDashboard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        leads.init_db(self.tmp.name)

    def tearDown(self):
        leads.close()
        os.unlink(self.tmp.name)

    def test_empty_dashboard(self):
        d = leads.dashboard()
        self.assertEqual(d["total"], 0)
        self.assertEqual(d["nouveaux_30j"], 0)
        self.assertEqual(d["sans_statut"], 0)
        self.assertEqual(d["par_heat"], {})
        self.assertEqual(d["timeline"], [])

    def test_aggregations(self):
        leads.merge_analysis([
            _make_result("john.doe@acme.com", score=85, heat="chaud", sources=["LinkedIn"]),
        ])
        leads.merge_analysis([_make_result("jane.martin@beta.com", score=40, heat="froid")])
        d = leads.dashboard()
        self.assertEqual(d["total"], 2)
        self.assertEqual(d["domaines_total"], 2)
        self.assertEqual(d["scans_total"], 2)
        self.assertEqual(d["par_heat"]["chaud"], 1)
        self.assertEqual(d["par_heat"]["froid"], 1)
        self.assertEqual(d["par_type_domaine"]["pro"], 2)
        self.assertEqual(len(d["top_domaines"]), 2)
        self.assertTrue(any(s["source"] == "LinkedIn" for s in d["top_sources"]))
        self.assertEqual(len(d["timeline"]), 1)

    def test_route(self):
        import app as app_module
        app_module.app.testing = True
        client = app_module.app.test_client()
        res = client.get("/leads/dashboard")
        self.assertEqual(res.status_code, 200)
        self.assertIn("total", res.get_json())


class TestLeadsRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        leads.init_db(self.tmp.name)
        import app as app_module
        app_module.app.testing = True
        app_module._buckets.clear()
        self.client = app_module.app.test_client()

    def tearDown(self):
        leads.close()
        os.unlink(self.tmp.name)

    def test_import_empty(self):
        res = self.client.post("/leads/import", json={"emails": []})
        self.assertEqual(res.status_code, 400)

    def test_import_list(self):
        res = self.client.post("/leads/import", json={"emails": [
            _make_result("john.doe@acme.com"),
            _make_result("j.doe@acme.com"),
        ]})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["created"], 1)
        self.assertEqual(body["stats"]["total"], 1)

    def test_patch(self):
        leads.merge_analysis([_make_result("john.doe@acme.com")])
        lead = leads.list_leads()[0]
        res = self.client.patch(f"/leads/{lead['id']}", json={"status": "Client"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "Client")

    def test_patch_missing(self):
        res = self.client.patch("/leads/99999", json={"status": "Client"})
        self.assertEqual(res.status_code, 404)

    def test_delete(self):
        leads.merge_analysis([_make_result("john.doe@acme.com")])
        lead = leads.list_leads()[0]
        res = self.client.delete(f"/leads/{lead['id']}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["stats"]["total"], 0)


class TestAppRoutes(unittest.TestCase):
    def setUp(self):
        import app as app_module
        app_module.app.testing = True
        self.client = app_module.app.test_client()
        self.orig_max = app_module.RATE_LIMIT_MAX
        self.orig_window = app_module.RATE_LIMIT_WINDOW
        app_module.RATE_LIMIT_MAX = 1000
        app_module.RATE_LIMIT_WINDOW = 60
        app_module._buckets.clear()

    def tearDown(self):
        import app as app_module
        app_module.RATE_LIMIT_MAX = self.orig_max
        app_module.RATE_LIMIT_WINDOW = self.orig_window
        app_module._buckets.clear()

    def test_index(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"MailLens", res.data)

    def test_extract_empty(self):
        res = self.client.post("/extract", json={"text": "   "})
        self.assertEqual(res.status_code, 400)

    def test_estimate_invalid(self):
        res = self.client.post("/generate/estimate", json={"domain": "pasdete"})
        self.assertEqual(res.status_code, 400)

    def test_pitch_invalid(self):
        res = self.client.post("/generate/pitch", json={"email": "pasun-email"})
        self.assertEqual(res.status_code, 400)

    def test_bad_score_does_not_500(self):
        res = self.client.post("/generate/pitch",
                               json={"email": "j.doe@acme.com", "score": "pas-un-nombre"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("subject", res.get_json())

    def test_bad_count_does_not_500(self):
        res = self.client.post("/generate/demo", json={"count": "abc"})
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(res.get_json()["count"], 0)

    def test_rate_limit_enforced(self):
        import app as app_module
        app_module.RATE_LIMIT_MAX = 3
        for _ in range(3):
            res = self.client.post("/extract", json={"text": "toto@acme.fr"})
            self.assertEqual(res.status_code, 200)
        res = self.client.post("/extract", json={"text": "toto@acme.fr"})
        self.assertEqual(res.status_code, 429)

    def test_static_not_rate_limited(self):
        import app as app_module
        app_module.RATE_LIMIT_MAX = 1
        for _ in range(5):
            res = self.client.get("/")
            self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main()