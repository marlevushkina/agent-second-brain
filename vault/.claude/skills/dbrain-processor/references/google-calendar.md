# Google Calendar Integration

## Available MCP Tools

### Reading Events
- `list-calendars` — list all available calendars
- `list-events` — list events with date range filtering
- `get-event` — get event details by ID
- `search-events` — search events by text query
- `get-freebusy` — check availability across calendars
- `get-current-time` — get current date/time in calendar timezone

### Writing Events
- `create-event` — create new calendar event
- `update-event` — update existing event
- `delete-event` — delete event

### Other
- `respond-to-event` — respond to invitations (Accept/Decline/Maybe)
- `list-colors` — list available event color options

---

## Event Creation

```
mcp__google-calendar__create-event:
  summary: "Meeting title"
  description: "Meeting description"
  start: "2026-02-20T14:00:00+03:00"
  end: "2026-02-20T15:00:00+03:00"
  attendees: ["email@example.com"]
  location: "Zoom / Office"
```

### Time Rules
- ALWAYS use ISO 8601 format with timezone: `YYYY-MM-DDTHH:MM:SS+03:00`
- Default timezone: Moscow (UTC+3)
- Default meeting duration: 1 hour (if not specified)
- For all-day events use date format: `YYYY-MM-DD`

### Event Title Style
Same as tasks — direct, clear, specific:

- "Созвон с командой по проекту X"
- "Встреча с клиентом: обсуждение стратегии"
- "1-on-1 с [имя]"
- "Дедлайн: сдача отчёта"

---

## Pre-Creation Checklist

### 1. Check Calendar (REQUIRED)
```
list-events → check existing events for the same time slot
get-freebusy → verify no conflicts
```

### 2. Check Duplicates (REQUIRED)
Search for similar events on the same day before creating.

---

## Routing: Calendar vs Tasks

| Context | Target |
|---------|--------|
| Meeting with specific time | Google Calendar |
| Call/zoom with attendees | Google Calendar |
| Deadline reminder | Google Calendar + TickTick task |
| Action item (no specific time) | TickTick or Planfix |
| All-day event/reminder | Google Calendar |

### Routing Keywords

**→ Google Calendar:** встреча, созвон, звонок, zoom, митинг, совещание, обед, event, calendar, календарь, напоминание в календарь

**→ TickTick/Planfix:** задача, сделать, написать, отправить, подготовить

---

## Listing Events

```
mcp__google-calendar__list-events:
  calendarId: "primary"
  timeMin: "2026-02-18T00:00:00+03:00"
  timeMax: "2026-02-25T00:00:00+03:00"
```

- Use `primary` for the main calendar
- Always set timeMin/timeMax for bounded queries
- For "today's events": timeMin = today 00:00, timeMax = tomorrow 00:00
- For "this week": timeMin = monday, timeMax = next monday

---

## Error Handling

CRITICAL: Never suggest "add manually".

If `create-event` fails:
1. Include EXACT error message in report
2. Continue with next entry
3. Show error in HTML report

WRONG output:
  "Не удалось создать событие (MCP недоступен). Добавь вручную"

CORRECT output:
  "Ошибка создания события: [exact error from MCP tool]"
