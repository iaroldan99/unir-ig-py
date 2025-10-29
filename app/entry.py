# app/entry.py
from fastapi import FastAPI

app = FastAPI(title="Entry Minimal")

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"ok": True}
