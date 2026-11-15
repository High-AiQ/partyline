"""Every review notice scopes repository test commands to the changed code."""

SCOPED_REVIEW_TESTS = (
    'Run only tests reaching changed code: scope the configured test command to those tests. '
    'Never run full suites, e2e suites or whole-suite coverage. '
    'List the test commands run and their results in verdict findings. '
    'Call env_gap only when affected tests cannot run; full-suite evidence is not required. ')
