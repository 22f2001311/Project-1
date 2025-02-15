from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import os
import json
import sqlite3
import requests
import markdown
import duckdb
from datetime import datetime
from openai import OpenAI
from PIL import Image
import pytesseract
import pandas as pd
from io import BytesIO
from bs4 import BeautifulSoup
import uvicorn

SAFE_FUNCTIONS = {
    "install_and_run": install_and_run,
    "format_markdown": format_markdown,
    "count_weekdays": count_weekdays,
    "sort_contacts": sort_contacts,
    "extract_log_lines": extract_log_lines,
    "extract_email": extract_email,
    "calculate_sales": calculate_sales,
    "fetch_api_data": fetch_api_data,
    "clone_and_commit": clone_and_commit,
    "run_sql": run_sql,
    "scrape_website": scrape_website,
    "convert_md_to_html": convert_md_to_html
}
app = FastAPI()
DATA_DIR = "/data"
AIPROXY_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6IjIyZjIwMDEzMTFAZHMuc3R1ZHkuaWl0bS5hYy5pbiJ9.zREmyIWRLAyv0sgEc-zpRNhoviGVMeo--fiLqQ94m7w"

client = OpenAI(api_key=AIPROXY_TOKEN, base_url="https://aiproxy.sanand.workers.dev/openai/")

def secure_path(path):
    if not path.startswith(DATA_DIR):
        raise HTTPException(status_code=403, detail="Access denied outside /data directory")
    return path

def parse_task_with_llm(task_description):
    prompt = f"""
    Given the following task description, extract the key details:
   
    Task: "{task_description}"
   
    Return the response as a JSON object with:
    - "action" (the main operation to perform, e.g., "install_and_run", "format_file", etc.)
    - Other relevant fields needed for execution.
   
    Example outputs:
    1. Input: "Count the number of Wednesdays in /data/dates.txt and save to /data/dates-wednesdays.txt"
       Output: {{"action": "count_weekdays", "file": "/data/dates.txt", "weekday": "Wednesday", "output": "/data/dates-wednesdays.txt"}}

    2. Input: "Format the contents of /data/format.md using Prettier."
       Output: {{"action": "format_file", "file": "/data/format.md"}}

    Now, extract the structured information from the task description:
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": "You are an AI that extracts structured data from task descriptions."},
                  {"role": "user", "content": prompt}],
        temperature=0
    )

    try:
        structured_data = json.loads(response.choices[0].message.content.strip())
        return structured_data
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid LLM response: {str(e)}")

def safe_execute_task(task_steps):
    executed_steps = []
    
    for step in task_steps["steps"]:
        try:
            func_name, args = step.split("(", 1)
            args = args.rstrip(")").split(",") if args else []
            args = [arg.strip().strip("'").strip('"') for arg in args]

            if func_name in SAFE_FUNCTIONS:
                result = SAFE_FUNCTIONS[func_name](*args)
                executed_steps.append({"function": func_name, "result": result})
            else:
                raise HTTPException(status_code=403, detail=f"Unauthorized function: {func_name}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Execution error: {str(e)}")

    return {"status": "success", "steps_executed": executed_steps}   

def execute_task(task):
    try:
        task_steps = parse_task_with_llm(task)
        return safe_execute_task(task_steps)  
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent Error: {str(e)}")

@app.post("/run")
def run_task(task: str):
    if not task:
        raise HTTPException(status_code=400, detail="Task description is required")
    return execute_task(task)

@app.get("/read")
def read_file(path: str):
    secure_path(path)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    with open(path, "r") as f:
        return f.read()

@app.post("/install-and-run")
def install_and_run(email: str):
    subprocess.run(["pip", "install", "uv"], shell=False, check=True)
    result = subprocess.run(["uv", "run", "https://raw.githubusercontent.com/sanand0/tools-in-data-science-public/tds-2025-01/project-1/datagen.py", email], capture_output=True, text=True)
    return {"status": "success", "output": result.stdout}

@app.post("/format-md")
def format_markdown():
    subprocess.run(["npx", "prettier@3.4.2", "--write", "/data/format.md"], check=True)
    return {"status": "success"}

@app.post("/count-weekdays")
def count_weekdays(input_file: str, weekday: str, output_file: str):
    secure_path(input_file)
    secure_path(output_file)
    with open(input_file) as f:
        lines = f.readlines()
    count = sum(1 for line in lines if datetime.strptime(line.strip(), "%Y-%m-%d").strftime("%A") == weekday)
    with open(output_file, "w") as f:
        f.write(str(count))
    return {"status": "success", "count": count}

@app.post("/sort-contacts")
def sort_contacts():
    with open("/data/contacts.json") as f:
        contacts = json.load(f)
    sorted_contacts = sorted(contacts, key=lambda x: (x["last_name"], x["first_name"]))
    with open("/data/contacts-sorted.json", "w") as f:
        json.dump(sorted_contacts, f, indent=2)
    return {"status": "success"}

@app.post("/extract-log-lines")
def extract_log_lines():
    logs = sorted(os.listdir("/data/logs/"), key=lambda x: os.path.getmtime(f"/data/logs/{x}"), reverse=True)[:10]
    with open("/data/logs-recent.txt", "w") as f:
        for log in logs:
            with open(f"/data/logs/{log}") as log_f:
                f.write(log_f.readline())
    return {"status": "success"}

@app.post("/extract-email")
def extract_email():
    with open("/data/email.txt") as f:
        email_text = f.read()

    prompt = (
        "Extract the sender's email address from the following email text. "
        "Respond only with a JSON object containing {'email': 'email@example.com'}.\n\n"
        f"Email Text:\n{email_text}"
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    try:
        email_data = json.loads(response.choices[0].message.content.strip())
        if "email" not in email_data:
            raise ValueError("Missing 'email' key in response")
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"Invalid LLM response: {str(e)}")

    with open("/data/email-sender.txt", "w") as f:
        f.write(email_data["email"])

    return {"status": "success", "email": email_data["email"]}

@app.post("/calculate-sales")
def calculate_sales():
    conn = sqlite3.connect("/data/ticket-sales.db")
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(units * price) FROM tickets WHERE type = 'Gold'")
    total_sales = cursor.fetchone()[0] or 0
    conn.close()
    with open("/data/ticket-sales-gold.txt", "w") as f:
        f.write(str(total_sales))
    return {"status": "success", "total_sales": total_sales}

### 🔥 **Phase B Tasks** (Advanced Automation) ###

@app.post("/fetch-api-data")
def fetch_api_data(url: str, output_file: str):
    secure_path(output_file)
    response = requests.get(url)
    with open(output_file, "w") as f:
        f.write(response.text)
    return {"status": "success"}

@app.post("/clone-and-commit")
def clone_and_commit(repo_url: str, commit_msg: str):
    subprocess.run(["git", "clone", repo_url, "/data/repo"], check=True)
    os.chdir("/data/repo")
    subprocess.run(["git", "commit", "-am", commit_msg], check=True)
    subprocess.run(["git", "push"], check=True)
    return {"status": "success"}

@app.post("/run-sql")
def run_sql(query: str, db_file: str):
    secure_path(db_file)
    conn = duckdb.connect(db_file)
    result = conn.execute(query).fetchall()
    conn.close()
    return {"status": "success", "result": result}

@app.post("/scrape-website")
def scrape_website(url: str, output_file: str):
    secure_path(output_file)
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text()
    with open(output_file, "w") as f:
        f.write(text)
    return {"status": "success"}

@app.post("/convert-md-to-html")
def convert_md_to_html():
    with open("/data/docs/index.md") as f:
        md_content = f.read()
    html_content = markdown.markdown(md_content)
    with open("/data/docs/index.html", "w") as f:
        f.write(html_content)
    return {"status": "success"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)