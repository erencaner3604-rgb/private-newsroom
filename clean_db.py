import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

raw_creds = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
cred = credentials.Certificate(json.loads(raw_creds))
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Yeni 7 kategori dışındaki tüm eski kategorileri siliyoruz
VALID_CATEGORIES = [
    "breaking_world",
    "economy_finance",
    "luxury_horology",
    "real_estate_market",
    "ai_vc_tech",
    "trade_logistics",
    "aegean_radar"
]

docs = db.collection("articles").stream()
deleted_count = 0

for doc in docs:
    data = doc.to_dict()
    if data.get("category") not in VALID_CATEGORIES:
        doc.reference.delete()
        deleted_count += 1

print(f">>> TOPLAM {deleted_count} ADET ESKİ KATEGORİ VERİSİ FİRESTORE'DAN TEMİZLENDİ.")
