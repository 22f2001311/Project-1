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
import openai
from PIL import Image
import pytesseract
import pandas as pd
from io import BytesIO
from bs4 import BeautifulSoup
import uvicorn
import re


app = FastAPI()
DATA_DIR = "/data"
AIPROXY_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6IjIyZjIwMDEzMTFAZHMuc3R1ZHkuaWl0bS5hYy5pbiJ9.zREmyIWRLAyv0sgEc-zpRNhoviGVMeo--fiLqQ94m7w"

client = OpenAI(api_key=AIPROXY_TOKEN, base_url="https://aiproxy.sanand.workers.dev/openai/v1/")

def secure_path(path):
    # Define your project data directory (the allowed base directory)
    project_base_path = os.getenv("PROJECT_BASE_PATH", "/Users/pranjalagrawal/Documents/TDS_Project_1/Project-1/data")
    
    # If the path starts with "/data/", map it to the actual project data directory
    if path.startswith("/data/"):
        # Remove the leading '/data/' and join with the project base path
        path = os.path.join(project_base_path, path[len("/data/"):])
    
    abs_path = os.path.abspath(path)
    print(f"Attempting to secure path: {abs_path}")  # Debug print

    if not abs_path.startswith(project_base_path):
        raise HTTPException(
            status_code=403, 
            detail=f"Access denied: {abs_path} is outside {project_base_path}"
        )
    
    return abs_path


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
    print("LLM Response:", response)
    content = response.choices[0].message.content  # ✅ Get the response content
    content = re.sub(r"^```json\n(.*?)\n```$", r"\1", content, flags=re.DOTALL).strip()
    try:
        structured_data = json.loads(content)
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
        task_data = parse_task_with_llm(task)
        
        # Convert "action" into a single-step execution if needed
        if "action" in task_data:
            action = task_data.pop("action")  # Extract action
            
            # Build the step string using only the values, not the keys
            if task_data:
                # Use only the values (in quotes) to form positional arguments
                step = f'{action}(' + ", ".join('"' + str(v) + '"' for v in task_data.values()) + ')'
            else:
                step = f"{action}()"
            
            print("Generated step:", step)  # For debugging
            task_data["steps"] = [step]
    
        return safe_execute_task(task_data)
    
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
def format_file(file: str = "/data/format.md", *args, **kwargs):
    # Instead of converting to abspath first, let secure_path handle it:
    file = secure_path(file)  # This returns the correct mapped absolute path
    if not os.path.exists(file):
        raise HTTPException(status_code=404, detail=f"File not found: {file}")
    # Run Prettier formatting
    subprocess.run(["npx", "prettier@3.4.2", "--write", file], check=True)
    return {"status": "success", "formatted_file": file}

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

@app.post("/extract-markdown-headers")
def extract_markdown_headers(path: str):
    secure_path(path)
    with open(path, "r") as f:
        md_content = f.read()
    headers = re.findall(r"^(#{1,6})\s+(.+)", md_content, re.MULTILINE)
    return {"headers": [{"level": len(h[0]), "text": h[1]} for h in headers]}

@app.post("/extract-credit-card")
def extract_credit_card():
    with open("/data/transactions.txt") as f:
        text = f.read()
    matches = re.findall(r"\b\d{4}-\d{4}-\d{4}-\d{4}\b", text)
    return {"credit_cards": matches}

@app.post("/find-similar-comments")
def find_similar_comments():
    df = pd.read_csv("/data/comments.csv")
    comments = df["comment"].tolist()
    similarities = {}
    for i, c1 in enumerate(comments):
        for j, c2 in enumerate(comments):
            if i != j and c1[:10] == c2[:10]:
                similarities.setdefault(c1, []).append(c2)
    return {"similar_comments": similarities}

SAFE_FUNCTIONS = {
    "install_and_run": install_and_run, 
    "format_file": format_file,  
    "count_weekdays": count_weekdays,  
    "sort_contacts": sort_contacts,  
    "extract_log_lines": extract_log_lines,  
    "extract_markdown_headers": extract_markdown_headers,  
    "extract_email": extract_email,  
    "extract_credit_card": extract_credit_card,  
    "find_similar_comments": find_similar_comments,  
    "calculate_sales": calculate_sales  
}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)