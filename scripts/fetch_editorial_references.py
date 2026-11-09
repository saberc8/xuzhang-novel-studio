"""Download pinned GitHub source snapshots, without installing or running them."""
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "artifacts" / "editorial-references"


def main():
    manifest = json.loads((ROOT / "docs/editorial-quality-research.json").read_text())
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for entry in manifest["repositories"]:
        repository, commit = entry["repository"], entry["commit"]
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not re.fullmatch(r"[a-f0-9]{40}", commit):
            raise ValueError("Invalid repository identity in research manifest")
        destination = DESTINATION / repository.replace("/", "--")
        if destination.exists():
            stamp = json.loads((destination / ".reference.json").read_text())
            if (stamp["repository"], stamp["commit"]) != (repository, commit):
                raise ValueError(f"Existing source differs from manifest: {destination}")
        else:
            url = f"https://codeload.github.com/{repository}/tar.gz/{commit}"
            print(f"Downloading pinned source: {repository}", flush=True)
            temporary = Path(tempfile.mkdtemp(prefix=".fetch-", dir=DESTINATION))
            try:
                archive_path = temporary / "source.tar.gz"
                subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location",
                                "--proto", "=https", "--connect-timeout", "15", "--max-time", "600", "--retry", "1",
                                "--max-filesize", str(200 * 1024 * 1024), "--output", str(archive_path), url], check=True)
                with tarfile.open(archive_path) as archive:
                    members = archive.getmembers()
                    if len(members) > 50000 or sum(m.size for m in members) > 512 * 1024 * 1024:
                        raise ValueError("Unexpected archive size")
                    archive.extractall(temporary / "unpacked", filter="data")
                roots = list((temporary / "unpacked").iterdir())
                if len(roots) != 1 or not roots[0].is_dir():
                    raise ValueError("Unexpected source archive layout")
                stamp = {"repository": repository, "commit": commit, "url": url,
                         "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                         "format": "source snapshot; no Git history; code not executed"}
                (roots[0] / ".reference.json").write_text(json.dumps(stamp, indent=2) + "\n")
                roots[0].rename(destination)
            finally:
                shutil.rmtree(temporary)
        print(f"{repository} @ {commit}: {destination}", flush=True)


if __name__ == "__main__":
    main()
