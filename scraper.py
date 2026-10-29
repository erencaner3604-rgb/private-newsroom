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
# 2. TEMİZ VE GARANTİ ÇALIŞAN RSS SORGULARI
# ---------------------------------------------------------
FEEDS_CONFIG = [
    # 1. KÜRESEL MANŞETLER
    {
        "cat": "breaking_world",
        "source": "Reuters & Global Breaking",
        "q": "geopolitics OR diplomacy OR White House OR Kremlin OR NATO OR United Nations",
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "breaking_world",
        "source": "FT & World Affairs",
        "q": "world summit OR foreign policy OR international crisis",
        "hl": "en-GB", "gl": "GB", "ceid": "GB:en"
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
        "q": "TCMB OR faiz kararı OR Borsa İstanbul OR Hazine OR enflasyon",
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },

    # 3. LÜKS & SAATÇİLİK
    {
        "cat": "luxury_horology",
        "source": "LVMH & Luxury Maisons",
        "q": "LVMH OR Kering OR Richemont OR Hermes OR Brunello Cucinelli OR luxury goods",
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "luxury_horology",
        "source": "Haute Horlogerie & Watches",
        "q": "Rolex OR Patek Philippe OR Audemars Piguet OR Vacheron Constantin OR watch auction",
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "luxury_horology",
        "source": "Swiss Watch Industry",
        "q": "Swiss watch exports OR Watches and Wonders OR independent watchmaker",
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },

    # 4. GAYRİMENKUL
    {
        "cat": "real_estate_market",
        "source": "Global Real Estate & REITs",
        "q": "commercial real estate OR prime residential OR housing market OR REIT",
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "real_estate_market",
        "source": "Türkiye Konut & Arsa",
        "q": "konut fiyat endeksi OR konut satışları OR GYO OR arsa yatırımı",
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },

    # 5. YAPAY ZEKA & VC
    {
        "cat": "ai_vc_tech",
        "source": "AI Tech & Breakthroughs",
        "q": "artificial intelligence OR OpenAI OR Anthropic OR Nvidia AI OR AI models",
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "ai_vc_tech",
        "source": "Venture Capital Deals",
        "q": "venture capital OR Series A funding OR startup valuation OR VC investment",
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },

    # 6. DIŞ TİCARET & LOJİSTİK
    {
        "cat": "trade_logistics",
        "source": "Global Shipping & Freight",
        "q": "container shipping OR freight rates OR Red Sea shipping OR supply chain",
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "trade_logistics",
        "source": "İhracat & Lojistik TR",
        "q": "ihracat rakamları OR dış ticaret dengesi OR liman lojistiği OR navlun",
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },

    # 7. İZMİR & BODRUM
    {
        "cat": "aegean_radar",
        "source": "İzmir Liman & Sanayi",
        "q": "İzmir Alsancak Limanı OR Çandarlı Limanı OR İZTO OR EBSO",
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
# 3. PROMPT & ANALİZ
# ---------------------------------------------------------
SYSTEM_PROMPT = """
You are the Chief Intelligence Analyst for the "Private News Room" (Executive Intelligence Platform).
Evaluate, curate, and translate this news item into institutional intelligence.

Return ONLY a raw JSON object with this exact schema:
{
  "importance_score": <integer between 72 and 98>,
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

    # 1. Gemini
    if GEMINI_KEY:
        try:
            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(
                f"{SYSTEM_PROMPT}\n\nAnalyze this:\n{content}",
                generation_config={"response_mime_type": "application/json"}
            )
            return json.loads(response.text.strip())
        except Exception as e:
            print(f"Gemini hatası, Groq'a geçiliyor: {e}")

    # 2. Groq
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
# 4. SCRAPING VE VERİTABANI MOTORU
# ---------------------------------------------------------
def run_scraper():
    print(">>> PRIVATE NEWS ROOM: HABER MOTORU ÇALIŞTIRILIYOR...")
    
    # Eski kayıtları temizle
    print(">>> ESKİ HABERLER TEMİZLENİYOR...")
    old_docs = db.collection("articles").limit(100).stream()
    del_count = 0
    for d in old_docs:
        d.reference.delete()
        del_count += 1
    print(f">>> {del_count} ESKİ HABER SİLİNDİ.")

    articles_col = db.collection("articles")
    added_count = 0

    for feed_info in FEEDS_CONFIG:
        cat = feed_info["cat"]
        source_name = feed_info["source"]
        
        # Temiz ve hatasız URL kodlama
        encoded_q = urllib.parse.quote(feed_info["q"])
        url = f"https://news.google.com/rss/search?q={encoded_q}&hl={feed_info['hl']}&gl={feed_info['gl']}&ceid={feed_info['ceid']}"

        parsed = feedparser.parse(url)
        entries = parsed.entries or []
        print(f"\n--- [{cat}] {source_name}: {len(entries)} aday haber bulundu ---")

        for entry in entries[:4]:  # Her kaynaktan en yeni 4 haberi işle
            raw_title = entry.title
            link = entry.link
            
            doc_id = hashlib.md5((raw_title + cat).encode("utf-8")).hexdigest()

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
    print(f">>> İŞLEM TAMAMLANDI! Toplam Eklenen Yeni Rapor: {added_count}")
    print(f"==========================================")

if __name__ == "__main__":
    run_scraper()
