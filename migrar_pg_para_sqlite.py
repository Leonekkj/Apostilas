"""
Migra dados do PostgreSQL (Render) para SQLite local.

Uso:
    DATABASE_URL=postgresql://... python migrar_pg_para_sqlite.py

O arquivo apostilas.db será criado/sobrescrito no diretório do projeto.
"""
import os, sys, sqlite3, json

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERRO: defina DATABASE_URL antes de rodar.")
    print("Exemplo: DATABASE_URL=postgresql://user:pass@host/db python migrar_pg_para_sqlite.py")
    sys.exit(1)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERRO: psycopg2 não instalado. Rode: pip install psycopg2-binary")
    sys.exit(1)

TABELAS = [
    "topicos",
    "apostilas",
    "kits",
    "anuncios",
    "ml_tokens",
    "shopee_tokens",
    "vendas",
    "produtos",
]

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apostilas.db")

print(f"Conectando ao PostgreSQL...")
pg = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
pg_cur = pg.cursor()

# Cria (ou abre) o SQLite e recria o schema via database.py
print(f"Criando SQLite em {DB_PATH}...")
if os.path.exists(DB_PATH):
    os.rename(DB_PATH, DB_PATH + ".bak")
    print(f"  Backup do banco anterior em {DB_PATH}.bak")

# Usa database.py para criar as tabelas no SQLite
os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
import importlib
import database as db_mod
importlib.reload(db_mod)
db_mod.criar_tabelas()
print("  Schema SQLite criado.")

sq = sqlite3.connect(DB_PATH)
sq.row_factory = sqlite3.Row

def pg_to_sqlite_val(v):
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, dict):
        return json.dumps(v)
    return v

total_migrado = 0
for tabela in TABELAS:
    try:
        pg_cur.execute(f"SELECT * FROM {tabela}")
        rows = pg_cur.fetchall()
        if not rows:
            print(f"  {tabela}: vazia, pulando")
            continue

        cols = list(rows[0].keys())
        placeholders = ",".join(["?" for _ in cols])
        col_names = ",".join(cols)

        sq.execute(f"DELETE FROM {tabela}")  # limpa antes de inserir

        inserted = 0
        for row in rows:
            vals = [pg_to_sqlite_val(row[c]) for c in cols]
            try:
                sq.execute(f"INSERT OR REPLACE INTO {tabela} ({col_names}) VALUES ({placeholders})", vals)
                inserted += 1
            except Exception as e:
                print(f"    AVISO linha ignorada em {tabela}: {e}")

        sq.commit()
        print(f"  {tabela}: {inserted}/{len(rows)} linhas migradas")
        total_migrado += inserted

    except Exception as e:
        print(f"  {tabela}: ERRO — {e}")

pg.close()
sq.close()

print(f"\nMigração concluída — {total_migrado} linhas no total.")
print(f"Banco SQLite salvo em: {DB_PATH}")
print("\nPara rodar localmente sem o Render:")
print("  python start.py")
print("  (sem DATABASE_URL no ambiente — usa SQLite automaticamente)")
