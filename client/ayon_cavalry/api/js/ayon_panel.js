// AYON Panel for Cavalry
// Dockable UI Script that connects to the AYON Python server
// for workfile management and pipeline integration.
//
// Install: copy to %APPDATA%/Cavalry/Scripts/AYON/
// Open: Window > Scripts > AYON > ayon_panel

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

var PYTHON_PORT = 8098;
var CAVALRY_PORT = 8099;
var HEARTBEAT_INTERVAL_SEC = 3;
// With setRealtime() we poll ~60/sec; send heartbeat every N cycles (~3 sec)
var HEARTBEAT_INTERVAL_CYCLES = HEARTBEAT_INTERVAL_SEC * 60;
var TIMING_ENABLED = false;

// Try to read connection config written by the Python launcher.
// The config file sits next to this script.
function loadConfig() {
    try {
        var configPath = ui.scriptLocation + "/ayon_config.json";
        if (api.filePathExists(configPath)) {
            var raw = api.readFromFile(configPath);
            var cfg = JSON.parse(raw);
            if (cfg.python_port) {
                PYTHON_PORT = cfg.python_port;
            }
            if (cfg.timing === false) {
                TIMING_ENABLED = false;
            }
            console.log("AYON: Loaded config - Python port: " + PYTHON_PORT);
        } else {
            console.warn(
                "AYON: No config file found at " + configPath
                + ", using defaults."
            );
        }
    } catch (e) {
        console.error("AYON: Failed to load config: " + e);
    }
}

loadConfig();

// Reusable WebClient for POSTs to Python (avoids connection overhead per request)
var pythonClient = null;

function getPythonClient() {
    if (!pythonClient) {
        pythonClient = new api.WebClient("http://localhost:" + PYTHON_PORT);
    }
    return pythonClient;
}

function refreshPythonClient() {
    loadConfig();
    pythonClient = null;
    return getPythonClient();
}

function showErrorModal(title, message) {
    try {
        var modal = new ui.Modal();
        modal.showStringInput(title, message, "");
    } catch (e) {
        console.error("AYON: " + title + " - " + message);
    }
}

// ---------------------------------------------------------------------------
// Command Execution
// ---------------------------------------------------------------------------

var AYON_DATA_KEY = "ayon_data";
var AYON_CONTEXT_KEY = "ayon_context";

function _readAyonData(layerId, key) {
    key = key || AYON_DATA_KEY;
    if (!api.hasUserDataKey(layerId, key)) {
        return null;
    }
    var raw = api.getUserDataKey(layerId, key);
    if (raw === null || raw === undefined || raw === "") {
        return null;
    }
    if (typeof raw === "object") {
        return raw;
    }
    try {
        return JSON.parse(raw);
    } catch (e) {
        console.warn("AYON: Could not parse metadata on " + layerId + ": " + e);
        return null;
    }
}

function _getRenderQueueItemPaths(itemId) {
    var info = {};
    try {
        var attrs = api.getAttributes(itemId);
        for (var i = 0; i < attrs.length; i++) {
            var attrName = attrs[i].toLowerCase();
            if (attrName.indexOf("directory") !== -1 ||
                attrName.indexOf("path") !== -1 ||
                attrName.indexOf("output") !== -1 ||
                attrName.indexOf("file") !== -1) {
                try {
                    info[attrs[i]] = api.get(itemId, attrs[i]);
                } catch (e) {
                    // skip unreadable attrs
                }
            }
        }
        // Also dump all attr names for debugging
        info.__all_attrs__ = attrs;
    } catch (e) {
        console.warn("AYON: Could not read RQ item attrs: " + e);
    }
    return info;
}

function dirnameFromScriptPath(scriptPath) {
    var normalized = (scriptPath || "").replace(/\\/g, "/");
    var lastSlash = normalized.lastIndexOf("/");
    if (lastSlash <= 0) {
        return normalized;
    }
    return normalized.substring(0, lastSlash);
}

function writeAyonBridgeFile(filePath, content) {
    var normalized = String(filePath || "").replace(/\\/g, "/");
    if (!normalized) {
        throw new Error("Missing bridge file path.");
    }
    // Cavalry defaults overwriteExisting to false; bridge files must be replaced.
    var ok = api.writeToFile(normalized, String(content), true);
    if (!ok) {
        throw new Error("Failed to write bridge file: " + normalized);
    }
    return normalized;
}

function stageScriptArgs(scriptPath, argsPath, payloadObj, commandId) {
    var scriptDir = dirnameFromScriptPath(scriptPath);
    var argsDest = scriptDir + "/._ayon_run_args.json";
    var argsContent = null;

    if (payloadObj !== undefined && payloadObj !== null) {
        var stagedPayload = JSON.parse(JSON.stringify(payloadObj));
        if (commandId) {
            stagedPayload.command_id = commandId;
        }
        argsContent = JSON.stringify(stagedPayload);
    } else if (argsPath && api.filePathExists(argsPath)) {
        argsContent = api.readFromFile(argsPath);
    }

    if (argsContent !== null) {
        writeAyonBridgeFile(argsDest, argsContent);
        writeAyonBridgeFile(scriptDir + "/._ayon_run_args_path.txt", argsDest);
        if (typeof ui !== "undefined" && ui.scriptLocation) {
            writeAyonBridgeFile(
                ui.scriptLocation + "/._ayon_run_args_path.txt",
                argsDest
            );
            var stalePanelArgs = ui.scriptLocation + "/._ayon_run_args.json";
            if (api.filePathExists(stalePanelArgs)) {
                api.deleteFilePath(stalePanelArgs);
            }
        }
        if (commandId) {
            writeAyonBridgeFile(scriptDir + "/._ayon_run_command_id.txt", commandId);
            if (typeof ui !== "undefined" && ui.scriptLocation) {
                writeAyonBridgeFile(
                    ui.scriptLocation + "/._ayon_run_command_id.txt",
                    commandId
                );
            }
        }
    }
    return argsDest;
}

function stageRunScriptDir(scriptPath) {
    var scriptDir = dirnameFromScriptPath(scriptPath);
    try {
        if (typeof globalThis !== "undefined") {
            globalThis.__AYON_RUN_SCRIPT_DIR__ = scriptDir;
        }
    } catch (e) {}
    writeAyonBridgeFile(scriptDir + "/._ayon_run_script_dir.txt", scriptDir);
    if (typeof ui !== "undefined" && ui.scriptLocation) {
        writeAyonBridgeFile(
            ui.scriptLocation + "/._ayon_run_script_dir.txt",
            scriptDir
        );
    }
    return scriptDir;
}

function clearAyonScriptResult(scriptDir) {
    try {
        if (typeof globalThis !== "undefined") {
            delete globalThis.__AYON_LAST_SCRIPT_RESULT__;
        }
    } catch (e) {}
    try {
        if (typeof AYON_LAST_SCRIPT_RESULT !== "undefined") {
            AYON_LAST_SCRIPT_RESULT = undefined;
        }
    } catch (e2) {}
    if (scriptDir) {
        try {
            var resultPath = scriptDir + "/._ayon_run_result.json";
            if (api.filePathExists(resultPath)) {
                api.deleteFilePath(resultPath);
            }
        } catch (e3) {}
    }
}

function readAyonScriptResult(scriptDir) {
    var scriptResult = null;
    if (scriptDir) {
        try {
            var resultPath = scriptDir + "/._ayon_run_result.json";
            if (api.filePathExists(resultPath)) {
                var fileResult = api.readFromFile(resultPath);
                if (fileResult && String(fileResult).trim()) {
                    scriptResult = fileResult;
                }
            }
        } catch (eFile) {}
    }
    if (scriptResult === null) {
        try {
            if (typeof globalThis !== "undefined" && globalThis.__AYON_LAST_SCRIPT_RESULT__) {
                scriptResult = globalThis.__AYON_LAST_SCRIPT_RESULT__;
            } else if (typeof AYON_LAST_SCRIPT_RESULT !== "undefined") {
                scriptResult = AYON_LAST_SCRIPT_RESULT;
            }
        } catch (e) {}
    }
    if (scriptResult !== null && typeof scriptResult !== "string") {
        scriptResult = JSON.stringify(scriptResult);
    }
    return scriptResult;
}

function executeCommand(cmd) {
    var result = {};
    try {
        if (cmd.command === "batch") {
            var cmds = cmd.args.commands || [];
            var results = [];
            for (var bi = 0; bi < cmds.length; bi++) {
                var subCmd = cmds[bi];
                var subResult = executeCommand({
                    command: subCmd.command,
                    args: subCmd.args || {}
                });
                results.push(subResult);
            }
            result = {success: true, results: results};
        } else {
        switch (cmd.command) {

            // ----- Scene operations -----

            case "open_scene":
                api.openScene(cmd.args.path, true);
                result = {success: true, path: api.getSceneFilePath()};
                break;

            case "save_scene":
                result = {
                    success: api.saveScene(),
                    path: api.getSceneFilePath()
                };
                break;

            case "save_scene_as":
                result = {
                    success: api.saveSceneAs(cmd.args.path),
                    path: cmd.args.path
                };
                break;

            case "get_scene_path":
                result = {success: true, path: api.getSceneFilePath()};
                break;

            case "has_unsaved_changes":
                result = {success: true, unsaved: api.sceneHasUnsavedChanges()};
                break;

            // ----- Metadata (userData) -----
            // Stored as JSON string for reliable persistence in .cv file.
            // Use ayon_data for instances; ayon_context for publish context
            // (separate keys so update_context_data does not overwrite instances).

            case "imprint": {
                var key = (cmd.args.key === "ayon_context")
                    ? AYON_CONTEXT_KEY
                    : AYON_DATA_KEY;
                api.setUserData(
                    cmd.args.layer_id,
                    key,
                    JSON.stringify(cmd.args.data)
                );
                result = {success: true};
                break;
            }

            case "read": {
                var readData = _readAyonData(cmd.args.layer_id);
                result = {success: true, data: readData};
                break;
            }

            case "get_metadata": {
                var items = [];
                var keysToScan = [AYON_DATA_KEY, AYON_CONTEXT_KEY];
                var seen = {};
                function scanLayer(lid) {
                    if (seen[lid]) return;
                    seen[lid] = true;
                    for (var k = 0; k < keysToScan.length; k++) {
                        try {
                            var d = _readAyonData(lid, keysToScan[k]);
                            if (d !== null) {
                                d.__layer_id__ = lid;
                                items.push(d);
                            }
                        } catch (e) {
                            console.warn("AYON: Skipping " + lid + "/" + keysToScan[k] + ": " + e);
                        }
                    }
                }
                var assetLayers = api.getAssetWindowLayers(false);
                for (var ai = 0; ai < assetLayers.length; ai++) scanLayer(assetLayers[ai]);
                var comps = api.getComps();
                for (var ci = 0; ci < comps.length; ci++) scanLayer(comps[ci]);
                var rqItems = api.getRenderQueueItems();
                for (var ri = 0; ri < rqItems.length; ri++) scanLayer(rqItems[ri]);
                var sceneLayers = api.getAllSceneLayers();
                for (var si = 0; si < sceneLayers.length; si++) scanLayer(sceneLayers[si]);
                result = {success: true, items: items};
                break;
            }

            case "remove_metadata":
                api.setUserData(cmd.args.layer_id, AYON_DATA_KEY, "");
                result = {success: true};
                break;

            // ----- Compositions -----

            case "get_comps": {
                var compIds = api.getComps();
                var comps = [];
                for (var k = 0; k < compIds.length; k++) {
                    comps.push({
                        id: compIds[k],
                        name: api.getNiceName(compIds[k])
                    });
                }
                result = {success: true, comps: comps};
                break;
            }

            case "get_active_comp": {
                var ac = api.getActiveComp();
                result = {
                    success: true,
                    id: ac,
                    name: api.getNiceName(ac)
                };
                break;
            }

            case "get_comp_settings": {
                var compId = cmd.args.comp_id || api.getActiveComp();
                result = {
                    success: true,
                    comp_id: compId,
                    resolution_width: api.get(compId, "resolution.x"),
                    resolution_height: api.get(compId, "resolution.y"),
                    frame_start: api.get(compId, "frameRange.start"),
                    frame_end: api.get(compId, "frameRange.end"),
                    fps: api.get(compId, "fps"),
                    name: api.getNiceName(compId)
                };
                break;
            }

            case "set_comp_settings": {
                var sCompId = cmd.args.comp_id || api.getActiveComp();
                var settings = {};
                if (cmd.args.resolution_width !== undefined &&
                    cmd.args.resolution_height !== undefined) {
                    settings["resolution"] = [
                        cmd.args.resolution_width,
                        cmd.args.resolution_height
                    ];
                }
                if (cmd.args.frame_start !== undefined &&
                    cmd.args.frame_end !== undefined) {
                    var fs = Math.floor(Number(cmd.args.frame_start));
                    var fe = Math.floor(Number(cmd.args.frame_end));
                    settings["startFrame"] = fs;
                    settings["endFrame"] = fe;
                    settings["playbackStart"] = fs;
                    settings["playbackEnd"] = fe;
                }
                if (cmd.args.fps !== undefined) {
                    settings["fps"] = cmd.args.fps;
                }
                api.set(sCompId, settings);
                result = {success: true};
                break;
            }

            case "rename_layer":
                api.rename(cmd.args.layer_id, cmd.args.name);
                result = {success: true};
                break;

            case "get_layer_info": {
                var infoId = cmd.args.layer_id;
                result = {
                    success: true,
                    id: infoId,
                    name: api.getNiceName(infoId),
                    type: api.getLayerType(infoId),
                    exists: api.layerExists(infoId)
                };
                break;
            }

            case "get_comp_layers": {
                var clCompId = cmd.args.comp_id || api.getActiveComp();
                var topOnly = cmd.args.top_level || false;
                api.setActiveComp(clCompId);
                var layerIds = api.getCompLayers(topOnly);
                var layers = [];
                for (var j = 0; j < layerIds.length; j++) {
                    layers.push({
                        id: layerIds[j],
                        name: api.getNiceName(layerIds[j]),
                        type: api.getLayerType(layerIds[j])
                    });
                }
                result = {success: true, layers: layers};
                break;
            }

            case "get_comps_in_layer": {
                var layerId = cmd.args.layer_id;
                var compIds = api.getComps();
                var compIdsSet = {};
                for (var ci = 0; ci < compIds.length; ci++) {
                    compIdsSet[compIds[ci]] = true;
                }
                var found = [];
                if (compIdsSet[layerId]) {
                    found.push(layerId);
                } else {
                    var layerType = (api.getLayerType(layerId) || "").toLowerCase();
                    if (layerType.indexOf("group") !== -1 ||
                        layerType.indexOf("folder") !== -1 ||
                        layerType.indexOf("comp") !== -1) {
                        try {
                            var allLayers = api.getAssetWindowLayers(false);
                            for (var li = 0; li < allLayers.length; li++) {
                                var lid = allLayers[li];
                                if (compIdsSet[lid]) {
                                    try {
                                        var parent = api.getParentComp ? api.getParentComp(lid) : null;
                                        if (parent === layerId) {
                                            found.push(lid);
                                        }
                                    } catch (e) {}
                                }
                            }
                            if (found.length === 0 && api.getCompLayers) {
                                try {
                                    api.setActiveComp(layerId);
                                    var childIds = api.getCompLayers(false);
                                    for (var cj = 0; cj < childIds.length; cj++) {
                                        if (compIdsSet[childIds[cj]]) {
                                            found.push(childIds[cj]);
                                        }
                                    }
                                } catch (e) {}
                            }
                        } catch (e) {}
                    }
                }
                result = {success: true, comp_ids: found};
                break;
            }

            // ----- Assets -----

            case "load_asset": {
                var assetId = api.loadAsset(
                    cmd.args.path,
                    cmd.args.is_sequence || false
                );
                result = {success: true, asset_id: assetId};
                break;
            }

            case "import_scene":
                api.importScene(cmd.args.path);
                result = {success: true};
                break;

            case "replace_asset":
                api.replaceAsset(cmd.args.asset_id, cmd.args.path);
                result = {success: true};
                break;

            case "add_asset_to_comp": {
                var footageId = api.addAssetToComp(cmd.args.asset_id);
                var currentFrame = api.getFrame();
                // Newly added clips are placed at frame 0 by default; getInFrame is
                // unreliable for fresh footage (can return comp frame). Always offset
                // to playhead so the clip appears where the user expects.
                var offset = currentFrame;
                result = {
                    success: true,
                    footage_id: footageId,
                    offset: offset
                };
                break;
            }

            case "offset_layer_time": {
                api.offsetLayerTime(cmd.args.layer_id, cmd.args.offset);
                result = {success: true};
                break;
            }

            case "get_asset_info": {
                var aId = cmd.args.asset_id;
                result = {
                    success: true,
                    asset_id: aId,
                    file_path: api.getAssetFilePath(aId),
                    asset_type: api.getAssetType(aId),
                    is_file_asset: api.isFileAsset(aId)
                };
                break;
            }

            case "get_asset_window_layers": {
                var topLevel = cmd.args.top_level || false;
                var awIds = api.getAssetWindowLayers(topLevel);
                var assets = [];
                for (var ai = 0; ai < awIds.length; ai++) {
                    assets.push({
                        id: awIds[ai],
                        name: api.getNiceName(awIds[ai]),
                        type: api.getLayerType(awIds[ai])
                    });
                }
                result = {success: true, assets: assets};
                break;
            }

            case "delete_layer":
                api.deleteLayer(cmd.args.layer_id);
                result = {success: true};
                break;

            // ----- Selection -----

            case "get_selection": {
                var sel = api.getSelection();
                var selItems = [];
                for (var si = 0; si < sel.length; si++) {
                    selItems.push({
                        id: sel[si],
                        name: api.getNiceName(sel[si]),
                        type: api.getLayerType(sel[si])
                    });
                }
                result = {success: true, selection: selItems};
                break;
            }

            case "select":
                api.select(cmd.args.layer_ids || []);
                result = {success: true};
                break;

            case "export_selected":
                result = {
                    success: api.exportSelected(cmd.args.path),
                    path: cmd.args.path
                };
                break;

            case "set_active_comp":
                api.setActiveComp(cmd.args.comp_id);
                result = {success: true};
                break;

            case "get_create_context": {
                var sel = api.getSelection();
                var compIds = api.getComps();
                var selItems = [];
                for (var si = 0; si < sel.length; si++) {
                    selItems.push({
                        id: sel[si],
                        name: api.getNiceName(sel[si]),
                        type: api.getLayerType(sel[si])
                    });
                }
                var comps = [];
                for (var ck = 0; ck < compIds.length; ck++) {
                    comps.push({id: compIds[ck], name: api.getNiceName(compIds[ck])});
                }
                var items = [];
                var keysToScan = [AYON_DATA_KEY, AYON_CONTEXT_KEY];
                var seen = {};
                function scanLayerGcc(lid) {
                    if (seen[lid]) return;
                    seen[lid] = true;
                    for (var k = 0; k < keysToScan.length; k++) {
                        try {
                            var d = _readAyonData(lid, keysToScan[k]);
                            if (d !== null) {
                                d.__layer_id__ = lid;
                                items.push(d);
                            }
                        } catch (e) {}
                    }
                }
                var assetLayers = api.getAssetWindowLayers(false);
                for (var ai = 0; ai < assetLayers.length; ai++) scanLayerGcc(assetLayers[ai]);
                for (var ci = 0; ci < compIds.length; ci++) scanLayerGcc(compIds[ci]);
                var rqItems = api.getRenderQueueItems();
                for (var ri = 0; ri < rqItems.length; ri++) scanLayerGcc(rqItems[ri]);
                var sceneLayers = api.getAllSceneLayers();
                for (var si = 0; si < sceneLayers.length; si++) scanLayerGcc(sceneLayers[si]);
                result = {
                    success: true,
                    selection: selItems,
                    comps: comps,
                    scene_path: api.getSceneFilePath(),
                    items: items
                };
                break;
            }

            // ----- Rendering -----

            case "get_render_queue_items": {
                var rqItems = api.getRenderQueueItems();
                var rqList = [];
                for (var ri = 0; ri < rqItems.length; ri++) {
                    rqList.push({
                        id: rqItems[ri],
                        name: api.getNiceName(rqItems[ri])
                    });
                }
                result = {success: true, items: rqList};
                break;
            }

            case "add_render_queue_item": {
                var rqId = api.addRenderQueueItem(cmd.args.comp_id);
                result = {success: true, item_id: rqId};
                break;
            }

            case "create_rq_item_and_imprint": {
                var compId = cmd.args.comp_id;
                var imprintData = cmd.args.data || {};
                var renderPath = (cmd.args.path || "").replace(/\\/g, "/");
                var rqId = api.addRenderQueueItem(compId);
                if (renderPath) {
                    try {
                        api.set(rqId, {filePath: renderPath});
                    } catch (e) {}
                }
                imprintData.__layer_id__ = rqId;
                var key = (cmd.args.key === "ayon_context") ? AYON_CONTEXT_KEY : AYON_DATA_KEY;
                api.setUserData(rqId, key, JSON.stringify(imprintData));
                result = {success: true, item_id: rqId};
                break;
            }

            case "create_rq_item_multi_comp_and_imprint": {
                var compIds = cmd.args.comp_ids || [];
                if (!Array.isArray(compIds)) {
                    compIds = compIds != null ? [compIds] : [];
                }
                var imprintData = cmd.args.data || {};
                var renderPath = (cmd.args.path || "").replace(/\\/g, "/");
                if (compIds.length === 0) {
                    result = {success: false, item_id: "", error: "No comp_ids"};
                    break;
                }
                // Create 1 RQ item with first comp (sets targets.0)
                var rqId = api.addRenderQueueItem(compIds[0]);
                // Expand targets array with api.addArrayIndex (Cavalry API for array attributes)
                // then connect each comp to targets.N.id
                if (compIds.length > 1) {
                    try {
                        for (var si = 1; si < compIds.length; si++) {
                            api.addArrayIndex(rqId, "targets");
                        }
                        for (var mi = 0; mi < compIds.length; mi++) {
                            api.connect(compIds[mi], "id", rqId, "targets." + mi + ".id");
                        }
                    } catch (e) {
                        console.warn("AYON: Could not add multi-comp targets: " + e);
                    }
                }
                if (renderPath) {
                    try {
                        api.set(rqId, {filePath: renderPath});
                    } catch (e) {}
                }
                imprintData.__layer_id__ = rqId;
                var key = (cmd.args.key === "ayon_context") ? AYON_CONTEXT_KEY : AYON_DATA_KEY;
                api.setUserData(rqId, key, JSON.stringify(imprintData));
                result = {success: true, item_id: rqId};
                break;
            }

            case "prepare_multi_comp_manifest": {
                // Attach (or clear) a Post-Render Script on the RQ item that
                // records each render's exact composition + resolved path to a
                // manifest file. Cavalry runs postRenderExpression after every
                // render performed by the item (once per target).
                var rqManifestId = cmd.args.item_id;
                var manifestPath = (cmd.args.manifest_path || "").replace(/\\/g, "/");
                var expr = "";
                if (manifestPath) {
                    expr =
                        "try{" +
                        "var __mp=" + JSON.stringify(manifestPath) + ";" +
                        "var __e=JSON.stringify(" +
                        "{comp:render.composition,path:render.path});" +
                        "var __o=\"\";try{__o=api.readFromFile(__mp);}" +
                        "catch(e){__o=\"\";}" +
                        "api.writeToFile(__mp,__o+__e+\"\\n\",true);" +
                        "}catch(err){}";
                }
                var setOk = false;
                try {
                    api.set(rqManifestId, {postRenderExpression: expr});
                    setOk = true;
                } catch (e) {
                    console.warn(
                        "AYON: could not set postRenderExpression on " +
                        rqManifestId + ": " + e
                    );
                }
                result = {success: setOk};
                break;
            }

            case "render": {
                var renderItemId = cmd.args.item_id;
                api.render(renderItemId);
                var itemPaths = _getRenderQueueItemPaths(renderItemId);
                try {
                    if (!itemPaths.filePath) {
                        itemPaths.filePath = api.get(renderItemId, "filePath");
                    }
                } catch (e) { /* filePath may not exist */ }
                result = {
                    success: true,
                    render_path: api.getRenderPath(),
                    scene_path: api.getSceneFilePath(),
                    item_attrs: itemPaths
                };
                break;
            }

            case "render_all":
                api.renderAll();
                result = {
                    success: true,
                    render_path: api.getRenderPath(),
                    scene_path: api.getSceneFilePath()
                };
                break;

            case "get_render_path":
                result = {success: true, path: api.getRenderPath()};
                break;

            case "set_render_path": {
                var path = (cmd.args.path || "").replace(/\\/g, "/");
                var itemId = cmd.args.item_id || null;
                try {
                    if (typeof api.setRenderPath === "function" && !itemId) {
                        api.setRenderPath(path);
                    } else {
                        var rqItems = itemId ? [itemId] : api.getRenderQueueItems();
                        for (var ri = 0; ri < rqItems.length; ri++) {
                            try {
                                api.set(rqItems[ri], {filePath: path});
                            } catch (e) {
                                console.warn(
                                    "AYON: set_render_path on " + rqItems[ri] + " failed: " + e
                                );
                            }
                        }
                    }
                } catch (e) {
                    console.warn("AYON: set_render_path failed: " + e);
                }
                result = {success: true};
                break;
            }

            case "get_render_queue_item_info": {
                var rqiId = cmd.args.item_id;
                var rqiAttrs = api.getAttributes(rqiId);
                var rqiInfo = {id: rqiId, attributes: {}};
                for (var ai2 = 0; ai2 < rqiAttrs.length; ai2++) {
                    try {
                        rqiInfo.attributes[rqiAttrs[ai2]] = api.get(
                            rqiId, rqiAttrs[ai2]
                        );
                    } catch (e) {
                        // Some attrs may not be readable
                    }
                }
                result = {success: true, info: rqiInfo};
                break;
            }

            case "get_rq_item_format": {
                var rqiId = cmd.args.item_id;
                var format = null;
                var triedAttrs = [];
                var genToExt = {
                    "MP4": "mp4", "PNG": "png", "JPEG": "jpeg",
                    "WebM": "webm", "QuickTime": "mov", "SVG": "svg",
                    "GIF": "gif", "WebP": "webp", "APNG": "apng",
                    "Audio": "audio", "Lottie": "lottie", "SpriteSheet": "spritesheet"
                };
                function nodeTypeToExt(nodeType) {
                    if (!nodeType || typeof nodeType !== "string") return null;
                    var match = nodeType.match(/^render(.+)$/i);
                    if (match) {
                        var fmtName = match[1];
                        return genToExt[fmtName] || fmtName.toLowerCase();
                    }
                    return null;
                }
                try {
                    var genType = (typeof api.getCurrentGeneratorType === "function")
                        ? api.getCurrentGeneratorType(rqiId, "generator") : "";
                    triedAttrs.push("getCurrentGeneratorType=" + genType);
                    if (genType) {
                        var ext = nodeTypeToExt(genType);
                        if (ext) {
                            format = {attr: "generator", value: ext};
                        }
                    }
                } catch (e) {
                    triedAttrs.push("getCurrentGeneratorType=N/A");
                }
                if (!format) {
                    try {
                        var genId = (typeof api.getCurrentGenerator === "function")
                            ? api.getCurrentGenerator(rqiId, "generator") : "";
                        triedAttrs.push("getCurrentGenerator=" + genId);
                        if (genId) {
                            var nodeType = String(genId).split("#")[0];
                            var ext = nodeTypeToExt(nodeType);
                            if (ext) {
                                format = {attr: "generator", value: ext};
                            }
                        }
                    } catch (e) {
                        triedAttrs.push("getCurrentGenerator=N/A");
                    }
                }
                if (!format) {
                    try {
                        var genConn = api.getInConnection(rqiId, "generator");
                        triedAttrs.push("getInConnection=" + genConn);
                        if (genConn && genConn.length > 0) {
                            var nodePart = genConn.split(".")[0] || genConn;
                            var nodeType = nodePart.split("#")[0] || nodePart;
                            var ext = nodeTypeToExt(nodeType);
                            if (ext) {
                                format = {attr: "generator", value: ext};
                            }
                        }
                    } catch (e) {
                        triedAttrs.push("getInConnection=N/A");
                    }
                }
                var allAttrs = [];
                try {
                    allAttrs = api.getAttributes(rqiId);
                } catch (e) {}
                if (!format) {
                    var formatAttrNames = [
                        "format", "outputFormat", "fileFormat", "renderFormat",
                        "output.format", "output.outputFormat",
                        "generator.format", "generator.outputFormat", "generator.fileFormat"
                    ];
                    for (var fi = 0; fi < formatAttrNames.length; fi++) {
                        var attrName = formatAttrNames[fi];
                        try {
                            var val = api.get(rqiId, attrName);
                            triedAttrs.push(attrName + "=" + JSON.stringify(val));
                            if (val !== null && val !== undefined && val !== "") {
                                format = {attr: attrName, value: val};
                                break;
                            }
                        } catch (e) {
                            triedAttrs.push(attrName + "=N/A");
                        }
                    }
                    if (!format) {
                        for (var ai = 0; ai < allAttrs.length; ai++) {
                            var attrName = allAttrs[ai];
                            if (attrName.toLowerCase().indexOf("format") === -1) continue;
                            if (formatAttrNames.indexOf(attrName) !== -1) continue;
                            try {
                                var val = api.get(rqiId, attrName);
                                triedAttrs.push(attrName + "=" + JSON.stringify(val));
                                if (val !== null && val !== undefined && val !== "") {
                                    format = {attr: attrName, value: val};
                                    break;
                                }
                            } catch (e) {
                                triedAttrs.push(attrName + "=N/A");
                            }
                        }
                    }
                }
                var filePath = null;
                try {
                    filePath = api.get(rqiId, "filePath");
                } catch (e) {}
                result = {
                    success: true,
                    format: format,
                    filePath: filePath,
                    tried: triedAttrs,
                    allAttrNames: allAttrs
                };
                break;
            }

            case "run_file_script": {
                var scriptPath = (cmd.args.path || "").replace(/\\/g, "/");
                var argsPath = (cmd.args.args_path || "").replace(/\\/g, "/");
                var payloadObj = cmd.args.payload;
                if (!scriptPath) {
                    result = {success: false, error: "Missing script path"};
                    break;
                }
                var scriptDir = null;
                try {
                    stageScriptArgs(scriptPath, argsPath, payloadObj, cmd.id);
                    scriptDir = stageRunScriptDir(scriptPath);
                } catch (e) {
                    result = {
                        success: false,
                        error: "Could not stage script args: " + e
                    };
                    break;
                }
                clearAyonScriptResult(scriptDir);
                try {
                    ui.runFileScript(scriptPath);
                } catch (eRun) {
                    result = {
                        success: false,
                        error: String(eRun),
                        script_path: scriptPath
                    };
                    break;
                }
                var scriptResult = readAyonScriptResult(scriptDir);
                if (!scriptResult) {
                    result = {
                        success: false,
                        error: "Script finished without returning a result payload.",
                        script_path: scriptPath
                    };
                    break;
                }
                result = {
                    success: true,
                    script_path: scriptPath,
                    script_result: scriptResult
                };
                break;
            }

            default:
                result = {
                    success: false,
                    error: "Unknown command: " + cmd.command
                };
        }
        }
    } catch (e) {
        result = {success: false, error: String(e)};
        console.error("AYON: Command '" + cmd.command + "' failed: " + e);
    }
    return result;
}

// ---------------------------------------------------------------------------
// Communication - Cavalry WebServer (receives commands from Python)
// ---------------------------------------------------------------------------

var server = new api.WebServer();

function CommandHandler() {
    this.onPost = function () {
        while (server.postCount()) {
            var post = server.getNextPost();
            try {
                var t0 = TIMING_ENABLED ? Date.now() : 0;
                var cmd = JSON.parse(post.result);
                var result = executeCommand(cmd);
                var tExec = TIMING_ENABLED ? (Date.now() - t0) : 0;

                // Post result back to Python server
                var t1 = TIMING_ENABLED ? Date.now() : 0;
                var client = getPythonClient();
                var payload = JSON.stringify({
                    id: cmd.id,
                    result: result
                });
                client.post("/result", payload, "application/json");
                var tPost = TIMING_ENABLED ? (Date.now() - t1) : 0;

                if (TIMING_ENABLED && cmd.command) {
                    console.log(
                        "AYON [TIMING] Cavalry cmd " + cmd.command +
                        ": execute " + tExec + "ms, POST result " + tPost + "ms"
                    );
                }
                if (client.status() !== 200) {
                    console.error(
                        "AYON: Failed to send result (status "
                        + client.status() + ")"
                    );
                }
            } catch (e) {
                console.error("AYON: Error processing command: " + e);
            }
        }

        // Piggyback a heartbeat on every poll cycle
        sendHeartbeat();
    };
}

var commandHandler = new CommandHandler();
server.addCallbackObject(commandHandler);
// Poll 60x/sec for low-latency; setHighFrequency() is only 1x/sec (~500ms avg delay)
server.setRealtime();

// Find an available port for the Cavalry WebServer
function startCavalryServer() {
    for (var port = CAVALRY_PORT; port < CAVALRY_PORT + 12; port++) {
        try {
            server.listen("localhost", port);
            CAVALRY_PORT = port;
            console.log("AYON: Cavalry WebServer listening on port " + port);
            return true;
        } catch (e) {
            console.warn(
                "AYON: Port " + port + " unavailable, trying next..."
            );
        }
    }
    console.error("AYON: Could not find available port for WebServer");
    return false;
}

// ---------------------------------------------------------------------------
// Heartbeat - periodic status to Python
// ---------------------------------------------------------------------------

var heartbeatCounter = 0;

function sendHeartbeat() {
    heartbeatCounter++;
    if (heartbeatCounter < HEARTBEAT_INTERVAL_CYCLES) {
        return;
    }
    heartbeatCounter = 0;

    try {
        var client = getPythonClient();
        var payload = JSON.stringify({
            scene_path: api.getSceneFilePath(),
            cavalry_port: CAVALRY_PORT
        });
        client.post("/heartbeat", payload, "application/json");
    } catch (e) {
        // Python server may not be up yet, that's ok
    }
}

// ---------------------------------------------------------------------------
// Notify Python that we're ready
// ---------------------------------------------------------------------------

var READY_MAX_RETRIES = 10;
var READY_RETRY_INTERVAL_MS = 2000;
var readyRetryCount = 0;

function notifyReady() {
    try {
        var client = getPythonClient();
        var payload = JSON.stringify({
            cavalry_port: CAVALRY_PORT,
            scene_path: api.getSceneFilePath()
        });
        client.post("/ready", payload, "application/json");

        if (client.status() === 200) {
            console.log("AYON: Successfully connected to Python server");
            setStatus(true, "AYON: Connected");
            return true;
        }
    } catch (e) {
        // Server not ready yet
    }
    readyRetryCount++;
    if (readyRetryCount < READY_MAX_RETRIES) {
        setStatus(false,
            "AYON: Waiting for server... (" + readyRetryCount
            + "/" + READY_MAX_RETRIES + ")"
        );
    } else {
        setStatus(false, "AYON: Could not reach server");
        console.error(
            "AYON: Failed to connect after " + READY_MAX_RETRIES + " attempts"
        );
    }
    return false;
}

function retryNotifyReady() {
    if (readyRetryCount >= READY_MAX_RETRIES) {
        return;
    }
    if (!notifyReady()) {
        var timer = new api.Timer({
            onTimeout: function () { retryNotifyReady(); }
        });
        timer.start(READY_RETRY_INTERVAL_MS);
    }
}

// ---------------------------------------------------------------------------
// Tool Buttons - request Python to open AYON pipeline tools
// ---------------------------------------------------------------------------

function hasExactlyOneCompSelected() {
    var sel = api.getSelection();
    var compIds = api.getComps();
    var compIdsSet = {};
    for (var k = 0; k < compIds.length; k++) compIdsSet[compIds[k]] = true;
    var selectedComps = [];
    for (var si = 0; si < sel.length; si++) {
        if (compIdsSet[sel[si]]) selectedComps.push(sel[si]);
    }
    if (selectedComps.length === 0) {
        for (var si = 0; si < sel.length; si++) {
            var t = (api.getLayerType(sel[si]) || "").toLowerCase();
            if (t.indexOf("comp") !== -1) selectedComps.push(sel[si]);
        }
    }
    return selectedComps.length === 1;
}

function showCreateDialog() {
    var creators = [
        {identifier: "render", label: "Render"},
        {identifier: "sceneFragment", label: "Scene Fragment"}
    ];
    var productDropDown = new ui.DropDown();
    productDropDown.setSize(200, 22);
    for (var i = 0; i < creators.length; i++) {
        productDropDown.addEntry(creators[i].label);
    }
    var variantEdit = ui.LineEdit();
    variantEdit.setPlaceholder("Main");
    variantEdit.setText("Main");
    var dialog = new ui.Container();
    dialog.setBackgroundColor("#373737");
    dialog.setMinimumWidth(260);
    dialog.setMinimumHeight(180);
    var mainLayout = new ui.VLayout();
    mainLayout.add(new ui.Label("Product type:"));
    mainLayout.add(productDropDown);
    mainLayout.add(new ui.Label("Variant:"));
    mainLayout.add(variantEdit);
    var createBtn = new ui.Button("Create");
    var cancelBtn = new ui.Button("Cancel");
    var btnLayout = new ui.HLayout();
    btnLayout.addStretch();
    btnLayout.add(cancelBtn);
    btnLayout.add(createBtn);
    mainLayout.add(btnLayout);
    mainLayout.setMargins(8, 8, 8, 8);
    dialog.setLayout(mainLayout);
    createBtn.onClick = function () {
        var idx = productDropDown.getValue();
        var creatorId = (creators[idx] && creators[idx].identifier) || "render";
        var variant = (variantEdit.getText() || "Main").toString().trim() || "Main";
        getPythonClient().post(
            "/tool",
            JSON.stringify({
                tool: "creator",
                creator_identifier: creatorId,
                variant: variant
            }),
            "application/json"
        );
        dialog.close();
    };
    cancelBtn.onClick = function () { dialog.close(); };
    dialog.show();
}

function openTool(toolName, extraPayload) {
    try {
        var payload = extraPayload || {tool: toolName};
        if (!payload.tool) payload.tool = toolName;
        if (toolName === "creator" && hasExactlyOneCompSelected()) {
            showCreateDialog();
            return;
        }
        var client = getPythonClient();
        client.post("/tool", JSON.stringify(payload), "application/json");
        if (client.status() !== 200) {
            console.error(
                "AYON: Failed to open " + toolName
                + " (status " + client.status() + ")"
            );
        }
    } catch (e) {
        console.error("AYON: Could not reach server for " + toolName + ": " + e);
    }
}

function setStatus(connected, message) {
    if (!connected) {
        console.error("AYON: " + message);
    }
}

// ---------------------------------------------------------------------------
// UI
// ---------------------------------------------------------------------------

ui.setTitle("AYON");

var toolsLayout = new ui.VLayout();
toolsLayout.setSpaceBetween(2);
toolsLayout.setMargins(4, 4, 4, 4);

var workfilesBtn = new ui.Button("Workfiles");
workfilesBtn.onClick = function () { openTool("workfiles"); };
workfilesBtn.setFixedHeight(40);
toolsLayout.add(workfilesBtn);

var loadBtn = new ui.Button("Load");
loadBtn.onClick = function () { openTool("loader"); };
loadBtn.setFixedHeight(40);
toolsLayout.add(loadBtn);

var publishBtn = new ui.Button("Publish");
publishBtn.onClick = function () { openTool("publisher"); };
publishBtn.setFixedHeight(40);
toolsLayout.add(publishBtn);

var createBtn = new ui.Button("Create");
createBtn.onClick = function () { openTool("creator"); };
createBtn.setFixedHeight(40);
toolsLayout.add(createBtn);

var manageBtn = new ui.Button("Manage");
manageBtn.onClick = function () { openTool("sceneinventory"); };
manageBtn.setFixedHeight(40);
toolsLayout.add(manageBtn);

function requestSetSettings(frames, resolution) {
    try {
        var client = refreshPythonClient();
        var payload = {
            tool: "set_settings",
            frames: !!frames,
            resolution: !!resolution
        };
        client.post("/tool", JSON.stringify(payload), "application/json");
        var status = client.status();
        if (status !== 200) {
            console.error("AYON: Set settings failed (status " + status + ")");
            refreshPythonClient();
            showErrorModal(
                "AYON - Set Settings Failed",
                "Could not reach Python server (status " + status + "). " +
                "Ensure Cavalry was launched from AYON."
            );
        }
    } catch (e) {
        console.error("AYON: Set settings error: " + e);
        refreshPythonClient();
        showErrorModal(
            "AYON - Set Settings Error",
            "Error: " + String(e) + ". Ensure Cavalry was launched from AYON."
        );
    }
}

var setFramesBtn = new ui.Button("Set Frame Range");
setFramesBtn.onClick = function () { requestSetSettings(true, false); };
setFramesBtn.setFixedHeight(40);
toolsLayout.add(setFramesBtn);

var setResolutionBtn = new ui.Button("Set Resolution");
setResolutionBtn.onClick = function () { requestSetSettings(false, true); };
setResolutionBtn.setFixedHeight(40);
toolsLayout.add(setResolutionBtn);

var toolsContainer = new ui.Container();
toolsContainer.setLayout(toolsLayout);
toolsContainer.setRadius(3, 3, 3, 3);

ui.add(toolsContainer);
ui.addStretch();

// ---------------------------------------------------------------------------
// Startup
// ---------------------------------------------------------------------------

try {
    if (startCavalryServer()) {
        if (!notifyReady()) {
            retryNotifyReady();
        }
    } else {
        setStatus(false, "AYON: Server failed to start");
    }
} catch (e) {
    console.error("AYON: Startup error: " + e);
    setStatus(false, "AYON: Error - " + e);
}

ui.show();
