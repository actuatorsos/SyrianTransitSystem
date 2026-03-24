"""Minimal test endpoint to diagnose Vercel Python runtime."""

from fastapi import FastAPI

app = FastAPI()

@app.get("/api/test")
def test():
    result = {"status": "ok", "python": "working"}

    # Test each dependency
    try:
        import httpx
        result["httpx"] = "ok"
    except Exception as e:
        result["httpx"] = str(e)

    try:
        import jwt
        result["pyjwt"] = "ok"
    except Exception as e:
        result["pyjwt"] = str(e)

    try:
        import bcrypt
        result["bcrypt"] = "ok"
    except Exception as e:
        result["bcrypt"] = str(e)

    try:
        from pydantic import BaseModel
        result["pydantic"] = "ok"
    except Exception as e:
        result["pydantic"] = str(e)

    try:
        from dotenv import load_dotenv
        result["dotenv"] = "ok"
    except Exception as e:
        result["dotenv"] = str(e)

    import os
    result["SUPABASE_URL"] = "set" if os.getenv("SUPABASE_URL") else "missing"
    result["SUPABASE_KEY"] = "set" if os.getenv("SUPABASE_KEY") else "missing"
    result["SUPABASE_SERVICE_KEY"] = "set" if os.getenv("SUPABASE_SERVICE_KEY") else "missing"
    result["JWT_SECRET"] = "set" if os.getenv("JWT_SECRET") else "missing"

    return result
