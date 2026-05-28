import sqlite3
import json
import os
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apostilas.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def criar_tabelas() -> None:
    """Cria todas as tabelas se não existirem e popula tópicos padrão."""
    conn = _get_conn()
    try:
        cur = conn.cursor()

        cur.executescript("""
            CREATE TABLE IF NOT EXISTS topicos (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                nome     TEXT NOT NULL,
                slug     TEXT UNIQUE NOT NULL,
                keywords TEXT,
                ativo    INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS apostilas (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                topico_id      INTEGER REFERENCES topicos(id),
                num_exercicios INTEGER NOT NULL,
                conteudo_json  TEXT,
                pdf_path       TEXT,
                criado_em      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS anuncios (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                apostila_id  INTEGER REFERENCES apostilas(id),
                tipo         TEXT NOT NULL,
                template_id  INTEGER DEFAULT 1,
                ml_id        TEXT,
                status       TEXT DEFAULT 'rascunho',
                titulo       TEXT,
                preco        REAL,
                imagem_path  TEXT,
                publicado_em TEXT,
                erro_msg     TEXT
            );

            CREATE TABLE IF NOT EXISTS ml_tokens (
                id            INTEGER PRIMARY KEY DEFAULT 1,
                access_token  TEXT,
                refresh_token TEXT,
                expires_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS kits (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                nome         TEXT NOT NULL,
                apostila_ids TEXT NOT NULL,
                criado_em    TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS vendas (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                ml_order_id         TEXT UNIQUE NOT NULL,
                anuncio_id          INTEGER REFERENCES anuncios(id),
                comprador_nickname  TEXT DEFAULT '',
                valor               REAL DEFAULT 0.0,
                quantidade          INTEGER DEFAULT 1,
                data_venda          TEXT,
                sincronizado_em     TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS produtos (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                nome      TEXT NOT NULL,
                serie     INTEGER DEFAULT 1,
                topico_id INTEGER REFERENCES topicos(id),
                criado_em TEXT DEFAULT (datetime('now'))
            );
        """)

        # Migration: add new columns to anuncios (SQLite workaround for ADD COLUMN IF NOT EXISTS).
        # SQLite does not support FK constraints in ALTER TABLE, so kit_id has no REFERENCES
        # clause here. Integrity is enforced at application level in criar_anuncio().
        for col_name, col_def in [
            ("variacao",  "INTEGER DEFAULT 1"),
            ("angulo",    "TEXT DEFAULT ''"),
            ("kit_id",    "INTEGER"),
            ("descricao", "TEXT DEFAULT ''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE anuncios ADD COLUMN {col_name} {col_def}")
            except sqlite3.OperationalError:
                pass  # column already exists

        for col_name, col_def in [
            ("produto_id", "INTEGER"),
        ]:
            try:
                conn.execute(f"ALTER TABLE apostilas ADD COLUMN {col_name} {col_def}")
            except sqlite3.OperationalError:
                pass  # column already exists

        conn.commit()
        seed_topicos(conn)
    finally:
        conn.close()


def seed_topicos(conn: Optional[sqlite3.Connection] = None) -> None:
    """Insere os 6 tópicos padrão se a tabela estiver vazia."""
    close_after = conn is None
    if conn is None:
        conn = _get_conn()

    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM topicos")
        count = cur.fetchone()[0]
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
            "INSERT INTO topicos (nome, slug, keywords) VALUES (?, ?, ?)",
            topicos,
        )
        conn.commit()
    finally:
        if close_after:
            conn.close()


def listar_topicos() -> list[dict]:
    """Retorna todos os tópicos ativos."""
    conn = _get_conn()
    try:
        cur = conn.execute("SELECT * FROM topicos WHERE ativo = 1 ORDER BY id")
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def buscar_topico(slug: str) -> Optional[dict]:
    """Retorna um tópico pelo slug ou None se não encontrado."""
    conn = _get_conn()
    try:
        cur = conn.execute("SELECT * FROM topicos WHERE slug = ?", (slug,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def salvar_apostila(topico_id: int, num_exercicios: int, conteudo_json: str, produto_id=None) -> int:
    """Insere uma nova apostila e retorna o id gerado."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO apostilas (topico_id, num_exercicios, conteudo_json, produto_id) VALUES (?, ?, ?, ?)",
            (topico_id, num_exercicios, conteudo_json, produto_id),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def buscar_apostila(topico_id: int, num_exercicios: int) -> Optional[dict]:
    """Retorna apostila existente para esse tópico+variação (cache)."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            "SELECT * FROM apostilas WHERE topico_id = ? AND num_exercicios = ? ORDER BY id DESC LIMIT 1",
            (topico_id, num_exercicios),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def atualizar_pdf_apostila(apostila_id: int, pdf_path: str) -> None:
    """Atualiza o caminho do PDF de uma apostila."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE apostilas SET pdf_path = ? WHERE id = ?",
            (pdf_path, apostila_id),
        )
        conn.commit()
    finally:
        conn.close()


def salvar_conteudo_apostila(apostila_id: int, conteudo_json: str, pdf_path: str) -> None:
    """Salva o conteúdo gerado e o caminho do PDF de uma apostila."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE apostilas SET conteudo_json = ?, pdf_path = ? WHERE id = ?",
            (conteudo_json, pdf_path, apostila_id),
        )
        conn.commit()
    finally:
        conn.close()


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

    conn = _get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO anuncios
               (apostila_id, tipo, template_id, titulo, preco, status, variacao, angulo, kit_id, descricao)
               VALUES (?, ?, ?, ?, ?, 'rascunho', ?, ?, ?, ?)""",
            (apostila_id, tipo, template_id, titulo, preco, variacao, angulo, kit_id, descricao),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def importar_anuncio_externo(ml_id: str, titulo: str, preco: float, status: str = "publicado", thumbnail: str = "") -> int:
    """Insere um anúncio importado do ML (sem apostila_id nem kit_id)."""
    conn = _get_conn()
    try:
        # Verifica se já existe
        existing = conn.execute("SELECT id FROM anuncios WHERE ml_id = ?", (ml_id,)).fetchone()
        if existing:
            return existing[0]
        cur = conn.execute(
            """INSERT INTO anuncios
               (apostila_id, kit_id, tipo, template_id, titulo, preco, status, variacao, angulo, ml_id, imagem_path)
               VALUES (NULL, NULL, 'importado', 1, ?, ?, ?, 1, 'importado', ?, ?)""",
            (titulo, preco, status, ml_id, thumbnail),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


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
    conn = _get_conn()
    try:
        sql = """
            SELECT
                an.*,
                ap.topico_id,
                ap.num_exercicios,
                ap.pdf_path,
                ap.criado_em AS apostila_criado_em,
                tp.nome AS topico_nome,
                tp.slug AS topico_slug,
                kt.nome AS kit_nome
            FROM anuncios an
            LEFT JOIN apostilas ap ON an.apostila_id = ap.id
            LEFT JOIN topicos   tp ON ap.topico_id   = tp.id
            LEFT JOIN kits      kt ON an.kit_id       = kt.id
            WHERE 1=1
        """
        params: list = []

        if status is not None:
            sql += " AND an.status = ?"
            params.append(status)
        if tipo is not None:
            sql += " AND an.tipo = ?"
            params.append(tipo)
        if topico_id is not None:
            sql += " AND ap.topico_id = ?"
            params.append(topico_id)
        if kit_id is not None:
            sql += " AND an.kit_id = ?"
            params.append(kit_id)
        if apostila_id is not None:
            sql += " AND an.apostila_id = ?"
            params.append(apostila_id)

        sql += " ORDER BY an.id DESC LIMIT ? OFFSET ?"
        params.extend([limite, offset])

        cur = conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


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
    }
    campos = {k: v for k, v in kwargs.items() if k in campos_permitidos}
    if not campos:
        return

    set_clause = ", ".join(f"{col} = ?" for col in campos)
    values = list(campos.values()) + [anuncio_id]

    conn = _get_conn()
    try:
        conn.execute(
            f"UPDATE anuncios SET {set_clause} WHERE id = ?",
            values,
        )
        conn.commit()
    finally:
        conn.close()


def contar_anuncios(status: Optional[str] = None) -> dict:
    """Retorna contagem de anúncios por status."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            """SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'publicado' THEN 1 ELSE 0 END) AS publicados,
                SUM(CASE WHEN status = 'rascunho'  THEN 1 ELSE 0 END) AS rascunho,
                SUM(CASE WHEN status = 'erro'      THEN 1 ELSE 0 END) AS erro,
                SUM(CASE WHEN status = 'pausado'   THEN 1 ELSE 0 END) AS pausado
            FROM anuncios
            """
            + ("WHERE status = ?" if status else ""),
            ([status] if status else []),
        )
        row = cur.fetchone()
        return {
            "total":      row["total"] or 0,
            "publicados": row["publicados"] or 0,
            "rascunho":   row["rascunho"] or 0,
            "erro":       row["erro"] or 0,
            "pausado":    row["pausado"] or 0,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Kits
# ---------------------------------------------------------------------------

def criar_kit(nome: str, apostila_ids: list) -> int:
    """Cria um kit com lista de apostila_ids (JSON) e retorna o id gerado."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO kits (nome, apostila_ids) VALUES (?, ?)",
            (nome, json.dumps(apostila_ids)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_kits() -> list:
    """Retorna todos os kits com contagem de apostilas."""
    conn = _get_conn()
    try:
        cur = conn.execute("SELECT * FROM kits ORDER BY id DESC")
        rows = [dict(row) for row in cur.fetchall()]
        for kit in rows:
            try:
                ids = json.loads(kit.get("apostila_ids") or "[]")
            except json.JSONDecodeError:
                ids = []
            kit["apostila_count"] = len(ids)
            kit["apostila_ids_list"] = ids
        return rows
    finally:
        conn.close()


def buscar_kit(kit_id: int) -> Optional[dict]:
    """Retorna um kit pelo id ou None."""
    conn = _get_conn()
    try:
        cur = conn.execute("SELECT * FROM kits WHERE id = ?", (kit_id,))
        row = cur.fetchone()
        if row is None:
            return None
        kit = dict(row)
        try:
            ids = json.loads(kit.get("apostila_ids") or "[]")
        except json.JSONDecodeError:
            ids = []
        kit["apostila_count"] = len(ids)
        kit["apostila_ids_list"] = ids
        return kit
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Produtos (apostilas com contagem de anúncios)
# ---------------------------------------------------------------------------

def buscar_topico_por_id(topico_id: int) -> Optional[dict]:
    """Retorna um tópico pelo id ou None se não encontrado."""
    conn = _get_conn()
    try:
        cur = conn.execute("SELECT * FROM topicos WHERE id = ?", (topico_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def buscar_apostila_por_id(apostila_id: int) -> Optional[dict]:
    """Retorna uma apostila pelo id com dados do tópico, ou None se não encontrada."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            "SELECT ap.*, tp.nome AS topico_nome, tp.slug AS topico_slug "
            "FROM apostilas ap LEFT JOIN topicos tp ON ap.topico_id = tp.id "
            "WHERE ap.id = ?",
            (apostila_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def buscar_anuncio_por_id(anuncio_id: int) -> Optional[dict]:
    """Retorna um anúncio pelo id com dados de apostila, tópico e kit."""
    conn = _get_conn()
    try:
        sql = """
            SELECT an.*, ap.topico_id, ap.num_exercicios, ap.pdf_path,
                   tp.nome AS topico_nome, tp.slug AS topico_slug, kt.nome AS kit_nome
            FROM anuncios an
            LEFT JOIN apostilas ap ON an.apostila_id = ap.id
            LEFT JOIN topicos tp ON ap.topico_id = tp.id
            LEFT JOIN kits kt ON an.kit_id = kt.id
            WHERE an.id = ?
        """
        cur = conn.execute(sql, (anuncio_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def listar_produtos() -> list:
    """Retorna apostilas únicas com info do tópico e contagem de anúncios."""
    conn = _get_conn()
    try:
        cur = conn.execute(
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
            GROUP BY ap.id
            ORDER BY ap.id DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def salvar_ml_tokens(access_token: str, refresh_token: str, expires_at: str) -> None:
    """Upsert dos tokens do Mercado Livre (sempre id=1)."""
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO ml_tokens (id, access_token, refresh_token, expires_at)
               VALUES (1, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   access_token  = excluded.access_token,
                   refresh_token = excluded.refresh_token,
                   expires_at    = excluded.expires_at""",
            (access_token, refresh_token, expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def buscar_ml_tokens() -> Optional[dict]:
    """Retorna os tokens do Mercado Livre ou None."""
    conn = _get_conn()
    try:
        cur = conn.execute("SELECT * FROM ml_tokens WHERE id = 1")
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Delete helpers
# ---------------------------------------------------------------------------

def deletar_anuncios_por_apostila(apostila_id: int) -> list:
    """Marks all non-deleted anuncios of an apostila as 'deletado'.
    Returns list of ml_ids that had a published listing (for closing on ML)."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            "SELECT id, ml_id FROM anuncios WHERE apostila_id = ? AND status != 'deletado'",
            (apostila_id,),
        )
        rows = cur.fetchall()
        ml_ids = [r["ml_id"] for r in rows if r["ml_id"]]
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE anuncios SET status = 'deletado' WHERE id IN ({placeholders})",
                ids,
            )
        conn.commit()
        return ml_ids
    finally:
        conn.close()


def deletar_apostila(apostila_id: int) -> None:
    """Hard-deletes an apostila and its anuncio rows."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM anuncios WHERE apostila_id = ?", (apostila_id,))
        conn.execute("DELETE FROM apostilas WHERE id = ?", (apostila_id,))
        conn.commit()
    finally:
        conn.close()


def deletar_anuncios_por_kit(kit_id: int) -> list:
    """Marks all non-deleted anuncios of a kit as 'deletado'.
    Returns list of ml_ids for ML closing."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            "SELECT id, ml_id FROM anuncios WHERE kit_id = ? AND status != 'deletado'",
            (kit_id,),
        )
        rows = cur.fetchall()
        ml_ids = [r["ml_id"] for r in rows if r["ml_id"]]
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE anuncios SET status = 'deletado' WHERE id IN ({placeholders})",
                ids,
            )
        conn.commit()
        return ml_ids
    finally:
        conn.close()


def deletar_kit(kit_id: int) -> None:
    """Hard-deletes a kit and its anuncio rows."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM anuncios WHERE kit_id = ?", (kit_id,))
        conn.execute("DELETE FROM kits WHERE id = ?", (kit_id,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Vendas
# ---------------------------------------------------------------------------

def buscar_anuncio_id_por_ml_id(ml_id: str) -> Optional[int]:
    """Retorna o id do anúncio com o ml_id informado, ou None se não encontrado."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT id FROM anuncios WHERE ml_id = ?", (ml_id,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def salvar_venda(
    ml_order_id: str,
    anuncio_id: Optional[int],
    comprador_nickname: str,
    valor: float,
    quantidade: int,
    data_venda: str,
) -> None:
    """Upsert de uma venda pelo ml_order_id (não cria duplicatas)."""
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO vendas
               (ml_order_id, anuncio_id, comprador_nickname, valor, quantidade, data_venda)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(ml_order_id) DO UPDATE SET
                 anuncio_id=excluded.anuncio_id,
                 comprador_nickname=excluded.comprador_nickname,
                 valor=excluded.valor,
                 quantidade=excluded.quantidade,
                 data_venda=excluded.data_venda,
                 sincronizado_em=datetime('now')""",
            (ml_order_id, anuncio_id, comprador_nickname, valor, quantidade, data_venda),
        )
        conn.commit()
    finally:
        conn.close()


def listar_vendas(
    apostila_id: Optional[int] = None,
    anuncio_id: Optional[int] = None,
    sem_apostila: bool = False,
) -> list[dict]:
    """Lista vendas com JOIN em anuncios, apostilas e topicos."""
    conn = _get_conn()
    try:
        sql = """
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
            sql += " AND an.apostila_id = ?"
            params.append(apostila_id)
        if anuncio_id is not None:
            sql += " AND v.anuncio_id = ?"
            params.append(anuncio_id)
        if sem_apostila:
            sql += " AND (v.anuncio_id IS NULL OR an.apostila_id IS NULL)"
        sql += " ORDER BY v.data_venda DESC"
        cur = conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def resumo_vendas_por_apostila() -> list[dict]:
    """Agrega vendas por apostila. Vendas sem apostila vinculada aparecem como apostila_id=None."""
    conn = _get_conn()
    try:
        # Vendas vinculadas a uma apostila
        cur = conn.execute("""
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
        rows = [dict(row) for row in cur.fetchall()]

        # Vendas sem apostila vinculada (anuncio_id null ou anuncio sem apostila)
        cur2 = conn.execute("""
            SELECT COUNT(v.id) AS total_vendas, SUM(v.valor * v.quantidade) AS faturamento
            FROM vendas v
            LEFT JOIN anuncios an ON v.anuncio_id = an.id
            WHERE v.anuncio_id IS NULL OR an.apostila_id IS NULL
        """)
        outros = dict(cur2.fetchone())
        if outros["total_vendas"] and outros["total_vendas"] > 0:
            rows.append({
                "apostila_id": None,
                "topico_nome": "Outros anúncios",
                "num_exercicios": None,
                "total_vendas": outros["total_vendas"],
                "faturamento": outros["faturamento"],
            })

        return rows
    finally:
        conn.close()


def listar_todas_apostilas() -> list[dict]:
    """Retorna todas as apostilas com nome do tópico (para o dropdown de link)."""
    conn = _get_conn()
    try:
        cur = conn.execute("""
            SELECT ap.id, ap.num_exercicios, tp.nome AS topico_nome
            FROM apostilas ap
            JOIN topicos tp ON ap.topico_id = tp.id
            ORDER BY tp.nome, ap.num_exercicios
        """)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def criar_produto(nome: str, topico_id: int, serie: int = 1) -> int:
    conn = _get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO produtos (nome, serie, topico_id) VALUES (?, ?, ?)",
            (nome, serie, topico_id),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_produtos_com_apostilas() -> list:
    conn = _get_conn()
    try:
        produtos = conn.execute(
            "SELECT p.*, tp.nome AS topico_nome FROM produtos p LEFT JOIN topicos tp ON p.topico_id = tp.id ORDER BY p.id DESC"
        ).fetchall()
        result = []
        for prod in produtos:
            pd = dict(prod)
            apostilas = conn.execute(
                """SELECT ap.id, ap.num_exercicios, ap.pdf_path, ap.criado_em,
                          COUNT(an.id) AS total_anuncios,
                          SUM(CASE WHEN an.status='publicado' THEN 1 ELSE 0 END) AS anuncios_publicados
                   FROM apostilas ap LEFT JOIN anuncios an ON an.apostila_id = ap.id
                   WHERE ap.produto_id = ? GROUP BY ap.id ORDER BY ap.num_exercicios""",
                (pd["id"],)
            ).fetchall()
            pd["apostilas"] = [dict(a) for a in apostilas]
            result.append(pd)
        return result
    finally:
        conn.close()


def listar_apostilas_por_produto(produto_id: int) -> list:
    conn = _get_conn()
    try:
        cur = conn.execute(
            "SELECT * FROM apostilas WHERE produto_id = ? ORDER BY num_exercicios",
            (produto_id,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def deletar_produto(produto_id: int) -> None:
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM produtos WHERE id = ?", (produto_id,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Smoke-test: executar diretamente para verificar criação do banco
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Criando banco em: {DB_PATH}")
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
