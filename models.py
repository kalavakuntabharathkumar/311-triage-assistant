"""
Pydantic models and database schema for 311 triage.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
import sqlite3
import os
from datetime import datetime


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize SQLite database with required tables."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    
    # Service requests table (raw from NYC API)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS service_requests (
            unique_key TEXT PRIMARY KEY,
            created_date TEXT,
            closed_date TEXT,
            agency TEXT,
            agency_name TEXT,
            complaint_type TEXT,
            descriptor TEXT,
            location_type TEXT,
            incident_zip TEXT,
            incident_address TEXT,
            street_name TEXT,
            cross_street_1 TEXT,
            cross_street_2 TEXT,
            intersection_street_1 TEXT,
            intersection_street_2 TEXT,
            address_type TEXT,
            city TEXT,
            landmark TEXT,
            facility_type TEXT,
            status TEXT,
            due_date TEXT,
            resolution_description TEXT,
            resolution_action_updated_date TEXT,
            community_board TEXT,
            borough TEXT,
            x_coordinate_state_plane REAL,
            y_coordinate_state_plane REAL,
            park_facility_name TEXT,
            park_borough TEXT,
            vehicle_type TEXT,
            taxi_company_borough TEXT,
            taxi_pick_up_location TEXT,
            bridge_highway_name TEXT,
            bridge_highway_direction TEXT,
            road_ramp TEXT,
            bridge_highway_segment TEXT,
            latitude REAL,
            longitude REAL,
            location TEXT
        )
    """)
    
    # Triage results table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS triage_results (
            unique_key TEXT PRIMARY KEY,
            urgency_score INTEGER NOT NULL,
            department TEXT NOT NULL,
            summary TEXT,
            model_version TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (unique_key) REFERENCES service_requests(unique_key)
        )
    """)
    
    # Indexes for common queries
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sr_created ON service_requests(created_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sr_borough ON service_requests(borough)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sr_complaint ON service_requests(complaint_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tr_urgency ON triage_results(urgency_score)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tr_dept ON triage_results(department)")
    
    conn.commit()
    return conn


class ServiceRequest(BaseModel):
    """Mirrors the service_requests table columns."""
    unique_key: str
    created_date: Optional[str] = None
    closed_date: Optional[str] = None
    agency: Optional[str] = None
    agency_name: Optional[str] = None
    complaint_type: Optional[str] = None
    descriptor: Optional[str] = None
    location_type: Optional[str] = None
    incident_zip: Optional[str] = None
    incident_address: Optional[str] = None
    street_name: Optional[str] = None
    cross_street_1: Optional[str] = None
    cross_street_2: Optional[str] = None
    intersection_street_1: Optional[str] = None
    intersection_street_2: Optional[str] = None
    address_type: Optional[str] = None
    city: Optional[str] = None
    landmark: Optional[str] = None
    facility_type: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[str] = None
    resolution_description: Optional[str] = None
    resolution_action_updated_date: Optional[str] = None
    community_board: Optional[str] = None
    borough: Optional[str] = None
    x_coordinate_state_plane: Optional[float] = None
    y_coordinate_state_plane: Optional[float] = None
    park_facility_name: Optional[str] = None
    park_borough: Optional[str] = None
    vehicle_type: Optional[str] = None
    taxi_company_borough: Optional[str] = None
    taxi_pick_up_location: Optional[str] = None
    bridge_highway_name: Optional[str] = None
    bridge_highway_direction: Optional[str] = None
    road_ramp: Optional[str] = None
    bridge_highway_segment: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location: Optional[str] = None


class TriageResult(BaseModel):
    unique_key: str
    urgency_score: int = Field(ge=1, le=5)
    department: str
    summary: str = ""
    model_version: str = "gpt-3.5-turbo-0125"
    created_at: Optional[str] = None

    def model_dump(self) -> dict:
        return {
            "unique_key": self.unique_key,
            "urgency_score": self.urgency_score,
            "department": self.department,
            "summary": self.summary,
            "model_version": self.model_version,
            "created_at": self.created_at or datetime.utcnow().isoformat(),
        }
