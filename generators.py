import random
import re
from unicodedata import category as _ucat, normalize

from extract import EMAIL_REGEX, TYPO_MAP

FIRST_NAMES = [
    "Marie", "Julie", "Sophie", "Camille", "Léa", "Chloé", "Manon", "Sarah",
    "Emma", "Lola", "Nina", "Alicia", "Arthur", "Louis", "Hugo", "Thomas",
    "Mathis", "Nathan", "Lucas", "Raphaël", "Gabriel", "Jules", "Adam", "Enzo",
    "Théo", "Pierre", "Antoine", "Julien", "Nicolas", "Olivier", "Karim", "Nadia",
]

LAST_NAMES = [
    "Martin", "Bernard", "Dubois", "Moreau", "Laurent", "Lefebvre", "Roux",
    "Fournier", "Girard", "Bonnet", "Dupont", "Lambert", "Fontaine", "Rousseau",
    "Vincent", "Muller", "Faure", "André", "Mercier", "Blanc", "Guerin",
    "Boyer", "Garnier", "Chevalier", "Perrin", "Morel", "Renard",
    "Picard", "Rolland", "Benali", "Haddad", "Diarra", "Ndiaye", "Petit",
]

DEMO_PRO_DOMAINS = [
    "capgemini.com", "atos.net", "oracle.com", "sap.com", "ibm.com", "microsoft.com",
    "google.com", "amazon.fr", "orange.fr", "sfr.fr", "bouyguestelecom.fr",
    "bnpparibas.com", "societegenerale.fr", "airfrance.fr", "sncf.fr", "edf.fr",
    "totalenergies.com", "loreal.fr", "danone.com", "auchan.fr", "carrefour.com",
    "decathlon.fr", "lvmh.fr", "veolia.com", "safran-group.com", "thalesgroup.com",
]

DEMO_PERSO_DOMAINS = [
    "gmail.com", "outlook.fr", "hotmail.fr", "yahoo.fr", "orange.fr", "free.fr",
    "sfr.fr", "laposte.net", "protonmail.com", "proton.me", "icloud.com",
    "wanadoo.fr", "live.fr", "gmx.fr", "mail.com",
]

DEMO_ROLES = [
    "Responsable commercial", "Directrice marketing", "Ingénieur R&D",
    "Chargée de clientèle", "Chef de projet", "Business Developer",
    "Responsable achats", "Directeur technique", "Consultante senior",
    "Responsable des ressources humaines", "Comptable", "Assistante de direction",
]

DEMO_COMPANIES = [
    "Capgemini", "Atos", "Oracle France", "SAP France", "IBM France", "Microsoft France",
    "Google France", "Amazon France", "Orange Business", "SFR Business", "BNP Paribas",
    "Société Générale", "Air France", "SNCF Réseau", "EDF", "TotalEnergies", "L'Oréal",
    "Danone", "Auchan Retail", "Carrefour", "Decathlon", "LVMH", "Veolia", "Safran",
]

DEMO_SUBJECTS = [
    "Suivi de votre demande", "Rappel : notre rendez-vous",
    "Prochaine étape — partenariat", "Proposition commerciale",
    "Relance de votre dossier", "Accusé de réception",
]


def slugify(value):
    value = (value or "").strip().lower()
    value = normalize("NFD", value)
    value = "".join(c for c in value if _ucat(c) != "Mn")
    value = value.replace("'", "").replace("-", "").replace(" ", "")
    return value


def _random_phone():
    return (f"0{random.randint(1, 7)} {random.randint(10, 99)} "
            f"{random.randint(10, 99)} {random.randint(10, 99)} {random.randint(10, 99)}")


def _local_part(first, last):
    f, l = slugify(first), slugify(last)
    return random.choice([
        f"{f}.{l}",
        f"{f[0]}.{l}" if f else l,
        f"{f}{l[0]}" if l else f,
        f"{f[0]}{l}" if f else l,
        f"{f}",
        f"{l}.{f}" if f else l,
    ])


def _make_email(first, last, force_typo=False, pro=True):
    domain = None
    if force_typo:
        correct = random.choice(list(TYPO_MAP.keys()))
        domain = random.choice(TYPO_MAP[correct])
    elif pro:
        domain = random.choice(DEMO_PRO_DOMAINS)
    else:
        domain = random.choice(DEMO_PERSO_DOMAINS)
    return f"{_local_part(first, last)}@{domain}", domain


def _b_exchange():
    f1, l1 = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
    e1, _ = _make_email(f1, l1, random.random() < 0.08, pro=True)
    f2, l2 = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
    e2, _ = _make_email(f2, l2, random.random() < 0.12, pro=random.random() < 0.6)
    recent = random.random() < 0.7
    year = "2026" if recent else random.choice(["2022", "2023"])
    month = random.choice(["septembre", "octobre", "novembre", "décembre"]) if recent \
        else random.choice(["février", "mars", "avril", "mai"])
    return [
        "", "De : " + random.choice(DEMO_SUBJECTS),
        "Bonjour,",
        f"Suite à notre échange du {random.randint(1, 28)} {month} {year}, je vous transmets "
        f"les coordonnées de {f2} {l2} : {e2}.",
        f"{f2} vient de rejoindre notre équipe et gère désormais votre compte. "
        f"Pour toute question, le service client répond également via {e1}.",
        "Merci et bonne journée.",
        f"{f1} {l1}",
        "",
    ]


def _b_signature():
    f, l = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
    e, _ = _make_email(f, l, random.random() < 0.12, pro=True)
    role, company = random.choice(DEMO_ROLES), random.choice(DEMO_COMPANIES)
    return [
        "", "--",
        f"{f} {l}", role, company,
        f"Email : {e}",
        f"Tél : {_random_phone()}",
        "",
        "Cordialement, je vous prie de bien vouloir mettre à jour mes coordonnées dans "
        "votre fichier de contacts et de m'envoyer une réponse à cette adresse.",
    ]


def _b_newsletter():
    f, l = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
    contact, _ = _make_email(f, l, False, True)
    from_add = f"newsletter@{random.choice(DEMO_PRO_DOMAINS)}"
    return [
        "", "NEWSLETTER PARTENAIRES",
        "Bonjour,",
        "Retrouvez chaque mois les tendances du secteur dans notre lettre d'information.",
        f"Pour toute question, écrivez-nous à {contact}.",
        f"Vous recevez ce message car vous êtes abonné à notre newsletter. "
        f"Désabonnement : {from_add}.",
        "",
    ]


def _b_social():
    f, l = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
    e1, _ = _make_email(f, l, random.random() < 0.1, pro=True)
    notif = f"no-reply-{random.randint(10, 99)}@{random.choice(DEMO_PRO_DOMAINS)}"
    return [
        "", f"LinkedIn — {random.choice(['Nouveau message', 'Invitation à se connecter', 'Nouvelle alerte'])}",
        f"{f} {l} vient de vous envoyer un message via LinkedIn.",
        f"Pour le contacter directement : {e1}.",
        f"Ou répondez via la notification LinkedIn (depuis {notif}).",
        "",
    ]


def _b_invoice():
    num = random.randint(10000, 99999)
    amount = round(random.uniform(120, 4500), 2)
    d = f"{random.randint(1, 28)}/{random.randint(1, 12)}/2026"
    billing = f"facturation@{random.choice(DEMO_PRO_DOMAINS)}"
    return [
        "", f"Votre facture n°{num} du {d} est disponible.",
        f"Montant : {amount:.2f} € à régler sous 30 jours.",
        f"En cas de question, notre service facturation vous répond à {billing}. Bonne réception.",
        "",
    ]


def _b_support():
    ticket = random.randint(1000, 9999)
    sup = f"support@{random.choice(DEMO_PRO_DOMAINS)}"
    return [
        "", f"Service client — Ticket n°{ticket}",
        "Nous avons bien reçu votre demande. Un conseiller vous répondra sous 24 h.",
        f"Pour ajouter des pièces jointes, écrivez à {sup}.",
        "",
    ]


_DEMO_BLOCKS = [_b_exchange, _b_signature, _b_newsletter, _b_social, _b_invoice, _b_support]


def generate_demo_text(count=12):
    count = max(1, min(int(count), 40))
    lines = [
        "Bonjour,",
        "",
        "Voici un récapitulatif des contacts réunis dans le cadre du salon SIEL 2026 (septembre).",
        "Ils seront utiles pour la relance de la semaine prochaine.",
        "",
    ]
    for _ in range(count):
        lines.extend(random.choice(_DEMO_BLOCKS)())
    lines.extend([
        "",
        "Bonne journée,",
        "Aurélie Fortin",
        "Responsable des partenariats",
        "aurelie.fortin@atos.net",
        f"Tél : {_random_phone()}",
        "",
        "MailLens — document de démonstration généré automatiquement.",
    ])
    return "\n".join(lines)


def generate_emails_from_names(domain, first_name, last_name):
    f = slugify(first_name)
    l = slugify(last_name)
    fi = f[0] if f else ""
    li = l[0] if l else ""
    spec = [
        (f"{f}.{l}" if f and l else "", "prenom.nom"),
        (f"{fi}.{l}" if f and l else "", "p.nom"),
        (f"{f}{li}" if f and l else "", "prenom + initiale du nom"),
        (f"{fi}{l}" if f and l else "", "initiale du prénom + nom"),
        (f"{l}.{f}" if f and l else "", "nom.prenom"),
        (f"{l}" if l else "", "nom"),
        (f"{f}" if f else "", "prenom"),
    ]
    candidates = []
    seen = set()
    for local, label in spec:
        if not local or local in seen:
            continue
        seen.add(local)
        candidates.append({"email": f"{local}@{domain}", "pattern": label})
    return candidates