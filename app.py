"""
app.py
------
Flask backend for the dashboard. Serves the form, receives the
submitted data, triggers the Selenium automation in automation.py,
and renders the results back on the page.
"""

import os
from flask import Flask, render_template, request

from automation import run_automation

app = Flask(__name__)


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", result=None)


@app.route("/run-automation", methods=["POST"])
def trigger_automation():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    first_name = request.form.get("first_name", "").strip()
    last_name = request.form.get("last_name", "").strip()
    employee_id = request.form.get("employee_id", "").strip()

    # Basic validation before we even touch Selenium
    if not all([username, password, first_name, last_name]):
        result = {
            "success": False,
            "message": "Please fill in all required fields.",
            "employee_added": None,
            "employee_table": [],
            "log_file": None,
            "csv_file": None,
        }
        return render_template("index.html", result=result,
                                form_data=request.form)

    result = run_automation(
        username=username,
        password=password,
        first_name=first_name,
        last_name=last_name,
        employee_id=employee_id,
        headless=True,  # set to False locally if you want to watch the browser
    )

    return render_template("index.html", result=result, form_data=request.form)


if __name__ == "__main__":
    app.run(debug=True, port=5000)