import os
import re
import time
from collections import defaultdict

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

# Charge .env (local) AVANT que les modules lisent les variables d'environnement.
load_dotenv()

from extract import EMAIL_REGEX, extract, score_label
from generators import generate_demo_text, generate_emails_from_names
from leads import dashboard, delete_lead, list_leads, merge_analysis, stats, update_lead
from pitch import build_pitch

app = Flask(__name__)

RATE_LIMIT_WINDOW = float(os.environ.get("MAILLENS_RATE_WINDOW", "60"))
RATE_LIMIT_MAX = int(os.environ.get("MAILLENS_RATE_MAX", "120"))

_buckets: dict = defaultdict(list)


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@app.before_request
def rate_limit():
    if not (request.path == "/extract"
            or request.path.startswith("/generate/")
            or request.path.startswith("/leads/")):
        return None
    now = time.monotonic()
    bucket = _buckets[request.remote_addr or "local"]
    bucket[:] = [t for t in bucket if now - t < RATE_LIMIT_WINDOW]
    if len(bucket) >= RATE_LIMIT_MAX:
        return jsonify({"error": "Trop de requêtes, réessayez dans quelques instants."}), 429
    bucket.append(now)
    return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/extract", methods=["POST"])
def extract_route():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    if not text.strip():
        return jsonify({"error": "Aucun texte fourni"}), 400
    return jsonify(extract(text))


@app.route("/generate/demo", methods=["POST"])
def generate_demo():
    data = request.get_json(silent=True) or {}
    count = _to_int(data.get("count", 12), 12)
    text = generate_demo_text(count)
    return jsonify({
        "text": text,
        "count": len(re.findall(EMAIL_REGEX.pattern, text, re.IGNORECASE)),
    })


@app.route("/generate/estimate", methods=["POST"])
def generate_estimate():
    data = request.get_json(silent=True) or {}
    domain = (data.get("domain") or "").strip().lower()
    first = (data.get("first_name") or "").strip()
    last = (data.get("last_name") or "").strip()
    if not domain or "." not in domain:
        return jsonify({"error": "Domaine invalide"}), 400
    if not first and not last:
        return jsonify({"error": "Prénom ou nom requis"}), 400
    candidates = generate_emails_from_names(domain, first, last)
    generic = [
        {"email": f"{g}@{domain}", "pattern": "adresse générique"}
        for g in ("contact", "info", "bonjour")
    ]
    return jsonify({
        "domain": domain,
        "candidates": candidates,
        "generic": generic,
        "total": len(candidates) + len(generic),
    })


@app.route("/generate/pitch", methods=["POST"])
def generate_pitch_route():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    if not email or "@" not in email:
        return jsonify({"error": "Email invalide"}), 400
    score = _to_int(data.get("score"), 0)
    heat = score_label(score)
    pitch = build_pitch(
        email,
        data.get("context") or "",
        list(data.get("sources") or []),
        heat,
    )
    return jsonify(pitch)


@app.route("/leads", methods=["GET"])
def leads_list():
    return jsonify({
        "leads": list_leads(
            status=(request.args.get("status") or None) or None,
            q=(request.args.get("q") or "").strip() or None,
        ),
        "stats": stats(),
    })


@app.route("/leads/import", methods=["POST"])
def leads_import():
    data = request.get_json(silent=True) or {}
    results = data.get("emails")
    if not isinstance(results, list) or not results:
        return jsonify({"error": "Aucun résultat à importer"}), 400
    report = merge_analysis(results)
    report["stats"] = stats()
    return jsonify(report)


@app.route("/leads/dashboard", methods=["GET"])
def leads_dashboard():
    return jsonify(dashboard())


@app.route("/leads/<int:lead_id>", methods=["PATCH"])
def leads_update(lead_id):
    data = request.get_json(silent=True) or {}
    lead = update_lead(lead_id, status=data.get("status"), notes=data.get("notes"))
    if lead is None:
        return jsonify({"error": "Lead introuvable"}), 404
    return jsonify(lead)


@app.route("/leads/<int:lead_id>", methods=["DELETE"])
def leads_delete(lead_id):
    if not delete_lead(lead_id):
        return jsonify({"error": "Lead introuvable"}), 404
    return jsonify({"deleted": lead_id, "stats": stats()})


if __name__ == "__main__":
    app.run(debug=True)