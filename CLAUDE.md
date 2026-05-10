# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Visão Geral

Sistema Python para gerar e publicar apostilas pedagógicas automaticamente no Mercado Livre.
Gera conteúdo com Claude API, converte para PDF com ReportLab, cria capas com Pillow,
e publica via Mercado Livre API. Meta: 30 anúncios/dia, 1000+ em um mês.

## Comandos de Desenvolvimento

```bash
# Instalar dependências
pip install -r requirements.txt

# Rodar somente a API/dashboard
ADMIN_TOKEN=meutoken uvicorn api:app --reload --port 8000

# Rodar API + scheduler juntos
ADMIN_TOKEN=meutoken python start.py

# Testar geradores isoladamente
python generator/content.py
python generator/pdf.py
python generator/images.py

# Simular scheduler sem publicar no ML
python scheduler.py --dry-run
```

## Stack

| Camada | Tecnologia |
|--------|-----------|
| API/Dashboard | FastAPI + Uvicorn |
| Banco | SQLite local (`apostilas.db`) |
| Frontend | HTML/CSS/JS vanilla em `app/index.html` |
| Conteúdo | Claude API (anthropic SDK) |
| PDF | ReportLab |
| Capas | Pillow |
| Agendamento | APScheduler |
| ML API | requests + OAuth 2.0 |

## Arquitetura

```
generator/content.py  ← Claude API gera exercícios por tópico/variação
generator/pdf.py      ← ReportLab monta PDF da apostila
generator/images.py   ← Pillow gera capas (5 templates de cores)
       ↓
database.py           ← SQLite: topicos, apostilas, anuncios, ml_tokens
       ↓
ml/auth.py            ← OAuth 2.0 do ML (access/refresh token)
ml/client.py          ← ML API: criar anúncio, upload imagem, pausar
       ↓
scheduler.py          ← Publica 30 anúncios/dia (usa APScheduler)
       ↓
api.py (FastAPI)      ← Dashboard: stats, fila, controles, OAuth callback
       ↓
app/index.html        ← Frontend vanilla JS
```

`start.py` inicia `scheduler.py` como subprocess e depois `os.execv` para uvicorn.

## Banco de Dados (database.py)

Tabelas: `topicos`, `apostilas`, `anuncios`, `ml_tokens`

- `topicos`: temas das apostilas (coordenação motora, memória, etc.)
- `apostilas`: conteúdo gerado (topico_id, num_exercicios, conteudo_json, pdf_path)
- `anuncios`: anúncios no ML (apostila_id, tipo digital/físico, template_id, ml_id, status, preco)
- `ml_tokens`: access/refresh token do ML (sempre id=1)

Status de anúncio: `rascunho` → `publicado` | `pausado` | `erro`

## Variáveis de Ambiente

Ver `.env.example`. Obrigatórias: `ANTHROPIC_API_KEY`, `ML_CLIENT_ID`, `ML_CLIENT_SECRET`, `ADMIN_TOKEN`.

## Notas Importantes

- Capas geradas em 1200×1200px (padrão ML), salvas em `output/images/`
- PDFs salvos em `output/pdfs/`
- 5 templates de capa: azul, verde, laranja, roxo, vermelho
- Variações de exercícios: 60, 90, 120, 150
- Tópicos iniciais: Coordenação Motora, Memória, Coordenação Motora Fina, Atenção e Concentração, Percepção Visual, Sequência Lógica
- Rate limit do ML: pausa 5s entre publicações no scheduler
