# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Visão Geral

Sistema Python (CogniVita) para gerar e publicar apostilas pedagógicas automaticamente no
Mercado Livre (e experimentalmente na Shopee). Gera conteúdo com Groq (Llama 3.3 70B),
converte para PDF com ReportLab, cria capas com Pillow/IA, e publica via ML API.
Entrega PDF digital ao comprador via webhook de pedidos do ML.

## Comandos de Desenvolvimento

```bash
# Instalar dependências
pip install -r requirements.txt

# Rodar somente a API/dashboard (SQLite local automático)
ADMIN_TOKEN=meutoken uvicorn api:app --reload --port 8000

# Rodar API + scheduler juntos (como no Render)
ADMIN_TOKEN=meutoken python start.py

# Testar geradores isoladamente
python generator/content.py
python generator/pdf.py
python generator/images.py

# Simular scheduler sem publicar no ML
python scheduler.py --dry-run

# Rodar um batch de publicação único
python scheduler.py --once
```

Não há suite de testes automatizados.

## Stack

| Camada | Tecnologia |
|--------|-----------|
| API/Dashboard | FastAPI + Uvicorn |
| Banco (produção) | PostgreSQL no **Neon** via psycopg2 pool (`DATABASE_URL` no `.env`) |
| Banco (dev) | SQLite (`apostilas.db`) — usado só se `DATABASE_URL` estiver vazia |
| Frontend | HTML/CSS/JS vanilla em `app/index.html` |
| Conteúdo | Groq (Llama 3.3 70B) → fallback Llama 3.1 8B → fallback Qwen (DashScope via SDK openai); Claude (`claude-sonnet-4-6`) em funções específicas |
| PDF | ReportLab (+ Playwright para PDFs premium) |
| Capas | Pillow (5 templates) + IA (fal.ai, google-genai) |
| Storage de imagens/vídeos | Cloudflare R2 (`storage.py`, boto3) — opcional, fallback para path local |
| Agendamento | APScheduler (`scheduler.py`, subprocess do `start.py`) |
| ML API | requests + OAuth 2.0 (`ml/`) |
| Shopee | `shopee/` (OAuth + client) + automação Playwright experimental |
| YouTube | `youtube/` — upload de clipes para ML Decola (pausado: bloqueio na API do ML) |
| Execução | **Local** (`python start.py` na máquina do usuário) — NÃO usa mais Render; `render.yaml`/`Procfile` são legado |
| Preços/Validação | `pricing.py` (fonte única de preços) + `validacao.py` (validador central) |

## Arquitetura

```
generator/content.py  ← Groq/Qwen/Claude geram exercícios, títulos e descrições
generator/pdf.py      ← ReportLab monta PDF da apostila
generator/images.py   ← Pillow + IA geram capas (1200×1200, padrão ML)
generator/video.py    ← clipes Ken Burns (feature pausada)
       ↓
database.py           ← SQLite local / PostgreSQL produção (PH = %s/?), tabelas abaixo
storage.py            ← upload de capas/vídeos para Cloudflare R2
       ↓
ml/auth.py            ← OAuth 2.0 ML (access/refresh token, state anti-CSRF)
ml/client.py          ← ML API: criar anúncio, upload imagem, preço, pausar/fechar
ml/orders.py          ← pedidos pagos (sincronização de vendas)
ml/messages.py        ← mensagens pós-venda (envio de PDF ao comprador)
shopee/auth.py|client.py ← OAuth + publicação Shopee (experimental)
       ↓
scheduler.py          ← jobs: publica 30/dia (9h/13h/17h), kits automáticos (6h),
                        sincroniza vendas + gera PDFs vendidos (a cada hora)
       ↓
api.py (FastAPI)      ← dashboard, ~70 endpoints, webhook ML, OAuth callbacks
       ↓
app/index.html        ← frontend vanilla JS
```

`start.py` inicia `scheduler.py` como subprocess (herdando stdout/stderr) e depois faz
`os.execv` para uvicorn. `start.py`, `scheduler.py` e `api.py` carregam o `.env` —
TODOS os entry points resolvem o mesmo banco (Neon quando `DATABASE_URL` presente).

⚠️ O `.env` local aponta para o banco de PRODUÇÃO (Neon). Subir `uvicorn api:app`
nesta máquina conecta em produção. Para testar contra SQLite: `$env:DATABASE_URL=''`
antes de iniciar.

## Banco de Dados (database.py)

Tabelas principais: `topicos`, `apostilas`, `anuncios`, `vendas`, `ml_tokens`, `shopee_tokens`

- `topicos`: temas das apostilas (coordenação motora, memória, etc.)
- `apostilas`: conteúdo gerado (topico_id, num_exercicios, conteudo_json, pdf_path)
- `anuncios`: anúncios no ML (apostila_id, tipo digital/fisico, kit_id, ml_id, status, preco)
- `vendas`: pedidos do ML (ml_order_id, anuncio_id, comprador, valor, pdf_entregue)
- `ml_tokens` / `shopee_tokens`: OAuth (sempre id=1)

Status de anúncio: `rascunho` → `publicado` | `pausado` | `erro` | `deletado`

## ⛔ REGRA INEGOCIÁVEL: produto digital é PROIBIDO

**Não existe venda digital.** O Mercado Livre proíbe anúncio de produto digital
e isso já causou suspensão da conta. TODO produto é físico impresso:
- `criar_anuncio` sempre com tipo `"fisico"` (ou `"importado"` para espelhos do ML)
- Títulos NUNCA contêm "PDF" ou "Digital"
- O job `fix_cp_digital` (convertia caça-palavras → digital) foi DESATIVADO — não reativar
- O código de entrega de PDF por mensagem (webhook, tipo digital) é legado morto

## Fluxo pós-venda

1. ML envia notificação em `POST /api/ml/webhook` (orders/payments) +
   redundância: job horário do scheduler sincroniza pedidos pagos
2. Registra em `vendas`; venda NOVA dispara mensagem automática de boas-vindas
3. Gera o PDF interno da apostila vendida (para impressão na gráfica) — capa
   premium CSS; `capa_img` é encaixe dormente para arte de IA futura
4. Usuário envia PDFs + etiqueta ME à gráfica, que imprime, encaderna e posta

## Variáveis de Ambiente

Ver `.env.example`. Obrigatórias: `GROQ_API_KEY`, `ML_CLIENT_ID`, `ML_CLIENT_SECRET`, `ADMIN_TOKEN`.
Recomendada em produção: `ML_WEBHOOK_SECRET` (protege o webhook; re-registrar via
`POST /api/admin/ml/registrar-webhook` depois de definir).

## Notas Importantes

- Capas geradas em 1200×1200px (padrão ML), salvas em `output/images/` e subidas ao R2 se configurado
- PDFs salvos em `output/pdfs/`
- Variações de exercícios (fatias): 30, 60, 90, 120, 150, 200
- Preços físicos retail por fatia definidos em `_PRECOS_PRODUTO` (api.py e scheduler.py — manter em sincronia)
- Kits: combinações de 2–4 tópicos, preço = soma individual × 0.85, máx 20 kits/execução
- Rate limit do ML: `PAUSE_BETWEEN = 5s` entre publicações (batch e kits)
- Título de anúncio ML: máx 60 caracteres; categorias bloqueadas: MLB1726 (software)
- Scripts one-off ficam fora do git (`_*.py` no .gitignore) — mover para `scripts/` se virarem permanentes
- NUNCA commitar: `shopee_cookies.json`, `shopee_session/`, `.env` (já no .gitignore)
