import sqlite3
import os
import pandas as pd

# Buscamos en la carpeta actual
path = "produccion_v55_master.db"

print("--- INICIO DIAGNÓSTICO ---")
if os.path.exists(path):
    print(f"✅ Archivo encontrado: {path}")
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    
    # 1. Ver qué tablas existen
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tablas = cursor.fetchall()
    
    if len(tablas) == 0:
        print("⚠️ ALERTA: La base de datos existe pero NO TIENE TABLAS.")
    else:
        print(f"📊 Se encontraron {len(tablas)} tablas. Listando contenido:")
        for t in tablas:
            nombre = t[0]
            try:
                # Contar registros
                cursor.execute(f"SELECT COUNT(*) FROM {nombre}")
                cantidad = cursor.fetchone()[0]
                print(f"   ➡️ Tabla: '{nombre}' | Registros: {cantidad}")
                
                # Mostrar nombres de columnas (para ver si coinciden)
                df = pd.read_sql(f"SELECT * FROM {nombre} LIMIT 1", conn)
                print(f"      Columnas: {list(df.columns)}")
                print("-" * 20)
            except Exception as e:
                print(f"      Error leyendo {nombre}: {e}")

    conn.close()
else:
    print("❌ No se encuentra el archivo en esta carpeta.")
print("--- FIN DIAGNÓSTICO ---")