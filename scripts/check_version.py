"""Manifest-, Card- und CHANGELOG-Version müssen übereinstimmen."""
import json
import pathlib
import re
import sys

root = pathlib.Path(__file__).resolve().parents[1]
comp = root / "custom_components" / "smartify_heating"
manifest = json.loads((comp / "manifest.json").read_text(encoding="utf-8"))["version"]
js = (comp / "frontend" / "smartify-heating-card.js").read_text(encoding="utf-8")
m = re.search(r"const SHC_VERSION = '([^']+)'", js)
card = m.group(1) if m else None
changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
errors = []
if card != manifest:
    errors.append(f"Card-Version {card} != Manifest {manifest}")
if not re.search(rf"(?m)^##\s+v?{re.escape(manifest)}(\s|$)", changelog):
    errors.append(f"CHANGELOG ohne Eintrag für {manifest}")
if errors:
    print("\n".join(errors))
    sys.exit(1)
print(f"Version metadata consistent: {manifest}")
