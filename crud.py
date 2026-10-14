from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
import models
import schemas
from security import hash_password
def create_user(db:Session,user:schemas.UserCreate):
    db_user=models.User(
            full_name=user.full_name,
            email=user.email,
            hashed_password=hash_password(user.password)
    )
    try:
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Email already exists"
        )
def delete_user(db:Session,user_id:int):
    user=db.query(models.User).filter(models.User.id==user_id).first()
    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )
    db.delete(user)
    db.commit()
    return {"message":"User deleted successfully"}
def get_users(db:Session):
    return db.query(models.User).all()

def get_user_by_id(db:Session,user_id:int):
    user=db.query(models.User).filter(models.User.id==user_id).first()
    
    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User does not exist"
        )

    return user

def get_user_by_email(db:Session,email:str):
    return(db.query(models.User).filter(models.User.email==email).first())

def create_job_applications(db:Session,job:schemas.JobApplicationCreate,user_id:int):
    
    get_user_by_id(db,user_id)

    db_job=models.JobApplication(
        company=job.company,
        role=job.role,
        status=job.status,
        job_link=job.job_link,
        notes=job.notes,
        user_id=user_id
    )
    db.add(db_job)
    db.commit()
    db.refresh(db_job)
    return db_job

def update_job_application(db:Session,job_id:int,job_update:schemas.JobApplicationUpdate,user_id:int):
    db_job=get_job_by_id_for_user(db,job_id,user_id)

    if db_job is None:
        raise HTTPException(
            status_code=404,
            detail="Job does not exist"
        )
    update=job_update.model_dump(exclude_unset=True)

    for key,value in update.items():
        setattr(db_job,key,value)
    db.commit()
    db.refresh(db_job)
    return db_job

def delete_job_application(db:Session,job_id:int,user_id:int):
    db_job=db.query(models.JobApplication).filter(models.JobApplication.id==job_id,models.JobApplication.user_id==user_id).first()

    if db_job is None:
        raise HTTPException(
            status_code=404,
            detail="Job does not exist"
        )
    db.delete(db_job)
    db.commit()
    return {"message":"Job deleted successfully"}

def get_job_application(db:Session):
    return db.query(models.JobApplication).all()


def get_job_by_id_for_user(db:Session,job_id:int,user_id:int):
    job=db.query(models.JobApplication).filter(models.JobApplication.id == job_id, models.JobApplication.user_id == user_id).first()
    return job

def get_jobs_by_user(db:Session,user_id:int,status:schemas.JobStatus |None = None,company:str |None = None,role:str |None = None,skip:int=0,limit:int=0,sort_by:str="id",order:str="asc"):

    get_user_by_id(db,user_id)
    
    query= db.query(models.JobApplication).filter(models.JobApplication.user_id==user_id)

    if status:
       query=query.filter(models.JobApplication.status==status.value)
    if company:
        query=query.filter(models.JobApplication.company.ilike(f"%{company}%"))
    if role:
        query=query.filter(models.JobApplication.role.ilike(f"%{role}%"))

    allowed_sort_fields={
        "id": models.JobApplication.id,
        "company": models.JobApplication.company,
        "role": models.JobApplication.role,
        "status": models.JobApplication.status
    }
    sort_column=allowed_sort_fields.get(sort_by)

    if sort_column is None:
        raise HTTPException(
            status_code=400,
            detail="Sort column is required"
        )
    if order.lower() == "desc":
        query=query.order_by(sort_column.desc())

    elif order.lower()=="asc":
        query=query.order_by(sort_column.asc())
    
    else:
        raise HTTPException(
            status_code=400,
            detail="Order must be asc or desc"
        )

    return query.offset(skip).limit(limit).all()
