"""Intentional >1 s tests; never use this list to permit a real sleep."""

SLOW_TEST_ALLOWLIST = {
    "tests.test_storage_cleanup_gaps.CleanupGapsTest."
    "test_3000_retained_mirrors_do_not_spawn_git_per_attachment":
        "Real 3,000 mirror directories and attachment rows benchmark metadata classification; no waits.",
    "tests.test_storage_cleanup_gaps.CleanupGapsTest.test_large_orphan_recovery_has_all_files_and_deletions":
        "Real Git snapshots 2,100 deletions and 2,100 new files, past the 2,000-path preview limit.",
    "tests.test_db_concurrency.ConcurrentAccessTest.test_every_concurrent_insert_is_counted_once":
        "Real thread scheduling and 1,000 concurrent SQLite writes are the behavior under test.",
    "tests.test_db_concurrency.ConcurrentAccessTest.test_reads_stay_intact_while_other_threads_write":
        "Real thread scheduling with six readers and four writers is the behavior under test.",
    "tests.test_delivery_proof_conformance.DeliveryProofConformanceTest."
    "test_each_bundled_adapter_declares_a_tested_delivery_proof":
        "This conformance meta-test executes every bundled adapter's delivery-proof regression.",
    "tests.test_retirement_auxiliary.RetirementAuxiliaryTest."
    "test_repeated_retirement_reassesses_paths_without_accumulating_exemptions":
        "Repeated real Git worktree and repository lifecycle operations are the behavior under test.",
    "tests.test_review_worktrees.ReviewWorktreesTest.test_cli_create_list_prune":
        "The CLI integration test creates, lists, and prunes real Git worktrees.",
    "tests.test_retirement_force.ForcedRetirementTest.test_goal_and_recursion_require_explicit_flags":
        "Multiple force requests inspect, snapshot, and remove real nested Git worktrees.",
    "tests.test_retirement_force.ForcedRetirementTest.test_recursive_order_and_late_failure_preserve_parent":
        "Real nested Git worktree removal and failure recovery are the behavior under test.",
    "tests.test_retirement_nested.NestedWorktreeTest.test_task_teardown_can_remove_nested_workspace_before_outer_worktree":
        "Real nested Git worktree teardown and registration pruning are the behavior under test.",
    "tests.test_compaction_events.CompactionEventsTest.test_importing_the_server_never_cycles_on_the_capability":
        "Two fresh interpreters import the real server in both orders to prove there is no cycle.",
    "tests.test_mcp_attach.McpConfigFileTests.test_generated_helper_loads_service_package_from_any_cwd":
        "Three fresh MCP subprocesses initialize from different working directories.",
    "tests.test_prereview.PrereviewTest.test_a_large_commit_and_a_chatty_table_stay_fast":
        "A real Git fast-import creates 20,000 files before the prereview check reads them.",
    "tests.test_retirement_auxiliary.RetirementAuxiliaryTest.test_failed_snapshot_creates_no_sweep_exemptions":
        "Real auxiliary Git worktrees are created before the injected snapshot failure.",
    "tests.test_retirement_nested.NestedRetirementGuardTest.test_interrupted_nested_removal_keeps_both_registrations_for_retry":
        "Interrupted real nested Git worktree removal preserves both registrations for retry.",
}
