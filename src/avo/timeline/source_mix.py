"""Bind relative source gain changes to exact canonical placed audio nodes."""

import re
from copy import deepcopy
from math import isfinite

from .contracts import ContractError, canonical_json_bytes
from .import_layout import audio_sample_ranges


class SourceMixError(ValueError):
    pass


_REQUIRED = {
    "placementId",
    "sourceId",
    "sourceSha256",
    "streamIndex",
    "channels",
    "gainDeltaDb",
}


def _require(condition, message):
    if not condition:
        raise SourceMixError(message)


def _same(left, right):
    try:
        return canonical_json_bytes(left) == canonical_json_bytes(right)
    except ContractError as error:
        raise SourceMixError(
            "source mix native graph must contain finite JSON values"
        ) from error


def _number(value, minimum, maximum, label):
    _require(type(value) in (int, float), f"{label} must be a finite number")
    _require(
        minimum <= value <= maximum and isfinite(value),
        f"{label} is outside its bounds",
    )
    return value


def _index(records, key):
    _require(isinstance(records, list), f"{key} inventory must be an array")
    result = {}
    for record in records:
        _require(isinstance(record, dict), f"{key} record must be an object")
        identity = record.get(key)
        _require(isinstance(identity, str) and bool(identity), f"{key} is missing")
        _require(identity not in result, f"duplicate {key}: {identity}")
        result[identity] = record
    return result


def _adjustment_shape(item):
    _require(isinstance(item, dict), "source mix adjustment must be an object")
    _require(
        _REQUIRED <= item.keys() <= _REQUIRED | {"peakCeilingDeltaDb"},
        "source mix adjustment fields differ",
    )
    for key in ("placementId", "sourceId"):
        _require(
            isinstance(item[key], str) and bool(item[key]),
            f"{key} must be a nonempty string",
        )
    _require(
        isinstance(item["sourceSha256"], str)
        and re.fullmatch(r"[a-f0-9]{64}", item["sourceSha256"]),
        "sourceSha256 must be a SHA-256 digest",
    )
    _require(
        type(item["streamIndex"]) is int and item["streamIndex"] >= 0,
        "streamIndex must be nonnegative",
    )
    channels = item["channels"]
    _require(
        isinstance(channels, list) and bool(channels),
        "channels must be a nonempty array",
    )
    _require(
        all(type(channel) is int and channel >= 0 for channel in channels),
        "channels must contain nonnegative integers",
    )
    _number(item["gainDeltaDb"], -30, 30, "gainDeltaDb")
    if "peakCeilingDeltaDb" in item:
        _number(item["peakCeilingDeltaDb"], -30, 30, "peakCeilingDeltaDb")


def _canonical_target(snapshot, adjustment):
    _require(
        snapshot.get("layoutMode") == "placed", "source mix requires a placed CMap"
    )
    layout = snapshot["layout"]
    placements = _index(layout["placements"], "placementId")
    tracks = _index(layout["tracks"], "trackId")
    sources = _index(snapshot["sources"], "sourceId")
    item = placements.get(adjustment["placementId"])
    _require(item is not None, "source mix placement is unknown")
    track = tracks.get(item["trackId"], {})
    _require(
        item["mediaKind"] == track.get("kind") == "audio",
        "source mix target must be audio",
    )
    _require(
        item["enabled"] is True and track.get("enabled") is True,
        "source mix target is disabled",
    )
    _require(
        not item.get("muted", False) and not track.get("muted", False),
        "source mix target is muted",
    )
    source = sources.get(item["sourceId"], {})
    selection = item["routing"]["audioSelection"]
    _target_identity(item, source, selection, adjustment)
    return item, selection


def _target_identity(item, source, selection, adjustment):
    _require(
        source.get("kind") == "raw", "source mix target must retain an original source"
    )
    _require(item["sourceId"] == adjustment["sourceId"], "source mix sourceId differs")
    _require(
        source["fingerprint"]["sha256"] == adjustment["sourceSha256"],
        "source mix source fingerprint differs",
    )
    _require(
        selection["streamIndex"] == adjustment["streamIndex"]
        and type(selection["streamIndex"]) is int,
        "source mix stream selection differs",
    )
    _require(
        _same(selection["channels"], adjustment["channels"]),
        "source mix channel selection differs",
    )
    _require(
        selection["outputLayout"] in {"dual-mono", "stereo"},
        "unsupported source mix output layout",
    )
    _require(
        type(selection["sourceSampleRate"]) is int
        and selection["sourceSampleRate"] > 0,
        "source mix native sample rate is invalid",
    )
    for key in ("in", "out"):
        _require(
            item[key]["domain"] == "raw-source"
            and item[key]["sourceId"] == item["sourceId"],
            "source mix raw clock differs",
        )
    for key in ("start", "end"):
        _require(
            item[key]["domain"] == "cmap-output", "source mix program clock differs"
        )
    audio_sample_ranges(item)


def _gain_parameters(parameters, adjustment):
    result = deepcopy(parameters)
    baseline = _number(result.get("gainDb", 0), -120, 30, "base gainDb")
    result["gainDb"] = _number(
        baseline + adjustment["gainDeltaDb"], -120, 30, "result gainDb"
    )
    if "peakCeilingDbfs" in result:
        _number(
            result["peakCeilingDbfs"],
            -12,
            -1,
            "base peakCeilingDbfs",
        )
    if "peakCeilingDeltaDb" in adjustment:
        _require(
            "peakCeilingDbfs" in result,
            "peak ceiling delta requires an existing ceiling",
        )
        result["peakCeilingDbfs"] = _number(
            result["peakCeilingDbfs"] + adjustment["peakCeilingDeltaDb"],
            -12,
            -1,
            "result peakCeilingDbfs",
        )
    return result


def validate_source_mix_adjustments(cmap_snapshot, adjustments):
    """Validate exact enabled placement identities; return detached declarations."""
    _require(isinstance(adjustments, list), "source mix adjustments must be an array")
    seen = set()
    try:
        for adjustment in adjustments:
            _adjustment_shape(adjustment)
            _require(
                adjustment["placementId"] not in seen, "duplicate source mix placement"
            )
            seen.add(adjustment["placementId"])
            item, _ = _canonical_target(cmap_snapshot, adjustment)
            parameters = {"gainDb": item.get("gainDb", 0)}
            if "audioPeakCeilingDbfs" in item:
                parameters["peakCeilingDbfs"] = item["audioPeakCeilingDbfs"]
            _gain_parameters(parameters, adjustment)
    except (KeyError, TypeError, ZeroDivisionError) as error:
        raise SourceMixError(
            "source mix canonical identity/clock is malformed"
        ) from error
    except ValueError as error:
        if isinstance(error, SourceMixError):
            raise
        raise SourceMixError(str(error)) from error
    return deepcopy(adjustments)


def _graph_index(graph):
    _require(isinstance(graph, dict), "source mix audio graph must be an object")
    nodes = _index(graph.get("nodes"), "nodeId")
    operations = _index(graph.get("operations"), "operationId")
    for op in operations.values():
        _require(isinstance(op.get("kind"), str), "native operation kind is missing")
        _require(
            isinstance(op.get("parameters"), dict),
            "native operation parameters must be an object",
        )
        if "nodeId" in op["parameters"]:
            identity = op["parameters"]["nodeId"]
            _require(
                isinstance(identity, str) and identity in nodes,
                "native operation node reference is invalid",
            )
    return nodes, operations


def _node_operations(graph, node_id):
    return [
        op for op in graph["operations"] if op["parameters"].get("nodeId") == node_id
    ]


def _matches(node, trim, item, selection, adjustment):
    source_range, output_range = audio_sample_ranges(item)
    mapping = (
        [selection["channels"][0]] * 2
        if selection["outputLayout"] == "dual-mono"
        else selection["channels"]
    )
    identity = {
        "kind": "source",
        "sourceRange": source_range,
        "outputRange": output_range,
        "sourceSampleRate": selection["sourceSampleRate"],
        "targetSampleRate": 48000,
        "sourceLayout": selection["sourceLayout"],
        "targetLayout": "stereo",
        "channelMap": mapping,
    }
    params = trim["parameters"]
    source = params.get("source") or {}
    return (
        _same({key: node.get(key) for key in identity}, identity)
        and params.get("sourceId") == item["sourceId"]
        and source.get("sha256") == adjustment["sourceSha256"]
        and source.get("streamIndex") == adjustment["streamIndex"]
        and type(source.get("streamIndex")) is int
        and trim.get("range") == output_range
    )


def _base_target(snapshot, base, nodes, adjustment):
    item, selection = _canonical_target(snapshot, adjustment)
    matches = []
    for trim in base["operations"]:
        if trim["kind"] != "trim":
            continue
        node = nodes.get(trim["parameters"].get("nodeId"))
        if node is not None and _matches(node, trim, item, selection, adjustment):
            matches.append(node)
    _require(
        len(matches) == 1, "source mix placement requires one exact native BASE node"
    )
    node = matches[0]
    operations = _node_operations(base, node["nodeId"])
    _base_filters(node, operations)
    gains = [op for op in operations if op["kind"] == "gain"]
    _require(len(gains) <= 1, "duplicate native gain for source mix target")
    _base_gain(item, node, gains)
    return node, operations, gains[0] if gains else None


def _base_filters(node, operations):
    kinds = [op["kind"] for op in operations]
    _require(
        kinds.count("trim") == 1
        and kinds.count("resample") == (node["sourceSampleRate"] != 48000)
        and set(kinds) <= {"trim", "resample", "gain"},
        "native BASE source filters are missing, duplicated or unsupported",
    )
    for op in operations:
        _require(
            _same(op.get("range"), node["outputRange"]),
            "native BASE filter range differs",
        )
        if op["kind"] == "resample":
            expected = {
                "nodeId": node["nodeId"],
                "sourceSampleRate": node["sourceSampleRate"],
                "targetSampleRate": 48000,
            }
            _require(
                _same(op["parameters"], expected),
                "native BASE resample parameters differ",
            )


def _base_gain(item, node, gains):
    declared = "gainDb" in item or "audioPeakCeilingDbfs" in item
    _require(bool(gains) == declared, "native BASE gain differs from CMap")
    if not gains:
        return
    expected = {"nodeId": node["nodeId"], "gainDb": item.get("gainDb", 0)}
    if "audioPeakCeilingDbfs" in item:
        expected["peakCeilingDbfs"] = item["audioPeakCeilingDbfs"]
    _require(
        _same(gains[0]["parameters"], expected)
        and _same(gains[0].get("range"), node["outputRange"]),
        "native BASE gain parameters/range differ from CMap",
    )


def _expected_gain(node, gain, adjustment):
    result = (
        deepcopy(gain)
        if gain
        else {
            "operationId": "source-mix-gain-" + node["nodeId"],
            "kind": "gain",
            "range": deepcopy(node["outputRange"]),
            "parameters": {"nodeId": node["nodeId"]},
        }
    )
    result["parameters"] = _gain_parameters(result["parameters"], adjustment)
    return result


def _contribution_identity(node, trim):
    parameters = trim["parameters"]
    source = parameters.get("source") or {}
    _require(isinstance(source, dict), "source mix trim source must be an object")
    return {
        "sourceId": parameters.get("sourceId"),
        "sourceSha256": source.get("sha256"),
        "streamIndex": source.get("streamIndex"),
        **{key: node.get(key) for key in ("sourceRange", "outputRange", "channelMap")},
    }


def _unique_actual_contribution(graph, nodes, node, base_operations):
    trim = next(op for op in base_operations if op["kind"] == "trim")
    expected = _contribution_identity(node, trim)
    matches = []
    for operation in graph["operations"]:
        if operation["kind"] != "trim":
            continue
        candidate = nodes.get(operation["parameters"].get("nodeId"))
        if candidate is not None and _same(
            _contribution_identity(candidate, operation), expected
        ):
            matches.append(candidate["nodeId"])
    _require(
        matches == [node["nodeId"]],
        "source mix target requires exactly one actual source contribution",
    )


def _check_actual(
    graph, nodes, node, base_operations, base_gain, expected, require_applied
):
    node_id = node["nodeId"]
    _require(
        _same(nodes.get(node_id), node),
        "actual source mix native node differs from BASE",
    )
    _unique_actual_contribution(graph, nodes, node, base_operations)
    operations = _node_operations(graph, node_id)
    gains = [op for op in operations if op["kind"] == "gain"]
    _require(len(gains) <= 1, "duplicate actual gain for source mix target")
    _require(
        _same(
            [op for op in operations if op["kind"] != "gain"],
            [op for op in base_operations if op["kind"] != "gain"],
        ),
        "actual source mix trim/resample/native operations differ from BASE",
    )
    required = expected if require_applied else base_gain
    _require(
        _same(gains, [required] if required else []),
        "actual source mix gain differs from expected BASE/application",
    )


def _install_gain(graph, node, base_gain, expected):
    if base_gain:
        index = next(
            i
            for i, op in enumerate(graph["operations"])
            if op["operationId"] == base_gain["operationId"]
        )
        graph["operations"][index] = expected
        return
    _require(
        all(op["operationId"] != expected["operationId"] for op in graph["operations"]),
        "source mix gain operationId collides",
    )
    index = max(
        i
        for i, op in enumerate(graph["operations"])
        if op["parameters"].get("nodeId") == node["nodeId"]
    )
    graph["operations"].insert(index + 1, expected)


def apply_source_mix_adjustments(
    cmap_snapshot, base_audio_graph, audio_graph, adjustments, *, require_applied=False
):
    """Apply BASE-relative gains once, or verify their exact already-applied form."""
    adjustments = validate_source_mix_adjustments(cmap_snapshot, adjustments)
    result = deepcopy(audio_graph)
    if not adjustments:
        return result
    base_nodes, _ = _graph_index(base_audio_graph)
    actual_nodes, _ = _graph_index(result)
    seen = set()
    for adjustment in adjustments:
        node, operations, gain = _base_target(
            cmap_snapshot, base_audio_graph, base_nodes, adjustment
        )
        _require(
            node["nodeId"] not in seen, "source mix placements overlap on one BASE node"
        )
        seen.add(node["nodeId"])
        expected = _expected_gain(node, gain, adjustment)
        _check_actual(
            result, actual_nodes, node, operations, gain, expected, require_applied
        )
        if not require_applied:
            _install_gain(result, node, gain, expected)
    return result
