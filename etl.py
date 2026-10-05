"""
Incremental ETL for NYC 311 Service Requests.

Fetches data from the Socrata API (https://data.cityofnewyork.us/resource/erm2-nwe9.json)
using SoQL queries for pagination and date filtering. Performs idempotent upserts into SQLite
based on the `unique_key` field.
"""
import os
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from models import ServiceRequest, init_db
from utils import get_env

logger = logging.getLogger(__name__)

# NYC 311 Socrata endpoint
API_URL = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"
# Fields we care about (reduce payload)
SELECT_FIELDS = [
    "unique_key", "created_date", "closed_date", "agency", "agency_name",
    "complaint_type", "descriptor", "location_type", "incident_zip",
    "incident_address", "street_name", "cross_street_1", "cross_street_2",
    "intersection_street_1", "intersection_street_2", "address_type",
    "city", "landmark", "facility_type", "status", "due_date",
    "resolution_description", "resolution_action_updated_date",
    "community_board", "borough", "x_coordinate_state_plane",
    "y_coordinate_state_plane", "park_facility_name", "park_borough",
    "vehicle_type", "taxi_company_borough", "taxi_pick_up_location",
    "bridge_highway_name", "bridge_highway_direction", "road_ramp",
    "bridge_highway_segment", "latitude", "longitude", "location"
]


def build_where_clause(days_back: int) -> str:
    """Build SoQL WHERE clause for records created in the last N days."""
    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S")
    return f"created_date >= '{since}'"


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type((requests.RequestException, requests.Timeout)),
    reraise=True
)
def fetch_page(offset: int, limit: int, where: str) -> List[Dict[str, Any]]:
    """Fetch a single page of results from the Socrata API."""
    params = {
        "$select": ",".join(SELECT_FIELDS),
        "$where": where,
        "$limit": limit,
        "$offset": offset,
        "$order": "created_date ASC",
    }
    resp = requests.get(API_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def upsert_requests(conn: sqlite3.Connection, records: List[Dict[str, Any]]) -> int:
    """Upsert records into the service_requests table. Returns number of rows affected."""
    if not records:
        return 0
    cols = ServiceRequest.model_fields.keys()
    placeholders = ", ".join(["?"] * len(cols))
    col_list = ", ".join(cols)
    # SQLite upsert: INSERT OR REPLACE (requires PRIMARY KEY on unique_key)
    sql = f"""
        INSERT OR REPLACE INTO service_requests ({col_list})
        VALUES ({placeholders})
    """
    data = []
    for rec in records:
        # Convert Socrata types to Python types matching our model
        row = []
        for col in cols:
            val = rec.get(col)
            if val == "":
                val = None
            row.append(val)
        data.append(tuple(row))
    cur = conn.executemany(sql, data)
    conn.commit()
    return cur.rowcount


def run_etl(days_back: int = 1, limit: int = 50000, db_path: Optional[str] = None) -> int:
    """Main ETL entry point. Returns total records upserted."""
    db_path = db_path or get_env("DB_PATH", "data/311.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = init_db(db_path)
    where = build_where_clause(days_back)
    logger.info(f"Fetching records since {where.split("'")[1]}")
    
    total_upserted = 0
    offset = 0
    page_size = 1000  # Socrata max page size
    
    while True:
        logger.debug(f"Fetching offset={offset}, limit={page_size}")
        try:
            page = fetch_page(offset, page_size, where)
        except requests.HTTPError as e:
            logger.error(f"API request failed: {e}")
            raise
        
        if not page:
            break
        
        upserted = upsert_requests(conn, page)
        total_upserted += upserted
        logger.info(f"Upserted {upserted} records (total: {total_upserted})")
        
        if len(page) < page_size:
            break
        offset += page_size
        
        # Safety cap
        if total_upserted >= limit:
            logger.warning(f"Reached limit of {limit} records, stopping.")
            break
    
    conn.close()
    logger.info(f"ETL complete. Total records upserted: {total_upserted}")
    return total_upserted


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--days-back", type=int, default=1)
    parser.add_argument("--limit", type=int, default=50000)
    args = parser.parse_args()
    run_etl(args.days_back, args.limit)
