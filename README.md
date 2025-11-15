# QR Payment Powered Mobile Charging

This repo demonstrates how to link QR-code based payments with a Raspberry Pi controlled charging station. When a customer scans a QR code and completes a payment, the backend triggers the Pi to energize a relay for a duration mapped to the paid amount (e.g. 10 min or 30 min).

## Repository Structure

- `backend/` – FastAPI service with Razorpay integration and MQTT publisher.
- `raspberry_pi/` – MQTT listener that drives GPIO pins to toggle relays.
- `docs/` – Architecture notes and flow diagrams.

## 1. Backend Setup (FastAPI + Razorpay)

1. **Create a Razorpay account** (free test mode) and collect:
   - Key ID (`rzp_test_...`)
   - Key Secret
   - Webhook secret (define while configuring a webhook; keep the value handy).
2. **Install dependencies**:
   ```bash
   cd /Users/jaiminpatel/Downloads/powerbank/backend
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Environment variables** – create `backend/.env` with:
   ```
   RAZORPAY_KEY_ID=rzp_test_xxx
   RAZORPAY_KEY_SECRET=xxxx
   RAZORPAY_WEBHOOK_SECRET=your_webhook_secret
   PUBLIC_BASE_URL=https://<your-ngrok-domain>
   MQTT_HOST=localhost
   MQTT_PORT=1883
   MQTT_TOPIC_PREFIX=powerbank
   ```
4. **Run the API**:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
5. **Expose for Razorpay webhooks** (dev): `ngrok http 8000` and add the HTTPS URL as the webhook endpoint in Razorpay (`https://<ngrok>/razorpay/webhook`). Subscribe to `payment_link.paid`.
6. **Generate QR code**:
   ```bash
   http POST :8000/create-session plan_code=ten_min device_id=bay-1
   ```
   Use the returned `payment_link_url` with a free tool like `qr-code-generator.com` or the Python `qrcode` package to print a QR for your charging kiosk.

## 2. Message Broker (MQTT)

- Install Mosquitto locally (`brew install mosquitto`) or run via Docker:
  ```bash
  docker run -it -p 1883:1883 eclipse-mosquitto
  ```
- Ensure the topic prefix in `backend/config/pricing.toml` matches the Raspberry Pi script (`powerbank/charges/<device_id>`).

## 3. Raspberry Pi Controller

1. **Hardware** – Raspberry Pi (any model with GPIO), 5 V relay board, power supply, and charging sockets. Wire the relay as a high-side switch for the power outlet.
2. **Software setup**:
   ```bash
   sudo apt update
   sudo apt install python3-pip python3-venv python3-rpi.gpio
   cd /home/pi/powerbank/raspberry_pi
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Run listener**:
   ```bash
   python charge_controller.py
   ```
   The script subscribes to `powerbank/charges/bay-1` and toggles GPIO 17 for the requested duration. Adjust `HardwareConfig` to match your wiring.

## 4. Testing Workflow

- Use Razorpay test mode instruments (e.g., card `4111 1111 1111 1111`, any future expiry, random CVV) or simulate UPI approval in the Razorpay dashboard.
- Watch the Raspberry Pi logs to confirm the relay activates for the expected time.
- Use `mosquitto_sub -t 'powerbank/charges/#'` to debug messages.
- Add unit tests with `pytest` for the backend plan lookup and webhook signature verification.

## 5. Suggested Enhancements

- Store session data in SQLite (`sqlmodel` or `alembic`).
- Add authentication for the `/create-session` endpoint.
- Implement retry logic if the Pi is offline (persist commands, use MQTT retained messages).
- Build a simple status dashboard (FastAPI + HTMX) to display active bays.

Refer to `docs/qr_charge_architecture.md` for in-depth design rationale and safety considerations.

## 6. Deploy to Render (Git-connected)

1. **Push this repo to GitHub/GitLab** – Render pulls straight from your Git provider.
2. **Enable Render deploys**:
   - Render detects `render.yaml` at the repo root and provisions a free Python Web Service (`powerbank-backend`).
   - If you prefer the dashboard flow, select *New → Web Service*, choose the repo, set the root directory to `backend`, build command `pip install -r requirements.txt`, and start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
3. **Environment variables (Render dashboard or `render.yaml`)** – set:
   - `RAZORPAY_KEY_ID`
   - `RAZORPAY_KEY_SECRET`
   - `RAZORPAY_WEBHOOK_SECRET`
   - `PUBLIC_BASE_URL=https://<your-service>.onrender.com`
   - `MQTT_HOST` pointing to your broker (public Mosquitto, EMQX Cloud, HiveMQ, or a self-hosted instance on another Render service/VPS).
4. **Deploy** – Trigger the first deploy; Uvicorn exposes the service at `https://<service>.onrender.com`.
5. **Webhook setup** – In Razorpay set the webhook URL to `https://<service>.onrender.com/razorpay/webhook` and subscribe to `payment_link.paid`. Render’s HTTPS URL replaces the need for ngrok in production.
6. **MQTT connectivity** – Ensure the Raspberry Pi can reach the broker configured in `MQTT_HOST` (if it’s public) or create a Render Private Service / external broker if you need a VPN.

Redeploys happen automatically on `main` (or whichever branch you configure) after each push, so the Pi always talks to the latest backend build.


