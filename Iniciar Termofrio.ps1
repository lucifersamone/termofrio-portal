# -- INICIO DEL SCRIPT POWERSHELL --
# 1. Iniciar Ngrok apuntando al 8501
Start-Process "ngrok" -ArgumentList "http --url=unmeliorated-rusty-lucienne.ngrok-free.dev 8501" -WindowStyle Hidden

# 2. Iniciar la App Unificada en el 8501
$pythonPath = "C:\Users\taller\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$scriptPath = Join-Path $PSScriptRoot "principal.py" 

& $pythonPath -m streamlit run $scriptPath --server.port 8501
# -- FIN DEL SCRIPT POWERSHELL --