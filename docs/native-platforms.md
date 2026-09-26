# One startup command, platform-specific protection

## Product contract

The target is `uv run partyline` from a normal terminal on Linux, macOS, and native
Windows PowerShell/CMD. Starting a foreground instance must not require the user to
install a service or write a memory-limit configuration file. Attached CLIs remain
real interactive terminal processes; their speech still comes from structured
transcripts. Memory protection must not silently disable the write fence.

This is a platform plan, not a claim of native Windows support today. The current
terminal runtime imports `fcntl` and `termios`, uses `os.openpty` and Unix process
groups, and ships no Windows write-fence backend. Database ownership locks now use
Windows byte-range locks or Unix `flock`. The native Windows CI foundation runs
those database tests under a verified Job Object memory cap; this does not yet
make the interactive application runnable on Windows.

## Memory architecture

Keep startup, memory enforcement, terminal I/O, and filesystem protection behind
separate platform interfaces. A memory backend must establish its limit before
running the CLI, read back the effective settings, and report what it protects:
one process or the whole process tree. Missing enforcement must be an actionable
failure, not an unlimited fallback or a successful check against another instance.

| Platform | Foreground startup and memory | Terminal |
| --- | --- | --- |
| Linux | Automatically create a transient user scope for the server and a separate scope for each CLI; verify the cgroup's actual limit. An installed service keeps its existing unit guard. | Unix PTY |
| macOS | Use native per-process resource limits; verify enforcement on supported macOS versions. Do not describe an address-space limit as a combined resident-memory budget for a tree. | Unix PTY |
| Native Windows | Create a Job Object per attachment and a separate job for the server. Configure committed-memory limits and job cleanup before resuming the child. Read the limits back with the job query API. | ConPTY |

Windows Job Objects can limit the combined committed memory of their processes.
Create children suspended, assign them to their job, verify configuration, then
resume them. Disable breakaway so descendants remain counted; close/terminate the
attachment job on detach. Assignment failure must stop the child before execution.
See Microsoft's [Job Objects documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
and [memory limit flags](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information).

ConPTY provides an actual interactive Windows console session. Its input and output
channels require appropriate concurrent draining and bounded shutdown; it must not
be replaced with a subprocess pipe pretending to be a terminal. See Microsoft's
[ConPTY session lifecycle](https://learn.microsoft.com/en-us/windows/console/creating-a-pseudoconsole-session).

Apple's current [resource-limit implementation](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_resource.c)
passes `RLIMIT_AS` to its VM subsystem. A real Mac test must still prove the bound,
inheritance and CLI compatibility. JavaScript runtimes can reserve much more virtual
address space than resident memory, so the existing 4G address-space setting must
not be assumed equivalent to Linux's cgroup memory accounting.

An additional aggregate budget is needed if the goal includes bounding the sum of
many simultaneous attachments. Separate 4 GiB caps alone do not prevent many CLIs
collectively exhausting host RAM. Linux can use a shared parent slice and Windows a
parent job. macOS needs its own design and honest accounting of any monitoring delay;
polling RSS is not an equivalent hard kernel cap.

## Native Windows release blockers

1. Introduce a terminal interface for start, resize, write, drain, wait, interrupt,
   and stop; implement ConPTY and remove unconditional Unix imports.
2. Add Job Object memory enforcement, including descendant accounting and cleanup
   when the server exits unexpectedly. Keep the server outside attachment jobs.
3. Replace Unix-only database locking and audit path, signal, executable and adapter
   assumptions. Preserve the single-owner database lock and transcript claims.
4. Implement and verify a Windows write-fence backend. A Job Object limits resources;
   it does not implement the repository/database write protection. Determine a
   Windows mechanism that can express the existing grants without changing users'
   repository ACLs globally. If that requires extra installation or privileges,
   document the product tradeoff before selecting it. Do not ship an unfenced default.
5. Run native Windows and macOS CI and interactive smoke checks before expanding the
   README's supported-platform claim. Mocked `sys.platform` tests cannot establish
   native support.

## Acceptance checks

- On each supported OS, a clean checkout starts through `uv run partyline`, preserves
  CLI options, environment, cwd and terminal behavior, and stops cleanly with Ctrl-C.
- A tiny bounded memory fixture proves enforcement and child inheritance under an
  outer safety cap. A sibling CLI and the server remain alive when one hits its cap.
- Inspect the launched process's effective limit; reject unavailable controllers,
  unlimited values, failed job assignment and inherited flags used to bypass setup.
- Prove repository/database write refusal and allowed worktree writes on that OS.
- Exercise literal dollar signs, paths with spaces, console resize, interrupts,
  transcript delivery, server exit, and attachment teardown.

The immediate Linux repair supplies automatic foreground scopes and fixes the
systemd argument-expansion regression. It does not complete the Windows port or
claim an aggregate memory budget across all platforms.
