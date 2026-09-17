import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import FileResponse
from pydantic import BaseModel
from passlib.context import CryptContext
from jose import JWTError, jwt

# Import zadania asynchronicznego z workera Celery
from app.celery_worker import process_file_task


# ==========================================
# CONFIGURATION & SECURITY SETUP
# ==========================================

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "admin123")
DB_PORT = os.getenv("DB_PORT", "5432")

SECRET_KEY = "super-secret-key-change-it"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="FileShare API z PostgreSQL i Celery")


# ==========================================
# DATABASE CONNECTION & INITIALIZATION
# ==========================================

def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT
    )


@app.on_event("startup")
def startup_event():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id SERIAL PRIMARY KEY,
                    filename VARCHAR(255) NOT NULL,
                    filepath VARCHAR(500) NOT NULL,
                    token VARCHAR(100) UNIQUE NOT NULL,
                    expires_at TIMESTAMP WITH TIME ZONE,
                    owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    access_type VARCHAR(20) DEFAULT 'link'
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_permissions (
                    file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    PRIMARY KEY (file_id, user_id)
                );
            """)
            conn.commit()


# ==========================================
# PYDANTIC SCHEMAS
# ==========================================

class UserCreate(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


# ==========================================
# AUTHENTICATION & UTILITY FUNCTIONS
# ==========================================

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s;", (username,))
            user = cursor.fetchone()
            if user is None:
                raise credentials_exception
            return user


# ==========================================
# API ENDPOINTS
# ==========================================

@app.post("/register", status_code=status.HTTP_201_CREATED)
def register(user: UserCreate):
    hashed_password = get_password_hash(user.password)
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id, username;",
                    (user.username, hashed_password)
                )
                new_user = cursor.fetchone()
                conn.commit()
                return {"message": "User created successfully", "username": new_user[1]}
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=400, detail="Username already registered")


@app.post("/token", response_model=Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s;", (form_data.username,))
            user = cursor.fetchone()

    if not user or not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/upload")
def upload_file(
    file: UploadFile = File(...),
    access_type: str = Form("link"),
    allowed_usernames: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user)
):
    file_token = str(uuid.uuid4())
    unique_filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO files (filename, filepath, token, expires_at, owner_id, access_type) 
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;
                """,
                (file.filename, file_path, file_token, expires_at, current_user["id"], access_type)
            )
            file_id = cursor.fetchone()[0]

            if access_type == "restricted" and allowed_usernames:
                usernames_list = [u.strip() for u in allowed_usernames.split(",") if u.strip()]
                for uname in usernames_list:
                    cursor.execute("SELECT id FROM users WHERE username = %s;", (uname,))
                    target_user = cursor.fetchone()
                    if target_user:
                        target_id = target_user[0]
                        cursor.execute(
                            "INSERT INTO file_permissions (file_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                            (file_id, target_id)
                        )

            conn.commit()

    # Zlecenie zadania w tle do zewnętrznego workera Celery przez Redisa
    task = process_file_task.delay(file.filename, current_user["username"])

    return {
        "filename": file.filename,
        "download_link": f"/download/{file_token}",
        "access_type": access_type,
        "task_id": task.id,
        "message": "File uploaded successfully and task sent to Celery worker!"
    }


@app.get("/download/{file_token}")
def download_file(file_token: str, request: Request, token: Optional[str] = None):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM files WHERE token = %s;", (file_token,))
            file_record = cursor.fetchone()

    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    if file_record["expires_at"] and file_record["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="File link has expired")

    if file_record["access_type"] == "restricted":
        auth_header = request.headers.get("Authorization")
        current_user = None
        
        if auth_header and auth_header.startswith("Bearer "):
            jwt_token = auth_header.split(" ")[1]
            try:
                payload = jwt.decode(jwt_token, SECRET_KEY, algorithms=[ALGORITHM])
                username: str = payload.get("sub")
                if username:
                    with get_connection() as conn:
                        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                            cursor.execute("SELECT * FROM users WHERE username = %s;", (username,))
                            current_user = cursor.fetchone()
            except JWTError:
                pass

        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required to access this restricted file")

        if current_user["id"] != file_record["owner_id"]:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        "SELECT 1 FROM file_permissions WHERE file_id = %s AND user_id = %s;",
                        (file_record["id"], current_user["id"])
                    )
                    permitted = cursor.fetchone()
            if not permitted:
                raise HTTPException(status_code=403, detail="Access denied: you are not on the allowed list for this file")

    if os.path.exists(file_record["filepath"]):
        return FileResponse(file_record["filepath"], filename=file_record["filename"])
    
    raise HTTPException(status_code=404, detail="File on disk not found")

