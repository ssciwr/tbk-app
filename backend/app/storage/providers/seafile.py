from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from typing import Any, BinaryIO, Literal
from urllib.parse import urlparse

import requests

from ..base import StorageProvider


class SeafileError(RuntimeError):
    pass


class SeafileProvider(StorageProvider):
    def __init__(
        self,
        server_url: str,
        library_name: str,
        username: str | None = None,
        password: str | None = None,
        account_token: str | None = None,
        repo_token: str | None = None,
        timeout: int = 30,
    ) -> None:
        if not server_url:
            raise ValueError("SEAFILE_URL is required")
        if not library_name:
            raise ValueError("SEAFILE_LIBRARY_NAME is required")

        self.server_url = server_url.rstrip("/")
        self.library_name = library_name
        self.timeout = timeout
        self.session = requests.Session()
        self._lock = Lock()

        self.repo_token = repo_token
        self.account_token = account_token
        self.username = username
        self.password = password

        if not repo_token and not account_token and not (username and password):
            raise ValueError(
                "Provide one authentication mode: repo token, account token, or username/password"
            )

        self._version = self._get_server_version()
        self._major_version = int(self._version.split(".")[0]) if self._version else 0

        self.repo_id: str | None = None
        self._by_repo_token = bool(repo_token)
        self._headers: dict[str, str] = {"accept": "application/json"}

        if self._by_repo_token:
            assert repo_token is not None
            self._headers |= self._auth_header(repo_token)
            repo_info = self._request_json("GET", "/api/v2.1/via-repo-token/repo-info/")
            self.repo_id = (
                str(repo_info.get("repo_id")) if repo_info.get("repo_id") else None
            )
            if not self.repo_id:
                raise SeafileError("Failed to resolve repo info from repo token")
        else:
            token = self.account_token or self._authenticate_user()
            self._headers |= self._auth_header(token)
            self.repo_id = self._ensure_library()

        self._next_id = self._discover_next_case_id()

    def _auth_header(self, token: str) -> dict[str, str]:
        if self._major_version < 11:
            return {"Authorization": f"Token {token}"}
        return {"Authorization": f"Bearer {token}"}

    def _get_server_version(self) -> str:
        response = self.session.get(
            f"{self.server_url}/api2/server-info/", timeout=self.timeout
        )
        if response.status_code != 200:
            raise SeafileError(
                f"Failed to get Seafile server info: {response.status_code}"
            )
        payload = response.json()
        version = payload.get("version")
        if not isinstance(version, str):
            raise SeafileError("Seafile server version is missing")
        return version

    def _authenticate_user(self) -> str:
        if not self.username or not self.password:
            raise SeafileError("Username/password auth requested without credentials")
        response = self.session.post(
            f"{self.server_url}/api2/auth-token/",
            data={"username": self.username, "password": self.password},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise SeafileError(
                f"Failed to authenticate with Seafile: {response.status_code}"
            )
        token = response.json().get("token")
        if not isinstance(token, str) or not token:
            raise SeafileError("Invalid Seafile auth token")
        return token

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = self.session.request(
            method,
            f"{self.server_url}{path}",
            params=params,
            data=data,
            json=json_body,
            files=files,
            headers=self._headers | (headers or {}),
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise SeafileError(
                f"Seafile request failed ({response.status_code}): {response.text}"
            )
        if not response.text:
            return {}
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        try:
            return response.json()
        except json.JSONDecodeError:
            text = response.text.strip()
            if text.startswith('"') and text.endswith('"'):
                return text[1:-1]
            return text

    def _repo_dir_endpoint(self) -> str:
        if self._by_repo_token:
            return "/api/v2.1/via-repo-token/dir/"
        assert self.repo_id
        return f"/api2/repos/{self.repo_id}/dir/"

    def _repo_upload_link_endpoint(self) -> str:
        if self._by_repo_token:
            return "/api/v2.1/via-repo-token/upload-link/"
        assert self.repo_id
        return f"/api2/repos/{self.repo_id}/upload-link/"

    def _list_dir(self, path: str) -> list[dict[str, Any]]:
        params = {"path": path} if self._by_repo_token else {"p": path}
        payload = self._request_json("GET", self._repo_dir_endpoint(), params=params)
        if self._by_repo_token:
            entries = payload.get("dirent_list", [])
            if not isinstance(entries, list):
                return []
            return entries
        if isinstance(payload, list):
            return payload
        return []

    def _create_dir(self, path: str) -> None:
        params = {"path": path} if self._by_repo_token else {"p": path}
        self._request_json(
            "POST",
            self._repo_dir_endpoint(),
            params=params,
            data={"operation": "mkdir"},
        )

    def _ensure_library(self) -> str:
        repos = self._request_json("GET", "/api2/repos/")
        if not isinstance(repos, list):
            raise SeafileError("Invalid response when listing repositories")

        for repo in repos:
            if repo.get("name") == self.library_name:
                repo_id = repo.get("id") or repo.get("repo_id")
                if repo_id:
                    return str(repo_id)

        created = self._request_json(
            "POST", "/api2/repos/", json_body={"name": self.library_name}
        )
        repo_id = created.get("repo_id") or created.get("id")
        if not repo_id:
            raise SeafileError("Failed to create Seafile library")
        return str(repo_id)

    def _discover_next_case_id(self) -> int:
        max_case_id = 0
        for entry in self._list_dir("/"):
            name = entry.get("name", "")
            if isinstance(name, str) and name.isdigit():
                max_case_id = max(max_case_id, int(name))
        return max_case_id + 1

    def _create_shared_link(self, path: str) -> str:
        payload: dict[str, Any] = {
            "path": path,
            "permissions": {
                "can_edit": False,
                "can_download": True,
                "can_upload": True,
            },
        }
        if not self._by_repo_token:
            payload["repo_id"] = self.repo_id
            endpoint = "/api/v2.1/share-links/"
        else:
            endpoint = "/api/v2.1/via-repo-token/share-links/"

        result = self._request_json("POST", endpoint, json_body=payload)
        link = result.get("link")
        if not isinstance(link, str) or not link:
            raise SeafileError("Failed to create shared link")
        return link

    def create_storage_for_user(self) -> str:
        with self._lock:
            case_id = self._next_id
            self._next_id += 1

        case_root = f"/{case_id}"
        self._create_dir(case_root)
        self._create_dir(f"{case_root}/normal")
        self._create_dir(f"{case_root}/xray")

        try:
            return self._create_shared_link(case_root)
        except Exception:
            return f"seafile://{case_id}"

    def _upload_to_repo(
        self, parent_dir: str, file_obj: BinaryIO, filename: str
    ) -> None:
        params = {"path": parent_dir} if self._by_repo_token else {"p": parent_dir}
        upload_link = self._request_json(
            "GET", self._repo_upload_link_endpoint(), params=params
        )

        if isinstance(upload_link, dict):
            upload_url = upload_link.get("upload_link")
        else:
            upload_url = upload_link

        if not isinstance(upload_url, str) or not upload_url:
            raise SeafileError("Failed to resolve upload link")

        upload_url = upload_url.strip().strip('"')
        if "?" in upload_url:
            upload_url = f"{upload_url}&ret-json=1"
        else:
            upload_url = f"{upload_url}?ret-json=1"

        if hasattr(file_obj, "seek"):
            file_obj.seek(0)

        response = self.session.post(
            upload_url,
            files={"file": (Path(filename).name, file_obj)},
            data={"parent_dir": parent_dir},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise SeafileError(
                f"Failed uploading file to repository: {response.status_code}"
            )

    def _extract_share_token(self, share_link: str) -> str:
        path_parts = [part for part in urlparse(share_link).path.split("/") if part]
        if not path_parts:
            raise SeafileError("Invalid share link")
        if len(path_parts) == 1:
            return path_parts[0]
        if path_parts[-1] in {"d", "f", "s"} and len(path_parts) >= 2:
            return path_parts[-2]
        return path_parts[-1]

    def _upload_via_share_link(
        self,
        share_link: str,
        file_type: Literal["normal", "xray"],
        file_obj: BinaryIO,
        filename: str,
    ) -> None:
        token = self._extract_share_token(share_link)
        metadata = self._request_json("GET", f"/api/v2.1/share-links/{token}/")
        base_path = metadata.get("path")
        if not isinstance(base_path, str) or not base_path.startswith("/"):
            raise SeafileError("Unable to resolve base path from shared link")

        upload_info = self._request_json(
            "GET",
            f"/api/v2.1/share-links/{token}/upload/",
            params={"path": f"/{file_type}"},
        )
        upload_link = (
            upload_info.get("upload_link") if isinstance(upload_info, dict) else None
        )
        if not isinstance(upload_link, str) or not upload_link:
            raise SeafileError("Unable to resolve upload link for shared path")

        if "?" in upload_link:
            upload_link = f"{upload_link}&ret-json=1"
        else:
            upload_link = f"{upload_link}?ret-json=1"

        if hasattr(file_obj, "seek"):
            file_obj.seek(0)

        parent_dir = f"{base_path.rstrip('/')}/{file_type}"
        response = self.session.post(
            upload_link,
            files={"file": (Path(filename).name, file_obj)},
            data={"parent_dir": parent_dir},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise SeafileError(
                f"Failed uploading file via shared link: {response.status_code}"
            )

    def upload_file(
        self,
        user_ref: int | str,
        file_type: Literal["normal", "xray"],
        file_obj: BinaryIO,
        filename: str,
    ) -> None:
        if file_type not in {"normal", "xray"}:
            raise ValueError("file_type must be 'normal' or 'xray'")

        if isinstance(user_ref, int) or (
            isinstance(user_ref, str) and user_ref.isdigit()
        ):
            case_id = int(user_ref)
            self._upload_to_repo(f"/{case_id}/{file_type}", file_obj, filename)
            return

        if isinstance(user_ref, str) and user_ref.startswith("seafile://"):
            case_id = int(user_ref.replace("seafile://", "", 1))
            self._upload_to_repo(f"/{case_id}/{file_type}", file_obj, filename)
            return

        if isinstance(user_ref, str) and user_ref.startswith("http"):
            self._upload_via_share_link(user_ref, file_type, file_obj, filename)
            return

        raise ValueError("Unsupported Seafile user reference")
