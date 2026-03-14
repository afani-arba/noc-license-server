"""
Database connection untuk noc-license-server.
Menggunakan MongoDB via Motor (async driver).
"""
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME   = os.getenv("DB_NAME", "noc_license")

client: AsyncIOMotorClient | None = None
db = None


async def connect_db():
    global client, db
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    # Index untuk pencarian cepat
    await db.licenses.create_index("key", unique=True)
    await db.licenses.create_index("customer")
    print(f"[DB] Connected to MongoDB: {MONGO_URL}/{DB_NAME}")


async def close_db():
    global client
    if client:
        client.close()


def get_db():
    return db
