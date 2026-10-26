from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse, PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
DATABASE_PATH = APP_DIR / "luxpet.db"
SECRET_KEY = os.getenv("LUXPET_SECRET_KEY", "luxpet-dev-secret-change-me")
TOKEN_TTL_SECONDS = 60 * 60 * 24

app = FastAPI(
    title="LuxPet Boutique Premium",
    description="Personaliza accesorios exclusivos para tu mascota.",
    version="4.8.0",
)

if not STATIC_DIR.exists():
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

bearer_scheme = HTTPBearer(auto_error=False)

SIZES = ("XXS", "XS", "S", "M", "L", "XL", "XXL")
ACCESSORY_TYPES = (
    "Placa Grabada", "Collar de Cuero", "Arnés Confort", 
    "Correa Elegance 3m", "Bandana de Seda", "Moño de Gala", "Cama Oropel"
)
COLORS = ("Rosa empolvado", "Azul noche", "Verde salvia", "Lavanda", "Dorado Luxe", "Negro Azabache")

PET_TYPES = ("Perro", "Gato", "Conejo", "Hámster", "Hurón", "Loro", "Cobaya", "Capibara", "Erizo")

PET_IMAGES = {
    "Perro": "https://images.unsplash.com/photo-1543466835-00a7907e9de1?auto=format&fit=crop&w=300&q=80",
    "Gato": "https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?auto=format&fit=crop&w=300&q=80",
    "Conejo": "https://images.unsplash.com/photo-1585110396000-c9ffd4e4b308?auto=format&fit=crop&w=300&q=80",
    "Hámster": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcS1p9zHrS4vacaPMMXPwJTaFIwOfxXCfEIwRl26WTm4qg&s=10",
    "Hurón": "https://www.clinicaveterinariazarpa.com/wp-content/uploads/2019/04/huron-cuidados-basicos-veterinario.jpg",
    "Loro": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQebDUS5U76EagNt8m7AP159B41i1YRnHOheNSrxtqvZOhmCEnwS8eU2JE&s=10",
    "Cobaya": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRdHHZ9xrQfd2w5Cft2Ev_BPC21t7hjzK-9iyvhce76sQ&s=10",
    "Capibara": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTE32LihXG7e2E31yQqDiEsEnXt_AzmfG0qDF-gchBubA&s=10",
    "Erizo": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSbQdAjoQMnTfbUa--3D-JcRG531VbWeD-VIRaWLt_97XEq9SJdY7Noks-Y&s=10"
}

PRODUCT_IMAGES = {
    "Placa Grabada": "/static/Placas Confort 3D.jpg",
    "Collar de Cuero": "/static/Coleccion Velvet Gold.jpg",
    "Arnés Confort": "/static/Arnes Ergonomico.jpg",
    "Correa Elegance 3m": "/static/Correa_transito_turquesa.jpg",
    "Bandana de Seda": "/static/Gemini_Generated_Image_lfir6clfir6clfir.jpg",
    "Moño de Gala": "/static/Gemini_Generated_Image_3p2smf3p2smf3p2s.jpg",
    "Cama Oropel": "/static/cama oropel.jpg"
}

COLOR_MAP = {
    "Rosa empolvado": "#f2a6b4",
    "Azul noche": "#1b263b",
    "Verde salvia": "#87a96b",
    "Lavanda": "#b5a7d5",
    "Dorado Luxe": "#d4af37",
    "Negro Azabache": "#1a1a1a"
}

PRICES = {
    "Placa Grabada": 45000,
    "Collar de Cuero": 85000,
    "Arnés Confort": 129900,
    "Correa Elegance 3m": 65000,
    "Bandana de Seda": 38000,
    "Moño de Gala": 29900,
    "Cama Oropel": 189900
}

COUPONS = {
    "LUXPET10": 10,
    "WELCOME": 15,
    "VIP20": 20
}


class UserRegister(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str
    password: str = Field(min_length=6, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Introduce un correo válido.")
        return normalized


class UserLogin(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Introduce un correo válido.")
        return normalized


class AccessoryCustomization(BaseModel):
    accessory_type: str
    pet_name: str = Field(min_length=1, max_length=40)
    pet_type: str = Field(default="Perro")
    color: str
    size: str
    engraving: str = Field(default="", max_length=80)


class CustomizationUpdate(BaseModel):
    accessory_type: str
    pet_name: str = Field(min_length=1, max_length=40)
    pet_type: str = Field(default="Perro")
    color: str
    size: str
    engraving: str = Field(default="", max_length=80)


class OrderCreate(BaseModel):
    payment_method: str
    total_amount: float
    coupon_code: str | None = None


class OrderStatusUpdate(BaseModel):
    status: str


class InventoryUpdate(BaseModel):
    product_name: str
    stock: int


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'client',
                active_session_token TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS customizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                accessory_type TEXT NOT NULL,
                pet_name TEXT NOT NULL,
                pet_type TEXT NOT NULL DEFAULT 'Perro',
                color TEXT NOT NULL,
                size TEXT NOT NULL,
                engraving TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                payment_method TEXT NOT NULL,
                total_amount REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'Completado',
                coupon_applied TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT NOT NULL UNIQUE,
                stock INTEGER NOT NULL DEFAULT 25,
                min_threshold INTEGER NOT NULL DEFAULT 5
            );
            CREATE TABLE IF NOT EXISTS store_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        for prod in ACCESSORY_TYPES:
            exists = connection.execute("SELECT id FROM inventory WHERE product_name = ?", (prod,)).fetchone()
            if not exists:
                connection.execute("INSERT INTO inventory (product_name, stock, min_threshold) VALUES (?, 30, 5)", (prod,))
        
        settings = connection.execute("SELECT key FROM store_settings WHERE key = 'store_status'").fetchone()
        if not settings:
            connection.execute("INSERT INTO store_settings (key, value) VALUES ('store_status', 'open')")
        connection.commit()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"{base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        encoded_salt, encoded_digest = stored_hash.split("$", 1)
        salt = base64.urlsafe_b64decode(encoded_salt.encode())
        expected = base64.urlsafe_b64decode(encoded_digest.encode())
    except (ValueError, base64.binascii.Error):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return hmac.compare_digest(actual, expected)


def encode_token(user_id: int) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": str(user_id), "exp": int(time.time()) + TOKEN_TTL_SECONDS}

    def encode_part(value: dict[str, Any]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    unsigned = f"{encode_part(header)}.{encode_part(payload)}"
    signature = hmac.new(SECRET_KEY.encode(), unsigned.encode(), hashlib.sha256).digest()
    return f"{unsigned}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def decode_token(token: str) -> int:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
        unsigned = f"{encoded_header}.{encoded_payload}"
        expected_signature = hmac.new(
            SECRET_KEY.encode(), unsigned.encode(), hashlib.sha256
        ).digest()
        provided_signature = base64.urlsafe_b64decode(
            encoded_signature + "=" * (-len(encoded_signature) % 4)
        )
        if not hmac.compare_digest(provided_signature, expected_signature):
            raise ValueError("invalid signature")
        payload = json.loads(
            base64.urlsafe_b64decode(
                encoded_payload + "=" * (-len(encoded_payload) % 4)
            ).decode()
        )
        if int(payload["exp"]) < int(time.time()):
            raise ValueError("expired token")
        return int(payload["sub"])
    except (KeyError, ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> sqlite3.Row:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inicia sesión para continuar.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token_str = credentials.credentials
    user_id = decode_token(token_str)
    with get_connection() as connection:
        user = connection.execute(
            "SELECT id, name, email, role, active_session_token, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    if user is None:
        raise HTTPException(status_code=401, detail="Usuario no encontrado.")
    
    if user["email"] == ADMIN_EMAIL or user["role"] == "admin":
        if user["active_session_token"] and user["active_session_token"] != token_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Esta cuenta de administrador ya inició sesión en otro dispositivo. Sesión cerrada aquí por seguridad."
            )
            
    return user


@app.get("/api/catalog")
def catalog() -> dict[str, Any]:
    day_seed = int(datetime.now().strftime("%d"))
    discounts = {}
    for idx, prod in enumerate(ACCESSORY_TYPES):
        if (idx + day_seed) % 3 == 0:
            discounts[prod] = 15
        elif (idx + day_seed) % 5 == 0:
            discounts[prod] = 20
        else:
            discounts[prod] = 0

    with get_connection() as connection:
        inv_rows = connection.execute("SELECT product_name, stock, min_threshold FROM inventory").fetchall()
        inventory_data = {r["product_name"]: {"stock": r["stock"], "min_threshold": r["min_threshold"]} for r in inv_rows}
        
        status_row = connection.execute("SELECT value FROM store_settings WHERE key = 'store_status'").fetchone()
        store_status = status_row["value"] if status_row else "open"

    return {
        "accessory_types": ACCESSORY_TYPES, 
        "colors": COLORS, 
        "sizes": SIZES,
        "pet_types": PET_TYPES,
        "pet_images": PET_IMAGES,
        "product_images": PRODUCT_IMAGES,
        "color_map": COLOR_MAP,
        "prices": PRICES,
        "discounts": discounts,
        "inventory": inventory_data,
        "store_status": store_status
    }


@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
def register(user: UserRegister) -> dict[str, Any]:
    with get_connection() as connection:
        existing = connection.execute("SELECT id, name, email FROM users WHERE email = ?", (user.email.lower(),)).fetchone()
        if existing:
            raise HTTPException(
                status_code=409, 
                detail=f"El correo '{user.email}' ya está registrado. Por favor inicia sesión con tu cuenta existente."
            )

        try:
            cursor = connection.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'client')",
                (user.name.strip(), user.email.lower(), hash_password(user.password)),
            )
            user_id = cursor.lastrowid
            token = encode_token(user_id)
            connection.execute("UPDATE users SET active_session_token = ? WHERE id = ?", (token, user_id))
            connection.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="El correo ya está registrado en el sistema.")

    return {
        "message": "¡Cuenta creada exitosamente!",
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user_id, "name": user.name.strip(), "email": user.email.lower(), "role": "client"},
    }


@app.post("/api/auth/login")
def login(user: UserLogin) -> dict[str, Any]:
    with get_connection() as connection:
        stored_user = connection.execute(
            "SELECT id, name, email, password_hash, role FROM users WHERE email = ?",
            (user.email.lower(),),
        ).fetchone()
        if stored_user is None or not verify_password(user.password, stored_user["password_hash"]):
            raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.")
        
        if stored_user["email"] != ADMIN_EMAIL and stored_user["role"] != "admin":
            status_row = connection.execute("SELECT value FROM store_settings WHERE key = 'store_status'").fetchone()
            if status_row and status_row["value"] == "closed":
                raise HTTPException(
                    status_code=403, 
                    detail="⚠️ La tienda se encuentra temporalmente cerrada por mantenimiento del dueño. Inténtalo más tarde."
                )

        token = encode_token(stored_user["id"])
        connection.execute(
            "UPDATE users SET active_session_token = ? WHERE id = ?",
            (token, stored_user["id"])
        )
        connection.commit()

    return {
        "message": "¡Autenticación completada!",
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": stored_user["id"],
            "name": stored_user["name"],
            "email": stored_user["email"],
            "role": stored_user["role"],
        },
    }


@app.post("/api/customizations", status_code=status.HTTP_201_CREATED)
def create_customization(
    customization: AccessoryCustomization,
    user: sqlite3.Row = Depends(current_user),
) -> dict[str, Any]:
    with get_connection() as connection:
        if user["email"] != ADMIN_EMAIL and user["role"] != "admin":
            status_row = connection.execute("SELECT value FROM store_settings WHERE key = 'store_status'").fetchone()
            if status_row and status_row["value"] == "closed":
                raise HTTPException(status_code=403, detail="La tienda está cerrada por el dueño. No se permiten nuevas compras.")

    if customization.accessory_type not in ACCESSORY_TYPES:
        raise HTTPException(status_code=422, detail="Tipo de accesorio no válido.")
    if customization.pet_type not in PET_TYPES:
        raise HTTPException(status_code=422, detail="Tipo de mascota no válido.")
    if customization.color not in COLORS:
        raise HTTPException(status_code=422, detail="Color no disponible.")
    if customization.size not in SIZES:
        raise HTTPException(status_code=422, detail="Talla no disponible.")
    
    with get_connection() as connection:
        inv = connection.execute("SELECT stock FROM inventory WHERE product_name = ?", (customization.accessory_type,)).fetchone()
        if inv and inv["stock"] <= 0:
            raise HTTPException(status_code=400, detail=f"Lo sentimos, el producto '{customization.accessory_type}' está agotado.")

        cursor = connection.execute(
            """
            INSERT INTO customizations
            (user_id, accessory_type, pet_name, pet_type, color, size, engraving)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                customization.accessory_type,
                customization.pet_name.strip(),
                customization.pet_type,
                customization.color,
                customization.size,
                customization.engraving.strip(),
            ),
        )
        saved = connection.execute(
            "SELECT * FROM customizations WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return {"message": "¡Diseño agregado al carrito con éxito!", "customization": dict(saved)}


@app.get("/api/customizations")
def list_customizations(
    user: sqlite3.Row = Depends(current_user),
) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM customizations WHERE user_id = ? ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
    return [dict(row) for row in rows]


@app.delete("/api/customizations/{customization_id}")
def delete_customization(
    customization_id: int,
    user: sqlite3.Row = Depends(current_user),
) -> dict[str, Any]:
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM customizations WHERE id = ? AND user_id = ?",
            (customization_id, user["id"]),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Producto no encontrado en tu carrito.")
    return {"message": "Producto eliminado del carrito correctamente."}


@app.get("/api/user/me")
def get_user_profile(user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    with get_connection() as connection:
        orders = connection.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)
        ).fetchall()
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "created_at": user["created_at"],
        "orders": [dict(o) for o in orders]
    }


@app.post("/api/coupons/validate")
def validate_coupon(data: dict[str, str]) -> dict[str, Any]:
    code = data.get("code", "").strip().upper()
    if code in COUPONS:
        return {"valid": True, "discount_percentage": COUPONS[code], "message": f"¡Cupón '{code}' aplicado con éxito ({COUPONS[code]}% OFF)!"}
    raise HTTPException(status_code=400, detail="Cupón de descuento no válido o expirado.")


@app.post("/api/orders", status_code=status.HTTP_201_CREATED)
def create_order(
    order_data: OrderCreate,
    user: sqlite3.Row = Depends(current_user),
) -> dict[str, Any]:
    with get_connection() as connection:
        if user["email"] != ADMIN_EMAIL and user["role"] != "admin":
            status_row = connection.execute("SELECT value FROM store_settings WHERE key = 'store_status'").fetchone()
            if status_row and status_row["value"] == "closed":
                raise HTTPException(status_code=403, detail="La tienda se encuentra cerrada por el dueño. No se pueden procesar pagos.")

        cart_items = connection.execute(
            "SELECT * FROM customizations WHERE user_id = ?", (user["id"],)
        ).fetchall()

        if not cart_items:
            raise HTTPException(
                status_code=400, detail="No puedes procesar una orden con el carrito vacío."
            )

        for item in cart_items:
            prod_name = item["accessory_type"]
            connection.execute(
                "UPDATE inventory SET stock = MAX(0, stock - 1) WHERE product_name = ?",
                (prod_name,)
            )

        cursor = connection.execute(
            """
            INSERT INTO orders (user_id, payment_method, total_amount, coupon_applied)
            VALUES (?, ?, ?, ?)
            """,
            (user["id"], order_data.payment_method, order_data.total_amount, order_data.coupon_code),
        )
        order_id = cursor.lastrowid
        connection.execute("DELETE FROM customizations WHERE user_id = ?", (user["id"],))
        connection.commit()

    return {
        "message": "¡Orden registrada con éxito!",
        "order_id": order_id,
        "payment_method": order_data.payment_method,
        "total_amount": order_data.total_amount,
    }


@app.get("/api/orders")
def list_orders(user: sqlite3.Row = Depends(current_user)) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
    return [dict(row) for row in rows]


# ==============================================================================
# FUNCIONES EXCLUSIVAS PARA EL DUEÑO (ADMINISTRADOR)
# ==============================================================================

ADMIN_EMAIL = "julianjuanm@gmail.com"
ADMIN_PASSWORD = "arroz1234"


def init_admin_role_and_account() -> None:
    with get_connection() as conn:
        try:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'client'")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN active_session_token TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        admin_user = conn.execute("SELECT id FROM users WHERE email = ?", (ADMIN_EMAIL,)).fetchone()
        if not admin_user:
            conn.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'admin')",
                ("Juan Manuel (Dueño Propietario)", ADMIN_EMAIL, hash_password(ADMIN_PASSWORD))
            )
        else:
            conn.execute(
                "UPDATE users SET role = 'admin', password_hash = ? WHERE id = ?",
                (hash_password(ADMIN_PASSWORD), admin_user["id"])
            )
        conn.commit()


initialize_database()
init_admin_role_and_account()


def current_admin(user: sqlite3.Row = Depends(current_user)) -> sqlite3.Row:
    if user["email"] != ADMIN_EMAIL and user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso exclusivo para el Dueño Propietario de LuxPet."
        )
    return user


@app.get("/api/admin/metrics")
def get_admin_metrics(filter_period: str = "all", admin: sqlite3.Row = Depends(current_admin)) -> dict[str, Any]:
    with get_connection() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        total_revenue = conn.execute("SELECT COALESCE(SUM(total_amount), 0) FROM orders").fetchone()[0]
        
        date_filter_sql = ""
        now = datetime.now()
        if filter_period == "today":
            date_filter_sql = f"WHERE DATE(created_at) = '{now.strftime('%Y-%m-%d')}'"
        elif filter_period == "week":
            week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')
            date_filter_sql = f"WHERE DATE(created_at) >= '{week_ago}'"
        elif filter_period == "month":
            month_ago = (now - timedelta(days=30)).strftime('%Y-%m-%d')
            date_filter_sql = f"WHERE DATE(created_at) >= '{month_ago}'"

        daily_sales = conn.execute(f"""
            SELECT DATE(created_at) as sale_date, COUNT(*) as orders_count, SUM(total_amount) as daily_revenue
            FROM orders {date_filter_sql} GROUP BY DATE(created_at) ORDER BY sale_date DESC
        """).fetchall()

        top_products = conn.execute(f"""
            SELECT accessory_type as product_name, COUNT(*) as total_sold
            FROM customizations GROUP BY accessory_type ORDER BY total_sold DESC
        """).fetchall()

        recent_orders = conn.execute(f"""
            SELECT o.id, u.name as user_name, u.email, o.payment_method, o.total_amount, o.status, o.created_at
            FROM orders o JOIN users u ON o.user_id = u.id {date_filter_sql.replace('created_at', 'o.created_at')} ORDER BY o.created_at DESC
        """).fetchall()
        
        all_users = conn.execute("SELECT id, name, email, role, created_at FROM users ORDER BY id DESC").fetchall()
        inventory_rows = conn.execute("SELECT * FROM inventory").fetchall()
        
        status_row = conn.execute("SELECT value FROM store_settings WHERE key = 'store_status'").fetchone()
        store_status = status_row["value"] if status_row else "open"

    return {
        "metrics": {
            "users_count": total_users,
            "orders_count": total_orders,
            "total_revenue": total_revenue
        },
        "daily_sales": [dict(r) for r in daily_sales],
        "top_products": [dict(r) for r in top_products],
        "inventory": [dict(r) for r in inventory_rows],
        "orders": [dict(r) for r in recent_orders],
        "users": [dict(u) for u in all_users],
        "store_status": store_status
    }


@app.put("/api/admin/store/toggle")
def toggle_store_status(admin: sqlite3.Row = Depends(current_admin)) -> dict[str, Any]:
    with get_connection() as conn:
        current = conn.execute("SELECT value FROM store_settings WHERE key = 'store_status'").fetchone()
        new_status = "closed" if current and current["value"] == "open" else "open"
        conn.execute("UPDATE store_settings SET value = ? WHERE key = 'store_status'", (new_status,))
        conn.commit()
    return {"message": f"Estado de la tienda actualizado a: {'Abierta' if new_status == 'open' else 'Cerrada'}", "status": new_status}


@app.put("/api/admin/inventory")
def update_inventory(
    inv_update: InventoryUpdate,
    admin: sqlite3.Row = Depends(current_admin),
) -> dict[str, Any]:
    with get_connection() as conn:
        conn.execute(
            "UPDATE inventory SET stock = ? WHERE product_name = ?",
            (inv_update.stock, inv_update.product_name)
        )
        conn.commit()
    return {"message": f"Inventario de '{inv_update.product_name}' actualizado a {inv_update.stock} unidades."}


@app.put("/api/admin/orders/{order_id}/status")
def update_order_status(
    order_id: int,
    status_update: OrderStatusUpdate,
    admin: sqlite3.Row = Depends(current_admin),
) -> dict[str, Any]:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE orders SET status = ? WHERE id = ?",
            (status_update.status, order_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Orden no encontrada.")
        conn.commit()
    return {"message": f"Estado de la orden #{order_id} actualizado a '{status_update.status}'."}


@app.delete("/api/admin/users/{user_id}")
def delete_user_by_admin(
    user_id: int,
    admin: sqlite3.Row = Depends(current_admin),
) -> dict[str, Any]:
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propia cuenta de Dueño.")
    
    with get_connection() as conn:
        conn.execute("DELETE FROM customizations WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM orders WHERE user_id = ?", (user_id,))
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")
        conn.commit()
    return {"message": "Usuario y sus registros asociados han sido eliminados correctamente."}


@app.get("/api/admin/export/orders")
def export_orders_csv(admin: sqlite3.Row = Depends(current_admin)) -> StreamingResponse:
    with get_connection() as conn:
        orders = conn.execute("""
            SELECT o.id, u.name, u.email, o.payment_method, o.total_amount, o.status, o.created_at
            FROM orders o JOIN users u ON o.user_id = u.id ORDER BY o.created_at DESC
        """).fetchall()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID Orden", "Cliente", "Email", "Método de Pago", "Monto Total (COP)", "Estado", "Fecha Creación"])

    for o in orders:
        writer.writerow([o["id"], o["name"], o["email"], o["payment_method"], o["total_amount"], o["status"], o["created_at"]])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=luxpet_reporte_ventas.csv"}
    )


@app.get("/api/admin/export/users")
def export_users_csv(admin: sqlite3.Row = Depends(current_admin)) -> StreamingResponse:
    with get_connection() as conn:
        users = conn.execute("SELECT id, name, email, role, created_at FROM users ORDER BY id DESC").fetchall()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID Usuario", "Nombre Completo", "Correo Electrónico (Email)", "Rol", "Fecha Registro"])

    for u in users:
        writer.writerow([u["id"], u["name"], u["email"], u["role"], u["created_at"]])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=luxpet_clientes_correos.csv"}
    )


# ==============================================================================
# ENDPOINT DE HEALTH CHECK (PARA MANTENER ACTIVO EL SERVIDOR EN RENDER)
# ==============================================================================
@app.api_route("/api/health", methods=["GET", "HEAD"])
def health_check():
    return "OK"


# ==============================================================================
# VISTA FRONTEND PRINCIPAL Y PANEL JS
# ==============================================================================

HOME_PAGE = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LuxPet Boutique | Acceso Privado</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=Playfair+Display:ital,wght@0,600;0,700;1,400&family=Great+Vibes&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
  <style>
    :root {
      --bg-cream: #fbf7f2;
      --gold: #d4af37;
      --gold-dark: #aa820a;
      --ink: #221f26;
      --card-bg: rgba(255, 255, 255, 0.92);
    }
    body {
      color: var(--ink);
      background-color: var(--bg-cream);
      background-image: url("data:image/svg+xml,%3Csvg width='80' height='80' viewBox='0 0 80 80' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='%23d4af37' fill-opacity='0.12' fill-rule='evenodd'%3E%3Cpath d='M20 18c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm8 0c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm-12 6c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm16 0c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm-8 6c-3.3 0-6-2.7-6-6 0-1.2.4-2.3 1-3.2 1.2 1.3 3 2.2 5 2.2s3.8-.9 5-2.2c.6.9 1 2 1 3.2 0 3.3-2.7 6-6 6z'/%3E%3Cpath d='M60 58c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm8 0c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm-12 6c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm16 0c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm-8 6c-3.3 0-6-2.7-6-6 0-1.2.4-2.3 1-3.2 1.2 1.3 3 2.2 5 2.2s3.8-.9 5-2.2c.6.9 1 2 1 3.2 0 3.3-2.7 6-6 6 z'/%3E%3C/g%3E%3C/svg%3E");
      font-family: 'Plus Jakarta Sans', sans-serif;
      overflow-x: hidden;
      min-height: 100vh;
    }
    h1, h2, h3, .brand-font { font-family: 'Playfair Display', serif; }
    .fancy-title {
      font-family: 'Great Vibes', cursive;
      background: linear-gradient(135deg, #d4af37, #e8a598, #aa820a);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      filter: drop-shadow(0px 2px 4px rgba(0,0,0,0.15));
    }
    .navbar {
      background: rgba(253, 249, 246, 0.95);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid #ebdcd5;
    }
    .brand-logo-img { height: 42px; width: auto; object-fit: contain; border-radius: 6px; }
    .login-wrapper {
      min-height: calc(100vh - 80px);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 40px 20px;
      background: linear-gradient(rgba(0, 0, 0, 0.45), rgba(0, 0, 0, 0.45)), 
                  url('https://images.unsplash.com/photo-1548199973-03cce0bbc87b?auto=format&fit=crop&w=1920&q=80') center/cover no-repeat fixed;
    }
    .login-box { max-width: 900px; width: 100%; }
    .dog-container { width: 130px; height: 130px; margin: 0 auto; cursor: pointer; position: relative; }
    .dog-tail { transform-origin: 10px 80px; animation: wagTail 0.8s ease-in-out infinite alternate; }
    .dog-ear-l { transform-origin: 30px 35px; animation: earFlap 2.5s ease-in-out infinite; }
    .dog-ear-r { transform-origin: 70px 35px; animation: earFlap 2.5s ease-in-out 0.3s infinite; }
    .dog-eye { animation: blinkEye 4s infinite; transform-origin: center; }
    @keyframes wagTail { 0% { transform: rotate(0deg); } 100% { transform: rotate(28deg); } }
    @keyframes earFlap { 0%, 100% { transform: rotate(0deg); } 50% { transform: rotate(-8deg); } }
    @keyframes blinkEye { 0%, 94%, 98%, 100% { transform: scaleY(1); } 96% { transform: scaleY(0.1); } }
    .hero {
      position: relative;
      background: linear-gradient(135deg, rgba(253, 249, 246, 0.88), rgba(247, 234, 229, 0.92)),
                  url('https://images.unsplash.com/photo-1534361960057-19889db9875e?auto=format&fit=crop&w=1600&q=80') center/cover no-repeat;
      padding: 60px 0 50px;
      border-bottom: 1px solid #efe3db;
    }
    .preview-card {
      background: rgba(255, 255, 255, 0.95);
      border: 1px solid #e8dbd2;
      border-radius: 24px;
      box-shadow: 0 20px 40px rgba(60, 38, 25, 0.08);
      padding: 25px;
      position: relative;
      backdrop-filter: blur(10px);
    }
    .preview-box {
      background: #faf6f0;
      border: 2px dashed #e2d2c7;
      border-radius: 20px;
      padding: 35px 20px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 220px;
      position: relative;
    }
    .preview-pet-img {
      width: 70px; height: 70px; border-radius: 50%; object-fit: cover;
      border: 3px solid var(--gold); box-shadow: 0 4px 10px rgba(0,0,0,0.15); margin-bottom: 15px;
    }
    .collar-strap {
      height: 26px; width: 85%; border-radius: 13px; background-color: #f2a6b4;
      box-shadow: 0 6px 15px rgba(0,0,0,0.12); position: relative; display: flex; align-items: center; justify-content: center; transition: all 0.4s ease;
    }
    .collar-buckle {
      position: absolute; right: 15px; width: 16px; height: 32px;
      background: linear-gradient(135deg, #d4af37, #fff2a3, #a8820a); border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.2);
    }
    .collar-tag {
      position: absolute; width: 52px; height: 52px; background: linear-gradient(135deg, #ffd700, #fff3a1, #b8860b);
      border-radius: 50%; top: 12px; box-shadow: 0 6px 15px rgba(212, 175, 55, 0.4); display: flex; flex-direction: column;
      align-items: center; justify-content: center; font-size: 0.7rem; font-weight: 700; color: #2b2100; text-align: center;
      padding: 4px; word-break: break-all; transition: all 0.3s ease; cursor: pointer;
    }
    .collar-tag:hover { transform: scale(1.1) rotate(5deg); }
    .tag-ring { width: 10px; height: 10px; border: 2px solid #8d6700; border-radius: 50%; position: absolute; top: -7px; }
    .card-custom { border: 1px solid #efe3db; border-radius: 20px; background: rgba(255, 255, 255, 0.94); box-shadow: 0 10px 30px rgba(0,0,0,0.04); backdrop-filter: blur(8px); }
    .btn-gold {
      background: linear-gradient(135deg, #d4af37, #c59b27); color: #ffffff; font-weight: 600; border: none;
      border-radius: 50px; padding: 12px 28px; box-shadow: 0 4px 15px rgba(212, 175, 55, 0.3); transition: all 0.3s ease;
    }
    .btn-gold:hover { background: linear-gradient(135deg, #c59b27, #a8820a); color: #fff; transform: translateY(-2px); box-shadow: 0 6px 20px rgba(212, 175, 55, 0.4); }
    .form-control, .form-select { border-radius: 12px; border: 1px solid #e0d0c5; padding: 10px 14px; background-color: #fff; }
    .form-control:focus, .form-select:focus { border-color: var(--gold); box-shadow: 0 0 0 0.25rem rgba(212, 175, 55, 0.2); }
    #checkout { display: none; }
    .pay-card { border: 2px solid #ebdcd5; border-radius: 14px; padding: 16px; cursor: pointer; transition: all 0.2s ease; background: #ffffff; height: 100%; }
    .pay-card:hover, .pay-card.active { border-color: var(--gold); background: #fffdf7; transform: translateY(-3px); box-shadow: 0 8px 20px rgba(212, 175, 55, 0.15); }
    #alert { position: fixed; right: 25px; top: 85px; z-index: 999; }
    .cart-btn-nav { position: relative; border-radius: 50px; background: #ffffff; border: 1px solid #ebdcd5; padding: 6px 16px; cursor: pointer; transition: all 0.2s ease; }
    .cart-btn-nav:hover { background: #fdfbf7; border-color: var(--gold); }
    .cart-badge { position: absolute; top: -6px; right: -6px; background: var(--gold-dark); color: #fff; font-size: 0.7rem; font-weight: 700; width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; }
    .catalog-grid-img { width: 100%; height: 140px; object-fit: cover; border-radius: 12px; }
    
    .search-autocomplete-box {
      position: absolute; top: 100%; left: 0; right: 0; background: #ffffff; border: 1px solid #ebdcd5;
      border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); z-index: 1050; max-height: 250px; overflow-y: auto; display: none;
    }
    .search-suggestion-item { padding: 10px 15px; cursor: pointer; border-bottom: 1px solid #f2ece9; font-size: 0.9rem; }
    .search-suggestion-item:hover { background: #fdfbf7; color: var(--gold-dark); font-weight: 600; }
  </style>
</head>
<body>

<nav class="navbar navbar-expand-lg sticky-top">
  <div class="container py-1 d-flex justify-content-between align-items-center">
    <div class="d-flex align-items-center gap-3">
      <button class="btn btn-outline-dark rounded-circle p-2 d-none" id="btnSidebarToggle" type="button" data-bs-toggle="offcanvas" data-bs-target="#sidebarDrawer">
        ☰
      </button>

      <a class="navbar-brand brand-font fs-3 text-dark fw-bold mb-0 d-flex align-items-center gap-2" href="#">
        <img src="/static/Logo principal.jpg" alt="LuxPet Logo Principal" class="brand-logo-img">
        <span>LuxPet <span class="fs-6 text-muted font-sans fw-normal">Boutique</span></span>
      </a>
    </div>

    <!-- Barra de búsqueda oculta por defecto en la vista de Login/Registro -->
    <div class="d-none align-items-center flex-grow-1 mx-4 position-relative" id="clientSearchWrapper">
      <input type="text" id="homeSearchInput" class="form-control rounded-pill px-3 py-1 bg-white shadow-sm" placeholder="🔍 Buscar placas, collares, arneses, camas..." oninput="handleSearchAutocomplete(this.value)">
      <div id="searchSuggestions" class="search-autocomplete-box"></div>
    </div>

    <div class="d-flex align-items-center gap-3" id="userNavStatus"></div>
  </div>
</nav>

<div id="alert"></div>

<div class="offcanvas offcanvas-start" tabindex="-1" id="sidebarDrawer">
  <div class="offcanvas-header border-bottom">
    <div class="d-flex align-items-center gap-2">
      <img src="/static/Logo dorado.jpg" alt="LuxPet Logo Dorado" style="height: 35px; width: auto;" class="rounded">
      <h5 class="offcanvas-title brand-font fw-bold">LuxPet Menú</h5>
    </div>
    <button type="button" class="btn-close" data-bs-dismiss="offcanvas" aria-label="Close"></button>
  </div>
  <div class="offcanvas-body d-flex flex-column justify-content-between">
    <div>
      <div class="p-3 bg-light rounded-4 mb-4">
        <div class="d-flex align-items-center gap-3">
          <div class="fs-2">👤</div>
          <div>
            <strong class="d-block text-dark" id="sbUserName">Usuario</strong>
            <small class="text-muted d-block" id="sbUserEmail">correo@ejemplo.com</small>
          </div>
        </div>
      </div>

      <h6 class="fw-bold text-uppercase small text-muted mb-3">Galería y Estilos</h6>
      <div class="row g-2 mb-4">
        <div class="col-6 text-center">
          <img src="/static/Coleccion Velvet Gold.jpg" class="catalog-grid-img" alt="Collar">
          <span class="d-block small fw-semibold mt-1">Collares Velvet</span>
        </div>
        <div class="col-6 text-center">
          <img src="/static/Placas Confort 3D.jpg" class="catalog-grid-img" alt="Placa">
          <span class="d-block small fw-semibold mt-1">Placas 3D</span>
        </div>
      </div>

      <h6 class="fw-bold text-uppercase small text-muted mb-2">Soporte del Propietario</h6>
      <div class="small text-secondary mb-3">
        <p class="mb-1">📧 julianjuanm@gmail.com (Dueño)</p>
        <p class="mb-1">📱 +57 314 4537607</p>
      </div>
    </div>

    <div class="pt-3 border-top">
      <button onclick="logout()" class="btn btn-outline-danger w-100 rounded-pill">
        🔒 Cerrar sesión
      </button>
    </div>
  </div>
</div>

<div id="loginScreen" class="login-wrapper">
  <div class="login-box">
    <div class="row align-items-center g-4">
      <div class="col-lg-6 text-center text-lg-start text-white pe-lg-4">
        <span class="badge bg-warning text-dark mb-2 px-3 py-2 rounded-pill fw-bold text-uppercase" style="letter-spacing:1px;">Colección Exclusiva 🐾</span>
        <h1 class="display-3 fancy-title mb-0">Luxpet Boutique</h1>
        <p class="fs-5 text-light opacity-90 fw-light mt-2 mb-4">Alta costura y accesorios personalizados con grabado láser para los reyes del hogar.</p>
      </div>

      <div class="col-lg-6">
        <div class="card card-custom p-4 shadow-lg border-0">
          <div class="text-center mb-3">
            <img src="/static/Logo principal.jpg" alt="LuxPet Logo Principal" style="height: 60px;" class="mb-2 rounded shadow-sm">
            <h2 class="h4 brand-font fw-bold mt-1 mb-0">Bienvenido a la Boutique</h2>
            <p class="text-muted small">Ingresa tus datos o regístrate.</p>
          </div>

          <div class="btn-group w-100 mb-3" role="group">
            <button type="button" class="btn btn-outline-dark btn-sm active" onclick="setMode('login',this)">Iniciar sesión</button>
            <button type="button" class="btn btn-outline-dark btn-sm" onclick="setMode('register',this)">Registrarse</button>
          </div>

          <form id="authForm">
            <div id="nameWrap" class="mb-3 d-none">
              <label class="form-label small fw-semibold">Nombre completo</label>
              <input id="name" class="form-control" placeholder="Ej. Camila Silva">
            </div>
            <div class="mb-3">
              <label class="form-label small fw-semibold">Correo electrónico</label>
              <input id="email" type="email" class="form-control" placeholder="nombre@correo.com" required>
            </div>
            <div class="mb-4">
              <label class="form-label small fw-semibold">Contraseña</label>
              <input id="password" type="password" class="form-control" minlength="6" required>
            </div>
            <button class="btn btn-gold w-100" id="authButton">Entrar a mi cuenta</button>
          </form>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="mainContent" class="d-none">
  
  <section class="py-4 bg-white border-bottom">
    <div class="container">
      <div class="text-center mb-4">
        <span class="badge bg-warning text-dark px-3 py-1 rounded-pill fw-bold text-uppercase">Nuestra Colección de Alta Costura y Confort</span>
        <h2 class="h3 brand-font fw-bold mt-2">Diseños únicos confeccionados para consentir a tu mascota</h2>
      </div>
      <div class="row g-3">
        <div class="col-md-3">
          <div class="card border-0 shadow-sm rounded-4 overflow-hidden">
            <img src="/static/Coleccion Velvet Gold.jpg" class="w-100" style="height: 160px; object-fit: cover;" alt="Collar">
            <div class="card-body p-2 text-center bg-light"><small class="fw-bold">Collares Velvet Gold</small></div>
          </div>
        </div>
        <div class="col-md-3">
          <div class="card border-0 shadow-sm rounded-4 overflow-hidden">
            <img src="/static/Placas Confort 3D.jpg" class="w-100" style="height: 160px; object-fit: cover;" alt="Placas">
            <div class="card-body p-2 text-center bg-light"><small class="fw-bold">Placas Grabadas 3D</small></div>
          </div>
        </div>
        <div class="col-md-3">
          <div class="card border-0 shadow-sm rounded-4 overflow-hidden">
            <img src="/static/Arnes Ergonomico.jpg" class="w-100" style="height: 160px; object-fit: cover;" alt="Arneses">
            <div class="card-body p-2 text-center bg-light"><small class="fw-bold">Arneses Ergonómicos</small></div>
          </div>
        </div>
        <div class="col-md-3">
          <div class="card border-0 shadow-sm rounded-4 overflow-hidden">
            <img src="/static/images.jpg" class="w-100" style="height: 160px; object-fit: cover;" alt="Accesorios">
            <div class="card-body p-2 text-center bg-light"><small class="fw-bold">Accesorios de Lujo</small></div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <header class="hero">
    <div class="container">
      <div class="row align-items-center g-4">
        <div class="col-lg-6">
          <div class="dog-container" title="¡Hazme un mimito!" onclick="barkDog()">
            <svg viewBox="0 0 100 100">
              <path class="dog-tail" d="M 15 75 Q 5 60 18 50" stroke="#c48b57" stroke-width="7" stroke-linecap="round" fill="none"/>
              <ellipse cx="40" cy="70" rx="22" ry="16" fill="#df9b62"/>
              <rect x="25" y="78" width="6" height="15" rx="3" fill="#c48b57"/>
              <rect x="45" y="78" width="6" height="15" rx="3" fill="#c48b57"/>
              <circle cx="50" cy="45" r="20" fill="#df9b62"/>
              <path class="dog-ear-l" d="M 32 35 C 20 35 20 55 30 55 C 33 55 35 45 32 35 Z" fill="#8c532b"/>
              <path class="dog-ear-r" d="M 68 35 C 80 35 80 55 70 55 C 67 55 65 45 68 35 Z" fill="#8c532b"/>
              <ellipse cx="50" cy="50" rx="9" ry="7" fill="#fff5ea"/>
              <ellipse cx="50" cy="46" rx="4" ry="3" fill="#2b1a0e"/>
              <circle class="dog-eye" cx="43" cy="40" r="2.5" fill="#2b1a0e"/>
              <circle class="dog-eye" cx="57" cy="40" r="2.5" fill="#2b1a0e"/>
              <path id="dogTongue" d="M 48 53 Q 50 60 52 53 Z" fill="#f28b82" opacity="0.8"/>
            </svg>
          </div>

          <span class="text-uppercase small fw-bold tracking-wider d-block text-center text-lg-start mt-2" style="color:var(--gold-dark); letter-spacing: 2px;">Hecho a mano en Italia & Colombia</span>
          <h1 class="display-5 fw-bold mt-2 mb-3 text-center text-lg-start">Elegancia y ternura para tu mejor amigo.</h1>
          <p class="lead text-secondary mb-4 text-center text-lg-start">Diseña placas, collares, arneses y camas de alta gama con grabado láser en tiempo real y descuentos especiales.</p>
          
          <div class="d-flex gap-3 justify-content-center justify-content-lg-start">
            <a href="#designer" class="btn btn-gold btn-lg">Diseñar Accesorio</a>
            <button onclick="mostrarMetodoPago(true)" class="btn btn-outline-dark rounded-pill btn-lg px-4">Métodos de Pago</button>
          </div>
        </div>

        <div class="col-lg-6">
          <div class="preview-card">
            <div class="d-flex justify-content-between align-items-center mb-3">
              <span class="fw-bold text-uppercase small text-muted">Vista previa 3D en vivo</span>
              <span class="badge bg-warning text-dark border" id="badgeDiscountPreview">¡Descuento del Día!</span>
            </div>
            <div class="preview-box">
              <img id="prevPetImg" src="https://images.unsplash.com/photo-1543466835-00a7907e9de1?auto=format&fit=crop&w=300&q=80" class="preview-pet-img" alt="Mascota">
              
              <div class="collar-strap" id="prevStrap">
                <div class="collar-buckle"></div>
                <div class="collar-tag" id="prevTag">
                  <div class="tag-ring"></div>
                  <span id="prevPetName">Mascota</span>
                  <span id="prevEngraving" style="font-size:0.5rem; opacity:0.85;"></span>
                </div>
              </div>
            </div>
            <div class="row text-center mt-3 pt-2 border-top g-2">
              <div class="col-3"><small class="text-muted d-block">Animal</small><strong id="lblPetType">Perro</strong></div>
              <div class="col-3"><small class="text-muted d-block">Talla</small><strong id="lblSize">M</strong></div>
              <div class="col-3"><small class="text-muted d-block">Color</small><strong id="lblColor">Rosa empolvado</strong></div>
              <div class="col-3"><small class="text-muted d-block">Precio</small><strong id="lblPrice" class="text-success">$0</strong></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </header>

  <main class="container py-5">
    
    <section class="mb-5">
      <div class="d-flex justify-content-between align-items-center mb-4">
        <div>
          <h2 class="h4 mb-1">Catálogo Exclusivo LuxPet</h2>
          <p class="text-muted small mb-0">Nuestros productos estelares disponibles para personalizar.</p>
        </div>
      </div>
      <div class="row g-4" id="clientCatalogCards"></div>
    </section>

    <section id="designer" class="mb-5">
      <div class="card card-custom p-4">
        <div class="d-flex justify-content-between align-items-center mb-3">
          <div>
            <h2 class="h4 mb-1">Personaliza tu accesorio</h2>
            <p class="text-muted small mb-0">Selecciona el tipo de mascota, materiales, colores y grabado.</p>
          </div>
          <span class="fs-2">💎</span>
        </div>

        <form id="designForm">
          <div class="row g-3">
            <div class="col-md-6">
              <label class="form-label fw-semibold small">Tipo de accesorio</label>
              <select id="accessory_type" class="form-select" required onchange="updatePreview()"><option value="">Seleccionar...</option></select>
            </div>
            <div class="col-md-6">
              <label class="form-label fw-semibold small">Tipo de mascota</label>
              <select id="pet_type" class="form-select" required><option value="">Seleccionar...</option></select>
            </div>
            <div class="col-md-6">
              <label class="form-label fw-semibold small">Nombre de tu mascota</label>
              <input id="pet_name" class="form-control" placeholder="Ej. Bruno" required>
            </div>
            <div class="col-md-6">
              <label class="form-label fw-semibold small">Color del cuero/tela</label>
              <select id="color" class="form-select" required><option value="">Seleccionar...</option></select>
            </div>
            <div class="col-md-6">
              <label class="form-label fw-semibold small">Talla</label>
              <select id="size" class="form-select" required><option value="">Seleccionar...</option></select>
            </div>
            <div class="col-12">
              <label class="form-label fw-semibold small">Teléfono o mensaje para grabado (opcional)</label>
              <input id="engraving" class="form-control" placeholder="Ej. 300 123 4567 / Vacunado">
            </div>
            <div class="col-12 pt-2">
              <button class="btn btn-gold btn-lg w-100">Agregar al Carrito de Compras ✨</button>
            </div>
          </div>
        </form>

        <div id="designs" class="mt-4"></div>
      </div>
    </section>

    <section id="checkout" class="pt-4 border-top mb-5">
      <div class="card card-custom p-4">
        <div class="text-center mb-4">
          <h2 class="h3 fw-bold">Método de Pago & Cupones</h2>
          <p class="text-muted small">Aplica cupones de descuento y selecciona tu método de pago preferido.</p>
        </div>

        <div class="row justify-content-center mb-4">
          <div class="col-md-6">
            <div class="input-group">
              <input type="text" id="couponInput" class="form-control" placeholder="Código de cupón (Ej. LUXPET10, WELCOME)">
              <button class="btn btn-outline-dark" type="button" onclick="applyCoupon()">Aplicar Cupón</button>
            </div>
            <small id="couponFeedback" class="text-success fw-semibold d-block mt-1"></small>
          </div>
        </div>

        <div class="row g-3 mb-4">
          <div class="col-md-4">
            <div class="pay-card text-center" onclick="selectPay(this, 'Tarjeta de Crédito')">
              <div class="fs-2 mb-2">💳</div>
              <strong class="d-block mb-1">Tarjeta de Crédito</strong>
              <span class="text-muted small">Visa / Mastercard</span>
            </div>
          </div>
          <div class="col-md-4">
            <div class="pay-card text-center" onclick="selectPay(this, 'PayPal')">
              <div class="fs-2 mb-2">🅿️</div>
              <strong class="d-block mb-1">PayPal</strong>
              <span class="text-muted small">Pago rápido</span>
            </div>
          </div>
          <div class="col-md-4">
            <div class="pay-card text-center" onclick="selectPay(this, 'Transferencia QR')">
              <div class="fs-2 mb-2">📱</div>
              <strong class="d-block mb-1">Transferencia QR</strong>
              <span class="text-muted small">Nequi / Daviplata</span>
            </div>
          </div>
        </div>

        <div class="mt-4 p-4 bg-light rounded-4 text-center border">
          <p class="mb-2 text-muted small">Monto Total Final: <strong class="text-dark fs-4" id="checkoutTotalAmount">$0 COP</strong> <span class="text-muted">(IVA y Descuentos incluidos)</span></p>
          <button class="btn btn-dark btn-lg px-5 rounded-pill mt-2" onclick="openSelectedPaymentModal()">Completar Orden de Compra 🛍️</button>
        </div>
      </div>
    </section>
  </main>

  <footer class="bg-dark text-white py-4 mt-5 text-center">
    <div class="container">
      <img src="/static/Logo blanco y negro.jpg" alt="LuxPet Logo Blanco y Negro" style="height: 40px; width: auto;" class="mb-2 rounded">
      <p class="mb-1 brand-font fs-4">LuxPet Boutique</p>
      <p class="text-muted small mb-0">© 2026 LuxPet. Todos los derechos reservados.</p>
    </div>
  </footer>
</div>

<div class="modal fade" id="cartModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered modal-lg">
    <div class="modal-content rounded-4 border-0 p-3">
      <div class="modal-header border-bottom">
        <h5 class="modal-title brand-font fw-bold">🛒 Resumen de tu Carrito</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
      </div>
      <div class="modal-body py-4">
        <div id="cartModalList"></div>
      </div>
      <div class="modal-footer border-top d-flex justify-content-between">
        <div>
          <span class="text-muted small">Total del Pedido:</span>
          <strong class="fs-5 d-block text-dark" id="cartModalTotal">$0 COP</strong>
        </div>
        <div class="d-flex gap-2">
          <button type="button" class="btn btn-outline-secondary rounded-pill" data-bs-dismiss="modal">Seguir Comprando</button>
          <button type="button" class="btn btn-gold rounded-pill" onclick="goToCheckout()">Proceder al Pago 💳</button>
        </div>
      </div>
    </div>
  </div>
</div>

<div class="modal fade" id="clientHistoryModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered modal-lg">
    <div class="modal-content rounded-4 border-0 p-4">
      <div class="modal-header border-bottom">
        <h5 class="modal-title brand-font fw-bold">📦 Mi Historial de Pedidos</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
      </div>
      <div class="modal-body py-4" id="clientHistoryContainer">
        <p class="text-muted text-center">Cargando tus compras...</p>
      </div>
      <div class="modal-footer border-top-0">
        <button type="button" class="btn btn-secondary rounded-pill" data-bs-dismiss="modal">Cerrar</button>
      </div>
    </div>
  </div>
</div>

<div class="modal fade" id="paymentDataModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content rounded-4 border-0 p-4">
      <div class="modal-header border-bottom-0 pb-0">
        <h5 class="modal-title brand-font fw-bold" id="paymentModalTitle">💳 Datos de Pago</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
      </div>
      <div class="modal-body py-3" id="paymentDetailsContainer"></div>
      <div class="modal-footer border-top-0 pt-0">
        <button type="button" class="btn btn-outline-secondary rounded-pill" data-bs-dismiss="modal">Cancelar</button>
        <button type="button" class="btn btn-gold rounded-pill px-4" onclick="processMockPayment()">Confirmar y Pagar 🛍️</button>
      </div>
    </div>
  </div>
</div>

<script>
let token = localStorage.getItem('luxpet_token'), mode = 'login', colorMap = {}, prices = {}, discounts = {}, inventory = {}, productImages = {}, petImages = {}, currentUser = null;
let selectedMethod = 'Tarjeta de Crédito';
let userCartItems = [];
let appliedCouponCode = null;
let couponDiscountPct = 0;
const $ = id => document.getElementById(id);

function mostrarMetodoPago(scroll = true) {
  const seccionPago = $('checkout');
  if (seccionPago) {
    seccionPago.style.display = 'block';
    if (scroll) seccionPago.scrollIntoView({ behavior: 'smooth' });
  }
}

function notify(message, good=false) { 
  const alertEl = $('alert');
  if (alertEl) {
    alertEl.innerHTML = `<div class="alert ${good?'alert-success':'alert-danger'} shadow-lg border-0 rounded-4 px-4 py-3">${message}</div>`; 
    setTimeout(()=> alertEl.innerHTML='', 4000); 
  }
}

function barkDog() {
  notify('🐾 ¡Guau! Tu mascota está feliz con tus elecciones de diseño.', true);
}

function selectPay(el, method) {
  document.querySelectorAll('.pay-card').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  selectedMethod = method;
  openSelectedPaymentModal();
}

function openSelectedPaymentModal() {
  renderPaymentForm();
  if ($('paymentModalTitle'))$('paymentModalTitle').textContent = `💳 ${selectedMethod}`;
  const modalEl = $('paymentDataModal');
  if (modalEl) {
    let modal = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
    modal.show();
  }
}

function renderPaymentForm() {
  const container = $('paymentDetailsContainer');
  if (!container) return;

  if (selectedMethod === 'Tarjeta de Crédito') {
    container.innerHTML = `
      <div class="row g-3">
        <div class="col-12"><label class="form-label small fw-semibold">Número de la tarjeta</label><input type="text" class="form-control" placeholder="4532 •••• •••• 8920"></div>
        <div class="col-md-6"><label class="form-label small fw-semibold">Expiración</label><input type="text" class="form-control" placeholder="MM/AA"></div>
        <div class="col-md-6"><label class="form-label small fw-semibold">CVV</label><input type="password" class="form-control" placeholder="123" maxlength="4"></div>
      </div>
    `;
  } else {
    container.innerHTML = `<p class="text-muted small">Completa la transacción autorizando desde tu cuenta preferida de ${selectedMethod}.</p>`;
  }
}

async function applyCoupon() {
  const code = $('couponInput')?.value.trim();
  if (!code) return notify('Ingresa un código de cupón.');
  try {
    const res = await api('/api/coupons/validate', {
      method: 'POST',
      body: JSON.stringify({ code })
    });
    couponDiscountPct = res.discount_percentage;
    appliedCouponCode = code;
    if ($('couponFeedback'))$('couponFeedback').textContent = res.message;
    notify(res.message, true);
    if ($('checkoutTotalAmount'))$('checkoutTotalAmount').textContent = formatCOP(calculateCartTotal());
  } catch (err) {
    notify(err.message);
  }
}

async function processMockPayment() {
  if (!token) return notify('Por favor inicia sesión primero.');
  if (userCartItems.length === 0) return notify('El carrito está vacío.');

  const dataModalEl = $('paymentDataModal');
  if (dataModalEl) (bootstrap.Modal.getInstance(dataModalEl) || new bootstrap.Modal(dataModalEl)).hide();

  const totalAmount = calculateCartTotal();
  try {
    await api('/api/orders', {
      method: 'POST',
      body: JSON.stringify({ payment_method: selectedMethod, total_amount: totalAmount, coupon_code: appliedCouponCode })
    });
    notify(`🎉 ¡Pago de ${formatCOP(totalAmount)} registrado con éxito!`, true);
    appliedCouponCode = null;
    couponDiscountPct = 0;
    await loadDesigns();
  } catch (err) {
    notify(err.message);
  }
}

function setMode(next, button) { 
  mode = next; 
  document.querySelectorAll('#loginScreen .btn-group button').forEach(b => b.classList.remove('active')); 
  button.classList.add('active'); 
  if ($('nameWrap'))$('nameWrap').classList.toggle('d-none', next === 'login'); 
  if ($('authButton'))$('authButton').textContent = next === 'login' ? 'Entrar a mi cuenta' : 'Crear mi cuenta'; 
}

async function api(url, options={}) { 
  const headers = {'Content-Type': 'application/json', ...(options.headers || {})}; 
  if (token) headers.Authorization = `Bearer ${token}`; 
  const response = await fetch(url, {...options, headers}); 
  const data = await response.json(); 
  if (!response.ok) throw new Error(data.detail || 'Ha ocurrido un error'); 
  return data; 
}

function getFinalProductPrice(accessoryType) {
  const basePrice = prices[accessoryType] || 45000;
  const discountPct = discounts[accessoryType] || 0;
  return basePrice * (1 - discountPct / 100);
}

function updatePreview() {
  const petName = $('pet_name')?.value.trim() || 'Mascota';
  const petType = $('pet_type')?.value || 'Perro';
  const engraving = $('engraving')?.value.trim() || '';
  const color = $('color')?.value || 'Rosa empolvado';
  const size = $('size')?.value || 'M';
  const type = $('accessory_type')?.value || 'Collar de Cuero';

  if ($('prevPetName'))$('prevPetName').textContent = petName;
  if ($('prevEngraving'))$('prevEngraving').textContent = engraving;
  if ($('lblSize'))$('lblSize').textContent = size;
  if ($('lblColor'))$('lblColor').textContent = color;
  if ($('lblPetType'))$('lblPetType').textContent = petType;
  
  const finalP = getFinalProductPrice(type);
  const disc = discounts[type] || 0;
  if ($('lblPrice')) {$('lblPrice').innerHTML = disc > 0 ? `<span class="text-decoration-line-through text-muted small">${formatCOP(prices[type] || 45000)}</span> <span class="text-success">${formatCOP(finalP)}</span>` : formatCOP(finalP);
  }
  if ($('badgeDiscountPreview')) {$('badgeDiscountPreview').textContent = disc > 0 ? `🔥 ¡${disc}% Descuento Hoy!` : '✨ Alta Calidad';
  }

  if (petImages && petImages[petType] && $('prevPetImg'))$('prevPetImg').src = petImages[petType];
  if (color && colorMap[color] && $('prevStrap'))$('prevStrap').style.backgroundColor = colorMap[color];
}

function handleSearchAutocomplete(query) {
  const q = query.toLowerCase().trim();
  const box = $('searchSuggestions');
  if (!box) return;

  if (q.length === 0) {
    box.style.display = 'none';
    box.innerHTML = '';
    filterCatalogHome('');
    return;
  }

  const allAcc = Object.keys(prices);
  const matches = allAcc.filter(acc => acc.toLowerCase().includes(q));

  if (matches.length > 0) {
    box.style.display = 'block';
    box.innerHTML = matches.map(m => `
      <div class="search-suggestion-item" onclick="selectSearchSuggestion('${m}')">
        🔍 <strong>${m}</strong> <span class="text-muted small">(${formatCOP(getFinalProductPrice(m))})</span>
      </div>
    `).join('');
  } else {
    box.style.display = 'block';
    box.innerHTML = `<div class="search-suggestion-item text-muted">No se encontraron resultados para "${query}"</div>`;
  }

  filterCatalogHome(q);
}

function selectSearchSuggestion(accName) {
  const input = $('homeSearchInput');
  if (input) input.value = accName;
  const box = $('searchSuggestions');
  if (box) box.style.display = 'none';
  selectAccessoryFromCatalog(accName);
}

function filterCatalogHome(query) {
  const q = query.toLowerCase();
  const selectAcc = $('accessory_type');
  if (selectAcc) {
    const options = selectAcc.options;
    for (let i = 0; i < options.length; i++) {
      const text = options[i].text.toLowerCase();
      options[i].style.display = text.includes(q) || q === '' ? '' : 'none';
    }
  }

  const cardsContainer = $('clientCatalogCards');
  if (cardsContainer) {
    const cards = cardsContainer.getElementsByClassName('client-catalog-item');
    for (let card of cards) {
      const title = card.getAttribute('data-name').toLowerCase();
      card.style.display = title.includes(q) || q === '' ? '' : 'none';
    }
  }
}

async function loadCatalog() { 
  try {
    const data = await api('/api/catalog'); 
    colorMap = data.color_map || {};
    prices = data.prices || {};
    discounts = data.discounts || {};
    inventory = data.inventory || {};
    productImages = data.product_images || {};
    petImages = data.pet_images || {};
    
    if (data.store_status === 'closed') {
      notify('⚠️ Aviso: La tienda se encuentra cerrada temporalmente por el Dueño.');
    }
    
    [['accessory_type', data.accessory_types], ['pet_type', data.pet_types], ['color', data.colors], ['size', data.sizes]].forEach(([id, items]) => {
      const selectEl = $(id);
      if (selectEl && items) {
        selectEl.innerHTML = '<option value="">Seleccionar...</option>';
        items.forEach(item => {
          let labelText = item;
          if (id === 'accessory_type' && discounts[item] && discounts[item] > 0) {
            labelText += ` (🔥 ${discounts[item]}% OFF)`;
          }
          selectEl.insertAdjacentHTML('beforeend', `<option value="${item}">${labelText}</option>`);
        });
      }
    });

    const cardsContainer = $('clientCatalogCards');
    if (cardsContainer && data.accessory_types) {
      cardsContainer.innerHTML = data.accessory_types.map(acc => {
        const img = productImages[acc] || '/static/Logo principal.jpg';
        const baseP = prices[acc] || 45000;
        const disc = discounts[acc] || 0;
        const finalP = getFinalProductPrice(acc);

        return `
          <div class="col-md-4 client-catalog-item" data-name="${acc}">
            <div class="card card-custom p-3 h-100 shadow-sm">
              <img src="${img}" class="rounded-4 mb-3" style="height: 180px; object-fit: cover;" alt="${acc}">
              <div class="d-flex justify-content-between align-items-center mb-2">
                <h5 class="fw-bold mb-0">${acc}</h5>
                ${disc > 0 ? `<span class="badge bg-danger">${disc}% OFF</span>` : '<span class="badge bg-success">Disponible</span>'}
              </div>
              <p class="text-muted small mb-2">Accesorio de lujo hecho a mano con los mejores estándares.</p>
              <div class="d-flex justify-content-between align-items-center mt-auto pt-2 border-top">
                <div>
                  ${disc > 0 ? `<small class="text-decoration-line-through text-muted d-block">${formatCOP(baseP)}</small>` : ''}
                  <strong class="text-dark fs-5">${formatCOP(finalP)}</strong>
                </div>
                <button class="btn btn-outline-dark btn-sm rounded-pill" onclick="selectAccessoryFromCatalog('${acc}')">Diseñar ✨</button>
              </div>
            </div>
          </div>
        `;
      }).join('');
    }
  } catch (err) {
    console.error("Error catálogo:", err);
  }
}

function selectAccessoryFromCatalog(accName) {
  const sel = $('accessory_type');
  if (sel) {
    sel.value = accName;
    updatePreview();
    $('designer').scrollIntoView({ behavior: 'smooth' });
  }
}

['pet_name', 'pet_type', 'engraving', 'color', 'size', 'accessory_type'].forEach(id => {
  if ($(id)) {
    $(id).addEventListener('input', updatePreview);$(id).addEventListener('change', updatePreview);
  }
});

if ($('authForm')) {$('authForm').onsubmit = async e => {
    e.preventDefault(); 
    try { 
      const payload = { email: $('email').value, password:$('password').value };
      if (mode === 'register') payload.name = $('name').value;

      const data = await api(`/api/auth/${mode === 'login' ? 'login' : 'register'}`, {
        method: 'POST',
        body: JSON.stringify(payload)
      });
      
      token = data.access_token; 
      currentUser = data.user;
      localStorage.setItem('luxpet_token', token); 
      notify(data.message, true); 
      showDashboard();
      await loadDesigns(); 
    } catch(error) { 
      notify(error.message); 
    } 
  };
}

function logout() {
  token = null;
  currentUser = null;
  localStorage.removeItem('luxpet_token');
  location.reload();
}

function showDashboard() {
  if ($('loginScreen'))$('loginScreen').classList.add('d-none');
  
  // Mostrar la barra de búsqueda ahora que el usuario inició sesión
  if ($('clientSearchWrapper')) {
    $('clientSearchWrapper').classList.remove('d-none');$('clientSearchWrapper').classList.add('d-md-flex');
  }
  
  if (currentUser && (currentUser.email === 'julianjuanm@gmail.com' || currentUser.role === 'admin')) {
    if ($('mainContent'))$('mainContent').classList.add('d-none');
    if ($('btnSidebarToggle'))$('btnSidebarToggle').classList.remove('d-none');
    if ($('userNavStatus')) {$('userNavStatus').innerHTML = `
        <div class="d-flex align-items-center gap-2 border-start ps-3">
          <span class="small fw-semibold text-danger">👑 Panel Exclusivo del Dueño (Juan Manuel)</span>
          <button onclick="logout()" class="btn btn-sm btn-outline-danger rounded-pill ms-2">Salir</button>
        </div>
      `;
    }
    renderAdminDashboard();
    return;
  }

  if ($('mainContent'))$('mainContent').classList.remove('d-none');
  if ($('btnSidebarToggle'))$('btnSidebarToggle').classList.remove('d-none');

  if ($('userNavStatus')) {$('userNavStatus').innerHTML = `
      <button class="btn btn-sm btn-outline-secondary rounded-pill me-2" onclick="openClientHistoryModal()">📦 Mis Pedidos</button>
      <div class="cart-btn-nav" onclick="openCartModal()">
        🛒 <span class="d-none d-md-inline fw-semibold ms-1">Carrito</span>
        <span class="cart-badge" id="navCartCount">${userCartItems.length}</span>
      </div>
      <div class="d-flex align-items-center gap-2 border-start ps-3">
        <span class="small fw-semibold text-dark">👤 ${currentUser?.name || 'Cliente'}</span>
        <button onclick="logout()" class="btn btn-sm btn-outline-danger rounded-pill ms-1 d-none d-md-inline">Salir</button>
      </div>
    `;
  }
  if ($('sbUserName'))$('sbUserName').textContent = currentUser?.name || 'Cliente LuxPet';
  if ($('sbUserEmail'))$('sbUserEmail').textContent = currentUser?.email || '';
}

if ($('designForm')) {$('designForm').onsubmit = async e => {
    e.preventDefault(); 
    try { 
      await api('/api/customizations', {
        method: 'POST',
        body: JSON.stringify({
          accessory_type: $('accessory_type').value,
          pet_type: $('pet_type').value,
          pet_name: $('pet_name').value,
          color: $('color').value,
          size: $('size').value,
          engraving: $('engraving').value
        })
      }); 
      notify('¡Tu diseño personalizado se ha agregado al carrito! ✨', true); 
      mostrarMetodoPago(true);
      e.target.reset(); 
      updatePreview();
      await loadDesigns(); 
    } catch(error) { notify(error.message); } 
  };
}

async function removeFromCart(itemId) {
  try {
    const res = await api(`/api/customizations/${itemId}`, { method: 'DELETE' });
    notify(res.message || 'Producto eliminado del carrito.', true);
    await loadDesigns();
  } catch (error) { notify(error.message); }
}

function calculateCartTotal() {
  const subtotal = userCartItems.reduce((acc, item) => acc + getFinalProductPrice(item.accessory_type), 0);
  if (couponDiscountPct > 0) {
    return subtotal * (1 - couponDiscountPct / 100);
  }
  return subtotal;
}

function formatCOP(amount) {
  return new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(amount);
}

function openCartModal() {
  const modalList = $('cartModalList');
  const total = calculateCartTotal();
  if (modalList) {
    modalList.innerHTML = userCartItems.length === 0 ? '<p class="text-center py-4 text-muted">Tu carrito está vacío.</p>' :
      userCartItems.map(item => `
        <div class="d-flex align-items-center justify-content-between p-3 mb-2 bg-light rounded-3 border">
          <div><h6 class="mb-0 fw-bold">${item.accessory_type} - ${item.pet_name}</h6><small class="text-muted">${item.color} | Talla ${item.size} | Precio: ${formatCOP(getFinalProductPrice(item.accessory_type))}</small></div>
          <button class="btn btn-sm btn-outline-danger" onclick="removeFromCart(${item.id})">❌</button>
        </div>
      `).join('');
  }
  if ($('cartModalTotal'))$('cartModalTotal').textContent = formatCOP(total);
  const cartModalEl = $('cartModal');
  if (cartModalEl) (bootstrap.Modal.getInstance(cartModalEl) || new bootstrap.Modal(cartModalEl)).show();
}

async function openClientHistoryModal() {
  const container = $('clientHistoryContainer');
  if (!container) return;
  container.innerHTML = '<p class="text-center py-3 text-muted">Cargando tus pedidos...</p>';
  const modalEl = $('clientHistoryModal');
  if (modalEl) (bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl)).show();

  try {
    const profile = await api('/api/user/me');
    const orders = profile.orders || [];
    container.innerHTML = orders.length === 0 ? '<p class="text-center py-4 text-muted">Aún no tienes compras registradas.</p>' :
      `
      <div class="table-responsive">
        <table class="table table-hover align-middle small">
          <thead class="table-dark">
            <tr><th>ID</th><th>Pago</th><th>Total</th><th>Estado</th><th>Fecha</th></tr>
          </thead>
          <tbody>
            ${orders.map(o => `
              <tr>
                <td>#${o.id}</td>
                <td>${o.payment_method}</td>
                <td><strong>${formatCOP(o.total_amount)}</strong></td>
                <td><span class="badge bg-success">${o.status}</span></td>
                <td>${o.created_at}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
      `;
  } catch (err) {
    container.innerHTML = `<p class="text-danger text-center">Error al cargar historial: ${err.message}</p>`;
  }
}

function goToCheckout() {
  const modalEl = $('cartModal');
  if (modalEl) (bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl)).hide();
  mostrarMetodoPago(true);
}

async function loadDesigns() { 
  if(!token) return; 
  try { 
    userCartItems = await api('/api/customizations'); 
    if ($('navCartCount'))$('navCartCount').textContent = userCartItems.length;
    if ($('checkoutTotalAmount'))$('checkoutTotalAmount').textContent = formatCOP(calculateCartTotal());
  } catch (err) { 
    localStorage.removeItem('luxpet_token'); 
    token = null; 
  } 
}

(async function init() {
  await loadCatalog();
  if (token) {
    try {
      currentUser = await api('/api/user/me');
      await loadDesigns();
      showDashboard();
    } catch {
      localStorage.removeItem('luxpet_token');
      token = null;
    }
  }
})();
</script>
</body>
</html>
"""

ADMIN_SCRIPT_EXTENSION = """
<script>
(function() {
  window.refreshAdminDashboard = async function(period = 'all') {
    notify('Sincronizando panel del dueño...', true);
    await renderAdminDashboard(period);
  };

  window.toggleStoreStatusByOwner = async function() {
    try {
      const res = await api('/api/admin/store/toggle', { method: 'PUT' });
      notify(res.message, true);
      renderAdminDashboard();
    } catch(err) {
      notify(err.message);
    }
  };

  window.renderAdminDashboard = async function(period = 'all') {
    try {
      const data = await api(`/api/admin/metrics?filter_period=${period}`);
      let adminSection = document.getElementById('adminSection');
      if (!adminSection) {
        adminSection = document.createElement('section');
        adminSection.id = 'adminSection';
        adminSection.className = 'container py-4 my-4';
        document.body.appendChild(adminSection);
      }

      let stockAlertsHTML = '';
      if (data.inventory && data.inventory.length > 0) {
        const lowStockItems = data.inventory.filter(i => i.stock <= i.min_threshold);
        if (lowStockItems.length > 0) {
          stockAlertsHTML = `
            <div class="alert alert-danger shadow-sm rounded-4 mb-4 p-3 border-0">
              <h5 class="fw-bold mb-1">⚠️ Alerta Crítica de Inventario / Stock Bajo para el Dueño:</h5>
              <p class="small mb-2">Los siguientes productos están por agotarse o llegaron al límite mínimo en la bodega:</p>
              <ul class="mb-0 small">
                ${lowStockItems.map(i => `<li><strong>${i.product_name}</strong> - Solo quedan <strong>${i.stock} unidades</strong> disponibles (Mínimo: ${i.min_threshold}).</li>`).join('')}
              </ul>
            </div>
          `;
        }
      }

      const storeIsOpen = data.store_status === 'open';

      adminSection.innerHTML = `
        <div class="card card-custom p-4 border-warning mb-4 shadow-sm" style="background: #fffdf9;">
          <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
            <div>
              <span class="badge bg-warning text-dark px-3 py-2 rounded-pill fw-bold">PANEL EXCLUSIVO DEL DUEÑO (JUAN MANUEL)</span>
              <h2 class="h3 fw-bold mt-2">Control Maestro Boutique 👑</h2>
            </div>
            <div class="d-flex gap-2 flex-wrap align-items-center">
              <button onclick="toggleStoreStatusByOwner()" class="btn ${storeIsOpen ? 'btn-outline-danger' : 'btn-outline-success'} rounded-pill btn-sm fw-bold">
                ${storeIsOpen ? '🔴 Cerrar Tienda Temporalmente' : '🟢 Abrir Tienda'}
              </button>
              <select class="form-select form-select-sm" style="width: auto;" onchange="renderAdminDashboard(this.value)">
                <option value="all" ${period==='all'?'selected':''}>📅 Todo el tiempo</option>
                <option value="today" ${period==='today'?'selected':''}>📅 Hoy</option>
                <option value="week" ${period==='week'?'selected':''}>📅 Última semana</option>
                <option value="month" ${period==='month'?'selected':''}>📅 Último mes</option>
              </select>
              <button onclick="refreshAdminDashboard('${period}')" class="btn btn-outline-warning rounded-pill btn-sm fw-bold">🔄 Sincronizar</button>
              <button onclick="downloadCSVReport()" class="btn btn-outline-dark rounded-pill btn-sm fw-bold">📥 Exportar Reporte CSV</button>
              <button onclick="downloadUsersCSV()" class="btn btn-gold rounded-pill btn-sm fw-bold">📧 Descargar Correos (CSV)</button>
            </div>
          </div>

          ${stockAlertsHTML}

          <div class="row g-3 mb-4 text-center">
            <div class="col-md-4">
              <div class="p-3 bg-white rounded-4 border shadow-sm">
                <small class="text-muted d-block uppercase fw-bold">Clientes Registrados (Correos Guardados)</small>
                <strong class="fs-2 text-dark">${data.metrics.users_count}</strong>
              </div>
            </div>
            <div class="col-md-4">
              <div class="p-3 bg-white rounded-4 border shadow-sm">
                <small class="text-muted d-block uppercase fw-bold">Ventas Totales (Pedidos)</small>
                <strong class="fs-2 text-dark">${data.metrics.orders_count}</strong>
              </div>
            </div>
            <div class="col-md-4">
              <div class="p-3 bg-white rounded-4 border shadow-sm">
                <small class="text-muted d-block uppercase fw-bold">Recaudación Neta Total</small>
                <strong class="fs-2 text-success">${formatCOP(data.metrics.total_revenue)}</strong>
              </div>
            </div>
          </div>

          <ul class="nav nav-pills mb-3" id="adminTabs" role="tablist">
            <li class="nav-item">
              <button class="nav-link active rounded-pill px-4" data-bs-toggle="pill" data-bs-target="#tab-orders" type="button">Historial de Órdenes & Pedidos</button>
            </li>
            <li class="nav-item">
              <button class="nav-link rounded-pill px-4" data-bs-toggle="pill" data-bs-target="#tab-sales" type="button">Ventas Diarias & Estadísticas</button>
            </li>
            <li class="nav-item">
              <button class="nav-link rounded-pill px-4" data-bs-toggle="pill" data-bs-target="#tab-inventory" type="button">Control de Inventario & Bodega</button>
            </li>
            <li class="nav-item">
              <button class="nav-link rounded-pill px-4" data-bs-toggle="pill" data-bs-target="#tab-users" type="button">Gestión de Usuarios & Correos Guardados</button>
            </li>
          </ul>

          <div class="tab-content" id="adminTabContent">
            
            <!-- Órdenes -->
            <div class="tab-pane fade show active" id="tab-orders">
              <div class="table-responsive">
                <table class="table table-hover align-middle small">
                  <thead class="table-dark">
                    <tr>
                      <th>ID</th>
                      <th>Cliente</th>
                      <th>Método Pago</th>
                      <th>Monto</th>
                      <th>Estado de la Orden</th>
                      <th>Fecha</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${data.orders.length ? data.orders.map(o => `
                      <tr>
                        <td>#${o.id}</td>
                        <td><strong>${o.user_name}</strong><br><small class="text-muted">${o.email}</small></td>
                        <td>${o.payment_method}</td>
                        <td><strong>${formatCOP(o.total_amount)}</strong></td>
                        <td>
                          <select class="form-select form-select-sm" onchange="changeOrderStatus(${o.id}, this.value)">
                            <option value="Completado" ${o.status==='Completado'?'selected':''}>Completado</option>
                            <option value="En Producción" ${o.status==='En Producción'?'selected':''}>En Producción</option>
                            <option value="Enviado" ${o.status==='Enviado'?'selected':''}>Enviado</option>
                            <option value="Cancelado" ${o.status==='Cancelado'?'selected':''}>Cancelado</option>
                          </select>
                        </td>
                        <td>${o.created_at}</td>
                      </tr>
                    `).join('') : '<tr><td colspan="6" class="text-center py-3 text-muted">No hay órdenes registradas para este periodo.</td></tr>'}
                  </tbody>
                </table>
              </div>
            </div>

            <!-- Ventas Diarias & Estadísticas -->
            <div class="tab-pane fade" id="tab-sales">
              <div class="row g-4">
                <div class="col-md-6">
                  <h5 class="fw-bold mb-3">📈 Ventas Diarias Registradas</h5>
                  <div class="table-responsive">
                    <table class="table table-bordered bg-white small">
                      <thead class="table-secondary">
                        <tr><th>Fecha</th><th>Pedidos</th><th>Recaudación Diaria</th></tr>
                      </thead>
                      <tbody>
                        ${data.daily_sales.length ? data.daily_sales.map(ds => `
                          <tr>
                            <td>${ds.sale_date}</td>
                            <td>${ds.orders_count}</td>
                            <td><strong>${formatCOP(ds.daily_revenue)}</strong></td>
                          </tr>
                        `).join('') : '<tr><td colspan="3" class="text-center text-muted">Sin ventas registradas.</td></tr>'}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div class="col-md-6">
                  <h5 class="fw-bold mb-3">🏆 Productos Más Vendidos / Diseñados</h5>
                  <div class="table-responsive">
                    <table class="table table-bordered bg-white small">
                      <thead class="table-secondary">
                        <tr><th>Producto / Accesorio</th><th>Cantidad Solicitada</th></tr>
                      </thead>
                      <tbody>
                        ${data.top_products.length ? data.top_products.map(tp => `
                          <tr>
                            <td>${tp.product_name}</td>
                            <td><span class="badge bg-success">${tp.total_sold} unidades</span></td>
                          </tr>
                        `).join('') : '<tr><td colspan="2" class="text-center text-muted">Sin estadísticas aún.</td></tr>'}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>

            <!-- Control de Inventario & Bodega -->
            <div class="tab-pane fade" id="tab-inventory">
              <h5 class="fw-bold mb-3">📦 Disponibilidad en Bodega & Alertas de Stock</h5>
              <div class="table-responsive">
                <table class="table table-hover align-middle small bg-white">
                  <thead class="table-dark">
                    <tr><th>Producto</th><th>Stock Actual</th><th>Umbral Mínimo</th><th>Estado</th><th>Acción / Reabastecer</th></tr>
                  </thead>
                  <tbody>
                    ${data.inventory.map(inv => `
                      <tr>
                        <td><strong>${inv.product_name}</strong></td>
                        <td><span class="badge ${inv.stock <= inv.min_threshold ? 'bg-danger' : 'bg-success'} fs-6">${inv.stock}</span></td>
                        <td>${inv.min_threshold}</td>
                        <td>${inv.stock <= inv.min_threshold ? '⚠️ Stock Bajo (Agotándose)' : '✅ Disponible'}</td>
                        <td>
                          <div class="input-group input-group-sm" style="max-width: 180px;">
                            <input type="number" class="form-control" id="inv_input_${inv.id}" value="${inv.stock}" min="0">
                            <button class="btn btn-outline-dark" onclick="updateInventoryStock('${inv.product_name}',${inv.id})">Guardar</button>
                          </div>
                        </td>
                      </tr>
                    `).join('')}
                  </tbody>
                </table>
              </div>
            </div>

            <!-- Usuarios & Correos Guardados -->
            <div class="tab-pane fade" id="tab-users">
              <div class="d-flex justify-content-between align-items-center mb-3">
                <h5 class="fw-bold mb-0">👥 Lista de Correos Registrados en la Base de Datos</h5>
                <button onclick="downloadUsersCSV()" class="btn btn-sm btn-gold rounded-pill fw-bold">📥 Descargar Correos en Excel/CSV</button>
              </div>
              <div class="table-responsive">
                <table class="table table-hover align-middle small">
                  <thead class="table-dark">
                    <tr>
                      <th>ID</th>
                      <th>Nombre</th>
                      <th>Correo Electrónico (Email)</th>
                      <th>Rol</th>
                      <th>Fecha Registro</th>
                      <th>Acción</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${data.users.map(u => `
                      <tr>
                        <td>#${u.id}</td>
                        <td><strong>${u.name}</strong></td>
                        <td><span class="badge bg-light text-dark border font-monospace fs-6">${u.email}</span></td>
                        <td><span class="badge ${u.role==='admin'?'bg-danger':'bg-secondary'}">${u.role}</span></td>
                        <td>${u.created_at}</td>
                        <td>
                          ${u.email !== 'julianjuanm@gmail.com' ? `<button class="btn btn-sm btn-outline-danger border-0" onclick="deleteUserByAdmin(${u.id})">🗑️ Eliminar</button>` : '<span class="text-muted">Propietario Principal</span>'}
                        </td>
                      </tr>
                    `).join('')}
                  </tbody>
                </table>
              </div>
            </div>

          </div>
        </div>
      `;
    } catch(err) {
      console.error('Error al cargar panel de administración:', err);
    }
  };

  window.updateInventoryStock = async function(productName, id) {
    const inputEl = document.getElementById(`inv_input_${id}`);
    if (!inputEl) return;
    const newStock = parseInt(inputEl.value);
    try {
      const res = await api('/api/admin/inventory', {
        method: 'PUT',
        body: JSON.stringify({ product_name: productName, stock: newStock })
      });
      notify(res.message, true);
      renderAdminDashboard();
    } catch(err) {
      notify(err.message);
    }
  };

  window.changeOrderStatus = async function(orderId, newStatus) {
    try {
      const res = await api(`/api/admin/orders/${orderId}/status`, {
        method: 'PUT',
        body: JSON.stringify({ status: newStatus })
      });
      notify(res.message, true);
    } catch(err) {
      notify(err.message);
    }
  };

  window.deleteUserByAdmin = async function(userId) {
    if (!confirm('¿Estás seguro de que deseas eliminar este usuario y todos sus registros asociados?')) return;
    try {
      const res = await api(`/api/admin/users/${userId}`, { method: 'DELETE' });
      notify(res.message, true);
      renderAdminDashboard();
    } catch(err) {
      notify(err.message);
    }
  };

  window.downloadCSVReport = function() {
    window.open(`/api/admin/export/orders?token=${token}`, '_blank');
  };

  window.downloadUsersCSV = function() {
    window.open(`/api/admin/export/users?token=${token}`, '_blank');
  };
})();
</script>
"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home_admin_extended() -> str:
    return HOME_PAGE.replace("</body>", f"{ADMIN_SCRIPT_EXTENSION}\n</body>")
