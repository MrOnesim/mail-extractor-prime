import random

from extract import domain_of, score_label

PITCH_SUBJECTS = [
    "Échange rapide de 15 minutes",
    "Une idée à partager avec {company}",
    "Contact {company} — suite à notre échange",
    "Proposition de collaboration",
    "Accompagnement {company}",
]

PITCH_OPENERS = {
    "LinkedIn": "Je vous contacte après avoir vu votre profil LinkedIn et votre expérience dans le secteur.",
    "Formulaire": "Vous m'avez récemment laissé vos coordonnées via notre formulaire : merci pour votre confiance.",
    "Facturation": "Dans la continuité de nos échanges de facturation, je souhaitais voir avec vous les suites possibles.",
    "E-commerce": "Après votre dernière commande, je souhaitais vous présenter une offre complémentaire adaptée à vos besoins.",
    "Support": "Suite à votre demande passée au support, je voulais vous proposer une solution plus globale et personnalisée.",
    "Signature": "J'ai découvert votre adresse dans une signature professionnelle et je me tiens volontiers à votre disposition.",
    "Newsletter": "Comme vous êtes abonné à notre newsletter, je me permets de vous proposer un échange plus approfondi.",
    "Contact direct": "Vous nous avez récemment contactés — je vous remercie et reviens vers vous avec plaisir.",
}

PITCH_CLOSINGS = [
    "Seriez-vous disponible 15 minutes cette semaine ou la suivante pour en parler ?",
    "Un créneau de 15 minutes la semaine prochaine vous conviendrait-il ?",
    "Accepteriez-vous un court appel de 15 minutes pour que je vous présente notre approche ?",
]

PITCH_URGENCY = {
    "chaud": "Je sais que le sujet est actif chez vous en ce moment, aussi je reviens vers vous au plus vite.\n\n",
    "tiede": "Sans vouloir vous presser, je tenais à revenir vers vous avant la fin du trimestre.\n\n",
    "froid": "",
}


def build_pitch(email, context, sources, heat="tiede"):
    domain = domain_of(email)
    company = _pitch_company(domain)
    src = next((s for s in sources if s in PITCH_OPENERS), "Contact direct")
    opener = PITCH_OPENERS[src]

    body = [
        "Bonjour,",
        "",
        opener,
        "",
        f"Nous accompagnons les équipes de {company} dans leur transformation digitale et "
        "nous cherchons justement des interlocuteurs comme vous.",
        "",
        random.choice(PITCH_CLOSINGS),
        "",
        PITCH_URGENCY.get(heat, ""),
        "Bien cordialement,",
        "",
        "MailLens",
    ]
    subject = random.choice(PITCH_SUBJECTS).format(company=company)
    return {
        "subject": subject,
        "text": "\n".join(line for line in body if line.strip()),
        "opener": src,
    }


def _pitch_company(domain):
    parts = domain.split(".")
    name = parts[-2] if len(parts) >= 2 else parts[0]
    return name.replace("-", " ").capitalize()