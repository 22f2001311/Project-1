from fastapi import FastAPI, HTTPException
import os

app = FastAPI()

@app.post("/run")
async def run_task(task: str):
    # Placeholder for handling the task
    return {"status": "Task received", "task": task}

@app.get("/read")
async def read_file(path: str):
    try:
        with open(path, "r") as f:
            content = f.read()
        return {"content": content}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
