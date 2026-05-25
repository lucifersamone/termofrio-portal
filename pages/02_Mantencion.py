import streamlit as st
from streamlit_drawable_canvas import st_canvas
from datetime import datetime, timedelta, date
import sqlite3
import pandas as pd
import os
from PIL import Image, ImageOps
import numpy as np
import qrcode
import base64
import time 
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors 
import io
import psycopg2
import re

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Gestión Mantención", layout="wide")

# --- RUTAS FIJAS (Optimizadas para Nube) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

DB_PATH = os.path.join(ROOT_DIR, 'mantenimiento_taller.db')
CARPETA_FOTOS = os.path.join(ROOT_DIR, "img_maquinas")
CARPETA_FIRMAS = os.path.join(ROOT_DIR, "firmas")
CARPETA_INFORMES = os.path.join(ROOT_DIR, "informes_checklist")
CARPETA_EVIDENCIAS = os.path.join(ROOT_DIR, "evidencias_externas")
CARPETA_QRS = os.path.join(ROOT_DIR, "qrs_nuevos")
CARPETA_BIBLIOTECA = os.path.join(ROOT_DIR, "biblioteca_maquinas")
CARPETA_FOTOS_EVIDENCIA = os.path.join(ROOT_DIR, "evidencias_fotograficas")

# --- RUTAS DE LOGOS ---
LOGO_TERMOFRIO = os.path.join(CARPETA_QRS, "termofriologo.jpg") 
LOGO_ISO = os.path.join(CARPETA_QRS, "tfiso.jpg") 

MESES_NOMBRES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

# --- PAUTAS TÉCNICAS PARA MANTENEDORES EXTERNOS ---
CHECKS_EXTERNOS_MAQUINAS = {
    "Plasma": [
        "Revisión de Tableros eléctricos", 
        "Revisión de compresor", 
        "Revisión de torcha",
        "Revisión Extractor de Humo",
        "Revisión de Mesa de corte",
        "Revisión de rieles"
    ],
    "Cilindradora": [
        "Revisión de partes mecánicas",
        "Engrase de Rodamientos y partes mecánicas", 
        "Alineación y Calibración de Rodillos",
        "Limpieza General"
    ],
    "Plegadora": [
        "Revisión de partes mecánicas",
        "Revisión de contrapeso",
        "Limpieza general"
    ],
    "Coiline": [
        "Revisión de Sistema hidráulico",
        "Ajuste y Nivelación de Rodillos y carril",
        "Revisión de estructuras de bobinas", 
        "Revisión tablero general y de máquina",
        "Limpieza general"
    ],
    "Rodonadora Electrica": [
        "Revisión Eléctrica y Cuadro de Mando", 
        "Engrase y Lubricación General", 
        "Ajuste de Piezas Móviles y Correas", 
        "Prueba de Funcionamiento en Vacío",
        "Limpieza general"
    ],
    "Pestañera": [
        "Revisión Eléctrica", 
        "Engrase y Lubricación General", 
        "Ajuste de Piezas Móviles y Correas", 
        "Prueba de Funcionamiento en Vacío",
        "Limpieza General"
    ],
    "Rodonadora Manual": [
        "Revisión de Partes mecánicas",
        "Engrase y Lubricación General", 
        "Ajuste de Piezas Móviles", 
        "Prueba de Funcionamiento en Vacío",
        "Limpieza General"
    ],
    "General": [
        "Revisión General de Equipo",
        "Limpieza General"
    ]
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

# --- OPTIMIZACIÓN 1: CACHÉ PARA CONFIGURACIÓN INICIAL ---
@st.cache_resource
def setup_entorno_inicial():
    for c in [CARPETA_FOTOS, CARPETA_FIRMAS, CARPETA_INFORMES, CARPETA_EVIDENCIAS, CARPETA_QRS, CARPETA_BIBLIOTECA, CARPETA_FOTOS_EVIDENCIA]:
        if not os.path.exists(c): os.makedirs(c)
        
    conn = get_connection(); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS registros_inspeccion (
        fecha_hora TEXT, maquina_id TEXT, operador TEXT, checks_ok TEXT, 
        repuesto_necesario INTEGER, comentarios TEXT, firma_path TEXT, pdf_path TEXT
    )''')
    try: c.execute("ALTER TABLE registros_inspeccion ADD COLUMN pdf_path TEXT")
    except: pass
    try: c.execute("ALTER TABLE registros_inspeccion ADD COLUMN foto_evidencia_path TEXT")
    except: pass
    
    c.execute('''CREATE TABLE IF NOT EXISTS maquinas (
        id TEXT PRIMARY KEY, nombre TEXT, caracteristicas TEXT, frecuencia_mantencion TEXT, foto_path TEXT, modelo TEXT
    )''')
    try: c.execute("ALTER TABLE maquinas ADD COLUMN modelo TEXT")
    except: pass
    
    c.execute('''CREATE TABLE IF NOT EXISTS plan_externo (
        id INTEGER PRIMARY KEY AUTOINCREMENT, maquina_id TEXT, fecha_programada DATE, 
        proveedor TEXT, estado TEXT, evidencia_pdf_path TEXT, fecha_realizacion DATE,
        evaluacion_proveedor TEXT
    )''')
    try: c.execute("ALTER TABLE plan_externo ADD COLUMN evaluacion_proveedor TEXT")
    except: pass
    conn.commit(); conn.close()
    return True

setup_entorno_inicial()

# --- OPTIMIZACIÓN 2: CACHÉ PARA EL LOGO HTML ---
@st.cache_data
def get_logo_html(ruta_logo):
    if os.path.exists(ruta_logo):
        with open(ruta_logo, "rb") as img_file:
            b64_string = base64.b64encode(img_file.read()).decode()
        return f"""
            <div style="display: flex; justify-content: center; margin-bottom: 20px;">
                <img src="data:image/jpeg;base64,{b64_string}" alt="Logo Termofrio" style="max-height: 90px; width: auto; max-width: 100%; object-fit: contain;">
            </div>
        """
    return "<h2 style='text-align: center; color: #b30000;'>TERMOFRIO SPA - MANTENIMIENTO</h2>"

# --- FUNCIONES LÓGICAS ---
def get_maquinas_lista():
    conn = get_connection()
    try: df = pd.read_sql("SELECT id FROM maquinas ORDER BY id", conn); return df['id'].tolist()
    except: return []
    finally: conn.close()

def obtener_puntos(maquina_id):
    m = str(maquina_id).upper()
    
    if any(x in m for x in ["CNC", "PLASMA", "COILINE"]):
        puntos = ["Limpieza General", "Tablero Eléctrico y Cables", "PC y Pantalla", "Sist. Aire / Hidráulico", "Rieles/Guías", "Consumibles/Corte"]
        if "COILINE" in m: puntos.append("Carretes y Rodamientos")
        return puntos
        
    if any(x in m for x in ["CILINDRADORA", "GUILLOTINA", "PLEGADORA"]):
        return ["Limpieza General", "Engrase / Lubricación", "Estado de Cuchillos / Prismas / Rodillos", "Ajuste Mecánico y Manivelas"]
        
    if any(x in m for x in ["RODONADORA", "PESTAÑERA", "PESTANERA", "TDF", "EMBALLETADORA"]):
        if "MANUAL" in m and "RODONADORA" in m:
            return ["Limpieza General", "Engrase / Lubricación", "Estado de Rodillos / Ejes", "Ajuste Mecánico y Manivelas"]
        else:
            return ["Limpieza General", "Tablero Eléctrico y Cables", "Funcionamiento Motor", "Rodamientos y Guías", "Protecciones Seguridad"]
            
    return ["Limpieza General", "Tablero Eléctrico y Cables", "Funcionamiento Motor", "Rodamientos y Guías", "Protecciones Seguridad"]

def obtener_estado_semana(maquina_id):
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT rowid, operador, fecha_hora, repuesto_necesario FROM registros_inspeccion WHERE maquina_id=? ORDER BY fecha_hora DESC", conn, params=(maquina_id,))
        if df.empty: return None
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'])
        hoy = datetime.now()
        inicio_semana = (hoy - timedelta(days=hoy.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        df_semana = df[df['fecha_hora'] >= inicio_semana]
        if df_semana.empty: return None
        return df_semana.iloc[0]
    except: return None
    finally: conn.close()

# --- FUNCIÓN DE GENERACIÓN DE PDF MEJORADA NATIVA ---
def generar_pdf_checklist(maquina, operador, fecha_dt, checks_lista, estado, obs, firma_path, foto_evidencia_path=None):
    nombre_seguro = "".join([c if c.isalnum() else "_" for c in maquina])
    fecha_str_file = fecha_dt.strftime('%Y%m%d_%H%M%S')
    nombre_pdf = f"{nombre_seguro}_{fecha_str_file}.pdf"
    ruta_pdf = os.path.join(CARPETA_INFORMES, nombre_pdf)
    try:
        c = canvas.Canvas(ruta_pdf, pagesize=letter)
        w, h = letter
        
        # --- PÁGINA 1: DATOS DEL CHECKLIST ---
        c.setFillColor(colors.darkblue)
        c.rect(0, h - 80, w, 80, fill=1, stroke=0)
        
        if os.path.exists(LOGO_TERMOFRIO):
            try: c.drawImage(ImageReader(LOGO_TERMOFRIO), 15, h - 75, width=150, height=70, mask='auto', preserveAspectRatio=True)
            except Exception as e: print(f"Error cargando logo termofrio: {e}")
            
        if os.path.exists(LOGO_ISO):
            try: c.drawImage(ImageReader(LOGO_ISO), w - 85, h - 75, width=70, height=70, mask='auto', preserveAspectRatio=True)
            except Exception as e: print(f"Error cargando logo ISO: {e}")

        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(w/2, h - 40, "REPORTE DE INSPECCIÓN TÉCNICA")
        c.setFont("Helvetica", 12)
        c.drawCentredString(w/2, h - 60, "TERMOFRIO SPA")
        
        c.setFillColor(colors.black)
        y_info = h - 110
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y_info, f"Máquina:"); c.setFont("Helvetica", 12); c.drawString(120, y_info, maquina)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(350, y_info, f"Fecha:"); c.setFont("Helvetica", 12); c.drawString(400, y_info, fecha_dt.strftime('%d/%m/%Y %H:%M'))
        
        y_info -= 20
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y_info, f"Operador/Técnico:"); c.setFont("Helvetica", 12); c.drawString(170, y_info, operador)
        
        y_info -= 40
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(w/2, y_info, "ESTADO DEL EQUIPO")
        y_info -= 25
        c.setFont("Helvetica-Bold", 20)
        if estado == "CON FALLA":
            c.setFillColor(colors.red); texto_estado = "⛔ NO OPERATIVO / CON FALLA"
        else:
            c.setFillColor(colors.green); texto_estado = "✅ OPERATIVO"
        c.drawCentredString(w/2, y_info, texto_estado)
        c.setFillColor(colors.black)
        c.setStrokeColor(colors.gray)
        c.line(50, y_info - 20, w - 50, y_info - 20)
        
        y = y_info - 50
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "Detalle Verificado:")
        y -= 25
        c.setFont("Helvetica", 11)
        
        for item in checks_lista:
            if "No Cumple" in item or "FALLA" in item:
                c.setFillColor(colors.red); c.drawString(60, y, "[X]")
            else:
                c.setFillColor(colors.green); c.drawString(60, y, "[OK]")
            c.setFillColor(colors.black)
            c.drawString(90, y, item)
            y -= 20
            if y < 100: c.showPage(); y = h - 50
            
        y -= 20
        c.setFillColor(colors.darkblue)
        c.rect(50, y, w-100, 20, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(60, y+5, "Observaciones Registradas")
        
        y -= 20
        c.setFillColor(colors.black); c.setFont("Helvetica", 10)
        if obs.strip():
            txt_obj = c.beginText(60, y); txt_obj.textLines(obs); c.drawText(txt_obj)
        else:
            c.drawString(60, y, "Sin observaciones adicionales.")
            
        y_firma = 100
        c.setStrokeColor(colors.black)
        c.line(w/2 - 100, y_firma, w/2 + 100, y_firma)
        c.setFont("Helvetica", 10)
        c.drawCentredString(w/2, y_firma - 15, f"Firma: {operador}")
        
        if os.path.exists(firma_path):
            try: c.drawImage(ImageReader(firma_path), w/2 - 60, y_firma + 5, width=120, height=60, mask='auto')
            except: pass

        # --- PÁGINA 2: EVIDENCIA FOTOGRÁFICA ---
        if foto_evidencia_path and os.path.exists(foto_evidencia_path):
            c.showPage()
            
            c.setFillColor(colors.darkblue)
            c.rect(0, h - 80, w, 80, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 16)
            c.drawCentredString(w/2, h - 40, "ANEXO: EVIDENCIA FOTOGRAFICA")
            c.setFont("Helvetica", 12)
            c.drawCentredString(w/2, h - 60, f"MAQUINA: {maquina}")
            
            try:
                pil_img = Image.open(foto_evidencia_path)
                pil_img = ImageOps.exif_transpose(pil_img) 
                
                img_buffer = io.BytesIO()
                pil_img.save(img_buffer, format="PNG") 
                img_buffer.seek(0)
                
                w_img, h_img = pil_img.size
                target_w_max = w - 100 
                target_h_max = h - 200 
                
                if h_img > w_img:
                    target_h = h - 220 
                    target_w = w - 200 
                    c.drawImage(ImageReader(img_buffer), 100, 50, width=target_w, height=target_h, preserveAspectRatio=True, mask='auto')
                else: 
                    target_w = w - 100
                    target_h = 400
                    c.drawImage(ImageReader(img_buffer), 50, h - 550, width=target_w, height=target_h, preserveAspectRatio=True, mask='auto')
                
            except Exception as e:
                c.setFillColor(colors.black)
                c.drawString(50, h - 150, f"Error al cargar la fotografía de evidencia: {e}")
                
        c.save(); return ruta_pdf
    except Exception as e: print(e); return None

def calcular_estado_mes(fecha_prog, estado_db):
    if estado_db == 'Realizado': return "✅ OK"
    hoy = datetime.now().date()
    try: prog = pd.to_datetime(fecha_prog).date()
    except: return "⚪ Error"
    if hoy > prog and (hoy.month > prog.month or hoy.year > prog.year): return "🔴 Vencido"
    if hoy.month == prog.month and hoy.year == prog.year:
        ultimo_dia = (prog.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        try: dias_habiles = np.busday_count(hoy, ultimo_dia)
        except: dias_habiles = 30
        return "🟠 ALERTA" if dias_habiles <= 10 else "🔵 En Plazo"
    return "📅 Prog."

# --- CONTROL DE ACCESO ---
try: param_maquina = st.query_params.get("maquina", None)
except: param_maquina = None

estoy_logueado = 'logged_in' in st.session_state and st.session_state.logged_in

modo_kiosco = False
if param_maquina: modo_kiosco = True
elif estoy_logueado: modo_kiosco = False
else:
    st.warning("⚠️ Acceso Restringido. Inicie sesión en la pantalla Principal o escanee el QR.")
    st.stop()

# ================= VISTA 1: MODO KIOSCO (CELULAR / QR) =================
if modo_kiosco:
    st.markdown(get_logo_html(LOGO_TERMOFRIO), unsafe_allow_html=True)
        
    st.info(f"📱 Equipo seleccionado: **{param_maquina}**")
    
    conn = get_connection()
    foto = pd.read_sql("SELECT foto_path FROM maquinas WHERE id=?", conn, params=(param_maquina,))
    df_estado = pd.read_sql("SELECT repuesto_necesario, fecha_hora FROM registros_inspeccion WHERE maquina_id=? ORDER BY fecha_hora DESC LIMIT 1", conn, params=(param_maquina,))
    df_plan = pd.read_sql("SELECT fecha_programada, proveedor FROM plan_externo WHERE maquina_id=? AND estado='Programado' ORDER BY fecha_programada ASC LIMIT 1", conn, params=(param_maquina,))
    conn.close()
    
    st.markdown("---")
    col_est1, col_est2 = st.columns(2)
    with col_est1:
        if not df_estado.empty:
            es_falla = df_estado.iloc[0]['repuesto_necesario'] == 1
            fecha_ult = pd.to_datetime(df_estado.iloc[0]['fecha_hora']).strftime("%d/%m/%Y")
            if es_falla:
                st.error(f"🔴 **ESTADO ACTUAL:** CON FALLA \n\n*(Última act: {fecha_ult})*")
            else:
                st.success(f"🟢 **ESTADO ACTUAL:** OPERATIVO \n\n*(Última act: {fecha_ult})*")
        else:
            st.warning("⚪ **ESTADO ACTUAL:** Sin registros históricos")

    with col_est2:
        if not df_plan.empty:
            fp = pd.to_datetime(df_plan.iloc[0]['fecha_programada'])
            mes_str = MESES_NOMBRES[fp.month - 1]
            st.info(f"📅 **PRÓX. PREVENTIVO EXTERNO:** \n\n**{mes_str} {fp.year}** (Prov: {df_plan.iloc[0]['proveedor']})")
        else:
            st.info("📅 **PRÓX. PREVENTIVO EXTERNO:** \n\nNo programada en matriz")
    st.markdown("---")

    if not foto.empty and foto.iloc[0]['foto_path'] and os.path.exists(foto.iloc[0]['foto_path']):
        st.image(foto.iloc[0]['foto_path'], use_container_width=True)

    tipo_usuario = st.radio("¿Qué tipo de mantenimiento realizará?", ["👷 Personal Interno (Checklist Semanal)", "🔧 Personal Externo (Mantenimiento Técnico)"])
    st.divider()

    # --- FLUJO 1: PERSONAL INTERNO ---
    if "Interno" in tipo_usuario:
        registro_semana = obtener_estado_semana(param_maquina)
        mostrar_formulario = True

        if registro_semana is not None:
            op_real = registro_semana['operador']
            fecha_real = pd.to_datetime(registro_semana['fecha_hora']).strftime("%d/%m/%Y %H:%M")
            es_falla = registro_semana['repuesto_necesario'] == 1
            
            if es_falla:
                st.error(f"⚠️ **ESTE EQUIPO FUE DECLARADO EN FALLA ESTA SEMANA** (Reportado por {op_real})")
                accion = st.radio("¿Qué desea hacer?", ["Registrar reparación y habilitar equipo", "Solo ver estado (No hacer nada)"])
                if accion == "Registrar reparación y habilitar equipo":
                    with st.form("frm_reparacion"):
                        st.subheader("Registro de Reparación")
                        op = st.selectbox("Técnico / Operador que repara:", ["Seleccionar...", "Julson Epingle", "Luis Zapata", "Mauricio Villanueva", "Oscar Fabres", "Lucio Zúñiga"])
                        obs_rep = st.text_area("Describa el trabajo realizado para solucionar la falla (Obligatorio):")
                        
                        foto_rep_up = st.file_uploader("📸 Adjuntar Foto de la Reparación (Opcional)", type=['jpg', 'jpeg', 'png'], key="img_rep")
                        
                        st.write("**Firma Digital:**")
                        canvas_rep = st_canvas(stroke_width=2, height=100, key="f_rep", background_color="#fff")
                        if st.form_submit_button("✅ Habilitar Máquina (Operativa)"):
                            if op == "Seleccionar..." or not obs_rep.strip() or canvas_rep.image_data is None:
                                st.error("Llene todos los campos para levantar la falla.")
                            else:
                                fecha_dt = datetime.now()
                                f_str = fecha_dt.strftime("%Y-%m-%d %H:%M:%S")
                                f_path = os.path.join(CARPETA_FIRMAS, f"REP_{param_maquina}_{fecha_dt.strftime('%Y%m%d%H%M')}.png")
                                Image.fromarray(canvas_rep.image_data.astype(np.uint8)).save(f_path)
                                
                                ruta_evidencia = ""
                                if foto_rep_up:
                                    ruta_evidencia = os.path.join(CARPETA_FOTOS_EVIDENCIA, f"EVID_{param_maquina}_{fecha_dt.strftime('%Y%m%d%H%M%S')}.png")
                                    with open(ruta_evidencia, "wb") as f: f.write(foto_rep_up.getbuffer())
                                
                                conn = get_connection(); c = conn.cursor()
                                c.execute("INSERT INTO registros_inspeccion (fecha_hora, maquina_id, operador, checks_ok, repuesto_necesario, comentarios, firma_path, pdf_path, foto_evidencia_path) VALUES (?,?,?,?,?,?,?,?,?)", 
                                          (f_str, param_maquina, op, "REPARACIÓN DE FALLA PREVIA: OK", 0, obs_rep, f_path, "", ruta_evidencia))
                                conn.commit(); last_id = c.lastrowid; conn.close()
                                
                                try:
                                    pdf_path = generar_pdf_checklist(param_maquina, op, fecha_dt, ["Reparación de falla completada: OK"], "Operativo", obs_rep, f_path, ruta_evidencia)
                                    conn = get_connection(); c=conn.cursor()
                                    c.execute("UPDATE registros_inspeccion SET pdf_path=? WHERE rowid=?", (pdf_path, last_id))
                                    conn.commit(); conn.close()
                                except: pass
                                
                                st.success("¡Máquina reparada y operativa nuevamente!")
                                st.balloons()
                                time.sleep(2.5) 
                                st.rerun()
                mostrar_formulario = False
            else:
                st.success(f"✅ **Equipo ya inspeccionado esta semana** (Revisado el {fecha_real} por {op_real}).")
                if not st.checkbox("¿Ocurrió una nueva falla y desea registrarla ahora?"):
                    mostrar_formulario = False

        if mostrar_formulario:
            with st.form("frm_kiosco_interno"):
                st.subheader("📝 Checklist Visual de Inspección")
                op = st.selectbox("Operador Responsable:", ["Seleccionar...", "Julson Epingle", "Luis Zapata", "Mauricio Villanueva", "Oscar Fabres", "Lucio Zúñiga"])
                puntos = obtener_puntos(param_maquina)
                
                respuestas_checks = []
                for p in puntos:
                    estado_p = st.radio(f"🔹 {p}", ["Cumple", "No Cumple"], index=0, horizontal=True)
                    motivo_p = ""
                    if estado_p == "No Cumple":
                        motivo_p = st.text_input(f"✍️ Indique el motivo para '{p}':")
                    respuestas_checks.append({"punto": p, "estado": estado_p, "motivo": motivo_p})
                
                st.markdown("---")
                es_operativo = st.radio("¿El equipo se encuentra en condiciones OPERATIVAS para trabajar?", ["Sí, 100% Operativo", "No, Presenta Falla"], index=None)
                motivo_falla_final = ""
                if es_operativo == "No, Presenta Falla":
                    motivo_falla_final = st.text_area("⚠️ Describa brevemente la falla principal:")
                
                foto_chk_up = st.file_uploader("📸 Adjuntar Foto de Evidencia (Opcional - Útil para reportar piezas rotas)", type=['jpg', 'jpeg', 'png'], key="img_chk")

                st.write("**Firma Digital del Operador:**")
                canvas_int = st_canvas(stroke_width=2, height=100, key="f_int", background_color="#fff")
                
                if st.form_submit_button("💾 Guardar Inspección"):
                    errores = False
                    if op == "Seleccionar...": errores = True; st.error("Seleccione Operador.")
                    if es_operativo is None: errores = True; st.error("Indique si el equipo está operativo o no.")
                    if es_operativo == "No, Presenta Falla" and not motivo_falla_final.strip(): errores = True; st.error("Debe explicar la falla final.")
                    if canvas_int.image_data is None: errores = True; st.error("Debe firmar el documento.")
                    for r in respuestas_checks:
                        if r['estado'] == 'No Cumple' and not r['motivo'].strip():
                            errores = True; st.error(f"Falta el motivo para '{r['punto']}'.")

                    if not errores:
                        fecha_dt = datetime.now(); f_str = fecha_dt.strftime("%Y-%m-%d %H:%M:%S")
                        f_path = os.path.join(CARPETA_FIRMAS, f"{param_maquina}_{fecha_dt.strftime('%Y%m%d%H%M')}.png")
                        Image.fromarray(canvas_int.image_data.astype(np.uint8)).save(f_path)
                        
                        ruta_evidencia = ""
                        if foto_chk_up:
                            ruta_evidencia = os.path.join(CARPETA_FOTOS_EVIDENCIA, f"EVID_{param_maquina}_{fecha_dt.strftime('%Y%m%d%H%M%S')}.png")
                            with open(ruta_evidencia, "wb") as f: f.write(foto_chk_up.getbuffer())
                        
                        txt_chk_lista = []
                        for r in respuestas_checks:
                            if r['estado'] == 'Cumple': txt_chk_lista.append(f"{r['punto']}: Cumple")
                            else: txt_chk_lista.append(f"{r['punto']}: No Cumple ({r['motivo']})")
                        
                        str_db = " | ".join(txt_chk_lista)
                        es_falla_db = 1 if "No" in es_operativo else 0
                        estado_pdf = "CON FALLA" if es_falla_db == 1 else "Operativo"
                        
                        conn = get_connection(); c=conn.cursor()
                        c.execute("INSERT INTO registros_inspeccion (fecha_hora, maquina_id, operador, checks_ok, repuesto_necesario, comentarios, firma_path, pdf_path, foto_evidencia_path) VALUES (?,?,?,?,?,?,?,?,?)", 
                                  (f_str, param_maquina, op, str_db, es_falla_db, motivo_falla_final, f_path, "", ruta_evidencia))
                        conn.commit(); last_id = c.lastrowid; conn.close()
                        
                        st.success("✅ **Inspección Guardada Exitosamente**")
                        st.balloons()
                        
                        try:
                            pdf_path = generar_pdf_checklist(param_maquina, op, fecha_dt, txt_chk_lista, estado_pdf, motivo_falla_final, f_path, ruta_evidencia)
                            if pdf_path:
                                conn = get_connection(); c=conn.cursor()
                                c.execute("UPDATE registros_inspeccion SET pdf_path=? WHERE rowid=?", (pdf_path, last_id))
                                conn.commit(); conn.close()
                        except: pass
                        
                        time.sleep(2.5) 
                        st.rerun()

    # --- FLUJO 2: PERSONAL EXTERNO ---
    else:
        st.subheader("🛠️ Registro de Mantenimiento Preventivo Externo")
        conn = get_connection()
        planes_pendientes = pd.read_sql("SELECT id, fecha_programada, proveedor FROM plan_externo WHERE maquina_id=? AND estado='Programado'", conn, params=(param_maquina,))
        conn.close()

        with st.form("frm_externo"):
            if not planes_pendientes.empty:
                st.info("Esta máquina tiene mantenimientos programados en la Matriz Anual.")
                planes_pendientes['mes_fmt'] = pd.to_datetime(planes_pendientes['fecha_programada']).dt.strftime('%B %Y')
                opciones_plan = ["No asociar a plan (Mantención Extra)"] + planes_pendientes['mes_fmt'].tolist()
                plan_seleccionado = st.selectbox("¿A qué mes corresponde este mantenimiento?", opciones_plan)
            else:
                st.warning("No hay mantenimientos preventivos agendados. Esto se registrará como un servicio extra.")
                plan_seleccionado = "No asociar a plan (Mantención Extra)"

            tec_ext = st.text_input("Nombre del Técnico:")
            prov_ext = st.text_input("Empresa Proveedora:")
            
            st.markdown("### 🛠️ Pauta de Mantención Técnica")
            st.caption(f"Lista de verificación obligatoria para: **{param_maquina}**")
            
            nombre_maq = str(param_maquina).upper()
            lista_checks_ext = CHECKS_EXTERNOS_MAQUINAS["General"]
            
            if "PLASMA" in nombre_maq:
                lista_checks_ext = CHECKS_EXTERNOS_MAQUINAS["Plasma"]
            elif "CILINDRADORA" in nombre_maq:
                lista_checks_ext = CHECKS_EXTERNOS_MAQUINAS["Cilindradora"]
            elif "PLEGADORA" in nombre_maq:
                lista_checks_ext = CHECKS_EXTERNOS_MAQUINAS["Plegadora"]
            elif "COILINE" in nombre_maq:
                lista_checks_ext = CHECKS_EXTERNOS_MAQUINAS["Coiline"]
            elif any(x in nombre_maq for x in ["PESTAÑERA", "PESTANERA", "TDF", "EMBALLETADORA"]):
                lista_checks_ext = CHECKS_EXTERNOS_MAQUINAS["Rodonadora Electrica"]
            elif "RODONADORA" in nombre_maq:
                if "ELEC" in nombre_maq or "ELÉC" in nombre_maq:
                    lista_checks_ext = CHECKS_EXTERNOS_MAQUINAS["Rodonadora Electrica"]
                else:
                    lista_checks_ext = CHECKS_EXTERNOS_MAQUINAS["Rodonadora Manual"]
                    
            checks_marcados_ext = []
            for check in lista_checks_ext:
                if st.checkbox(check, key=f"ext_{check}"):
                    checks_marcados_ext.append(check)
            
            st.markdown("---")
            tareas_ext = st.text_area("📝 Diagnóstico / Observaciones Técnicas:", placeholder="Detalle los ajustes realizados, piezas cambiadas o justificaciones...")
            estado_ext = st.radio("Estado Final post-mantenimiento:", ["100% Operativo", "Requiere más reparaciones (Falla)"], horizontal=True)
            
            foto_ext_up = st.file_uploader("📸 Adjuntar Foto del Trabajo (Opcional)", type=['jpg', 'jpeg', 'png'], key="img_ext")

            st.write("**Firma del Técnico:**")
            canvas_ext = st_canvas(stroke_width=2, height=100, key="f_ext", background_color="#fff")
            
            if st.form_submit_button("💾 Guardar Mantenimiento Externo"):
                if not tec_ext.strip() or not prov_ext.strip() or not tareas_ext.strip() or canvas_ext.image_data is None:
                    st.error("Todos los campos de texto y la firma son obligatorios.")
                elif not checks_marcados_ext:
                    st.error("Debe marcar al menos un ítem de la pauta de mantención técnica.")
                else:
                    fecha_dt = datetime.now(); f_str = fecha_dt.strftime("%Y-%m-%d %H:%M:%S")
                    f_path = os.path.join(CARPETA_FIRMAS, f"EXT_{param_maquina}_{fecha_dt.strftime('%Y%m%d%H%M%S')}.png")
                    Image.fromarray(canvas_ext.image_data.astype(np.uint8)).save(f_path)
                    
                    ruta_evidencia = ""
                    if foto_ext_up:
                        ruta_evidencia = os.path.join(CARPETA_FOTOS_EVIDENCIA, f"EVID_{param_maquina}_{fecha_dt.strftime('%Y%m%d%H%M%S')}.png")
                        with open(ruta_evidencia, "wb") as f: f.write(foto_ext_up.getbuffer())
                    
                    es_falla = 1 if "Falla" in estado_ext else 0
                    txt_check_ext = " | ".join(checks_marcados_ext)
                    obs_completa = f"Empresa: {prov_ext} | Técnico: {tec_ext}\nObservaciones:\n{tareas_ext}"
                    
                    conn = get_connection(); c = conn.cursor()
                    c.execute("INSERT INTO registros_inspeccion (fecha_hora, maquina_id, operador, checks_ok, repuesto_necesario, comentarios, firma_path, pdf_path, foto_evidencia_path) VALUES (?,?,?,?,?,?,?,?,?)", 
                              (f_str, param_maquina, f"{tec_ext} ({prov_ext})", txt_check_ext, es_falla, obs_completa, f_path, "", ruta_evidencia))
                    conn.commit(); last_id = c.lastrowid
                    
                    if plan_seleccionado != "No asociar a plan (Mantención Extra)":
                        mes_elegido = plan_seleccionado.split(" ")[0]
                        id_plan_actualizar = None
                        for _, row in planes_pendientes.iterrows():
                            if mes_elegido in row['mes_fmt']: id_plan_actualizar = row['id']; break
                        if id_plan_actualizar:
                            c.execute("UPDATE plan_externo SET estado='Realizado', fecha_realizacion=?, proveedor=? WHERE id=?", (fecha_dt.date(), prov_ext, id_plan_actualizar))
                            conn.commit()
                    conn.close()

                    st.success("✅ **Mantenimiento Externo Registrado con Éxito**")
                    st.balloons()
                    
                    try:
                        pdf_path = generar_pdf_checklist(param_maquina, f"{tec_ext} ({prov_ext})", fecha_dt, checks_marcados_ext, "Operativo" if es_falla==0 else "CON FALLA", tareas_ext, f_path, ruta_evidencia)
                        conn = get_connection(); c=conn.cursor()
                        c.execute("UPDATE registros_inspeccion SET pdf_path=? WHERE rowid=?", (pdf_path, last_id))
                        conn.commit(); conn.close()
                    except: pass
                    
                    time.sleep(2.5) 
                    st.rerun()

# ================= VISTA 2: MODO ADMIN (PC) =================
else:
    st.title("🔧 Gestión de Activos")
    tab1, tab2, tab3 = st.tabs(["📝 Historial Check Lists (PDFs)", "🗓️ Plan Externo", "⚙️ Configuración"])

    with tab1:
        st.header("🗂️ Archivo de Inspecciones")
        col_f1, col_f2 = st.columns(2)
        with col_f1: filtro_maq = st.selectbox("Filtrar por Máquina:", ["Todas"] + get_maquinas_lista())
        with col_f2: filtro_fecha = st.date_input("Filtrar por Fecha:", value=None)
        
        conn = get_connection()
        query = "SELECT rowid, fecha_hora, maquina_id, operador, repuesto_necesario, pdf_path, checks_ok, comentarios, firma_path, foto_evidencia_path FROM registros_inspeccion"
        condiciones = []; params = []
        if filtro_maq != "Todas": condiciones.append("maquina_id = ?"); params.append(filtro_maq)
        if filtro_fecha: condiciones.append("fecha_hora LIKE ?"); params.append(f"{filtro_fecha.strftime('%Y-%m-%d')}%")
        if condiciones: query += " WHERE " + " AND ".join(condiciones)
        query += " ORDER BY fecha_hora DESC"
        
        df_hist = pd.read_sql(query, conn, params=params)
        conn.close()
        
        c_izq, c_der = st.columns([2, 1])
        with c_izq:
            if not df_hist.empty:
                df_hist['Estado'] = df_hist['repuesto_necesario'].apply(lambda x: "🔴 FALLA" if x==1 else "🟢 OK")
                df_hist['Fecha'] = pd.to_datetime(df_hist['fecha_hora']).dt.strftime('%d-%m-%Y %H:%M')
                st.info("Seleccione una fila para gestionar el PDF.")
                event = st.dataframe(df_hist[['Fecha', 'maquina_id', 'operador', 'Estado']], use_container_width=True, hide_index=True, selection_mode="single-row", on_select="rerun")
                seleccion = event.selection.rows
            else: st.warning("Sin registros."); seleccion = []

        with c_der:
            st.subheader("📥 Gestión PDF")
            if seleccion:
                idx = seleccion[0]; registro = df_hist.iloc[idx]; ruta_pdf = registro['pdf_path']
                st.write(f"**Registro:** {registro['maquina_id']}")
                st.write(f"**Fecha:** {registro['Fecha']}")
                if ruta_pdf and os.path.exists(ruta_pdf):
                    with open(ruta_pdf, "rb") as f: st.download_button("⬇️ DESCARGAR PDF", data=f, file_name=os.path.basename(ruta_pdf), mime="application/pdf", type="primary")
                else: 
                    st.warning("⚠️ PDF no disponible.")
                    if st.button("🔄 REGENERAR PDF"):
                        f_dt = pd.to_datetime(registro['fecha_hora'])
                        checks_limpios = str(registro['checks_ok']).split(" | ")
                        est_str = "CON FALLA" if registro['repuesto_necesario'] == 1 else "Operativo"
                        foto_rut = registro.get('foto_evidencia_path', None) 
                        
                        new_pdf = generar_pdf_checklist(registro['maquina_id'], registro['operador'], f_dt, checks_limpios, est_str, registro['comentarios'], registro['firma_path'], foto_rut)
                        if new_pdf:
                            conn = get_connection(); c=conn.cursor()
                            c.execute("UPDATE registros_inspeccion SET pdf_path=? WHERE rowid=?", (new_pdf, int(registro['rowid'])))
                            conn.commit(); conn.close()
                            st.success("Regenerado OK."); st.rerun()
            else: st.caption("👈 Seleccione un registro.")

    with tab2:
        st.header("🗓️ Planificación de Mantenimiento Externo")
        col_prog, col_view = st.columns([1, 2])
        with col_prog:
            st.markdown("### 🛠️ Configurar Plan")
            with st.container(border=True):
                m_prog = st.selectbox("1. Seleccione Máquina:", get_maquinas_lista(), key="sel_maq_prog")
                periodicidad = st.selectbox("2. Periodicidad:", ["Trimestral (4 veces)", "Semestral (2 veces)", "Anual (1 vez)", "Mensual (12 veces)"], key="sel_freq_prog")
                anio_plan = st.number_input("Año:", value=datetime.now().year, step=1)
                cant_eventos = 1
                if "Semestral" in periodicidad: cant_eventos = 2
                elif "Trimestral" in periodicidad: cant_eventos = 4
                elif "Mensual" in periodicidad: cant_eventos = 12
                with st.form("form_meses"):
                    datos_a_guardar = []
                    for i in range(cant_eventos):
                        c1, c2 = st.columns([1.5, 1])
                        with c1: mes_txt = st.selectbox(f"Mes #{i+1}", MESES_NOMBRES, key=f"m_{i}")
                        with c2: hecho = st.checkbox("¿Hecho?", key=f"chk_{i}")
                        fecha_real = st.date_input(f"F. Real #{i+1}", value=datetime.now(), key=f"d_{i}", format="DD-MM-YYYY") if hecho else None
                        datos_a_guardar.append({"mes_nombre": mes_txt, "hecho": hecho, "fecha_real": fecha_real})
                    prov = st.text_input("Proveedor Estimado:", "Externo")
                    if st.form_submit_button("💾 Actualizar Plan"):
                        conn = get_connection(); c = conn.cursor()
                        c.execute("DELETE FROM plan_externo WHERE maquina_id=? AND strftime('%Y', fecha_programada)=?", (m_prog, str(anio_plan)))
                        for item in datos_a_guardar:
                            mes_idx = MESES_NOMBRES.index(item["mes_nombre"]) + 1
                            fecha_prog = date(anio_plan, mes_idx, 1)
                            estado = "Realizado" if item["hecho"] else "Programado"
                            f_real_db = item["fecha_real"] if item["hecho"] else None
                            c.execute("""INSERT INTO plan_externo (maquina_id, fecha_programada, proveedor, estado, fecha_realizacion) VALUES (?,?,?,?,?)""", (m_prog, fecha_prog, prov, estado, f_real_db))
                        conn.commit(); conn.close(); st.success("Plan actualizado."); st.rerun()

        with col_view:
            st.markdown("### 👀 Matriz Visual Anual")
            conn = get_connection(); df_plan = pd.read_sql("SELECT * FROM plan_externo", conn); conn.close()
            if not df_plan.empty:
                df_plan['fecha_programada'] = pd.to_datetime(df_plan['fecha_programada'])
                df_plan = df_plan[df_plan['fecha_programada'].dt.year == datetime.now().year]
                maquinas_all = get_maquinas_lista()
                matrix_data = []
                plan_map = {m: {} for m in maquinas_all}
                for _, row in df_plan.iterrows():
                    mid = row['maquina_id']
                    if mid in maquinas_all:
                        mes_idx = row['fecha_programada'].month
                        icon = calcular_estado_mes(row['fecha_programada'], row['estado'])
                        if row['estado'] == 'Realizado' and row['fecha_realizacion']: icon = f"✅ {pd.to_datetime(row['fecha_realizacion']).strftime('%d/%m')}"
                        plan_map[mid][mes_idx] = icon
                for m in maquinas_all:
                    row_data = {"Máquina": m}
                    for i, mes_name in enumerate(MESES_NOMBRES, 1): row_data[mes_name] = plan_map[m].get(i, "")
                    matrix_data.append(row_data)
                st.dataframe(pd.DataFrame(matrix_data), use_container_width=True, hide_index=True)
                st.caption("🟠 ALERTA: Quedan 10 días hábiles (2 semanas) o menos.")
            else: st.info("No hay planes.")
            
            st.divider()
            st.subheader("📂 Evidencia Técnica (Subir PDF Externo)")
            conn = get_connection()
            df_real = pd.read_sql("SELECT id, maquina_id, fecha_realizacion FROM plan_externo WHERE estado='Realizado' AND evidencia_pdf_path IS NULL", conn)
            conn.close()
            if not df_real.empty:
                df_real['fecha_fmt'] = pd.to_datetime(df_real['fecha_realizacion']).dt.strftime('%d-%m-%Y')
                opts = df_real.apply(lambda x: f"{x['maquina_id']} ({x['fecha_fmt']}) ID:{x['id']}", axis=1)
                sel_ev = st.selectbox("Seleccionar Mantenimiento Realizado:", opts)
                pdf = st.file_uploader("Adjuntar PDF Informe de Proveedor", type="pdf")
                if st.button("Guardar Evidencia") and pdf:
                    eid = int(sel_ev.split("ID:")[1])
                    path = os.path.join(CARPETA_EVIDENCIAS, f"EVID_PROV_{eid}_{pdf.name}")
                    with open(path, "wb") as f: f.write(pdf.getbuffer())
                    conn = get_connection(); c=conn.cursor()
                    c.execute("UPDATE plan_externo SET evidencia_pdf_path=? WHERE id=?", (path, eid))
                    conn.commit(); conn.close(); st.success("Guardado."); st.rerun()
            else: st.info("Todo documentado.")

    with tab3:
        st.header("⚙️ Configuración de Máquinas")
        
        c_add, c_del, c_qr = st.columns(3)
        
        with c_add:
            st.markdown("### ➕ Agregar Máquina")
            with st.form("form_add_maq"):
                new_id = st.text_input("ID Máquina (Ej: PLEGADORA_1)*")
                new_name = st.text_input("Nombre / Descripción (Opcional)")
                new_img = st.file_uploader("Foto de la Máquina (JPG/PNG)", type=['jpg', 'jpeg', 'png'])
                
                if st.form_submit_button("Guardar Máquina"):
                    if new_id.strip():
                        new_id_clean = new_id.strip().upper().replace(" ", "_")
                        conn = get_connection(); c = conn.cursor()
                        c.execute("SELECT id FROM maquinas WHERE id=?", (new_id_clean,))
                        if c.fetchone():
                            st.error("Esta máquina ya existe.")
                        else:
                            ruta_foto = ""
                            if new_img:
                                ruta_foto = os.path.join(CARPETA_FOTOS, f"{new_id_clean}_{new_img.name}")
                                with open(ruta_foto, "wb") as f: f.write(new_img.getbuffer())
                            c.execute("INSERT INTO maquinas (id, nombre, foto_path) VALUES (?, ?, ?)", (new_id_clean, new_name, ruta_foto))
                            conn.commit(); conn.close()
                            st.success(f"Agregada: {new_id_clean}")
                            st.rerun()
                    else: st.error("El ID es obligatorio.")

        with c_del:
            st.markdown("### ❌ Eliminar Máquina")
            maquinas_actuales = get_maquinas_lista()
            if maquinas_actuales:
                maq_a_borrar = st.selectbox("Seleccione la máquina:", maquinas_actuales)
                if st.button("Eliminar Máquina"):
                    conn = get_connection(); c = conn.cursor()
                    c.execute("DELETE FROM maquinas WHERE id=?", (maq_a_borrar,))
                    conn.commit(); conn.close()
                    st.success(f"Eliminada: {maq_a_borrar}")
                    st.rerun()
            else:
                st.info("No hay máquinas.")

        with c_qr:
            st.markdown("### 🖨️ Generador de QR")
            u = st.text_input("URL Base del Sistema (ngrok):")
            if st.button("Generar QRs"):
                if u.strip():
                    maquinas_generar = get_maquinas_lista()
                    for m in maquinas_generar:
                        qrcode.make(f"{u.strip()}/Mantencion?maquina={m}").save(os.path.join(CARPETA_QRS, f"qr_{m}.png"))
                    st.success(f"✅ QRs generados en la carpeta 'qrs_nuevos'.")
                else:
                    st.error("Ingrese la URL.")

        st.divider()
        st.subheader("📋 Listado Actual de Máquinas Activas")
        df_maquinas_activas = pd.DataFrame(get_maquinas_lista(), columns=["ID Máquina"])
        st.dataframe(df_maquinas_activas, use_container_width=True, hide_index=True)