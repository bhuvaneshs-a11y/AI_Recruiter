from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True)
    zoho_id = Column(String, unique=True, nullable=False)
    full_name = Column(String)
    email = Column(String)
    phone = Column(String)
    resume_file_path = Column(String)
    zoho_modified_time = Column(String)
    created_at = Column(DateTime, server_default=func.current_timestamp())
    updated_at = Column(DateTime, server_default=func.current_timestamp())

    applications = relationship("Application", back_populates="candidate")
    analyses = relationship("ResumeAnalysis", back_populates="candidate")


class JobOpening(Base):
    __tablename__ = "job_openings"

    id = Column(Integer, primary_key=True)
    zoho_id = Column(String, unique=True, nullable=False)
    title = Column(String)
    description = Column(Text)
    required_skills = Column(Text)  # JSON array
    experience_level = Column(String)
    created_at = Column(DateTime, server_default=func.current_timestamp())

    applications = relationship("Application", back_populates="job_opening")


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("candidate_id", "job_opening_id"),)

    id = Column(Integer, primary_key=True)
    zoho_id = Column(String, unique=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    job_opening_id = Column(Integer, ForeignKey("job_openings.id"), nullable=False)
    applied_at = Column(String)

    candidate = relationship("Candidate", back_populates="applications")
    job_opening = relationship("JobOpening", back_populates="applications")
    analyses = relationship("ResumeAnalysis", back_populates="application")


class ResumeAnalysis(Base):
    __tablename__ = "resume_analyses"

    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    analyzed_at = Column(DateTime, server_default=func.current_timestamp())
    backend = Column(String)  # "claude" | "rule_based"
    status = Column(String)  # "completed" | "failed"

    # job-fit side
    overall_fit_score = Column(Integer)
    confidence = Column(String)  # "high" | "medium" | "low"
    summary = Column(Text)
    skills_matched = Column(Text)  # JSON array
    skills_missing = Column(Text)  # JSON array
    experience_assessment = Column(Text)
    career_trajectory_notes = Column(Text)
    suggested_interview_questions = Column(Text)  # JSON array

    # verification side
    credibility_score = Column(Integer)
    red_flags = Column(Text)  # JSON array

    raw_llm_response = Column(Text)
    error_message = Column(Text)

    candidate = relationship("Candidate", back_populates="analyses")
    application = relationship("Application", back_populates="analyses")
    project_verifications = relationship("ProjectVerification", back_populates="resume_analysis")


class ProjectVerification(Base):
    __tablename__ = "project_verifications"

    id = Column(Integer, primary_key=True)
    resume_analysis_id = Column(Integer, ForeignKey("resume_analyses.id"), nullable=False)
    project_name = Column(String)
    claim = Column(Text)
    links = Column(Text)  # JSON array
    verdict = Column(String)  # "verified" | "partially_verified" | "unverified" | "suspicious"
    evidence = Column(Text)

    resume_analysis = relationship("ResumeAnalysis", back_populates="project_verifications")
