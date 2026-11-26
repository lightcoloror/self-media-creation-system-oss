"""Checks for the encoded subtitle layer, using bound cues and decoded frames."""
import json
import re
import shutil
import subprocess
from pathlib import Path

from rough_cut_checks import bound, load

_THRESHOLDS_PATH = Path(__file__).resolve().parents[1] / "config/video-quality-thresholds.v1.json"


def _load_mobile_thresholds():
    if _THRESHOLDS_PATH.is_file():
        cfg = json.loads(_THRESHOLDS_PATH.read_text(encoding="utf-8")).get("mobile_subtitle", {})
        return int(cfg.get("min_glyph_px_at_270", 12)), int(cfg.get("reference_width_px", 270))
    return 12, 270


MIN_GLYPH_PX_AT_270, MOBILE_REF_WIDTH_PX = _load_mobile_thresholds()
DEFAULT_STYLES = {"dialogue", "subtitle", "subtitles", "default"}


def final_cues(manifest):
    config = manifest.get("final_subtitles") or manifest["subtitles"]
    pack = load(bound(config["pack_ref"]))
    if len(pack["requests"]) != 1:
        raise ValueError("final_caption_quality_requires_one_reviewed_subtitle_track")
    return config, pack["requests"][0]["subtitle_cues"]


def sample_times(cues):
    visible = [cue for cue in cues if any(char.isalnum() for char in cue["text"])]
    if not visible:
        return []
    indexes = {len(visible) * position // 4 for position in (1, 2, 3)}
    return sorted({round((visible[i]["start_seconds"] + visible[i]["end_seconds"]) / 2, 3) for i in indexes})


def _clock(text):
    h, m, s = text.strip().replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def burned_cues(path, styles):
    if path.suffix.lower() in {".srt", ".vtt"}:
        from video_knowledge_pipeline.transcript import parse_transcript
        return [(cue.start, cue.end, cue.text) for cue in parse_transcript(path)]
    if path.suffix.lower() != ".ass":
        raise ValueError("unsupported_final_subtitle_format")
    events = False
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("["):
            events = line.strip().casefold() == "[events]"
        if events and line.startswith("Format:"):
            fields = [key.strip().lower() for key in line.split(":", 1)[1].split(",")]
            if fields[-1] != "text" or not {"start", "end", "style"} <= set(fields):
                raise ValueError("unsupported_final_ass_event_format")
            break
    else:
        raise ValueError("final_ass_event_format_required")
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("Dialogue:"):
            event = dict(zip(fields, line.split(":", 1)[1].split(",", len(fields)-1)))
            if event["style"].strip().casefold() in styles:
                text = re.sub(r"\{[^}]*\}", "", event["text"]).replace(r"\N", " ").replace(r"\n", " ").replace(r"\h", " ")
                rows.append((_clock(event["start"]), _clock(event["end"]), text))
    return rows


def verify_burned_cues(path, cues, styles=DEFAULT_STYLES):
    observed = sorted(burned_cues(path, styles))
    expected = sorted((c["start_seconds"], c["end_seconds"], c["text"]) for c in cues)
    def text_key(text):
        return "".join(text.split())  # Permit visual wrapping while retaining punctuation.
    tolerance = .0051 if path.suffix.lower() == ".ass" else .0011
    if len(observed) != len(expected) or any(
            abs(a - p) > tolerance or abs(b - q) > tolerance or text_key(text) != text_key(reviewed)
            for (a, b, text), (p, q, reviewed) in zip(observed, expected)):
        raise ValueError("encoded_caption_punctuation_text_or_timing_differs_from_reviewed_cues")


def verify_mobile_samples(cues, frames, observed):
    from PIL import Image

    times = sample_times(cues)
    rows = observed.get("subtitle_glyph_samples", [])
    if not isinstance(rows, list) or [row["time_seconds"] for row in rows] != times:
        raise ValueError("decoded_mobile_subtitle_samples_required")
    actual = {row["time_seconds"]: row["frame_ref"] for row in frames}
    for row in rows:
        frame = actual.get(row["time_seconds"])
        if frame is None or row.get("frame_ref") != frame:
            raise ValueError("subtitle_glyph_measurement_not_from_current_decoded_frame")
        with Image.open(bound(frame)) as image:
            width, height = image.size
        box = row.get("glyph_box", [])
        if not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box):
            raise ValueError("subtitle_glyph_pixel_box_required")
        left, top, right, bottom = box
        if (not 0 <= left < right <= width or not 0 <= top < bottom <= height
                or (bottom-top)*MOBILE_REF_WIDTH_PX < MIN_GLYPH_PX_AT_270*width):
            raise ValueError("subtitle_glyph_below_mobile_minimum_or_outside_frame")


def check_edit_punctuation(source_cues, final_cues, segments, *, accepted_rebreaks=None):
    def text(cues):
        return "".join(char for cue in cues for char in cue["text"] if not char.isspace())

    def spoken(value):
        return "".join(char for char in value if char.isalnum())

    # Index explicit human-confirmed rebreaks at specific cuts (bound by cut_seconds + before/after text).
    rebreak_map = {}
    for row in accepted_rebreaks or ():
        if (isinstance(row, dict) and isinstance(row.get("reason"), str) and row["reason"].strip()
                and isinstance(row.get("source_text"), str) and isinstance(row.get("final_text"), str)
                and isinstance(row.get("cut_seconds"), (int, float))):
            rebreak_map[round(float(row["cut_seconds"]), 3)] = (
                "".join(row["source_text"].split()),
                "".join(row["final_text"].split()),
            )

    def _is_confirmed_rebreak(cut_s, orig_s, curr_s):
        pair = rebreak_map.get(round(cut_s, 3))
        return pair is not None and pair == (orig_s, curr_s)

    OPENING_PUNCT = set("“‘「『《（([【<")

    def _substring_punct_changed(orig_s, curr_s):
        """Detect dropped/changed punctuation even when curr_s merges in an extra cue outside the join."""
        sp_orig, sp_curr = spoken(orig_s), spoken(curr_s)
        if not sp_orig or sp_orig not in sp_curr:
            return False
        # Map each spoken char in curr_s back to its index in curr_s to slice exact corresponding span.
        pos = [i for i, ch in enumerate(curr_s) if ch.isalnum()]
        idx = sp_curr.find(sp_orig)
        start_i = pos[idx]
        end_i = pos[idx + len(sp_orig) - 1]
        # Left extension only absorbs opening quotes/brackets belonging to this span (never previous sentence's ending punct).
        start_ext = start_i
        while start_ext > 0 and curr_s[start_ext - 1] in OPENING_PUNCT:
            start_ext -= 1
        # Right extension absorbs trailing/closing punct of this span, stopping before opening punct of the next span.
        end_ext = end_i + 1
        while end_ext < len(curr_s) and not curr_s[end_ext].isalnum() and curr_s[end_ext] not in OPENING_PUNCT:
            end_ext += 1
        aligned_curr = curr_s[start_ext:end_ext]
        if orig_s and orig_s[0] in OPENING_PUNCT:
            return orig_s != aligned_curr
        return orig_s != curr_s[start_i:end_ext]

    for left, right in zip(segments, segments[1:]):
        cut = right["target_start"]
        join_source = []
        join_span_start, join_span_end = None, None
        for segment, boundary in ((left, left["source_end"]), (right, right["source_start"])):
            for cue in source_cues:
                start, end = cue["start_seconds"], cue["end_seconds"]
                if not (segment["source_start"] <= start < end <= segment["source_end"]
                        and min(abs(start - boundary), abs(end - boundary)) <= 1):
                    continue
                a = segment["target_start"] + (start - segment["source_start"]) / segment["speed"]
                b = segment["target_start"] + (end - segment["source_start"]) / segment["speed"]
                join_source.append((a, b, cue))
                join_span_start = a if join_span_start is None else min(join_span_start, a)
                join_span_end = b if join_span_end is None else max(join_span_end, b)
        if not join_source:
            continue
        join_source.sort(key=lambda item: item[0])
        merged_final = sorted(
            [
                row for row in final_cues
                if row["end_seconds"] > join_span_start + 0.02 and row["start_seconds"] < join_span_end - 0.02
            ],
            key=lambda row: row["start_seconds"],
        )
        orig_joined = text([item[2] for item in join_source])
        curr_joined = text(merged_final)
        if _is_confirmed_rebreak(cut, orig_joined, curr_joined):
            continue
        for a, b, cue in join_source:
            overlapping = [
                row for row in final_cues
                if row["end_seconds"] > a + 0.02 and row["start_seconds"] < b - 0.02
            ]
            original, current = text([cue]), text(overlapping)
            if _is_confirmed_rebreak(cut, original, current):
                continue
            if original != current and (
                (spoken(original) and spoken(original) == spoken(current))
                or _substring_punct_changed(original, current)
            ):
                raise ValueError("caption_punctuation_changed_at_retained_edit_join: " + str(round(cut, 3)))
        if len(join_source) >= 2 and orig_joined != curr_joined and (
            (spoken(orig_joined) and spoken(orig_joined) == spoken(curr_joined))
            or _substring_punct_changed(orig_joined, curr_joined)
        ):
            raise ValueError("caption_punctuation_changed_at_retained_edit_join: " + str(round(cut, 3)))


_TERMINAL_SINKS = {"nullsink", "anullsink"}
_AUDIO_ONLY_FILTERS = {
    "anull", "acopy", "amix", "amerge", "volume", "loudnorm", "atempo", "afade", "adelay",
    "aresample", "aformat", "alimiter", "acompressor", "acrossfade", "asplit", "asetpts",
    "atrim", "apad", "dynaudnorm", "sidechaincompress", "pan", "channelsplit", "channelmap",
    "highpass", "lowpass", "bandpass", "equalizer", "afftdn", "speechnorm", "silencedetect",
    "silenceremove", "anullsrc", "aevalsrc", "sine", "anoisesrc", "aemphasis", "agate",
    "aloop", "amultiply", "apulsator", "areverse", "asetrate", "ashowinfo", "astats",
}
_AUDIO_TO_VIDEO_FILTERS = {
    "showwaves", "showwavespic", "showspectrum", "showspectrumpic", "avectorscope",
    "ahistogram", "showfreqs", "showcqt", "showvolume", "abitscope", "aphasemeter",
}
_VIDEO_ONLY_FILTERS = {
    "ass", "subtitles", "null", "copy", "scale", "scale2ref", "fps", "format", "overlay",
    "drawtext", "drawbox", "drawgrid", "crop", "pad", "trim", "setpts", "split", "color",
    "nullsrc", "testsrc", "testsrc2", "rgbtestsrc", "smptebars", "fade", "hflip", "vflip",
    "transpose", "rotate", "eq", "lut", "lutrgb", "lutyuv", "gblur", "boxblur", "unsharp",
    "colorkey", "chromakey", "alphamerge", "vstack", "hstack", "xstack", "xfade", "setsar",
    "setdar", "yadif", "bwdif", "zscale", "tonemap", "lut3d", "vignette", "negate", "hue",
    "colorbalance", "curves", "geq", "zoompan", "loop", "tpad", "fifo", "select",
    "framerate", "minterpolate", "hwupload", "hwdownload", "scale_cuda", "overlay_cuda",
}
# Closed-world controlled render template contract:
# 1. Runtime command/control filters are forbidden anywhere in the command (pre- or post-burn).
_FORBIDDEN_RUNTIME_FILTERS = {"sendcmd", "asendcmd", "zmq", "azmq", "cue", "acue"}
# 2. Timestamp/cadence-mutating filters before caption burn can desync ASS clock vs encoded frames.
_PRE_BURN_FORBIDDEN_FILTERS = {
    "setpts", "trim", "select", "tpad", "loop", "reverse",
    "framestep", "decimate", "mpdecimate", "settb", "fps",
}
# 3. After caption burn (or when preserving a previously burned video), ONLY zero-draw,
#    geometry-preserving, frame-identity passthrough filters are permitted — unless the stage
#    is an official byte-verified progress_overlay filtergraph script.
_POST_BURN_PASSTHROUGH_FILTERS = {
    "null", "copy", "fifo", "format", "split",
    "hwupload", "hwdownload", "hwupload_cuda",
}
_VERIFIED_PROGRESS_FILTERS = {"overlay", "drawtext"}
_SOURCE_FILTERS = {
    "color", "nullsrc", "testsrc", "testsrc2", "rgbtestsrc", "smptebars", "smptehdbars",
    "anullsrc", "aevalsrc", "sine", "anoisesrc",
}
# CLI flags that truncate, seek, loop, or shift stream timestamps (disallowed on both fresh burn and preservation).
_TIMELINE_MUTATING_FLAGS = {
    "-ss", "-t", "-to", "-sseof", "-vframes", "-stream_loop", "-itsoffset", "-itsscale",
}
_TIMELINE_MUTATING_PREFIXES = ("-frames",)
_ZERO_ARG_FLAGS = {
    "-y", "-n", "-nostdin", "-stdin", "-hide_banner", "-vn", "-an", "-sn", "-dn", "-mn",
    "-shortest", "-re", "-stats", "-nostats", "-copyts", "-start_at_zero",
    "-ignore_unknown", "-fix_sub_duration", "-accurate_seek", "-noaccurate_seek",
    "-copyinkf", "-benchmark", "-benchmark_all", "-report", "-xerror", "-psnr",
    "-dump", "-hex", "-bitexact", "-nobitexact", "-autoscale", "-noautoscale",
    "-find_stream_info", "-nofind_stream_info", "-recast_media", "-norecast_media",
    "-drop_changed", "-vstats", "-qphist",
}
_VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".ts", ".m4v", ".flv"}
_PROBE_CACHE = {}
_LAVFI_PROBE_CACHE = {}


def _extract_filter_expressions(command):
    """Yield actual FFmpeg video-capable filter values (-vf/-filter/-filter_complex/-lavfi)."""
    if not isinstance(command, list):
        return
    i = 1 if (command and isinstance(command[0], str) and not command[0].startswith("-")) else 0
    while i < len(command):
        tok = command[i]
        if not isinstance(tok, str):
            i += 1
            continue
        if tok in _ZERO_ARG_FLAGS or not tok.startswith("-") or len(tok) == 1:
            i += 1
            continue
        if i + 1 >= len(command) or not isinstance(command[i + 1], str):
            break
        val = command[i + 1]
        if tok in ("-filter_complex", "-lavfi") or tok == "-vf" or tok.startswith("-vf:"):
            yield val
        elif tok == "-filter" or tok.startswith("-filter:"):
            spec = tok[len("-filter:"):] if tok.startswith("-filter:") else ""
            if not (spec and spec[0] in ("a", "s", "d", "t") and (len(spec) == 1 or spec[1] == ":")):
                yield val
        i += 2


def _split_top_level(expr, sep):
    """Split FFmpeg filtergraph by top-level separator (';', ',', or ':'), respecting quotes & escapes."""
    parts, buf, quote, esc = [], [], None, False
    for ch in expr:
        if esc:
            buf.append(ch); esc = False; continue
        if ch == "\\" and quote != "'":
            buf.append(ch); esc = True; continue
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch; buf.append(ch); continue
        if ch == sep:
            parts.append("".join(buf)); buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _split_filter_nodes(expr):
    """Split an FFmpeg filtergraph into individual filter invocations, respecting single/double quotes."""
    nodes = []
    for chain in _split_top_level(expr, ";"):
        nodes.extend(_split_top_level(chain, ","))
    return nodes


def _strip_outer_pads(node):
    """Strip leading and unquoted trailing [pad] labels from a filter node."""
    s = re.sub(r"^\s*(?:\[[^\]]+\]\s*)+", "", node.strip())
    if s and s[-1] not in ("'", '"'):
        s = re.sub(r"(?:\s*\[[^\]]+\])+\s*$", "", s)
    return s.strip()


def _filter_name(node):
    """Extract lowercase base filter name (without @instance or =args)."""
    body = _strip_outer_pads(node)
    match = re.match(r"^([A-Za-z0-9_]+)(?:@[A-Za-z0-9_]+)?(?:\s*=|$)", body)
    return match.group(1).lower() if match else ""


def _unquote_ffmpeg_val(raw_val):
    s = raw_val.strip()
    if len(s) >= 2 and s[0] == s[-1] == '"' and "'" not in s:
        s = s[1:-1]
    out, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "'":
            i += 1
            while i < n and s[i] != "'":
                out.append(s[i])
                i += 1
            if i < n and s[i] == "'":
                i += 1
        elif ch == "\\" and i + 1 < n:
            out.append(s[i + 1])
            i += 2
        else:
            out.append(ch)
            i += 1
    val = "".join(out)
    return val.replace(r"\:", ":").replace(r"\'", "'").replace(r"\\", "\\")


def _node_references_caption(node, path, cwd=None):
    """Check one filter node for an active subtitles=/ass= burn matching path (rejects enable=/si= overrides)."""
    target = path.resolve()
    body = _strip_outer_pads(node)
    match = re.match(r"^(?:subtitles|ass)(?:@[A-Za-z0-9_]+)?=(.+)$", body)
    if not match:
        return False
    opts = _split_top_level(match.group(1), ":")
    raw_val = None
    for opt in opts:
        # Reject timeline enable= gating on subtitle filters (could disable captions over part/all of video).
        if re.match(r"^\s*enable\s*=", opt, re.I):
            return False
        m_si = re.match(r"^\s*(?:si|stream_index)\s*=(.*)$", opt, re.I)
        if m_si and _unquote_ffmpeg_val(m_si.group(1)).strip() not in ("0", ""):
            return False
        named = re.match(r"^\s*(?:filename|f)\s*=(.+)$", opt, re.I)
        if named:
            raw_val = named.group(1)  # Last filename=/f= wins per FFmpeg option parsing.
    if raw_val is None and opts and not re.match(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=", opts[0]):
        raw_val = opts[0]
    if not raw_val:
        return False
    decoded = _unquote_ffmpeg_val(raw_val)
    if not decoded:
        return False
    cand = Path(decoded)
    if not cand.is_absolute():
        if not cwd:
            return False
        cand = Path(cwd) / cand
    try:
        return cand.resolve() == target
    except OSError:
        return False


def _arg_references_caption(arg, path, cwd=None):
    """Parse exact subtitles=/ass= filter node filename argument (ignores drawtext or other filters)."""
    return any(_node_references_caption(node, path, cwd=cwd) for node in _split_filter_nodes(arg))


def _parse_filter_opts(node):
    """Parse a filter node into (name, positional_args, named_args_dict)."""
    body = _strip_outer_pads(node)
    name = _filter_name(body)
    if "=" not in body:
        return name, [], {}
    args_str = body.split("=", 1)[1]
    pos, named = [], {}
    for opt in _split_top_level(args_str, ":"):
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", opt, re.DOTALL)
        if m:
            named[m.group(1).strip().lower()] = _unquote_ffmpeg_val(m.group(2))
        elif opt.strip():
            pos.append(_unquote_ffmpeg_val(opt))
    return name, pos, named


def _expr_has_forbidden_runtime_filter(expr):
    """Return True if any filter node in expr is a runtime command/control filter (sendcmd/zmq/cue)."""
    return any(_filter_name(node) in _FORBIDDEN_RUNTIME_FILTERS for node in _split_filter_nodes(expr))


def _command_has_forbidden_runtime_filter(command, loaded_scripts=()):
    """Scan all filter options in command (video, audio, complex, and bound scripts) for runtime command filters."""
    for expr in loaded_scripts:
        if _expr_has_forbidden_runtime_filter(expr):
            return True
    i = 1 if (command and isinstance(command[0], str) and not command[0].startswith("-")) else 0
    while i < len(command):
        tok = command[i]
        if not isinstance(tok, str):
            i += 1
            continue
        if tok in _ZERO_ARG_FLAGS or not tok.startswith("-") or len(tok) == 1:
            i += 1
            continue
        if i + 1 >= len(command) or not isinstance(command[i + 1], str):
            break
        val = command[i + 1]
        if (
            tok in ("-vf", "-af", "-filter", "-filter_complex", "-lavfi")
            or tok.startswith(("-vf:", "-af:", "-filter:"))
        ):
            if _expr_has_forbidden_runtime_filter(val):
                return True
        elif tok == "-filter_script" or tok.startswith("-filter_script:"):
            return True
        i += 2
    return False


def _node_safe_post_burn(node, *, is_verified_progress=False):
    """Closed-world post-burn check: only pure identity passthroughs or official verified progress_overlay."""
    nm, _pos, named = _parse_filter_opts(node)
    if nm in _FORBIDDEN_RUNTIME_FILTERS:
        return False
    if nm in ("ass", "subtitles"):
        return "enable" not in named
    if nm in _POST_BURN_PASSTHROUGH_FILTERS:
        return "enable" not in named
    if is_verified_progress and nm in _VERIFIED_PROGRESS_FILTERS:
        return True
    return False


def _vf_expr_burns_caption(expr, path, cwd=None):
    """Verify a per-stream -vf/-filter expression burns path under the closed-world template contract."""
    if path is None or _expr_has_forbidden_runtime_filter(expr):
        return False
    chains = [c.strip() for c in _split_top_level(expr, ";") if c.strip()]
    if len(chains) != 1:
        return False
    nodes = [n.strip() for n in _split_top_level(chains[0], ",") if n.strip()]
    burn_idx = max((idx for idx, n in enumerate(nodes) if _node_references_caption(n, path, cwd=cwd)), default=-1)
    if burn_idx < 0:
        return False
    for j, node in enumerate(nodes):
        if j < burn_idx and _filter_name(node) in (_PRE_BURN_FORBIDDEN_FILTERS | _FORBIDDEN_RUNTIME_FILTERS):
            return False
        if j > burn_idx and not _node_safe_post_burn(node):
            return False
    return True


def _vf_expr_preserves_caption(expr):
    """Verify a per-stream -vf/-filter expression preserves an already-burned input via identity passthroughs only."""
    if _expr_has_forbidden_runtime_filter(expr):
        return False
    chains = [c.strip() for c in _split_top_level(expr, ";") if c.strip()]
    if len(chains) != 1:
        return False
    nodes = [n.strip() for n in _split_top_level(chains[0], ",") if n.strip()]
    if not nodes:
        return False
    return all(_node_safe_post_burn(node) for node in nodes)


def _spec_matches_video_stream(opt_kind, spec, out_lo, out_hi, v_idx, *, attached_pic=False, v_nonpic_idx=None):
    """Return 'definite', 'none', or 'ambiguous' for whether a per-stream specifier matches a video output."""
    if opt_kind in ("vf", "vcodec"):
        return "definite"
    spec = (spec or "").strip()
    if spec == "":
        return "definite"
    if re.fullmatch(r"\d+", spec):
        idx = int(spec)
        if out_lo is not None and out_hi is not None and out_lo == out_hi == idx:
            return "definite"
        if (out_lo is not None and idx < out_lo) or (out_hi is not None and idx > out_hi):
            return "none"
        return "ambiguous"
    if spec[0] in ("a", "s", "d", "t") and (len(spec) == 1 or spec[1] == ":"):
        return "none"
    if spec[0] in ("v", "V"):
        if spec[0] == "V" and attached_pic:
            return "none"
        target_v_idx = v_nonpic_idx if (spec[0] == "V" and v_nonpic_idx is not None) else v_idx
        if len(spec) == 1:
            return "definite"
        if spec[1] == ":":
            rest = spec[2:]
            if rest == "":
                return "definite"
            if re.fullmatch(r"\d+", rest):
                if target_v_idx is None:
                    return "ambiguous"
                return "definite" if int(rest) == target_v_idx else "none"
            return "ambiguous"
    return "ambiguous"


def _infer_direct_media_type(node_names):
    """Infer chain output media type from filter names alone ('video', 'audio', or None to defer)."""
    if any(name in _AUDIO_TO_VIDEO_FILTERS for name in node_names):
        return "video"
    if any(name in _VIDEO_ONLY_FILTERS for name in node_names):
        return "video"
    if any(name in _AUDIO_ONLY_FILTERS for name in node_names):
        return "audio"
    return None


def _parse_int_opt(node_body, key, default, positional=False):
    if "=" not in node_body:
        return default
    args = node_body.split("=", 1)[1]
    opts = _split_top_level(args, ":")
    for opt in opts:
        m = re.match(rf"^\s*{re.escape(key)}=(\d+)\s*$", opt)
        if m:
            return int(m.group(1))
    if positional and opts and re.fullmatch(r"\s*\d+\s*", opts[0]):
        return int(opts[0].strip())
    return default


def _parse_complex_graph(graph_expr, path, cwd=None, *, is_verified_progress=False):
    """Parse one -filter_complex/-lavfi graph into labeled pad definitions and unlabeled outputs."""
    pad_defs = {}
    unlabeled_outputs = []
    for chain in _split_top_level(graph_expr, ";"):
        chain_s = chain.strip()
        if not chain_s:
            continue
        lead = re.match(r"^((?:\[[^\]]+\]\s*)+)", chain_s)
        in_pads = re.findall(r"\[([^\]]+)\]", lead.group(1)) if lead else []
        body_s = chain_s[lead.end():] if lead else chain_s
        out_pads = []
        if body_s and body_s[-1] not in ("'", '"'):
            trail = re.search(r"((?:\s*\[[^\]]+\])+)\s*$", body_s)
            if trail:
                out_pads = re.findall(r"\[([^\]]+)\]", trail.group(1))
                body_s = body_s[:trail.start()]
        nodes = [n.strip() for n in _split_top_level(body_s, ",") if n.strip()]
        node_names = [_filter_name(n) for n in nodes]
        if not node_names:
            return None
        last_name = node_names[-1]
        if not out_pads and last_name in _TERMINAL_SINKS:
            continue
        burn_idx = (
            max((idx for idx, n in enumerate(nodes) if _node_references_caption(n, path, cwd=cwd)), default=-1)
            if path is not None else -1
        )
        implicit_input = bool(not in_pads and node_names[0] not in _SOURCE_FILTERS)
        base_entry = {
            "in_pads": in_pads,
            "nodes": nodes,
            "node_names": node_names,
            "burn_idx": burn_idx,
            "implicit_input": implicit_input,
            "is_verified_progress": is_verified_progress,
        }
        if last_name == "concat":
            v_cnt = _parse_int_opt(_strip_outer_pads(nodes[-1]), "v", 1)
            a_cnt = _parse_int_opt(_strip_outer_pads(nodes[-1]), "a", 0)
            slots = ["video"] * v_cnt + ["audio"] * a_cnt
            if out_pads:
                for idx, op in enumerate(out_pads):
                    if op in pad_defs:
                        return None
                    st = slots[idx] if idx < len(slots) else "unknown"
                    pad_defs[op] = dict(base_entry, media_type=st)
            else:
                for st in slots:
                    unlabeled_outputs.append(dict(base_entry, media_type=st))
        elif not out_pads and last_name in ("split", "asplit"):
            cnt = _parse_int_opt(_strip_outer_pads(nodes[-1]), "outputs", 2, positional=True)
            st = "audio" if last_name == "asplit" else "video"
            for _ in range(max(cnt, 1)):
                unlabeled_outputs.append(dict(base_entry, media_type=st))
        else:
            direct_type = _infer_direct_media_type(node_names)
            if out_pads:
                for op in out_pads:
                    if op in pad_defs:
                        return None
                    pad_defs[op] = dict(base_entry, media_type=direct_type)
            else:
                unlabeled_outputs.append(dict(base_entry, media_type=direct_type))
    return pad_defs, unlabeled_outputs


def _resolve_fc_media_type(item, pad_defs, resolved_inputs=None, visiting=None):
    if item["media_type"] is not None:
        return item["media_type"]
    visiting = set() if visiting is None else visiting
    in_types = []
    for p in item["in_pads"]:
        if p in pad_defs:
            if p in visiting:
                in_types.append("unknown")
            else:
                in_types.append(_resolve_fc_media_type(pad_defs[p], pad_defs, resolved_inputs, visiting | {p}))
        elif re.fullmatch(r"\d+:[vV](?::\S*)?", p):
            in_types.append("video")
        elif re.fullmatch(r"\d+:a(?::\S*)?", p):
            in_types.append("audio")
        else:
            m_num = re.fullmatch(r"(\d+):(\d+)", p)
            if m_num and resolved_inputs is not None:
                in_i, s_i = int(m_num.group(1)), int(m_num.group(2))
                if 0 <= in_i < len(resolved_inputs) and resolved_inputs[in_i] is not None:
                    matched = [s for s in resolved_inputs[in_i] if s["index"] == s_i]
                    if matched:
                        in_types.append(matched[0]["codec_type"])
                        continue
            in_types.append("unknown")
    if in_types:
        if all(t == "audio" for t in in_types):
            return "audio"
        if any(t == "video" for t in in_types):
            return "video"
    return "unknown"


def _fc_upstream_clean_for_burn(in_pads, pad_defs, visiting=None):
    """Ensure upstream chains feeding a fresh burn contain no timestamp-mutating or runtime-command filters."""
    visiting = set() if visiting is None else visiting
    for p in in_pads:
        if p not in pad_defs:
            continue
        if p in visiting:
            return False
        up = pad_defs[p]
        if any(nm in (_PRE_BURN_FORBIDDEN_FILTERS | _FORBIDDEN_RUNTIME_FILTERS) for nm in up["node_names"]):
            return False
        if not _fc_upstream_clean_for_burn(up["in_pads"], pad_defs, visiting | {p}):
            return False
    return True


def _fc_item_reaches_caption(
    item,
    pad_defs,
    *,
    burned_input_indices=frozenset(),
    all_video_inputs_burned=False,
    visiting=None,
):
    """Closed-world check: chain freshly burns caption (with clean upstream & identity post-burn) or safely preserves burned input."""
    visiting = set() if visiting is None else visiting
    nodes = item["nodes"]
    in_pads = item["in_pads"]
    burn_idx = item["burn_idx"]
    is_prog = bool(item.get("is_verified_progress"))

    # Case 1: Caption freshly burned inside this chain.
    if burn_idx >= 0:
        if not _fc_upstream_clean_for_burn(in_pads, pad_defs):
            return False
        for j, node in enumerate(nodes):
            if j < burn_idx and _filter_name(node) in (_PRE_BURN_FORBIDDEN_FILTERS | _FORBIDDEN_RUNTIME_FILTERS):
                return False
            if j > burn_idx and not _node_safe_post_burn(node, is_verified_progress=is_prog):
                return False
        return True

    # Case 2: Preserve captions from upstream pad(s) via identity passthrough or official verified progress_overlay.
    for node in nodes:
        if not _node_safe_post_burn(node, is_verified_progress=is_prog):
            return False

    if not in_pads:
        return bool(item.get("implicit_input") and all_video_inputs_burned)

    if len(in_pads) == 1:
        parent_pad = in_pads[0]
    elif is_prog and any(nm == "overlay" for nm in item["node_names"]):
        parent_pad = in_pads[0]
    else:
        return False

    if parent_pad in pad_defs:
        if parent_pad in visiting:
            return False
        return _fc_item_reaches_caption(
            pad_defs[parent_pad],
            pad_defs,
            burned_input_indices=burned_input_indices,
            all_video_inputs_burned=all_video_inputs_burned,
            visiting=visiting | {parent_pad},
        )
    m_in = re.fullmatch(r"(\d+)(?::\S+)?", parent_pad)
    return bool(m_in and int(m_in.group(1)) in burned_input_indices)


def _resolve_ffprobe(command):
    if command and isinstance(command[0], str):
        exe = Path(command[0])
        if exe.parent != Path("."):
            for name in ("ffprobe.exe", "ffprobe"):
                sib = exe.parent / name
                if sib.is_file():
                    return str(sib)
    found = shutil.which("ffprobe")
    if found:
        return found
    try:
        from rough_cut_checks import _mvp
        return _mvp().resolve_media_tool("ffprobe")
    except Exception:
        return None


def _normalize_probed_streams(raw_streams):
    streams = []
    for row in sorted(raw_streams, key=lambda r: int(r.get("index", 0))):
        ct = str(row.get("codec_type", "other")).lower()
        if ct not in ("video", "audio", "subtitle", "data", "attachment"):
            ct = "other"
        disp = row.get("disposition") or {}
        streams.append({
            "index": int(row.get("index", len(streams))),
            "codec_type": ct,
            "attached_pic": bool(disp.get("attached_pic", 0)),
        })
    return streams


def _probe_file_streams(media_path, command):
    resolved = media_path.resolve()
    try:
        st = resolved.stat()
    except OSError:
        return None
    cache_key = (str(resolved), st.st_mtime_ns, st.st_size)
    if cache_key in _PROBE_CACHE:
        return _PROBE_CACHE[cache_key]
    ffprobe = _resolve_ffprobe(command)
    if not ffprobe:
        return None
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error",
             "-show_entries", "stream=index,codec_type:stream_disposition=attached_pic",
             "-of", "json", str(resolved)],
            capture_output=True, text=True, check=True, timeout=15,
        )
        raw_streams = json.loads(proc.stdout).get("streams", [])
    except Exception:
        return None
    streams = _normalize_probed_streams(raw_streams)
    _PROBE_CACHE[cache_key] = streams
    return streams


def _probe_lavfi_streams(spec, command):
    """Probe exact stream table of a -f lavfi input via ffprobe (handles multi-stream [out0];[out1] graphs)."""
    if spec in _LAVFI_PROBE_CACHE:
        return _LAVFI_PROBE_CACHE[spec]
    ffprobe = _resolve_ffprobe(command)
    if not ffprobe:
        return None
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-f", "lavfi", "-i", spec,
             "-show_entries", "stream=index,codec_type:stream_disposition=attached_pic",
             "-of", "json"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        raw_streams = json.loads(proc.stdout).get("streams", [])
    except Exception:
        return None
    streams = _normalize_probed_streams(raw_streams)
    _LAVFI_PROBE_CACHE[spec] = streams
    return streams


def _resolve_input_streams(inputs, command, cwd=None, bound_inputs=None):
    """Resolve exact input stream lists for each -i input via ffprobe (for both files and lavfi graphs)."""
    resolved = []
    for entry in inputs:
        if entry["fmt"] == "lavfi":
            resolved.append(_probe_lavfi_streams(entry["path"], command))
            continue
        cand = Path(entry["path"])
        if not cand.is_absolute():
            if not cwd:
                resolved.append(None)
                continue
            cand = Path(cwd) / cand
        try:
            cand_res = cand.resolve()
        except OSError:
            resolved.append(None)
            continue
        if bound_inputs is not None and cand_res not in bound_inputs:
            # Formal receipt check: refuse to trust stream layout of an unbound file on disk.
            resolved.append(None)
            continue
        if cand_res.is_file():
            resolved.append(_probe_file_streams(cand_res, command))
        else:
            resolved.append(None)
    return resolved


def _match_input_streams(streams, spec):
    """Match an FFmpeg input stream specifier (without leading input index) against a probed stream list."""
    if spec == "":
        return list(streams)
    if re.fullmatch(r"\d+", spec):
        idx = int(spec)
        return [s for s in streams if s["index"] == idx]
    m = re.fullmatch(r"([vVasdt])(?::(\d+))?", spec)
    if not m:
        return None  # Unsupported complex specifier (e.g. metadata/program): fail closed.
    tcode, sub_str = m.group(1), m.group(2)
    if tcode == "v":
        cand = [s for s in streams if s["codec_type"] == "video"]
    elif tcode == "V":
        cand = [s for s in streams if s["codec_type"] == "video" and not s["attached_pic"]]
    elif tcode == "a":
        cand = [s for s in streams if s["codec_type"] == "audio"]
    elif tcode == "s":
        cand = [s for s in streams if s["codec_type"] == "subtitle"]
    elif tcode == "d":
        cand = [s for s in streams if s["codec_type"] == "data"]
    else:
        cand = [s for s in streams if s["codec_type"] == "attachment"]
    if sub_str is None:
        return cand
    k = int(sub_str)
    return [cand[k]] if 0 <= k < len(cand) else []


def _is_timeline_mutating_flag(tok):
    if tok in _TIMELINE_MUTATING_FLAGS:
        return True
    for pref in _TIMELINE_MUTATING_PREFIXES:
        if tok == pref:
            return True
        if tok.startswith(pref + ":"):
            spec = tok[len(pref) + 1:]
            if not (spec and spec[0] in ("a", "s", "d", "t") and (len(spec) == 1 or spec[1] == ":")):
                return True
    return False


def _parse_ffmpeg_command_segments(command):
    """Segment an FFmpeg command into global complex graphs, inputs, and per-output option blocks."""
    inputs = []
    complex_graphs = []
    outputs = []

    cur_fmt = None
    cur_maps = []
    cur_filters = []
    cur_codecs = []
    cur_vn = False
    cur_an = False
    cur_sn = False
    cur_dn = False
    cur_timeline_mutated = False

    def _reset_cur():
        nonlocal cur_fmt, cur_maps, cur_filters, cur_codecs, cur_vn, cur_an, cur_sn, cur_dn, cur_timeline_mutated
        cur_fmt = None
        cur_maps = []
        cur_filters = []
        cur_codecs = []
        cur_vn = False
        cur_an = False
        cur_sn = False
        cur_dn = False
        cur_timeline_mutated = False

    i = 1 if (isinstance(command[0], str) and not command[0].startswith("-")) else 0
    while i < len(command):
        tok = command[i]
        if not isinstance(tok, str):
            return None
        if tok == "-filter_complex_script":
            if i + 1 >= len(command) or not isinstance(command[i + 1], str):
                return None
            complex_graphs.append(("script", command[i + 1]))
            i += 2
            continue
        if tok in ("-filter_complex", "-lavfi"):
            if i + 1 >= len(command) or not isinstance(command[i + 1], str):
                return None
            complex_graphs.append(("inline", command[i + 1]))
            i += 2
            continue
        if tok == "-i":
            if i + 1 >= len(command) or not isinstance(command[i + 1], str):
                return None
            inputs.append({"fmt": cur_fmt, "path": command[i + 1], "timeline_mutated": cur_timeline_mutated})
            _reset_cur()
            i += 2
            continue
        if tok == "-f":
            if i + 1 >= len(command) or not isinstance(command[i + 1], str):
                return None
            cur_fmt = command[i + 1].strip().lower()
            i += 2
            continue
        if tok == "-vn":
            cur_vn = True
            i += 1
            continue
        if tok == "-an":
            cur_an = True
            i += 1
            continue
        if tok == "-sn":
            cur_sn = True
            i += 1
            continue
        if tok == "-dn":
            cur_dn = True
            i += 1
            continue
        if tok == "-map":
            if i + 1 >= len(command) or not isinstance(command[i + 1], str):
                return None
            cur_maps.append(command[i + 1].strip())
            i += 2
            continue
        if tok == "-vf" or tok.startswith("-vf:"):
            if i + 1 >= len(command) or not isinstance(command[i + 1], str):
                return None
            cur_filters.append(("vf", "v", command[i + 1]))
            i += 2
            continue
        if tok == "-filter" or tok.startswith("-filter:"):
            if i + 1 >= len(command) or not isinstance(command[i + 1], str):
                return None
            spec = tok[len("-filter:"):] if tok.startswith("-filter:") else ""
            cur_filters.append(("filter", spec, command[i + 1]))
            i += 2
            continue
        if tok == "-filter_script" or tok.startswith("-filter_script:"):
            if i + 1 >= len(command) or not isinstance(command[i + 1], str):
                return None
            spec = tok[len("-filter_script:"):] if tok.startswith("-filter_script:") else ""
            cur_filters.append(("filter_script", spec, command[i + 1]))
            i += 2
            continue
        if tok == "-vcodec":
            if i + 1 >= len(command) or not isinstance(command[i + 1], str):
                return None
            cur_codecs.append(("vcodec", "v", command[i + 1].strip().lower()))
            i += 2
            continue
        if tok in ("-c", "-codec") or tok.startswith("-c:") or tok.startswith("-codec:"):
            if i + 1 >= len(command) or not isinstance(command[i + 1], str):
                return None
            spec = tok.split(":", 1)[1] if ":" in tok else ""
            cur_codecs.append(("codec", spec, command[i + 1].strip().lower()))
            i += 2
            continue
        if tok in _ZERO_ARG_FLAGS:
            i += 1
            continue
        if tok.startswith("-") and len(tok) > 1:
            if i + 1 >= len(command) or not isinstance(command[i + 1], str):
                return None
            if _is_timeline_mutating_flag(tok):
                cur_timeline_mutated = True
            i += 2
            continue
        # Positional argument (or bare "-" stdout) after inputs delimits an output file.
        outputs.append({
            "path": tok,
            "maps": cur_maps,
            "filters": cur_filters,
            "codecs": cur_codecs,
            "vn": cur_vn,
            "an": cur_an,
            "sn": cur_sn,
            "dn": cur_dn,
            "timeline_mutated": cur_timeline_mutated,
        })
        _reset_cur()
        i += 1

    return inputs, complex_graphs, outputs


def _evaluate_output_block(
    out_block,
    *,
    is_first_output,
    unlabeled_fc_streams,
    all_labeled_pads,
    duplicate_labels,
    inputs,
    resolved_inputs,
    path,
    cwd=None,
    burned_input_indices=frozenset(),
    all_video_inputs_burned=False,
):
    """Evaluate one output block, returning (valid, has_guaranteed_video, has_any_video, all_videos_verified)."""
    out_streams = list(unlabeled_fc_streams) if is_first_output else []
    maps = out_block["maps"]

    if maps:
        has_positive_map = False
        for raw_map in maps:
            if not raw_map:
                return False, False, False, False
            if raw_map.startswith("-"):
                neg = raw_map[1:].rstrip("?")
                m_neg_full = re.fullmatch(r"(\d+)(?::(\S+))?", neg)
                if not m_neg_full:
                    return False, False, False, False
                neg_in = int(m_neg_full.group(1))
                neg_sub = m_neg_full.group(2) or ""
                if not (0 <= neg_in < len(resolved_inputs)):
                    return False, False, False, False
                probed = resolved_inputs[neg_in]
                if probed is not None:
                    matched = _match_input_streams(probed, neg_sub)
                    if matched is None:
                        return False, False, False, False
                    excl_ids = {s["index"] for s in matched}
                    out_streams = [
                        st for st in out_streams
                        if not (st["source"] == "input_map" and st.get("input_idx") == neg_in
                                and st.get("src_stream_idx") in excl_ids)
                    ]
                else:
                    m_simple = re.fullmatch(r"(\d+)(?::([vVasdt]))?", neg)
                    if not m_simple:
                        return False, False, False, False
                    neg_type = m_simple.group(2)
                    type_map = {"v": "video", "V": "video", "a": "audio", "s": "subtitle", "d": "data", "t": "attachment"}
                    kept = []
                    for st in out_streams:
                        if st["source"] != "input_map" or st.get("input_idx") != neg_in:
                            kept.append(st)
                            continue
                        if neg_type is None:
                            continue
                        if st["media_type"] == type_map[neg_type]:
                            if neg_type in ("v", "V") and st["from_whole_input"]:
                                kept.append(dict(st, media_type="other", count_lo=0, count_hi=None, grouped_video=False))
                            continue
                        kept.append(st)
                    out_streams = kept
                continue

            has_positive_map = True
            if raw_map.startswith("[") and raw_map.endswith("]") and len(raw_map) > 2:
                label = raw_map[1:-1]
                if label in duplicate_labels or label not in all_labeled_pads:
                    return False, False, False, False
                info, pad_defs = all_labeled_pads[label]
                out_streams.append({
                    "source": "filter_complex",
                    "media_type": _resolve_fc_media_type(info, pad_defs, resolved_inputs),
                    "fc_burns_caption": _fc_item_reaches_caption(
                        info, pad_defs,
                        burned_input_indices=burned_input_indices,
                        all_video_inputs_burned=all_video_inputs_burned,
                    ),
                    "fc_fresh_burn": _fc_item_reaches_caption(
                        info, pad_defs,
                    ),
                    "count_lo": 1,
                    "count_hi": 1,
                    "from_whole_input": False,
                    "grouped_video": False,
                    "attached_pic": False,
                })
                continue

            opt = raw_map.endswith("?")
            spec = raw_map[:-1] if opt else raw_map
            m_in = re.fullmatch(r"(\d+)(?::(\S+))?", spec)
            if not m_in:
                return False, False, False, False
            in_idx = int(m_in.group(1))
            sub_spec = m_in.group(2) or ""
            if resolved_inputs and not (0 <= in_idx < len(resolved_inputs)):
                return False, False, False, False
            probed = resolved_inputs[in_idx] if (0 <= in_idx < len(resolved_inputs)) else None

            if probed is not None:
                matched = _match_input_streams(probed, sub_spec)
                if matched is None:
                    return False, False, False, False
                if not matched:
                    if opt:
                        continue
                    return False, False, False, False
                for ms in matched:
                    out_streams.append({
                        "source": "input_map",
                        "input_idx": in_idx,
                        "src_stream_idx": ms["index"],
                        "media_type": ms["codec_type"],
                        "count_lo": 1,
                        "count_hi": 1,
                        "from_whole_input": False,
                        "grouped_video": False,
                        "attached_pic": ms["attached_pic"],
                    })
                continue

            m_typed = re.fullmatch(r"([vVasdt])(?::(\d+))?", sub_spec)
            type_map = {"v": "video", "V": "video", "a": "audio", "s": "subtitle", "d": "data", "t": "attachment"}
            if sub_spec == "":
                out_streams.append({
                    "source": "input_map",
                    "input_idx": in_idx,
                    "src_stream_idx": None,
                    "media_type": "video",
                    "count_lo": 0 if opt else 1,
                    "count_hi": None,
                    "from_whole_input": True,
                    "grouped_video": True,
                    "attached_pic": False,
                })
            elif m_typed:
                tcode = m_typed.group(1)
                exact_sub = m_typed.group(2) is not None
                mtype = type_map[tcode]
                out_streams.append({
                    "source": "input_map",
                    "input_idx": in_idx,
                    "src_stream_idx": None,
                    "media_type": mtype,
                    "count_lo": 0 if opt else 1,
                    "count_hi": 1 if exact_sub else None,
                    "from_whole_input": False,
                    "grouped_video": (mtype == "video" and not exact_sub),
                    "attached_pic": False,
                })
            elif re.fullmatch(r"\d+", sub_spec):
                out_streams.append({
                    "source": "input_map",
                    "input_idx": in_idx,
                    "src_stream_idx": None,
                    "media_type": "unknown",
                    "count_lo": 0 if opt else 1,
                    "count_hi": 1,
                    "from_whole_input": False,
                    "grouped_video": False,
                    "attached_pic": False,
                })
            else:
                out_streams.append({
                    "source": "input_map",
                    "input_idx": in_idx,
                    "src_stream_idx": None,
                    "media_type": "unknown",
                    "count_lo": 0 if opt else 1,
                    "count_hi": None,
                    "from_whole_input": False,
                    "grouped_video": True,
                    "attached_pic": False,
                })
        if not has_positive_map:
            return False, False, False, False
    else:
        has_fc_video = any(s["media_type"] in ("video", "unknown") for s in out_streams)
        has_fc_audio = any(s["media_type"] == "audio" for s in out_streams)
        video_in_indices = [
            idx for idx, streams in enumerate(resolved_inputs)
            if streams is None or any(s["codec_type"] == "video" for s in streams)
        ]
        audio_in_indices = [
            idx for idx, streams in enumerate(resolved_inputs)
            if streams is None or any(s["codec_type"] == "audio" for s in streams)
        ]
        if not has_fc_video and not out_block["vn"] and (not resolved_inputs or video_in_indices):
            auto_in_idx = video_in_indices[0] if len(video_in_indices) == 1 else None
            out_streams.append({
                "source": "auto_input",
                "input_idx": auto_in_idx,
                "media_type": "video",
                "count_lo": 1,
                "count_hi": 1,
                "from_whole_input": False,
                "grouped_video": False,
                "attached_pic": False,
            })
        if not has_fc_audio and not out_block["an"] and (not resolved_inputs or audio_in_indices):
            out_streams.append({
                "source": "auto_input",
                "input_idx": audio_in_indices[0] if len(audio_in_indices) == 1 else None,
                "media_type": "audio",
                "count_lo": 1,
                "count_hi": 1,
                "from_whole_input": False,
                "grouped_video": False,
                "attached_pic": False,
            })

    # Apply FFmpeg -vn/-an/-sn/-dn stream-disabling flags to input-sourced streams (filter_complex streams are unaffected).
    disabled_types = set()
    if out_block["vn"]:
        disabled_types.add("video")
    if out_block["an"]:
        disabled_types.add("audio")
    if out_block["sn"]:
        disabled_types.add("subtitle")
    if out_block["dn"]:
        disabled_types.add("data")
    if disabled_types:
        filtered = []
        for st in out_streams:
            if st["source"] != "filter_complex":
                if st["media_type"] in disabled_types:
                    continue
                if st["media_type"] == "unknown":
                    filtered.append(dict(st, count_lo=0))
                    continue
            filtered.append(st)
        out_streams = filtered

    per_stream_filters = out_block["filters"]
    per_stream_codecs = out_block["codecs"]
    out_timeline_mutated = bool(out_block.get("timeline_mutated"))
    any_input_timeline_mutated = any(inp.get("timeline_mutated") for inp in inputs)

    def _input_mutated(st):
        in_idx = st.get("input_idx")
        if in_idx is not None and 0 <= in_idx < len(inputs):
            return bool(inputs[in_idx].get("timeline_mutated"))
        return any_input_timeline_mutated

    def _source_preserves(st):
        if out_timeline_mutated or _input_mutated(st):
            return False
        in_idx = st.get("input_idx")
        if in_idx is not None:
            return in_idx in burned_input_indices
        if st["source"] == "auto_input" and all_video_inputs_burned:
            return True
        return False

    def _eval_stream(st, out_lo, out_hi, v_idx, v_nonpic_idx):
        # Output-side seek/trim/frame-cap (-ss/-t/-to/-frames:v/-vframes/-itsscale/-itsoffset)
        # shifts or truncates the encoded timeline AFTER subtitle burning -> reject on BOTH fresh burn & preservation!
        if out_timeline_mutated:
            return False

        eff_codec = None
        for ck, cspec, cval in per_stream_codecs:
            mstate = _spec_matches_video_stream(
                ck, cspec, out_lo, out_hi, v_idx,
                attached_pic=st["attached_pic"], v_nonpic_idx=v_nonpic_idx,
            )
            if mstate == "definite":
                eff_codec = cval
            elif mstate == "ambiguous" and cval == "copy":
                eff_codec = "copy"

        if st["source"] == "filter_complex":
            if eff_codec == "copy" or any_input_timeline_mutated:
                return False
            for fk, fspec, _fexpr in per_stream_filters:
                if _spec_matches_video_stream(
                    fk, fspec, out_lo, out_hi, v_idx,
                    attached_pic=st["attached_pic"], v_nonpic_idx=v_nonpic_idx,
                ) != "none":
                    return False
            return bool(st["fc_burns_caption"])

        if _input_mutated(st):
            return False

        can_preserve = _source_preserves(st)
        eff_expr = None
        filter_seen = False
        ambiguous_non_preserving = False
        for fk, fspec, fexpr in per_stream_filters:
            mstate = _spec_matches_video_stream(
                fk, fspec, out_lo, out_hi, v_idx,
                attached_pic=st["attached_pic"], v_nonpic_idx=v_nonpic_idx,
            )
            if mstate == "definite":
                filter_seen = True
                ambiguous_non_preserving = False
                eff_expr = None if fk == "filter_script" else fexpr
            elif mstate == "ambiguous":
                if fk == "filter_script":
                    filter_seen = True
                    eff_expr = None
                    ambiguous_non_preserving = True
                else:
                    if not _vf_expr_burns_caption(fexpr, path, cwd=cwd):
                        eff_expr = None
                    if not _vf_expr_preserves_caption(fexpr):
                        ambiguous_non_preserving = True

        if eff_codec != "copy" and eff_expr is not None and _vf_expr_burns_caption(eff_expr, path, cwd=cwd):
            return True
        if can_preserve and not ambiguous_non_preserving:
            if not filter_seen:
                return True
            if eff_codec != "copy" and eff_expr is not None and _vf_expr_preserves_caption(eff_expr):
                return True
        return False

    cur_lo = 0
    cur_hi = 0
    cur_v_idx = 0
    cur_v_nonpic_idx = 0
    delivered_videos = []
    for st in out_streams:
        out_lo = cur_lo
        out_hi = None if st["from_whole_input"] else cur_hi
        if st["media_type"] in ("video", "unknown"):
            v_idx = cur_v_idx
            v_nonpic_idx = None if st["attached_pic"] else cur_v_nonpic_idx
            burns = _eval_stream(st, out_lo, out_hi, v_idx, v_nonpic_idx)
            if burns and st.get("grouped_video"):
                tail_lo = (out_lo + 1) if out_lo is not None else None
                burns = _eval_stream(st, tail_lo, None, None, None)
            delivered_videos.append((burns, st["count_lo"] >= 1))
            if st["count_hi"] is None:
                cur_v_idx = None
                cur_v_nonpic_idx = None
            else:
                if cur_v_idx is not None:
                    cur_v_idx += 1
                if not st["attached_pic"] and cur_v_nonpic_idx is not None:
                    cur_v_nonpic_idx += 1

        cur_lo += st["count_lo"]
        cur_hi = None if (cur_hi is None or st["count_hi"] is None) else (cur_hi + st["count_hi"])

    has_any_video = bool(delivered_videos)
    has_guaranteed_video = any(guaranteed for _burns, guaranteed in delivered_videos)
    all_videos_verified = all(burns for burns, _guaranteed in delivered_videos)
    return True, has_guaranteed_video, has_any_video, all_videos_verified


def _command_burns_caption_to_mapped_video(
    command,
    path,
    cwd=None,
    *,
    input_streams=None,
    bound_inputs=None,
    target_outputs=None,
    burned_input_indices=frozenset(),
    verified_progress_graphs=frozenset(),
):
    """Verify every delivered video stream burns (or preserves) the exact caption file under closed-world templates."""
    if not isinstance(command, list) or not command:
        return False
    parsed_cmd = _parse_ffmpeg_command_segments(command)
    if parsed_cmd is None:
        return False
    inputs, complex_graphs, outputs = parsed_cmd
    if not outputs:
        return False

    if input_streams is not None:
        resolved_inputs = list(input_streams)
    else:
        resolved_inputs = _resolve_input_streams(inputs, command, cwd=cwd, bound_inputs=bound_inputs)

    video_bearing_inputs = [
        idx for idx, streams in enumerate(resolved_inputs)
        if streams is None or any(s["codec_type"] == "video" for s in streams)
    ]
    all_video_inputs_burned = bool(video_bearing_inputs) and all(idx in burned_input_indices for idx in video_bearing_inputs)

    # Parse all -filter_complex / -lavfi / bound -filter_complex_script graphs cumulatively.
    all_labeled_pads = {}
    duplicate_labels = set()
    unlabeled_fc_streams = []
    loaded_graph_exprs = []
    for gkind, gval in complex_graphs:
        is_verified_progress = False
        if gkind == "script":
            cand = Path(gval)
            if not cand.is_absolute():
                if not cwd:
                    return False
                cand = Path(cwd) / cand
            try:
                cand_res = cand.resolve(strict=True)
            except OSError:
                return False
            if bound_inputs is None or cand_res not in bound_inputs:
                return False
            try:
                graph_expr = cand_res.read_text(encoding="utf-8-sig")
            except OSError:
                return False
            is_verified_progress = cand_res in verified_progress_graphs
        else:
            graph_expr = gval
        loaded_graph_exprs.append(graph_expr)
        parsed = _parse_complex_graph(graph_expr, path, cwd=cwd, is_verified_progress=is_verified_progress)
        if parsed is None:
            return False
        pad_defs, unlabeled_outputs = parsed
        for label, info in pad_defs.items():
            if label in all_labeled_pads:
                duplicate_labels.add(label)
            else:
                all_labeled_pads[label] = (info, pad_defs)
        for item in unlabeled_outputs:
            unlabeled_fc_streams.append({
                "source": "filter_complex",
                "media_type": _resolve_fc_media_type(item, pad_defs, resolved_inputs),
                "fc_burns_caption": _fc_item_reaches_caption(
                    item, pad_defs,
                    burned_input_indices=burned_input_indices,
                    all_video_inputs_burned=all_video_inputs_burned,
                ),
                "fc_fresh_burn": _fc_item_reaches_caption(
                    item, pad_defs,
                ),
                "count_lo": 1,
                "count_hi": 1,
                "from_whole_input": False,
                "grouped_video": False,
                "attached_pic": False,
            })

    if _command_has_forbidden_runtime_filter(command, loaded_scripts=loaded_graph_exprs):
        return False

    if target_outputs is not None:
        target_set = {Path(p).resolve() for p in target_outputs}
        if not target_set:
            return False
        matched_indices = []
        matched_targets = set()
        for idx, ob in enumerate(outputs):
            raw_out = ob["path"]
            if raw_out == "-":
                continue
            cand = Path(raw_out)
            if not cand.is_absolute():
                if not cwd:
                    continue
                cand = Path(cwd) / cand
            try:
                res = cand.resolve()
            except OSError:
                continue
            if res in target_set:
                matched_indices.append(idx)
                matched_targets.add(res)
        if matched_targets != target_set or not matched_indices:
            return False
        for idx in matched_indices:
            valid, has_guaranteed_v, _has_any_v, all_v_ok = _evaluate_output_block(
                outputs[idx],
                is_first_output=(idx == 0),
                unlabeled_fc_streams=unlabeled_fc_streams,
                all_labeled_pads=all_labeled_pads,
                duplicate_labels=duplicate_labels,
                inputs=inputs,
                resolved_inputs=resolved_inputs,
                path=path,
                cwd=cwd,
                burned_input_indices=burned_input_indices,
                all_video_inputs_burned=all_video_inputs_burned,
            )
            if not (valid and has_guaranteed_v and all_v_ok):
                return False
        return True

    any_guaranteed_video = False
    for idx in range(len(outputs)):
        valid, has_guaranteed_v, has_any_v, all_v_ok = _evaluate_output_block(
            outputs[idx],
            is_first_output=(idx == 0),
            unlabeled_fc_streams=unlabeled_fc_streams,
            all_labeled_pads=all_labeled_pads,
            duplicate_labels=duplicate_labels,
            inputs=inputs,
            resolved_inputs=resolved_inputs,
            path=path,
            cwd=cwd,
            burned_input_indices=burned_input_indices,
            all_video_inputs_burned=all_video_inputs_burned,
        )
        if not valid:
            return False
        if has_any_v and not all_v_ok:
            return False
        if has_guaranteed_v:
            any_guaranteed_video = True
    return any_guaranteed_video


def _verify_receipt_artifact(art):
    """Verify a receipt artifact dict (supports both 2-key refs and 5-key ffmpeg_execution_receipt artifacts)."""
    if not (isinstance(art, dict) and isinstance(art.get("path"), str) and isinstance(art.get("sha256"), str)):
        return None
    resolved = Path(art["path"]).resolve(strict=True)
    bound({"path": str(resolved), "sha256": art["sha256"]})
    if isinstance(art.get("bytes"), int) and resolved.stat().st_size != art["bytes"]:
        raise ValueError("rough_cut_input_changed")
    return resolved


def _boxes_intersect(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def _verified_progress_graphs_for_receipt(receipt, bound_inputs):
    """Return set of verified progress_overlay filtergraph script paths bound in receipt['inputs']."""
    plan_path = None
    graph_path = None
    for row in receipt.get("inputs", []):
        art = row.get("artifact")
        if not (isinstance(art, dict) and art.get("path")):
            continue
        res = Path(art["path"]).resolve()
        if res not in bound_inputs:
            continue
        if row.get("role") == "progress_plan":
            plan_path = res
        elif row.get("role") == "filtergraph":
            graph_path = res
    if plan_path is None or graph_path is None:
        return frozenset()
    try:
        import video_progress_contract as vpc
        comp = vpc.component()
        plan = comp.validate(plan_path)
        expected_fg = comp.filtergraph(plan, graph_path.parent, write_texts=False)
        if graph_path.read_text(encoding="utf-8") != expected_fg:
            return frozenset()
        bar_rect = (plan.get("geometry") or {}).get("rect")
        if not isinstance(bar_rect, dict):
            return frozenset()
        bar_box = (
            float(bar_rect["x"]), float(bar_rect["y"]),
            float(bar_rect["x"]) + float(bar_rect["width"]),
            float(bar_rect["y"]) + float(bar_rect["height"]),
        )
        elements = ((plan.get("layout_with_progress") or {}).get("elements") or [])
        sub_rects = [el.get("rect") for el in elements if el.get("role") == "subtitle" and isinstance(el.get("rect"), dict)]
        if not sub_rects:
            return frozenset()
        for sr in sub_rects:
            s_box = (
                float(sr["x"]), float(sr["y"]),
                float(sr["x"]) + float(sr["width"]),
                float(sr["y"]) + float(sr["height"]),
            )
            if _boxes_intersect(bar_box, s_box):
                return frozenset()
        return frozenset({graph_path})
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        return frozenset()


def _receipt_video_target_outputs(receipt, command, *, exact_target_path=None, exact_target_sha=None):
    """Select video delivery outputs from receipt['outputs'].

    - If exact_target_path or exact_target_sha is given: bind STRICTLY to matching output row(s).
    - Otherwise: select all video-bearing outputs (and any 'candidate' output even if audio-only so it fails closed),
      ignoring pure-audio non-candidate sidecars (e.g. diagnostic .mka/.wav with 0 video streams).
    """
    verified = []
    for row in receipt.get("outputs", []):
        art = row.get("artifact")
        if isinstance(art, dict) and art.get("path") and art.get("sha256"):
            verified.append((row.get("role"), _verify_receipt_artifact(art), art))
    if not verified:
        return []
    if exact_target_path is not None or exact_target_sha is not None:
        matched = []
        for role, p, art in verified:
            if exact_target_path is not None and p != exact_target_path:
                continue
            if exact_target_sha is not None and art["sha256"] != exact_target_sha:
                continue
            matched.append((role, p, art))
        return matched
    video_rows = []
    for role, p, art in verified:
        if role == "candidate":
            video_rows.append((role, p, art))
            continue
        streams = _probe_file_streams(p, command)
        if streams is not None:
            if any(s["codec_type"] == "video" for s in streams):
                video_rows.append((role, p, art))
        elif p.suffix.lower() in _VIDEO_SUFFIXES:
            video_rows.append((role, p, art))
    return video_rows


def _receipt_caption_verified_outputs(
    receipt,
    burn_ref,
    path,
    burned_media=frozenset(),
    *,
    exact_target_path=None,
    exact_target_sha=None,
):
    """Evaluate one receipt in a render chain, returning (ok, set_of_verified_output_identities)."""
    command = receipt.get("executed_command", receipt["command"])
    cwd = receipt.get("cwd")
    inputs = receipt.get("inputs", [])
    has_burn_file = any(
        isinstance(row.get("artifact"), dict)
        and row["artifact"].get("sha256") == burn_ref["sha256"]
        and Path(row["artifact"]["path"]).resolve() == path.resolve()
        for row in inputs
    )
    bound_inputs = {}
    for row in inputs:
        art = row.get("artifact")
        if isinstance(art, dict) and art.get("path") and art.get("sha256"):
            bound_inputs[_verify_receipt_artifact(art)] = art

    burned_input_indices = set()
    parsed_cmd = _parse_ffmpeg_command_segments(command) if isinstance(command, list) else None
    if parsed_cmd is not None and burned_media:
        cmd_inputs, _cg, _outs = parsed_cmd
        for idx, entry in enumerate(cmd_inputs):
            if entry["fmt"] == "lavfi":
                continue
            cand = Path(entry["path"])
            if not cand.is_absolute():
                if not cwd:
                    continue
                cand = Path(cwd) / cand
            try:
                cand_res = cand.resolve()
            except OSError:
                continue
            art = bound_inputs.get(cand_res)
            if art is not None and (cand_res, art["sha256"]) in burned_media:
                burned_input_indices.add(idx)

    if not has_burn_file and not burned_input_indices:
        return False, set()

    verified_progress_graphs = _verified_progress_graphs_for_receipt(receipt, bound_inputs)
    target_rows = _receipt_video_target_outputs(
        receipt, command, exact_target_path=exact_target_path, exact_target_sha=exact_target_sha,
    )
    if (receipt.get("outputs") or exact_target_path is not None or exact_target_sha is not None) and not target_rows:
        return False, set()
    target_paths = [p for _role, p, _art in target_rows] if target_rows else None
    ok = _command_burns_caption_to_mapped_video(
        command,
        path if has_burn_file else None,
        cwd=cwd,
        bound_inputs=bound_inputs,
        target_outputs=target_paths,
        burned_input_indices=frozenset(burned_input_indices),
        verified_progress_graphs=verified_progress_graphs,
    )
    if not ok:
        return False, set()
    return True, {(p, art["sha256"]) for _role, p, art in target_rows}


def _receipt_burns_caption(
    receipt,
    burn_ref,
    path,
    burned_media=frozenset(),
    *,
    exact_target_path=None,
    exact_target_sha=None,
):
    ok, _verified = _receipt_caption_verified_outputs(
        receipt,
        burn_ref,
        path,
        burned_media=burned_media,
        exact_target_path=exact_target_path,
        exact_target_sha=exact_target_sha,
    )
    return ok


def _resolve_selected_final_video(manifest, observed, target_video=None):
    """Resolve and cross-check ALL declared final video identities (target_video, desk_ref, observed, final_layout_ref, final_observations_ref)."""
    paths = set()
    shas = set()
    if isinstance(target_video, dict) and target_video.get("path") and target_video.get("sha256"):
        paths.add(bound(target_video).resolve())
        shas.add(str(target_video["sha256"]).strip())
    if isinstance(manifest, dict) and isinstance(manifest.get("desk_ref"), dict) and manifest["desk_ref"].get("path"):
        desk_data = load(bound(manifest["desk_ref"]))
        items = desk_data.get("items") or []
        if len(items) == 1 and isinstance(items[0].get("video"), dict):
            vid = items[0]["video"]
            if vid.get("path") and vid.get("sha256"):
                paths.add(bound(vid).resolve())
                shas.add(str(vid["sha256"]).strip())
    obs_sha = observed.get("video_sha256") if isinstance(observed, dict) else None
    if isinstance(obs_sha, str) and obs_sha.strip():
        shas.add(obs_sha.strip())
    if isinstance(manifest, dict) and isinstance(manifest.get("final_layout_ref"), dict):
        lref = manifest["final_layout_ref"]
        if lref.get("path") and lref.get("sha256"):
            lpath = bound(lref)
            layout = load(lpath)
            cand = layout.get("candidate") if isinstance(layout, dict) else None
            if isinstance(cand, dict):
                lsha = cand.get("expected_sha256") or cand.get("sha256")
                if isinstance(lsha, str) and lsha.strip():
                    shas.add(lsha.strip())
                if "path" in cand:
                    cpath = cand.get("path")
                    if not (isinstance(cpath, str) and cpath.strip()):
                        raise ValueError("final_caption_file_not_bound_to_subtitle_burn_after_edit")
                    root_dir = Path(manifest.get("layout_workspace_root", lpath.parent)).resolve()
                    cp = Path(cpath.strip())
                    paths.add(cp.resolve() if cp.is_absolute() else (root_dir / cp).resolve())
    if isinstance(manifest, dict) and isinstance(manifest.get("final_observations_ref"), dict):
        oref = manifest["final_observations_ref"]
        if oref.get("path") and oref.get("sha256"):
            obs_pkt = load(bound(oref))
            ovid = obs_pkt.get("video_ref") if isinstance(obs_pkt, dict) else None
            if isinstance(ovid, dict) and ovid.get("path") and ovid.get("sha256"):
                paths.add(bound(ovid).resolve())
                shas.add(str(ovid["sha256"]).strip())
    if len(shas) > 1 or len(paths) > 1:
        raise ValueError("final_caption_file_not_bound_to_subtitle_burn_after_edit")
    return (next(iter(paths), None), next(iter(shas), None))


def check(manifest, observed, frames, *, target_video=None):
    config, cues = final_cues(manifest)
    if not cues:
        return
    references = [*manifest.get("render_chain_refs", []), manifest["render_receipt_ref"]]
    if manifest.get("final_timeline_ref"):
        edit = load(bound(manifest["final_timeline_ref"]))
        if edit["edit_render_receipt_ref"] not in references:
            raise ValueError("final_timeline_render_receipt_not_in_chain")
        references = references[references.index(edit["edit_render_receipt_ref"]):]
        source_pack = load(bound(manifest["subtitles"]["pack_ref"]))
        check_edit_punctuation(
            source_pack["requests"][0]["subtitle_cues"],
            cues,
            edit["timeline"]["segments"],
            accepted_rebreaks=observed.get("accepted_edit_rebreaks"),
        )
    burn_ref = config.get("render_file_ref")
    if burn_ref is None:
        raise ValueError("current_final_burned_caption_file_required")
    path = bound(burn_ref)
    sel_path, sel_sha = _resolve_selected_final_video(manifest, observed, target_video=target_video)
    burned_media = set()
    final_ok = False
    for idx, ref in enumerate(references):
        receipt = load(bound(ref))
        is_final = (idx == len(references) - 1)
        ok, verified_outputs = _receipt_caption_verified_outputs(
            receipt,
            burn_ref,
            path,
            burned_media=frozenset(burned_media),
            exact_target_path=sel_path if is_final else None,
            exact_target_sha=sel_sha if is_final else None,
        )
        if ok:
            burned_media.update(verified_outputs)
        if is_final:
            final_ok = ok
    if not final_ok:
        raise ValueError("final_caption_file_not_bound_to_subtitle_burn_after_edit")
    styles = config.get("dialogue_styles", sorted(DEFAULT_STYLES))
    if not isinstance(styles, list) or not styles or any(not isinstance(style, str) or not style.strip() for style in styles):
        raise ValueError("final_dialogue_styles_invalid")
    verify_burned_cues(path, cues, set(DEFAULT_STYLES) | {style.casefold() for style in styles})
    verify_mobile_samples(cues, frames, observed)
