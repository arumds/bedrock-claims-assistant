"""Extra - Simple Flask web interface + feedback mechanism.

  python extras/web_app.py      ->  http://127.0.0.1:5000

Upload a claim (txt/md/pdf/docx), it is stored in S3, processed by the
Step 3 pipeline, and the result is shown. Thumbs up/down feedback is saved to
S3 under feedback/ and to extras/feedback.jsonl.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, redirect, render_template_string, request, url_for
from werkzeug.utils import secure_filename

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from step2_poc.upload_documents import ALLOWED  # noqa: E402
from step3_components.claim_pipeline import ClaimPipeline  # noqa: E402

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # Converse document limit is 4.5 MB
pipe = ClaimPipeline()
RESULTS: dict[str, dict] = {}
FEEDBACK_FILE = Path(__file__).with_name("feedback.jsonl")

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Claims PoC</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#1f2937;background:#f8fafc}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:1rem 1.25rem;margin:1rem 0}
h1{font-size:1.4rem} h2{font-size:1.05rem;margin-top:0} pre{white-space:pre-wrap;background:#f1f5f9;padding:.75rem;border-radius:6px;font-size:.85rem}
.tag{display:inline-block;padding:.1rem .5rem;border-radius:99px;font-size:.8rem;background:#e0e7ff;margin-right:.3rem}
.warn{color:#b45309} .err{color:#b91c1c} button{padding:.45rem .9rem;border-radius:6px;border:1px solid #cbd5e1;background:#fff;cursor:pointer}
button.primary{background:#2563eb;color:#fff;border-color:#2563eb} table{border-collapse:collapse;width:100%} td{border-bottom:1px solid #eee;padding:.3rem .4rem;font-size:.9rem}
</style></head><body>
<h1>Insurance claim processor <span class="tag">{{ 'MOCK' if mock else region }}</span></h1>
<div class="card"><h2>1. Upload a claim document</h2>
<form method="post" action="{{ url_for('upload') }}" enctype="multipart/form-data">
<input type="file" name="file" required> <button class="primary">Upload &amp; process</button></form>
<p style="font-size:.85rem">Or process an existing document:</p>
<form method="post" action="{{ url_for('process_existing') }}"><select name="key">
{% for k in keys %}<option>{{ k }}</option>{% endfor %}</select> <button>Process</button></form></div>
{% if r %}
<div class="card"><h2>2. Extracted information <span class="tag">{{ r.models.extraction }}</span></h2>
{% if r.pii_redacted %}<p class="warn">Redacted before sending to model: {{ r.pii_redacted }}</p>{% endif %}
<table>{% for k, v in (r.extracted_info or {}).items() %}<tr><td><b>{{ k }}</b></td><td>{{ v }}</td></tr>{% endfor %}</table>
{% for e in r.extraction_validation.errors %}<p class="err">✗ {{ e }}</p>{% endfor %}
{% for w in r.extraction_validation.warnings %}<p class="warn">⚠ {{ w }}</p>{% endfor %}</div>
<div class="card"><h2>3. Claim summary <span class="tag">{{ r.models.summary }}</span></h2>
<p>{% for s in r.policy_sections_used %}<span class="tag">{{ s }}</span>{% endfor %}</p>
<pre>{{ r.summary }}</pre>
{% for w in r.summary_validation.warnings %}<p class="warn">⚠ {{ w }}</p>{% endfor %}
<p style="font-size:.85rem">{{ r.metrics }}</p>
<form method="post" action="{{ url_for('feedback', rid=rid) }}">
<b>Was this useful?</b> <button name="rating" value="up">👍</button> <button name="rating" value="down">👎</button>
<input name="comment" placeholder="optional comment" style="width:50%"></form>
{% if thanks %}<p>Thanks - feedback saved.</p>{% endif %}</div>{% endif %}
</body></html>"""


def _render(rid=None, thanks=False):
    return render_template_string(PAGE, keys=pipe.store.list_keys(config.CLAIMS_PREFIX),
                                  r=RESULTS.get(rid), rid=rid, thanks=thanks,
                                  mock=config.MOCK_MODE, region=config.REGION)


@app.get("/")
def index():
    """Home page: upload form, plus the selected result if any."""
    return _render(request.args.get("rid"), request.args.get("thanks") == "1")


def _run(key: str):
    rid = uuid.uuid4().hex[:10]
    RESULTS[rid] = pipe.process(key)
    return redirect(url_for("index", rid=rid))


@app.post("/upload")
def upload():
    """Save an uploaded claim to S3 and process it."""
    f = request.files.get("file")
    name = secure_filename(f.filename) if f else ""
    if not name or Path(name).suffix.lower() not in ALLOWED:
        return f"Unsupported file. Allowed: {sorted(ALLOWED)}", 400
    tmp = config.PROJECT_ROOT / ".uploads" / name
    tmp.parent.mkdir(exist_ok=True)
    f.save(tmp)
    key = config.CLAIMS_PREFIX + name
    pipe.store.upload_file(tmp, key)
    tmp.unlink(missing_ok=True)
    return _run(key)


@app.post("/process")
def process_existing():
    """Process a claim that is already in the bucket."""
    return _run(request.form["key"])


@app.post("/feedback/<rid>")
def feedback(rid):
    """Store a thumbs-up/down rating with the model IDs and prompt versions."""
    r = RESULTS.get(rid, {})
    entry = {
        "id": rid,
        "at": datetime.now(timezone.utc).isoformat(),
        "document": r.get("document"),
        "models": r.get("models"),
        "prompt_versions": r.get("prompt_versions"),
        "rating": request.form.get("rating"),
        "comment": request.form.get("comment", "")[:1000],
    }
    with FEEDBACK_FILE.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
    pipe.store.put_json(f"{config.FEEDBACK_PREFIX}{rid}.json", entry)
    return redirect(url_for("index", rid=rid, thanks=1))


if __name__ == "__main__":
    app.run(debug=False, port=5000)
