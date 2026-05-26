import streamlit as st
import pandas as pd
import sqlite3
import requests
import os
from datetime import datetime, date, timedelta
from pandas.tseries.offsets import BusinessDay
import numpy as np
import altair as alt
import base64
import io
import tempfile
import random
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from fpdf import FPDF
import psycopg2
import re

# --- ADAPTADOR INVISIBLE PARA SUPABASE (VERSION 2.4 - COMPLETO Y ALINEADO) ---
class SQLiteToPostgresCursor:
    def __init__(self, pg_cursor):
        self.pg_cursor = pg_cursor
        self._lastrowid = None
        
    @property
    def lastrowid(self):
        return self._lastrowid
        
    def execute(self, query, vars=None):
        if vars is not None:
            query = query.replace('?', '%s')
            cleaned_vars = []
            for v in vars:
                if hasattr(v, 'item') and callable(getattr(v, 'item')):
                    cleaned_vars.append(v.item())
                else:
                    cleaned_vars.append(v)
            vars = tuple(cleaned_vars)
            
        query = re.sub(r"(?i)\bas\s+'([^']+)'", r'AS "\1"', query)
        query = query.replace('[', '"').replace(']', '"')
        query = re.sub(r'(?i)\bpedidos\b', 'pedidostf', query)
        
        is_insert = query.strip().upper().startswith("INSERT")
        if is_insert and "RETURNING" not in query.upper():
            query = query.rstrip('; ') + " RETURNING id"
            
        res = self.pg_cursor.execute(query, vars)
        
        if is_insert:
            try:
                row = self.pg_cursor.fetchone()
                if row:
                    self._lastrowid = row[0]
            except Exception:
                self._lastrowid = None
        return res
        
    def executemany(self, query, vars_list=None):
        if vars_list is not None:
            query = query.replace('?', '%s')
            cleaned_vars_list = []
            for vars in vars_list:
                cleaned_vars = []
                for v in vars:
                    if hasattr(v, 'item') and callable(getattr(v, 'item')):
                        cleaned_vars.append(v.item())
                    else:
                        cleaned_vars.append(v)
                cleaned_vars_list.append(tuple(cleaned_vars))
            vars_list = cleaned_vars_list
            
        query = re.sub(r"(?i)\bas\s+'([^']+)'", r'AS "\1"', query)
        query = query.replace('[', '"').replace(']', '"')
        query = re.sub(r'(?i)\bpedidos\b', 'pedidostf', query)
        return self.pg_cursor.executemany(query, vars_list)
        
    def __getattr__(self, name):
        return getattr(self.pg_cursor, name)

class SupabaseSQLAdapter:
    def __init__(self):
        self.conn = psycopg2.connect(
            host=st.secrets["DB_HOST"],
            database=st.secrets["DB_NAME"],
            user=st.secrets["DB_USER"],
            port=st.secrets["DB_PORT"],
            password=st.secrets["DB_PASS"]
        )
        self.conn.autocommit = True
        
    def cursor(self):
        return SQLiteToPostgresCursor(self.conn.cursor())

    def commit(self):
        pass

    def close(self):
        self.conn.close()

    def __getattr__(self, name):
        return getattr(self.conn, name)

# --- LA FUNCIÓN QUE RECONOCERÁ TU CÓDIGO ---
def get_connection(): 
    return SupabaseSQLAdapter()
    
# Configuración extendida de página
st.set_page_config(page_title="Dashboard Fabricacion Ductos", page_icon="termofrio.ico", layout="wide")

# --- RUTAS DE BASES DE DATOS Y RECURSOS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PROD = os.path.join(BASE_DIR, 'produccion_v55_master.db')
DB_MANT = os.path.join(BASE_DIR, 'mantenimiento_taller.db')
CARPETA_FOTOS = os.path.join(BASE_DIR, "img_maquinas")

# Rutas para el PDF
DIR_RECURSOS = os.path.join(BASE_DIR, 'firma_timbre')
LOGO_PATH = os.path.join(DIR_RECURSOS, 'termofriologo.jpg')
ISO_PATH = os.path.join(DIR_RECURSOS, 'tfiso.jpg')

# ====================================================================
# FUNCIONES DE UTILIDAD PARA PDF NATIVO
# ====================================================================
def limpiar_texto(text):
    """Limpia caracteres especiales que causan errores en PDFs."""
    if not isinstance(text, str): text = str(text)
    mapping = {"–": "-", "—": "-", "…": "...", "“": '"', "”": '"', "‘": "'", "’": "'"}
    for char, replacement in mapping.items(): text = text.replace(char, replacement)
    return text.encode("latin-1", "replace").decode("latin-1")

# ====================================================================
# FUNCIONES DE BASE DE DATOS
# ====================================================================
def get_connection():
    return SupabaseSQLAdapter() 

def obtener_siguiente_correlativo_obra(obra_codigo, tf):
    conn = get_connection()
    c = conn.cursor()
    obra_segura = obra_codigo if (obra_codigo and str(obra_codigo).strip() != "" and obra_codigo != "Seleccione Obra...") else "NULO_OBRA_XYZ"
    tf_seguro = tf if (tf and str(tf).strip() != "") else "NULO_TF_XYZ"
    
    c.execute("""
        SELECT num_pedido 
        FROM pedidos 
        WHERE obra_codigo = ? OR tf = ?
        ORDER BY id DESC LIMIT 1
    """, (obra_segura, tf_seguro))
    
    resultado = c.fetchone()
    conn.close()

    if resultado and resultado[0]:
        ultimo_num_texto = str(resultado[0])
        try:
            if "-" in ultimo_num_texto:
                ultimo_numero = int(ultimo_num_texto.split('-')[-1])
            else:
                ultimo_numero = int(ultimo_num_texto)
            nuevo_numero = ultimo_numero + 1
        except ValueError: nuevo_numero = 1
    else: nuevo_numero = 1
        
    return f"OT-{nuevo_numero}"

@st.cache_resource
def actualizar_bd_estructuras():
    conn = get_connection(); c = conn.cursor()
    try: c.execute("ALTER TABLE pedidos ADD COLUMN observaciones TEXT DEFAULT ''") 
    except: pass
    try: c.execute("ALTER TABLE pedidos ADD COLUMN estado_despacho TEXT DEFAULT 'En Taller'") 
    except: pass
    try: c.execute("ALTER TABLE pedidos ADD COLUMN fecha_despacho DATE") 
    except: pass
    try: c.execute("ALTER TABLE pedidos ADD COLUMN men TEXT DEFAULT ''") 
    except: pass
    try: c.execute("ALTER TABLE pedidos ADD COLUMN nivel_urgencia TEXT DEFAULT 'Normal'")
    except: pass
    try: c.execute("ALTER TABLE pedidos ADD COLUMN ruta_excel TEXT DEFAULT ''")
    except: pass
    try: c.execute('''CREATE TABLE IF NOT EXISTS usuarios_claves (usuario TEXT PRIMARY KEY, clave TEXT, ultimo_2fa DATE)''')
    except: pass
    try: c.execute("ALTER TABLE usuarios_claves ADD COLUMN ultimo_2fa DATE")
    except: pass
    conn.commit(); conn.close()
    return True

actualizar_bd_estructuras()

# --- DIRECTORIO DE USUARIOS Y ROLES (MULTI-OBRA) ---
USUARIOS = {
    "admin": {"clave": "termofrio", "rol": "administrador", "nombre": "Admin Taller"},
    
    "navile": {
        "clave": "1234", "rol": "cliente", "nombre": "Natanael Avile",
        "correo": "navile@termofrio.cl", 
        "tf": ["13655"], "ceco": ["2-11-063"], "obra": ["TF-13655 SANTIAGO WEST TEMPLE"]
    },
    "mrubilar": {
        "clave": "5678", "rol": "cliente", "nombre": "Miguel Rubilar",
        "correo": "miguel.rubilar@ejemplo.cl", 
        "tf": ["13655"], "ceco": ["2-11-063"], "obra": ["TF-13655 SANTIAGO WEST TEMPLE"]
    },
    
    "ainostroza": {
        "clave": "1234", "rol": "cliente", "nombre": "Alejandro Inostroza",
        "correo": "ainostroza@termofrio.cl", 
        "tf": ["13784", "13817"], 
        "ceco": ["2-12-023", "2-12-024"],
        "obra": ["TF – 13784 ACHS EDIFICIO B PROVIDENCIA", "TF-13817 ACHS - EDIFICIO K1 PISO 1 - EDIFICIO C"]
    },
    "malvina": {
        "clave": "1234", "rol": "cliente", "nombre": "Miguel Alviña",
        "correo": "malvina@termofrio.cl", 
        "tf": ["13784", "13817"], 
        "ceco": ["2-12-023", "2-12-024"],
        "obra": ["TF – 13784 ACHS EDIFICIO B PROVIDENCIA", "TF-13817 ACHS - EDIFICIO K1 PISO 1 - EDIFICIO C"]
    },
    "rinostroza": {
        "clave": "1234", "rol": "cliente", "nombre": "Rolando Inostroza",
        "correo": "rinostroza@termofrio.cl", 
        "tf": ["13784", "13817"], 
        "ceco": ["2-12-023", "2-12-024"],
        "obra": ["TF – 13784 ACHS EDIFICIO B PROVIDENCIA", "TF-13817 ACHS - EDIFICIO K1 PISO 1 - EDIFICIO C"]
    },
    
    "cbustos": {"clave": "1234", "rol": "cliente", "nombre": "Cristian Bustos", "correo": "cristian.bustos@ejemplo.cl"},
    "jguzman": {"clave": "1234", "rol": "cliente", "nombre": "Joel Guzman", "correo": "jguzman@termofrio.cl"},
    "pramirez": {"clave": "1234", "rol": "cliente", "nombre": "Paulo Ramirez", "correo": "pramirez@termofrio.cl"},
    "jabarca": {"clave": "1234", "rol": "cliente", "nombre": "Juan Pablo Abarca", "correo": "jabarca@termofrio.cl"},
    "jhidalgo": {"clave": "1234", "rol": "cliente", "nombre": "Jose Hidalgo", "correo": "jhidalgo@termofrio.cl"},
    "mcataldo": {"clave": "1234", "rol": "cliente", "nombre": "Marco Cataldo", "correo": "mcataldo@termofrio.cl"},
    "falvarez": {"clave": "1234", "rol": "cliente", "nombre": "Francisco Alvarez", "correo": "falvarez@termofrio.cl"},
    "adiaz": {"clave": "1234", "rol": "cliente", "nombre": "Ariel Diaz", "correo": "adiaza@termofrio.cl"},
    "amarin": {"clave": "1234", "rol": "cliente", "nombre": "Axel Marin", "correo": "amarin@termofrio.cl"},
}

LISTA_DESCRIPCIONES = [
    "Ducto Recto", "Codo", "Codo Transfor.", "Medio Codo", "Transformación", 
    "S", "S Transformada", "Zapato c/ Templador", "Zapato s/ Templador", 
    "Caja Difusora", "Caja Difusora Esp.", "Cachimba", "Collarín", 
    "Collarín c/ Templador", "Cono", "Cuello Normal", "Cuello Presentación", 
    "Curva con Casquete", "Ducto c/ Aleta", "Ducto c/ Templador", 
    "Ducto Cil. Fe N/1 mm", "Ducto Cil. Fe N/1,5 mm", "Ducto Cil. Fe N/2 mm", 
    "Ducto Cil. Fe N/3 mm", "Ducto Cilíndrico", "Ducto Rec. Fe N/1 mm", 
    "Ducto Rec. Fe N/1,5 mm", "Ducto Rec. Fe N/2 mm", "Ducto Rec. Fe N/3 mm", 
    "Pleno", "Tapa", "Transf. Red - Cuad", "Unión c/ Lona", "Vicera c/ Malla", 
    "Plancha Lisa", "Pieza especial"
]

LISTA_SIMETRIAS = ["Asimétrica", "Inferior Parejo", "Pareja Der. - Inf. Pareja", "Pareja Der. - Simétrica", "Pareja Der. - Sup. Pareja", "Pareja Izq. - Inf. Pareja", "Pareja Izq. - Simétrica", "Pareja Izq. - Sup. Pareja", "Simétrica - Inf. Pareja", "Simétrica - Simétrica", "Simétrica - Sup. Pareja", "Simétrico", "Superior Parejo", "Cuadrado"]
LISTA_UNIONES = ["Balleta", "Copla Rodón", "Embutido", "Escu. - Recar. 25", "Escuadra", "Flange", "Liso", "Malla", "Pestaña 15", "Pestaña 25", "Pestaña 30", "Pestaña 40", "Pestaña 50", "TDF", "Triple 50", "Triple 60", "Tapa ciega", "Tapa c/collarin"]

MAPEO_CAMPOS = {
    "Ducto Recto": ["A", "B", "H", "Entrada", "Salida"],
    "Codo": ["A", "B", "Radio", "Simetria", "Angulo", "Entrada", "Salida"],
    "Codo Transfor.": ["A", "B", "Radio", "Simetria", "C", "D", "Angulo", "Entrada", "Salida"],
    "Medio Codo": ["A", "B", "Radio", "Simetria", "Angulo", "Entrada", "Salida"],
    "Transformación": ["A", "B", "Simetria", "C", "D", "H", "Entrada", "Salida"],
    "S": ["A", "B", "d", "H", "Entrada", "Salida"],
    "S Transformada": ["A", "B", "d", "Simetria", "C", "D", "H", "Entrada", "Salida"],
    "Zapato c/ Templador": ["A", "B", "H", "Entrada", "Salida"],
    "Zapato s/ Templador": ["A", "B", "H", "Entrada", "Salida"],
    "Caja Difusora": ["A", "B", "H", "Dia1", "Entrada", "Salida"],
    "Cachimba": ["A", "B", "Angulo", "Entrada", "Salida"],
    "Caja Difusora Esp.": ["A", "B", "H", "Dia1", "Entrada", "Salida"],
    "Collarín": ["H", "Dia1", "Entrada", "Salida"],
    "Collarín c/ Templador": ["H", "Dia1", "Entrada", "Salida"],
    "Cono": ["H", "Dia1", "Dia2", "Entrada", "Salida"],
    "Cuello Normal": ["A", "B", "H", "Entrada", "Salida"],
    "Cuello Presentación": ["A", "B", "H", "Entrada", "Salida"],
    "Curva con Casquete": ["Dia1", "Angulo", "Casquetes", "Entrada", "Salida"], 
    "Ducto c/ Aleta": ["A", "B", "H", "Entrada", "Salida"],
    "Ducto c/ Templador": ["A", "B", "H", "Entrada", "Salida"],
    "Ducto Cil. Fe N/1 mm": ["H", "Dia1", "Entrada", "Salida"],
    "Ducto Cil. Fe N/1,5 mm": ["H", "Dia1", "Entrada", "Salida"],
    "Ducto Cil. Fe N/2 mm": ["H", "Dia1", "Entrada", "Salida"],
    "Ducto Cil. Fe N/3 mm": ["H", "Dia1", "Entrada", "Salida"],
    "Ducto Cilíndrico": ["H", "Dia1", "Entrada", "Salida"],
    "Ducto Rec. Fe N/1 mm": ["A", "B", "H", "Entrada", "Salida"],
    "Ducto Rec. Fe N/1,5 mm": ["A", "B", "H", "Entrada", "Salida"],
    "Ducto Rec. Fe N/2 mm": ["A", "B", "H", "Entrada", "Salida"],
    "Ducto Rec. Fe N/3 mm": ["A", "B", "H", "Entrada", "Salida"],
    "Pleno": ["A", "B", "C", "D", "H", "Entrada", "Salida"],
    "Tapa": ["A", "B", "Entrada", "Salida"],
    "Transf. Red - Cuad": ["A", "B", "Simetria", "H", "Dia1", "Entrada", "Salida"],
    "Unión c/ Lona": ["A", "B", "H", "Entrada", "Salida"],
    "Vicera c/ Malla": ["A", "B", "Entrada", "Salida"],
    "Plancha Lisa": ["A", "B"], 
    "Pieza especial": ["A", "B", "d", "Simetria", "C", "D", "H", "Dia1", "Dia2", "Angulo", "Casquetes", "Entrada", "Salida"]
}

def enviar_codigo_2fa(codigo):
    api_key = "re_BDpTi8ZD_5bBbZV28hy3ZgK2FaukBqjZM"
    url = "https://api.resend.com/emails"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {
        "from": "Sistema Termofrio <onboarding@resend.dev>",
        "to": ["rockandlu1@gmail.com"], 
        "subject": "🔒 Código de Seguridad 2FA - Termofrio SPA",
        "text": f"Tu código de seguridad de doble factor (2FA) para el usuario ADMIN es:\n\n{codigo}\n\nEste código es válido para este inicio de sesión."
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200: return True
        else: return False
    except: return False

def procesar_login_exitoso(user):
    st.session_state.logged_in = True
    st.session_state.username_actual = user
    st.session_state.rol = USUARIOS[user]["rol"]
    st.session_state.nombre_usuario = USUARIOS[user]["nombre"]
    st.session_state.correo_usuario = USUARIOS[user].get("correo", "")
    
    tf_v = USUARIOS[user].get("tf", [])
    st.session_state.tf_usuario = tf_v if isinstance(tf_v, list) else ([tf_v] if tf_v else [])
    ceco_v = USUARIOS[user].get("ceco", [])
    st.session_state.ceco_usuario = ceco_v if isinstance(ceco_v, list) else ([ceco_v] if ceco_v else [])
    obra_v = USUARIOS[user].get("obra", [])
    st.session_state.obra_usuario = obra_v if isinstance(obra_v, list) else ([obra_v] if obra_v else [])
    
    st.session_state.esperando_2fa = False
    st.rerun()

# --- LOGIN UNIFICADO CON BASE DE DATOS ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.rol = None
    st.session_state.nombre_usuario = None
    st.session_state.username_actual = None

parametros_url = st.query_params
if parametros_url.get("rol") == "gerencia":
    st.session_state.logged_in = True
    st.session_state.rol = "gerencia"
    st.session_state.nombre_usuario = "Gerencia General"
    st.session_state.username_actual = "gerencia"

if 'esperando_2fa' not in st.session_state: st.session_state.esperando_2fa = False
if 'codigo_2fa_real' not in st.session_state: st.session_state.codigo_2fa_real = None

if not st.session_state.logged_in:
    st.markdown("<h1 style='text-align: center; color: #1f77b4;'>🔒 Acceso al Sistema Termofrio</h1>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1, 1])
    with c2:
        if not st.session_state.esperando_2fa:
            with st.form("login_form"):
                st.markdown("#### Ingreso Seguro")
                user = st.text_input("Usuario")
                pwd = st.text_input("Contraseña", type="password")
                if st.form_submit_button("Ingresar 🚀", use_container_width=True):
                    if user in USUARIOS:
                        conn = get_connection(); c = conn.cursor()
                        try:
                            c.execute("SELECT clave, ultimo_2fa FROM usuarios_claves WHERE usuario=?", (user,))
                            row = c.fetchone()
                        except:
                            c.execute("SELECT clave FROM usuarios_claves WHERE usuario=?", (user,))
                            row = c.fetchone()
                            row = (row[0], None) if row else None
                        conn.close()

                        clave_real = row[0] if row else USUARIOS[user]["clave"]
                        ultimo_2fa = pd.to_datetime(row[1]).date() if (row and len(row)>1 and row[1]) else None

                        if pwd == clave_real:
                            if user == "admin":
                                hoy = datetime.now().date()
                                if ultimo_2fa is None or (hoy - ultimo_2fa).days >= 30:
                                    codigo_gen = str(random.randint(100000, 999999))
                                    st.session_state.codigo_2fa_real = codigo_gen
                                    if enviar_codigo_2fa(codigo_gen):
                                        st.session_state.esperando_2fa = True
                                        st.rerun()
                                    else: st.error("Error al enviar 2FA.")
                                else: procesar_login_exitoso(user)
                            else: procesar_login_exitoso(user)
                        else: st.error("Usuario o contraseña incorrectos")
                    else: st.error("Usuario o contraseña incorrectos")
        else:
            st.warning("🛡️ Se requiere Verificación de Seguridad (cada 30 días).")
            st.info("Hemos enviado un código de 6 dígitos al correo registrado.")
            with st.form("form_2fa"):
                codigo_ingresado = st.text_input("Ingresa el código numérico:")
                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    if st.form_submit_button("Verificar Código ✅", use_container_width=True):
                        if codigo_ingresado == st.session_state.codigo_2fa_real:
                            conn = get_connection(); c = conn.cursor()
                            c.execute("SELECT 1 FROM usuarios_claves WHERE usuario='admin'")
                            if c.fetchone(): c.execute("UPDATE usuarios_claves SET ultimo_2fa=? WHERE usuario='admin'", (datetime.now().date(),))
                            else: c.execute("INSERT INTO usuarios_claves (usuario, clave, ultimo_2fa) VALUES (?, ?, ?)", ("admin", USUARIOS["admin"]["clave"], datetime.now().date()))
                            conn.commit(); conn.close()
                            procesar_login_exitoso("admin")
                        else: st.error("❌ Código incorrecto.")
                with col_b2:
                    if st.form_submit_button("Cancelar", use_container_width=True):
                        st.session_state.esperando_2fa = False
                        st.session_state.codigo_2fa_real = None
                        st.rerun()
    st.stop()

# --- BARRA LATERAL CON OPCIÓN DE CAMBIO DE CLAVE ---
with st.sidebar:
    st.markdown(f"👤 **Usuario:** {st.session_state.nombre_usuario}")
    st.markdown(f"🏷️ **Rol:** {str(st.session_state.rol).capitalize()}")
    st.divider()
    
    with st.expander("🔑 Cambiar Contraseña"):
        with st.form("form_cambiar_clave"):
            nueva_clave = st.text_input("Nueva Contraseña", type="password")
            confirmar_clave = st.text_input("Confirmar Contraseña", type="password")
            if st.form_submit_button("Actualizar Clave"):
                if nueva_clave and nueva_clave == confirmar_clave:
                    conn = get_connection(); c = conn.cursor()
                    c.execute("INSERT OR REPLACE INTO usuarios_claves (usuario, clave) VALUES (?, ?)", (st.session_state.username_actual, nueva_clave))
                    conn.commit(); conn.close()
                    st.success("✅ Contraseña actualizada correctamente.")
                else: st.error("❌ Las contraseñas no coinciden o están vacías.")

    st.divider()
    if st.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.rol = None
        st.session_state.nombre_usuario = None
        st.session_state.username_actual = None
        st.rerun()

# ====================================================================
# FUNCIONES INTERNAS SECUNDARIAS
# ====================================================================
def get_obras_ceco_df():
    conn = get_connection()
    try: df = pd.read_sql("SELECT * FROM maestro_obras", conn)
    except: df = pd.DataFrame()
    conn.close()
    return df

def buscar_datos_por_tf(tf_pedido):
    if not tf_pedido: return None, None
    conn = get_connection()
    try:
        df_obras = pd.read_sql("SELECT * FROM maestro_obras", conn)
        tf_input_clean = str(tf_pedido).upper().replace("TF", "").replace("-", "").strip()
        for _, row in df_obras.iterrows():
            if tf_input_clean in str(row['tf']).upper(): return row['ceco'], row['nombre']
    except: pass
    finally: conn.close()
    return None, None

def get_precios_df_cliente():
    conn = get_connection()
    try: df = pd.read_sql("SELECT * FROM lista_precios", conn)
    except: df = pd.DataFrame()
    conn.close()
    return df

def get_materiales_disponibles_cliente():
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT DISTINCT material FROM lista_precios WHERE material != 'Pieza Especial'", conn)
        materiales = [str(m).strip() for m in df['material'].dropna().unique().tolist() if str(m).strip()]
    except: materiales = []
    conn.close()
    
    materiales_ordenados = sorted(materiales)
    idx_galv = next((i for i, v in enumerate(materiales_ordenados) if v.lower() == "galvanizado"), -1)
    
    if idx_galv != -1:
        galv_item = materiales_ordenados.pop(idx_galv)
        materiales_ordenados.insert(0, galv_item)
    elif not materiales_ordenados: materiales_ordenados = ["Galvanizado"]
    elif "Galvanizado" not in materiales_ordenados: materiales_ordenados.insert(0, "Galvanizado")
    return materiales_ordenados

def buscar_precio_logica_cliente(desc, cant, peso, df_precios, material_seleccionado):
    desc_p = str(desc).upper().strip()
    if material_seleccionado == "Galvanizado":
        match = df_precios[df_precios['item'].str.upper() == desc_p]
        if match.empty:
            for _, r in df_precios.iterrows():
                m = str(r['item']).upper()
                if r['material'] in ['Galvanizado', 'Pieza Especial']:
                    if m in desc_p and len(m)>3: match = pd.DataFrame([r]); break
                    if desc_p in m and len(desc_p)>3: match = pd.DataFrame([r]); break
        if not match.empty:
            d = match.iloc[0]; p = d['precio']; u = str(d['unidad']).lower().strip()
            if u == 'un': return p, cant * p, 'un', f"Lista: {d['item']} (Pieza Esp.)"
            else: return p, peso * p, 'kg', f"Lista: {d['item']} (Galv)"
        else: return 0, 0, "-", "Manual"
    else:
        filtro = df_precios[(df_precios['material'].str.upper() == material_seleccionado.upper()) & (df_precios['unidad'].str.lower() == 'kg')]
        p_base = filtro['precio'].max() if not filtro.empty else 0
        if p_base > 0: return p_base, peso * p_base, 'kg', f"Base {material_seleccionado}"
        else: return 0, 0, "kg", f"Sin precio base"

def calcular_peso_teorico(desc, l_a, l_b, l_c, l_d, l_h, diam, diam2, esp):
    try:
        a = float(str(l_a).replace(',','.')) / 100 if l_a else 0.0
        b = float(str(l_b).replace(',','.')) / 100 if l_b else 0.0
        c = float(str(l_c).replace(',','.')) / 100 if l_c else 0.0
        d = float(str(l_d).replace(',','.')) / 100 if l_d else 0.0
        h = float(str(l_h).replace(',','.')) / 100 if l_h else 0.0
        d1 = float(str(diam).replace(',','.')) / 100 if diam else 0.0
        d2 = float(str(diam2).replace(',','.')) / 100 if diam2 else 0.0
        espesor = float(esp)
        area = 0.0
        desc_upper = str(desc).upper()

        if "RECTO" in desc_upper or "ALETA" in desc_upper or "TEMPLADOR" in desc_upper: area = 2 * (a + b) * h
        elif "CIL" in desc_upper or "CONO" in desc_upper:
            radio_prom = (d1 + d2) / 2 if d2 > 0 else d1
            area = 3.1416 * radio_prom * h
        elif "PLENO" in desc_upper or "CAJA" in desc_upper:
            profundidad = h if h > 0 else 0.25 
            area = 2 * (a + b) * profundidad + (a * b)
        elif "TRANSF" in desc_upper:
            p1 = 2 * (a + b) if a > 0 else 3.1416 * d1
            p2 = 2 * (c + d) if c > 0 else 3.1416 * d2
            area = ((p1 + p2) / 2) * h
        elif "CODO" in desc_upper:
            radio_medio = (a / 2) + 0.15 
            largo_curva = (3.1416 * radio_medio) / 2 
            area = 2 * (a + b) * largo_curva
        elif "S " in desc_upper or " S " in desc_upper: area = 2 * (a + b) * h * 1.2
        elif "TAPA" in desc_upper or "PLANCHA" in desc_upper: area = a * b
        else:
            if h > 0 and (a > 0 or d1 > 0): area = 2 * (a + b) * h if a > 0 else 3.1416 * d1 * h
            else: area = a * b
        peso_base = area * espesor * 8.0 
        return peso_base * 1.15 
    except: return 0.0

def generar_pdf_cliente(pedido_num, tf, obra, ceco, solicitante, items_df, kg_est, observaciones="", men=""):
    """Generador de PDF para Clientes - 100% Nativo en Python, compatible con la Nube."""
    clean_id = str(pedido_num).replace("/", "-").replace("\\", "-").strip()
    temp_dir = tempfile.gettempdir()
    ruta_pdf = os.path.join(temp_dir, f"Comprobante_{clean_id}.pdf")

    try:
        pdf = FPDF(orientation='L', unit='mm', format='A4')
        pdf.add_page()
        
        if os.path.exists(LOGO_PATH):
            try: pdf.image(LOGO_PATH, x=10, y=8, w=40)
            except: pass
        
        pdf.set_font("Arial", "B", 14)
        pdf.set_text_color(85, 85, 85)
        pdf.cell(0, 15, "COMPROBANTE DE SOLICITUD DE FABRICACION - TERMOFRIO SPA", ln=True, align="C")
        pdf.ln(5)

        pdf.set_text_color(0, 0, 0)
        pdf.set_fill_color(245, 245, 245)
        
        pdf.set_font("Arial", "B", 10)
        pdf.cell(30, 6, "N de Pedido:", border=0, fill=True)
        pdf.set_font("Arial", "", 10)
        pdf.cell(60, 6, limpiar_texto(str(pedido_num)), border=0, fill=True)
        
        pdf.set_font("Arial", "B", 10)
        try: kg_est_formateado = f"{float(kg_est):.1f}"
        except: kg_est_formateado = str(kg_est)
        pdf.cell(0, 6, limpiar_texto(f"KG ESTIMADOS TOTALES: {kg_est_formateado} Kg"), border=0, fill=True, ln=True, align="R")

        pdf.set_font("Arial", "B", 10)
        pdf.cell(30, 6, "Obra Destino:", border=0, fill=True)
        pdf.set_font("Arial", "", 10)
        pdf.cell(60, 6, limpiar_texto(str(obra)), border=0, fill=True)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 6, f"Fecha Emision: {datetime.now().strftime('%d/%m/%Y')}", border=0, fill=True, ln=True, align="R")

        pdf.set_font("Arial", "B", 10)
        pdf.cell(30, 6, "Codigo TF/CC:", border=0, fill=True)
        pdf.set_font("Arial", "", 10)
        pdf.cell(60, 6, limpiar_texto(str(tf)), border=0, fill=True)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(60, 6, limpiar_texto(f"CECO: {ceco}"), border=0, fill=True)
        if men and str(men).strip() and str(men) != "nan":
            pdf.cell(0, 6, limpiar_texto(f"MEN: {men}"), border=0, fill=True, ln=True, align="R")
        else:
            pdf.cell(0, 6, "", border=0, fill=True, ln=True)

        pdf.set_font("Arial", "B", 10)
        pdf.cell(30, 6, "Solicitante:", border=0, fill=True)
        pdf.set_font("Arial", "", 10)
        pdf.cell(0, 6, limpiar_texto(str(solicitante)), border=0, fill=True, ln=True)

        pdf.ln(5)

        pdf.set_font("Arial", "B", 9)
        pdf.set_fill_color(105, 105, 105)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(15, 8, "Item", border=1, align="C", fill=True)
        pdf.cell(65, 8, "Descripcion", border=1, fill=True)
        pdf.cell(140, 8, "Medidas y Especificaciones", border=1, fill=True)
        pdf.cell(15, 8, "Cant.", border=1, align="C", fill=True)
        pdf.cell(20, 8, "Espesor", border=1, align="C", fill=True)
        pdf.cell(20, 8, "Kg Est.", border=1, align="C", fill=True, ln=True)

        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", "", 9)
        for _, row in items_df.iterrows():
            try: kg_str = f"{float(row.get('peso_total', 0)):.2f}"
            except: kg_str = str(row.get('peso_total', ''))
            
            try: esp_str = f"{float(row.get('espesor', 0)):.1f}"
            except: esp_str = str(row.get('espesor', ''))

            itm = str(row.get('item_numero', row.get('item_num', '')))
            dsc = str(row.get('descripcion', row.get('Descripción', '')))
            det = str(row.get('detalles', row.get('Detalles/Medidas', ''))).replace('nan', '')
            cnt = str(row.get('cantidad', row.get('Cantidad', '')))

            pdf.cell(15, 6, limpiar_texto(itm), border=1, align="C")
            pdf.cell(65, 6, limpiar_texto(dsc)[:35], border=1) 
            pdf.cell(140, 6, limpiar_texto(det)[:85], border=1)
            pdf.cell(15, 6, limpiar_texto(cnt), border=1, align="C")
            pdf.cell(20, 6, limpiar_texto(esp_str), border=1, align="C")
            pdf.cell(20, 6, limpiar_texto(kg_str), border=1, align="C", ln=True)

        if observaciones and str(observaciones).strip() and str(observaciones) != "nan":
            pdf.ln(5)
            pdf.set_font("Arial", "I", 9)
            pdf.multi_cell(0, 6, limpiar_texto(f"Comentarios / Observaciones: {observaciones}"), border=1)

        pdf.output(ruta_pdf)
        return ruta_pdf
    except Exception as e:
        print(f"Error generando PDF Cliente nativo: {e}")
        return None

# ====================================================================
# VISTA EXCLUSIVA PARA CLIENTES / SUPERVISORES
# ====================================================================
if st.session_state.rol == "cliente":
    if 'carrito_cliente' not in st.session_state: st.session_state.carrito_cliente = []

    st.markdown("""<style>[data-testid="stSidebarNav"] {display: none;}</style>""", unsafe_allow_html=True)
    
    st.title(f"👋 Bienvenido, {st.session_state.nombre_usuario}")
    st.markdown("Portal de Solicitudes y Seguimiento de Termofrio SPA.")
    
    tab_mis_pedidos, tab_nuevo_pedido = st.tabs(["📦 Mis Pedidos", "✍️ Nuevo Pedido Manual"])
    
    with tab_mis_pedidos:
        st.subheader("Estado de mis solicitudes")
        try:
            conn = get_connection()
            tf_list = st.session_state.tf_usuario
            obra_list = st.session_state.obra_usuario
            
            query = """
            SELECT id, num_pedido as 'N° Pedido', quien_envia as 'Solicitante', obra_codigo as 'Obra', fecha_recepcion as 'Ingreso', 
            fecha_termino as 'F. Cierre', fecha_despacho as 'F. Despacho',
            estado as 'Estado', kg_estimados as 'Kg Est.', kg_reales as 'Kg Reales' 
            FROM pedidos 
            WHERE quien_envia = ? 
            """
            params = [st.session_state.nombre_usuario]
            
            if tf_list:
                query += f" OR tf IN ({','.join(['?']*len(tf_list))})"
                params.extend(tf_list)
            if obra_list:
                query += f" OR obra_codigo IN ({','.join(['?']*len(obra_list))})"
                params.extend(obra_list)
                
            query += " ORDER BY id DESC"
            df_mis_pedidos = pd.read_sql(query, conn, params=params)
            
            if not df_mis_pedidos.empty:
                filtro_est = st.radio("Filtro de visualización:", ["Todos", "Pendientes (En Taller)", "Terminados (Historial)"], horizontal=True)
                if filtro_est == "Pendientes (En Taller)": df_vista = df_mis_pedidos[df_mis_pedidos['Estado'] == 'Pendiente']
                elif filtro_est == "Terminados (Historial)": df_vista = df_mis_pedidos[df_mis_pedidos['Estado'] == 'Terminado']
                else: df_vista = df_mis_pedidos
                    
                st.dataframe(df_vista.drop(columns=['id']), use_container_width=True, hide_index=True)
                st.markdown("---")
                st.markdown("#### 🔍 Ver Detalle y Descargar Comprobante")
                col_b1, col_b2 = st.columns([1, 2])
                with col_b1:
                    pedido_a_ver = st.selectbox("Seleccionar Pedido:", df_vista['N° Pedido'].astype(str) + " / " + df_vista['Obra'], key="cli_ver_ped")
                    if pedido_a_ver: id_ver = df_vista[df_vista['N° Pedido'].astype(str) + " / " + df_vista['Obra'] == pedido_a_ver].iloc[0]['id']
                
                if pedido_a_ver:
                    with col_b2:
                        st.markdown("<br>", unsafe_allow_html=True)
                        df_items_raw = pd.read_sql(f"SELECT * FROM items_pedido WHERE pedido_id={id_ver}", conn)
                        obs_query = pd.read_sql(f"SELECT * FROM pedidos WHERE id={id_ver}", conn)
                        fila_ped = obs_query.iloc[0]
                        obs_txt = fila_ped['observaciones'] if 'observaciones' in fila_ped else ""
                        men_txt = fila_ped['men'] if 'men' in fila_ped else ""

                        if not df_items_raw.empty:
                            df_items_display = df_items_raw[['item_numero', 'descripcion', 'detalles', 'cantidad', 'espesor', 'peso_total']].rename(columns={
                                'item_numero': 'Ítem', 'descripcion': 'Pieza', 'detalles': 'Especificaciones', 'cantidad': 'Cant.', 'espesor': 'Esp. (mm)', 'peso_total': 'Kg Est.'
                            })
                            st.dataframe(df_items_display, use_container_width=True, hide_index=True)
                            
                            if st.button("📄 Descargar Comprobante PDF", key="btn_comprobante"):
                                with st.spinner("Generando documento..."):
                                    ruta_pdf = generar_pdf_cliente(
                                        pedido_num=fila_ped['num_pedido'], tf=fila_ped['tf'], obra=fila_ped['obra_codigo'], ceco=fila_ped['ceco'], solicitante=fila_ped['quien_envia'],
                                        items_df=df_items_raw, kg_est=fila_ped['kg_estimados'], observaciones=obs_txt, men=men_txt
                                    )
                                    if ruta_pdf:
                                        with open(ruta_pdf, "rb") as f:
                                            st.download_button("📥 Guardar en mi equipo", f, file_name=f"Comprobante_{fila_ped['num_pedido']}.pdf")
                        else: st.info("Sin detalle de piezas.")
                
                df_pendientes = df_mis_pedidos[df_mis_pedidos['Estado'] == 'Pendiente'].copy()
                if not df_pendientes.empty:
                    st.divider()
                    st.markdown("#### 🗑️ Anular Pedido")
                    col_del1, col_del2 = st.columns([3, 1])
                    with col_del1:
                        df_pendientes['display_name'] = "Pedido N° " + df_pendientes['N° Pedido'].astype(str) + " - Obra: " + df_pendientes['Obra'].astype(str)
                        pedido_a_borrar = st.selectbox("Selecciona el pedido a anular:", df_pendientes['display_name'])
                    with col_del2:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button("🚫 Anular Seleccionado", type="primary"):
                            id_borrar = df_pendientes[df_pendientes['display_name'] == pedido_a_borrar].iloc[0]['id']
                            cursor = conn.cursor()
                            cursor.execute("DELETE FROM items_pedido WHERE pedido_id=?", (int(id_borrar),))
                            cursor.execute("DELETE FROM pedidos WHERE id=?", (int(id_borrar),))
                            conn.commit()
                            st.success("✅ Pedido anulado.")
                            st.rerun()
            else: st.info("Aún no tienes pedidos registrados.")
            conn.close()
        except Exception as e: st.error(f"Error: {e}")
            
    with tab_nuevo_pedido:
        st.header("Ingresar Requerimientos")
        st.info("Formulario Dinámico: Selecciona la pieza y solo te pediremos las medidas necesarias para su fabricación.")
        
        df_obras_m = get_obras_ceco_df()
        lista_obras = ["Seleccione Obra..."] + df_obras_m['nombre'].tolist() if not df_obras_m.empty else ["Seleccione Obra..."]

        col_m1, col_m2, col_m3 = st.columns(3)
        tfs_asignados = st.session_state.tf_usuario
        obras_asignadas = st.session_state.obra_usuario
        cecos_asignados = st.session_state.ceco_usuario

        with col_m1:
            if len(tfs_asignados) > 1:
                obra_manual = st.selectbox("🏗️ Obra Destino", obras_asignadas)
                idx = obras_asignadas.index(obra_manual)
                tf_manual = st.text_input("Código TF ó CC", value=tfs_asignados[idx], disabled=True)
                ceco_auto = cecos_asignados[idx]
            elif len(tfs_asignados) == 1:
                tf_manual = st.text_input("Código TF ó CC", value=tfs_asignados[0], disabled=True)
                obra_manual = st.text_input("🏗️ Obra Destino", value=obras_asignadas[0], disabled=True)
                ceco_auto = cecos_asignados[0]
            else:
                tf_manual = st.text_input("Código TF ó CC (Ej: 13655 o CC02)", key="tf_m_cli")
                ceco_auto, obra_auto = buscar_datos_por_tf(tf_manual)
                index_obra = 0
                if obra_auto and obra_auto in lista_obras: index_obra = lista_obras.index(obra_auto)
                obra_manual = st.selectbox("🏗️ Obra Destino", lista_obras + ["Otra (Escribir manual)"], index=index_obra)
                if obra_manual == "Otra (Escribir manual)": obra_manual = st.text_input("Escribir nombre de la obra:", value=obra_auto if obra_auto else "")

        with col_m2:
            if len(tfs_asignados) >= 1: ceco_manual = st.text_input("CECO", value=ceco_auto, disabled=True)
            else:
                default_ceco = ceco_auto if ceco_auto else ""
                if tf_manual.strip().upper() == "CC02": default_ceco = "4-02-002 EXTRAS"
                ceco_manual = st.text_input("CECO", value=default_ceco)
            men_manual = st.text_input("MEN (Opcional)")
            
        with col_m3:
            quien_manual = st.text_input("👤 Solicitante", value=st.session_state.nombre_usuario, disabled=True)
            correo_manual = st.text_input("📧 Correo Electrónico", value=st.session_state.correo_usuario, disabled=bool(st.session_state.correo_usuario))
            
        col_mat, col_aisl = st.columns([2, 1])
        with col_mat: mat_manual = st.selectbox("🛠️ Material General", get_materiales_disponibles_cliente(), key="mat_manual_cliente")
        with col_aisl:
            st.markdown("<br>", unsafe_allow_html=True) 
            aislacion_manual = st.checkbox("🧊 Incluir Aislación Interior", key="chk_aisl_admin")
            forro_metalico_manual = st.checkbox("🛡️ Incluir Forro Metálico", key="chk_forro_admin")
        st.divider()
        st.markdown("#### 🛒 1. Agregar Piezas al Pedido")
        
        df_precios_m = get_precios_df_cliente()
        
        c_p1, c_p2 = st.columns([3, 1])
        with c_p1:
            opcion_desc = st.selectbox("Nombre de la Pieza", ["Seleccione..."] + LISTA_DESCRIPCIONES + ["Otra (Escribir manual)"], key="op_d_cli")
            desc_m = st.text_input("Escribir nombre de la pieza:") if opcion_desc == "Otra (Escribir manual)" else (opcion_desc if opcion_desc != "Seleccione..." else "")
        cant_m = c_p2.number_input("Cantidad", min_value=1, value=1, key="cant_m_cli")

        l_a = l_b = l_c = l_d = l_d_desv = l_h = diam = diam2 = ang = casq = sim = u_ent = u_sal = radio = ""
        
        if desc_m:
            req_fields = MAPEO_CAMPOS.get(desc_m, MAPEO_CAMPOS["Pieza especial"])
            
            with st.expander("📐 Dimensiones de Fabricación", expanded=True):
                col_inputs, col_img = st.columns([3, 2]) 
                
                with col_inputs:
                    if any(k in req_fields for k in ["A", "B", "C", "D", "d"]):
                        cg1 = st.columns(5)
                        if "A" in req_fields: l_a = cg1[0].text_input("Lado A (cm) *", placeholder="Ej: 50", key="a_cli")
                        if "B" in req_fields: l_b = cg1[1].text_input("Lado B (cm) *", placeholder="Ej: 30", key="b_cli")
                        lbl_c = "Lado C (cm)" if desc_m == "Pleno" else "Lado C (cm) *"
                        if "C" in req_fields: l_c = cg1[2].text_input(lbl_c, placeholder="Ej: 20", key="c_cli")
                        lbl_d = "Lado D (cm)" if desc_m == "Pleno" else "Lado D (cm) *"
                        if "D" in req_fields: l_d = cg1[3].text_input(lbl_d, placeholder="Ej: 20", key="d_cli")
                        if "d" in req_fields: l_d_desv = cg1[4].text_input("Desv. d (cm) *", placeholder="Ej: 10", key="desv_cli")
                    
                    if any(k in req_fields for k in ["H", "Dia1", "Dia2", "Angulo", "Radio", "Casquetes"]):
                        cg2 = st.columns(6)
                        if "H" in req_fields: l_h = cg2[0].text_input("Largo H (cm) *", placeholder="Ej: 150", key="h_cli")
                        lbl_dia1 = "Diámetro 1" if desc_m in ["Caja Difusora", "Caja Difusora Esp."] else "Diámetro 1 *"
                        if "Dia1" in req_fields: diam = cg2[1].text_input(lbl_dia1, placeholder="Ej: 25", key="di1_cli")
                        if "Dia2" in req_fields: diam2 = cg2[2].text_input("Diámetro 2 *", placeholder="Ej: 15", key="di2_cli")
                        if "Angulo" in req_fields: ang = cg2[3].text_input("Ángulo (°)", placeholder="Ej: 45", key="an_cli")
                        if "Radio" in req_fields: radio = cg2[4].text_input("Radio (cm) *", placeholder="Ej: 15", key="rad_cli")
                        if "Casquetes" in req_fields: casq = cg2[5].text_input("N° Casq", placeholder="Ej: 3", key="ca_cli")
                    
                    if any(k in req_fields for k in ["Simetria", "Entrada", "Salida"]):
                        cg3 = st.columns(3)
                        if "Simetria" in req_fields: sim = cg3[0].selectbox("Simetría *", [""] + LISTA_SIMETRIAS, key="si_cli")
                        if "Entrada" in req_fields: u_ent = cg3[1].selectbox("Unión Entrada *", [""] + LISTA_UNIONES, key="ue_cli")
                        if "Salida" in req_fields: u_sal = cg3[2].selectbox("Unión Salida *", [""] + LISTA_UNIONES, key="us_cli")

                with col_img:
                    st.markdown("<div style='text-align: center; color: #7f8c8d; font-size: 14px;'><b>Planos de Fabricación</b></div>", unsafe_allow_html=True)
                    try:
                        if desc_m == "Ducto Recto" and l_a and l_b and l_h:
                            a_val = float(str(l_a).replace(',', '.'))
                            b_val = float(str(l_b).replace(',', '.'))
                            h_val = float(str(l_h).replace(',', '.'))
                            if a_val > 0 and b_val > 0 and h_val > 0:
                                fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6, 3))
                                fig.patch.set_alpha(0.0)
                                ax1.patch.set_alpha(0.0)
                                rect1 = patches.Rectangle((-a_val/2, -b_val/2), a_val, b_val, linewidth=2, edgecolor='#2980b9', facecolor='#d4e6f1')
                                ax1.add_patch(rect1)
                                m1 = max(a_val, b_val)
                                ax1.set_xlim(-m1/2 - m1*0.2, m1/2 + m1*0.2)
                                ax1.set_ylim(-m1/2 - m1*0.2, m1/2 + m1*0.2)
                                ax1.set_aspect('equal'); ax1.axis('off')
                                ax1.text(0, -b_val/2 - m1*0.1, f"A: {a_val}", ha='center', fontsize=10, fontweight='bold')
                                ax1.text(-a_val/2 - m1*0.1, 0, f"B: {b_val}", va='center', rotation=90, fontsize=10, fontweight='bold')
                                ax1.set_title("Corte (A x B)", fontsize=11, color="#34495e", fontweight='bold')
                                
                                ax2.patch.set_alpha(0.0)
                                rect2 = patches.Rectangle((-a_val/2, 0), a_val, h_val, linewidth=2, edgecolor='#27ae60', facecolor='#d5f5e3')
                                ax2.add_patch(rect2)
                                m2 = max(a_val, h_val)
                                ax2.set_xlim(-m2/2 - m2*0.2, m2/2 + m2*0.2)
                                ax2.set_ylim(-h_val*0.1, h_val + h_val*0.1)
                                ax2.set_aspect('equal'); ax2.axis('off')
                                ax2.text(0, -h_val*0.08, f"A: {a_val}", ha='center', fontsize=10, fontweight='bold')
                                ax2.text(a_val/2 + m2*0.08, h_val/2, f"H: {h_val} cm", va='center', fontsize=10, fontweight='bold', color='#c0392b')
                                ax2.set_title("Planta (Largo H)", fontsize=11, color="#34495e", fontweight='bold')
                                st.pyplot(fig)
                                
                        elif desc_m in ["Codo", "Medio Codo"] and l_a and ang and radio:
                            a_val = float(str(l_a).replace(',', '.'))
                            ang_val = float(str(ang).replace(',', '.'))
                            r_in = float(str(radio).replace(',', '.')) 
                            if a_val > 0 and ang_val > 0 and r_in > 0:
                                fig, ax = plt.subplots(figsize=(4, 4))
                                fig.patch.set_alpha(0.0); ax.patch.set_alpha(0.0)
                                r_out = r_in + a_val
                                codo_patch = patches.Wedge((0,0), r_out, 0, ang_val, width=a_val, linewidth=2, edgecolor='#e67e22', facecolor='#fdebd0')
                                ax.add_patch(codo_patch)
                                ax.set_xlim(-r_out*0.2, r_out*1.2)
                                ax.set_ylim(-r_out*0.2, r_out*1.2)
                                ax.set_aspect('equal'); ax.axis('off')
                                ax.text(r_in + a_val/2, -r_out*0.05, f"A: {a_val} cm", ha='center', va='top', fontsize=10, fontweight='bold')
                                ax.text(0, 0, f"{ang_val}°", ha='right', va='top', fontsize=12, fontweight='bold', color='#c0392b')
                                ax.plot([0, r_in], [0, 0], color='black', linestyle='--', linewidth=1)
                                ax.text(r_in/2, r_out*0.05, f"R: {r_in}cm", ha='center', fontsize=9)
                                ax.set_title("Planta de Curvatura", fontsize=11, color="#34495e", fontweight='bold')
                                st.pyplot(fig)

                        elif desc_m == "Transformación" and l_a and l_b and l_c and l_d and l_h:
                            a_val = float(str(l_a).replace(',', '.'))
                            b_val = float(str(l_b).replace(',', '.'))
                            c_val = float(str(l_c).replace(',', '.'))
                            d_val = float(str(l_d).replace(',', '.'))
                            h_val = float(str(l_h).replace(',', '.'))
                            
                            if all(v > 0 for v in [a_val, b_val, c_val, d_val, h_val]):
                                fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6, 3))
                                fig.patch.set_alpha(0.0)
                                
                                ax1.patch.set_alpha(0.0)
                                rect_ab = patches.Rectangle((-a_val/2, -b_val/2), a_val, b_val, linewidth=2, edgecolor='#2980b9', facecolor='#d4e6f1', alpha=0.5)
                                rect_cd = patches.Rectangle((-c_val/2, -d_val/2), c_val, d_val, linewidth=2, edgecolor='#e67e22', facecolor='#fdebd0', alpha=0.6)
                                ax1.add_patch(rect_ab)
                                ax1.add_patch(rect_cd)
                                m1 = max(a_val, b_val, c_val, d_val)
                                ax1.set_xlim(-m1/2 - m1*0.2, m1/2 + m1*0.2)
                                ax1.set_ylim(-m1/2 - m1*0.2, m1/2 + m1*0.2)
                                ax1.set_aspect('equal'); ax1.axis('off')
                                ax1.text(0, -b_val/2 - m1*0.05, f"Boca 1 (A x B)", ha='center', fontsize=9, color='#2980b9', fontweight='bold')
                                ax1.text(0, d_val/2 + m1*0.05, f"Boca 2 (C x D)", ha='center', fontsize=9, color='#d35400', fontweight='bold')
                                ax1.set_title("Cortes Superpuestos", fontsize=11, color="#34495e", fontweight='bold')
                                
                                ax2.patch.set_alpha(0.0)
                                trap = patches.Polygon([(-a_val/2, 0), (a_val/2, 0), (c_val/2, h_val), (-c_val/2, h_val)], closed=True, linewidth=2, edgecolor='#27ae60', facecolor='#d5f5e3')
                                ax2.add_patch(trap)
                                m2 = max(a_val, c_val, h_val)
                                ax2.set_xlim(-m2/2 - m2*0.2, m2/2 + m2*0.2)
                                ax2.set_ylim(-h_val*0.1, h_val + h_val*0.1)
                                ax2.set_aspect('equal'); ax2.axis('off')
                                ax2.text(0, -h_val*0.08, f"A: {a_val}", ha='center', fontsize=10, fontweight='bold')
                                ax2.text(0, h_val + h_val*0.02, f"C: {c_val}", ha='center', fontsize=10, fontweight='bold')
                                ax2.text(max(a_val, c_val)/2 + m2*0.08, h_val/2, f"H: {h_val} cm", va='center', fontsize=10, fontweight='bold', color='#c0392b')
                                ax2.set_title("Planta (A -> C)", fontsize=11, color="#34495e", fontweight='bold')
                                
                                st.pyplot(fig)

                        elif "A" in req_fields and "B" in req_fields and l_a and l_b:
                            a_val = float(str(l_a).replace(',', '.'))
                            b_val = float(str(l_b).replace(',', '.'))
                            if a_val > 0 and b_val > 0:
                                fig, ax = plt.subplots(figsize=(3, 3))
                                fig.patch.set_alpha(0.0); ax.patch.set_alpha(0.0)
                                rect = patches.Rectangle((-a_val/2, -b_val/2), a_val, b_val, linewidth=3, edgecolor='#2980b9', facecolor='#d4e6f1')
                                ax.add_patch(rect)
                                max_dim = max(a_val, b_val)
                                ax.set_xlim(-max_dim/2 - max_dim*0.3, max_dim/2 + max_dim*0.3)
                                ax.set_ylim(-max_dim/2 - max_dim*0.3, max_dim/2 + max_dim*0.3)
                                ax.set_aspect('equal'); ax.axis('off')
                                ax.text(0, -b_val/2 - max_dim*0.1, f"A: {a_val} cm", ha='center', fontweight='bold')
                                ax.text(-a_val/2 - max_dim*0.1, 0, f"B: {b_val} cm", va='center', rotation=90, fontweight='bold')
                                st.pyplot(fig)
                                
                        elif "Dia1" in req_fields and diam:
                            d_val = float(str(diam).replace(',', '.'))
                            if d_val > 0:
                                fig, ax = plt.subplots(figsize=(3, 3))
                                fig.patch.set_alpha(0.0); ax.patch.set_alpha(0.0)
                                circulo = patches.Circle((0, 0), d_val/2, linewidth=3, edgecolor='#27ae60', facecolor='#d5f5e3')
                                ax.add_patch(circulo)
                                ax.set_xlim(-d_val/2 - d_val*0.3, d_val/2 + d_val*0.3)
                                ax.set_ylim(-d_val/2 - d_val*0.3, d_val/2 + d_val*0.3)
                                ax.set_aspect('equal'); ax.axis('off')
                                ax.text(0, -d_val/2 - d_val*0.1, f"Ø: {d_val} cm", ha='center', fontweight='bold')
                                st.pyplot(fig)
                        else:
                            st.info("💡 Ingresa medidas para ver el plano de fabricación.")
                    except ValueError:
                        st.caption("⏳ Esperando medidas válidas...")

            max_dim_cm = 0.0
            for val in [l_a, l_b, l_c, l_d, diam, diam2]:
                if val:
                    try: max_dim_cm = max(max_dim_cm, float(str(val).replace(',', '.')))
                    except: pass
            
            max_mm = max_dim_cm * 10
            esp_smacna = 0.5
            if max_mm > 1800: esp_smacna = 1.0
            elif max_mm > 1300: esp_smacna = 0.8
            elif max_mm > 1000: esp_smacna = 0.6

            cw1, cw2, cw3 = st.columns(3)
            with cw1:
                esp_m = st.number_input("Espesor (mm)", min_value=0.0, value=float(esp_smacna), step=0.1, key="esp_m_cli")
                st.caption(f"📏 Sugerido por Norma SMACNA (250 Pa): {esp_smacna} mm")
                
            with cw2:
                peso_teorico = calcular_peso_teorico(desc_m, l_a, l_b, l_c, l_d, l_h, diam, diam2, esp_m)
                if peso_teorico > 0:
                    peso_mostrar = peso_teorico * cant_m
                    lbl_ayuda = f"🧮 Cálculo Teórico"
                else:
                    conn_h = get_connection(); c_h = conn_h.cursor()
                    c_h.execute("SELECT peso_total, cantidad FROM items_pedido WHERE upper(descripcion)=? AND cantidad>0 AND peso_total>0", (desc_m.upper().strip(),))
                    rows = c_h.fetchall()
                    conn_h.close()
                    peso_hist = sum([r[0]/r[1] for r in rows])/len(rows) if rows else 0.0
                    peso_mostrar = peso_hist * cant_m
                    lbl_ayuda = f"💡 IA Historial" if peso_hist > 0 else "Sin datos para estimar"

                key_peso = f"peso_dyn_{desc_m}_{peso_mostrar}_{cant_m}"
                peso_m = st.number_input("⚖️ Peso Estimado (Kg)", min_value=0.0, value=float(peso_mostrar), format="%.2f", key=key_peso)
                st.caption(lbl_ayuda)
            
            with cw3:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("➕ Agregar Pieza a la Lista", use_container_width=True):
                    NOMBRES_CAMPOS = {
                        "A": "Lado A", "B": "Lado B", "C": "Lado C", "D": "Lado D", "d": "Desviación d",
                        "H": "Altura/Largo H", "Dia1": "Diámetro 1", "Dia2": "Diámetro 2", 
                        "Angulo": "Ángulo", "Casquetes": "N° Casquetes", "Simetria": "Simetría", 
                        "Entrada": "Unión Entrada", "Salida": "Unión Salida", "Radio": "Radio"
                    }
                    campos_llenos = {
                        "A": l_a, "B": l_b, "C": l_c, "D": l_d, "d": l_d_desv,
                        "H": l_h, "Dia1": diam, "Dia2": diam2, "Angulo": ang,
                        "Casquetes": casq, "Simetria": sim, "Entrada": u_ent, "Salida": u_sal,
                        "Radio": radio
                    }
                    
                    faltan = []
                    if opcion_desc not in ["Pieza especial", "Otra (Escribir manual)", "Seleccione..."]:
                        for req in req_fields:
                            if desc_m == "Pleno" and req in ["C", "D"]: continue 
                            if desc_m in ["Caja Difusora", "Caja Difusora Esp."] and req == "Dia1": continue 
                            if not str(campos_llenos.get(req, "")).strip(): faltan.append(NOMBRES_CAMPOS.get(req, req))
                    
                    if not desc_m.strip(): st.error("❌ Debes escribir o seleccionar el nombre de la pieza.")
                    elif faltan: st.error(f"❌ Faltan datos obligatorios para '{desc_m}': **{', '.join(faltan)}**")
                    else:
                        pu, tot, un, ori = buscar_precio_logica_cliente(desc_m, cant_m, peso_m, df_precios_m, mat_manual)
                        
                        dims_str = []
                        if l_a: dims_str.append(f"A:{l_a}cm")
                        if l_b: dims_str.append(f"B:{l_b}cm")
                        if l_c: dims_str.append(f"C:{l_c}cm")
                        if l_d: dims_str.append(f"D:{l_d}cm")
                        if l_d_desv: dims_str.append(f"d:{l_d_desv}cm")
                        if radio: dims_str.append(f"R:{radio}cm")
                        if l_h: dims_str.append(f"H:{l_h}cm")
                        
                        if diam and diam2: dims_str.append(f"Ø1:{diam} Ø2:{diam2}cm")
                        elif diam: dims_str.append(f"Ø:{diam}cm")
                        
                        partes_str = []
                        if dims_str: partes_str.append("Dim: " + " ".join(dims_str))
                        if ang: partes_str.append(f"Ang: {ang}°")
                        if casq: partes_str.append(f"Casq: {casq}")
                        if u_ent or u_sal: 
                            uniones = f"{u_ent} / {u_sal}".strip(" /")
                            partes_str.append(f"Unión: {uniones}")
                        if sim: partes_str.append(f"Simetría: {sim}")
                        
                        texto_final_medidas = " | ".join(partes_str)
                        
                        st.session_state.carrito_cliente.append({
                            "item_num": len(st.session_state.carrito_cliente) + 1,
                            "Descripción": desc_m.strip(), "Cantidad": cant_m, "Espesor": esp_m,
                            "Kg": peso_m, "Detalles/Medidas": texto_final_medidas, "material": mat_manual,
                            "unidad_cobro": un, "precio_unitario": pu, "total_linea": tot, "origen_precio": ori
                        })
                        st.success(f"✅ Pieza agregada exitosamente.")
                        st.rerun()

        st.divider()
        st.markdown("#### 📋 2. Resumen de Tu Pedido")
        
        if len(st.session_state.carrito_cliente) > 0:
            df_carrito = pd.DataFrame(st.session_state.carrito_cliente)
            st.dataframe(
                df_carrito[['item_num', 'Descripción', 'Detalles/Medidas', 'Cantidad', 'Espesor', 'Kg']], 
                column_config={"item_num": "Ítem N°"}, use_container_width=True, hide_index=True
            )

            col_b1, col_b2 = st.columns([1, 4])
            with col_b1:
                if st.button("🗑️ Borrar Última Pieza"):
                    st.session_state.carrito_cliente.pop()
                    st.rerun()

            peso_total_carrito = df_carrito['Kg'].sum()
            neto_total_carrito = df_carrito['total_linea'].sum()
            st.markdown(f"### ⚖️ Peso Estimado Total: {peso_total_carrito:,.2f} Kg")

            st.markdown("#### 📝 Información Adicional")
            comentarios_manual = st.text_area("Comentarios u Observaciones del Pedido", placeholder="Ej: Entregar por acceso lateral...", key="obs_m_cli_bottom")

            if st.button("🚀 Confirmar y Enviar Pedido al Taller", type="primary"):
                conn = get_connection(); c = conn.cursor()
                flim = pd.Timestamp(datetime.now()) + BusinessDay(5)
                fuente_guardado = "Portal Cliente (Manual)"
                if aislacion_manual: fuente_guardado += " (Aislación)"
                if forro_metalico_manual: fuente_guardado += " (Forro Metálico)"
                
                if len(st.session_state.tf_usuario) > 1:
                    obra_final = obra_manual
                    idx = st.session_state.obra_usuario.index(obra_final)
                    tf_final = st.session_state.tf_usuario[idx]
                    ceco_final = st.session_state.ceco_usuario[idx]
                elif len(st.session_state.tf_usuario) == 1:
                    obra_final = st.session_state.obra_usuario[0]
                    tf_final = st.session_state.tf_usuario[0]
                    ceco_final = st.session_state.ceco_usuario[0]
                else:
                    tf_final = tf_manual
                    obra_final = obra_manual
                    ceco_final = ceco_manual

                numero_oficial = obtener_siguiente_correlativo_obra(obra_final, tf_final)
                
                c.execute("INSERT INTO pedidos (num_pedido, tf, obra_codigo, ceco, quien_envia, fuente, fecha_recepcion, fecha_limite, total_neto_estimado, kg_estimados, kg_reales, m2_totales, estado, estado_plazo, nivel_urgencia, ruta_excel, observaciones, men) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (numero_oficial, tf_final, obra_final, ceco_final, st.session_state.nombre_usuario, fuente_guardado, datetime.now(), flim.date(), neto_total_carrito, peso_total_carrito, 0, 0, 'Pendiente', 'En Proceso', 'Normal', "Generado Manualmente", comentarios_manual, men_manual))
                pid = c.lastrowid

                for r in st.session_state.carrito_cliente:
                    c.execute("INSERT INTO items_pedido (pedido_id, item_numero, descripcion, cantidad, peso_total, espesor, material, unidad_cobro, precio_unitario, total_linea, origen_precio, detalles) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             (pid, r['item_num'], r['Descripción'], r['Cantidad'], r['Kg'], r['Espesor'], r['material'], r['unidad_cobro'], r['precio_unitario'], r['total_linea'], r['origen_precio'], r['Detalles/Medidas']))
                
                conn.commit(); conn.close()
                st.session_state.carrito_cliente = [] 
                    
                st.success(f"✅ ¡Pedido enviado con éxito al Taller! Se asignó el folio oficial: {numero_oficial}")
                st.balloons() 
                    
                import time
                time.sleep(2.5) 
                    
                st.rerun() 
        else: st.info("No hay piezas en este pedido todavía.")
    st.stop()


# ====================================================================
# VISTA EXCLUSIVA PARA ADMINISTRADOR Y GERENCIA (CENTRO DE COMANDO)
# ====================================================================
if st.session_state.rol == "gerencia":
    st.markdown("""
        <style>
            [data-testid="stSidebar"] {display: none !important;}
            [data-testid="collapsedControl"] {display: none !important;}
        </style>
    """, unsafe_allow_html=True)

st.markdown("<h1 style='color: #2c3e50;'>🏢 Centro de Comando Gerencial</h1>", unsafe_allow_html=True)
st.caption("Visión global de Producción y Mantenimiento de Activos.")

# --- TABS DE GERENCIA: SOLO DASHBOARD ---
tabs_admin = st.tabs(["📊 Dashboard de Producción"])

with tabs_admin[0]:
    st.subheader("🚥 Estatus de Fabricación en Taller")
    try:
        conn_estatus = get_connection()
        df_estatus = pd.read_sql("SELECT num_pedido, obra_codigo, estado, nivel_urgencia, fecha_recepcion, fecha_termino, estado_despacho FROM pedidos", conn_estatus)
        conn_estatus.close()

        if not df_estatus.empty:
            if 'estado_despacho' not in df_estatus.columns: df_estatus['estado_despacho'] = 'En Taller'
            df_estatus['estado_despacho'] = df_estatus['estado_despacho'].fillna('En Taller')
            
            df_pend = df_estatus[df_estatus['estado'] == 'Pendiente'].copy()
            if not df_pend.empty:
                df_pend['sort_urgencia'] = df_pend['nivel_urgencia'].apply(lambda x: 0 if str(x) == 'ALTA' else 1)
                df_pend['fecha_recepcion_dt'] = pd.to_datetime(df_pend['fecha_recepcion'], format='mixed', errors='coerce')
                df_pend = df_pend.sort_values(by=['sort_urgencia', 'fecha_recepcion_dt'])
                
                en_proceso_count = min(2, len(df_pend))
                pendientes_count = len(df_pend) - en_proceso_count
                nombres_en_proceso = df_pend.head(en_proceso_count)['num_pedido'].astype(str).tolist()
                texto_en_proceso = "Pedido(s): " + ", ".join(nombres_en_proceso)
            else:
                en_proceso_count = 0; pendientes_count = 0; texto_en_proceso = "Ninguno en máquina"

            df_listos = df_estatus[(df_estatus['estado'] == 'Terminado') & (df_estatus['estado_despacho'] != 'Despachado')]
            listos_count = len(df_listos)

            hoy_estatus = datetime.now()
            inicio_semana = (hoy_estatus - timedelta(days=hoy_estatus.weekday())).date()
            df_desp = df_estatus[(df_estatus['estado'] == 'Terminado') & (df_estatus['estado_despacho'] == 'Despachado')].copy()
            df_desp['fecha_termino_dt'] = pd.to_datetime(df_desp['fecha_termino'], format='mixed', errors='coerce').dt.date
            despachados_semana = len(df_desp[df_desp['fecha_termino_dt'] >= inicio_semana])

            c_est1, c_est2, c_est3, c_est4 = st.columns(4)
            c_est1.markdown(f'<div style="background-color:#f8d7da;padding:15px;border-radius:10px;border-left:5px solid #dc3545;height:100%;"><h5>⏳ En Cola</h5><h1>{pendientes_count}</h1><span style="font-size:12px;">A la espera de corte</span></div>', unsafe_allow_html=True)
            c_est2.markdown(f'<div style="background-color:#fff3cd;padding:15px;border-radius:10px;border-left:5px solid #ffc107;height:100%;"><h5>⚙️ En Proceso</h5><h1>{en_proceso_count}</h1><span style="font-size:12px;"><b>{texto_en_proceso}</b></span></div>', unsafe_allow_html=True)
            c_est3.markdown(f'<div style="background-color:#d4edda;padding:15px;border-radius:10px;border-left:5px solid #28a745;height:100%;"><h5>📦 Listos (Taller)</h5><h1>{listos_count}</h1><span style="font-size:12px;">Esperando retiro</span></div>', unsafe_allow_html=True)
            c_est4.markdown(f'<div style="background-color:#d1ecf1;padding:15px;border-radius:10px;border-left:5px solid #17a2b8;height:100%;"><h5>🚚 Despachados</h5><h1>{despachados_semana}</h1><span style="font-size:12px;">Entregados esta semana</span></div>', unsafe_allow_html=True)

    except Exception as e: st.error(f"Error cargando estatus: {e}")
        
    st.divider()

    st.subheader("📈 Rendimiento de Producción (EDP)")
    st.caption("Seleccione el rango de fechas para actualizar los indicadores y gráficos.")

    hoy = datetime.now()
    if hoy.day <= 20: 
        f_fin_def = date(hoy.year, hoy.month, 20)
        f_ini_def = (date(hoy.year, hoy.month, 1) - timedelta(days=1)).replace(day=21)
    else: 
        f_ini_def = date(hoy.year, hoy.month, 21)
        next_m = hoy.month+1 if hoy.month<12 else 1
        next_y = hoy.year if hoy.month<12 else hoy.year+1
        f_fin_def = date(next_y, next_m, 20)

    col_f1, col_f2 = st.columns(2)
    f_ini = col_f1.date_input("🗓️ Inicio de Periodo", value=f_ini_def)
    f_fin = col_f2.date_input("🗓️ Fin de Periodo", value=f_fin_def)

    try:
        conn_p = get_connection()
        df_ped = pd.read_sql("SELECT * FROM pedidos WHERE estado='Terminado'", conn_p)
        df_items = pd.read_sql("SELECT * FROM items_pedido", conn_p)
        
        # 🔥 ESCUDO DE LIMPIEZA CONTRA ESPACIOS OCULTOS
        df_ped.columns = [str(c).lower().strip() for c in df_ped.columns]
        df_items.columns = [str(c).lower().strip() for c in df_items.columns]

        if 'num_pedido' in df_ped.columns:
            df_ped['num_pedido'] = df_ped['num_pedido'].astype(str).str.strip().str.upper()
        if 'num_pedido' in df_items.columns:
            df_items['num_pedido'] = df_items['num_pedido'].astype(str).str.strip().str.upper()
            
        conn_p.close()
        
        if not df_ped.empty:
            df_ped['fecha_termino'] = pd.to_datetime(df_ped['fecha_termino'], format='mixed', errors='coerce').dt.date
            mask = (df_ped['fecha_termino'] >= f_ini) & (df_ped['fecha_termino'] <= f_fin)
            df_ped_filtrado = df_ped[mask].copy()
            
            if not df_ped_filtrado.empty:
                df_full = pd.merge(df_items, df_ped_filtrado, left_on='pedido_id', right_on='id')
                
                df_full['factor'] = np.where(
                    (df_full['kg_reales'] > 0) & (df_full['kg_estimados'] > 0),
                    df_full['kg_reales'] / df_full['kg_estimados'],
                    1.0
                )
                df_full['peso_ajustado'] = df_full['peso_total'] * df_full['factor']

                mask_un = df_full['unidad_cobro'].str.lower() == 'un'
                df_full['total_linea_ajustado'] = df_full['total_linea']
                df_full.loc[~mask_un, 'total_linea_ajustado'] *= df_full.loc[~mask_un, 'factor']
                
                total_kilos = df_ped_filtrado['kg_reales'].sum()
                valor_edp = df_full['total_linea_ajustado'].sum()

                st.markdown("<br>", unsafe_allow_html=True)
                kpi_col1, kpi_col2 = st.columns(2)
                
                html_card_1 = f"""
                <div style="background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); padding: 25px; border-radius: 15px; color: white; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                    <h3 style="margin:0; font-size: 20px; font-weight: normal;">⚖️ Kilos Totales Fabricados</h3>
                    <h1 style="margin:5px 0 0 0; font-size: 40px; font-weight: bold;">{total_kilos:,.1f} Kg</h1>
                </div>
                """
                html_card_2 = f"""
                <div style="background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); padding: 25px; border-radius: 15px; color: white; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                    <h3 style="margin:0; font-size: 20px; font-weight: normal;">💰 Valorización Real (EDP)</h3>
                    <h1 style="margin:5px 0 0 0; font-size: 40px; font-weight: bold;">$ {valor_edp:,.0f}</h1>
                </div>
                """
                kpi_col1.markdown(html_card_1, unsafe_allow_html=True)
                kpi_col2.markdown(html_card_2, unsafe_allow_html=True)
                st.markdown("<br>", unsafe_allow_html=True)
                
                col_g1, col_g2 = st.columns(2)
                with col_g1:
                    st.markdown("##### 🏢 Kilos por Obra (Desglose)")
                    df_obras = df_ped_filtrado.groupby('obra_codigo')['kg_reales'].sum().reset_index()
                    chart_obras = alt.Chart(df_obras).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5).encode(
                        x=alt.X('obra_codigo:N', title='Obra', sort='-y', axis=alt.Axis(labelAngle=-45)),
                        y=alt.Y('kg_reales:Q', title='Kg Reales'),
                        color=alt.Color('obra_codigo:N', legend=None, scale=alt.Scale(scheme='tableau10')), 
                        tooltip=['obra_codigo', 'kg_reales']
                    ).properties(height=350)
                    text_obras = chart_obras.mark_text(align='center', baseline='bottom', dy=-5, fontSize=12, fontWeight='bold').encode(text=alt.Text('kg_reales:Q', format='.0f'))
                    st.altair_chart((chart_obras + text_obras), use_container_width=True)
                    
                with col_g2:
                    st.markdown("##### 📈 Evolución Diaria de Entrega")
                    df_timeline = df_ped_filtrado.groupby('fecha_termino')['kg_reales'].sum().reset_index()
                    chart_line = alt.Chart(df_timeline).mark_area(
                        line={'color':'#2980b9'},
                        color=alt.Gradient(gradient='linear', stops=[alt.GradientStop(color='#3498db', offset=0), alt.GradientStop(color='rgba(255,255,255,0)', offset=1)], x1=1, x2=1, y1=1, y2=0)
                    ).encode(
                        x=alt.X('fecha_termino:T', title='Fecha de Cierre'), y=alt.Y('kg_reales:Q', title='Kilos Terminados'),
                        tooltip=[alt.Tooltip('fecha_termino:T', title='Fecha', format='%d-%m-%Y'), alt.Tooltip('kg_reales:Q', title='Kilos')]
                    ).properties(height=350).interactive()
                    points = alt.Chart(df_timeline).mark_circle(size=60, color='#e74c3c').encode(x='fecha_termino:T', y='kg_reales:Q', tooltip=[alt.Tooltip('fecha_termino:T', title='Fecha', format='%d-%m-%Y'), alt.Tooltip('kg_reales:Q', title='Kilos')])
                    text_line = alt.Chart(df_timeline).mark_text(align='center', baseline='bottom', dy=-10, fontSize=12, fontWeight='bold', color='#2c3e50').encode(x='fecha_termino:T', y='kg_reales:Q', text=alt.Text('kg_reales:Q', format='.0f'))
                    st.altair_chart(chart_line + points + text_line, use_container_width=True)
            else: st.info(f"No hay pedidos terminados registrados entre el {f_ini.strftime('%d/%m/%Y')} y el {f_fin.strftime('%d/%m/%Y')}.")
        else: st.warning("No hay pedidos en la base de datos de Producción.")
    except Exception as e: st.error(f"Error cargando dashboard de producción: {e}")

    st.divider()

    st.subheader("👷 Estado Histórico de Activos del Taller")
    st.caption("Selecciona un día para ver cómo estaban las máquinas en esa fecha exacta.")
    fecha_foto = st.date_input("📸 Fecha de Evaluación de Máquinas", value=datetime.now().date())

    try:
        conn_m = get_connection()
        df_maq = pd.read_sql("SELECT id, nombre, foto_path FROM maquinas", conn_m)
        df_insp = pd.read_sql("SELECT maquina_id, fecha_hora, repuesto_necesario FROM registros_inspeccion ORDER BY fecha_hora DESC", conn_m)
        conn_m.close()
        
        if not df_maq.empty:
            inicio_semana_foto = fecha_foto - timedelta(days=fecha_foto.weekday())
            df_insp['fecha_dt'] = pd.to_datetime(df_insp['fecha_hora'], format='mixed', errors='coerce')
            limite_tiempo = pd.to_datetime(fecha_foto) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1) 
            df_insp_foto = df_insp[df_insp['fecha_dt'] <= limite_tiempo].copy()
            
            count_op, count_pen, count_falla = 0, 0, 0
            estados_maq = {}
            for _, maq in df_maq.iterrows():
                mid = maq['id']
                recs = df_insp_foto[df_insp_foto['maquina_id'] == mid]
                if recs.empty:
                    estados_maq[mid] = {'txt': 'Sin Registros en esa fecha', 'color': '#7f8c8d', 'icon': '⚪'}
                    count_pen += 1
                else:
                    ultima_inspeccion = recs.iloc[0]
                    fecha_ult = ultima_inspeccion['fecha_dt'].date()
                    if fecha_ult >= inicio_semana_foto:
                        if ultima_inspeccion['repuesto_necesario'] == 1:
                            estados_maq[mid] = {'txt': 'Con Falla', 'color': '#e74c3c', 'icon': '🔴'}; count_falla += 1
                        else:
                            estados_maq[mid] = {'txt': 'Operativa (Al Día)', 'color': '#27ae60', 'icon': '🟢'}; count_op += 1
                    else:
                        estados_maq[mid] = {'txt': 'Revisión Pendiente', 'color': '#f39c12', 'icon': '🟡'}; count_pen += 1

            st.markdown("##### 📊 Resumen del Día Seleccionado")
            c_res1, c_res2, c_res3 = st.columns(3)
            c_res1.metric("🟢 Máquinas Operativas", count_op)
            c_res2.metric("🟡 Revisiones Pendientes", count_pen)
            c_res3.metric("🔴 En Falla", count_falla)
            st.markdown("<br>", unsafe_allow_html=True)
            
            cols = st.columns(4)
            for i, (_, maq) in enumerate(df_maq.iterrows()):
                mid = maq['id']
                stat = estados_maq[mid]
                ruta_img = maq['foto_path']
                with cols[i % 4]:
                    with st.container(border=True):
                        if pd.notna(ruta_img) and os.path.exists(ruta_img):
                            with open(ruta_img, "rb") as f: b64 = base64.b64encode(f.read()).decode()
                            st.markdown(f'<img src="data:image/png;base64,{b64}" style="width:100%; height:150px; object-fit:cover; border-radius:5px;">', unsafe_allow_html=True)
                        else: st.markdown('<div style="width:100%; height:150px; background-color:#ecf0f1; border-radius:5px; display:flex; align-items:center; justify-content:center; color:#bdc3c7;">Sin foto</div>', unsafe_allow_html=True)
                        st.markdown(f"**{mid}**")
                        st.markdown(f"<h5>{stat['icon']} <span style='color: {stat['color']};'>{stat['txt']}</span></h5>", unsafe_allow_html=True)
        else: st.info("No hay máquinas registradas en el sistema.")
    except Exception as e: st.error(f"Error cargando base de Mantenimiento: {e}")

    if st.session_state.rol == "gerencia":
        st.divider()
        st.subheader("📋 Conglomerado Total de Pedidos")
        st.caption("🔒 Modo Solo Lectura: Listado completo histórico de todas las obras.")
        try:
            conn_g = get_connection()
            query_gerencia = """
            SELECT num_pedido as 'N° Pedido', tf as 'TF', obra_codigo as 'Obra', 
            quien_envia as 'Solicitante', estado as 'Estado', fecha_recepcion as 'Ingreso', 
            kg_estimados as 'Kg Est.', kg_reales as 'Kg Reales' 
            FROM pedidos ORDER BY id DESC
            """
            df_todos = pd.read_sql(query_gerencia, conn_g)
            conn_g.close()
            st.dataframe(df_todos, use_container_width=True, hide_index=True)
        except Exception as e: st.error(f"Error cargando la base de datos para gerencia: {e}")