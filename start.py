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
    """Instala playwright + Chromium em runtime (não está no requirements.txt)."""
    env = os.environ.copy()
    env.pop("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", None)

    # 1. Instala o pacote Python playwright se não estiver disponível
    try:
        import playwright  # noqa: F401
        logger.info("Playwright já instalado")
    except ImportError:
        logger.info("Instalando playwright via pip...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "playwright>=1.40.0"],
            check=True, timeout=120,
        )

    # 2. Instala o browser Chromium
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=300, env=env,
        )
        if result.returncode == 0:
            logger.info("Playwright Chromium instalado com sucesso")
        else:
            logger.warning(f"playwright install: {result.stderr[:300]}")
    except Exception as e:
        logger.warning(f"Falha ao instalar Chromium: {e}")


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
