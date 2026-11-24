"""Storage paths and the one-time cutover for submitted native pin-return arrays."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

HOME_RUNS = Path("$CLUSTER_HOME/eda/runs")
SCRATCH = Path("$CLUSTER_STORAGE")
RUNS = SCRATCH / "design-repo/chip/runs"
SPOOL = SCRATCH / "design-repo/chip/inflight"
PIN_JOBS = {
    "six-mask-grid": r"native_six_release_mesh_[a-z0-9_]+_t[0-9]+_[0-9a-f]{14}",
    "sx_RC_filter": r"native_grounded_wire_[0-9a-f]{12}_[0-9a-f]{14}",
    "native-raw-0-100": r"native_[a-z0-9_]+_raw_alphabet_[0-9a-f]{14}",
}


def checksum(stream):
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        result.update(chunk)
    return result.hexdigest()


def route_unopened():
    """An exclusive link can win before open(), or leave the writer's inode alone."""
    if SCRATCH.stat().st_uid != os.getuid() or not os.access(SCRATCH, os.W_OK):
        raise ValueError("Scratch account mismatch")
    queue = subprocess.check_output(["squeue", "-r", "-u", "clusteruser", "-t", "RUNNING",
                                     "-h", "-o", "%i|%j|%Z"], text=True)
    for row in queue.splitlines():
        task, job, path = row.split("|")
        root = Path(path)
        if job not in PIN_JOBS or root.parent != HOME_RUNS or not re.fullmatch(PIN_JOBS[job], root.name):
            continue
        array, index = map(int, task.split("_"))
        if (root / "job.id").read_text().strip() != str(array):
            raise ValueError(f"Registration differs for {task}")
        manifest = (root / "inputs.sha256").read_bytes()
        if hashlib.sha256(manifest).hexdigest()[:14] != root.name[-14:]:
            raise ValueError(f"Incorrect frozen bundle for {task}")
        sources = {name: value for value, name in (line.split() for line in manifest.decode().splitlines())}
        for name in ("cases.txt", "run.sh"):
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != sources[name]:
                raise ValueError(f"Changed {name} for {task}")
        case = (root / "cases.txt").read_text().splitlines()[index]
        script = (root / "run.sh").read_text()
        if (not re.fullmatch(r"[a-zA-Z0-9_]+", case) or
                not re.search(r"(?m)^gzip -n -[46] -c pins.dat > pins.dat.gz$", script)):
            raise ValueError(f"Unrecognized waveform output for {task}")
        folder = root / case
        if folder.resolve() != folder or not folder.is_dir() or (folder / "completed.sha256").exists():
            continue
        link = folder / "pins.dat"
        target = SPOOL / root.name / case / "pins.dat"
        if link.is_symlink() and link.readlink() == target:
            outcome = "already routed"
        elif os.path.lexists(link) or os.path.lexists(target):
            outcome = "existing entry preserved"
        else:
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                link.symlink_to(target)
                outcome = "linked before waveform open"
            except FileExistsError:
                outcome = "existing entry preserved"
        print(json.dumps(dict(task=task, run=str(root), case=case, outcome=outcome, target=str(target))), flush=True)


def compact(folder, *, routed_only=False):
    """Release an exact duplicate only after both compressed returns pass their manifest."""
    paths = {"pins.dat.gz": "pins.dat", "log.gz": "solver.log"}
    rows = [line.split() for line in (folder / "completed.sha256").read_text().splitlines()]
    if len(rows) != 2 or {name for _, name in rows} != set(paths):
        raise ValueError(f"Invalid completed manifest in {folder}")
    for wanted, name in rows:
        with (folder / name).open("rb") as src:
            if checksum(src) != wanted:
                raise ValueError(f"Damaged compressed return {folder / name}")
    for archive, name in paths.items():
        link = folder / name
        target = SPOOL / folder.parent.name / folder.name / name
        routed = link.is_symlink() and link.readlink() == target
        if routed_only and not routed:
            continue
        if link.is_symlink() and not routed:
            raise ValueError(f"Unrecognized waveform link {link}")
        if not link.is_file():
            continue
        with gzip.open(folder / archive, "rb") as src, link.open("rb") as raw:
            if checksum(src) != checksum(raw):
                raise ValueError(f"Plain and compressed returns differ for {link}")
        if routed:
            target.unlink()
        link.unlink()


def pin_launcher(original):
    directives = [line for line in original.decode().splitlines() if line.startswith("#SBATCH")]
    body = """set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
name=$(sed -n "$((SLURM_ARRAY_TASK_ID+1))p" cases.txt)
[[ "$name" =~ ^[a-zA-Z0-9_]+$ ]]
mkdir -p "$name"
exec 8>"$name/storage.lock"
flock -n 8
sha256sum -c --status storage.sha256
if ! test -s "$name/completed.sha256"; then bash run.sh; fi
python3 -B cluster_storage.py compact "$name"
"""
    return ("#!/bin/bash\n" + "\n".join(directives) + "\n" + body).encode()


def finish_cutover(records):
    """After Slurm releases the registered writers, verify their compact returns and free scratch."""
    entries=[json.loads(line) for line in Path(records).read_text().splitlines()]
    arrays=sorted({r["task"].split("_")[0] for r in entries})
    if not arrays or any(not re.fullmatch(r"\d+",j) for j in arrays):
        raise ValueError("Unexpected array IDs")
    states=subprocess.check_output(["sacct","-nPX","-j",",".join(arrays),
                                    "-o","JobID%64,State%40,ExitCode"],text=True)
    terminal={fields[0]:fields[1:3] for fields in (line.split("|") for line in states.splitlines())}
    for entry in entries:
        root=Path(entry["run"]);case=entry["case"];folder=root/case
        if (root.parent!=HOME_RUNS or not any(re.fullmatch(p,root.name) for p in PIN_JOBS.values()) or
                not re.fullmatch(r"[A-Za-z0-9_]+",case) or
                Path(entry["target"])!=SPOOL/root.name/case/"pins.dat"):
            raise ValueError("Unexpected cutover record")
        state=terminal.get(entry["task"])
        outcome="preserved partial return"
        if state==["COMPLETED","0:0"] and (folder/"completed.sha256").is_file():
            compact(folder,routed_only=True)
            outcome="verified compact return"
        print(json.dumps(dict(task=entry["task"],state=state,outcome=outcome)),flush=True)


def probe_wrdata():
    """Exercise ngspice file output using a literal vector with no circuit or analysis."""
    SPOOL.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as work, tempfile.TemporaryDirectory(dir=SPOOL) as bulk:
        folder = Path(work)
        raw = Path(bulk) / "scope"
        link = folder / "pins.dat"
        link.symlink_to(raw)
        (folder / "probe.ctl").write_text("Script storage check\n.control\nlet v=vector(3)\nsetscale v\nwrdata pins.dat v\nquit\n.endc\n.end\n")
        subprocess.run(["$CLUSTER_HOME/eda/ngspice-45.2-debian/bin/ngspice-run", "-b", "probe.ctl"],
                       cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
        if not link.is_symlink() or not link.samefile(raw) or not raw.stat().st_size:
            raise ValueError("ngspice did not follow the output link")
        compressed = subprocess.check_output(["gzip", "-n", "-6", "-c", link])
        if gzip.decompress(compressed) != raw.read_bytes():
            raise ValueError("Receipt compression differs")
        subprocess.run(["ln","-f",link,folder/"alias.dat"],check=True)
        if not (folder/"alias.dat").samefile(raw):
            raise ValueError("Unbroken return did not follow its hard-linked alias")
        print(json.dumps(dict(probe="literal-vector wrdata through scratch symlink and hard-linked alias", bytes=raw.stat().st_size,
                              gzip_sha256=hashlib.sha256(compressed).hexdigest())), flush=True)


if __name__ == "__main__":
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("action", choices=["probe", "route-unopened", "compact", "finish-cutover"])
    args.add_argument("case", nargs="?")
    options = args.parse_args()
    if options.action == "compact":
        compact(Path.cwd() / options.case)
    elif options.action == "finish-cutover":
        finish_cutover(options.case)
    elif options.action == "probe":
        probe_wrdata()
    else:
        route_unopened()
