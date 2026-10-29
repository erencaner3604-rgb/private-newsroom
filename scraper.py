#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Eren & Caner Private News Room — 7 Stratejik İstihbarat Radarı
Gemini 3.8 Flash (Birincil) + Groq GPT-OSS-120B (Yedek)
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
GROQ_MODEL = "openai/gpt-oss-120b"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# 7 STRATEJİK KATEGORİ VE KAPSAMLI SEO RADARI
FEEDS_CONFIG = [
    # 1. KÜRESEL MANŞETLER & EN ÇOK KONUŞULANLAR
    {
        "cat": "breaking_world",
        "source": "Global Breaking & Geopolitics",
        "q": '("breaking news" OR "developing story" OR "world politics" OR "geopolitical crisis" OR "summit" OR "diplomatic") -sports -celebrity',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "breaking_world",
        "source": "Türkiye & Bölgesel Sıcak Gündem",
        "q": '("son dakika" OR "flaş gelişme" OR "jeopolitik" OR "kritik zirve" OR "diplomasi" OR "dış politika") -magazin -dizi',
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },

    # 2. MAKRO EKONOMİ, FİNANS & PİYASALAR
    {
        "cat": "economy_finance",
        "source": "Global Macro & Central Banks",
        "q": '("Federal Reserve" OR "interest rate decision" OR "bond yields" OR "eurobond" OR "inflation dynamics" OR "sovereign debt" OR "carry trade")',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "economy_finance",
        "source": "TCMB, Para Politikası & BIST",
        "q": '("TCMB" OR "faiz kararı" OR "enflasyon raporu" OR "eurobond ihracı" OR "Borsa İstanbul" OR "kur korumalı" OR "swap piyasası" OR "Hazine ihaleleri")',
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },

    # 3. LÜKS MAISONS & HAUTE HORLOGERIE
    {
        "cat": "luxury_horology",
        "source": "Luxury Conglomerates & Maisons",
        "q": '("LVMH" OR "Kering" OR "Richemont" OR "Hermès" OR "Chanel" OR "luxury retail index" OR "luxury market slow down" OR "M&A luxury")',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "luxury_horology",
        "source": "Haute Horlogerie & Timepieces",
        "q": '("Rolex" OR "Patek Philippe" OR "Audemars Piguet" OR "Vacheron Constantin" OR "A. Lange & Söhne" OR "haute horlogerie" OR "watch auction" OR "WatchCharts")',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "luxury_horology",
        "source": "Lüks Perakende & Koleksiyon TR",
        "q": '("lüks sektörü" OR "saat koleksiyonu" OR "mücevherat piyasası" OR "lüks tüketim" OR "Sotheby\'s saat" OR "Christie\'s")',
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },

    # 4. GAYRİMENKUL PİYASASI & ARAZİ YATIRIMLARI
    {
        "cat": "real_estate_market",
        "source": "Global Real Estate & REITs",
        "q": '("commercial real estate" OR "prime residential" OR "housing price index" OR "REIT" OR "land development" OR "real estate fund")',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "real_estate_market",
        "source": "Türkiye Konut, Arsa & GYO",
        "q": '("konut fiyat endeksi" OR "arsa yatırımı" OR "GYO" OR "gayrimenkul değerleme" OR "imar planı" OR "ticari mülk getirisi" OR "arazi geliştirme")',
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },

    # 5. YAPAY ZEKA & GİRİŞİM SERMAYESİ (VC)
    {
        "cat": "ai_vc_tech",
        "source": "AI Breakthroughs & Autonomous Tech",
        "q": '("artificial intelligence" OR "large language models" OR "autonomous agents" OR "OpenAI" OR "Anthropic" OR "semiconductor chips" OR "Nvidia AI")',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "ai_vc_tech",
        "source": "Venture Capital & Dealmaking",
        "q": '("venture capital" OR "seed round" OR "Series A funding" OR "startup valuation" OR "tech M&A" OR "unicorn exit")',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "ai_vc_tech",
        "source": "Girişim Ekosistemi & Teknoloji TR",
        "q": '("yapay zeka girişimi" OR "girişim sermayesi" OR "yatırım turu" OR "erken aşama fon" OR "teknopark" OR "scaleup")',
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },

    # 6. DIŞ TİCARET & KÜRESEL LOJİSTİK
    {
        "cat": "trade_logistics",
        "source": "Global Trade Routes & Shipping",
        "q": '("container freight rates" OR "Drewry index" OR "Red Sea shipping" OR "Suez Canal" OR "global supply chain" OR "maritime logistics" OR "trade tariffs")',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "trade_logistics",
        "source": "İhracat, Gümrük & Liman Lojistiği",
        "q": '("dış ticaret dengesi" OR "ihracat rakamları" OR "navlun fiyatları" OR "liman işletmeciliği" OR "gümrük tarifesi" OR "lojistik koridoru" OR "Orta Koridor")',
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },

    # 7. STRATEJİK EGE RADARI: İZMİR & BODRUM
    {
        "cat": "aegean_radar",
        "source": "İzmir Ticaret, Liman & Sanayi",
        "q": '("İzmir Limanı" OR "Alsancak Limanı" OR "Çandarlı Limanı" OR "Kemalpaşa Lojistik" OR "İzmir serbest bölge" OR "EBSO" OR "İZTO" OR "İzmir sanayi")',
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },
    {
        "cat": "aegean_radar",
        "source": "Bodrum & Ege Kıyı Yatırımları",
        "q": '("Bodrum Marina" OR "Yalıkavak Marina" OR "Bodrum lüks resort" OR "Bodrum turizm yatırımı" OR "Bodrum gayrimenkul" OR "Muğla kıyı planlama" OR "Ege marinaları")',
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },
]

SYSTEM_PROMPT = """You are the Senior Executive Intelligence Editor for Eren and Caner's Private News Room.
Produce elite analytical briefings strictly in valid JSON format.

RULES:
1. Output strictly in TR and EN.
2. Structure: 3-4 key takeaways and a 2-paragraph strategic analysis.
3. Tone: Institutional, insightful, strategic, no fluff.
4. Response MUST be valid JSON matching this schema:
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
            # Her sorgudan en taze 5 haberi çek
            return (parsed.entries or [])[:5]
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
    # 1. Öncelik: Gemini 3.8 Flash
    if gemini_model:
        try:
            res = gemini_model.generate_content(prompt_text)
            return json.loads(res.text)
        except Exception as e:
            logger.warning(f"Gemini yanıt veremedi / kota: {e}. Groq devreye giriyor...")

    # 2. Yedek: Groq (openai/gpt-oss-120b)
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
            logger.error(f"Groq hatası: {ex}")

    return {}

def main() -> None:
    logger.info(">>> E&C 7 Stratejik İstihbarat Radarı Başlatılıyor...")
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
        logger.info(f"[{feed['source']}] Taranan: {len(entries)} başlık")

        for entry in entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "")
            raw_summary = entry.get("summary", "")

            if not title or len(title) < 8:
                continue

            doc_id = compute_article_id(title, link)
            # Deduplication: Önceden eklenen haber atlanır
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
            time.sleep(0.4)

    logger.info(f">>> ÇEVRİM TAMAMLANDI. Eklenen Yeni Rapor Sayısı: {total_saved}")

if __name__ == "__main__":
    main()
