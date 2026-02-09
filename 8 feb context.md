# Контекст сессий 8-9 февраля 2026

## 8 фев: /content команда
- Реализована команда /content для генерации content seeds
- Google Docs синхронизация встреч (Fireflies)
- Всё задеплоено и работает

## 9 фев: Замена Todoist на TickTick — ЗАВЕРШЕНО

### Что сделано
- Код полностью мигрирован (33 файла): config, processor, handlers, skills, agents, scripts
- MCP сервер: `@alexarevalo.ai/mcp-server-ticktick` установлен глобально на VPS
- OAuth credentials прописаны в `.env` и в `/home/dbrain/.claude.json`
- `/process` протестирован — задачи создаются в TickTick
- Дефолтная дата задач: завтра (было +3 дня)
- Удалена зависимость `todoist-api-python`, удалён skill `todoist-ai`

### TickTick credentials
- Client ID: Y0cXJJ3di47chFnMwe
- Client Secret: HM9Dh03k9kFPSA6JCfIqMG2nISg7Lb11
- Access Token: 5a53f6da-8b98-48fd-b2e7-a8be03919ae6
- Redirect URL: http://localhost:8000/callback
- Приложение зарегистрировано на developer.ticktick.com

### VPS детали
- Проект: `/opt/agent-second-brain`
- Пользователь бота: `dbrain` (не root!)
- Systemd сервис: `d-brain` (systemctl restart d-brain)
- Claude CLI конфиг: `/home/dbrain/.claude.json` — MCP прописан тут
- MCP работает через прямой путь `/usr/local/bin/mcp-server-ticktick` (не npx)
- --mcp-config файл НЕ работал, решение — `claude mcp add` + правка .claude.json напрямую через python скрипт
- SSH: `ssh root@vmi3063515`

### Нерешённые мелочи
- Claude иногда пишет "Todoist MCP недоступен" в отчёте — галлюцинация, TickTick работает
- Process Goals не создаются автоматически (TickTick MCP не поддерживает labels/recurring полностью)
- docs/README.md и docs/*.md всё ещё содержат Todoist-документацию

### Что дальше
- Тестировать /do, /weekly с TickTick
- При необходимости доработать промпты чтобы убрать упоминания Todoist из ответов Claude
- Обновить README/docs если нужно
