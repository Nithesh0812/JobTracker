import os
import jwt
from pwdlib import PasswordHash
from datetime import datetime,timezone,timedelta
from dotenv import load_dotenv

load_dotenv()
SECRET_KEY=os.getenv("SECRET_KEY")

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment is not set")

ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES=30

password_hash = PasswordHash.recommended()

def hash_password(password: str) ->str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) ->bool:
    return password_hash.verify(plain_password,hashed_password)

def create_access_token(data:dict)-> str:
    payload=data.copy()

    expire_time=(datetime.now(timezone.utc)+ timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))

    payload.update({"exp":expire_time})

    return jwt.encode(payload,SECRET_KEY,algorithm=ALGORITHM)

def decode_access_token(token:str)->int | None:
    try:
        payload=jwt.decode(token,SECRET_KEY,algorithms=[ALGORITHM])

        user_id=payload.get("sub")
        if user_id is None:
            return None
        
        return int(user_id)
    except(jwt.InvalidTokenError,ValueError):
        return None
        
        