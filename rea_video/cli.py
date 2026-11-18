"""rea-video command line."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from .util import ASR_LANGS, LOG, OCR_LANGS, load_env_files, read_json, setup_logging, read_image
from .i18n import DEFAULT_LANG, LANGS, T, set_lang
from .classify import LABELS
from .vlm import vlm_note



def _env(args) -> None:
    from .memory import pref

    # 不读当前目录的 .env：在别人的仓库里运行时，它可以改 VLM 地址或 CAPSULE_CINEMA_PYTHON
    files = [Path(__file__).resolve().parent.parent / ".env"]
    explicit = getattr(args, "env_file", None)
    env_file = explicit or pref("env_file")
    if env_file:
        if not Path(env_file).expanduser().is_file():
            # silently skipping it made people think the VLM was configured
            msg = T("找不到配置文件 {p}", "env file not found: {p}", p=env_file)
            if explicit:
                raise SystemExit(f"rea-video: {msg}")
            LOG.warning("%s%s", msg, T("（来自 prefs env_file）", " (from prefs env_file)"))
        files.insert(0, Path(env_file))
    loaded = load_env_files(files)
    if loaded:
        LOG.debug("env loaded from %s", loaded)


def _ocr_lang(args) -> None:
    """--ocr-lang (or prefs ocr_lang) -> $REA_OCR_LANG, which overlay.get_ocr reads."""
    from .memory import pref

    lang = getattr(args, "ocr_lang", None) or pref("ocr_lang")
    if lang:
        if lang not in OCR_LANGS:
            raise SystemExit(f"Unsupported OCR language {lang} (choose from {', '.join(OCR_LANGS)})")
        os.environ["REA_OCR_LANG"] = lang


def _asr_lang(args) -> None:
    """--asr-lang (or prefs asr_lang) -> $REA_ASR_LANG, which speech.transcribe reads."""
    from .memory import pref

    lang = getattr(args, "asr_lang", None) or pref("asr_lang")
    if lang:
        if lang not in ASR_LANGS:
            raise SystemExit(f"Unsupported speech language {lang} (choose from {', '.join(ASR_LANGS)})")
        os.environ["REA_ASR_LANG"] = lang


def _check_vlm_config() -> None:
    """Reject external model calls before any video processing starts."""
    from .vlm import EXTERNAL_VLM_DISABLED

    raise SystemExit(f"rea-video: {EXTERNAL_VLM_DISABLED}")


def cmd_decompose(args) -> int:
    from .pipeline import decompose

    _ocr_lang(args)
    _asr_lang(args)

    out = Path(args.out) if args.out else Path("out") / Path(args.video).stem
    from .memory import pref

    meta = read_json(Path(args.meta)) if args.meta else None
    use_vlm = args.vlm
    if use_vlm:
        _check_vlm_config()
    stems = not args.no_stems and pref("stems", "on") == "on"
    lang = args.lang or pref("lang", DEFAULT_LANG)
    if lang not in LANGS:
        raise SystemExit(f"Unsupported report language {lang} (choose from {', '.join(LANGS)})")
    b = decompose(args.video, out, use_vlm=use_vlm, whole_vlm=not args.no_whole, ocr=not args.no_ocr,
                  workers=args.workers, engine=args.engine or pref("engine"), platform_meta=meta, stems=stems,
                  packaging=not args.no_packaging, lang=lang, asr=not args.no_asr, max_shots_vlm=max(1, args.max_vlm_shots),
                  speakers=not args.no_speakers, survey=not args.no_survey)
    print(json.dumps({"out": str(out), "verdict": b["summary"]["verdict"], "shots": b["summary"]["shots"],
                      "confidence": b["summary"]["confidence"], "vlm": b["summary"]["vlm"],
                      "report": str(out / "report.html")}, ensure_ascii=False, indent=2))
    return 0


def cmd_survey(args) -> int:
    from .media import video_info
    from .memory import pref
    from .shots import build_track, detect_shots
    from .survey import run

    out = Path(args.out) if args.out else Path("out") / Path(args.video).stem
    info = video_info(args.video)
    track = build_track(str(args.video), info)
    asker = None
    if args.vlm:
        _check_vlm_config()
    res = run(Path(args.video).expanduser().resolve(), out.expanduser().resolve(), track, detect_shots(track), info,
              asker=asker, workers=args.workers, detail=not args.no_detail)
    if res["status"] == "waiting":
        res["next"] = T("看 images 里的图，按 tasks 里的问题把答案写进 waiting 里的文件（各文件互不相关，可以并发），再运行同一条命令",
                        "look at the images, answer the questions in tasks into the waiting files (independent: can run in parallel), then run the same command again")
    else:
        res["next"] = T("运行 rea-video decompose（同一个 -o），镜头按这次的切点切分，关键帧和节奏写进报告",
                        "run rea-video decompose (same -o): shots follow these cuts, key frames and rhythm go into the report")
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


def cmd_review(args) -> int:
    """Write review_tasks.json + review_answers.json so a multimodal agent can act as the VLM."""
    from .review import build_tasks

    out = Path(args.out_dir)
    b = read_json(out / "breakdown.json")
    set_lang(b.get("lang", DEFAULT_LANG))
    tasks, answers = build_tasks(b, str(out))
    from .util import dumps_rows

    (out / "review_tasks.json").write_text(dumps_rows(tasks), encoding="utf-8")
    ans_path = out / "review_answers.json"
    if args.force or not ans_path.is_file():
        ans_path.write_text(dumps_rows(answers), encoding="utf-8")
    high = [s for s in tasks["shots"] if s["priority"] == "high"]
    print(f"{len(tasks['shots'])} shots to review; {len(high)} high priority: " + ", ".join(f"{s['id']}({'; '.join(s['why'])})" for s in high))
    print(f"Instructions and image paths: {out / 'review_tasks.json'}")
    print(f"Write answers to: {ans_path}")
    print(f"Then run: rea-video apply-review {out} --by <NAME>")
    return 0


def cmd_apply_review(args) -> int:
    from .pipeline import finalize
    from .review import apply_answers

    out = Path(args.out_dir)
    b = read_json(out / "breakdown.json")
    if args.lang:
        b["lang"] = args.lang
    set_lang(b.get("lang", DEFAULT_LANG))
    answers = read_json(Path(args.answers) if args.answers else out / "review_answers.json")
    from .memory import pref

    log = apply_answers(b, answers, by=args.by or pref("reviewer"))
    b = finalize(b, out)
    for p in log["problems"]:
        print(f"Skipped {p}")
    if log.get("unanswered"):
        print(f"Skipped {len(log['unanswered'])} unanswered shots")
    changed = [(r["id"], log["before"][r["id"]], r["base"]["label"]) for r in b["shots"]
               if r["id"] in log["before"] and log["before"][r["id"]] != r["base"]["label"]]
    print(f"Applied {len(log['applied'])}/{len(b['shots'])} shots; changed {len(changed)} labels" +
          ("：" + ", ".join(f"{i} {a}→{c}" for i, a, c in changed) if changed else ""))
    print(f"Verdict: {b['summary']['verdict']}")
    print(f"VLM: {b['summary']['vlm']}")
    if log.get("packaging"):
        print('Applied packaging review: ' + ", ".join(f"{k} {n}" for k, n in log["packaging"].items()))
    if not log["applied"] and not log.get("packaging") and not log["problems"]:
        print('No answers to apply; fill in review_answers.json using review_tasks.json first')
    return 0 if log["applied"] or log.get("packaging") else 1


def cmd_stems(args) -> int:
    from .stems import extract_stems

    out = Path(args.out) if args.out else Path("out") / Path(args.video).stem
    print(json.dumps(extract_stems(args.video, out), ensure_ascii=False, indent=2))
    return 0


def cmd_probe(args) -> int:
    from .media import video_info
    from .probe import provenance

    info = video_info(args.video)
    p = provenance(info)
    p.pop("tags", None) if not args.tags else None
    print(json.dumps({"width": info.width, "height": info.height, "fps": info.fps, "duration": info.duration,
                      "vcodec": info.vcodec, "aspect_ratio": info.aspect_ratio, "provenance": p}, ensure_ascii=False, indent=2))
    return 0


def cmd_eval(args) -> int:
    from .evaluate import evaluate

    _ocr_lang(args)

    if args.vlm:
        _check_vlm_config()
    res = evaluate(Path(args.labels), Path(args.out), use_vlm=args.vlm, ocr=not args.no_ocr, reuse=not args.fresh,
                   only=set(args.only.split(",")) if args.only else None, stems=args.stems)
    print(json.dumps(res["summary"], ensure_ascii=False, indent=2))
    gone = res["summary"].get("missing")
    if gone:
        print("rea-video: " + T("只评了 {n}/{m} 个样本，其余找不到文件：{ids}", "scored {n} of {m} videos, files missing for: {ids}",
                                  n=res["summary"]["videos"], m=res["summary"]["videos_listed"], ids=", ".join(gone)), file=sys.stderr)
    return 0


def cmd_videomd(args) -> int:
    from .videomd import write

    root = Path(args.out_dir)
    if args.check:
        from .videomd import check

        errs = check(root)
        print("\n".join(errs) if errs else T("符合 VIDEO.md 规范", "conforms to the VIDEO.md spec"))
        return 1 if errs else 0
    b = read_json(root / "breakdown.json")
    set_lang(b.get("lang", DEFAULT_LANG))
    print(write(b, root))
    return 0


def cmd_pdf(args) -> int:
    from .pdf import write_pdf

    try:
        print(write_pdf(Path(args.out_dir)))
    except RuntimeError as e:
        print(f"rea-video: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_capsule(args) -> int:
    from .integrations.capsule_cinema import export_capsule_analysis

    b = read_json(Path(args.breakdown))
    out = export_capsule_analysis(b, Path(args.out) if args.out else Path(args.breakdown).with_name("capsule_analysis.json"))
    print(out)
    return 0


def _capsule_root(args, check: bool = True) -> Path:
    from .memory import capsule_root

    root = capsule_root(args.capsule_root)
    if check and not root.is_dir():
        raise SystemExit(T(f"找不到 capsule-cinema 仓库：{root}。用 --capsule-root 指定，或 rea-video prefs capsule_root <路径> 设成默认",
                           f"capsule-cinema repo not found: {root}. Pass --capsule-root, or set it once with: rea-video prefs capsule_root <path>"))
    return root


def cmd_remake_plan(args) -> int:
    from .integrations.capsule_cinema import build_remake_jobs

    bdir = Path(args.breakdown).parent
    root = _capsule_root(args)
    try:  # the jobs are the remake plan's units as they stand: change the model or the swaps with `rea-video plan`
        jobs = build_remake_jobs(read_json(Path(args.breakdown)), bdir, capsule_root=root)
    except ValueError as exc:
        print(f"rea-video: {exc}", file=sys.stderr)
        return 2
    print(jobs)
    return 0


def _capsule_python(explicit: str | None, capsule_root: Path) -> str:
    'capsule-cinema interpreter: --python > CAPSULE_CINEMA_PYTHON > checkout .venv > current Python.'
    if explicit or os.getenv("CAPSULE_CINEMA_PYTHON"):
        return explicit or os.environ["CAPSULE_CINEMA_PYTHON"]
    venv = capsule_root.expanduser() / ".venv/bin/python"
    return str(venv) if venv.is_file() else sys.executable


def _run_integration(script: str, python: str, argv: list[str]) -> int:
    import subprocess

    path = Path(__file__).resolve().parent / "integrations" / script
    return subprocess.call([python, str(path), *argv])


def cmd_remake_run(args) -> int:
    jobs = Path(args.jobs).expanduser().resolve()
    # capsule-root 只认命令行（jobs.json 可能是别人给的，不能让它决定跑哪个解释器、import 哪里的代码）
    root = _capsule_root(args, check=not args.dry_run)
    argv = ["--jobs", str(jobs), "--capsule-root", str(root)] + (["--only", args.only] if args.only else []) + (["--dry-run"] if args.dry_run else [])
    # 试跑不调用 capsule-cinema，用当前解释器即可
    python = sys.executable if args.dry_run and not args.python else _capsule_python(args.python, root)
    return _run_integration("run_remake.py", python, argv)


def cmd_capsule_draft(args) -> int:
    root = _capsule_root(args)
    argv = ["--breakdown", str(Path(args.breakdown).expanduser().resolve()), "--capsule-root", str(root)]
    argv += ["--capsule-name", args.capsule_name] if args.capsule_name else []
    argv += ["--capsule-display-name", args.capsule_display_name] if args.capsule_display_name else []
    argv += ["--write-capsule"] if args.write_capsule else []
    argv += ["--overwrite-capsule"] if args.overwrite_capsule else []
    return _run_integration("to_capsule.py", _capsule_python(args.python, root), argv)


def cmd_assemble(args) -> int:
    from .remake import assemble

    print(assemble(Path(args.breakdown), Path(args.results), Path(args.out) if args.out else None, overlays=args.overlays))
    return 0


def cmd_tiles(args) -> int:
    """Time-labelled frame grid for close inspection of a passage."""
    import cv2
    import numpy as np

    from .media import extract_frame, video_info
    from .visual import shot_sheet

    # bad numbers used to die deep inside numpy / PIL with a traceback, or silently print an empty result
    if args.every <= 0:
        raise SystemExit('rea-video: --every must be greater than 0 (frame sampling interval in seconds)')
    if args.start < 0:
        raise SystemExit('rea-video: --start must not be negative')
    if args.cols < 1:
        raise SystemExit('rea-video: --cols must be at least 1')
    if args.max < 1:
        raise SystemExit('rea-video: --max must be at least 1')
    if args.cell < 1:
        raise SystemExit('rea-video: --cell must be at least 1')
    info = video_info(args.video)
    end = args.end if args.end is not None else info.duration
    if args.start >= end:
        raise SystemExit(f"rea-video: --end must be greater than --start (video duration: {info.duration:.2f}s)")
    times = list(np.arange(args.start, end, args.every))[: args.max]
    import tempfile

    frames = []
    with tempfile.TemporaryDirectory() as tmpd:
        for i, t in enumerate(times):
            p = extract_frame(args.video, float(t), Path(tmpd) / f"tile_{i:03d}.jpg", width=args.cell)
            img = read_image(p)
            if img is not None:
                frames.append(img)
    rows = [frames[i:i + args.cols] for i in range(0, len(frames), args.cols)]
    paths = []
    for r, row in enumerate(rows):
        out = Path(args.out) if len(rows) == 1 else Path(args.out).with_name(f"{Path(args.out).stem}_{r + 1}{Path(args.out).suffix}")
        shot_sheet(row, [float(t) for t in times[r * args.cols:(r + 1) * args.cols]], out, n=len(row), cell_w=args.cell)
        paths.append(str(out))
    print(json.dumps({"tiles": paths, "times": [round(float(t), 3) for t in times]}, ensure_ascii=False))
    return 0


def cmd_frames(args) -> int:
    from .layers import scene_frames

    if args.every <= 0:
        raise SystemExit('rea-video: --every must be greater than 0')
    out = Path(args.out_dir)
    if not (out / "breakdown.json").is_file():
        raise SystemExit(f"rea-video: no breakdown.json in {out}; run decompose first")
    res = scene_frames(out, every=args.every, n_points=args.points, all_shots=args.all)
    if not res["scenes"]:
        print(T('No code-rendered shots; add --all to extract frames from every shot', "no code-rendered shots (add --all to cover every shot)"))
        return 0
    print(json.dumps({"scenes": len(res["scenes"]), "file": str(out / "frames" / "scenes.json"),
                      "cuts": [s["start"] for s in res["scenes"]]}, ensure_ascii=False))
    return 0


def cmd_compare(args) -> int:
    from .layers import compare

    if args.every <= 0:
        raise SystemExit('rea-video: --every must be greater than 0')
    for p in (args.ref, args.remake):
        if not Path(p).is_file():
            raise SystemExit(f"rea-video: file not found: {p}")
    res = compare(args.ref, args.remake, every=args.every, out=Path(args.out) if args.out else None,
                  scenes=Path(args.scenes) if args.scenes else None, worst=args.worst)
    brief = {k: res[k] for k in ("score", "place", "shape", "offset", "advice", "worst") if k in res}
    if res.get("scenes"):
        brief["lowest_scenes"] = res["scenes"][:5]
    if res.get("sheet"):
        brief["sheet"] = res["sheet"]
    print(json.dumps(brief, ensure_ascii=False, indent=1))
    return 0


def cmd_remake(args) -> int:
    from .remake import remake

    out = Path(args.out_dir)
    if not (out / "breakdown.json").is_file():
        raise SystemExit(f"rea-video: no breakdown.json in {out}; run decompose first")
    print(json.dumps(remake(out, code=args.code, overlays=not args.no_overlays), ensure_ascii=False, indent=1))
    return 0


def cmd_code_remake(args) -> int:
    from .code_remake import code_remake

    out = Path(args.out_dir)
    if not (out / "breakdown.json").is_file():
        raise SystemExit(f"rea-video: no breakdown.json in {out}; run decompose first")
    try:
        res = code_remake(out, reset=args.reset, render=not args.no_render, score=not args.no_compare)
    except ValueError as e:
        raise SystemExit(f"rea-video: {e}")
    res.pop("matched", None)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


def cmd_drive(args) -> int:
    from .drive import drive, join

    out = Path(args.out_dir)
    if not (out / "breakdown.json").is_file():
        raise SystemExit(f"rea-video: no breakdown.json in {out}; run decompose first")
    try:
        if args.join is not None:
            res = join(out, Path(args.join) if args.join else None)
        else:
            shots = None
            if args.shots:
                shots = []
                for part in args.shots.split(","):
                    a, _, z = part.strip().partition("-")
                    shots += list(range(int(a), int(z or a) + 1))
            res = drive(out, shots=shots, depth=args.depth, clean=not args.no_clean, prefer=args.prefer, max_s=args.max)
            res = {k: v for k, v in res.items() if k != "segments"} | {"segments": [
                {k: s[k] for k in ("id", "start", "end", "duration", "cut_in", "cuts_inside")} for s in res["segments"]],
                "readme": str(out / "drive" / "README.md")}
    except (ValueError, FileNotFoundError) as e:
        raise SystemExit(f"rea-video: {e}")
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


def cmd_summary(args) -> int:
    """Compact, agent-friendly view of a breakdown (instead of reading the whole JSON)."""
    from .i18n import T, join

    b = read_json(Path(args.breakdown))
    set_lang(b.get("lang", DEFAULT_LANG))
    s = b["summary"]
    lines = [f"{b['source']['filename']} | {b['source']['duration']}s {b['source']['width']}x{b['source']['height']} {b['source']['fps']}fps",
             f"{T('结论', 'Verdict')}: {s['verdict']}", f"{T('置信度', 'Confidence')}: {s['confidence']}", f"VLM: {s.get('vlm') or vlm_note(b['analysis']['vlm'])}", ""]
    from . import narrative

    steps = narrative.beats(b)
    if steps:
        lines[-1:-1] = [T("叙事线", "Narrative") + ": " + " → ".join(
            f"#{s['shots'][0]}" + (f"-{s['shots'][-1]}" if len(s['shots']) > 1 else "") + f" {s['role_zh'] or (s['points'] or ['?'])[0][:16]}" for s in steps)]
    vc = b.get("video_context") or {}
    if vc.get("transcoded"):
        lines.append(T("平台转码: {p}（噪声类证据失效；原生 30fps 无重复帧: {n}）", "Platform transcode: {p} (noise evidence unusable; native 30fps without duplicate frames: {n})",
                       p=join(vc.get("platform", [])), n=vc.get("native30")))
    prov = b.get("provenance", {})
    if prov.get("aigc") or prov.get("hints"):
        lines.append(f"{T('元数据', 'Metadata')}: aigc={prov.get('aigc')} hints={prov.get('hints')}")
    from .aspects import shot_text
    from .memory import hint_for, patterns

    pats = patterns()
    low_n = sum(r["base"]["confidence"] < 0.6 for r in b["shots"])
    mark_low = low_n <= len(b["shots"]) / 2  # when most shots are low, one line says so instead of a tag on every row
    if not mark_low:
        sure = [str(r["index"]) for r in b["shots"] if r["base"]["confidence"] >= 0.6]
        lines.append(T("低置信: {n}/{m} 镜置信度 <0.6，都要复核", "Low confidence: {n}/{m} shots below 0.6, review them all", n=low_n, m=len(b["shots"]))
                     + (T("（只有 #{s} 不用）", " (all but #{s})", s=",".join(sure)) if sure else ""))
    notes: list[str] = []  # the same "待确认" sentence repeats across shots: number it, print each once below the table

    def note_ref(text: str) -> str:
        if text not in notes:
            notes.append(text)
        return T("待确认{i}", "open question {i}", i="①②③④⑤⑥⑦⑧⑨⑩"[notes.index(text)] if notes.index(text) < 10 else f"({notes.index(text) + 1})")

    for r in b["shots"]:
        base = r["base"]
        alt = sorted(base["probs"].items(), key=lambda kv: -kv[1])[1]
        det = r["deterministic"]["probs"]
        past = None if base["decided_by"] == "user" or r.get("review") else hint_for(max(det, key=det.get), pats)  # looked at: settled
        mat = (r.get("material") or {}).get("origin_zh", "")
        second = T("(用户纠正)", "(user correction)") if base["decided_by"] == "user" else T("(次选 {l} {p:.2f})", "(runner-up {l} {p:.2f})", l=alt[0], p=alt[1])
        lines.append(f"#{r['index']:>2} {r['start']:7.2f}-{r['end']:7.2f} {base['label']:<14} {base['confidence']:.2f} {second} "
                     f"| {T('素材', 'material')}:{mat} | {T('叠加', 'overlays')}:{','.join(sorted({l['kind'] for l in r.get('layers', [])})) or '-'} | {r['features'].get('camera')}"
                     + (T("  ← 低置信，需要复核", "  ← low confidence, review it") if mark_low and base["confidence"] < 0.6 else "")
                     + (f"  ← {note_ref(base['uncertain'])}" if base.get("uncertain") else "")
                     + (T("  ← 有分歧：{d}", "  ← disputed: {d}", d=base["disputed"]) if base.get("disputed") else "")
                     + (T("  ← 用户纠正过素材来源", "  ← material origin corrected by the user") if (r.get("material") or {}).get("user_corrected") else "")
                     + (f"  ← {past}" if past else "")
                     + (f" | {shot_text(r, brief=True)}" if r["base"]["label"] in ("live_action", "avatar") and shot_text(r, brief=True) else "")
                     + (T(" | 动效 {n} 个，元素截图 {f}", " | {n} motion events, element crops {f}", n=len(r["motion"].get("events", [])),
                          f=r["motion"]["elements_sheet"]) if r["base"]["label"] in ("code_render", "screen_capture")
                        and (r.get("motion") or {}).get("elements_sheet") else ""))
    if notes:
        lines += [f"{note_ref(n)}: {n}" for n in notes]
    if s.get("aspects"):
        lines += [""] + s["aspects"]
    from .entities import cast

    c = cast(b)
    if c["characters"] or c["scenes"]:
        lines.append("")
        for ch in c["characters"]:
            lines.append(f"{T('角色', 'Character')} {ch['id']} {ch['name']} | {ch['look']} | {T('镜头', 'shots')} {','.join(str(i) for i in ch['shots']) or '-'}")
        for sc in c["scenes"]:
            lines.append(f"{T('场景', 'Scene')} {sc['id']} {sc['where']} {sc['when']} | {sc['look']} | {T('镜头', 'shots')} {','.join(str(i) for i in sc['shots']) or '-'}")
    a = b.get("audio", {})
    if a.get("has_audio"):
        mu = a.get("music", {})
        lines += ["", f"{T('人声', 'Voice')}: {a.get('voice', {}).get('present')} ({a.get('voice', {}).get('ratio')}) | {T('音乐', 'Music')}: {mu.get('present')} "
                      f"{(T('无明显节拍', 'no beat') if mu.get('no_beat') else (str(mu['tempo_bpm']) + 'BPM' if mu.get('tempo_bpm') is not None else ''))} {(mu.get('key') or {}).get('tonic', '')}{(mu.get('key') or {}).get('mode', '')} | "
                      f"{T('音效', 'SFX')}: {_sfx_count(b)} | {T('卡点', 'beat-synced')}: {a.get('beat_synced_edit')}"]
        if (b.get("sound_sources") or {}).get("summary_zh"):
            lines.append(f"{T('声音来源', 'Sound sources')}: " + b["sound_sources"]["summary_zh"])
        if (b.get("stems") or {}).get("ok"):
            lines.append(T("音轨: stems/original.wav（原声） stems/vocals.wav（人声） stems/music.wav（配乐）",
                           "Stems: stems/original.wav (original) stems/vocals.wav (voice) stems/music.wav (music)"))
    pk = b.get("packaging")
    if pk:
        tag = T("包装", "Packaging")
        lines += [""] + [f"{tag}: {x}" for x in (pk.get("summary_zh") or [T("没有检出后期叠加的文字或贴纸", "no overlaid text or stickers detected")])]
        low = [st for st in pk.get("stickers", []) if not st.get("in_picture") and st.get("confidence") in ("low", "vlm")]
        if low:
            lines.append(f"{tag}: " + T("需要看图确认的贴纸 ", "stickers to confirm by eye ") + join(f"{st['id']} {st['t0']:.1f}-{st['t1']:.1f}s" for st in low)
                         + T("（截图在 packaging/）", " (crops under packaging/)"))
        if pk.get("files"):
            lines.append(f"{T('包装文件', 'Packaging files')}: " + " ".join(pk["files"].values()))
    print("\n".join(lines))
    return 0


def _sfx_count(b: dict) -> str:
    sfx = (b.get("audio_plan") or {}).get("sfx_merged", [])
    maybe = sum(1 for e in sfx if e.get("confidence") == "low")
    sure = len(sfx) - maybe
    return f"{sure}" + (T(" + 可能 {m}（待确认）", " + {m} possible (unconfirmed)", m=maybe) if maybe else "")


def cmd_correct(args) -> int:
    """The user says a shot is wrong: fix this breakdown and remember the correction."""
    from .memory import correct
    from .pipeline import finalize

    out = Path(args.out_dir)
    b = read_json(out / "breakdown.json")
    real = None if args.real is None else args.real == "yes"
    try:
        logged = correct(b, label=args.label, real=real, shots=args.shots, start=args.start, end=args.end, note=args.note or "")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    b = finalize(b, out)
    changed = [f"{c['shot']} {c['before']}→{c['label']}" for c in logged if c.get("label") and c["before"] != c["label"]]
    print(f"Corrected {len(logged)} shots" + ((": " + ", ".join(changed)) if changed else "") + "; saved to memory")
    print(f"Verdict: {b['summary']['verdict']}")
    return 0


def cmd_plan(args) -> int:
    """The remake part of the report, from the remake intent (remake/intent.yaml: model, generate all or only the AI
    shots, what is swapped for what). The breakdown itself is not touched."""
    from .generation import load_intent, save_intent
    from .integrations.capsule_cinema import ref_clips
    from .pipeline import finalize
    from .plan import CAP, Planner, user_capabilities
    from .production import _norm

    out = Path(args.out_dir)
    intent = load_intent(out)
    if args.model:
        intent["model"] = args.model
    if args.generate:
        intent["generate"] = args.generate
    if not intent.get("model"):
        print(T("rea-video: 还没选模型：问用户用哪个，写进 {p} 的 model，或加 --model", "rea-video: no model yet: ask the user, then set model in {p} or pass --model",
                p=out / "remake" / "intent.yaml"), file=sys.stderr)
        return 2
    pl = Planner()
    live = {k: m for k, m in pl.models.items() if m.get("status") not in ("shutdown", "deprecated")}
    m = next((x for x in live.values() if _norm(x["id"]) == _norm(intent["model"]) or _norm(x.get("name", "")) == _norm(intent["model"])), None)
    if not m:
        print(f"rea-video: unknown model {intent['model']}. Check its official documentation for limits, "
              f"reference inputs, multi-shot support, key frames, audio, and prompting. Use {CAP / 'models' / 'video.yaml'} "
              f"as a template for {user_capabilities() / 'models' / (re.sub(r'[^a-z0-9.-]+', '-', intent['model'].lower()) + '.yaml')}, "
              "then try again. List recorded models with: rea-video models", file=sys.stderr)
        return 2
    intent["model"] = m["id"]
    save_intent(out, intent)
    b = read_json(out / "breakdown.json")
    set_lang(b.get("lang", DEFAULT_LANG))
    b = finalize(b, out, engine=m["id"])
    plan = b.get("production_plan") or {}
    n = sum(len(ref_clips(b, out, u)) for u in plan.get("units") or [])
    v = m.get("verified") or {}
    print(T("复刻方案已按 {m} 重出（报告第二部分）：{p}", "Remake plan redone for {m} (part two of the report): {p}",
            m=m["id"], p=b["summary"].get("production", "")))
    if n:
        print(T("原片参考 {n} 个（已擦掉字幕）：{d}", "{n} source references (subtitles erased): {d}", n=n, d=out / "remake" / "refs"))
    print(T("模型资料：{src}，核实于 {d}", "Model facts: {src}, checked {d}", src='local override' if m.get("local") else 'capability map', d=v.get("date") or "?"))
    from .generation import check_lines

    cs = plan.get("checks") or []
    if cs:
        print(T("方案检查：", "Plan checks:"))
        print("\n".join(check_lines(cs)))
    return 1 if any(c["level"] == "error" for c in cs) else 0


def cmd_models(args) -> int:
    """List the generation models the capability map knows, or print how to write prompts for one of them."""
    from .plan import Planner
    from .production import _norm, prompting_md

    pl = Planner()
    live = {k: m for k, m in pl.models.items() if m.get("status") not in ("shutdown", "deprecated")}
    if not args.model:
        for cat, title in (("video", 'Video'), ("image", 'Image (first frames / key frames)'), ("character", 'Character animation')):
            print(f"{title}:")
            for mid, m in live.items():
                if m["category"] == cat:
                    lim = (m.get("limits") or {}).get("duration_s") or {}
                    extra = [f"≤{lim['max']:g}s" if lim.get("max") else "", 'multi-shot' if "video.multi_shot" in m["primitives"] else "",
                             'prompt guide available' if mid in pl.prompting else ""]
                    print(f"  {mid:22s} {m['name']}" + ("  · " + " · ".join(x for x in extra if x) if any(extra) else ""))
        print('\nModel prompt guide: rea-video models <id>; general key-frame guidance: rea-video models keyframes')
        return 0
    if args.model == "keyframes":
        print('General key-frame guidance:\n' + "\n".join(f"- {x}" for x in pl.keyframe_notes))
        return 0
    m = next((x for x in live.values() if _norm(x["id"]) == _norm(args.model)), None)
    if not m:
        print(f"rea-video: unknown model {args.model}; list models with rea-video models", file=sys.stderr)
        return 2
    lim = m.get("limits") or {}
    d = lim.get("duration_s") or {}
    facts = [f"per generation {d.get('min', 0):g}-{d['max']:g}s" if d.get("max") else "", "multi-shot" if "video.multi_shot" in m["primitives"] else "",
             'first frame' if "video.i2v_first_frame" in m["primitives"] else "", 'first and last frames' if "video.i2v_first_last" in m["primitives"] else "",
             'multiple references' if "video.multi_reference" in m["primitives"] else "", 'reference video' if "video.reference_video" in m["primitives"] else "",
             'native audio' if (m.get("audio") or {}).get("native") else ""]
    print(f"{m['id']} · {m['name']}" + (" · " + " · ".join(x for x in facts if x) if any(facts) else ""))
    notes = pl.prompting.get(m["id"])
    if not notes:
        print('No model-specific prompt guide recorded; use the general guidance.')
        return 0
    print("\n".join(prompting_md(notes, full=True)))
    if m["category"] == "video":
        print('\nGeneral key-frame guidance: rea-video models keyframes')
    return 0


def cmd_prefs(args) -> int:
    from .memory import PREF_KEYS, add_note, load_prefs, remove_note, set_pref

    if args.key and args.value is None and "=" in args.key:  # also accept `prefs key=value`
        args.key, args.value = args.key.split("=", 1)
    if args.key and args.key not in PREF_KEYS:
        print(f"Unknown preference {args.key} (choose from {', '.join(PREF_KEYS)}; usage: rea-video prefs <key> <value>)", file=sys.stderr)
        return 2
    try:
        if args.note:
            add_note(args.note)
        elif args.remove_note:
            remove_note(args.remove_note)
        elif args.key and args.unset:
            set_pref(args.key, None)
        elif args.key and args.value is not None:
            set_pref(args.key, args.value)
        elif args.key:
            print(load_prefs().get(args.key, ""))
            return 0
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    prefs = load_prefs()
    for k, desc in PREF_KEYS.items():
        print(f"{k:<9} = {prefs.get(k, '(not set)')}    # {desc}")
    for i, n in enumerate(prefs.get("notes", []), 1):
        print(f"Note {i}: {n}")
    return 0


def cmd_memory(args) -> int:
    from .memory import export_labels, summary_lines

    if args.export_labels:
        n = export_labels(Path(args.export_labels))
        print(f"Exported {n} video corrections to {args.export_labels}; fill in the paths before running rea-video eval")
        return 0
    print("\n".join(summary_lines()))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rea-video", description='Reverse-engineer videos shot by shot and create remake plans')
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--env-file", help="Extra .env for optional generation integrations; external VLM is disabled")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("decompose", help='Analyse a video')
    d.add_argument("video")
    d.add_argument("-o", "--out")
    d.add_argument("--vlm", action="store_true", help="disabled in this fork; use agent review")
    d.add_argument("--no-vlm", action="store_true", help='Keep external VLM calls disabled (already enforced in this fork)')
    d.add_argument("--no-whole", action="store_true", help='Skip whole-video VLM analysis (disabled in this fork)')
    d.add_argument("--no-ocr", action="store_true", help='Skip OCR and text timelines; retain sticker detection')
    d.add_argument("--ocr-lang", choices=OCR_LANGS, help='OCR language: zh reads Chinese and English (default), ja Japanese, ko Korean; ja/ko download recognition models on first use')
    d.add_argument("--no-packaging", action="store_true", help='Skip subtitle, title, sticker, and sound-effect packaging analysis')
    d.add_argument("--lang", choices=LANGS, help='Report language: en (default) or zh; overrides the saved language preference')
    d.add_argument("--workers", type=int, default=3)
    d.add_argument("--max-vlm-shots", type=int, default=60, help='Legacy VLM call limit (unused in this fork)')
    d.add_argument("--engine", help='Video model ID for remake planning; defaults to the saved engine or seedance2.0')
    d.add_argument("--meta", help='Platform metadata JSON, including music title, author, and originality')
    d.add_argument("--no-asr", action="store_true", help='Skip local speech recognition; optional [asr] support downloads about 160 MB on first use')
    d.add_argument("--asr-lang", choices=ASR_LANGS, help='Speech language: auto (Chinese, English, Japanese, Korean, Cantonese) or bn (Bengali; downloads about 90 MB)')
    d.add_argument("--no-speakers", action="store_true", help='Skip speaker separation; optional [asr] support downloads about 35 MB on first use')
    d.add_argument("--no-survey", action="store_true", help='Skip the overview survey and use detected shot boundaries')
    d.add_argument("--no-stems", action="store_true", help='Skip voice, music, and sound-effect stem separation')
    d.set_defaults(func=cmd_decompose)

    st = sub.add_parser("stems", help='Separate the soundtrack into voice, music, and effects')
    st.add_argument("video")
    st.add_argument("-o", "--out")
    st.set_defaults(func=cmd_stems)

    p = sub.add_parser("probe", help='Inspect container metadata and provenance hints')
    p.add_argument("video")
    p.add_argument("--tags", action="store_true")
    p.set_defaults(func=cmd_probe)

    e = sub.add_parser("eval", help='Evaluate analysis accuracy against labelled samples')
    e.add_argument("labels", help="labels.yaml")
    e.add_argument("-o", "--out", default="out/eval")
    e.add_argument("--vlm", action="store_true")
    e.add_argument("--no-ocr", action="store_true")
    e.add_argument("--ocr-lang", choices=OCR_LANGS, help='OCR language; see decompose --ocr-lang')
    e.add_argument("--fresh", action="store_true", help='Recompute analyses instead of reusing cached results')
    e.add_argument("--only", default="", help='Reanalyse these comma-separated sample IDs; reuse other cached results')
    e.add_argument("--stems", action="store_true", help='Separate audio stems for samples with audio labels')
    e.set_defaults(func=cmd_eval)

    c = sub.add_parser("capsule", help='Export analysis JSON for capsule-cinema')
    c.add_argument("breakdown")
    c.add_argument("-o", "--out")
    c.set_defaults(func=cmd_capsule)

    r = sub.add_parser("remake-plan", help='Create capsule-cinema generation jobs from a remake plan')
    r.add_argument("breakdown")
    r.add_argument("--capsule-root", help='capsule-cinema checkout; defaults to CAPSULE_CINEMA_ROOT, saved capsule_root, or ~/code/github/capsule-cinema')
    r.set_defaults(func=cmd_remake_plan)

    rr = sub.add_parser("remake-run", help='Run capsule-cinema generation jobs (billable; inspect --dry-run first)')
    rr.add_argument("jobs", help='jobs.json produced by remake-plan')
    rr.add_argument("--capsule-root", help='The same capsule-cinema checkout used by remake-plan')
    rr.add_argument("--dry-run", action="store_true", help='List jobs and parameters without calling a model')
    rr.add_argument("--only", default="", help='Run only these comma-separated shot or unit IDs')
    rr.add_argument("--python", help='capsule-cinema Python; defaults to CAPSULE_CINEMA_PYTHON or <capsule-root>/.venv/bin/python')
    rr.set_defaults(func=cmd_remake_run)

    cd = sub.add_parser("capsule-draft", help='Create a capsule-cinema draft from an analysis')
    cd.add_argument("breakdown")
    cd.add_argument("--capsule-root", help='capsule-cinema checkout; defaults to CAPSULE_CINEMA_ROOT, saved capsule_root, or ~/code/github/capsule-cinema')
    cd.add_argument("--capsule-name", default="")
    cd.add_argument("--capsule-display-name", default="")
    cd.add_argument("--write-capsule", action="store_true", help='Write the draft into capsule-cinema capsules/')
    cd.add_argument("--overwrite-capsule", action="store_true")
    cd.add_argument("--python", help='capsule-cinema Python; same default as remake-run')
    cd.set_defaults(func=cmd_capsule_draft)

    a = sub.add_parser("assemble", help='Assemble remade shots on the original timeline and create a comparison video')
    a.add_argument("breakdown")
    a.add_argument("results", help='results.json from remake-run, or a file using the same format')
    a.add_argument("-o", "--out")
    a.add_argument("--overlays", action="store_true",
                   help='Reapply measured subtitles and titles to replaced shots; supply sticker assets separately')
    a.set_defaults(func=cmd_assemble)

    t = sub.add_parser("tiles", help='Extract a contact sheet for close visual review')
    t.add_argument("video")
    t.add_argument("--start", type=float, default=0.0)
    t.add_argument("--end", type=float)
    t.add_argument("--every", type=float, default=0.5)
    t.add_argument("--cols", type=int, default=6)
    t.add_argument("--cell", type=int, default=320)
    t.add_argument("--max", type=int, default=48)
    t.add_argument("-o", "--out", default="out/tiles.jpg")
    t.set_defaults(func=cmd_tiles)

    fr = sub.add_parser("frames", help='Extract scene frames, element crops, sample points, and background colours')
    fr.add_argument("out_dir", help='Analysis output directory')
    fr.add_argument("--every", type=float, default=0.25, help='Frame sampling interval in seconds (default: 0.25)')
    fr.add_argument("--points", type=int, default=4000, help='Sample points per scene (default: 4000)')
    fr.add_argument("--all", action="store_true", help='Process every shot, including shots not classified as code-rendered')
    fr.set_defaults(func=cmd_frames)

    cp = sub.add_parser("compare", help='Compare reference and remake frames; report the weakest matches')
    cp.add_argument("ref", help='Reference video')
    cp.add_argument("remake", help='Remade video')
    cp.add_argument("--every", type=float, default=0.5, help='Frame sampling interval in seconds (default: 0.5)')
    cp.add_argument("--scenes", help='frames/scenes.json for per-scene scores')
    cp.add_argument("--worst", type=int, default=8, help='Number of weakest matches to show (default: 8)')
    cp.add_argument("-o", "--out", help='Directory for compare.json and compare_worst.jpg')
    cp.set_defaults(func=cmd_compare)

    rm = sub.add_parser("remake", help='Build a local remake from still images and supplied shots; retain placeholders for unfinished shots')
    rm.add_argument("out_dir", help='Analysis output directory')
    rm.add_argument("--code", action="store_true", help='Create a code-remake draft for code-rendered shots')
    rm.add_argument("--no-overlays", action="store_true", help='Skip subtitle and title overlays on replaced shots')
    rm.set_defaults(func=cmd_remake)

    cr = sub.add_parser("code-remake", help='Create an editable code-rendered draft, render it, and compare against the source')
    cr.add_argument("out_dir", help='Analysis output directory')
    cr.add_argument("--reset", action="store_true", help='Recreate spec.json instead of preserving edits')
    cr.add_argument("--no-render", action="store_true", help='Write the project without rendering')
    cr.add_argument("--no-compare", action="store_true", help='Skip scoring after rendering')
    cr.set_defaults(func=cmd_code_remake)

    dv = sub.add_parser("drive", help='Prepare caption-free motion-reference clips, or join generated clips with --join')
    dv.add_argument("out_dir", help='Analysis output directory')
    dv.add_argument("--shots", help='Shot ranges such as 3-7,9; defaults to motion-drive units from the remake plan')
    dv.add_argument("--depth", action="store_true", help='Also create depth video; requires transformers and torch')
    dv.add_argument("--no-clean", action="store_true", help='Keep subtitles and stickers in reference clips')
    dv.add_argument("--prefer", type=float, help='Preferred clip duration in seconds (default: 10)')
    dv.add_argument("--max", type=float, help='Maximum clip duration in seconds (default: 15; Kling limit: 30)')
    dv.add_argument("--join", nargs="?", const="", default=None, metavar="RESULTS", help='Join generated clips from RESULTS or drive/results.json into remake/mine.json')
    dv.set_defaults(func=cmd_drive)

    sm = sub.add_parser("summary", help='Print a compact analysis summary and flag low-confidence shots')
    sm.add_argument("breakdown")
    sm.set_defaults(func=cmd_summary)

    rl = sub.add_parser("videomd", help='Regenerate VIDEO.md and video/ from breakdown.json')
    rl.add_argument("out_dir")
    rl.add_argument("--check", action="store_true", help='Validate the VIDEO.md package without rewriting it')
    rl.set_defaults(func=cmd_videomd)

    pd = sub.add_parser("pdf", help='Print report.html as PDF using an installed Chrome, Chromium, or Edge')
    pd.add_argument("out_dir")
    pd.set_defaults(func=cmd_pdf)

    sv = sub.add_parser("survey", help='Prepare agent image tasks for shot boundaries, transitions, and key frames')
    sv.add_argument("video")
    sv.add_argument("-o", "--out")
    sv.add_argument("--vlm", action="store_true", help="disabled in this fork; use agent review")
    sv.add_argument("--no-vlm", action="store_true", help='Use the current agent to answer image tasks (external VLM is disabled)')
    sv.add_argument("--no-detail", action="store_true", help='Find shot boundaries without selecting per-shot key frames')
    sv.add_argument("--workers", type=int, default=4, help='Number of analysis workers')
    sv.set_defaults(func=cmd_survey)

    rv = sub.add_parser("review", help='Create image-review tasks and answer templates for the current agent')
    rv.add_argument("out_dir", help='Analysis output directory')
    rv.add_argument("--force", action="store_true", help='Replace an existing review_answers.json template')
    rv.set_defaults(func=cmd_review)

    ar = sub.add_parser("apply-review", help='Merge agent review answers and regenerate reports')
    ar.add_argument("out_dir")
    ar.add_argument("answers", nargs="?", help='Answer file (default: <out_dir>/review_answers.json)')
    ar.add_argument("--by", help='Reviewer name recorded in the report')
    ar.add_argument("--lang", choices=LANGS, help='Regenerate reports in this language; existing free-text descriptions retain their language')
    ar.set_defaults(func=cmd_apply_review)

    co = sub.add_parser("correct", help='Correct shot labels or material origins and save the correction')
    co.add_argument("out_dir", help='Analysis output directory')
    co.add_argument("--shots", help='Comma-separated shot IDs, such as 3,5 or shot_003; all selects every shot')
    co.add_argument("--start", type=float)
    co.add_argument("--end", type=float)
    co.add_argument("--label", help='Correct production-method label: ' + "、".join(LABELS))
    co.add_argument("--real", choices=["yes", "no"], help='Whether the shot uses real source material')
    co.add_argument("--note", help='Reason for the correction')
    co.set_defaults(func=cmd_correct)

    pl_ = sub.add_parser("plan", help='Regenerate the remake plan for the selected model')
    pl_.add_argument("out_dir", help='Analysis output directory')
    pl_.add_argument("--model", help='Model ID or name recorded in remake/intent.yaml; see rea-video models')
    pl_.add_argument("--generate", choices=["ai", "all"], help='ai: generate AI shots only; all: generate every shot')
    pl_.set_defaults(func=cmd_plan)

    mo = sub.add_parser("models", help='List available generation models or show a model prompt guide')
    mo.add_argument("model", nargs="?", help='Model ID such as seedance-2.5 or kling-3.0; keyframes shows general guidance')
    mo.set_defaults(func=cmd_models)

    pf = sub.add_parser("prefs", help='View or edit saved preferences and agent notes')
    pf.add_argument("key", nargs="?")
    pf.add_argument("value", nargs="?")
    pf.add_argument("--unset", action="store_true")
    pf.add_argument("--note", help='Add a preference note for the agent')
    pf.add_argument("--remove-note", type=int, metavar="N")
    pf.set_defaults(func=cmd_prefs)

    me = sub.add_parser("memory", help='Show saved preferences and corrections, or export evaluation labels')
    me.add_argument("--export-labels", metavar="YAML")
    me.set_defaults(func=cmd_memory)

    for sp in sub.choices.values():  # also accept `rea-video decompose x.mp4 --env-file ...`
        sp.add_argument("--env-file", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    args = ap.parse_args(argv)
    if getattr(args, "vlm", False):
        from .vlm import EXTERNAL_VLM_DISABLED

        ap.error(EXTERNAL_VLM_DISABLED)
    setup_logging(args.verbose)
    _env(args)
    from .media import MediaError

    try:
        return args.func(args)
    except MediaError as exc:  # missing ffmpeg / unreadable video: one line, not a traceback
        hint = ""
        if "not found on PATH" in str(exc):
            hint = T("\n安装 ffmpeg：macOS `brew install ffmpeg`，Ubuntu/Debian `sudo apt install ffmpeg`",
                     "\ninstall ffmpeg: macOS `brew install ffmpeg`, Ubuntu/Debian `sudo apt install ffmpeg`")
        print(f"rea-video: {exc}{hint}", file=sys.stderr)
        if args.verbose:
            raise
        return 2
    except FileNotFoundError as exc:  # wrong path to a video / breakdown.json / answers file
        if args.verbose:
            raise
        print("rea-video: " + T(f"找不到文件：{exc.filename}", f"file not found: {exc.filename}"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
