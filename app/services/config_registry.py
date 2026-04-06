"""Dynamic ConfigRegistry — runtime-refreshable config without restart.

Architecture (Azure sentinel key pattern adapted for Supabase):
1. DB is source of truth (Supabase tables)
2. File overrides (data/*.json) loaded at startup
3. Env var overrides have highest priority
4. Minimal fallbacks hardcoded only as last resort
5. Background refresh polls sentinel key; on change, reloads all configs
6. Atomic snapshot swap — readers never see partial updates
7. Failures keep last-good snapshot; metric emitted

Config domains:
- mutuelle_aliases: STT correction patterns
- known_mutuelles: fuzzy matching list
- ssml_abbreviations: TTS normalization
- ssml_patterns: regex patterns for number/date/phone
- ssml_months: month name dictionary

Usage:
    registry = ConfigRegistry(supabase=sb, cache=cache)
    await registry.start()  # initial load + start background refresh

    # Hot-path reads (O(1), no lock):
    aliases = registry.mutuelle_aliases
    abbreviations = registry.ssml_abbreviations

    # Force refresh:
    await registry.refresh()

    # Shutdown:
    await registry.stop()
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.services.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigSnapshot:
    """Immutable config snapshot — atomically swapped on refresh."""
    version: int = 0
    loaded_at: float = 0.0
    mutuelle_aliases: dict[str, list[str]] = field(default_factory=dict)
    known_mutuelles: list[str] = field(default_factory=list)
    ssml_abbreviations: dict[str, str] = field(default_factory=dict)
    ssml_patterns: dict[str, str] = field(default_factory=dict)
    ssml_months: dict[str, str] = field(default_factory=dict)


class ConfigRegistry:
    """Runtime-refreshable config registry.

    Reads from Supabase tables, falls back to file/env, keeps last-good snapshot.
    Background task polls sentinel key and reloads on change.
    """

    def __init__(
        self,
        supabase: SupabaseClient | None = None,
        refresh_interval_sec: float = 60.0,
        sentinel_key: str = "config_version",
    ):
        self._supabase = supabase
        self._refresh_interval = refresh_interval_sec
        self._sentinel_key = sentinel_key
        self._snapshot: ConfigSnapshot = ConfigSnapshot()
        self._last_sentinel: str = ""
        self._refresh_task: asyncio.Task | None = None
        self._running = False

        # Metrics
        self._reload_count = 0
        self._reload_failures = 0
        self._last_reload_ms = 0.0

    @property
    def snapshot(self) -> ConfigSnapshot:
        return self._snapshot

    @property
    def mutuelle_aliases(self) -> dict[str, list[str]]:
        return self._snapshot.mutuelle_aliases

    @property
    def known_mutuelles(self) -> list[str]:
        return self._snapshot.known_mutuelles

    @property
    def ssml_abbreviations(self) -> dict[str, str]:
        return self._snapshot.ssml_abbreviations

    @property
    def ssml_patterns(self) -> dict[str, str]:
        return self._snapshot.ssml_patterns

    @property
    def ssml_months(self) -> dict[str, str]:
        return self._snapshot.ssml_months

    @property
    def version(self) -> int:
        return self._snapshot.version

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "version": self._snapshot.version,
            "loaded_at": self._snapshot.loaded_at,
            "reload_count": self._reload_count,
            "reload_failures": self._reload_failures,
            "last_reload_ms": self._last_reload_ms,
            "mutuelles": len(self._snapshot.known_mutuelles),
            "aliases": len(self._snapshot.mutuelle_aliases),
            "abbreviations": len(self._snapshot.ssml_abbreviations),
        }

    async def start(self) -> None:
        """Initial load + start background refresh loop."""
        await self.refresh()
        self._running = True
        self._refresh_task = asyncio.create_task(self._refresh_loop())
        logger.info("ConfigRegistry started: version=%d, %d mutuelles, %d aliases, %d abbreviations",
                    self._snapshot.version,
                    len(self._snapshot.known_mutuelles),
                    len(self._snapshot.mutuelle_aliases),
                    len(self._snapshot.ssml_abbreviations))

    async def stop(self) -> None:
        """Stop background refresh."""
        self._running = False
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass

    async def refresh(self) -> bool:
        """Reload all configs from DB. Returns True if snapshot changed."""
        start = time.monotonic()
        try:
            new_snapshot = await self._build_snapshot()
            if new_snapshot.version != self._snapshot.version:
                self._snapshot = new_snapshot  # Atomic swap
                self._reload_count += 1
                self._last_reload_ms = (time.monotonic() - start) * 1000

                # Push updates into pipeline modules (runtime hot-swap)
                self._push_to_pipeline(new_snapshot)

                # Emit metrics
                try:
                    from app.observability.metrics import record_config_reload
                    record_config_reload(True, self._last_reload_ms, new_snapshot.version)
                except ImportError:
                    pass

                logger.info("Config refreshed: version=%d in %.0fms",
                           new_snapshot.version, self._last_reload_ms)
                return True
            return False
        except Exception as e:
            self._reload_failures += 1
            self._last_reload_ms = (time.monotonic() - start) * 1000

            try:
                from app.observability.metrics import record_config_reload
                record_config_reload(False, self._last_reload_ms, self._snapshot.version)
            except ImportError:
                pass

            logger.warning("Config refresh failed (keeping last-good v%d): %s",
                          self._snapshot.version, e)
            return False

    async def _refresh_loop(self) -> None:
        """Background polling loop — checks sentinel, reloads on change."""
        while self._running:
            try:
                await asyncio.sleep(self._refresh_interval)
                if not self._running:
                    break

                # Check sentinel key
                sentinel_changed = await self._check_sentinel()
                if sentinel_changed:
                    await self.refresh()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Config refresh loop error: %s", e)

    async def _check_sentinel(self) -> bool:
        """Check if sentinel changed. Uses refresh interval as fallback if no sentinel table."""
        if not self._supabase:
            return True  # No DB — always refresh from files

        # Try sentinel table first; if it doesn't exist, always refresh
        try:
            rows = await self._supabase.select(
                "config_sentinel",
                {"key": self._sentinel_key},
                limit=1,
            )
            if rows:
                current = str(rows[0].get("value", ""))
                if current != self._last_sentinel:
                    self._last_sentinel = current
                    return True
                return False
        except Exception:
            pass
        # No sentinel table or error — refresh unconditionally on interval
        return True

    @staticmethod
    def _content_hash(data: dict | list) -> str:
        """Compute deterministic hash of config content for change detection."""
        import hashlib
        raw = json.dumps(data, sort_keys=True, default=str).encode()
        return hashlib.sha256(raw).hexdigest()[:16]

    @classmethod
    def _file_content_hash(cls, path: Path) -> str:
        """Best-effort hash of a JSON config file used for change detection."""
        try:
            if not path.exists() or not path.is_file():
                return ""
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, (dict, list)):
                return cls._content_hash(payload)
        except (OSError, json.JSONDecodeError):
            return ""
        return ""

    async def _build_snapshot(self) -> ConfigSnapshot:
        """Build a new config snapshot from all sources."""

        # Load from DB (highest priority for dynamic updates)
        db_aliases = await self._load_db_aliases()
        db_abbreviations = await self._load_db_abbreviations()
        db_patterns = await self._load_db_patterns()
        db_months = await self._load_db_months()
        db_mutuelles = await self._load_db_mutuelles()

        # Merge: DB overrides file overrides fallback
        # (file and fallback are already loaded by the modules at import time)
        from app.pipeline.stt_correction import _MUTUELLE_ALIASES, _KNOWN_MUTUELLE_NAMES
        from app.pipeline.fuzzy_matching import KNOWN_MUTUELLES
        from app.pipeline.ssml_normalizer import ABBREVIATIONS

        # Merge aliases: DB wins over file/fallback
        merged_aliases = dict(_MUTUELLE_ALIASES)
        for canonical, aliases in db_aliases.items():
            if canonical in merged_aliases:
                for a in aliases:
                    if a not in merged_aliases[canonical]:
                        merged_aliases[canonical].append(a)
            else:
                merged_aliases[canonical] = aliases

        # Merge known mutuelles
        merged_mutuelles = list(KNOWN_MUTUELLES)
        for m in db_mutuelles:
            if m not in merged_mutuelles:
                merged_mutuelles.append(m)

        # Merge abbreviations: DB wins
        merged_abbreviations = dict(ABBREVIATIONS)
        merged_abbreviations.update(db_abbreviations)

        # Merge patterns: DB wins
        from app.pipeline.ssml_normalizer import _PATTERN_STRINGS
        merged_patterns = dict(_PATTERN_STRINGS)
        merged_patterns.update(db_patterns)

        # Validate regex patterns before accepting
        validated_patterns = {}
        for key, pattern in merged_patterns.items():
            if self._validate_regex(pattern):
                validated_patterns[key] = pattern
            else:
                logger.warning("Rejected invalid regex for %s: %s", key, pattern[:50])
                # Keep existing pattern if available
                if key in self._snapshot.ssml_patterns:
                    validated_patterns[key] = self._snapshot.ssml_patterns[key]

        # Merge months: DB wins
        from app.pipeline.ssml_normalizer import _MONTHS
        merged_months = dict(_MONTHS)
        merged_months.update(db_months)

        # Compute content hash for change detection (no churn on identical content)
        keyterms_path = os.getenv("OPTIBOT_KEYTERMS_PATH")
        if keyterms_path:
            keyterms_file = Path(keyterms_path)
        else:
            keyterms_file = Path(__file__).resolve().parents[2] / "data" / "deepgram_keyterms.json"

        all_content = {
            "aliases": merged_aliases,
            "mutuelles": merged_mutuelles,
            "abbreviations": merged_abbreviations,
            "patterns": validated_patterns,
            "months": merged_months,
            "keyterms_hash": self._file_content_hash(keyterms_file),
        }
        content_hash = self._content_hash(all_content)

        # Only bump version if content actually changed
        if content_hash == getattr(self._snapshot, '_content_hash', ''):
            return self._snapshot  # No change — return same snapshot

        version = self._snapshot.version + 1

        snapshot = ConfigSnapshot(
            version=version,
            loaded_at=time.time(),
            mutuelle_aliases=merged_aliases,
            known_mutuelles=merged_mutuelles,
            ssml_abbreviations=merged_abbreviations,
            ssml_patterns=validated_patterns,
            ssml_months=merged_months,
        )
        # Store hash for next comparison (using object.__setattr__ since frozen)
        object.__setattr__(snapshot, '_content_hash', content_hash)
        return snapshot

    def _push_to_pipeline(self, snapshot: ConfigSnapshot) -> None:
        """Push snapshot data into pipeline modules for runtime hot-swap."""
        try:
            from app.pipeline.stt_correction import set_runtime_aliases
            set_runtime_aliases(snapshot.mutuelle_aliases, snapshot.version)
        except Exception as e:
            logger.warning("Failed to push STT aliases: %s", e)

        try:
            from app.pipeline.ssml_normalizer import set_runtime_abbreviations
            set_runtime_abbreviations(snapshot.ssml_abbreviations, snapshot.version)
        except Exception as e:
            logger.warning("Failed to push SSML abbreviations: %s", e)

        try:
            from app.pipeline.fuzzy_matching import set_runtime_known_mutuelles
            set_runtime_known_mutuelles(snapshot.known_mutuelles, snapshot.version)
        except Exception as e:
            logger.warning("Failed to push known mutuelles: %s", e)

        try:
            from app.pipeline.ssml_normalizer import set_runtime_patterns, set_runtime_months
            if snapshot.ssml_patterns:
                set_runtime_patterns(snapshot.ssml_patterns, snapshot.version)
            if snapshot.ssml_months:
                set_runtime_months(snapshot.ssml_months, snapshot.version)
        except Exception as e:
            logger.warning("Failed to push SSML patterns/months: %s", e)

        try:
            from app.pipeline.keyterm_builder import reload_keyterm_db
            reload_keyterm_db()
        except Exception as e:
            logger.warning("Failed to reload keyterm DB: %s", e)

    def _validate_regex(self, pattern: str) -> bool:
        """Validate regex is safe and compilable. Reject overly complex patterns."""
        if len(pattern) > 500:
            return False
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
            # Quick test to ensure it doesn't catastrophic-backtrack
            compiled.search("test string for validation")
            return True
        except (re.error, RecursionError):
            return False

    async def _load_db_aliases(self) -> dict[str, list[str]]:
        if not self._supabase:
            return {}
        try:
            rows = await self._supabase.select("mutuelle_aliases", {"active": "true"}, limit=500)
            aliases: dict[str, list[str]] = {}
            for row in rows:
                # Schema: mutuelle (canonical name), alias (variant)
                canonical = row.get("mutuelle", "")
                alias = row.get("alias", "")
                if canonical and alias:
                    aliases.setdefault(canonical, []).append(alias)
            return aliases
        except Exception:
            return {}

    async def _load_db_abbreviations(self) -> dict[str, str]:
        if not self._supabase:
            return {}
        try:
            rows = await self._supabase.select("ssml_abbreviations", limit=500)
            return {row["key"]: row["expansion"] for row in rows if "key" in row and "expansion" in row}
        except Exception:
            return {}

    async def _load_db_patterns(self) -> dict[str, str]:
        if not self._supabase:
            return {}
        try:
            rows = await self._supabase.select("ssml_regex_patterns", limit=100)
            return {row["name"]: row["pattern"] for row in rows if "name" in row and "pattern" in row}
        except Exception:
            return {}

    async def _load_db_months(self) -> dict[str, str]:
        if not self._supabase:
            return {}
        try:
            rows = await self._supabase.select("ssml_month_names", {"active": "true"}, limit=50)
            # Schema: month_key, month_name
            return {row["month_key"]: row["month_name"] for row in rows if "month_key" in row and "month_name" in row}
        except Exception:
            return {}

    async def _load_db_mutuelles(self) -> list[str]:
        if not self._supabase:
            return []
        try:
            rows = await self._supabase.select("mutuelles", limit=500)
            return [row.get("nom_affiche", row.get("nom", "")) for row in rows if row.get("nom")]
        except Exception:
            return []
