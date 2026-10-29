import os
import json
import time
import hashlib
from datetime import datetime, timezone
import urllib.parse
import feedparser
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai
from groq import Groq

# ---------------------------------------------------------
# 1. ORTAM DEĞİŞKENLERİ & SERVİSLER
# ---------------------------------------------------------
FIREBASE_SA = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GROQ_KEY = os.environ.get("GROQ_API_KEY", "").strip()

if not FIREBASE_SA:
    raise ValueError("HATA: FIREBASE_SERVICE_ACCOUNT secret tanımlanmamış.")

cred_dict = json.loads(FIREBASE_SA)
cred = credentials.Certificate(cred_dict)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None

# ---------------------------------------------------------
# 2. GARANTİ ÇALIŞAN RSS VE KATEGORİ HARİTASI
# ---------------------------------------------------------
FEEDS_CONFIG = [
    # 1. KÜRESEL MANŞETLER (Global Reuters / BBC)
    {
        "cat": "breaking_world",
        "source": "Reuters & Global Breaking",
        "q": "geopolitics OR diplomacy OR White House OR NATO OR United Nations",
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },

    # 2. EKONOMİ & FİNANS
    {
        "cat": "economy_finance",
        "source": "Global Macro & Fed",
        "q": "Federal Reserve OR interest rates OR ECB OR inflation OR Wall Street",
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "economy_finance",
        "source": "TCMB & Borsa İstanbul",
        "q": "TCMB OR faiz kararı OR Borsa İstanbul OR enflasyon",
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },

    # 3. LÜKS & SAATÇİLİK
    {
        "cat": "luxury_horology",
        "source": "LVMH & Luxury Maisons",
        "q": "LVMH OR Kering OR Richemont OR Hermes OR Brunello Cucinelli",
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "luxury_horology",
        "source": "Haute Horlogerie & Watchmaking",
        "q": "Rolex OR Patek Philippe OR Audemars Piguet OR Vacheron Constantin OR Watches and Wonders",
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },

    # 4. GAYRİMENKUL
    {
        "cat": "real_estate_market",
        "source": "Real Estate & REITs",
        "q": "commercial real estate OR housing market OR REIT OR gayrimenkul konut",
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },

    # 5. YAPAY ZEKA & VC
    {
        "cat": "ai_vc_tech",
        "source": "AI Breakthroughs & Tech",
        "q": "artificial intelligence OR OpenAI OR Anthropic OR Nvidia AI OR venture capital",
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },

    # 6. DIŞ TİCARET & LOJİSTİK
    {
        "cat": "trade_logistics",
        "source": "Global Logistics & Shipping",
        "q": "container shipping OR freight rates OR supply chain OR ihracat dış ticaret",
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },

    # 7. İZMİR & BODRUM RADARI
    {
        "cat": "aegean_radar",
        "source": "İzmir Ticaret & Liman",
        "q": "İzmir Alsancak Limanı OR EBSO OR İZTO OR İzmir ekonomi",
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },
    {
        "cat": "aegean_radar",
        "source": "Bodrum Turizm & Marina",
        "q": "Bodrum Yalıkavak Marina OR Bodrum turizm yatırımı OR Bodrum gayrimenkul",
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },
]

# ---------------------------------------------------------
# 3. AI ANALİZİ
# ---------------------------------------------------------
SYSTEM_PROMPT = """
You are the Chief Intelligence Analyst for the "Private News Room" (Executive Intelligence Platform).
Evaluate, curate, and translate this news item into institutional intelligence.

Return ONLY a raw JSON object with this exact schema:
{
  "importance_score": <integer between 75 and 98>,
  "translations": {
    "TR": {
      "headline": "<Executive Turkish headline>",
      "takeaways": [
        "<Key 1 Turkish takeaway>",
        "<Key 2 Turkish takeaway>",
        "<Key 3 Turkish takeaway>"
      ],
      "summary": "<In-depth Turkish institutional summary>"
    },
    "EN": {
      "headline": "<Executive English headline>",
      "takeaways": [
        "<Key 1 English takeaway>",
        "<Key 2 English takeaway>",
        "<Key 3 English takeaway>"
      ],
      "summary": "<In-depth English institutional summary>"
    }
  }
}
"""

def analyze_with_ai(title, summary_raw):
    content = f"Title: {title}\nSummary: {summary_raw}"

    if GEMINI_KEY:
        try:
            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(
                f"{SYSTEM_PROMPT}\n\nAnalyze this:\n{content}",
                generation_config={"response_mime_type": "application/json"}
            )
            return json.loads(response.text.strip())
        except Exception as e:
            print(f"Gemini hatası: {e}")

    if groq_client:
        try:
            chat = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content}
                ],
                response_format={"type": "json_object"}
            )
            return json.loads(chat.choices[0].message.content.strip())
        except Exception as e:
            print(f"Groq hatası: {e}")

    return None

# ---------------------------------------------------------
# 4. VERİTABANI MOTORU
# ---------------------------------------------------------
def run_scraper():
    print(">>> PRIVATE NEWS ROOM: HABER MOTORU BAŞLATILDI...")
    articles_col = db.collection("articles")
    added_count = 0

    for feed_info in FEEDS_CONFIG:
        cat = feed_info["cat"]
        source_name = feed_info["source"]
        
        encoded_q = urllib.parse.quote(feed_info["q"])
        url = f"https://news.google.com/rss/search?q={encoded_q}&hl={feed_info['hl']}&gl={feed_info['gl']}&ceid={feed_info['ceid']}"

        parsed = feedparser.parse(url)
        entries = parsed.entries or []
        print(f"\n--- [{cat}] {source_name}: {len(entries)} haber bulundu ---")

        for entry in entries[:3]:  # Her alt başlıktan en yeni 3 haberi al
            raw_title = entry.title
            link = entry.link
            
            doc_id = hashlib.md5((raw_title + cat).encode("utf-8")).hexdigest()

            # Zaten varsa atla (mükerrer kayıt engelleme)
            if articles_col.document(doc_id).get().exists:
                continue

            clean_summary = BeautifulSoup(getattr(entry, 'summary', ''), "html.parser").get_text()

            ai_data = analyze_with_ai(raw_title, clean_summary)
            if not ai_data:
                continue

            score = ai_data.get("importance_score", 85)
            translations = ai_data.get("translations", {})

            doc_payload = {
                "category": cat,
                "source": source_name,
                "original_title": raw_title,
                "link": link,
                "importance_score": int(score),
                "translations": translations,
                "published_at": datetime.now(timezone.utc).isoformat()
            }

            articles_col.document(doc_id).set(doc_payload)
            added_count += 1
            print(f"  [+] Eklendi ({score/10:.1f}): {raw_title[:60]}...")
            time.sleep(1)

    print(f"\n==========================================")
    print(f">>> BİTTİ! Eklenen Yeni Haber: {added_count}")
    print(f"==========================================")

if __name__ == "__main__":
    run_scraper()
