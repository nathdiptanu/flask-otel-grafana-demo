
# Flask OTEL Demo with Grafana, Loki, and Tempo

## Overview

This project demonstrates a mini workflow simulation in Flask with OpenTelemetry tracing and logs, integrated with Grafana for observability.

Features:
- Flask app with multiple APIs.
- Distributed tracing with Tempo.
- Centralized logging with Loki + Promtail.
- Swagger UI for testing APIs.
- Workflow with error and timeout handling.

## Project Structure

```
flask-otel-grafana-demo/
├─ docker-compose.yml
├─ grafana/
│  └─ provisioning/
│     ├─ datasources/
│     │  └─ datasources.yml
│     └─ dashboards/
│        └─ dashboards.yml
├─ loki/
│  └─ config.yml
├─ promtail/
│  └─ config.yml
├─ tempo/
│  └─ config.yml
└─ app/
   ├─ Dockerfile
   ├─ requirements.txt
   ├─ wsgi.py
   └─ app.py
```

## APIs

### Basic APIs
- `/health` → Health check
- `/hello` → Greeting
- `/work` → Simulated work spans
- `/error` → Intentional error for testing

### Workflow APIs

#### `/api1`
- Returns `order_id`
- Calls `/api2` internally
- Generates distributed trace

#### `/api2`
- Takes `order_id` → returns `transaction_id`
- Timeout >5s → HTTP 504
- Invalid/missing order_id → HTTP 400
- Calls `/api3` internally

#### `/api3`
- Takes `transaction_id` → finalizes transaction
- Timeout >10s → HTTP 504
- Invalid transaction_id → HTTP 400

## Setup

1. Clone repo:

```bash
git clone <repo-url>
cd flask-otel-grafana-demo
```

2. Start services:

```bash
docker-compose up --build
```

3. Swagger UI: [http://localhost:8000/apidocs/](http://localhost:8000/apidocs/)

## Testing Workflow

### Successful Workflow
POST `/api1` → returns:

```json
{
  "order_id": "aa80a26f",
  "api2_result": {
    "transaction_id": "59f1a98d",
    "api3_result": {
      "transaction_id": "59f1a98d",
      "status": "completed"
    }
  }
}
```

### Simulate Errors
1. Invalid `order_id` in `/api2`:

```json
{"order_id": "invalid123"} → HTTP 400, logs "Invalid order_id"
```

2. Invalid `transaction_id` in `/api3`:

```json
{"transaction_id": "invalid123"} → HTTP 400, logs "Invalid transaction_id"
```

3. Timeout in `/api2` or `/api3`:
- Temporarily set processing_time >5s (API2) or >10s (API3)
- Trigger `/api1` → HTTP 504, logs timeout message

## Viewing Traces and Logs
1. Grafana Explore → Tempo
   - Filter by service: `flask-otel-demo`
   - Click a trace → view spans
2. Click "Logs for this span"
   - Promtail must be running
   - Logs show `trace_id` and `span_id`
3. Loki manual query:

```
{job="flask-app"} | trace_id="PUT_YOUR_TRACE_ID_HERE"
```

## Quick Cheat-Sheet: Swagger JSON & Error Scenarios

| API | Method | Body (JSON) | Expected Result |
|-----|--------|-------------|----------------|
| `/api1` | POST | None | Returns `order_id`, triggers workflow, status: completed |
| `/api2` | POST | {"order_id": "<valid_order_id>"} | Returns `transaction_id`, triggers `/api3` |
| `/api2` | POST | {"order_id": "invalid123"} | HTTP 400, logs "Invalid order_id" |
| `/api2` | POST | processing_time >5 | HTTP 504, logs "API2 timeout exceeded 5s" |
| `/api3` | POST | {"transaction_id": "<valid_tx_id>"} | Returns status: completed |
| `/api3` | POST | {"transaction_id": "invalid123"} | HTTP 400, logs "Invalid transaction_id" |
| `/api3` | POST | processing_time >10 | HTTP 504, logs "API3 timeout exceeded 10s" |

Notes:
- Keep `processing_time` fixed for predictable testing
- Alerts in Grafana can be triggered on timeout spans or error logs
- All workflows now reliably work using internal Python function calls

## Quick curl commands

```bash
# Trigger successful workflow
curl -X POST "http://localhost:8000/api1" -H "Content-Type: application/json"

# Trigger API2 error
curl -X POST "http://localhost:8000/api2" -H "Content-Type: application/json" -d '{"order_id":"invalid123"}'

# Trigger API3 error
curl -X POST "http://localhost:8000/api3" -H "Content-Type: application/json" -d '{"transaction_id":"invalid123"}'
```
