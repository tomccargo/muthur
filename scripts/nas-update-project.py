"""Update a Container Manager project from its compose file and rebuild it. Runs on the Synology NAS, as root.

    python3 nas-update-project.py /volume1/docker/muthur/compose.yaml [project name] [--check]

The project is found by name (default: muthur) through Container Manager's own API (synowebapi,
SYNO.Docker.Project), so the change shows in Container Manager as if made there. --check only says
which project it found. Pull the new image first: docker pull tomccargo/muthur:latest (docs/DEPLOY.md).
"""
import json
import subprocess
import sys

API = "/usr/syno/bin/synowebapi"


def call(method, **params):
    args = [API, "--exec", "api=SYNO.Docker.Project", "version=1", f"method={method}"] + [f"{k}={json.dumps(v)}" for k, v in params.items()]
    return subprocess.run(args, capture_output=True, text=True).stdout


def answer(text):
    """synowebapi prints a log line before its JSON answer."""
    return json.loads(text[text.index("\n{") + 1:] if "\n{" in text else text)


args = [a for a in sys.argv[1:] if a != "--check"]
compose, name = args[0], args[1] if len(args) > 1 else "muthur"
projects = (answer(call("list")).get("data") or {}).values()
project = next((p for p in projects if p.get("name") == name), None)
if not project:
    sys.exit(f"No Container Manager project called {name}. Create it once in Container Manager: Project, Create.")
if "--check" in sys.argv:
    print(f"found {name}: {project['id']} at {project.get('path')}, {project.get('status')}")
    sys.exit(0)
out = call("update", id=project["id"], content=open(compose, encoding="utf-8").read())
print("update:", '"success" : true' in out or '"success": true' in out)
out = call("build_stream", id=project["id"])
print("\n".join(out.strip().splitlines()[-6:]))
