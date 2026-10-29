#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Eren & Caner Private News Room — Fast Executive Scraper
"""

import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import quote_plus

import feedparser
import firebase_admin
import google.generativeai as genai
import requests
from firebase_admin import credentials, firestore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("ECNewsRoomBot")

GEMINI_MODEL_NAME = "gemini-3.8-flash"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# Her kategori için en kritik ve hızlı odaklı sorgular (Hızlı yürütme için optimize edildi)
TARGET_QUERIES = [
    {"cat": "economy", "source": "Bloomberg & Makro", "q": "economy OR fed OR markets when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"cat": "economy", "source": "Ekonomim & Finans", "q": "ekonomi OR borsa OR faiz when:1d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    {"cat": "luxury", "source": "Lüks Moda & Maisons", "q": "LVMH OR Kering OR Hermes luxury when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"cat": "luxury", "source": "Saatçilik & Horology", "q": "luxury watches Patek Rolex when:3d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"cat": "tech", "source": "AI & Girişim", "q": "Artificial Intelligence startup funding when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"cat": "realestate", "source": "Kentsel Tasarım", "q": "architecture urban planning when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"cat": "local", "source": "İzmir Stratejik Radar", "q": "İzmir imar OR İzmir proje OR İzmir kentsel when:3d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    {"cat": "local", "source": "Bodrum Turizm & Yatırım", "q": "Bodrum marina OR Bodrum yatırım OR Bodrum turizm when:3d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    {"cat": "culture", "source": "Kültür & Spor", "q": "sanat bienal OR spor şampiyonlar when:2d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
]

SYSTEM_INSTRUCTION = """
You are the Chief Intelligence Editor for Eren and Caner's Private Executive News Terminal.
Transform news into noise-free executive briefings.

Local news filter: Strictly discard petty crime or minor road accidents. Only keep real estate, luxury, investments, marina, urban planning.

Return strictly valid JSON:
{
  "discard": false,
  "importance_score": 90,
  "translations": {
    "TR": { "headline": "...", "takeaways": ["...", "...", "..."], "summary": "..." },
    "EN": { "headline": "...", "takeaways": ["...", "...", "..."], "summary": "..." },
    "FR": { "headline": "...", "takeaways": ["...", "...", "..."], "summary": "..." },
    "RU": { "headline": "...", "takeaways": ["...", "...", "..."], "summary": "..." }
  }
}
"""

def init_firestore() -> firestore.Client:
    raw_creds = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
    if not raw_creds:
        raise RuntimeError("Missing FIREBASE_SERVICE_ACCOUNT")
    cred_dict = json.loads(raw_creds)
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

def init_gemini() -> genai.GenerativeModel:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(
        model_name=GEMINI_MODEL_NAME,
        system_instruction=SYSTEM_INSTRUCTION,
        generation_config={"temperature": 0.2, "response_mime_type": "application/json"},
    )

def fetch_top_entry(query_str: str, hl: str, gl: str, ceid: str) -> List[Dict[str, Any]]:
    url = f"https://news.google.com/rss/search?q={quote_plus(query_str)}&hl={hl}&gl={gl}&ceid={ceid}"
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=8)
        if resp.status_code == 200:
            parsed = feedparser.parse(resp.content)
            return parsed.entries[:1] # Her kanaldan en sıcak 1 ana haberi alır
    except Exception as e:
        logger.warning(f"Fetch hatası: {e}")
    return []

def compute_article_id(title: str, link: str) -> str:
    normalized = (title.strip().lower()[:80] + "|" + link.split("?")[0].strip().lower())
    return "art_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]

def main() -> None:
    logger.info(">>> EC Hizli Bot Baslatildi...")
    db = init_firestore()
    model = init_gemini()
    col = db.collection("articles")

    total_added = 0

    for item in TARGET_QUERIES:
        entries = fetch_top_entry(item["q"], item["hl"], item["gl"], item["ceid"])
        if not entries:
            continue

        entry = entries[0]
        title = entry.get("title", "").strip()
        link = entry.get("link", "")
        summary = entry.get("summary", "")

        if not title:
            continue

        doc_id = compute_article_id(title, link)
        if col.document(doc_id).get().exists:
            logger.info(f"Atlandi (Zaten var): {title[:35]}")
            continue

        prompt = f"CATEGORY: {item['cat']}\nSOURCE: {item['source']}\nTITLE: {title}\nTEXT: {summary}"
        try:
            res = model.generate_content(prompt)
            data = json.loads(res.text)

            if data.get("discard") is True:
                continue

            score = int(data.get("importance_score", 88))
            doc = {
                "category": item["cat"],
                "source": item["source"],
                "original_title": title,
                "published_at": datetime.now(timezone.utc).isoformat(),
                "importance_score": score,
                "is_vip": score >= 85,
                "translations": data.get("translations", {})
            }
            col.document(doc_id).set(doc)
            total_added += 1
            logger.info(f"+++ FIRESTORE YAZILDI: {title[:40]}")
            time.sleep(2) # Kotayı zorlamadan hızlı geçiş
        except Exception as ex:
            logger.error(f"Hata: {ex}")

    logger.info(f">>> BOT BITTI. Eklenen yeni brifing: {total_added}")

if __name__ == "__main__":
    main()
