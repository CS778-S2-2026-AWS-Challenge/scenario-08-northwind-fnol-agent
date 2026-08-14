1，
output：
tests/test_claim_creation_journey.py::test_at01_natural_intake_confirms_then_creates_mock_claim PASSED [ 33%]
tests/test_claim_creation_journey.py::test_claim_creation_rejects_a_stale_working_claim_revision PASSED [ 66%]
tests/test_claim_creation_journey.py::test_pending_later_evidence_does_not_block_controlled_claim_creation PASSED [100%]

- 输入：
  用户输入：
  “Another car hit the rear of mine at Queen Street and damaged the rear bumper.”
  用户确认系统提取的事故描述、地点和损失信息，然后创建 claim。

- 响应：
  系统要求用户确认结构化信息；确认后创建 mock claim，
  返回 claim number、route、next step 和 expected timing。

- 状态变化：
  proposed fields → confirmed fields → created claim。

- 结果：
  PASS。
  自动测试证据：
  `test_at01_natural_intake_confirms_then_creates_mock_claim PASSED`

- 缺陷：
  None。

  2，

  output：
tests/test_workbench_api py::test_staff_reads_complete_claim_detail_from_shared_state PASSED [ 11%]
tests/test_workbench_api.py::test_staff_lists_claims_for_workbench_queue PASSED    [ 22%]
tests/test_workbench_api.py::test_workbench_claim_list_rejects_claimant_credentials PASSED [ 33%]
tests/test_workbench_api.py::test_created_claim_route_does_not_override_workbench_queue PASSED [ 44%]
tests/test_workbench_api.py::test_workbench_claim_detail_returns_documented_not_found PASSED [ 55%]
tests/test_workbench_api.py::test_workbench_rejects_claimant_and_invalid_credentials PASSED [ 66%]
tests/test_workbench_api.py::test_claimant_projections_do_not_expose_workbench_only_data PASSED [ 77%]
tests/test_workbench_api.py::test_staff_receives_complete_handoff_packet_while_claimant_projection_is_safe PASSED [ 88%]
tests/test_workbench_api.py::test_workbench_detail_reads_shared_claim_creation_and_routing_results PASSED [100%]

- 输入：
  使用一个进入 professional review 的 claim，并由 staff 打开 employee workbench 查看 claim detail。

- 响应：
  Staff 可以看到共享 claim 状态、结构化表单、证据、pending items、
  review signal、内部消息、handoff packet 和下一步。
  Claimant 只能看到安全的进度更新，不能看到内部 signal、staff actions 或内部消息。

- 状态变化：
  claim 被放入 `professional_review` workbench queue；
  staff 的操作和 handoff 内容写回同一份 shared claim state。

- 结果：
  PASS。

- 自动测试证据：
  - `test_staff_reads_complete_claim_detail_from_shared_state PASSED`
  - `test_staff_lists_claims_for_workbench_queue PASSED`
  - `test_staff_receives_complete_handoff_packet_while_claimant_projection_is_safe PASSED`
  - `test_claimant_projections_do_not_expose_workbench_only_data PASSED`

- 缺陷：
  None。

Q3，
