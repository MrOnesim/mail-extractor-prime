# MailLens

[![CI](https://github.com/MrOnesim/mail-extractor-prime/actions/workflows/ci.yml/badge.svg)](https://github.com/MrOnesim/mail-extractor-prime/actions/workflows/ci.yml)

Extracteur et analyseur intelligent d'emails : collez un texte, l'outil extrait,
nettoie, valide et qualifie chaque adresse, puis alimente une base de leads avec
dédoublonnage automatique par identité.

## Fonctionnalités

- **Extraction** d'emails depuis n'importe quel texte brut (regex renforcée, gestion
  des typos courantes type `gmail.cmo`, `gmal.com`, `comail.com`).
- **Validation DNS** des domaines (MX concurrent, cache TTL 300 s, timeout paramétrable).
- **Scoring** `0–100` : qualité du domaine (pro/perso/générique/jetable), activité
  détectée (`vu <date>`), sources (LinkedIn, Signature, corps…).
- **Visualisation** : badges statut/audience/source, jauge de score, tags persistés,
  pagination 50, exports (copie filtrée, CSV, JSON), insights en barres, thème clair/sombre.
- **Générateurs** : emails de test réalistes, estimation d'adresse entreprise
  (domaine + prénom/nom).
- **Cold email** : génération d'un pitch de relance par contact.
- **Base de leads** (SQLite) : import en un clic, fusion d'identité automatique
  (`jean.dupont@` = `j.dupont@` = `dupont.jean@`), statuts/notes éditables,
  suppression, filtres, export CSV et **tableau de bord** (répartitions, top domaines,
  sources, timeline des imports).

## Stack

- Python 3.9+, Flask 3.1, `psycopg[binary,pool]`
- Stockage : SQLite (dev) ou **Postgres Neon** (production) — automatique via `DATABASE_URL`
- dnspython pour la validation MX
- Front vanilla (HTML/CSS/JS), aucune dépendance côté client

## Lancement local

```bash
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # renseigner DATABASE_URL pour tester Neon en local
python app.py
```

Ouvrir <http://localhost:5000> (ou `MAILLENS_PORT` est inutilisé, le serveur tourne
sur le port 5000 ; le port peut être ajusté via `app.run(port=...)`).

Test du backend :

```bash
python -m unittest test_app
```

CI : `.github/workflows/ci.yml` (tests Python 3.11/3.12 + `node --check` sur chaque push/PR).

## Déploiement sur Vercel

`vercel.json` est déjà configuré (`@vercel/python`, toutes les routes dirigées
vers `app.py`, le dossier `static/` est servi par Flask).

**Via l'interface (recommandé)** : pousser le dossier sur un dépôt Git puis
« Add New → Project » sur [vercel.com](https://vercel.com), framework détecté
automatiquement. Construire et déployer sans réglage.

**Via la CLI** :

```bash
npm i -g vercel
vercel          # premier déploiement (aperçu)
vercel --prod   # mise en production
```

### Variables d'environnement (optionnelles)

| Variable | Défaut | Rôle |
|---|---|---|
| `MAILLENS_DNS_TIMEOUT` | `2.0` | Timeout DNS en secondes |
| `MAILLENS_DNS_TTL` | `300` | Cache DNS en secondes |
| `MAILLENS_DNS_WORKERS` | `16` | Threads DNS (max 32) |
| `MAILLENS_RECENT_WINDOW` | `45` | Jours considérés « récent » |
| `MAILLENS_RATE_WINDOW` | `60` | Fenêtre du rate-limit (s) |
| `MAILLENS_RATE_MAX` | `120` | Requêtes max par fenêtre |
| `MAILLENS_DB` | — | Chemin SQLite (si `DATABASE_URL` absent) |
| `DATABASE_URL` | — | Chaîne Postgres **Neon** → persistance serverless |

### NB : persistance sur Vercel (Neon)

Par défaut l'app prend `DATABASE_URL` et, s'il est défini, utilise **Postgres
géré (Neon)** — le stockage devient persistant même en serverless (contrairement
au disque éphémère). Sans `DATABASE_URL`, elle retombe sur SQLite (fichier local
en dev, `/tmp` sur Vercel, donc non persistant).

Setup en 2 minutes :

1. Créer un projet sur [neon.tech](https://neon.tech) (plan gratuit suffisant).
2. Copier la chaîne de connexion : `postgresql://user:password@host/dbname?sslmode=require`.
3. Dans Vercel → Project → **Settings → Environment Variables**, ajouter
   `DATABASE_URL` = cette chaîne (préfixer `PROD` pour la Production) puis
   re-déployer. Le schéma de table est créé automatiquement au premier appel.

Le pool de connexions (`psycopg_pool`, max 4 par instance) est créé paresseusement
au premier appel ; sur Neon, le mode pooler (datasource avec connexion poolée) est
recommandé pour les fonctions serverless. Le rôle est tout aussi utilisable en local :
`DATABASE_URL=... python app.py`.

## Structure

```
app.py            routes Flask + rate-limit
extract.py        extraction, validation DNS, scoring, clés d'audience
generators.py     générateurs démo / estimation d'adresses
pitch.py          génération de relances
leads.py          base de leads SQLite + fusion d'identité + dashboard
templates/        index.html
static/           app.js, style.css
```