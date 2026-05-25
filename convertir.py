import sqlite3
import pandas as pd
import os

# 1. Buscamos automáticamente cualquier archivo .db en la carpeta
archivos_db = [f for f in os.listdir('.') if f.endswith('.db')]

if not archivos_db:
    print("❌ No se encontró ningún archivo .db en esta carpeta.")
else:
    archivo_base = archivos_db[0]
    print(f"🔄 Abriendo base de datos: {archivo_base}")
    
    # 2. Nos conectamos a la base de datos local
    conexion = sqlite3.connect(archivo_base)
    cursor = conexion.cursor()
    
    # 3. Le preguntamos a la base de datos qué tablas tiene dentro
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tablas = cursor.fetchall()
    
    # 4. Exportamos cada tabla a un archivo CSV independiente
    for tabla in tablas:
        nombre_tabla = tabla[0]
        # Ignoramos tablas internas del sistema
        if nombre_tabla.startswith('sqlite_'):
            continue
            
        print(f"💾 Exportando tabla '{nombre_tabla}' a CSV...")
        df = pd.read_sql_query(f"SELECT * FROM {nombre_tabla}", conexion)
        df.to_csv(f"{nombre_tabla}.csv", index=False, encoding='utf-8')
        
    conexion.close()
    print("✨ ¡Proceso terminado! Ya puedes revisar tu carpeta.")