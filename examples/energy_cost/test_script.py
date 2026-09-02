#!/usr/bin/env python3
"""
Ejecuta el comando `\\irmasin <archivo.json>` diez veces seguidas para
cada uno de seis archivos JSON, y guarda las últimas 14 líneas de la
salida de cada ejecución en un archivo de texto (uno por cada JSON).
"""

import subprocess
from pathlib import Path

# --- CONFIGURACIÓN -----------------------------------------------------

# Lista de los 6 archivos JSON a procesar. Ajusta las rutas/nombres.
JSON_FILES = [
    "options_homo_simple.json",
    "options_homo_homogeneous.json",
    "options_homo_heterogeneous.json",
    "options_het_simple.json",
    "options_het_homogeneous.json",
    "options_het_heterogeneous.json",
]

# Número de repeticiones por archivo
N_REPS = 10

# Cantidad de líneas finales a guardar por ejecución
N_LINES = 14

# Comando a ejecutar. Se arma como string y se corre con shell=True
# porque el "\" antes de irmasin normalmente sirve para evitar que el
# shell use un alias con ese nombre.
COMMAND_TEMPLATE = r"\irmasim {json_file}"

# Carpeta donde se guardan los resultados
OUTPUT_DIR = Path("resultados_irmasim")

# -------------------------------------------------------------------

def run_command(json_file: str) -> str:
    """Ejecuta el comando para un JSON dado y devuelve stdout+stderr combinados."""
    cmd = COMMAND_TEMPLATE.format(json_file=json_file)
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
    )
    # Combina stdout y stderr por si el resultado relevante sale por stderr
    return result.stdout + result.stderr


def last_n_lines(text: str, n: int) -> list[str]:
    lines = text.splitlines()
    return lines[-n:] if len(lines) >= n else lines


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    for json_file in JSON_FILES:
        json_path = Path(json_file)
        out_path = OUTPUT_DIR / f"{json_path.stem}_resultados.txt"

        print(f"\n=== Procesando {json_file} ===")

        with open(out_path, "w", encoding="utf-8") as out_f:
            for i in range(1, N_REPS + 1):
                print(f"  Ejecución {i}/{N_REPS}...")
                salida = run_command(json_file)
                lineas = last_n_lines(salida, N_LINES)

                out_f.write(f"--- Ejecución {i} ---\n")
                out_f.write("\n".join(lineas))
                out_f.write("\n\n")

        print(f"  Resultados guardados en: {out_path}")

    print("\nProceso finalizado.")


if __name__ == "__main__":
    main()
