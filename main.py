from fastapi import FastAPI, Depends,HTTPException,Response,Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials,HTTPBearer
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError,OperationalError,InterfaceError,TimeoutError as PoolTimeoutError
from sqlalchemy.pool import QueuePool
from database import SessionLocal,engine
from fastapi import Query
import models,schemas,crud
from security import verify_password,create_access_token,decode_access_token
from sqlalchemy import text
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
import metrics
import logging
from logging_config import configure_logging,log_event
from middleware import request_middleware
import time

configure_logging()
logger=logging.getLogger("jobtracker.auth")
db_logger=logging.getLogger("jobtracker.db")
app = FastAPI()
app.middleware("http")(request_middleware)

@app.exception_handler(SQLAlchemyError)
def database_error_handler(request:Request,exc:SQLAlchemyError):
    request.state.error_type=type(exc).__name__

    if isinstance(exc,PoolTimeoutError):
        pool=engine.pool
        is_queue_pool=isinstance(pool,QueuePool)
        metrics.DB_POOL_EXHAUSTED.inc()
        log_event(db_logger,"db_pool_exhausted",logging.ERROR,
                  pool_size=pool.size() if is_queue_pool else None,
                  checked_out=pool.checkedout() if is_queue_pool else None)
        return JSONResponse(status_code=503, content={"detail":" Database unavailable"})

    if isinstance(exc,(OperationalError,InterfaceError)) or getattr(exc,"connection_invalidated",False):
        log_event(db_logger,"db_unavailable",logging.ERROR,error_type=type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail":"Database unavailable"})
    
    log_event(db_logger,"db_transaction_failed",logging.ERROR,error_type=type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail":"Internal Server Error"})

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
        log_event(logger,"auth_token_rejected",logging.WARNING,reason="invalid or expired token")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired Token"
        )
    user=db.get(models.User,user_id)
    if user is None:
        log_event(logger,"auth_token_rejected",logging.WARNING,reason="user not found")
        raise HTTPException(
            status_code=401,
            detail="User doesnt exist"
        )
    return user

#Manually create and pass the db session to the health check endpoint to avoid dependency injection issues
def check_database(db:Session,request:Request):
    """ Run SELECT 1. Return ok and milliseconds taken. If an exception occurs, return ok=False and the exception type in request.state.error_type """
    start = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        ok = True
    except SQLAlchemyError as exc:
        ok = False
        request.state.error_type=type(exc).__name__
    elapsed=time.perf_counter() - start
    metrics.DB_UP.set(1 if ok else 0)
    metrics.DB_CHECK_SECONDS.set(elapsed)
    return ok,round(elapsed * 1000, 2)

@app.get("/health")
def health_check(request:Request, db:Session=Depends(get_db)):
    ok,_=check_database(db,request)
    if not ok:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        )
    return {"status":"healthy"}

@app.get("/metrics",include_in_schema=False)
def metrics_endpoint(request:Request,db:Session=Depends(get_db)):
    check_database(db,request)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
@app.get("/health/live")
def health_live():
    return {"status":"alive"}

@app.get("/health/ready")
def health_ready(request:Request,db:Session=Depends(get_db)):
        ok,latency_ms=check_database(db,request)
        if not ok:
            return JSONResponse(
                status_code=503,
                content={"status":"not_ready","checks":{"database":{"status":"unavailable","latency_ms":latency_ms}}},
            )
        return {"status":"ready","checks":{"database":{"status":"available","latency_ms":latency_ms}}}
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
        log_event(logger,"auth_login_failed",logging.WARNING)
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )
    access_token=create_access_token({"sub":str(user.id)})
    log_event(logger,"auth_login_successful",user_id=user.id)
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
            detail=f"Job not found"
        )
    return job

@app.patch("/jobs/{job_id}",response_model=schemas.JobApplicationResponse)
def job_update(job_id:int,job_update:schemas.JobApplicationUpdate,db:Session=Depends(get_db),current_user=Depends(get_current_user)):
    return crud.update_job_application(db,job_id,job_update,user_id=current_user.id)

@app.delete("/jobs/{job_id}",status_code=204)
def job_delete(job_id:int,db:Session=Depends(get_db),current_user=Depends(get_current_user)):
    crud.delete_job_application(db,job_id=job_id,user_id=current_user.id)
    return Response(status_code=204)