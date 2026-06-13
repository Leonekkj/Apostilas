"""
start.py — Entry point (roda local; banco de produção no Neon).
Detecta o banco via DATABASE_URL (carregada do .env):
  - Com DATABASE_URL  → produção: PostgreSQL (Neon), garante Playwright
  - Sem DATABASE_URL  → dev: SQLite (apostilas.db), pula instalações
"""
import os
import sys
import subprocess
import logging

from dotenv import load_dotenv
load_dotenv()

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
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    if IS_LOCAL:
        logger.info("Modo DEV — SQLite (apostilas.db), sem instalação de Playwright")
    else:
        logger.info("Modo PRODUÇÃO — PostgreSQL (Neon), verificando Playwright...")
        _instalar_playwright()

    # Inicia scheduler em background
    logger.info("Iniciando scheduler...")
    # Herda stdout/stderr do processo pai — logs do scheduler aparecem no Render
    subprocess.Popen([sys.executable, "scheduler.py"])
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
