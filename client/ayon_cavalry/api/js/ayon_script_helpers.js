// Generic helpers for Cavalry scripts invoked via AYON run_file_script.

function writeAyonBridgeFile(filePath, content) {
    var normalized = String(filePath || "").replace(/\\/g, "/");
    if (!normalized) {
        throw new Error("Missing bridge file path.");
    }
    var ok = api.writeToFile(normalized, String(content), true);
    if (!ok) {
        throw new Error("Failed to write bridge file: " + normalized);
    }
    return normalized;
}

function getAyonRunScriptDir() {
    try {
        if (typeof globalThis !== "undefined" && globalThis.__AYON_RUN_SCRIPT_DIR__) {
            return String(globalThis.__AYON_RUN_SCRIPT_DIR__).replace(/\\/g, "/");
        }
    } catch (e) {}
    var bridgeCandidates = [];
    if (typeof ui !== "undefined" && ui.scriptLocation) {
        bridgeCandidates.push(ui.scriptLocation + "/._ayon_run_script_dir.txt");
    }
    try {
        if (typeof globalThis !== "undefined" && globalThis.__AYON_RUN_SCRIPT_DIR__) {
            bridgeCandidates.push(
                String(globalThis.__AYON_RUN_SCRIPT_DIR__).replace(/\\/g, "/")
                + "/._ayon_run_script_dir.txt"
            );
        }
    } catch (eBridge) {}
    for (var i = 0; i < bridgeCandidates.length; i++) {
        var bridgePath = bridgeCandidates[i];
        if (bridgePath && api.filePathExists(bridgePath)) {
            return api.readFromFile(bridgePath).replace(/\\/g, "/").trim();
        }
    }
    if (typeof ui !== "undefined" && ui.scriptLocation) {
        return ui.scriptLocation;
    }
    return null;
}

function resolveAyonHelpersPath() {
    var scriptDir = getAyonRunScriptDir();
    var candidates = [];
    if (scriptDir) {
        candidates.push(scriptDir + "/../AYON/ayon_script_helpers.js");
        candidates.push(scriptDir + "/ayon_script_helpers.js");
    }
    if (typeof ui !== "undefined" && ui.scriptLocation) {
        candidates.push(ui.scriptLocation + "/ayon_script_helpers.js");
        candidates.push(ui.scriptLocation + "/../AYON/ayon_script_helpers.js");
    }
    for (var i = 0; i < candidates.length; i++) {
        var candidate = candidates[i];
        if (candidate && api.filePathExists(candidate)) {
            return candidate;
        }
    }
    return null;
}

function resolveAyonScriptArgsPath() {
    var pointerCandidates = [];
    if (typeof ui !== "undefined" && ui.scriptLocation) {
        pointerCandidates.push(ui.scriptLocation + "/._ayon_run_args_path.txt");
    }
    var scriptDir = getAyonRunScriptDir();
    if (scriptDir) {
        pointerCandidates.push(scriptDir + "/._ayon_run_args_path.txt");
    }
    for (var i = 0; i < pointerCandidates.length; i++) {
        var candidate = pointerCandidates[i];
        if (!candidate || !api.filePathExists(candidate)) {
            continue;
        }
        var pointedPath = api.readFromFile(candidate).replace(/\\/g, "/").trim();
        if (pointedPath && api.filePathExists(pointedPath)) {
            return pointedPath;
        }
    }
    return null;
}

function readAyonScriptArgs() {
    var argsPath = resolveAyonScriptArgsPath();
    if (!argsPath) {
        throw new Error(
            "Missing AYON script args file. Expected ._ayon_run_args_path.txt "
            + "to point at a staged payload."
        );
    }
    var payload = JSON.parse(api.readFromFile(argsPath));
    if (!payload || typeof payload !== "object") {
        throw new Error("AYON script args payload is invalid.");
    }
    if (!payload.run_id) {
        console.warn("AYON: Script args payload is missing run_id.");
    }
    return payload;
}

function setAyonScriptResult(value) {
    var serialized = JSON.stringify(value);
    try {
        globalThis.__AYON_LAST_SCRIPT_RESULT__ = serialized;
    } catch (e) {
        try {
            AYON_LAST_SCRIPT_RESULT = serialized;
        } catch (e2) {}
    }
    var scriptDir = getAyonRunScriptDir();
    if (scriptDir) {
        try {
            writeAyonBridgeFile(scriptDir + "/._ayon_run_result.json", serialized);
        } catch (e3) {
            console.warn("AYON: Could not write script result file: " + e3);
        }
    }
}
