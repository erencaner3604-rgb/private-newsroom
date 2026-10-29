#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Eren & Caner Private News Room — Autonomous Executive Scraper & AI Curator
"""

import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import feedparser
import firebase_admin
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
from firebase_admin import credentials, firestore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("ECNewsRoomBot")

GEMINI_MODEL_NAME = "gemini-3.8-flash"
RETENTION_DAYS = 14

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# Doğrudan çalışan garantili Google News RSS motoru
CATEGORY_TOPICS: Dict[str, List[Dict[str, str]]] = {
    "economy": [
        {"name": "Bloomberg & Reuters Makro", "query": "economy OR inflation OR fed OR markets when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Ekonomim & Dünya", "query": "ekonomi OR borsa OR merkez bankası when:1d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    ],
    "luxury": [
        {"name": "Lüks Moda & Maisons", "query": "LVMH OR Kering OR Hermès OR luxury fashion when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Haute Horlogerie & Saat", "query": "Patek Philippe OR Rolex OR Audemars Piguet OR luxury watches when:3d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    ],
    "tech": [
        {"name": "Yapay Zeka & Startups", "query": "Artificial Intelligence OR OpenAI OR startup funding when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Türkiye Girişimcilik", "query": "girişim OR yatırım turu OR teknoloji when:2d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    ],
    "realestate": [
        {"name": "Kentsel Tasarım & Mimarlık", "query": "architecture design OR urban development when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Türkiye Gayrimenkul", "query": "konut OR gayrimenkul OR kentsel dönüşüm when:2d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    ],
    "local": [
        {"name": "İzmir Gelişim & İmar & Yatırım", "query": "İzmir imar OR İzmir proje OR İzmir kentsel dönüşüm when:3d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
        {"name": "Bodrum Turizm & Yatırım", "query": "Bodrum marina OR Bodrum turizm yatırım OR Bodrum imar when:3d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    ],
    "culture": [
        {"name": "Kültür & Sanat", "query": "sanat sergi OR bienal OR art market when:3d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
        {"name": "Global Sports Arena", "query": "Champions League OR Formula 1 OR EuroLeague when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    ]
}

SYSTEM_INSTRUCTION = """
You are the Chief Intelligence Editor for Eren and Caner's Private Executive News Terminal.
Summarize raw news into executive, noise-free, elite briefings.

CRITICAL LOCAL FILTER (category == "local"):
- Discard small car accidents, petty crime, bickering. Only keep urban planning, marina, hospitality investments, real estate, tourism.

Output strictly valid JSON:
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
        raise RuntimeError("Missing FIREBASE_SERVICE_ACCOUNT environment variable.")
    cred_dict = json.loads(raw_creds)
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

def init_gemini() -> genai.GenerativeModel:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY environment variable.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(
        model_name=GEMINI_MODEL_NAME,
        system_instruction=SYSTEM_INSTRUCTION,
        generation_config={"temperature": 0.2, "response_mime_type": "application/json"},
    )

def fetch_feed(query_str: str, hl: str, gl: str, ceid: str) -> List[Dict[str, Any]]:
    url = f"https://news.google.com/rss/search?q={quote_plus(query_str)}&hl={hl}&gl={gl}&ceid={ceid}"
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=12)
        if resp.status_code == 200:
            parsed = feedparser.parse(resp.content)
            return parsed.entries[:2]
    except Exception as e:
        logger.warning(f"Feed error: {e}")
    return []

def compute_article_id(title: str, link: str) -> str:
    normalized = (title.strip().lower()[:80] + "|" + link.split("?")[0].strip().lower())
    return "art_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]

def main() -> None:
    logger.info(">>> EC Newsroom Bot Calisiyor...")
    db = init_firestore()
    model = init_gemini()
    col = db.collection("articles")

    total_added = 0

    for cat_id, sources in CATEGORY_TOPICS.items():
        logger.info(f"--- Kategori taranıyor: {cat_id} ---")
        for src in sources:
            entries = fetch_feed(src["query"], src["hl"], src["gl"], src["ceid"])
            logger.info(f"[{src['name']}] Bulunan haber sayisi: {len(entries)}")

            for entry in entries:
                title = entry.get("title", "").strip()
                link = entry.get("link", "")
                summary = entry.get("summary", "")

                if not title or len(title) < 10:
                    continue

                doc_id = compute_article_id(title, link)
                if col.document(doc_id).get().exists:
                    logger.info(f"Zaten kayitli: {title[:40]}")
                    continue

                prompt = f"CATEGORY: {cat_id}\nSOURCE: {src['name']}\nTITLE: {title}\nTEXT: {summary}"
                try:
                    res = model.generate_content(prompt)
                    time.sleep(4.5)
                    data = json.loads(res.text)

                    if data.get("discard") is True:
                        continue

                    score = int(data.get("importance_score", 85))
                    doc = {
                        "category": cat_id,
                        "source": src["name"],
                        "original_title": title,
                        "published_at": datetime.now(timezone.utc).isoformat(),
                        "importance_score": score,
                        "is_vip": score >= 88,
                        "translations": data.get("translations", {})
                    }
                    col.document(doc_id).set(doc)
                    total_added += 1
                    logger.info(f"+++ FIRESTORE'A EKLENDI: {title[:45]} (Etki: {score})")
                except Exception as ex:
                    logger.error(f"Hata olustu: {ex}")
                    time.sleep(3)

    logger.info(f">>> ISLEM TAMAMLANDI. Toplam Eklenen Haber: {total_added}")

if __name__ == "__main__":
    main()
