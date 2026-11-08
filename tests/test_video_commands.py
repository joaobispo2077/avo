"""Exercise registry CLI output and dispatch without touching the user's state."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from avo import videos


@pytest.fixture
def context(tmp_path, monkeypatch):
    ctx = SimpleNamespace(
        provider="channel", video_id="episode", video_key="stable-key", raw_dir=tmp_path
    )
    monkeypatch.setattr(videos.video_context, "resolve_context", Mock(return_value=ctx))
    return ctx


def test_list_json_and_human_output(monkeypatch, capsys, tmp_path):
    entries = [
        {
            "id": "episode",
            "title": "Café",
            "status": "editing",
            "rawDir": str(tmp_path),
        },
        {"id": "draft", "rawDir": str(tmp_path)},
    ]
    listing = Mock(return_value=entries)
    monkeypatch.setattr(videos.video_registry, "list_videos", listing)
    monkeypatch.setattr(
        videos.video_context,
        "work_mode_advisory",
        lambda provider: f"advisory: {provider}",
    )
    assert videos.main(["list", "--provider", "channel", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == entries
    assert videos.main(["list", "--provider", "channel"]) == 0
    output = capsys.readouterr().out
    assert "Café" in output and "(untitled)" in output and "advisory: channel" in output
    listing.assert_called_with("channel")
    listing.return_value = []
    assert videos.main(["list", "--provider", "channel"]) == 0
    assert "No videos registered" in capsys.readouterr().out


@pytest.mark.parametrize("project_exists,locked", [(False, False), (True, True)])
def test_show_project_and_lock_status(
    monkeypatch, tmp_path, capsys, project_exists, locked
):
    entry = {
        "id": "episode",
        "provider": "channel",
        "rawDir": str(tmp_path),
        "title": "Title",
        "projectFile": "custom.json",
    }
    if project_exists:
        (tmp_path / "custom.json").write_text("{}")
    monkeypatch.setattr(
        videos.video_registry, "load_registry", Mock(return_value=entry)
    )
    monkeypatch.setattr(
        videos.video_context,
        "read_lock",
        Mock(return_value={"acquiredAt": "today"} if locked else None),
    )
    args = ["show", "--provider", "channel", "--video-id", "episode"]
    assert videos.main([*args, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == entry
    assert videos.main(args) == 0
    output = capsys.readouterr().out
    assert f"custom.json ({'exists' if project_exists else 'missing'})" in output
    assert ("held since today" in output) == locked
    assert "Title" in output


@pytest.mark.parametrize("command", ["show", "resolve", "context set"])
@pytest.mark.parametrize(
    "error",
    [FileNotFoundError("missing"), videos.video_registry.VideoRegistryError("invalid")],
)
def test_registry_errors_are_actionable(monkeypatch, capsys, command, error):
    monkeypatch.setattr(videos.video_registry, "load_registry", Mock(side_effect=error))
    monkeypatch.setattr(
        videos.video_context, "resolve_context", Mock(side_effect=error)
    )
    assert (
        videos.main(
            [*command.split(), "--provider", "channel", "--video-id", "episode"]
        )
        == 1
    )
    assert str(error) in capsys.readouterr().err


def test_resolve_json_verbose_and_text(context, monkeypatch, capsys):
    merge = Mock(return_value={"source": "provider"})
    monkeypatch.setattr(videos.video_context, "merge_config", merge)
    args = ["resolve", "--provider", "channel", "--video-id", "episode"]
    assert videos.main([*args, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {
        "provider": "channel",
        "videoId": "episode",
        "videoKey": "stable-key",
        "rawDir": str(context.raw_dir),
    }
    merge.assert_not_called()
    assert videos.main([*args, "--json", "--verbose"]) == 0
    assert json.loads(capsys.readouterr().out)["mergedConfig"] == {"source": "provider"}
    merge.assert_called_once_with(context)
    assert videos.main([*args, "--verbose"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        str(context.raw_dir),
        "videoKey: stable-key",
    ]


def test_context_lifecycle(context, monkeypatch, capsys):
    save = Mock(return_value=context.raw_dir / "active.json")
    clear = Mock()
    load = Mock(return_value=None)
    monkeypatch.setattr(videos.avo_state, "save_active_context", save)
    monkeypatch.setattr(videos.avo_state, "load_active_context", load)
    monkeypatch.setattr(videos.avo_state, "clear_active_context", clear)
    assert (
        videos.main(
            ["context", "set", "--provider", "channel", "--video-id", "episode"]
        )
        == 0
    )
    saved = save.call_args.args[0]
    assert saved == {
        "mode": "concurrency",
        "provider": "channel",
        "videoId": "episode",
        "videoKey": "stable-key",
        "rawDir": str(context.raw_dir),
    }
    assert "Active context set" in capsys.readouterr().out
    assert videos.main(["context", "show"]) == 0
    assert "No active context" in capsys.readouterr().out
    assert videos.main(["context", "show", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {}
    load.return_value = {**saved, "updatedAt": "today"}
    assert videos.main(["context", "show"]) == 0
    assert "today" in capsys.readouterr().out
    assert videos.main(["context", "show", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == load.return_value
    assert videos.main(["context", "clear"]) == 0
    clear.assert_called_once_with()


def test_advisory_lock_lifecycle(context, monkeypatch, capsys):
    acquire = Mock(return_value=context.raw_dir / "lock.json")
    release = Mock(return_value=True)
    read = Mock(return_value=None)
    monkeypatch.setattr(videos.video_context, "acquire_lock", acquire)
    monkeypatch.setattr(videos.video_context, "release_lock", release)
    monkeypatch.setattr(videos.video_context, "read_lock", read)
    args = [
        "lock",
        "acquire",
        "--provider",
        "channel",
        "--video-id",
        "episode",
        "--force",
        "--session-id",
        "session",
    ]
    assert videos.main(args) == 0
    acquire.assert_called_once_with(context, force=True, session_id="session")
    assert "acquired" in capsys.readouterr().out
    acquire.side_effect = videos.video_registry.VideoRegistryError("busy")
    assert videos.main(args) == 1
    assert "busy" in capsys.readouterr().err
    release_args = ["lock", "release", "--raw-dir", str(context.raw_dir)]
    assert videos.main(release_args) == 0
    assert "released" in capsys.readouterr().out
    release.assert_called_once_with(context.raw_dir)
    release.return_value = False
    assert videos.main(release_args) == 0
    assert "No advisory lock found" in capsys.readouterr().out
    status_args = ["lock", "status", "--raw-dir", str(context.raw_dir)]
    assert videos.main(status_args) == 0
    assert "No advisory lock." in capsys.readouterr().out
    assert videos.main([*status_args, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {}
    read.return_value = {
        "provider": "channel",
        "videoId": "episode",
        "videoKey": "key",
        "host": "host",
        "pid": 42,
        "acquiredAt": "today",
    }
    assert videos.main(status_args) == 0
    output = capsys.readouterr().out
    assert "host/42" in output and "today" in output
    assert videos.main([*status_args, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == read.return_value


def test_reindex_success_and_failure(monkeypatch, tmp_path, capsys):
    rebuild = Mock(return_value=tmp_path / "index.json")
    monkeypatch.setattr(videos.video_registry, "rebuild_index", rebuild)
    assert videos.main(["reindex", "--provider", "channel"]) == 0
    rebuild.assert_called_once_with("channel")
    assert str(tmp_path / "index.json") in capsys.readouterr().out
    rebuild.side_effect = videos.video_registry.VideoRegistryError("bad manifest")
    assert videos.main(["reindex", "--provider", "channel"]) == 1
    assert "bad manifest" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv", [[], ["list"], ["context"], ["lock"], ["show", "--provider", "channel"]]
)
def test_required_cli_arguments(argv):
    with pytest.raises(SystemExit) as exc:
        videos.main(argv)
    assert exc.value.code == 2
