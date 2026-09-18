"""Stable logical cache segmentation for v7 requests."""

import hashlib
import json

from backend.domain.agent_context_runtime import (
    CachePlan,
    CacheSegment,
    ContextPlan,
    RequestProfile,
)
from backend.domain.prompt_pack import PromptBundle


def build_cache_plan(
    *,
    release_set_id: str,
    model_profile_id: str,
    claim_revision: int,
    principal_scope: str,
    bundle: PromptBundle,
    request_profile: RequestProfile,
    schema_id: str,
    schema: dict[str, object],
    tools: list[dict[str, object]],
    context_plan: ContextPlan,
    layout_version: str = 'northwind-cache-layout-v1',
) -> CachePlan:
    static_tokens = bundle.estimated_tokens
    family_task_tokens = sum(
        item.estimated_tokens
        for item in bundle.fragment_refs
        if item.fragment_id.startswith(('family.', 'task.', 'capability.'))
    )
    tool_manifest_id = f'{request_profile.profile_id}:{request_profile.version}:' + (
        ','.join(request_profile.tool_names) if request_profile.tool_names else 'none'
    )
    fingerprint_payload = {
        'layout_version': layout_version,
        'prompt_pack_version': bundle.prompt_pack_version,
        'fragment_refs': [f'{item.fragment_id}@{item.version}' for item in bundle.fragment_refs],
        'schema_id': schema_id,
        'schema': schema,
        'tool_manifest_id': tool_manifest_id,
        'tools': tools,
    }
    prefix_fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, separators=(',', ':'), sort_keys=True).encode('utf-8')
    ).hexdigest()
    return CachePlan(
        layout_version=layout_version,
        prefix_fingerprint=prefix_fingerprint,
        tool_manifest_id=tool_manifest_id,
        segments=[
            CacheSegment(
                segment_id='static-contract',
                cache_key=(
                    f'{release_set_id}:{model_profile_id}:{bundle.prompt_pack_version}:{schema_id}'
                ),
                estimated_tokens=max(0, static_tokens - family_task_tokens),
                checkpoint=True,
            ),
            CacheSegment(
                segment_id='route-contract',
                cache_key=f'{release_set_id}:{model_profile_id}:{bundle.prompt_bundle_id}',
                estimated_tokens=family_task_tokens,
                checkpoint=True,
            ),
            CacheSegment(
                segment_id='dynamic-context',
                cache_key=f'{principal_scope}:revision:{claim_revision}',
                estimated_tokens=context_plan.estimated_tokens,
                checkpoint=False,
            ),
        ],
    )
