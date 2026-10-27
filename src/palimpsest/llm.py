"""Local-first model access.

Every call goes to Ollama on localhost. There is deliberately no code path in
this file that can reach a remote API: the disk being examined never leaves the
machine, and neither does anything we infer from it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("PALIMPSEST_MODEL", "gemma3:4b")
DEFAULT_EMBED = os.environ.get("PALIMPSEST_EMBED", "nomic-embed-text")


class LLMError(RuntimeError):
    pass


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def parse_json_loose(raw: str) -> Any:
    """Models sometimes wrap JSON in prose or fences. Find the object."""
    text = _strip_fences(raw)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise LLMError(f"no JSON in model output: {text[:200]!r}")
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise LLMError(f"unbalanced JSON in model output: {text[:200]!r}")


@dataclass
class LLM:
    model: str = DEFAULT_MODEL
    embed_model: str = DEFAULT_EMBED
    vision_model: str | None = None
    host: str = DEFAULT_HOST
    timeout: int = 900
    enabled: bool = True
    cache_dir: str | None = None
    keep_alive: str = "30m"
    calls: int = 0
    cached_calls: int = 0
    prompt_tokens: int = 0
    eval_tokens: int = 0
    _tags: dict[str, Any] | None = field(default=None, repr=False)

    # ---- cache ---------------------------------------------------------
    def _key(self, model: str, system: str, user: str, images: list[str] | None) -> str:
        digest = hashlib.sha256()
        digest.update(model.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(system.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(user.encode("utf-8"))
        for image in images or []:
            digest.update(b"\x00")
            digest.update(image.encode("ascii", "ignore"))
        return digest.hexdigest()[:32]

    def _cache_path(self, key: str) -> Path | None:
        if not self.cache_dir:
            return None
        root = Path(self.cache_dir)
        root.mkdir(parents=True, exist_ok=True)
        return root / f"{key}.json"

    # ---- transport -----------------------------------------------------
    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            self.host + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise LLMError(
                f"cannot reach Ollama at {self.host} ({exc}). Is the container up? "
                f"Try: docker start ollama"
            ) from exc

    def tags(self) -> dict[str, Any]:
        if self._tags is None:
            req = urllib.request.Request(self.host + "/api/tags")
            with urllib.request.urlopen(req, timeout=10) as resp:
                self._tags = json.loads(resp.read().decode("utf-8"))
        return self._tags

    def models(self) -> list[str]:
        return [m["name"] for m in self.tags().get("models", [])]

    def has_model(self, name: str) -> bool:
        base = name.split(":")[0]
        return any(m == name or m.split(":")[0] == base for m in self.models())

    def require(self) -> None:
        if not self.enabled:
            raise LLMError("model use is disabled (--no-llm)")
        for name in {self.model, self.vision_model or self.model}:
            if not self.has_model(name):
                raise LLMError(
                    f"model {name!r} is not pulled. Try: docker exec ollama ollama pull {name}"
                )

    # ---- chat ----------------------------------------------------------
    def chat(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        images: list[str] | None = None,
        temperature: float = 0.2,
        num_predict: int = 700,
        json_mode: bool = True,
    ) -> str:
        if not self.enabled:
            raise LLMError("model use is disabled (--no-llm)")
        actual_model = model or self.model
        key = self._key(actual_model, system, user, images)
        cached = self._cache_path(key)
        if cached and cached.exists():
            try:
                self.cached_calls += 1
                return str(json.loads(cached.read_text(encoding="utf-8"))["content"])
            except (json.JSONDecodeError, KeyError, OSError):
                pass

        message: dict[str, Any] = {"role": "user", "content": user}
        if images:
            message["images"] = images
        payload: dict[str, Any] = {
            "model": actual_model,
            "stream": False,
            "keep_alive": self.keep_alive,
            "messages": [{"role": "system", "content": system}, message],
            "options": {"temperature": temperature, "num_predict": num_predict},
        }
        if json_mode:
            payload["format"] = "json"
        data = self._post("/api/chat", payload)
        self.calls += 1
        self.prompt_tokens += int(data.get("prompt_eval_count", 0) or 0)
        self.eval_tokens += int(data.get("eval_count", 0) or 0)
        content = str(data.get("message", {}).get("content", ""))
        if cached:
            try:
                cached.write_text(
                    json.dumps({"content": content, "model": actual_model}),
                    encoding="utf-8",
                )
            except OSError:
                pass
        return content

    def json_chat(self, system: str, user: str, *, retries: int = 1, **kw: Any) -> Any:
        last: Exception | None = None
        for attempt in range(retries + 1):
            raw = self.chat(system, user, **kw)
            try:
                return parse_json_loose(raw)
            except (LLMError, json.JSONDecodeError) as exc:
                last = exc
                user = user + "\n\nReturn ONLY valid JSON. No prose, no fences."
        raise LLMError(f"model did not return usable JSON: {last}")

    # ---- vision --------------------------------------------------------
    def vision_json(self, image_path: str | Path, system: str, user: str, **kw: Any) -> Any:
        prepared = prepare_image(image_path)
        try:
            b64 = base64.b64encode(Path(prepared).read_bytes()).decode("ascii")
            return self.json_chat(
                system,
                user,
                model=self.vision_model or self.model,
                images=[b64],
                **kw,
            )
        finally:
            if prepared != str(image_path):
                Path(prepared).unlink(missing_ok=True)

    # ---- embeddings ----------------------------------------------------
    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.enabled:
            raise LLMError("model use is disabled (--no-llm)")
        try:
            data = self._post("/api/embed", {"model": self.embed_model, "input": texts})
            vectors = data.get("embeddings")
            if vectors and len(vectors) == len(texts):
                return [[float(x) for x in v] for v in vectors]
        except (LLMError, KeyError):
            pass
        out: list[list[float]] = []
        for text in texts:
            data = self._post("/api/embeddings", {"model": self.embed_model, "prompt": text})
            out.append([float(x) for x in data["embedding"]])
        return out

    def usage(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "cached": self.cached_calls,
            "prompt_tokens": self.prompt_tokens,
            "eval_tokens": self.eval_tokens,
        }


def prepare_image(path: str | Path, max_edge: int = 768) -> str:
    """Downscale before vision inference. A 12 MP photo costs ~10x the tokens
    for no extra signal in triage."""
    src = str(path)
    try:
        fd, tmp = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        subprocess.run(
            [
                "ffmpeg", "-loglevel", "error", "-y", "-i", src,
                "-vf", f"scale='min({max_edge},iw)':-2",
                "-q:v", "4", tmp,
            ],
            check=True,
            timeout=60,
        )
        if os.path.getsize(tmp) > 0:
            return tmp
        os.unlink(tmp)
    except (OSError, subprocess.SubprocessError):
        pass
    return src
