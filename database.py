import json
import os
from contextlib import contextmanager
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apostilas.db")

DATABASE_URL = os.environ.get("DATABASE_URL", "")

USE_POSTGRES = DATABASE_URL.startswith("postgresql") or DATABASE_URL.startswith("postgres")

if USE_POSTGRES:
    import time
    import threading
    import psycopg2
    import psycopg2.extras
    from psycopg2 import pool as _pg_pool

    _POOL = None
    _POOL_LOCK = threading.Lock()

    def _get_pool():
        global _POOL
        if _POOL is None:
            with _POOL_LOCK:
                if _POOL is None:
                    print("Apostilas: conectando ao PostgreSQL com pool...")
                    attempt = 0
                    while True:
                        try:
                            _POOL = _pg_pool.ThreadedConnectionPool(
                                minconn=1,
                                maxconn=10,
                                dsn=DATABASE_URL,
                                keepalives=1,
                                keepalives_idle=30,
                                keepalives_interval=10,
                                keepalives_count=3,
                            )
                            break
                        except psycopg2.OperationalError as e:
                            wait = min(2 ** attempt, 30)
                            attempt += 1
                            print(f"PostgreSQL indisponível (tentativa {attempt}), retry em {wait}s: {e}")
                            time.sleep(wait)
        return _POOL

    @contextmanager
    def _get_conn():
        pool = _get_pool()
        c = pool.getconn()
        try:
            # Verifica se a conexão ainda está viva
            try:
                c.cursor().execute("SELECT 1")
            except Exception:
                try:
                    pool.putconn(c, close=True)
                except Exception:
                    pass
                c = psycopg2.connect(DATABASE_URL)
            yield c
        finally:
            try:
                pool.putconn(c)
            except Exception:
                try:
                    c.close()
                except Exception:
                    pass

    def _row_to_dict(row, cursor):
        """Converte uma row do psycopg2 (RealDictRow) em dict."""
        return dict(row) if row is not None else None

    def _rows_to_dicts(rows, cursor):
        return [dict(r) for r in rows]

else:
    import sqlite3

    print("Apostilas: usando SQLite local")

    @contextmanager
    def _get_conn():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def _row_to_dict(row, cursor):
        return dict(row) if row is not None else None

    def _rows_to_dicts(rows, cursor):
        return [dict(r) for r in rows]


PH = "%s" if USE_POSTGRES else "?"


def _cursor(conn):
    """Retorna cursor com RealDictCursor no PG, cursor padrão no SQLite."""
    if USE_POSTGRES:
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()


def _lastrowid(cur, conn):
    """Retorna o id da última linha inserida, compatível com PG e SQLite."""
    if USE_POSTGRES:
        row = cur.fetchone()
        return row["id"] if row else None
    return cur.lastrowid


def _insert_returning(sql_base: str) -> str:
    """Adiciona RETURNING id ao SQL se for PostgreSQL."""
    if USE_POSTGRES:
        return sql_base + " RETURNING id"
    return sql_base


def criar_tabelas() -> None:
    """Cria todas as tabelas se não existirem e popula tópicos padrão."""
    with _get_conn() as conn:
        cur = _cursor(conn)

        # No PostgreSQL, cada statement deve ser executado separadamente.
        # No SQLite poderíamos usar executescript(), mas executamos separados
        # para manter código único.
        statements = [
            """
            CREATE TABLE IF NOT EXISTS topicos (
                id       {serial} PRIMARY KEY,
                nome     TEXT NOT NULL,
                slug     TEXT UNIQUE NOT NULL,
                keywords TEXT,
                ativo    {bool_type} DEFAULT {true_val}
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS apostilas (
                id             {serial} PRIMARY KEY,
                topico_id      INTEGER REFERENCES topicos(id),
                num_exercicios INTEGER NOT NULL,
                conteudo_json  TEXT,
                pdf_path       TEXT,
                criado_em      TEXT DEFAULT {now_expr},
                produto_id     INTEGER
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS anuncios (
                id           {serial} PRIMARY KEY,
                apostila_id  INTEGER REFERENCES apostilas(id),
                tipo         TEXT NOT NULL,
                template_id  INTEGER DEFAULT 1,
                ml_id        TEXT,
                status       TEXT DEFAULT 'rascunho',
                titulo       TEXT,
                preco        REAL,
                imagem_path  TEXT,
                publicado_em TEXT,
                erro_msg     TEXT,
                variacao     INTEGER DEFAULT 1,
                angulo       TEXT DEFAULT '',
                kit_id       INTEGER,
                descricao    TEXT DEFAULT ''
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ml_tokens (
                id            INTEGER PRIMARY KEY DEFAULT 1,
                access_token  TEXT,
                refresh_token TEXT,
                expires_at    TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS shopee_tokens (
                id            INTEGER PRIMARY KEY DEFAULT 1,
                access_token  TEXT,
                refresh_token TEXT,
                expires_at    TEXT,
                shop_id       INTEGER
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS kits (
                id           {serial} PRIMARY KEY,
                nome         TEXT NOT NULL,
                apostila_ids TEXT NOT NULL,
                criado_em    TEXT DEFAULT {now_expr}
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS vendas (
                id                  {serial} PRIMARY KEY,
                ml_order_id         TEXT UNIQUE NOT NULL,
                anuncio_id          INTEGER REFERENCES anuncios(id),
                comprador_nickname  TEXT DEFAULT '',
                valor               REAL DEFAULT 0.0,
                quantidade          INTEGER DEFAULT 1,
                data_venda          TEXT,
                sincronizado_em     TEXT DEFAULT {now_expr},
                comprador_id        TEXT DEFAULT '',
                pdf_entregue        {bool_type} DEFAULT {false_val}
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS produtos (
                id        {serial} PRIMARY KEY,
                nome      TEXT NOT NULL,
                serie     INTEGER DEFAULT 1,
                topico_id INTEGER REFERENCES topicos(id),
                criado_em TEXT DEFAULT {now_expr}
            )
            """,
        ]

        if USE_POSTGRES:
            fmt = dict(
                serial="SERIAL",
                bool_type="BOOLEAN",
                true_val="TRUE",
                false_val="FALSE",
                now_expr="NOW()::TEXT",
            )
        else:
            fmt = dict(
                serial="INTEGER",
                bool_type="INTEGER",
                true_val="1",
                false_val="0",
                now_expr="(datetime('now'))",
            )

        for stmt in statements:
            cur.execute(stmt.format(**fmt))

        # Migration: adicionar colunas que podem não existir em bancos antigos.
        # PostgreSQL: ALTER TABLE ... ADD COLUMN IF NOT EXISTS (idempotente).
        # SQLite: tentativa com try/except (não suporta IF NOT EXISTS).

        # Tabela: anuncios
        _add_columns(cur, conn, "anuncios", [
            ("variacao",      "INTEGER DEFAULT 1"),
            ("angulo",        "TEXT DEFAULT ''"),
            ("kit_id",        "INTEGER"),
            ("descricao",     "TEXT DEFAULT ''"),
            ("shopee_item_id","TEXT"),
            ("shopee_status", "TEXT DEFAULT 'nao_publicado'"),
        ])

        # Tabela: apostilas
        _add_columns(cur, conn, "apostilas", [
            ("produto_id", "INTEGER"),
        ])

        # Tabela: vendas
        _add_columns(cur, conn, "vendas", [
            ("comprador_id",  "TEXT DEFAULT ''"),
            ("pdf_entregue",  "INTEGER DEFAULT 0"),
        ])

        # Tabela: produtos
        _add_columns(cur, conn, "produtos", [
            ("tema",        "TEXT"),
            ("dificuldade", "TEXT"),
        ])

        conn.commit()

    seed_topicos()
    _upsert_topico(
        "Caça-Palavras",
        "caca-palavras",
        "caca palavras idosos passatempo letras busca",
    )


def _add_columns(cur, conn, table: str, columns: list) -> None:
    """Adiciona colunas a uma tabela de forma idempotente.

    PostgreSQL: usa ADD COLUMN IF NOT EXISTS.
    SQLite: usa PRAGMA table_info + try/except.
    """
    if USE_POSTGRES:
        for col_name, col_def in columns:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_def}")
    else:
        cur.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cur.fetchall()}
        for col_name, col_def in columns:
            if col_name not in existing:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                except Exception:
                    pass  # coluna já existe (race condition improvável no SQLite)


def seed_topicos(conn=None) -> None:
    """Insere os 6 tópicos padrão se a tabela estiver vazia."""
    _close_after = conn is None
    if conn is not None:
        # Legado: chamada com conexão externa (não é mais usada internamente,
        # mas preservada para compatibilidade).
        _seed_with_conn(conn)
        return

    with _get_conn() as c:
        _seed_with_conn(c)


def _seed_with_conn(conn) -> None:
    cur = _cursor(conn)
    cur.execute("SELECT COUNT(*) FROM topicos")
    row = cur.fetchone()
    count = row[0] if not USE_POSTGRES else row["count"]
    if count > 0:
        return

    topicos = [
        ("Coordenação Motora", "coordenacao-motora",
         "coordenação motora exercícios crianças"),
        ("Memória", "memoria",
         "memória exercícios cognitivos estimulação"),
        ("Coordenação Motora Fina", "coordenacao-motora-fina",
         "coordenação motora fina pinça caligrafia"),
        ("Atenção e Concentração", "atencao-concentracao",
         "atenção concentração foco exercícios"),
        ("Percepção Visual", "percepcao-visual",
         "percepção visual discriminação figura fundo"),
        ("Sequência Lógica", "sequencia-logica",
         "sequência lógica raciocínio ordem"),
    ]

    cur.executemany(
        f"INSERT INTO topicos (nome, slug, keywords) VALUES ({PH}, {PH}, {PH})",
        topicos,
    )
    conn.commit()


def _upsert_topico(nome: str, slug: str, keywords: str) -> None:
    """Insere tópico se o slug ainda não existe (idempotente)."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        if USE_POSTGRES:
            cur.execute(
                f"INSERT INTO topicos (nome, slug, keywords) VALUES ({PH}, {PH}, {PH}) "
                f"ON CONFLICT (slug) DO NOTHING",
                (nome, slug, keywords),
            )
        else:
            cur.execute(
                f"INSERT OR IGNORE INTO topicos (nome, slug, keywords) VALUES ({PH}, {PH}, {PH})",
                (nome, slug, keywords),
            )
        conn.commit()


def listar_topicos() -> list[dict]:
    """Retorna todos os tópicos ativos."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        if USE_POSTGRES:
            cur.execute("SELECT * FROM topicos WHERE ativo = TRUE ORDER BY id")
        else:
            cur.execute("SELECT * FROM topicos WHERE ativo = 1 ORDER BY id")
        return _rows_to_dicts(cur.fetchall(), cur)


def buscar_topico(slug: str) -> Optional[dict]:
    """Retorna um tópico pelo slug ou None se não encontrado."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(f"SELECT * FROM topicos WHERE slug = {PH}", (slug,))
        row = cur.fetchone()
        return _row_to_dict(row, cur)


def salvar_apostila(topico_id: int, num_exercicios: int, conteudo_json: str, produto_id=None) -> int:
    """Insere uma nova apostila e retorna o id gerado."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        sql = _insert_returning(
            f"INSERT INTO apostilas (topico_id, num_exercicios, conteudo_json, produto_id) "
            f"VALUES ({PH}, {PH}, {PH}, {PH})"
        )
        cur.execute(sql, (topico_id, num_exercicios, conteudo_json, produto_id))
        row_id = _lastrowid(cur, conn)
        conn.commit()
        return row_id


def buscar_apostila(topico_id: int, num_exercicios: int) -> Optional[dict]:
    """Retorna apostila existente para esse tópico+variação (cache)."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"SELECT * FROM apostilas WHERE topico_id = {PH} AND num_exercicios = {PH} "
            f"ORDER BY id DESC LIMIT 1",
            (topico_id, num_exercicios),
        )
        row = cur.fetchone()
        return _row_to_dict(row, cur)


def atualizar_pdf_apostila(apostila_id: int, pdf_path: str) -> None:
    """Atualiza o caminho do PDF de uma apostila."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"UPDATE apostilas SET pdf_path = {PH} WHERE id = {PH}",
            (pdf_path, apostila_id),
        )
        conn.commit()


def salvar_conteudo_apostila(apostila_id: int, conteudo_json: str, pdf_path: str) -> None:
    """Salva o conteúdo gerado e o caminho do PDF de uma apostila."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"UPDATE apostilas SET conteudo_json = {PH}, pdf_path = {PH} WHERE id = {PH}",
            (conteudo_json, pdf_path, apostila_id),
        )
        conn.commit()


def criar_anuncio(
    apostila_id: Optional[int] = None,
    tipo: str = "",
    template_id: int = 1,
    titulo: str = "",
    preco: float = 0.0,
    variacao: int = 1,
    angulo: str = "",
    kit_id: Optional[int] = None,
    descricao: str = "",
) -> int:
    """Insere um anúncio com status='rascunho' e retorna o id.

    Para anúncios de kit, apostila_id pode ser NULL e kit_id deve ser informado.
    """
    if apostila_id is None and kit_id is None:
        raise ValueError("criar_anuncio: apostila_id ou kit_id deve ser informado")
    if apostila_id is not None and kit_id is not None:
        raise ValueError("criar_anuncio: apostila_id e kit_id são mutuamente exclusivos")

    with _get_conn() as conn:
        cur = _cursor(conn)
        sql = _insert_returning(
            f"INSERT INTO anuncios "
            f"(apostila_id, tipo, template_id, titulo, preco, status, variacao, angulo, kit_id, descricao) "
            f"VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, 'rascunho', {PH}, {PH}, {PH}, {PH})"
        )
        cur.execute(sql, (apostila_id, tipo, template_id, titulo, preco, variacao, angulo, kit_id, descricao))
        row_id = _lastrowid(cur, conn)
        conn.commit()
        return row_id


def importar_anuncio_externo(ml_id: str, titulo: str, preco: float, status: str = "publicado", thumbnail: str = "") -> int:
    """Insere um anúncio importado do ML (sem apostila_id nem kit_id)."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        # Verifica se já existe
        cur.execute(f"SELECT id FROM anuncios WHERE ml_id = {PH}", (ml_id,))
        existing = cur.fetchone()
        if existing:
            return existing["id"] if USE_POSTGRES else existing[0]
        sql = _insert_returning(
            f"INSERT INTO anuncios "
            f"(apostila_id, kit_id, tipo, template_id, titulo, preco, status, variacao, angulo, ml_id, imagem_path) "
            f"VALUES (NULL, NULL, 'importado', 1, {PH}, {PH}, {PH}, 1, 'importado', {PH}, {PH})"
        )
        cur.execute(sql, (titulo, preco, status, ml_id, thumbnail))
        row_id = _lastrowid(cur, conn)
        conn.commit()
        return row_id


def listar_anuncios(
    status: Optional[str] = None,
    tipo: Optional[str] = None,
    topico_id: Optional[int] = None,
    kit_id: Optional[int] = None,
    apostila_id: Optional[int] = None,
    limite: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Lista anúncios com LEFT JOIN em apostilas, tópicos e kits.

    Inclui anúncios de kit (apostila_id=NULL). Retorna topico_nome e kit_nome.
    """
    with _get_conn() as conn:
        cur = _cursor(conn)
        sql = """
            SELECT
                an.*,
                ap.topico_id,
                ap.num_exercicios,
                ap.pdf_path,
                ap.produto_id,
                ap.criado_em AS apostila_criado_em,
                tp.nome AS topico_nome,
                tp.slug AS topico_slug,
                kt.nome AS kit_nome,
                pr.nome AS produto_nome,
                pr.serie AS produto_serie
            FROM anuncios an
            LEFT JOIN apostilas ap ON an.apostila_id = ap.id
            LEFT JOIN topicos   tp ON ap.topico_id   = tp.id
            LEFT JOIN kits      kt ON an.kit_id       = kt.id
            LEFT JOIN produtos  pr ON ap.produto_id   = pr.id
            WHERE 1=1
        """
        params: list = []

        if status is not None:
            sql += f" AND an.status = {PH}"
            params.append(status)
        else:
            sql += " AND an.status != 'deletado'"
        if tipo is not None:
            sql += f" AND an.tipo = {PH}"
            params.append(tipo)
        if topico_id is not None:
            sql += f" AND ap.topico_id = {PH}"
            params.append(topico_id)
        if kit_id is not None:
            sql += f" AND an.kit_id = {PH}"
            params.append(kit_id)
        if apostila_id is not None:
            sql += f" AND an.apostila_id = {PH}"
            params.append(apostila_id)

        sql += f" ORDER BY an.id DESC LIMIT {PH} OFFSET {PH}"
        params.extend([limite, offset])

        cur.execute(sql, params)
        return _rows_to_dicts(cur.fetchall(), cur)


def contar_anuncios_filtrado(
    status: Optional[str] = None,
    tipo: Optional[str] = None,
    topico_id: Optional[int] = None,
    kit_id: Optional[int] = None,
    apostila_id: Optional[int] = None,
) -> int:
    """Conta anúncios com os mesmos filtros de listar_anuncios."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        sql = """
            SELECT COUNT(*) FROM anuncios an
            LEFT JOIN apostilas ap ON an.apostila_id = ap.id
            WHERE 1=1
        """
        params = []
        if status is not None:
            sql += f" AND an.status = {PH}"
            params.append(status)
        else:
            sql += " AND an.status != 'deletado'"
        if tipo is not None:
            sql += f" AND an.tipo = {PH}"
            params.append(tipo)
        if topico_id is not None:
            sql += f" AND ap.topico_id = {PH}"
            params.append(topico_id)
        if kit_id is not None:
            sql += f" AND an.kit_id = {PH}"
            params.append(kit_id)
        if apostila_id is not None:
            sql += f" AND an.apostila_id = {PH}"
            params.append(apostila_id)
        cur.execute(sql, params)
        row = cur.fetchone()
        if not row:
            return 0
        # RealDictCursor (PG) retorna dict; SQLite retorna tupla
        val = list(row.values())[0] if isinstance(row, dict) else row[0]
        return int(val) if val is not None else 0


def buscar_anuncios_rascunho(limite: int = 30) -> list[dict]:
    """Retorna até `limite` anúncios com status='rascunho', incluindo dados da apostila."""
    return listar_anuncios(status="rascunho", limite=limite)


def atualizar_anuncio(anuncio_id: int, **kwargs) -> None:
    """Atualiza campos dinâmicos de um anúncio (só atualiza campos passados)."""
    if not kwargs:
        return

    campos_permitidos = {
        "status", "ml_id", "imagem_path", "erro_msg",
        "publicado_em", "titulo", "preco", "template_id",
        "variacao", "angulo", "kit_id", "apostila_id",
        "shopee_item_id", "shopee_status",
    }
    campos = {k: v for k, v in kwargs.items() if k in campos_permitidos}
    if not campos:
        return

    # Usa PH (não f-string literal "?") para compatibilidade PG/SQLite
    set_clause = ", ".join(f"{col} = {PH}" for col in campos)
    values = list(campos.values()) + [anuncio_id]

    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"UPDATE anuncios SET {set_clause} WHERE id = {PH}",
            values,
        )
        conn.commit()


def contar_anuncios(status: Optional[str] = None) -> dict:
    """Retorna contagem de anúncios por status."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        base_sql = """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'publicado' THEN 1 ELSE 0 END) AS publicados,
                SUM(CASE WHEN status = 'rascunho'  THEN 1 ELSE 0 END) AS rascunho,
                SUM(CASE WHEN status = 'erro'      THEN 1 ELSE 0 END) AS erro,
                SUM(CASE WHEN status = 'pausado'   THEN 1 ELSE 0 END) AS pausado
            FROM anuncios
        """
        if status:
            cur.execute(base_sql + f" WHERE status = {PH}", (status,))
        else:
            cur.execute(base_sql)
        row = cur.fetchone()
        d = _row_to_dict(row, cur) if USE_POSTGRES else dict(row)
        return {
            "total":      d.get("total") or 0,
            "publicados": d.get("publicados") or 0,
            "rascunho":   d.get("rascunho") or 0,
            "erro":       d.get("erro") or 0,
            "pausado":    d.get("pausado") or 0,
        }


# ---------------------------------------------------------------------------
# Kits
# ---------------------------------------------------------------------------

def criar_kit(nome: str, apostila_ids: list) -> int:
    """Cria um kit com lista de apostila_ids (JSON) e retorna o id gerado."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        sql = _insert_returning(
            f"INSERT INTO kits (nome, apostila_ids) VALUES ({PH}, {PH})"
        )
        cur.execute(sql, (nome, json.dumps(apostila_ids)))
        row_id = _lastrowid(cur, conn)
        conn.commit()
        return row_id


def listar_apostilas_por_topico_e_num_ex() -> dict:
    """Retorna {topico_id: {num_exercicios: apostila_id}} — apostila mais recente por (topico, tamanho)."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute("""
            SELECT topico_id, num_exercicios, MAX(id) AS apostila_id
            FROM apostilas
            WHERE produto_id IS NOT NULL
            GROUP BY topico_id, num_exercicios
        """)
        result: dict = {}
        for row in cur.fetchall():
            d = _row_to_dict(row, cur) if USE_POSTGRES else dict(row)
            t, n, a = d["topico_id"], d["num_exercicios"], d["apostila_id"]
            result.setdefault(t, {})[n] = a
        return result


def kit_existe(apostila_ids: list) -> bool:
    """Retorna True se já existe kit com exatamente esse conjunto de apostila_ids."""
    target = sorted(int(x) for x in apostila_ids)
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute("SELECT apostila_ids FROM kits")
        for row in cur.fetchall():
            d = _row_to_dict(row, cur) if USE_POSTGRES else dict(row)
            existing = sorted(int(x) for x in json.loads(d.get("apostila_ids") or "[]"))
            if existing == target:
                return True
        return False


def listar_kits() -> list:
    """Retorna todos os kits com contagem de apostilas."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute("SELECT * FROM kits ORDER BY id DESC")
        rows = _rows_to_dicts(cur.fetchall(), cur)
        for kit in rows:
            try:
                ids = json.loads(kit.get("apostila_ids") or "[]")
            except json.JSONDecodeError:
                ids = []
            kit["apostila_count"] = len(ids)
            kit["apostila_ids_list"] = ids
        return rows


def buscar_kit(kit_id: int) -> Optional[dict]:
    """Retorna um kit pelo id ou None."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(f"SELECT * FROM kits WHERE id = {PH}", (kit_id,))
        row = cur.fetchone()
        if row is None:
            return None
        kit = _row_to_dict(row, cur)
        try:
            ids = json.loads(kit.get("apostila_ids") or "[]")
        except json.JSONDecodeError:
            ids = []
        kit["apostila_count"] = len(ids)
        kit["apostila_ids_list"] = ids
        return kit


# ---------------------------------------------------------------------------
# Produtos (apostilas com contagem de anúncios)
# ---------------------------------------------------------------------------

def buscar_topico_por_id(topico_id: int) -> Optional[dict]:
    """Retorna um tópico pelo id ou None se não encontrado."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(f"SELECT * FROM topicos WHERE id = {PH}", (topico_id,))
        row = cur.fetchone()
        return _row_to_dict(row, cur)


def buscar_apostila_por_id(apostila_id: int) -> Optional[dict]:
    """Retorna uma apostila pelo id com dados do tópico e produto, ou None se não encontrada."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"SELECT ap.*, tp.nome AS topico_nome, tp.slug AS topico_slug, "
            f"p.nome AS produto_nome, p.tema AS produto_tema, p.dificuldade AS produto_dificuldade "
            f"FROM apostilas ap "
            f"LEFT JOIN topicos tp ON ap.topico_id = tp.id "
            f"LEFT JOIN produtos p ON ap.produto_id = p.id "
            f"WHERE ap.id = {PH}",
            (apostila_id,),
        )
        row = cur.fetchone()
        return _row_to_dict(row, cur)


def buscar_anuncio_por_id(anuncio_id: int) -> Optional[dict]:
    """Retorna um anúncio pelo id com dados de apostila, tópico e kit."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        sql = f"""
            SELECT an.*, ap.topico_id, ap.num_exercicios, ap.pdf_path,
                   tp.nome AS topico_nome, tp.slug AS topico_slug, kt.nome AS kit_nome
            FROM anuncios an
            LEFT JOIN apostilas ap ON an.apostila_id = ap.id
            LEFT JOIN topicos tp ON ap.topico_id = tp.id
            LEFT JOIN kits kt ON an.kit_id = kt.id
            WHERE an.id = {PH}
        """
        cur.execute(sql, (anuncio_id,))
        row = cur.fetchone()
        return _row_to_dict(row, cur)


def listar_produtos() -> list:
    """Retorna apostilas únicas com info do tópico e contagem de anúncios."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            """
            SELECT
                ap.id,
                ap.topico_id,
                ap.num_exercicios,
                ap.pdf_path,
                ap.criado_em,
                tp.nome AS topico_nome,
                tp.slug AS topico_slug,
                COUNT(an.id) AS total_anuncios,
                SUM(CASE WHEN an.status = 'publicado' THEN 1 ELSE 0 END) AS anuncios_publicados
            FROM apostilas ap
            LEFT JOIN topicos tp ON ap.topico_id = tp.id
            LEFT JOIN anuncios an ON an.apostila_id = ap.id
            GROUP BY ap.id, ap.topico_id, ap.num_exercicios, ap.pdf_path, ap.criado_em,
                     tp.nome, tp.slug
            ORDER BY ap.id DESC
            """
        )
        return _rows_to_dicts(cur.fetchall(), cur)


def salvar_ml_tokens(access_token: str, refresh_token: str, expires_at: str) -> None:
    """Upsert dos tokens do Mercado Livre (sempre id=1)."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        if USE_POSTGRES:
            cur.execute(
                """INSERT INTO ml_tokens (id, access_token, refresh_token, expires_at)
                   VALUES (1, %s, %s, %s)
                   ON CONFLICT(id) DO UPDATE SET
                       access_token  = EXCLUDED.access_token,
                       refresh_token = EXCLUDED.refresh_token,
                       expires_at    = EXCLUDED.expires_at""",
                (access_token, refresh_token, expires_at),
            )
        else:
            cur.execute(
                """INSERT INTO ml_tokens (id, access_token, refresh_token, expires_at)
                   VALUES (1, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       access_token  = excluded.access_token,
                       refresh_token = excluded.refresh_token,
                       expires_at    = excluded.expires_at""",
                (access_token, refresh_token, expires_at),
            )
        conn.commit()


def buscar_ml_tokens() -> Optional[dict]:
    """Retorna os tokens do Mercado Livre ou None."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute("SELECT * FROM ml_tokens WHERE id = 1")
        row = cur.fetchone()
        return _row_to_dict(row, cur)


def salvar_shopee_tokens(access_token: str, refresh_token: str, expires_at: str, shop_id: int) -> None:
    """Upsert dos tokens da Shopee (sempre id=1)."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        if USE_POSTGRES:
            cur.execute(
                """INSERT INTO shopee_tokens (id, access_token, refresh_token, expires_at, shop_id)
                   VALUES (1, %s, %s, %s, %s)
                   ON CONFLICT(id) DO UPDATE SET
                       access_token  = EXCLUDED.access_token,
                       refresh_token = EXCLUDED.refresh_token,
                       expires_at    = EXCLUDED.expires_at,
                       shop_id       = EXCLUDED.shop_id""",
                (access_token, refresh_token, expires_at, shop_id),
            )
        else:
            cur.execute(
                """INSERT INTO shopee_tokens (id, access_token, refresh_token, expires_at, shop_id)
                   VALUES (1, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       access_token  = excluded.access_token,
                       refresh_token = excluded.refresh_token,
                       expires_at    = excluded.expires_at,
                       shop_id       = excluded.shop_id""",
                (access_token, refresh_token, expires_at, shop_id),
            )
        conn.commit()


def buscar_shopee_tokens() -> Optional[dict]:
    """Retorna os tokens da Shopee ou None."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute("SELECT * FROM shopee_tokens WHERE id = 1")
        row = cur.fetchone()
        return _row_to_dict(row, cur)


# ---------------------------------------------------------------------------
# Delete helpers
# ---------------------------------------------------------------------------

def deletar_anuncios_por_apostila(apostila_id: int) -> list:
    """Marks all non-deleted anuncios of an apostila as 'deletado'.
    Returns list of ml_ids that had a published listing (for closing on ML)."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"SELECT id, ml_id FROM anuncios WHERE apostila_id = {PH} AND status != 'deletado'",
            (apostila_id,),
        )
        rows = _rows_to_dicts(cur.fetchall(), cur)
        ml_ids = [r["ml_id"] for r in rows if r.get("ml_id")]
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join([PH] * len(ids))
            cur.execute(
                f"UPDATE anuncios SET status = 'deletado' WHERE id IN ({placeholders})",
                ids,
            )
        conn.commit()
        return ml_ids


def deletar_apostila(apostila_id: int) -> None:
    """Hard-deletes an apostila and its anuncio rows."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(f"DELETE FROM anuncios WHERE apostila_id = {PH}", (apostila_id,))
        cur.execute(f"DELETE FROM apostilas WHERE id = {PH}", (apostila_id,))
        conn.commit()


def deletar_anuncios_por_kit(kit_id: int) -> list:
    """Marks all non-deleted anuncios of a kit as 'deletado'.
    Returns list of ml_ids for ML closing."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"SELECT id, ml_id FROM anuncios WHERE kit_id = {PH} AND status != 'deletado'",
            (kit_id,),
        )
        rows = _rows_to_dicts(cur.fetchall(), cur)
        ml_ids = [r["ml_id"] for r in rows if r.get("ml_id")]
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join([PH] * len(ids))
            cur.execute(
                f"UPDATE anuncios SET status = 'deletado' WHERE id IN ({placeholders})",
                ids,
            )
        conn.commit()
        return ml_ids


def fix_precos_kits_db(desconto: float = 0.85) -> list[dict]:
    """Recalcula e atualiza o preço de todos os anúncios de kit não publicados.

    Para cada kit, soma o preço do anúncio físico mais barato de cada apostila
    (ou usa 79.90 como fallback) e aplica o desconto. Retorna lista de alterações.
    """
    with _get_conn() as conn:
        cur = _cursor(conn)

        # Busca todos os anúncios de kit não publicados com seus kit_ids
        cur.execute("""
            SELECT an.id, an.kit_id, an.preco, k.apostila_ids
            FROM anuncios an
            JOIN kits k ON an.kit_id = k.id
            WHERE an.kit_id IS NOT NULL
              AND (an.status IS NULL OR an.status NOT IN ('publicado', 'deletado'))
        """)
        rows = _rows_to_dicts(cur.fetchall(), cur)

        alteracoes = []
        kits_preco: dict = {}

        for row in rows:
            kit_id = row["kit_id"]
            if kit_id not in kits_preco:
                try:
                    apostila_ids = json.loads(row.get("apostila_ids") or "[]")
                except Exception:
                    apostila_ids = []

                total = 0.0
                for aid in apostila_ids:
                    cur.execute(f"""
                        SELECT preco FROM anuncios
                        WHERE apostila_id = {PH} AND tipo = 'fisico'
                          AND status NOT IN ('deletado')
                        ORDER BY preco DESC LIMIT 1
                    """, (aid,))
                    r = cur.fetchone()
                    total += float(r[0]) if r and r[0] else 79.90

                kits_preco[kit_id] = round(total * desconto, 2)

            novo_preco = kits_preco[kit_id]
            preco_atual = float(row.get("preco") or 0)
            if abs(preco_atual - novo_preco) > 0.01:
                cur.execute(
                    f"UPDATE anuncios SET preco = {PH} WHERE id = {PH}",
                    (novo_preco, row["id"]),
                )
                alteracoes.append({
                    "anuncio_id": row["id"],
                    "kit_id": kit_id,
                    "preco_antigo": preco_atual,
                    "preco_novo": novo_preco,
                })

        conn.commit()
        return alteracoes


def deletar_kit(kit_id: int) -> None:
    """Hard-deletes a kit and its anuncio rows."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(f"DELETE FROM anuncios WHERE kit_id = {PH}", (kit_id,))
        cur.execute(f"DELETE FROM kits WHERE id = {PH}", (kit_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# Vendas
# ---------------------------------------------------------------------------

def buscar_anuncio_id_por_ml_id(ml_id: str) -> Optional[int]:
    """Retorna o id do anúncio com o ml_id informado, ou None se não encontrado."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(f"SELECT id FROM anuncios WHERE ml_id = {PH}", (ml_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return row["id"] if USE_POSTGRES else row[0]


def salvar_venda(
    ml_order_id: str,
    anuncio_id: Optional[int],
    comprador_nickname: str,
    valor: float,
    quantidade: int,
    data_venda: str,
    comprador_id: str = "",
) -> None:
    """Upsert de uma venda pelo ml_order_id (não cria duplicatas)."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        if USE_POSTGRES:
            cur.execute(
                """INSERT INTO vendas
                   (ml_order_id, anuncio_id, comprador_nickname, valor, quantidade, data_venda, comprador_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT(ml_order_id) DO UPDATE SET
                     anuncio_id=EXCLUDED.anuncio_id,
                     comprador_nickname=EXCLUDED.comprador_nickname,
                     valor=EXCLUDED.valor,
                     quantidade=EXCLUDED.quantidade,
                     data_venda=EXCLUDED.data_venda,
                     comprador_id=EXCLUDED.comprador_id,
                     sincronizado_em=NOW()::TEXT""",
                (ml_order_id, anuncio_id, comprador_nickname, valor, quantidade, data_venda, comprador_id),
            )
        else:
            cur.execute(
                """INSERT INTO vendas
                   (ml_order_id, anuncio_id, comprador_nickname, valor, quantidade, data_venda, comprador_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ml_order_id) DO UPDATE SET
                     anuncio_id=excluded.anuncio_id,
                     comprador_nickname=excluded.comprador_nickname,
                     valor=excluded.valor,
                     quantidade=excluded.quantidade,
                     data_venda=excluded.data_venda,
                     comprador_id=excluded.comprador_id,
                     sincronizado_em=datetime('now')""",
                (ml_order_id, anuncio_id, comprador_nickname, valor, quantidade, data_venda, comprador_id),
            )
        conn.commit()


def marcar_pdf_entregue(ml_order_id: str) -> None:
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(f"UPDATE vendas SET pdf_entregue=1 WHERE ml_order_id={PH}", (ml_order_id,))
        conn.commit()


def buscar_venda_por_order_id(ml_order_id: str) -> Optional[dict]:
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"""SELECT v.*, a.tipo AS anuncio_tipo, a.apostila_id
               FROM vendas v
               LEFT JOIN anuncios a ON v.anuncio_id = a.id
               WHERE v.ml_order_id = {PH}""",
            (ml_order_id,),
        )
        row = cur.fetchone()
        return _row_to_dict(row, cur)


def listar_vendas(
    apostila_id: Optional[int] = None,
    anuncio_id: Optional[int] = None,
    sem_apostila: bool = False,
) -> list[dict]:
    """Lista vendas com JOIN em anuncios, apostilas e topicos."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        sql = f"""
            SELECT
                v.*,
                an.titulo      AS anuncio_titulo,
                an.ml_id       AS anuncio_ml_id,
                tp.nome        AS topico_nome,
                ap.id          AS apostila_id,
                ap.num_exercicios
            FROM vendas v
            LEFT JOIN anuncios  an ON v.anuncio_id   = an.id
            LEFT JOIN apostilas ap ON an.apostila_id  = ap.id
            LEFT JOIN topicos   tp ON ap.topico_id    = tp.id
            WHERE 1=1
        """
        params: list = []
        if apostila_id is not None:
            sql += f" AND an.apostila_id = {PH}"
            params.append(apostila_id)
        if anuncio_id is not None:
            sql += f" AND v.anuncio_id = {PH}"
            params.append(anuncio_id)
        if sem_apostila:
            sql += " AND (v.anuncio_id IS NULL OR an.apostila_id IS NULL)"
        sql += " ORDER BY v.data_venda DESC"
        cur.execute(sql, params)
        return _rows_to_dicts(cur.fetchall(), cur)


def resumo_vendas_por_apostila() -> list[dict]:
    """Agrega vendas por apostila. Vendas sem apostila vinculada aparecem como apostila_id=None."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        # Vendas vinculadas a uma apostila
        cur.execute("""
            SELECT
                ap.id                          AS apostila_id,
                tp.nome                        AS topico_nome,
                ap.num_exercicios,
                COUNT(v.id)                    AS total_vendas,
                SUM(v.valor * v.quantidade)    AS faturamento
            FROM vendas v
            JOIN anuncios  an ON v.anuncio_id  = an.id
            JOIN apostilas ap ON an.apostila_id = ap.id
            JOIN topicos   tp ON ap.topico_id   = tp.id
            GROUP BY ap.id, tp.nome, ap.num_exercicios
            ORDER BY total_vendas DESC
        """)
        rows = _rows_to_dicts(cur.fetchall(), cur)

        # Vendas sem apostila vinculada (anuncio_id null ou anuncio sem apostila)
        cur.execute("""
            SELECT COUNT(v.id) AS total_vendas, SUM(v.valor * v.quantidade) AS faturamento
            FROM vendas v
            LEFT JOIN anuncios an ON v.anuncio_id = an.id
            WHERE v.anuncio_id IS NULL OR an.apostila_id IS NULL
        """)
        outros_row = cur.fetchone()
        outros = _row_to_dict(outros_row, cur)
        if outros and outros.get("total_vendas") and outros["total_vendas"] > 0:
            rows.append({
                "apostila_id": None,
                "topico_nome": "Outros anúncios",
                "num_exercicios": None,
                "total_vendas": outros["total_vendas"],
                "faturamento": outros["faturamento"],
            })

        return rows


def buscar_apostilas_vendidas_sem_pdf() -> list[dict]:
    """Retorna apostilas que tiveram vendas mas ainda não têm PDF gerado."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute("""
            SELECT DISTINCT ap.id, ap.topico_id, ap.num_exercicios, ap.conteudo_json,
                            tp.nome AS topico_nome
            FROM vendas v
            JOIN anuncios  an ON v.anuncio_id  = an.id
            JOIN apostilas ap ON an.apostila_id = ap.id
            JOIN topicos   tp ON ap.topico_id   = tp.id
            WHERE (ap.pdf_path IS NULL OR ap.pdf_path = '')
        """)
        return _rows_to_dicts(cur.fetchall(), cur)


def listar_todas_apostilas() -> list[dict]:
    """Retorna todas as apostilas com nome do tópico (para o dropdown de link)."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute("""
            SELECT ap.id, ap.num_exercicios, tp.nome AS topico_nome
            FROM apostilas ap
            JOIN topicos tp ON ap.topico_id = tp.id
            ORDER BY tp.nome, ap.num_exercicios
        """)
        return _rows_to_dicts(cur.fetchall(), cur)


def criar_produto(nome: str, topico_id: int, serie: int = 1) -> int:
    with _get_conn() as conn:
        cur = _cursor(conn)
        sql = _insert_returning(
            f"INSERT INTO produtos (nome, serie, topico_id) VALUES ({PH}, {PH}, {PH})"
        )
        cur.execute(sql, (nome, serie, topico_id))
        row_id = _lastrowid(cur, conn)
        conn.commit()
        return row_id


def criar_produto_caca_palavras(nome: str, topico_id: int, tema: str, dificuldade: str, serie: int = 1) -> int:
    """Cria produto de caça-palavras com tema e dificuldade."""
    with _get_conn() as conn:
        cur = _cursor(conn)
        sql = _insert_returning(
            f"INSERT INTO produtos (nome, topico_id, tema, dificuldade, serie) "
            f"VALUES ({PH}, {PH}, {PH}, {PH}, {PH})"
        )
        cur.execute(sql, (nome, topico_id, tema, dificuldade, serie))
        row_id = _lastrowid(cur, conn)
        conn.commit()
        return row_id


def listar_produtos_com_apostilas() -> list:
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            "SELECT p.*, tp.nome AS topico_nome, tp.slug AS topico_slug FROM produtos p "
            "LEFT JOIN topicos tp ON p.topico_id = tp.id ORDER BY p.id DESC"
        )
        produtos = _rows_to_dicts(cur.fetchall(), cur)
        result = []
        for prod in produtos:
            cur2 = _cursor(conn)
            cur2.execute(
                f"""SELECT ap.id, ap.num_exercicios, ap.pdf_path, ap.criado_em,
                          COUNT(CASE WHEN an.status != 'deletado' THEN 1 END) AS total_anuncios,
                          SUM(CASE WHEN an.status='publicado' THEN 1 ELSE 0 END) AS anuncios_publicados,
                          SUM(CASE WHEN an.status='rascunho'  THEN 1 ELSE 0 END) AS anuncios_rascunho
                   FROM apostilas ap LEFT JOIN anuncios an ON an.apostila_id = ap.id
                   WHERE ap.produto_id = {PH} GROUP BY ap.id, ap.num_exercicios, ap.pdf_path, ap.criado_em
                   ORDER BY ap.num_exercicios""",
                (prod["id"],)
            )
            apostilas_list = _rows_to_dicts(cur2.fetchall(), cur2)
            prod["apostilas"] = apostilas_list
            # Agrega contadores no nível do produto
            prod["total_anuncios"] = sum(a.get("total_anuncios") or 0 for a in apostilas_list)
            prod["anuncios_publicados"] = sum(a.get("anuncios_publicados") or 0 for a in apostilas_list)
            prod["anuncios_rascunho"] = sum(a.get("anuncios_rascunho") or 0 for a in apostilas_list)
            # ID da primeira apostila (menor num_exercicios) para thumbnail
            prod["thumb_apostila_id"] = apostilas_list[0]["id"] if apostilas_list else None
            result.append(prod)
        return result


def listar_apostilas_por_produto(produto_id: int) -> list:
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"SELECT * FROM apostilas WHERE produto_id = {PH} ORDER BY num_exercicios",
            (produto_id,),
        )
        return _rows_to_dicts(cur.fetchall(), cur)


def deletar_produto(produto_id: int) -> None:
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(f"DELETE FROM produtos WHERE id = {PH}", (produto_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# Smoke-test: executar diretamente para verificar criação do banco
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Banco: {'PostgreSQL' if USE_POSTGRES else f'SQLite em {DB_PATH}'}")
    criar_tabelas()

    topicos = listar_topicos()
    print(f"Tópicos inseridos: {len(topicos)}")
    for t in topicos:
        print(f"  [{t['id']}] {t['nome']} (slug={t['slug']})")

    # Smoke-test apostila
    apostila_id = salvar_apostila(topico_id=1, num_exercicios=60, conteudo_json='{"exercicios":[]}')
    print(f"Apostila criada: id={apostila_id}")

    apostila = buscar_apostila(topico_id=1, num_exercicios=60)
    print(f"Apostila encontrada: {apostila['id']}")

    # Smoke-test anuncio
    anuncio_id = criar_anuncio(
        apostila_id=apostila_id,
        tipo="digital",
        template_id=1,
        titulo="Apostila de Coordenação Motora - 60 exercícios",
        preco=29.90,
    )
    print(f"Anúncio criado: id={anuncio_id}")

    atualizar_anuncio(anuncio_id, status="publicado", ml_id="MLB123456")
    rascunhos = buscar_anuncios_rascunho()
    print(f"Rascunhos: {len(rascunhos)}")

    contagem = contar_anuncios()
    print(f"Contagem: {contagem}")

    # Smoke-test anuncio com variacao/angulo
    anuncio_var_id = criar_anuncio(
        apostila_id=apostila_id,
        tipo="digital",
        template_id=2,
        titulo="Apostila de Coordenação Motora - variação beneficio",
        preco=29.90,
        variacao=2,
        angulo="beneficio",
    )
    print(f"Anúncio com variacao criado: id={anuncio_var_id}")

    # Smoke-test kits
    kit_id = criar_kit(nome="Kit Coordenação Completo", apostila_ids=[apostila_id])
    print(f"Kit criado: id={kit_id}")

    kits = listar_kits()
    print(f"Kits listados: {len(kits)} — primeiro: {kits[0]['nome']} ({kits[0]['apostila_count']} apostilas)")

    kit = buscar_kit(kit_id)
    print(f"Kit encontrado: {kit['nome']}, ids={kit['apostila_ids_list']}")

    # Smoke-test anuncio de kit (apostila_id=None)
    anuncio_kit_id = criar_anuncio(
        tipo="digital",
        template_id=1,
        titulo="Kit Coordenação Completo",
        preco=59.90,
        kit_id=kit_id,
    )
    print(f"Anúncio de kit criado: id={anuncio_kit_id}")

    # Listar anuncios inclui anuncio de kit (LEFT JOIN)
    todos = listar_anuncios()
    print(f"Total anúncios (incl. kit): {len(todos)}")

    kit_anuncios = listar_anuncios(kit_id=kit_id)
    print(f"Anúncios do kit: {len(kit_anuncios)} — kit_nome={kit_anuncios[0]['kit_nome']}")

    # Smoke-test listar_produtos
    produtos = listar_produtos()
    print(f"Produtos listados: {len(produtos)} — primeiro: {produtos[0]['topico_nome']} ({produtos[0]['total_anuncios']} anúncios)")

    # Smoke-test atualizar_anuncio com novos campos
    atualizar_anuncio(anuncio_var_id, variacao=3, angulo="publico")
    print("atualizar_anuncio com variacao/angulo: OK")

    # Smoke-test ML tokens
    salvar_ml_tokens("tok_acc", "tok_ref", "2026-12-31T00:00:00")
    tokens = buscar_ml_tokens()
    print(f"ML tokens: access={tokens['access_token']}")

    print("\nOK — banco criado e todas as funções funcionando.")
