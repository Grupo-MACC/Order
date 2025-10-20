import jwt
import os
from fastapi import HTTPException
#from config import settings

PUBLIC_KEY_PATH = "/home/pyuser/code/auth_public.pem"

def read_public_pem():
    if not os.path.exists(PUBLIC_KEY_PATH):
        print("no hay")
        print(PUBLIC_KEY_PATH)
        raise ValueError(f"Public key not found at {PUBLIC_KEY_PATH}")
    with open(PUBLIC_KEY_PATH, "r", encoding="utf-8") as f:
        return f.read()

def decode_token(token: str) -> dict:
    try:
        public_pem = read_public_pem()
        payload = jwt.decode(token, public_pem, algorithms=["RS256"])
        return payload
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail="Public key file not found")
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")