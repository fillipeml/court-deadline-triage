"""The only place, besides config.py, that reads demo mode and picks real or local implementations."""

from __future__ import annotations

from typing import Any

from .catalogue import Catalogue
from .config import Config
from .demo import FixtureClassifier, FixtureDjenClient
from .djen import DjenClient
from .mail import GraphMailer, Mailer, OutboxMailer
from .sweep import PublicationSource


def build_client(config: Config) -> PublicationSource:
    if config.demo_mode:
        return FixtureDjenClient()
    return DjenClient(config)


def build_classifier(config: Config, catalogue: Catalogue) -> Any | None:
    """None when the model is unavailable: the pre-filter still runs and the rest stays pending."""
    if config.demo_mode:
        return FixtureClassifier()
    if not config.llm_available:
        return None
    from .classifier import Classifier

    return Classifier(catalogue, config.classifier_model)


def build_mailer(config: Config) -> Mailer:
    if config.demo_mode:
        return OutboxMailer(config.output_dir / "outbox")
    return GraphMailer(config)
