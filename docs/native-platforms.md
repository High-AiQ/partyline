# One startup command, platform-specific protection

## Product contract

The target is `uv run partyline` from a normal terminal on Linux, macOS, and native
Windows PowerShell/CMD. Starting a foreground instance must not require the user to
install a service or write a memory-limit configuration file. Attached CLIs remain
real interactive terminal processes; their speech still comes from structured
transcripts. Memory protection must not silently disable the write fence.

Native Windows uses ConPTY for real interactive terminals, restricted tokens and
filesystem ACLs for protected paths, and Job Objects for memory limits. It needs
Windows 10 build 17763 or newer, Python 3.11+, Git, and uv. Run the usual
`uv run partyline` in PowerShell or CMD; no WSL, service installation, elevation,
or Developer Mode is required. Install each vendor CLI separately and sign in
before attaching it. Vendor availability on Windows still varies.

Use local drives that support persistent ACLs (normally NTFS). Network shares,
mapped network drives, and permission paths through junctions are refused.
Standard npm command shims resolve to Node and the installed script, preserving
literal arguments. Custom batch scripts need an explicit interpreter.

Native CI exercises console input/output, Unicode, resizing, descendant cleanup,
memory enforcement, restricted Git commits, protected-file deletion refusal,
credential-file permissions, shell quoting, and startup. These are fixture
programs, not authenticated turns from every vendor CLI.

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

## Windows permission scope

Each attachment receives a fresh synthetic security identity. Partyline adds
permission entries for that identity, verifies the restricted token against the
protected files and their ancestors, then launches the console suspended and
assigns its memory job before resuming it. The real user's existing permissions
remain intact. Cleanup removes the added entries after the child tree stops.
Abrupt termination can leave inert entries; identities are never reused.

Windows also restricts reads. Partyline grants access to the CLI runtime, its
known state directories, Git configuration, and the attachment's private
connection file. Additional private paths may need an approved grant. Existing
public Windows permissions still apply outside the protected set; this is not
an absolute allowlist of every writable path on the computer. See
[the write fence](write-fence.md) for Git behavior and limitations.

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

The Linux launch path automatically creates foreground scopes and disables
systemd argument expansion. The platform caps do not establish one aggregate
memory budget across all attachments.
