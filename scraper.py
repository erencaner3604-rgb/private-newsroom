#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Eren & Caner Private News Room — Hibrit İstihbarat Motoru
Gemini 3.8 Flash (Birincil) + Groq Llama 3.1 8B Instant (Yedek)
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
from groq import Groq

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("ECHybridBot")

# MODEL TANIMLARI
GEMINI_MODEL_NAME = "gemini-3.8-flash"
GROQ_MODEL = "llama-3.1-8b-instant"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

FEEDS_CONFIG = [
    # 1. Piyasalar & Makro
    {"cat": "economy", "source": "Bloomberg & Markets", "q": "global economy OR inflation OR markets", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"cat": "economy", "source": "Ekonomim & Finans", "q": "ekonomi OR borsa OR merkez bankası", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},

    # 2. Lüks Maisons & Saatçilik
    {"cat": "luxury", "source": "Lüks Maisons & Moda", "q": "LVMH OR Kering OR luxury brand OR fashion", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"cat": "luxury", "source": "Haute Horlogerie Radar", "q": "luxury watches OR Rolex OR Patek", "hl": "en-US", "gl": "US", "ceid": "US:en"},

    # 3. Girişimcilik & Yapay Zeka
    {"cat": "tech", "source": "Venture Capital & AI", "q": "artificial intelligence startup OR venture capital", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"cat": "tech", "source": "Türkiye Girişim & AI", "q": "yapay zeka OR girişim OR teknoloji yatırımı", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},

    # 4. Kentsel Tasarım & Gayrimenkul
    {"cat": "realestate", "source": "Kentsel Tasarım & Mimarlık", "q": "urban planning OR architecture design", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"cat": "realestate", "source": "Gayrimenkul & İmar", "q": "kentsel dönüşüm OR gayrimenkul OR mimari", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},

    # 5. İzmir & Bodrum Radarı
    {"cat": "local", "source": "İzmir Stratejik Radar", "q": "İzmir büyükşehir OR İzmir ekonomi OR İzmir proje", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    {"cat": "local", "source": "Bodrum & Ege Yatırım", "q": "Bodrum turizm OR Bodrum yatırım OR Ege kıyı", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},

    # 6. Kültür & Spor
    {"cat": "culture", "source": "Kültür & Sanat", "q": "sergi OR bienal OR çağdaş sanat", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    {"cat": "culture", "source": "Global Sports Arena", "q": "Formula 1 OR EuroLeague OR Champions League", "hl": "en-US", "gl": "US", "ceid": "US:en"},
]

SYSTEM_PROMPT = """You are the Senior Executive Intelligence Editor for Eren and Caner's Private News Room.
Produce elite analytical briefings strictly in valid JSON format.

RULES:
1. Output strictly in TR and EN.
2. Structure: 3-4 key takeaways and a 2-paragraph strategic analysis.
3. Response MUST be valid JSON matching this schema:
{
  "importance_score": 90,
  "translations": {
    "TR": {
      "headline": "Stratejik Başlık",
      "takeaways": ["Çıkarım 1", "Çıkarım 2", "Çıkarım 3"],
      "summary": "Paragraf 1...\\n\\nParagraf 2..."
    },
    "EN": {
      "headline": "Strategic Headline",
      "takeaways": ["Takeaway 1", "Takeaway 2", "Takeaway 3"],
      "summary": "Paragraph 1...\\n\\nParagraph 2..."
    }
  }
}"""

def init_firestore() -> firestore.Client:
    raw_creds = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
    cred_dict = json.loads(raw_creds)
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

def fetch_feed_entries(query_str: str, hl: str, gl: str, ceid: str) -> List[Dict[str, Any]]:
    url = f"https://news.google.com/rss/search?q={quote_plus(query_str)}&hl={hl}&gl={gl}&ceid={ceid}"
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=8)
        if resp.status_code == 200:
            parsed = feedparser.parse(resp.content)
            return (parsed.entries or [])[:4]
    except Exception as e:
        logger.warning(f"Feed okuma hatası: {e}")
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
            for tag in doc(["script", "style", "nav", "footer", "aside"]):
                tag.decompose()
            main_elem = doc.find("article") or doc.find("main") or doc.body
            if main_elem:
                paras = [p.get_text(" ", strip=True) for p in main_elem.find_all("p") if len(p.get_text(" ", strip=True)) > 40]
                if paras:
                    return f"{clean_summary}\n\n" + "\n\n".join(paras[:4])
    except Exception:
        pass
    return clean_summary

def compute_article_id(title: str, link: str) -> str:
    normalized = (title.strip().lower()[:80] + "|" + link.split("?")[0].strip().lower())
    return "art_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]

def analyze_article(gemini_model, groq_client: Groq, prompt_text: str) -> Dict[str, Any]:
    # 1. Önce Gemini 3.8 Flash
    if gemini_model:
        try:
            res = gemini_model.generate_content(prompt_text)
            return json.loads(res.text)
        except Exception as e:
            logger.warning(f"Gemini yanıt veremedi / kota bitti: {e}. Groq Llama 3.1 devreye giriyor...")

    # 2. Gemini hata verirse / kota biterse Groq Llama 3.1 8B Instant devreye girer
    if groq_client:
        try:
            chat = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt_text}
                ],
                model=GROQ_MODEL,
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            return json.loads(chat.choices[0].message.content)
        except Exception as ex:
            logger.error(f"Groq da hata verdi: {ex}")

    return {}

def main() -> None:
    logger.info(">>> E&C Hibrit (Gemini 3.8 Flash + Groq Llama 3.1) Botu Başlatılıyor...")
    db = init_firestore()
    col = db.collection("articles")

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()

    gemini_model = None
    if gemini_key:
        try:
            genai.configure(api_key=gemini_key)
            gemini_model = genai.GenerativeModel(
                model_name=GEMINI_MODEL_NAME,
                system_instruction=SYSTEM_PROMPT,
                generation_config={"temperature": 0.2, "response_mime_type": "application/json"}
            )
        except Exception as e:
            logger.warning(f"Gemini başlatılamadı: {e}")

    groq_client = Groq(api_key=groq_key) if groq_key else None

    total_saved = 0

    for feed in FEEDS_CONFIG:
        entries = fetch_feed_entries(feed["q"], feed["hl"], feed["gl"], feed["ceid"])
        logger.info(f"[{feed['source']}] Bulunan: {len(entries)} haber")

        for entry in entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "")
            raw_summary = entry.get("summary", "")

            if not title or len(title) < 8:
                continue

            doc_id = compute_article_id(title, link)
            if col.document(doc_id).get().exists:
                continue

            content_text = extract_quick_body(link, raw_summary)
            prompt = (
                f"CATEGORY: {feed['cat']}\n"
                f"SOURCE: {feed['source']}\n"
                f"TITLE: {title}\n"
                f"CONTEXT:\n{content_text}\n"
            )

            data = analyze_article(gemini_model, groq_client, prompt)
            if not data or not data.get("translations"):
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
            logger.info(f"+++ EKLENDI [{feed['cat']}]: {title[:40]}")
            time.sleep(0.5)

    logger.info(f">>> İŞLEM TAMAMLANDI. Eklenen Yeni Rapor Sayısı: {total_saved}")

if __name__ == "__main__":
    main()
