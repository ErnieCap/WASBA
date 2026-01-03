from flask import Flask, render_template, request
from service import assess_case

app = Flask(__name__)


@app.route("/", methods=["GET"])
def index():
    return render_template("form.html")


@app.route("/assess", methods=["POST"])
def assess():
    # --- existing fields ---
    notes = request.form.get("notes", "")
    num_previous_incidents_raw = request.form.get("num_previous_incidents", "0")
    vulnerable_raw = request.form.get("vulnerable_tenant", "no")
    incident_type = request.form.get("incident_type", "")
    criminal_history_raw = request.form.get("has_criminal_history", "no")

    try:
        num_previous_incidents = int(num_previous_incidents_raw)
    except ValueError:
        num_previous_incidents = 0

    vulnerable_tenant = (vulnerable_raw.lower() == "yes")
    has_criminal_history = (criminal_history_raw.lower() == "yes")

    case = {
        "notes": notes,
        "num_previous_incidents": num_previous_incidents,
        "vulnerable_tenant": vulnerable_tenant,
        "incident_type": incident_type,
        "has_criminal_history": has_criminal_history,
    }

    # --- NEW: matrix fields (optional) ---
    # Only include matrix_scores if ALL 14 questions are answered.
    matrix_scores = {}
    all_answered = True
    for i in range(1, 15):
        raw = request.form.get(f"matrix_q{i}", "")
        if raw == "":
            all_answered = False
            break
        try:
            matrix_scores[f"matrix_q{i}"] = int(raw)
        except ValueError:
            all_answered = False
            break

    if all_answered:
        case["matrix_scores"] = matrix_scores

    result = assess_case(case)
    return render_template("result.html", result=result)


if __name__ == "__main__":
    app.run(debug=True)
