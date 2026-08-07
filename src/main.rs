#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    env, fs,
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};

use anyhow::{Context, Result};
use axum::{
    extract::{Multipart, Path as AxumPath, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{delete, get, post},
    Json, Router,
};
use reqwest::multipart::{Form, Part};
use rusqlite::{params, Connection, OptionalExtension};
use rust_embed::RustEmbed;
use serde::{Deserialize, Serialize};
use tokio::sync::Mutex;
use tower_http::{cors::CorsLayer, trace::TraceLayer};
use uuid::Uuid;

const DOCLINGO_TRANSLATE_URL: &str = "https://api.doclingo.cn/api/core/external/translate";
const DOCLINGO_API_URL: &str = "https://api.doclingo.cn/api/core/external";

#[derive(RustEmbed)]
#[folder = "frontend/dist/"]
struct Frontend;

#[derive(Clone)]
struct AppState {
    db: Arc<Mutex<Connection>>,
    data_dir: PathBuf,
    client: reqwest::Client,
}

#[derive(Debug, Serialize)]
struct ApiError {
    error: ErrorBody,
}
#[derive(Debug, Serialize)]
struct ErrorBody {
    code: &'static str,
    message: String,
}
type ApiResult<T> = Result<T, (StatusCode, Json<ApiError>)>;

fn error(
    code: &'static str,
    status: StatusCode,
    message: impl Into<String>,
) -> (StatusCode, Json<ApiError>) {
    (
        status,
        Json(ApiError {
            error: ErrorBody {
                code,
                message: message.into(),
            },
        }),
    )
}

#[derive(Debug, Serialize, Clone)]
struct Job {
    id: String,
    original_name: String,
    source_path: String,
    output_dir: String,
    target_language: String,
    model: String,
    ocr_enabled: bool,
    translate_filename: bool,
    status: String,
    progress: String,
    remote_query_key: Option<String>,
    output_path: Option<String>,
    error: Option<String>,
    created_at: String,
}

#[derive(Debug, Deserialize)]
struct RetryRequest {
    output_dir: Option<String>,
}

#[tokio::main]
async fn main() -> Result<()> {
    dotenvy::dotenv().ok();
    let data_dir = env::current_dir()?.join("app-data");
    fs::create_dir_all(data_dir.join("inbox"))?;
    let db = Connection::open(data_dir.join("translator.db"))?;
    migrate(&db)?;
    let state = AppState {
        db: Arc::new(Mutex::new(db)),
        data_dir,
        client: reqwest::Client::new(),
    };
    tokio::spawn(worker(state.clone()));
    let app = Router::new()
        .route("/api/jobs", get(list_jobs).post(create_jobs))
        .route("/api/jobs/{id}/retry", post(retry_job))
        .route("/api/jobs/{id}", delete(cancel_job))
        .route("/api/select-output-dir", post(select_output_dir))
        .route("/api/metadata", get(get_metadata))
        .fallback(get(serve_frontend))
        .layer(CorsLayer::permissive())
        .layer(TraceLayer::new_for_http())
        .with_state(state);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:3000").await?;
    println!("Translator API listening on http://127.0.0.1:3000");
    let _ = std::process::Command::new("cmd")
        .args(["/C", "start", "", "http://127.0.0.1:3000"])
        .spawn();
    axum::serve(listener, app).await.context("server stopped")
}

async fn serve_frontend(uri: axum::http::Uri) -> Response {
    let path = uri.path().trim_start_matches('/');
    let asset = Frontend::get(if path.is_empty() { "index.html" } else { path })
        .or_else(|| Frontend::get("index.html"));
    match asset {
        Some(asset) => (
            [(
                "content-type",
                mime_guess::from_path(path).first_or_octet_stream().as_ref(),
            )],
            asset.data,
        )
            .into_response(),
        None => StatusCode::NOT_FOUND.into_response(),
    }
}

fn migrate(db: &Connection) -> Result<()> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, original_name TEXT NOT NULL, source_path TEXT NOT NULL, output_dir TEXT NOT NULL,
        target_language TEXT NOT NULL, model TEXT NOT NULL DEFAULT 'chatgpt-4omini', ocr_enabled INTEGER NOT NULL, translate_filename INTEGER NOT NULL,
        status TEXT NOT NULL, progress TEXT NOT NULL DEFAULT '-', remote_query_key TEXT, output_path TEXT,
        error TEXT, created_at TEXT NOT NULL
    );")?;
    let _ = db.execute(
        "ALTER TABLE jobs ADD COLUMN model TEXT NOT NULL DEFAULT 'chatgpt-4omini'",
        [],
    );
    Ok(())
}

async fn list_jobs(State(state): State<AppState>) -> ApiResult<Json<Vec<Job>>> {
    let db = state.db.lock().await;
    jobs_from(&db, "SELECT * FROM jobs ORDER BY created_at DESC", [])
        .map(Json)
        .map_err(internal)
}

async fn create_jobs(
    State(state): State<AppState>,
    mut multipart: Multipart,
) -> ApiResult<(StatusCode, Json<Vec<Job>>)> {
    let mut output_dir = None;
    let mut target_language = None;
    let mut model = None;
    let mut ocr_enabled = false;
    let mut translate_filename = true;
    let mut files = Vec::new();
    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|e| error("UPLOAD_INVALID", StatusCode::BAD_REQUEST, e.to_string()))?
    {
        let name = field.name().unwrap_or_default().to_owned();
        if name == "files" {
            let filename = field.file_name().unwrap_or("document").to_owned();
            files.push((
                filename,
                field
                    .bytes()
                    .await
                    .map_err(|e| error("UPLOAD_INVALID", StatusCode::BAD_REQUEST, e.to_string()))?,
            ));
        } else {
            let value = field
                .text()
                .await
                .map_err(|e| error("UPLOAD_INVALID", StatusCode::BAD_REQUEST, e.to_string()))?;
            match name.as_str() {
                "output_dir" => output_dir = Some(value),
                "target_language" => target_language = Some(value),
                "model" => model = Some(value),
                "ocr_enabled" => ocr_enabled = value == "true",
                "translate_filename" => translate_filename = value != "false",
                _ => {}
            }
        }
    }
    if files.is_empty() {
        return Err(error(
            "NO_FILES",
            StatusCode::BAD_REQUEST,
            "Choose at least one file.",
        ));
    }
    let output_dir = output_dir
        .filter(|p| output_dir_writable(Path::new(p)))
        .ok_or_else(|| {
            error(
                "OUTPUT_DIR_UNAVAILABLE",
                StatusCode::BAD_REQUEST,
                "Choose a writable output folder.",
            )
        })?;
    let target_language = target_language
        .filter(|l| !l.trim().is_empty())
        .ok_or_else(|| {
            error(
                "INVALID_LANGUAGE",
                StatusCode::BAD_REQUEST,
                "Choose a target language.",
            )
        })?;
    let model = model.filter(|m| !m.trim().is_empty()).ok_or_else(|| {
        error(
            "INVALID_MODEL",
            StatusCode::BAD_REQUEST,
            "Choose a translation model.",
        )
    })?;
    let mut created = Vec::new();
    let db = state.db.lock().await;
    for (filename, bytes) in files {
        let id = Uuid::new_v4().to_string();
        let clean_name = Path::new(&filename)
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("document")
            .to_owned();
        let inbox = state.data_dir.join("inbox").join(&id);
        fs::create_dir_all(&inbox).map_err(internal)?;
        let source_path = inbox.join(&clean_name);
        fs::write(&source_path, bytes).map_err(internal)?;
        let created_at = now();
        db.execute("INSERT INTO jobs (id, original_name, source_path, output_dir, target_language, model, ocr_enabled, translate_filename, status, progress, created_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, 'queued', '-', ?9)", params![id, clean_name, source_path.display().to_string(), output_dir, target_language, model, ocr_enabled as i32, translate_filename as i32, created_at]).map_err(internal)?;
        created.push(job_by_id(&db, &id).map_err(internal)?);
    }
    Ok((StatusCode::CREATED, Json(created)))
}

async fn retry_job(
    State(state): State<AppState>,
    AxumPath(id): AxumPath<String>,
    Json(body): Json<RetryRequest>,
) -> ApiResult<Json<Job>> {
    let db = state.db.lock().await;
    let changed = if let Some(output_dir) = body.output_dir { db.execute("UPDATE jobs SET status='queued', progress='-', error=NULL, remote_query_key=NULL, output_path=NULL, output_dir=?2 WHERE id=?1 AND status='failed'", params![id, output_dir]) } else { db.execute("UPDATE jobs SET status='queued', progress='-', error=NULL, remote_query_key=NULL, output_path=NULL WHERE id=?1 AND status='failed'", params![id]) }.map_err(internal)?;
    if changed == 0 {
        return Err(error(
            "JOB_NOT_RETRYABLE",
            StatusCode::BAD_REQUEST,
            "Only failed jobs can be retried.",
        ));
    }
    job_by_id(&db, &id).map(Json).map_err(internal)
}

async fn cancel_job(
    State(state): State<AppState>,
    AxumPath(id): AxumPath<String>,
) -> ApiResult<StatusCode> {
    let db = state.db.lock().await;
    let changed = db.execute("UPDATE jobs SET status='cancelled' WHERE id=?1 AND status NOT IN ('completed', 'cancelled')", params![id]).map_err(internal)?;
    if changed == 0 {
        return Err(error(
            "JOB_NOT_CANCELLABLE",
            StatusCode::BAD_REQUEST,
            "Job cannot be cancelled.",
        ));
    }
    Ok(StatusCode::NO_CONTENT)
}

#[derive(Serialize)]
struct OutputDir {
    path: String,
}
async fn select_output_dir() -> ApiResult<Json<OutputDir>> {
    tokio::task::spawn_blocking(|| rfd::FileDialog::new().pick_folder())
        .await
        .map_err(internal)?
        .map(|path| {
            Json(OutputDir {
                path: path.display().to_string(),
            })
        })
        .ok_or_else(|| {
            error(
                "PICKER_CANCELLED",
                StatusCode::BAD_REQUEST,
                "No folder selected.",
            )
        })
}

#[derive(Serialize, Deserialize)]
struct ModelInfo {
    #[serde(rename = "engineName")]
    engine_name: String,
    #[serde(rename = "tokenCostRatio")]
    token_cost_ratio: String,
}
#[derive(Serialize, Deserialize)]
struct LanguageInfo {
    #[serde(rename = "languageName")]
    language_name: String,
    #[serde(rename = "languageCode")]
    language_code: String,
}
#[derive(Serialize, Deserialize)]
struct AccountInfo {
    #[serde(rename = "bagWords")]
    bag_words: i64,
    #[serde(rename = "totalWords")]
    total_words: i64,
    #[serde(rename = "vipWords")]
    vip_words: i64,
    status: i32,
}
#[derive(Serialize)]
struct Metadata {
    models: Vec<ModelInfo>,
    languages: Vec<LanguageInfo>,
    account: AccountInfo,
}

async fn get_metadata(State(state): State<AppState>) -> ApiResult<Json<Metadata>> {
    let key = env::var("DOCLINGO_API_KEY").map_err(|_| {
        error(
            "API_KEY_NOT_CONFIGURED",
            StatusCode::SERVICE_UNAVAILABLE,
            "Set DOCLINGO_API_KEY before loading Doclingo metadata.",
        )
    })?;
    let models = external_list::<ModelInfo>(&state.client, &key, "models")
        .await
        .map_err(internal)?;
    let languages = external_list::<LanguageInfo>(
        &state.client,
        &key,
        "gettranslatorlanguagelist?internationalCode=zh-CN",
    )
    .await
    .map_err(internal)?;
    let account = external_data::<AccountInfo>(&state.client, &key, "getapiuserinfo")
        .await
        .map_err(internal)?;
    Ok(Json(Metadata {
        models,
        languages,
        account,
    }))
}

async fn worker(state: AppState) {
    loop {
        if let Err(e) = work_once(&state).await {
            eprintln!("Worker error: {e:#}");
        }
        tokio::time::sleep(Duration::from_secs(5)).await;
    }
}

async fn work_once(state: &AppState) -> Result<()> {
    let job = {
        let db = state.db.lock().await;
        next_job(&db)?
    };
    let Some(job) = job else {
        return Ok(());
    };
    let key = match env::var("DOCLINGO_API_KEY") {
        Ok(key) => key,
        Err(_) => {
            update(
                state,
                &job.id,
                "failed",
                "-",
                None,
                None,
                Some("DOCLINGO_API_KEY is not configured.".into()),
            )
            .await?;
            return Ok(());
        }
    };
    if job.remote_query_key.is_none() {
        update(state, &job.id, "uploading", "0%", None, None, None).await?;
        match submit(&state.client, &key, &job).await {
            Ok(query_key) => {
                update(
                    state,
                    &job.id,
                    "translating",
                    "0%",
                    Some(query_key),
                    None,
                    None,
                )
                .await?
            }
            Err(e) => {
                update(
                    state,
                    &job.id,
                    "failed",
                    "-",
                    None,
                    None,
                    Some(e.to_string()),
                )
                .await?
            }
        }
        return Ok(());
    }
    let status = match query_status(
        &state.client,
        &key,
        job.remote_query_key.as_deref().unwrap(),
    )
    .await
    {
        Ok(status) => status,
        Err(e) => {
            update(
                state,
                &job.id,
                "failed",
                "-",
                None,
                None,
                Some(e.to_string()),
            )
            .await?;
            return Ok(());
        }
    };
    match status.status {
        1 => {
            update(state, &job.id, "downloading", "100%", None, None, None).await?;
            let url = status
                .target_file_url
                .context("Doclingo did not return a file URL")?;
            let bytes = state
                .client
                .get(url)
                .send()
                .await?
                .error_for_status()?
                .bytes()
                .await?;
            let output = output_path(&job)?;
            fs::write(&output, bytes)?;
            update(
                state,
                &job.id,
                "completed",
                "100%",
                None,
                Some(output.display().to_string()),
                None,
            )
            .await?;
        }
        2 => {
            update(
                state,
                &job.id,
                "failed",
                "-",
                None,
                None,
                Some(
                    status
                        .fail_reason
                        .unwrap_or_else(|| "Translation failed.".into()),
                ),
            )
            .await?
        }
        _ => {
            update(
                state,
                &job.id,
                "translating",
                &status.translate_rate.unwrap_or_else(|| "-".into()),
                None,
                None,
                None,
            )
            .await?
        }
    }
    Ok(())
}

#[derive(Deserialize)]
struct DoclingoResponse<T> {
    success: bool,
    message: Option<String>,
    data: Option<T>,
    list: Option<Vec<T>>,
}
#[derive(Deserialize)]
struct Submitted {
    #[serde(rename = "translateQueryKey")]
    query_key: String,
}
#[derive(Deserialize)]
struct RemoteStatus {
    status: i32,
    #[serde(rename = "translateRate")]
    translate_rate: Option<String>,
    #[serde(rename = "targetFileUrl")]
    target_file_url: Option<String>,
    #[serde(rename = "failReason")]
    fail_reason: Option<String>,
}

async fn submit(client: &reqwest::Client, key: &str, job: &Job) -> Result<String> {
    let bytes = tokio::fs::read(&job.source_path).await?;
    let part = Part::bytes(bytes).file_name(job.original_name.clone());
    let form = Form::new()
        .part("file", part)
        .text("targetLang", job.target_language.clone())
        .text("model", job.model.clone())
        .text("ocrFlag", if job.ocr_enabled { "1" } else { "0" })
        .text("mathFlag", "1");
    let response: DoclingoResponse<Submitted> = client
        .post(DOCLINGO_TRANSLATE_URL)
        .bearer_auth(key)
        .multipart(form)
        .send()
        .await?
        .error_for_status()?
        .json()
        .await?;
    response
        .data
        .filter(|_| response.success)
        .map(|item| item.query_key)
        .context("Doclingo rejected the job")
}

async fn query_status(
    client: &reqwest::Client,
    key: &str,
    query_key: &str,
) -> Result<RemoteStatus> {
    let url = format!(
        "https://api.doclingo.cn/api/core/external/trans/query?translateQueryKey={query_key}"
    );
    let response: DoclingoResponse<RemoteStatus> = client
        .get(url)
        .bearer_auth(key)
        .send()
        .await?
        .error_for_status()?
        .json()
        .await?;
    response
        .data
        .filter(|_| response.success)
        .context("Doclingo status request failed")
}

async fn external_list<T: for<'de> Deserialize<'de>>(
    client: &reqwest::Client,
    key: &str,
    path: &str,
) -> Result<Vec<T>> {
    let response: DoclingoResponse<T> = client
        .get(format!("{DOCLINGO_API_URL}/{path}"))
        .bearer_auth(key)
        .send()
        .await?
        .error_for_status()?
        .json()
        .await?;
    response.list.filter(|_| response.success).context(
        response
            .message
            .unwrap_or_else(|| "Doclingo metadata request failed.".into()),
    )
}

async fn external_data<T: for<'de> Deserialize<'de>>(
    client: &reqwest::Client,
    key: &str,
    path: &str,
) -> Result<T> {
    let response: DoclingoResponse<T> = client
        .get(format!("{DOCLINGO_API_URL}/{path}"))
        .bearer_auth(key)
        .send()
        .await?
        .error_for_status()?
        .json()
        .await?;
    response.data.filter(|_| response.success).context(
        response
            .message
            .unwrap_or_else(|| "Doclingo metadata request failed.".into()),
    )
}

fn output_path(job: &Job) -> Result<PathBuf> {
    let source = Path::new(&job.original_name);
    let base = source
        .file_stem()
        .and_then(|v| v.to_str())
        .unwrap_or("translated");
    let extension = source.extension().and_then(|v| v.to_str()).unwrap_or("bin");
    let base = if job.translate_filename {
        format!("{base}_{}", job.target_language)
    } else {
        base.to_owned()
    };
    let dir = Path::new(&job.output_dir);
    for n in 1..10_000 {
        let suffix = if n == 1 {
            String::new()
        } else {
            format!(" ({n})")
        };
        let output = dir.join(format!("{base}{suffix}.{extension}"));
        if !output.exists() {
            return Ok(output);
        }
    }
    anyhow::bail!("No available output filename")
}

fn output_dir_writable(path: &Path) -> bool {
    path.is_dir() && fs::OpenOptions::new().write(true).open(path).is_ok()
}
fn now() -> String {
    format!(
        "{:020}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis()
    )
}
fn internal(e: impl std::fmt::Display) -> (StatusCode, Json<ApiError>) {
    error("INTERNAL", StatusCode::INTERNAL_SERVER_ERROR, e.to_string())
}

fn job_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Job> {
    Ok(Job {
        id: row.get(0)?,
        original_name: row.get(1)?,
        source_path: row.get(2)?,
        output_dir: row.get(3)?,
        target_language: row.get(4)?,
        model: row.get(5)?,
        ocr_enabled: row.get::<_, i32>(6)? != 0,
        translate_filename: row.get::<_, i32>(7)? != 0,
        status: row.get(8)?,
        progress: row.get(9)?,
        remote_query_key: row.get(10)?,
        output_path: row.get(11)?,
        error: row.get(12)?,
        created_at: row.get(13)?,
    })
}
fn jobs_from<P: rusqlite::Params>(
    db: &Connection,
    sql: &str,
    params: P,
) -> rusqlite::Result<Vec<Job>> {
    let mut statement = db.prepare(sql)?;
    let rows = statement.query_map(params, job_row)?.collect();
    rows
}
fn job_by_id(db: &Connection, id: &str) -> rusqlite::Result<Job> {
    db.query_row("SELECT * FROM jobs WHERE id=?1", params![id], job_row)
}
fn next_job(db: &Connection) -> rusqlite::Result<Option<Job>> {
    db.query_row("SELECT * FROM jobs WHERE status IN ('queued', 'translating') ORDER BY created_at ASC LIMIT 1", [], job_row).optional()
}
async fn update(
    state: &AppState,
    id: &str,
    status: &str,
    progress: &str,
    remote_key: Option<String>,
    output: Option<String>,
    failure: Option<String>,
) -> Result<()> {
    let db = state.db.lock().await;
    db.execute("UPDATE jobs SET status=?2, progress=?3, remote_query_key=COALESCE(?4, remote_query_key), output_path=COALESCE(?5, output_path), error=?6 WHERE id=?1", params![id, status, progress, remote_key, output, failure])?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_model_metadata() {
        let response: DoclingoResponse<ModelInfo> = serde_json::from_str(
            r#"{"success":true,"list":[{"engineName":"chatgpt-4o","tokenCostRatio":"4"}]}"#,
        )
        .unwrap();
        assert_eq!(response.list.unwrap()[0].token_cost_ratio, "4");
    }

    #[test]
    fn creates_safe_suffixes() {
        let dir = std::env::temp_dir().join(Uuid::new_v4().to_string());
        fs::create_dir_all(&dir).unwrap();
        let job = Job {
            id: "1".into(),
            original_name: "报价.xlsx".into(),
            source_path: "-".into(),
            output_dir: dir.display().to_string(),
            target_language: "fr".into(),
            model: "chatgpt-4omini".into(),
            ocr_enabled: false,
            translate_filename: true,
            status: "queued".into(),
            progress: "-".into(),
            remote_query_key: None,
            output_path: None,
            error: None,
            created_at: "-".into(),
        };
        assert!(output_path(&job).unwrap().ends_with("报价_fr.xlsx"));
        fs::remove_dir_all(dir).unwrap();
    }
}
