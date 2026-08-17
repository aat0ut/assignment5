import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

def getdb():
    conn = psycopg.connect(DATABASE_URL)
    cur = conn.cursor()
    return conn, cur

def initialize_table(conn, cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks(
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        done BOOLEAN NOT NULL
    )
    """)
    conn.commit()

def insert_data(conn, cur, records):
    query = 'INSERT INTO tasks (title, done) VALUES (%s, %s)'
    if isinstance(records, list):
        stripped = [(r[1], r[2]) for r in records]  # drop id, let SERIAL assign it
        cur.executemany(query, stripped)
        conn.commit()
        return {"201": f"Successfully added {len(records)} records"}
    elif isinstance(records, tuple):
        cur.execute(query, (records[1], records[2]))
        conn.commit()
        return {"201": "Successfully added a record"}
    else:
        return {"400": "Error has occurred"}

def retrieve_all(conn, cur):
    cur.execute('SELECT * FROM tasks')
    results = cur.fetchall()
    data = []
    for result in results:
        data.append({"id": result[0], "title": result[1], "done": result[2]})
    return data

def retrieve(conn, cur, id):
    cur.execute('SELECT * FROM tasks WHERE id=%s', (int(id),))
    result = cur.fetchone()
    if result is None:
        return {"404": {"Error": "Not found"}}
    return {"200": {"id": result[0], "title": result[1], "done": result[2]}}

def update(conn, cur, task):
    cur.execute("UPDATE tasks SET title=%s, done=%s WHERE id=%s", (task['title'], task['done'], task['id']))
    conn.commit()
    return {"200": task}

def delete(conn, cur, id):
    response = retrieve(conn, cur, id)
    if "200" in response:
        cur.execute("DELETE FROM tasks WHERE id=%s", (int(id),))
        conn.commit()
        return {"204": f"Task with id {id} has been deleted successfully"}
    else:
        return response