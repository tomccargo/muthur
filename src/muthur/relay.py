"""The relay: Download Station and muthur's own update, done on the NAS as root, without a DSM login (ARCHITECTURE.md §16).

The DSM user that owns the Download Station tasks may use two-step verification, so muthur can't log in as that user. This
runs in its own container instead (compose.yaml, service `relay`): root, privileged, the host's PID namespace and no network,
so it can enter the host (nsenter -t 1) and run DSM's own /usr/syno/bin/synowebapi with `runner=<user>`, as lambert's relay
does. It reads only <id>.req.json files in its spool folder (muthur's config/relay), never passes anything through a shell,
and answers in <id>.res.json. What it may do is fixed here:

    list     SYNO.DownloadStation2.Task v2 list   the runner's tasks: id, title, status (by name), destination, progress
    delete   SYNO.DownloadStation2.Task v2 delete  only ids shaped dbid_<n>, force_complete=false
    pull     docker pull of muthur's own image (from this container's environment, never from a request), in the background
    rebuild  starts a one-off `muthur-update` container that has Container Manager rebuild the project (SYNO.Docker.Project),
             so the rebuild outlives this container, which the rebuild replaces

Progress of an update is in update.json in the spool. The DSM user comes from DS_USER, or else is the user PUID belongs to.

    python -m muthur.relay            the relay
    python -m muthur.relay --rebuild  the one-off update container
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid

SPOOL = os.environ.get("MUTHUR_RELAY_SPOOL", "/spool")
HOST = ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p"]
SYNOWEBAPI = "/usr/syno/bin/synowebapi"
DOCKER = "/usr/local/bin/docker"
STALE = 600  # answers nobody picked up, and requests older than this, are removed
TASK_ID = re.compile(r"^dbid_\d{1,12}$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}(:[A-Za-z0-9._-]{1,128})?$")

# DS2 reports a task's status as a number. Synology's own Download Station UI (download.js, DSM 7.0) names them:
# https://gist.github.com/Rhilip/e1b72f5d5974998077805e5c31f1d53d ; 5 = finished checked on Nostromo (2026-11-22).
STATUS = {1: "waiting", 2: "downloading", 3: "paused", 4: "finishing", 5: "finished", 6: "hash_checking", 7: "pre_seeding",
          8: "seeding", 9: "filehosting_waiting", 10: "extracting"}
ERRORS = {102: "Download Station has no such API here.", 400: "Download Station refused the request.",
          544: "Download Station doesn't know that task."}


def status_name(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return STATUS.get(value, "error" if value >= 100 else f"status {value}")
    return "unknown"


def parse(out: str) -> dict:
    """synowebapi may print a log line before its JSON answer."""
    return json.loads(out[out.index("\n{") + 1:] if "\n{" in out else out)


def host(args: list[str], timeout: float = 60, run=subprocess.run) -> str:
    return run(HOST + args, capture_output=True, text=True, timeout=timeout).stdout or ""


def webapi(api: str, version: int, method: str, run=subprocess.run, timeout: float = 60, **params) -> dict:
    """One synowebapi call; params are JSON-encoded, as DSM's web UI sends them. Raises ValueError for a failure."""
    args = [SYNOWEBAPI, "--exec", f"api={api}", f"version={version}", f"method={method}"]
    # runner is synowebapi's own option, the bare user name (as lambert's relay sends it); the rest are the API's JSON values.
    args += [f"{k}={v if k == 'runner' else json.dumps(v)}" for k, v in params.items()]
    try:
        body = parse(host(args, timeout, run))
    except (OSError, subprocess.SubprocessError) as e:
        raise ValueError(f"The relay couldn't run synowebapi ({type(e).__name__}).") from e
    except ValueError as e:
        raise ValueError("DSM gave no readable answer.") from e
    if not body.get("success"):
        code = (body.get("error") or {}).get("code")
        raise ValueError(ERRORS.get(code, f"DSM answered with error {code}.") if isinstance(code, int) else f"DSM answered with error {code}.")
    return body.get("data") or {}


def runner() -> str:
    """The DSM user whose tasks these are: DS_USER, else the name of PUID in the host's /etc/passwd."""
    name = os.environ.get("DS_USER", "").strip()
    if not name:
        uid = os.environ.get("PUID", "").strip()
        try:
            with open("/proc/1/root/etc/passwd", encoding="utf-8") as f:
                name = next((line.split(":")[0] for line in f if line.split(":")[2:3] == [uid]), "")
        except OSError:
            name = ""
    return name if NAME.match(name) else ""


# -- Download Station ------------------------------------------------------------
def ds_list(user: str, run=subprocess.run) -> dict:
    data = webapi("SYNO.DownloadStation2.Task", 2, "list", run, runner=user, offset=0, limit=-1, additional=["detail", "transfer"])
    tasks = []
    for t in data.get("task") or []:
        add = t.get("additional") or {}
        size, got = t.get("size") or 0, (add.get("transfer") or {}).get("size_downloaded")
        tasks.append({"id": t.get("id"), "title": t.get("title"), "status": status_name(t.get("status")),
                      "destination": (add.get("detail") or {}).get("destination"),
                      "progress": round(100 * got / size) if isinstance(got, int) and size else None})
    return {"ok": True, "tasks": tasks}


def ds_delete(user: str, ids, run=subprocess.run) -> dict:
    if not isinstance(ids, list) or not ids or len(ids) > 200 or not all(isinstance(i, str) and TASK_ID.match(i) for i in ids):
        return {"ok": False, "error": "The relay refused malformed task ids."}
    data = webapi("SYNO.DownloadStation2.Task", 2, "delete", run, runner=user, id=ids, force_complete=False)
    failed = [f.get("id") for f in data.get("failed_task") or [] if f.get("error")]
    return {"ok": True, "failed": failed}


# -- muthur's own update -----------------------------------------------------------
def write_json(path: str, value: dict) -> None:
    tmp = f"{path}.{uuid.uuid4().hex[:6]}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def update_state(spool: str, state: str, **more) -> None:
    write_json(os.path.join(spool, "update.json"), {"state": state, "at": int(time.time()), **more})


def docker(args: list[str], timeout: float = 60, run=subprocess.run) -> str:
    return host([DOCKER, *args], timeout, run).strip()


def image() -> str:
    """The image an update pulls; empty when updating is off (MUTHUR_UPDATES=off)."""
    name = os.environ.get("MUTHUR_IMAGE", "").strip()
    return name if IMAGE.match(name) and os.environ.get("MUTHUR_UPDATES", "on").strip().lower() != "off" else ""


def pull(spool: str, run=subprocess.run) -> None:
    """Pull muthur's image; 'pulled' when it differs from the one muthur runs, else 'current'."""
    name, container = image(), os.environ.get("MUTHUR_CONTAINER", "muthur")
    try:
        update_state(spool, "pulling", image=name)
        r = run(HOST + [DOCKER, "pull", "-q", name], capture_output=True, text=True, timeout=1800)
        if r.returncode:
            update_state(spool, "failed", problem=f"docker pull {name} failed: {(r.stderr or r.stdout).strip()[-300:]}")
            return
        new = docker(["image", "inspect", "--format", "{{.Id}}", name], run=run)
        running = docker(["inspect", "--format", "{{.Image}}", container], run=run)
        update_state(spool, "current" if new and new == running else "pulled", image=name)
    except (OSError, subprocess.SubprocessError) as e:
        update_state(spool, "failed", problem=f"The relay couldn't pull ({type(e).__name__}).")


def rebuild(spool: str, run=subprocess.run) -> dict:
    """Start the one-off container that rebuilds the project; it gets the project from muthur's own compose labels."""
    name, container = image(), os.environ.get("MUTHUR_CONTAINER", "muthur")
    labels = json.loads(docker(["inspect", "--format", "{{json .Config.Labels}}", container], run=run) or "{}")
    project, compose = labels.get("com.docker.compose.project", ""), labels.get("com.docker.compose.project.config_files", "")
    me = os.environ.get("MUTHUR_RELAY_CONTAINER", "muthur-relay")
    mounts = json.loads(docker(["inspect", "--format", "{{json .Mounts}}", me], run=run) or "[]")
    spool_host = next((m.get("Source") for m in mounts if m.get("Destination") == spool), "")
    if not (NAME.match(project) and compose.startswith("/") and compose.endswith((".yaml", ".yml")) and "," not in compose and spool_host):
        return {"ok": False, "error": "The relay couldn't tell which Container Manager project muthur is."}
    out = run(HOST + [DOCKER, "run", "-d", "--rm", "--name", "muthur-update", "--user", "0:0", "--privileged", "--pid", "host",
                      "--network", "none", "-v", f"{spool_host}:/spool", "-e", f"MUTHUR_PROJECT={project}",
                      "-e", f"MUTHUR_COMPOSE={compose}", "--entrypoint", "/sbin/tini", name, "--", "python", "-m", "muthur.relay", "--rebuild"],
              capture_output=True, text=True, timeout=120)
    if out.returncode:
        return {"ok": False, "error": f"The relay couldn't start the update: {(out.stderr or out.stdout).strip()[-300:]}"}
    update_state(spool, "rebuilding", image=name)
    return {"ok": True}


def rebuild_project(spool: str = SPOOL, run=subprocess.run) -> None:
    """In the one-off container: Container Manager's own API updates and rebuilds the project (as nas-update-project.py)."""
    project, compose = os.environ.get("MUTHUR_PROJECT", ""), os.environ.get("MUTHUR_COMPOSE", "")
    try:
        content = host(["/bin/cat", compose], run=run)
        found = next((p for p in (webapi("SYNO.Docker.Project", 1, "list", run) or {}).values()
                      if isinstance(p, dict) and p.get("name") == project), None)
        if not found or not content:
            update_state(spool, "failed", problem=f"No Container Manager project called {project}.")
            return
        webapi("SYNO.Docker.Project", 1, "update", run, id=found["id"], content=content)
        update_state(spool, "rebuilding", project=project)
        # build_stream recreates every container of the project (muthur and the relay) with the pulled image.
        out = host([SYNOWEBAPI, "--exec", "api=SYNO.Docker.Project", "version=1", "method=build_stream", f"id={json.dumps(found['id'])}"],
                   timeout=1800, run=run)
        update_state(spool, "done", detail=out.strip().splitlines()[-1][-300:] if out.strip() else "")
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        update_state(spool, "failed", problem=str(e) or type(e).__name__)


# -- the spool -----------------------------------------------------------------------
PULLING = threading.Lock()


def handle(path: str, user: str, spool: str, run=subprocess.run) -> dict:
    try:
        if os.path.getsize(path) > 16384:
            raise ValueError("too big")
        with open(path, encoding="utf-8") as f:
            req = json.load(f)
        op = req.get("op")
    except (OSError, ValueError, AttributeError):
        return {"ok": False, "error": "The relay couldn't read the request."}
    try:
        if op in ("list", "delete") and not user:
            return {"ok": False, "error": "The relay doesn't know the DSM user; set DS_USER in .env."}
        if op == "list":
            return ds_list(user, run)
        if op == "delete":
            return ds_delete(user, req.get("ids"), run)
        if op in ("pull", "rebuild") and not image():
            return {"ok": False, "error": "Updating from muthur is off (MUTHUR_UPDATES=off in .env)."}
        if op == "pull":
            if not PULLING.acquire(blocking=False):
                return {"ok": True, "already": True}
            update_state(spool, "pulling", image=image())  # before answering, so muthur never reads an older state

            def go():
                try:
                    pull(spool, run)
                finally:
                    PULLING.release()
            threading.Thread(target=go, daemon=True).start()
            return {"ok": True}
        if op == "rebuild":
            return rebuild(spool, run)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return {"ok": False, "error": str(e) or type(e).__name__}
    return {"ok": False, "error": "The relay doesn't do that."}


def answer(req: str, result: dict) -> None:
    write_json(req[: -len(".req.json")] + ".res.json", result)
    try:
        os.remove(req)
    except OSError:
        pass


def tidy(spool: str) -> None:
    now = time.time()
    for name in os.listdir(spool):
        if name.endswith((".res.json", ".req.json", ".tmp")):
            p = os.path.join(spool, name)
            try:
                if now - os.path.getmtime(p) > STALE:
                    os.remove(p)
            except OSError:
                pass


def once(spool: str, user: str, run=subprocess.run) -> int:
    done = 0
    for name in sorted(os.listdir(spool)):
        if name.endswith(".req.json"):
            path = os.path.join(spool, name)
            answer(path, handle(path, user, spool, run))
            done += 1
    return done


def prepare(spool: str) -> None:
    """The spool belongs to muthur's user and nobody else (muthur writes requests; root reads them)."""
    os.makedirs(spool, exist_ok=True)
    uid, gid = os.environ.get("PUID", ""), os.environ.get("PGID", "")
    if uid.isdigit() and gid.isdigit():
        os.chown(spool, int(uid), int(gid))
    os.chmod(spool, 0o700)


def main() -> None:
    if "--rebuild" in sys.argv:
        rebuild_project()
        return
    if not os.path.exists("/proc/1/root" + SYNOWEBAPI):
        print("muthur relay: this isn't a Synology NAS (no synowebapi); nothing to do.", flush=True)
        while True:
            time.sleep(3600)
    prepare(SPOOL)
    user = runner()
    alive = os.path.join(SPOOL, "relay.alive")
    beat = tidied = 0.0
    print(f"muthur relay: spool {SPOOL}, DSM user {user or '(unknown)'}, image {image() or '(updates off)'}", flush=True)
    while True:
        now = time.time()
        if now - beat >= 15:
            write_json(alive, {"at": int(now), "user": user, "updates": bool(image())})
            beat = now
        if now - tidied >= 300:
            tidy(SPOOL)
            tidied = now
        try:
            n = once(SPOOL, user)
            if n:
                print(f"handled {n} request(s)", flush=True)
        except OSError as e:
            print(f"spool error: {e}", flush=True)
        time.sleep(0.5)


if __name__ == "__main__":
    main()
