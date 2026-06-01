import os
import qrcode
import pandas as pd

# 1. Configuración de la dirección oficial en internet (RAÍZ SEGURA)
URL_PROD = "https://termofrio-portal.streamlit.app"
CARPETA_QRS = "qrs_nuevos"

if not os.path.exists(CARPETA_QRS):
    os.makedirs(CARPETA_QRS)

print("⏳ Leyendo listado de máquinas desde el archivo local...")

try:
    df = pd.read_csv("maquinas.csv")
    col_id = None
    for col in df.columns:
        if 'id' in col.lower():
            col_id = col
            break
    if col_id is None:
        col_id = df.columns[0]
        
    maquinas = df[col_id].dropna().unique().tolist()
    print(f"📊 Se encontraron {len(maquinas)} máquinas en maquinas.csv.")

except Exception as e:
    print(f"⚠️ Usando lista de respaldo por defecto...")
    maquinas = [
        "CILINDRADORA_1", "CNC_1_PLASMA", "COILINE", "PLEGADORA_1", 
        "GUILLOTINA_1", "RODONADORA_1", "PESTAÑERA_1", "TDF_1", "EMBALLETADORA_1"
    ]

print("\n🚀 Generando códigos QR con puente de redirección...")
for m in maquinas:
    m_clean = str(m).strip().upper().replace(" ", "_")
    
    # 🔴 CAMBIO DE ESTRATEGIA: Apunta a la raíz con /?maquina para evitar el bloqueo del proxy
    url_final = f"{URL_PROD}?maquina={m_clean}&v=3"
    ruta_guardado = os.path.join(CARPETA_QRS, f"qr_{m_clean}.png")
    
    qr = qrcode.make(url_final)
    qr.save(ruta_guardado)
    print(f"✅ Creado: {ruta_guardado} ➡️ {url_final}")

print("\n🎉 ¡Nuevos QRs generados con éxito con el puente de seguridad instalado!")