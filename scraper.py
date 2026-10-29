#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Eren & Caner Private News Room — Deep Executive Intelligence Curator
Model: gemini-3.8-flash | Timeout: 60 Dk Uyumlu | Diller: TR & EN Derin Analiz
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
from bs4 import BeautifulSoup
from firebase_admin import credentials, firestore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("ECNewsRoomBot")

GEMINI_MODEL_NAME = "gemini-3.8-flash"
GEMINI_SLEEP_SECONDS = 3.0

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# --- HABER MASALARI: İSTEDİĞİN ZAMAN EKLE / ÇIKAR ---
FEEDS_CONFIG = [
    # 1. Küresel ve Yerel Finans
    {"cat": "economy", "source": "Bloomberg & Makro", "q": "global economy OR inflation OR markets when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"cat": "economy", "source": "Ekonomim & Finans", "q": "ekonomi OR borsa OR merkez bankası when:1d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},

    # 2. Lüks Maisons & Saatçilik
    {"cat": "luxury", "source": "Lüks Maisons & Moda", "q": "LVMH OR Kering OR Hermès luxury retail when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"cat": "luxury", "source": "Haute Horlogerie Radar", "q": "Patek Philippe OR Rolex OR Audemars Piguet when:3d", "hl": "en-US", "gl": "US", "ceid": "US:en"},

    # 3. Girişimcilik & Yapay Zeka
    {"cat": "tech", "source": "VC & Artificial Intelligence", "q": "Artificial Intelligence venture capital OR startup when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"cat": "tech", "source": "Türkiye Girişim Ekosistemi", "q": "girişim OR yapay zeka yatırım when:2d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},

    # 4. Kentsel Tasarım & Gayrimenkul
    {"cat": "realestate", "source": "ArchDaily & Mimarlık", "q": "urban planning OR architecture design when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"cat": "realestate", "source": "Türkiye Gayrimenkul", "q": "kentsel dönüşüm OR gayrimenkul konut imar when:2d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},

    # 5. İzmir & Bodrum (Stratejik Yerel Radar)
    {"cat": "local", "source": "İzmir Stratejik Radar", "q": "İzmir imar OR İzmir kentsel dönüşüm OR İzmir belediye proje when:3d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    {"cat": "local", "source": "Bodrum Turizm & Yatırım", "q": "Bodrum marina OR Bodrum turizm yatırım OR Bodrum imar when:3d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},

    # 6. Kültür & Spor
    {"cat": "culture", "source": "Kültür Sanat Radarı", "q": "sanat piyasası OR bienal OR sergi when:3d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    {"cat": "culture", "source": "Global Sports Arena", "q": "Champions League OR Formula 1 OR EuroLeague when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
]

SYSTEM_INSTRUCTION = """
You are the Senior Executive Intelligence Editor for Eren and Caner's Private News Room.
Your objective is to produce elite, institutional-grade, highly comprehensive analytical briefings.

CRITICAL RULES:
1. STRICT LOCAL FILTER (category == "local"):
   - DISCARD: petty street crime, car crashes, small municipal bickering.
   - RETAIN ONLY: zoning/master plans (imar), urban regeneration (kentsel dönüşüm), infrastructure, luxury marinas, hospitality investments.
2. TONE & DEPTH:
   - Provide 4 detailed, data-driven key takeaways highlighting strategic implications, metrics, and industry shifts.
   - Provide a 2-paragraph thorough strategic analysis (macro context, corporate strategy, long-term impact).
   - Generate outputs EXCLUSIVELY in TR (Turkish) and EN (English).

RETURN STRICTLY VALID JSON:
{
  "discard": false,
  "importance_score": 92,
  "translations": {
    "TR": {
      "headline": "...",
      "takeaways": [
        "...",
        "...",
        "...",
        "..."
      ],
      "summary": "Paragraf 1 (Stratejik bağlam ve makro dinamikler)...\\n\\nParagraf 2 (Sektörel etki, sermaye akışı ve orta-uzun vadeli çıkarımlar)..."
    },
    "EN": {
      "headline": "...",
      "takeaways": [
        "...",
        "...",
        "...",
        "..."
      ],
      "summary": "Paragraph 1 (Strategic context and macro drivers)...\\n\\nParagraph 2 (Industry impact, capital flows, and long-term implications)..."
    }
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

def fetch_feed_entries(query_str: str, hl: str, gl: str, ceid: str) -> List[Dict[str, Any]]:
    url = f"https://news.google.com/rss/search?q={quote_plus(query_str)}&hl={hl}&gl={gl}&ceid={ceid}"
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=8)
        if resp.status_code == 200:
            parsed = feedparser.parse(resp.content)
            return (parsed.entries or [])[:1]
    except Exception as e:
        logger.warning(f"Feed hatasi: {e}")
    return []

def extract_quick_body(url: str, rss_summary: str) -> str:
    soup = BeautifulSoup(rss_summary or "", "html.parser")
    clean_summary = soup.get_text(" ", strip=True)

    if not url or "news.google.com" in url:
        return clean_summary

    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=3.5)
        if resp.status_code == 200:
            doc = BeautifulSoup(resp.text, "html.parser")
            for tag in doc(["script", "style", "nav", "footer", "aside", "form"]):
                tag.decompose()
            main_elem = doc.find("article") or doc.find("main") or doc.body
            if main_elem:
                paras = [p.get_text(" ", strip=True) for p in main_elem.find_all("p") if len(p.get_text(" ", strip=True)) > 50]
                if paras:
                    return f"{clean_summary}\n\n" + "\n\n".join(paras[:6])
    except Exception:
        pass
    return clean_summary

def compute_article_id(title: str, link: str) -> str:
    normalized = (title.strip().lower()[:80] + "|" + link.split("?")[0].strip().lower())
    return "art_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]

def main() -> None:
    logger.info(">>> E&C Deep TR/EN Executive Curator Baslatiliyor...")
    db = init_firestore()
    model = init_gemini()
    col = db.collection("articles")

    total_saved = 0

    for feed in FEEDS_CONFIG:
        entries = fetch_feed_entries(feed["q"], feed["hl"], feed["gl"], feed["ceid"])
        logger.info(f"[{feed['source']}] Bulunan haber: {len(entries)}")

        for entry in entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "")
            raw_summary = entry.get("summary", "")

            if not title or len(title) < 12:
                continue

            doc_id = compute_article_id(title, link)
            if col.document(doc_id).get().exists:
                logger.info(f"Mevcut haber atlandi: {title[:35]}")
                continue

            content_text = extract_quick_body(link, raw_summary)
            prompt = (
                f"CATEGORY: {feed['cat']}\n"
                f"SOURCE: {feed['source']}\n"
                f"TITLE: {title}\n"
                f"FULL CONTEXT:\n{content_text}\n"
            )

            try:
                res = model.generate_content(prompt)
                time.sleep(GEMINI_SLEEP_SECONDS)
                data = json.loads(res.text)

                if data.get("discard") is True:
                    logger.info(f"Filtreye takildi (Discard): {title[:35]}")
                    continue

                score = int(data.get("importance_score", 90))
                doc = {
                    "category": feed["cat"],
                    "source": feed["source"],
                    "original_title": title,
                    "published_at": datetime.now(timezone.utc).isoformat(),
                    "importance_score": score,
                    "is_vip": score >= 88,
                    "translations": data.get("translations", {}),
                }
                col.document(doc_id).set(doc)
                total_saved += 1
                logger.info(f"+++ FIRESTORE'A EKLENDI [{score}/100]: {title[:45]}")
            except Exception as ex:
                logger.error(f"Hata olustu: {ex}")
                time.sleep(2)

    logger.info(f">>> ISLEM BASARIYLA BITTI. Toplam Eklenen: {total_saved}")

if __name__ == "__main__":
    main()
