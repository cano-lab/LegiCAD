//! Minimal MCP-compatible stdio adapter for Legible Studio.
//!
//! This intentionally avoids a fast-moving SDK dependency in the first pass:
//! it speaks JSON-RPC over MCP's `Content-Length` stdio framing and exposes the
//! core tools over the shared `ls-agent` service crate. The tool contracts stay
//! in Rust types in `ls-agent`; this crate is a thin adapter.

use std::io::{self, BufRead, Write};

use serde_json::{Value, json};

fn main() -> anyhow::Result<()> {
    let stdin = io::stdin();
    let mut reader = io::BufReader::new(stdin.lock());
    let stdout = io::stdout();
    let mut writer = io::BufWriter::new(stdout.lock());

    while let Some(msg) = read_message(&mut reader)? {
        let response = handle_message(msg);
        if !response.is_null() {
            write_message(&mut writer, &response)?;
        }
    }
    Ok(())
}

fn read_message(reader: &mut impl BufRead) -> anyhow::Result<Option<Value>> {
    let mut content_length = None;
    loop {
        let mut line = String::new();
        let n = reader.read_line(&mut line)?;
        if n == 0 {
            return Ok(None);
        }
        let trimmed = line.trim_end_matches(['\r', '\n']);
        if trimmed.is_empty() {
            break;
        }
        if let Some(v) = trimmed.strip_prefix("Content-Length:") {
            content_length = Some(v.trim().parse::<usize>()?);
        }
    }
    let Some(len) = content_length else {
        return Ok(None);
    };
    let mut buf = vec![0_u8; len];
    reader.read_exact(&mut buf)?;
    let value = serde_json::from_slice(&buf)?;
    Ok(Some(value))
}

fn write_message(writer: &mut impl Write, value: &Value) -> anyhow::Result<()> {
    let body = serde_json::to_vec(value)?;
    write!(writer, "Content-Length: {}\r\n\r\n", body.len())?;
    writer.write_all(&body)?;
    writer.flush()?;
    Ok(())
}

fn handle_message(msg: Value) -> Value {
    let id = msg.get("id").cloned().unwrap_or(Value::Null);
    let method = msg.get("method").and_then(Value::as_str).unwrap_or("");
    if method.starts_with("notifications/") {
        return Value::Null;
    }
    match method {
        "initialize" => ok(
            id,
            json!({
                "protocolVersion": "2024-11-05",
                "serverInfo": { "name": "legible-mcp", "version": env!("CARGO_PKG_VERSION") },
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {}
                }
            }),
        ),
        "tools/list" => ok(id, json!({ "tools": tools() })),
        "tools/call" => {
            let params = msg.get("params").cloned().unwrap_or_default();
            match call_tool(&params) {
                Ok(v) => ok(id, v),
                Err(e) => err(id, -32000, &e.to_string()),
            }
        }
        "resources/list" => ok(
            id,
            json!({
                "resources": [
                    {"uri": "legible://catalog/part9", "name": "Part 9 catalog", "mimeType": "application/json"},
                    {"uri": "legible://catalog/part3", "name": "Part 3 catalog", "mimeType": "application/json"},
                    {"uri": "legible://catalog/mixed", "name": "Mixed-mode catalog", "mimeType": "application/json"}
                ]
            }),
        ),
        "resources/read" => {
            let uri = msg
                .get("params")
                .and_then(|p| p.get("uri"))
                .and_then(Value::as_str)
                .unwrap_or("");
            let mode = uri.strip_prefix("legible://catalog/");
            match mode {
                Some(mode) => ok(
                    id,
                    json!({
                        "contents": [{
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": serde_json::to_string_pretty(&agent::catalog(Some(mode))).unwrap_or_default()
                        }]
                    }),
                ),
                None => err(id, -32602, "unknown resource URI"),
            }
        }
        "prompts/list" => ok(
            id,
            json!({
                "prompts": [
                    {"name": "design_obc_building", "description": "Design an OBC building through solve/validate/fix/export."},
                    {"name": "repair_obc_design", "description": "Repair a failing design one typed patch at a time."},
                    {"name": "review_obc_bundle", "description": "Review generated bundle coverage and warnings."}
                ]
            }),
        ),
        "prompts/get" => {
            let name = msg
                .get("params")
                .and_then(|p| p.get("name"))
                .and_then(Value::as_str)
                .unwrap_or("");
            ok(id, prompt(name))
        }
        _ => err(id, -32601, "method not found"),
    }
}

fn tools() -> Vec<Value> {
    vec![
        tool(
            "legible_catalog",
            "List supported modes, templates, and room types.",
        ),
        tool(
            "legible_solve_template",
            "Generate building JSON from a supported template.",
        ),
        tool(
            "legible_solve_manifest",
            "Generate building JSON from a ProgramManifest.",
        ),
        tool(
            "legible_validate",
            "Run structured OBC validation on building JSON.",
        ),
        tool(
            "legible_suggest_fixes",
            "Suggest typed fixes for validation/egress issues.",
        ),
        tool(
            "legible_apply_patch",
            "Apply a constrained DesignPatch to building JSON.",
        ),
        tool(
            "legible_iterate",
            "Run deterministic validate/fix iterations.",
        ),
        tool(
            "legible_export_bundle",
            "Export SVG/PDF/PNG/DXF/IFC bundle artifacts.",
        ),
    ]
}

fn tool(name: &str, description: &str) -> Value {
    json!({
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "additionalProperties": true
        }
    })
}

fn call_tool(params: &Value) -> anyhow::Result<Value> {
    let name = params.get("name").and_then(Value::as_str).unwrap_or("");
    let args = params
        .get("arguments")
        .cloned()
        .unwrap_or_else(|| json!({}));
    let data = match name {
        "legible_catalog" => {
            let mode = args.get("mode").and_then(Value::as_str);
            serde_json::to_value(agent::catalog(mode))?
        }
        "legible_solve_template" => {
            let req: agent::SolveTemplateRequest = serde_json::from_value(args)?;
            agent::solve_template(&req)?
        }
        "legible_solve_manifest" => {
            let manifest: solver::ProgramManifest =
                serde_json::from_value(args.get("manifest").cloned().unwrap_or(args))?;
            agent::solve_manifest(&manifest)?
        }
        "legible_validate" => {
            let req: agent::ValidateRequest = serde_json::from_value(args)?;
            serde_json::to_value(agent::validate(&req)?)?
        }
        "legible_suggest_fixes" => {
            let req: agent::SuggestFixesRequest = serde_json::from_value(args)?;
            serde_json::to_value(agent::suggest_fixes(&req)?)?
        }
        "legible_apply_patch" => {
            let req: agent::ApplyPatchRequest = serde_json::from_value(args)?;
            serde_json::to_value(agent::apply_patch(&req)?)?
        }
        "legible_iterate" => {
            let req: agent::IterateRequest = serde_json::from_value(args)?;
            serde_json::to_value(agent::iterate(&req)?)?
        }
        "legible_export_bundle" => {
            let req: agent::ExportBundleRequest = serde_json::from_value(args)?;
            serde_json::to_value(agent::export_bundle(&req)?)?
        }
        _ => anyhow::bail!("unknown tool '{name}'"),
    };
    Ok(json!({
        "content": [
            {
                "type": "text",
                "text": serde_json::to_string_pretty(&data)?
            }
        ],
        "structuredContent": data
    }))
}

fn prompt(name: &str) -> Value {
    let text = match name {
        "repair_obc_design" => {
            "Use legible_validate first. Then call legible_suggest_fixes with implemented_only=true. Apply one patch at a time with legible_apply_patch and revalidate after each patch. Stop when passed, blocked, or user accepts remaining warnings."
        }
        "review_obc_bundle" => {
            "Review the exported Legible bundle. Explain generated artifacts, validation coverage, skipped checks, warnings, and the professional-review disclaimer."
        }
        _ => {
            "Design the building through Legible tools: call legible_catalog; choose a supported template or manifest; call legible_solve_template or legible_solve_manifest; call legible_validate; if it fails, call legible_suggest_fixes and legible_apply_patch one patch at a time; export only after passing or after explicit user acceptance of remaining warnings."
        }
    };
    json!({
        "description": name,
        "messages": [{
            "role": "user",
            "content": { "type": "text", "text": text }
        }]
    })
}

fn ok(id: Value, result: Value) -> Value {
    json!({ "jsonrpc": "2.0", "id": id, "result": result })
}

fn err(id: Value, code: i64, message: &str) -> Value {
    json!({
        "jsonrpc": "2.0",
        "id": id,
        "error": { "code": code, "message": message }
    })
}
