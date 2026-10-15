from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from main import app,get_db

import pytest

from models import User

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

def auth_headers(client,email):
    register_response = client.post(
        "/auth/register",
        json={
            "full_name": "Test User",
            "email": email,
            "password": "testpassword123"
        }
    )

    assert register_response.status_code == 201

    login_response = client.post(
        "/auth/login",
        json={
            "email": email,
            "password": "testpassword123"
        }
    )

    assert login_response.status_code == 200

    data = login_response.json()
    access_token = data["access_token"]

    return {"Authorization": f"Bearer {access_token}"}

def test_register_rejects_invalid_email(client):
    response=client.post("/auth/register", json={
        "full_name": "Test User",
        "email": "invalid-email@",
        "password": "testpassword123"
    })
    assert response.status_code == 422

def test_register_rejects_short_password(client):
    response=client.post("/auth/register", json={
        "full_name": "Test User",
        "email": "testuser@example.com",
        "password": "short"
    })
    assert response.status_code == 422

def create_job(client, headers, **overrides):
    job_data = {
        "company": "Test Company",
        "role": "Test Role",
        "status": "Applied",
        "job_link": "https://example.com/job",
        "notes": "Test notes"
    }
    job_data.update(overrides)
    response = client.post(
        "/jobs",
        headers=headers,
        json=job_data
    )
    return response

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

def test_jobs_require_auth(client):
    response = client.get("/jobs")
    assert response.status_code == 401

def test_create_and_get_job(client):
    headers =auth_headers(client,"testuser@example.com")
    create_response = create_job(client, headers)

    assert create_response.status_code == 201
    created_job = create_response.json()
    assert created_job["company"] == "Test Company"
    assert created_job["role"] == "Test Role"
    assert created_job["status"] == "Applied"

    job_id = created_job["id"]
    get_response = client.get(f"/jobs/{job_id}", headers=headers)
    assert get_response.status_code == 200
    retrieved_job = get_response.json()
    assert retrieved_job["company"] == "Test Company"
    assert retrieved_job["role"] == "Test Role"
    assert retrieved_job["status"] == "Applied"

def test_list_jobs_with_defaults(client):
    headers =auth_headers(client,"testuser@example.com")
    create_response=create_job(client,headers)

    assert create_response.status_code==201

    created=create_response.json()

    assert created["company"]=="Test Company"
    assert created["role"]=="Test Role" 
    assert created["status"]=="Applied"

    list_response=client.get(f"/jobs",headers=headers)

    assert list_response.status_code==200

    jobs=list_response.json()
    assert len(jobs)==1
    assert jobs[0]["company"]=="Test Company"
    assert jobs[0]["role"]=="Test Role"
    assert jobs[0]["status"]=="Applied"

def test_filter_jobs_by_status(client):
    headers= auth_headers(client,"testuser@example.com")
    first_job = create_job(client,headers=headers,status="Applied")
    second_job = create_job(client,headers=headers,status="Interview")

    assert first_job.status_code == 201
    assert second_job.status_code == 201

    first_response =client.get("/jobs",headers=headers,params={"status":"Applied"})
    assert first_response.status_code == 200

    jobs=first_response.json()
    assert len(jobs)==1
    assert jobs[0]["status"]=="Applied"

    second_response=client.get("/jobs",headers=headers,params={"status":"Interview"})
    assert second_response.status_code==200

    jobs=second_response.json()
    assert len(jobs)==1
    assert jobs[0]["status"]=="Interview"

def test_invalid_sort_column(client):
    headers = auth_headers(client,"testuser@example.com")

    response=client.get("/jobs",headers=headers,params={"sort_by":"password"})

    assert response.status_code == 400

    assert response.json()["detail"]=="Invalid sort column"

def test_update_job_status(client):
    headers=auth_headers(client,"testuser@example.com")
    create_response = create_job(client,headers=headers)

    assert create_response.status_code == 201

    job_id = create_response.json()["id"]
    update_job_response = client.patch(f"/jobs/{job_id}",headers=headers,json = {"status":"Interview"})

    assert update_job_response.status_code == 200

    assert update_job_response.json()["status"] == "Interview"

def test_delete_job(client):
    headers=auth_headers(client,"testuser@example.com")
    create_response= create_job(client,headers=headers)

    assert create_response.status_code == 201

    job_id =create_response.json()["id"]
    delete_response=client.delete(f"/jobs/{job_id}",headers=headers)
    assert delete_response.status_code == 200

    get_response=client.get(f"/jobs/{job_id}",headers=headers)
    assert get_response.status_code == 404

def test_users_cannot_access_other_users_jobs(client):
    headers_user1 = auth_headers(client,"testuser1@example.com")
    headers_user2 = auth_headers(client,"testuser2@example.com")

    create_response_user1 = create_job(client,headers=headers_user1)
    assert create_response_user1.status_code == 201

    job_id_user1 = create_response_user1.json()["id"]

    # User 2 tries to access User 1's job
    read_response=client.get(f"/jobs/{job_id_user1}",headers=headers_user2)
    assert read_response.status_code == 404

    update_response = client.patch(f"/jobs/{job_id_user1}",headers=headers_user2,json={"notes":"hacked"})
    assert update_response.status_code == 404

    delete_response =client.delete(f"/jobs/{job_id_user1}",headers=headers_user2)
    assert delete_response.status_code == 404

    get_response_user2=client.get(f"/jobs",headers=headers_user2)
    assert get_response_user2.status_code == 200
    assert get_response_user2.json() == []

    get_response_user1 = client.get(f"/jobs/{job_id_user1}",headers=headers_user1)
    assert get_response_user1.status_code == 200
    assert get_response_user1.json()["notes"] == "Test notes"

def test_token_for_deleted_user_is_rejected(client):
    headers = auth_headers(client,"testuser1@example.com")

    db=TestingSessionLocal()
    user=db.query(User).filter(User.email =="testuser1@example.com").first()
    db.delete(user)
    db.commit()
    db.close()

    response= client.get("/auth/me",headers=headers)
    assert response.status_code == 401