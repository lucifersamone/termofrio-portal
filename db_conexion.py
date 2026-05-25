# db_conexion.py
import streamlit as st
import requests
import pandas as pd

# 1. Credenciales centralizadas desde tu secrets.toml
URL_BASE = st.secrets["SUPABASE_URL"].strip().rstrip("/")
API_KEY = st.secrets["SUPABASE_KEY"].strip()

HEADERS = {
    "apikey": API_KEY,
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"  # Permite confirmar cambios
}

# 2. LEER DATOS (Reemplaza a pd.read_sql)
def leer_tabla(nombre_tabla):
    endpoint = f"{URL_BASE}/rest/v1/{nombre_tabla}?select=*"
    try:
        res = requests.get(endpoint, headers=HEADERS)
        return pd.DataFrame(res.json()) if res.status_code == 200 else pd.DataFrame()
    except:
        return pd.DataFrame()

# 3. INSERTAR DATOS (Reemplaza a INSERT INTO)
def insertar_registro(nombre_tabla, datos_dict):
    endpoint = f"{URL_BASE}/rest/v1/{nombre_tabla}"
    try:
        res = requests.post(endpoint, headers=HEADERS, json=datos_dict)
        return res.status_code in [200, 201]
    except:
        return False

# 4. ACTUALIZAR DATOS (Reemplaza a UPDATE)
def actualizar_registro(nombre_tabla, id_columna, id_valor, datos_dict):
    endpoint = f"{URL_BASE}/rest/v1/{nombre_tabla}?{id_columna}=eq.{id_valor}"
    try:
        res = requests.patch(endpoint, headers=HEADERS, json=datos_dict)
        return res.status_code in [200, 204]
    except:
        return False

# 5. ELIMINAR DATOS (Reemplaza a DELETE FROM)
def eliminar_registro(nombre_tabla, id_columna, id_valor):
    endpoint = f"{URL_BASE}/rest/v1/{nombre_tabla}?{id_columna}=eq.{id_valor}"
    try:
        res = requests.delete(endpoint, headers=HEADERS)
        return res.status_code in [200, 204]
    except:
        return False