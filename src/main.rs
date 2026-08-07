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
    routing::{delete, get, post},
    Json, Router,
};
use reqwest::multipart::{Form, Part};
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use tokio::sync::Mutex;
use tower_http::{cors::CorsLayer, trace::TraceLayer};
use uuid::Uuid;

const DOCLINGO_TRANSLATE_URL: &str = "https://api.doclingo.cn/api/core/external/translate";
const DOCLINGO_API_URL: &str = "https://api.doclingo.cn/api/core/external";

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

fn main() -> Result<()> {
    if let Ok(exe) = env::current_exe() {
        if let Some(dir) = exe.parent() {
            dotenvy::from_path(dir.join(".env")).ok();
        }
    }
    dotenvy::dotenv().ok();
    let runtime = Arc::new(tokio::runtime::Runtime::new()?);
    let data_dir = env::current_dir()?.join("app-data");
    fs::create_dir_all(data_dir.join("inbox"))?;
    let db = Connection::open(data_dir.join("translator.db"))?;
    migrate(&db)?;
    let state = AppState {
        db: Arc::new(Mutex::new(db)),
        data_dir,
        client: reqwest::Client::new(),
    };
    runtime.spawn(worker(state.clone()));
    let router = Router::new()
        .route("/api/jobs", get(list_jobs).post(create_jobs))
        .route("/api/jobs/{id}/retry", post(retry_job))
        .route("/api/jobs/{id}", delete(cancel_job))
        .route("/api/select-output-dir", post(select_output_dir))
        .route("/api/metadata", get(get_metadata))
        .layer(CorsLayer::permissive())
        .layer(TraceLayer::new_for_http())
        .with_state(state.clone());
    let listener = runtime.block_on(tokio::net::TcpListener::bind("127.0.0.1:0"))?;
    runtime.spawn(async move {
        if let Err(error) = axum::serve(listener, router).await {
            eprintln!("Translator API stopped: {error}");
        }
    });
    run_slint(state, runtime)
}

slint::slint! {
    import { Button, CheckBox, ComboBox, LineEdit } from "std-widgets.slint";

    export component AppWindow inherits Window {
        title: "Doclingo Translator";
        width: 1180px;
        height: 780px;
        background: #12151b;
        default-font-family: "Microsoft YaHei";

        in-out property <string> notice: "正在加载 Doclingo 信息…";
        in-out property <string> output-dir: "";
        in-out property <string> target-language: "";
        in-out property <string> model: "";
        in-out property <[string]> languages;
        in-out property <[string]> models;
        in-out property <[string]> queue;
        in-out property <string> summary: "0 个任务  ·  已完成 0 个";
        in-out property <string> account-info: "正在加载账户信息…";
        in-out property <bool> ocr-enabled: false;
        in-out property <bool> translate-filename: true;
        callback add-files();
        callback choose-output();
        callback start-translation();

        VerticalLayout {
            spacing: 0px;
            Rectangle {
                height: 64px;
                background: #0d0f14;
                border-color: #2c313b;
                border-width: 1px;
                HorizontalLayout {
                    padding-left: 26px; padding-right: 26px; spacing: 18px;
                    Text { text: "文档翻译"; color: #ffb31c; font-size: 24px; font-weight: 700; vertical-alignment: center; }
                    Rectangle { width: 1px; height: 24px; background: #3a404b; }
                    Text { text: "Doclingo · 本地翻译队列"; color: #9099a8; font-size: 14px; vertical-alignment: center; }
                    Rectangle { horizontal-stretch: 1; }
                    Text { text: "●  就绪"; color: #22d37b; font-size: 14px; vertical-alignment: center; }
                }
            }
            HorizontalLayout {
                spacing: 0px;
                Rectangle {
                    width: 300px; background: #15191f; border-color: #303641; border-width: 1px;
                    VerticalLayout {
                        padding: 18px; spacing: 10px;
                        Text { text: "工作区"; color: #8993a1; font-size: 12px; }
                        Rectangle { height: 42px; border-radius: 9px; background: #43361f; Text { text: "翻译队列"; color: #ffb31c; font-size: 16px; font-weight: 700; horizontal-alignment: center; vertical-alignment: center; } }
                        Text { text: "翻译记录"; color: #b8c0cc; font-size: 15px; }
                        Text { text: "术语库"; color: #b8c0cc; font-size: 15px; }
                        Text { text: "设置"; color: #b8c0cc; font-size: 15px; }
                        Rectangle { height: 1px; background: #303641; }
                        Text { text: "翻译设置"; color: white; font-size: 16px; font-weight: 700; }
                        Text { text: "输出语言"; color: #98a2b2; font-size: 13px; }
                        ComboBox { model: root.languages; current-value <=> root.target-language; }
                        Text { text: "翻译引擎"; color: #98a2b2; font-size: 13px; }
                        ComboBox { model: root.models; current-value <=> root.model; }
                        CheckBox { text: "启用 OCR"; checked <=> root.ocr-enabled; }
                        CheckBox { text: "自动翻译文件名"; checked <=> root.translate-filename; }
                        Text { text: "输出目录"; color: #98a2b2; font-size: 13px; }
                        HorizontalLayout { spacing: 8px; LineEdit { text <=> root.output-dir; horizontal-stretch: 1; } Button { text: "选择"; clicked => { root.choose-output(); } } }
                        Rectangle { vertical-stretch: 1; }
                        Rectangle { height: 118px; border-radius: 10px; background: #202530; border-width: 1px; border-color: #414957;
                            VerticalLayout { padding: 12px; spacing: 6px;
                                Text { text: "账户信息"; color: white; font-size: 16px; font-weight: 700; }
                                Text { text: root.account-info; color: #b8c2cf; font-size: 13px; wrap: word-wrap; }
                                Text { text: "每 30 秒自动刷新"; color: #6fbde4; font-size: 12px; }
                            }
                        }
                    }
                }
                Rectangle {
                    background: #1a1e25;
                    VerticalLayout {
                        padding: 22px; spacing: 16px;
                        HorizontalLayout {
                            spacing: 10px;
                            Button { text: "+  添加文件"; clicked => { root.add-files(); } }
                            Button { text: "清空选择"; }
                            Text { text: root.notice; color: #a3adba; font-size: 13px; vertical-alignment: center; horizontal-stretch: 1; }
                        }
                        Rectangle {
                            height: 170px; border-radius: 14px; background: #202530; border-width: 1px; border-color: #414957;
                            VerticalLayout { padding: 28px; spacing: 8px;
                                Text { text: "拖入文档"; color: white; font-size: 24px; font-weight: 700; horizontal-alignment: center; }
                                Text { text: "支持 Doclingo 可翻译的全部文档格式"; color: #aeb7c5; font-size: 14px; horizontal-alignment: center; }
                                Text { text: "也可点击“添加文件”进行多选"; color: #6fbde4; font-size: 14px; horizontal-alignment: center; }
                            }
                        }
                        Rectangle {
                            background: #202530; border-radius: 14px; border-width: 1px; border-color: #414957; vertical-stretch: 1;
                            VerticalLayout { padding: 16px; spacing: 10px;
                                Text { text: "翻译队列"; color: white; font-size: 20px; font-weight: 700; }
                                Rectangle { height: 1px; background: #414957; }
                                HorizontalLayout { Text { text: "文件名"; color: #aeb7c5; horizontal-stretch: 3; } Text { text: "输出语言"; color: #aeb7c5; horizontal-stretch: 1; } Text { text: "状态"; color: #aeb7c5; horizontal-stretch: 1; } Text { text: "进度"; color: #aeb7c5; horizontal-stretch: 1; } }
                                for row in root.queue: Text { text: row; color: #e5e9ef; font-size: 14px; }
                                Rectangle { vertical-stretch: 1; }
                            }
                        }
                        Rectangle { height: 70px; background: #202530; border-radius: 14px; border-width: 1px; border-color: #414957;
                            HorizontalLayout { padding: 14px; Text { text: root.summary; color: #b6c0cd; font-size: 14px; vertical-alignment: center; horizontal-stretch: 1; } Button { text: "开始翻译"; clicked => { root.start-translation(); } } }
                        }
                    }
                }
            }
        }
    }
}

fn run_slint(state: AppState, runtime: Arc<tokio::runtime::Runtime>) -> Result<()> {
    use slint::{ComponentHandle, ModelRc, SharedString, VecModel};
    use std::{collections::HashMap, rc::Rc, sync::Mutex as StdMutex};
    let ui = AppWindow::new().map_err(|e| anyhow::anyhow!("cannot create native window: {e}"))?;
    let files = Arc::new(StdMutex::new(Vec::<PathBuf>::new()));
    let language_codes = Arc::new(StdMutex::new(HashMap::<String, String>::new()));
    let refresh = |ui: &AppWindow, state: &AppState, runtime: &Arc<tokio::runtime::Runtime>| {
        let jobs = runtime
            .block_on(async {
                let db = state.db.lock().await;
                jobs_from(&db, "SELECT * FROM jobs ORDER BY created_at DESC", [])
            })
            .unwrap_or_default();
        let rows = jobs
            .iter()
            .map(|j| {
                SharedString::from(format!(
                    "{}     {}     {}     {}",
                    j.original_name,
                    j.target_language,
                    status_label(&j.status),
                    j.progress
                ))
            })
            .collect::<Vec<_>>();
        ui.set_queue(ModelRc::new(Rc::new(VecModel::from(rows))));
        ui.set_summary(
            format!(
                "共 {} 个任务  ·  已完成 {} 个",
                jobs.len(),
                jobs.iter().filter(|j| j.status == "completed").count()
            )
            .into(),
        );
    };
    if let Ok(meta) = runtime.block_on(fetch_metadata(&state)) {
        let languages = meta
            .languages
            .iter()
            .map(|x| {
                let name = chinese_language_name(&x.language_code, &x.language_name);
                language_codes
                    .lock()
                    .unwrap()
                    .insert(name.clone(), x.language_code.clone());
                SharedString::from(name)
            })
            .collect::<Vec<_>>();
        if ui.get_target_language().is_empty() {
            if let Some(language) = languages.first() {
                ui.set_target_language(language.clone());
            }
        }
        ui.set_languages(ModelRc::new(Rc::new(VecModel::from(languages))));
        ui.set_models(ModelRc::new(Rc::new(VecModel::from(
            meta.models
                .into_iter()
                .map(|x| SharedString::from(x.engine_name))
                .collect::<Vec<_>>(),
        ))));
        ui.set_account_info(account_summary(&meta.account).into());
        ui.set_notice(format!("账户可用额度：{} 字", meta.account.total_words).into());
    }
    refresh(&ui, &state, &runtime);
    let weak = ui.as_weak();
    let files_for_add = files.clone();
    ui.on_add_files(move || {
        if let Some(paths) = rfd::FileDialog::new().pick_files() {
            let count = paths.len();
            files_for_add.lock().unwrap().extend(paths);
            if let Some(ui) = weak.upgrade() {
                ui.set_notice(format!("已选择 {} 个文件，设置后点击开始翻译。", count).into());
            }
        }
    });
    let weak = ui.as_weak();
    ui.on_choose_output(move || {
        if let Some(path) = rfd::FileDialog::new().pick_folder() {
            if let Some(ui) = weak.upgrade() {
                ui.set_output_dir(path.display().to_string().into());
            }
        }
    });
    let weak = ui.as_weak();
    let start_state = state.clone();
    let start_runtime = runtime.clone();
    let start_files = files.clone();
    let start_languages = language_codes.clone();
    ui.on_start_translation(move || {
        if let Some(ui) = weak.upgrade() {
            let paths = std::mem::take(&mut *start_files.lock().unwrap());
            let result = start_runtime.block_on(enqueue_paths(
                &start_state,
                paths,
                &ui.get_output_dir(),
                &start_languages
                    .lock()
                    .unwrap()
                    .get(ui.get_target_language().as_str())
                    .cloned()
                    .unwrap_or_else(|| ui.get_target_language().to_string()),
                &ui.get_model(),
                ui.get_ocr_enabled(),
                ui.get_translate_filename(),
            ));
            ui.set_notice(match result {
                Ok(jobs) => format!("已加入 {} 个翻译任务。", jobs.len()).into(),
                Err(e) => e.to_string().into(),
            });
        }
    });
    let timer = slint::Timer::default();
    let weak = ui.as_weak();
    let timer_state = state.clone();
    let timer_runtime = runtime.clone();
    timer.start(
        slint::TimerMode::Repeated,
        Duration::from_secs(30),
        move || {
            if let Some(ui) = weak.upgrade() {
                if let Ok(meta) = timer_runtime.block_on(fetch_metadata(&timer_state)) {
                    ui.set_account_info(account_summary(&meta.account).into());
                    ui.set_notice(format!("账户可用额度：{} 字", meta.account.total_words).into());
                }
            }
        },
    );
    ui.run()
        .map_err(|e| anyhow::anyhow!("native application stopped: {e}"))
}

fn chinese_language_name(code: &str, fallback: &str) -> String {
    match code {
        "zh" | "zh-CN" => "简体中文",
        "zh-TW" => "繁体中文",
        "en" | "en-US" => "英语",
        "fr" => "法语",
        "de" => "德语",
        "ja" => "日语",
        "ko" => "韩语",
        "es" => "西班牙语",
        "pt" | "pt-BR" => "葡萄牙语",
        "it" => "意大利语",
        "ru" => "俄语",
        "ar" => "阿拉伯语",
        _ => fallback,
    }
    .to_owned()
}

fn account_summary(account: &AccountInfo) -> String {
    format!(
        "总额度：{} 字\n会员额度：{} 字\n套餐额度：{} 字",
        account.total_words, account.vip_words, account.bag_words
    )
}

#[cfg(any())]
struct TranslatorApp {
    state: AppState,
    runtime: Arc<tokio::runtime::Runtime>,
    files: Vec<PathBuf>,
    jobs: Vec<Job>,
    metadata: Option<Metadata>,
    metadata_rx: Option<mpsc::Receiver<Result<Metadata, String>>>,
    output_dir: String,
    target_language: String,
    model: String,
    ocr_enabled: bool,
    translate_filename: bool,
    notice: String,
    last_jobs_refresh: Instant,
    last_metadata_refresh: Instant,
}

#[cfg(any())]
impl TranslatorApp {
    fn new(
        cc: &eframe::CreationContext<'_>,
        state: AppState,
        runtime: Arc<tokio::runtime::Runtime>,
    ) -> Self {
        let mut fonts = egui::FontDefinitions::default();
        if let Ok(bytes) = fs::read(r"C:\Windows\Fonts\msyh.ttc") {
            fonts.font_data.insert(
                "microsoft_yahei".into(),
                Arc::new(egui::FontData::from_owned(bytes)),
            );
            for family in [egui::FontFamily::Proportional, egui::FontFamily::Monospace] {
                fonts
                    .families
                    .entry(family)
                    .or_default()
                    .insert(0, "microsoft_yahei".into());
            }
        }
        cc.egui_ctx.set_fonts(fonts);
        let mut style = (*cc.egui_ctx.style()).clone();
        style.visuals = egui::Visuals::dark();
        style.visuals.panel_fill = egui::Color32::from_rgb(20, 23, 28);
        style.visuals.window_fill = egui::Color32::from_rgb(30, 34, 41);
        style.visuals.faint_bg_color = egui::Color32::from_rgb(35, 39, 47);
        style.visuals.extreme_bg_color = egui::Color32::from_rgb(16, 19, 24);
        style.visuals.widgets.noninteractive.bg_fill = egui::Color32::from_rgb(30, 34, 41);
        style.visuals.widgets.inactive.bg_fill = egui::Color32::from_rgb(36, 40, 47);
        style.visuals.selection.bg_fill = egui::Color32::from_rgb(255, 176, 24);
        style.spacing.item_spacing = egui::vec2(10.0, 10.0);
        style.spacing.button_padding = egui::vec2(12.0, 8.0);
        cc.egui_ctx.set_style(style);
        let mut app = Self {
            state,
            runtime,
            files: Vec::new(),
            jobs: Vec::new(),
            metadata: None,
            metadata_rx: None,
            output_dir: String::new(),
            target_language: String::new(),
            model: String::new(),
            ocr_enabled: false,
            translate_filename: true,
            notice: "正在加载 Doclingo 模型、语言和账户信息…".into(),
            last_jobs_refresh: Instant::now() - Duration::from_secs(2),
            last_metadata_refresh: Instant::now() - Duration::from_secs(30),
        };
        app.refresh_metadata();
        app
    }

    fn refresh_metadata(&mut self) {
        if self.metadata_rx.is_some() {
            return;
        }
        self.last_metadata_refresh = Instant::now();
        let state = self.state.clone();
        let (tx, rx) = mpsc::channel();
        self.runtime.spawn(async move {
            let _ = tx.send(fetch_metadata(&state).await.map_err(|e| e.to_string()));
        });
        self.metadata_rx = Some(rx);
    }

    fn refresh_jobs(&mut self) {
        if self.last_jobs_refresh.elapsed() < Duration::from_secs(1) {
            return;
        }
        self.last_jobs_refresh = Instant::now();
        if let Ok(jobs) = self.runtime.block_on(async {
            let db = self.state.db.lock().await;
            jobs_from(&db, "SELECT * FROM jobs ORDER BY created_at DESC", [])
        }) {
            self.jobs = jobs;
        }
    }

    fn enqueue(&mut self) {
        if self.files.is_empty() {
            self.notice = "请先添加文件。".into();
            return;
        }
        if !output_dir_writable(Path::new(&self.output_dir)) {
            self.notice = "请选择可写入的输出文件夹。".into();
            return;
        }
        if self.target_language.is_empty() || self.model.is_empty() {
            self.notice = "请先选择输出语言和翻译模型。".into();
            return;
        }
        let files = std::mem::take(&mut self.files);
        match self.runtime.block_on(enqueue_paths(
            &self.state,
            files,
            &self.output_dir,
            &self.target_language,
            &self.model,
            self.ocr_enabled,
            self.translate_filename,
        )) {
            Ok(jobs) => {
                self.notice = format!("已加入 {} 个翻译任务。", jobs.len());
                self.jobs.splice(0..0, jobs);
            }
            Err(e) => self.notice = e.to_string(),
        }
    }
}

#[cfg(any())]
impl eframe::App for TranslatorApp {
    fn update(&mut self, ctx: &egui::Context, _: &mut eframe::Frame) {
        let mut visuals = egui::Visuals::dark();
        visuals.panel_fill = egui::Color32::from_rgb(20, 23, 28);
        visuals.window_fill = egui::Color32::from_rgb(30, 34, 41);
        visuals.faint_bg_color = egui::Color32::from_rgb(35, 39, 47);
        visuals.extreme_bg_color = egui::Color32::from_rgb(16, 19, 24);
        visuals.widgets.noninteractive.bg_fill = egui::Color32::from_rgb(30, 34, 41);
        visuals.widgets.inactive.bg_fill = egui::Color32::from_rgb(36, 40, 47);
        ctx.set_visuals(visuals);
        ctx.request_repaint_after(Duration::from_millis(500));
        if self.last_metadata_refresh.elapsed() >= Duration::from_secs(30) {
            self.refresh_metadata();
        }
        if let Some(rx) = &self.metadata_rx {
            if let Ok(result) = rx.try_recv() {
                self.metadata_rx = None;
                match result {
                    Ok(metadata) => {
                        if self.target_language.is_empty() {
                            self.target_language = metadata
                                .languages
                                .first()
                                .map(|x| x.language_code.clone())
                                .unwrap_or_default();
                        }
                        if self.model.is_empty() {
                            self.model = metadata
                                .models
                                .first()
                                .map(|x| x.engine_name.clone())
                                .unwrap_or_default();
                        }
                        self.metadata = Some(metadata);
                        self.notice = "Doclingo 账户信息已刷新。".into();
                    }
                    Err(e) => self.notice = format!("无法获取 Doclingo 信息：{e}"),
                }
            }
        }
        for file in ctx.input(|i| i.raw.dropped_files.clone()) {
            if let Some(path) = file.path {
                if !self.files.contains(&path) {
                    self.files.push(path);
                }
            }
        }
        self.refresh_jobs();
        egui::TopBottomPanel::top("app_header")
            .exact_height(64.0)
            .frame(egui::Frame::default().fill(egui::Color32::from_rgb(15, 17, 21)))
            .show(ctx, |ui| {
                ui.horizontal(|ui| {
                    ui.add_space(12.0);
                    ui.heading(
                        egui::RichText::new("文档翻译")
                            .size(22.0)
                            .color(egui::Color32::from_rgb(255, 183, 28)),
                    );
                    ui.separator();
                    ui.label(egui::RichText::new("Doclingo · 本地翻译队列").weak());
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.label(
                            egui::RichText::new("● 就绪")
                                .color(egui::Color32::from_rgb(27, 203, 116)),
                        );
                    });
                });
            });
        egui::SidePanel::left("sidebar")
            .min_width(300.0)
            .frame(egui::Frame::default().fill(egui::Color32::from_rgb(20, 23, 28)))
            .show(ctx, |ui| {
                ui.add_space(18.0);
                ui.heading(
                    egui::RichText::new("文档翻译")
                        .color(egui::Color32::from_rgb(255, 180, 24))
                        .size(23.0),
                );
                ui.add_space(22.0);
                let nav_width = ui.available_width();
                ui.add_sized(
                    [nav_width, 38.0],
                    egui::Button::new(
                        egui::RichText::new(format!("翻译队列     {}", self.jobs.len()))
                            .strong()
                            .color(egui::Color32::from_rgb(255, 183, 28)),
                    )
                    .fill(egui::Color32::from_rgb(55, 47, 32)),
                );
                ui.add_sized(
                    [nav_width, 34.0],
                    egui::Button::new("翻译记录").fill(egui::Color32::TRANSPARENT),
                );
                ui.add_sized(
                    [nav_width, 34.0],
                    egui::Button::new("术语库").fill(egui::Color32::TRANSPARENT),
                );
                ui.add_sized(
                    [nav_width, 34.0],
                    egui::Button::new("设置").fill(egui::Color32::TRANSPARENT),
                );
                ui.separator();
                ui.label(egui::RichText::new(format!("{} 个历史任务", self.jobs.len())).weak());
                ui.add_space(18.0);
                egui::Frame::new()
                    .fill(egui::Color32::from_rgb(29, 33, 39))
                    .inner_margin(egui::Margin::same(14))
                    .corner_radius(10.0)
                    .stroke(egui::Stroke::new(
                        1.0_f32,
                        egui::Color32::from_rgb(65, 71, 80),
                    ))
                    .show(ui, |ui| {
                        ui.label(egui::RichText::new("翻译设置").strong());
                        ui.add_space(6.0);
                        ui.label("输出语言");
                        egui::ComboBox::from_id_salt("language")
                            .selected_text(language_label(
                                self.metadata.as_ref(),
                                &self.target_language,
                            ))
                            .show_ui(ui, |ui| {
                                if let Some(meta) = &self.metadata {
                                    for language in &meta.languages {
                                        ui.selectable_value(
                                            &mut self.target_language,
                                            language.language_code.clone(),
                                            &language.language_name,
                                        );
                                    }
                                }
                            });
                        ui.add_space(8.0);
                        ui.label("翻译引擎");
                        egui::ComboBox::from_id_salt("model")
                            .selected_text(&self.model)
                            .show_ui(ui, |ui| {
                                if let Some(meta) = &self.metadata {
                                    for model in &meta.models {
                                        ui.selectable_value(
                                            &mut self.model,
                                            model.engine_name.clone(),
                                            format!(
                                                "{}  ×{}",
                                                model.engine_name, model.token_cost_ratio
                                            ),
                                        );
                                    }
                                }
                            });
                        ui.checkbox(&mut self.ocr_enabled, "启用 OCR");
                        ui.checkbox(&mut self.translate_filename, "自动翻译文件名");
                        ui.add_space(8.0);
                        ui.label("输出目录");
                        ui.horizontal(|ui| {
                            ui.add(
                                egui::TextEdit::singleline(&mut self.output_dir)
                                    .desired_width(180.0),
                            );
                            if ui.button("选择").clicked() {
                                if let Some(path) = rfd::FileDialog::new().pick_folder() {
                                    self.output_dir = path.display().to_string();
                                }
                            }
                        });
                        ui.add_space(18.0);
                        if let Some(meta) = &self.metadata {
                            ui.separator();
                            ui.label(egui::RichText::new("账户余额").strong());
                            ui.label(format!("总额度  {} 字", meta.account.total_words));
                            ui.label(format!("会员额度  {} 字", meta.account.vip_words));
                            ui.label(format!("套餐额度  {} 字", meta.account.bag_words));
                            if ui.small_button("刷新账户信息").clicked() {
                                self.refresh_metadata();
                            }
                        }
                    });
            });
        egui::CentralPanel::default()
            .frame(egui::Frame::default().fill(egui::Color32::from_rgb(24, 27, 33)))
            .show(ctx, |ui| {
                ui.set_min_width(ui.available_width());
                ui.add_space(12.0);
                let content_width = ui.available_width();
                ui.horizontal(|ui| {
                    if ui
                        .add(
                            egui::Button::new(
                                egui::RichText::new("＋ 添加文件")
                                    .size(18.0)
                                    .color(egui::Color32::from_rgb(24, 25, 28)),
                            )
                            .fill(egui::Color32::from_rgb(255, 183, 28)),
                        )
                        .clicked()
                    {
                        if let Some(paths) = rfd::FileDialog::new().pick_files() {
                            for path in paths {
                                if !self.files.contains(&path) {
                                    self.files.push(path);
                                }
                            }
                        }
                    }
                    if ui.button("移除全部").clicked() {
                        self.files.clear();
                    }
                    ui.separator();
                    ui.label(&self.notice);
                });
                ui.add_space(12.0);
                egui::Frame::new()
                    .fill(egui::Color32::from_rgb(31, 35, 41))
                    .inner_margin(egui::Margin::same(18))
                    .corner_radius(12.0)
                    .stroke(egui::Stroke::new(
                        1.0_f32,
                        egui::Color32::from_rgb(67, 73, 82),
                    ))
                    .show(ui, |ui| {
                        ui.set_min_width(content_width - 18.0);
                        ui.heading(format!("待提交文件 ({})", self.files.len()));
                        if self.files.is_empty() {
                            ui.add_space(16.0);
                            ui.vertical_centered(|ui| {
                                ui.label(egui::RichText::new("拖入文档").size(22.0).strong());
                                ui.label("支持 Doclingo 可翻译的全部文档格式");
                                ui.label("或点击上方“添加文件”进行多选");
                            });
                            ui.add_space(16.0);
                        } else {
                            egui::ScrollArea::vertical()
                                .max_height(150.0)
                                .show(ui, |ui| {
                                    for path in &self.files {
                                        ui.horizontal(|ui| {
                                            ui.label("▧");
                                            ui.label(
                                                path.file_name()
                                                    .and_then(|x| x.to_str())
                                                    .unwrap_or("document"),
                                            );
                                            ui.with_layout(
                                                egui::Layout::right_to_left(egui::Align::Center),
                                                |ui| {
                                                    ui.label(path.display().to_string());
                                                },
                                            );
                                        });
                                    }
                                });
                        }
                    });
                ui.add_space(14.0);
                egui::Frame::new()
                    .fill(egui::Color32::from_rgb(29, 33, 39))
                    .inner_margin(egui::Margin::same(16))
                    .corner_radius(12.0)
                    .stroke(egui::Stroke::new(
                        1.0_f32,
                        egui::Color32::from_rgb(67, 73, 82),
                    ))
                    .show(ui, |ui| {
                        ui.set_min_width(content_width - 18.0);
                        ui.heading("翻译队列");
                        ui.separator();
                        egui::ScrollArea::vertical()
                            .max_height(310.0)
                            .show(ui, |ui| {
                                egui::Grid::new("jobs")
                                    .striped(true)
                                    .min_col_width(95.0)
                                    .show(ui, |ui| {
                                        ui.strong("文件名");
                                        ui.strong("输出语言");
                                        ui.strong("状态");
                                        ui.strong("进度");
                                        ui.end_row();
                                        for job in &self.jobs {
                                            ui.label(&job.original_name);
                                            ui.label(&job.target_language);
                                            ui.label(status_label(&job.status));
                                            ui.add(
                                                egui::ProgressBar::new(progress_value(
                                                    &job.progress,
                                                ))
                                                .text(&job.progress),
                                            );
                                            ui.end_row();
                                        }
                                    });
                            });
                    });
                ui.add_space(12.0);
                egui::Frame::new()
                    .fill(egui::Color32::from_rgb(31, 35, 41))
                    .inner_margin(egui::Margin::same(12))
                    .corner_radius(12.0)
                    .stroke(egui::Stroke::new(
                        1.0_f32,
                        egui::Color32::from_rgb(67, 73, 82),
                    ))
                    .show(ui, |ui| {
                        ui.set_min_width(content_width - 18.0);
                        ui.horizontal(|ui| {
                            ui.label(format!("共 {} 个任务", self.jobs.len()));
                            ui.separator();
                            ui.label(format!(
                                "已完成 {} 个",
                                self.jobs.iter().filter(|j| j.status == "completed").count()
                            ));
                            ui.with_layout(
                                egui::Layout::right_to_left(egui::Align::Center),
                                |ui| {
                                    if ui
                                        .add_sized(
                                            [180.0, 44.0],
                                            egui::Button::new(
                                                egui::RichText::new("开始翻译")
                                                    .size(20.0)
                                                    .color(egui::Color32::WHITE),
                                            )
                                            .fill(egui::Color32::from_rgb(0, 166, 218)),
                                        )
                                        .clicked()
                                    {
                                        self.enqueue();
                                    }
                                },
                            );
                        });
                    });
            });
    }
}

fn status_label(status: &str) -> &str {
    match status {
        "queued" => "排队中",
        "uploading" => "上传中",
        "translating" => "翻译中",
        "downloading" => "下载中",
        "completed" => "已完成",
        "failed" => "失败",
        "cancelled" => "已取消",
        _ => status,
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

async fn enqueue_paths(
    state: &AppState,
    paths: Vec<PathBuf>,
    output_dir: &str,
    target_language: &str,
    model: &str,
    ocr_enabled: bool,
    translate_filename: bool,
) -> Result<Vec<Job>> {
    if paths.is_empty() {
        anyhow::bail!("请先添加文件。");
    }
    if !output_dir_writable(Path::new(output_dir)) {
        anyhow::bail!("请选择可写入的输出文件夹。");
    }
    let mut input = Vec::with_capacity(paths.len());
    for path in paths {
        let name = path
            .file_name()
            .and_then(|x| x.to_str())
            .context("无效的文件名")?
            .to_owned();
        input.push((name, fs::read(path)?));
    }
    let db = state.db.lock().await;
    let mut created = Vec::with_capacity(input.len());
    for (name, bytes) in input {
        let id = Uuid::new_v4().to_string();
        let inbox = state.data_dir.join("inbox").join(&id);
        fs::create_dir_all(&inbox)?;
        let source_path = inbox.join(&name);
        fs::write(&source_path, bytes)?;
        db.execute("INSERT INTO jobs (id, original_name, source_path, output_dir, target_language, model, ocr_enabled, translate_filename, status, progress, created_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, 'queued', '-', ?9)", params![id, name, source_path.display().to_string(), output_dir, target_language, model, ocr_enabled as i32, translate_filename as i32, now()])?;
        created.push(job_by_id(&db, &id)?);
    }
    Ok(created)
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

#[derive(Serialize, Deserialize, Clone)]
struct ModelInfo {
    #[serde(rename = "engineName")]
    engine_name: String,
    #[serde(rename = "tokenCostRatio")]
    token_cost_ratio: String,
}
#[derive(Serialize, Deserialize, Clone)]
struct LanguageInfo {
    #[serde(rename = "languageName")]
    language_name: String,
    #[serde(rename = "languageCode")]
    language_code: String,
}
#[derive(Serialize, Deserialize, Clone)]
struct AccountInfo {
    #[serde(rename = "bagWords")]
    bag_words: i64,
    #[serde(rename = "totalWords")]
    total_words: i64,
    #[serde(rename = "vipWords")]
    vip_words: i64,
    status: i32,
}
#[derive(Serialize, Clone)]
struct Metadata {
    models: Vec<ModelInfo>,
    languages: Vec<LanguageInfo>,
    account: AccountInfo,
}

async fn get_metadata(State(state): State<AppState>) -> ApiResult<Json<Metadata>> {
    fetch_metadata(&state).await.map(Json).map_err(internal)
}

async fn fetch_metadata(state: &AppState) -> Result<Metadata> {
    let key = env::var("DOCLINGO_API_KEY")
        .map_err(|_| anyhow::anyhow!("请在 .env 中设置 DOCLINGO_API_KEY。"))?;
    let models = external_list::<ModelInfo>(&state.client, &key, "models").await?;
    let languages = external_list::<LanguageInfo>(
        &state.client,
        &key,
        "gettranslatorlanguagelist?internationalCode=zh-CN",
    )
    .await?;
    let account = external_data::<AccountInfo>(&state.client, &key, "getapiuserinfo").await?;
    Ok(Metadata {
        models,
        languages,
        account,
    })
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
