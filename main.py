"""
pharmacity-backend/main.py

FastAPI backend — bot ning factory.db bazasiga ulanadi.
Real-time yangilanishlar SSE orqali.

Ishga tushirish:
    uvicorn main:app --reload --port 8000
"""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

load_dotenv()

DB_PATH      = os.getenv("DB_PATH",      "../pharmacy_bot/factory.db")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
HOST         = os.getenv("HOST",         "0.0.0.0")
PORT         = int(os.getenv("PORT",     "8000"))


# ─────────────────────────────────────────────────────────────────────────────
# Startup
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = Path(DB_PATH).resolve()
    print(f"[pharmacity-backend] DB: {db_path}")
    if not db_path.exists():
        print(f"  ⚠️  DB topilmadi: {db_path}")
        print("      Bot ni avval ishga tushirib, factory.db yarating.")
    else:
        print(f"  ✅ DB tayyor ({db_path.stat().st_size:,} bayt)")
    yield


app = FastAPI(title="Pharmacity API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers — aiosqlite (async)
# ─────────────────────────────────────────────────────────────────────────────

async def db_fetch(sql: str, params: tuple = ()) -> list[dict]:
    """SELECT — bir nechta qator qaytaradi."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB ERROR] {e}")
        return []


async def db_one(sql: str, params: tuple = ()) -> dict | None:
    """SELECT — bitta qator qaytaradi."""
    rows = await db_fetch(sql, params)
    return rows[0] if rows else None


# ─────────────────────────────────────────────────────────────────────────────
# Admin tekshiruvi
# ─────────────────────────────────────────────────────────────────────────────

async def check_admin(chat_id: int) -> bool:
    row = await db_one("SELECT 1 FROM admins WHERE chat_id = ?", (chat_id,))
    return row is not None


def require_admin(chat_id: int | None):
    """chat_id None yoki admin emas bo'lsa 403 exception."""
    if chat_id is None:
        raise HTTPException(status_code=403, detail="chat_id talab qilinadi")
    return chat_id


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "db_exists": Path(DB_PATH).exists(),
        "db_path": str(Path(DB_PATH).resolve()),
    }


@app.get("/api/check-admin/{chat_id}")
async def check_admin_endpoint(chat_id: int):
    return {"is_admin": await check_admin(chat_id)}


# ── Stats ────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats(chat_id: int | None = None):
    cid = require_admin(chat_id)
    if not await check_admin(cid):
        raise HTTPException(status_code=403, detail="Ruxsat yo'q")

    mats_count    = (await db_one("SELECT COUNT(*) AS c FROM materials"))["c"]
    prods_count   = (await db_one("SELECT COUNT(*) AS c FROM products"))["c"]
    batches_count = (await db_one("SELECT COUNT(*) AS c FROM production_batches"))["c"]
    low_count     = (await db_one(
        "SELECT COUNT(*) AS c FROM materials WHERE current_stock < min_stock"
    ))["c"]
    total_prod    = (await db_one(
        "SELECT COALESCE(SUM(quantity),0) AS s FROM production_batches"
    ))["s"]

    weekly = await db_fetch(
        """
        SELECT DATE(produced_at) AS day, SUM(quantity) AS total
        FROM   production_batches
        WHERE  produced_at >= DATE('now','-6 days')
        GROUP  BY DATE(produced_at)
        ORDER  BY day
        """
    )

    top_products = await db_fetch(
        """
        SELECT p.name, COALESCE(SUM(pb.quantity),0) AS total
        FROM   products p
        LEFT JOIN production_batches pb ON pb.product_id = p.id
        GROUP  BY p.id
        ORDER  BY total DESC
        LIMIT  5
        """
    )

    return {
        "materials_count":   mats_count,
        "products_count":    prods_count,
        "batches_count":     batches_count,
        "low_stock_count":   low_count,
        "total_produced":    total_prod,
        "weekly_production": weekly,
        "top_products":      top_products,
    }


# ── Materials ────────────────────────────────────────────────────────────────

@app.get("/api/materials")
async def get_materials(chat_id: int | None = None):
    cid = require_admin(chat_id)
    if not await check_admin(cid):
        raise HTTPException(status_code=403, detail="Ruxsat yo'q")
    return await db_fetch("SELECT * FROM materials ORDER BY id")


# ── Products ─────────────────────────────────────────────────────────────────

@app.get("/api/products")
async def get_products(chat_id: int | None = None):
    cid = require_admin(chat_id)
    if not await check_admin(cid):
        raise HTTPException(status_code=403, detail="Ruxsat yo'q")

    products = await db_fetch("SELECT * FROM products ORDER BY id")
    result   = []

    for p in products:
        recipe = await db_fetch(
            """
            SELECT r.quantity_grams,
                   m.id            AS material_id,
                   m.name          AS material_name,
                   m.unit,
                   m.current_stock
            FROM   recipes   r
            JOIN   materials m ON m.id = r.material_id
            WHERE  r.product_id = ?
            """,
            (p["id"],),
        )
        total = await db_one(
            "SELECT COALESCE(SUM(quantity),0) AS s FROM production_batches WHERE product_id=?",
            (p["id"],),
        )
        last_batch = await db_one(
            """
            SELECT produced_at, quantity
            FROM   production_batches
            WHERE  product_id = ?
            ORDER  BY produced_at DESC
            LIMIT  1
            """,
            (p["id"],),
        )
        result.append({
            **p,
            "recipe":         recipe,
            "total_produced": total["s"] if total else 0,
            "last_batch":     last_batch,
        })

    return result


# ── Batches ──────────────────────────────────────────────────────────────────

@app.get("/api/batches")
async def get_batches(chat_id: int | None = None, limit: int = 30):
    cid = require_admin(chat_id)
    if not await check_admin(cid):
        raise HTTPException(status_code=403, detail="Ruxsat yo'q")
    return await db_fetch(
        """
        SELECT pb.id,
               pb.quantity,
               pb.produced_at,
               p.name AS product_name
        FROM   production_batches pb
        JOIN   products p ON p.id = pb.product_id
        ORDER  BY pb.produced_at DESC
        LIMIT  ?
        """,
        (limit,),
    )


# ─────────────────────────────────────────────────────────────────────────────
# SSE — Real-time stream
# ─────────────────────────────────────────────────────────────────────────────

async def sse_generator(chat_id: int):
    """
    Har 2.5 sekundda DB ni tekshiradi.
    O'zgarish bo'lsa yangi snapshot yuboradi.
    """
    if not await check_admin(chat_id):
        yield f"data: {json.dumps({'error': 'forbidden'})}\n\n"
        return

    last_batch_id   = -1
    last_stock_hash = ""

    while True:
        try:
            # Oxirgi partiya ID
            lb = await db_one(
                "SELECT id FROM production_batches ORDER BY id DESC LIMIT 1"
            )
            cur_batch_id = lb["id"] if lb else 0

            # Ombor snapshot
            stocks     = await db_fetch("SELECT id, current_stock FROM materials ORDER BY id")
            stock_hash = json.dumps(stocks, sort_keys=True)

            changed = (cur_batch_id != last_batch_id or stock_hash != last_stock_hash)

            if changed:
                last_batch_id   = cur_batch_id
                last_stock_hash = stock_hash

                materials = await db_fetch("SELECT * FROM materials ORDER BY id")
                recent    = await db_fetch(
                    """
                    SELECT pb.id, pb.quantity, pb.produced_at, p.name AS product_name
                    FROM   production_batches pb
                    JOIN   products p ON p.id = pb.product_id
                    ORDER  BY pb.produced_at DESC
                    LIMIT  5
                    """
                )
                stats_snap = {
                    "low_stock_count": len([m for m in materials if m["current_stock"] < m["min_stock"]]),
                    "total_produced":  (await db_one(
                        "SELECT COALESCE(SUM(quantity),0) AS s FROM production_batches"
                    ))["s"],
                    "batches_count":   (await db_one(
                        "SELECT COUNT(*) AS c FROM production_batches"
                    ))["c"],
                }

                payload = {
                    "type":           "update",
                    "materials":      materials,
                    "recent_batches": recent,
                    "stats":          stats_snap,
                    "ts":             time.time(),
                }
                yield f"data: {json.dumps(payload)}\n\n"

            # Heartbeat (keep-alive) — har 20 sekundda
            yield f": heartbeat\n\n"
            await asyncio.sleep(2.5)

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[SSE ERROR] {e}")
            await asyncio.sleep(5)


@app.get("/api/stream/{chat_id}")
async def sse_stream(chat_id: int):
    return StreamingResponse(
        sse_generator(chat_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Ishga tushirish
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
