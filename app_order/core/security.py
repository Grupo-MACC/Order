import jwt
from dependencies import PUBLIC_KEY_PATH
from config import settings

def read_public_pem():
    with open(PUBLIC_KEY_PATH, "r", encoding="utf-8") as f:
        return f.read()

def decode_token(token: str) -> dict:
    public_pem = read_public_pem()
    try:
        payload = jwt.decode(token, public_pem, algorithms=[settings.ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token expired")
    except jwt.InvalidSignatureError:
        raise ValueError("Invalid signature – check your RSA keys")
    except jwt.InvalidAlgorithmError:
        raise ValueError("Algorithm mismatch – check settings.ALGORITHM")
    except jwt.DecodeError:
        raise ValueError("Malformed token")
    except Exception as e:
        raise ValueError(f"Unexpected error decoding token: {str(e)}")