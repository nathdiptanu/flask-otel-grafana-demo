import logging
import os
import time
import uuid
from flask import Flask, jsonify, request, abort
from flasgger import Swagger

# --- OpenTelemetry setup ---
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor

SERVICE_NAME = "flask-otel-demo"

# ------------------------------
# Logging with trace/span IDs
# ------------------------------
def _install_trace_context_in_logging():
    old_factory = logging.getLogRecordFactory()
    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx and ctx.trace_id != 0 and ctx.span_id != 0:
            record.trace_id = f"{ctx.trace_id:032x}"
            record.span_id = f"{ctx.span_id:016x}"
        else:
            record.trace_id = "0" * 32
            record.span_id = "0" * 16
        return record

    logging.setLogRecordFactory(record_factory)
    fmt = "%(asctime)s %(levelname)s trace_id=%(trace_id)s span_id=%(span_id)s %(name)s: %(message)s"
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

# ------------------------------
# OpenTelemetry tracing
# ------------------------------
def _install_otel_tracing():
    resource = Resource.create({"service.name": SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://localhost:4318/v1/traces")
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

# ------------------------------
# In-memory storage
# ------------------------------
ORDERS = {}
TRANSACTIONS = {}

# ------------------------------
# Internal workflow functions
# ------------------------------
def api3_internal(tx_id, log):
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("api3-finalize-transaction"):
        if tx_id not in TRANSACTIONS:
            log.error(f"Invalid transaction_id={tx_id}")
            abort(400, "Invalid transaction_id")
        processing_time = 3  # fixed for reliability
        time.sleep(processing_time)
        TRANSACTIONS[tx_id]["status"] = "completed"
        log.info(f"Transaction {tx_id} finalized")
        return {"transaction_id": tx_id, "status": "completed"}

def api2_internal(order_id, log):
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("api2-process-order"):
        if order_id not in ORDERS:
            log.error(f"Invalid order_id={order_id}")
            abort(400, "Invalid order_id")
        processing_time = 3  # fixed for reliability
        time.sleep(processing_time)
        tx_id = str(uuid.uuid4())[:8]
        TRANSACTIONS[tx_id] = {"order_id": order_id, "status": "processed"}
        log.info(f"Transaction created: {tx_id} for order {order_id}")
        api3_result = api3_internal(tx_id, log)
        return {"transaction_id": tx_id, "api3_result": api3_result}

# ------------------------------
# Flask app factory
# ------------------------------
def create_app():
    _install_otel_tracing()
    _install_trace_context_in_logging()

    app = Flask(__name__)
    app.config["SWAGGER"] = {"title": "Flask OTEL Demo", "uiversion": 3}
    Swagger(app)

    FlaskInstrumentor().instrument_app(app)
    log = logging.getLogger("app")

    # ------------------------------
    # Basic APIs
    # ------------------------------
    @app.get("/health")
    def health():
        """Health check
        ---
        tags: [system]
        responses:
          200:
            description: OK
            content:
              application/json:
                example: {"status": "ok"}
        """
        log.info("health pinged")
        return jsonify({"status": "ok"})

    @app.get("/hello")
    def hello():
        """Say hello
        ---
        tags: [demo]
        parameters:
          - in: query
            name: name
            schema:
              type: string
            required: false
            description: Name to greet
        responses:
          200:
            description: Greeting
            content:
              application/json:
                example: {"message": "Hello, world!"}
        """
        name = request.args.get("name", "world")
        log.info("saying hello")
        return jsonify({"message": f"Hello, {name}!"})

    @app.get("/work")
    def work():
        """Simulate some work and nested spans
        ---
        tags: [demo]
        responses:
          200:
            description: Work result
        """
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("make-coffee"):
            time.sleep(0.15)
            with tracer.start_as_current_span("boil-water"):
                time.sleep(0.1)
        log.info("work done")
        return jsonify({"ok": True, "step": "coffee"})

    @app.get("/error")
    def error():
        """Intentional error to see exception traces
        ---
        tags: [demo]
        responses:
          500:
            description: Boom
        """
        log.warning("going to raise an error")
        raise RuntimeError("Boom!")

    # ------------------------------
    # Workflow APIs
    # ------------------------------
    @app.post("/api1")
    def api1():
        """Start order workflow (api1 → api2 → api3)
        ---
        tags: [workflow]
        responses:
          200:
            description: Order created and processed
        """
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("api1-create-order"):
            order_id = str(uuid.uuid4())[:8]
            ORDERS[order_id] = {"status": "created"}
            log.info(f"Order created: {order_id}")
            api2_result = api2_internal(order_id, log)
            return jsonify({"order_id": order_id, "api2_result": api2_result})

    @app.post("/api2")
    def api2():
        """Process order (internal, used by api1)
        ---
        tags: [workflow]
        consumes: ["application/json"]
        parameters:
          - in: body
            name: body
            required: true
            schema:
              type: object
              required: [order_id]
              properties:
                order_id: {type: string}
        responses:
          200:
            description: Transaction created and finalized
        """
        data = request.get_json() or {}
        order_id = data.get("order_id")
        result = api2_internal(order_id, log)
        return jsonify(result)

    @app.post("/api3")
    def api3():
        """Finalize transaction (internal, used by api2)
        ---
        tags: [workflow]
        consumes: ["application/json"]
        parameters:
          - in: body
            name: body
            required: true
            schema:
              type: object
              required: [transaction_id]
              properties:
                transaction_id: {type: string}
        responses:
          200:
            description: Transaction finalized
        """
        data = request.get_json() or {}
        tx_id = data.get("transaction_id")
        result = api3_internal(tx_id, log)
        return jsonify(result)

    return app

# ------------------------------
# Run server
# ------------------------------
if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=8000)
