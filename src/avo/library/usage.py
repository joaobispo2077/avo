"""Batch-owned observations are referenced once, never copied into video costs."""

from decimal import Decimal, InvalidOperation

from avo.library.rules import reject


def record_usage(
    store,
    batch_id,
    attempt_id,
    recording_id,
    *,
    tokens=None,
    amount=None,
    currency=None,
    basis="unmetered-local",
):
    if tokens is not None and (
        not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0
    ):
        reject(
            "LIB_INVALID_REQUEST",
            "Token observations must be measured nonnegative integers",
        )
    _money(amount, currency)
    body = {
        "batchId": batch_id,
        "attemptId": attempt_id,
        "recordingId": recording_id,
        "tokens": tokens,
        "amount": amount,
        "currency": currency,
        "basis": basis,
        "coverage": "partial"
        if tokens is not None or amount is not None
        else "unavailable",
    }
    return store.put("usage", body)


def _money(amount, currency):
    if amount is None:
        return
    try:
        value = Decimal(amount)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("Invalid recorded monetary amount") from exc
    if not value.is_finite() or value < 0 or not currency:
        reject(
            "LIB_INVALID_REQUEST",
            "Recorded money requires a finite amount and currency",
        )
