"""
start.py — Entry point para Railway.
Inicia o scheduler como subprocess e executa uvicorn via os.execv.
"""
import os
import sys
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    port = os.getenv("PORT", "8000")

    # Inicia scheduler em background
    logger.info("Iniciando scheduler...")
    subprocess.Popen(
        [sys.executable, "scheduler.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    logger.info("Scheduler iniciado")

    # Execv para uvicorn (substitui o processo atual — Railway monitora este)
    logger.info(f"Iniciando uvicorn na porta {port}...")
    uvicorn_path = os.path.join(os.path.dirname(sys.executable), "uvicorn")
    if not os.path.exists(uvicorn_path):
        uvicorn_path = "uvicorn"  # fallback to PATH

    os.execv(
        sys.executable,
        [sys.executable, "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", port],
    )


if __name__ == "__main__":
    main()
