import qrcode
import os

# NOTA: Agregamos /Mantencion a la URL para que Streamlit sepa a qué pestaña ir
URL_BASE = "https://unmeliorated-rusty-lucienne.ngrok-free.dev/Mantencion?maquina="

maquinas = [
    "CNC_1_PLASMA", "CNC_2_PLASMA", "COILINE", "EMBALLETADORA",
    "GUILLOTINA_1", "GUILLOTINA_2", "PESTANERA_1_PIPO", "TDF_1", "PLEGADORA_1"
]

if not os.path.exists('qrs_nuevos'): os.makedirs('qrs_nuevos')

for m in maquinas:
    img = qrcode.make(URL_BASE + m)
    img.save(f"qrs_nuevos/qr_{m}.png")
    print(f"✅ QR Actualizado para pestaña: {m}")