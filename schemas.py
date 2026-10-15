from typing import Optional
from pydantic import BaseModel,ConfigDict,EmailStr,Field
from enum import Enum
from datetime import datetime
class UserCreate(BaseModel):
    full_name:str
    email:EmailStr
    password:str = Field(min_length=8,max_length=128)

class UserResponse(BaseModel):
    id:int
    full_name:str
    email:str
    model_config=ConfigDict(from_attributes=True)
    
class UserLogin(BaseModel):
    email:EmailStr
    password:str

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