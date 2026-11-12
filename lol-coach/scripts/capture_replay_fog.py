"""Capture native fog-on / fog-off PNG pairs at specified ROFL times on Windows.

By default a private desktop replays the file in spectator All. With --attach-pid,
an existing replay keeps its selected perspective and each time also gets a HUD
frame for verifying the team label. The installed game files stay read-only.
"""
import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as w
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.request
from uuid import uuid4


class StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", w.DWORD), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR), ("title", w.LPWSTR),
        *[(name, w.DWORD) for name in
          ("x", "y", "width", "height", "chars_x", "chars_y", "fill", "flags")],
        ("show", w.WORD), ("reserved_size", w.WORD), ("reserved_buffer", w.LPVOID),
        ("stdin", w.HANDLE), ("stdout", w.HANDLE), ("stderr", w.HANDLE),
    ]


class ProcessInfo(ctypes.Structure):
    _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE), ("pid", w.DWORD), ("tid", w.DWORD)]


@contextmanager
def owned_replay(exe, replay):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.CreateDesktopW.argtypes = [w.LPCWSTR, w.LPCWSTR, w.LPVOID, w.DWORD, w.DWORD, w.LPVOID]
    user.CreateDesktopW.restype = w.HANDLE
    user.CloseDesktop.argtypes = [w.HANDLE]
    kernel.CreateProcessW.argtypes = [
        w.LPCWSTR, w.LPWSTR, w.LPVOID, w.LPVOID, w.BOOL, w.DWORD, w.LPVOID, w.LPCWSTR,
        ctypes.POINTER(StartupInfo), ctypes.POINTER(ProcessInfo),
    ]
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    name = "LoLReplayFog_" + uuid4().hex
    desktop = user.CreateDesktopW(name, None, None, 0, 0x1FF, None)
    if not desktop:
        raise ctypes.WinError(ctypes.get_last_error())
    info = ProcessInfo()
    try:
        startup = StartupInfo(cb=ctypes.sizeof(StartupInfo), desktop="WinSta0\\" + name)
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(exe), str(replay)]))
        if not kernel.CreateProcessW(str(exe), command, None, None, False, 0, None,
                                     str(exe.parent), ctypes.byref(startup), ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        yield info.pid, lambda: kernel.WaitForSingleObject(info.process, 0) == 258
    finally:
        if info.process:
            if kernel.WaitForSingleObject(info.process, 0) == 258:
                kernel.TerminateProcess(info.process, 0)
                kernel.WaitForSingleObject(info.process, 10000)
            kernel.CloseHandle(info.thread)
            kernel.CloseHandle(info.process)
        user.CloseDesktop(desktop)


def stage(game_dir, scratch):
    # CPython's Windows junction helper is also used by its own filesystem tests.
    import _winapi
    game = scratch / "Game"
    game.mkdir()
    for source in game_dir.iterdir():
        if source.is_file():
            shutil.copy2(source, game / source.name)
    for name in ("DATA", "AntiCheatExpert"):
        source = game_dir / name
        if source.is_dir():
            _winapi.CreateJunction(str(source), str(game / name))
    config = game / "Config"
    config.mkdir()
    (config / "game.cfg").write_text(
        "[General]\nEnableReplayApi=1\nWidth=1280\nHeight=720\nWindowMode=1\n"
        "EnableLightFx=0\n[Volume]\nMasterVolume=0\nMasterMute=1\n", encoding="ascii")
    return game / "League of Legends.exe"


@contextmanager
def attached_replay(pid, exe, replay, build):
    if pid <= 0:
        raise ValueError("Expected a positive replay PID")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    shell.CommandLineToArgvW.argtypes = [w.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(w.LPWSTR)
    kernel.LocalFree.argtypes = [w.HLOCAL]
    handle = kernel.OpenProcess(0x100000 | 0x1000, False, pid)
    if not handle:
        raise ValueError("Unable to open the requested replay PID")
    try:
        # Match the command line against the requested local ROFL, without logging it.
        inspect = (
            "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
            "$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$env:LOLFogPID);"
            "if (!$p -or !$p.ExecutablePath -or !$p.CommandLine) { exit 1 };"
            "$ver=(Get-Item -LiteralPath $p.ExecutablePath).VersionInfo.FileVersion;"
            "@{exe=$p.ExecutablePath;cmd=$p.CommandLine;version=$ver}|ConvertTo-Json -Compress"
        )
        raw = subprocess.check_output(["powershell", "-NoProfile", "-NonInteractive", "-Command", inspect],
                                      env={**os.environ, "LOLFogPID": str(pid)})
        process = json.loads(raw.decode("utf-8-sig"))
        if Path(process["exe"]).resolve() != exe or process["version"] != build:
            raise ValueError("Requested PID does not match the expected game executable and ROFL build")
        count = ctypes.c_int()
        pointer = shell.CommandLineToArgvW(process["cmd"], ctypes.byref(count))
        if not pointer:
            raise ValueError("Cannot read the replay process arguments")
        try:
            files = [Path(arg) for arg in pointer[1:count.value] if arg.lower().endswith(".rofl")]
        finally:
            kernel.LocalFree(ctypes.cast(pointer, w.HLOCAL))
        if len(files) != 1 or not files[0].is_absolute() or files[0].resolve() != replay:
            raise ValueError("PID was not launched from the requested absolute replay file")
        yield pid, lambda: kernel.WaitForSingleObject(handle, 0) == 258
    finally:
        kernel.CloseHandle(handle)


def request_api(client, path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request("https://127.0.0.1:2999/replay/" + path, data=body,
                                 headers={"Content-Type": "application/json"})
    with client.open(req, timeout=2) as response:
        return json.load(response)


def wait_until(check, description, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.1)
    raise RuntimeError("Timed out waiting for " + description)


@contextmanager
def capture_workspace(parent):
    workspace = tempfile.TemporaryDirectory(prefix="replay-fog-", dir=parent)
    try:
        yield Path(workspace.name)
    finally:
        # The game can release its working directory shortly after process exit.
        for attempt in range(20):
            try:
                workspace.cleanup()
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.25)


def capture(request, scratch, output, at, enabled, index, mode=None):
    mode = mode or ("fog" if enabled else "reference")
    render = request("render", {"fogOfWar": enabled})
    if render["fogOfWar"] != enabled:
        raise RuntimeError("Replay renderer did not apply fog setting")
    request("playback", {"time": at, "paused": True})

    def paused_at():
        state = request("playback")
        if state["paused"] and not state["seeking"] and abs(state["time"] - at) < 0.002:
            return state

    state = wait_until(paused_at, "the requested paused replay tick")
    time.sleep(0.4)
    render = request("render")
    if render["fogOfWar"] != enabled:
        raise RuntimeError("Replay did not retain the selected fog setting after seeking")
    target = scratch / f"capture-{index}-{mode}"
    target.mkdir()
    settings = request("recording", {
        "codec": "png", "startTime": -1, "endTime": at + 0.15, "framesPerSecond": 5,
        "path": str(target), "recording": True, "enforceFrameRate": True,
    })
    if not settings["recording"] or abs(settings["currentTime"] - at) > 0.002:
        raise RuntimeError("Capture did not start on the verified game tick")
    wait_until(lambda: not request("recording")["recording"], "PNG output")
    first = Path(settings["path"]).resolve() / "000000.png"
    if not first.is_relative_to(target):
        raise ValueError("Client returned an unexpected capture directory")
    wait_until(first.is_file, "the original first frame")
    png = first.read_bytes()
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid client PNG")
    filename = f"{str(at).removesuffix('.0')}-{mode}.png"
    (output / filename).write_bytes(png)
    return {"file": filename, "sha256": hashlib.sha256(png).hexdigest(), "render": render,
            "playback_before_recording": state, "capture_start": settings["currentTime"],
            "width": settings["width"], "height": settings["height"]}


def restore_view(request, original, modified_keys):
    # The top camera ignores position writes in its own mode. Set its target
    # from the free camera before handing it back to the spectator.
    pose = ("cameraPosition", "cameraRotation")
    keys = (set(modified_keys) - set(pose)) | {"interfaceReplay", "fogOfWar",
                                                "selectionName", "cameraAttached"}
    settings = {k: original[k] for k in keys}
    target = dict(original["cameraPosition"])
    for attempt in range(2):
        request("render", {"cameraMode": "fps", "fieldOfView": original["fieldOfView"],
                           "cameraRotation": original["cameraRotation"], "cameraPosition": target})
        request("render", settings)
        time.sleep(0.2)
        actual = request("render")["cameraPosition"]
        delta = {axis: original["cameraPosition"][axis] - actual[axis] for axis in target}
        # Top mode can shift a static camera slightly to fit the map boundary.
        # Moving targets and directed cameras retain their native camera controller.
        if (original["cameraMode"] != "top" or original["cameraAttached"] or
                max(map(abs, delta.values())) <= 0.25):
            break
        target = {axis: target[axis] + delta[axis] for axis in target}
    return {"camera_mode": original["cameraMode"], "position_before": original["cameraPosition"],
            "position_restored": actual, "attempts": attempt + 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path, required=True, help="Installed Game directory")
    parser.add_argument("--rofl", type=Path, required=True)
    parser.add_argument("--attach-pid", type=int, help="Capture the perspective already selected in this replay")
    parser.add_argument("--at", type=float, nargs="+", required=True, help="Game seconds")
    parser.add_argument("--output", type=Path, required=True, help="New directory")
    parser.add_argument("--camera", nargs=3, type=float, metavar=("WORLD_X", "HEIGHT", "WORLD_Z"),
                        default=(7450, 15000, 7450))
    args = parser.parse_args()
    game, replay, output = (p.resolve() for p in (args.game_dir, args.rofl, args.output))
    if not (game / "League of Legends.exe").is_file() or not (game / "DATA").is_dir():
        parser.error("An installed Windows game directory is required")
    if output.is_relative_to(game):
        parser.error("Use an output directory outside the game installation")
    if any(not math.isfinite(v) or v < 0 for v in args.at) or len(set(args.at)) != len(args.at):
        parser.error("Expected finite, unique, nonnegative game times")
    if not all(math.isfinite(v) for v in args.camera) or args.camera[1] <= 0:
        parser.error("Expected a finite camera position above the map")
    with replay.open("rb") as source:
        head = source.read(15)
        if len(head) != 15 or head[:5] != b"RIOT\x02":
            parser.error("Expected a ROFL2 file")
        build = source.read(head[14]).decode("ascii")
        source.seek(0)
        replay_hash = hashlib.file_digest(source, "sha256").hexdigest()
    if args.attach_pid is None:
        with socket.socket() as check:
            check.settimeout(0.4)
            if check.connect_ex(("127.0.0.1", 2999)) == 0:
                parser.error("Port 2999 is already in use")
    if output.exists():
        parser.error("Output directory already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    client = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
    with capture_workspace(output.parent) as scratch:
        if args.attach_pid is None:
            exe = stage(game, scratch)
            session = owned_replay(exe, replay)
        else:
            exe = game / "League of Legends.exe"
            session = attached_replay(args.attach_pid, exe, replay, build)
        with session as (pid, alive):
            def ready():
                if args.attach_pid is None:
                    for path in (exe.parent / "Logs").rglob("*r3dlog.txt"):
                        evidence = path.read_text(errors="replace").lower()
                        if "failed to read replay file" in evidence:
                            signed = "bad signature" in evidence
                            output.mkdir()
                            rejection = {"status": "rejected_before_gameplay",
                                         "replay_sha256": replay_hash, "replay_build": build,
                                         "log_messages": (["bad signature"] if signed else []) +
                                                         ["failed to read replay file"]}
                            (output / "rejection.json").write_text(json.dumps(rejection, indent=2),
                                                                    encoding="utf-8")
                            reason = " (bad signature)" if signed else ""
                            raise ValueError("The unmodified client rejected the replay file" + reason)
                if not alive():
                    raise RuntimeError("Renderer exited before replay API became ready")
                try:
                    return request_api(client, "game")["processID"] == pid
                except OSError:
                    return False

            wait_until(ready, "the selected process's replay API", seconds=70 if args.attach_pid is None else 8)

            def request(path, data=None):
                if not alive() or request_api(client, "game")["processID"] != pid:
                    raise RuntimeError("The owned replay is no longer available")
                return request_api(client, path, data)

            original_playback = request("playback")
            length = original_playback["length"]
            if any(t + 0.2 >= length for t in args.at):
                raise ValueError(f"Capture times must end before replay length {length:g}")
            if args.attach_pid is None:
                logs = list((exe.parent / "Logs").rglob("*r3dlog.txt"))
                if not any(f"Version {build} (" in p.read_text(errors="replace") for p in logs):
                    raise ValueError("Replay header version does not match the recorded engine build")
            if request("recording")["recording"] or original_playback["seeking"]:
                raise ValueError("Replay is currently recording or seeking")
            output.mkdir()
            params = {"cameraMode": "fps", "cameraPosition": dict(zip(("x","y","z"), args.camera)),
                      "cameraRotation": {"x": 0, "y": 89.99, "z": 0}, "fieldOfView": 76,
                      "farClip": 40000, "interfaceAll": False}
            for key in ("champions", "minions", "particles", "floatingText", "outlineSelect",
                        "outlineHover", "healthBarChampions", "healthBarMinions", "healthBarPets",
                        "healthBarStructures", "healthBarWards"):
                params[key] = False
            frames = []
            restoration = None
            old_render = request("render")
            try:
                request("render", params)
                for i, at in enumerate(args.at):
                    if args.attach_pid is not None:
                        request("render", {"interfaceAll": True, "interfaceReplay": True})
                        frames.append(capture(request, scratch, output, at, True, i, "perspective-hud"))
                        request("render", {"interfaceAll": False})
                    for fog in (True, False):
                        frames.append(capture(request, scratch, output, at, fog, i))
            finally:
                if args.attach_pid is not None and alive():
                    if request("recording")["recording"]:
                        request("recording", {"recording": False})
                    request("playback", {"time": original_playback["time"], "paused": True})
                    wait_until(lambda: not request("playback")["seeking"], "restoring the replay time")
                    restoration = restore_view(request, old_render, params)
                    request("playback", {k: original_playback[k] for k in ("paused", "speed")})
            manifest = {"schema": "native-replay-fog-pairs/v1", "replay_sha256": replay_hash,
                        "build": build, "perspective": ("default spectator All" if args.attach_pid is None
                                                        else "existing spectator setting, verify HUD label"),
                        "team_attribution": None, "restoration": restoration, "frames": frames}
            (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(output / "manifest.json")


if __name__ == "__main__":
    main()
