const express = require("express");
const mongoose = require("mongoose");
const morgan = require("morgan");
const cors = require("cors");
const logger = require("./logger");
const os = require("os");
const metrics = require("./metrics");

const app = express();
const PORT = 5000;

app.use(cors());
app.use(express.json());

// ─── Prometheus metrics endpoint ─────────────────────────────────────────────
app.get("/metrics", async (req, res) => {
  res.set("Content-Type", metrics.register.contentType);
  res.end(await metrics.register.metrics());
});

// ─── HTTP metrics middleware ──────────────────────────────────────────────────
app.use((req, res, next) => {
  metrics.httpRequestsInFlight.inc();
  const end = metrics.httpRequestDurationMs.startTimer();
  res.on("finish", () => {
    const route = req.route ? req.route.path : req.path;
    const labels = { method: req.method, route, status_code: res.statusCode };
    end(labels);
    metrics.httpRequestsTotal.inc(labels);
    metrics.httpRequestsInFlight.dec();
  });
  next();
});

// ─── Detailed HTTP request logging ──────────────────────────────────────────
app.use((req, res, next) => {
  const start = Date.now();
  const reqId = `req_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  req.reqId = reqId;

  logger.info("Incoming request", {
    type: "http-request",
    reqId,
    method: req.method,
    path: req.path,
    query: req.query,
    ip: req.ip,
    userAgent: req.get("user-agent"),
    contentLength: req.get("content-length") || 0,
    referer: req.get("referer") || "direct",
  });

  res.on("finish", () => {
    const duration = Date.now() - start;
    const logFn = res.statusCode >= 500 ? "error" : res.statusCode >= 400 ? "warn" : "info";
    logger[logFn]("Request completed", {
      type: "http-response",
      reqId,
      method: req.method,
      path: req.path,
      statusCode: res.statusCode,
      duration,
      contentLength: res.get("content-length") || 0,
    });

    if (duration > 1000) {
      logger.warn("Slow request detected", {
        type: "performance",
        reqId,
        method: req.method,
        path: req.path,
        duration,
        threshold: 1000,
      });
    }
  });

  next();
});

app.use(
  morgan("combined", {
    stream: { write: (msg) => logger.info(msg.trim(), { type: "http-access-log" }) },
  })
);

// ─── MongoDB connection with detailed logging ───────────────────────────────
const MONGO_URI = process.env.MONGO_URI || "mongodb://mongo:27017/elktest";

logger.info("Attempting MongoDB connection", { type: "database", uri: MONGO_URI.replace(/\/\/.*@/, "//***@") });

mongoose.connection.on("connecting", () => logger.info("MongoDB connecting...", { type: "database", event: "connecting" }));
mongoose.connection.on("connected", () => logger.info("MongoDB connected successfully", { type: "database", event: "connected" }));
mongoose.connection.on("disconnected", () => logger.warn("MongoDB disconnected", { type: "database", event: "disconnected" }));
mongoose.connection.on("error", (err) => logger.error("MongoDB connection error", { type: "database", event: "error", error: err.message }));

mongoose.connect(MONGO_URI).catch((err) =>
  logger.error("MongoDB initial connection failed", { type: "database", error: err.message })
);

// ─── Schemas ────────────────────────────────────────────────────────────────
const LogEntry = mongoose.model(
  "LogEntry",
  new mongoose.Schema({
    level: String,
    message: String,
    source: String,
    timestamp: { type: Date, default: Date.now },
  })
);

const Order = mongoose.model(
  "Order",
  new mongoose.Schema({
    orderId: String,
    userId: String,
    amount: Number,
    status: String,
    items: Number,
    createdAt: { type: Date, default: Date.now },
  })
);

// ─── API Routes ─────────────────────────────────────────────────────────────

app.get("/api/health", (req, res) => {
  const mem = process.memoryUsage();
  const health = {
    status: "ok",
    uptime: process.uptime(),
    timestamp: new Date().toISOString(),
    memory: { heapUsed: mem.heapUsed, heapTotal: mem.heapTotal, rss: mem.rss },
    pid: process.pid,
    nodeVersion: process.version,
  };
  logger.info("Health check performed", {
    type: "health",
    endpoint: "/api/health",
    uptime: health.uptime,
    heapUsedMB: Math.round(mem.heapUsed / 1024 / 1024),
    rssMB: Math.round(mem.rss / 1024 / 1024),
  });
  res.json(health);
});

app.get("/api/logs", async (req, res) => {
  const queryStart = Date.now();
  try {
    const logs = await LogEntry.find().sort({ timestamp: -1 }).limit(100);
    logger.info("Log entries fetched", {
      type: "database-query",
      collection: "logentries",
      operation: "find",
      count: logs.length,
      queryDuration: Date.now() - queryStart,
    });
    res.json(logs);
  } catch (err) {
    logger.error("Failed to fetch logs", { type: "database-query", operation: "find", error: err.message, queryDuration: Date.now() - queryStart });
    res.status(500).json({ error: "Internal server error" });
  }
});

app.post("/api/logs", async (req, res) => {
  const queryStart = Date.now();
  try {
    const entry = await LogEntry.create(req.body);
    logger.info("Log entry created", {
      type: "database-query",
      collection: "logentries",
      operation: "insert",
      level: req.body.level,
      queryDuration: Date.now() - queryStart,
    });
    res.status(201).json(entry);
  } catch (err) {
    logger.error("Failed to create log entry", { type: "database-query", operation: "insert", error: err.message });
    res.status(500).json({ error: "Internal server error" });
  }
});

// ─── Simulation Endpoints ───────────────────────────────────────────────────

app.get("/api/simulate/error", (req, res) => {
  const err = new Error("Simulated critical application error");
  logger.error("CRITICAL: Application error occurred", {
    type: "application-error",
    severity: "critical",
    errorCode: "ERR_SIM_500",
    message: err.message,
    stack: err.stack,
    pid: process.pid,
    memory: process.memoryUsage(),
  });
  res.status(500).json({ error: "Simulated error" });
});

app.get("/api/simulate/warning", (req, res) => {
  const mem = process.memoryUsage();
  logger.warn("High memory usage detected", {
    type: "performance",
    category: "memory",
    heapUsedMB: Math.round(mem.heapUsed / 1024 / 1024),
    heapTotalMB: Math.round(mem.heapTotal / 1024 / 1024),
    rssMB: Math.round(mem.rss / 1024 / 1024),
    externalMB: Math.round(mem.external / 1024 / 1024),
    threshold: "80%",
  });
  res.json({ warning: "simulated warning logged" });
});

app.get("/api/simulate/auth-fail", (req, res) => {
  const reason = ["invalid_password", "account_locked", "token_expired", "invalid_token"][Math.floor(Math.random() * 4)];
  logger.warn("Authentication failure", {
    type: "security",
    event: "authentication_failed",
    severity: "high",
    ip: req.ip,
    userAgent: req.get("user-agent"),
    attemptedUser: `user_${Math.floor(Math.random() * 100)}`,
    reason,
    geoip: { country: "US", city: ["New York", "Los Angeles", "Chicago", "Houston"][Math.floor(Math.random() * 4)] },
  });
  metrics.authFailuresTotal.inc({ reason });
  res.status(401).json({ error: "Unauthorized" });
});

app.get("/api/simulate/slow", async (req, res) => {
  const start = Date.now();
  const delay = 1000 + Math.random() * 4000;
  logger.info("Starting slow operation", { type: "performance", category: "latency", expectedDelay: Math.round(delay) });
  await new Promise((r) => setTimeout(r, delay));
  const duration = Date.now() - start;
  logger.warn("Slow operation completed", {
    type: "performance",
    category: "latency",
    duration,
    endpoint: "/api/simulate/slow",
    exceededThreshold: duration > 3000,
  });
  res.json({ message: "slow response", duration });
});

// 404 handler
app.use((req, res) => {
  logger.warn("Route not found", {
    type: "http-error",
    statusCode: 404,
    method: req.method,
    path: req.path,
    ip: req.ip,
    userAgent: req.get("user-agent"),
  });
  res.status(404).json({ error: "Not found" });
});

// ─── Continuous Log Generator ───────────────────────────────────────────────
function generateContinuousLogs() {
  const users = Array.from({ length: 50 }, (_, i) => `user_${i + 1}`);
  const pages = ["/dashboard", "/profile", "/settings", "/products", "/orders", "/checkout", "/admin", "/reports", "/analytics", "/support"];
  const methods = ["GET", "POST", "PUT", "DELETE", "PATCH"];
  const statusCodes = [200, 201, 204, 301, 400, 401, 403, 404, 500, 502, 503];
  const dbOps = ["find", "findOne", "insert", "update", "delete", "aggregate"];
  const collections = ["users", "orders", "products", "sessions", "payments", "notifications"];
  const services = ["auth-service", "payment-service", "order-service", "notification-service", "user-service", "inventory-service"];
  const regions = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"];
  const errorMessages = [
    "Connection refused", "Timeout exceeded", "Out of memory", "Disk full",
    "DNS resolution failed", "TLS handshake error", "Connection reset by peer",
    "Too many open files", "Permission denied", "Resource temporarily unavailable",
  ];

  const scenarios = [
    // ── User Activity Logs ──
    () => {
      const userId = users[Math.floor(Math.random() * users.length)];
      logger.info("User login successful", {
        type: "user-activity", event: "login", userId,
        ip: `10.0.${Math.floor(Math.random() * 255)}.${Math.floor(Math.random() * 255)}`,
        sessionId: `sess_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        loginMethod: ["password", "oauth_google", "oauth_github", "sso"][Math.floor(Math.random() * 4)],
      });
    },
    () => {
      logger.info("User logout", {
        type: "user-activity", event: "logout",
        userId: users[Math.floor(Math.random() * users.length)],
        sessionDuration: Math.floor(Math.random() * 3600),
      });
    },
    () => {
      logger.info("Page view", {
        type: "user-activity", event: "page_view",
        userId: users[Math.floor(Math.random() * users.length)],
        page: pages[Math.floor(Math.random() * pages.length)],
        referrer: ["google", "direct", "internal", "email_campaign"][Math.floor(Math.random() * 4)],
        loadTime: Math.floor(Math.random() * 2000),
        browser: ["Chrome", "Firefox", "Safari", "Edge"][Math.floor(Math.random() * 4)],
      });
    },
    () => {
      logger.info("User action", {
        type: "user-activity", event: "click",
        userId: users[Math.floor(Math.random() * users.length)],
        element: ["button_buy", "link_product", "nav_menu", "search_bar", "filter_category"][Math.floor(Math.random() * 5)],
        page: pages[Math.floor(Math.random() * pages.length)],
      });
    },

    // ── API / HTTP Logs ──
    () => {
      const method = methods[Math.floor(Math.random() * methods.length)];
      const status = statusCodes[Math.floor(Math.random() * statusCodes.length)];
      const logFn = status >= 500 ? "error" : status >= 400 ? "warn" : "info";
      logger[logFn]("API request", {
        type: "api-request",
        method,
        endpoint: `/api/${["users", "orders", "products", "payments", "notifications"][Math.floor(Math.random() * 5)]}`,
        statusCode: status,
        responseTime: Math.floor(Math.random() * 800),
        requestSize: Math.floor(Math.random() * 5000),
        responseSize: Math.floor(Math.random() * 50000),
        service: services[Math.floor(Math.random() * services.length)],
      });
    },

    // ── Database Logs ──
    () => {
      const op = dbOps[Math.floor(Math.random() * dbOps.length)];
      const duration = Math.floor(Math.random() * 500);
      const logFn = duration > 300 ? "warn" : "info";
      logger[logFn]("Database operation", {
        type: "database",
        operation: op,
        collection: collections[Math.floor(Math.random() * collections.length)],
        duration,
        documentsAffected: Math.floor(Math.random() * 100),
        slow: duration > 300,
        index: duration < 50 ? "used" : "scan",
      });
    },
    () => {
      logger.info("Database connection pool status", {
        type: "database",
        event: "pool_status",
        activeConnections: Math.floor(Math.random() * 20),
        idleConnections: Math.floor(Math.random() * 10),
        waitingRequests: Math.floor(Math.random() * 5),
        maxPoolSize: 20,
      });
    },

    // ── Security Logs ──
    () => {
      const endpoint = `/api/${["login", "register", "reset-password", "verify"][Math.floor(Math.random() * 4)]}`;
      logger.warn("Rate limit triggered", {
        type: "security",
        event: "rate_limit",
        ip: `192.168.${Math.floor(Math.random() * 255)}.${Math.floor(Math.random() * 255)}`,
        endpoint,
        requestCount: 80 + Math.floor(Math.random() * 50),
        limit: 100,
        windowSeconds: 60,
      });
      metrics.rateLimitHitsTotal.inc({ endpoint });
    },
    () => {
      logger.warn("Suspicious activity detected", {
        type: "security",
        event: "suspicious_activity",
        severity: ["low", "medium", "high", "critical"][Math.floor(Math.random() * 4)],
        ip: `10.${Math.floor(Math.random() * 255)}.${Math.floor(Math.random() * 255)}.${Math.floor(Math.random() * 255)}`,
        pattern: ["brute_force", "sql_injection_attempt", "xss_attempt", "path_traversal", "port_scan"][Math.floor(Math.random() * 5)],
        blocked: Math.random() > 0.3,
      });
    },
    () => {
      logger.info("JWT token issued", {
        type: "security",
        event: "token_issued",
        userId: users[Math.floor(Math.random() * users.length)],
        tokenType: ["access", "refresh"][Math.floor(Math.random() * 2)],
        expiresIn: [900, 3600, 86400][Math.floor(Math.random() * 3)],
      });
    },

    // ── Performance / Infrastructure Logs ──
    () => {
      const mem = process.memoryUsage();
      logger.info("System metrics snapshot", {
        type: "infrastructure",
        event: "metrics_snapshot",
        hostname: os.hostname(),
        platform: os.platform(),
        cpuLoad: os.loadavg(),
        totalMemoryMB: Math.round(os.totalmem() / 1024 / 1024),
        freeMemoryMB: Math.round(os.freemem() / 1024 / 1024),
        processHeapMB: Math.round(mem.heapUsed / 1024 / 1024),
        processRssMB: Math.round(mem.rss / 1024 / 1024),
        uptimeSeconds: Math.round(process.uptime()),
      });
    },
    () => {
      logger.info("Cache operation", {
        type: "performance",
        event: ["cache_hit", "cache_miss", "cache_set", "cache_evict"][Math.floor(Math.random() * 4)],
        key: `${["user", "product", "order", "session", "config"][Math.floor(Math.random() * 5)]}:${Math.floor(Math.random() * 500)}`,
        ttl: [60, 300, 600, 1800, 3600][Math.floor(Math.random() * 5)],
        size: Math.floor(Math.random() * 10000),
      });
    },
    () => {
      const latency = Math.floor(Math.random() * 500);
      const logFn = latency > 200 ? "warn" : "info";
      logger[logFn]("External service call", {
        type: "performance",
        event: "external_call",
        service: ["stripe-api", "sendgrid", "aws-s3", "redis", "elasticsearch", "twilio"][Math.floor(Math.random() * 6)],
        method: methods[Math.floor(Math.random() * methods.length)],
        latency,
        success: Math.random() > 0.1,
        region: regions[Math.floor(Math.random() * regions.length)],
        retryCount: Math.random() > 0.8 ? Math.floor(Math.random() * 3) + 1 : 0,
      });
    },

    // ── Business Event Logs ──
    () => {
      const amount = parseFloat((Math.random() * 999 + 1).toFixed(2));
      const currency = ["USD", "EUR", "GBP"][Math.floor(Math.random() * 3)];
      const paymentMethod = ["credit_card", "paypal", "stripe", "bank_transfer"][Math.floor(Math.random() * 4)];
      logger.info("Order created", {
        type: "business",
        event: "order_created",
        orderId: `ORD-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        userId: users[Math.floor(Math.random() * users.length)],
        amount,
        currency,
        items: Math.floor(Math.random() * 10) + 1,
        paymentMethod,
      });
      metrics.ordersCreatedTotal.inc({ currency, payment_method: paymentMethod });
      metrics.revenueTotal.inc({ currency }, amount);
    },
    () => {
      const status = ["completed", "failed", "refunded", "pending"][Math.floor(Math.random() * 4)];
      const logFn = status === "failed" ? "error" : status === "refunded" ? "warn" : "info";
      const gateway = ["stripe", "paypal", "square"][Math.floor(Math.random() * 3)];
      logger[logFn]("Payment processed", {
        type: "business",
        event: "payment_processed",
        transactionId: `TXN-${Date.now()}`,
        status,
        amount: parseFloat((Math.random() * 500 + 5).toFixed(2)),
        processingTime: Math.floor(Math.random() * 3000),
        gateway,
        failureReason: status === "failed" ? ["insufficient_funds", "card_declined", "timeout", "fraud_detected"][Math.floor(Math.random() * 4)] : undefined,
      });
      metrics.paymentsTotal.inc({ status, gateway });
    },
    () => {
      logger.info("Inventory update", {
        type: "business",
        event: "inventory_change",
        productId: `PROD-${Math.floor(Math.random() * 500)}`,
        previousStock: Math.floor(Math.random() * 100) + 20,
        newStock: Math.floor(Math.random() * 100),
        change: -Math.floor(Math.random() * 10) - 1,
        warehouse: ["warehouse-a", "warehouse-b", "warehouse-c"][Math.floor(Math.random() * 3)],
      });
    },

    // ── Worker / Background Job Logs ──
    () => {
      const duration = Math.floor(Math.random() * 10000);
      const success = Math.random() > 0.15;
      const logFn = success ? "info" : "error";
      const jobType = ["email_send", "report_generate", "data_cleanup", "sync_external", "image_resize", "invoice_generate"][Math.floor(Math.random() * 6)];
      const queue = ["high", "default", "low"][Math.floor(Math.random() * 3)];
      logger[logFn]("Background job completed", {
        type: "worker",
        event: "job_completed",
        jobId: `job_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
        jobType,
        duration,
        success,
        retries: Math.floor(Math.random() * 3),
        queue,
        error: success ? undefined : errorMessages[Math.floor(Math.random() * errorMessages.length)],
      });
      metrics.jobsCompletedTotal.inc({ job_type: jobType, queue, status: success ? "success" : "failed" });
    },
    () => {
      const queue = ["high", "default", "low"][Math.floor(Math.random() * 3)];
      const pending = Math.floor(Math.random() * 50);
      logger.info("Queue metrics", {
        type: "worker",
        event: "queue_metrics",
        queue,
        pending,
        processing: Math.floor(Math.random() * 10),
        completed: Math.floor(Math.random() * 1000),
        failed: Math.floor(Math.random() * 20),
        avgProcessingTime: Math.floor(Math.random() * 5000),
      });
      metrics.queueDepth.set({ queue }, pending);
    },

    // ── Notification Logs ──
    () => {
      const channel = ["email", "sms", "push", "webhook", "slack"][Math.floor(Math.random() * 5)];
      const delivered = Math.random() > 0.1;
      logger[delivered ? "info" : "error"]("Notification dispatched", {
        type: "notification",
        event: "dispatch",
        channel,
        recipient: users[Math.floor(Math.random() * users.length)],
        template: ["welcome", "order_confirm", "password_reset", "promo", "alert"][Math.floor(Math.random() * 5)],
        delivered,
        latency: Math.floor(Math.random() * 2000),
        error: delivered ? undefined : "delivery_failed",
      });
    },

    // ── Error Logs (various severities) ──
    () => {
      const service = services[Math.floor(Math.random() * services.length)];
      logger.error("Unhandled exception caught", {
        type: "application-error",
        severity: "critical",
        error: errorMessages[Math.floor(Math.random() * errorMessages.length)],
        service,
        stack: `Error: ${errorMessages[Math.floor(Math.random() * errorMessages.length)]}\n    at processRequest (/app/server.js:${Math.floor(Math.random() * 200)}:${Math.floor(Math.random() * 40)})\n    at Layer.handle (/app/node_modules/express/lib/router/layer.js:95:5)`,
        pid: process.pid,
      });
      metrics.errorsTotal.inc({ type: "application-error", severity: "critical", service });
    },
    () => {
      const service = services[Math.floor(Math.random() * services.length)];
      logger.error("Circuit breaker tripped", {
        type: "infrastructure",
        event: "circuit_breaker",
        service,
        state: ["open", "half-open"][Math.floor(Math.random() * 2)],
        failureCount: Math.floor(Math.random() * 20) + 5,
        lastError: errorMessages[Math.floor(Math.random() * errorMessages.length)],
        cooldownSeconds: 30,
      });
      metrics.errorsTotal.inc({ type: "infrastructure", severity: "high", service });
    },

    // ── Deployment / Config Logs ──
    () => {
      logger.info("Configuration loaded", {
        type: "config",
        event: "config_reload",
        source: ["env", "file", "remote"][Math.floor(Math.random() * 3)],
        keys: Math.floor(Math.random() * 30) + 5,
        region: regions[Math.floor(Math.random() * regions.length)],
        environment: "production",
      });
    },

    // ── Audit Logs ──
    () => {
      logger.info("Audit event", {
        type: "audit",
        event: ["user_created", "user_deleted", "role_changed", "permission_granted", "settings_updated", "data_exported"][Math.floor(Math.random() * 6)],
        performedBy: users[Math.floor(Math.random() * users.length)],
        targetUser: users[Math.floor(Math.random() * users.length)],
        ip: `10.0.${Math.floor(Math.random() * 255)}.${Math.floor(Math.random() * 255)}`,
        changes: { field: ["role", "email", "name", "status"][Math.floor(Math.random() * 4)], from: "old_value", to: "new_value" },
      });
    },
  ];

  // Generate logs every 800ms (fast, continuous flow)
  setInterval(() => {
    const count = 1 + Math.floor(Math.random() * 4);
    for (let i = 0; i < count; i++) {
      scenarios[Math.floor(Math.random() * scenarios.length)]();
    }
  }, 800);

  // Periodic system health log every 10 seconds
  setInterval(() => {
    const mem = process.memoryUsage();
    logger.info("Periodic health report", {
      type: "health",
      event: "periodic_check",
      uptime: Math.round(process.uptime()),
      heapUsedMB: Math.round(mem.heapUsed / 1024 / 1024),
      rssMB: Math.round(mem.rss / 1024 / 1024),
      cpuLoad: os.loadavg(),
      freeMemoryMB: Math.round(os.freemem() / 1024 / 1024),
      activeHandles: process._getActiveHandles().length,
      activeRequests: process._getActiveRequests().length,
    });
  }, 10000);

  // Simulate occasional error bursts every 30-60 seconds
  setInterval(() => {
    const burstSize = Math.floor(Math.random() * 5) + 2;
    logger.warn("Error burst detected", { type: "infrastructure", event: "error_burst", burstSize });
    for (let i = 0; i < burstSize; i++) {
      setTimeout(() => {
        logger.error("Cascading failure", {
          type: "application-error",
          severity: ["high", "critical"][Math.floor(Math.random() * 2)],
          error: errorMessages[Math.floor(Math.random() * errorMessages.length)],
          service: services[Math.floor(Math.random() * services.length)],
          correlationId: `burst_${Date.now()}`,
        });
      }, i * 200);
    }
  }, 30000 + Math.random() * 30000);
}

// ─── Start Server ───────────────────────────────────────────────────────────
app.listen(PORT, () => {
  logger.info("=== SERVER STARTED ===", {
    type: "startup",
    port: PORT,
    nodeVersion: process.version,
    platform: os.platform(),
    arch: os.arch(),
    hostname: os.hostname(),
    pid: process.pid,
    env: process.env.NODE_ENV || "development",
    totalMemoryMB: Math.round(os.totalmem() / 1024 / 1024),
    cpus: os.cpus().length,
  });

  logger.info("Starting continuous log generator", { type: "startup", event: "log_generator_init" });
  generateContinuousLogs();
  logger.info("Log generator active - producing diverse logs every 800ms", { type: "startup", event: "log_generator_running" });

  // Push metrics to Pushgateway every 15 seconds
  const PUSH_INTERVAL_MS = parseInt(process.env.PUSH_INTERVAL_MS || "15000", 10);
  setInterval(() => metrics.pushMetrics("test-backend"), PUSH_INTERVAL_MS);
  logger.info("Pushgateway push scheduled", {
    type: "startup",
    event: "pushgateway_init",
    url: process.env.PUSHGATEWAY_URL || "http://pushgateway:9091",
    intervalMs: PUSH_INTERVAL_MS,
  });
});
