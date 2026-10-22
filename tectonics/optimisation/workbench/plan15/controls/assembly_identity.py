"""Source-only Plan15 assembly comparison policy; no scientific eligibility.

The caller verifies actual source bytes and injects _POLICY_SOURCE_SHA256.
This module has no IO, compilation, process inspection, pickle decoding or cache.
Only observe() constructs evidence; validation reconstructs it from retained raw
text. A comparison identity concerns emitted text under this explicit policy,
never numerical equivalence or literal diagnostic-byte equivalence.
"""

_POLICY_SOURCE_SHA256 = None
POLICY_VERSION = "plan15.assembly-comparison.r2"
CONTEXT_SCHEMA = "plan15.assembly-context.r1"
RECORD_SCHEMA = "plan15.assembly-observation.r1"
MAX_ASSEMBLY_BYTES = 2097152
H3_SHA256 = "e0be3a309c8ab9ccee3c1a36525f72da27e816b1ce984651dbd85a3c072a14aa"
CERT_SHA256 = "4099a297a8423a6213761ab4f305d442dda647ec6c7a46ee4d4734d253041f71"
NATIVE_BINDING_SCHEMA = "plan15.native-binding.r1"
MPFR_DLL_SHA256 = "b81a548eb7a23d4e3acbe296f1eff077a0b284617a2c1cc53a1ccdb0637b52b8"
MPFR_DLL_PATH = (
    r"C:\Users\LOCAL_USER\Documents\Codex\2026-09-02\the-diadem-local-tasks-10"
    r"\.r44-env\Lib\site-packages\gmpy2.libs\libmpfr-6.dll"
)
MPFR_EXPORTS = (
    "mpfr_mul", "mpfr_add", "mpfr_set", "mpfr_less_p", "mpfr_greater_p",
    "mpfr_lessequal_p", "mpfr_regular_p", "mpfr_sgn", "mpfr_get_exp",
    "mpfr_flags_save", "mpfr_flags_clear", "mpfr_flags_restore",
    "mpfr_get_emin", "mpfr_get_emax",
)
EMITTER_PINS = {
    "cpu.py": "646ae6bd4170786750299571f03db0bf4d7832fd1954c4047239a809c7f406b1",
    "pythonapi.py": "bf5548155e0750c3d0073be0b913e4b4f2749482a2b23304e20602073a6b2836",
    "base.py": "7c834586dbb58358420b88c0ce3a73037fa0318bd4ece501762cd83892d5f33b",
    "config.py": "cf057d6e36976c7422e36ebc24d7c45d359760d0cb0422c22f75cfee49d1927d",
}
FUNCTIONS = ("_classes", "_four", "_product", "_pair_dots")
SIGNATURE_TEXTS = (
    "(Array(int64, 2, 'C', False, aligned=True), Array(int64, 2, 'C', False, aligned=True))",
    "(Array(int64, 1, 'C', False, aligned=True), int64, int64, int64, int64)",
    "(Array(int64, 1, 'C', False, aligned=True), int8, int8, int64, int64, int64, int64)",
    "(Array(int64, 2, 'C', False, aligned=True), Array(int64, 2, 'C', False, aligned=True), Array(int8, 2, 'C', False, aligned=True), Array(bool, 1, 'C', False, aligned=True), Array(int64, 2, 'C', False, aligned=True), Array(int64, 2, 'C', False, aligned=True), Array(int8, 2, 'C', False, aligned=True), Array(int64, 1, 'C', False, aligned=True), Array(int64, 1, 'C', False, aligned=True), Array(int32, 1, 'C', False, aligned=True), Array(int32, 1, 'C', False, aligned=True), Array(int64, 1, 'C', False, aligned=True), bool, int64, int64)",
)
CONTEXT_KEYS = (
    "schema", "process_id", "source_generation", "module_sha256",
    "certificate_sha256", "emitter_pins", "source_pins", "route", "build",
    "native_runtime", "native_binding",
)
BUILD_KEYS = (
    "compiled_assembly_sha256", "disk_jit_cache", "fastmath", "gmpy2",
    "llvmlite", "load_seconds", "module_sha256", "mpfr", "mpfr_dll",
    "mpfr_dll_sha256", "nogil", "numba", "signatures",
)
SIGNATURE_KEYS = (
    "byte_end", "byte_start", "function", "function_index", "sha256",
    "signature", "signature_index",
)
RECORD_KEYS = (
    "schema", "status", "scientific_eligibility", "equivalence_claim",
    "policy", "context", "signatures", "raw_text", "raw_sha256",
    "raw_utf8_bytes", "joins", "units", "transformations", "comparison_sha256",
)
EXCLUDED_PROCESS_FIELDS = (
    "context.process_id", "context.build.compiled_assembly_sha256",
    "context.build.load_seconds", "signatures[].sha256", "raw_text",
    "raw_sha256", "raw_utf8_bytes", "transformations",
    "units[].raw_sha256", "units[].raw_utf8_bytes", "units[].consumer_evidence",
    "context.native_binding.pid", "context.native_binding.creation_filetime",
    "context.native_binding.module.base", "context.native_binding.exports.*.address",
)


class AssemblyIdentityError(ValueError):
    """Fail-closed refusal with a stable machine-readable reason code."""

    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(code + ": " + detail)


def _require(condition, code, detail):
    if not condition:
        raise AssemblyIdentityError(code, detail)


def _keys(value, expected, label):
    _require(type(value) is dict and set(value) == set(expected),
             "SCHEMA", label + " has missing/unknown keys or is not a dict")


def _hash(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(value):
    import json

    def supported(item, depth=0):
        _require(depth <= 64, "JSON", "data exceeds bounded JSON nesting")
        if type(item) is dict:
            _require(all(type(key) is str for key in item), "JSON", "JSON object keys must be strings")
            for child in item.values():
                supported(child, depth + 1)
        elif type(item) in (list, tuple):
            for child in item:
                supported(child, depth + 1)
        else:
            _require(type(item) in (str, int, float, bool, type(None)),
                     "JSON", "unsupported exact JSON value type")

    supported(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AssemblyIdentityError("JSON", "non-canonical JSON data") from exc


def _copy(value):
    import json
    return json.loads(_json(value))


def _sha(value, label):
    _require(type(value) is str and len(value) == 64
             and all(c in "0123456789abcdef" for c in value),
             "SHA256", label + " is not a lowercase SHA256")


def _strings(value, label):
    _require(type(value) is dict and bool(value), "SCHEMA", label + " is empty/not a dict")
    for key, item in value.items():
        _require(type(key) is str and bool(key) and type(item) is str and bool(item),
                 "SCHEMA", label + " requires nonempty string keys/values")


def _policy():
    _sha(_POLICY_SOURCE_SHA256, "loader policy source pin")
    return {
        "version": POLICY_VERSION,
        "source_sha256": _POLICY_SOURCE_SHA256,
        "emitter_pins": dict(EMITTER_PINS),
        "grammar": "numba-0.65.1-llvmlite-0.47.0-x86_64-elf-text.r2",
        "exceptions": ["pickle-object-id-symbols", "cpucontext-symbol-and-reporting-asciz-address",
                       "independently-bound-mpfr-export-dynamic-globals-and-linked-quad"],
        "excluded_process_fields": list(EXCLUDED_PROCESS_FIELDS),
    }


def _native_binding(value, process_id, build):
    """Validate the closed receipt without discovering native authority.

    The receiver's independently reconstructed expected context supplies the
    parsed pinned-byte size/RVAs and live process mapping.  Complete receipt
    equality is mandatory in validate_evidence; this structural check alone
    cannot establish executable-section membership, forwarding or ownership.
    """
    _keys(value, ("schema", "pid", "creation_filetime", "module", "exports"), "native_binding")
    _require(value["schema"] == NATIVE_BINDING_SCHEMA,
             "BINDING_SCHEMA", "unsupported native binding")
    for name in ("pid", "creation_filetime"):
        _require(type(value[name]) is int and 0 < value[name] < 2**64,
                 "BINDING_PROCESS", "positive exact native " + name + " required")
    _require(value["pid"] == process_id, "BINDING_PROCESS", "binding/context PID differs")
    module = value["module"]
    _keys(module, ("path", "sha256", "base", "size"), "native_binding.module")
    _require(module["path"] == MPFR_DLL_PATH == build["mpfr_dll"]
             and module["sha256"] == MPFR_DLL_SHA256 == build["mpfr_dll_sha256"],
             "BINDING_MODULE", "native module/build pin differs")
    _require(type(module["base"]) is int and 0 < module["base"] < 2**64
             and type(module["size"]) is int and 0 < module["size"] < 2**32
             and module["base"] + module["size"] <= 2**64,
             "BINDING_MODULE", "invalid native image range")
    _keys(value["exports"], MPFR_EXPORTS, "native_binding.exports")
    seen = set()
    for name in MPFR_EXPORTS:
        item = value["exports"][name]
        _keys(item, ("address", "rva"), "native_binding.exports." + name)
        _require(type(item["rva"]) is int and 0 < item["rva"] < module["size"]
                 and type(item["address"]) is int and 0 < item["address"] < 2**64
                 and item["address"] == module["base"] + item["rva"],
                 "BINDING_EXPORT", "invalid/out-of-image native export " + name)
        _require(item["rva"] not in seen, "BINDING_ALIAS", "aliased native exports refused")
        seen.add(item["rva"])
    return value


def _context(context):
    # The native reporter uses tuples; transport uses JSON arrays. Canonicalise
    # those containers only, preserving every key/value and all numeric types.
    _require(type(context) is dict, "SCHEMA", "context is not a dict")
    value = _copy(context)
    _keys(value, CONTEXT_KEYS, "context")
    _require(value["schema"] == CONTEXT_SCHEMA, "CONTEXT_VERSION", "unsupported context")
    _require(type(value["process_id"]) is int and value["process_id"] > 0,
             "PROCESS", "actual positive process PID required")
    _keys(value["source_generation"],
          ("composition_sha256", "profile_sha256", "manifest_sha256", "contract_sha256"),
          "source_generation")
    for name, sha in value["source_generation"].items():
        _sha(sha, name)
    _require(value["module_sha256"] == H3_SHA256
             and value["certificate_sha256"] == CERT_SHA256,
             "SEALED_SOURCE", "H3/certificate pin differs")
    _require(value["emitter_pins"] == EMITTER_PINS,
             "EMITTER_SOURCE", "unsupported/incomplete emitter pins")
    pins = value["source_pins"]
    _strings(pins, "source_pins")
    for name, sha in pins.items():
        _sha(sha, name)
    required_pins = dict(EMITTER_PINS)
    required_pins.update({
        "assembly_identity.py": _POLICY_SOURCE_SHA256,
        "private_heat_compiled_dot_r1.py": H3_SHA256,
        "private_heat_certification_kernel_r1.py": CERT_SHA256,
    })
    for name, sha in required_pins.items():
        matches = [item for path, item in pins.items()
                   if path.replace("\\", "/").rsplit("/", 1)[-1] == name]
        _require(matches == [sha], "EMITTER_SOURCE", "source_pins must contain unique " + name)
    _require(value["route"] == "compiled", "ROUTE", "compiled observation required")
    build = value["build"]
    _keys(build, BUILD_KEYS, "build")
    for name in ("compiled_assembly_sha256", "module_sha256", "mpfr_dll_sha256"):
        _sha(build[name], "build." + name)
    _require(build["module_sha256"] == H3_SHA256, "SEALED_SOURCE", "build module differs")
    for name, expected in (("fastmath", False), ("disk_jit_cache", False), ("nogil", True)):
        _require(type(build[name]) is bool and build[name] is expected,
                 "BUILD_FLAGS", "unsupported " + name)
    for name, expected in (("numba", "0.65.1"), ("llvmlite", "0.47.0"),
                           ("gmpy2", "2.3.2"), ("mpfr", "MPFR 4.2.2")):
        _require(type(build[name]) is str and build[name] == expected,
                 "TOOLCHAIN", "unsupported " + name)
    _require(type(build["signatures"]) is int and build["signatures"] == 4,
             "SIGNATURE", "four compiled signatures required")
    _require(type(build["mpfr_dll"]) is str and bool(build["mpfr_dll"]),
             "NATIVE", "MPFR DLL path required")
    _require(type(build["load_seconds"]) is float and build["load_seconds"] >= 0,
             "BUILD_COST", "nonnegative finite float load_seconds required")
    native = value["native_runtime"]
    _keys(native, ("backend", "exact", "executable", "flags", "options", "python", "warnings"),
          "native_runtime")
    _require(native["backend"] == "gmpy2", "NATIVE", "gmpy2 backend required")
    for name in ("executable", "python"):
        _require(type(native[name]) is str and bool(native[name]), "NATIVE", name + " required")
    _keys(native["exact"], ("binaries", "versions"), "native_runtime.exact")
    _keys(native["exact"]["binaries"],
          ("gmpy2:libgcc_s_seh-1.dll", "gmpy2:libgmp-10.dll", "gmpy2:libmpc-3.dll",
           "gmpy2:libmpfr-6.dll", "gmpy2:libwinpthread-1.dll", "gmpy2_extension"),
          "native binaries")
    _strings(native["exact"]["binaries"], "native binaries")
    _keys(native["exact"]["versions"],
          ("exact_arithmetic", "gmp", "gmp_binary_scope", "gmpy2"), "native versions")
    _strings(native["exact"]["versions"], "native versions")
    _require(native["exact"]["binaries"]["gmpy2:libmpfr-6.dll"] == build["mpfr_dll"],
             "NATIVE", "MPFR binary/build paths disagree")
    _require(type(native["flags"]) is list and len(native["flags"]) == 18,
             "NATIVE", "complete Python flags required")
    for index, flag in enumerate(native["flags"]):
        _require(type(flag) is (bool if index in (13, 16) else int),
                 "NATIVE", "Python flag type differs")
    for name in ("options", "warnings"):
        _require(type(native[name]) is list and all(type(x) is str for x in native[name]),
                 "NATIVE", name + " must contain strings")
    _native_binding(value["native_binding"], value["process_id"], build)
    return value


def _signatures(signatures):
    _require(type(signatures) is list and len(signatures) == 4,
             "SIGNATURE", "four ordered signature records required")
    result = _copy(signatures)
    for index, item in enumerate(result):
        _keys(item, SIGNATURE_KEYS, "signature")
        _require(item["function"] == FUNCTIONS[index]
                 and item["signature"] == SIGNATURE_TEXTS[index],
                 "SIGNATURE", "function/signature ABI or ordering differs")
        for name in ("byte_start", "byte_end", "function_index", "signature_index"):
            _require(type(item[name]) is int and item[name] >= 0,
                     "SIGNATURE", name + " must be a nonnegative int")
        _require(item["function_index"] == index and item["signature_index"] == 0,
                 "SIGNATURE", "function/signature indices differ")
        _require(item["byte_end"] > item["byte_start"], "SIGNATURE", "empty/reversed unit")
        _sha(item["sha256"], "signature sha256")
    return result


def source_signature_key(context, signatures):
    """Exact cache guard; reuse only if this key and actual loader pins match.

    The caller must supply the actual PID, current sealed source/build metadata
    and dispatcher signatures; the observer does not discover or trust a cache.
    """
    return _hash(_json({"policy": _policy(), "context": _context(context),
                        "signatures": _signatures(signatures)}))


def _unit(text, signature, process_id, native_binding):
    import re
    # ASCII was checked by observe; character offsets are exact UTF-8 offsets.
    lines = text.splitlines(keepends=True)
    starts = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line)
    pickle_token = re.compile(r"\.const\.(pickledata|picklebuf)\.([1-9][0-9]*)(\.sha1)?")
    cpu_token = re.compile(r"<numba\.core\.cpu\.CPUContext object at 0x([0-9A-Fa-f]{16})>")
    dynamic_token = re.compile(r"numba\.dynamic\.globals\.([1-9a-f][0-9a-f]{0,15})(\.[1-9][0-9]{0,3})?")
    native_targets = {item["address"]: (name, item["rva"])
                      for name, item in native_binding["exports"].items()}
    dynamic_occurrences = {}
    dynamic_targets = {}
    pickle_ids = {}
    pickle_occurrences = {}
    cpu_occurrences = {}
    replacements = []
    definitions = {}
    consumer_evidence = []
    wrapper = None

    def replacement(line_index, match, group, canonical, kind, role, symbol, target=None):
        start = starts[line_index] + match.start(group)
        end = starts[line_index] + match.end(group)
        replacements.append({
            "process_id": process_id,
            "function_index": signature["function_index"],
            "function": signature["function"],
            "signature_index": signature["signature_index"],
            "unit_byte_start": start, "unit_byte_end": end,
            "byte_start": signature["byte_start"] + start,
            "byte_end": signature["byte_start"] + end,
            "line": line_index + 1, "kind": kind, "role": role,
            "before": match.group(group), "after": canonical, "symbol": symbol,
        })
        if target is not None:
            replacements[-1].update(export_name=target[0], export_rva=target[1],
                                     instance=target[2])

    for index, line in enumerate(lines):
        body = line[:-1] if line.endswith("\n") else line
        # Wrapper ownership is taken from the actual assembly, not a summary.
        if body.startswith("cfunc.") and body.endswith(":"):
            wrapper = body[:-1]
        if body.startswith(".Lfunc_end"):
            wrapper = None
        dm = list(dynamic_token.finditer(body))
        if "numba.dynamic.globals" in body:
            _require(len(dm) == 1 and body.count("numba.dynamic.globals") == 1,
                     "DYNAMIC_GRAMMAR", "unrecognised/ambiguous dynamic global")
            match = dm[0]
            address_text, instance = match.groups()
            symbol = match.group(0)
            address = int(address_text, 16)
            _require(address in native_targets, "DYNAMIC_TARGET", "unproved native target")
            name, rva = native_targets[address]
            target = (name, rva, instance or "")
            canonical = name + "_rva_" + format(rva, "x")
            role = None
            if body == symbol + ":":
                role = "definition"
            elif body == "\t.type\t" + symbol + ",@object":
                role = "type"
            elif body == "\t.weak\t" + symbol:
                role = "weak"
            elif body == "\t.size\t" + symbol + ", 8":
                role = "size"
            elif re.fullmatch(r"\tmovabsq\t\$" + re.escape(symbol) + r", %(rax|r15)", body):
                role = "instruction-reference"
            _require(role is not None, "DYNAMIC_GRAMMAR", "unsupported native global use/alias")
            dynamic_occurrences.setdefault(symbol, []).append((index, role))
            dynamic_targets[symbol] = (address, target)
            replacement(index, match, 1, canonical, "mpfr-export-address", role, symbol, target)
        pm = list(pickle_token.finditer(body))
        if ".const.pickle" in body:
            _require(len(pm) == 1 and body.count(".const.pickle") == 1,
                     "PICKLE_GRAMMAR", "unrecognised/ambiguous pickle occurrence")
            match = pm[0]
            family, object_id, suffix = match.groups()
            symbol = match.group(0)
            _require(not suffix or family == "pickledata", "PICKLE_GRAMMAR", "buf.sha1 unsupported")
            # Only entire, source-observed symbol positions are recognised.
            role = None
            if body == symbol + ":":
                role = "definition"
            elif body == "\t.type\t" + symbol + ",@object":
                role = "type"
            elif re.fullmatch(r"\t.size\t" + re.escape(symbol) + r", [1-9][0-9]*", body):
                role = "size"
            elif body == "\t.quad\t" + symbol:
                role = "quad-reference"
            elif body == "\tmovabsq\t$" + symbol + ", %" + (
                    "rax" if family == "picklebuf" else "r8" if suffix else "rcx"):
                role = "instruction-reference"
            _require(role is not None, "PICKLE_GRAMMAR", "unsupported symbol use/alias: " + body)
            pickle_ids.setdefault(object_id, str(len(pickle_ids) + 1))
            pickle_occurrences.setdefault(symbol, []).append((index, role))
            if role == "definition":
                _require(symbol not in definitions, "PICKLE_DEFINITION", "duplicate definition")
                definitions[symbol] = index
            replacement(index, match, 2, pickle_ids[object_id], "pickle-object-id", role, symbol)
        cm = list(cpu_token.finditer(body))
        if "CPUContext" in body:
            _require(len(cm) == 1 and body.count("CPUContext") == 1,
                     "CPU_GRAMMAR", "unrecognised/ambiguous CPUContext occurrence")
            match = cm[0]
            address = match.group(1)
            _require(int(address, 16) > 0, "CPU_GRAMMAR", "null object representation unsupported")
            representation = match.group(0)
            symbol = '".const.' + representation + '"'
            role = None
            if body == symbol + ":":
                role = "definition"
            elif body == "\t.type\t" + symbol + ",@object":
                role = "type"
            elif body == "\t.size\t" + symbol + ", 57":
                role = "size"
            elif body == '\t.asciz\t"' + representation + '"':
                role = "reporting-payload"
            elif body == "\tmovabsq\t$" + symbol + ", %rcx":
                role = "reporting-reference"
                wrapper_prefix = ("cfunc._ZN28private_heat_compiled_dot_r1"
                                  + str(len(signature["function"])) + signature["function"] + "B")
                _require(wrapper is not None and wrapper.startswith(wrapper_prefix),
                         "CPU_CONSUMER", "reference outside corresponding cfunc wrapper")
                tails = (
                    "\tmovabsq\t$PyUnicode_FromString, %rax\n\tcallq\t*%rax\n"
                    "\tmovabsq\t$PyErr_WriteUnraisable, %rbx\n\tmovq\t%rax, %rdi\n"
                    "\tmovq\t%rdi, %rcx\n\tcallq\t*%rbx\n",
                    "\tmovabsq\t$PyUnicode_FromString, %rax\n\tcallq\t*%rax\n"
                    "\tmovabsq\t$PyErr_WriteUnraisable, %r14\n\tmovq\t%rax, %rbx\n"
                    "\tmovq\t%rbx, %rcx\n\tcallq\t*%r14\n",
                )
                tail = "".join(lines[index + 1:index + 7])
                _require(tail in tails, "CPU_CONSUMER", "reporting consumer sequence differs")
                consumer_evidence.append({
                    "process_id": process_id, "wrapper": wrapper,
                    "symbol": symbol, "unit_byte_start": starts[index],
                    "unit_byte_end": starts[index] + len(line) + len(tail),
                    "byte_start": signature["byte_start"] + starts[index],
                    "byte_end": signature["byte_start"] + starts[index] + len(line) + len(tail),
                    "raw_text": line + tail,
                    "consumer": ["PyUnicode_FromString", "PyErr_WriteUnraisable"],
                })
            _require(role is not None, "CPU_GRAMMAR", "unsupported CPUContext use/alias")
            cpu_occurrences.setdefault(address, []).append((index, role))
            replacement(index, match, 1, "0000000000000001", "cpucontext-address", role, symbol)

    # Only source-observed declaration forms, with one exact pointer payload.
    instances = {}
    for symbol, occurrences in dynamic_occurrences.items():
        for role in ("type", "weak", "definition", "size"):
            _require(sum(found == role for _, found in occurrences) == 1,
                     "DYNAMIC_DEFINITION", "missing/duplicate native " + role)
        references = [i for i, role in occurrences if role == "instruction-reference"]
        _require(bool(references), "DYNAMIC_REFERENCE", "unconsumed native global")
        at = next(i for i, role in occurrences if role == "definition")
        type_at = next(i for i, role in occurrences if role == "type")
        address, target = dynamic_targets[symbol]
        name, rva, instance = target
        instances.setdefault(address, set()).add(instance)
        prefix = ["\t.type\t" + symbol + ",@object\n"]
        if type_at + 1 < len(lines) and lines[type_at + 1] == '\t.section\t.ldata,"awl",@progbits\n':
            prefix.append(lines[type_at + 1])
        declaration = prefix + ["\t.weak\t" + symbol + "\n", "\t.p2align\t3, 0x0\n",
                                symbol + ":\n", "\t.quad\t" + str(address) + "\n",
                                "\t.size\t" + symbol + ", 8\n"]
        _require(at == type_at + len(prefix) + 2
                 and lines[type_at:type_at + len(declaration)] == declaration,
                 "DYNAMIC_PAYLOAD", "native declaration/pointer/size/alignment link differs")
        _require(next(i for i, role in occurrences if role == "weak") == at - 2
                 and next(i for i, role in occurrences if role == "size") == at + 2,
                 "DYNAMIC_DEFINITION", "native directives outside linked declaration")
        payload = re.fullmatch(r"\t.quad\t([1-9][0-9]*)\n", lines[at + 1])
        _require(payload is not None, "DYNAMIC_PAYLOAD", "unsupported native pointer payload")
        replacement(at + 1, payload, 1, name + "_rva_" + format(rva, "x"),
                    "mpfr-export-pointer", "linked-quad-payload", symbol, target)
        end = type_at + len(declaration)
        consumer_evidence.append({
            "process_id": process_id, "function_index": signature["function_index"],
            "function": signature["function"], "signature_index": signature["signature_index"],
            "symbol": symbol, "export_name": name, "export_rva": rva, "instance": instance,
            "unit_byte_start": starts[type_at], "unit_byte_end": starts[end - 1] + len(lines[end - 1]),
            "byte_start": signature["byte_start"] + starts[type_at],
            "byte_end": signature["byte_start"] + starts[end - 1] + len(lines[end - 1]),
            "raw_text": "".join(lines[type_at:end]), "consumer": "pinned-mpfr-function-address",
            "references": [{"unit_byte_start": starts[i], "unit_byte_end": starts[i] + len(lines[i]),
                            "byte_start": signature["byte_start"] + starts[i],
                            "byte_end": signature["byte_start"] + starts[i] + len(lines[i]),
                            "line": i + 1, "raw_text": lines[i]} for i in references],
        })
    for family in instances.values():
        numbered = sorted(int(item[1:]) for item in family if item)
        _require("" in family and numbered == list(range(1, len(numbered) + 1)),
                 "DYNAMIC_INSTANCE", "missing/ambiguous native global instance linkage")

    # Exact object declaration/body relationship, without interpreting payloads.
    for object_id in pickle_ids:
        data = ".const.pickledata." + object_id
        sha1 = data + ".sha1"
        buf = ".const.picklebuf." + object_id
        _require(data in definitions and sha1 in definitions,
                 "PICKLE_DEFINITION", "data/SHA1 definitions missing")
        sizes = {}
        for symbol in (data, sha1, buf):
            occurrences = pickle_occurrences.get(symbol, [])
            if symbol == buf and not occurrences:
                continue
            for role in ("definition", "type", "size"):
                _require(sum(r == role for _, r in occurrences) == 1,
                         "PICKLE_DEFINITION", "missing/duplicate " + role + " for " + symbol)
            at = definitions[symbol]
            _require(at >= 2 and lines[at - 2] == "\t.type\t" + symbol + ",@object\n"
                     and lines[at - 1] == "\t.p2align\t4, 0x0\n",
                     "PICKLE_DEFINITION", "unsupported declaration/alignment")
            size_rows = [i for i, role in occurrences if role == "size"]
            end = size_rows[0]
            size_match = re.fullmatch(r"\t.size\t" + re.escape(symbol) + r", ([1-9][0-9]*)\n", lines[end])
            _require(size_match is not None, "PICKLE_DEFINITION", "malformed size")
            sizes[symbol] = int(size_match.group(1))
            if symbol != buf:
                _require(end == at + 2 and re.fullmatch(r'\t.ascii\t"(?:[^"\\\n]|\\[^\n])*"\n', lines[at + 1]) is not None,
                         "PICKLE_PAYLOAD", "unsupported literal payload grammar")
                if symbol == sha1:
                    _require(sizes[symbol] == 20, "PICKLE_PAYLOAD", "SHA1 size must remain 20")
            else:
                expected = ["\t.quad\t" + data + "\n", "\t.long\t" + str(sizes[data]) + "\n",
                            "\t.zero\t4\n", "\t.quad\t" + sha1 + "\n", "\t.quad\t0\n",
                            "\t.long\t0\n", "\t.zero\t4\n"]
                _require(sizes[symbol] == 40 and lines[at + 1:end] == expected,
                         "PICKLE_ALIAS", "buffer layout/data/SHA1 link differs")
        for symbol in (data, sha1):
            references = [(i, role) for i, role in pickle_occurrences[symbol]
                          if role in ("quad-reference", "instruction-reference")]
            expected_role = "quad-reference" if buf in definitions else "instruction-reference"
            _require(len(references) == 1 and references[0][1] == expected_role,
                     "PICKLE_REFERENCE", "missing/duplicate/unsupported data/SHA1 reference")
            if buf in definitions:
                expected_at = definitions[buf] + (4 if symbol == sha1 else 1)
                _require(references[0][0] == expected_at,
                         "PICKLE_ALIAS", "reference outside corresponding buffer")
        if buf in definitions:
            references = [role for _, role in pickle_occurrences[buf]
                          if role in ("instruction-reference", "quad-reference")]
            _require(references == ["instruction-reference"],
                     "PICKLE_REFERENCE", "missing/duplicate/unsupported buffer reference")

    expected_cpu = 0 if signature["function"] == "_four" else 1
    _require(len(cpu_occurrences) == expected_cpu, "CPU_DEFINITION", "missing/extra context object")
    for address, occurrences in cpu_occurrences.items():
        _require(sorted(role for _, role in occurrences)
                 == sorted(("type", "definition", "size", "reporting-payload", "reporting-reference")),
                 "CPU_DEFINITION", "context def/ref/payload not one-to-one")
        at = [i for i, role in occurrences if role == "definition"][0]
        representation = "<numba.core.cpu.CPUContext object at 0x" + address + ">"
        symbol = '".const.' + representation + '"'
        expected = ["\t.type\t" + symbol + ",@object\n", "\t.p2align\t4, 0x0\n",
                    symbol + ":\n", '\t.asciz\t"' + representation + '"\n',
                    "\t.size\t" + symbol + ", 57\n"]
        _require(at >= 2 and lines[at - 2:at + 3] == expected,
                 "CPU_DEFINITION", "context body/size/alignment differs")
    _require(len(pickle_ids) == (4 if signature["function"] == "_classes" else 0),
             "PICKLE_DEFINITION", "unexpected object family coverage")
    replacements.sort(key=lambda item: item["unit_byte_start"])
    transformed = []
    cursor = 0
    for item in replacements:
        start, end = item["unit_byte_start"], item["unit_byte_end"]
        _require(start >= cursor and text[start:end] == item["before"],
                 "TRANSFORM", "overlap or raw offset mismatch")
        transformed.extend((text[cursor:start], item["after"]))
        cursor = end
    transformed.append(text[cursor:])
    return "".join(transformed), replacements, consumer_evidence


def _comparison_parts(policy, context, signatures, joins, units):
    strict_context = _copy(context)
    del strict_context["process_id"]
    del strict_context["build"]["compiled_assembly_sha256"]
    del strict_context["build"]["load_seconds"]
    del strict_context["native_binding"]["pid"]
    del strict_context["native_binding"]["creation_filetime"]
    del strict_context["native_binding"]["module"]["base"]
    for item in strict_context["native_binding"]["exports"].values():
        del item["address"]
    strict_signatures = _copy(signatures)
    for item in strict_signatures:
        del item["sha256"]
    return {
        "schema": "plan15.assembly-identity.r2", "policy": _copy(policy),
        "context": strict_context, "signatures": strict_signatures,
        "joins": _copy(joins),
        "units": [{"function_index": item["function_index"],
                   "function": item["function"], "signature_index": item["signature_index"],
                   "comparison_sha256": item["comparison_sha256"]} for item in units],
        "scientific_eligibility": False, "equivalence_claim": "NONE",
    }


def observe(assembly: str, signatures: list[dict], context: dict) -> dict:
    """Observe already-captured text; refuse unknown/missing grammar or identity.

    Offsets are exact half-open UTF-8 byte ranges from the capture, not inferred
    by splitting on function names. The actual one-byte LF joins are retained.
    No permission to run this function or to compile science is implied by its
    existence as a source candidate.
    """
    _require(type(assembly) is str and 0 < len(assembly) <= MAX_ASSEMBLY_BYTES and assembly.isascii(),
             "RAW_TEXT", "nonempty ASCII emitted assembly required")
    _require("\r" not in assembly and "\x00" not in assembly, "RAW_TEXT", "unsupported text encoding/newlines")
    policy = _policy()
    ctx = _context(context)
    sigs = _signatures(signatures)
    raw_sha = _hash(assembly)
    _require(ctx["build"]["compiled_assembly_sha256"] == raw_sha,
             "RAW_SHA256", "build/captured raw hash differs")
    units, transformations, joins = [], [], []
    cursor = 0
    for index, item in enumerate(sigs):
        start, end = item["byte_start"], item["byte_end"]
        _require(end <= len(assembly) and start == cursor,
                 "SIGNATURE_BOUNDARY", "gap/overlap/incomplete boundary")
        piece = assembly[start:end]
        _require(piece.startswith('\t.file\t"<string>"\n')
                 and piece.endswith('\t.section\t".note.GNU-stack","",@progbits\n'),
                 "SIGNATURE_BOUNDARY", "unit start/end emitter grammar differs")
        _require(_hash(piece) == item["sha256"], "SIGNATURE_SHA256", "piece hash differs")
        transformed, changes, consumers = _unit(piece, item, ctx["process_id"], ctx["native_binding"])
        units.append({"function_index": item["function_index"], "function": item["function"],
                      "signature_index": item["signature_index"], "raw_sha256": item["sha256"],
                      "raw_utf8_bytes": len(piece), "comparison_sha256": _hash(transformed),
                      "consumer_evidence": consumers})
        transformations.extend(changes)
        cursor = end
        if index < len(sigs) - 1:
            next_start = sigs[index + 1]["byte_start"]
            _require(next_start == end + 1 and assembly[end:next_start] == "\n",
                     "SIGNATURE_BOUNDARY", "unsupported/missing joined-piece separator")
            joins.append({"byte_start": end, "byte_end": next_start, "raw_text": "\n"})
            cursor = next_start
    _require(cursor == len(assembly), "SIGNATURE_BOUNDARY", "uncovered raw suffix")
    identity = _comparison_parts(policy, ctx, sigs, joins, units)
    return {
        "schema": RECORD_SCHEMA, "status": "OBSERVED", "scientific_eligibility": False,
        "equivalence_claim": "NONE", "policy": policy, "context": ctx,
        "signatures": sigs, "raw_text": assembly, "raw_sha256": raw_sha,
        "raw_utf8_bytes": len(assembly), "joins": joins, "units": units,
        "transformations": transformations, "comparison_sha256": _hash(_json(identity)),
    }


def validate_evidence(record: dict, expected_context: dict) -> dict:
    """Rebuild full evidence; expected_context comes from the actual process.

    Return the complete validated record. There is no partial-valid state and
    no trust in a caller-provided digest, transform map or process identity.
    """
    _keys(record, RECORD_KEYS, "observation record")
    _require(record["schema"] == RECORD_SCHEMA and record["status"] == "OBSERVED",
             "RECORD_VERSION", "unsupported status/schema")
    expected = _context(expected_context)
    _require(_json(record["context"]) == _json(expected), "CONTEXT_MISMATCH", "actual context differs")
    rebuilt = observe(record["raw_text"], record["signatures"], expected)
    _require(_json(record) == _json(rebuilt), "EVIDENCE_MISMATCH", "record differs from complete reconstruction")
    return rebuilt


def comparison_identity(record: dict, expected_context: dict) -> dict:
    """Return only a completely reconstructed emitted-text policy identity.

    Receivers must supply the actual independently reconstructed expected_context;
    the saved worker receipt cannot authorise itself. Raw signature ranges remain
    exact identity fields, so an address/ID width change refuses comparison too.
    """
    _keys(record, RECORD_KEYS, "observation record")
    value = validate_evidence(record, expected_context)
    return _comparison_parts(value["policy"], value["context"], value["signatures"],
                             value["joins"], value["units"])
