import uuid
from fastapi.testclient import TestClient
from app.main import app

# ==========================================
# CLIENT CONFIGURATION
# ==========================================

client = TestClient(app)


# ==========================================
# 1. TESTY WALIDACJI (Nowe reguły użytkownika i hasła)
# ==========================================

def test_register_username_too_short():
    """Testuje, czy nazwa użytkownika krótsza niż 6 znaków jest odrzucana (422)."""
    response = client.post(
        "/register",
        json={"username": "User", "password": "StrongPassword!1"}
    )
    assert response.status_code == 422


def test_register_username_missing_uppercase():
    """Testuje, czy nazwa użytkownika bez wielkiej litery jest odrzucana (422)."""
    response = client.post(
        "/register",
        json={"username": "dariyatest", "password": "StrongPassword!1"}
    )
    assert response.status_code == 422


def test_register_password_ends_with_space():
    """Testuje, czy hasło kończące się spacją powoduje błąd walidacji (422)."""
    response = client.post(
        "/register",
        json={"username": "DariyaTest", "password": "StrongPassword!1 "}
    )
    assert response.status_code == 422


def test_register_password_missing_special_char():
    """Testuje, czy hasło bez znaku specjalnego jest odrzucane (422)."""
    response = client.post(
        "/register",
        json={"username": "DariyaTest", "password": "StrongPassword123"}
    )
    assert response.status_code == 422


# ==========================================
# 2. AUTHENTICATION & REGISTRATION TESTS
# ==========================================

def test_register_user():
    """Testuje poprawną rejestrację z unikalnym użytkownikiem spełniającym warunki."""
    unique_username = f"Test_{uuid.uuid4().hex[:6]}"
    response = client.post(
        "/register",
        json={
            "username": unique_username,
            "password": "StrongPassword!1"
        }
    )
    assert response.status_code in [200, 201]
    data = response.json()
    assert data["username"] == unique_username


# ==========================================
# 3. FILE UPLOAD & INTEGRATION TESTS
# ==========================================

def test_login_and_upload_file():
    """Testuje pełny przepływ: rejestracja -> logowanie (token) -> wysyłka pliku z autoryzacją."""
    unique_username = f"Uploader_{uuid.uuid4().hex[:6]}"
    password = "StrongPassword!1"

    # Rejestracja
    client.post(
        "/register",
        json={
            "username": unique_username,
            "password": password
        }
    )

    # Logowanie po token
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

    # Przygotowanie pliku do wysyłki
    file_content = b"To jest zawartosc pliku testowego."
    files = {
        "file": ("test_file.txt", file_content, "text/plain")
    }
    headers = {
        "Authorization": f"Bearer {token}"
    }

    # Upload pliku
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


# ==========================================
# 4. SECURITY & ACCESS TESTS
# ==========================================

def test_access_restricted_file_without_token():
    """Sprawdza, czy próba pobrania pliku bez tokena zwraca błąd autoryzacji lub braku zasobu."""
    response = client.get("/files/1")
    assert response.status_code in [401, 403, 404]