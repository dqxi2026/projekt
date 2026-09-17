import uuid
from fastapi.testclient import TestClient
from app.main import app


# ==========================================
# CLIENT CONFIGURATION
# ==========================================

client = TestClient(app)


# ==========================================
# AUTHENTICATION & REGISTRATION TESTS
# ==========================================

def test_register_user():
    unique_username = f"testuser_{uuid.uuid4().hex[:6]}"
    response = client.post(
        "/register",
        json={
            "username": unique_username,
            "password": "StrongPassword123"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == unique_username


# ==========================================
# FILE UPLOAD & INTEGRATION TESTS
# ==========================================

def test_login_and_upload_file():
    unique_username = f"uploader_{uuid.uuid4().hex[:6]}"
    password = "StrongPassword123"

    client.post(
        "/register",
        json={
            "username": unique_username,
            "password": password
        }
    )

    login_response = client.post(
        "/token",
        data={
            "username": unique_username,
            "password": password
        }
    )
    assert login_response.status_code == 200
    token_data = login_response.json()
    token = token_data["access_token"]

    file_content = b"To jest zawartosc pliku testowego."
    files = {
        "file": ("test_file.txt", file_content, "text/plain")
    }
    headers = {
        "Authorization": f"Bearer {token}"
    }

    upload_response = client.post(
        "/upload",
        headers=headers,
        files=files,
        data={"access_type": "link"}
    )
    
    assert upload_response.status_code == 200
    upload_data = upload_response.json()
    assert "download_link" in upload_data
    assert upload_data["filename"] == "test_file.txt"
    
    