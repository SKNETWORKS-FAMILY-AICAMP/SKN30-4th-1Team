use base64::{engine::general_purpose, Engine as _};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use std::io::Read;
use std::path::{Path, PathBuf};
use tauri::Manager;
#[cfg(target_os = "macos")]
use tauri::{
    menu::{Menu, MenuItemBuilder, PredefinedMenuItem},
    AppHandle, Emitter,
};

const MAX_PREVIEW_BYTES: u64 = 5 * 1024 * 1024;
const MAX_TEXT_PREVIEW_BYTES: u64 = 512 * 1024;
const GITHUB_DEVICE_CODE_URL: &str = "https://github.com/login/device/code";
const GITHUB_ACCESS_TOKEN_URL: &str = "https://github.com/login/oauth/access_token";
#[cfg(target_os = "macos")]
const SETTINGS_MENU_ID: &str = "paim-settings";
#[cfg(target_os = "macos")]
const OPEN_SETTINGS_EVENT: &str = "paim://open-settings";

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
struct GithubDeviceCodeResponse {
    device_code: Option<String>,
    user_code: Option<String>,
    verification_uri: Option<String>,
    expires_in: Option<u64>,
    interval: Option<u64>,
    error: Option<String>,
    error_description: Option<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
struct GithubAccessTokenResponse {
    access_token: Option<String>,
    token_type: Option<String>,
    scope: Option<String>,
    error: Option<String>,
    error_description: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DirectoryChildEntry {
    name: String,
    path: String,
    kind: String,
}

// 선택한 폴더의 바로 아래 항목만 읽어 큰 repo에서도 트리를 지연 로딩한다.
#[tauri::command]
fn read_directory_children(path: String) -> Result<Vec<DirectoryChildEntry>, String> {
    let directory = PathBuf::from(path);

    if !directory.is_dir() {
        return Err("폴더 경로가 아닙니다".to_string());
    }

    let mut entries = std::fs::read_dir(&directory)
        .map_err(|_| "폴더를 읽을 수 없습니다".to_string())?
        .filter_map(|entry| entry.ok())
        .filter_map(|entry| {
            let path = entry.path();
            let metadata = entry.metadata().ok()?;
            let name = path.file_name()?.to_string_lossy().into_owned();
            let kind = if metadata.is_dir() {
                "directory"
            } else {
                "file"
            };

            Some(DirectoryChildEntry {
                name,
                path: path.to_string_lossy().into_owned(),
                kind: kind.to_string(),
            })
        })
        .collect::<Vec<_>>();

    entries.sort_by(|left, right| {
        let left_dir = left.kind == "directory";
        let right_dir = right.kind == "directory";

        right_dir
            .cmp(&left_dir)
            .then_with(|| left.name.to_lowercase().cmp(&right.name.to_lowercase()))
    });

    Ok(entries)
}

#[tauri::command]
fn path_kind(path: String) -> Result<String, String> {
    let meta = std::fs::metadata(&path).map_err(|e| e.to_string())?;

    Ok(if meta.is_dir() { "directory" } else { "file" }.to_string())
}

// 선택한 텍스트 파일의 본문만 읽어 파일 패널 프리뷰에 보여준다.
#[tauri::command]
fn read_text_file(path: String) -> Result<String, String> {
    let file = PathBuf::from(path);

    if !file.is_file() {
        return Err("파일 경로가 아닙니다".to_string());
    }

    let metadata = std::fs::metadata(&file).map_err(|_| "파일을 읽을 수 없습니다".to_string())?;
    if metadata.len() > MAX_TEXT_PREVIEW_BYTES {
        return Err("큰 파일은 미리볼 수 없습니다".to_string());
    }

    std::fs::read_to_string(&file).map_err(|_| "텍스트 파일만 미리볼 수 있습니다".to_string())
}

// 선택한 문서를 multipart 업로드할 수 있도록 base64 문자열로 읽는다.
#[tauri::command]
fn read_file_base64(path: String, max_bytes: Option<u64>) -> Result<String, String> {
    let file = PathBuf::from(path);

    if !file.is_file() {
        return Err("파일 경로가 아닙니다".to_string());
    }

    let metadata = std::fs::metadata(&file).map_err(|_| "파일을 읽을 수 없습니다".to_string())?;
    if max_bytes.is_some_and(|limit| metadata.len() > limit) {
        return Err("FILE_TOO_LARGE".to_string());
    }

    let bytes = if let Some(limit) = max_bytes {
        let source = std::fs::File::open(&file)
            .map_err(|_| "파일을 읽을 수 없습니다".to_string())?;
        let mut bytes = Vec::new();
        source
            .take(limit.saturating_add(1))
            .read_to_end(&mut bytes)
            .map_err(|_| "파일을 읽을 수 없습니다".to_string())?;
        if bytes.len() as u64 > limit {
            return Err("FILE_TOO_LARGE".to_string());
        }
        bytes
    } else {
        std::fs::read(&file).map_err(|_| "파일을 읽을 수 없습니다".to_string())?
    };

    Ok(general_purpose::STANDARD.encode(bytes))
}

// 로컬 이미지 파일을 프론트 미리보기용 data URL로 변환한다.
#[tauri::command]
fn create_attachment_preview(path: String) -> Result<Option<String>, String> {
    let Some(mime_type) = image_mime_type(&path) else {
        return Ok(None);
    };
    let metadata =
        std::fs::metadata(&path).map_err(|_| "이미지 파일을 읽을 수 없습니다".to_string())?;

    if metadata.len() > MAX_PREVIEW_BYTES {
        return Ok(None);
    }

    let bytes = std::fs::read(&path).map_err(|_| "이미지 파일을 읽을 수 없습니다".to_string())?;
    let encoded = general_purpose::STANDARD.encode(bytes);

    Ok(Some(format!("data:{mime_type};base64,{encoded}")))
}

// GitHub OAuth device flow 시작은 브라우저 CORS를 피하려고 Tauri에서 호출한다.
#[tauri::command]
fn github_oauth_device_code(
    client_id: String,
    scope: String,
) -> Result<GithubDeviceCodeResponse, String> {
    post_github_oauth_form(
        GITHUB_DEVICE_CODE_URL,
        &[("client_id", client_id.as_str()), ("scope", scope.as_str())],
    )
}

// 사용자가 브라우저 인증을 끝냈는지 확인하고 access token을 받는다.
#[tauri::command]
fn github_oauth_access_token(
    client_id: String,
    device_code: String,
) -> Result<GithubAccessTokenResponse, String> {
    post_github_oauth_form(
        GITHUB_ACCESS_TOKEN_URL,
        &[
            ("client_id", client_id.as_str()),
            ("device_code", device_code.as_str()),
            ("grant_type", "urn:ietf:params:oauth:grant-type:device_code"),
        ],
    )
}

fn post_github_oauth_form<T: DeserializeOwned>(
    url: &str,
    form: &[(&str, &str)],
) -> Result<T, String> {
    let response = match ureq::post(url)
        .set("Accept", "application/json")
        .send_form(form)
    {
        Ok(response) => response,
        Err(ureq::Error::Status(_, response)) => response,
        Err(error) => return Err(error.to_string()),
    };

    response.into_json().map_err(|error| error.to_string())
}

// 확장자를 기준으로 미리보기 가능한 이미지 MIME 타입을 반환한다.
fn image_mime_type(path: &str) -> Option<&'static str> {
    match Path::new(path)
        .extension()
        .and_then(|extension| extension.to_str())
        .map(|extension| extension.to_ascii_lowercase())
        .as_deref()
    {
        Some("avif") => Some("image/avif"),
        Some("gif") => Some("image/gif"),
        Some("jpeg") | Some("jpg") => Some("image/jpeg"),
        Some("png") => Some("image/png"),
        Some("webp") => Some("image/webp"),
        _ => None,
    }
}

#[cfg(target_os = "macos")]
fn build_macos_menu<R: tauri::Runtime>(app: &AppHandle<R>) -> tauri::Result<Menu<R>> {
    let menu = Menu::default(app)?;
    let items = menu.items()?;

    if let Some(app_menu) = items.first().and_then(|item| item.as_submenu()) {
        let settings_item = MenuItemBuilder::with_id(SETTINGS_MENU_ID, "Settings…")
            .accelerator("CmdOrCtrl+,")
            .build(app)?;
        let settings_separator = PredefinedMenuItem::separator(app)?;

        // macOS 표준 순서: About · separator · Settings… · separator · Services.
        app_menu.insert_items(&[&settings_item, &settings_separator], 2)?;
    }

    Ok(menu)
}

// PaiM 데스크톱 앱의 Tauri 런타임을 시작한다.
pub fn run() {
    let builder = tauri::Builder::default();
    #[cfg(target_os = "macos")]
    let builder = builder.menu(build_macos_menu).on_menu_event(|app, event| {
        if event.id() != SETTINGS_MENU_ID {
            return;
        }

        if let Some(window) = app.get_webview_window("main") {
            let _ = window.show();
            let _ = window.set_focus();
            let _ = window.emit(OPEN_SETTINGS_EVENT, ());
        }
    });

    builder
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                window.show().expect("main window should be visible");
            }

            Ok(())
        })
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            read_directory_children,
            path_kind,
            read_text_file,
            read_file_base64,
            create_attachment_preview,
            github_oauth_device_code,
            github_oauth_access_token
        ])
        .run(tauri::generate_context!())
        .expect("failed to run PaiM desktop application");
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    // 테스트끼리 파일명이 겹치지 않도록 현재 시간 기반 임시 경로를 만든다.
    fn temp_path(file_name: &str) -> std::path::PathBuf {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time should be after unix epoch")
            .as_nanos();

        std::env::temp_dir().join(format!("paim-{suffix}-{file_name}"))
    }

    #[test]
    fn image_mime_type_accepts_supported_extensions() {
        assert_eq!(image_mime_type("mock.PNG"), Some("image/png"));
        assert_eq!(image_mime_type("mock.jpeg"), Some("image/jpeg"));
        assert_eq!(image_mime_type("mock.webp"), Some("image/webp"));
    }

    #[test]
    fn image_mime_type_rejects_non_images() {
        assert_eq!(image_mime_type("mock.txt"), None);
        assert_eq!(image_mime_type("mock"), None);
    }

    #[test]
    fn create_attachment_preview_returns_data_url_for_small_png() {
        let path = temp_path("preview.png");
        let png_bytes = [
            0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, b'I', b'H',
            b'D', b'R', 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00,
            0x00, 0x1f, 0x15, 0xc4, 0x89,
        ];

        fs::write(&path, png_bytes).expect("test png should be writable");
        let preview = create_attachment_preview(path.to_string_lossy().into_owned())
            .expect("preview command should succeed");
        fs::remove_file(path).expect("test png should be removable");

        let preview = preview.expect("small png should create a preview");
        assert!(preview.starts_with("data:image/png;base64,"));
    }

    #[test]
    fn create_attachment_preview_ignores_non_image_files() {
        let path = temp_path("preview.txt");

        fs::write(&path, "not an image").expect("test file should be writable");
        let preview = create_attachment_preview(path.to_string_lossy().into_owned())
            .expect("non-image preview command should succeed");
        fs::remove_file(path).expect("test file should be removable");

        assert!(preview.is_none());
    }

    #[test]
    fn read_directory_children_sorts_directories_first() {
        let root = temp_path("tree");
        let src = root.join("src");
        let app = root.join("App.tsx");

        fs::create_dir_all(&src).expect("test directory should be writable");
        fs::write(&app, "export {}").expect("test file should be writable");

        let entries = read_directory_children(root.to_string_lossy().into_owned())
            .expect("directory children should be readable");

        fs::remove_file(app).expect("test file should be removable");
        fs::remove_dir(src).expect("test child directory should be removable");
        fs::remove_dir(root).expect("test root directory should be removable");

        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].name, "src");
        assert_eq!(entries[0].kind, "directory");
        assert_eq!(entries[1].name, "App.tsx");
        assert_eq!(entries[1].kind, "file");
    }

    #[test]
    fn path_kind_returns_file() {
        let path = temp_path("kind-file.txt");

        fs::write(&path, "file").expect("test file should be writable");
        let kind =
            path_kind(path.to_string_lossy().into_owned()).expect("file kind should be readable");
        fs::remove_file(path).expect("test file should be removable");

        assert_eq!(kind, "file");
    }

    #[test]
    fn path_kind_returns_directory() {
        let path = temp_path("kind-dir");

        fs::create_dir(&path).expect("test directory should be writable");
        let kind = path_kind(path.to_string_lossy().into_owned())
            .expect("directory kind should be readable");
        fs::remove_dir(path).expect("test directory should be removable");

        assert_eq!(kind, "directory");
    }

    #[test]
    fn path_kind_rejects_missing_path() {
        let path = temp_path("missing");

        assert!(path_kind(path.to_string_lossy().into_owned()).is_err());
    }

    #[test]
    fn read_text_file_returns_utf8_content() {
        let path = temp_path("preview.txt");

        fs::write(&path, "line 1\nline 2").expect("test file should be writable");
        let content = read_text_file(path.to_string_lossy().into_owned())
            .expect("text file should be readable");
        fs::remove_file(path).expect("test file should be removable");

        assert_eq!(content, "line 1\nline 2");
    }

    #[test]
    fn read_file_base64_returns_file_bytes() {
        let path = temp_path("upload.md");

        fs::write(&path, "# upload").expect("test file should be writable");
        let encoded = read_file_base64(path.to_string_lossy().into_owned(), None)
            .expect("file bytes should be readable");
        fs::remove_file(path).expect("test file should be removable");

        assert_eq!(encoded, "IyB1cGxvYWQ=");
    }

    #[test]
    fn read_file_base64_rejects_file_over_limit() {
        let path = temp_path("oversized-upload.bin");

        fs::write(&path, b"12345").expect("test file should be writable");
        let error = read_file_base64(path.to_string_lossy().into_owned(), Some(4))
            .expect_err("oversized file should be rejected before reading");
        fs::remove_file(path).expect("test file should be removable");

        assert_eq!(error, "FILE_TOO_LARGE");
    }
}
