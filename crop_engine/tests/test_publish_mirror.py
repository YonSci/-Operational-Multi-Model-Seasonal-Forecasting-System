"""scripts/publish_daily.py: files the crop dashboard deletes on purpose are removed from the published copy."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("publish_daily", ROOT / "scripts" / "publish_daily.py")
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)

CROP = "frontend/public/tracker/data/crop"


def _files(root, names):
    d = root / CROP
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / n).write_text("{}", encoding="utf-8")
    return d


def test_deleted_crop_files_are_removed_from_the_published_copy(tmp_path):
    base, wt = tmp_path / "base", tmp_path / "wt"
    _files(base, ["index.json", "seasonal.json"])                       # scenarios.json deleted by the crop step
    pub = _files(wt, ["index.json", "seasonal.json", "scenarios.json", "nitrogen.json"])
    (pub / "bulletins").mkdir()
    (pub / "bulletins" / "site.pdf").write_text("x", encoding="utf-8")
    removed = publish.mirror_removals(base, wt)
    assert sorted(removed) == [f"{CROP}/nitrogen.json", f"{CROP}/scenarios.json"]
    assert sorted(p.name for p in pub.glob("*.json")) == ["index.json", "seasonal.json"]
    assert (pub / "bulletins" / "site.pdf").exists()                    # only the folder's own .json files


def test_nothing_is_removed_when_the_crop_step_did_not_run(tmp_path):
    base, wt = tmp_path / "base", tmp_path / "wt"
    (base / CROP).mkdir(parents=True)                                   # no index.json here
    pub = _files(wt, ["index.json", "scenarios.json"])
    assert publish.mirror_removals(base, wt) == []
    assert (pub / "scenarios.json").exists()
