from fastapi import FastAPI, HTTPException, Header, Depends
from typing_extensions import TypedDict
from typing import Optional
import db
import auth
from pydantic import BaseModel
import os
from src.llm.schema import TriageInput, TriageOutput
from openai import OpenAI

llm_client = OpenAI(
    base_url=os.environ["LLM_BASE_URL"],
    api_key=os.environ["LLM_API_KEY"],
)

with open("prompts/triage-v1.md") as f:
    TRIAGE_PROMPT = f.read()

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

@app.post("/triage")
def triage(payload: TriageInput):
    if os.environ.get("LLM_STUB") == "1":
        return TriageOutput(category="other", urgency="low", confidence=0.42)

    response = llm_client.chat.completions.create(
        model=os.environ["LLM_MODEL"],
        temperature=0.2,
        messages=[
            {"role": "system", "content": TRIAGE_PROMPT},
            {"role": "user", "content": payload.text},
        ],
    )
    raw_text = response.choices[0].message.content
    print("RAW MODEL OUTPUT:", raw_text)
    return {"raw": raw_text}
    
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