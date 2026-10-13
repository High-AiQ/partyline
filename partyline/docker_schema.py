"""The shape of every body a managed line may send, and the rebuild that enforces it.

A spec maps each canonical field name to its own spec: ``None`` for a value passed as is
(strings, numbers, lists of strings, label and option maps whose keys are data, not
fields), a dict for a nested object, a one-item list for a list of objects, or
``("map", spec)`` for an object whose keys are data and whose values are objects. Docker's
decoder reads keys of *every* nested object without regard to case, so ``rebuild`` matches
keys case-insensitively at every level and emits only canonical names; the checks then run
on the rebuilt object, never on what the client sent.
"""

from __future__ import annotations

from .docker_policy import refuse


def fields(names: str, **nested) -> dict:
    return {name: nested.get(name) for name in names.split()}


MOUNT = fields(
    "Type Source Target ReadOnly Consistency BindOptions VolumeOptions TmpfsOptions",
    BindOptions=fields("Propagation NonRecursive CreateMountpoint ReadOnlyNonRecursive "
                       "ReadOnlyForceRecursive"),
    VolumeOptions=fields("NoCopy Labels DriverConfig Subpath",
                         DriverConfig=fields("Name Options")),
    TmpfsOptions=fields("SizeBytes Mode Options"))
DEVICE_REQUEST = fields("Driver Count DeviceIDs Capabilities Options")
ENDPOINT = fields(
    "IPAMConfig Links Aliases NetworkID EndpointID Gateway IPAddress IPPrefixLen IPv6Gateway "
    "GlobalIPv6Address GlobalIPv6PrefixLen MacAddress DriverOpts GwPriority DNSNames",
    IPAMConfig=fields("IPv4Address IPv6Address LinkLocalIPs"))
FORBIDDEN = ("Privileged CapAdd Devices DeviceCgroupRules VolumesFrom CgroupParent Cgroup Links Sysctls "
             "StorageOpt OomKillDisable MaskedPaths ReadonlyPaths ContainerIDFile BlkioWeightDevice "
             "BlkioDeviceReadBps BlkioDeviceWriteBps BlkioDeviceReadIOps BlkioDeviceWriteIOps "
             "CpuRealtimePeriod CpuRealtimeRuntime IOMaximumIOps IOMaximumBandwidth KernelMemory "
             "Isolation Annotations").split()  # known and dangerous: accepted only when empty
HOST = fields(
    "Binds LogConfig NetworkMode PortBindings RestartPolicy AutoRemove VolumeDriver CapDrop CgroupnsMode "
    "Dns DnsOptions DnsSearch ExtraHosts GroupAdd IpcMode OomScoreAdj PidMode PublishAllPorts "
    "ReadonlyRootfs SecurityOpt Tmpfs UTSMode UsernsMode ShmSize Runtime CpuShares Memory NanoCpus "
    "CpuPeriod CpuQuota CpusetCpus CpusetMems DeviceRequests MemoryReservation MemorySwap "
    "MemorySwappiness PidsLimit Ulimits CpuCount CpuPercent Mounts Init ConsoleSize BlkioWeight "
    + " ".join(FORBIDDEN),
    LogConfig=fields("Type Config"),
    PortBindings=("map", [fields("HostIp HostPort")]),
    RestartPolicy=fields("Name MaximumRetryCount"),
    DeviceRequests=[DEVICE_REQUEST], Ulimits=[fields("Name Soft Hard")], Mounts=[MOUNT])
CREATE = fields(
    "Hostname Domainname User AttachStdin AttachStdout AttachStderr ExposedPorts Tty OpenStdin StdinOnce "
    "Env Cmd Healthcheck ArgsEscaped Image Volumes WorkingDir Entrypoint NetworkDisabled MacAddress "
    "OnBuild Labels StopSignal StopTimeout Shell HostConfig NetworkingConfig",
    Healthcheck=fields("Test Interval Timeout StartPeriod StartInterval Retries"), HostConfig=HOST,
    NetworkingConfig=fields("EndpointsConfig", EndpointsConfig=("map", ENDPOINT)))
EXEC_CREATE = fields("AttachStdin AttachStdout AttachStderr DetachKeys Tty Env Cmd WorkingDir User "
                     "ConsoleSize Privileged")
EXEC_START = fields("Detach Tty ConsoleSize")
VOLUME = fields("Name Driver DriverOpts Labels")


def rebuild(value, spec, where: str, problems: list[tuple[str, str]]):
    """``value`` rebuilt through ``spec`` under canonical names; fields outside the spec become problems."""
    if spec is None or value is None:
        return value
    if isinstance(spec, list):
        if not isinstance(value, list):
            raise refuse("malformed-body", f"{where} must be a JSON list", 400)
        return [rebuild(item, spec[0], f"{where}[]", problems) for item in value]
    if not isinstance(value, dict):
        raise refuse("malformed-body", f"{where} must be a JSON object", 400)
    if isinstance(spec, tuple):
        return {key: rebuild(item, spec[1], f"{where}.{key}", problems) for key, item in value.items()}
    index = {name.lower(): name for name in spec}
    out = {}
    for key, item in value.items():
        if (canonical := index.get(key.lower())) is None:
            problems.append(("field-not-allowed", f"{where}.{key} is not allowed"))
        else:
            out[canonical] = rebuild(item, spec[canonical], f"{where}.{canonical}", problems)
    return out
