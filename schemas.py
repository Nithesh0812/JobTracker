from typing import Optional
from pydantic import BaseModel,ConfigDict
from enum import Enum
from datetime import datetime
class UserCreate(BaseModel):
    full_name:str
    email:str
    password:str

class UserResponse(BaseModel):
    id:int
    full_name:str
    email:str
    model_config=ConfigDict(from_attributes=True)
    
class UserLogin(BaseModel):
    email:str
    password:str

class UserLoginResponse(BaseModel):
    message:str
    user_id:int

class JobStatus(str,Enum):
    applied="Applied"
    interviewed="Interview"
    offered="Offer Extended"
    rejected="Rejected"

class JobApplicationCreate(BaseModel):
    company:str
    role:str
    status:JobStatus = JobStatus.applied
    job_link:Optional[str]=None
    notes: Optional[str]=None

class JobApplicationResponse(BaseModel):
    id:int
    company:str
    role:str
    status:str
    job_link: Optional[str]=None
    notes: Optional[str]=None
    user_id:int
    created_at:datetime
    updated_at:datetime
    model_config=ConfigDict(from_attributes=True)
    
class JobApplicationUpdate(BaseModel):
    company: Optional[str] = None
    role: Optional[str] = None
    status: JobStatus |None= None
    job_link: Optional[str] = None
    notes: Optional[str] = None


class TokenResponse(BaseModel):
    access_token:str
    token_type:str