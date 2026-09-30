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
from io import StringIO
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse
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
    version="4.2.0",
)

if not STATIC_DIR.exists():
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

bearer_scheme = HTTPBearer(auto_error=False)

SIZES = ("XXS", "XS", "S", "M", "L", "XL", "XXL")
ACCESSORY_TYPES = ("Placa Grabada", "Collar de Cuero", "Arnés Confort")
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
    "Arnés Confort": 129900
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


class OrderStatusUpdate(BaseModel):
    status: str


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
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


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
    user_id = decode_token(credentials.credentials)
    with get_connection() as connection:
        user = connection.execute(
            "SELECT id, name, email, role, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    if user is None:
        raise HTTPException(status_code=401, detail="Usuario no encontrado.")
    return user


@app.get("/api/catalog")
def catalog() -> dict[str, Any]:
    return {
        "accessory_types": ACCESSORY_TYPES, 
        "colors": COLORS, 
        "sizes": SIZES,
        "pet_types": PET_TYPES,
        "pet_images": PET_IMAGES,
        "color_map": COLOR_MAP,
        "prices": PRICES
    }


@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
def register(user: UserRegister) -> dict[str, Any]:
    with get_connection() as connection:
        try:
            cursor = connection.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (user.name.strip(), user.email.lower(), hash_password(user.password)),
            )
            user_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="El correo ya está registrado.")
    return {
        "message": "¡Cuenta creada exitosamente!",
        "access_token": encode_token(user_id),
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
    return {
        "message": "¡Autenticación completada!",
        "access_token": encode_token(stored_user["id"]),
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
    if customization.accessory_type not in ACCESSORY_TYPES:
        raise HTTPException(status_code=422, detail="Tipo de accesorio no válido.")
    if customization.pet_type not in PET_TYPES:
        raise HTTPException(status_code=422, detail="Tipo de mascota no válido.")
    if customization.color not in COLORS:
        raise HTTPException(status_code=422, detail="Color no disponible.")
    if customization.size not in SIZES:
        raise HTTPException(status_code=422, detail="Talla no disponible.")
    with get_connection() as connection:
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
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "created_at": user["created_at"],
    }


@app.put("/api/customizations/{customization_id}")
def update_customization(
    customization_id: int,
    customization: CustomizationUpdate,
    user: sqlite3.Row = Depends(current_user),
) -> dict[str, Any]:
    if customization.accessory_type not in ACCESSORY_TYPES:
        raise HTTPException(status_code=422, detail="Tipo de accesorio no válido.")
    if customization.pet_type not in PET_TYPES:
        raise HTTPException(status_code=422, detail="Tipo de mascota no válido.")
    if customization.color not in COLORS:
        raise HTTPException(status_code=422, detail="Color no disponible.")
    if customization.size not in SIZES:
        raise HTTPException(status_code=422, detail="Talla no disponible.")

    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE customizations
            SET accessory_type = ?, pet_name = ?, pet_type = ?, color = ?, size = ?, engraving = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                customization.accessory_type,
                customization.pet_name.strip(),
                customization.pet_type,
                customization.color,
                customization.size,
                customization.engraving.strip(),
                customization_id,
                user["id"],
            ),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Diseño no encontrado en tu carrito.")

        updated = connection.execute(
            "SELECT * FROM customizations WHERE id = ?", (customization_id,)
        ).fetchone()

    return {"message": "¡Diseño actualizado exitosamente!", "customization": dict(updated)}


@app.post("/api/orders", status_code=status.HTTP_201_CREATED)
def create_order(
    order_data: OrderCreate,
    user: sqlite3.Row = Depends(current_user),
) -> dict[str, Any]:
    with get_connection() as connection:
        cart_items = connection.execute(
            "SELECT * FROM customizations WHERE user_id = ?", (user["id"],)
        ).fetchall()

        if not cart_items:
            raise HTTPException(
                status_code=400, detail="No puedes procesar una orden con el carrito vacío."
            )

        cursor = connection.execute(
            """
            INSERT INTO orders (user_id, payment_method, total_amount)
            VALUES (?, ?, ?)
            """,
            (user["id"], order_data.payment_method, order_data.total_amount),
        )
        order_id = cursor.lastrowid
        connection.execute("DELETE FROM customizations WHERE user_id = ?", (user["id"],))

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
# FUNCIONES EXCLUSIVAS PARA ADMINISTRADOR
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

        admin_user = conn.execute("SELECT id FROM users WHERE email = ?", (ADMIN_EMAIL,)).fetchone()
        if not admin_user:
            conn.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'admin')",
                ("Administrador LuxPet", ADMIN_EMAIL, hash_password(ADMIN_PASSWORD))
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
            detail="Acceso restringido para el Administrador Principal."
        )
    return user


@app.get("/api/admin/metrics")
def get_admin_metrics(admin: sqlite3.Row = Depends(current_admin)) -> dict[str, Any]:
    with get_connection() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        total_revenue = conn.execute("SELECT COALESCE(SUM(total_amount), 0) FROM orders").fetchone()[0]
        recent_orders = conn.execute("""
            SELECT o.id, u.name as user_name, u.email, o.payment_method, o.total_amount, o.status, o.created_at
            FROM orders o JOIN users u ON o.user_id = u.id ORDER BY o.created_at DESC
        """).fetchall()
        all_users = conn.execute("SELECT id, name, email, role, created_at FROM users ORDER BY id DESC").fetchall()

    return {
        "metrics": {
            "users_count": total_users,
            "orders_count": total_orders,
            "total_revenue": total_revenue
        },
        "orders": [dict(r) for r in recent_orders],
        "users": [dict(u) for u in all_users]
    }


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
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propia cuenta de Administrador.")
    
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
    .review-card { background: rgba(255, 255, 255, 0.95); border-radius: 16px; border: 1px solid #efe3db; padding: 24px; box-shadow: 0 8px 20px rgba(0,0,0,0.03); height: 100%; }
    .gallery-img { border-radius: 16px; height: 220px; object-fit: cover; width: 100%; transition: transform 0.3s ease; }
    .gallery-card:hover .gallery-img { transform: scale(1.03); }
    #alert { position: fixed; right: 25px; top: 85px; z-index: 999; }
    .cart-btn-nav { position: relative; border-radius: 50px; background: #ffffff; border: 1px solid #ebdcd5; padding: 6px 16px; cursor: pointer; transition: all 0.2s ease; }
    .cart-btn-nav:hover { background: #fdfbf7; border-color: var(--gold); }
    .cart-badge { position: absolute; top: -6px; right: -6px; background: var(--gold-dark); color: #fff; font-size: 0.7rem; font-weight: 700; width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; }
    .sidebar-img { width: 100%; height: 120px; object-fit: cover; border-radius: 12px; }
    .cart-item-preview { width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; color: white; font-size: 0.75rem; box-shadow: 0 2px 6px rgba(0,0,0,0.15); }
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

      <div class="mb-4">
        <button class="btn btn-outline-dark w-100 rounded-pill d-flex align-items-center justify-content-center gap-2 py-2" onclick="openCartModal()" data-bs-dismiss="offcanvas">
          <span>🛒 Mi Carrito de Compras</span>
          <span class="badge bg-warning text-dark rounded-pill" id="sbCartCount">0</span>
        </button>
      </div>

      <h6 class="fw-bold text-uppercase small text-muted mb-3">Catálogo de Productos</h6>
      <div class="row g-2 mb-4">
        <div class="col-6">
          <img src="/static/Coleccion Velvet Gold.jpg" class="sidebar-img" alt="Collares Luxe">
          <span class="d-block small fw-semibold text-center mt-1">Collares Luxe</span>
        </div>
        <div class="col-6">
          <img src="/static/Placas Confort 3D.jpg" class="sidebar-img" alt="Placas Láser">
          <span class="d-block small fw-semibold text-center mt-1">Placas Láser</span>
        </div>
        <div class="col-6 mt-2">
          <img src="/static/Arnes Ergonomico.jpg" class="sidebar-img" alt="Arneses Soft">
          <span class="d-block small fw-semibold text-center mt-1">Arneses Soft</span>
        </div>
        <div class="col-6 mt-2">
          <img src="/static/Coleccion Velvet Gold.jpg" class="sidebar-img" alt="Correas Gold">
          <span class="d-block small fw-semibold text-center mt-1">Correas Gold</span>
        </div>
      </div>

      <h6 class="fw-bold text-uppercase small text-muted mb-2">Contacto & Soporte</h6>
      <div class="small text-secondary mb-3">
        <p class="mb-1">📧 julianjuanm@gmail.com</p>
        <p class="mb-1">📱 +57 314 4537607</p>
        <p class="mb-0">📍 Bogotá - Medellín - Cali - Villavicencio</p>
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
            <p class="text-muted small">Ingresa tus datos para continuar.</p>
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
          <p class="lead text-secondary mb-4 text-center text-lg-start">Diseña placas, collares y arneses de alta gama con personalización láser en tiempo real.</p>
          
          <div class="d-flex gap-3 justify-content-center justify-content-lg-start">
            <a href="#designer" class="btn btn-gold btn-lg">Diseñar Accesorio</a>
            <button onclick="mostrarMetodoPago(true)" class="btn btn-outline-dark rounded-pill btn-lg px-4">Métodos de Pago</button>
          </div>
        </div>

        <div class="col-lg-6">
          <div class="preview-card">
            <div class="d-flex justify-content-between align-items-center mb-3">
              <span class="fw-bold text-uppercase small text-muted">Vista previa 3D en vivo</span>
              <span class="badge bg-light text-dark border">Grabado láser en oro</span>
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
              <div class="col-3"><small class="text-muted d-block">Estilo</small><strong id="lblType">Collar</strong></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </header>

  <main class="container py-5">
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
              <select id="accessory_type" class="form-select" required><option value="">Seleccionar...</option></select>
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
          <h2 class="h3 fw-bold">Método de Pago</h2>
          <p class="text-muted small">Selecciona tu plataforma preferida para completar tu pedido.</p>
        </div>

        <div class="row g-3 mb-4">
          <div class="col-md-3">
            <div class="pay-card text-center" onclick="selectPay(this, 'Tarjeta de Crédito')">
              <div class="fs-2 mb-2">💳</div>
              <strong class="d-block mb-1">Tarjeta de Crédito</strong>
              <span class="text-muted small">Visa / Mastercard</span>
            </div>
          </div>
          <div class="col-md-3">
            <div class="pay-card text-center" onclick="selectPay(this, 'PayPal')">
              <div class="fs-2 mb-2">🅿️</div>
              <strong class="d-block mb-1">PayPal</strong>
              <span class="text-muted small">Pago rápido</span>
            </div>
          </div>
          <div class="col-md-3">
            <div class="pay-card text-center" onclick="selectPay(this, 'Numero de telefono')">
              <div class="fs-2 mb-2">📱</div>
              <strong class="d-block mb-1">Numero de telefono</strong>
              <span class="text-muted small">Nequi / Daviplata</span>
            </div>
          </div>
        </div>

        <div class="mt-4 p-4 bg-light rounded-4 text-center border">
          <p class="mb-2 text-muted small">Monto Total: <strong class="text-dark fs-4" id="checkoutTotalAmount">$0 COP</strong> <span class="text-muted">(IVA incluido)</span></p>
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

<div class="modal fade" id="paymentModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content rounded-4 border-0 p-4 text-center">
      <div class="modal-body">
        <div class="spinner-border text-warning mb-3" style="width: 3rem; height: 3rem;" role="status"></div>
        <h4 class="h5 font-heading">Procesando pago seguro...</h4>
        <p class="text-muted small mb-0">Conectando con el método seleccionado (<span id="modalPayMethod">Tarjeta</span>)...</p>
      </div>
    </div>
  </div>
</div>

<script>
let token = localStorage.getItem('luxpet_token'), mode = 'login', colorMap = {}, prices = {}, petImages = {}, currentUser = null;
let selectedMethod = 'Tarjeta de Crédito';
let userCartItems = [];
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
    setTimeout(()=> alertEl.innerHTML='', 3500); 
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
    container.innerHTML = `<p class="text-muted small">Completa la transacción autorizando desde tu numero de telefono O Correo electronico previamente establecido ${selectedMethod}.</p>`;
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
      body: JSON.stringify({ payment_method: selectedMethod, total_amount: totalAmount })
    });
    notify(`🎉 ¡Pago de ${formatCOP(totalAmount)} registrado con éxito!`, true);
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

function updatePreview() {
  const petName = $('pet_name')?.value.trim() || 'Mascota';
  const petType = $('pet_type')?.value || 'Perro';
  const engraving = $('engraving')?.value.trim() || '';
  const color = $('color')?.value || 'Rosa empolvado';
  const size = $('size')?.value || 'M';
  const type = $('accessory_type')?.value || 'Collar';

  if ($('prevPetName'))$('prevPetName').textContent = petName;
  if ($('prevEngraving'))$('prevEngraving').textContent = engraving;
  if ($('lblSize'))$('lblSize').textContent = size;
  if ($('lblColor'))$('lblColor').textContent = color;
  if ($('lblType'))$('lblType').textContent = type.split(' ')[0];
  if ($('lblPetType'))$('lblPetType').textContent = petType;
  if (petImages && petImages[petType] && $('prevPetImg'))$('prevPetImg').src = petImages[petType];
  if (color && colorMap[color] && $('prevStrap'))$('prevStrap').style.backgroundColor = colorMap[color];
}

async function loadCatalog() { 
  try {
    const data = await api('/api/catalog'); 
    colorMap = data.color_map || {};
    prices = data.prices || {};
    petImages = data.pet_images || {};
    
    [['accessory_type', data.accessory_types], ['pet_type', data.pet_types], ['color', data.colors], ['size', data.sizes]].forEach(([id, items]) => {
      const selectEl = $(id);
      if (selectEl && items) {
        selectEl.innerHTML = '<option value="">Seleccionar...</option>';
        items.forEach(item => selectEl.insertAdjacentHTML('beforeend', `<option>${item}</option>`));
      }
    });
  } catch (err) {
    console.error("Error catálogo:", err);
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
  if ($('mainContent'))$('mainContent').classList.remove('d-none');
  if ($('btnSidebarToggle'))$('btnSidebarToggle').classList.remove('d-none');

  if ($('userNavStatus')) {$('userNavStatus').innerHTML = `
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
  return userCartItems.reduce((acc, item) => acc + (prices[item.accessory_type] || 45000), 0);
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
          <div><h6 class="mb-0 fw-bold">${item.accessory_type} - ${item.pet_name}</h6><small class="text-muted">${item.color} | Talla ${item.size}</small></div>
          <button class="btn btn-sm btn-outline-danger" onclick="removeFromCart(${item.id})">❌</button>
        </div>
      `).join('');
  }
  if ($('cartModalTotal'))$('cartModalTotal').textContent = formatCOP(total);
  const cartModalEl = $('cartModal');
  if (cartModalEl) (bootstrap.Modal.getInstance(cartModalEl) || new bootstrap.Modal(cartModalEl)).show();
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
    if ($('sbCartCount'))$('sbCartCount').textContent = userCartItems.length;
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

# ==============================================================================
# INYECCIÓN DINO-JS EN EL CLIENTE PARA MODO ADMINISTRADOR VISTA DEDICADA
# ==============================================================================

ADMIN_SCRIPT_EXTENSION = """
<script>
(function() {
  const oldShowDashboard = window.showDashboard;
  window.showDashboard = function() {
    if (oldShowDashboard) oldShowDashboard();
    if (currentUser && (currentUser.email === 'julianjuanm@gmail.com' || currentUser.role === 'admin')) {
      renderAdminDashboard();
    }
  };

  async function renderAdminDashboard() {
    try {
      const data = await api('/api/admin/metrics');
      let adminSection = document.getElementById('adminSection');
      if (!adminSection) {
        adminSection = document.createElement('section');
        adminSection.id = 'adminSection';
        adminSection.className = 'container py-4 my-4';
        const main = document.querySelector('main');
        if (main) main.insertBefore(adminSection, main.firstChild);
      }

      adminSection.innerHTML = `
        <div class="card card-custom p-4 border-warning mb-4 shadow-sm" style="background: #fffdf9;">
          <div class="d-flex justify-content-between align-items-center mb-3">
            <div>
              <span class="badge bg-warning text-dark px-3 py-2 rounded-pill fw-bold">PANEL PRINCIPAL DE ADMINISTRACIÓN</span>
              <h2 class="h3 fw-bold mt-2">Bienvenido, Juan Manuel 👑</h2>
            </div>
            <div class="d-flex gap-2">
              <button onclick="downloadCSVReport()" class="btn btn-outline-dark rounded-pill btn-sm fw-bold">📥 Exportar Ventas CSV</button>
              <span class="fs-1">🛠️️</span>
            </div>
          </div>

          <div class="row g-3 mb-4 text-center">
            <div class="col-md-4">
              <div class="p-3 bg-white rounded-4 border shadow-sm">
                <small class="text-muted d-block uppercase fw-bold">Clientes Registrados</small>
                <strong class="fs-2 text-dark">${data.metrics.users_count}</strong>
              </div>
            </div>
            <div class="col-md-4">
              <div class="p-3 bg-white rounded-4 border shadow-sm">
                <small class="text-muted d-block uppercase fw-bold">Ventas Totales</small>
                <strong class="fs-2 text-dark">${data.metrics.orders_count}</strong>
              </div>
            </div>
            <div class="col-md-4">
              <div class="p-3 bg-white rounded-4 border shadow-sm">
                <small class="text-muted d-block uppercase fw-bold">Recaudación Total</small>
                <strong class="fs-2 text-success">${formatCOP(data.metrics.total_revenue)}</strong>
              </div>
            </div>
          </div>

          <ul class="nav nav-pills mb-3" id="pills-tab" role="tablist">
            <li class="nav-item">
              <button class="nav-link active rounded-pill px-4" id="pills-orders-tab" data-bs-toggle="pill" data-bs-target="#pills-orders" type="button">Gestión de Órdenes Globales</button>
            </li>
            <li class="nav-item">
              <button class="nav-link rounded-pill px-4" id="pills-users-tab" data-bs-toggle="pill" data-bs-target="#pills-users" type="button">Gestión de Usuarios</button>
            </li>
          </ul>

          <div class="tab-content" id="pills-tabContent">
            <div class="tab-pane fade show active" id="pills-orders">
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
                    `).join('') : '<tr><td colspan="6" class="text-center py-3 text-muted">No hay órdenes registradas aún.</td></tr>'}
                  </tbody>
                </table>
              </div>
            </div>

            <div class="tab-pane fade" id="pills-users">
              <div class="table-responsive">
                <table class="table table-hover align-middle small">
                  <thead class="table-dark">
                    <tr>
                      <th>ID</th>
                      <th>Nombre</th>
                      <th>Correo Electrónico</th>
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
                        <td>${u.email}</td>
                        <td><span class="badge ${u.role==='admin'?'bg-danger':'bg-secondary'}">${u.role}</span></td>
                        <td>${u.created_at}</td>
                        <td>
                          ${u.email !== 'julianjuanm@gmail.com' ? `<button class="btn btn-sm btn-outline-danger border-0" onclick="deleteUserByAdmin(${u.id})">🗑️ Eliminar</button>` : '<span class="text-muted">Propietario</span>'}
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
  }

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
    if (!confirm('¿Estás seguro de que deseas eliminar este usuario y todos sus registros asociadas?')) return;
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
})();
</script>
"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home_admin_extended() -> str:
    return HOME_PAGE.replace("</body>", f"{ADMIN_SCRIPT_EXTENSION}\n</body>")
