"""SQLAlchemy ORM models for projects, meshes, materials, BCs and jobs."""
import datetime as dt
import uuid

from sqlalchemy import Column, String, Float, Integer, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from .database import Base


def gen_id() -> str:
    return uuid.uuid4().hex[:12]


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=dt.datetime.utcnow)
    updated_at = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    # Mesh data stored as JSON blobs (nodes: [[x,y,z],...], elements: [[n1..n4],...])
    nodes = Column(JSON, default=list)
    elements = Column(JSON, default=list)
    surface_faces = Column(JSON, default=list)  # boundary triangles for picking/rendering

    material = Column(JSON, default=dict)  # {name, E, nu, density, conductivity, specific_heat}

    boundary_conditions = Column(JSON, default=list)  # list of BC dicts
    loads = Column(JSON, default=list)  # list of load dicts

    analysis_type = Column(String, default="static")  # "static" | "modal" | "thermal"
    n_modes = Column(Integer, default=6)  # number of modes for modal analysis
    gravity = Column(JSON, default=lambda: {"enabled": False, "x": 0.0, "y": 0.0, "z": -9.81})

    jobs = relationship("Job", back_populates="project", cascade="all, delete-orphan")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=gen_id)
    project_id = Column(String, ForeignKey("projects.id"))
    status = Column(String, default="pending")  # pending, running, completed, failed
    solver_used = Column(String, default="")  # "calculix" or "internal"
    log = Column(Text, default="")
    progress = Column(Float, default=0.0)
    created_at = Column(DateTime, default=dt.datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

    # Results stored as JSON: displacements [[ux,uy,uz],...], von_mises [...], per node
    results = Column(JSON, default=dict)

    project = relationship("Project", back_populates="jobs")
