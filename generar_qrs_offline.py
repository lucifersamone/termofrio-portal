import os
import qrcode
import pandas as pd

# 🔴 TU URL REAL Y OFICIAL EN INTERNET
URL_PROD = "https://termofrio-app-7t8hkxxpr9cieryygrxyaw.streamlit.app"
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

print("\n🚀 Fabricando códigos QR de acceso directo de taller...")
for m in maquinas:
    m_clean = str(m).strip().upper().replace(" ", "_")
    
    # Construcción limpia usando la URL que no rebota
    url_final = f"{URL_PROD}/?maquina={m_clean}"
    ruta_guardado = os.path.join(CARPETA_QRS, f"qr_{m_clean}.png")
    
    qr = qrcode.make(url_final)
    qr.save(ruta_guardado)
    print(f"✅ QR Creado: {ruta_guardado} ➡️ {url_final}")

print("\n🎉 ¡Todos los QRs de las máquinas han sido generados exitosamente!")