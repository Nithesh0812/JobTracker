from sqlalchemy import Column,Integer,String,ForeignKey,DateTime
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime,UTC
class User(Base):
    __tablename__="users"
    id=Column(Integer,primary_key=True)
    full_name=Column(String,nullable=False)
    email=Column(String,nullable=False,unique=True)
    hashed_password= Column(String, nullable = False)
    job_applications=relationship("JobApplication",back_populates="user",cascade="all, delete-orphan")

class JobApplication(Base):
    __tablename__="job_application"
    id = Column(Integer, primary_key=True)
    company = Column(String, nullable=False)
    role = Column(String, nullable=False)
    status = Column(String, nullable=False, default="applied")
    job_link = Column(String, nullable=True)
    notes = Column(String, nullable=True)

    user_id=Column(Integer,ForeignKey("users.id"),nullable=False)

    user=relationship("User",back_populates="job_applications")

    created_at=Column(DateTime(timezone=True),default=lambda:datetime.now(UTC),nullable=False)
    
    updated_at=Column(DateTime(timezone=True),default=lambda:datetime.now(UTC),onupdate=lambda:datetime.now(UTC),nullable=False)