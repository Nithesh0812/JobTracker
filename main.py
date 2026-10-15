from fastapi import FastAPI, Depends,HTTPException
from fastapi.security import HTTPAuthorizationCredentials,HTTPBearer
from sqlalchemy.orm import Session
from database import SessionLocal
from fastapi import Query
import models,schemas,crud
from security import verify_password,create_access_token,decode_access_token
from sqlalchemy import text
app = FastAPI()
bearer_scheme=HTTPBearer()
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(credentials:HTTPAuthorizationCredentials=Depends(bearer_scheme),db:Session=Depends(get_db)):
    token=credentials.credentials
    user_id=decode_access_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired Token"
        )
    user=db.get(models.User,user_id)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="User doesnt exist"
        )
    return user

@app.get("/health")
def health_check(db:Session=Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status":"healthy"}
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        )
@app.get("/auth/me",response_model=schemas.UserResponse)
def get_me(current_user=Depends(get_current_user)):
    return current_user

@app.get("/")
def home():
    return {"message": "Job Tracker is running"}

@app.post("/auth/login",response_model=schemas.TokenResponse)
def login(credentials:schemas.UserLogin,db:Session=Depends(get_db)):
    user=crud.get_user_by_email(db,credentials.email)
    if user is None or user.hashed_password is None or not verify_password(credentials.password,user.hashed_password):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )
    access_token=create_access_token({"sub":str(user.id)})
    return{"access_token":access_token,"token_type":"bearer"}

@app.post("/auth/register",response_model=schemas.UserResponse,status_code=201)
def create_user(user:schemas.UserCreate,db:Session=Depends(get_db)):
    return crud.create_user(db,user)

@app.post("/jobs",response_model=schemas.JobApplicationResponse,status_code=201)
def create_job_for_user(job:schemas.JobApplicationCreate,db:Session=Depends(get_db),current_user=Depends(get_current_user)):
    return crud.create_job_applications(db,job,current_user.id)

@app.get("/jobs",response_model=list[schemas.JobApplicationResponse])
def get_jobs_for_user(sort_by:str ="id",order:str ="asc",skip:int=Query(default=0,ge=0),limit:int=Query(default=10,ge=1,le=20),status:schemas.JobStatus |None=None,company:str |None=None,role:str |None=None,db:Session=Depends(get_db),current_user=Depends(get_current_user)):
    return crud.get_jobs_by_user(sort_by=sort_by,order=order,db=db,user_id=current_user.id,status=status,company=company,role=role,skip=skip,limit=limit)

@app.get("/jobs/{job_id}",response_model=schemas.JobApplicationResponse)
def get_jobs_by_id(job_id:int,db:Session=Depends(get_db),current_user=Depends(get_current_user)):
    job=crud.get_job_by_id_for_user(db,job_id=job_id,user_id=current_user.id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"Job does not exist for user_id: {current_user.id} "
        )
    return job

@app.patch("/jobs/{job_id}",response_model=schemas.JobApplicationResponse)
def job_update(job_id:int,job_update:schemas.JobApplicationUpdate,db:Session=Depends(get_db),current_user=Depends(get_current_user)):
    return crud.update_job_application(db,job_id,job_update,user_id=current_user.id)

@app.delete("/jobs/{job_id}")
def job_delete(job_id:int,db:Session=Depends(get_db),current_user=Depends(get_current_user)):
    return crud.delete_job_application(db,job_id=job_id,user_id=current_user.id)
    