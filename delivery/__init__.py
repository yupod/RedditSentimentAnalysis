from config import DocumentDeliveryConfig, EmailDeliveryConfig
from delivery.base import BaseDelivery
from delivery.document import DocumentDelivery
from delivery.email_delivery import EmailDelivery


def create_delivery(config) -> BaseDelivery:
    if isinstance(config, EmailDeliveryConfig):
        return EmailDelivery(config)
    if isinstance(config, DocumentDeliveryConfig):
        return DocumentDelivery(config)
    raise ValueError(f"Unknown delivery type: {type(config)}")
