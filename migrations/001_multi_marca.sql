-- migrations/001_multi_marca.sql
-- Idempotente: usa IF NOT EXISTS em tudo

CREATE TABLE IF NOT EXISTS mb_marcas (
    id            SERIAL PRIMARY KEY,
    nome          TEXT NOT NULL,
    slug          TEXT UNIQUE NOT NULL,
    cor_principal TEXT DEFAULT '#1B6B4A',
    logo_url      TEXT,
    ativo         BOOLEAN DEFAULT true,
    criado_em     TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mb_contas_plataforma (
    id          SERIAL PRIMARY KEY,
    marca_id    INTEGER NOT NULL REFERENCES mb_marcas(id),
    plataforma  TEXT NOT NULL CHECK (plataforma IN ('ml', 'shopee', 'amazon')),
    credenciais JSONB NOT NULL DEFAULT '{}',
    ativo       BOOLEAN DEFAULT true,
    criado_em   TIMESTAMP DEFAULT NOW(),
    UNIQUE (marca_id, plataforma)
);

CREATE TABLE IF NOT EXISTS mb_produtos (
    id              SERIAL PRIMARY KEY,
    marca_id        INTEGER NOT NULL REFERENCES mb_marcas(id),
    nome            TEXT NOT NULL,
    descricao       TEXT,
    tipo            TEXT NOT NULL DEFAULT 'proprio' CHECK (tipo IN ('proprio', 'revenda')),
    preco_base      NUMERIC(10,2),
    custo_producao  NUMERIC(10,2),
    imagem_url      TEXT,
    conteudo_path   TEXT,
    ativo           BOOLEAN DEFAULT true,
    criado_em       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mb_listagens (
    id                  SERIAL PRIMARY KEY,
    produto_id          INTEGER NOT NULL REFERENCES mb_produtos(id),
    conta_id            INTEGER NOT NULL REFERENCES mb_contas_plataforma(id),
    titulo              TEXT NOT NULL,
    preco               NUMERIC(10,2),
    status              TEXT DEFAULT 'rascunho'
                            CHECK (status IN ('rascunho','publicado','pausado','arquivado','deletado')),
    plataforma_item_id  TEXT,
    imagem_url          TEXT,
    erro_msg            TEXT,
    criado_em           TIMESTAMP DEFAULT NOW(),
    atualizado_em       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mb_pedidos (
    id                    SERIAL PRIMARY KEY,
    listagem_id           INTEGER NOT NULL REFERENCES mb_listagens(id),
    plataforma_pedido_id  TEXT NOT NULL,
    status                TEXT DEFAULT 'novo'
                              CHECK (status IN ('novo','pdf_gerado','enviado_grafica','entregue','cancelado')),
    valor                 NUMERIC(10,2),
    nome_cliente          TEXT,
    endereco_entrega      JSONB DEFAULT '{}',
    pdf_gerado            BOOLEAN DEFAULT false,
    enviado_grafica       BOOLEAN DEFAULT false,
    criado_em             TIMESTAMP DEFAULT NOW(),
    atualizado_em         TIMESTAMP DEFAULT NOW()
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_mb_produtos_marca ON mb_produtos(marca_id);
CREATE INDEX IF NOT EXISTS idx_mb_listagens_produto ON mb_listagens(produto_id);
CREATE INDEX IF NOT EXISTS idx_mb_listagens_conta ON mb_listagens(conta_id);
CREATE INDEX IF NOT EXISTS idx_mb_listagens_status ON mb_listagens(status);
CREATE INDEX IF NOT EXISTS idx_mb_pedidos_listagem ON mb_pedidos(listagem_id);
CREATE INDEX IF NOT EXISTS idx_mb_pedidos_status ON mb_pedidos(status);
