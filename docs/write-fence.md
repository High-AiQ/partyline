# The write fence

Every attached process runs inside a platform kernel sandbox. All
repositories known to Partyline and Partyline's database are protected
from writes by default. A line's own worktree and git needs are reopened
on top; access outside the protected set follows the platform rules below. The fence is the
enforcement below the text brief: the kernel decides where writes land.

| DO | DO NOT |
| --- | --- |
| Wrap at the one spawn point (`adapters.base.Adapter.start`) so no adapter can forget it | Wrap per adapter, or leave one spawn path unwrapped |
| Fail closed: backend missing or unable to run, no process — a 409 naming the reason and person-side install remedy | Fall back to an unconfined launch, ever |
| Ship a backend for every supported platform | Fail closed without naming the install remedy |
| Push over HTTPS with gh credentials or `ssh -F /dev/null` from a fenced process | Expect the system ssh config to be readable inside the fence |
| Treat the fence as the line's real sandbox | Assume the CLI's own sandbox also applies under the fence |
| Protect every active managed repository and the Partyline database by default | Assume an unknown repository is protected before Partyline has recorded a line there |
| Grant extra write scope only by person or captain-above decision, recorded on the line | Let a line widen its own write scope, or widen it because a brief asked nicely |
| Keep the wrap to filesystem writes: mounts on Linux, a profile on Darwin, nothing else added | Unshare the network, pid namespace, or environment — this is a filesystem fence, not a jail |
| Bind or allow a path only if it exists | Bind or allow a path that does not exist "so it will work later" |

## Platforms

`fence.launch_argv` picks the backend by `sys.platform` and refuses to
spawn when the chosen one cannot run (`fence.backend_available()` returns
a human-readable reason; startup preflight and the attach 409 include the
same platform-specific person-side install remedy).

- **Linux — bubblewrap.** A mount namespace starts with `/` bound
  writable, `/dev` passed through with `--dev-bind`, and `/proc` mounted.
  The host's `/tmp` remains writable. Partyline then binds protected repository
  roots read-only, reopens this line's worktree and required Git paths
  writable, binds the database and its sidecars read-only, and applies
  recorded grants last. Bind order matters: the last mount at a path wins.
- **Darwin — `/usr/bin/sandbox-exec`.** macOS has no bubblewrap and no
  mount namespace a process may create, so the fence generates an SBPL
  profile (Apple's documented sandbox profile language) and passes it
  with `-p`: `(allow default)`, scoped denies under protected roots and
  the database, then allows this line's own worktree, Git paths, and
  grants back in. A child worktree also allows writes under the common
  `.git` root so Git's transient root files work; later, more-specific
  denies keep `config`, `hooks`, `description`, `HEAD`, `info`, `branches`,
  and sibling worktree metadata protected, with only this line's metadata
  reopened. It also allows `/private/tmp`
  and the process `TMPDIR` in both spellings, and the
  devices a CLI needs to write — `/dev/null`, `/dev/tty`, `/dev/console`,
  and the `/dev/ttysNNN` pty slaves. Availability is checked the same
  way as bubblewrap's: no `sandbox-exec`, no process.

- **Windows — restricted tokens and ACLs.** Requires Windows 10 build 17763+
  and local drives with persistent ACLs. Each attachment gets a unique synthetic
  SID with grants for its worktree, Git metadata, private temporary directory,
  CLI state, and approved paths. Explicit denies protect repository files,
  database files, and deletion through their ancestors. The restricted token is
  checked before the real ConPTY process starts. Existing user permissions stay
  intact; cleanup removes only this attachment's entries. Crashes can leave
  inert entries whose identity is never reused. Network drives and junctions in
  permission paths are refused. Additional private host paths may be unreadable
  until granted. Public Windows permissions outside protected roots still apply.

Known limits of the Darwin backend, documented rather than hidden: the
profile is visible in `ps` (so is the bubblewrap argv — this is a fence
against accidents, not a jail against malice); `/tmp` remains shared with
the host and writable; and `sandbox-exec` is formally
deprecated by Apple while remaining the documented interface available
on every macOS this code runs on.

## The wrap

`partyline/fence.py` builds the plan and explicitly creates the user namespace. On Linux:

```
bwrap --bind / / --dev-bind /dev /dev --proc /proc --unshare-user
      --ro-bind <protected repository> <same path> ...
      --bind <line worktree> <same path> ...
      --ro-bind <database or sidecar> <same path> ...
      --bind <granted path> <same path> ... --die-with-parent -- <command>
```

On Darwin:

```
sandbox-exec -p <generated profile> <command>
```

The environment, working directory, process group, and network are kept.
On Linux and macOS, reads are not fenced: a process can still read the host.
Windows restricted tokens also constrain reads; see its platform notes below. The fence bounds
**writes**, and it is not a security boundary against a hostile binary —
it is a fence against accidents, not a jail against malice. See
`docs/security.md` for the trust model.

On Linux, the server wraps every launch in a separate transient systemd scope
before entering bubblewrap, even when the filesystem fence is disabled.
The per-process memory budget defaults to `4G` and can be changed with
`PARTYLINE_PROCESS_MEMORY_LIMIT`. The budget is advisory — the memory sampler
warns as a process nears and passes it — and the scope's `MemoryMax` is an
emergency backstop above it (1.5× or +1 GiB, within 3/4 of host RAM; see
`docs/resource-budget.md`); swap is disabled. A verifier runs inside the scope
and refuses to start the CLI unless it sees a finite `memory.max` at or below
the backstop. The boot preflight runs a harmless read-only
probe inside a transient scope and checks `memory.max`; if the user manager
ignores the property, startup logs the failure and attachment starts fail
closed. Darwin applies the same configurable bound with inherited `RLIMIT_AS`,
since it has no systemd cgroups.

`uv run partyline` automatically creates a temporary systemd user scope on Linux,
preserving the foreground terminal, environment, and working directory. No service
file is required. Its server cap defaults to the smaller of 2 GiB and 5/8 of host
RAM; `PARTYLINE_SERVER_MEMORY_LIMIT` overrides it. Startup verifies `memory.max`
and `memory.oom.group=0` inside that scope. Each attached CLI has its own separate
scope, so its allocations do not consume the server's cap. These are individual
caps; Partyline also applies a portable host-wide admission budget based on declared
leases (see [fleet resource budget](resource-budget.md)). Linux needs cgroup v2 and
a working systemd user manager (systemd 254 or newer); an unavailable cap causes
startup to fail closed.

On Windows the foreground server has a verified Job Object cap with the same
2 GiB/host-memory default. Each attachment gets a separate 4 GiB job, counting
committed memory across its descendants. The child starts suspended and cannot
execute before assignment succeeds. Ordinary server helpers remain in the server
job; only explicitly managed attachments leave it. Detaching or closing an
attachment kills its whole job. Neither WSL nor a service is required.

For installed Partyline services, boot and `partyline doctor` still check
`OOMPolicy=continue` and a finite `MemoryMax` below host RAM. Unsafe service
settings produce the drop-in remedy documented in
[Restarting the running instance](restart.md#install-the-service-oom-guard).
macOS uses its existing per-process address-space limits and does not require
systemd. Windows uses ConPTY, restricted tokens, and Job Objects; see
[native platform support](native-platforms.md).

## Docker access

Inside the fence's user namespace the Docker socket's group is unmapped
(unprivileged bubblewrap maps only our own uid and gid), so every connect from a
fenced process fails with `EACCES`, and no bind can fix that. Docker access is
therefore **relayed**: a write-set grant whose path resolves to the host socket
(`/run/docker.sock`, `/var/run/docker.sock`, or the `unix://` path of `DOCKER_HOST`)
is accepted as a *docker access* grant instead of refused, and the server, which runs
outside the fence and holds the group, copies bytes between a per-line socket and
the host socket.

**Unrestricted access is root-equivalent access to the host; the default, managed access,
is a constrained policy proxy (see Managed Docker access).** Only a person may approve either; an
ancestor captain cannot, even if it holds the grant itself. The grant is an ordinary
row in the line's write set.

At spawn a granted line gets `DOCKER_HOST=unix://~/.partyline/docker/<conv_id>/docker.sock`.
The relay is started lazily then (directory `0700`, socket `0600`, our uid, which is
mapped inside the fence) and stopped when the line is archived. While any live line
on the host holds a docker grant (decided from the grant rows, not the directory),
every process gets `--tmpfs ~/.partyline/docker`; a granted line binds back only its
own `<conv_id>` directory, so no other line can reach a relay. With no docker grant
anywhere the fence argv is unchanged. Because a process started before the grant
lacks that mount, approving a docker grant resumes **every** live process on the
host, not just the granted line's. A relay never outlives a restart of the server:
the next spawn recreates it. When the server lacks the docker group (a systemd user manager keeps the groups it
had at login), the relay falls back to a **bridge**: the server starts
`python -m partyline.docker_bridge` under `sg docker`, which lets a member of the
group run a command with it and needs no password. The bridge listens on
`~/.partyline/docker-bridge/bridge.sock` (directory `0700`, socket `0600`, our uid) and
copies bytes to the host socket; while it lives every relay routes through it. It
exits when the server does, is restarted if it dies, and is abandoned after three
failed starts in five minutes (the relay's 502 then carries the bridge's stderr).
Fenced processes cannot reach it: while any docker grant exists the fence mounts a
`--tmpfs` over `~/.partyline/docker-bridge` and binds nothing back. `GET
/api/docker-relay` reports `bridge: {running, pid, last_error}`.

If the server process itself cannot open the host socket (it needs the docker
group, and a systemd user manager keeps the groups it had at login), the relay
answers a client with `502 Bad Gateway` and the reason, logs the errno, and posts
a notice on the line when it starts. `GET /api/docker-relay` (a person, or a
line's captain for its own line) lists each relay's socket, whether it is
listening, open connections, the last upstream error, and a live probe. Starting
a relay twice reuses the one listener. Revoking a grant has no route yet; archive
the line to stop its relay.

### Managed Docker access (the default)

A docker grant has a mode, stored on the grant row (`docker_mode`, default `managed`,
existing grants included). Only a person chooses `unrestricted`: in the approval dialog
(*approve unrestricted*), through `POST …/write-set/request/<id>/approve {"docker_mode":
"unrestricted"}`, or by granting directly with `{"docker_mode": …}`. A process cannot.
Changing a grant's mode closes the line's open relay connections, so no connection outlives
the policy it was made under.

**The managed relay is a default-deny policy proxy** (`docker_proxy.py`, `docker_plan.py`,
`docker_body.py`, `docker_policy.py`). It parses each request strictly with h11 and
rebuilds it from the parsed parts, so what was checked is what the daemon receives. It
never forwards the client's bytes or JSON: a body is parsed, every object must have keys
that are distinct once lowercased (Docker's decoder matches keys without regard to case),
and a *fresh* body is built from allowlists of known fields, emitted under their canonical
names. A field not on the list is refused, so a field Docker adds later is closed until
someone decides it is safe. Anything it cannot parse (bad framing, `Content-Length` with
`Transfer-Encoding`, an unknown HTTP version) closes the connection; a head and body must
arrive within 30 s, a body is capped at 1 MB (image builds stream, capped at 4 GB), and a
line may hold 64 connections. It serves one request per connection and answers
`Connection: close`; the docker CLI and SDKs reconnect, and a request pipelined behind
the first is never forwarded. Container names and short ids resolve through the daemon to
the full id, and the forwarded path carries that id.

**Ownership is the line's tree.** A managed container belongs to its creator's top-level
line (label `partyline.tree`); any line under that line may list, inspect, start, stop,
exec in, log and remove it. Other trees get `not-owned`. Listing, `ps`, events and stop use
the same scope: the proxy forces a `partyline.tree=<root>` label filter that a client
filter can only narrow.

| Allowed | Condition |
| --- | --- |
| `_ping`, `version`, `info`, image list and inspect, `volumes` list, `system/df` | none |
| image pull (`fromImage`, `tag`, `platform`) | none (`fromSrc` import is refused) |
| `events`, container list (`ps`, with filters) | narrowed to the line's tree |
| inspect, logs, stats, wait, top, stop, kill, remove, exec create | container in the tree |
| start, restart | in the tree, **managed**, limits present, passes admission |
| attach, exec start (with stdin), resize | in the tree; a raw pump after the daemon's `101` |
| create | declares its limits (below) |
| `volumes/create` | `local` driver, no `DriverOpts` |
| `build` and the BuildKit `session`/`grpc` upgrades | no host network, no remote context |

Everything else, including `containers/<id>/update`, rename, prune, networks, volume
removal and image removal, is refused. Query parameters are allowlisted per call.
A hijacking call (attach, exec start, `session`) becomes a raw pump only when the daemon
itself answers `101` (or a `200` raw stream); any other answer is relayed and the
connection ends, so a refused upgrade never leaves a raw line to the daemon.

**Create must declare** (one refusal names every gap):

- `HostConfig.Memory` > 0 and `MemorySwap` equal to it (no swap), because a container with
  no cap is what the daemon work in finding 5.14 escaped through;
- a CPU limit (`NanoCpus` or `CpuQuota` > 0) and `PidsLimit` > 0;
- the label `partyline.max-seconds` (maximum lifetime, seconds), at most the host cap
  (setting `docker_max_seconds_cap`, default 24 h);
- the label `partyline.gpu-mem-mb` (VRAM need, MB) whenever it has GPU `DeviceRequests`.

Create is checked for limits but not against the budget: a created container is not
running and uses nothing.

**Create refuses**: `Privileged`; `CapAdd`; `NetworkMode`, `PidMode`, `IpcMode`, `UTSMode`,
`UsernsMode` or `CgroupnsMode` of `host` or `container:…`; `Devices` and `DeviceCgroupRules`
(only GPU `DeviceRequests` are allowed); `VolumesFrom`; `CgroupParent`; `Cgroup`; `Links`;
`Sysctls`; `StorageOpt`; `OomKillDisable`; masked or read-only path overrides; any
`SecurityOpt` but `no-new-privileges`; any `Runtime` but `runc`; a `RestartPolicy` other
than absent or `no`; any `VolumeDriver` but the default, and mount `DriverConfig`; bind or
mount sources that expose the Docker socket (or a directory that contains it, such as `/run`),
lie outside the line's worktrees (its attachments' working directories) and approved
write-set paths, or pass through a symlink. The symlink rule is checked at create and again
immediately before a start is forwarded; a path swapped for a link between that check and the
daemon's own mount remains a narrow race, so keep binds to directories only the line writes,
or use named volumes. `NVIDIA_*` and `CUDA_VISIBLE_DEVICES` in the request's own `Env` are
refused unless the container uses `DeviceRequests`; the image's baked-in environment is not
judged. If the daemon's default runtime is not `runc` (read from `/info`, cached 60 s), every
non-GPU create is refused (`default-runtime`) rather than guessing. Each of these would let a
container leave its limits or the fence.

The proxy sets `partyline.conversation=<line>`, `partyline.tree=<root>`,
`partyline.managed=1` and `partyline.attachment` itself, overriding anything the client
sent (the attachment label keeps the client's value only if it names an attachment of
this line, else it is the line's captain).

**Start and restart re-inspect** the container: it must be in the tree, carry
`partyline.managed=1`, still satisfy the limits and refusals above, and pass admission,
else `403 … recreate it through the managed path`. That is how containers created before
this existed (`Memory=0`) are refused. A start takes no body.

**Admission counts running containers only.** On a start, the CLI memory reservations, plus
the caps of every managed container running at that moment (read live from the daemon, plus
starts admitted but not yet running), plus this cap, must fit the host budget in
`resource_budget`; otherwise `409 budget-exceeded` with the numbers. The admission lock is
held for the decision and for recording the slot, never while the request is forwarded.

**GPU.** Only one managed GPU container runs at a time (setting `docker_gpu_slots`, default 1;
`PUT /api/docker-gpu {"slots": n}`, a person). Before a GPU start, `nvidia-smi
--query-gpu=memory.free` runs (10 s timeout, result cached 5 s); the start is admitted only
if it succeeds and the declared VRAM fits. A failure, a timeout or a missing `nvidia-smi`
marks the GPU **unhealthy**: GPU starts get `409 gpu-unhealthy`, and the line and its root
line are told once. Only a person clears it, with `POST /api/docker-gpu/clear`; nothing resets
the GPU automatically. `GET /api/docker-gpu` shows the state. The slot frees as soon as the
daemon reports the container stopped.

**Lifetime.** The inventory stops a managed container that has run longer than its
`partyline.max-seconds` (capped as above), counted from its last start, and tells its line.
It stops, never removes, so outputs survive. A stop can land in the middle of a job: declare
a generous lifetime, and treat a vanished container as an interrupted job.

**Builds** (`POST /build`, BuildKit `session`) are allowed because images have to come from
somewhere, but a build's steps run outside every memory budget; keep them off while heavy
GPU work runs. `networkmode=host`, `container:…` and `remote` contexts are refused.

**Refusal format.** Every refusal is `{"message": "refused: <rule-name>: <detail>", "rules":
[...]}`: policy refusals are `403`, admission refusals `409`, malformed bodies `400`, an
oversized body `413`, the connection cap `429`. The rule name is stable and kebab-case, so
a client can act on it; `rules` lists every rule a request hit (the message leads with the
first, and tags the others). Rules:

`endpoint-not-allowed`, `update-refused`, `malformed-path`, `query-not-allowed`,
`malformed-body`, `body-too-large`, `not-owned`, `not-managed`, `limits-required`,
`lifetime-cap`, `restart-policy`, `privileged`, `host-namespace`, `runtime`, `default-runtime`,
`gpu-env`, `volume-driver`, `bind-source`, `forbidden-setting`, `field-not-allowed`,
`security-opt`, `device-request`, `mount-type`, `build-network`, `build-remote`,
`upgrade-required`, `connection-limit`, `budget-exceeded`, `gpu-busy`, `gpu-memory`,
`gpu-unhealthy`. (`update-refused`: limits cannot change in place, recreate the container;
`not-managed`: it was not created through this path; `gpu-env`: `NVIDIA_*` without
`DeviceRequests`; `field-not-allowed`: a field outside the allowlists.)

**For launchers.** A launcher talks to `DOCKER_HOST` as usual, but its create must declare
the limits above, or Docker work there stops working on purpose. A command that passes:

```
docker run -d --name my-gpu-worker \
  --memory 8g --memory-swap 8g --cpus 4 --pids-limit 512 \
  --label partyline.max-seconds=3600 \
  --gpus all --label partyline.gpu-mem-mb=9000 \
  -v models:/models my-image:tag
```

Drop `--gpus` and the VRAM label for CPU work. Use named volumes for data. `docker
compose`, networks and volume removal are not on the allowlist; use `docker run`/`create`,
or ask a person for an unrestricted grant. A limits change means recreating the container
(`docker rm`, then `docker run`).

**Unrestricted** mode keeps the old byte-forwarding relay: root-equivalent access to the
host, outside every budget and every rule above. Its approval text and dialog say so
plainly. The daemon can start any container, change any limit and mount anything, so
choose it only when you accept that.

### Docker workloads: outside CLI budgets

Containers belong to the host daemon, not to an attachment's cgroup, so no CLI memory
budget bounds them; a docker grant says so when it is requested. An *unrestricted* relay
is a byte forwarder and enforces nothing; the *managed* relay (the default, below) is a
policy proxy and does.

**Label contract.** A container a line starts carries `partyline.conversation=<conv id>`
and `partyline.attachment=<att id>`. A process with a docker grant finds both in
`PARTYLINE_DOCKER_LABELS` (space-separated `key=value` words) so a launcher can pass
`--label`/`labels:` itself. Unlabeled containers still show, as *unattributed*.

**Inventory.** While any docker grant exists the server lists the daemon's containers
(`/containers/json?all=1`), inspects running ones for `HostConfig.Memory` and takes a
one-shot stats reading, at most every 15 s (`docker_workloads.py`, in the memory sampler's
tick). `GET /api/docker-workloads` returns them with their line, `attribution` and
`uncapped` (a running container with `Memory=0`): a person sees all, a process only its
line's tree. The resource push and `ResourceIndicator` show a separate *Docker
workloads: outside CLI budgets* figure with the count of containers that have no RAM cap.
The sample runs in its own task with a 60 s timeout (a hung daemon cannot delay the memory
warnings), tolerates malformed replies, and keeps going after the last docker grant ends
for as long as labeled containers were running at the last look, since that is when
survivors matter. Labels are trustworthy only on managed lines, where the proxy sets
them; an *unrestricted* line can start containers with any labels, or none, and so can
spoof ownership. Stopping is limited to the lines the caller can see (its own, and for a
captain those under it).

**Survivors and stop.** When a detach or close leaves a line with no live process, a
notice lists that line's still-running labeled containers (once per set, per 10 minutes;
approval resumes and replaces do not post it). `POST /api/docker-workloads/{id}/stop`
stops a container by its hex id (never a name) when its `partyline.conversation` label
names the caller's line or one under it; a person may stop any. It stops, never removes,
so outputs and shared services survive.

## Memory failures and recovery

A process killed by the kernel cannot catch its own OOM. The Partyline host stays
outside the attachment's memory scope and records the failure. Linux attachment
scopes retain their failed state until the host reads `Result=oom-kill`, the limit,
and the peak when systemd provides it. A launcher's `-15` or `-9` exit alone is not
proof of OOM. On other platforms, or when the evidence is unavailable, the report
keeps the exit cause unconfirmed.

An unexpected nonzero exit (or a confirmed OOM) leaves a durable incident and a
notice on the process's line. Partyline privately wakes its nearest live captain:
the line's captain first, then the first available ancestor captain. A captain's
own failure goes upward. There is one incident per activation, no automatic
restart, and no escalation for a deliberate detach or a normal exit. With no live
captain, the line's notice and incident remain available to a person.

A transcript adapter that exits before it is ready (it never claimed a CLI session)
is a startup failure, not a memory event. Its incident carries `startup: true` and
`last_output`, the last 15 non-blank lines of the pty with ANSI stripped (the adapter
keeps a bounded ~4 KB tail; what is relayed is unchanged). The line notice reads
`⚠ @name exited during startup (code N): <last 3 lines>`, and the captain is woken
with advice to fix the cause and replace the process with a fresh one: resuming
cannot work, and the resume endpoint answers 409.

`GET /api/attachments/<id>/memory` returns the last incident, the saved override,
the effective limit for the next launch, and the host's maximum allowed override.
An authorized captain or person can change a **stopped** process with
`PUT /api/attachments/<id>/memory` and `{"limit":"6G"}`. Use `{"limit":null}` to
restore the host default, then use the existing resume action. A worker cannot
grant itself more memory. Overrides survive resume and fresh-session replacement.
The API ceiling is the smaller of `PARTYLINE_MAX_PROCESS_MEMORY_LIMIT` (default
`8G`) and 75% of host RAM. These caps do not reserve RAM or guarantee that the
combined workload fits; the captain still needs to consider other live processes.

First inspect the failed command and its error output. A failing assertion that
prints a huge object graph needs a bounded diagnostic, not more RAM. Run uncertain
tests under a smaller independent cap so the test can fail while the agent lives.
The early memory warning names the process's three largest descendants — pid,
RSS and a short command line — with each pid as the process itself sees it (the
last `NSpid` field), so the fix is targeted. Stop one with `kill <pid>`, or with
`POST /api/attachments/<id>/signal {"pid": N, "signal": "TERM"|"KILL"}`, which
the process itself or its line's captain may call and which refuses anything
that is not a strict descendant of that process. Never `pkill -f` or `killall`:
every attachment runs under one uid, so a pattern kill reaches other lines'
processes (two attachments exited -15 from one captain's cleanup on 2026-10-12).
A per-attachment PID namespace (`bwrap --unshare-pid`) would make that physically
impossible, and is deliberately not used: probed on 2026-10-12, `scripts/capped-test`
inside such a fence falls back from the cgroup `MemoryMax` scope (whole process tree)
to `RLIMIT_AS` (one process), so the flag would trade a cross-line kill risk for a
silently weaker test cap.

The repository's `scripts/capped-test` now uses the scope result to return 137 for
a confirmed OOM even when systemd's launcher was terminated with SIGTERM.

## The protected set and carve-outs


At spawn and resume, Partyline reads every non-archived conversation and
the cwd of each attachment on those lines. Each cwd inside a Git
repository contributes its canonical repository root to the protected
set; duplicate roots collapse. The database, runtime lock, and SQLite
sidecar paths are protected separately. A root captain whose cwd is the
repository root is exempt from that root's deny and keeps the person's
checkout writable. A child line's cwd is a worktree below the root, so
only that worktree is reopened. A repository that Partyline has not yet
recorded in an active line is writable until it is known to Partyline.
This follows from deriving the protected set from the database.

| path | writable | why |
| --- | --- | --- |
| a managed repository root | no | all active lines' Git roots are protected, except a root captain's own checkout |
| this line's cwd tree | yes | the line's own worktree is reopened above its protected repository root |
| the repository's `.review/` directory | yes | disposable review checkouts may be created after spawn; only the line's recorded review checkouts get writable Git metadata |
| git shared state (child lines) | partially | see the mirror below |
| Partyline's database, lock, and sidecars | no | attachment processes cannot alter Partyline state directly |
| granted paths (`conversation_write_grants`) | yes | requested, granted, recorded, and bound last |
| paths outside the protected set | platform-dependent | the protect list is intentionally derived from active Partyline lines |

For any line working in a repository, the whole canonical `<repo>/.review/`
directory is writable, including review checkout directories created after
the process starts. These checkouts are disposable: Partyline creates and
prunes them, and acceptance verifies the SHA object rather than the checkout.
This means sibling lines can write files in each other's review checkouts;
nothing under `.review/` is a source of truth.

Git metadata is narrower. At spawn and resume, Partyline loads review rows
for the owning conversation only. The fence checks each row's owner, full
SHA, canonical `<repo>/.review/<sha>` path, and repository identity before
binding that checkout's own Git metadata writable through `git_fence`.
The shared `.git/worktrees/` directory stays read-only. A checkout created
after spawn has no writable metadata bind, so a Git index refresh fails
softly; read-only commands such as `diff`, `log`, and `show` still work.

The host's `/tmp` remains writable inside the Linux mount namespace.
Temporary files created there use the host directory and are visible to
the host; use a repository worktree for files that need repository
protection.

## Git for a child line

A worktree's Git metadata lives in the parent repository's shared `.git`.
Binding it writable would let a line rewrite a sibling's branch, the repo
config, or its hooks. `partyline/git_fence.py` shares only what commits
need:

- `objects/` is shared and writable — content-addressed and immutable
  once written, and the commit a line hands its captain must exist in the
  real object store or the accept fast-forward cannot find it.
- `refs/`, `logs/`, and `packed-refs` are a **copy-on-write mirror** under
  `~/.partyline/sessions/fence/<line>/`, mounted over the real paths. The
  line reads fresh sibling refs and commits to its own branch freely;
  every write lands in the mirror and the real repository is never bound
  writable. The mirror refreshes on each launch — real refs copied in,
  the line's own branch (and any branch it created) kept.
- `worktrees/` is read-only except the line's own metadata directory.

The whole common `.git` root is also covered by a per-line private overlay.
It is seeded and refreshed from root-level files while leaving `config`,
`hooks`, and the separately managed `objects/`, `worktrees/`, `refs/`,
`logs/`, and `packed-refs` out. The real objects, config, hooks, and
worktrees are then mounted with their required scopes, and this line's
metadata plus the refs mirror are mounted after them. Git can therefore
create root-level transient files such as `ORIG_HEAD`, `FETCH_HEAD`, and
`packed-refs.lock` without writing into the repository's real `.git` root.

On Darwin there are no mounts, so the private overlays cannot exist and
the guarantee is weaker by construction (`git_fence.darwin_write_paths`):
the profile allows file-write under the common `.git` root for transient
root files and shared `objects/`, `refs/`, `logs/`, and `packed-refs`.
More-specific denies keep `config`, `hooks`, `description`, `HEAD`, `info`,
`branches`, and sibling `.git/worktrees/` metadata protected; this line's
own metadata is allowed back. **Sibling refs and common transient Git
files are writable there.**
A sibling can clobber this line's branch view (and vice versa); the
acceptance flow — hand a SHA, let the captain fast-forward — is what keeps
work trustworthy, not the filesystem.

On Windows, child branches are named `line/<slug>/work`. Their private ref
subdirectory permits Git's atomic lock files without granting sibling refs.
The line writes its own worktree metadata, ref/reflog directory, and shared
objects. It cannot write common Git configuration, hooks, sibling refs, or
common transient files. Operations needing those paths (for example fetches
that update shared refs or repository maintenance) must run through the captain.
Windows uses real refs, so the host sees committed child progress immediately;
there is no Linux-style ref mirror. Review the reported SHA in a managed review
checkout on every platform.

Consequences worth knowing (these describe the Linux mirror; on Darwin
the real refs really do move):

- The line's branch advances **in the mirror**. `git log` inside the line
  is correct; the real branch moves only when the captain accepts the
  handed-off SHA (which works, because the commit object is shared):
  accept reads the mirror ref (`git_fence.mirror_branch_ref`) to tell the
  line's own work from a stray, then fast-forwards the real ref.
- Deleting a ref that lives only in `packed-refs` fails with a warning;
  the line's own branch is always loose in the mirror, so its own branch
  operations are unaffected.
- Branch views are launch-time fresh; a long-lived process does not see
  sibling merges that happen mid-turn.

## Nested sandboxes

Some CLIs bring their own filesystem sandbox. Codex's is bubblewrap on
Linux, and bubblewrap cannot nest under the fence (verified 2026-09-22:
the inner namespace creation is refused); on Darwin its sandbox-exec
profile cannot nest under ours either. When a process is fenced, an
adapter's declared `fence_args` are appended to its command — codex
declares `--dangerously-bypass-approvals-and-sandbox`, so the fence is
the only sandbox, as it already is for every other adapter. `fence_args`
apply only while the process is actually fenced; with the feature off,
the CLI's own sandbox stays.

## Scope expansion

```
POST /api/conversations/<id>/write-set   {"path": "/abs/normalized/path"}
GET  /api/conversations/<id>/write-set
GET  /api/conversations/<id>/write-set/request
POST /api/conversations/<id>/write-set/request/<id>/approve   (person only)
POST /api/conversations/<id>/write-set/request/<id>/deny      {"reason": "…"}
POST /api/conversations/<id>/write-set/request/<id>/withdraw  (the requester only)
DELETE /api/conversations/<id>/write-set/request/<id>         (person only)
```

A **person** POST grants directly and the grant is recorded immediately. A
**machine** on the line, or the captain of an ancestor line, POST files a
pending request instead — at most one per line; a second filing is **409**.
Every open tab on that line shows the banner; a person approves or declines.
Approval inserts the grant row, posts a system notice, privately rings the
requester on its home line (by attachment id, never by name), and detaches
and resumes every live process on the line so the widened bind applies.
Decline clears the request and rings the requester the same way; `deny` does the
same with a reason (1–500 characters) posted on the requesting line, and the
process that filed a request may `withdraw` it. A **captain** may approve or deny
too, but only inside a grant it already holds: it must be the live lead of a
strict ancestor of the requesting line, must not be the requester, and the
requested path — resolved through symlinks — must lie inside a write grant on its
own line. Anything wider is refused with `outside your grants; a person decides`. Grants are
rows in `conversation_write_grants` with the grantor recorded. Paths must be
absolute and normalized; a path that does not exist at spawn time binds nothing.

## Feature flag

`write_fence` (default **on**, stable). At boot, Partyline runs the selected
backend once against a harmless command. A failed check is logged and shown
at `/api/fence/status`; attach and resume remain refused with the same
person-side install remedy. `partyline doctor` runs the probe and checks the
CLI requirements declared by installed adapter manifests. The emergency
`PARTYLINE_FEATURE_WRITE_FENCE=0` switch remains for one restart cycle only.

## Adapter notes

| adapter | manifest additions | first attach |
| --- | --- | --- |
| codex | `fence_args` (sandbox replaced by the fence) | none |
| claude | none | a folder-trust dialog per new worktree path, answered once in the pty |
| cursor | none | none: the bundled command ships `--trust` |
| opencode | none | none |
| antigravity | none | a trust dialog per new worktree path; the pinned log root is writable outside protected repositories |
| grok | none | none with `--permission-mode bypassPermissions` |
| deepseek | none | `~/.dsh` is writable unless it is within a protected repository |
| hermes | none | `~/.hermes` is writable unless it is within a protected repository |
| muse | none | `~/.local/share/muse` is writable unless it is within a protected repository |
| pi | none | `~/.pi` and pinned sessions are writable unless within a protected repository |

Probe evidence (2026-09-22/23, real CLIs under the fence): codex, claude,
cursor, opencode, and grok completed real turns and wrote only inside the
fence; antigravity validated startup, auth, transcript writes, and paste
ingestion (its model turn was quota-blocked, which is external to the
fence). Logs: the write-fence line's hand-off. deepseek, hermes, muse, and
pi never got that probe — which is how qwen (deepseek) shipped: it exited 1
at its first write to `~/.dsh` under the old fence (found 2026-09-23).
Those home writes are now writable by default unless they fall under an
active protected repository; a real fenced spawn of those four remains
to be re-probed on a host that can create namespaces.
