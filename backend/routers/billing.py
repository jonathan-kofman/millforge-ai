"""
Stripe Checkout + webhooks for MillForge SaaS tiers.

Env:
  STRIPE_SECRET_KEY
  STRIPE_WEBHOOK_SECRET
  STRIPE_PUBLISHABLE_KEY (optional — returned by /api/billing/config for future Elements)
  FRONTEND_URL (success/cancel redirects, default http://localhost:5173)
  STRIPE_PRICE_STARTER_MONTHLY, STRIPE_PRICE_STARTER_ANNUAL
  STRIPE_PRICE_GROWTH_MONTHLY, STRIPE_PRICE_GROWTH_ANNUAL
  STRIPE_PRICE_ENTERPRISE_MONTHLY, STRIPE_PRICE_ENTERPRISE_ANNUAL
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user_optional
from database import get_db
from db_models import User
from models.schemas import (
    BillingCheckoutRequest,
    BillingCheckoutResponse,
    BillingCheckoutSessionResponse,
    BillingConfigResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["Billing"])

_BILLABLE = frozenset({"starter", "growth", "enterprise"})


def _price_env_key(tier_id: str, billing_cycle: str) -> str:
    tier = tier_id.strip().lower()
    cycle = billing_cycle.strip().lower()
    if tier not in _BILLABLE or cycle not in ("monthly", "annual"):
        return ""
    return f"STRIPE_PRICE_{tier.upper()}_{'ANNUAL' if cycle == 'annual' else 'MONTHLY'}"


def _get_price_id(tier_id: str, billing_cycle: str) -> Optional[str]:
    key = _price_env_key(tier_id, billing_cycle)
    if not key:
        return None
    val = os.getenv(key, "").strip()
    return val or None


def _stripe_secret() -> Optional[str]:
    s = os.getenv("STRIPE_SECRET_KEY", "").strip()
    return s or None


@router.get("/config", response_model=BillingConfigResponse)
def billing_config():
    secret = _stripe_secret()
    pk = os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip() or None
    return BillingConfigResponse(stripe_enabled=bool(secret), publishable_key=pk)


@router.post("/checkout", response_model=BillingCheckoutResponse)
def create_checkout(
    body: BillingCheckoutRequest,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    secret = _stripe_secret()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured (set STRIPE_SECRET_KEY).",
        )
    price_id = _get_price_id(body.tier_id, body.billing_cycle)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing Stripe price for tier={body.tier_id} billing_cycle={body.billing_cycle}. "
            f"Set env {_price_env_key(body.tier_id, body.billing_cycle)}.",
        )

    email = (body.customer_email or "").strip() or None
    if user:
        email = user.email
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="customer_email is required when not signed in.",
        )

    frontend = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
    stripe.api_key = secret

    md: dict[str, str] = {
        "tier_id": body.tier_id.strip().lower(),
        "billing_cycle": body.billing_cycle.strip().lower(),
    }
    if user:
        md["user_id"] = str(user.id)

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=email,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{frontend}/?tab=pricing&checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{frontend}/?tab=pricing&checkout=cancelled",
        metadata=md,
        subscription_data={"metadata": md},
    )
    if not session.url:
        raise HTTPException(status_code=500, detail="Stripe did not return a checkout URL")
    return BillingCheckoutResponse(checkout_url=session.url)


@router.get("/checkout-session", response_model=BillingCheckoutSessionResponse)
def get_checkout_session(
    session_id: str,
    user: Optional[User] = Depends(get_current_user_optional),
):
    secret = _stripe_secret()
    if not secret or not session_id.strip():
        return BillingCheckoutSessionResponse(success=False)
    stripe.api_key = secret
    try:
        s = stripe.checkout.Session.retrieve(
            session_id.strip(),
            expand=["subscription"],
        )
    except stripe.error.StripeError as e:
        logger.warning("Stripe retrieve session failed: %s", e)
        return BillingCheckoutSessionResponse(success=False)

    if getattr(s, "payment_status", None) != "paid":
        return BillingCheckoutSessionResponse(
            success=False,
            payment_status=getattr(s, "payment_status", None),
        )

    tier_id = (s.metadata or {}).get("tier_id")
    billing_cycle = (s.metadata or {}).get("billing_cycle")

    sub_status = None
    sub = getattr(s, "subscription", None)
    if isinstance(sub, stripe.Subscription):
        sub_status = sub.status
    elif isinstance(sub, str):
        try:
            sub_obj = stripe.Subscription.retrieve(sub)
            sub_status = sub_obj.status
        except stripe.error.StripeError:
            pass

    cust_email = getattr(s, "customer_details", None) and s.customer_details.email
    if not cust_email:
        cust_email = getattr(s, "customer_email", None)

    if user and cust_email and user.email.lower() != str(cust_email).lower():
        raise HTTPException(status_code=403, detail="Session email does not match signed-in user.")

    return BillingCheckoutSessionResponse(
        success=True,
        payment_status=s.payment_status,
        tier_id=tier_id,
        billing_cycle=billing_cycle,
        subscription_status=sub_status,
        customer_email=cust_email,
    )


def _apply_checkout_completed(db: Session, obj: dict[str, Any]) -> None:
    md = obj.get("metadata") or {}
    tier_id = md.get("tier_id")
    user_id_raw = md.get("user_id")
    customer = obj.get("customer")
    subscription = obj.get("subscription")

    cust_id = customer if isinstance(customer, str) else (customer or {}).get("id")
    sub_id = subscription if isinstance(subscription, str) else (subscription or {}).get("id")

    if user_id_raw:
        try:
            uid = int(user_id_raw)
        except (TypeError, ValueError):
            uid = None
        if uid is not None:
            u = db.query(User).filter(User.id == uid).first()
            if u:
                if cust_id:
                    u.stripe_customer_id = cust_id
                if sub_id:
                    u.stripe_subscription_id = sub_id
                if tier_id:
                    u.subscription_tier = tier_id
                u.subscription_status = "active"
                db.commit()


def _sync_subscription_event(db: Session, sub: dict[str, Any]) -> None:
    customer_id = sub.get("customer")
    if not customer_id:
        return
    u = db.query(User).filter(User.stripe_customer_id == customer_id).first()
    if not u:
        return
    u.stripe_subscription_id = sub.get("id") or u.stripe_subscription_id
    st = sub.get("status")
    if st:
        u.subscription_status = st
    md = sub.get("metadata") or {}
    if md.get("tier_id"):
        u.subscription_tier = md["tier_id"]
    db.commit()


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    secret = _stripe_secret()
    wh_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret or not wh_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe webhook not configured.",
        )
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    if not sig:
        raise HTTPException(status_code=400, detail="Missing stripe-signature")

    stripe.api_key = secret
    try:
        event = stripe.Webhook.construct_event(payload, sig, wh_secret)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    et = event["type"]
    raw = event["data"]["object"]
    if isinstance(raw, dict):
        data = raw
    else:
        data = raw.to_dict_recursive()

    try:
        if et == "checkout.session.completed":
            _apply_checkout_completed(db, data)
        elif et in ("customer.subscription.updated", "customer.subscription.deleted"):
            _sync_subscription_event(db, data)
    except Exception as exc:
        logger.exception("Billing webhook handler error: %s", exc)
        raise HTTPException(status_code=500, detail="Webhook processing failed")

    return {"received": True}
