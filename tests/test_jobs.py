from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from main import app,get_db

import pytest

TEST_DATABASE_URL="sqlite://"

engine=create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread":False},
        poolclass=StaticPool,
        )

TestingSessionLocal=sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    )

def override_get_db():
    db=TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
app.dependency_overrides[get_db]=override_get_db

@pytest.fixture
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return TestClient(app)

@pytest.fixture
def test_user(client):
    user_data = {
        "full_name": "Test User",
        "email": "testuser@example.com",
        "password": "testpassword123"
    }

    response = client.post(
        "/auth/register",
        json= user_data
        )
    
    assert response.status_code == 201

    return user_data
    

def test_root(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "Job Tracker is running"
    }


def test_create_user(client):
    response = client.post(
        "/auth/register",
        json={
            "full_name": "Test User",
            "email": "testuser@example.com",
            "password": "testpassword123"
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["full_name"] == "Test User"
    assert data["email"] == "testuser@example.com"
    assert "id" in data

def test_login_returns_access_token(client, test_user):
    response = client.post(
        "/auth/login",
        json={
            "email": test_user["email"],
            "password": test_user["password"]
        }
    )

    assert response.status_code == 200

    data = response.json()

    assert "access_token" in data
    assert data["token_type"] == "bearer"