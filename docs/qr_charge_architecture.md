## QR-Based Powerbank Charging Flow

### Overview
This design links a QR-code payment workflow with an automated charging station controlled by a Raspberry Pi. A Python backend verifies payment success and instructs the Pi to switch charging relays for an amount-dependent duration (for example, 10 min or 30 min).

```
Customer → scans QR → pays provider → provider → webhook → backend
Backend → publishes command (MQTT/WebSocket/REST) → Raspberry Pi → relay → charger
```

### Components
- **Payment provider** – Razorpay (test mode) or any provider that supports payment links and webhooks. Razorpay is referenced in the sample code because it offers UPI support and a free developer tier.
- **Backend service** – FastAPI application that receives payment intent webhooks, validates the signature, records success, derives the charging duration, and notifies the Pi.
- **Message broker / transport** – MQTT (e.g., Eclipse Mosquitto) or HTTPS direct calls. MQTT is resilient for intermittent connections; HTTPS polling is simpler but less responsive.
- **Raspberry Pi controller** – Python script that subscribes to charging instructions and toggles GPIO pins wired to one or more relays driving the charging ports.
- **Persistent state (optional)** – SQLite or PostgreSQL to log sessions, track device health, and support audits.
- **Monitoring & safety** – Watchdog timer on the Pi, over-current protection on the power rails, emergency stop.

### Sequence
1. **Create payment link** – The backend exposes `POST /create-session` which issues a Razorpay Payment Link. The response includes a URL that is rendered into a QR code. Notes on the link store the device identifier and charging duration.
2. **Payment success** – Razorpay sends a `payment_link.paid` webhook. The backend verifies the signature, reads the notes, and enqueues a `start_charge` command with `duration_minutes`.
3. **Pi receives command** – The Pi script, subscribed to `charges/start`, parses the JSON payload, validates safety constraints, and toggles GPIO high to energize a relay. A countdown timer turns the relay off automatically; manual cancel commands are also supported.
4. **Status feedback** – The Pi reports `started/completed/error` events back to the backend, which can update a dashboard.

### Amount-to-Duration Mapping
Configure plans in `backend/config/pricing.toml`:
```0:7:backend/config/pricing.toml
currency = "INR"

[plans.ten_min]
amount = 10
duration = 10

[plans.thirty_min]
amount = 30
duration = 30

[plans.hour_pass]
amount = 50
duration = 60
```
The backend enforces the mapping so that unsupported plans are rejected before the payment link is issued. Amounts are expressed in major currency units (₹). The FastAPI service converts them into the smallest unit (paise) when creating a Razorpay Payment Link.

### Deployment Suggestions
- **Development** – Use Razorpay test instruments (card/UPI sandbox), run FastAPI and Mosquitto via Docker Compose, expose the webhook endpoint with `ngrok`, and run the Pi script on a local Pi or simulate with `RPi.GPIO` stubs on a laptop.
- **Version control** – Initialize a Git repo, commit backend and Pi code separately. Use a GitHub private repository (free) for collaboration.
- **CI/CD** – Optional GitHub Actions workflow running `pytest`, `flake8`, and `mypy`. For Pi deployments, `ansible` or `fabric` can push updates.

### Safety Considerations
- Design relay switching with proper flyback diodes.
- Add current sensing to detect device unplug or fault.
- Ensure the Pi script always fails safe (turns relays off) on errors, restarts, or when the backend loses contact.
- Keep customer data minimal; rely on provider tokens instead of storing PAN or personal information.


