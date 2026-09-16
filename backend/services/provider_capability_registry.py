"""Provider-specific capability contracts used before request transport."""

from backend.domain.agent_context_runtime import ProviderCapability, RequestProfile
from backend.domain.configuration import ModelRuntimeConfiguration


def provider_capability(configuration: ModelRuntimeConfiguration) -> ProviderCapability:
    media_types = ['text/plain']
    if configuration.image_input:
        media_types.append('image/*')
    if configuration.document_input:
        media_types.append('application/pdf')
    if configuration.protocol == 'bedrock_converse':
        return ProviderCapability(
            capability_version=f'{configuration.profile_id}@v1',
            protocol=configuration.protocol,
            structured_output_method='forced_tool',
            tool_call_support=configuration.tools,
            # Business-tool plus forced-output continuation has not been
            # qualified for the current Bedrock adapter. Fail closed.
            tool_result_continuation=None,
            supported_media_types=media_types,
            prompt_cache_type='none',
            cache_usage_fields=['cacheReadInputTokens', 'cacheWriteInputTokens'],
            continuation_mechanism=None,
        )
    return ProviderCapability(
        capability_version=f'{configuration.profile_id}@v1',
        protocol=configuration.protocol,
        structured_output_method='json_schema',
        tool_call_support=configuration.tools,
        tool_result_continuation=('assistant_tool_message' if configuration.tools else None),
        supported_media_types=media_types,
        prompt_cache_type='implicit',
        minimum_cache_tokens=1024,
        maximum_cache_points=1,
        cache_usage_fields=[
            'prompt_tokens_details.cached_tokens',
            'cache_read_input_tokens',
            'cache_write_input_tokens',
        ],
        continuation_mechanism='chat_completion_tool_message',
    )


def validate_profile_compatibility(
    profile: RequestProfile,
    capability: ProviderCapability,
) -> None:
    if profile.tool_names and not capability.tool_call_support:
        raise ValueError('The provider does not support the selected profile tool manifest.')
    if profile.requires_tool_continuation and capability.tool_result_continuation is None:
        raise ValueError('The provider does not support the selected profile continuation.')
    if profile.requires_media_types and not set(profile.requires_media_types).intersection(
        capability.supported_media_types
    ):
        raise ValueError('The provider does not support the selected profile media contract.')


def validate_capability_binding(
    configuration: ModelRuntimeConfiguration,
    capability: ProviderCapability,
) -> None:
    """Verify published fields that must match executable adapter capabilities.

    Args:
        configuration: The selected executable model binding.
        capability: The capability record published in the active Release Set.

    Raises:
        ValueError: If the publication claims transport behavior the adapter cannot execute.
    """

    expected = provider_capability(configuration)
    if any(
        (
            capability.protocol != expected.protocol,
            capability.structured_output_method != expected.structured_output_method,
            capability.tool_call_support is not expected.tool_call_support,
            capability.tool_result_continuation != expected.tool_result_continuation,
            capability.supported_media_types != expected.supported_media_types,
            capability.prompt_cache_type != expected.prompt_cache_type,
            capability.continuation_mechanism != expected.continuation_mechanism,
        )
    ):
        raise ValueError('The published provider capability does not match the model binding.')
