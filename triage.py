"""
LLM-based triage for 311 service requests.

Classifies each request with:
- urgency_score (1-5)
- department (routing)
- summary (plain-language one-liner)

Supports both synchronous OpenAI Chat Completions and asynchronous Batch API.
"""
import os
import json
import logging
import time
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import openai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from models import TriageResult, init_db
from utils import get_env

logger = logging.getLogger(__name__)

# OpenAI configuration
MODEL = "gpt-3.5-turbo-0125"
MAX_TOKENS = 150
TEMPERATURE = 0.1

# System prompt for consistent classification
SYSTEM_PROMPT = """You are a municipal 311 triage assistant. Classify the service request with:
1. urgency_score: integer 1-5 (5 = life safety/immediate hazard)
2. department: one of [DOT, DSNY, DEP, NYPD, FDNY, HPD, DOB, DPR, DOE, OTHER]
3. summary: one sentence plain-language summary for a dashboard.

Return ONLY valid JSON with keys: urgency_score, department, summary.
"""


def build_user_prompt(request: Dict[str, Any]) -> str:
    """Construct a concise prompt from the request fields."""
    fields = [
        f"Type: {request.get('complaint_type', 'N/A')}",
        f"Descriptor: {request.get('descriptor', 'N/A')}",
        f"Borough: {request.get('borough', 'N/A')}",
        f"Location: {request.get('incident_address') or request.get('intersection_street_1', 'N/A')}",
        f"Status: {request.get('status', 'N/A')}",
        f"Agency: {request.get('agency_name', 'N/A')}",
    ]
    return "\n".join(fields)


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=20),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError)),
    reraise=True
)
def classify_single(request: Dict[str, Any], client: openai.OpenAI) -> Optional[TriageResult]:
    """Classify a single request via Chat Completions API."""
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(request)},
            ],
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        # Validate & coerce
        urgency = max(1, min(5, int(data.get("urgency_score", 3))))
        dept = data.get("department", "OTHER").upper()
        summary = data.get("summary", "").strip()
        return TriageResult(
            unique_key=request["unique_key"],
            urgency_score=urgency,
            department=dept,
            summary=summary,
            model_version=MODEL,
        )
    except Exception as e:
        logger.warning(f"Failed to classify {request.get('unique_key')}: {e}")
        return None


def run_triage_sync(batch_size: int = 100, db_path: Optional[str] = None, max_workers: int = 5) -> int:
    """Run triage synchronously with thread pool."""
    db_path = db_path or get_env("DB_PATH", "data/311.db")
    conn = init_db(db_path)
    api_key = get_env("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = openai.OpenAI(api_key=api_key)

    # Fetch untriaged records
    cur = conn.execute("""
        SELECT * FROM service_requests
        WHERE unique_key NOT IN (SELECT unique_key FROM triage_results)
        ORDER BY created_date DESC
        LIMIT ?
    """, (batch_size,))
    columns = [d[0] for d in cur.description]
    records = [dict(zip(columns, row)) for row in cur.fetchall()]
    
    if not records:
        logger.info("No untriaged records found.")
        return 0

    logger.info(f"Classifying {len(records)} records with {max_workers} workers")
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(classify_single, rec, client): rec for rec in records}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                results.append(res)
    
    # Bulk insert triage results
    if results:
        placeholders = ", ".join(["?"] * len(TriageResult.model_fields))
        cols = ", ".join(TriageResult.model_fields.keys())
        sql = f"INSERT OR REPLACE INTO triage_results ({cols}) VALUES ({placeholders})"
        data = [tuple(r.model_dump().values()) for r in results]
        conn.executemany(sql, data)
        conn.commit()
        logger.info(f"Inserted {len(results)} triage results")
    
    conn.close()
    return len(results)


def run_triage_batch(batch_size: int = 1000, db_path: Optional[str] = None) -> int:
    """Run triage using OpenAI Batch API (async, cheaper)."""
    db_path = db_path or get_env("DB_PATH", "data/311.db")
    conn = init_db(db_path)
    api_key = get_env("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = openai.OpenAI(api_key=api_key)

    # Fetch untriaged records
    cur = conn.execute("""
        SELECT * FROM service_requests
        WHERE unique_key NOT IN (SELECT unique_key FROM triage_results)
        ORDER BY created_date DESC
        LIMIT ?
    """, (batch_size,))
    columns = [d[0] for d in cur.description]
    records = [dict(zip(columns, row)) for row in cur.fetchall()]
    
    if not records:
        logger.info("No untriaged records for batch.")
        return 0

    # Prepare JSONL input file
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        for rec in records:
            request = {
                "custom_id": rec["unique_key"],
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": build_user_prompt(rec)},
                    ],
                    "max_tokens": MAX_TOKENS,
                    "temperature": TEMPERATURE,
                    "response_format": {"type": "json_object"},
                },
            }
            f.write(json.dumps(request) + "\n")
        input_file_path = f.name
    
    try:
        # Upload file
        with open(input_file_path, "rb") as f:
            batch_input_file = client.files.create(file=f, purpose="batch")
        
        # Create batch
        batch = client.batches.create(
            input_file_id=batch_input_file.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
        )
        logger.info(f"Created batch {batch.id}, status: {batch.status}")
        
        # Poll for completion (in production, you'd use a separate process/webhook)
        while batch.status in ("validating", "in_progress", "finalizing"):
            time.sleep(30)
            batch = client.batches.retrieve(batch.id)
            logger.info(f"Batch {batch.id} status: {batch.status}")
        
        if batch.status != "completed":
            logger.error(f"Batch failed: {batch.status}")
            return 0
        
        # Download results
        output_file = client.files.content(batch.output_file_id)
        results = []
        for line in output_file.text.strip().split("\n"):
            resp = json.loads(line)
            custom_id = resp["custom_id"]
            if resp["response"]["status_code"] == 200:
                content = resp["response"]["body"]["choices"][0]["message"]["content"]
                data = json.loads(content)
                urgency = max(1, min(5, int(data.get("urgency_score", 3))))
                dept = data.get("department", "OTHER").upper()
                summary = data.get("summary", "").strip()
                results.append(TriageResult(
                    unique_key=custom_id,
                    urgency_score=urgency,
                    department=dept,
                    summary=summary,
                    model_version=MODEL,
                ))
            else:
                logger.warning(f"Batch item {custom_id} failed: {resp['response']}")
        
        # Bulk insert
        if results:
            placeholders = ", ".join(["?"] * len(TriageResult.model_fields))
            cols = ", ".join(TriageResult.model_fields.keys())
            sql = f"INSERT OR REPLACE INTO triage_results ({cols}) VALUES ({placeholders})"
            data = [tuple(r.model_dump().values()) for r in results]
            conn.executemany(sql, data)
            conn.commit()
            logger.info(f"Inserted {len(results)} batch triage results")
        
        return len(results)
    finally:
        os.unlink(input_file_path)
        conn.close()


def run_triage(batch_size: int = 100, use_batch_api: bool = False, db_path: Optional[str] = None) -> int:
    """Main triage entry point."""
    if use_batch_api:
        return run_triage_batch(batch_size, db_path)
    else:
        return run_triage_sync(batch_size, db_path)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--use-batch-api", action="store_true")
    args = parser.parse_args()
    run_triage(args.batch_size, args.use_batch_api)
