from __future__ import annotations

import asyncio
import json
import logging
import os
import posixpath
import random
import re
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, AsyncIterator, Callable, Iterable
from urllib.parse import quote, unquote, urljoin, urlsplit

import httpx
import srt
import chardet
from dotenv import dotenv_values, set_key, unset_key
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from guessit import guessit
from openai import OpenAI
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = Path.home() / "Library" / "Application Support" / "Subtitle Maker"
CONFIG_PATH = CONFIG_DIR / "config.json"
ENV_PATH = BASE_DIR / ".env"
TARGET_LANGUAGES = {
    "zh-cn": ("Simplified Chinese", "zh-Hans"),
    "zh-tw": ("Traditional Chinese", "zh-Hant"),
    "es": ("Spanish", "es"),
    "fr": ("French", "fr"),
    "de": ("German", "de"),
    "ja": ("Japanese", "ja"),
    "ko": ("Korean", "ko"),
    "pt-br": ("Brazilian Portuguese", "pt-BR"),
    "it": ("Italian", "it"),
    "ru": ("Russian", "ru"),
    "ar": ("Arabic", "ar"),
    "hi": ("Hindi", "hi"),
    "tr": ("Turkish", "tr"),
    "pl": ("Polish", "pl"),
    "nl": ("Dutch", "nl"),
    "id": ("Indonesian", "id"),
    "vi": ("Vietnamese", "vi"),
    "th": ("Thai", "th"),
    "uk": ("Ukrainian", "uk"),
    "cs": ("Czech", "cs"),
}
SUBTITLE_MODES = {
    "target": "Target language only",
    "bilingual": "English & target language",
    "minimalistic": "Minimalistic",
}
SETTING_DEFAULTS = {
    "webdav_username": "",
    "webdav_endpoint": "",
    "webdav_scan_path": "",
    "opensubtitles_consumer_name": "subtitle-maker",
    "opensubtitles_username": "",
    "openai_base_url": "https://api.openai.com/v1",
    "openai_model_id": "gpt-5.6-luna",
    "openai_reasoning_effort": "low",
    "target_language": "zh-cn",
    "default_subtitle_mode": "bilingual",
    "minimal_frequency_tier": "2000",
}
SECRET_SETTINGS = ("webdav_password", "opensubtitles_api_key", "opensubtitles_password", "openai_api_key")
SECRET_ENV_NAMES = {key: key.upper() for key in SECRET_SETTINGS}
VIDEO_EXTENSIONS = {".avi", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".ts", ".webm"}
SUBTITLE_EXTENSIONS = {".ass", ".srt", ".ssa", ".vtt"}
HASH_BLOCK_SIZE = 64 * 1024
MAX_SUBTITLE_BYTES = 10 * 1024 * 1024
TERMINAL_STAGES = {"completed", "failed"}
DAV = "{DAV:}"
LOGGER = logging.getLogger("uvicorn.error")
FREQUENCY_PATH = BASE_DIR / "backend" / "frequency_data.json"
FREQUENCY_DATA: dict[str, Any] = {}
FREQUENCY_READY = threading.Event()
FREQUENCY_ERROR: str | None = None
WORD_PATTERN = re.compile(r"\*|[A-Za-z]+(?:['’][A-Za-z]+)*")


class PipelineError(RuntimeError):
    pass


def phrase_pattern(value: str, lemmas: dict[str, str]) -> tuple[str, ...]:
    value = re.sub(r"\([^)]*\)", "", value.replace("*self", "*"))
    value = re.sub(r"([A-Za-z’']+)/[A-Za-z’']+", r"\1", value)
    return tuple("*" if token == "*" else lemmas.get(token.casefold(), token.casefold()) for token in WORD_PATTERN.findall(value))


def load_frequency_data(path: Path = FREQUENCY_PATH) -> None:
    global FREQUENCY_DATA, FREQUENCY_ERROR
    FREQUENCY_READY.clear()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        words, lemmas, phrases = payload["words"], payload["lemmas"], payload["phrases"]
        if payload.get("_meta", {}).get("ngsl_headwords") != 2809 or len(phrases) < 500:
            raise ValueError("frequency data was incomplete")
        patterns: dict[tuple[str, ...], int] = {}
        for phrase, rank in phrases.items():
            pattern = phrase_pattern(phrase, lemmas)
            if len(pattern) > 1:
                patterns[pattern] = max(patterns.get(pattern, 0), int(rank))
        FREQUENCY_DATA = {"words": words, "lemmas": lemmas, "phrases": patterns}
        FREQUENCY_ERROR = None
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        FREQUENCY_DATA = {}
        FREQUENCY_ERROR = str(exc)
    finally:
        FREQUENCY_READY.set()


def frequency_data() -> dict[str, Any]:
    if not FREQUENCY_READY.wait(timeout=30):
        raise PipelineError("Minimalistic frequency data is still loading")
    if FREQUENCY_ERROR:
        raise PipelineError("Could not load Minimalistic frequency data")
    return FREQUENCY_DATA


def load_saved_settings() -> dict[str, str]:
    try:
        stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError("Could not read saved settings") from exc
    if not isinstance(stored, dict):
        raise PipelineError("Saved settings must be a JSON object")
    return SETTING_DEFAULTS | {key: str(value) for key, value in stored.items() if key in SETTING_DEFAULTS}


def load_saved_secrets() -> dict[str, str]:
    try:
        stored = dotenv_values(ENV_PATH, interpolate=False)
        return {key: value for key, name in SECRET_ENV_NAMES.items() if (value := stored.get(name))}
    except (OSError, UnicodeError) as exc:
        raise PipelineError("Could not read secrets from .env") from exc


@dataclass(frozen=True)
class Config:
    webdav_username: str
    webdav_password: str
    webdav_endpoint: str
    webdav_scan_path: str
    opensubtitles_api_key: str
    opensubtitles_consumer_name: str
    openai_base_url: str
    openai_api_key: str
    openai_model_id: str
    openai_reasoning_effort: str
    target_language: str
    default_subtitle_mode: str
    minimal_frequency_tier: int = 2000
    opensubtitles_username: str | None = None
    opensubtitles_password: str | None = None

    @classmethod
    def load(cls) -> "Config":
        return cls.from_settings(load_saved_settings(), load_saved_secrets())

    @classmethod
    def from_settings(cls, values: dict[str, str], secrets: dict[str, str]) -> "Config":
        required = (
            "webdav_username",
            "webdav_endpoint",
            "webdav_scan_path",
            "opensubtitles_consumer_name",
            "openai_base_url",
            "openai_model_id",
            "openai_reasoning_effort",
            "target_language",
            "default_subtitle_mode",
        )
        missing = [name for name in required if not values.get(name)]
        missing.extend(name for name in ("webdav_password", "opensubtitles_api_key", "openai_api_key") if not secrets.get(name))
        if missing:
            raise PipelineError("Missing settings: " + ", ".join(sorted(set(missing))))

        endpoint = values["webdav_endpoint"].strip()
        if "://" not in endpoint:
            endpoint = "https://" + endpoint
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
            raise PipelineError("WEBDAV_ENDPOINT must be an HTTP(S) host or base URL")

        effort = values["openai_reasoning_effort"].strip().lower()
        if effort not in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}:
            raise PipelineError("OpenAI reasoning effort is invalid")
        target_language = values["target_language"].strip().lower()
        if target_language not in TARGET_LANGUAGES:
            raise PipelineError("Target language is invalid")
        subtitle_mode = values["default_subtitle_mode"].strip().lower()
        if subtitle_mode not in SUBTITLE_MODES:
            raise PipelineError("Default subtitle mode is invalid")
        try:
            minimal_frequency_tier = int(values["minimal_frequency_tier"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PipelineError("Minimalistic frequency tier is invalid") from exc
        if minimal_frequency_tier not in {1000, 2000, 3000, 4000, 5000}:
            raise PipelineError("Minimalistic frequency tier is invalid")

        return cls(
            webdav_username=values["webdav_username"],
            webdav_password=secrets["webdav_password"],
            webdav_endpoint=endpoint.rstrip("/") + "/",
            webdav_scan_path=values["webdav_scan_path"],
            opensubtitles_api_key=secrets["opensubtitles_api_key"],
            opensubtitles_consumer_name=values["opensubtitles_consumer_name"],
            openai_base_url=values["openai_base_url"].rstrip("/") + "/",
            openai_api_key=secrets["openai_api_key"],
            openai_model_id=values["openai_model_id"],
            openai_reasoning_effort=effort,
            target_language=target_language,
            default_subtitle_mode=subtitle_mode,
            minimal_frequency_tier=minimal_frequency_tier,
            opensubtitles_username=values.get("opensubtitles_username") or None,
            opensubtitles_password=secrets.get("opensubtitles_password") or None,
        )


@dataclass(frozen=True)
class FileEntry:
    name: str
    path: str
    type: str
    size: int | None = None
    modified: str | None = None


@dataclass(frozen=True)
class SubtitleCandidate:
    file_id: int
    language: str
    release: str
    moviehash_match: bool


@dataclass
class JobItem:
    path: str
    status: str = "queued"
    message: str = "Waiting to start"
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None


@dataclass
class Job:
    id: str
    items: list[JobItem]
    target_language: str = "zh-cn"
    subtitle_mode: str = "bilingual"
    status: str = "queued"
    message: str = "Waiting to start"
    error: str | None = None
    created_at: float = field(default_factory=time.time)


class JobRequest(BaseModel):
    paths: list[str]
    mode: str | None = None


class SettingsRequest(BaseModel):
    values: dict[str, str]
    secrets: dict[str, str] = Field(default_factory=dict)
    clear_secrets: list[str] = Field(default_factory=list)


def normalize_relative(path: str) -> str:
    path = unquote(path or "").replace("\\", "/")
    if "\x00" in path or path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise PipelineError("Path must be relative to WEBDAV_SCAN_PATH")
    parts = [part for part in path.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        raise PipelineError("Path traversal is not allowed")
    return "/".join(parts)


def calculate_moviehash(size: int, first: bytes, last: bytes) -> str:
    if size < HASH_BLOCK_SIZE * 2 or len(first) != HASH_BLOCK_SIZE or len(last) != HASH_BLOCK_SIZE:
        raise PipelineError("Video is too small or ranged reads were incomplete")
    value = size
    for block in (first, last):
        value += sum(struct.unpack(f"<{HASH_BLOCK_SIZE // 8}Q", block))
    return f"{value & 0xFFFFFFFFFFFFFFFF:016x}"


def normalized_title(value: str) -> str:
    return re.sub(r"[^\w]+", "", value.casefold(), flags=re.UNICODE)


def normalize_release_filename(filename: str) -> str:
    match = re.fullmatch(r"\[[^]]+\]\[([^]]+)\]\[(\d+)\](?:\[[^]]+\])*(\.[^.]+)", filename)
    return f"{match.group(1)} {match.group(2)}{match.group(3)}" if match else filename


def language_output_path(
    video_path: str,
    target_language: str,
    exists: Callable[[str], bool],
    subtitle_mode: str = "target",
) -> str:
    video = PurePosixPath(normalize_relative(video_path))
    parent = "" if str(video.parent) == "." else str(video.parent)
    tag = TARGET_LANGUAGES[target_language][1]
    name = f"{video.stem}.minimal.{tag}.ass" if subtitle_mode == "minimalistic" else f"{video.stem}.{tag}.srt"
    path = f"{parent}/{name}" if parent else name
    if exists(path):
        if subtitle_mode == "minimalistic":
            raise PipelineError("The Minimalistic subtitle file already exists")
        raise PipelineError(f"The {TARGET_LANGUAGES[target_language][0]} subtitle file already exists")
    return path


def choose_output_path(
    video_path: str,
    target_language: str,
    exists: Callable[[str], bool],
    subtitle_mode: str = "target",
) -> str:
    video = PurePosixPath(normalize_relative(video_path))
    parent = "" if str(video.parent) == "." else str(video.parent)
    tag = TARGET_LANGUAGES[target_language][1]
    names = [f"{video.stem}.minimal.{tag}.ass"] if subtitle_mode == "minimalistic" else [
        f"{video.stem}.srt",
        f"{video.stem}.{tag}.srt",
    ]
    for name in names:
        path = f"{parent}/{name}" if parent else name
        if not exists(path):
            return path
    if subtitle_mode == "minimalistic":
        raise PipelineError("The Minimalistic subtitle file already exists")
    raise PipelineError(f"Both default and {TARGET_LANGUAGES[target_language][0]} subtitle files already exist")


def detect_sidecar_language(video_name: str, subtitle_name: str, data: bytes) -> str | None:
    video_stem = PurePosixPath(video_name).stem
    subtitle_stem = PurePosixPath(subtitle_name).stem
    extra = subtitle_stem[len(video_stem) :] if subtitle_stem.casefold().startswith(video_stem.casefold()) else ""
    markers = "." + re.sub(r"[^a-z0-9]+", ".", extra.casefold()).strip(".") + "."
    aliases = {
        "zh-tw": ("zh-tw", "zh-hant", "cht", "traditional-chinese"),
        "zh-cn": ("zh-cn", "zh-hans", "zh", "zho", "chi", "chs", "cn", "chinese", "simplified-chinese"),
        "en": ("en", "eng", "english"),
    }
    for code, (name, tag) in TARGET_LANGUAGES.items():
        aliases.setdefault(code, (code, tag, name))
    for code, names in aliases.items():
        if any(f".{re.sub(r'[^a-z0-9]+', '.', name.casefold()).strip('.')}." in markers for name in names):
            return code

    encoding = chardet.detect(data).get("encoding") or "utf-8"
    text = data.decode(encoding, errors="ignore")
    han = len(re.findall(r"[\u3400-\u9fff]", text))
    kana = len(re.findall(r"[\u3040-\u30ff]", text))
    hangul = len(re.findall(r"[\uac00-\ud7af]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if han >= 3 and kana == 0 and hangul == 0:
        return "zh-cn"
    if latin >= 10:
        return "en"
    return None


def batch_cues(cues: list[tuple[int, srt.Subtitle]]) -> list[list[tuple[int, srt.Subtitle]]]:
    batches: list[list[tuple[int, srt.Subtitle]]] = []
    current: list[tuple[int, srt.Subtitle]] = []
    chars = 0
    for item in cues:
        length = len(item[1].content)
        if current and (len(current) >= 200 or chars + length > 24_000):
            batches.append(current)
            current, chars = [], 0
        current.append(item)
        chars += length
    if current:
        batches.append(current)
    return batches


class WebDAV:
    def __init__(
        self,
        config: Config,
        client: httpx.Client | None = None,
        media_client: httpx.Client | None = None,
    ):
        self.config = config
        scan = quote(config.webdav_scan_path.strip("/"), safe="/")
        self.root_url = urljoin(config.webdav_endpoint, scan).rstrip("/") + "/"
        self.root = urlsplit(self.root_url)
        self.root_path = unquote(self.root.path).rstrip("/")
        self.client = client or httpx.Client(
            auth=(config.webdav_username, config.webdav_password),
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=False,
        )
        self.media_client = media_client or httpx.Client(
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=False,
        )

    def url_for(self, relative: str, directory: bool = False) -> str:
        relative = normalize_relative(relative)
        encoded = "/".join(quote(part, safe="") for part in relative.split("/") if part)
        url = self.root_url + encoded
        return url.rstrip("/") + "/" if directory else url

    def _safe_target(self, value: str, base: str | None = None) -> str:
        target = urlsplit(urljoin(base or self.root_url, value))
        target_path = unquote(target.path).rstrip("/")
        if (target.scheme, target.netloc) != (self.root.scheme, self.root.netloc):
            raise PipelineError("WebDAV redirected outside the configured server")
        if target_path != self.root_path and not target_path.startswith(self.root_path + "/"):
            raise PipelineError("WebDAV path escaped WEBDAV_SCAN_PATH")
        return target.geturl()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self.client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise PipelineError("WebDAV request failed") from exc
        if response.status_code in {301, 302, 307, 308}:
            location = response.headers.get("location")
            if not location:
                raise PipelineError("WebDAV returned an invalid redirect")
            try:
                response = self.client.request(method, self._safe_target(location, url), **kwargs)
            except httpx.HTTPError as exc:
                raise PipelineError("WebDAV redirect failed") from exc
        return response

    def _relative_href(self, href: str) -> str | None:
        try:
            target = urlsplit(self._safe_target(href))
        except PipelineError:
            return None
        path = unquote(target.path).rstrip("/")
        relative = path[len(self.root_path) :].strip("/")
        return normalize_relative(relative)

    def _parse_entries(self, content: bytes) -> list[FileEntry]:
        try:
            document = ET.fromstring(content)
        except ET.ParseError as exc:
            raise PipelineError("WebDAV returned invalid XML") from exc
        entries: list[FileEntry] = []
        for response in document.findall(f".//{DAV}response"):
            href = response.findtext(f"{DAV}href")
            if not href:
                continue
            relative = self._relative_href(href)
            if relative is None:
                continue
            prop = response.find(f".//{DAV}prop")
            if prop is None:
                continue
            is_dir = prop.find(f"{DAV}resourcetype/{DAV}collection") is not None
            length = prop.findtext(f"{DAV}getcontentlength")
            entries.append(
                FileEntry(
                    name=PurePosixPath(relative).name if relative else PurePosixPath(self.root_path).name,
                    path=relative,
                    type="directory" if is_dir else "video" if PurePosixPath(relative).suffix.lower() in VIDEO_EXTENSIONS else "file",
                    size=int(length) if length and length.isdigit() else None,
                    modified=prop.findtext(f"{DAV}getlastmodified"),
                )
            )
        return entries

    def _propfind(self, relative: str, depth: int, directory: bool = False) -> list[FileEntry]:
        url = self.url_for(relative, directory=directory)
        body = b'<?xml version="1.0"?><propfind xmlns="DAV:"><prop><resourcetype/><getcontentlength/><getlastmodified/></prop></propfind>'
        response = self._request(
            "PROPFIND",
            url,
            headers={"Depth": str(depth), "Content-Type": "application/xml"},
            content=body,
        )
        if response.status_code != 207:
            raise PipelineError(f"WebDAV listing failed ({response.status_code})")
        if len(response.content) > 5 * 1024 * 1024:
            raise PipelineError("WebDAV directory response is too large")
        return self._parse_entries(response.content)

    def list(self, relative: str) -> list[FileEntry]:
        relative = normalize_relative(relative)
        entries = [entry for entry in self._propfind(relative, 1, directory=True) if entry.path != relative]
        entries = [entry for entry in entries if entry.type in {"directory", "video"}]
        return sorted(entries, key=lambda entry: (entry.type != "directory", entry.name.casefold()))

    def sidecars(self, video_path: str) -> list[FileEntry]:
        video = PurePosixPath(normalize_relative(video_path))
        parent = "" if str(video.parent) == "." else str(video.parent)
        prefix = video.stem.casefold()
        matches = []
        for entry in self._propfind(parent, 1, directory=True):
            candidate = PurePosixPath(entry.name)
            candidate_stem = candidate.stem.casefold()
            if (
                entry.type == "file"
                and candidate.suffix.casefold() in SUBTITLE_EXTENSIONS
                and (
                    candidate_stem == prefix
                    or any(candidate_stem.startswith(prefix + separator) for separator in (".", "-", "_"))
                )
            ):
                matches.append(entry)
        return sorted(matches, key=lambda entry: (PurePosixPath(entry.name).suffix.casefold() != ".srt", entry.name.casefold()))

    def file_info(self, relative: str) -> FileEntry:
        relative = normalize_relative(relative)
        entries = self._propfind(relative, 0)
        entry = next((item for item in entries if item.path == relative), None)
        if not entry or entry.type != "video" or not entry.size:
            raise PipelineError("Selected path is not a supported video")
        return entry

    def exists(self, relative: str) -> bool:
        response = self._request(
            "PROPFIND",
            self.url_for(relative),
            headers={"Depth": "0", "Content-Type": "application/xml"},
            content=b'<?xml version="1.0"?><propfind xmlns="DAV:"><prop><resourcetype/></prop></propfind>',
        )
        if response.status_code == 207:
            return True
        if response.status_code == 404:
            return False
        raise PipelineError(f"WebDAV could not check the output path ({response.status_code})")

    def _open_media(self, relative: str, headers: dict[str, str]) -> httpx.Response:
        url = self.url_for(relative)
        try:
            request = self.client.build_request("GET", url, headers=headers)
            response = self.client.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise PipelineError("WebDAV media request failed") from exc
        if response.status_code in {301, 302, 307, 308}:
            location = response.headers.get("location")
            response.close()
            target = urlsplit(urljoin(url, location or ""))
            if target.scheme != "https" or not target.netloc or not location:
                raise PipelineError("WebDAV returned an unsafe media redirect")
            try:
                # The CDN request deliberately uses a client with no WebDAV auth.
                request = self.media_client.build_request("GET", target.geturl(), headers=headers)
                response = self.media_client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise PipelineError("WebDAV media redirect failed") from exc
            if response.status_code in {301, 302, 307, 308}:
                response.close()
                raise PipelineError("WebDAV media redirected more than once")
        return response

    def read_range(self, relative: str, start: int, end: int) -> bytes:
        response = self._open_media(relative, {"Range": f"bytes={start}-{end}"})
        try:
            if response.status_code != 206:
                raise PipelineError("WebDAV server does not support required byte ranges")
            expected = end - start + 1
            data = b"".join(response.iter_bytes())
            if len(data) != expected:
                raise PipelineError("WebDAV returned an incomplete byte range")
            return data
        finally:
            response.close()

    def moviehash(self, relative: str, size: int) -> str:
        first = self.read_range(relative, 0, HASH_BLOCK_SIZE - 1)
        last = self.read_range(relative, size - HASH_BLOCK_SIZE, size - 1)
        return calculate_moviehash(size, first, last)

    def stream(self, relative: str, range_header: str | None) -> httpx.Response:
        headers = {"Range": range_header} if range_header else {}
        response = self._open_media(relative, headers)
        if range_header and response.status_code != 206:
            response.close()
            raise PipelineError("WebDAV ignored a media range request")
        if response.status_code not in {200, 206}:
            response.close()
            raise PipelineError(f"WebDAV media request failed ({response.status_code})")
        return response

    def read_small(self, relative: str, limit: int = MAX_SUBTITLE_BYTES) -> bytes:
        response = self._open_media(relative, {})
        try:
            if response.status_code != 200:
                raise PipelineError(f"WebDAV subtitle read failed ({response.status_code})")
            if int(response.headers.get("content-length", "0") or 0) > limit:
                raise PipelineError("Existing subtitle is unexpectedly large")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise PipelineError("Existing subtitle is unexpectedly large")
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            response.close()

    def put(self, relative: str, data: bytes) -> None:
        response = self._request(
            "PUT",
            self.url_for(relative),
            headers={"Content-Type": "application/x-subrip; charset=utf-8", "If-None-Match": "*"},
            content=data,
        )
        if response.status_code == 412:
            raise PipelineError("The output subtitle appeared before upload; nothing was overwritten")
        if response.status_code not in {200, 201, 204}:
            raise PipelineError(f"WebDAV upload failed ({response.status_code})")


class OpenSubtitles:
    def __init__(self, config: Config, client: httpx.Client | None = None):
        self.username = config.opensubtitles_username
        self.password = config.opensubtitles_password
        self.client = client or httpx.Client(
            base_url="https://api.opensubtitles.com/api/v1/",
            headers={
                "Api-Key": config.opensubtitles_api_key,
                "User-Agent": f"{config.opensubtitles_consumer_name} v0.1",
                "Accept": "application/json",
            },
            timeout=30,
            follow_redirects=True,
        )

    @staticmethod
    def _retry_delay(response: httpx.Response | None, attempt: int, operation: str) -> float:
        if response is not None:
            header = response.headers.get("retry-after") or response.headers.get("ratelimit-reset")
            if header:
                try:
                    delay = float(header)
                    if response.headers.get("retry-after") is None and delay > time.time():
                        delay -= time.time()
                except ValueError:
                    try:
                        from email.utils import parsedate_to_datetime

                        delay = parsedate_to_datetime(header).timestamp() - time.time()
                    except (TypeError, ValueError):
                        delay = 0
                if delay > 60:
                    raise PipelineError(f"{operation} was rate limited; try again later")
                return max(0, delay)
        return 2**attempt + random.uniform(0, 0.25)

    def _request(self, method: str, url: str, operation: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(3):
            response: httpx.Response | None = None
            try:
                response = self.client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise PipelineError(f"{operation} could not connect") from exc
            if response is not None and response.status_code not in {429, 500, 502, 503, 504}:
                return response
            if attempt == 2:
                assert response is not None
                return response
            delay = self._retry_delay(response, attempt, operation)
            if response is not None:
                response.close()
            time.sleep(delay)
        raise AssertionError("unreachable")

    def _login(self) -> None:
        if not self.username or not self.password:
            raise PipelineError(
                "OpenSubtitles requires a user token; add OPENSUBTITLE_USERNAME and OPENSUBTITLE_PASSWORD to .env"
            )
        response = self._request(
            "POST",
            "login",
            "OpenSubtitles login",
            json={"username": self.username, "password": self.password},
        )
        if response.status_code != 200 or not (token := response.json().get("token")):
            raise PipelineError("OpenSubtitles login failed; check the configured username and password")
        self.client.headers["Authorization"] = f"Bearer {token}"

    def _search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        response = self._request("GET", "subtitles", "OpenSubtitles search", params=params)
        if response.status_code != 200:
            try:
                payload = response.json()
                detail = payload.get("errors") or payload.get("message") if isinstance(payload, dict) else None
            except ValueError:
                detail = None
            if isinstance(detail, list):
                detail = ", ".join(map(str, detail))
            raise PipelineError(
                f"OpenSubtitles search failed ({response.status_code}){f': {detail}' if detail else ''}"
            )
        return response.json().get("data", [])

    @staticmethod
    def _candidate(item: dict[str, Any]) -> SubtitleCandidate | None:
        attrs = item.get("attributes", {})
        language = str(attrs.get("language", "")).lower()
        files = attrs.get("files") or []
        if (language != "en" and language not in TARGET_LANGUAGES) or attrs.get("nb_cd", 1) != 1 or not files:
            return None
        try:
            file_id = int(files[0]["file_id"])
        except (KeyError, TypeError, ValueError):
            return None
        return SubtitleCandidate(
            file_id=file_id,
            language=language,
            release=str(attrs.get("release") or files[0].get("file_name") or "Unknown release"),
            moviehash_match=bool(attrs.get("moviehash_match")),
        )

    @staticmethod
    def _metadata_match(item: dict[str, Any], guessed: dict[str, Any]) -> bool:
        details = item.get("attributes", {}).get("feature_details") or {}
        if not isinstance(details, dict):
            return False
        expected_title = normalized_title(str(guessed.get("title", "")))
        if not expected_title:
            return False
        if guessed.get("type") == "episode":
            if details.get("season_number") != guessed.get("season") or details.get("episode_number") != guessed.get("episode"):
                return False
            actual_title = normalized_title(str(details.get("parent_title", "")))
        else:
            if guessed.get("year") and details.get("year") != guessed.get("year"):
                return False
            actual_title = normalized_title(str(details.get("title") or details.get("movie_name") or ""))
        return bool(actual_title) and (expected_title == actual_title or expected_title in actual_title or actual_title in expected_title)

    @staticmethod
    def _prefer(items: Iterable[dict[str, Any]], languages: tuple[str, ...]) -> SubtitleCandidate | None:
        candidates = [candidate for item in items if (candidate := OpenSubtitles._candidate(item))]
        return next((candidate for language in languages for candidate in candidates if candidate.language == language), None)

    def find(self, filename: str, moviehash: str, languages: tuple[str, ...]) -> SubtitleCandidate:
        language_query = ",".join(languages)
        hash_results = self._search(
            {
                "languages": language_query,
                "moviehash": moviehash,
                "moviehash_match": "only",
                "query": filename.casefold(),
            }
        )
        candidate = self._prefer(
            (item for item in hash_results if item.get("attributes", {}).get("moviehash_match")), languages
        )
        if candidate:
            return candidate

        guessed = guessit(normalize_release_filename(filename))
        params: dict[str, Any] = {
            "languages": language_query,
            "query": str(guessed.get("title", "")).casefold(),
            "type": guessed.get("type", "movie"),
        }
        if guessed.get("type") != "episode" and guessed.get("year"):
            params["year"] = guessed["year"]
        if guessed.get("type") == "episode":
            params.update(season_number=guessed.get("season"), episode_number=guessed.get("episode"))
        fallback = self._search({key: value for key, value in params.items() if value is not None})
        candidate = self._prefer((item for item in fallback if self._metadata_match(item, guessed)), languages)
        if not candidate:
            raise PipelineError("No reliable requested subtitle was found")
        return candidate

    def download(self, candidate: SubtitleCandidate) -> tuple[bytes, dict[str, Any]]:
        if self.username and self.password and "Authorization" not in self.client.headers:
            self._login()
        response = self._request(
            "POST",
            "download",
            "OpenSubtitles download request",
            json={"file_id": candidate.file_id, "sub_format": "srt"},
        )
        if self.username and self.password and response.status_code in {401, 403, 406}:
            self._login()
            response = self._request(
                "POST",
                "download",
                "OpenSubtitles download request",
                json={"file_id": candidate.file_id, "sub_format": "srt"},
            )
        if response.status_code != 200:
            try:
                message = response.json().get("message")
            except (ValueError, AttributeError):
                message = None
            if message and "token" in message.casefold():
                raise PipelineError(
                    "OpenSubtitles requires a user token; add OPENSUBTITLE_USERNAME and OPENSUBTITLE_PASSWORD to .env"
                )
            raise PipelineError(message or f"OpenSubtitles download failed ({response.status_code})")
        payload = response.json()
        link = payload.get("link")
        if not link:
            raise PipelineError("OpenSubtitles did not return a download link")

        subtitle_response = self._request("GET", link, "Temporary subtitle download")
        if subtitle_response.status_code != 200:
            raise PipelineError("The temporary subtitle download failed")
        if len(subtitle_response.content) > MAX_SUBTITLE_BYTES:
            raise PipelineError("Downloaded subtitle is unexpectedly large")
        quota = {
            "remaining": payload.get("remaining"),
            "resetTimeUtc": payload.get("reset_time_utc"),
        }
        return subtitle_response.content, quota

    def remaining_downloads(self) -> int:
        if self.username and self.password and "Authorization" not in self.client.headers:
            self._login()
        response = self._request("GET", "infos/user", "OpenSubtitles user info")
        if response.status_code != 200:
            raise PipelineError(f"OpenSubtitles user info failed ({response.status_code})")
        remaining = response.json().get("data", {}).get("remaining_downloads")
        if not isinstance(remaining, int) or remaining < 0:
            raise PipelineError("OpenSubtitles returned an invalid download quota")
        return remaining


def translation_instructions(target_language: str) -> str:
    return (
        f"Translate every supplied English subtitle cue into natural {TARGET_LANGUAGES[target_language][0]}. "
        "Keep names, meaning, formatting tags, and intentional line breaks. Be concise. "
        "Return every id exactly once and output only the required JSON schema."
    )


def translation_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "subtitle_translations",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "translations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
                            "required": ["id", "text"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["translations"],
                "additionalProperties": False,
            },
        },
    }


def minimalistic_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "subtitle_glosses",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "translations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer"},
                                "glosses": {
                                    "type": "array",
                                    "maxItems": 3,
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "candidate": {"type": "integer"},
                                            "text": {"type": "string"},
                                        },
                                        "required": ["candidate", "text"],
                                        "additionalProperties": False,
                                    },
                                },
                            },
                            "required": ["id", "glosses"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["translations"],
                "additionalProperties": False,
            },
        },
    }


def minimalistic_instructions(target_language: str) -> str:
    return (
        f"For each English subtitle cue, choose up to three supplied candidates that most help comprehension and translate only those "
        f"into concise {TARGET_LANGUAGES[target_language][0]} glosses. Omit names, acronyms, and items that should not be translated. "
        "Keep each candidate id unchanged, return every cue id exactly once, and output only the required JSON schema."
    )


def plain_subtitle_text(value: str) -> str:
    value = re.sub(r"\{\\[^}]*\}", "", value)
    return " ".join(re.sub(r"<[^>]+>", "", value).replace("\\N", "\n").split())


def minimal_candidates(text: str, data: dict[str, Any], tier: int) -> tuple[str, list[dict[str, Any]]]:
    plain = plain_subtitle_text(text)
    matches = list(WORD_PATTERN.finditer(plain))
    lemmas = [data["lemmas"].get(match.group().casefold(), match.group().casefold()) for match in matches]
    candidates: list[dict[str, Any]] = []
    occupied: set[int] = set()
    # ponytail: 506 patterns are faster and simpler to scan than maintaining a phrase trie.
    for pattern, rank in sorted(data["phrases"].items(), key=lambda item: len(item[0]), reverse=True):
        if rank <= tier or len(pattern) > len(matches):
            continue
        for start in range(len(matches) - len(pattern) + 1):
            indexes = range(start, start + len(pattern))
            if occupied.intersection(indexes) or any(expected != "*" and expected != lemmas[index] for index, expected in zip(indexes, pattern)):
                continue
            candidates.append({
                "start": matches[start].start(),
                "end": matches[start + len(pattern) - 1].end(),
                "rank": rank,
                "kind": "phrase",
            })
            occupied.update(indexes)

    for index, match in enumerate(matches):
        word = match.group()
        rank = data["words"].get(word.casefold())
        if index in occupied or len(word.strip("'’")) < 2 or (rank is not None and rank <= tier):
            continue
        if word.isupper() or (word[0].isupper() and match.start() > 0 and plain[match.start() - 1] not in ".!?\n"):
            continue
        candidates.append({"start": match.start(), "end": match.end(), "rank": rank, "kind": "word"})

    candidates.sort(key=lambda item: item["start"])
    for candidate_id, candidate in enumerate(candidates):
        candidate["id"] = candidate_id
        candidate["text"] = plain[candidate["start"] : candidate["end"]]
    return plain, candidates


def ass_time(value: Any) -> str:
    centiseconds = max(0, int(value.total_seconds() * 100))
    minutes, seconds = divmod(centiseconds, 6000)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{seconds // 100:02}.{seconds % 100:02}"


def ass_text(value: str) -> str:
    return value.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def render_minimalistic_ass(subtitles: list[srt.Subtitle], glosses: dict[int, list[dict[str, Any]]]) -> str:
    output = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        "Style: English,Courier New,48,&H00FFFFFF,&H000000FF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2,1,5,20,20,40,1",
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    for cue_id, subtitle in enumerate(subtitles):
        plain = plain_subtitle_text(subtitle.content)
        if not plain:
            continue
        start, end = ass_time(subtitle.start), ass_time(subtitle.end)
        font_size = max(18, min(48, int(1840 / (len(plain) * 0.6))))
        x, y = round(960 - len(plain) * font_size * 0.3), 1010
        output.append(f"Dialogue: 0,{start},{end},English,,0,0,0,,{{\\an4\\pos({x},{y})\\fs{font_size}}}{ass_text(plain)}")
        for gloss in glosses.get(cue_id, []):
            translation = gloss["translation"]
            scale_x = max(1, round((gloss["end"] - gloss["start"]) * 60 / len(translation)))
            copied_line = (
                ass_text(plain[:gloss["start"]])
                + f"{{\\alpha&H00&\\1c&H00B8E7FF&\\fscx{scale_x}\\fscy58}}{ass_text(translation)}"
                + f"{{\\alpha&HFF&\\fscx100\\fscy100}}{ass_text(plain[gloss['end']:])}"
            )
            output.append(
                f"Dialogue: 1,{start},{end},English,,0,0,0,,{{\\an4\\pos({x},{y - font_size})\\fs{font_size}\\alpha&HFF&}}{copied_line}"
            )
    return "\n".join(output) + "\n"


def translate_srt(
    input_path: Path,
    output_path: Path,
    config: Config,
    client: Any | None = None,
    *,
    target_language: str | None = None,
    subtitle_mode: str | None = None,
    frequency: dict[str, Any] | None = None,
) -> dict[str, int]:
    target_language = target_language or config.target_language
    subtitle_mode = subtitle_mode or config.default_subtitle_mode
    subtitles = list(srt.parse(input_path.read_text(encoding="utf-8-sig")))
    indexed = list(enumerate(subtitles))
    if not indexed:
        raise PipelineError("Downloaded subtitle contains no cues")
    usage = {"promptTokens": 0, "completionTokens": 0, "totalTokens": 0}
    translations: dict[int, str] = {}
    glosses: dict[int, list[dict[str, Any]]] = {}
    candidates: dict[int, dict[int, dict[str, Any]]] = {}
    work = indexed

    if subtitle_mode == "minimalistic":
        data = frequency or frequency_data()
        work = []
        for cue_id, subtitle in indexed:
            _, cue_candidates = minimal_candidates(subtitle.content, data, config.minimal_frequency_tier)
            if cue_candidates:
                candidates[cue_id] = {candidate["id"]: candidate for candidate in cue_candidates}
                work.append((cue_id, subtitle))
        if not work:
            output_path.write_text(render_minimalistic_ass(subtitles, {}), encoding="utf-8")
            return usage

    client = client or OpenAI(
        api_key=config.openai_api_key,
        base_url=config.openai_base_url,
        max_retries=2,
        timeout=90,
    )

    for batch in batch_cues(work):
        expected = {cue_id for cue_id, _ in batch}
        if subtitle_mode == "minimalistic":
            payload = [
                {
                    "id": cue_id,
                    "text": plain_subtitle_text(cue.content),
                    "candidates": [
                        {"id": candidate["id"], "text": candidate["text"], "rank": candidate["rank"]}
                        for candidate in candidates[cue_id].values()
                    ],
                }
                for cue_id, cue in batch
            ]
        else:
            payload = [{"id": cue_id, "text": cue.content} for cue_id, cue in batch]
        error: Exception | None = None
        for attempt in range(3):
            try:
                completion = client.chat.completions.create(
                    model=config.openai_model_id,
                    messages=[
                        {
                            "role": "developer",
                            "content": minimalistic_instructions(target_language)
                            if subtitle_mode == "minimalistic"
                            else translation_instructions(target_language),
                        },
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
                    ],
                    reasoning_effort=config.openai_reasoning_effort,
                    response_format=minimalistic_schema() if subtitle_mode == "minimalistic" else translation_schema(),
                    store=False,
                    max_completion_tokens=16_000,
                    n=1,
                    verbosity="low",
                )
            except Exception as exc:
                raise PipelineError("AI translation request failed") from exc
            try:
                content = completion.choices[0].message.content
                result = json.loads(content or "")
                rows = result.get("translations", [])
                received = [row.get("id") for row in rows]
                if set(received) != expected or len(received) != len(expected):
                    raise ValueError("translation ids did not match the request")
                for row in rows:
                    cue_id = row["id"]
                    if subtitle_mode == "minimalistic":
                        selected = row.get("glosses")
                        if not isinstance(selected, list) or len(selected) > 3:
                            raise ValueError("glosses were invalid")
                        selected_ids = [item.get("candidate") for item in selected if isinstance(item, dict)]
                        if len(selected_ids) != len(selected) or len(set(selected_ids)) != len(selected_ids):
                            raise ValueError("gloss candidate ids were invalid")
                        glosses[cue_id] = []
                        for item in selected:
                            candidate = candidates[cue_id].get(item["candidate"])
                            if not candidate or not isinstance(item.get("text"), str):
                                raise ValueError("gloss translation was invalid")
                            translation = " ".join(item["text"].split())
                            if translation:
                                glosses[cue_id].append(candidate | {"translation": translation})
                    else:
                        if not isinstance(row.get("text"), str):
                            raise ValueError("translation text was invalid")
                        translations[cue_id] = row["text"].strip()
                if completion.usage:
                    usage["promptTokens"] += completion.usage.prompt_tokens or 0
                    usage["completionTokens"] += completion.usage.completion_tokens or 0
                    usage["totalTokens"] += completion.usage.total_tokens or 0
                error = None
                break
            except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
                error = exc
                if attempt < 2:
                    time.sleep(attempt + 1)
        if error:
            raise PipelineError("AI translation failed after three attempts") from error

    if subtitle_mode == "minimalistic":
        output_path.write_text(render_minimalistic_ass(subtitles, glosses), encoding="utf-8")
    else:
        for cue_id, subtitle in indexed:
            translated = translations[cue_id]
            if translated:
                subtitle.content = translated if subtitle_mode == "target" else subtitle.content.rstrip() + "\n" + translated
        output_path.write_text(srt.compose(subtitles, reindex=False), encoding="utf-8")
    return usage


MEDIA_TOKENS: dict[str, str] = {}
MEDIA_TOKENS_LOCK = threading.Lock()


def sync_subtitle(video_path: str, input_path: Path, output_path: Path, _: Config) -> None:
    executable = shutil.which("ffsubsync")
    if not executable:
        raise PipelineError("ffsubsync is not installed; run `uv sync`")
    token = secrets.token_urlsafe(24)
    with MEDIA_TOKENS_LOCK:
        MEDIA_TOKENS[token] = video_path
    try:
        result = subprocess.run(
            [
                executable,
                f"http://127.0.0.1:8000/internal/media/{token}",
                "-i",
                str(input_path),
                "-o",
                str(output_path),
                "--max-duration-seconds",
                "300",
                "--frame-rate",
                "16000",
                "--extract-audio-first",
                "--skip-sync-on-low-quality",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15 * 60,
            check=False,
        )
        if result.returncode or not output_path.exists() or not output_path.stat().st_size:
            raise PipelineError("Subtitle synchronization failed")
    except subprocess.TimeoutExpired as exc:
        raise PipelineError("Subtitle synchronization timed out") from exc
    finally:
        with MEDIA_TOKENS_LOCK:
            MEDIA_TOKENS.pop(token, None)


def process_video(
    relative: str,
    config: Config,
    webdav: WebDAV,
    opensubtitles: OpenSubtitles,
    progress: Callable[[str, str], None],
    syncer: Callable[[str, Path, Path, Config], None] = sync_subtitle,
    translator: Callable[..., dict[str, int]] = translate_srt,
    target_language: str | None = None,
    subtitle_mode: str | None = None,
) -> dict[str, Any]:
    target_language = target_language or config.target_language
    subtitle_mode = subtitle_mode or config.default_subtitle_mode
    target_name = TARGET_LANGUAGES[target_language][0]
    relative = normalize_relative(relative)
    info = webdav.file_info(relative)
    progress("searching", "Checking existing sidecar subtitles")
    english_sidecar: tuple[FileEntry, bytes] | None = None
    for entry in webdav.sidecars(relative):
        data = webdav.read_small(entry.path)
        language = detect_sidecar_language(info.name, entry.name, data)
        if subtitle_mode == "target" and language == target_language:
            return {
                "outputPath": entry.path,
                "sourceLanguage": target_language,
                "release": f"Existing sidecar: {entry.name}",
                "moviehashMatch": False,
                "quota": {"remaining": None, "resetTimeUtc": None},
                "aiUsage": {"promptTokens": 0, "completionTokens": 0, "totalTokens": 0},
                "existing": True,
            }
        if language == "en" and english_sidecar is None:
            english_sidecar = (entry, data)

    if english_sidecar:
        entry, subtitle_bytes = english_sidecar
        output_path = language_output_path(relative, target_language, webdav.exists, subtitle_mode)
        candidate = SubtitleCandidate(0, "en", f"Existing sidecar: {entry.name}", False)
        quota = {"remaining": None, "resetTimeUtc": None}
        source_suffix = PurePosixPath(entry.name).suffix.casefold()
        progress("downloading", "Using the existing English sidecar")
    else:
        output_path = choose_output_path(relative, target_language, webdav.exists, subtitle_mode)
        progress("hashing", "Reading the first and last 64 KiB")
        moviehash = webdav.moviehash(relative, info.size or 0)
        progress("searching", "Finding an exact subtitle match")
        languages = ("en",) if subtitle_mode in {"bilingual", "minimalistic"} else (target_language, "en")
        candidate = opensubtitles.find(info.name, moviehash, languages)
        progress("downloading", f"Downloading {candidate.language} subtitle")
        subtitle_bytes, quota = opensubtitles.download(candidate)
        source_suffix = ".srt"

    with tempfile.TemporaryDirectory(prefix="subtitle-maker-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / f"source{source_suffix}"
        synced = temp / "synced.srt"
        final = temp / ("final.ass" if subtitle_mode == "minimalistic" else "final.srt")
        source.write_bytes(subtitle_bytes)

        if candidate.moviehash_match:
            try:
                subtitles = list(srt.parse(source.read_text(encoding="utf-8-sig")))
                if not subtitles:
                    raise ValueError("subtitle contains no cues")
                synced.write_text(srt.compose(subtitles, reindex=False), encoding="utf-8")
                progress("synchronizing", "Exact video match; synchronization not needed")
            except (UnicodeDecodeError, ValueError, srt.SRTParseError):
                progress("synchronizing", "Matching subtitles against a five-minute audio sample")
                syncer(relative, source, synced, config)
        else:
            progress("synchronizing", "Matching subtitles against a five-minute audio sample")
            syncer(relative, source, synced, config)
        usage = {"promptTokens": 0, "completionTokens": 0, "totalTokens": 0}
        if candidate.language == "en":
            progress("translating", f"Translating English cues to {target_name}")
            usage = translator(
                synced,
                final,
                config,
                target_language=target_language,
                subtitle_mode=subtitle_mode,
            )
        else:
            shutil.copyfile(synced, final)

        progress("uploading", f"Uploading {PurePosixPath(output_path).name}")
        webdav.put(output_path, final.read_bytes())

    return {
        "outputPath": output_path,
        "sourceLanguage": candidate.language,
        "release": candidate.release,
        "moviehashMatch": candidate.moviehash_match,
        "quota": quota,
        "aiUsage": usage,
    }


try:
    CONFIG = Config.load()
    CONFIG_ERROR: str | None = None
    WEBDAV = WebDAV(CONFIG)
    OPENSUBTITLES = OpenSubtitles(CONFIG)
except Exception as exc:
    CONFIG = None
    CONFIG_ERROR = str(exc)
    WEBDAV = None
    OPENSUBTITLES = None

JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="subtitle-job")


def require_services() -> tuple[Config, WebDAV, OpenSubtitles]:
    if not CONFIG or not WEBDAV or not OPENSUBTITLES:
        raise HTTPException(status_code=503, detail=CONFIG_ERROR or "Application is not configured")
    return CONFIG, WEBDAV, OPENSUBTITLES


def update_job(job_id: str, item_index: int, stage: str, message: str) -> None:
    with JOBS_LOCK:
        job = JOBS[job_id]
        item = job.items[item_index]
        item.started_at = item.started_at or time.time()
        item.status = stage
        item.message = message
        job.status = "running"
        job.message = f"{item_index + 1} of {len(job.items)} · {PurePosixPath(item.path).name} · {message}"


def run_job(job_id: str) -> None:
    try:
        config, webdav, opensubtitles = require_services()
        ai = OpenAI(
            api_key=config.openai_api_key,
            base_url=config.openai_base_url,
            max_retries=2,
            timeout=90,
        )
        with JOBS_LOCK:
            job = JOBS[job_id]
            job.status = "running"
            job.message = f"Starting 1 of {len(job.items)}"
            paths = [item.path for item in job.items]
            target_language = job.target_language
            subtitle_mode = job.subtitle_mode

        succeeded = 0
        for index, path in enumerate(paths):
            update_job(job_id, index, "running", "Starting")
            try:
                result = process_video(
                    path,
                    config,
                    webdav,
                    opensubtitles,
                    lambda stage, message, index=index: update_job(job_id, index, stage, message),
                    translator=lambda source, destination, config, **options: translate_srt(
                        source, destination, config, ai, **options
                    ),
                    target_language=target_language,
                    subtitle_mode=subtitle_mode,
                )
            except PipelineError as exc:
                with JOBS_LOCK:
                    item = JOBS[job_id].items[index]
                    item.status = "failed"
                    item.message = "Could not finish"
                    item.error = str(exc)
            except Exception:
                LOGGER.exception("job_item_crashed job_id=%s path=%r", job_id, path)
                with JOBS_LOCK:
                    item = JOBS[job_id].items[index]
                    item.status = "failed"
                    item.message = "Could not finish"
                    item.error = "Unexpected internal error"
            else:
                succeeded += 1
                with JOBS_LOCK:
                    item = JOBS[job_id].items[index]
                    item.status = "completed"
                    item.message = "Existing target subtitle found" if result.get("existing") else "Subtitle created successfully"
                    item.result = result
            finally:
                with JOBS_LOCK:
                    JOBS[job_id].items[index].finished_at = time.time()

        with JOBS_LOCK:
            job = JOBS[job_id]
            failed = len(job.items) - succeeded
            job.status = "completed" if succeeded else "failed"
            job.message = f"{succeeded} of {len(job.items)} videos completed"
            if failed:
                job.message += f"; {failed} failed"
            if not succeeded:
                job.error = "Every video in the batch failed"
    except Exception:
        LOGGER.exception("job_crashed job_id=%s", job_id)
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job:
                job.status = "failed"
                job.message = "Batch failed"
                job.error = "Unexpected internal error"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    loader = asyncio.create_task(asyncio.to_thread(load_frequency_data))
    yield
    await loader


app = FastAPI(title="Subtitle Maker", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Content-Type"],
)


def request_path(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


@app.middleware("http")
async def log_requests(request: Request, call_next: Callable[[Request], Any]) -> Response:
    request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        LOGGER.exception(
            "request_crashed request_id=%s method=%s path=%s query=%r duration_ms=%.1f client=%s",
            request_id,
            request.method,
            request_path(request),
            request.url.query,
            (time.perf_counter() - started) * 1000,
            request.client.host if request.client else "unknown",
        )
        raise
    response.headers["X-Request-ID"] = request_id
    LOGGER.info(
        "request_finished request_id=%s method=%s path=%s query=%r status=%s duration_ms=%.1f client=%s",
        request_id,
        request.method,
        request_path(request),
        request.url.query,
        response.status_code,
        (time.perf_counter() - started) * 1000,
        request.client.host if request.client else "unknown",
    )
    return response


@app.exception_handler(HTTPException)
async def log_http_error(request: Request, exc: HTTPException) -> Response:
    LOGGER.log(
        logging.ERROR if exc.status_code >= 500 else logging.WARNING,
        "request_rejected request_id=%s method=%s path=%s query=%r status=%s detail=%r client=%s",
        request.state.request_id,
        request.method,
        request_path(request),
        request.url.query,
        exc.status_code,
        exc.detail,
        request.client.host if request.client else "unknown",
    )
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def log_validation_error(request: Request, exc: RequestValidationError) -> Response:
    errors = [
        {"field": ".".join(map(str, error["loc"])), "type": error["type"], "message": error["msg"]}
        for error in exc.errors()
    ]
    LOGGER.warning(
        "request_validation_failed request_id=%s method=%s path=%s query=%r status=422 errors=%s client=%s",
        request.state.request_id,
        request.method,
        request_path(request),
        request.url.query,
        json.dumps(errors, ensure_ascii=False),
        request.client.host if request.client else "unknown",
    )
    return await request_validation_exception_handler(request, exc)


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    try:
        values = load_saved_settings()
        secrets = load_saved_secrets()
        return {
            "values": values,
            "secrets": {key: key in secrets for key in SECRET_SETTINGS},
            "options": {
                "target_languages": [{"value": code, "label": value[0]} for code, value in TARGET_LANGUAGES.items()],
                "subtitle_modes": [{"value": code, "label": label} for code, label in SUBTITLE_MODES.items()],
            },
        }
    except PipelineError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.put("/api/settings")
def update_settings(body: SettingsRequest) -> dict[str, Any]:
    unknown_values = set(body.values) - SETTING_DEFAULTS.keys()
    unknown_secrets = (set(body.secrets) | set(body.clear_secrets)) - set(SECRET_SETTINGS)
    if unknown_values or unknown_secrets:
        raise HTTPException(status_code=400, detail="Unknown setting")

    values = SETTING_DEFAULTS | body.values
    try:
        previous_secrets = load_saved_secrets()
    except PipelineError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    updates = {key: value for key, value in body.secrets.items() if value}
    clears = set(body.clear_secrets) - updates.keys()
    secrets = previous_secrets | updates
    for key in clears:
        secrets.pop(key, None)
    try:
        Config.from_settings(values, secrets)
    except PipelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    temporary: Path | None = None
    try:
        CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(CONFIG_DIR, 0o700)
        with tempfile.NamedTemporaryFile(
            "w", dir=CONFIG_DIR, prefix="config.", encoding="utf-8", delete=False
        ) as output:
            temporary = Path(output.name)
            json.dump(values, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        for key, value in updates.items():
            set_key(ENV_PATH, SECRET_ENV_NAMES[key], value)
        for key in clears:
            if ENV_PATH.exists():
                unset_key(ENV_PATH, SECRET_ENV_NAMES[key])
        if ENV_PATH.exists():
            os.chmod(ENV_PATH, 0o600)
        os.replace(temporary, CONFIG_PATH)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not save settings") from exc
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return {"saved": True, "message": "Saved to .env. Restart Subtitle Maker to apply changes."}


@app.get("/api/health")
def health() -> dict[str, Any]:
    binaries = {"ffmpeg": bool(shutil.which("ffmpeg")), "ffsubsync": bool(shutil.which("ffsubsync"))}
    download_auth = bool(CONFIG and CONFIG.opensubtitles_username and CONFIG.opensubtitles_password)
    return {
        "ready": CONFIG_ERROR is None and download_auth and all(binaries.values()),
        "configuration": (
            CONFIG_ERROR
            or ("ready" if download_auth else "Add OPENSUBTITLE_USERNAME and OPENSUBTITLE_PASSWORD to .env")
        ),
        "binaries": binaries,
    }


@app.get("/api/files")
def files(path: str = Query(default="")) -> dict[str, Any]:
    _, webdav, _ = require_services()
    try:
        relative = normalize_relative(path)
        return {"path": relative, "entries": [asdict(entry) for entry in webdav.list(relative)]}
    except PipelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/quota")
def quota() -> dict[str, int]:
    _, _, opensubtitles = require_services()
    try:
        return {"remaining": opensubtitles.remaining_downloads()}
    except PipelineError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/jobs", status_code=202)
def create_job(body: JobRequest) -> dict[str, str]:
    config, _, _ = require_services()
    if not body.paths:
        raise HTTPException(status_code=400, detail="Select at least one video")
    try:
        paths = [normalize_relative(path) for path in body.paths]
    except PipelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if any(not path for path in paths):
        raise HTTPException(status_code=400, detail="Every selected video needs a path")
    if len(set(paths)) != len(paths):
        raise HTTPException(status_code=400, detail="A video can only appear once in a batch")
    mode = (body.mode or config.default_subtitle_mode).strip().lower()
    if mode not in SUBTITLE_MODES:
        raise HTTPException(status_code=400, detail="Subtitle mode is invalid")
    with JOBS_LOCK:
        queued_paths = {
            item.path
            for job in JOBS.values()
            if job.status not in TERMINAL_STAGES
            for item in job.items
        }
        if queued_paths.intersection(paths):
            raise HTTPException(status_code=409, detail="A selected video is already in the queue")
        job = Job(
            id=str(uuid.uuid4()),
            items=[JobItem(path=path) for path in paths],
            target_language=config.target_language,
            subtitle_mode=mode,
        )
        JOBS[job.id] = job
    EXECUTOR.submit(run_job, job.id)
    return {"jobId": job.id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return asdict(job)


@app.api_route("/internal/media/{token}", methods=["GET", "HEAD"], include_in_schema=False)
def media_proxy(token: str, request: Request) -> Response:
    _, webdav, _ = require_services()
    with MEDIA_TOKENS_LOCK:
        relative = MEDIA_TOKENS.get(token)
    if not relative:
        raise HTTPException(status_code=404, detail="Media token expired")
    try:
        upstream = webdav.stream(relative, request.headers.get("range"))
    except PipelineError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    headers = {
        key: value
        for key in ("content-length", "content-range", "accept-ranges", "content-type")
        if (value := upstream.headers.get(key))
    }
    if request.method == "HEAD":
        upstream.close()
        return Response(status_code=upstream.status_code, headers=headers)

    def body() -> Iterable[bytes]:
        try:
            yield from upstream.iter_bytes()
        finally:
            upstream.close()

    return StreamingResponse(body(), status_code=upstream.status_code, headers=headers)


frontend_out = BASE_DIR / "frontend" / "out"
if frontend_out.is_dir():
    app.mount("/", StaticFiles(directory=frontend_out, html=True), name="frontend")
