# pharmacity-backend

FastAPI backend — bot ning `factory.db` bazasiga ulanadi.

## Ishga tushirish

```bash
cd pharmacity-backend

# Virtual muhit
python -m venv venv
source venv/bin/activate   # Linux/macOS
venv\Scripts\activate      # Windows

pip install -r requirements.txt

# .env sozlash
cp .env.example .env
# DB_PATH ni to'g'ri yo'lga ko'rsating

# Ishga tushirish
uvicorn main:app --reload --port 8000
```

## Endpointlar

| Method | URL | Tavsif |
|--------|-----|--------|
| GET | `/api/health` | Server holati |
| GET | `/api/check-admin/{chat_id}` | Admin tekshiruvi |
| GET | `/api/stats?chat_id=` | Umumiy statistika |
| GET | `/api/materials?chat_id=` | Xomashyolar ro'yxati |
| GET | `/api/products?chat_id=` | Dorilar + retseptlar |
| GET | `/api/batches?chat_id=` | Partiyalar tarixi |
| GET | `/api/stream/{chat_id}` | SSE real-time stream |

## Real-time (SSE)

`/api/stream/{chat_id}` — har 2.5 sekundda DB tekshiradi,
o'zgarish bo'lsa yangi snapshot yuboradi:

```json
{
  "type": "update",
  "materials": [...],
  "recent_batches": [...],
  "stats": { "low_stock_count": 2, "total_produced": 1500, "batches_count": 42 },
  "ts": 1710000000.0
}
```
