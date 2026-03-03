import os
import json
import requests
from flask import Flask, render_template, request
from google import genai
from google.genai import types

app = Flask(__name__)

# =============================
# CONFIGURATION (ENV VARIABLES)
# =============================
PROJECT_ID = 10000

JIRA_AUTH = os.getenv("JIRA_AUTH")
AIO_AUTH = os.getenv("AIO_AUTH")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

STATUS_PUBLISHED = 3


# =============================
# ADF TEXT EXTRACTOR
# =============================
def extract_text_from_adf(node):
    text = ""

    if isinstance(node, dict):
        if node.get("type") == "text":
            text += node.get("text", "")

        if "content" in node:
            for child in node["content"]:
                text += extract_text_from_adf(child)

        if node.get("type") in ["paragraph", "listItem"]:
            text += "\n"

    elif isinstance(node, list):
        for item in node:
            text += extract_text_from_adf(item)

    return text


# =============================
# GET JIRA TICKET
# =============================
def get_ticket_details(ticket_id):

    if not JIRA_AUTH:
        raise Exception("JIRA_AUTH not configured.")

    url = f"https://gosalapavankalyan.atlassian.net/rest/api/3/issue/{ticket_id}?fields=summary,description"

    headers = {
        "Authorization": JIRA_AUTH,
        "Accept": "application/json"
    }

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    data = response.json()

    summary = data["fields"].get("summary", "")
    desc_obj = data["fields"].get("description")
    description = extract_text_from_adf(desc_obj).strip()

    return summary, description


# =============================
# GENERATE TEST CASES
# =============================
def generate_test_cases(ticketdata):

    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY not configured.")

    client = genai.Client(api_key=GEMINI_API_KEY)

    SYSTEM_PROMPT = """
    You are a Senior QA Automation Engineer.

    Generate Positive, Negative, and Boundary test cases.

    STRICT RULES:
    - Return ONLY valid JSON array.
    - Each test case MUST contain:
        title (string)
        description (string)
        precondition (string)
        steps (array of objects)
    - Each step object MUST contain:
        step
        data
        expectedResult
        stepType = "TEXT"
    """

    formatted_input = f"{SYSTEM_PROMPT}\n\nContext:\n{ticketdata}"

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=formatted_input,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json"
        )
    )

    parsed = json.loads(response.text)

    if isinstance(parsed, dict):
        parsed = [parsed]

    return parsed


# =============================
# CREATE + LINK TEST CASE
# =============================
def create_and_link_testcase(ticket_id, test_case):

    if not AIO_AUTH:
        raise Exception("AIO_AUTH not configured.")

    create_url = f"https://tcms.aiojiraapps.com/aio-tcms/api/v1/project/{PROJECT_ID}/testcase"

    headers = {
        "Authorization": AIO_AUTH,
        "Content-Type": "application/json"
    }

    payload = {
        "title": test_case.get("title"),
        "description": test_case.get("description"),
        "precondition": test_case.get("precondition"),
        "scriptType": {"ID": 1},
        "status": {"ID": STATUS_PUBLISHED},
        "steps": test_case.get("steps", [])
    }

    response = requests.post(create_url, headers=headers, json=payload)

    if response.status_code not in [200, 201]:
        raise Exception("Failed to create test case in AIO.")

    testcase_id = response.json().get("ID")

    link_url = f"https://tcms.aiojiraapps.com/aio-tcms/api/v1/project/{PROJECT_ID}/testcase/{testcase_id}/detail"

    payload["jiraRequirementIDs"] = [ticket_id]

    requests.put(link_url, headers=headers, json=payload)


# =============================
# ROUTE
# =============================
@app.route("/", methods=["GET", "POST"])
def index():

    generated_cases = []
    message = ""
    ticket_id = ""
    story_summary = ""
    story_description = ""

    if request.method == "POST":

        ticket_id = request.form.get("ticket_id")

        try:
            summary, description = get_ticket_details(ticket_id)

            story_summary = summary
            story_description = description

            ticket_context = f"Summary: {summary}\nDescription: {description}"

            test_cases = generate_test_cases(ticket_context)

            for case in test_cases:
                create_and_link_testcase(ticket_id, case)

            generated_cases = test_cases
            message = f"Test cases are generated and attached to ticket {ticket_id} successfully."

        except Exception as e:
            message = f"Error: {str(e)}"

    return render_template(
        "index.html",
        cases=generated_cases,
        message=message,
        ticket_id=ticket_id,
        story_summary=story_summary,
        story_description=story_description
    )


if __name__ == "__main__":
    app.run()