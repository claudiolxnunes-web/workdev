import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


logger = logging.getLogger(__name__)


class GraphConfigurationError(RuntimeError):
    pass


class GraphRequestError(RuntimeError):
    pass


class EngineeringGraphSync:
    """Sincroniza entidades do PostgreSQL com o Engineering Graph no Supabase.

    Escritas exigem uma chave secreta no backend. A chave pública usada pelo
    frontend nunca é aceita aqui, preservando o RLS das tabelas do grafo.
    """

    def __init__(self, url: str | None = None, secret_key: str | None = None):
        self.url = (url or os.getenv("SUPABASE_URL")
                    or os.getenv("VITE_SUPABASE_URL") or "").rstrip("/")
        self.secret_key = (secret_key or os.getenv("SUPABASE_SECRET_KEY")
                           or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "")

    @property
    def configured(self) -> bool:
        return bool(self.url and self.secret_key)

    def configuration_status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "url_configured": bool(self.url),
            "secret_configured": bool(self.secret_key),
            "realtime_tables": ["graph_nodes", "graph_edges"],
        }

    def _headers(self) -> dict[str, str]:
        headers = {
            "apikey": self.secret_key,
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        # As chaves novas sb_secret_ não são JWT e devem ir somente em apikey.
        # O service_role legado é JWT e continua usando Authorization Bearer.
        if not self.secret_key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self.secret_key}"
        return headers

    def _request(
        self,
        method: str,
        table: str,
        *,
        params: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        if not self.configured:
            raise GraphConfigurationError(
                "Configure SUPABASE_SECRET_KEY no backend para sincronizar o grafo"
            )
        query = urllib.parse.urlencode(params or {})
        endpoint = f"{self.url}/rest/v1/{table}"
        if query:
            endpoint = f"{endpoint}?{query}"
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            endpoint,
            data=body,
            method=method,
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:500]
            raise GraphRequestError(
                f"Supabase respondeu HTTP {error.code}: {detail}"
            ) from error
        except urllib.error.URLError as error:
            raise GraphRequestError(f"Supabase indisponível: {error.reason}") from error

    def _find_node(
        self,
        *,
        entity_id: str,
        project_id: str,
        node_type: str | None = None,
    ) -> dict[str, Any] | None:
        params = {
            "select": "*",
            "entity_id": f"eq.{entity_id}",
            "project_id": f"eq.{project_id}",
            "limit": "1",
        }
        if node_type:
            params["type"] = f"eq.{node_type}"
        rows = self._request("GET", "graph_nodes", params=params)
        return rows[0] if rows else None

    def ensure_node(
        self,
        node_type: str,
        entity_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        existing = self._find_node(
            entity_id=str(entity_id),
            project_id=str(project_id),
            node_type=node_type,
        )
        if existing:
            return existing
        payload = {
            "type": node_type,
            "entity_id": str(entity_id),
            "project_id": str(project_id),
        }
        rows = self._request(
            "POST",
            "graph_nodes",
            payload=payload,
        )
        if not rows:
            raise GraphRequestError("Supabase não retornou o nó criado")
        return rows[0]

    def ensure_edge(
        self,
        source_node: str,
        target_node: str,
        relationship: str,
    ) -> dict[str, Any]:
        rows = self._request(
            "GET",
            "graph_edges",
            params={
                "select": "*",
                "source_node": f"eq.{source_node}",
                "target_node": f"eq.{target_node}",
                "relationship": f"eq.{relationship}",
                "limit": "1",
            },
        )
        if rows:
            return rows[0]
        created = self._request(
            "POST",
            "graph_edges",
            payload={
                "source_node": source_node,
                "target_node": target_node,
                "relationship": relationship,
            },
        )
        if not created:
            raise GraphRequestError("Supabase não retornou a relação criada")
        return created[0]

    def sync_project(self, project_id: str) -> dict[str, Any]:
        return self.ensure_node("Project", str(project_id), str(project_id))

    def sync_backlog(
        self,
        item_id: str,
        project_id: str,
        item_type: str = "feature",
    ) -> dict[str, Any]:
        project = self.sync_project(project_id)
        node_type = "Feature" if item_type == "feature" else "Task"
        item = self.ensure_node(node_type, item_id, project_id)
        relationship = "HAS_FEATURE" if node_type == "Feature" else "HAS_TASK"
        self.ensure_edge(project["id"], item["id"], relationship)
        return item

    def sync_subtask(
        self,
        subtask_id: str,
        backlog_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        parent = self._find_node(entity_id=backlog_id, project_id=project_id)
        if not parent:
            parent = self.sync_backlog(backlog_id, project_id, "chore")
        subtask = self.ensure_node("Subtask", subtask_id, project_id)
        self.ensure_edge(parent["id"], subtask["id"], "HAS_SUBTASK")
        return subtask

    def sync_related(
        self,
        node_type: str,
        entity_id: str,
        project_id: str,
        relationship: str,
        parent_entity_id: str | None = None,
    ) -> dict[str, Any]:
        parent = None
        if parent_entity_id:
            parent = self._find_node(
                entity_id=parent_entity_id,
                project_id=project_id,
            )
        if not parent:
            parent = self.sync_project(project_id)
        node = self.ensure_node(node_type, entity_id, project_id)
        self.ensure_edge(parent["id"], node["id"], relationship)
        return node

    def sync_commit(
        self,
        commit_id: str,
        project_id: str,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        return self.sync_related(
            "Commit", commit_id, project_id, "LINKED_TO_COMMIT", task_id
        )

    def sync_deployment(
        self,
        deployment_id: str,
        project_id: str,
        commit_id: str | None = None,
    ) -> dict[str, Any]:
        return self.sync_related(
            "Deployment", deployment_id, project_id,
            "LINKED_TO_DEPLOY", commit_id,
        )

    def sync_safely(self, operation: str, *args: Any, **kwargs: Any) -> bool:
        if not self.configured:
            logger.warning(
                "Engineering Graph não configurado; evento %s aguardará backfill",
                operation,
            )
            return False
        try:
            getattr(self, operation)(*args, **kwargs)
            return True
        except Exception:
            logger.exception("Falha ao sincronizar evento %s", operation)
            return False


graph_sync = EngineeringGraphSync()
