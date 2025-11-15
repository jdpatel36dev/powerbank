from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress

import razorpay
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from .config import Settings
from .messaging import ChargeCommand, ChargePublisher
from .models import CreateSessionRequest, CreateSessionResponse

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.settings = settings
    app.state.razorpay_client = razorpay.Client(
        auth=(settings.razorpay_key_id, settings.razorpay_key_secret)
    )
    publisher = ChargePublisher(
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        topic_prefix=settings.mqtt_topic_prefix,
        username=settings.mqtt_username,
        password=settings.mqtt_password,
    )
    app.state.publisher = publisher
    try:
        publisher.connect()
        yield
    finally:
        publisher.disconnect()


app = FastAPI(title="Powerbank Payment Backend", lifespan=lifespan)


def get_settings() -> Settings:
    return app.state.settings


def get_publisher() -> ChargePublisher:
    return app.state.publisher


def get_razorpay_client() -> razorpay.Client:
    return app.state.razorpay_client


@app.post("/create-session", response_model=CreateSessionResponse)
async def create_checkout_session(
    payload: CreateSessionRequest,
    settings: Settings = Depends(get_settings),
    client: razorpay.Client = Depends(get_razorpay_client),
) -> CreateSessionResponse:
    plan = settings.pricing.lookup_plan(payload.plan_code)

    callback_path = payload.callback_path or settings.callback_path
    callback_url = f"{settings.public_base_url.rstrip('/')}{callback_path}"

    payment_link_data = dict(
        amount=plan.amount_major_units * 100,
        currency=settings.pricing.currency.upper(),
        accept_partial=False,
        description=f"{plan.duration_minutes}-minute charging pass",
        notes={
            "plan_code": plan.code,
            "device_id": payload.device_id,
            "duration_minutes": str(plan.duration_minutes),
        },
        callback_url=callback_url,
        callback_method="get",
    )

    customer = {}
    if payload.customer_email:
        customer["email"] = payload.customer_email
    if payload.customer_contact:
        customer["contact"] = payload.customer_contact
    if customer:
        payment_link_data["customer"] = customer
        payment_link_data["notify"] = {
            "email": bool(payload.customer_email),
            "sms": bool(payload.customer_contact),
        }

    try:
        link = await asyncio.to_thread(client.payment_link.create, payment_link_data)
    except razorpay.errors.RazorpayError as exc:
        logger.exception("Razorpay error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to create Razorpay payment link",
        ) from exc

    return CreateSessionResponse(
        payment_link_url=link.get("short_url") or link.get("url"),
        payment_link_id=link.get("id"),
        plan_code=plan.code,
        amount_major_units=plan.amount_major_units,
        currency=settings.pricing.currency,
        duration_minutes=plan.duration_minutes,
    )


@app.post("/razorpay/webhook")
async def razorpay_webhook(
    request: Request,
    razorpay_signature: str = Header(..., alias="X-Razorpay-Signature"),
    settings: Settings = Depends(get_settings),
    publisher: ChargePublisher = Depends(get_publisher),
):
    payload = await request.body()
    body_text = payload.decode("utf-8")
    try:
        razorpay.Utility.verify_webhook_signature(
            body_text,
            razorpay_signature,
            settings.razorpay_webhook_secret,
        )
    except razorpay.errors.SignatureVerificationError as exc:
        logger.warning("Invalid Razorpay signature: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature") from exc
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Failed to verify webhook: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")

    try:
        event = json.loads(body_text)
    except json.JSONDecodeError as exc:
        logger.exception("Webhook body is not valid JSON: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON") from exc

    event_type = event.get("event")

    if event_type == "payment_link.paid":
        payment_link_entity = (
            event.get("payload", {})
            .get("payment_link", {})
            .get("entity", {})
        )
        notes = payment_link_entity.get("notes") or {}
        plan_code = notes.get("plan_code")
        device_id = notes.get("device_id", "bay-1")
        duration_override = notes.get("duration_minutes")
        payment_reference = payment_link_entity.get("id", "unknown-link")

        try:
            plan = settings.pricing.lookup_plan(plan_code)
        except ValueError as exc:
            logger.error("Unknown plan code from Razorpay notes: %s", plan_code)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        duration_minutes = plan.duration_minutes
        if duration_override:
            with suppress(ValueError):
                duration_minutes = int(duration_override)

        command = ChargeCommand(
            device_id=device_id,
            duration_minutes=duration_minutes,
            payment_reference=payment_reference,
        )
        try:
            publisher.publish_charge(command)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed to publish charge command")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to publish charge command",
            ) from exc

        logger.info(
            "Charge command enqueued (plan=%s, device=%s, duration=%s)",
            plan.code,
            device_id,
            duration_minutes,
        )

    return JSONResponse({"received": True})


@app.get("/health")
async def healthcheck(
    publisher: ChargePublisher = Depends(get_publisher),
) -> dict[str, bool]:
    return {"ok": True, "mqtt_connected": publisher is not None}


