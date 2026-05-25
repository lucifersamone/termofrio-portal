import streamlit as st
import pandas as pd
import sqlite3
import os
import tempfile
from fpdf import FPDF
import matplotlib.pyplot as plt
from datetime import datetime, date, timedelta
from pandas.tseries.offsets import BusinessDay
import numpy as np
import urllib.parse 
import altair as alt
import io
import matplotlib.patches as patches
import psycopg2
import re

# --- ADAPTADOR INVISIBLE PARA SUPABASE (VERSION 2.0 ENFIERRADA) ---
class SQLiteToPostgresCursor:
    def __init__(self, pg_cursor):
        self.pg_cursor = pg_cursor
        
    def execute(self, query, vars=None):
        # 1. Traducir variables: '?' de SQLite a '%s' de Postgres
        if vars is not None:
            query = query.replace('?', '%s')
            
        # 2. Reparar comillas en alias: Cambia AS 'N° Pedido' por AS "N° Pedido"
        query = re.sub(r"(?i)\bas\s+'([^']+)'", r'AS "\1"', query)
        
        # 3. Reparar corchetes: Cambia [tabla] o [columna] por comillas dobles
        query = query.replace('[', '"').replace(']', '"')
        
        return self.pg_cursor.execute(query, vars)
        
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
    def cursor(self):
        return SQLiteToPostgresCursor(self.conn.cursor())
    def commit(self):
        self.conn.commit()
    def close(self):
        self.conn.close()
    def __getattr__(self, name):
        return getattr(self.conn, name)

# --- LA FUNCIÓN QUE RECONOCERÁ TU CÓDIGO ---
def get_connection(): 
    return SupabaseSQLAdapter()

def limpiar_texto(text):
    """Limpia caracteres especiales que causan errores en PDFs."""
    if not isinstance(text, str): text = str(text)
    mapping = {"–": "-", "—": "-", "…": "...", "“": '"', "”": '"', "‘": "'", "’": "'"}
    for char, replacement in mapping.items(): text = text.replace(char, replacement)
    return text.encode("latin-1", "replace").decode("latin-1")

# --- 🔐 SEGURIDAD UNIFICADA CON ROLES ---
if 'logged_in' not in st.session_state or not st.session_state.logged_in:
    st.warning("⚠️ Acceso Restringido. Por favor inicie sesión en la pantalla Principal.")
    st.stop()

if st.session_state.get('rol') == 'cliente':
    st.error("🔒 Acceso denegado. Este portal es de uso exclusivo para administración de taller.")
    st.stop()

# --- RUTAS Y CARPETAS (Adaptadas para la Nube) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
DB_PATH = os.path.join(ROOT_DIR, 'produccion_v55_master.db')
DIR_RECURSOS = os.path.join(ROOT_DIR, 'firma_timbre') 
FIRMA_PATH = os.path.join(DIR_RECURSOS, 'firma.png')
TIMBRE_PATH = os.path.join(DIR_RECURSOS, 'timbre.png')
LOGO_PATH = os.path.join(DIR_RECURSOS, 'termofriologo.jpg')
ISO_PATH = os.path.join(DIR_RECURSOS, 'tfiso.jpg')
CARPETA_EXCELS = os.path.join(ROOT_DIR, 'excels_guardados') 

os.makedirs(CARPETA_EXCELS, exist_ok=True)

CONTRASEÑA_EXCEL = "termofrio" 
PASS_ADMIN_GENERAL = "adminprecios"

# --- LISTAS DESPLEGABLES ESTANDARIZADAS ---
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

LISTA_SIMETRIAS = [
    "Asimétrica", "Inferior Parejo", "Pareja Der. - Inf. Pareja",
    "Pareja Der. - Simétrica", "Pareja Der. - Sup. Pareja",
    "Pareja Izq. - Inf. Pareja", "Pareja Izq. - Simétrica",
    "Pareja Izq. - Sup. Pareja", "Simétrica - Inf. Pareja",
    "Simétrica - Simétrica", "Simétrica - Sup. Pareja",
    "Simétrico", "Superior Parejo", "Cuadrado"
]

LISTA_UNIONES = [
    "Balleta", "Copla Rodón", "Embutido", "Escu. - Recar. 25", "Escuadra",
    "Flange", "Liso", "Malla", "Pestaña 15", "Pestaña 25", "Pestaña 30",
    "Pestaña 40", "Pestaña 50", "TDF", "Triple 50", "Triple 60",
    "Tapa ciega", "Tapa c/collarin"
]

MAPEO_CAMPOS = {
    "Ducto Recto": ["A", "B", "H", "Entrada", "Salida"],
    "Codo": ["A", "B", "Simetria", "Angulo", "Entrada", "Salida"],
    "Codo Transfor.": ["A", "B", "Simetria", "C", "D", "Angulo", "Entrada", "Salida"],
    "Medio Codo": ["A", "B", "Simetria", "Angulo", "Entrada", "Salida"],
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

# --- ADAPTADOR INVISIBLE PARA SUPABASE (VERSION 2.2 CON TRADUCTOR DE TIPOS NUMÉRICOS) ---
class SQLiteToPostgresCursor:
    def __init__(self, pg_cursor):
        self.pg_cursor = pg_cursor
        
    def execute(self, query, vars=None):
        # 1. Traducir variables: '?' de SQLite a '%s' de Postgres
        if vars is not None:
            query = query.replace('?', '%s')
            
            # 🔥 PIEZA CLAVE: Convierte formatos numéricos de ingeniería (NumPy/Pandas) 
            # a números nativos de Python para evitar el error 'InvalidSchemaName'
            cleaned_vars = []
            for v in vars:
                if hasattr(v, 'item') and callable(getattr(v, 'item')):
                    cleaned_vars.append(v.item()) # .item() extrae el número puro sin el "np.float64"
                else:
                    cleaned_vars.append(v)
            vars = tuple(cleaned_vars)
            
        # 2. Reparar comillas en alias: Cambia AS 'N° Pedido' por AS "N° Pedido"
        query = re.sub(r"(?i)\bas\s+'([^']+)'", r'AS "\1"', query)
        
        # 3. Reparar corchetes: Cambia [tabla] o [columna] por comillas dobles
        query = query.replace('[', '"').replace(']', '"')
        
        # 4. Mapeo de tablas: Cambia automáticamente "pedidos" por "pedidostf"
        query = re.sub(r'(?i)\bpedidos\b', 'pedidostf', query)
        
        return self.pg_cursor.execute(query, vars)
        
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
        # Guarda de inmediato y evita que el Pooler corte la conexión
        self.conn.autocommit = True
        
    def cursor(self):
        return SQLiteToPostgresCursor(self.conn.cursor())

    def commit(self):
        # Desactivado porque autocommit=True ya hace el trabajo solo
        pass

    def close(self):
        self.conn.close()

    def __getattr__(self, name):
        return getattr(self.conn, name)

# --- LA FUNCIÓN MAESTRA ---
def get_connection(): 
    return SupabaseSQLAdapter()

# --- MAGIA: EL MOTOR BLINDADO QUE TOMA EL CORRELATIVO CORRECTO ---
def obtener_siguiente_correlativo_obra(obra_codigo, tf):
    """Busca el número de pedido más alto para una obra específica y devuelve el siguiente con prefijo OT."""
    conn = get_connection()
    c = conn.cursor()
    
    # Blindaje contra espacios en blanco o valores nulos
    obra_segura = obra_codigo if (obra_codigo and str(obra_codigo).strip() != "" and obra_codigo != "Seleccione Obra...") else "NULO_OBRA_XYZ"
    tf_seguro = tf if (tf and str(tf).strip() != "") else "NULO_TF_XYZ"
    
    c.execute("SELECT num_pedido FROM pedidos WHERE obra_codigo = ? OR tf = ? ORDER BY id DESC LIMIT 1", (obra_segura, tf_seguro))
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

def actualizar_bd_estructuras():
    conn = get_connection(); c = conn.cursor()
    try: c.execute("ALTER TABLE pedidos ADD COLUMN nivel_urgencia TEXT DEFAULT 'Normal'")
    except: pass 
    try: c.execute("ALTER TABLE pedidos ADD COLUMN ruta_excel TEXT")
    except: pass
    try: c.execute("ALTER TABLE pedidos ADD COLUMN observaciones TEXT DEFAULT ''") 
    except: pass
    try: c.execute("ALTER TABLE pedidos ADD COLUMN men TEXT DEFAULT ''") 
    except: pass
    try: c.execute("ALTER TABLE pedidos ADD COLUMN estado_despacho TEXT DEFAULT 'En Taller'") 
    except: pass
    try: c.execute("ALTER TABLE pedidos ADD COLUMN fecha_despacho DATE") 
    except: pass
    try: c.execute("ALTER TABLE items_pedido ADD COLUMN detalles TEXT")
    except: pass
    try: c.execute('''CREATE TABLE IF NOT EXISTS directorio_solicitantes (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE, correo TEXT)''')
    except: pass
    try: c.execute('''CREATE TABLE IF NOT EXISTS maestro_obras (tf TEXT, ceco TEXT, nombre TEXT)''')
    except: pass
    for col in ['kg_contrato', 'kg_adicionales', 'kg_historicos', 'kg_hist_galv', 'kg_hist_fe', 'kg_hist_inox']:
        try: c.execute(f"ALTER TABLE maestro_obras ADD COLUMN {col} REAL DEFAULT 0.0")
        except: pass
    conn.commit(); conn.close()

actualizar_bd_estructuras() 

def get_precios_df():
    conn = get_connection()
    try: df = pd.read_sql("SELECT * FROM lista_precios", conn)
    except: df = pd.DataFrame()
    conn.close()
    return df

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

def get_materiales_disponibles():
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT DISTINCT material FROM lista_precios WHERE material != 'Pieza Especial'", conn)
        materiales = df['material'].dropna().unique().tolist()
    except: materiales = []
    conn.close()
    if "Galvanizado" not in materiales: materiales.insert(0, "Galvanizado")
    return sorted(materiales)

def buscar_precio_logica_v39(desc, cant, peso, df_precios, material_seleccionado):
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
        
        # --- AQUÍ ESTÁ EL CAMBIO PARA LOS CENTÍMETROS ---
        h = float(str(l_h).replace(',','.')) / 100 if l_h else 0.0
        
        d1 = float(str(diam).replace(',','.')) / 100 if diam else 0.0
        d2 = float(str(diam2).replace(',','.')) / 100 if diam2 else 0.0
        espesor = float(esp)

        area = 0.0
        desc_upper = str(desc).upper()

        if "RECTO" in desc_upper or "ALETA" in desc_upper or "TEMPLADOR" in desc_upper:
            area = 2 * (a + b) * h
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
        elif "S " in desc_upper or " S " in desc_upper:
            area = 2 * (a + b) * h * 1.2
        elif "TAPA" in desc_upper or "PLANCHA" in desc_upper:
            area = a * b
        else:
            if h > 0 and (a > 0 or d1 > 0): 
                area = 2 * (a + b) * h if a > 0 else 3.1416 * d1 * h
            else: 
                area = a * b
        
        peso_base = area * espesor * 8.0 
        return peso_base * 1.15 
    except Exception as e:
        return 0.0

def calcular_semaforo(row):
    if row['estado'] == 'Terminado': return "✅ Finalizado"
    try:
        limite = pd.to_datetime(row['fecha_limite'], format='mixed', errors='coerce').date()
        hoy = datetime.now().date()
        dias = (limite - hoy).days
        if dias < 0: return "🔴 VENCIDO"
        elif dias <= 2: return "🟡 Por Vencer"
        else: return "🟢 En Plazo"
    except: return "⚪ Error"

def procesar_pedido(archivo, df_precios, material_default):
    xls = pd.ExcelFile(archivo)
    enc = {"obra":"", "num":"", "envia":"", "fecha":None, "m2": 0.0, "tf": ""}
    items = []
    hoja_items = None
    for h in xls.sheet_names:
        if "HOJA DE PEDIDO" in h.upper(): hoja_items = h; break
    if not hoja_items:
        for h in xls.sheet_names:
            if "DISEÑO" in h.upper() or "DISENO" in h.upper(): hoja_items = h; break
    if not hoja_items and xls.sheet_names: hoja_items = xls.sheet_names[0]
    
    for h in xls.sheet_names:
        if "DISEÑO" in h.upper() or "DISENO" in h.upper():
            try:
                df_temp = pd.read_excel(xls, sheet_name=h, header=None)
                tf_c = df_temp.iloc[5, 3] 
                if not pd.isna(tf_c): enc["tf"] = str(tf_c).replace(".0", "").strip()
            except: pass; break
            
    if hoja_items:
        try:
            df = pd.read_excel(xls, sheet_name=hoja_items, header=None)
            if not enc["tf"]:
                try: enc["tf"] = str(df.iloc[5, 3]).replace(".0", "").strip()
                except: pass
            try:
                enc["obra"] = str(df.iloc[5, 6]); enc["num"] = str(df.iloc[6, 6]); enc["envia"] = str(df.iloc[7, 6]) 
                enc["m2"] = pd.to_numeric(df.iloc[7, 34], errors='coerce') or 0.0
            except: pass
            
            row_h = -1; col_d = 8; col_c = 10; col_p = 32; col_esp = 30 
            for r in range(20):
                for c in range(df.shape[1]):
                    v = str(df.iloc[r, c]).upper()
                    if "DESCRIPCI" in v: row_h = r; col_d = c
                    if "CANT" in v and "." in v: col_c = c
                    if "KILOS" in v: col_p = c
                    if "ESP" in v or "MM" in v: col_esp = c
                if row_h != -1: break
            if row_h == -1: row_h = 10 
            
            for r in range(row_h+1, len(df)):
                desc = str(df.iloc[r, col_d]).strip()
                if desc == "nan" or desc == "" or "TOTAL" in desc.upper(): continue
                inum = df.iloc[r, 0] if not pd.isna(df.iloc[r, 0]) else df.iloc[r, 2]
                cnt = pd.to_numeric(df.iloc[r, col_c], errors='coerce') or 0.0
                pes = pd.to_numeric(df.iloc[r, col_p], errors='coerce') or 0.0
                esp = pd.to_numeric(df.iloc[r, col_esp], errors='coerce') or 0.0
                if cnt == 0 and pes == 0: continue
                pu, tot, un, ori = buscar_precio_logica_v39(desc, cnt, pes, df_precios, material_default)
                items.append({"item_num":inum, "descripcion":desc, "cantidad":cnt, "espesor":esp, "peso_total":pes, "material": material_default, "unidad_cobro":un, "precio_unitario":pu, "total_linea":tot, "origen_precio":ori})
        except: pass
    
    df_result = pd.DataFrame(items)
    return enc, df_result


# --- LÓGICA DE PDF DE DOCUMENTOS NATIVA ---
def generar_pdf_manual(pedido_num, tf, obra, ceco, solicitante, items_df, kg_reales, fuente="", observaciones="", tipo="despacho", men=""):
    """Generador de PDF profesional y compatible con Nube."""
    clean_id = str(pedido_num).replace("/", "-").replace("\\", "-").strip()
    temp_dir = tempfile.gettempdir()
    prefijo = "Orden_Trabajo" if tipo == "interna" else "Pedido_Despacho"
    ruta_pdf = os.path.join(temp_dir, f"{prefijo}_{clean_id}.pdf")

    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    
    # Encabezado
    pdf.set_font("Arial", "B", 16)
    titulo = "ORDEN DE TRABAJO INTERNA" if tipo == "interna" else "ORDEN DE FABRICACION Y DESPACHO"
    pdf.cell(0, 10, limpiar_texto(f"{titulo} - TERMOFRIO"), ln=True, align="C")
    
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 8, limpiar_texto(f"Pedido: {pedido_num} | Obra: {obra} | TF: {tf}"), ln=True)
    pdf.ln(5)
    
    # Tabla
    pdf.set_font("Arial", "B", 9)
    pdf.cell(15, 8, "Item", border=1, align="C")
    pdf.cell(80, 8, "Descripcion", border=1)
    pdf.cell(100, 8, "Medidas/Detalles", border=1)
    pdf.cell(20, 8, "Cant.", border=1, align="C")
    pdf.cell(20, 8, "Kg", border=1, align="C", ln=True)
    
    pdf.set_font("Arial", "", 9)
    for _, fila in items_df.iterrows():
        pdf.cell(15, 6, limpiar_texto(str(fila.get('item_numero', ''))), border=1, align="C")
        pdf.cell(80, 6, limpiar_texto(str(fila.get('descripcion', '')))[:45], border=1)
        pdf.cell(100, 6, limpiar_texto(str(fila.get('detalles', '')))[:60], border=1)
        pdf.cell(20, 6, str(fila.get('cantidad', '')), border=1, align="C")
        peso = fila.get('peso_total', 0)
        pdf.cell(20, 6, f"{float(peso) if peso else 0:.2f}", border=1, align="C", ln=True)
        
    pdf.output(ruta_pdf)
    return ruta_pdf

def generar_pdf_firmado(ticket_id, kg_reales=0):
    """Wrapper para extraer datos de BD y llamar al generador."""
    conn = get_connection()
    try:
        ped = pd.read_sql(f"SELECT * FROM pedidos WHERE num_pedido = '{ticket_id}'", conn)
        if ped.empty: return None
        items = pd.read_sql(f"SELECT * FROM items_pedido WHERE pedido_id = {ped.iloc[0]['id']}", conn)
        return generar_pdf_manual(
            pedido_num=ticket_id,
            tf=ped.iloc[0]['tf'],
            obra=ped.iloc[0]['obra_codigo'],
            ceco=ped.iloc[0]['ceco'],
            solicitante=ped.iloc[0]['quien_envia'],
            items_df=items,
            kg_reales=kg_reales,
            observaciones=ped.iloc[0]['observaciones'],
            tipo="despacho",
            men=ped.iloc[0]['men']
        )
    finally:
        conn.close()


# --- INTERFAZ PRINCIPAL ---
st.title("📦 Producción - Termofrio SPA")
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📥 Ingreso", "📋 Gestión & Cierre", "⚙️ Configuración", "📊 Informes EDP", "📈 Dashboard"])

with tab1:
    st.header("Gestión de Nuevos Pedidos")
    
    t_excel, t_manual = st.tabs(["📁 Carga Rápida por Excel", "✍️ Ingreso Manual de Piezas"])
    
    with t_excel:
        mats_db = get_materiales_disponibles()
        material_sel = st.selectbox("🛠️ Material del Pedido (Excel)", mats_db, key="mat_excel_admin")
        arch_ped = st.file_uploader("Sube Excel Pedido", type=["xls", "xlsx", "xlsm"])
        if arch_ped:
            enc, df_det = procesar_pedido(arch_ped, get_precios_df(), material_sel)
            if df_det.empty: st.error("❌ Sin items válidos detectados.")
            else:
                ceco_bd, obra_bd = buscar_datos_por_tf(enc['tf'])
                c1, c2, c3, c4 = st.columns(4)
                with c1: st.text_input("TF Detectado", value=enc['tf'], disabled=True)
                with c2: obra_input = st.text_input("Obra Oficial", value=obra_bd if obra_bd else enc['obra'])
                with c3: ceco_input = st.text_input("CECO Oficial", value=ceco_bd if ceco_bd else "")
                with c4: m2_input = st.number_input("M2 Totales", value=enc['m2'], format="%.2f")
                
                c5, c6 = st.columns(2)
                with c5: quien = st.text_input("Solicitante", value=enc['envia'])
                with c6: fuente = st.text_input("Fuente / Etiqueta", value="General")
                
                edited_df = st.data_editor(df_det, use_container_width=True, num_rows="dynamic")
                neto = edited_df['total_linea'].sum(); peso = edited_df['peso_total'].sum()
                st.markdown(f"### 💰 Neto: $ {neto:,.0f} | ⚖️ Peso: {peso:,.1f} Kg")
                
                if st.button("💾 Guardar Pedido (Excel)", type="primary"):
                    
                    # --- MAGIA AQUÍ: Ignoramos el número del Excel y calculamos el correcto ---
                    numero_oficial = obtener_siguiente_correlativo_obra(obra_input, enc['tf'])

                    nombre_seguro = str(numero_oficial).replace("/", "-").replace("\\", "-")
                    fecha_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                    ruta_guardado = os.path.join(CARPETA_EXCELS, f"Pedido_Local_{nombre_seguro}_{fecha_str}.xlsx")
                    
                    with open(ruta_guardado, "wb") as f:
                        f.write(arch_ped.getvalue())

                    conn = get_connection(); c = conn.cursor()
                    flim = pd.Timestamp(datetime.now()) + BusinessDay(5)
                    c.execute("INSERT INTO pedidos (num_pedido, tf, obra_codigo, ceco, quien_envia, fuente, fecha_recepcion, fecha_limite, total_neto_estimado, kg_estimados, kg_reales, m2_totales, estado, estado_plazo, nivel_urgencia, ruta_excel, observaciones, men) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", 
                             (numero_oficial, enc['tf'], obra_input, ceco_input, quien, fuente, datetime.now(), flim.date(), neto, peso, 0, m2_input, 'Pendiente', 'En Proceso', 'Normal', ruta_guardado, "", ""))
                    pid = c.lastrowid
                    for _,r in edited_df.iterrows():
                        c.execute("INSERT INTO items_pedido (pedido_id, item_numero, descripcion, cantidad, peso_total, espesor, material, unidad_cobro, precio_unitario, total_linea, origen_precio) VALUES (?,?,?,?,?,?,?,?,?,?,?)", 
                                 (pid, r['item_num'], r['descripcion'], r['cantidad'], r['peso_total'], r['espesor'], r['material'], r['unidad_cobro'], r['precio_unitario'], r['total_linea'], r['origen_precio']))
                    conn.commit(); conn.close()
                    st.success(f"✅ ¡Guardado correctamente en DB y Bóveda como el pedido {numero_oficial}!"); st.rerun()

    with t_manual:
        if 'carrito_admin' not in st.session_state:
            st.session_state.carrito_admin = []

        st.info("Formulario Inteligente: Selecciona la pieza y el sistema solo te pedirá las dimensiones necesarias.")
        
        df_obras_m = get_obras_ceco_df()
        lista_obras = ["Seleccione Obra..."] + df_obras_m['nombre'].tolist() if not df_obras_m.empty else ["Seleccione Obra..."]
        
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            tf_manual = st.text_input("Código TF ó CC (Ej: 13655 o CC02)")
            ceco_auto, obra_auto = buscar_datos_por_tf(tf_manual)
            index_obra = 0
            if obra_auto and obra_auto in lista_obras: index_obra = lista_obras.index(obra_auto)
            obra_manual = st.selectbox("🏗️ Obra Destino", lista_obras + ["Otra (Escribir manual)"], index=index_obra)
            if obra_manual == "Otra (Escribir manual)": obra_manual = st.text_input("Escribir nombre de la obra:", value=obra_auto if obra_auto else "")

        with col_m2:
            num_manual = st.text_input("N° de Pedido (Automático)", value="Se asignará automáticamente", disabled=True)
            
            default_ceco_admin = ceco_auto if ceco_auto else ""
            if tf_manual.strip().upper() == "CC02":
                default_ceco_admin = "4-02-002 EXTRAS"
                
            ceco_manual = st.text_input("CECO (Opcional)", value=default_ceco_admin)
            men_manual = st.text_input("MEN (Opcional)")
            
        with col_m3:
            quien_manual = st.text_input("👤 Solicitante (OBLIGATORIO)")
            correo_manual = st.text_input("📧 Correo Electrónico (OBLIGATORIO)")
            
        col_mat, col_aisl = st.columns([2, 1])
        with col_mat: mat_manual = st.selectbox("🛠️ Material General", get_materiales_disponibles(), key="mat_manual_admin")
        with col_aisl:
            st.markdown("<br>", unsafe_allow_html=True) 
            aislacion_manual = st.checkbox("🧊 Incluir Aislación Interior", key="chk_aisl_admin")
            forro_metalico_manual = st.checkbox("🛡️ Incluir Forro Metálico", key="chk_forro_admin")

        st.divider()
        st.markdown("#### 🛒 1. Agregar Piezas al Pedido")
        
        df_precios_m = get_precios_df()
        
        c_p1, c_p2 = st.columns([3, 1])
        with c_p1:
            opcion_desc = st.selectbox("Nombre de la Pieza", ["Seleccione..."] + LISTA_DESCRIPCIONES + ["Otra (Escribir manual)"])
            desc_m = st.text_input("Escribir nombre de la pieza:") if opcion_desc == "Otra (Escribir manual)" else (opcion_desc if opcion_desc != "Seleccione..." else "")
        cant_m = c_p2.number_input("Cantidad", min_value=1, value=1, key="cant_m")

        l_a = l_b = l_c = l_d = l_d_desv = l_h = diam = diam2 = ang = casq = sim = u_ent = u_sal = ""
        
        if desc_m:
            req_fields = MAPEO_CAMPOS.get(desc_m, MAPEO_CAMPOS["Pieza especial"])
            
            with st.expander("📐 Dimensiones de Fabricación", expanded=True):
                if any(k in req_fields for k in ["A", "B", "C", "D", "d"]):
                    cg1 = st.columns(5)
                    if "A" in req_fields: l_a = cg1[0].text_input("Lado A (cm) *", placeholder="Ej: 50")
                    if "B" in req_fields: l_b = cg1[1].text_input("Lado B (cm) *", placeholder="Ej: 30")
                    
                    lbl_c = "Lado C (cm)" if desc_m == "Pleno" else "Lado C (cm) *"
                    if "C" in req_fields: l_c = cg1[2].text_input(lbl_c, placeholder="Ej: 20")
                    
                    lbl_d = "Lado D (cm)" if desc_m == "Pleno" else "Lado D (cm) *"
                    if "D" in req_fields: l_d = cg1[3].text_input(lbl_d, placeholder="Ej: 20")
                    
                    if "d" in req_fields: l_d_desv = cg1[4].text_input("Desviación d (cm) *", placeholder="Ej: 10")
                
                if any(k in req_fields for k in ["H", "Dia1", "Dia2", "Angulo", "Casquetes"]):
                    cg2 = st.columns(5)
                    
                    if "H" in req_fields: l_h = cg2[0].text_input("Altura/Largo H (cm) *", placeholder="Ej: 150")
                    
                    lbl_dia1 = "Diámetro 1 (cm)" if desc_m in ["Caja Difusora", "Caja Difusora Esp."] else "Diámetro 1 (cm) *"
                    if "Dia1" in req_fields: diam = cg2[1].text_input(lbl_dia1, placeholder="Ej: 25")
                    
                    if "Dia2" in req_fields: diam2 = cg2[2].text_input("Diámetro 2 (cm) *", placeholder="Ej: 15")
                    if "Angulo" in req_fields: ang = cg2[3].text_input("Ángulo (°)", placeholder="Ej: 45")
                    if "Casquetes" in req_fields: casq = cg2[4].text_input("N° Casquetes", placeholder="Ej: 3")
                
                if any(k in req_fields for k in ["Simetria", "Entrada", "Salida"]):
                    cg3 = st.columns(3)
                    if "Simetria" in req_fields: sim = cg3[0].selectbox("Simetría *", [""] + LISTA_SIMETRIAS)
                    if "Entrada" in req_fields: u_ent = cg3[1].selectbox("Unión Entrada *", [""] + LISTA_UNIONES)
                    if "Salida" in req_fields: u_sal = cg3[2].selectbox("Unión Salida *", [""] + LISTA_UNIONES)

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
                esp_m = st.number_input("Espesor (mm)", min_value=0.0, value=float(esp_smacna), step=0.1, key="esp_m")
                st.caption(f"📏 Sugerido por Norma SMACNA (250 Pa): {esp_smacna} mm")
                
            with cw2:
                # --- MAGIA EN TIEMPO REAL PARA EL PESO ---
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
                        "Entrada": "Unión Entrada", "Salida": "Unión Salida"
                    }
                    
                    campos_llenos = {
                        "A": l_a, "B": l_b, "C": l_c, "D": l_d, "d": l_d_desv,
                        "H": l_h, "Dia1": diam, "Dia2": diam2, "Angulo": ang,
                        "Casquetes": casq, "Simetria": sim, "Entrada": u_ent, "Salida": u_sal
                    }
                    
                    faltan = []
                    if opcion_desc not in ["Pieza especial", "Otra (Escribir manual)", "Seleccione..."]:
                        for req in req_fields:
                            if desc_m == "Pleno" and req in ["C", "D"]: continue 
                            if desc_m in ["Caja Difusora", "Caja Difusora Esp."] and req == "Dia1": continue 
                            if not str(campos_llenos.get(req, "")).strip():
                                faltan.append(NOMBRES_CAMPOS.get(req, req))
                    
                    if not desc_m.strip():
                        st.error("❌ Debes escribir o seleccionar el nombre de la pieza.")
                    elif faltan:
                        st.error(f"❌ No puedes agregar esta pieza. Faltan datos obligatorios para '{desc_m}': **{', '.join(faltan)}**")
                    else:
                        pu, tot, un, ori = buscar_precio_logica_v39(desc_m, cant_m, peso_m, df_precios_m, mat_manual)
                        
                        dims_str = []
                        if l_a: dims_str.append(f"A:{l_a}cm")
                        if l_b: dims_str.append(f"B:{l_b}cm")
                        if l_c: dims_str.append(f"C:{l_c}cm")
                        if l_d: dims_str.append(f"D:{l_d}cm")
                        if l_d_desv: dims_str.append(f"d:{l_d_desv}cm")
                        
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
                        
                        st.session_state.carrito_admin.append({
                            "item_num": len(st.session_state.carrito_admin) + 1,
                            "Descripción": desc_m.strip(),
                            "Cantidad": cant_m,
                            "Espesor": esp_m,
                            "Kg": peso_m,
                            "Detalles/Medidas": texto_final_medidas,
                            "material": mat_manual,
                            "unidad_cobro": un,
                            "precio_unitario": pu,
                            "total_linea": tot,
                            "origen_precio": ori
                        })
                        st.success(f"✅ Pieza agregada exitosamente.")
                        st.rerun()

                        st.divider()
        st.markdown("#### 📋 2. Resumen del Pedido Manual")
        
        if len(st.session_state.carrito_admin) > 0:
            df_carrito = pd.DataFrame(st.session_state.carrito_admin)
            
            st.dataframe(
                df_carrito[['item_num', 'Descripción', 'Detalles/Medidas', 'Cantidad', 'Espesor', 'Kg']], 
                column_config={"item_num": "Ítem N°"},
                use_container_width=True, hide_index=True
            )

            col_b1, col_b2 = st.columns([1, 4])
            with col_b1:
                if st.button("🗑️ Borrar Última Pieza"):
                    st.session_state.carrito_admin.pop()
                    st.rerun()

            peso_total_carrito = df_carrito['Kg'].sum()
            neto_total_carrito = df_carrito['total_linea'].sum()
            st.markdown(f"### ⚖️ Peso Estimado Total: {peso_total_carrito:,.2f} Kg")

            st.markdown("#### 📝 Información Adicional")
            comentarios_manual = st.text_area("Comentarios u Observaciones del Pedido", placeholder="Ej: Entregar por acceso lateral...", key="obs_admin_bottom")

            if st.button("🚀 Confirmar y Guardar Pedido Manual", type="primary"):
                if obra_manual == "Seleccione Obra..." or not quien_manual.strip() or not correo_manual.strip():
                    st.error("❌ Falta información: Obra, Solicitante y Correo son campos obligatorios.")
                else:
                    
                    # --- MAGIA AQUÍ TAMBIÉN ---
                    numero_oficial = obtener_siguiente_correlativo_obra(obra_manual, tf_manual)

                    conn = get_connection(); c = conn.cursor()
                    
                    c.execute("INSERT OR REPLACE INTO directorio_solicitantes (nombre, correo) VALUES (?, ?)", (quien_manual.strip(), correo_manual.strip()))

                    flim = pd.Timestamp(datetime.now()) + BusinessDay(5)
                    fuente_guardado = "Generado Manualmente Taller"
                    if aislacion_manual: fuente_guardado += " (Aislación)"
                    if forro_metalico_manual: fuente_guardado += " (Forro Metálico)"
                    
                    c.execute("INSERT INTO pedidos (num_pedido, tf, obra_codigo, ceco, quien_envia, fuente, fecha_recepcion, fecha_limite, total_neto_estimado, kg_estimados, kg_reales, m2_totales, estado, estado_plazo, nivel_urgencia, ruta_excel, observaciones, men) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (numero_oficial, tf_manual, obra_manual, ceco_manual, quien_manual, fuente_guardado, datetime.now(), flim.date(), neto_total_carrito, peso_total_carrito, 0, 0, 'Pendiente', 'En Proceso', 'Normal', "Generado Manualmente", comentarios_manual, men_manual))
                    pid = c.lastrowid

                    for r in st.session_state.carrito_admin:
                        c.execute("INSERT INTO items_pedido (pedido_id, item_numero, descripcion, cantidad, peso_total, espesor, material, unidad_cobro, precio_unitario, total_linea, origen_precio, detalles) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (pid, r['item_num'], r['Descripción'], r['Cantidad'], r['Kg'], r['Espesor'], r['material'], r['unidad_cobro'], r['precio_unitario'], r['total_linea'], r['origen_precio'], r['Detalles/Medidas']))
                    
                    conn.commit(); conn.close()
                    st.session_state.carrito_admin = [] 
                    st.success(f"✅ ¡Pedido manual creado como {numero_oficial} y enviado a la cola de fabricación!")
        else:
            st.info("No hay piezas en este pedido todavía.")

with tab2:
    st.header("📋 Gestión de Pedidos y Urgencias")
    conn = get_connection(); dfp = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", conn); conn.close()
    
    if not dfp.empty:
        dfp['Alerta'] = dfp.apply(calcular_semaforo, axis=1)
        
        filtro = st.radio("Ver registros de Base de Datos:", ["Pendientes", "Terminados", "Todos"], horizontal=True)
        if filtro == "Pendientes": dfv = dfp[dfp['estado']=='Pendiente']
        elif filtro == "Terminados": dfv = dfp[dfp['estado']=='Terminado']
        else: dfv = dfp
        
        cols_view = ['Alerta', 'num_pedido', 'tf', 'obra_codigo', 'quien_envia', 'nivel_urgencia', 'fecha_recepcion', 'fecha_limite', 'kg_estimados', 'kg_reales', 'estado']
        columnas_finales = [c for c in cols_view if c in dfv.columns]
        st.dataframe(dfv[columnas_finales], use_container_width=True, hide_index=True)
        
        # --- VISOR DE DETALLES Y MEDIDAS EN PANTALLA ---
        st.markdown("---")
        st.markdown("#### 🔍 Ver Detalle y Medidas de un Pedido")
        st.caption("Selecciona un pedido para ver exactamente qué piezas y medidas trae antes de fabricar.")
        col_b1, col_b2 = st.columns([1, 2])
        
        with col_b1:
            pedido_a_ver = st.selectbox("Seleccionar Pedido:", dfp['num_pedido'].astype(str) + " / " + dfp['obra_codigo'], key="ver_detalles_ped")
            fila_pedido_ver = dfp[dfp['num_pedido'].astype(str) + " / " + dfp['obra_codigo'] == pedido_a_ver].iloc[0]
            id_ver = fila_pedido_ver['id']
            
        with col_b2:
            st.markdown("<br>", unsafe_allow_html=True)
            conn_ver = get_connection()
            df_items_raw = pd.read_sql(f"SELECT * FROM items_pedido WHERE pedido_id={id_ver}", conn_ver)
            
            obs_query = pd.read_sql(f"SELECT observaciones, men FROM pedidos WHERE id={id_ver}", conn_ver)
            obs_txt = obs_query.iloc[0]['observaciones'] if not obs_query.empty else ""
            men_txt = obs_query.iloc[0]['men'] if not obs_query.empty and 'men' in obs_query.columns else ""
            conn_ver.close()

        if not df_items_raw.empty:
            df_items_display = df_items_raw[['item_numero', 'descripcion', 'detalles', 'cantidad', 'espesor', 'peso_total']].rename(columns={
                'item_numero': 'Ítem', 'descripcion': 'Pieza', 'detalles': 'Medidas y Especificaciones', 'cantidad': 'Cant.', 'espesor': 'Espesor (mm)', 'peso_total': 'Peso (Kg)'
            })
            st.dataframe(df_items_display, use_container_width=True, hide_index=True)
            
          # --- Alerta visual en pantalla de MEN, Comentarios y EXTRAS ---
            alertas_ui = []
            if "Aislación" in str(fila_pedido_ver['fuente']): alertas_ui.append("🧊 AISLACIÓN INTERIOR")
            if "Forro Metálico" in str(fila_pedido_ver['fuente']): alertas_ui.append("🛡️ FORRO METÁLICO")

            if alertas_ui or men_txt.strip() or obs_txt.strip():
                msj = ""
                if alertas_ui: msj += f"**🚨 ATENCIÓN:** Este pedido incluye **{' y '.join(alertas_ui)}**\n\n"
                if men_txt.strip(): msj += f"**📍 MEN:** {men_txt}  \n"
                if obs_txt.strip(): msj += f"**📝 Comentarios:** {obs_txt}"
                st.warning(msj)

            # --- BOTONES DE IMPRESIÓN PARA TALLER ---
            st.markdown("##### 🖨️ Documentos para Taller (Impresión)")
            col_doc1, col_doc2 = st.columns(2)
            
            with col_doc1:
                if st.button("📄 Generar Orden de Trabajo (PDF)", key="btn_ot_interna"):
                    with st.spinner("Generando Orden de Trabajo..."):
                        ruta_pdf_ot = generar_pdf_manual(
                            pedido_num=fila_pedido_ver['num_pedido'],
                            tf=fila_pedido_ver['tf'],
                            obra=fila_pedido_ver['obra_codigo'],
                            ceco=fila_pedido_ver['ceco'],
                            solicitante=fila_pedido_ver['quien_envia'],
                            items_df=df_items_raw, 
                            kg_reales=0, 
                            fuente=fila_pedido_ver['fuente'],
                            observaciones=obs_txt,
                            tipo="interna",
                            men=men_txt
                        )
                        if ruta_pdf_ot:
                            with open(ruta_pdf_ot, "rb") as f:
                                st.download_button("📥 Descargar Orden de Trabajo", f, file_name=f"Orden_Trabajo_{fila_pedido_ver['num_pedido']}.pdf")
            
            with col_doc2:
                 ruta_ex = str(fila_pedido_ver.get('ruta_excel', ''))
                 if ruta_ex != "Generado Manualmente" and pd.notna(ruta_ex) and os.path.exists(ruta_ex):
                     with open(ruta_ex, "rb") as f:
                         st.download_button("📥 Descargar Excel Original", f, file_name=os.path.basename(ruta_ex))

        else:
            st.info("No hay piezas en este pedido o es un formato antiguo.")

        st.divider()

        st.subheader("🚀 Fila de Producción y Urgencias")
        pend_fifo = dfp[dfp['estado']=='Pendiente'].copy()
        terminados_hist = dfp[dfp['estado'] == 'Terminado'].copy()
        
        if not terminados_hist.empty:
            terminados_hist['dias_demora'] = (pd.to_datetime(terminados_hist['fecha_termino'], format='mixed', errors='coerce') - pd.to_datetime(terminados_hist['fecha_recepcion'], format='mixed', errors='coerce')).dt.days
            terminados_hist['dias_demora'] = terminados_hist['dias_demora'].apply(lambda x: 1 if pd.isna(x) or x <= 0 else x)
            promedio_dias_real = round(terminados_hist['dias_demora'].mean(), 1)
        else:
            promedio_dias_real = 2.0

        if not pend_fifo.empty:
            c_urg1, c_urg2 = st.columns([3, 1])
            with c_urg1:
                pedido_a_cambiar = st.selectbox("Cambiar nivel de prioridad del pedido:", pend_fifo['num_pedido'].astype(str) + " / " + pend_fifo['obra_codigo'])
                id_urgencia = pend_fifo[pend_fifo['num_pedido'].astype(str) + " / " + pend_fifo['obra_codigo'] == pedido_a_cambiar].iloc[0]['id']
            with c_urg2:
                nuevo_nivel = st.radio("Estado:", ["Normal", "ALTA"], horizontal=True)
                if st.button("Aplicar Nivel", key="btn_ap_nivel"):
                    conn = get_connection(); c = conn.cursor()
                    c.execute("UPDATE pedidos SET nivel_urgencia=? WHERE id=?", (nuevo_nivel, int(id_urgencia)))
                    conn.commit(); conn.close(); st.success("Prioridad actualizada"); st.rerun()

            pend_fifo['sort_urgencia'] = pend_fifo['nivel_urgencia'].apply(lambda x: 0 if str(x) == 'ALTA' else 1)
            pend_fifo['fecha_recepcion'] = pd.to_datetime(pend_fifo['fecha_recepcion'], format='mixed', errors='coerce')
            pend_fifo = pend_fifo.sort_values(by=['sort_urgencia', 'fecha_recepcion'])
            pend_fifo['Turno_Fila'] = range(1, len(pend_fifo) + 1)
            
            def calcular_entrega(row):
                dias_carga = row['Turno_Fila'] * 0.5
                dias_redondeados = int(np.ceil(dias_carga))
                base_date = max(row['fecha_recepcion'], pd.Timestamp(datetime.now())) if not pd.isna(row['fecha_recepcion']) else pd.Timestamp(datetime.now())
                return (base_date + BusinessDay(dias_redondeados)).date()
                
            pend_fifo['Entrega Estimada'] = pend_fifo.apply(calcular_entrega, axis=1)

            st.dataframe(pend_fifo[['Turno_Fila', 'nivel_urgencia', 'num_pedido', 'obra_codigo', 'quien_envia', 'fecha_recepcion', 'Entrega Estimada']], use_container_width=True, hide_index=True)

            with st.expander("Ver Herramienta de Correos y Notificaciones", expanded=False):
                st.markdown("##### ✉️ PASO 1: Notificar Programación al Cliente")
                st.info(f"El promedio de entrega histórico del taller es de **{promedio_dias_real} días**.")
                sel_p = st.selectbox("Seleccionar Pedido a notificar:", pend_fifo['num_pedido'].astype(str) + " / " + pend_fifo['obra_codigo'])
                d = pend_fifo[pend_fifo['num_pedido'].astype(str) + " / " + pend_fifo['obra_codigo'] == sel_p].iloc[0]
                
                solicitante_db = str(d.get('quien_envia', '')).strip()
                correo_destino = ""
                if solicitante_db and solicitante_db != "nan":
                    try:
                        conn_c = get_connection()
                        df_correo = pd.read_sql(f"SELECT correo FROM directorio_solicitantes WHERE nombre='{solicitante_db}'", conn_c)
                        conn_c.close()
                        if not df_correo.empty: correo_destino = str(df_correo.iloc[0]['correo']).strip()
                    except: pass

                asunto_correo = f"Programación de Fabricación - Pedido N° {d['num_pedido']} - Obra {d['obra_codigo']}"
                fecha_est_str = d['Entrega Estimada'].strftime('%d/%m/%Y')
                
                texto_html = f"""Estimados,\n
Junto con saludar, informamos que su pedido ha sido ingresado exitosamente a nuestro sistema y se encuentra en cola de fabricación.\n
Para garantizar la equidad y transparencia, la producción se programa estrictamente por orden de llegada.\n
Actualmente, su pedido se encuentra en el Turno N° {d['Turno_Fila']} de nuestra fila de pendientes.\n\n
Información importante de plazos:\n
- El promedio histórico de respuesta de nuestro taller es de {promedio_dias_real} días de fabricación.\n
- El plazo máximo estandarizado es de hasta 5 días hábiles.\n\n
➡️ En base a la carga de trabajo actual, la fecha estimada de entrega para su pedido es el {fecha_est_str}\n\n
Agradecemos su comprensión.\nDepartamento de Producción - Termofrio SPA"""
                
                if correo_destino: st.success(f"✅ Se asoció el correo: {correo_destino}")
                else: st.warning(f"⚠️ No se encontró correo para '{solicitante_db}'. Puedes agregarlo en la pestaña de Configuración.")

                if correo_destino:
                    subj_enc = urllib.parse.quote(asunto_correo)
                    body_enc = urllib.parse.quote(texto_html)
                    mailto_url = f"mailto:{correo_destino}?subject={subj_enc}&body={body_enc}"
                    st.link_button("📧 Enviar Notificación por Correo", mailto_url, type="primary")

        st.divider()

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("✅ PASO 2: Cerrar Pedido (Taller)")
            st.caption("Ingresa los Kilos Reales de lo fabricado para finalizarlo.")
            pend = dfp[dfp['estado']=='Pendiente']
            if not pend.empty:
                sel_cierre = st.selectbox("Seleccionar Pedido a Cerrar:", pend['num_pedido'].astype(str) + " / " + pend['obra_codigo'])
                id_c = pend[pend['num_pedido'].astype(str) + " / " + pend['obra_codigo']==sel_cierre].iloc[0]['id']
                peso_r = st.number_input("Peso Real Fabricado (Kg)", min_value=0.0, format="%.2f")
                fecha_c = st.date_input("Fecha Término", value=datetime.now())
                if st.button("Confirmar Cierre de Pedido", key="btn_cierre", type="primary"):
                    conn=get_connection(); c=conn.cursor()
                    c.execute("UPDATE pedidos SET estado='Terminado', fecha_termino=?, kg_reales=? WHERE id=?", (fecha_c, peso_r, int(id_c)))
                    conn.commit(); conn.close(); st.success("Cerrado y guardado en historial."); st.rerun()

        with c2:
            st.subheader("📄 PASO 3: Generar PDF Final de Despacho")
            st.caption("Generación automática del PDF finalizado.")
            term = dfp[dfp['estado']=='Terminado']
            if not term.empty:
                sel_pdf = st.selectbox("Seleccionar Pedido Terminado:", term['num_pedido'].astype(str) + " / " + term['obra_codigo'])
                
                if st.button("🚀 Procesar PDF Automático", key="btn_proc_pdf"):
                    fila_pdf = term[term['num_pedido'].astype(str) + " / " + term['obra_codigo']==sel_pdf].iloc[0]
                    
                    with st.spinner("Generando PDF Oficial de Despacho..."):
                        ruta_pdf = generar_pdf_firmado(ticket_id=fila_pdf['num_pedido'], kg_reales=fila_pdf['kg_reales'])
                        if ruta_pdf:
                            st.session_state.pdf_tmp = ruta_pdf
                            st.session_state.pdf_num = fila_pdf['num_pedido']
                            st.session_state.pdf_obra = fila_pdf['obra_codigo']
                            st.session_state.pdf_solic = str(fila_pdf.get('quien_envia', '')).strip()
                            st.session_state.pdf_kg = fila_pdf['kg_reales']
                            st.success("✅ Archivo PDF Generado exitosamente.")
                        else:
                            st.error("❌ Error al generar el PDF.")
                
                if 'pdf_tmp' in st.session_state and os.path.exists(st.session_state.pdf_tmp):
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    with open(st.session_state.pdf_tmp, "rb") as f:
                        st.download_button("📥 1. Descargar PDF a mi PC", f, file_name=f"Pedido_Despacho_{st.session_state.pdf_num}.pdf", key="btn_dl_pdf", type="primary")
                    
                    correo_dest = ""
                    try:
                        conn_c = get_connection()
                        df_c = pd.read_sql(f"SELECT correo FROM directorio_solicitantes WHERE nombre='{st.session_state.pdf_solic}'", conn_c)
                        conn_c.close()
                        if not df_c.empty: correo_dest = str(df_c.iloc[0]['correo']).strip()
                    except: pass

                    html_despacho = f"""Estimados,\n
Junto con saludar, informamos que su Pedido N° {st.session_state.pdf_num} (Obra: {st.session_state.pdf_obra}) se encuentra terminado y listo para retiro/despacho.\n
⚖️ Peso Total Fabricado: {st.session_state.pdf_kg} Kg.\n
Favor recordar adjuntar el documento PDF oficial descargado de la plataforma a este correo para el respaldo.\n
Quedamos a su disposición para coordinar la entrega.\n\nSaludos cordiales,\nDepartamento de Producción - Termofrio SPA"""
                    
                    st.info("⚠️ Descarga el PDF primero usando el botón de arriba, y luego adjúntalo manualmente en tu correo.")
                    
                    if correo_dest:
                        subj_enc = urllib.parse.quote(f"Pedido Listo para Retiro/Despacho - N° {st.session_state.pdf_num} - Obra {st.session_state.pdf_obra}")
                        body_enc = urllib.parse.quote(html_despacho)
                        mailto_url = f"mailto:{correo_dest}?subject={subj_enc}&body={body_enc}"
                        st.link_button("📧 2. Abrir Borrador de Correo", mailto_url)

        st.divider()
        st.subheader("🚚 PASO 4: Registrar Salida a Terreno (Despacho)")
        st.caption("Marca los pedidos que ya fueron retirados físicamente del taller para descontarlos de la tarjeta de Listos en Taller.")
        
        # Prevenimos nulos en pedidos antiguos
        if 'estado_despacho' not in dfp.columns: dfp['estado_despacho'] = 'En Taller'
        dfp['estado_despacho'] = dfp['estado_despacho'].fillna('En Taller')
        
        df_listos_taller = dfp[(dfp['estado'] == 'Terminado') & (dfp['estado_despacho'] != 'Despachado')].copy()
        
        if not df_listos_taller.empty:
            c_desp1, c_desp2 = st.columns([3, 1])
            with c_desp1:
                sel_despacho = st.selectbox("Seleccionar Pedido Entregado / Retirado:", df_listos_taller['num_pedido'].astype(str) + " / " + df_listos_taller['obra_codigo'])
            with c_desp2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("Marcar como Despachado 🚚", type="primary", use_container_width=True):
                    id_despacho = df_listos_taller[df_listos_taller['num_pedido'].astype(str) + " / " + df_listos_taller['obra_codigo'] == sel_despacho].iloc[0]['id']
                    conn = get_connection(); c = conn.cursor()
                    fecha_hoy = datetime.now().date()
                    c.execute("UPDATE pedidos SET estado_despacho='Despachado', fecha_despacho=? WHERE id=?", (fecha_hoy, int(id_despacho)))
                    conn.commit(); conn.close()
                    st.success("¡Pedido marcado como despachado!")
                    st.rerun()
        else:
            st.info("Todos los pedidos terminados ya han sido despachados a terreno.")

        st.divider()
        with st.expander("Borrar Pedido"):
            dfp['display_del'] = "ID: " + dfp['id'].astype(str) + " | Pedido: " + dfp['num_pedido'].astype(str) + " | Obra: " + dfp['obra_codigo'].astype(str)
            dels = st.selectbox("Seleccione el pedido exacto a borrar:", dfp['display_del'])
            if st.button("Eliminar Definitivamente", key="btn_elim_ped_bd"):
                idd = int(dels.split("ID: ")[1].split(" |")[0])
                conn=get_connection();c=conn.cursor()
                c.execute("DELETE FROM items_pedido WHERE pedido_id=?",(idd,))
                c.execute("DELETE FROM pedidos WHERE id=?",(idd,))
                conn.commit();conn.close();st.rerun()

# --- PESTAÑA 3: CONFIGURACIÓN Y MAESTROS ---
with tab3:
    st.header("⚙️ Configuración y Maestros")
    c1, c2 = st.columns(2)
    with c1: 
        st.markdown("##### 💰 Lista de Precios")
        st.dataframe(get_precios_df(), use_container_width=True, hide_index=True)
    with c2: 
        st.markdown("##### 🏗️ Obras, Contratos e Historial por Material")
        st.info("💡 Haz doble clic en las celdas para editar el Contrato, Adicionales o Kg Históricos por material y presiona Guardar.")
        
        conn = get_connection()
        try: df_obras = pd.read_sql("SELECT tf, ceco, nombre, kg_contrato, kg_adicionales, kg_historicos, kg_hist_galv, kg_hist_fe, kg_hist_inox FROM maestro_obras", conn)
        except: 
            df_obras = pd.read_sql("SELECT * FROM maestro_obras", conn)
            for col in ['kg_contrato', 'kg_adicionales', 'kg_hist_galv', 'kg_hist_fe', 'kg_hist_inox', 'kg_historicos']:
                if col not in df_obras.columns: df_obras[col] = 0.0
        conn.close()
        
        for col in ['kg_contrato', 'kg_adicionales', 'kg_hist_galv', 'kg_hist_fe', 'kg_hist_inox', 'kg_historicos']:
            df_obras[col] = pd.to_numeric(df_obras[col], errors='coerce').fillna(0.0)

        edited_obras = st.data_editor(
            df_obras,
            column_config={
                "tf": st.column_config.TextColumn("TF", disabled=True),
                "ceco": st.column_config.TextColumn("CECO", disabled=True),
                "nombre": st.column_config.TextColumn("Nombre", disabled=True),
                "kg_contrato": st.column_config.NumberColumn("Base Contrato", step=100.0, format="%.1f"),
                "kg_adicionales": st.column_config.NumberColumn("Adicionales", step=100.0, format="%.1f"),
                "kg_hist_galv": st.column_config.NumberColumn("Hist. Galv", step=10.0, format="%.1f"),
                "kg_hist_fe": st.column_config.NumberColumn("Hist. Fe", step=10.0, format="%.1f"),
                "kg_hist_inox": st.column_config.NumberColumn("Hist. Inox", step=10.0, format="%.1f"),
                "kg_historicos": None 
            },
            hide_index=True,
            use_container_width=True,
            key="editor_obras_contratos_mat"
        )
        
        if st.button("💾 Guardar Kilos (Contratos, Adicionales e Historial)", type="primary"):
            conn = get_connection(); c = conn.cursor()
            for _, row in edited_obras.iterrows():
                k_hist_antiguo = float(row.get('kg_historicos', 0.0))
                c.execute("UPDATE maestro_obras SET kg_contrato=?, kg_adicionales=?, kg_hist_galv=?, kg_hist_fe=?, kg_hist_inox=?, kg_historicos=? WHERE tf=?", 
                          (float(row['kg_contrato']), float(row['kg_adicionales']), float(row['kg_hist_galv']), float(row['kg_hist_fe']), float(row['kg_hist_inox']), k_hist_antiguo, row['tf']))
            conn.commit(); conn.close()
            st.success("✅ ¡Kilos actualizados correctamente!")
            st.rerun()
    
    st.divider()
    st.subheader("🔐 Panel de Administración")
    pwd = st.text_input("Pass Admin", type="password")
    
    if pwd == PASS_ADMIN_GENERAL:
        c_up1, c_up2 = st.columns(2)
        with c_up1:
            st.markdown("##### Actualizar Precios (Carga Masiva)")
            up = st.file_uploader("Excel/CSV Precios", key="up_precios_file")
            if up and st.button("Cargar Precios", key="btn_carga_precio"):
                dfn = pd.read_csv(up) if up.name.endswith('.csv') else pd.read_excel(up)
                dfn.columns = dfn.columns.str.upper().str.strip()
                conn=get_connection(); c=conn.cursor(); c.execute("DELETE FROM lista_precios")
                for _,r in dfn.iterrows():
                    c.execute("INSERT INTO lista_precios (item, unidad, precio, material) VALUES (?,?,?,?)", (str(r['ITEM']), str(r.get('UN','kg')), r['PRECIO'], str(r.get('MATERIAL','Galvanizado'))))
                conn.commit(); conn.close(); st.success("Precios actualizados."); st.rerun()
        
        with c_up2:
            st.markdown("##### Actualizar Obras (Carga Masiva)")
            up_obras = st.file_uploader("Excel/CSV Obras (Col: TF, CECO, NOMBRE, KG_CONTRATO, KG_ADICIONALES)", key="up_obras_file")
            if up_obras and st.button("Cargar Obras", key="btn_carga_obras"):
                dfo = pd.read_csv(up_obras) if up_obras.name.endswith('.csv') else pd.read_excel(up_obras)
                dfo.columns = dfo.columns.str.upper().str.strip()
                conn=get_connection(); c=conn.cursor()
                c.execute("DELETE FROM maestro_obras")
                for _,r in dfo.iterrows():
                    tf_v = str(r.get('TF', '')).strip()
                    ceco_v = str(r.get('CECO', '')).strip()
                    nom_v = str(r.get('NOMBRE', r.get('OBRA', ''))).strip()
                    kg_v = float(r.get('KG_CONTRATO', 0.0))
                    kg_a = float(r.get('KG_ADICIONALES', 0.0))
                    c.execute("INSERT INTO maestro_obras (tf, ceco, nombre, kg_contrato, kg_adicionales) VALUES (?,?,?,?,?)", (tf_v, ceco_v, nom_v, kg_v, kg_a))
                conn.commit(); conn.close(); st.success("Obras actualizadas."); st.rerun()

        st.divider()
        st.markdown("##### 💰 Gestión Manual de Precios")
        col_pr1, col_pr2 = st.columns(2)
        with col_pr1:
            with st.form("form_nuevo_precio"):
                st.caption("Añadir un solo precio nuevo")
                n_item = st.text_input("Nombre del Ítem (Ej: DUCTO RECTO)")
                c1_f, c2_f = st.columns(2)
                with c1_f: n_mat = st.selectbox("Material", ["Galvanizado", "Pieza Especial", "FE", "INOX", "Otro"])
                with c2_f: n_uni = st.selectbox("Unidad", ["kg", "un", "m2", "ml"])
                n_prec = st.number_input("Precio ($)", min_value=0, step=100)
                
                if st.form_submit_button("Guardar Precio"):
                    if n_item.strip():
                        try:
                            conn=get_connection(); c=conn.cursor()
                            c.execute("INSERT INTO lista_precios (item, unidad, precio, material) VALUES (?,?,?,?)", (n_item.strip(), n_uni, n_prec, n_mat))
                            conn.commit(); conn.close(); st.success("Precio Guardado."); st.rerun()
                        except Exception as e: st.error(e)
                    else:
                        st.warning("El nombre del ítem es obligatorio.")
        with col_pr2:
            conn = get_connection()
            try: df_pre = pd.read_sql("SELECT rowid as id_bd, item, material, precio FROM lista_precios", conn)
            except: df_pre = pd.DataFrame()
            conn.close()
            if not df_pre.empty:
                df_pre['display'] = df_pre['id_bd'].astype(str) + " - " + df_pre['item'] + " (" + df_pre['material'] + ") $" + df_pre['precio'].astype(str)
                del_pre = st.selectbox("Eliminar Precio", df_pre['display'])
                if st.button("Eliminar Precio", key="btn_elim_precio"):
                    rowid_del = del_pre.split(" - ")[0].strip()
                    conn=get_connection(); c=conn.cursor(); c.execute("DELETE FROM lista_precios WHERE rowid=?", (rowid_del,)); conn.commit(); conn.close(); st.rerun()
            else:
                st.info("No hay precios registrados.")

        st.divider()
        st.markdown("##### 🏗️ Gestión Manual de Obras")
        col_ob1, col_ob2 = st.columns(2)
        with col_ob1:
            with st.form("form_nueva_obra"):
                st.caption("Añadir una sola obra nueva")
                n_tf = st.text_input("Código TF (Ej: 13655)")
                n_ceco = st.text_input("CECO (Ej: 2-11-063)")
                n_nom = st.text_input("Nombre de la Obra")
                if st.form_submit_button("Guardar Obra"):
                    if n_tf and n_nom:
                        try:
                            conn=get_connection(); c=conn.cursor()
                            c.execute("INSERT INTO maestro_obras (tf, ceco, nombre) VALUES (?, ?, ?)", (n_tf.strip(), n_ceco.strip(), n_nom.strip()))
                            conn.commit(); conn.close(); st.success("Guardado."); st.rerun()
                        except Exception as e: st.error(e)
                    else:
                        st.warning("El TF y el Nombre son obligatorios.")
        with col_ob2:
            conn = get_connection()
            try: df_obr = pd.read_sql("SELECT tf, ceco, nombre FROM maestro_obras", conn)
            except: df_obr = pd.DataFrame()
            conn.close()
            if not df_obr.empty:
                del_obra = st.selectbox("Eliminar Obra", df_obr['tf'].astype(str) + " - " + df_obr['nombre'].astype(str))
                if st.button("Eliminar Obra", key="btn_elim_obra"):
                    tf_del = del_obra.split(" - ")[0].strip()
                    conn=get_connection(); c=conn.cursor(); c.execute("DELETE FROM maestro_obras WHERE tf=?", (tf_del,)); conn.commit(); conn.close(); st.rerun()

        st.divider()
        st.markdown("##### 📧 Directorio de Solicitantes (Correos Automáticos)")
        col_dir1, col_dir2 = st.columns(2)
        with col_dir1:
            with st.form("form_nuevo_correo"):
                n_sol = st.text_input("Nombre del Solicitante (Exacto al Excel)")
                c_sol = st.text_input("Correo Electrónico")
                if st.form_submit_button("Guardar Contacto"):
                    if n_sol and c_sol:
                        try:
                            conn=get_connection(); c=conn.cursor()
                            c.execute("INSERT OR REPLACE INTO directorio_solicitantes (nombre, correo) VALUES (?, ?)", (n_sol.strip(), c_sol.strip()))
                            conn.commit(); conn.close(); st.success("Guardado."); st.rerun()
                        except Exception as e: st.error(e)
        with col_dir2:
            conn = get_connection()
            try: df_dir = pd.read_sql("SELECT nombre, correo FROM directorio_solicitantes", conn)
            except: df_dir = pd.DataFrame()
            conn.close()
            st.dataframe(df_dir, use_container_width=True)
            if not df_dir.empty:
                del_nom = st.selectbox("Eliminar Contacto", df_dir['nombre'])
                if st.button("Eliminar Contacto", key="btn_elim_cont_bd"):
                    conn=get_connection(); c=conn.cursor(); c.execute("DELETE FROM directorio_solicitantes WHERE nombre=?", (del_nom,)); conn.commit(); conn.close(); st.rerun()

with tab4:
    st.header("📊 Informe Detallado para Carátula EDP")
    conn = get_connection()
    df_all_ped = pd.read_sql("SELECT * FROM pedidos", conn)
    df_all_items = pd.read_sql("SELECT * FROM items_pedido", conn)
    conn.close()
    
    if not df_all_ped.empty:
        df_all_ped['fecha_termino'] = pd.to_datetime(df_all_ped['fecha_termino'], format='mixed', errors='coerce')
        c1, c2 = st.columns(2)
        hoy = datetime.now()
        if hoy.day <= 20: 
            f_fin = date(hoy.year, hoy.month, 20); f_ini = (date(hoy.year, hoy.month, 1) - timedelta(days=1)).replace(day=21)
        else: 
            f_ini = date(hoy.year, hoy.month, 21); next_m = hoy.month+1 if hoy.month<12 else 1; next_y = hoy.year if hoy.month<12 else hoy.year+1; f_fin = date(next_y, next_m, 20)
        
        sd = c1.date_input("Inicio Periodo", value=f_ini); ed = c2.date_input("Fin Periodo", value=f_fin)
        mask = (df_all_ped['estado'] == 'Terminado') & (df_all_ped['fecha_termino'] >= pd.Timestamp(sd)) & (df_all_ped['fecha_termino'] <= pd.Timestamp(ed))
        df_f = df_all_ped[mask].copy() 
        
        if not df_f.empty:
            st.markdown("### 🔍 Filtros Adicionales")
            cf1, cf2, cf3, cf4 = st.columns(4)
            
            df_f['quien_envia'] = df_f['quien_envia'].fillna("Desconocido")
            df_f['fuente'] = df_f['fuente'].fillna("General")

            lista_obras = ["Todas"] + sorted(df_f['obra_codigo'].unique().tolist())
            lista_solic = ["Todos"] + sorted(df_f['quien_envia'].unique().tolist())
            lista_fuent = ["Todas"] + sorted(df_f['fuente'].unique().tolist())

            with cf1: f_obra = st.selectbox("Obra", lista_obras)
            with cf2: f_num = st.text_input("N° Pedido (Vacío para todos)")
            with cf3: f_solic = st.selectbox("Solicitante", lista_solic)
            with cf4: f_fuent = st.selectbox("Fuente", lista_fuent)

            if f_obra != "Todas": df_f = df_f[df_f['obra_codigo'] == f_obra]
            if f_num.strip(): df_f = df_f[df_f['num_pedido'].astype(str).str.contains(f_num.strip())]
            if f_solic != "Todos": df_f = df_f[df_f['quien_envia'] == f_solic]
            if f_fuent != "Todas": df_f = df_f[df_f['fuente'] == f_fuent]

            st.write(f"**Pedidos encontrados en el periodo y filtros:** {len(df_f)}")
            
            t_kg_est = df_f['kg_estimados'].sum()
            t_kg_real = df_f['kg_reales'].sum()
            t_m2 = df_f['m2_totales'].sum()
            
            col_t1, col_t2, col_t3 = st.columns(3)
            col_t1.metric("⚖️ Total Kg Estimados", f"{t_kg_est:,.1f} Kg")
            col_t2.metric("⚖️ Total Kg Reales", f"{t_kg_real:,.1f} Kg")
            col_t3.metric("🧊 Total M2", f"{t_m2:,.2f} M2")
            st.markdown("<br>", unsafe_allow_html=True)
            
            with st.expander("👁️ Ver detalle de pedidos filtrados (Auditoría: Kilos y M2)"):
                st.dataframe(df_f[['num_pedido', 'obra_codigo', 'quien_envia', 'fuente', 'kg_estimados', 'kg_reales', 'm2_totales']], hide_index=True)

            if not df_f.empty:
                df_full = pd.merge(df_all_items, df_f, left_on='pedido_id', right_on='id', suffixes=('_item', '_ped'))
                def clasificar(row):
                    m = str(row['material']).upper(); u = str(row['unidad_cobro']).lower()
                    if "PIEZA ESPECIAL" in m or u=='un': return "GALV_ESP"
                    if "FE" in m: return "FE"
                    if "INOX" in m: return "INOX"
                    return "GALV"
                df_full['TIPO_EDP'] = df_full.apply(clasificar, axis=1)
                
                df_ajustado = pd.DataFrame()
                for pid in df_full['pedido_id'].unique():
                    df_p = df_full[df_full['pedido_id'] == pid].copy()
                    kg_r = df_p.iloc[0]['kg_reales']; kg_e = df_p.iloc[0]['kg_estimados']
                    if kg_r < 1: kg_r = kg_e
                    factor = kg_r / kg_e if kg_r > 0 and kg_e > 0 else 1.0
                    mask_un = df_p['unidad_cobro'].str.lower() == 'un'
                    df_p.loc[~mask_un, 'peso_total'] *= factor
                    df_p.loc[~mask_un, 'total_linea'] *= factor
                    df_ajustado = pd.concat([df_ajustado, df_p])
        
res = []

        # 🔥 TRADUCTOR INTELIGENTE
        mapeo_columnas = {}
        for col in df_ajustado.columns:
            col_limpia = str(col).strip().lower()
            if col_limpia == 'ceco':
                mapeo_columnas[col] = 'ceco'
            elif col_limpia in ['obra_codigo', 'obra_cod', 'obra', 'obra código']:
                mapeo_columnas[col] = 'obra_codigo'
            elif col_limpia in ['tipo_edp']:
                mapeo_columnas[col] = 'TIPO_EDP'
            elif col_limpia in ['peso_total', 'pesototal']:
                mapeo_columnas[col] = 'peso_total'
            elif col_limpia in ['total_linea', 'totallinea', 'total_línea']:
                mapeo_columnas[col] = 'total_linea'

        df_ajustado.rename(columns=mapeo_columnas, inplace=True)

        for (ceco, obra), g in df_ajustado.groupby(['ceco', 'obra_codigo']):
            res.append({
                "CECO": ceco, "OBRA": obra,
                "KG_GALV": round(g[g['TIPO_EDP']=='GALV']['peso_total'].sum(), 1), "$ GALV": round(g[g['TIPO_EDP']=='GALV']['total_linea'].sum(), 0),
                "KG_FE": round(g[g['TIPO_EDP']=='FE']['peso_total'].sum(), 1), "$ FE": round(g[g['TIPO_EDP']=='FE']['total_linea'].sum(), 0),
                "KG_ESP": round(g[g['TIPO_EDP']=='GALV_ESP']['peso_total'].sum(), 1), "$ ESP": round(g[g['TIPO_EDP']=='GALV_ESP']['total_linea'].sum(), 0)
            })

        df_edp_final = pd.DataFrame(res)
        totales = pd.DataFrame([{"CECO": "TOTALES", "OBRA": "---", "KG_GALV": df_edp_final["KG_GALV"].sum(), "$ GALV": df_edp_final["$ GALV"].sum(), "KG_FE": df_edp_final["KG_FE"].sum(), "$ FE": df_edp_final["$ FE"].sum(), "KG_ESP": df_edp_final["KG_ESP"].sum(), "$ ESP": df_edp_final["$ ESP"].sum()}])
        df_edp_final = pd.concat([df_edp_final, totales], ignore_index=True)
                    
        st.divider()
        st.write("### Tabla de Datos (Selecciona y copia directamente)")
        st.dataframe(df_edp_final, use_container_width=True, hide_index=True)
        st.download_button("📥 Descargar CSV para Excel", df_edp_final.to_csv(index=False).encode('utf-8-sig'), "EDP_Periodo.csv", "text/csv")
                    
        st.divider()
        st.markdown("### 🧊 Calculadora de Bono por Aislación Interior")
        st.info("Marque manualmente en la columna 'Aplica Bono' los pedidos que llevan aislación interior (Ej: pedidos de Natanael Aviel confirmados por correo). El bono se calcula a $500 por M2.")
                    
        df_bono = df_f[['num_pedido', 'obra_codigo', 'quien_envia', 'm2_totales']].copy()
        df_bono['Aplica Bono'] = False 
                    
        edited_bono = st.data_editor(
            df_bono,
            column_config={
                "Aplica Bono": st.column_config.CheckboxColumn("Aplica Bono", default=False),
                "num_pedido": "N° Pedido",
                "obra_codigo": "Obra",
                "quien_envia": "Solicitante",
                "m2_totales": "M2 Totales"
            },
            disabled=["num_pedido", "obra_codigo", "quien_envia", "m2_totales"],
            hide_index=True,
            use_container_width=True,
            key="editor_bono_aislacion"
        )
                    
        m2_seleccionados = edited_bono[edited_bono['Aplica Bono'] == True]['m2_totales'].sum()
        monto_bono_aislacion = m2_seleccionados * 500
                    
        if m2_seleccionados > 0:
            st.success(f"**Total M2 con Aislación Seleccionados:** {m2_seleccionados:,.2f} M2")
            st.markdown(f"#### 💰 Bono Total Aislación (a repartir): $ {monto_bono_aislacion:,.0f}")
        else:
            st.caption("No hay M2 seleccionados. Marque la casilla correspondiente para calcular el monto.")

    else:
        st.warning("No se encontraron pedidos con los filtros seleccionados.")
                        
with tab5:
    st.header("📈 Dashboard de Producción")
    conn = get_connection(); df_all_ped = pd.read_sql("SELECT * FROM pedidos", conn); df_all_items = pd.read_sql("SELECT * FROM items_pedido", conn); conn.close()
    if not df_all_ped.empty:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Pedidos", len(df_all_ped))
        c2.metric("Pendientes", len(df_all_ped[df_all_ped['estado']=='Pendiente']))
        c3.metric("Kilos Estimados Totales", f"{df_all_ped['kg_estimados'].sum():,.1f} Kg")
        st.divider()
        g1, g2 = st.columns(2)
        with g1:
            st.subheader("⚖️ Kilos por Obra (Top 10)")
            df_g = df_all_ped.groupby('obra_codigo')['kg_estimados'].sum().sort_values(ascending=False).head(10)
            st.bar_chart(df_g)
        with g2:
            st.subheader("🏗️ Estado de Pedidos (Por Kilos)")
            counts_kg = df_all_ped.groupby('estado')['kg_estimados'].sum()
            if not counts_kg.empty and counts_kg.sum() > 0:
                fig, ax = plt.subplots(figsize=(5,5))
                ax.pie(counts_kg, labels=counts_kg.index, autopct='%1.1f%%', colors=['#ff9999','#66b3ff'])
                st.pyplot(fig)
            else:
                st.info("No hay kilos registrados.")
        st.divider()
        
        st.subheader("📅 Producción por Fecha (Recepción)")
        df_all_ped['fecha_recepcion'] = pd.to_datetime(df_all_ped['fecha_recepcion'], format='mixed', errors='coerce').dt.date
        df_t = df_all_ped.groupby('fecha_recepcion')['kg_estimados'].sum()
        st.line_chart(df_t)
        
        st.divider()
        
        df_term = df_all_ped[df_all_ped['estado'] == 'Terminado'].copy()
        
        def clasificar_dashboard(row):
            m = str(row['material']).upper()
            if "FE" in m or "FIERRO" in m: return "FE"
            if "INOX" in m: return "INOX"
            return "GALV"
            
        reales_mat = pd.DataFrame()
        
        if not df_term.empty and not df_all_items.empty:
            df_full_dash = pd.merge(df_all_items, df_term, left_on='pedido_id', right_on='id', suffixes=('_item', '_ped'))
            df_full_dash['TIPO_MAT'] = df_full_dash.apply(clasificar_dashboard, axis=1)
            
            df_full_dash['factor'] = np.where(
                (df_full_dash['kg_reales'] > 0) & (df_full_dash['kg_estimados'] > 0),
                df_full_dash['kg_reales'] / df_full_dash['kg_estimados'],
                1.0
            )
            df_full_dash['peso_ajustado'] = df_full_dash['peso_total'] * df_full_dash['factor']
            reales_mat = df_full_dash.groupby(['obra_codigo', 'TIPO_MAT'])['peso_ajustado'].sum().unstack(fill_value=0).reset_index()

        conn = get_connection()
        try: 
            df_obras_contrato = pd.read_sql("SELECT nombre as obra_codigo, kg_contrato, kg_adicionales, kg_historicos, kg_hist_galv, kg_hist_fe, kg_hist_inox FROM maestro_obras", conn)
        except: 
            df_obras_contrato = pd.DataFrame()
        conn.close()
        
        if not df_obras_contrato.empty:
            if not reales_mat.empty:
                df_merge = pd.merge(df_obras_contrato, reales_mat, on='obra_codigo', how='left').fillna(0)
            else:
                df_merge = df_obras_contrato.copy()
            
            for c in ['GALV', 'FE', 'INOX']:
                if c not in df_merge.columns: df_merge[c] = 0.0
            for c in ['kg_historicos', 'kg_hist_galv', 'kg_hist_fe', 'kg_hist_inox', 'kg_contrato', 'kg_adicionales']:
                if c not in df_merge.columns: df_merge[c] = 0.0
                else: df_merge[c] = pd.to_numeric(df_merge[c], errors='coerce').fillna(0.0)

            df_merge['Galvanizado Total'] = df_merge['GALV'] + df_merge['kg_hist_galv'] + df_merge['kg_historicos']
            df_merge['Fierro (FE)'] = df_merge['FE'] + df_merge['kg_hist_fe']
            df_merge['Acero Inox'] = df_merge['INOX'] + df_merge['kg_hist_inox']
            
            # --- REEMPLAZAR DESDE AQUÍ ---
            st.subheader("📊 Avance y Saldo de Contratos (SOLO GALVANIZADO)")
            st.caption("Visualiza el total del contrato, lo que ya se fabricó y **el saldo que va restando**.")
            
            df_general = df_merge[(df_merge['kg_contrato'] > 0) | (df_merge['Galvanizado Total'] > 0)].copy()
            
            if not df_general.empty:
                # LA MAGIA MATEMÁTICA: Calculamos explícitamente el saldo restante
                df_general['Total Contratado'] = df_general['kg_contrato'] + df_general['kg_adicionales']
                df_general['Saldo Restante'] = df_general['Total Contratado'] - df_general['Galvanizado Total']
                
                df_plot_general = df_general[['obra_codigo', 'Total Contratado', 'Galvanizado Total', 'Saldo Restante']].copy()
                df_plot_general.rename(columns={
                    'Total Contratado': '1. Total Contrato', 
                    'Galvanizado Total': '2. Ya Fabricado',
                    'Saldo Restante': '3. Saldo Restante'
                }, inplace=True)
                
                df_melt = df_plot_general.melt('obra_codigo', var_name='Categoría', value_name='Kilos')
                df_melt_labels = df_melt[df_melt['Kilos'] != 0] 
                
                # Colores intuitivos: Contrato (Azul), Fabricado (Naranja), Saldo Restante (Verde)
                color_scale_avance = alt.Scale(
                    domain=['1. Total Contrato', '2. Ya Fabricado', '3. Saldo Restante'],
                    range=['#2980b9', '#e67e22', '#27ae60'] 
                )

                base = alt.Chart(df_melt).encode(
                    x=alt.X('obra_codigo:N', title='Obra', axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y('Kilos:Q', title='Kg'),
                    color=alt.Color('Categoría:N', scale=color_scale_avance, legend=alt.Legend(title="", orient='top')),
                    xOffset='Categoría:N'
                )
                bars = base.mark_bar()
                text = alt.Chart(df_melt_labels).mark_text(
                    align='center', baseline='bottom', dy=-5, fontSize=11, fontWeight='bold'
                ).encode(
                    x=alt.X('obra_codigo:N'),
                    y=alt.Y('Kilos:Q'),
                    xOffset='Categoría:N',
                    text=alt.Text('Kilos:Q', format='.0f') 
                )
                st.altair_chart((bars + text).properties(height=400), use_container_width=True)

                st.markdown("---")
                st.subheader("⚖️ Saldo Restante por Obra (Galvanizado)")
                st.caption("✅ Valores Positivos (+): **Kilos que aún quedan por fabricar** para completar el contrato.<br> ❌ Valores Negativos (-): **Kilos en Sobregiro** (Se fabricó más de lo contratado).", unsafe_allow_html=True)
                
                df_plot_bal = df_general[['obra_codigo', 'Saldo Restante']].set_index('obra_codigo')
                st.bar_chart(df_plot_bal)

            else:
                st.info("Ingresa los datos del contrato en Configuración para ver las comparativas.")
            # --- HASTA AQUÍ EL REEMPLAZO ---
                    
            st.divider()
            st.subheader("🧱 Total Kilos Fabricados por Material")
            st.caption("Incluye los Kilos Históricos ingresados manualmente. Cada color representa un material distinto.")
            
            df_plot_mat = df_merge[['obra_codigo', 'Galvanizado Total', 'Fierro (FE)', 'Acero Inox']].copy()
            df_plot_mat = df_plot_mat[(df_plot_mat[['Galvanizado Total', 'Fierro (FE)', 'Acero Inox']] != 0).any(axis=1)]
            
            if not df_plot_mat.empty:
                df_melt_mat = df_plot_mat.melt('obra_codigo', var_name='Material', value_name='Kilos')
                df_melt_mat_labels = df_melt_mat[df_melt_mat['Kilos'] > 0]
                
                color_scale = alt.Scale(
                    domain=['Galvanizado Total', 'Fierro (FE)', 'Acero Inox'],
                    range=['#3498db', '#e67e22', '#7f8c8d'] 
                )

                base_mat = alt.Chart(df_melt_mat).encode(
                    x=alt.X('obra_codigo:N', title='Obra', axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y('Kilos:Q', title='Kg'),
                    color=alt.Color('Material:N', scale=color_scale, legend=alt.Legend(title="", orient='top')),
                    xOffset='Material:N'
                )
                bars_mat = base_mat.mark_bar()
                text_mat = alt.Chart(df_melt_mat_labels).mark_text(
                    align='center', baseline='bottom', dy=-5, fontSize=11, fontWeight='bold'
                ).encode(
                    x=alt.X('obra_codigo:N'),
                    y=alt.Y('Kilos:Q'),
                    xOffset='Material:N',
                    text=alt.Text('Kilos:Q', format='.0f')
                )
                
                st.altair_chart((bars_mat + text_mat).properties(height=400), use_container_width=True)
            else:
                st.info("Cierra pedidos o ingresa históricos para ver el gráfico de materiales.")



