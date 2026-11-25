"""Compose reviewed postimages and prepare the next landing handoff."""

from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import re

from atlas_land import Incomplete, decode, digest, fingerprint, require, save

PUBLIC_PATH = re.compile(r"[A-Za-z0-9_./-]+\Z")


def member(root, name):
    path = PurePosixPath(name)
    require(PUBLIC_PATH.fullmatch(name) and not path.is_absolute() and ".." not in path.parts
            and path.parts and path.parts[0] != ".git" and path.as_posix() == name, f"Invalid member path: {name}")
    full = root.joinpath(*path.parts)
    require(full.resolve() == full, f"Member crosses a link: {name}")
    return full


def patch_sections(raw):
    sections = {}
    found = None
    body = []
    for line in raw.splitlines(keepends=True):
        if line.startswith(b"diff --git "):
            if found is not None:
                sections[found] = b"".join(body)
            part = line.strip().split(b" ")
            require(len(part) == 4 and part[2].startswith(b"a/") and part[3].startswith(b"b/")
                    and part[2][2:] == part[3][2:], "Expected a named unified text patch without renames")
            found = part[2][2:].decode("ascii")
            require(found not in sections, f"Duplicate patch member: {found}")
            body = []
        elif found is not None:
            body.append(line)
        else:
            require(not line.strip(), "Expected a unified Git diff")
    if found is not None:
        sections[found] = b"".join(body)
    require(sections, "Empty content patch")
    for name, text in sections.items():
        require(b"@@ " in text and b"GIT binary patch" not in text, f"Unsupported patch: {name}")
        # A hunk can contain text starting with dashes or pluses, so inspect only its file headers.
        first = text.split(b"@@ ", 1)[0].splitlines()
        headers = [line[4:] for line in first if line.startswith((b"--- ", b"+++ "))]
        require(len(headers) == 2 and headers[0] in (b"a/" + name.encode("ascii"), b"/dev/null")
                and headers[1] in (b"b/" + name.encode("ascii"), b"/dev/null"), f"Patch headers disagree for {name}")
    return sections


def compose(round_, settings, job):
    mode = settings["kind"]
    if mode == "already-issued":
        reference = settings["report"]
        issued = round_.json(reference)
        require(issued["parent"] == round_.config["base_commit"], "Issued composition belongs to a different parent")
        for name in ("diff", "declaration", "seal", "record"):
            round_.checked(issued[name])
        return {**issued, "source_report": reference, "reused_issuance": True}

    require(mode in ("independent", "cumulative"), f"Unknown composition kind: {mode}")
    parent = round_.path(settings["parent_root"])
    parent_report = round_.json(settings["parent_manifest"])
    parent_id = parent_report["identity"]
    require(parent_id == round_.config["base_commit"], "Receiving composition parent differs")
    parent_members = parent_report["members"]
    plan = []
    owned = set()
    units = settings["units"]
    require(units and (mode != "cumulative" or len(units) == 1), "Invalid independent or cumulative unit list")
    for unit in units:
        review = round_.json(unit)
        require(review["base"] == parent_id or mode == "independent", "Cumulative correction names another parent")
        patch = round_.path(review["patch"]["path"]).read_bytes()
        require(sha256(patch).hexdigest() == review["patch"]["sha256"], "Reviewed patch fingerprint differs")
        sections = patch_sections(patch)
        require(sections.keys() == review["members"].keys(), "Reviewed patch and member roster disagree")
        overlap = owned.intersection(sections)
        require(not overlap, "Unresolved overlap: " + ", ".join(sorted(overlap)))
        owned.update(sections)
        for name, section in sections.items():
            row = review["members"][name]
            target = member(parent, name)
            require(row["before"] == parent_members.get(name), f"Conflicting receiving preimage: {name}")
            require(target.is_file() == (row["before"] is not None), f"Conflicting receiving preimage: {name}")
            plan.append((name, section, row))

    target = job / "composition"
    target.mkdir()
    staged_members = {}
    declared = {name: row for name, _, row in plan}
    for name, expected in parent_members.items():
        source = member(parent, name)
        path = member(target, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as reader, path.open("xb") as writer:
            data = reader.read()
            require(sha256(data).hexdigest() == expected, f"Conflicting receiving preimage: {name}")
            writer.write(data)
        if name not in declared:
            staged_members[name] = expected

    engine = round_.path(settings["patch_executable"])
    patch_env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    patch_env["GIT_CEILING_DIRECTORIES"] = str(target.parent)
    for index, (name, section, row) in enumerate(plan):
        path = member(target, name)
        patch_input = job / f"patch-{index}.diff"
        patch_input.write_bytes(section)
        try:
            round_.launch(f"patch-{index}", (engine, "-c", "core.autocrlf=false", "apply", "--no-index",
                                             "--whitespace=nowarn", patch_input), job, job, cwd=target, env=patch_env)
        except Incomplete as exc:
            raise Incomplete(f"Reviewed patch did not apply to {name}", **exc.evidence) from exc
        if row["after"] is None:
            require(not path.exists(), f"Reviewed deletion did not remove {name}")
        else:
            require(path.is_file() and digest(path) == row["after"], f"Reviewed postimage differs for {name}")
            staged_members[name] = row["after"]
    actual = {path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()}
    require(actual == set(staged_members), "Composed tree includes unexpected files")
    return {"parent": parent_id, "root": str(target), "tree": fingerprint(staged_members), "members": staged_members,
            "unit_reports": units, "reused_issuance": False}


def completed(round_, phase, scope, build, read=decode):
    result = round_.local(phase, scope)
    if result.is_file():
        raw = result.read_bytes()
        return read(raw), {"path": str(result), "sha256": sha256(raw).hexdigest()}
    record = build(round_.stage(phase))
    return record, save(result, record)


def bind_issuance(round_, spec, composition, source_report, work):
    if composition["reused_issuance"]:
        return composition
    require(spec is not None, "A reviewed receiving issuer is needed for this composition")
    if spec.get("kind") == "legacy-equal-members":
        issuer = Path(__file__).with_name("atlas_land_issue_equal.py")
        identity = ("--composition", source_report["path"], "--composition-sha256", source_report["sha256"])
    else:
        issuer = round_.checked(spec["entry"])
        identity = ()
    binding = round_.checked(spec["settings"])
    native = work / "native"
    report = work / "issuer.json"
    evidence = round_.launch("issue-candidate", (round_.path(spec["python"]), "-B", "-I", issuer,
                                                 "--input-tree", composition["root"], "--output-tree", native,
                                                 "--report", report, "--settings", binding, *identity), work, work)
    raw = report.read_bytes()
    issued = decode(raw)
    require(issued["source_tree"] == composition["tree"] and Path(issued["native"]).resolve() == native,
            "Issuer report did not bind the composed source")
    return {**issued, "composition": source_report,
            "issuer_report": {"path": str(report), "sha256": sha256(raw).hexdigest()}, "issuer_run": evidence}


def kit_files(round_, preparations, work):
    published = {}
    for name, selection in preparations.items():
        file = member(work, name)
        file.parent.mkdir(parents=True, exist_ok=True)
        template = round_.json(selection["template"])
        for key, replacement in selection["fields"].items():
            require(template[key] == replacement["before"], f"Template preimage differs for {name}/{key}")
            template[key] = replacement["after"]
        published[name] = save(file, template)
    return published


def require_artifacts(round_, references):
    for reference in references:
        path = round_.path(reference["path"])
        require(path.is_file(), f"Prepared artifact is missing: {path}")


def prepared_files(round_, phase, scope, templates):
    def read_saved(raw):
        files = decode(raw)
        require_artifacts(round_, files.values())
        return files

    return completed(round_, phase, scope, lambda work: kit_files(round_, templates, work), read_saved)


def prepare(round_):
    settings = round_.config["preparation"]
    composition_scope = {"base": round_.config["base_commit"], "composition": settings["composition"]}
    composition, composition_ref = completed(round_, "composition", composition_scope,
                                              lambda work: compose(round_, settings["composition"], work))
    if not composition["reused_issuance"] and "issuer" not in settings:
        return {"status": "INCOMPLETE", "exit": 2, "reason": "A reviewed receiving issuer is pending",
                "composition": composition_ref, "tree": composition["tree"], "root": composition["root"]}
    issuer = settings.get("issuer")
    measured_issuance = (not composition["reused_issuance"] and issuer is not None
                         and issuer.get("kind") == "legacy-equal-members")
    issuance_scope = {"composition": composition_ref, "issuer": issuer}
    if measured_issuance:
        # Older issuer reports echoed the requested identity without checking their source bytes.
        issuance_scope["reviewed_members"] = True
    issued, issued_ref = completed(round_, "issued", issuance_scope,
                                   lambda work: bind_issuance(round_, issuer, composition, composition_ref, work))
    version = settings["version_disposition"]
    require(issued["version_disposition"] == version, "Issued version disposition differs")
    diff = issued["diff"]
    native_artifacts = (issued[name] for name in ("declaration", "seal", "record") if name in issued)
    require_artifacts(round_, (diff, *native_artifacts))
    templates = settings.get("templates", {})
    kit, kit_ref = prepared_files(round_, "kit", {"issued": issued_ref, "templates": templates}, templates)
    result = {"status": "PREPARED", "exit": 0, "composition": composition_ref, "issued": issued_ref, "kit": kit_ref,
              "kit_files": kit, "diff": diff, "version_disposition": version,
              "next_owner": settings.get("next_owner", "Publication owner")}
    if "comparison" in settings:
        comparison = round_.json(settings["comparison"])
        result["comparison"] = {"reference": settings["comparison"], "status": comparison["status"],
                                "exit": comparison["exit"], "strict_exit": comparison.get("strict_exit"),
                                "qualification_status": comparison.get("candidate", {}).get("qualification_status")}
    if "reviewed_issue" in settings:
        issue = settings["reviewed_issue"]
        approval = round_.json(issue["approval"])
        require(approval["status"] == "ACCEPT" and approval["issued"] == issued_ref
                and approval["draft"] == issue["draft"]
                and approval["comparison"] == settings["comparison"] and result["comparison"]["exit"] == 0,
                "Reviewed issue requires a passing comparison and verdict bound to the exact candidate")
        _, issue_ref = prepared_files(round_, "issue", {"issued": issued_ref, "issue": issue},
                                      {"issue.json": issue["draft"]})
        result["reviewed_issue"] = issue_ref
    result_scope = {"settings": settings, "issued": issued_ref} if measured_issuance else settings
    path = round_.local("prepare-result", result_scope)
    ref = {"path": str(path), "sha256": digest(path)} if path.is_file() else save(path, result)
    return {**result, "result": ref}
