import os
import json
import time
import hashlib
from datetime import datetime, timezone
import feedparser
import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai
from groq import Groq

# ---------------------------------------------------------
# 1. ORTAM DEĞİŞKENLERİ & SERVİS BAŞLATMA
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
# 2. 7 STRATEJİK KATEGORİ & GENİŞLETİLMİŞ RSS KAYNAKLARI
# ---------------------------------------------------------
FEEDS_CONFIG = [
    # 1. KÜRESEL MANŞETLER (Tamamen Global Dış Basın - Türkiye Hariç)
    {
        "cat": "breaking_world",
        "source": "Reuters & AP Global Breaking",
        "q": '("breaking news" OR "geopolitics" OR "United Nations" OR "White House" OR "Kremlin" OR "European Union" OR "Middle East" OR "NATO" OR "diplomacy") -sport -entertainment',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "breaking_world",
        "source": "BBC & FT World Affairs",
        "q": '("world summit" OR "foreign policy" OR "geopolitical tension" OR "international crisis" OR "ceasefire" OR "treaty")',
        "hl": "en-GB", "gl": "GB", "ceid": "GB:en"
    },

    # 2. MAKRO EKONOMİ, FİNANS & PİYASALAR
    {
        "cat": "economy_finance",
        "source": "Global Macro & Central Banks",
        "q": '("Federal Reserve" OR "interest rates" OR "ECB" OR "treasury yields" OR "eurobond" OR "inflation" OR "wall street" OR "macroeconomics")',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "economy_finance",
        "source": "TCMB, Para Politikası & BIST",
        "q": '("TCMB" OR "faiz kararı" OR "enflasyon" OR "Borsa İstanbul" OR "eurobond" OR "Hazine" OR "Merkez Bankası")',
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },

    # 3. LÜKS MAISONS & HAUTE HORLOGERIE (Genişletilmiş Küresel Lüks Basını & Saatçilik)
    {
        "cat": "luxury_horology",
        "source": "LVMH, Kering & Luxury Maisons",
        "q": '("LVMH" OR "Kering" OR "Richemont" OR "Hermes" OR "Chanel" OR "Brunello Cucinelli" OR "luxury goods" OR "luxury retail" OR "luxury market")',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "luxury_horology",
        "source": "Haute Horlogerie & Independent Watchmaking",
        "q": '("Rolex" OR "Patek Philippe" OR "Audemars Piguet" OR "Vacheron Constantin" OR "A. Lange" OR "Cartier watch" OR "F.P. Journe" OR "watch auction" OR "Sotheby\'s watches" OR "Phillips watches" OR "horology")',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "luxury_horology",
        "source": "Swiss Watch Industry & Retail",
        "q": '("Federation of the Swiss Watch Industry" OR "Swiss watch exports" OR "Watches and Wonders" OR "independent watchmaker" OR "timepiece")',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },

    # 4. GAYRİMENKUL PİYASASI & ARAZİ YATIRIMLARI
    {
        "cat": "real_estate_market",
        "source": "Global Real Estate & REITs",
        "q": '("commercial real estate" OR "prime residential" OR "housing market" OR "REIT" OR "property investment")',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "real_estate_market",
        "source": "Türkiye Gayrimenkul, Arsa & Konut",
        "q": '("konut fiyat endeksi" OR "arsa yatırımı" OR "GYO" OR "gayrimenkul sektörü" OR "konut satışları" OR "arazi")',
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },

    # 5. YAPAY ZEKA & GİRİŞİM SERMAYESİ (VC)
    {
        "cat": "ai_vc_tech",
        "source": "AI Breakthroughs & Autonomous Tech",
        "q": '("artificial intelligence" OR "large language models" OR "OpenAI" OR "Anthropic" OR "Nvidia" OR "AI chips" OR "AI agent")',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "ai_vc_tech",
        "source": "Venture Capital & Dealmaking",
        "q": '("venture capital" OR "seed round" OR "Series A funding" OR "startup valuation" OR "VC funding" OR "tech investment")',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },

    # 6. DIŞ TİCARET & KÜRESEL LOJİSTİK
    {
        "cat": "trade_logistics",
        "source": "Global Trade Routes & Shipping",
        "q": '("container shipping" OR "freight rates" OR "Drewry" OR "Red Sea shipping" OR "Suez Canal" OR "supply chain disruption" OR "maritime trade")',
        "hl": "en-US", "gl": "US", "ceid": "US:en"
    },
    {
        "cat": "trade_logistics",
        "source": "İhracat & Lojistik TR",
        "q": '("dış ticaret" OR "ihracat rakamları" OR "navlun" OR "liman lojistiği" OR "gümrük" OR "lojistik koridoru")',
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },

    # 7. STRATEJİK EGE RADARI: İZMİR & BODRUM
    {
        "cat": "aegean_radar",
        "source": "İzmir Ticaret, Liman & Sanayi",
        "q": '("İzmir Limanı" OR "Alsancak Limanı" OR "Çandarlı" OR "Kemalpaşa Lojistik" OR "İZTO" OR "EBSO" OR "İzmir serbest bölge")',
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },
    {
        "cat": "aegean_radar",
        "source": "Bodrum & Ege Kıyı Yatırımları",
        "q": '("Bodrum Marina" OR "Yalıkavak Marina" OR "Bodrum lüks resort" OR "Bodrum turizm yatırımı" OR "Bodrum gayrimenkul" OR "Muğla")',
        "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    },
]

# ---------------------------------------------------------
# 3. YAPAY ZEKA KÜRASYON İSTEMİ (PROMPT)
# ---------------------------------------------------------
SYSTEM_PROMPT = """
You are the Chief Intelligence Analyst for the "Private News Room" (Executive Intelligence Platform).
Your mission is to evaluate, curate, and translate strategic news into institutional intelligence.

RULES:
1. Return ONLY a valid, raw JSON object. Do not include markdown codeblocks like ```json.
2. The JSON structure MUST be strictly as follows:
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

CRITICAL SCORING LOGIC:
- DO NOT assign 90 by default. Dynamically evaluate the real impact.
- 93-98: Historic, game-changing market shock or systemic macroeconomic shift.
- 85-92: High-tier corporate move, major investment, key policy change.
- 72-84: Notable industry event, routine balance sheet, regional development.
"""

def analyze_with_ai(title, summary_raw):
    content = f"Title: {title}\nContext/Snippet: {summary_raw}"

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

    # 2. Groq (Yedek)
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
# 4. SCRAPING VE FIRESTORE KAYIT MOTORU
# ---------------------------------------------------------
def run_scraper():
    print(">>> PRIVATE NEWS ROOM: HABER TARAMA BAŞLATILDI...")
    
    # Eski/tekdüze haberleri veritabanından süpürür
    print(">>> ESKİ HABERLER TEMİZLENİYOR...")
    old_docs = db.collection("articles").limit(100).stream()
    deleted_count = 0
    for d in old_docs:
        d.reference.delete()
        deleted_count += 1
    print(f">>> {deleted_count} ADET ESKİ HABER SİLİNDİ, YENİ 7 KATEGORİ ÇEKİLİYOR...")

    articles_col = db.collection("articles")
    added_count = 0

    for feed_info in FEEDS_CONFIG:
        cat = feed_info["cat"]
        source_name = feed_info["source"]
        query = requests.utils.quote(feed_info["q"])
        url = f"[https://news.google.com/rss/search?q=](https://news.google.com/rss/search?q=){query}&hl={feed_info['hl']}&gl={feed_info['gl']}&ceid={feed_info['ceid']}"

        parsed = feedparser.parse(url)
        print(f"\n--- Kategori: [{cat}] | Kaynak: {source_name} ({len(parsed.entries)} aday haber) ---")

        for entry in parsed.entries[:5]:
            raw_title = entry.title
            link = entry.link
            
            doc_id = hashlib.md5((raw_title + cat).encode("utf-8")).hexdigest()

            if articles_col.document(doc_id).get().exists:
                continue

            clean_summary = BeautifulSoup(entry.summary if hasattr(entry, 'summary') else "", "html.parser").get_text()

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
            print(f"  [+] Eklendi ({score/10:.1f}): {raw_title[:65]}...")
            time.sleep(1)

    print(f"\n==========================================")
    print(f">>> ÇEVRİM TAMAMLANDI. Eklenen Yeni Rapor Sayısı: {added_count}")
    print(f"==========================================")

if __name__ == "__main__":
    run_scraper()
