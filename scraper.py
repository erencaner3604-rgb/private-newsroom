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

GEMINI_MODEL_NAME = "gemini-1.5-flash"
GEMINI_SLEEP_SECONDS = 4.3
MAX_ARTICLES_PER_SOURCE = 2
RETENTION_DAYS = 14

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

SOURCES_CONFIG: Dict[str, List[Dict[str, str]]] = {
    "economy": [
        {"name": "CNBC", "rss": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664", "fallback_query": "site:cnbc.com economy OR markets when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Yahoo Finance", "rss": "https://finance.yahoo.com/news/rssindex", "fallback_query": "site:finance.yahoo.com markets when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Investing.com", "rss": "https://www.investing.com/rss/news.rss", "fallback_query": "site:investing.com economy when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Reuters", "rss": "https://news.google.com/rss/search?q=site:reuters.com+business+when:1d&hl=en-US&gl=US&ceid=US:en", "fallback_query": "site:reuters.com business when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Ekonomim", "rss": "https://www.ekonomim.com/rss", "fallback_query": "site:ekonomim.com ekonomi when:1d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
        {"name": "Dünya Gazetesi", "rss": "https://www.dunya.com/rss", "fallback_query": "site:dunya.com ekonomi when:1d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
        {"name": "Foreks", "rss": "https://news.google.com/rss/search?q=Foreks+Haber+ekonomi+when:1d&hl=tr&gl=TR&ceid=TR:tr", "fallback_query": "Foreks Haber ekonomi when:1d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    ],
    "luxury": [
        {"name": "Luxe Digital", "rss": "https://luxe.digital/feed/", "fallback_query": "site:luxe.digital luxury business", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "CPP-Luxury", "rss": "https://cpp-luxury.com/feed/", "fallback_query": "site:cpp-luxury.com when:7d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "FashionNetwork", "rss": "https://ww.fashionnetwork.com/rss/feed/en,1.xml", "fallback_query": "site:fashionnetwork.com luxury when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Jing Daily", "rss": "https://jingdaily.com/feed", "fallback_query": "site:jingdaily.com luxury when:3d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Hodinkee", "rss": "https://www.hodinkee.com/articles/rss.xml", "fallback_query": "site:hodinkee.com watches when:3d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Monochrome Watches", "rss": "https://monochrome-watches.com/feed/", "fallback_query": "site:monochrome-watches.com when:3d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Fratello Watches", "rss": "https://www.fratellowatches.com/feed/", "fallback_query": "site:fratellowatches.com when:3d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    ],
    "tech": [
        {"name": "TechCrunch", "rss": "https://techcrunch.com/feed/", "fallback_query": "site:techcrunch.com AI OR startups when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "VentureBeat", "rss": "https://venturebeat.com/feed/", "fallback_query": "site:venturebeat.com AI when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Hacker News", "rss": "https://hnrss.org/frontpage?points=150", "fallback_query": "site:news.ycombinator.com", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Webrazzi", "rss": "https://webrazzi.com/feed/", "fallback_query": "site:webrazzi.com yatirim OR yapay zeka when:2d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
        {"name": "Swipeline", "rss": "https://www.swipeline.co/feed/", "fallback_query": "site:swipeline.co girisim when:3d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
        {"name": "Egirişim", "rss": "https://egirisim.com/feed/", "fallback_query": "site:egirisim.com girisim when:3d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    ],
    "realestate": [
        {"name": "ArchDaily", "rss": "https://www.archdaily.com/feed", "fallback_query": "site:archdaily.com architecture when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Dezeen", "rss": "https://www.dezeen.com/feed/", "fallback_query": "site:dezeen.com architecture when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Planetizen", "rss": "https://www.planetizen.com/rss.xml", "fallback_query": "site:planetizen.com urban planning when:3d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Arkitera", "rss": "https://www.arkitera.com/feed/", "fallback_query": "site:arkitera.com mimarlik when:3d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
        {"name": "Emlak Kulisi", "rss": "https://emlakkulisi.com/rss", "fallback_query": "site:emlakkulisi.com gayrimenkul when:2d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    ],
    "local": [
        {"name": "İz Gazete", "rss": "https://www.izgazete.net/rss", "fallback_query": "site:izgazete.net İzmir imar OR belediye OR ekonomi when:2d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
        {"name": "Ege'de Sonsöz", "rss": "https://www.egedesonsoz.com/rss", "fallback_query": "site:egedesonsoz.com İzmir imar OR yatırım OR meclis when:2d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
        {"name": "Gerçek İzmir", "rss": "https://www.gercekizmir.com/rss", "fallback_query": "site:gercekizmir.com İzmir proje OR imar OR ekonomi when:2d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
        {"name": "Kent TV (Bodrum)", "rss": "https://www.kenttv.net/rss", "fallback_query": "site:kenttv.net Bodrum marina OR imar OR turizm when:2d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
        {"name": "Bodrum Gündem", "rss": "https://www.bodrumgundem.com/feed", "fallback_query": "site:bodrumgundem.com Bodrum turizm OR imar OR marina when:2d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    ],
    "culture": [
        {"name": "Sokrates Dergi", "rss": "https://sokratesdergi.com/feed/", "fallback_query": "site:sokratesdergi.com", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
        {"name": "Artsy", "rss": "https://www.artsy.net/rss/news", "fallback_query": "site:artsy.net art market when:3d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"name": "Aposto", "rss": "https://news.google.com/rss/search?q=site:aposto.com+when:3d&hl=tr&gl=TR&ceid=TR:tr", "fallback_query": "site:aposto.com when:3d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
        {"name": "BBC Sport", "rss": "https://feeds.bbci.co.uk/sport/rss.xml", "fallback_query": "site:bbc.com/sport when:1d", "hl": "en-GB", "gl": "GB", "ceid": "GB:en"},
        {"name": "NTV Spor", "rss": "https://www.ntvspor.net/rss", "fallback_query": "site:ntvspor.net when:1d", "hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    ],
}

SYSTEM_INSTRUCTION = """
You are the Chief Intelligence Editor for Eren and Caner's Private Executive News Terminal.
Process raw news into noise-free, institutional-grade executive briefings.

CRITICAL RULES:
1. Discard (discard: true) promotional ads, gossip, coupon spam.
2. STRICT LOCAL FILTER (category == "local" - İzmir & Bodrum):
   - DISCARD: petty crime, traffic accidents, motorcycle crashes, power outages, local bickering.
   - ONLY KEEP: urban planning/zoning (imar), marina/superyacht projects, tourism investments, commercial real estate, local economy, high-profile cultural events.
3. OUTPUT FORMAT:
   - Objective, executive headline (no clickbait).
   - 3-4 data-dense key takeaways.
   - 2-paragraph comprehensive summary.
   - Strategic importance_score (1 to 100).
   - Full translations in TR, EN, FR, RU.

RETURN STRICTLY VALID JSON:
{
  "discard": false,
  "discard_reason": "",
  "importance_score": 88,
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

def build_google_news_rss_url(query_str: str, hl: str = "tr", gl: str = "TR", ceid: str = "TR:tr") -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(query_str)}&hl={hl}&gl={gl}&ceid={ceid}"

def fetch_feed_entries(source_cfg: Dict[str, str]) -> List[Dict[str, Any]]:
    rss_url = source_cfg["rss"]
    entries = []
    try:
        resp = requests.get(rss_url, headers=REQUEST_HEADERS, timeout=12)
        if resp.status_code == 200:
            parsed = feedparser.parse(resp.content)
            entries = parsed.entries or []
    except Exception:
        pass

    if not entries and source_cfg.get("fallback_query"):
        fallback_url = build_google_news_rss_url(
            source_cfg["fallback_query"],
            hl=source_cfg.get("hl", "tr"),
            gl=source_cfg.get("gl", "TR"),
            ceid=source_cfg.get("ceid", "TR:tr"),
        )
        try:
            resp = requests.get(fallback_url, headers=REQUEST_HEADERS, timeout=12)
            if resp.status_code == 200:
                parsed = feedparser.parse(resp.content)
                entries = parsed.entries or []
        except Exception:
            pass

    return entries[:MAX_ARTICLES_PER_SOURCE]

def clean_html_text(raw_html: str) -> str:
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "aside", "noscript", "iframe", "form"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(separator=" ", strip=True)).strip()

def extract_article_body(url: str, rss_summary: str) -> str:
    base_summary = clean_html_text(rss_summary)
    if not url or "news.google.com" in url:
        return base_summary
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=10)
        if resp.status_code != 200:
            return base_summary
        soup = BeautifulSoup(resp.text, "html.parser")
        for junk in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            junk.decompose()
        container = soup.find("article") or soup.find("main") or soup.body or soup
        paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p") if len(p.get_text(" ", strip=True)) > 45]
        return f"{base_summary}\n\n{'\n'.join(paragraphs[:15])}"[:7000].strip()
    except Exception:
        return base_summary[:4000]

def compute_article_id(title: str, link: str) -> str:
    normalized = (title.strip().lower()[:100] + "|" + link.split("?")[0].strip().lower())
    return "art_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]

def curate_article_with_gemini(model: genai.GenerativeModel, category: str, source_name: str, raw_title: str, raw_body: str) -> Optional[Dict[str, Any]]:
    prompt = f"CATEGORY: {category}\nSOURCE: {source_name}\nTITLE: {raw_title}\nCONTENT:\n{raw_body}\n"
    for attempt in range(1, 4):
        try:
            response = model.generate_content(prompt)
            time.sleep(GEMINI_SLEEP_SECONDS)
            if response and response.text:
                return json.loads(response.text)
        except Exception as exc:
            if "429" in str(exc) or "quota" in str(exc).lower():
                time.sleep(15 * attempt)
            else:
                time.sleep(GEMINI_SLEEP_SECONDS)
                return None
    return None

def recalculate_top_10_vip(db: firestore.Client) -> None:
    recent_docs = list(db.collection("articles").order_by("published_at", direction=firestore.Query.DESCENDING).limit(80).stream())
    if not recent_docs:
        return
    scored = sorted(recent_docs, key=lambda d: d.to_dict().get("importance_score", 0), reverse=True)
    top_10_ids = {d.id for d in scored[:10]}
    batch = db.batch()
    for d in recent_docs:
        batch.update(d.reference, {"is_vip": d.id in top_10_ids})
    batch.commit()

def prune_old_articles(db: firestore.Client) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    old_docs = list(db.collection("articles").where("published_at", "<", cutoff).limit(100).stream())
    if old_docs:
        batch = db.batch()
        for doc in old_docs:
            batch.delete(doc.reference)
        batch.commit()

def main() -> None:
    logger.info("=== Starting Autonomous News Scraper ===")
    db = init_firestore()
    model = init_gemini()
    articles_col = db.collection("articles")

    for category_id, sources in SOURCES_CONFIG.items():
        for src in sources:
            source_name = src["name"]
            entries = fetch_feed_entries(src)
            for entry in entries:
                raw_title = clean_html_text(entry.get("title", ""))
                link = entry.get("link", "")
                if not raw_title or len(raw_title) < 12:
                    continue
                doc_id = compute_article_id(raw_title, link)
                if articles_col.document(doc_id).get().exists:
                    continue

                raw_body = extract_article_body(link, entry.get("summary", ""))
                ai_result = curate_article_with_gemini(model, category_id, source_name, raw_title, raw_body)
                if not ai_result or ai_result.get("discard") is True:
                    continue

                score = max(1, min(100, int(ai_result.get("importance_score", 80))))
                doc_data = {
                    "category": category_id,
                    "source": source_name,
                    "original_title": raw_title,
                    "published_at": datetime.now(timezone.utc).isoformat(),
                    "importance_score": score,
                    "is_vip": score >= 90,
                    "translations": ai_result.get("translations", {}),
                }
                articles_col.document(doc_id).set(doc_data)
                logger.info(f"Saved: {raw_title[:50]}")

    recalculate_top_10_vip(db)
    prune_old_articles(db)
    logger.info("=== Finished ===")

if __name__ == "__main__":
    main()
