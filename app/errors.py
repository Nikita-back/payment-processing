class PermanentFailure(Exception):
    pass


class PaymentNotFoundError(PermanentFailure):
    pass


class IdempotencyConflictError(Exception):
    pass


class WebhookDeliveryError(Exception):
    pass


class WebhookURLRejected(Exception):
    pass


class PaymentInProgress(Exception):
    pass
