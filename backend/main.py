# main.py
import os
import time
import json
import shutil
import re
from typing import List

import numpy as np
import requests
from fastapi import FastAPI, File, UploadFile, HTTPException, Query, Form
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from utils.extractor import extract_text_from_pdf, split_text_into_chunks
from utils.predictor import classify_chunks

# -------------------------
# Load environment variables from .env (local dev)
# -------------------------
load_dotenv()

# =========================
# Azure embedding endpoint config
# (Your Azure endpoint returns {"embedding": [...]})
# =========================
AZURE_SCORING_URI = (os.getenv("AZURE_SCORING_URI") or "").strip()
AZURE_PRIMARY_KEY = (os.getenv("AZURE_PRIMARY_KEY") or "").strip()
# "bearer" -> Authorization: Bearer <key>
# "api-key" -> Authorization: <key> and api-key: <key>
AZURE_AUTH_STYLE = (os.getenv("AZURE_AUTH_STYLE", "bearer") or "bearer").strip().lower()


def _validate_azure_env():
    """Fail fast if env vars are placeholders or missing."""
    uri = AZURE_SCORING_URI.lower()
    if not uri or "<" in uri or "%3c" in uri:
        raise RuntimeError(
            "AZURE_SCORING_URI is not set to a real endpoint. "
            "Set the full https URL that ends with /score."
        )
    if not uri.startswith("https://") or not uri.endswith("/score"):
        raise RuntimeError("AZURE_SCORING_URI must be an https URL ending with /score.")
    if not AZURE_PRIMARY_KEY:
        raise RuntimeError("AZURE_PRIMARY_KEY is missing.")
    if AZURE_AUTH_STYLE not in ("bearer", "api-key"):
        raise RuntimeError("AZURE_AUTH_STYLE must be 'bearer' or 'api-key'.")


_validate_azure_env()


def _headers():
    """Build auth headers compatible with your Azure endpoint."""
    if AZURE_AUTH_STYLE == "api-key":
        return {
            "Content-Type": "application/json",
            "Authorization": AZURE_PRIMARY_KEY,
            "api-key": AZURE_PRIMARY_KEY,
        }
    # default bearer
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AZURE_PRIMARY_KEY}",
    }


def _robust_json(text: str):
    """Parse JSON that might be double-encoded."""
    try:
        data = json.loads(text)
    except Exception:
        return None
    if isinstance(data, str):
        try:
            return json.loads(data)
        except Exception:
            return None
    return data


def _embed(text: str, timeout: int = 60) -> np.ndarray:
    """
    Call Azure endpoint to get an embedding for the given text.
    Handles cases where the service double-encodes JSON (string body containing JSON).
    Accepts either {"embedding":[...]} or a raw list vector.
    """
    if not text:
        # Return a small zero vector to avoid crashes; similarity will be 0
        return np.zeros(1, dtype=np.float32)

    payload = {"text": text}
    r = requests.post(AZURE_SCORING_URI, headers=_headers(), json=payload, timeout=timeout)
    if not r.ok:
        raise RuntimeError(f"Azure {r.status_code}: {r.text}")

    # Try proper JSON first
    try:
        data = r.json()
    except Exception:
        data = _robust_json(r.text)

    # If Azure returned a JSON string (double-encoded), decode again
    if isinstance(data, str):
        data = _robust_json(data)

    if data is None:
        raise RuntimeError(f"Azure returned non-JSON: {r.text[:300]}")

    # Accept common shapes
    if isinstance(data, dict) and "embedding" in data:
        vec = data["embedding"]
    elif isinstance(data, list) and data and isinstance(data[0], (int, float)):
        vec = data
    else:
        raise RuntimeError(f"Azure response missing 'embedding': {str(data)[:300]}")

    return np.array(vec, dtype=np.float32)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity, safe for zero vectors."""
    a = a.astype(np.float32, copy=False)
    b = b.astype(np.float32, copy=False)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


# ---------- Matching text prep (score only relevant sections) ----------
SECTION_KEYS_FOR_MATCH = ["SUMMARY", "SKILLS", "EXPERIENCE", "PROJECTS"]

def _normalize_text(t: str) -> str:
    t = t.lower()
    t = re.sub(r'https?://\S+|www\.\S+', ' ', t)  # remove urls
    t = re.sub(r'\S+@\S+', ' ', t)                # remove emails
    t = re.sub(r'[^a-z0-9\s+.#/+-]', ' ', t)      # keep common tech chars
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def _text_for_matching(parsed: dict, raw_text: str) -> str:
    parts = []
    for k in SECTION_KEYS_FOR_MATCH:
        v = (parsed.get(k) or "").strip()
        if v:
            parts.append(v)
    if not parts:
        parts = [raw_text]  # fallback to raw if parser empty
    return _normalize_text("\n\n".join(parts))


def call_azure_match(resume_text_for_match: str, jd_text_for_match: str):
    """
    Two-pass embedding (resume + JD) -> cosine similarity -> scale to [0, 10].
    Returns a rounded score (2 decimals).
    """
    r_vec = _embed(resume_text_for_match)
    j_vec = _embed(jd_text_for_match)
    score = _cosine(r_vec, j_vec) * 10.0
    score = max(0.0, min(10.0, float(score)))
    return round(score, 2)


app = FastAPI()

# CORS (allow all for now; lock down in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _save_temp(upload: UploadFile, prefix: str) -> str:
    path = f"temp_{prefix}_{upload.filename}"
    with open(path, "wb") as buffer:
        shutil.copyfileobj(upload.file, buffer)
    return path


def _cleanup(paths: List[str]) -> None:
    for p in paths:
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


# --------------------------------------------
# Health/debug (safe)
# --------------------------------------------
@app.get("/_env_check")
def env_check():
    # Don’t leak secrets
    return {
        "uri_ok": AZURE_SCORING_URI.endswith("/score"),
        "auth_style": AZURE_AUTH_STYLE,
        "key_set": bool(AZURE_PRIMARY_KEY),
    }


# --------------------------------------------
# Parsing endpoint (supports both URLs)
# --------------------------------------------
@app.post("/upload-resume")
@app.post("/upload-resume/")
async def upload_resume(file: UploadFile = File(...)):
    pdf_path = _save_temp(file, "resume")
    try:
        text = extract_text_from_pdf(pdf_path)
        chunks = split_text_into_chunks(text)
        predictions = classify_chunks(chunks)
        return {"status": "success", "extracted_data": predictions}
    finally:
        _cleanup([pdf_path])


# --------------------------------------------
# Single JD + Resume matching (jd_text as plain text)
# --------------------------------------------
@app.post("/match-resume-jd")
@app.post("/match-resume-jd/")
async def match_resume_jd(
    resume: UploadFile = File(...),
    jd_text: str = Form(...),
):
    resume_path = _save_temp(resume, "single")
    try:
        resume_text_raw = extract_text_from_pdf(resume_path)
        parsed = classify_chunks(split_text_into_chunks(resume_text_raw))

        resume_text = _text_for_matching(parsed, resume_text_raw)
        jd_text_norm = _normalize_text(jd_text)

        score = call_azure_match(resume_text, jd_text_norm)

        return {
            "status": "success",
            "parsed_resume": parsed,
            "match_score": score,  # rounded to 2 decimals
        }
    except Exception as e:
        # Bubble up exact reason (no secrets)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _cleanup([resume_path])


# --------------------------------------------
# Bulk matching: multiple resumes + 1 JD (jd_text as plain text)
# Returns only results with score >= min_score
# --------------------------------------------
@app.post("/bulk-match")
@app.post("/bulk-match/")
async def bulk_match(
    jd_text: str = Form(...),
    resumes: List[UploadFile] = File(...),
    min_score: float = Query(7.0, ge=0.0),
):
    resume_paths = []
    try:
        jd_text_norm = _normalize_text(jd_text)
        # Precompute JD embedding once
        jd_vec = _embed(jd_text_norm)

        results = []
        for upload in resumes:
            path = _save_temp(upload, "bulk")
            resume_paths.append(path)

            raw = extract_text_from_pdf(path)
            parsed = classify_chunks(split_text_into_chunks(raw))
            r_text = _text_for_matching(parsed, raw)

            r_vec = _embed(r_text)

            score = _cosine(r_vec, jd_vec) * 10.0
            score = max(0.0, min(10.0, float(score)))
            score = round(score, 2)

            if score >= min_score:
                results.append({"filename": upload.filename, "score": score})

        results.sort(key=lambda x: x["score"], reverse=True)

        return {"status": "success", "matches": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _cleanup(resume_paths)
