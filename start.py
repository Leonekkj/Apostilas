"""
start.py — Entry point local e Render/Railway.
Detecta ambiente automaticamente via DATABASE_URL:
  - Com DATABASE_URL  → hosted (Render/Railway): instala Playwright, usa PostgreSQL
  - Sem DATABASE_URL  → local: pula instalações, usa SQLite (apostilas.db)
"""
import os
import sys
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

IS_LOCAL = not os.environ.get("DATABASE_URL", "")


def _instalar_playwright():
    """Instala playwright + Chromium em runtime (necessário no Render, filesystem efêmero)."""
    env = os.environ.copy()
    env.pop("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", None)

    try:
        import playwright  # noqa: F401
        logger.info("Playwright já instalado")
    except ImportError:
        logger.info("Instalando playwright via pip...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "playwright>=1.40.0"],
            check=True, timeout=120,
        )

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

    if IS_LOCAL:
        logger.info("Modo LOCAL — SQLite (apostilas.db), sem instalação de Playwright")
    else:
        logger.info("Modo HOSTED — PostgreSQL, instalando Playwright...")
        _instalar_playwright()

    # Inicia scheduler em background
    logger.info("Iniciando scheduler...")
    subprocess.Popen(
        [sys.executable, "scheduler.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    logger.info("Scheduler iniciado")

    logger.info(f"Iniciando uvicorn na porta {port}...")
    extra = ["--reload"] if IS_LOCAL else ["--workers", "1"]
    os.execv(
        sys.executable,
        [sys.executable, "-m", "uvicorn", "api:app",
         "--host", "0.0.0.0", "--port", port] + extra,
    )


if __name__ == "__main__":
    main()
