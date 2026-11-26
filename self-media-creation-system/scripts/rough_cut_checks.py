"""Validate the encoded spoken rough cut before the next editing stage."""
from __future__ import annotations

import array
import difflib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unicodedata
import wave

ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCHEMA = "self-media.rough-cut-check.v1"
READY_SCHEMA = "self-media.rough-cut-accepted.v1"
REVIEW_ID = "post-cut-check-001"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def ref(path):
    path = Path(path).resolve(strict=True)
    with path.open("rb") as handle:
        return {"path": str(path), "sha256": hashlib.file_digest(handle, "sha256").hexdigest()}


def bound(value):
    if value != ref(value["path"]):
        raise ValueError("rough_cut_input_changed")
    return Path(value["path"])


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def run_local_vkp(candidate, output):
    registry = next((parent / "scripts/local_tools.py" for parent in ROOT.parents
                     if (parent / "scripts/local_tools.py").is_file()), None)
    if registry is None:
        raise ValueError("registered_vkp_entry_not_found")
    registered = subprocess.check_output(
        [sys.executable, str(registry), "command", "video-knowledge-pipeline", "cli"],
        encoding="utf-8",
    )
    entry = json.loads(registered)["value"]
    shell = shutil.which("pwsh")
    if not shell:
        raise ValueError("registered_vkp_requires_pwsh")
    env = os.environ.copy()
    for key in ("LECTURE_ASR_PYTHON", "LECTURE_ASR_BIN_DIR", "VKP_LOCAL_MODEL_ROOT", "HF_HUB_CACHE"):
        if key in entry["wrapper_env"]:
            env[key] = entry["wrapper_env"][key]
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", MODELSCOPE_OFFLINE="1")
    command = [shell, "-NoProfile", "-File", entry["wrapper"], *entry["wrapper_args"], "-EntryPoint", "cli", "--",
               "prepare-local-video-run", str(candidate), str(output), "--execute-asr", "--asr-preset", "sensevoice",
               "--no-frame-extract", "--no-scene-detect", "--timeout-seconds", "600"]
    subprocess.run(command, env=env, timeout=660, check=True)
    return output / "video-knowledge-run.json"


def vkp_transcript(candidate, run_path):
    run = load(run_path)
    if run.get("schema") != "video_knowledge_local_video_run.v1" or run.get("ok") is not True:
        raise ValueError("completed_vkp_run_required")
    execution = run["asr_run"]
    if execution.get("execute") is not True or execution.get("provider") != "sensevoice":
        raise ValueError("executed_local_sensevoice_required")
    raw_path = Path(execution["raw_output_json"])
    raw = load(raw_path)
    manifest_path = Path(raw["chunk_manifest_path"])
    manifest = load(manifest_path)
    source = manifest["source"]
    if (source["sha256"] != candidate["sha256"] or Path(source["path"]).resolve() != Path(candidate["path"])
            or Path(run["selected_media_path"]).resolve() != Path(candidate["path"])
            or raw.get("canonical_complete") is not True):
        raise ValueError("vkp_run_not_for_current_encoded_rough_cut")
    transcript_path = Path(run["transcript_path"])
    transcript = load(transcript_path)
    if Path(transcript["source_path"]).resolve() != raw_path.resolve():
        raise ValueError("vkp_transcript_raw_source_mismatch")
    segments = transcript["segments"]
    if not segments or not any(s.get("text", "").strip() for s in segments):
        raise ValueError("encoded_rough_cut_transcript_empty")
    return segments, [ref(path) for path in (run_path, raw_path, manifest_path, transcript_path)]


def spoken_body(script):
    text = Path(script).read_text(encoding="utf-8-sig")
    if re.search(r"(?m)^##\s+主片\s*$", text):
        text = re.split(r"(?m)^##\s+主片\s*$", text, maxsplit=1)[1]
        text = re.split(r"(?m)^##\s+", text, maxsplit=1)[0]
    return "\n".join(line.strip() for line in text.splitlines()
                     if line.strip() and not line.lstrip().startswith(("#", "**画面", "**Visual", "---")))


_DIGITS = dict(zip("零〇一二两三四五六七八九", "001223456789"))
_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}
_NUMBER = re.compile(r"[0-9零〇一二两三四五六七八九十百千万亿]+(?:[点.][0-9零〇一二两三四五六七八九]+)?")


def spoken_number(match):
    value = match[0]
    if not any(char.isdigit() or char in _DIGITS for char in value):
        return value
    integer, *fraction = re.split(r"[点.]", value)
    pending, section, total = "", 0, 0
    for char in integer:
        if char not in _UNITS:
            pending += _DIGITS.get(char, char)
            continue
        unit = _UNITS[char]
        number = int(pending or (1 if unit == 10 and not section else 0))
        pending = ""
        if unit < 10000:
            section += number * unit
        else:
            section += number
            total = (total + section) * unit if unit == 100000000 else total + section * unit
            section = 0
    whole = str(total + section + int(pending or 0))
    if fraction:
        # Reserve the decimal marker through the punctuation cleanup.
        whole += "点" + "".join(_DIGITS.get(char, char) for char in fraction[0]).rstrip("0")
        whole = whole.rstrip("点")
    return whole


def canonical(text):
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^\w%]", "", _NUMBER.sub(spoken_number, normalized), flags=re.UNICODE)


def compare(script, segments, omissions):
    text = spoken_body(script)
    for phrase in omissions:
        if not phrase.strip() or text.count(phrase) != 1:
            raise ValueError("intentional_omission_must_identify_one_script_span")
        text = text.replace(phrase, "", 1)
    expected = canonical(text)
    actual = "".join(canonical(segment["text"]) for segment in segments)
    if not expected or not actual:
        raise ValueError("rough_cut_comparison_requires_nonempty_text")
    spans, cursor = [], 0
    for segment in segments:
        cursor += len(canonical(segment["text"]))
        spans.append((cursor, segment["start"], segment["end"]))
    matcher = difflib.SequenceMatcher(None, expected, actual, autojunk=False)
    changes = []
    for tag, a, b, c, d in matcher.get_opcodes():
        if tag != "equal":
            here = next((span for span in spans if span[0] > c), spans[-1])
            tail = next((span for span in spans if span[0] >= max(c + 1, d)), spans[-1])
            changes.append({"kind": tag, "script": expected[a:b], "recognized": actual[c:d],
                            "start_seconds": here[1], "end_seconds": tail[2]})
    repetitions = []
    for segment in segments:
        match = re.search(r"([^\W\d_]{2,12})\1", canonical(segment["text"]))
        if match:
            repetitions.append({"text": match[1], "start_seconds": segment["start"], "end_seconds": segment["end"]})
    return {"comparison_similarity": round(matcher.ratio(), 4), "changes": changes,
            "repetition_candidates": repetitions,
            "omitted_phrase_candidates": [p for p in omissions if canonical(p) in actual]}


def _mvp():
    path = ROOT.parent / "ai-video-tools-20260708/mvp-video-pipeline/src"
    sys.path.insert(0, str(path))
    from video_creation_pipeline import execution_receipts
    return execution_receipts


def technical(candidate, output, expected_seconds):
    mvp = _mvp()
    media = Path(candidate["path"])
    info = mvp.probe_media_metadata(media)
    streams = info["streams"]
    video = next((s for s in streams if s["codec_type"] == "video"), None)
    audio = next((s for s in streams if s["codec_type"] == "audio"), None)
    duration = float(info.get("format", {}).get("duration", 0))
    if not (audio and video and math.isfinite(duration) and duration > 0 and abs(duration - expected_seconds) <= .5):
        raise ValueError("rough_cut_tracks_or_expected_duration_failed")
    log = output / "rough-cut-decode.log"
    receipt = output / "rough-cut-decode-receipt.json"
    mvp.execute_ffmpeg_with_receipt(
        "technical_qa",
        ["ffmpeg", "-nostdin", "-v", "info", "-xerror", "-i", str(media),
         "-map", "0:v:0", "-map", "0:a:0",
         "-vf", "blackdetect=d=0.1:pix_th=0.02,freezedetect=n=0.003:d=2",
         "-af", "silencedetect=noise=-40dB:d=0.12,astats=metadata=0:reset=0", "-f", "null", "-"],
        [{"role":"candidate","path":media}], [{"role":"decode_log","path":log}], receipt,
        capture_log_path=log, guard_resource=True, timeout_s=3600,
    )
    diagnostics = log.read_text(encoding="utf-8", errors="replace")
    findings = [line.split("] ", 1)[-1] for line in diagnostics.splitlines()
                if re.search(r"black_start:|freeze_(start|end):|silence_(start|end):|Peak level dB:|RMS level dB:", line)]
    ends = [float(s["duration"]) for s in (audio, video) if s.get("duration") not in (None, "N/A")]
    skew = abs(ends[0] - ends[1]) if len(ends) == 2 else None
    return {"duration": duration, "expected_duration": expected_seconds, "video_size": [video["width"], video["height"]],
            "audio_video_duration_difference_s": skew, "decoder": ref(receipt), "log": ref(log), "candidates": findings}


def prepare(args):
    candidate, script, timeline = ref(args.candidate), ref(args.script), ref(args.timeline)
    expected_duration = timeline_rows(load(timeline["path"]))[-1]["target_end"]
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    supplied = getattr(args, "registration", None)
    if supplied:
        registration_ref = ref(supplied)
        record = registration(registration_ref)
        if record["candidate"] != candidate or record["timeline_map"] != timeline:
            raise ValueError("rough_cut_registration_candidate_or_timeline_mismatch")
    else:
        registration_ref = register(candidate["path"], timeline["path"], output / "rough-cut-registration.json")
    run = args.vkp_run or run_local_vkp(Path(candidate["path"]), output / "vkp")
    segments, vkp = vkp_transcript(candidate, run)
    tech = technical(candidate, output, expected_duration)
    comparison = compare(script["path"], segments, args.omit)
    expected = spoken_body(script["path"])
    for omission in args.omit:
        expected = expected.replace(omission, "", 1)
    cuts = safe_retake_cuts(canonical(expected), segments, bound(tech["log"]).read_text(encoding="utf-8", errors="replace"))
    source = None
    if cuts:
        source = {"registration": registration_ref, "vkp": vkp, "technical": tech, "comparison": comparison}
        repair = output / "automatic-repair"
        candidate, timeline, registration_ref = render_retake_repair(candidate, timeline, tech["duration"], cuts, repair)
        segments, vkp = vkp_transcript(candidate, run_local_vkp(Path(candidate["path"]), repair / "vkp"))
        tech = technical(candidate, repair, timeline_rows(load(timeline["path"]))[-1]["target_end"])
        comparison = compare(script["path"], segments, args.omit)
    bound(candidate)
    bound(script)
    bound(timeline)
    coverage = source_coverage_gaps(load(timeline["path"]))
    report = {"schema": AUDIT_SCHEMA, "status": "needs_review", "candidate": candidate, "script": script, "timeline": timeline,
              "registration": registration_ref, "vkp": vkp, "technical": tech, "comparison": comparison,
              "source_coverage": coverage,
              "project_identity": load(args.identity), "intentional_omissions": args.omit,
              "applied_cuts": cuts, "pre_repair": source}
    rows = review_items(report)
    report["automatic_review"] = not rows
    audit = output / "rough-cut-check.json"
    write_new(audit, report)
    if rows:
        write_new(output / "rough-cut-triage-template.json", {
            "schema": TRIAGE_SCHEMA, "audit": ref(audit), "reviewer": "",
            "decisions": [{"review_id": row["review_id"], "state": "pending", "basis": ""} for row in rows],
            "candidates": rows})
        return audit, None
    request = output / "review-request.json"
    write_new(request, {"schema_version": "self-media-human-review-request-pack.v1", "scope": "post_cut_check:" + ref(audit)["sha256"],
                        "project_identity": report["project_identity"], "requests": [automatic_item(report)]})
    return audit, request


def automatic_item(report):
    candidate = report["candidate"]
    return {"review_id": REVIEW_ID, "source_path": candidate["path"], "artifact_sha256": candidate["sha256"],
            "review_start_seconds": 0, "review_end_seconds": report["technical"]["duration"],
            "review_lane": "publication", "review_purpose": "复核回执",
            "review_question": "对稿和候选项核查已完成，无需提交作者处理。"}


def save_automatic_review(audit, bundle):
    import video_review_delivery as delivery
    vkp = delivery._import_vkp_review()
    pack_path = bundle / "targeted-review-pack.json"
    decisions_path = bundle / "targeted-review-decisions.json"
    _, pack = vkp.load_targeted_review_bundle(bundle)
    initial = load(decisions_path)
    if (initial.get("reviewer") != "待填写" or initial.get("status") != "in_progress"
            or initial.get("pack_payload_sha256") != pack["pack_payload_sha256"]
            or not initial.get("decisions") or any(row["decision"] != "pending" for row in initial["decisions"])):
        raise ValueError("rough_cut_automatic_review_cannot_overwrite_saved_decision")
    receipt = vkp.compose_review_receipt(pack, AUTO_REVIEWER, [{"review_id": REVIEW_ID, "decision": "pass",
                                                               "note": "Local ASR/script and technical checks."}])
    request = load(Path(pack["source_request_path"]))
    triage = request.get("rough_cut_triage")
    report = load(audit)
    if triage:
        if validated_triage(report, ref(audit), load(bound(triage))):
            raise ValueError("rough_cut_requires_author_decisions")
    elif not report.get("automatic_review") or review_items(report):
        raise ValueError("rough_cut_requires_agent_triage")
    vkp.write_json(decisions_path, receipt)
    output = bundle.parent / "rough-cut-acceptance.json"
    write_new(output, verify_review(audit, pack_path, decisions_path))
    return ref(output)


def verify_review(audit_path, pack_path, decisions_path):
    audit = load(audit_path)
    if audit.get("schema") != AUDIT_SCHEMA:
        raise ValueError("rough_cut_check_report_required")
    candidate = bound(audit["candidate"])
    for entry in [audit["script"], audit["timeline"], *audit["vkp"], audit["technical"]["decoder"], audit["technical"]["log"]]:
        bound(entry)
    import video_review_delivery as delivery
    delivery._import_vkp_review()
    from video_knowledge_pipeline.targeted_review import load_targeted_review_bundle, compose_review_receipt
    pack_path = Path(pack_path).resolve()
    decisions_path = Path(decisions_path).resolve()
    bundle, pack = load_targeted_review_bundle(pack_path.parent)
    if pack_path.name != "targeted-review-pack.json" or decisions_path != bundle / "targeted-review-decisions.json":
        raise ValueError("saved_vkp_review_required")
    request = Path(pack["source_request_path"])
    request_ref = ref(request)
    if request_ref["sha256"] != pack["source_request_sha256"]:
        raise ValueError("review_not_bound_to_current_rough_cut_check")
    request_data = load(request)
    audit_ref = ref(audit_path)
    scope = "post_cut_check:" + audit_ref["sha256"]
    triage = request_data.get("rough_cut_triage")
    if triage:
        scope = triaged_scope(audit_ref, triage)
        remaining = validated_triage(audit, audit_ref, load(bound(triage)))
    elif audit.get("registration"):
        remaining = review_items(audit)
        if remaining:
            raise ValueError("rough_cut_agent_triage_required")
    else:
        remaining = []
    if request_data["scope"] != scope or (audit.get("registration") and
            request_data["requests"] != (remaining or [automatic_item(audit)])):
        raise ValueError("review_not_bound_to_current_rough_cut_check")
    source, = pack["sources"]
    if Path(source["path"]).resolve() != candidate or source["sha256"] != audit["candidate"]["sha256"]:
        raise ValueError("rough_cut_review_media_mismatch")
    if audit.get("registration"):
        record = registration(audit["registration"])
        if record["candidate"] != audit["candidate"] or record["timeline_map"] != audit["timeline"]:
            raise ValueError("rough_cut_review_registration_mismatch")
    decisions = load(decisions_path)
    reviewed = decisions.get("decisions", [])
    expected_ids = {item["review_id"] for item in pack["requests"]}
    machine = decisions.get("reviewer") == AUTO_REVIEWER
    if machine and (remaining or expected_ids != {REVIEW_ID} or not (triage or audit.get("automatic_review"))):
        raise ValueError("rough_cut_machine_review_disallowed")
    if (decisions.get("pack_payload_sha256") != pack["pack_payload_sha256"]
            or len(reviewed) != len(expected_ids) or {row.get("review_id") for row in reviewed} != expected_ids
            or any(row.get("decision") != "pass" for row in reviewed)
            or not str(decisions.get("reviewer", "")).strip() or decisions["reviewer"] == "待填写"):
        raise ValueError("rough_cut_review_pending_or_needs_rework")
    # Validate the real saved receipt without replacing its original timestamp.
    expected = compose_review_receipt(pack, decisions["reviewer"], decisions["decisions"])
    if any(decisions.get(key) != value for key, value in expected.items() if key not in {"saved_at", "receipt_payload_sha256"}):
        raise ValueError("rough_cut_review_receipt_invalid")
    from video_knowledge_pipeline.targeted_review import _payload_sha256
    if decisions["receipt_payload_sha256"] != _payload_sha256(decisions, "receipt_payload_sha256"):
        raise ValueError("rough_cut_review_receipt_integrity_failed")
    return {"schema": READY_SCHEMA, "candidate": audit["candidate"], "audit": ref(audit_path),
            "pack": ref(pack_path), "review": ref(decisions_path)}


def require_ready(path, candidate):
    saved = load(path)
    actual = verify_review(bound(saved["audit"]), bound(saved["pack"]), bound(saved["review"]))
    if actual != saved or saved["candidate"] != candidate:
        raise ValueError("rough_cut_acceptance_not_for_current_candidate")
    return actual

REGISTRATION_SCHEMA = "self-media.rough-cut-registration.v1"
AUTO_REVIEWER = "VKP 自动复核"


def register(candidate, timeline, path, *, render_receipt=None):
    candidate_ref, timeline_ref = ref(candidate), ref(timeline)
    timeline_rows(load(timeline_ref["path"]))
    record = {"schema": REGISTRATION_SCHEMA, "candidate": candidate_ref, "timeline_map": timeline_ref,
              "render_receipt": ref(render_receipt) if render_receipt else None}
    write_new(path, record)
    return ref(path)


def timeline_rows(value):
    rows = value.get("segments", value.get("nle_segments"))
    if not rows:
        raise ValueError("valid_rough_cut_timeline_required")
    result, cursor = [], 0.0
    for row in rows:
        source = row.get("source_ref")
        if source is None:
            source = ({"path": row["source_path"], "sha256": row["source_sha256"]}
                      if "source_path" in row else value.get("source_video"))
        if isinstance(source, dict) and source.get("path") and not source.get("sha256"):
            source = ref(source["path"])
        if not isinstance(source, dict) or not {"path", "sha256"} <= source.keys():
            raise ValueError("rough_cut_timeline_source_required")
        source = {key: source[key] for key in ("path", "sha256")}
        start = row.get("source_start", row.get("in_s"))
        end = row.get("source_end", row.get("out_s"))
        target_start = row.get("target_start", row.get("target_start_s", cursor))
        target_end = row.get("target_end", row.get("target_end_s"))
        if target_end is None:
            target_end = cursor + row.get("duration_s", end - start)
        if (not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                    for x in (start, end, target_start, target_end))
                or not 0 <= start < end or abs(cursor - target_start) > .002 or target_end <= target_start):
            raise ValueError("valid_rough_cut_timeline_required")
        result.append({"source_ref": source, "source_start": start, "source_end": end,
                       "target_start": target_start, "target_end": target_end})
        cursor = target_end
    return result


def registration(value):
    if not value:
        raise ValueError("rough_cut_delivery_required")
    path = bound(value) if isinstance(value, dict) else Path(value)
    record = load(path)
    if record.get("schema") != REGISTRATION_SCHEMA:
        raise ValueError("rough_cut_registration_required")
    bound(record["candidate"])
    bound(record["timeline_map"])
    if record["render_receipt"]:
        bound(record["render_receipt"])
    return record


def require_current(delivery, acceptance, *, candidate=None, script=None, timeline=None):
    registered = registration(delivery)
    if candidate is not None and candidate != registered["candidate"]:
        raise ValueError("rough_cut_registration_candidate_mismatch")
    if not acceptance:
        raise ValueError("rough_cut_acceptance_required")
    path = bound(acceptance) if isinstance(acceptance, dict) else Path(acceptance)
    saved = require_ready(path, registered["candidate"])
    report = load(bound(saved["audit"]))
    registration_ref = delivery if isinstance(delivery, dict) else ref(delivery)
    if report.get("registration") != registration_ref or report["timeline"] != registered["timeline_map"]:
        raise ValueError("rough_cut_acceptance_registration_or_timeline_mismatch")
    if script is not None and report["script"] != script:
        raise ValueError("rough_cut_acceptance_script_mismatch")
    if timeline is not None:
        actual = timeline_rows(load(bound(report["timeline"])))
        expected = timeline_rows(timeline)
        if len(actual) != len(expected) or any(
                a["source_ref"] != b["source_ref"] or any(abs(a[k] - b[k]) > .002 for k in (
                    "source_start", "source_end", "target_start", "target_end"))
                for a, b in zip(actual, expected)):
            raise ValueError("rough_cut_acceptance_timeline_mismatch")
    return saved


def check_fine_request(request, request_path, delivery, acceptance):
    candidate = request.get("rough_cut_candidate")
    if not candidate:
        raise ValueError("rough_cut_current_candidate_required")
    if not delivery:
        raise ValueError("rough_cut_delivery_required")
    record = registration(delivery)
    sources = [candidate, *(row["source_ref"] for row in timeline_rows(load(bound(record["timeline_map"]))))]
    known = {(Path(source["path"]).resolve(), source["sha256"]) for source in sources}
    base_dir = Path(request_path).resolve().parent
    for row in request["requests"]:
        source = (base_dir / row["source_path"]).resolve()
        if (source, row["artifact_sha256"]) not in known:
            raise ValueError("fine_cut_request_media_not_in_current_rough_cut")
    return require_current(delivery, acceptance, candidate=candidate)


def check_manifest(manifest):
    if not manifest.get("rough_cut_delivery_ref"):
        raise ValueError("rough_cut_delivery_required")
    if not all(manifest.get(key) for key in ("edited_media", "script_ref", "timeline")):
        raise ValueError("rough_cut_current_media_script_and_timeline_required")
    return require_current(manifest["rough_cut_delivery_ref"], manifest.get("rough_cut_acceptance_ref"),
                           candidate=manifest["edited_media"], script=manifest["script_ref"], timeline=manifest["timeline"])


def safe_retake_cuts(expected, segments, log):
    """Only remove an extra full take with an exact later take and two silence anchors."""
    canonical_segments = [canonical(row["text"]) for row in segments]
    silence = []
    for match in re.finditer(r"silence_end: (\d+(?:\.\d+)?)\s*\| silence_duration: (\d+(?:\.\d+)?)", log):
        end, duration = map(float, match.groups())
        silence.append((end - duration, end))

    def gap_anchor(left, right):
        for a, b in silence:
            start, end = max(a, left), min(b, right)
            if end - start >= .12:
                return (start + end) / 2
        return None

    cuts = []
    for i in range(1, len(segments) - 2):
        j = i + 1
        earlier, later = canonical_segments[i], canonical_segments[j]
        x = expected.find(later)
        before, after = canonical_segments[i-1][-6:], canonical_segments[j+1][:6]
        if (min(len(earlier), len(later)) < 8 or not before or not after or x < 0
                or expected.count(later) != 1 or x < len(before)
                or expected[x-len(before):x] != before or not expected[x+len(later):].startswith(after)
                or re.findall(r"[0-9%零一二三四五六七八九十百千万亿两]", earlier)
                != re.findall(r"[0-9%零一二三四五六七八九十百千万亿两]", later)
                or (earlier != later and earlier in expected)
                or difflib.SequenceMatcher(None, earlier, later, autojunk=False).ratio() < .85):
            continue
        a = gap_anchor(segments[i-1]["end"], segments[i]["start"])
        b = gap_anchor(segments[i]["end"], segments[j]["start"])
        if a is not None and b is not None and b > a and (not cuts or a > cuts[-1]["end"]):
            cuts.append({"start": round(a, 6), "end": round(b, 6),
                         "reason": "earlier_extra_take_with_later_script_match_and_silence_boundaries"})
    return cuts


def retained_ranges(duration, cuts):
    starts = [0.0, *(cut["end"] for cut in cuts)]
    ends = [*(cut["start"] for cut in cuts), duration]
    return list(zip(starts, ends))


def render_retake_repair(candidate, timeline, duration, cuts, directory):
    directory.mkdir()
    rows = timeline_rows(load(bound(timeline)))
    ranges = retained_ranges(rows[-1]["target_end"], cuts)
    target, fixed = 0.0, []
    for left, right in ranges:
        for row in rows:
            a, b = max(left, row["target_start"]), min(right, row["target_end"])
            if b <= a:
                continue
            rate = (row["source_end"] - row["source_start"]) / (row["target_end"] - row["target_start"])
            fixed.append({"source_ref": row["source_ref"],
                          "source_start": row["source_start"] + (a - row["target_start"]) * rate,
                          "source_end": row["source_start"] + (b - row["target_start"]) * rate,
                          "target_start": target, "target_end": target + b - a})
            target += b - a
    target_media = directory / "spoken-rough-cut-reviewed-candidate.mp4"
    target_map = directory / "source-timeline-map.json"
    render_receipt = directory / "render-receipt.json"
    filters = []
    ranges = retained_ranges(duration, cuts)
    for i, (a, b) in enumerate(ranges):
        filters.extend([f"[0:v]trim=start={a:.6f}:end={b:.6f},setpts=PTS-STARTPTS[v{i}]",
                        f"[0:a]atrim=start={a:.6f}:end={b:.6f},asetpts=PTS-STARTPTS[a{i}]"])
    labels = "".join(f"[v{i}][a{i}]" for i in range(len(ranges)))
    filters.append(f"{labels}concat=n={len(ranges)}:v=1:a=1[v][a]")
    _mvp().execute_ffmpeg_with_receipt(
        "render", ["ffmpeg", "-nostdin", "-n", "-i", str(bound(candidate)), "-filter_complex", ";".join(filters),
                   "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                   "-c:a", "aac", "-b:a", "192k", str(target_media)],
        [{"role": "rough_cut", "path": candidate["path"]}, {"role": "timeline", "path": timeline["path"]}],
        [{"role": "candidate", "path": target_media}], render_receipt,
        capture_log_path=directory / "render.log", guard_resource=True, timeout_s=3600)
    write_new(target_map, {"segments": fixed, "rough_cut_repair_source": candidate, "applied_cuts": cuts})
    registration_ref = register(target_media, target_map, directory / "rough-cut-registration.json",
                                render_receipt=render_receipt)
    return ref(target_media), ref(target_map), registration_ref


def source_coverage_gaps(timeline_doc, *, min_gap_seconds=1.5):
    """Verify full-source disposition when source_duration_seconds is declared."""
    rows = timeline_rows(timeline_doc)
    timeline_sources = {row["source_ref"]["sha256"] for row in rows}
    source_durations = {}
    source_duration = timeline_doc.get("source_duration_seconds")
    if len(timeline_sources) == 1 and type(source_duration) in (int, float) and math.isfinite(source_duration) and source_duration > 0:
        source_durations[next(iter(timeline_sources))] = float(source_duration)
    for src_meta in timeline_doc.get("sources", []) or []:
        if isinstance(src_meta, dict):
            duration = src_meta.get("duration_seconds")
            if src_meta.get("sha256") and type(duration) in (int, float) and math.isfinite(duration) and duration > 0:
                source_durations[src_meta["sha256"]] = float(duration)

    known_sources = timeline_sources | source_durations.keys()
    unassigned_discarded_ranges = []
    undeclared_sources = sorted(list(timeline_sources - set(source_durations.keys())))
    accounted_by_sha = {sha: [] for sha in source_durations}
    for row in rows:
        sha = row["source_ref"]["sha256"]
        if sha in accounted_by_sha:
            accounted_by_sha[sha].append((float(row["source_start"]), float(row["source_end"])))
    for disc in timeline_doc.get("discarded_ranges", []) or []:
        if not isinstance(disc, dict) or not str(disc.get("reason", "")).strip():
            raise ValueError("rough_cut_discarded_range_reason_required")
        d_start = disc.get("source_start", disc.get("start"))
        d_end = disc.get("source_end", disc.get("end"))
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (d_start, d_end)) or d_end <= d_start or d_start < 0:
            raise ValueError("rough_cut_discarded_range_invalid")
        sha = (disc.get("source_ref") or {}).get("sha256")
        if not sha and len(known_sources) == 1:
            sha = next(iter(known_sources))
        if sha in accounted_by_sha:
            accounted_by_sha[sha].append((float(d_start), float(d_end)))
        elif sha not in known_sources:
            unassigned_discarded_ranges.append(disc)
    gaps = []
    for sha, total_dur in source_durations.items():
        intervals = sorted(accounted_by_sha.get(sha, []))
        merged = []
        for s, e in intervals:
            s_clamped, e_clamped = max(0.0, s), min(total_dur, e)
            if e_clamped <= s_clamped:
                continue
            if merged and s_clamped <= merged[-1][1] + 0.05:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e_clamped))
            else:
                merged.append((s_clamped, e_clamped))
        cursor = 0.0
        for s, e in merged:
            if s - cursor > min_gap_seconds:
                gaps.append({"source_sha256": sha, "source_start": round(cursor, 3), "source_end": round(s, 3),
                             "gap_seconds": round(s - cursor, 3)})
            cursor = max(cursor, e)
        if total_dur - cursor > min_gap_seconds:
            gaps.append({"source_sha256": sha, "source_start": round(cursor, 3), "source_end": round(total_dur, 3),
                         "gap_seconds": round(total_dur - cursor, 3)})

    all_declared = len(undeclared_sources) == 0
    checked = all_declared
    return {
        "checked": checked,
        "all_sources_declared": all_declared,
        "undeclared_sources": undeclared_sources,
        "min_gap_seconds": min_gap_seconds,
        "uncovered_gaps": gaps,
        "unassigned_discarded_ranges": unassigned_discarded_ranges,
        "review_needed": bool(undeclared_sources or gaps or unassigned_discarded_ranges),
    }


def review_items(audit):
    candidate, duration = audit["candidate"], audit["technical"]["duration"]
    comparison = audit["comparison"]
    groups = []
    for change in sorted(comparison["changes"], key=lambda item: (item["start_seconds"], item["end_seconds"])):
        if groups and change["start_seconds"] < groups[-1][-1]["end_seconds"]:
            groups[-1].append(change)
        else:
            groups.append([change])
    items = []
    for group in groups:
        start = max(0, group[0]["start_seconds"] - .5)
        end = min(duration, max(c["end_seconds"] for c in group) + .5)
        pairs = "\n".join(f"定稿：{c['script'] or '无'}；识别：{c['recognized'] or '无'}" for c in group)
        items.append((start, end, "请听这段：实际口播可以保留吗？", pairs))
    for phrase in comparison["omitted_phrase_candidates"]:
        if not items:
            items.append((0, duration, "确认这句是否按要求删除。", phrase))
    for row in comparison["repetition_candidates"]:
        start, end = max(0, row["start_seconds"] - .5), min(duration, row["end_seconds"] + .5)
        if not any(a < end and start < b for a, b, _, _ in items):
            items.append((start, end, "请听这段：这处重复需要保留吗？", row["text"]))
    for finding in audit["technical"]["candidates"]:
        black = re.search(r"black_start:([\d.]+) black_end:([\d.]+)", finding)
        silence = re.search(r"silence_end: ([\d.]+)\s*\| silence_duration: ([\d.]+)", finding)
        if black:
            start, end = map(float, black.groups())
            items.append((max(0, start - .25), min(duration, end + .25), "这处黑屏需要保留吗？", finding))
        elif silence and float(silence[2]) >= 3:
            end, length = map(float, silence.groups())
            items.append((max(0, end - length - .25), min(duration, end + .25), "这处长停顿需要保留吗？", finding))
    for gap in (audit.get("source_coverage") or {}).get("uncovered_gaps", []):
        items.append((
            0.0,
            min(duration, 2.0),
            f"请在原片 {gap['source_sha256'][:12]}… 核对未覆盖区间 "
            f"{gap['source_start']}s–{gap['source_end']}s。成片头两秒只是审核页面定位。",
            f"source {gap['source_start']}s-{gap['source_end']}s ({gap['gap_seconds']}s)",
        ))
    for disc in (audit.get("source_coverage") or {}).get("unassigned_discarded_ranges", []):
        start = disc.get("source_start", disc.get("start"))
        end = disc.get("source_end", disc.get("end"))
        items.append((0.0, min(duration, 2.0),
                      f"弃用区间 {start}s–{end}s 尚未绑定原片，未计入覆盖。请核对原片来源与删留范围。",
                      str(disc["reason"])))
    for unk_sha in (audit.get("source_coverage") or {}).get("undeclared_sources", []):
        items.append((
            0.0,
            min(duration, 2.0),
            "存在未登记总时长的原片素材，覆盖缺口未完全闭环，请核验该素材使用范围。",
            f"undeclared source sha: {unk_sha[:12]}...",
        ))
    items.sort(key=lambda item: item[0])
    return [{"review_id": f"post-cut-check-{i:03d}", "source_path": candidate["path"],
             "artifact_sha256": candidate["sha256"], "review_start_seconds": start, "review_end_seconds": end,
             "review_lane": "publication", "review_purpose": "当前粗剪复核",
             "review_question": question, "reference_text": reference}
            for i, (start, end, question, reference) in enumerate(items, 1)]



TRIAGE_SCHEMA = "self-media.rough-cut-triage.v1"


def validated_triage(report, audit_ref, triage):
    if triage.get("schema") != TRIAGE_SCHEMA or triage.get("audit") != audit_ref or not str(triage.get("reviewer", "")).strip():
        raise ValueError("rough_cut_triage_not_for_current_audit")
    candidates = review_items(report)
    rows = triage.get("decisions")
    if not isinstance(rows, list) or len(rows) != len(candidates):
        raise ValueError("rough_cut_triage_requires_all_candidates")
    by_id = {row["review_id"]: row for row in rows}
    if set(by_id) != {row["review_id"] for row in candidates}:
        raise ValueError("rough_cut_triage_references_unknown_or_duplicate_candidate")
    remaining = []
    for candidate in candidates:
        decision = by_id[candidate["review_id"]]
        state = decision.get("state")
        if state not in ("verified_keep", "needs_author_decision", "needs_rework") or not str(decision.get("basis", "")).strip():
            raise ValueError("rough_cut_triage_disposition_and_basis_required")
        if state == "needs_rework":
            raise ValueError("rough_cut_triage_requires_new_candidate: " + candidate["review_id"])
        if state == "needs_author_decision":
            question = decision.get("author_question")
            if question is not None:
                if not isinstance(question, str) or not question.strip() or len(question) > 140:
                    raise ValueError("rough_cut_author_question_invalid")
                candidate = {**candidate, "review_question": question.strip()}
            remaining.append(candidate)
    return remaining


def triaged_scope(audit_ref, triage_ref):
    payload = audit_ref["sha256"] + ":" + triage_ref["sha256"]
    return "post_cut_check:" + hashlib.sha256(payload.encode("ascii")).hexdigest()


def make_triaged_request(audit_path, triage_path, root):
    audit_ref, triage_ref = ref(audit_path), ref(triage_path)
    report = load(bound(audit_ref))
    candidate = bound(report["candidate"])
    rows = validated_triage(report, audit_ref, load(bound(triage_ref)))
    root.mkdir(parents=True, exist_ok=False)
    request = root / "review-request.json"
    write_new(request, {"schema_version": "self-media-human-review-request-pack.v1",
                        "scope": triaged_scope(audit_ref, triage_ref),
                        "project_identity": report["project_identity"], "rough_cut_triage": triage_ref,
                        "requests": rows or [automatic_item(report)]})
    if not candidate.is_file():
        raise ValueError("rough_cut_candidate_missing")
    return request, not rows


PRE_REVIEW_AUDIT_SCHEMA = "self-media.pre-review-audio-audit.v1"
AUDIO_AUDIT_SAMPLE_RATE = 16000
EDGE_WINDOW_SECONDS = 0.025
EDGE_FADE_SECONDS = 0.010
HOT_EDGE_DB = -33.0
HOT_EDGE_BODY_MARGIN_DB = 12.0
QUIET_VALLEY_TARGET_DB = -36.0
SHORT_CLIP_MERGE_SECONDS = 5.0


def _resolve_ffmpeg(explicit=None):
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return str(candidate.resolve())
        resolved = shutil.which(str(explicit))
        if resolved:
            return resolved
        raise ValueError("ffmpeg_executable_not_found")
    env_bin = os.environ.get("FFMPEG_BINARY")
    if env_bin and Path(env_bin).is_file():
        return str(Path(env_bin).resolve())
    which_bin = shutil.which("ffmpeg")
    if which_bin:
        return which_bin
    bin_dirs = []
    if os.environ.get("LECTURE_ASR_BIN_DIR"):
        bin_dirs.append(Path(os.environ["LECTURE_ASR_BIN_DIR"]))
    registry = next((parent / "scripts/local_tools.py" for parent in ROOT.parents
                     if (parent / "scripts/local_tools.py").is_file()), None)
    if registry is not None:
        try:
            registered = subprocess.check_output(
                [sys.executable, str(registry), "command", "video-knowledge-pipeline", "cli"],
                encoding="utf-8",
            )
            asr_bin = (json.loads(registered).get("value") or {}).get("wrapper_env", {}).get("LECTURE_ASR_BIN_DIR")
            if asr_bin:
                bin_dirs.append(Path(asr_bin))
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    for directory in bin_dirs:
        for name in ("ffmpeg.exe", "ffmpeg"):
            candidate = directory / name
            if candidate.is_file():
                return str(candidate.resolve())
    raise ValueError("ffmpeg_executable_not_found")


def _load_mono_16k_pcm16(path):
    with wave.open(str(path), "rb") as wf:
        channels, sampwidth, rate, nframes = wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()
        if channels != 1 or sampwidth != 2 or rate != AUDIO_AUDIT_SAMPLE_RATE:
            raise ValueError("audio_wav_must_be_16k_mono_pcm16")
        raw = wf.readframes(nframes)
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples, rate


def _ensure_source_wav(source_path, source_sha, audio_wav_path, cache_dir, ffmpeg_bin):
    if audio_wav_path is not None:
        samples, rate = _load_mono_16k_pcm16(Path(audio_wav_path).resolve(strict=True))
        return samples, len(samples) / rate
    if source_path.suffix.lower() == ".wav":
        try:
            samples, rate = _load_mono_16k_pcm16(source_path)
            return samples, len(samples) / rate
        except (ValueError, wave.Error):
            pass
    exe = _resolve_ffmpeg(ffmpeg_bin)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_wav = cache_dir / f"{source_sha[:16]}.wav"
    if not cached_wav.is_file():
        subprocess.run(
            [exe, "-nostdin", "-y", "-i", str(source_path), "-vn", "-ac", "1",
             "-ar", str(AUDIO_AUDIT_SAMPLE_RATE), "-c:a", "pcm_s16le", str(cached_wav)],
            check=True,
            capture_output=True,
        )
    samples, rate = _load_mono_16k_pcm16(cached_wav)
    return samples, len(samples) / rate


def _rms_db(samples, start_idx, end_idx):
    lo = max(0, int(start_idx))
    hi = min(len(samples), int(end_idx))
    if hi <= lo:
        return -120.0
    seg = samples[lo:hi]
    norm = 32768.0 * 32768.0
    mean_sq = sum(s * s for s in seg) / (len(seg) * norm)
    return round(20.0 * math.log10(max(math.sqrt(mean_sq), 1e-6)), 1)


def _find_quiet_edge(samples, sr, current_s, search_lo_s, search_hi_s, current_db, *, edge_kind):
    if search_hi_s <= search_lo_s:
        return None
    win_n = max(1, int(round(EDGE_WINDOW_SECONDS * sr)))
    step_s = 0.005
    best_valley = None
    fallback_valley = None
    t = search_lo_s
    while t <= search_hi_s + 1e-9:
        idx = int(round(t * sr))
        if edge_kind == "in":
            s_idx, e_idx = idx, idx + win_n
        else:
            s_idx, e_idx = idx - win_n, idx
        if 0 <= s_idx < e_idx <= len(samples):
            db = _rms_db(samples, s_idx, e_idx)
            dist = abs(t - current_s)
            cand = (db, dist, round(t, 3))
            if db <= QUIET_VALLEY_TARGET_DB and db <= current_db - 6.0:
                if best_valley is None or cand < best_valley:
                    best_valley = cand
            elif db <= HOT_EDGE_DB and db < current_db - 8.0:
                if fallback_valley is None or cand < fallback_valley:
                    fallback_valley = cand
        t += step_s
    chosen = best_valley or fallback_valley
    if chosen is None:
        return None
    return chosen[2], chosen[0]


def _write_concat_wav(path, chunks, sr=AUDIO_AUDIT_SAMPLE_RATE):
    combined = array.array("h")
    for chunk in chunks:
        combined.extend(chunk)
    if sys.byteorder != "little":
        combined.byteswap()
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(combined.tobytes())


def _apply_fade_copy(seg_samples, sr=AUDIO_AUDIT_SAMPLE_RATE):
    out = array.array("h", seg_samples)
    fade_n = min(int(round(EDGE_FADE_SECONDS * sr)), len(out) // 4)
    if fade_n > 1:
        denom = float(fade_n - 1)
        tail_offset = len(out) - fade_n
        for i in range(fade_n):
            gain = i / denom
            out[i] = int(round(out[i] * gain))
            out[tail_offset + i] = int(round(out[tail_offset + i] * gain))
    return out


def _clamp_cues(raw_cues, rs, re):
    cues = []
    for cue in raw_cues or []:
        if not isinstance(cue, dict):
            continue
        text = str(cue.get("text", "")).strip()
        a = cue.get("start_seconds", cue.get("start"))
        b = cue.get("end_seconds", cue.get("end"))
        if not text or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (a, b)):
            continue
        s = max(rs, round(float(a), 3))
        e = min(re, round(float(b), 3))
        if e > s + 0.05:
            item = {"start_seconds": s, "end_seconds": e, "text": text}
            for opt in ("layer", "speaker", "motion", "font_size_1080", "emphasis_reason"):
                if opt in cue:
                    item[opt] = cue[opt]
            cues.append(item)
        if len(cues) >= 40:
            break
    return cues


def pre_review_audio_audit(
    timeline_path,
    output_dir,
    *,
    script_path=None,
    identity_path=None,
    vkp_run_path=None,
    omissions=(),
    auto_fix_edges=True,
    ffmpeg_bin=None,
    vkp_runner=None,
    preparer=None,
):
    timeline_path = Path(timeline_path).resolve(strict=True)
    timeline_doc = load(timeline_path)
    normalized_rows = timeline_rows(timeline_doc)
    raw_rows = list(timeline_doc.get("segments", timeline_doc.get("nle_segments")))
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)

    top_wav = timeline_doc.get("audio_wav_path")
    unique_sources = {(r["source_ref"]["path"], r["source_ref"]["sha256"]) for r in normalized_rows}
    if top_wav and len(unique_sources) != 1:
        raise ValueError("top_level_audio_wav_path_requires_single_source")

    wav_cache = {}
    wav_dir = output_dir / "audio-cache"
    source_wav_override = {}
    for row, raw in zip(normalized_rows, raw_rows):
        src_ref = ref(row["source_ref"]["path"])
        if src_ref["sha256"] != row["source_ref"]["sha256"]:
            raise ValueError("rough_cut_input_changed")
        row["source_ref"] = src_ref
        override = raw.get("audio_wav_path") or top_wav
        if override:
            override_path = str(Path(override).resolve(strict=True))
            prev = source_wav_override.get(src_ref["sha256"])
            if prev and prev != override_path:
                raise ValueError("conflicting_audio_wav_override_for_source")
            source_wav_override[src_ref["sha256"]] = override_path

    for row in normalized_rows:
        sha = row["source_ref"]["sha256"]
        if sha not in wav_cache:
            samples, dur = _ensure_source_wav(
                Path(row["source_ref"]["path"]), sha, source_wav_override.get(sha), wav_dir, ffmpeg_bin
            )
            wav_cache[sha] = (samples, dur)

    working = []
    for idx, (row, raw) in enumerate(zip(normalized_rows, raw_rows)):
        sha = row["source_ref"]["sha256"]
        samples, src_dur = wav_cache[sha]
        cut_in = round(float(row["source_start"]), 3)
        cut_out = round(float(row["source_end"]), 3)
        prev_same_end = 0.0
        for j in range(idx - 1, -1, -1):
            if working[j]["source_ref"]["sha256"] == sha:
                prev_same_end = working[j]["cut_out"]
                break
        next_same_start = src_dur
        for j in range(idx + 1, len(normalized_rows)):
            if normalized_rows[j]["source_ref"]["sha256"] == sha:
                next_same_start = float(normalized_rows[j]["source_start"])
                break
        working.append({
            "seg_idx": idx,
            "raw": raw,
            "source_ref": row["source_ref"],
            "cut_in": cut_in,
            "cut_out": cut_out,
            "prev_same_end": prev_same_end,
            "next_same_start": min(src_dur, next_same_start),
            "source_duration": src_dur,
        })

    sr = AUDIO_AUDIT_SAMPLE_RATE
    edge_n = int(round(EDGE_WINDOW_SECONDS * sr))
    auto_fixed_count = 0
    for item in working:
        samples, _ = wav_cache[item["source_ref"]["sha256"]]
        raw = item["raw"]
        s_idx, e_idx = int(round(item["cut_in"] * sr)), int(round(item["cut_out"] * sr))
        in_db = _rms_db(samples, s_idx, min(e_idx, s_idx + edge_n))
        out_db = _rms_db(samples, max(s_idx, e_idx - edge_n), e_idx)
        body_db = _rms_db(samples, s_idx, e_idx)
        in_hot = (in_db > HOT_EDGE_DB) and (in_db > body_db - HOT_EDGE_BODY_MARGIN_DB)
        out_hot = (out_db > HOT_EDGE_DB) and (out_db > body_db - HOT_EDGE_BODY_MARGIN_DB)
        item["auto_fixed_in"] = None
        item["auto_fixed_out"] = None

        if auto_fix_edges:
            sha = item["source_ref"]["sha256"]
            if in_hot and not raw.get("intentional_hot_in"):
                prev_end = max(
                    [0.0] + [w["cut_out"] for w in working if w["seg_idx"] != item["seg_idx"]
                             and w["source_ref"]["sha256"] == sha and w["cut_out"] <= item["cut_in"] + 1e-6]
                )
                lo = max(prev_end, item["cut_in"] - 0.75)
                hi = item["cut_in"]
                found = _find_quiet_edge(samples, sr, item["cut_in"], lo, hi, in_db, edge_kind="in")
                if found is not None and found[0] < item["cut_out"] - 0.05:
                    new_in, new_db = found
                    item["auto_fixed_in"] = {
                        "old": item["cut_in"], "new": new_in,
                        "old_rms_db": in_db, "new_rms_db": new_db,
                    }
                    item["cut_in"] = new_in
                    auto_fixed_count += 1
                    s_idx = int(round(item["cut_in"] * sr))
                    in_db = _rms_db(samples, s_idx, min(e_idx, s_idx + edge_n))
                    body_db = _rms_db(samples, s_idx, e_idx)
                    in_hot = (in_db > HOT_EDGE_DB) and (in_db > body_db - HOT_EDGE_BODY_MARGIN_DB)

            if out_hot and not raw.get("intentional_hot_out"):
                next_start = min(
                    [item["source_duration"]] + [w["cut_in"] for w in working if w["seg_idx"] != item["seg_idx"]
                                                 and w["source_ref"]["sha256"] == sha and w["cut_in"] >= item["cut_out"] - 1e-6]
                )
                lo = max(item["cut_in"] + 0.10, item["cut_out"] - 0.20)
                hi = min(next_start, item["cut_out"] + 0.75)
                found = _find_quiet_edge(samples, sr, item["cut_out"], lo, hi, out_db, edge_kind="out")
                if found is not None and found[0] > item["cut_in"] + 0.10:
                    new_out, new_db = found
                    item["auto_fixed_out"] = {
                        "old": item["cut_out"], "new": new_out,
                        "old_rms_db": out_db, "new_rms_db": new_db,
                    }
                    item["cut_out"] = new_out
                    auto_fixed_count += 1
                    e_idx = int(round(item["cut_out"] * sr))
                    out_db = _rms_db(samples, max(s_idx, e_idx - edge_n), e_idx)
                    body_db = _rms_db(samples, s_idx, e_idx)
                    out_hot = (out_db > HOT_EDGE_DB) and (out_db > body_db - HOT_EDGE_BODY_MARGIN_DB)

        item.update(in_edge_rms_db=in_db, out_edge_rms_db=out_db, body_rms_db=body_db, in_hot=in_hot, out_hot=out_hot)

    chunks = []
    cursor = 0.0
    fixed_segments = []
    for item in working:
        samples, _ = wav_cache[item["source_ref"]["sha256"]]
        s_idx, e_idx = int(round(item["cut_in"] * sr)), int(round(item["cut_out"] * sr))
        seg_copy = _apply_fade_copy(samples[s_idx:e_idx], sr)
        seg_dur = len(seg_copy) / sr
        item["target_start"] = round(cursor, 3)
        item["target_end"] = round(cursor + seg_dur, 3)
        chunks.append(seg_copy)
        cursor += seg_dur

        beep_s = item["raw"].get("insert_beep_after_seconds")
        if beep_s is not None:
            if isinstance(beep_s, bool) or not isinstance(beep_s, (int, float)) or not 0 < beep_s <= 2.0:
                raise ValueError("insert_beep_after_seconds_invalid")
            n_beep = int(round(float(beep_s) * sr))
            beep = array.array("h", (int(round(4800.0 * math.sin(2.0 * math.pi * 1000.0 * i / sr))) for i in range(n_beep)))
            chunks.append(beep)
            cursor += len(beep) / sr

        fixed_seg = dict(item["raw"])
        fixed_seg.update({
            "source_ref": item["source_ref"],
            "source_start": item["cut_in"],
            "source_end": item["cut_out"],
            "target_start": item["target_start"],
            "target_end": item["target_end"],
        })
        fixed_segments.append(fixed_seg)

    concat_wav = output_dir / "postcut-concat-16k.wav"
    _write_concat_wav(concat_wav, chunks, sr)
    concat_ref = ref(concat_wav)

    fixed_timeline_doc = {k: v for k, v in timeline_doc.items() if k not in ("segments", "nle_segments")}
    fixed_timeline_doc["segments"] = fixed_segments
    fixed_timeline_path = output_dir / "postcut-timeline-fixed.json"
    write_new(fixed_timeline_path, fixed_timeline_doc)

    run_path = Path(vkp_run_path).resolve(strict=True) if vkp_run_path else (vkp_runner or run_local_vkp)(
        concat_wav, output_dir / "vkp"
    )
    vkp_segments, vkp_refs = vkp_transcript(concat_ref, run_path)

    findings = []
    review_cards = []
    verified_keep_count = 0
    total_segs = len(working)
    for idx, item in enumerate(working):
        raw = item["raw"]
        tin, tout = item["target_start"], item["target_end"]
        overlapping = [s for s in vkp_segments if float(s["end"]) > tin - 0.10 and float(s["start"]) < tout + 0.10]
        sv_text = "".join(s.get("text", "") for s in overlapping)
        sv_c = canonical(sv_text)

        first_text = str(raw.get("first_text", "") or raw.get("full_text", "") or raw.get("text", ""))
        last_text = str(raw.get("last_text", "") or raw.get("full_text", "") or raw.get("text", ""))
        prev_del = str(raw.get("prev_deleted_text", ""))
        next_del = str(raw.get("next_deleted_text", ""))

        head_full = canonical(first_text)
        tail_full = canonical(last_text)
        head_2 = head_full[:2]
        tail_2 = tail_full[-2:]
        head_ok = (head_2 in sv_c[:max(16, len(head_2) * 4)]) if head_2 else True
        tail_ok = (tail_2 in sv_c[-max(16, len(tail_2) * 4):]) if tail_2 else True

        bleed_in = False
        p_tail = canonical(prev_del)[-2:]
        if len(p_tail) == 2 and p_tail not in head_full[:4]:
            pos_head = sv_c.find(head_2) if head_2 else -1
            if pos_head > 0 and p_tail in sv_c[:pos_head]:
                bleed_in = True
            elif pos_head < 0 and p_tail in sv_c[:16]:
                bleed_in = True

        bleed_out = False
        n_head = canonical(next_del)[:2]
        if len(n_head) == 2 and n_head not in tail_full[-4:]:
            pos_tail = sv_c.rfind(tail_2) if tail_2 else -1
            if pos_tail >= 0 and n_head in sv_c[pos_tail + len(tail_2):]:
                bleed_out = True
            elif pos_tail < 0 and n_head in sv_c[-16:]:
                bleed_out = True

        is_opening = idx == 0
        is_closing = idx == total_segs - 1
        is_handoff_in = idx > 0 and working[idx - 1]["source_ref"]["sha256"] != item["source_ref"]["sha256"]
        is_handoff_out = idx < total_segs - 1 and working[idx + 1]["source_ref"]["sha256"] != item["source_ref"]["sha256"]

        flags = []
        if not head_ok:
            flags.append("asr_head_mismatch")
        if not tail_ok:
            flags.append("asr_tail_mismatch")
        if bleed_in:
            flags.append("possible_prev_deleted_bleed")
        if bleed_out:
            flags.append("possible_next_deleted_bleed")
        if item["in_hot"] and not raw.get("intentional_hot_in"):
            flags.append("hot_in_edge")
        if item["out_hot"] and not raw.get("intentional_hot_out"):
            flags.append("hot_out_edge")
        if raw.get("force_review"):
            flags.append("forced_review_cut")
        if is_opening or is_closing or is_handoff_in or is_handoff_out:
            flags.append("macro_boundary")

        disposition = "verified_keep" if not flags else "needs_author_decision"
        if disposition == "verified_keep":
            verified_keep_count += 1
        else:
            need_in = any(f in flags for f in (
                "asr_head_mismatch", "possible_prev_deleted_bleed", "hot_in_edge"
            )) or is_opening or is_handoff_in
            need_out = any(f in flags for f in (
                "asr_tail_mismatch", "possible_next_deleted_bleed", "hot_out_edge"
            )) or is_closing or is_handoff_out
            if "forced_review_cut" in flags and not (need_in or need_out):
                if raw.get("intentional_hot_out"):
                    need_out = True
                elif raw.get("intentional_hot_in"):
                    need_in = True
                else:
                    need_in = need_out = True

            ci, co = item["cut_in"], item["cut_out"]
            lane = raw.get("review_lane") or ("mixed" if "macro_boundary" in flags else "audio")
            modes = ["full"] if (co - ci) <= SHORT_CLIP_MERGE_SECONDS else [
                m for m, flag in (("in", need_in), ("out", need_out)) if flag
            ]
            for mode in modes:
                if mode == "in":
                    rs, re_ = ci, min(co, round(ci + 4.5, 3))
                    is_s, is_e = rs, min(re_, round(rs + 1.0, 3))
                    purpose = f"[最终切入点] {ci:.2f}s 起播（{','.join(flags)}）"
                    question = "直接按播放听开头：起音完整无吃字、没带入前句废音，对不对？"
                    ref_txt = f"最终保留开头：{first_text or raw.get('full_text', '')}"
                elif mode == "out":
                    re_ = co
                    rs = max(ci, round(co - 4.0, 3))
                    is_s, is_e = max(rs, round(re_ - 1.0, 3)), re_
                    purpose = f"[最终切出点] 播至 {co:.2f}s 准点停（{','.join(flags)}）"
                    question = "直接听到停住：尾音完整不截断、没带出后句废音，对不对？"
                    ref_txt = f"最终保留结尾：{last_text or raw.get('full_text', '')}"
                else:
                    rs, re_ = ci, co
                    is_s, is_e = ci, co
                    purpose = f"[短保留整句] {ci:.2f}->{co:.2f}s（{','.join(flags)}）"
                    question = "直接听完整这一句：首尾完整干净、无吃字无漏废字，对不对？"
                    ref_txt = f"最终保留整句：{raw.get('full_text') or first_text or last_text}"

                card = {
                    "review_id": f"pre-review-{idx:03d}-{mode}",
                    "source_path": item["source_ref"]["path"],
                    "artifact_sha256": item["source_ref"]["sha256"],
                    "workflow_stage": "rough_cut_recipe",
                    "review_lane": lane,
                    "playback_mode": "normal",
                    "review_start_seconds": round(rs, 3),
                    "review_end_seconds": round(re_, 3),
                    "issue_start_seconds": round(is_s, 3),
                    "issue_end_seconds": round(is_e, 3),
                    "review_purpose": purpose,
                    "review_question": question,
                    "reference_text": ref_txt,
                    "status": "pending",
                    "review_access_mode": "source_time_range",
                }
                cues = _clamp_cues(raw.get("subtitle_cues"), rs, re_)
                if cues:
                    card["subtitle_cues"] = cues
                review_cards.append(card)

        findings.append({
            "seg_idx": idx,
            "source_ref": item["source_ref"],
            "cut_in": item["cut_in"],
            "cut_out": item["cut_out"],
            "target_start": item["target_start"],
            "target_end": item["target_end"],
            "in_edge_rms_db": item["in_edge_rms_db"],
            "out_edge_rms_db": item["out_edge_rms_db"],
            "body_rms_db": item["body_rms_db"],
            "auto_fixed_in": item["auto_fixed_in"],
            "auto_fixed_out": item["auto_fixed_out"],
            "flags": flags,
            "disposition": disposition,
            "vkp_overlap_text": sv_text[:180],
        })

    script_comparison = None
    script_ref = None
    if script_path is not None:
        script_ref = ref(script_path)
        script_comparison = compare(script_ref["path"], vkp_segments, omissions)
    coverage = source_coverage_gaps(fixed_timeline_doc)

    identity_obj = load(Path(identity_path).resolve(strict=True)) if identity_path else timeline_doc.get("project_identity")
    audit_report = {
        "schema": PRE_REVIEW_AUDIT_SCHEMA,
        "timeline_source": ref(timeline_path),
        "fixed_timeline": ref(fixed_timeline_path),
        "concat_audio_wav": concat_ref,
        "concat_audio_bytes": concat_wav.stat().st_size,
        "script": script_ref,
        "vkp": vkp_refs,
        "segment_count": total_segs,
        "verified_keep_count": verified_keep_count,
        "flagged_count": total_segs - verified_keep_count,
        "auto_fixed_count": auto_fixed_count,
        "review_card_count": len(review_cards),
        "script_comparison": script_comparison,
        "source_coverage": coverage,
        "findings": findings,
    }
    audit_path = output_dir / "pre-review-audio-audit.json"
    write_new(audit_path, audit_report)
    audit_ref = ref(audit_path)

    result = {
        "schema": PRE_REVIEW_AUDIT_SCHEMA,
        "audit": str(audit_path),
        "fixed_timeline": str(fixed_timeline_path),
        "concat_audio_wav": str(concat_wav),
        "concat_audio_bytes": concat_wav.stat().st_size,
        "segment_count": total_segs,
        "verified_keep_count": verified_keep_count,
        "auto_fixed_count": auto_fixed_count,
        "review_card_count": len(review_cards),
        "media_copies_created": 0,
        "media_export_authorized": False,
    }
    if not review_cards:
        result.update(status="all_verified_keep", review_request=None, review_page=None, bundle_dir=None)
        return result

    req_doc = {
        "schema_version": "self-media-human-review-request-pack.v1",
        "scope": "pre_review_audio_audit:" + audit_ref["sha256"],
        "requests": review_cards,
    }
    if identity_obj is not None:
        req_doc["project_identity"] = identity_obj
    req_path = output_dir / "review-request.json"
    write_new(req_path, req_doc)

    import video_review_delivery as delivery
    review = delivery.prepare(req_path, output_dir / "review", "rough_cut_recipe", preparer=preparer)
    result.update(
        status="needs_review",
        review_request=str(req_path),
        review_page=review.get("review_html"),
        bundle_dir=review.get("bundle_dir"),
        pack_path=review.get("pack_path"),
        decisions_path=review.get("decisions_path"),
    )
    return result
