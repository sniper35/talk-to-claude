"""Factory for creating transcription service providers."""

from typing import Dict, Any, Type

from .base import BaseTranscriber
from .deepgram_client import DeepgramTranscriber
from .elevenlabs_client import ElevenLabsTranscriber
from .openai_client import OpenAITranscriber
from ..utils.logger import get_logger

_logger = get_logger("transcription.factory")

# Registry of available transcription providers
PROVIDERS: Dict[str, Type[BaseTranscriber]] = {
    "deepgram": DeepgramTranscriber,
    "elevenlabs": ElevenLabsTranscriber,
    "openai": OpenAITranscriber,
}


def create_transcriber(service: str, config: Dict[str, Any]) -> BaseTranscriber:
    """Create a transcription service provider based on configuration.

    Args:
        service: Name of the transcription service ('deepgram', 'elevenlabs', 'openai')
        config: Configuration dictionary containing:
            - api_key: API key for the service
            - Additional provider-specific settings

    Returns:
        Instance of the appropriate transcriber class

    Raises:
        ValueError: If the service name is not recognized
        KeyError: If required configuration is missing
    """
    service = service.lower()

    if service not in PROVIDERS:
        available = ", ".join(PROVIDERS.keys())
        raise ValueError(
            f"Unknown transcription service: '{service}'. "
            f"Available services: {available}"
        )

    provider_class = PROVIDERS[service]
    _logger.info(f"Creating transcriber: {service}")

    # Extract common configuration
    api_key = config.get("api_key")
    if not api_key:
        raise KeyError(f"API key not provided for {service} transcription service")

    # Get provider-specific configuration
    provider_config = config.get(service, {})

    # Create provider instance based on service type
    if service == "deepgram":
        return DeepgramTranscriber(
            api_key=api_key,
            model=provider_config.get("model", "nova-2-general"),
            language=provider_config.get("language", "en-US"),
            interim_results=config.get("interim_results", True),
            smart_format=provider_config.get("smart_format", True),
            utterance_end_ms=provider_config.get("utterance_end_ms", 1000),
        )

    elif service == "elevenlabs":
        return ElevenLabsTranscriber(
            api_key=api_key,
            model=provider_config.get("model", "scribe_v1"),
            language_code=provider_config.get("language_code", "en"),
            sample_rate=config.get("sample_rate", 16000),
        )

    elif service == "openai":
        return OpenAITranscriber(
            api_key=api_key,
            model=provider_config.get("model", "gpt-4o-transcribe"),
            language=provider_config.get("language", "en"),
            sample_rate=config.get("sample_rate", 16000),
            channels=config.get("channels", 1),
            silence_duration_ms=provider_config.get("silence_duration_ms", 1000),
            vad_threshold=provider_config.get("vad_threshold", 0.5),
        )

    # This shouldn't be reached due to the check above, but kept for safety
    raise ValueError(f"Unhandled transcription service: {service}")


def get_available_providers() -> list[str]:
    """Get list of available transcription provider names.

    Returns:
        List of provider name strings
    """
    return list(PROVIDERS.keys())


def register_provider(name: str, provider_class: Type[BaseTranscriber]) -> None:
    """Register a custom transcription provider.

    Args:
        name: Name to register the provider under
        provider_class: Class that implements BaseTranscriber
    """
    if not issubclass(provider_class, BaseTranscriber):
        raise TypeError(
            f"Provider class must inherit from BaseTranscriber, "
            f"got {provider_class.__name__}"
        )

    PROVIDERS[name.lower()] = provider_class
    _logger.info(f"Registered transcription provider: {name}")
