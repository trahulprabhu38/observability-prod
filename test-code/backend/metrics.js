"use strict";

const client = require("prom-client");

// ─── Registry ────────────────────────────────────────────────────────────────
const register = new client.Registry();
register.setDefaultLabels({ app: "test-backend" });

// Collect default Node.js process metrics (CPU, memory, event-loop lag, GC, etc.)
client.collectDefaultMetrics({ register });

// ─── HTTP Metrics ─────────────────────────────────────────────────────────────
const httpRequestDurationMs = new client.Histogram({
  name: "http_request_duration_ms",
  help: "Duration of HTTP requests in milliseconds",
  labelNames: ["method", "route", "status_code"],
  buckets: [5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
  registers: [register],
});

const httpRequestsTotal = new client.Counter({
  name: "http_requests_total",
  help: "Total number of HTTP requests",
  labelNames: ["method", "route", "status_code"],
  registers: [register],
});

const httpRequestsInFlight = new client.Gauge({
  name: "http_requests_in_flight",
  help: "Number of HTTP requests currently being processed",
  registers: [register],
});

// ─── Database Metrics ─────────────────────────────────────────────────────────
const dbOperationDurationMs = new client.Histogram({
  name: "db_operation_duration_ms",
  help: "Duration of MongoDB operations in milliseconds",
  labelNames: ["operation", "collection", "status"],
  buckets: [1, 5, 10, 25, 50, 100, 250, 500, 1000],
  registers: [register],
});

const dbOperationsTotal = new client.Counter({
  name: "db_operations_total",
  help: "Total number of database operations",
  labelNames: ["operation", "collection", "status"],
  registers: [register],
});

const dbConnectionPoolActive = new client.Gauge({
  name: "db_connection_pool_active",
  help: "Active MongoDB connection pool connections",
  registers: [register],
});

// ─── Business Metrics ─────────────────────────────────────────────────────────
const ordersCreatedTotal = new client.Counter({
  name: "orders_created_total",
  help: "Total number of orders created",
  labelNames: ["currency", "payment_method"],
  registers: [register],
});

const paymentsTotal = new client.Counter({
  name: "payments_total",
  help: "Total number of payments processed",
  labelNames: ["status", "gateway"],
  registers: [register],
});

const revenueTotal = new client.Counter({
  name: "revenue_total_usd",
  help: "Total revenue processed in USD (approximate)",
  labelNames: ["currency"],
  registers: [register],
});

// ─── Security / Error Metrics ─────────────────────────────────────────────────
const errorsTotal = new client.Counter({
  name: "errors_total",
  help: "Total number of application errors",
  labelNames: ["type", "severity", "service"],
  registers: [register],
});

const authFailuresTotal = new client.Counter({
  name: "auth_failures_total",
  help: "Total number of authentication failures",
  labelNames: ["reason"],
  registers: [register],
});

const rateLimitHitsTotal = new client.Counter({
  name: "rate_limit_hits_total",
  help: "Total number of rate-limit triggers",
  labelNames: ["endpoint"],
  registers: [register],
});

// ─── Worker / Queue Metrics ───────────────────────────────────────────────────
const jobsCompletedTotal = new client.Counter({
  name: "jobs_completed_total",
  help: "Total number of background jobs completed",
  labelNames: ["job_type", "queue", "status"],
  registers: [register],
});

const queueDepth = new client.Gauge({
  name: "queue_depth",
  help: "Current depth of a job queue",
  labelNames: ["queue"],
  registers: [register],
});

// ─── Pushgateway ──────────────────────────────────────────────────────────────
const PUSHGATEWAY_URL = process.env.PUSHGATEWAY_URL || "http://pushgateway:9091";
const gateway = new client.Pushgateway(PUSHGATEWAY_URL, [], register);

/**
 * Push metrics to Pushgateway.
 * jobName identifies the metric group in the gateway UI.
 */
async function pushMetrics(jobName = "test-backend") {
  try {
    await gateway.pushAdd({ jobName });
  } catch (err) {
    // Non-fatal — Prometheus scrape still works via /metrics even if push fails
    console.error("[Pushgateway] push failed:", err.message);
  }
}

module.exports = {
  register,
  // HTTP
  httpRequestDurationMs,
  httpRequestsTotal,
  httpRequestsInFlight,
  // Database
  dbOperationDurationMs,
  dbOperationsTotal,
  dbConnectionPoolActive,
  // Business
  ordersCreatedTotal,
  paymentsTotal,
  revenueTotal,
  // Security / Errors
  errorsTotal,
  authFailuresTotal,
  rateLimitHitsTotal,
  // Workers
  jobsCompletedTotal,
  queueDepth,
  // Pushgateway helper
  pushMetrics,
};
