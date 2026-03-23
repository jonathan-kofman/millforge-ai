# MillForge API Specification

Base URL: `http://localhost:8000`

Interactive docs: `http://localhost:8000/docs` (Swagger UI)

---

## POST /api/quote

Get an instant price and lead time estimate for a part order.

**Request**
```json
{
  "material": "steel",        // "steel" | "aluminum" | "titanium" | "copper"
  "dimensions": "200x100x10mm",
  "quantity": 500,
  "due_date": "2025-07-01T00:00:00Z",  // optional, defaults to +30 days
  "priority": 3               // 1 (urgent) – 10 (low), default 5
}
```

**Response 200**
```json
{
  "quote_id": "QUOTE-A1B2C3D4",
  "material": "steel",
  "dimensions": "200x100x10mm",
  "quantity": 500,
  "estimated_lead_time_hours": 36.5,
  "estimated_lead_time_days": 1.52,
  "unit_price_usd": 2.375,
  "total_price_usd": 1187.50,
  "currency": "USD",
  "valid_until": "2025-06-08T10:00:00Z",
  "notes": "Lead time compressed to 1.5 days vs. industry average of 60–90 days. Volume discount applied: 5%."
}
```

---

## POST /api/schedule

Optimize a production schedule for a given list of orders.

**Request**
```json
{
  "orders": [
    {
      "order_id": "ORD-001",
      "material": "steel",
      "quantity": 500,
      "dimensions": "200x100x10mm",
      "due_date": "2025-06-01T08:00:00Z",
      "priority": 2,
      "complexity": 1.0
    }
  ],
  "start_time": "2025-05-30T08:00:00Z"  // optional
}
```

**Response 200**
```json
{
  "generated_at": "2025-05-29T14:00:00Z",
  "summary": {
    "total_orders": 1,
    "on_time_count": 1,
    "on_time_rate_percent": 100.0,
    "makespan_hours": 24.5,
    "utilization_percent": 78.3
  },
  "schedule": [
    {
      "order_id": "ORD-001",
      "machine_id": 1,
      "material": "steel",
      "quantity": 500,
      "setup_start": "2025-05-30T08:00:00Z",
      "processing_start": "2025-05-30T08:30:00Z",
      "completion_time": "2025-05-30T10:35:00Z",
      "setup_minutes": 30,
      "processing_minutes": 125.0,
      "on_time": true,
      "lateness_hours": -45.4,
      "due_date": "2025-06-01T08:00:00Z"
    }
  ]
}
```

---

## GET /api/schedule/demo

Returns a schedule built from the built-in mock order dataset (8 orders across 4 materials). No request body required. Same response shape as POST /api/schedule.

---

## POST /api/vision/inspect

Inspect a part image for quality defects.

**Request**
```json
{
  "image_url": "https://example.com/part.jpg",
  "material": "steel",        // optional
  "order_id": "ORD-001"       // optional, for traceability
}
```

**Response 200**
```json
{
  "image_url": "https://example.com/part.jpg",
  "passed": true,
  "confidence": 0.923,
  "defects_detected": [],
  "recommendation": "Part meets quality specifications. Approve for shipment.",
  "inspector_version": "mock-v0.1",
  "order_id": "ORD-001"
}
```

---

## POST /api/contact

Submit a contact or pilot interest form.

**Request**
```json
{
  "name": "Jane Smith",
  "email": "jane@company.com",
  "company": "Acme Manufacturing",
  "message": "We produce 10,000 steel parts per month and are interested in piloting.",
  "pilot_interest": true
}
```

**Response 200**
```json
{
  "success": true,
  "message": "Thanks Jane! We've received your message and will reach out about our pilot program."
}
```

---

## GET /health

Returns `{"status": "ok"}`. Used by Docker health checks.
