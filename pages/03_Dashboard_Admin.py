import streamlit as st
import pandas as pd
import sqlite3
import os
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# --- 🔐 SEGURIDAD UNIFICADA ---
if 'logged_in' not in st.session_state or not st.session_state.logged_in:
    st.warning("⚠️ Acceso Restringido. Por favor inicie sesión en la pantalla Principal.")
    st.stop()

# --- RUTAS FIJAS ---
CARPETA_RAIZ = r"C:\Users\taller\OneDrive - Termofrio Ltda\Control Taller 2025\SISTEMA_INTEGRAL_TERMOFRIO"
DB_PROD = os.path.join(CARPETA_RAIZ, 'produccion_v55_master.db')
DB_MANT = os.path.join(CARPETA_RAIZ, 'mantenimiento_taller.db')

st.set_page_config(page_title="Termofrio SPA - Admin", layout="wide")
st.title("🛡️ Auditoría Interna - Termofrio SPA")

# --- FUNCIÓN DE SEGURIDAD PARA LA BASE DE DATOS ---
def asegurar_columnas_despacho():
    conn = sqlite3.connect(DB_PROD)
    cursor = conn.cursor()
    # Intentamos agregar las columnas por si acaso no existen
    try:
        cursor.execute("ALTER TABLE pedidos ADD COLUMN estado_despacho TEXT DEFAULT 'En Taller'")
    except:
        pass # Si ya existe, no hace nada
    try:
        cursor.execute("ALTER TABLE pedidos ADD COLUMN fecha_despacho DATE")
    except:
        pass # Si ya existe, no hace nada
    conn.commit()
    conn.close()

# Ejecutamos la seguridad apenas abre el archivo
asegurar_columnas_despacho()

def cargar_produccion():
    try:
        conn = sqlite3.connect(DB_PROD)
        df = pd.read_sql_query("SELECT * FROM pedidos ORDER BY fecha_recepcion DESC", conn)
        conn.close()
        return df
    except: return pd.DataFrame()

def cargar_mantenimiento():
    try:
        conn = sqlite3.connect(DB_MANT)
        df = pd.read_sql_query("SELECT rowid, * FROM registros_inspeccion ORDER BY fecha_hora DESC", conn)
        conn.close()
        return df
    except: return pd.DataFrame()

def generar_pdf_mantencion(datos):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, "TERMOFRIO SPA - REPORTE TÉCNICO")
    c.line(50, height - 60, width - 50, height - 60)
    y = height - 90
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, f"EQUIPO: {datos['maquina_id']}")
    c.drawString(300, y, f"FECHA: {datos['fecha_hora']}")
    y -= 20
    c.drawString(50, y, f"OPERADOR: {datos['operador']}")
    y -= 40
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "DETALLE DE INSPECCIÓN:")
    y -= 20
    c.setFont("Helvetica", 10)
    for item in str(datos['checks_ok']).split(" | "):
        c.drawString(70, y, f"• {item}")
        y -= 15
    y -= 20
    c.drawString(50, y, f"OBSERVACIONES: {datos['comentarios']}")
    if os.path.exists(datos['firma_path']):
        c.drawImage(datos['firma_path'], 50, y - 80, width=150, height=60, mask='auto')
    c.save()
    buffer.seek(0)
    return buffer

tab_prod, tab_mant = st.tabs(["📦 Auditoría Producción", "🔧 Auditoría Mantención"])

with tab_prod:
    st.header("Seguimiento de Pedidos y Trazabilidad")

    # --- BOTÓN DE LIMPIEZA MASIVA PARA LOS 126 PEDIDOS ---
    with st.expander("🛠️ Herramienta de Actualización Masiva de Despachos", expanded=False):
        st.warning("Este botón tomará TODOS los pedidos que están 'Terminados' en taller y los marcará como 'Despachados'. Automáticamente copiará la fecha de cierre de fabricación como fecha de despacho.")
        if st.button("🚀 Limpiar Cola: Marcar todos los listos como Despachados", type="primary"):
            conn = sqlite3.connect(DB_PROD)
            c = conn.cursor()
            # Actualiza los terminados que no están despachados y les pone la fecha de término
            c.execute("UPDATE pedidos SET estado_despacho='Despachado', fecha_despacho=fecha_termino WHERE estado='Terminado' AND (estado_despacho != 'Despachado' OR estado_despacho IS NULL)")
            conn.commit()
            conn.close()
            st.success("✅ ¡Base de datos actualizada! Todos los pedidos listos fueron marcados como despachados.")
            st.rerun()

    st.divider()

    df_p = cargar_produccion()
    if not df_p.empty:
        # Prevención de errores si las columnas son nuevas
        if 'estado_despacho' not in df_p.columns: df_p['estado_despacho'] = 'En Taller'
        if 'fecha_despacho' not in df_p.columns: df_p['fecha_despacho'] = None

        # --- BUSCADOR ---
        st.markdown("#### 🔍 Buscador de Trazabilidad")
        c_busq1, c_busq2 = st.columns(2)
        with c_busq1:
            buscar_ped = st.text_input("Buscar por N° Pedido (Ej: 105):")
        with c_busq2:
            buscar_tf = st.text_input("Buscar por TF ó CC (Ej: 13655):")
        
        # Filtros de búsqueda
        if buscar_ped:
            df_p = df_p[df_p['num_pedido'].astype(str).str.contains(buscar_ped, case=False, na=False)]
        if buscar_tf:
            df_p = df_p[df_p['tf'].astype(str).str.contains(buscar_tf, case=False, na=False) | df_p['ceco'].astype(str).str.contains(buscar_tf, case=False, na=False)]

        st.markdown("<br>", unsafe_allow_html=True)
        
        # Formateamos las fechas para que se vean bonitas
        df_p['fecha_limite'] = pd.to_datetime(df_p['fecha_limite'], errors='coerce').dt.strftime('%d/%m/%Y')
        df_p['fecha_despacho'] = pd.to_datetime(df_p['fecha_despacho'], errors='coerce').dt.strftime('%d/%m/%Y')

        # Tabla final con las nuevas columnas
        st.dataframe(df_p[['num_pedido', 'tf', 'obra_codigo', 'estado', 'kg_estimados', 'kg_reales', 'fecha_limite', 'estado_despacho', 'fecha_despacho']], use_container_width=True, hide_index=True)
    else: 
        st.info("No hay datos de producción.")

with tab_mant:
    st.header("Auditoría de Maquinaria")
    df_m = cargar_mantenimiento()
    if not df_m.empty:
        st.dataframe(df_m.drop(columns=['rowid', 'firma_path'], errors='ignore'), use_container_width=True, hide_index=True)
        st.divider()
        st.subheader("Descargar Reporte Firmado")
        sel = st.selectbox("Seleccione reporte:", df_m['fecha_hora'] + " - " + df_m['maquina_id'])
        if sel:
            fecha_sel = sel.split(" - ")[0]
            reg = df_m[df_m['fecha_hora'] == fecha_sel].iloc[0]
            btn_pdf = generar_pdf_mantencion(reg)
            st.download_button("📥 Descargar PDF", btn_pdf, file_name=f"Mantencion_{reg['maquina_id']}.pdf")
    else: st.info("No hay registros de mantenimiento.")