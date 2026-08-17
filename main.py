from fastapi import FastAPI, HTTPException, Header, Depends
from typing_extensions import TypedDict
from typing import Optional
import db
import auth
from pydantic import BaseModel, ValidationError
import os
from src.llm.schema import TriageInput, TriageOutput
from openai import OpenAI
import json
import logging
import time
import random
import logging

os.makedirs("logs", exist_ok=True)

llm_client = OpenAI(
    base_url=os.environ["LLM_BASE_URL"],
    api_key=os.environ["LLM_API_KEY"],
    timeout=30.0,
    max_retries=0, 
)

logging.basicConfig(level=logging.INFO)
cost_logger = logging.getLogger("llm_cost")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}

def call_model(user_text: str, repair_context: str = None):
    messages = [
        {"role": "system", "content": TRIAGE_PROMPT},
        {"role": "user", "content": user_text},
    ]
    if repair_context:
        messages.append({"role": "assistant", "content": repair_context})
        messages.append({"role": "user", "content": "Your previous answer was rejected. Return only corrected JSON matching the schema."})

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        start = time.monotonic()
        try:
            response = llm_client.chat.completions.create(
                model=os.environ["LLM_MODEL"],
                temperature=0.2,
                messages=messages,
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            usage = response.usage
            cost_logger.info(json.dumps({
                "prompt_version": "triage-v1",
                "model": os.environ["LLM_MODEL"],
                "input_tokens": usage.prompt_tokens if usage else None,
                "output_tokens": usage.completion_tokens if usage else None,
                "duration_ms": duration_ms,
                "attempt": attempt,
                "repair": repair_context is not None,
            }))
            return response.choices[0].message.content

        except Exception as e:
            status_code = getattr(e, "status_code", None)
            if status_code in RETRYABLE_STATUS and attempt < max_attempts:
                wait = (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                time.sleep(wait)
                continue
            elif status_code == 504 or "timeout" in str(e).lower():
                raise HTTPException(status_code=504, detail="Model call timed out")
            else:
                raise HTTPException(status_code=502, detail=f"Model call failed: {str(e)}")

        except Exception as e:
            status_code = getattr(e, "status_code", None)
            if status_code in RETRYABLE_STATUS and attempt < max_attempts:
                wait = (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                time.sleep(wait)
                continue
            elif status_code == 504 or "timeout" in str(e).lower():
                raise HTTPException(status_code=504, detail="Model call timed out")
            else:
                raise HTTPException(status_code=502, detail=f"Model call failed: {str(e)}")

with open("prompts/triage-v1.md") as f:
    TRIAGE_PROMPT = f.read()

def extract_json(text: str) -> str:
    """Strip code fences and surrounding text, return the JSON substring."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in model output")
    return text[start:end + 1]

def quarantine(input_text: str, raw_output: str, error: str):
    with open("logs/quarantine.jsonl", "a") as f:
        f.write(json.dumps({
            "input": input_text,
            "raw_output": raw_output,
            "error": error,
            "prompt_version": "triage-v1"
        }) + "\n")

class AuthRequest(BaseModel):
    email: str
    password: str

app = FastAPI()

class Tasks(TypedDict):
    id: int
    title: str
    done: bool

class updateTasks(TypedDict):
    title: Optional[str]
    done: Optional[bool]

conn, cur = db.getdb()
db.initialize_table(conn, cur)

data = db.retrieve_all(conn, cur)
if len(data) == 0:
    tasks = [
        Tasks(id=1,title='solve homework', done=False),
        Tasks(id=2,title='get groceries', done=True),
        Tasks(id=3,title='work out', done=False)
    ]
    tasks_tuples = [(rec['id'], rec['title'], rec['done']) for rec in tasks]
    db.insert_data(conn, cur, tasks_tuples)

@app.get("/protected/profile")
def profile(user = Depends(auth.get_current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "created_at": user.created_at
    }

@app.post("/auth/logout", status_code=204)
def logout(user = Depends(auth.get_current_user)):
    auth.supabase.auth.sign_out()
    return None

@app.get("/public/info")
def public_info():
    return {"message": "Welcome stranger! This info is public."}

@app.post("/auth/signup", status_code=201)
def signup(creds: AuthRequest):
    if not creds.email or not creds.password:
        raise HTTPException(status_code=400, detail="Email and password are required")
    try:
        result = auth.supabase.auth.sign_up({
            "email": creds.email,
            "password": creds.password
        })
        return result.user
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/triage", response_model=TriageOutput)
def triage(payload: TriageInput):
    if os.environ.get("LLM_ENABLED", "true").lower() == "false":
        return TriageOutput(category="other", urgency="low", confidence=0.0)

    if os.environ.get("LLM_STUB") == "1":
        return TriageOutput(category="other", urgency="low", confidence=0.42)

    raw_text = call_model(payload.text)

    try:
        json_str = extract_json(raw_text)
        return TriageOutput.model_validate_json(json_str)
    except (ValidationError, ValueError, json.JSONDecodeError) as first_error:
        # repair retry — one shot only
        repaired_raw = call_model(payload.text, repair_context=raw_text)
        try:
            json_str = extract_json(repaired_raw)
            return TriageOutput.model_validate_json(json_str)
        except (ValidationError, ValueError, json.JSONDecodeError) as second_error:
            quarantine(payload.text, repaired_raw, str(second_error))
            raise HTTPException(status_code=422, detail="Model could not produce a valid response")

@app.post("/auth/login")
def login(creds: AuthRequest):
    if not creds.email or not creds.password:
        raise HTTPException(status_code=400, detail="Email and password are required")
    try:
        result = auth.supabase.auth.sign_in_with_password({
            "email": creds.email,
            "password": creds.password
        })
        return {
            "access_token": result.session.access_token,
            "refresh_token": result.session.refresh_token
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid login credentials")

@app.get('/tasks')
def return_tasks():
    return db.retrieve_all(conn, cur)

@app.get("/tasks/{req_id}")
def return_task(req_id: int):
    result = db.retrieve(conn, cur, req_id)
    if "404" in result:
        raise HTTPException(status_code=404, detail="Task not found")
    return result["200"]

@app.post("/tasks/", status_code=201)
def create_task(task: Tasks):
    if not task.get("title"):
        raise HTTPException(status_code=400, detail="Title is required")
    tuple_task = (task['id'], task['title'], task['done'])
    return db.insert_data(conn, cur, tuple_task)

@app.put("/tasks/{req_id}")
def update_task(req_id: int, task: updateTasks):
    existing = db.retrieve(conn, cur, req_id)
    if "404" in existing:
        raise HTTPException(status_code=404, detail="Task not found")
    task['id'] = req_id
    return db.update(conn, cur, task)

@app.delete("/tasks/{req_id}", status_code=204)
def del_task(req_id: int):
    result = db.delete(conn, cur, req_id)
    if "404" in result:
        raise HTTPException(status_code=404, detail="Task not found")
    return None