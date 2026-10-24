# Logs no terminal

O backend escreve uma linha JSON por evento em stdout, usando somente `logging`
da biblioteca padrão. Não grava arquivos e não depende de serviços adicionais.

```sh
docker compose up --build -d
docker compose logs -f --no-log-prefix backend
```

Para executar localmente:

```sh
cd backend
.venv/bin/python -m app.server
```

`LOG_LEVEL` aceita DEBUG, INFO (padrão), WARNING, ERROR e CRITICAL. No Compose,
essa variável pode ser definida no `.env`. A proteção dos dados vale em todos os níveis.

Cada evento contém horário UTC, nível, serviço e evento. Requisições incluem UUID,
rota conhecida, método e status; etapas incluem duração em milissegundos. O resumo
contém somente contagens de linhas, aprovados, barrados e duplicatas. O cabeçalho
`X-Request-ID` permite correlacionar a resposta aos eventos do terminal.

Não são registrados conteúdo do CSV, documentos, CNPJs, valores financeiros,
nomes de arquivos, configuração, corpos, cabeçalhos, parâmetros de consulta ou
mensagens de exceção. Rotas desconhecidas aparecem como `unmatched`. Mensagens
livres de bibliotecas são substituídas por `library_log`. O access log padrão do
Uvicorn fica desativado para evitar duplicação e URLs completas.

O evento final ocorre depois do envio da resposta e da limpeza dos temporários.
Verificações de saúde bem-sucedidas ficam em DEBUG. Os corpos de resposta da API
continuam iguais; apenas o cabeçalho de correlação foi acrescentado.
