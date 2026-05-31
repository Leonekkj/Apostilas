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


def _instalar_playwright():
    """Instala o browser Chromium do Playwright se ainda não estiver disponível."""
    # Remove variável que bloqueia download (usada para evitar auto-install no build do Render)
    env = os.environ.copy()
    env.pop("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", None)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=180, env=env,
        )
        if result.returncode == 0:
            logger.info("Playwright Chromium instalado com sucesso")
        else:
            logger.warning(f"playwright install retornou {result.returncode}: {result.stderr[:200]}")
    except Exception as e:
        logger.warning(f"Falha ao instalar playwright: {e}")


def main():
    port = os.getenv("PORT", "8000")

    # Instala Chromium para geração de PDF (necessário no Render)
    _instalar_playwright()

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
